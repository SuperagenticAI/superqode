# Connect Commands

Commands and global flags for connecting to a provider, agent, or runtime.

---

## Overview

SuperQode provides two ways to connect:

- **`--connect` / `-C` global flag** -- set the connection profile on startup.
- **`superqode connect` command group** -- explicit CLI connect commands,
  setup guides, and agent connections.

---

## `--connect` / `-C` Global Flag

Select a connection profile directly from the CLI.

```bash
superqode --connect PROFILE [COMMAND]
superqode -C PROFILE [COMMAND]
```

### Choices

| Profile | Description |
|---------|-------------|
| `codex` | Self-contained. Uses Codex SDK. Auto-sets runtime to `codex-sdk`. Requires `openai_codex` package and `~/.codex/auth.json`. |
| `claude` | Self-contained. Uses Claude Agent SDK. Auto-sets runtime to `claude-agent-sdk`. Requires `claude_agent_sdk` package and `ANTHROPIC_API_KEY`. |
| `antigravity` | Self-contained `agy` runtime using Google Sign-In and the OS keyring. |
| `grok` | Grok Build (xAI's own agent) on your Grok subscription over ACP (`grok agent stdio`). Requires the `grok` binary and `grok login`. To run SuperQode's harness on the same subscription instead, use `:grok api`. |
| `byok` | Bring Your Own Key. Connect to a cloud provider with your own API key. |
| `local` | Connect to a local or self-hosted provider (Ollama, MLX, LM Studio, etc.). |
| `acp` | Connect to an ACP (Agent Client Protocol) coding agent. |

### Self-Contained Profiles

`codex`, `claude`, and `antigravity` are self-contained profiles. They each bundle their own
runtime, so the `runtime` setting is automatically selected:

- `--connect codex` sets runtime to `codex-sdk`
- `--connect claude` sets runtime to `claude-agent-sdk`
- `--connect antigravity` sets runtime to `antigravity-cli`

### Examples

```bash
# Start the TUI connected to Anthropic
superqode --connect byok anthropic <anthropic-model>

# Run a headless task via Codex
superqode --connect codex -p "explain this project"

# Run a headless task via Claude Agent SDK
superqode --connect claude -p "refactor this module"

# Connect to a local model
superqode --connect local ollama qwen3:8b

# Connect to an ACP agent
superqode --connect acp opencode

# Run Antigravity with your existing Google Sign-In
superqode --connect antigravity

# Connect SuperQode harness on your Grok subscription (official CLI login)
superqode --connect grok

# Grok Build as an external ACP agent (same CLI login, different product)
superqode --connect acp grok
```

---

## Connection Profiles

### codex

Uses the Codex SDK as the runtime backend.

| Requirement | Details |
|-------------|---------|
| Python package | `openai_codex` |
| Auth | `~/.codex/auth.json` (managed by the Codex CLI) |
| Runtime | Auto-set to `codex-sdk` |

### claude

Uses the Claude Agent SDK as the runtime backend.

| Requirement | Details |
|-------------|---------|
| Python package | `claude_agent_sdk` |
| Auth | `ANTHROPIC_API_KEY` environment variable |
| Runtime | Auto-set to `claude-agent-sdk` |

### antigravity

Uses the official `agy` CLI in headless print mode. Authentication stays inside
`agy`: run it once to complete Google Sign-In, after which it reads the session
from the OS keyring. SuperQode requires `agy` 1.1.1 or newer. For API keys, use
`:connect byok google` or the optional `antigravity-sdk` advanced runtime.

See [Google Antigravity](../providers/antigravity.md) for the harness ownership
matrix and the supported CLI, SDK, and SuperQode harness routes.

### grok

Runs **Grok Build**, xAI's own coding agent, on your Grok subscription over ACP
(`grok agent stdio`). This matches the Codex and Claude subscription profiles:
the vendor's agent owns the loop.

| Requirement | Details |
|-------------|---------|
| Binary | `grok` on PATH (`curl -fsSL https://x.ai/cli/install.sh \| bash`) |
| Auth | `grok login` (or `grok login --device-auth` on headless hosts); stored by the CLI in `~/.grok/auth.json` |
| Connector | ACP agent `grok` (Grok Build) |

To run **SuperQode's own harness** on the same subscription instead, use
`:grok api [model]`: it imports the CLI session into `~/.superqode/auth.json`
and routes through the `grok-cli` provider (CLI chat proxy). See
[BYOK Providers](../providers/byok.md#grok-subscription-official-cli).

### byok

Bring Your Own Key. Connect to any supported cloud provider using your own API
key. The CLI command requires a provider and model. The TUI `:connect byok`
command can open interactive pickers.

### local

Connect to a local or self-hosted provider (Ollama, MLX, LM Studio, vLLM, DS4,
etc.). The CLI command requires a provider and model. The TUI `:connect local`
command can open interactive pickers.

### acp

Connect to any ACP-compatible coding agent installed on your system. The CLI
command requires an agent name. The TUI `:connect acp` command can open an
interactive picker.

---

## `superqode connect`

The `superqode connect` command group provides subcommands for connecting to
providers, agents, and runtimes, as well as viewing setup guides.

```bash
superqode connect COMMAND [OPTIONS] [ARGS]
```

### Subcommands

| Command | Description |
|---------|-------------|
| `connect acp` | Connect to an ACP coding agent |
| `connect byok` | Connect to a cloud provider |
| `connect local` | Connect to a local provider |
| `connect setup` | Show setup guide for a provider |

---

## connect acp

Connect to an ACP (Agent Client Protocol) coding agent by short name.

```bash
superqode connect acp AGENT [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `AGENT` | Agent short name (e.g., `opencode`) |

### Options

| Option | Description |
|--------|-------------|
| `--project-dir`, `-d` | Project directory for the agent session |

### Examples

```bash
# Connect to OpenCode
superqode connect acp opencode

# Connect with a custom project directory
superqode connect acp opencode --project-dir /path/to/project
superqode connect acp opencode -d /path/to/project
```

### Notes

This command launches a simple CLI interactive session. For the full TUI
experience, run `superqode` and use `:connect acp <agent>` inside the TUI.

---

## connect byok

Connect to a cloud provider using your own API key. Provider and model are
required in the CLI command. Use the TUI `:connect byok` picker when you want
interactive provider and model selection.

```bash
superqode connect byok PROVIDER MODEL
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROVIDER` | Provider ID, for example `anthropic`, `openai`, or `google` |
| `MODEL` | Model ID, for example `<anthropic-balanced-model>` or `<openai-model>` |

### Examples

```bash
# Full inline specification
superqode connect byok anthropic <anthropic-model>

# Hugging Face Inference Provider route
superqode connect byok huggingface zai-org/GLM-5.2:fireworks-ai
superqode connect byok hf.zai-org/GLM-5.2:together

# For interactive selection, use the TUI
superqode
# then type: :connect byok
```

For Hugging Face Inference Providers, `hf.<repo>:<provider>`,
`hf/<repo>:<provider>`, and `huggingface/<repo>:<provider>` are accepted and
normalize to the `huggingface` provider. GLM-5.2 aliases include `glm52`,
`glm52-hf-fireworks`, `glm52-hf-together`, `glm52-hf-novita`,
`glm52-hf-zai`, and `glm52-hf-deepinfra`.

---

## connect local

Connect to a local or self-hosted provider. The CLI command requires both
provider and model. Use the TUI `:connect local` picker when you want
interactive provider and model selection.

```bash
superqode connect local PROVIDER MODEL
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROVIDER` | Local provider ID, for example `ollama`, `lmstudio`, `mlx`, or `ds4` |
| `MODEL` | Model ID |

### Examples

```bash
# Full inline specification
superqode connect local ollama qwen3:8b

# For interactive selection, use the TUI
superqode
# then type: :connect local
```

---

## connect setup

Show a setup guide for any of the 130+ supported providers. Displays required
environment variables, base URL, documentation URL, example models, and the
exact connect command.

```bash
superqode connect setup PROVIDER [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROVIDER` | Provider ID (e.g., `anthropic`, `ollama`, `deepseek`) |

### Options

| Option | Description |
|--------|-------------|
| `--json` | Emit JSON output |

### Examples

```bash
# Show setup guide for Anthropic
superqode connect setup anthropic

# Show setup guide for Ollama
superqode connect setup ollama

# Show setup guide for DeepSeek as JSON
superqode connect setup deepseek --json
```

### Output

```yaml
Provider: Anthropic
Category: US Labs
Tier: Tier 1

Environment Variables:
  ANTHROPIC_API_KEY (required)

Base URL: https://api.anthropic.com
Documentation: https://docs.anthropic.com/

Example Models:
  - <anthropic-model>
  - <anthropic-balanced-model>
  - <anthropic-fast-model>

Connect Command:
  superqode connect byok anthropic <model>
```

---

## Related Commands

- `superqode providers list` - List available providers
- `superqode providers test` - Test provider connection
- `superqode agents list` - List installed ACP agents
- `superqode auth info` - Show authentication status
