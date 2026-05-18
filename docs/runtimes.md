# Agent Runtimes

SuperQode's runtime layer is pluggable. You can keep the default native loop, or opt into a different backend with one flag. Runtime adapters are peers behind the same harness contract.

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
| `deepagents` | `pip install superqode[deepagents]` | Optional DeepAgents 0.6 runtime for graph and middleware-heavy coding harnesses. |

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
- Uses SDK cancellation for streaming runs.
- Persists SDK sessions through a SuperQode JSONL adapter.
- Routes non-OpenAI providers through `LitellmModel(...)` when the `[litellm]` extra is installed.
- Keeps tracing disabled by default for privacy.

Current limits:

- TUI approval dialog plumbing is still a follow-up.
- Native SDK sandbox integrations remain a follow-up.
- Native SDK MCP server objects are not yet the default bridge.

### `deepagents`

Wraps DeepAgents 0.6 through `create_deep_agent(...)`. This backend is useful when you want DeepAgents graph state, middleware, filesystem backend behavior, and subagent patterns behind a SuperQode `HarnessSpec`.

SuperQode maps:

- `provider` and `model` to DeepAgents `provider:model` model specs
- the working directory to `FilesystemBackend(root_dir=..., virtual_mode=True)`
- SuperQode job prompt to DeepAgents `system_prompt`
- configured skills and memory from runtime config
- DeepAgents results back into a normalized `AgentResponse`

Current limits:

- No-tool specs are rejected. Use `builtin` for model-only harnesses.
- Specs with `allow_shell=false` are rejected for now because DeepAgents exposes `execute` when using the filesystem backend.
- DeepAgents remains optional and peer-level. It does not replace the SuperQode harness kernel.

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
