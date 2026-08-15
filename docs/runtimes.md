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

The TUI and runtime doctor consistently show the packaged-product command
`uv tool install "superqode[<extra>]"`. This avoids leaking editable-checkout
commands into user onboarding or adding SuperQode to an unrelated application's
dependencies. Contributors working from this repository should use
`uv sync --extra <extra>`. SuperQode never installs an optional runtime without
explicit user action. See the
[official uv documentation](https://docs.astral.sh/uv/) for environment details.

| Runtime | Install | Notes |
| --- | --- | --- |
| `builtin` | included | SuperQode's native loop. This is the default and the canonical path for local-model and no-tool policy. |
| `adk` | `uv tool install "superqode[adk]"` | Google Agent Development Kit. Uses ADK's `Runner` and `LlmAgent`. |
| `openai-agents` | `uv tool install "superqode[openai-agents]"` | OpenAI Agents SDK v0.17+. Includes SDK sessions, tool bridging, and HITL support. |
| `codex-sdk` | `uv tool install "superqode[codex-sdk]"` | Official OpenAI Codex Python SDK runtime. Drives the published `openai-codex` package and its local app-server. |
| `copilot-sdk` | `uv tool install "superqode[copilot-sdk]"` | Official GitHub Copilot SDK runtime. Uses the user's Copilot account or an explicit GitHub token and normalizes SDK events into SuperQode. |
| `claude-agent-sdk` | `uv tool install "superqode[claude-agent-sdk]"` | Anthropic Claude Agent SDK runtime (API key via `ANTHROPIC_API_KEY`). The SDK provides its own Claude Code executable; `:claude` exposes model, permission, session, and slash-command controls. |
| `antigravity-sdk` | `uv tool install "superqode[antigravity-sdk]"` | Google Antigravity SDK runtime using `GEMINI_API_KEY` or `GOOGLE_API_KEY`. This is separate from the signed-in `agy` CLI route. |
| `antigravity-managed` | included | Google-hosted Antigravity agent over the Gemini Interactions API using `GEMINI_API_KEY` or `GOOGLE_API_KEY`. |
| `deepagents` | `uv tool install "superqode[deepagents]"` | Optional DeepAgents 0.7 runtime for graph and middleware-heavy coding harnesses. Also available as the built-in `deepagents` harness. |
| `pydanticai` | `uv tool install "superqode[pydanticai]"` | Optional PydanticAI runtime with SuperQode JSON-schema tool bridging, approval resume, native MCP config loading, fallback chains, and typed-output-friendly harness support. |

### Vendor SDK Bundle

The default package does not install large vendor SDKs. Install all supported
vendor SDK runtimes only when you need them together:

```bash
uv tool install "superqode[vendor-sdks]"
```

This bundle contains `codex-sdk`, `copilot-sdk`, `claude-agent-sdk`, and `antigravity-sdk`.
It does not contain the Grok CLI or the `agy` CLI. Those products manage their
own installation, authentication, and update lifecycle. Codex subscription
authentication also uses the separate Codex CLI and `codex login`.

Use either setup command to see commands adjusted for the current environment:

```bash
superqode runtime setup
```

```text
:runtime setup
```

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
superqode --runtime copilot-sdk --model gpt-5.6-sol --print "review this repository"
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
:runtime setup         # show individual and bundled vendor SDK setup
:runtime codex-sdk     # swap to a runtime by name; the status-bar badge updates
```

The swap takes effect on your **next message**, which reconnects on the new
backend. Precedence (CLI > YAML > env) still applies to the *initial* runtime.

## Connection Sources (`:connect`)

`:connect` chooses **what you connect to** (a product/account), while runtime is
the engine that executes it. The picker is profile-driven and shows live status:

```text
:connect
  How do you want to connect?
  [1] Local                        Ollama / LM Studio / MLX / vLLM ...
  [2] ACP (Agent Client Protocol)  Any installed external ACP agent
  [3] BYOK (Bring Your Own Key)    Your API key, such as OpenAI, Anthropic, or Gemini
  [4] Subscriptions                Vendor coding agents on a plan you already pay for
  [5] Other harnesses              Browse optional non-ACP integrations such as Tau
```

Option 4 opens the vendor screen. Esc returns to the screen above:

```text
:connect subscriptions
  US Coding Agents
  [1] Codex                Drive OpenAI Codex with your ChatGPT/Codex login (~/.codex)
  [2] Cursor               Use the Cursor plan signed in to Cursor CLI
  [3] Amp                  Use the Amp plan signed in to Amp CLI
  [4] Antigravity CLI      Use Google's agent harness with your Google Sign-In
  [5] Grok                 Use Grok Build through the signed-in Grok CLI
  [6] GitHub Copilot       Use your plan through the SDK or official CLI
  [7] Gemini CLI           Use Google's Gemini CLI through its vendor sign-in
  [8] Devin                Use Cognition's Devin CLI through devin acp
  [9] Factory Droid        Use the locally authenticated Droid CLI
  [10] Kiro                Use a Kiro or Amazon Q Developer plan through Kiro CLI

  China Coding Agents
  [11] GLM Coding Plan      Use the paid plan through its authenticated ACP agent
  [12] Qwen Code            Use QwenLM's signed-in first-party agent
  [13] Kimi Code            Use Moonshot AI's signed-in first-party agent
```

The screen is reserved for vendor plans and vendor-managed sign-in. API-key-only
routes such as the Claude Agent SDK and Z.AI general API stay under BYOK or
explicit runtime commands. SuperQode does not copy vendor tokens; the local
vendor CLI or ACP adapter owns its credential store.

### Missing dependency flow

When a SuperQode-owned optional Python runtime is missing, the TUI keeps the
user in place and offers three keyboard choices:

1. **Install it for me**: installs only the allow-listed
   `superqode[<runtime-extra>]` into the interpreter currently running
   SuperQode, then continues the connection.
2. **I will install it myself**: shows the exact environment-targeted command.
3. **Cancel**: returns to the connection screen.

This applies to runtimes such as `codex-sdk` and `copilot-sdk`. SuperQode does
not run npm, curl-to-shell, system-package-manager, or other vendor-agent
installers from the connection picker; those remain manual instructions.

Direct commands and CLI:

```bash
:connect subscriptions    # the vendor screen shown above
:connect codex            # in the TUI, uses your Codex subscription
:connect cursor           # Cursor subscription through Cursor Agent ACP
:connect amp              # Amp subscription through its ACP adapter
:connect kimi-code        # Moonshot AI Kimi Code through its official ACP server
:connect qwen-code        # Qwen Code through its stable ACP server
:connect acp gemini       # Google Gemini CLI through gemini --acp
:connect devin            # Cognition Devin CLI through devin acp
:connect droid            # Factory Droid subscription through ACP
:connect kiro             # Kiro/Amazon Q Developer plan through Kiro ACP
:connect glm-cli          # GLM Coding Plan through its ACP agent
:connect copilot          # official Copilot SDK path
:copilot models           # live model catalog for the active Copilot account
:connect acp copilot      # advanced Copilot CLI ACP compatibility path
:connect other-harnesses  # optional non-ACP integrations such as Tau
:connect antigravity      # signed-in agy CLI (Google OAuth/keyring)
:antigravity managed      # Google-hosted sandbox (Gemini API key)
:connect byok anthropic   # Anthropic API-key path
:connect byok zai         # Z.AI general API-key path
:connect byok google      # Google API key path
:connect acp              # installed and featured ACP agents
:connect acp all          # complete live ACP registry
superqode --connect codex # launch already on Codex
superqode --connect codex --print "summarize this repo"   # headless
```

Kimi Code and Qwen Code are first-party agent connections. SuperQode uses their
official ACP servers instead of replacing their native agent loops. Install and
authenticate the vendor CLI once, then select the named connection:

```bash
curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash
kimi
# Complete /login, then exit Kimi Code and run :connect kimi-code in SuperQode.

npm install -g @qwen-code/qwen-code
qwen auth
# Then run :connect qwen-code in SuperQode.
```

The same entries appear in `:harness` and can be selected directly with
`:harness switch kimi-code` or `:harness switch qwen-code`. Their explicit ACP
aliases, `acp:kimi` and `acp:qwen`, remain available for scripts and advanced
catalog workflows.

Tau can be selected and configured entirely inside SuperQode:

```text
:tau login ollama/qwen3.6:35b-mlx
```

Use `:tau help` to see its provider, model, session, logout, and retry
subcommands. The command selects Tau and connects the route, so a separate
`:connect`, Tau TUI, or `/login` command is not required.

Each source maps to a connector internally: **Codex** maps to the `codex-sdk` runtime
(self-contained, `~/.codex` auth); **GitHub Copilot** prefers the
`copilot-sdk` runtime and falls back to the official CLI's ACP server; explicit
SDK and CLI commands remain available;
**Claude** maps to the `claude-agent-sdk` runtime
(`ANTHROPIC_API_KEY`); **Antigravity** → the `antigravity-cli` runtime using
`agy`'s Google Sign-In/keyring; **BYOK/Local**
→ the `builtin` runtime + provider/model, with an optional runtime override;
**Advanced** → the raw `:runtime` picker.

Codex and GitHub Copilot provide supported subscription SDK paths. Claude has two paths:
**Claude Code (ACP)** uses your own local Claude CLI, and **Claude Agent SDK** is
an **API-key** runtime (`claude-agent-sdk`, `ANTHROPIC_API_KEY`). Both are shipped.
**Antigravity CLI** is a self-contained runtime backed by `agy --print`. The
official CLI owns Google OAuth and retrieves its session from the OS keyring;
SuperQode never reads the token. API-key users can use `:connect byok google`,
install the optional `antigravity-sdk` extra for the local SDK, or select
`:antigravity managed` for Google's hosted sandbox.

**Antigravity Managed** streams structured thought, tool, and text events and
resumes both conversation and hosted filesystem state. Its sandbox is remote;
SuperQode does not upload the current checkout automatically.

**Antigravity SDK** normalizes the local harness's typed events, usage, and
conversation identity. It also bridges mutating tool calls into SuperQode
approvals, propagates cancellation to the SDK backend, discovers project
skills, and converts configured stdio or Streamable HTTP MCP servers.

### Antigravity CLI

Google's Antigravity CLI (`agy`) is the consumer migration path for Gemini CLI:

```text
:antigravity launch
:antigravity status
:antigravity agent reviewer
:antigravity model gemini-model-slug
:antigravity effort high
:antigravity migrate
```

SuperQode does **not** route `agy` through ACP. `:connect antigravity` invokes
its supported headless print mode and continues the CLI conversation between
turns. `agy` 1.1.1 or newer is required because it fixes subprocess hangs and
error exit codes. The route streams text, but `agy` does not expose structured
tool or approval events.

Custom agent selection uses `agy --agent`, model selection uses `agy --model`,
and thinking effort uses `agy --effort`. Effort requires version 1.1.5 or newer
and accepts `low`, `medium`, or `high` in CLI 1.1.6. Use `auto` to return a
setting to the CLI default.

For a complete comparison of harness ownership, authentication, and supported
routes, see [Google Antigravity](providers/antigravity.md).

Gemini CLI remains listed under the generic ACP picker for enterprise/API-key ACP
users. For Google AI Pro, Ultra, and free Code Assist individual accounts, prefer
Antigravity CLI.

### Subscription CLI runtimes

A subscription connection spends the plan you already pay for, so it uses the
vendor's own SDK or its plain CLI. ACP is not offered under Subscriptions
because the ACP channel is a separate connection source.

```text
:runtime copilot-cli    # GitHub Copilot on your subscription (copilot login)
:runtime grok-cli       # Grok Build headless (`grok -p`); :connect grok stays ACP
```

`copilot-cli` and `grok-cli` drive the vendor's documented non-interactive mode
with structured output, so the turn streams into SuperQode's TUI while the
vendor keeps owning the agent loop.

**Billing.** These runtimes start the vendor process from an environment with
API-key variables removed, so a key left in your shell cannot silently move the
session onto metered billing. Your own environment is never modified: only the
copy handed to that one subprocess omits them, and the keys that were ignored
are reported when you connect. Use `:connect byok` when you do want to spend an
API key.

**Permissions.** A headless CLI cannot prompt per tool call, so SuperQode's
approval mode is translated into the vendor's own setting for the whole turn
and stated on the first turn rather than applied quietly:

| Approval mode | Grok | Copilot |
| --- | --- | --- |
| `auto` | `--permission-mode bypassPermissions` | `--allow-all-tools` |
| `ask` | `--permission-mode auto` | `--allow-all-tools` |
| `deny` | `--permission-mode dontAsk` | `--allow-all-tools` |

Copilot's CLI requires `--allow-all-tools` for non-interactive use and offers
no gradation, so every approval mode resolves to the same flags and the runtime
says so. Use the Copilot SDK route or `:connect acp copilot` when you want
per-tool approval prompts.

`SUPERQODE_VENDOR_CLI_TIMEOUT` (default `900` seconds) bounds one turn.

### Devin CLI

Cognition's Devin CLI has **two** routes, and ACP is the better one:

```text
:connect acp devin      # preferred: structured tool calls, diffs, approvals
:runtime devin-cli      # headless: devin --print, plain text only
```

`devin acp` speaks JSON-RPC over stdio and surfaces tool calls and permission
requests in the TUI. The `devin-cli` runtime instead drives Devin's documented
single-turn print mode, which emits prose and no structured events. Choose it
when you want Devin as a harness for unattended runs (`superqode run`,
benchmarks, scripted turns) rather than an interactive session.

Because a `--print` turn is unattended, a permission prompt would block with
nobody to answer it. The runtime therefore starts Devin in `bypass` mode, which
auto-approves tool calls, and pairs it with `--sandbox` wherever Devin supports
sandboxing (macOS; Linux with `bubblewrap` and `socat`; never Windows, where
Devin refuses to start rather than run unsandboxed). Both are overridable:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SUPERQODE_DEVIN_CLI_PERMISSION_MODE` | `bypass` | `normal`, `accept-edits`, `bypass`, `dangerous`, `autonomous`, or `plan`. Any mode other than `bypass` can stall an unattended turn. |
| `SUPERQODE_DEVIN_CLI_SANDBOX` | on where supported | Set `0` to disable. Setting `1` never forces the flag onto a platform Devin cannot sandbox. |

Model selection uses `devin --model` (`opus`, `sonnet`, `gpt`, `codex`,
`gemini`, `swe`, or a pinned id). The official CLI owns sign-in: run
`devin auth login` once, and SuperQode never reads or copies its credentials.
After the first turn the runtime pins the session id reported by
`devin list --format json` and resumes it with `--resume`, falling back to
`--continue` if that listing is not in a shape SuperQode recognises.

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

Programmatically, the `superqode.codex` helpers wrap the runtime so callers do not
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

### `copilot-sdk`

Wraps the official `github-copilot-sdk` Python package. The SDK manages a
pinned Copilot runtime and uses the user's Copilot login or an explicit GitHub
token. GitHub Copilot owns planning, built-in tools, file edits, and model
access. SuperQode supplies HarnessSpec context, permission decisions,
normalized events, evaluation, evidence, and terminal session controls.

```bash
uv tool install "superqode[copilot-sdk]"
npm install -g @github/copilot
copilot login
superqode --connect copilot
```

Inside the TUI:

```text
:copilot status
:copilot models
:copilot model gpt-5.6-sol
:copilot sessions
:copilot resume <session-id>
:copilot acp
```

Model availability is determined by the Copilot account and organization
policy. See [GitHub Copilot](providers/github-copilot.md) for the SDK and ACP
route comparison.

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

Wraps DeepAgents 0.7 through `create_deep_agent(...)`. This backend is useful when you want DeepAgents graph state, middleware, filesystem backend behavior, and subagent patterns behind a SuperQode `HarnessSpec`.

It is also a selectable harness. `superqode harness run deepagents "..."` and
`:harness switch deepagents` use the shipped preset, and
`superqode harness init <name> --template deepagents` starts a repository-owned
spec from it. See [LangChain DeepAgents](providers/deepagents.md) for the
complete route, including the `dcode` coding agent.

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
- SuperQode targets the DeepAgents 0.7 API. Another release reports a version problem rather than a missing package, so the required upgrade or downgrade is named directly.
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
