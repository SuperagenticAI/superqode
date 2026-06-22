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
- **Agent Switcher**: Switch between agents
- **Command Palette**: Quick actions
- **Status Bar**: Session status at a glance

## Launching the TUI

```bash
# Start TUI mode
superqode

# Start with a harness spec
superqode --harness harness.yaml

```

## Common TUI Workflow

Use this flow for a normal coding session:

1. Launch from the project root.
2. For local coding, run `:local init` to generate `superqode.local.yaml` and a readiness report.
3. Connect a provider, ACP agent, or local model with `:connect`.
4. Load a harness with `:harness superqode.local.yaml` when you want portable policy.
5. Type a focused prompt and press `Enter`.
6. Approve or reject pending tool calls.
7. Ask for a summary of changed files and tests.

Example:

```text
:connect
:local init
:harness superqode.local.yaml
:status
Summarize this repository and suggest the smallest safe improvement.
Find one low-risk cleanup, make the smallest fix, and run the narrowest useful test.
:approve
Summarize what changed.
```

## TUI Layout

```text
┌─────────────────────────────────────────────────────────────────┐
│ SuperQode - Session: session-20260108-143052                  ×│
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
| `Ctrl+A` | Switch agent |
| `Ctrl+S` | Save session |
| `Ctrl+Q` | Quit |
| `Ctrl+T` | Toggle agent thinking/session logs |
| `Ctrl+R` | Open the rewind / transcript overlay |
| `Escape` `Escape` | Rewind the conversation (when the prompt is empty) |
| `Escape` | Close modal/cancel |
| `Enter` | Submit input |
| `@` | Open the file-mention picker in the prompt |
| `Tab` | Accept completion / next widget |
| `Shift+Tab` | Previous widget |

## Quick Actions

Access via Command Palette (`Ctrl+K`) or Command Mode (`:`) in TUI:

- `:connect` - Connect to provider/agent
- `:connect local` - Open the local provider picker
- `:connect byok` - Open the BYOK provider picker
- `:local setup <name>` - TUI-first guide for model download, serving, context, harness, and smoke
- `:local init` - Generate `superqode.local.yaml` and run local readiness checks
- `:local airplane prepare` - Create a strict no-network local harness
- `:local airplane smoke` - Verify offline harness and local search readiness
- `:local smoke` - Run non-destructive local coding readiness checks
- `:local search <name>` - Find a model + how to get it on every engine (size + fit)
- `:hub` - Model-search mode: just type a model name (off by default)
- `:local labs` - Browse trusted models.dev Labs recommendations
- `:local warm <engine>` - Warm a local model and show first-token latency
- `:chat` - Raw direct-to-model chat: no repo/tools, shows TTFT + tok/s (off by default)
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
- `:view <file>` - View file content
- `:rewind` - Open the rewind overlay (or `:rewind <n>` to jump directly)
- `:tree` - Show saved session branches and forks
- `:theme` - Open the theme picker (or `:theme <name>` to apply one)
- `:export html|markdown|json` - Export the current transcript
- `:share` - Create, import, list, or revoke portable session artifacts
- `:trust` - Show or change local trust for this project
- `:plugins` - List, validate, install, enable, or disable plugins
- `:codex` - Connect to and manage the Codex SDK runtime
- `:claude` - Connect to and manage the Claude Agent SDK runtime
- `:antigravity` - Show Antigravity CLI handoff, status, and migration help
- `:plan <task>` - Ask for a plan only, without native tool execution
- `:plan approve` - Execute the last planned request with tools enabled
- `:plan edit [task]` - Edit the pending planned request before execution
- `:plan reject` - Clear the pending planned request
- `:compare <models>` - Re-run your last message across several models side by side
- `:context` - Show, pin, or re-detect the model's loaded context window
- `:thinking` - Cycle thinking-log verbosity (also `Ctrl+T`)
- `:queue clear` - Clear queued type-ahead messages
- `:workspace add|remove|list` - Register extra repositories for cross-repo search
- `:memory` - Search, remember, and inspect project memory providers
- `:sandbox` - Show or set the local command sandbox mode
- `:help` - Show all available commands

Tool and file-change output is collapsed by default so normal coding sessions stay readable. Agent thinking/session notes are also hidden by default. Use `Ctrl+T` when you want to see thinking logs, and use `:log verbose` before a task when you want full successful tool output, raw ACP agent session logs, and file names in the session report.

## Plan Mode, TODOs, and Questions

Plan mode gives you a review step before native tools run:

```text
:plan fix the failing tests     # planning only
:plan                           # show current plan
:plan approve                   # run the planned request
:plan edit adjust the request   # replace the pending request
:plan reject                    # discard it
:plan on                        # make future prompts planning-only
:plan off                       # return to normal execution
```

For BYOK/local SuperQode AgentLoop sessions, plan mode is enforced in two layers: tool schemas are not sent to the model, and any unexpected tool call is denied before execution. For vendor-owned SDK runtimes, SuperQode also denies approval prompts during plan mode, but tools that a vendor runtime can run without asking still depend on that runtime's own plan/no-tool controls.

Native `todo_write` updates and runtime-native plan events feed the same pinned plan panel and `:plan` view. Codex SDK `turn/plan/updated` / `todo_list` events and Claude Agent SDK `TodoWrite` tool calls are normalized into SuperQode's shared `plan_update` event. This keeps SuperQode's own tools and vendor agent runtimes aligned in one planning surface.

Antigravity CLI is currently an external interactive `agy` handoff in SuperQode, not a structured runtime. It will use the same `plan_update` path when Google exposes a documented ACP/headless event stream.

When an agent needs clarification it can use the `ask_user` tool. The TUI renders an inline question card above the prompt, and your next submitted message answers that question instead of starting a new task. Choice questions accept the option number or option text; empty input uses the default when one is provided.

## Typing While The Agent Works

You do not have to wait for a run to finish before typing.

On builtin connections (local models and BYOK providers), a message submitted mid-run is **steered into the current run**: it lands between the agent's tool calls and shapes the work in progress. The log confirms delivery with `steering the current run`. This is the fastest way to correct course ("skip the docs, focus on the failing test") without cancelling anything.

On connections that cannot be steered (ACP agents, vendor SDK runtimes) and during selection or question flows, messages go to the **type-ahead queue** instead. The queue renders under the prompt with a live preview and sends automatically when the agent is free. `:queue clear` empties it.

## Prompt Input

The top prompt is a wrapped multiline input. Long prompts expand the prompt box up to a fixed height and then scroll internally, so pasted tasks remain visible instead of being cut off. Press `Enter` to submit the current prompt.

### File mentions (`@`)

Type `@` in the prompt to open a fuzzy file picker. As you keep typing it filters
the workspace; selecting a directory (ending in `/`) drills into it. Accepted
mentions become `@path/to/file` references, and the referenced file contents are
included with your message when you submit.

```text
> Explain the bug in @src/superqode/agent/loop.py
> Compare @tests/test_tui_smoke.py with @src/superqode/app_main.py
```

### Streaming markdown

Assistant responses render as **live, formatted markdown** while they stream -
paragraphs, headings, lists, and code blocks appear as they complete. Partially
written paragraphs and unterminated code fences are held back so you never see
broken formatting mid-stream.

## Rewind & Transcript Overlay

Press `Ctrl+R` (or double-tap `Escape` with an empty prompt) to open the rewind
overlay. It shows the full conversation transcript and a list of your earlier
messages. Selecting one **rewinds the conversation to that point**: the agent's
stored history is truncated so it forgets everything after that message, and the
message is loaded back into the prompt for you to edit and resend.

```text
:rewind          # open the overlay
:rewind 3        # rewind directly to your 3rd message
:rewind last     # rewind to your most recent message
```

Use this to retry a turn with a better prompt without starting a new session.

## Themes

SuperQode ships several accent themes on top of its dark identity. Open the
picker with `:theme`, or apply one directly with `:theme <name>`:

```text
:theme            # open the picker with live swatch previews
:theme tokyonight
:theme dracula
```

The choice is saved to `~/.superqode/config.json` and applied on the next launch.

## Export

Save the current conversation to HTML, Markdown, or JSON:

```text
:export                         # writes .superqode/exports/transcript-<timestamp>.html
:export html ~/notes/session    # writes ~/notes/session.html
:export markdown ~/notes/session.md
:export json ~/notes/session.json
```

HTML keeps styled markdown. Markdown is good for issue trackers and pull request
notes. JSON is structured for automation and handoff.

## Sessions And Sharing

Use session commands when you want to inspect, branch, or hand off work:

```text
:tree
:session
:session rename <name>
:resume <id>
:fork <new-id>
:share
:share create [session] [path]
:share export [session] [path] [--json|--markdown]
:share import <artifact.superqode-share.json> [new-session-id]
:share list
:share revoke <artifact>
```

Share artifacts are local/offline `superqode-share-v1` JSON files. They are
intended for moving a session between machines or teammates without requiring a
hosted service.

## Project Trust And Plugins

Project trust protects local executable surfaces such as project plugins and MCP
configuration. Trust is stored outside the repository in `~/.superqode/trust.json`.

```text
:trust
:trust status
:trust doctor
:trust yes
:trust no
:plugins
:plugins doctor
:plugins add <local-plugin-dir|plugin.json>
:plugins enable <id>
:plugins disable <id>
```

`:plugins add` and `:plugins enable` require `:trust yes`.

## Runtime-Specific Commands

Codex SDK:

```text
:codex
:codex status
:codex models
:codex model
:codex effort
:codex sandbox
:codex review
:codex compact
:codex thread
:codex sessions
:codex resume <thread-id>
:codex fork <thread-id>
:codex rename <name>
:codex archive <thread-id>
:codex account
:codex logout
```

Claude Agent SDK:

```text
:claude
:claude status
:claude model
:claude permission
:claude sessions
:claude resume <session-id>
:claude rename <name>
:claude tag <tag>
:claude commands
:claude command <name> [args]
:claude review
```

Antigravity CLI handoff:

```text
:antigravity
:antigravity status
:antigravity migrate
:agy status
```

## Optional Vim Helpers

Vim mode is optional. It adds familiar command aliases without removing the
normal SuperQode command surface:

```text
:vim
:vim on
:vim off
:set vim
:set novim
:w [path]
:e <file>
:ls
:grep <term>
q:
@:
```

## Compare Models

Re-run your **last message** across several models or runtimes at once and read
the answers side by side. Each target runs a read-only chat completion
concurrently, so this is safe to fan out - and because SuperQode is multi-runtime,
you can mix providers in one comparison.

```text
:compare openai/<openai-model> anthropic/<anthropic-balanced-model>
:compare <openai-model> <openai-fast-model>     # bare model names use the connected provider
```

## Command Sandbox

`:sandbox` shows the active local command sandbox (mode, backend, and whether it
is currently confining commands). Switch modes for the session with
`:sandbox <mode>`:

```text
:sandbox                   # show status
:sandbox workspace-write   # confine writes to the workspace
:sandbox read-only         # no writes outside temp, no network
:sandbox off               # disable
```

See [Safety & Permissions](safety-permissions.md) for what each mode enforces.

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
| `AgentSwitcher` | Switch between agents |
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
switcher = AgentSwitcher()
selected = await switcher.select()
```

## Integration with Harness Workflows

The TUI allows you to interact with agents for coding tasks, while harness-based workflows are run separately via CLI:

```bash
# Start TUI
superqode

# Run harness task via CLI (in separate terminal)
superqode harness run --spec harness.yaml --prompt "analyze this codebase"
```

## Requirements

The TUI requires:

```bash
uv tool install "superqode[tui]"
# or
uv pip install textual rich
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
