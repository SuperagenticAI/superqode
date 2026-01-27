<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Terminal User Interface (TUI)

SuperQode includes a rich Terminal User Interface (TUI) for interactive QE sessions.

## Features

- **Rich Output**: Colored, formatted terminal output
- **Progress Tracking**: Real-time progress indicators
- **Interactive Prompts**: User input with completion
- **File Browser**: Navigate project files
- **Agent Switcher**: Switch between QE roles
- **Command Palette**: Quick actions
- **Status Bar**: Session status at a glance

## Launching the TUI

```bash
# Start TUI mode
superqode

# Start with specific role
superqode --role qe.security_tester
```

## TUI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ SuperQode - QE Session: qe-20260108-143052                  ×│
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
| `Escape` | Close modal/cancel |
| `Enter` | Submit input |
| `Tab` | Next widget |
| `Shift+Tab` | Previous widget |
| `:` | Command mode (for commands like `:connect`, `:qe`, etc.) |

## Quick Actions

Access via Command Palette (`Ctrl+K`) or Command Mode (`:`) in TUI:

- `:connect` - Connect to provider/agent
- `:qe <role>` - Switch to QE role mode (e.g., `:qe security_tester`)
- `:view <file>` - View file content
- `:help` - Show all available commands

Note: QE analysis sessions are run via CLI, not TUI commands. Use `superqe run .` in your terminal to start QE sessions.

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
| `AgentSwitcher` | Switch QE roles |
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

## Integration with QE

The TUI allows you to interact with agents in QE roles, while QE analysis sessions are run separately via CLI:

```bash
# Start TUI
superqode

# In TUI, switch to QE role
:qe security_tester

# Run QE analysis via CLI (in separate terminal)
superqe run . --mode quick
superqe run . --mode deep

# View QE artifacts (via CLI)
superqe artifacts .
superqe dashboard
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
