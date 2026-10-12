# Vim-Like Terminal Navigation

SuperQode provides an optional modal, Vim-like control layer for its terminal user interface. It applies familiar navigation to conversations, commands, searches, connection pickers, and terminal panes. It does not replace Vim or provide a general-purpose text editor.

## Enable Vim Mode

Enable the mode from the TUI:

```text
:vim on
```

The preference is stored in `~/.superqode/config.json` and applies to later sessions. Disable it with:

```text
:vim off
```

For temporary or managed environments, use the environment variable:

```bash
SUPERQODE_VIM_MODE=1 superqode
SUPERQODE_VIM_MODE=0 superqode
```

An explicit environment variable takes precedence over the saved preference.

Use `:vim` to inspect the current state and `:vim tutor` to open the in-product key reference.

## Input Modes

The active Vim input mode is shown in the status bar and in the task prompt border.

| Mode | Purpose | Entry |
| --- | --- | --- |
| `NORMAL` | Navigate the transcript, panes, searches, and pickers | `Escape` from an editable mode |
| `INSERT` | Enter or edit a coding task | `i`, `a`, or `o` from Normal mode |
| `COMMAND` | Enter a SuperQode Ex command | `:` from Normal mode |
| `SEARCH` | Search the current transcript | `/` or `?` from Normal mode |

Submitting a task, command, or search returns the TUI to Normal mode. SuperQode temporarily permits ordinary text entry when an agent question or setup prompt requires a response.

Entering `:`, `/`, or `?` from Normal mode keeps your task draft and its cursor
or selection separately. `Escape` restores them; submitting the command or
search restores them after it runs. Connection and setup fields stay empty for
selection or answers, and your draft returns when you leave setup. Draft
recovery saves the task while the command or search line is open.

In Search mode, `/help` searches for the word `help`; it does not invoke the
`/help` command. Enter commands with `:` or from Insert mode.

## Navigation

### Conversation

| Key | Action |
| --- | --- |
| `j` | Scroll down one line |
| `k` | Scroll up one line |
| `gg` | Jump to the beginning of the transcript |
| `G` | Jump to the end and resume follow mode |
| `Ctrl+U` or `Ctrl+B` | Scroll up by page |
| `Ctrl+D` or `Ctrl+F` | Scroll down by page |
| `/pattern` | Search forward |
| `?pattern` | Search backward |
| `n` | Select the next search match |
| `N` | Select the previous search match |

### Panes and pickers

| Key | Action |
| --- | --- |
| `h` | Open or focus the repository sidebar |
| `l` | Return focus to the main prompt |
| `Ctrl+W h` | Focus the repository sidebar |
| `Ctrl+W l` | Focus the main prompt |
| `Space` | Open the leader menu |
| `j` or `k` | Move through the active connection, model, runtime, session, mode, or harness picker |
| `Enter` | Confirm the highlighted picker item |
| `Escape` | Cancel the active picker or operation according to the current TUI context |

Approval prompts retain priority over modal bindings. When an approval is pending, `y`, `n`, `a`, and `Escape` keep their approval behavior.

### Panels

Vim navigation also works in theme, connection, session, MCP, activity and help
panels. Search boxes and editable text fields retain ordinary typing, including
the letters `j`, `k` and `g`.

| Key | Action in a panel |
| --- | --- |
| `j` / `k` | Select the next/previous list item, scroll a read-only view, or move between controls |
| `gg` / `G` | Jump to the first/last list item or the beginning/end of a read-only view |
| `Ctrl+U` / `Ctrl+D` | Move by page in a list or read-only view |
| `Tab` / `Shift+Tab` | Move between controls |
| `Enter` | Use the panel's existing selection or activation action |
| `Escape` | Use the panel's existing Back or Cancel action |

Panel bindings can be changed under the `app` scope in
`~/.superqode/keybindings.json`, using `panel_vim_down`, `panel_vim_up`,
`panel_vim_top`, `panel_vim_bottom`, `panel_vim_page_up` and
`panel_vim_page_down`. They are active only with Vim enabled and focus outside
an editable field. They do not change connection choices or the `:connect`
workflow.

Vim preferences use a JSON boolean, `"vim_mode": true` or `false`, in
`~/.superqode/config.json`. Invalid configuration is retained. If a setting
cannot be saved, the TUI explains that it applies only to the current session.

## Ex Commands

All SuperQode `:` commands remain available. Vim mode also provides these aliases:

| Command | SuperQode action |
| --- | --- |
| `:w [path]` | Export the current transcript |
| `:e <file>` | View a repository file |
| `:ls` | List saved sessions |
| `:grep <term>` | Search the workspace |
| `:q` | Exit SuperQode |
| `q:` | Show Ex command history |
| `@:` | Repeat the latest Ex command |

These commands use SuperQode objects rather than Vim buffers. For example, `:w` exports session evidence and `:e` opens a repository file in the TUI viewer.

## Scope

The Vim layer is designed for operating coding agents and inspecting their work. It intentionally does not implement:

- Vim text operators such as `d2w`
- Registers or macros
- A Vim buffer model
- Vim plugins or Vimscript
- Exact Vim or Neovim compatibility

With Vim mode enabled, `Ctrl+E` or `:edit external` opens your current task draft in the
editor configured by `$EDITOR`. Editor arguments such as `nvim -f` are supported.
Saving and closing returns the draft to Insert mode for review; press `Enter`
when you want to send it. Markdown headings are preserved, and an editor error
retains the original draft. With Vim mode disabled, the existing external-editor
workflow is unchanged.

The existing `:edit` command and `Ctrl+P` continue to load the previous task for
rewording. `End` moves to the end of a prompt line in either mode.

Use SuperQode as an ACP agent from Neovim when editing inside Neovim is the primary workflow.

## Recommended Product Description

The accurate product description is:

> A terminal-first, Vim-like control surface for coding agents, harnesses, sessions, diffs, and WorkOrders.

This describes the modal navigation layer without presenting SuperQode as a replacement for Vim or Neovim.
