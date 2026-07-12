# Agent Runtimes

SuperQode is your portable coding agent harness. You can keep the default native loop, or opt into a different backend with one flag. Runtime adapters are peers behind the same harness contract.

## Runtime Versus Harness

A harness describes what should happen. A runtime performs it.

| Term | Role |
| --- | --- |
| Harness | User-facing contract for flavor, tools, model policy, sandbox, workflow, output, and events |
| Runtime | Execution engine that runs the harness |
| Runtime adapter | Code that maps a SuperQode harness into a specific SDK or agent framework |
| Framework adapter | A runtime adapter backed by an external agent framework |

This distinction matters because users should be able to keep the same harness behavior while changing the
execution engine. When an engine cannot honor a policy, SuperQode reports that clearly.

The install commands below show the normal `uv tool install superqode` case. In
the TUI and runtime doctor, SuperQode adjusts the hint to the environment that
is actually running: source checkouts use
`uv pip install -e ".[<extra>]"`, project virtualenvs use
`uv add "superqode[<extra>]"`, and plain virtualenvs use
`uv pip install "superqode[<extra>]"`. Any one-click install prompt prints the
exact command first and waits for confirmation. See the
[official uv documentation](https://docs.astral.sh/uv/) for uv installation and
environment details.

| Runtime | Install | Notes |
| --- | --- | --- |
| `builtin` | included | SuperQode's native loop. This is the default and the canonical path for local-model and no-tool policy. |
| `adk` | `uv tool install "superqode[adk]"` | Google Agent Development Kit. Uses ADK's `Runner` and `LlmAgent`. |
| `openai-agents` | `uv tool install "superqode[openai-agents]"` | OpenAI Agents SDK v0.17+. Includes SDK sessions, tool bridging, and HITL support. |
| `codex-sdk` | `uv tool install "superqode[codex-sdk]"` | Official OpenAI Codex Python SDK runtime. Drives the published `openai-codex` package and its local app-server. |
| `claude-agent-sdk` | `uv tool install "superqode[claude-agent-sdk]"` | Anthropic Claude Agent SDK runtime (API key via `ANTHROPIC_API_KEY`). Drives `claude-agent-sdk` + the local Claude Code CLI; `:claude` exposes model/permission/sessions/slash-commands. |
| `deepagents` | `uv tool install "superqode[deepagents]"` | Optional DeepAgents 0.6 runtime for graph and middleware-heavy coding harnesses. |
| `pydanticai` | `uv tool install "superqode[pydanticai]"` | Optional PydanticAI runtime with SuperQode JSON-schema tool bridging, approval resume, native MCP config loading, fallback chains, and typed-output-friendly harness support. |

Runtime backends implement the same SuperQode harness contract where their underlying framework can honor it. If a backend cannot support a harness policy, it should fail clearly rather than silently degrading the run.

## Picking A Runtime

Precedence, highest first:

1. CLI flag: `--runtime adk`
2. `superqode.yaml`: `superqode.runtime: adk`
3. Env var: `SUPERQODE_RUNTIME=adk`
4. Default: `builtin`

### CLI

```bash
superqode --runtime adk
superqode --runtime openai-agents --print "summarize this repository"
superqode --runtime codex-sdk --print "summarize this repository"
superqode harness run --spec harness.yaml --runtime pydanticai --prompt "reason about this design"
```

### YAML

```yaml
superqode:
  runtime: openai-agents
```

### Env Var

```bash
SUPERQODE_RUNTIME=adk superqode --print "summarize README.md"
```

### TUI

Switch backends from inside a running session without restarting:

```text
:runtime list          # list runtimes with status (ready / missing + install hint / stub)
:runtime codex-sdk     # swap to a runtime by name; the status-bar badge updates
```

The swap takes effect on your **next message**, which reconnects on the new
backend. Precedence (CLI > YAML > env) still applies to the *initial* runtime.

## Connection Sources (`:connect`)

`:connect` chooses **what you connect to** (a product/account), while runtime is
the engine that executes it. The picker is profile-driven and shows live status:

```text
:connect
  [1] ACP agent            Any external ACP agent (incl. your local Claude Code)
  [2] BYOK provider        Your API key, such as OpenAI, Anthropic, or Gemini
  [3] Local model          Ollama / MLX / vLLM / LM Studio ...
  [4] Codex subscription   Drive OpenAI Codex with your ChatGPT/Codex login (~/.codex)
  [5] Claude Agent SDK     Use your Anthropic API key via claude-agent-sdk
  [6] Antigravity CLI      Use Google's agent harness with your Google Sign-In
  [7] Advanced runtime     Pick the execution engine (builtin / openai-agents / ...)
```

**Claude** has one headline entry: **Claude Agent SDK** (API key via
`ANTHROPIC_API_KEY`). Your *local* Claude Code (subscription login) is reached
through **ACP agent** like any other ACP agent. It is not duplicated as its own
profile. Neither path implies SuperQode using a Claude Pro/Max subscription.

Direct commands and CLI:

```bash
:connect codex            # in the TUI, uses your Codex subscription
:connect claude           # use Claude Agent SDK with ANTHROPIC_API_KEY
:connect antigravity      # signed-in agy CLI (Google OAuth/keyring)
:connect byok google      # Google API key path
:connect acp              # generic ACP picker, including local Claude Code
superqode --connect codex # launch already on Codex
superqode --connect codex --print "summarize this repo"   # headless
```

Each source maps to a connector internally: **Codex** → the `codex-sdk` runtime
(self-contained, `~/.codex` auth); **Claude** → the `claude-agent-sdk` runtime
(`ANTHROPIC_API_KEY`); **Antigravity** → the `antigravity-cli` runtime using
`agy`'s Google Sign-In/keyring; **BYOK/Local**
→ the `builtin` runtime + provider/model, with an optional runtime override;
**Advanced** → the raw `:runtime` picker.

Only **Codex** is a sanctioned *subscription* SDK path today. Claude has two paths:
**Claude Code (ACP)** uses your own local Claude CLI, and **Claude Agent SDK** is
an **API-key** runtime (`claude-agent-sdk`, `ANTHROPIC_API_KEY`). Both are shipped.
**Antigravity CLI** is a self-contained runtime backed by `agy --print`. The
official CLI owns Google OAuth and retrieves its session from the OS keyring;
SuperQode never reads the token. API-key users can use `:connect byok google`,
or install the optional `antigravity-sdk` extra and select that advanced runtime.

### Antigravity CLI

Google's Antigravity CLI (`agy`) is the consumer migration path for Gemini CLI:

```text
:antigravity launch
:antigravity status
:antigravity migrate
```

SuperQode does **not** route `agy` through ACP. `:connect antigravity` invokes
its supported headless print mode and continues the CLI conversation between
turns. `agy` 1.1.1 or newer is required because it fixes subprocess hangs and
error exit codes. The route streams text, but `agy` does not expose structured
tool or approval events.

For a complete comparison of harness ownership, authentication, and supported
routes, see [Google Antigravity](providers/antigravity.md).

Gemini CLI remains listed under the generic ACP picker for enterprise/API-key ACP
users. For Google AI Pro, Ultra, and free Code Assist individual accounts, prefer
Antigravity CLI.

## Inspecting Available Runtimes

```bash
superqode runtime list
```

Example output:

```text
                          SuperQode runtimes
┏━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ┃ Runtime       ┃ Status ┃ Description                           ┃
┡━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ▸  │ builtin       │ ready  │ SuperQode native agent loop (default) │
│    │ adk           │ ready  │ Google Agent Development Kit          │
│    │ openai-agents │ ready  │ OpenAI Agents SDK                     │
│    │ codex-sdk     │ ready  │ OpenAI Codex Python SDK / app-server  │
│    │ deepagents    │ ready  │ DeepAgents runtime adapter            │
└────┴───────────────┴────────┴───────────────────────────────────────┘
```

The `▸` marks the active runtime given current precedence. A runtime without its optional install shows up as `missing` with the install command inline.

For deeper diagnostics:

```bash
superqode runtime doctor adk
superqode runtime doctor
```

`doctor` exits non-zero if any probed runtime is missing. This is useful in CI to confirm the checkout has the runtimes the project assumes.

## Runtime Notes

### `builtin`

The default. Wraps SuperQode's `AgentLoop` 1:1. No optional install, no special config.

Use `builtin` for:

- normal repository work
- no-tool and model-only harnesses
- Gemma4 and DS4 policy experiments
- exact SuperQode sandbox behavior
- typed outputs and workflow execution through the native harness path
- approval pauses for ASK-permission tool calls
- rich harness graph events for model requests, streamed deltas, tool calls, tool results, and approvals

### `adk`

Wraps `google.adk.runners.Runner` and `google.adk.agents.LlmAgent`. Uses ADK's own model layer, `InMemorySessionService` for session storage, and bridges SuperQode tools as ADK `BaseTool` subclasses.

Current limits:

- ASK permissions are treated as DENY because ADK cannot surface an interactive prompt from inside a tool body yet.
- Sessions are in-memory inside ADK. SuperQode persistence is layered on top by callers.
- MCP servers are not yet bridged into ADK's native MCP system.
- The adapter is pinned to `>=1.33.0,<2.0`.

### `openai-agents`

Wraps `agents.Agent` and `agents.Runner` from the OpenAI Agents SDK.

Current behavior:

- Bridges SuperQode tools as `FunctionTool`s.
- Streams rich harness events from SDK stream events, including model deltas, tool calls, tool results, approval pauses, and sandbox start markers when SandboxAgent execution is enabled.
- Uses SDK cancellation for streaming runs.
- Persists SDK sessions through a SuperQode JSONL adapter.
- Routes non-OpenAI providers through `LitellmModel(...)` when the `[litellm]` extra is installed.
- Surfaces `needs_approval` interruptions through direct runtime sessions and HarnessSpec sessions.
- Consumes the harness sandbox contract when SandboxAgent execution is requested.
- Keeps tracing disabled by default for privacy.

Current limits:

- Native SDK sandbox integrations remain a follow-up.
- Native SDK MCP server objects are not yet the default bridge.

### `codex-sdk`

Wraps the official OpenAI Codex Python SDK (`openai-codex`) behind the SuperQode runtime contract. The SDK launches the Codex app-server locally and SuperQode talks to it through the SDK client.

Use `codex-sdk` when you want OpenAI Codex SDK behavior while still selecting the backend through SuperQode runtime and HarnessSpec configuration.

Current behavior:

- Uses the published `openai-codex` package installed from `superqode[codex-sdk]`.
- Starts the Codex SDK app-server through the SDK client; SuperQode does not vendor or import code from `reference/codex/sdk/python`.
- Maps SuperQode provider/model/cwd/sandbox settings into Codex thread and turn options where the SDK supports them.
- Streams normalized harness events for model deltas, command/file output deltas, patch updates, command/file/MCP/dynamic-tool results, and turn completion.
- Treats a streamed turn as successful only after Codex sends `turn/completed`; a dropped stream raises instead of producing a false `model_result`.
- Uses Codex SDK cancellation through the active turn interrupt path.
- Serializes turns per Codex runtime/thread so `cancel()` and approval prompts always apply to the active turn.
- Routes Codex command/file approval callbacks through SuperQode's `PermissionManager`.
  In the TUI, Codex approval callbacks are bridged to the inline `y`/`n`/`a`
  permission prompt and honor SuperQode's approval mode.
- Forwards Codex command/file/MCP results through SuperQode's existing tool-card callbacks in PureMode.
- Uses a bounded `openai-codex` dependency range because the adapter translates SDK protocol fields.

Current limits:

- Programmatic helpers do not display a UI prompt. Local Codex trust/policy in
  `~/.codex` can avoid approval callbacks; if Codex still asks without a TUI
  bridge or explicit policy, the default is to reject with a clear message. An
  explicitly supplied `PermissionManager(default=ALLOW)` or runtime approval
  callback can approve non-interactively.
- Native Codex SDK MCP configuration is owned by the local Codex config (`~/.codex`), not mapped from SuperQode MCP config.
- Typed-output handling still belongs to SuperQode's native harness/output layer.

Example:

```bash
uv tool install "superqode[codex-sdk]"
superqode --runtime codex-sdk --print "summarize this repository"
```

```yaml
runtime:
  backend: codex-sdk
```

In the TUI, switch backends mid-session without restarting:

```text
:codex                # shorthand for :runtime codex-sdk
:codex status         # fast SDK/app-server status without starting Codex
:codex status --probe # start the SDK app-server and list available models
:codex models         # list models exposed to your local Codex account
:codex model          # pick a model with arrows, numbers, mouse, or exact id
:codex model <id>     # set the model override directly
:codex effort         # pick reasoning effort interactively
:codex effort high    # set reasoning effort directly: minimal/low/medium/high/xhigh
:codex sandbox read-only       # override sandbox for future turns
:codex review         # run a read-only review turn against the current diff
:codex compact        # compact the active Codex thread
:codex sessions       # list Codex sessions for this working directory
:codex resume <id>    # resume an existing Codex thread
:codex fork <id>      # fork an existing Codex thread
:codex rename <name>  # rename the active Codex thread
:codex archive [id]   # archive a Codex thread, defaulting to the active one
:codex account        # show the current Codex account state
:runtime list          # shows codex-sdk as "ready" (or the install hint if missing)
:runtime codex-sdk     # swap backend; the status-bar badge updates
<your prompt>          # the next message reconnects and runs through Codex
```

The Codex model picker uses `CodexClient.model_list()` from the local account
when available, instead of a hardcoded model catalog. `:codex status --probe`
also caches the returned model list for the picker.

These commands are SuperQode commands mapped to the SDK's typed public APIs; the
Python SDK does not provide a generic "run a Codex slash command" passthrough.
`:codex review` intentionally uses the documented public pattern of a
read-only turn with a review prompt. The lower-level `review/start` protocol is
not used until the Python SDK exposes a stable public wrapper for it.

Programmatically, the `superqode.codex` helpers wrap the runtime so you don't
hand-build an `AgentConfig`:

```python
import asyncio
from superqode.codex import run_codex, stream_codex, codex_session

# one-shot (synchronous)
resp = run_codex("Add a docstring to main.py", cwd="myrepo")
print(resp.content, resp.stopped_reason)

# stream typed harness events
async def go():
    async for ev in stream_codex("Write tests for utils.py", cwd="myrepo"):
        print(ev.type, ev.data)
asyncio.run(go())

# multi-turn on one Codex thread; list models your account exposes
with codex_session(cwd="myrepo") as cx:
    print(cx.models())                       # e.g. <openai-model> (default), <openai-fast-model>, <openai-small-model>
    asyncio.run(cx.run("Summarize the repo"))
```

The default model is empty (`superqode.codex.DEFAULT_CODEX_MODEL`), which lets
Codex use your local `~/.codex` default. Override per call with `model=...`.
Programmatic helpers also accept `approval_callback=...`,
`permission_manager=...`, and `session_id=...` for non-interactive approval
policy and session correlation.
A runnable version of the above is in
[`examples/codex_sdk_quickstart.py`](https://github.com/SuperagenticAI/superqode/blob/main/examples/codex_sdk_quickstart.py).

The local `reference/codex/sdk/python` checkout is documentation/reference material only. Runtime code must depend on the packaged SDK (`openai-codex`) so installs are reproducible and do not accidentally bind to a local reference tree.

When a newer standalone Codex CLI is installed, SuperQode prefers it so the
subscription model catalogue stays current. Safe metadata operations such as
model listing and account reads automatically fall back to the SDK-pinned
app-server if the newer CLI returns an incompatible protocol response. Set
`SUPERQODE_CODEX_PREFER_LOCAL_CLI=0` to always use the SDK-pinned server; agent
turns are never replayed automatically because tools may already have run.

Set `SUPERQODE_CODEX_REAL_TEST=1` to run the optional real SDK/app-server smoke
test during development; it is skipped by default because it requires local
Codex auth and may contact the Codex service.

Performance notes: SuperQode reuses an already-connected Codex runtime when
`:codex`/`:runtime codex-sdk` is invoked again in the same working directory,
streams SDK notifications through one background reader thread, and batches
high-volume command output deltas before updating tool cards.

### `pydanticai`

Wraps `pydantic_ai.Agent` behind the SuperQode runtime contract and exposes the same engine through the `pydanticai` HarnessSpec backend.

Current behavior:

- Bridges SuperQode tools through PydanticAI's lower-level `ToolDefinition.parameters_json_schema` path.
- Supports tool-capable coding specs and no-tool specs.
- Streams rich harness events through PydanticAI `run_stream_events`, including model deltas, tool calls, tool results, final results, and deferred approval requests.
- Surfaces PydanticAI deferred tool approvals through the same `:approve` and `:reject` harness flow used by other pausing runtimes.
- Loads native PydanticAI MCP toolsets from `runtime.config.pydanticai.mcp_config_path`.
- Uses PydanticAI `FallbackModel` when `model_policy.fallbacks` are present.
- Enables Logfire/PydanticAI instrumentation when `observability.traces: true` or `runtime.config.pydanticai.logfire` is configured. Install `superqode[pydanticai-logfire]` for this path.
- Can wrap the PydanticAI agent with Prefect or DBOS durable execution via `runtime.config.pydanticai.durable: prefect` or `dbos` when those packages are installed.
- Applies SuperQode model policy settings such as temperature and reasoning effort where PydanticAI supports them.
- Keeps PydanticAI available as an optional install, not a hard dependency.

Current limits:

- Temporal durable execution requires a Temporal workflow and worker, so SuperQode reports a clear setup error instead of pretending it can run Temporal in-process.
- SuperQode's sandbox policy still owns local file and shell behavior.

Example runtime config:

```yaml
runtime:
  backend: pydanticai
  config:
    pydanticai:
      mcp_config_path: .superqode/mcp.json
      durable: prefect
      logfire:
        send_to_logfire: if-token-present
observability:
  traces: true
model_policy:
  fallbacks:
    - anthropic:<anthropic-balanced-model>
```

### `deepagents`

Wraps DeepAgents 0.6 through `create_deep_agent(...)`. This backend is useful when you want DeepAgents graph state, middleware, filesystem backend behavior, and subagent patterns behind a SuperQode `HarnessSpec`.

SuperQode maps:

- `provider` and `model` to DeepAgents `provider:model` model specs
- the working directory to `FilesystemBackend(root_dir=..., virtual_mode=True)`
- SuperQode job prompt to DeepAgents `system_prompt`
- configured skills and memory from runtime config
- DeepAgents results back into a normalized `AgentResponse`
- DeepAgents stream events into harness graph nodes for model deltas, tool calls, subagents, memory reads/writes, sandbox file/command activity, and final results

Current limits:

- No-tool specs are rejected. Use `builtin` for model-only harnesses.
- Specs with `allow_shell=false` are rejected for now because DeepAgents exposes `execute` when using the filesystem backend.
- DeepAgents remains optional. Use it when you want DeepAgents behavior behind a SuperQode harness.

## Embedding

If you are embedding SuperQode, construct a runtime through the runtime factory:

```python
from superqode.runtime import create_runtime, resolve_runtime_name

runtime = create_runtime(
    resolve_runtime_name(cli=user_flag),
    gateway=gateway,
    tools=tool_registry,
    config=agent_config,
)
response = await runtime.run("write hello.txt with the text 'hi'")
```

The constructor signature is identical across backends. Each runtime ignores args it does not use when that is safe. When a runtime cannot honor a harness policy, it should report a clear error.
