# Developer experience verification: 11 October 2026

The baseline was SuperQode 2.13.0 at `4eed5b33`. The upstream sidebar
cleanup at `d539875a` is included. The improvements below are included
in SuperQode 2.14.0.

## Implemented improvements

| Area | Result |
| --- | --- |
| Command consistency | One registry supplies implemented command routes, completion metadata, help and palette descriptions. `:help <command>` exposes nested actions. The canonical `:sidebar` remains available after the upstream alias cleanup. |
| Approval policy | `:approval ask\|auto\|deny` controls host approval policy. `:mode` remains Chat/Build/Plan; `:approvals` opens pending requests. The header shows ASK/AUTO/DENY, and policy changes clear a previous blanket grant. Supported headless runtimes enforce explicit choices; unsupported modes stop before a task. |
| Automation output | `--mode json` reserves stdout for a result or setup error. `--mode jsonl` emits ordered lifecycle, progress and tool events, followed by a result or error. Dependency output goes to redacted stderr; public provider errors exclude raw SDK request payloads. |
| Model defaults | Explicit choices retain precedence. Implicit native defaults use configured credentials or an installed local model. No credential-free OpenAI default is fabricated. Doctor uses the same resolver and distinguishes configuration readiness from successful inference. |
| Startup | Lazy imports keep the agent loop, UI and HTTP SDK out of root help/version. The unconditional 500 ms launch delay is removed. |
| Continuation | `--continue` restores the latest usable session in the current project, including its saved provider, model, harness, runtime and billing route. Archived and empty sessions are excluded. Non-streaming native replies are retained. Headless native and Codex forks preserve the source; other backends require their own fork command. |
| Compaction | `:compact <instructions>` summarizes earlier turns immediately, keeps the latest turn, persists the summary for resumed native sessions, and retains the complete transcript. Failed summaries do not replace stored history. |
| Keyboard discovery | `:hotkeys` searches actual binding actions and scopes. Scoped overrides cover application, composer and modal declarations, with conflict and unknown-action warnings. Ctrl+T toggles logs; Ctrl+D remains contextual Vim page navigation. Palette shortcuts reflect overrides. |
| Project prompts | Trusted `.superqode/commands/*.md` files add commands with literal argument substitution. Optional tool allowlists narrow existing permissions before remembered grants and hooks. Files cannot replace built-ins, aliases, approval policy, runtime or sandbox settings. Cancellation restores the command scope. |
| Diagnostics | `--debug` and `--log-file` create a local log with environment and stored credential redaction, POSIX owner-only permissions and Python 3.12-compatible Windows handling. Doctor reports configuration, dependencies, Python, local tools, terminal metadata, and SSH/tmux notes. |
| File recovery | Undo/redo preserve Git's index, commits and prior edits. They restore creation, deletion and binary changes, refuse subsequent edits before mutating any file, persist redo across restarts, and guard storage failures. Retention is bounded. |
| Conversation recovery | Rewind first saves the original conversation as a recovery branch. A failed stored rewind leaves the transcript, draft and cursor intact. The notification identifies the recovery session. |

JSONL is a lifecycle stream, not a token-delta stream. Tool arguments, tool
results and internal reasoning are omitted from its progress records. Vendor
runtimes that expose only a final answer cannot provide native per-tool events.
External harnesses retain their own model selection, context commands and
approval policy; host status does not claim to describe every vendor setting.

Declared keybinding actions are customizable. Fixed text editing and contextual
navigation gestures remain alongside them; this does not claim that every
terminal-generated key sequence can be remapped.

## Existing strengths retained

Workspace theme preview, Escape restoration, favorites/recent themes,
automatic light/dark pairs, customization, appearance settings, `:trial`,
and reviewed local diagnostic export were already implemented in 2.13.0.
Status rendering already included harness, context usage and cost when the
adapter supplies those values and the terminal has space.

These changes retain approval and project-trust protections. They do not adopt
unrestricted global execution or automatic public conversation sharing.

## Startup measurements

Seven fresh `.venv/bin/superqode` processes per flag, with captured output
and closed stdin, produced these medians on the same machine:

| Invocation | Initial baseline | Current checkout |
| --- | --- | --- |
| `--version` | 438.8 ms | 61.0 ms |
| `--help` | 435.5 ms | 61.1 ms |

Filesystem caches were not flushed. This is a local repeatability check,
not a controlled ranking against other agents or operating systems.
Removing the launch delay does not establish a measured TUI readiness time.

## Validation

Fresh subprocesses using an intentionally unknown provider now produce
parseable JSON and JSONL, return exit status 1, and keep library diagnostics
on stderr. No successful inference was requested by that check.

Offline real-PTY checks passed with `xterm-256color` at 80x24 and
`screen-256color` at 120x40. Each profile exercised 42 checks including
fragmented terminal palette reports, light/dark workspace preview, multiline
paste, Escape, focus, resize, reviewed export and the guided first-task panel.
Native clipboard writes were disabled. These TERM profiles do not simulate
an actual tmux server or SSH connection.

Local loopback tests validate Codex listener attachment/detachment and MCP
OAuth callback state handling. Runtime tests use scripted model responses
for tool events, approvals, cancellation, compaction and recovery.

The broad regression run passed 6,358 tests with 32 skips and 24 integration
tests deselected. A separate loopback run passed 66 tests. Follow-up CLI and
runtime checks passed 298 tests with three skips; the final recovery and
workspace follow-up passed 88 tests. These follow-ups include the later
headless approval, native fork, saved-reply and per-file undo fixes.
Ruff, formatting, public documentation style and diff whitespace checks pass.

Authenticated Codex checks also passed in empty temporary Git projects:
a no-tool READY reply; a file task that wrote exactly the requested content;
`--continue` reading that file; and a native fork with recorded lineage and
an unchanged source transcript. Every run produced ordered, parseable JSONL
and no stderr output. AUTO was chosen explicitly for the file task and its
continuation; it was not persisted as a global permission grant.

Successful inference with every other provider, all external harness policies,
Windows Terminal, and live SSH/tmux behavior
remain separate environment-dependent acceptance checks. No live tmux
executable is installed on this validation machine.

## Comparison qualifications

Feature presence does not establish the broadest protocol support or strongest
governance across all peers. Structured output is also available in
[OpenCode's SDK](https://docs.opencode.ai/docs/sdk/#structured-output), and
[OpenCode's documented sharing default is manual](https://docs.opencode.ai/docs/config/#sharing).
Pi's [JSON stream documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/json.md)
provides a useful reference for event framing. The complementary
[upstream review](upstream-tui-delta-2026-10-11.md) records pinned releases,
theme interoperability and further optional design ideas.
