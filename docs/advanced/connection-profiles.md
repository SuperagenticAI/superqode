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

### 7. Grok Subscription (connector: acp, agent: grok)

Runs **Grok Build**, xAI's own coding agent, on an eligible SuperGrok or X Premium+ account. This matches the Codex and Claude subscription profiles: the vendor's agent owns the loop. Requires the `grok` binary on PATH and a local `grok login` (`~/.grok/auth.json`). SuperQode starts `grok agent stdio` over ACP.

To run **SuperQode's own harness** on the same subscription instead, use `:grok api [model]`. That imports the CLI session token into SuperQode's auth store and routes through the `grok-cli` provider (CLI chat proxy), so `core`/`workbench` and SuperQode's tools drive Grok 4.5.

## TUI Usage

In the TUI, use `:connect` to open the type picker. Each profile shows availability status (green "ready" or yellow "needs setup" with guidance). Navigate with arrows or number keys.

Direct shortcuts:

- `:connect codex` - connect Codex SDK directly
- `:connect claude` - connect Claude Agent SDK directly
- `:connect antigravity` - show agy handoff
- `:connect grok` - Grok Build, xAI's own coding agent, on your subscription (ACP)
- `:grok api [model]` - SuperQode's harness on the same subscription (opt-in)
- `:connect byok` - open the cloud provider picker
- `:connect byok <provider>/<model>` - connect to a cloud model directly
- `:connect <model>` - connect by model name alone (e.g. `:connect gpt-5.6`); the provider is resolved from the catalog, preferring first-party providers over gateway mirrors
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
- Grok subscription (`:connect grok`) -> Grok Build ACP subprocess (`grok agent stdio`)
- Grok via SuperQode harness (`:grok api`) -> `grok-cli` provider + CLI session token
- Advanced -> user picks runtime

When --connect implies a runtime, it sets SUPERQODE_RUNTIME but does not override an explicit --runtime flag.
