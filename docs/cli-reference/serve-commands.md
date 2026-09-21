# Serve Commands

Expose SuperQode to other tools: an ACP agent for editors and benchmarks, MCP and A2A servers for harnesses, and a browser-based TUI.

---

## Servers at a glance

| Surface | Command | Who connects |
|---------|---------|--------------|
| Jev Tool Routing service | `superqode serve jev` | Python SDK, HTTP, and MCP clients. One provider-neutral routing decision API; suitable for Cloud Run. |
| Jev Tool Routing gateway | `superqode serve optimize --upstream https://api.openai.com` | Compatible coding harnesses. Routes tool schemas once per turn before forwarding OpenAI or Anthropic requests. |
| ACP | `superqode serve acp` | Any ACP client: Zed, JetBrains IDEs, Neovim, Devin Desktop, and the Harbor benchmark framework. Runs SuperQode as the coding agent, driven by your HarnessSpec. |
| MCP | `superqode mcp` | Any MCP client (Claude Desktop, IDEs, other agents). Exposes your HarnessSpec workflows as `list_harnesses`, `describe_harness`, and `run_harness` tools. |
| Harness MCP alias | `superqode serve harness --spec harness.yaml` | Same MCP server, shaped around one harness file or directory. |
| Local Session API | `superqode serve api` | Browser/mobile companions and local tools that inspect or drive the switchboard and Software Factory graph. |
| Web TUI | `superqode serve web` | A browser, for the full TUI without a terminal emulator. |
| A2A | `superqode serve a2a --spec harness.yaml` | Other agents and orchestrators over A2A 1.0 HTTP+JSON. See [A2A Providers](../providers/a2a.md). |

