---
title: Unified Harness Protocol
description: Connect SuperQode to a UHP server and run its harnesses through the Harness Protocol.
---

# Unified Harness Protocol

The Unified Harness Protocol (UHP) is an HTTP contract for handing a task to a
complete agent harness and getting finished work back. A UHP server advertises
the harnesses it runs, accepts a task, streams progress, and returns text and
files.

SuperQode speaks UHP as a client. Once connected, a harness on a UHP server is
registered as the `uhp` route and runs through the same session, event, and
evidence model as a local harness.

SuperQode targets UHP version `2026-08-11` and sends that version on every
request.

---

## Where UHP sits

UHP is a transport, in the same position as ACP. It is not a replacement for
the SuperQode Harness Protocol, which stays the internal control plane.

| Layer | What it does |
| --- | --- |
| Harness Protocol v1 | SuperQode's session, event, and evidence contract |
| UHP adapter | Translates one UHP server into that contract |
| UHP | The HTTP wire format between SuperQode and the server |
| Harness | Codex, Claude Code, or whatever else the server runs |

The difference from every other connection method is that a UHP server is a
**remote catalog**. An ACP agent is a local process SuperQode starts, and a
BYOK provider is an entry in a static list. With UHP the address comes first,
the harness list arrives over the network, and only then is there something to
select.

---

## Connect

```bash
superqode connect uhp --base-url https://your-server
```

SuperQode reads the server's discovery document, lists the harnesses it
advertises, and selects one when the server offers only one.

```text
Connected:  https://your-server
Protocol:   UHP 2026-08-11 (full)
Auth:       bearer key

Harnesses (2):
 * chrn_codex               Codex                Codex CLI · gpt-5
   chrn_claude              Claude Code          Claude Code · server default
```

Pick a specific harness when the server runs several:

```bash
superqode connect uhp --harness chrn_claude
```

An unknown harness id is an error, not a silent success: the command exits
non-zero and saves nothing.

From the TUI, `:connect uhp` runs the same discovery.

| Option | Description |
| --- | --- |
| `--base-url` | Server root, with or without a trailing `/v1` |
| `--api-key` | Bearer credential for the server |
| `--harness` | Harness id to select |
| `--save` / `--no-save` | Remember the connection (default: save) |
| `--json` | Emit the catalog, capabilities, and selection as JSON |

### Run a task

A saved connection with a selected harness makes `uhp` a selectable harness
everywhere SuperQode lists them:

```bash
superqode harness run uhp --prompt "review this repository" --stream
superqode harness protocol list          # uhp appears once configured
sq hub show uhp
```

In the TUI it is a normal switcher entry:

```text
:harness switch uhp
```

Without a selected harness the route reports itself as unavailable and says
what to run, rather than appearing ready and failing later.

`:connect uhp` discovers and saves the server. `:harness switch uhp` puts
that harness on the current session so the next prompt runs there:

```text
:connect uhp http://127.0.0.1:3000/api/harness
:harness switch uhp
```

Conversation threading works on both routes. The protocol controller persists
the response id with the session, and the harness backend writes it to
`.superqode/uhp/sessions/<session>.json`, so a later process continues the
same conversation instead of starting a new one.

---

## HarnessRouter Community Edition

Community Edition is the reference implementation most people will run, and
two details differ from the bare spec root:

- The protocol is served under a prefix, so the base URL is
  `http://127.0.0.1:3000/api/harness`, not `http://127.0.0.1:3000`.
- A default Docker install gates the API with the console login cookie rather
  than a bearer token. Starting the container with `HR_AUTH_DISABLED=1` removes
  the gate for local testing.

```bash
superqode connect uhp --base-url http://127.0.0.1:3000/api/harness
```

Cookie authentication is not stored in the saved connection. Pass a cookie
header through `UHPClient(headers=...)` when driving CE from Python, or run it
with the auth gate disabled.

---

## Credentials

| Variable | Purpose |
| --- | --- |
| `SUPERQODE_UHP_BASE_URL` | Server root |
| `SUPERQODE_UHP_API_KEY` | Bearer credential |
| `SUPERQODE_UHP_HARNESS` | Harness id to select |

Settings resolve from command arguments first, then the environment, then the
saved connection at `~/.superqode/uhp.json`. That file is created with
owner-only permissions.

A key supplied through `SUPERQODE_UHP_API_KEY` is deliberately **not** copied
into the saved connection, so a credential exported per shell stays in that
shell. A key passed with `--api-key` is saved, because there is nowhere else
for it to live. Stripping an environment key never discards a different key
that was saved earlier.

---

## Use it in Python

The client is usable on its own, without the rest of SuperQode:

```python
from superqode.harness import UHPClient

async with UHPClient("https://your-server", api_key=key) as client:
    discovery = await client.discover()
    print(discovery.default_version, discovery.conformance_class)
    print(discovery.supports("cancellation"))

    for harness in await client.list_harnesses():
        print(harness.id, harness.base, harness.default_model)

    response = await client.create_response(
        "Summarize this repository",
        harness_id="chrn_codex",
    )
    print(response.output_text)
    for citation in response.file_citations:
        print(citation.filename, citation.download_url)
```

Stream instead of waiting:

```python
async for event in client.stream_response("Fix the failing test", harness_id="chrn_codex"):
    if event.type == "response.output_text.delta":
        print(event.data["delta"], end="")
```

