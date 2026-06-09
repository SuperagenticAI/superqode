# Developer Workflows

Use this page when you want SuperQode to become your main coding-agent harness
or sit beside OpenCode, Pi, fast-agent, Codex CLI, Claude Code, Antigravity, and
other local tools.

The practical path is:

1. Connect the runtime or agent you already use.
2. Keep sessions readable, forkable, exportable, and portable.
3. Put local plugins and MCP behind project trust.
4. Move repeatable work into SuperQode harness specs over time.

## Start From The TUI

```bash
superqode --tui
```

Connection commands:

```text
:connect
:connect codex        # Codex SDK using your local Codex login
:connect claude       # Claude Code through ACP
:connect antigravity  # local Antigravity CLI handoff
:connect acp          # any configured ACP agent
:connect byok         # direct hosted provider/API key
:connect local        # Ollama, LM Studio, MLX, vLLM, SGLang, TGI, DS4
```

Optional Vim helpers:

```text
:vim on
:w
:e <file>
:ls
:grep <term>
q:
@:
```

## Sessions, Branches, And Export

In the TUI:

```text
:tree
:session
:session rename <name>
:resume <id>
:fork <new-id>
:export html
:export markdown
:export json
```

From the CLI:

```bash
superqode sessions list
superqode sessions tree
superqode sessions show <session-id>
superqode sessions export <session-id> --format markdown --output session.md
superqode sessions export <session-id> --format json --output session.json
```

## Portable Session Handoff

SuperQode supports local/offline share artifacts today. They are plain JSON
files using the `superqode-share-v1` format.

In the TUI:

```text
:share
:share create [session] [path]
:share export [session] [path] [--json|--markdown]
:share import <artifact.superqode-share.json> [new-session-id]
:share list
:share revoke <artifact>
```

From the CLI:

```bash
superqode share create <session-id>
superqode share export <session-id> --format markdown -o session.md
superqode share export <session-id> --format json -o session.json
superqode share list --json
superqode share import <artifact.superqode-share.json> --session-id imported-session
superqode share revoke <artifact>
```

Use `:tree` or `superqode sessions tree` to inspect fork lineage before sharing.

See [Session Commands](cli-reference/sessions-commands.md) and [Share Commands](cli-reference/share-commands.md) for the full API.

## Project Trust

Trust gates plugins and MCP operations. Check status with `:trust status` or `superqode trust status`. Grant trust with `:trust yes` or `superqode trust yes`. Validate the trust store and risk signals with `:trust doctor` or `superqode trust doctor`.

See [Trust Commands](cli-reference/trust-commands.md) for details.

## Local Plugin Workflow

Project plugins live under `.superqode/plugins/<id>/plugin.json`. Install with `:plugins add <path>` or `superqode plugins add <path>`. Requires project trust. Validate manifests and references with `:plugins doctor` or `superqode plugins doctor`.

See [Plugin Commands](cli-reference/plugins-commands.md) for the manifest format, hook points, and full CLI reference.

## Agent Memory Workflow

Store project facts and preferences with `:memory remember "text"` or `superqode memory remember "text"`. Search with `:memory search query` or `superqode memory search query`, and search Agent Experience Packs with `:memory search specmem query`.

See [Memory Commands](cli-reference/memory-commands.md) and [Agent Memory Layer](advanced/memory.md) for provider setup and the full API.

## Runtime-Specific TUI Commands

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

## Headless Coding Tasks

One-shot coding task:

```bash
superqode --print "fix the failing test and summarize the change"
```

Use a vendor/runtime path:

```bash
superqode --runtime codex-sdk --print "review this repo"
superqode --connect claude --print "summarize the last change"
```

Run with a portable harness spec:

```bash
superqode harness run --spec harness.yaml --prompt "implement the smallest safe fix"
superqode harness doctor --spec harness.yaml
```

## What SuperQode Adds

- One portable harness contract across local, BYOK, ACP, and SDK runtimes.
- Session tree, fork, import, export, and local share artifacts.
- Project trust before enabling project-local plugins/MCP.
- MCP diagnostics and attachable MCP resources.
- Optional Vim-style TUI commands without forcing Vim mode.
- Local-model UX with tool-support detection and provider smoke tests.
