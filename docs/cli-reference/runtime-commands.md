# Runtime Commands

Manage runtime backends for agent execution.

---

## runtime list

List available runtime backends with install status.

```bash
superqode runtime list
```

### Output

```text
Backend           Status     Description
builtin           ready      Default harness runtime
adk               missing    Google ADK (google-adk)
openai-agents     missing    OpenAI Agents SDK
pydanticai        missing    PydanticAI
codex-sdk         missing    Codex SDK
claude-agent-sdk  missing    Claude Agent SDK
```

---

## runtime doctor

Probe runtime dependency availability.

```bash
superqode runtime doctor [name]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `name` | Check a specific runtime (checks all if omitted) |

Checks whether the required SDK is installed, importable, and at a compatible version. Returns `ready` or `missing` per runtime.

---

## --runtime Global Flag

Use `--runtime` with headless runs or the TUI to select an execution backend:

```bash
superqode -p --runtime adk "implement the feature"
```

### Runtime Backends

| Backend | Package | Description |
|---------|---------|-------------|
| `builtin` | (built-in) | Default harness runtime, no extra dependencies |
| `adk` | `google-adk` | Google Agent Development Kit |
| `openai-agents` | `openai-agents` | OpenAI Agents SDK |
| `pydanticai` | `pydanticai` | PydanticAI agent framework |
| `codex-sdk` | `codex-sdk` | Codex SDK |
| `claude-agent-sdk` | `claude-agent-sdk` | Claude Agent SDK |

Each backend requires its respective package to be installed. Run `runtime doctor` to check availability.