Continue the same conversation by passing the previous response id:

```python
first = await client.create_response("Read the config", harness_id="chrn_codex")
second = await client.create_response(
    "Now change the timeout",
    harness_id="chrn_codex",
    previous_response_id=first.id,
)
```

### Retry safety

Every task submission carries an `Idempotency-Key`. Retrying a task without one
starts a second agent in the same workspace, so the client generates a key per
call and accepts an explicit `idempotency_key=` when you need a retry to reuse
the original.

---

## Use it as a harness

`UHPHarnessProtocolAdapter` puts a UHP server behind the standard lifecycle:

```python
from pathlib import Path

from superqode.harness import (
    FileHarnessStore,
    HarnessCreateRequest,
    HarnessProtocolController,
    UHPHarnessProtocolAdapter,
)

adapter = UHPHarnessProtocolAdapter(
    "https://your-server",
    harness_id="chrn_codex",
    api_key=key,
)
controller = HarnessProtocolController(
    [adapter],
    store=FileHarnessStore(".superqode/harness-protocol"),
)

session = await controller.create(
    HarnessCreateRequest(harness_id="uhp", model="gpt-5", working_directory=Path.cwd())
)
async for event in controller.send(session, "Review the current diff"):
    print(event.type, event.data)
```

### Event mapping

| UHP stream event | Canonical event |
| --- | --- |
| `response.output_text.delta` | `message.delta` |
| `response.reasoning_summary_text.delta` | `model.thinking` |
| `response.output_item.added` (function call) | `tool.requested` |
| `response.function_call_arguments.done` | `tool.requested` |
| `response.output_item.done` (call output) | `tool.completed` |
| `error` | `validation.completed` with status `error` |
| `container_file_citation` annotation | `artifact.created` |
| `response.completed` | `model.completed`, then `message.created` |

`run.started`, `run.completed`, and `run.failed` come from the controller, as
they do for every adapter.

---

## Capabilities

| Capability | Supported | Reason |
| --- | --- | --- |
| Streaming | Yes | Server-Sent Events |
| Resume | Yes | `previous_response_id`, persisted with the session |
| Cancel | Yes | Response cancel, falling back to session cancel |
| Tools | Yes | Function calls appear in the output |
| Usage | Yes | Reported when the server sends it |
| Steer | No | UHP has no mid-turn steering operation |
| Checkpoint | No | UHP has no checkpoint operation |
| Native export | No | Server-private state is not exportable |

Unsupported operations raise `HarnessCapabilityError` rather than silently
doing nothing.

`usage` is optional in the spec. A server that reports none produces a
`model.completed` event with no `usage` key, rather than a fabricated zero.

### Resume across a restart

UHP threads a conversation with `previous_response_id` instead of a long-lived
connection. The adapter hands the response id and the server's session id back
to the controller after each turn, which persists them with the session. A new
process therefore continues the same conversation rather than starting a fresh
one. When only the server session id survives, the adapter recovers the latest
response id from the server's session turns.

### Dropped streams

A dropped connection does not stop the task; the work continues on the server.
When a stream ends without a terminal event, the adapter re-reads the response
with `GET /v1/responses/{id}`, which is the source of truth after a disconnect.
If the task is still running and SuperQode is giving up, the adapter cancels it
explicitly rather than leaving a harness editing files unattended.

---

## Errors

Failures raise a typed exception carrying the server's own error code:

| Exception | UHP `error.type` |
| --- | --- |
| `UHPInvalidRequestError` | `invalid_request_error` |
| `UHPAuthenticationError` | `authentication_error` |
| `UHPPermissionError` | `permission_error` |
| `UHPRateLimitError` | `rate_limit_error` |
| `UHPHarnessError` | `harness_error` |
| `UHPServerError` | `server_error` |

Two details are worth knowing when reading stream failures.

An `error` stream event **does not end the task**. The spec requires it to be
followed by a terminal event, so the client yields it and lets the terminal
response decide the outcome. The error is raised only when a stream ends
without ever reaching a terminal event, which is a malformed stream.

The `error` event also reuses `type` for the event name, so it carries `code`,
`message`, and `param` but no error class. SuperQode preserves the code and
message on the base `UHPError` in that case, and resolves the specific class
only when the payload nests a full error object.

---

## Limits

- The client targets one protocol version. `connect uhp` warns when a server
  does not list `2026-08-11` among its versions.
- File artifacts are reported as citations with a download URL. SuperQode does
  not copy them into the workspace automatically; use
  `UHPClient.download_file` for that.
- **Harness configuration lives on the server.** A HarnessSpec does not drive a
  remote UHP harness, so tool policy, sandbox, and approvals are whatever the
  server was configured with. The adapter reports `policy_owner: server` in its
  descriptor metadata so this is visible rather than assumed.
- `superqode connect uhp` verifies the catalog. It does not verify that the
  credential is sufficient to run a task, because listing and running can be
  authorized separately.
- Cookie-gated servers are supported only by passing the cookie header
  explicitly from Python.

---

## See also

- [Harness Protocol](../advanced/harness-protocol.md) for the lifecycle a UHP
  session is normalized into
- [ACP](acp.md) for the other transport that connects an externally owned
  agent loop
- [Connection Methods](../concepts/modes.md) for how transports relate to the
  `:connect` question
