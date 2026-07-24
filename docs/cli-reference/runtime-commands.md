# Runtime Commands

Manage runtime backends for agent execution.

---

## runtime setup

Show environment-aware installation commands and authentication steps for the
Codex, GitHub Copilot, Claude Agent, and Antigravity SDK runtimes.

```bash
superqode runtime setup
```

The output includes commands for each SDK extra and the optional
`superqode[vendor-sdks]` bundle. The bundle does not include external
subscription CLIs such as Grok or `agy`.

Inside the TUI, use the equivalent command:

```text
:runtime setup
```

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
copilot-sdk       missing    GitHub Copilot SDK
claude-agent-sdk  missing    Claude Agent SDK
antigravity-sdk   missing    Antigravity local SDK
antigravity-cli   missing    Antigravity CLI
antigravity-managed ready    Google-hosted Antigravity agent
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
| `copilot-sdk` | `github-copilot-sdk` | GitHub Copilot SDK |
| `claude-agent-sdk` | `claude-agent-sdk` | Claude Agent SDK |
| `antigravity-sdk` | `google-antigravity` | Local Antigravity SDK harness |
| `antigravity-cli` | `agy` | Signed-in Antigravity CLI harness |
| `antigravity-managed` | (built-in) | Google-hosted Antigravity agent over the Gemini Interactions API |

Optional backends require their respective package to be installed.
`antigravity-managed` uses the built-in HTTP adapter but requires
`GEMINI_API_KEY` or `GOOGLE_API_KEY` when a task starts. Run `runtime doctor`
to check availability.

## Antigravity Runtime Controls

Use `:agy` to browse the native Antigravity CLI command family:

```text
:agy help
:agy connect
:agy status
:agy agents
:agy agent [name]
:agy models
:agy model [name]
:agy effort <auto|low|medium|high>
:agy changelog
:agy plugin <list|import|install|uninstall|enable|disable|validate|link>
:agy update
:agy install [--dir <path>|--skip-aliases|--skip-path]
:agy launch [agy flags]
:agy continue
:agy resume <conversation-id>
```

Native list and maintenance commands run in the background and return their
output to the SuperQode conversation log. `:agy launch`, `continue`, and
`resume` display an external-terminal command because agy's full-screen TUI
cannot be nested inside SuperQode's TUI.

After connecting the CLI or SDK runtime, inspect or change its thinking effort:

```text
:antigravity effort
:antigravity effort high
:antigravity effort auto
```

Inspect or select the model used for future turns:

```text
:antigravity model
:antigravity model <model-slug>
:antigravity model auto
```

The CLI runtime also supports the custom agents introduced by current `agy`
releases:

```text
:antigravity agent
:antigravity agent reviewer
:antigravity agent auto
```

These settings apply to future turns in the active runtime. SDK model and
effort must be selected before its first turn because model targets are fixed
when the SDK agent starts.
