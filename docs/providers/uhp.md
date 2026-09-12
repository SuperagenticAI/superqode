---
title: Unified Harness Protocol
description: Connect SuperQode to a UHP server and run its harnesses through the Harness Protocol.
---

# Unified Harness Protocol

The Unified Harness Protocol (UHP) is an HTTP contract for handing a task to a
complete agent harness and getting finished work back. A UHP server advertises
the harnesses it runs, accepts a task, streams progress, and returns text and
files.

SuperQode speaks UHP as a **client** and, separately, as a **native server**.

As a client, a harness on a remote UHP server is registered as the `uhp` route
and runs through the same session, event, and evidence model as a local harness.

As a server (`superqode serve uhp`), SuperQode exposes **one configured
HarnessSpec** over the UHP wire format: a native harness bind, not a
multi-backend runner. That is complementary to [HarnessRouter](https://github.com/HarnessRouter/harnessrouter):
HarnessRouter wraps Codex, Claude Code, and similar tools as a catalog;
`serve uhp` makes SuperQode's own harness speak UHP so any UHP client can drive
it. They are partners, not substitutes.

SuperQode targets UHP version `2026-08-11` and sends that version on every
client request. The native server answers that same version.

---

## Where UHP sits

UHP is a transport, in the same position as ACP. It is not a replacement for
the SuperQode Harness Protocol, which stays the internal control plane.

| Layer | What it does |
| --- | --- |
| Harness Protocol v1 | SuperQode's session, event, and evidence contract |
| UHP adapter | Translates one remote UHP server into that contract (client path) |
| `serve uhp` | Native UHP server: one SuperQode HarnessSpec on the wire |
| UHP | The HTTP wire format |
| Harness | On `serve uhp`: the bound SuperQode harness. On HarnessRouter: Codex, Claude Code, … |

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

From the TUI, `:connect uhp` opens a screen that takes the server address,
lists what it advertises, and switches to the harness you pick. It prefills
HarnessRouter Community Edition's Docker address, so a local container needs
no typing. The same screen is on `:connect protocols` as `:connect protocol-uhp`.

| Option | Description |
| --- | --- |
| `--base-url` | Server root, with or without a trailing `/v1` |
| `--api-key` | Bearer credential for the server |
| `--harness` | Harness id to select |
| `--max-output-tokens` | Cap the token budget for one task |
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

### The server picks the model

A harness on a UHP server already has a model. SuperQode does not send one, so
that choice stands. Pass `--model` when you want a different model for a run,
and only that explicit flag overrides the server:

```bash
superqode harness run uhp --prompt "..." --model "openai/gpt-5"
```

The model id has to be one the server can route. A server that cannot serve it
rejects the task rather than falling back, so the id must match what the
server's integrations provide. `SUPERQODE_MODEL` deliberately does not override
a remote harness: it is a local default for SuperQode's own harnesses and knows
nothing about what the server can serve.

### Capping the token budget

Some providers check affordability against the budget a task *reserves*, not
what it uses. A harness that asks for a large budget is then refused outright,
even for a one-word prompt, and the error names a number nobody chose:

```text
You requested up to 65536 tokens, but can only afford 1195.
```

Cap it, and the server asks for less:

```bash
superqode connect uhp --max-output-tokens 1000
```

The cap is saved with the connection and sent on every task.
`SUPERQODE_UHP_MAX_OUTPUT_TOKENS` sets it per shell. Without one, SuperQode
sends no budget and the server's own default applies.

The connect screen has the same field beside the address, so a task refused for
its budget can be fixed without leaving the terminal interface. Clearing the
field removes the cap.

### The workspace is the server's

The harness runs in its own workspace inside the server, not in your
repository. A bare prompt like "review this repository" describes whatever the
server already holds.

To send local files into that workspace, use UHP file upload (Extended Files):

```bash
superqode harness run uhp \
  --file src/example.py \
  --prompt "Review the attached module" \
  --download-dir .superqode/uhp/artifacts
```

`--file` may be repeated. Uploads go through `POST /v1/files` and are attached
as `input_file` parts on the task. `--download-dir` writes any
`container_file_citation` artifacts from the response onto disk.

From Python:

```python
async with UHPClient("https://your-server", api_key=key) as client:
    response = await client.create_response(
        "Summarise the attached notes",
        harness_id="chrn_codex",
        input_files=["notes.md"],
    )
    await client.download_citations(response.file_citations, ".superqode/uhp/artifacts")
```

Small files can also be inlined as data URLs with `inline_files=` (size-capped).
Prefer `input_files=` for anything larger than a few hundred kilobytes.

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

    # Upload local files, then pull artifacts back
    with_files = await client.create_response(
        "Review the attached module",
        harness_id="chrn_codex",
        input_files=["src/example.py"],
    )
    await client.download_citations(
        with_files.file_citations, ".superqode/uhp/artifacts"
    )
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
- File artifacts are reported as citations with a download URL. Use
  `UHPClient.save_file` / `download_citations`, or pass `--download-dir` on
  `harness run uhp`, to copy them into a local directory.
- **Harness configuration lives on the server.** A HarnessSpec does not drive a
  remote UHP harness, so tool policy, sandbox, approvals, the model, and the
  workspace are whatever the server was configured with. The adapter reports
  `policy_owner: server` in its descriptor metadata so this is visible rather
  than assumed.
- **Local files reach the harness through UHP upload.** Pass `--file` /
  `input_files=` (multipart `POST /v1/files`) or `inline_files=` (data URL).
  Without those, the harness still sees only the server's workspace.
- `superqode connect uhp` verifies the catalog. It does not verify that the
  credential is sufficient to run a task, because listing and running can be
  authorized separately.
- Cookie-gated servers are supported only by passing the cookie header
  explicitly from Python.

---

## Serve (native UHP harness)

Expose a local HarnessSpec as a UHP server so other products can drive SuperQode
through the same contract SuperQode uses as a client:

```bash
superqode serve uhp --spec harness.yaml
superqode serve uhp --spec harness.yaml --host 127.0.0.1 --port 8787
superqode serve uhp --api-key "$SUPERQODE_UHP_API_KEY"
```

| Option | Description |
| --- | --- |
| `--spec` | HarnessSpec file to bind (default: built-in coding template) |
| `--host` / `--port` | Bind address (default `127.0.0.1:8787`) |
| `--provider` / `--model` | Defaults for runs when the request omits a model |
| `--api-key` | Optional bearer token (`SUPERQODE_UHP_API_KEY`). When set, every route except `GET /v1/uhp` requires it |
| `--allow-remote` | Required to bind outside localhost |
| `--harness-id` | Override the advertised id (must match `^chrn_`) |
| `--working-dir` | Working directory for harness runs |

### What it serves

Core surface under `/v1/…` (protocol `2026-08-11`):

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/v1/uhp` | Discovery (unauthenticated). Claims conformance class **`core`** |
| `GET` | `/v1/harnesses` | Lists the single bound SuperQode harness |
| `GET` | `/v1/harnesses/{id}` | Harness detail |
| `GET` | `/v1/models` | Model catalogue for the bind |
| `GET` | `/v1/harnesses/{id}/models` | Per-harness models |
| `POST` | `/v1/responses` | Run a task (`stream: false` JSON or `stream: true` SSE) |
| `GET` | `/v1/responses/{id}` | Read a stored response |
| `GET` | `/v1/responses/{id}/input_items` | Input echo |
| `POST` | `/v1/responses/{id}/cancel` | Cancel (idempotent) |
| `DELETE` | `/v1/responses/{id}` | Delete stored response (does not cancel) |
| `POST` | `/v1/sessions/{id}/cancel` | Cancel in-flight work in a session |

Also: `UHP-Version` negotiation (`unsupported_protocol_version` on mismatch),
optional bearer auth, `Idempotency-Key`, `previous_response_id` session
threading, and reserved `tools` / `include` accepted with
`metadata.ignored_fields`.

### Conformance honesty

The server advertises `conformance_class: core` because that is the surface it
implements. It has **not** been certified by the UHP conformance suite; passing
endpoints locally is not a conformance claim. Extended (files, session listing)
and Full (harness management, sharing) are deferred.

### Partnership with HarnessRouter

- **HarnessRouter**: multi-backend UHP *runner*: advertise and run Codex,
  Claude Code, Hermes, etc. behind one catalog.
- **`superqode serve uhp`**: native UHP *harness*: one SuperQode HarnessSpec
  speaking the protocol so any UHP client (including SuperQode's own client,
  or HarnessRouter as a client elsewhere) can call it.

Use both when you want SuperQode's policy/evidence loop reachable over UHP
*and* third-party CLIs reachable through a runner. Neither replaces the other.

### Public host (`uhp.superqode.dev`)

The public UHP hostname is a **native SuperQode bind**, the same job as local
`serve uhp`. It is not a multi-backend catalog. Hub discovery (path C) can
later list the same SuperQode ids this host advertises; it does not turn this
host into a runner for Codex, Claude Code, or Hermes.

| Surface | Role |
| --- | --- |
| `https://uhp.superqode.dev/v1/uhp` | Discovery. Anonymous. No model call. Class `core`. |
| `GET /v1/harnesses`, `GET /v1/models` | Static catalog of the one bound SuperQode harness. Anonymous. No model call. |
| `POST /v1/responses` and session/response writes | Harness turn. Requires a SuperQode UHP bearer **and** the caller's provider key. SuperQode does not attach a model key on this host. |
| `https://superqode.dev` | Product site. Not a UHP endpoint. |
| Local `superqode serve uhp` | The working bind until the hostname is mapped and serving. |

Treat the public host as a catalog pilot plus optional BYOK runs. Tokens and
provider keys never belong in the discovery document. Cold starts are expected
on a scale-to-zero Cloud Run service.

Anonymous:

```bash
curl -sS https://uhp.superqode.dev/v1/uhp
superqode connect uhp --base-url https://uhp.superqode.dev --no-save
```

A harness turn (caller's DeepSeek key, not SuperQode's):

```bash
export SUPERQODE_UHP_API_KEY=...
export DEEPSEEK_API_KEY=...
superqode connect uhp --base-url https://uhp.superqode.dev --api-key "$SUPERQODE_UHP_API_KEY"
```

Reserve `uhp.superqode.dev` on the `superqode.dev` zone (GoDaddy). Point it at
the dedicated Cloud Run service `superqode-uhp` with Cloud Run domain mapping,
not at `a2a.superqode.dev` and not through a global HTTPS load balancer.

Create a **new** Cloud Run service. Do not open or retarget `superqode-a2a`.
Connect this GitHub repository, Dockerfile path `Dockerfile.uhp`, Cloud Build
file `cloudbuild.uhp.yaml`, service name `superqode-uhp`, region `us-central1`.
Set secret `SUPERQODE_UHP_API_KEY`. Do not set `DEEPSEEK_API_KEY` on the
service. Callers send that key as `X-Provider-Api-Key`. See
`deploy/uhp/README.md`.

Until that mapping answers, smoke-test on loopback:

```bash
superqode serve uhp --spec harness.yaml --port 8787
# elsewhere:
superqode connect uhp --base-url http://127.0.0.1:8787
superqode harness run uhp --prompt "summarise this repository"
```


---

## See also

- [Harness Protocol](../advanced/harness-protocol.md) for the lifecycle a UHP
  session is normalized into
- [ACP](acp.md) for the other transport that connects an externally owned
  agent loop
- [Connection Methods](../concepts/modes.md) for how transports relate to the
  `:connect` question
- [HarnessRouter / UHP](https://github.com/HarnessRouter/harnessrouter) for the
  multi-backend runner and the protocol specification
