# Connection Profiles

Seven connection profiles determine how SuperQode connects to model providers and agent runtimes. Each profile has a connector type, optional runtime, and detect() check.

## Connection Profiles

### 1. ACP Agent (connector: acp-picker)

Opens an interactive picker showing all discovered ACP agents (OpenCode, Claude Code, Gemini CLI, Codex CLI, OpenHands, etc.). Always available. No model auth setup needed.

### 2. BYOK Provider (connector: byok, runtime: builtin)

Brings your own API key. Opens a cloud provider picker, then model selector. Uses builtin runtime. detect() checks for any of 7 API key env vars (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.).

### 3. Local Model (connector: local, runtime: builtin)

Connects to local/self-hosted model servers. Opens a local provider picker (Ollama, MLX, LM Studio, vLLM, SGLang, TGI, DS4). Always available.

### 4. Codex Subscription (connector: runtime, runtime: codex-sdk)

Self-contained: brings its own model and auth via Codex login. Requires openai_codex package and ~/.codex/auth.json. Auto-connects on selection.

### 5. Claude Agent SDK (connector: runtime, runtime: claude-agent-sdk)

Self-contained: uses Anthropic API key directly. Requires claude_agent_sdk package and ANTHROPIC_API_KEY. Auto-connects on selection.

### 6. Antigravity CLI (connector: external-cli)

Handoff profile: shows the command to run `agy` in a terminal. Does not connect SuperQode's own loop. Requires agy binary on PATH.

### 7. Grok Subscription (connector: subscription, provider: grok-cli)

Connects **SuperQode's harness** to an eligible SuperGrok or X Premium+ account. Requires the `grok` binary on PATH and a local `grok login` (`~/.grok/auth.json`). On connect, SuperQode imports the CLI session token into its auth store and routes through the `grok-cli` provider (CLI chat proxy). **Grok Build ACP** remains available under `:connect acp grok` — that path runs xAI's agent, not SuperQode's harness.

## TUI Usage

In the TUI, use `:connect` to open the type picker. Each profile shows availability status (green "ready" or yellow "needs setup" with guidance). Navigate with arrows or number keys.

Direct shortcuts:

- `:connect codex` - connect Codex SDK directly
- `:connect claude` - connect Claude Agent SDK directly
- `:connect antigravity` - show agy handoff
- `:connect grok` - SuperQode harness on Grok subscription (CLI login)
- `:connect acp grok` - Grok Build coding agent via official CLI ACP
- `:connect byok` - open the cloud provider picker
- `:connect byok <provider>/<model>` - connect to a cloud model directly
- `:connect local` - open the local provider picker
- `:connect local <provider>/<model>` - connect to a local model directly
- `:connect acp` - open the ACP agent picker
- `:connect acp <agent>` - connect to an ACP agent directly

Special syntax: `:connect byok -` (previous), `:connect byok !` (history), `:connect byok last` (reconnect).

## CLI Usage

Use `--connect` / `-C` global flag:

```bash
superqode --connect codex --print "review this"
superqode -C claude --print "summarize changes"
superqode --connect grok
```

Use `superqode connect` subcommands:

```bash
superqode connect acp opencode
superqode connect byok anthropic <anthropic-model>
superqode connect local ollama qwen3:8b
superqode connect setup deepseek --json
```

## Runtime Mapping

- Codex profile -> runtime: codex-sdk
- Claude profile -> runtime: claude-agent-sdk
- BYOK/Local -> runtime: builtin
- ACP -> no runtime change (ACP subprocess)
- Antigravity -> handoff (no runtime)
- Grok subscription -> SuperQode harness (`grok-cli` + CLI session token)
- Grok Build agent -> ACP subprocess via `:connect acp grok` (`grok agent stdio`)
- Advanced -> user picks runtime

When --connect implies a runtime, it sets SUPERQODE_RUNTIME but does not override an explicit --runtime flag.
