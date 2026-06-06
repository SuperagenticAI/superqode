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

## Project Trust

Trust is stored outside the repository by default:

```text
~/.superqode/trust.json
```

Trust-sensitive project files:

```text
.superqode/plugins
.agents/plugins
.superqode/mcp.json
.mcp.json
.superqode/hooks.json
```

In the TUI:

```text
:trust
:trust status
:trust doctor
:trust yes
:trust no
```

From the CLI:

```bash
superqode trust status
superqode trust status --json
superqode trust doctor
superqode trust yes
superqode trust no
```

## Local Plugin Workflow

Project plugins live under `.superqode/plugins/<id>/plugin.json`.

In the TUI:

```text
:trust doctor
:trust yes
:plugins
:plugins doctor
:plugins add ./my-plugin
:plugins disable my-plugin
:plugins enable my-plugin
```

From the CLI:

```bash
superqode trust doctor
superqode trust yes
superqode plugins list
superqode plugins list --all --json
superqode plugins doctor
superqode plugins add ./my-plugin
superqode plugins disable my-plugin
superqode plugins enable my-plugin
```

`plugins add` and `plugins enable` require project trust. This prevents a cloned
repository from silently activating project-local plugin or MCP behavior.

## Agent Memory Workflow

Use local memory for explicit project facts, preferences, and procedures:

```text
:memory
:memory providers
:memory remember This repo uses pnpm, never npm
:memory search package manager
:memory forget <id>
:memory export
```

CLI:

```bash
superqode memory status
superqode memory providers
superqode memory remember "Use pnpm in this repo; do not use npm" --kind preference --tag tooling
superqode memory search "package manager"
superqode memory export --provider local -o memory.json
```

If a project has SpecMem, search its Agent Experience Pack:

```text
:memory search specmem checkout flow
```

```bash
superqode memory status --provider specmem
superqode memory search "checkout flow" --provider specmem
```

Vector databases should be treated as storage backends behind providers, not as
the memory API itself.

Optional hosted/graph memory providers are disabled by default. Developers can
enable them per project in `superqode.yaml` while keeping `local` as the default:

```yaml
memory:
  default_provider: local
  providers:
    mem0:
      enabled: true
      api_key_env: MEM0_API_KEY
    cognee:
      enabled: false
    supermemory:
      enabled: false
      api_key_env: SUPERMEMORY_API_KEY
```

Install only the providers you need:

```bash
pip install "superqode[mem0]"
pip install "superqode[supermemory]"
pip install "superqode[memory-providers]"
```

`memory-providers` installs Mem0 and Supermemory. Cognee is configurable, but
Cognee `1.1.2` currently depends on `rich<15`, which conflicts with
SuperQode's `rich>=15`; install/run Cognee separately or expose `cognee-cli`.

See [Agent Memory Layer](advanced/memory.md) for the provider readiness states,
full onboarding flow, and provider-specific setup.

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
