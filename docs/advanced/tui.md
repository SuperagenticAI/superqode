# Terminal User Interface (TUI)

SuperQode includes a rich Terminal User Interface (TUI) for interactive coding-agent sessions.

## Features

- **Rich Output**: Colored, formatted terminal output
- **Progress Tracking**: Real-time progress indicators
- **Compact Tool Activity**: Search, read, edit, and shell tools are summarized by default
- **Quiet Streaming Logs**: Agent thinking and successful tool output are hidden by default
- **Provider Selection**: ACP, BYOK, and Local provider pickers with setup hints
- **Model Labels**: Tool support, vision, reasoning, coding, context, and price labels where available
- **Local DS4 Support**: DS4 appears in the local provider picker when configured
- **Interactive Prompts**: User input with completion
- **File Browser**: Navigate project files
- **Agent Switcher**: Switch between validation roles
- **Command Palette**: Quick actions
- **Status Bar**: Session status at a glance

## Launching the TUI

```bash
# Start TUI mode
superqode

# Start with a harness spec
superqode --harness harness.yaml

# Start with specific role
superqode --role qe.security_tester
```

## Common TUI Workflow

Use this flow for a normal coding session:

1. Launch from the project root.
2. Connect a provider, ACP agent, or local model with `:connect`.
3. Load a harness with `:harness harness.yaml` when you want portable policy.
4. Type a focused prompt and press `Enter`.
5. Approve or reject pending tool calls.
6. Ask for a summary of changed files and tests.

Example:

```text
:connect
:harness harness.yaml
:status
Summarize this repository and suggest the smallest safe improvement.
Find one low-risk cleanup, make the smallest fix, and run the narrowest useful test.
:approve
Summarize what changed.
```

## TUI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ SuperQode - Validation Session: qe-20260108-143052                  ×│
├─────────────────────────────────────────────────────────────────┤
│ Sidebar        │ Main Content Area                              │
│                │                                                 │
│ ◉ Files        │ Agent Output                                   │
│ ◯ Agents       │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│ ◯ Findings     │                                                 │
│ ◯ Artifacts    │ Analyzing src/api/users.py...                  │
│                │                                                 │
│ Files          │ Found potential SQL injection at line 42       │
│ ├── src/       │                                                 │
│ │   ├── api/   │ ```python                                      │
│ │   └── utils/ │ query = f"SELECT * FROM users WHERE id = {id}" │
│ └── tests/     │ ```                                            │
│                │                                                 │
├─────────────────────────────────────────────────────────────────┤
│ ⌘K Command Palette │ Mode: Quick Scan │ Findings: 2 │ 00:45    │
└─────────────────────────────────────────────────────────────────┘
```

## Key Bindings

| Key | Action |
|-----|--------|
| `Ctrl+K` | Open command palette |
| `Ctrl+F` | Toggle file browser |
| `Ctrl+A` | Switch agent/role |
| `Ctrl+S` | Save session |
| `Ctrl+Q` | Quit |
| `Ctrl+T` | Toggle agent thinking/session logs |
| `Escape` | Close modal/cancel |
| `Enter` | Submit input |
| `Tab` | Next widget |
| `Shift+Tab` | Previous widget |
| `:` | Command mode (for commands like `:connect`, `:qe`, etc.) |

## Quick Actions

Access via Command Palette (`Ctrl+K`) or Command Mode (`:`) in TUI:

- `:connect` - Connect to provider/agent
- `:connect local` - Open the local provider picker
- `:connect byok` - Open the BYOK provider picker
- `:harness <path>` - Load a HarnessSpec
- `:harness status` - Show the active harness
- `:harness templates` - List built-in harness templates
- `:harness off` - Disable the active harness
- `:runtime list` - Show available runtime backends
- `:runtime <name>` - Switch runtime where available
- `:approve` - Approve a pending tool call
- `:reject` - Reject a pending tool call
- `:log` - Show current output verbosity
- `:log minimal` - Show status-only tool activity
- `:log normal` - Show compact tool summaries
- `:log verbose` - Show full tool outputs and changed file names
- `:qe <role>` - Switch to validation role mode (e.g., `:qe security_tester`)
- `:view <file>` - View file content
- `:help` - Show all available commands

Tool and file-change output is collapsed by default so normal coding sessions stay readable. Agent thinking/session notes are also hidden by default. Use `Ctrl+T` when you want to see thinking logs, and use `:log verbose` before a task when you want full successful tool output, raw ACP agent session logs, and file names in the session report.

## Prompt Input

The top prompt is a wrapped multiline input. Long prompts expand the prompt box up to a fixed height and then scroll internally, so pasted tasks remain visible instead of being cut off. Press `Enter` to submit the current prompt.

## Tool Activity Display

The TUI shows compact tool rows by default. Successful tools appear as compact action rows while failures remain visible with their error summary. Examples:

```text
read_file(pyproject.toml)
grep("provider", src)
bash("uv run pytest tests")
python_repl(2 lines: "x = 1")
```

This keeps the main response readable while still showing what the agent did. Errors remain visible in normal mode. Use `:log verbose` when you need full successful tool output, and `Ctrl+T` when you need agent thinking/session notes.

## Provider and Model Selection

Use `:connect` to choose between ACP agents, BYOK providers, and local model servers.

```text
:connect
:connect byok
:connect local
```

The BYOK model view includes capability labels:

| Label | Meaning |
|-------|---------|
| tools | Model supports tool calling |
| vision | Model can accept image inputs |
| reasoning | Model exposes reasoning capability |
| coding | Model is marked as code-optimized |
| ctx | Context window |
| price | Price per 1M tokens where known |

Local providers include DS4, Ollama, LM Studio, MLX, vLLM, and SGLang when supported by the current installation.

Note: validation analysis sessions are run via CLI, not TUI commands. Use `superqode qe run .` in your terminal to start validation sessions.

## Harnesses In The TUI

Harness specs make TUI sessions repeatable. A harness controls runtime, model policy, tools, sandbox behavior, approvals, event storage, and output handling.

Create and check a harness before loading it:

```bash
superqode harness init my-coder --template coding --output harness.yaml
superqode harness doctor --spec harness.yaml
```

Load it in the TUI:

```text
:harness harness.yaml
```

Use a no-tool harness for planning or architecture review without file, shell, or repository tools:

```bash
superqode harness init planner --template no-tool --output planner.yaml
superqode --harness planner.yaml
```

## Approvals

When the active policy requires approval, the TUI shows the pending operation before it runs.

```text
:approve
:approve 1 always
:reject
:reject 1 "use a safer command"
```

Use `always` only when you want to allow matching requests for the rest of the session.

## Configuration

TUI configuration in `superqode.yaml`:

```yaml
superqode:
  tui:
    sidebar_width: 30
    show_line_numbers: true
    syntax_highlighting: true
