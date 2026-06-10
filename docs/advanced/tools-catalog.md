# Tools Catalog

Every builtin tool the agent can use, what it's for, and the guarantees behind it. Tools are plain Python classes (`superqode/tools/`) with a name, description, JSON-Schema parameters, and an async `execute` — see [Plugin Authoring](plugin-authoring.md) to add your own.

Profiles select which tools a session gets: `coding` (the lean default), `full` (everything), `standard` (no network/agents), `ds4` (minimal schema surface for fast local calling), `none`. Pick one with `SUPERQODE_TOOL_PROFILE` or per-harness via `tools.profile`.

## Files

| Tool | What it does |
|---|---|
| `read_file` | Bounded, line-numbered reads: up to 2000 lines / 50KB per call, `N: ` prefixes, overlong lines clamped, binary/image files rejected with a clear message, and an explicit "continue with `start_line=…`" hint when there's more. Accepts `file_path`/`offset`/`limit` aliases that models trained on other harnesses emit. |
| `write_file`, `create_file` | Create or replace files (workspace-tracked when a tracking session is active). |
| `list_directory` | Directory listing. |
| `view_image` | Attach a local png/jpg/gif/webp to the conversation for vision-capable models (Gemma 4 multimodal, hosted vision models). The image rides as a standard `image_url` part; old attachments are pruned pixels-first when context gets tight. 4MB limit. |

## Editing — three dialects, models use what they know

| Tool | Format |
|---|---|
| `edit_file` | String replacement with a 10-strategy fallback ladder (exact → line-trimmed → block-anchor → whitespace-normalized → indentation-flexible → escape-normalized → trimmed-boundary → context-aware → line-number-stripped → multi-occurrence). Rejects edits to files modified externally since the last read. |
| `patch` | Standard unified diffs (`git diff` format) with configurable context fuzz. |
| `apply_patch` | The codex `*** Begin Patch` envelope that GPT-5.x and local gpt-oss models emit natively: Add/Delete/Update File, `*** Move to:` renames, `@@` locators, end-of-file anchors. Multi-file patches validate **fully before any write** — a failed hunk in file 3 leaves files 1–2 untouched. Bash invocations of `apply_patch <<'EOF' …` heredocs are intercepted and routed here automatically. |
| `insert_text`, `multi_edit` | Line-targeted insert; several replacements in one call. |

All edit paths share the same post-edit verification: fast per-file diagnostics (ruff/py_compile, eslint, gofmt, JSON/YAML) run after each change and feed findings back so the model self-corrects (`SUPERQODE_VERIFY_EDITS`, `SUPERQODE_FORMAT_ON_EDIT`).

## Shell

**`bash`** — one-shot commands. Output beyond the model-sized cap is spilled to disk in full and replaced with a head+tail preview plus the spill path (nothing is ever lost to truncation). `run_in_background: true` starts the command as a persistent session and returns its `session_id` immediately. Commands pass through the [exec policy and env policy](policies.md) before running, and through the OS sandbox (Seatbelt/bwrap) when one is active.

**`shell_session`** — persistent interactive processes: REPLs, dev servers, debuggers, anything that prompts on stdin. PTY-backed on POSIX.

```text
action=open   command="python3 -i"        → session_id + initial output
action=write  session_id=… input="2+2"    → new output ("4")
action=poll   session_id=…                → output since last call
action=list                               → all sessions and statuses
action=kill   session_id=…                → terminate
```

Each call waits up to `yield_ms` (default 1500) and returns early once output settles. Buffers cap at 2MB with spill-to-disk on return; sessions are reaped on exit and killed when SuperQode exits — no orphan processes.

## Search

`grep` and `glob` spawn ripgrep directly with structured `--json` output, report truncation honestly, and fan out across every repo registered with `:workspace add`. `code_search` finds symbols (definitions/references); `repo_search` is the cross-repo entry point. All read-only, so multiple searches in one turn run concurrently.

## Web & network

`web_search`, `web_fetch` (HTML→markdown), `fetch`, `download`. Good candidates for [deferred loading](agent-loop.md#4-deferred-tools-and-tool_search) on small-window models.

## Task management & interaction

`todo_write` / `todo_read` (per-session todo list — the loop nudges the model when items go stale), `ask_user` / `confirm` (structured questions through the TUI), `batch` (explicit parallel execution), `compact` (manual context compression).

## Agents

| Tool | Use |
|---|---|
| `sub_agent`, `task_coordinator` | Fire-and-forget delegation: spawn an isolated child for one task, get one result. |
| `spawn_agent`, `send_input`, `wait_agent`, `list_agents`, `close_agent` | **Peer agents** — long-lived, addressable children. See [Multi-Agent](multi-agent.md). |
| `a2a_call`, `a2a_discover` | Call external A2A agents. |

## Meta

| Tool | Use |
|---|---|
| `tool_search` | Discover and activate deferred tools ("fetch a web page" → activates `web_fetch`). Present whenever anything is deferred. |
| `request_permissions` | The model asks *you* for a session-scoped escalation with a justification; approval upgrades the named tools from ask-each-time to allowed. Hard denies are never overridable. See [Policies & Safety](policies.md). |
| `skill`, `read_skill`, `create_skill` | Project skills from `.agents/skills/*.md`. |
| `mcp_*` | MCP server tools, resources, and prompts ([MCP Configuration](../configuration/mcp-config.md)). |
| `lsp`, `diagnostics` | Go-to-definition, references, hover; project diagnostics ([LSP Integration](lsp-integration.md)). |
| `monty_python_repl` | Sandboxed Python interpreter (optional extra). |

## Guarantees that hold across every tool

1. **Order safety.** Only all-read-only batches run concurrently; mutations execute strictly in call order.
2. **Bounded output.** Every result is capped to the model's budget; oversized output spills to disk with a path, never silently discarded.
3. **Argument repair.** Malformed JSON arguments are repaired or rejected with corrective feedback — never executed as `{}`.
4. **Policy gates.** Hooks → exec-policy rules → permission manager, in that order, before anything runs ([order of authority](policies.md#order-of-authority)).
