# Agent runtimes

SuperQode's agent loop is **pluggable**. You can keep the default native loop, or opt into a different backend with one flag. Three runtimes ship today:

| Runtime         | Install                            | Notes                                                  |
|-----------------|------------------------------------|--------------------------------------------------------|
| `builtin`       | included                           | SuperQode's native loop — the default. No extra install. |
| `adk`           | `pip install superqode[adk]`       | Google Agent Development Kit. Uses ADK's `Runner` + `LlmAgent`. |
| `openai-agents` | `pip install superqode[openai-agents]` | OpenAI Agents SDK v0.17+. Includes native MCP support and real HITL. |

All three implement the same `AgentRuntime` protocol. The TUI, headless CLI, A2A server, and ACP unified agent all work with any of them.

---

## Picking a runtime

Precedence (highest first):

1. **CLI flag**: `--runtime adk`
2. **superqode.yaml**: `superqode.runtime: adk`
3. **Env var**: `SUPERQODE_RUNTIME=adk`
4. **Default**: `builtin`

### CLI

```
superqode --runtime adk
superqe run . --runtime openai-agents
```

### YAML

```yaml
superqode:
  runtime: openai-agents
```

### Env var (useful for CI)

```
SUPERQODE_RUNTIME=adk superqode --print "summarize README.md"
```

---

## Inspecting available runtimes

```
$ superqode runtime list
                          SuperQode runtimes
┏━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ┃ Runtime       ┃ Status ┃ Description                           ┃
┡━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ▸  │ builtin       │ ready  │ SuperQode native agent loop (default) │
│    │ adk           │ ready  │ Google Agent Development Kit          │
│    │ openai-agents │ ready  │ OpenAI Agents SDK                     │
└────┴───────────────┴────────┴───────────────────────────────────────┘
```

The `▸` marks the active runtime given current precedence. A runtime without its optional install shows up as `missing` with the install command inline.

For deeper diagnostics, including which sub-modules import cleanly:

```
superqode runtime doctor adk
superqode runtime doctor              # probes every known runtime
```

`doctor` exits non-zero if any probed runtime is missing — useful in CI to gate "this checkout has the runtimes the project assumes."

---

## Runtime-specific notes

### `builtin`

The default. Wraps SuperQode's `AgentLoop` 1:1 — same behavior as before runtimes were introduced. No optional install, no special config.

### `adk`

Wraps `google.adk.runners.Runner` + `google.adk.agents.LlmAgent`. Uses ADK's own model layer (`LiteLlm` for non-Gemini), `InMemorySessionService` for session storage, and bridges SuperQode's tools as ADK `BaseTool` subclasses.

**v1 limitations:**

- ASK permissions are treated as DENY (ADK can't surface an interactive prompt from inside a tool body — Phase 6 TODO).
- Sessions are in-memory only (SuperQode's JSONL persistence is layered on top by callers).
- MCP servers are not yet bridged into ADK's native MCP system.
- Pinned `>=1.33.0,<2.0`. ADK 2.0 will require an adapter rewrite.

### `openai-agents`

Wraps `agents.Agent` + `agents.Runner` (the OpenAI Agents SDK). This is the **most full-featured runtime** today:

- Bridges SuperQode tools as `FunctionTool`s with **real HITL** via `needs_approval` — ASK actually pauses the run and waits for approval (Phase 6 will wire that to the TUI dialog).
- **Streaming uses `result.cancel()`** for real cancellation (no flag-poll).
- Sessions persist via `SuperQodeSession`, a JSONL adapter for the SDK's `SessionABC` protocol, stored alongside the standard session file.
- Non-OpenAI providers route via `LitellmModel(...)` — the `[litellm]` sub-extra is included transparently with `pip install superqode[openai-agents]`.
- MCP tool definitions are bridged as `FunctionTool`s that delegate to SuperQode's `mcp_executor`. Native `MCPServerStdio` instances on the Agent are a v2 follow-up (Phase 7).

**v1 limitations:**

- HITL approval dialog plumbing in the TUI is Phase 6 (today `stopped_reason="needs_approval"` is reported but not interactively driven).
- `SandboxAgent` + 7-provider sandbox integration is Phase 7.
- Tracing is **disabled by default** for privacy (`RunConfig(tracing_disabled=True)`). Opt-in support coming later.

---

## How callers use this

If you're embedding SuperQode, construct a runtime via `create_runtime`:

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

The constructor signature is **identical across backends**. Each runtime quietly ignores args it doesn't use (the ADK adapter ignores `gateway`, etc.).
