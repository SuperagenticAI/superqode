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

| Runtime | Install | Notes |
| --- | --- | --- |
| `builtin` | included | SuperQode's native loop. This is the default and the canonical path for local-model and no-tool policy. |
| `adk` | `pip install superqode[adk]` | Google Agent Development Kit. Uses ADK's `Runner` and `LlmAgent`. |
| `openai-agents` | `pip install superqode[openai-agents]` | OpenAI Agents SDK v0.17+. Includes SDK sessions, tool bridging, and HITL support. |
| `codex-sdk` | `pip install superqode[codex-sdk]` | Official OpenAI Codex Python SDK runtime. Drives the published `openai-codex` package and its local app-server. |
| `deepagents` | `pip install superqode[deepagents]` | Optional DeepAgents 0.6 runtime for graph and middleware-heavy coding harnesses. |
| `pydanticai` | `pip install superqode[pydanticai]` | Optional PydanticAI runtime with SuperQode JSON-schema tool bridging, approval resume, native MCP config loading, fallback chains, and typed-output-friendly harness support. |

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
- Streams normalized harness events for model deltas, command output deltas, patch updates, command results, file-change results, and turn completion.
- Uses Codex SDK cancellation through the active turn interrupt path.
- Routes Codex command/file approval callbacks through SuperQode's `PermissionManager`.

Current limits:

- Interactive approval pause/resume is not bridged yet. `ALLOW` accepts, `DENY` rejects, and unresolved `ASK` approvals are rejected by default for safety.
- Native Codex SDK MCP configuration is not yet mapped from SuperQode MCP config.
- Typed-output handling still belongs to SuperQode's native harness/output layer.

Example:

```bash
pip install "superqode[codex-sdk]"
superqode --runtime codex-sdk --print "summarize this repository"
```

```yaml
runtime:
  backend: codex-sdk
```

The local `reference/codex/sdk/python` checkout is documentation/reference material only. Runtime code must depend on the packaged SDK (`openai-codex`) so installs are reproducible and do not accidentally bind to a local reference tree.

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
    - anthropic:claude-sonnet-4-5
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