```

## Widgets

### Available Widgets

| Widget | Purpose |
|--------|---------|
| `Prompt` | User input with completion |
| `FileBrowser` | Navigate project files |
| `AgentSwitcher` | Switch validation roles |
| `CommandPalette` | Quick actions |
| `StatusBar` | Session status |
| `Throbber` | Loading indicator |
| `Toast` | Notifications |
| `DiffView` | Show file diffs |
| `FileViewer` | View files with syntax highlighting |

### Example Usage

```python
from superqode.widgets import FileBrowser, AgentSwitcher

# File browser
browser = FileBrowser(root=project_root)
file = await browser.select_file()

# Agent switcher
roles = [
    ("qe.security_tester", "Security Testing"),
    ("qe.performance_tester", "Performance Testing"),
]
switcher = AgentSwitcher(roles)
selected = await switcher.select()
```

## Integration with validation

The TUI allows you to interact with agents in validation roles, while validation analysis sessions are run separately via CLI:

```bash
# Start TUI
superqode

# In TUI, switch to validation role
:qe security_tester

# Run validation analysis via CLI (in separate terminal)
superqode qe run . --mode quick
superqode qe run . --mode deep

# View validation artifacts (via CLI)
superqode qe artifacts .
superqode qe dashboard
```

## Requirements

The TUI requires:

```bash
pip install superqode[tui]
# or
pip install textual rich
```

## Troubleshooting

### TUI Not Starting

If the TUI fails to start:

1. **Check Textual installation:**
   ```bash
   python -c "import textual; print('Textual OK')"
   ```

2. **Verify terminal compatibility:**
   - Terminal must support ANSI escape codes
   - Recommended: iTerm2, Alacritty, Windows Terminal

3. **Check terminal size:**
   - Minimum: 80x24
   - Recommended: 120x40

### Performance Issues

For slow TUI performance:

1. **Reduce terminal size**
2. **Disable syntax highlighting**
3. **Use quick mode instead of deep mode**