A2A is the primary cross-service surface. The public [Agent Card](https://superqode.dev/.well-known/agent-card.json)
is published for discovery; operational requests go to `https://a2a.superqode.dev`.
Local `serve a2a` works today. See [A2A Protocol](../providers/a2a.md#public-agent-card-and-pilot-status).

## serve jev

Run the reusable Jev Tool Routing service locally:

```bash
export TYPESAFE_API_KEY="..."
superqode serve jev
```

It exposes `POST /v1/route-tools`, `GET /healthz`, and Streamable HTTP MCP at
`/mcp`. For stdio MCP use `superqode optimize mcp`. A stable `turn_id` reuses
one decision across all steps of a turn. The service preserves the caller's
tool objects, fails open on Jev errors, and stores only a bounded in-memory
turn cache.

Non-loopback binds require both `--allow-remote` and
`SUPERQODE_JEV_SERVICE_TOKEN`; clients send that token as an Authorization
bearer. A Cloud Run image, build configuration, and setup guide are included
as `Dockerfile.jev`, `cloudbuild.jev.yaml`, and `deploy/jev/README.md`.

Python harnesses can skip HTTP and use the same implementation in-process:

```python
from superqode.jev_tools import JevToolRouting

router = JevToolRouting(mode="enforce")
result = await router.route(task, tools, turn_id="turn-123")
model_tools = list(result.tools)
```

Use `JevToolRoutingClient` instead when calling the local or Cloud Run service.
The integration point is before a harness constructs its model request; an MCP
server by itself cannot rewrite another harness's hidden built-in catalogue.

---

## serve optimize

This feature is called **Jev Tool Routing**: Jev makes the fast closed-set tool
decision, while the coding model remains responsible for all generated text,
commands, paths, and patches.

Most developers should use the lifecycle-managed launcher:

```bash
export TYPESAFE_API_KEY="..."
superqode optimize setup
superqode optimize verify opencode
superqode optimize doctor
superqode optimize run opencode -- "review this repository"
superqode optimize run opencode --provider google --model gemini-3.8-flash -- run "review this repository"
```

`optimize setup [harness]` detects local harnesses, makes one small Jev
connectivity call, and prints ready-to-copy launch commands. It does not write
credentials or configuration. Use `--no-live` for detection only and `--json`
for automation. Pi accepts `--model` because its temporary provider must name a
model.

`optimize verify <harness>` validates the launch adapter, a controlled Jev tool
decision, schema-byte accounting, and same-turn cache reuse without invoking a
coding model. It reports whether the harness exposes a routable catalogue and
does not claim that synthetic control savings occurred in the harness. The
actual traffic check remains the aggregate report printed by `optimize run`.
Codex returns `gateway-limited`, Antigravity returns `detect-only`, and both use
a nonzero exit status so release automation cannot mistake them for verified
support.

`optimize run` chooses a free loopback port, starts the gateway, injects a
temporary harness-specific endpoint override, runs the original harness with
its normal interface, prints aggregate tool-routing savings, and removes all
temporary state. `optimize env <harness> --json` previews the exact command,
environment, and generated non-secret files. Supported profiles are Codex,
Claude Code, OpenCode, Grok Build, Pi, and native SuperQode. Antigravity appears
in `optimize doctor` as detect-only until its CLI exposes an endpoint hook.
`optimize bench [--threshold N]` provides a labeled, coding-model-free routing
check with aggregate recall, reduction, and latency metrics.

For Google, export `GEMINI_API_KEY` and pass `--provider google --model MODEL`.
OpenCode and Pi use native Gemini `generateContent` requests so thought
signatures remain intact. Their process-local generated configuration receives
only a non-secret local placeholder; the gateway injects the real key upstream.
Stock Pi has four core tools and may show no reduction until extensions add a
larger catalogue.

Codex 0.155 subscription traffic reaches the gateway, but its tool catalogue is
injected by the server rather than included in the client request. Doctor marks
this profile `gateway-limited`; no catalogue saving is claimed for that mode.

Use `serve optimize` below when you need to manage the gateway yourself.

Run the local OpenAI-compatible reverse proxy in safe observation mode:

```bash
export TYPESAFE_API_KEY="..."
superqode serve optimize \
  --upstream https://api.openai.com \
  --upstream-key-env OPENAI_API_KEY
```

Point a compatible harness at `http://127.0.0.1:8787/v1`. The proxy supports
`POST /v1/responses`, `POST /v1/chat/completions`, Anthropic
`POST /v1/messages`, native Gemini `generateContent`/`streamGenerateContent`,
streamed responses, and transparent forwarding of other
paths such as `/v1/models`.
Aggregate, non-sensitive process metrics are available at
`GET /superqode/status`; request bodies, prompts, tool arguments, and credentials
are not included.

For Anthropic and Claude Code, start the gateway with the real key held only by
the gateway process:

```bash
export TYPESAFE_API_KEY="..."
export ANTHROPIC_API_KEY="..."

superqode serve optimize \
  --upstream https://api.anthropic.com \
  --upstream-key-env ANTHROPIC_API_KEY
```

In a separate terminal, launch Claude Code through the local endpoint. The
placeholder is not sent upstream because the gateway replaces it with
`x-api-key`:

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
export ANTHROPIC_AUTH_TOKEN=local-superqode
unset ANTHROPIC_API_KEY
claude
```

Shadow mode asks Jev for a decision but forwards every tool. After inspecting
the `x-superqode-*` response headers, enable filtering:

```bash
superqode serve optimize \
  --upstream https://api.openai.com \
  --upstream-key-env OPENAI_API_KEY \
  --mode enforce
```

| Option | Description |
|--------|-------------|
| `--upstream` | Required provider base URL; may include `/v1` |
| `--mode` | `shadow` (default) or `enforce` |
| `--threshold` | Minimum Jev probability, default `0.30` |
| `--jev-timeout-ms` | Decision deadline, default 1500 ms |
| `--turn-ttl` | Seconds to retain one stable turn decision, default 1800 |
| `--upstream-key-env` | Environment variable holding the real provider key; otherwise the incoming Authorization header is forwarded |
| `--upstream-key-header` | `auto` (default), `authorization`, or `x-api-key`; auto recognizes `api.anthropic.com` |
| `--host` / `--port` | Listener, default `127.0.0.1:8787` |
| `--allow-remote` | Required for a non-loopback bind |

Clients can send `x-superqode-turn-id` for exact turn identity. Without it, the
gateway derives a stable identifier from the model, latest user message,
session/cache hints, and tool names. Routing errors fail open. Request bodies
and credentials are neither logged nor persisted by the gateway.

---

## mcp

Serve your harness specs over MCP, on stdio by default:

```bash
superqode mcp                                  # stdio (for MCP client configs)
superqode mcp --http --host 0.0.0.0 --port 8765
superqode mcp --dir ./harnesses                # serve specs from a directory
```

| Option | Description |
|--------|-------------|
| `--http` | Serve over streamable HTTP instead of stdio |
| `--host` | Bind address (default: `127.0.0.1`) |
| `--port` | Port number (default: `8765`) |
| `--dir` | Directory of harness specs to expose |

A typical MCP client configuration entry:

```json
{
  "mcpServers": {
    "superqode": {
      "command": "superqode",
      "args": ["mcp"]
    }
  }
}
```

---

## serve acp

Run SuperQode as an ACP agent on stdio, for Zed, JetBrains IDEs, Neovim, and Harbor/Terminal-Bench:

```bash
superqode serve acp                       # per-session harness discovery
superqode serve acp --spec harness.yaml   # pin one HarnessSpec
```

| Option | Description |
|--------|-------------|
| `--spec` | HarnessSpec file to use for all sessions |
| `--dir` | Directory of harness specs for discovery |
| `--provider` | Provider override (env: `SUPERQODE_ACP_PROVIDER`) |
| `--model` | Model override (env: `SUPERQODE_ACP_MODEL`) |

`SUPERQODE_ACP_SPEC` accepts a spec path or `template:<name>` for a built-in template. stdout carries JSON-RPC, so human-facing output goes to stderr. See the full guide: [ACP Agent Server](../advanced/acp-agent-server.md).

---

## serve harness

Expose harness workflows as MCP tools with a command that reads like harness-as-a-service:

```bash
superqode serve harness --spec harness.yaml
superqode serve harness --dir ./harnesses --http --port 8765
```

`--spec` serves the containing directory so relative `inherits` paths keep working; use the file stem as the harness name.

---

## serve api

Serve the local switchboard and Software Factory graph over JSON HTTP.

```bash
superqode serve api --port 8766
superqode serve api --host 0.0.0.0 --allow-remote --token "$SUPERQODE_API_TOKEN"
```

Options:

| Option | Description |
|--------|-------------|
| `--host` | Bind address (default: `127.0.0.1`) |
| `--port` | Port number (default: `8766`) |
| `--storage-dir` | Session storage directory (default: `.superqode/sessions`) |
| `--allow-remote` | Allow binding outside localhost |
| `--token` | Optional bearer token |

Useful endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Health check |
| `GET /sessions` | List graph sessions |
| `GET /sessions/graph` | Session switchboard tree |
| `GET /sessions/{id}/history` | Recent transcript messages |
| `POST /sessions/{id}/switch` | Mark a session active |
| `POST /sessions/{id}/handoff` | Create or deliver a handoff |
| `GET /factory/routes` | List Software Factory routes |
| `GET /sessions/{id}/factory` | Factory metadata for a session |
| `POST /sessions/{id}/factory/model` | Record a model/provider switch |
| `POST /sessions/{id}/factory/harness` | Record a harness switch |
| `POST /sessions/{id}/factory/mode` | Set a route such as `no-subscription` |

Remote serving should use `--token` and a trusted network.

---

## serve web

Start the Textual TUI server over HTTP.

```bash
superqode serve web [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--host` | Bind address (default: `127.0.0.1`) |
| `--port` | Port number (default: `8000`) |

### Examples

```bash
superqode serve web
superqode serve web --host 0.0.0.0 --port 8080
```

Uses `textual-serve` to expose the full SuperQode TUI over HTTP. Open the provided URL in a browser for a terminal-like experience without a local terminal emulator.

---

## serve a2a

Expose a HarnessSpec as an A2A 1.0 HTTP+JSON agent:

```bash
superqode serve a2a --spec harness.yaml
superqode serve a2a \
  --host 0.0.0.0 \
  --allow-remote \
  --public-url https://superqode.example.com
superqode serve a2a \
  --spec harness.yaml \
  --host 0.0.0.0 \
  --allow-remote \
  --public-url https://superqode.example.com \
  --token "$SUPERQODE_A2A_TOKEN" \
  --expose-harness
superqode serve a2a \
  --host 0.0.0.0 \
  --allow-remote \
  --public-url https://a2a.superqode.dev \
  --export-agent-card examples/a2a/agent-card.json
```

| Option | Description |
|--------|-------------|
| `--spec` | HarnessSpec file to serve |
| `--provider` / `--model` | Session defaults (env: `SUPERQODE_PROVIDER`, `SUPERQODE_MODEL`) |
| `--host` / `--port` | Bind address (default `127.0.0.1:8000`) |
| `--public-url` | Interface URL advertised in the Agent Card |
| `--harness-store` / `--store` | SQLite harness sessions, runs, evidence |
| `--task-store` | SQLite A2A task records (survives restart) |
| `--no-task-store` | Keep A2A task records in memory |
| `--token` | Operator token (env: `SUPERQODE_A2A_TOKEN`). Required with `--expose-harness` |
| `--allow-remote` | Allow binding outside localhost |
| `--expose-harness` | Serve the harness skill on a remote bind. Requires `--spec` and a token |
| `--export-agent-card` | Write the runtime Agent Card JSON and exit |

See [A2A Protocol](../providers/a2a.md) for durability, publishing, and the experimental multiplayer-computer packaging notes.

---

## serve status

Inspect server integrations supplied by the optional SuperQode Enterprise
package.

```bash
superqode serve status
```

The open-source package reports that this surface requires the Enterprise
package. The open-source `serve acp`, `serve a2a`, `serve harness`, `serve api`, and
`serve web` commands remain available as documented above.
