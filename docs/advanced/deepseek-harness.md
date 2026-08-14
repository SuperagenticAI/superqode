---
title: DeepSeek Harness
description: Run the DeepSeek Harness runtime as a SuperQode harness backend.
---

# DeepSeek Harness Integration

SuperQode runs [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
as an optional harness backend. DeepSeek keeps ownership of its agent loop,
tools, system prompts, compaction, and sandbox. SuperQode launches the runtime,
hosts its JSON-RPC stream, and normalizes progress into harness events so runs
appear in the existing evidence store.

DeepSeek publishes its TypeScript runtime as a compiled single-file executable
inside a Python platform wheel, so this route needs no Node.js, npm, or pnpm
workspace. The `deepseek-harness-sdk` distribution drives that executable over
newline-delimited JSON-RPC on stdio.

## Requirements

The runtime wheel is platform specific. DeepSeek publishes these targets:

| Platform | Wheel published |
| --- | --- |
| macOS arm64 (14+) | yes |
| Linux x86_64 (manylinux 2.28) | yes |
| Linux aarch64 (manylinux 2.28) | yes |
| macOS x86_64 | no |
| Windows | no |

The runtime binary is roughly 52 MB. On an unsupported platform the backend
reports as missing rather than failing at run time.

You also need a DeepSeek route. The runtime inherits `DEEPSEEK_API_KEY` and
`DEEPSEEK_BASE_URL` from the SuperQode process, so an existing shell
configuration keeps working, and either variable can point at a local proxy.

## Install

```bash
uv tool install "superqode[deepseek-harness]"
```

From a checkout, use `uv sync --extra deepseek-harness` instead.

The extra pulls `deepseek-harness-sdk`, which in turn pulls the matching
`deepseek-harness-runtime-bin` platform wheel carrying the compiled runtime, so
no separate download is required.

The dependency carries an environment marker for the three platforms DeepSeek
publishes wheels for. On any other platform the extra installs successfully but
contributes nothing, and the backend reports as missing rather than breaking the
install.

Restart SuperQode after installing, so the new package is importable.

## Select the preset

SuperQode ships a `deepseek-harness` preset, so no harness file and no Cordis
composition are required to start. In the TUI, open `:connect`, press `H` for Other Harnesses,
then select **DeepSeek Harness**. The entry stays visible when the SDK is
missing and shows the installation command.

```text
:harness switch deepseek-harness
:harness status
```

`dsh` and `deepseek` resolve to the same preset, so DeepSeek's own shorthand
still works, and `runtime.backend: dsh` keeps resolving in existing files.

The preset configures no Cordis file on purpose. The SDK injects DeepSeek's own
bundled composition whenever none is supplied, which keeps the plugin graph
upstream's to maintain. It sets `DSH_PERMISSION_MODE=workspace-write`, the
narrower of DeepSeek's two permission modes.

## Customize it

Generate an editable copy of the preset when the defaults need changing:

```bash
superqode harness init my-deepseek -t deepseek-harness
```

Or write the file directly. Save the following as `deepseek-harness.yaml`:

```yaml
version: 1
name: deepseek-harness
flavor: coding
runtime:
  backend: deepseek-harness
  config:
    deepseek_harness:
      max_tokens: 49152
model_policy:
  primary: deepseek-official/deepseek-v4-flash
execution_policy:
  sandbox: local
  approval_profile: none
  allow_read: true
  allow_write: true
  allow_shell: true
  allow_network: true
agents:
  - id: deepseek
    role: implementation
    tools: [read, write, edit, bash]
```

`allow_network: true` is required because the runtime calls the DeepSeek API.
Keep `sandbox: local`, because DeepSeek applies its own sandbox and SuperQode
does not wrap the runtime in an external one.

## Inspect it

```bash
superqode harness validate deepseek-harness.yaml
superqode harness doctor --spec deepseek-harness.yaml
superqode harness explain --spec deepseek-harness.yaml
```

`validate` confirms the backend selection:

```text
Valid harness: deepseek-harness (coding, runtime=deepseek-harness, workflow=single)
```

`doctor` reports installation state and backend compatibility:

```text
[ok] compatibility: Backend can run this spec.
[warning] approvals: Backend 'deepseek-harness' may not pause for approvals.
[ok] sandbox: Sandbox policy 'local' is recognized.
[ok] event_graph: Backend 'deepseek-harness' emits rich graph events.
```

The approvals warning is expected for this backend. Read
[Permission boundary](#permission-boundary) before granting write or shell
access.

When the SDK is absent, `doctor` reports the reason instead:

```text
[error] backend: Backend 'deepseek-harness' is missing.
  install: DeepSeek Harness SDK is not installed
```

## Run it

Start the TUI with the harness selected:

```bash
export DEEPSEEK_API_KEY=...
superqode --harness deepseek-harness.yaml
```

Or switch to it inside a running TUI, either by preset name or by file path:

```text
:harness switch deepseek-harness
:harness switch dsh
:harness switch ./deepseek-harness.yaml
:harness status
```

One-shot headless task:

```bash
superqode harness run --spec deepseek-harness.yaml \
  -p "Read README.md and summarize this project."
```

## Runtime configuration

Every key below is optional and lives under `runtime.config.deepseek_harness`:

| Key | Default | Purpose |
| --- | --- | --- |
| `provider` | `deepseek-official` | Provider route registered by the Cordis composition. Used when the request carries no route. |
| `model` | `deepseek-v4-flash` | Model id resolved by that provider adapter. |
| `max_tokens` | provider default | Per-request output token cap for the root agent and its in-process descendants. |
| `cordis` | bundled default | Path to a Cordis composition file, resolved against the working directory. |
| `session_root` | `.superqode/deepseek-harness/sessions` | Directory for the runtime's JSONL sessions. |
| `runtime_bin` | bundled executable | Explicit runtime executable, which bypasses the bundled default configuration. |
| `env` | inherited | Extra environment variables for the subprocess. |
| `base_url` | `DEEPSEEK_BASE_URL` | Overrides the API endpoint for this harness. |
| `api_key` | `DEEPSEEK_API_KEY` | Overrides the credential for this harness. |
| `request_timeout` | none | Seconds to wait for a single JSON-RPC response. |
| `prompt_timeout` | `600` | Seconds a prompt may run before the backend reports a timeout error. |
| `shutdown_timeout` | `1` | Seconds to wait for the subprocess to exit. |
| `use_superqode_route` | `false` | Forward the connected SuperQode provider and model to the runtime. |

## Model routes, local models, and BYOK

DeepSeek resolves provider route *names* from its own Cordis composition rather
than from SuperQode's model catalog. The bundled composition registers exactly
one name, `deepseek-official`, so forwarding a name like `ollama` fails the
handshake. The endpoint behind that route is configurable, which is what makes
local models work.

When you connect to a local or dynamic provider and switch to a `deepseek-harness`
harness, SuperQode bridges the route automatically: the route name stays
`deepseek-official` while `base_url` and `model` are repointed at your provider.
Connecting to `ollama/qwen3.5:9b` therefore runs on Ollama:

```text
route     : deepseek-official / qwen3.5:9b
endpoint  : http://localhost:11434/v1
bridged   : ollama/qwen3.5:9b
```

Bridging applies only to providers that speak the OpenAI wire format, which
covers local providers and dynamic models.dev entries. Providers with their own
wire format, such as Anthropic and Google, are left alone rather than pointed at
an adapter that cannot talk to them.

Bridging is skipped whenever the harness configures its own `base_url` or
`model`, so an explicit endpoint always wins:

| Goal | Approach |
| --- | --- |
| A local model | Connect to it normally; the route is bridged for you. |
| DeepSeek API | Set `DEEPSEEK_API_KEY`, and connect to a DeepSeek route or configure none. |
| A fixed endpoint | Set `base_url` and `model` in the harness file. |
| Another provider catalog | Mount `llm-pi-ai` in a Cordis composition, then set `use_superqode_route: true` so the connected route name is forwarded to it. |

### Selecting a composition

DeepSeek's plugin composition is owned by its own `cordis.yml`, not by the
HarnessSpec. Point `cordis` at a file to replace the bundled default:

```yaml
runtime:
  backend: deepseek-harness
  config:
    deepseek_harness:
      cordis: config/deepseek/cordis.yml
```

Keep the `@deepseek-ai/dsh-sdk-jsonrpc-server` entry in any custom composition,
because that plugin provides the stdio transport this backend speaks.

### Choosing a permission mode

The runtime reads `DSH_PERMISSION_MODE` for its own sandbox policy:

```yaml
runtime:
  backend: deepseek-harness
  config:
    deepseek_harness:
      env:
        DSH_PERMISSION_MODE: workspace-write
```

`workspace-write` confines mutations to the session working directory.
`danger-full-access` removes that restriction.

## Permission boundary

DeepSeek executes its own tools inside its own process. SuperQode approval
profiles, permission rules, and sandbox backends therefore do not gate a
DeepSeek tool call before it runs. The backend advertises this by reporting
`supports_approvals: false`, which produces the `doctor` warning shown above.

This has a direct consequence for `harness explain`. The Tools and Permissions
sections describe the spec, and the builtin backend enforces them, but the
`deepseek-harness` backend delegates execution. Treat `allow_write` and `allow_shell` in a
`deepseek-harness` harness as a statement of intent for reviewers, and use `DSH_PERMISSION_MODE`
for the control that the runtime actually applies.

Prefer `workspace-write` and a dedicated working directory until a tool
governance bridge can enforce SuperQode permission decisions before DeepSeek
executes a mutation.

## Event mapping

| DeepSeek notification or event | SuperQode harness event |
| --- | --- |
| `session.status` running | `start` |
| `session.status` idle | `end` |
| `turn/start` | `turn_start` |
| `turn/end` | `turn_complete`, carrying `reason` |
| `assistant/chunk` text delta | `model_delta` |
| `assistant/chunk` reasoning delta | `thinking_delta` |
| `assistant/chunk` tool call delta | `tool_delta` |
| `assistant/chunk` usage | `usage` |
| `assistant/message` | `message`, carrying committed text and usage |
| `tool/call` | `tool_call` |
| `tool/result` | `tool_result`, carrying `is_error` |
| `request/header`, `request/context` | `model_request` |
| `subagent.started`, `subagent.finished` | `subagent`, carrying ancestry |
| any other notification | `dsh_event` |

Every translated event keeps the complete original payload under
`data.dsh_notification`, so a future DeepSeek release stays readable before the
mapping is extended.

A run covers one prompt-to-idle interval. The backend starts attributing events
once it sees the durable inbox receipt for its own prompt, which keeps earlier
queued traffic out of the result. Token totals are summed from committed
`assistant/message` records only, because the streamed usage chunk repeats the
same per-step figures.

## Sessions and process reuse

The runtime writes JSONL sessions under `session_root`, which defaults to
`.superqode/deepseek-harness/sessions` inside the working directory. Those files belong to
DeepSeek's session format and are readable with its own tooling.

DeepSeek treats a session id as owning its persisted log. A second prompt sent
from a fresh process under an existing session id is rejected as an id
collision, so SuperQode keeps one runtime subprocess alive per session and sends
later turns to it. The process is closed when the session is cancelled, when a
turn fails at the transport level, and at interpreter exit.

Each live session therefore holds a runtime subprocess. Cancel a session to
release it.

## Current limits

| Area | State |
| --- | --- |
| Approvals | DeepSeek owns tool execution; SuperQode cannot gate a call first. |
| No-tool flavor | Unsupported; the backend reports `supports_no_tool: false`. |
| Workflow children | Multi-agent SuperQode workflows are unsupported; DeepSeek runs its own subagents. |
| MCP | Configure MCP inside the Cordis composition rather than through the HarnessSpec. |
| Structured output | Output schemas are not honored by this backend. |
| Cost reporting | The runtime reports tokens but no cost, so `cost_usd` stays empty. |
| Windows | No runtime wheel is published. |
| Anthropic and Google routes | Not bridged; they do not speak the OpenAI wire format the adapter uses. |
| Wizard | `:harness wizard` does not offer this preset; use `harness init -t deepseek-harness`. |
| Subscription login | No entry; the runtime authenticates with `DEEPSEEK_API_KEY`. |

## Version pinning

DeepSeek Harness is a developer preview and expects compatibility-breaking
changes. The Python SDK and its runtime wheel are released as an exact matched
pair, such as `deepseek-harness-sdk==0.1.0rc6` with
`deepseek-harness-runtime-bin==0.1.0rc6`. Pin the SDK deliberately and upgrade
both together.

## Related routes

DeepSeek also ships an [Agent Client Protocol](https://agentclientprotocol.com)
server, which SuperQode could host through its existing
[ACP agent catalog](../providers/acp.md). That path is not available yet,
because one package in the published plugin graph is missing from the npm
registry, so a standalone install cannot resolve. The ACP route is worth
revisiting when it installs cleanly, because ACP carries
`session/request_permission` and would let SuperQode's permission screen take
part in approvals.

## Next adoption gates

1. Offer the preset from `:harness wizard` alongside the model-family starters.
2. Track the upstream developer preview and move the
   `deepseek-harness-sdk>=0.1.0rc6,<0.2.0` pin deliberately.
3. Revisit the ACP route once the upstream package graph installs, since ACP
   carries `session/request_permission` and would let SuperQode approvals
   participate.
