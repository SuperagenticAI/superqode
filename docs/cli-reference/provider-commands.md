# Provider Commands

Commands for managing BYOK (Bring Your Own Key) providers, testing connections, and listing available models.

---

## Overview

The `superqode providers` command group manages provider connections:

```bash
superqode providers COMMAND [OPTIONS] [ARGS]
```

---

## providers list

List available BYOK providers.

```bash
superqode providers list [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--category` | Filter by category: `us`, `china`, `other-labs`, `model-hosts`, `local`, `free` |
| `--tier` | Filter by tier: `1`, `2`, `local` |
| `--configured` | Show only configured providers |

### Examples

```bash
# List all providers
superqode providers list

# List only US lab providers
superqode providers list --category us

# List only configured providers
superqode providers list --configured

# List free tier providers
superqode providers list --category free

# List local providers
superqode providers list --category local
```

### Output

```text
BYOK Providers
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Provider    ┃ Name          ┃ Tier   ┃ Category    ┃ Status           ┃ Env Var               ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━┩
│ anthropic   │ Anthropic     │ Tier 1 │ US Labs     │ [CORRECT] Configured    │ ANTHROPIC_API_KEY     │
│ openai      │ OpenAI        │ Tier 1 │ US Labs     │ [CORRECT] Configured    │ OPENAI_API_KEY        │
│ google      │ Google AI     │ Tier 1 │ US Labs     │ [INCORRECT] Not configured│ GOOGLE_API_KEY        │
│ ollama      │ Ollama        │ Local  │ Local       │  Local         │ (none)                │
└─────────────┴───────────────┴────────┴─────────────┴──────────────────┴───────────────────────┘

Total: 15 providers, 2 configured
```

---

## providers show

Show details for a specific provider.

```bash
superqode providers show PROVIDER_ID
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROVIDER_ID` | Provider identifier (e.g., `anthropic`, `ollama`) |

### Example

```bash
superqode providers show anthropic
```

### Output

```text
╭──────────────────────────────────────────────────────────────╮
│                    Provider: Anthropic                        │
├──────────────────────────────────────────────────────────────┤
│ Provider: Anthropic                                           │
│ ID: anthropic                                                 │
│ Tier: Tier 1 (First-class support)                           │
│ Category: US Labs                                             │
│ Status: [CORRECT] Configured                                         │
│                                                               │
│ Environment Variables:                                        │
│   ✓ ANTHROPIC_API_KEY                                        │
│                                                               │
│ Example Models:                                               │
│   • <anthropic-model>                                          │
│   • <anthropic-balanced-model>                                        │
│   • <anthropic-fast-model>                                         │
│   • <anthropic-balanced-model>                                        │
│                                                               │
│ Documentation: https://docs.anthropic.com/                    │
╰──────────────────────────────────────────────────────────────╯
```

---

## providers test

Test connection to a provider.

```bash
superqode providers test PROVIDER_ID [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROVIDER_ID` | Provider identifier |

### Options

| Option | Description |
|--------|-------------|
| `--model`, `-m` | Model to test with (uses default if not specified) |

### Example

```bash
# Test with default model
superqode providers test anthropic

# Test with specific model
superqode providers test anthropic -m <anthropic-balanced-model>
```

### Output

```text
Testing Anthropic with model <anthropic-balanced-model>...

[CORRECT] Success!
  Provider: anthropic
  Model: <anthropic-balanced-model>
  Tokens used: 15
```

---

## providers doctor

Show provider configuration status and setup hints.

```bash
superqode providers doctor [PROVIDER_ID] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--live` | Run live local-provider health checks |
| `--json` | Emit JSON output |

### Examples

```bash
# Show all provider status
superqode providers doctor

# Show DS4 status with live health checks
superqode providers doctor ds4 --live
```

---

## providers scan-free

Scan free-tier, starter-credit, ACP, local, and live zero-price model routes.

```bash
superqode providers scan-free [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--live` | Query live model/pricing catalogs instead of only curated fallback hints |
| `--source` | Live source to query: `openrouter`, `models-dev`, or `litellm`; repeatable |
| `--provider` | Filter by provider id, model id, or provider name |
| `--access` | Filter by access path: `api-key`, `account`, `acp`, `local`, or `routed` |
| `--kind` | Filter curated fallback offers by type |
| `--configured` | Only show no-key or already configured fallback offers |
| `--limit` | Maximum live rows |
| `--json` | Emit JSON output for TUI/store integrations |

### Examples

```bash
# Curated setup hints for free/local inference paths
superqode providers scan-free

# Real-time zero-price model routes from OpenRouter
superqode providers scan-free --live --source openrouter --limit 20

# Merge live signals from all supported sources
superqode providers scan-free --live --json

# TUI equivalent
:providers free
:providers free --live openrouter
```

### Live Sources

| Source | What it contributes |
|--------|---------------------|
| `openrouter` | Live model ids, zero-price routes, context, tool parameter support |
| `models-dev` | Cached broad provider/model/pricing catalog from `models.dev` |
| `litellm` | LiteLLM public pricing/context registry |

Signup credits and remaining account balance are provider-account state. SuperQode treats them as curated metadata unless a provider exposes a stable authenticated billing or entitlement API.

---

## providers guide

Show setup guidance and model quality labels for one provider or all providers.

```bash
superqode providers guide [PROVIDER_ID] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--json` | Emit JSON output |

### Examples

```bash
superqode providers guide
superqode providers guide ds4
superqode providers guide anthropic
```

---

## providers models

List example models for a provider.

```bash
superqode providers models PROVIDER_ID [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--json` | Emit JSON output |

### Examples

```bash
superqode providers models ds4
superqode providers models anthropic
```

---

## providers recommend

Recommend models for a task with cost, context, and tool-support labels.

```bash
superqode providers recommend [TASK] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--limit` | Maximum recommendations |
| `--json` | Emit JSON output |

### Examples

```bash
superqode providers recommend coding
superqode providers recommend local --limit 5
superqode providers recommend reasoning --json
```

---

## providers smoke

Run an opt-in local provider smoke check.

```bash
superqode providers smoke PROVIDER_ID [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--model` | Model to check |
| `--run` | Run a real local completion |
| `--prompt` | Prompt for `--run` |
| `--no-tool-test` | Skip the provider-specific tool-calling probe |
| `--json` | Emit JSON output |

### Examples

```bash
superqode providers smoke ds4
superqode providers smoke ds4 --model deepseek-v4-flash --run
```

---

## providers mlx

Manage MLX (Apple Silicon) models and servers.

```bash
superqode providers mlx ACTION [OPTIONS]
```

### Actions

| Action | Description |
|--------|-------------|
| `list` | List available MLX models (cached and server) |
| `server` | Show command to start MLX server |
| `models` | Show suggested MLX models |
| `check` | Check if mlx_lm is installed |
| `setup` | Complete setup guide for MLX |

### Examples

```bash
# List available MLX models
superqode providers mlx list

# Show server start command
superqode providers mlx server --model mlx-community/Qwen2.5-Coder-3B-4bit

# Show suggested models
superqode providers mlx models

# Check installation
superqode providers mlx check

# Full setup guide
superqode providers mlx setup
```

### MLX Server Options

| Option | Description |
|--------|-------------|
| `--model`, `-m` | Model for server command |
| `--host` | Server host (default: localhost) |
| `--port` | Server port (default: 8080) |

---

## providers monty

Manage optional Monty sandboxed Python REPL support.

```bash
superqode providers monty ACTION
```

### Actions

| Action | Description |
|--------|-------------|
| `check` | Check whether `pydantic-monty` is installed |
| `smoke` | Run a small `python_repl` smoke test |
| `setup` | Show install and behavior guidance |

### Examples

```bash
# Check installation
superqode providers monty check

# Run smoke test
superqode providers monty smoke

# Show setup guide
superqode providers monty setup
```

Monty registers the `python_repl` tool when the optional dependency is installed:

```bash
uv sync --extra monty
```

See [Monty Python REPL](../advanced/monty-python-repl.md) for tool behavior and
filesystem mount details.

---

## Connect Commands

### connect byok

Connect to a BYOK (cloud) provider.

```bash
superqode connect byok PROVIDER MODEL
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROVIDER` | Provider ID (e.g., `anthropic`, `openai`) |
| `MODEL` | Model ID (e.g., `<anthropic-balanced-model>`, `<openai-model>`) |

### Examples

```bash
# Connect to Anthropic
superqode connect byok anthropic <anthropic-balanced-model>

# Connect to OpenAI
superqode connect byok openai <openai-model>

# Connect to Google AI
superqode connect byok google gemini-3.1-pro-preview
```

---

### connect acp

Connect to an ACP (Agent Client Protocol) agent.

```bash
superqode connect acp AGENT
```

**Note:** This command launches a simple CLI interactive session. For the full TUI experience, run `superqode` and use `:connect acp <agent>` inside the TUI.

### Arguments

| Argument | Description |
|----------|-------------|
| `AGENT` | Agent ID (e.g., `opencode`) |

### Examples

```bash
# Connect to OpenCode (requires ZHIPUAI_API_KEY environment variable)
export ZHIPUAI_API_KEY=your-api-key-here
superqode connect acp opencode
```

### Prerequisites

- Agent must be installed (e.g., `npm i -g opencode-ai` for OpenCode)
- Required API keys must be set as environment variables
- Agent must pass health checks

---

### connect local

Connect to a local/self-hosted provider.

```bash
superqode connect local PROVIDER MODEL
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROVIDER` | Local provider ID (e.g., `ollama`, `lmstudio`, `mlx`) |
| `MODEL` | Model ID |

### Examples

```bash
# Connect to Ollama
superqode connect local ollama qwen3:8b

# Connect to LM Studio
superqode connect local lmstudio local-model

# Connect to MLX
superqode connect local mlx mlx-community/Qwen2.5-Coder-3B-4bit
```

---

## Provider Categories

### US Labs (Tier 1)

| Provider | API Key Variable |
|----------|------------------|
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
| `google` | `GOOGLE_API_KEY` |
| `xai` | `XAI_API_KEY` |
| `mistral` | `MISTRAL_API_KEY` |

### China Labs

| Provider | API Key Variable |
|----------|------------------|
| `deepseek` | `DEEPSEEK_API_KEY` |
| `zhipu` | `ZHIPU_API_KEY` |
| `alibaba` | `ALIBABA_API_KEY` |

### Model Hosts

| Provider | API Key Variable |
|----------|------------------|
| `openrouter` | `OPENROUTER_API_KEY` |
| `together` | `TOGETHER_API_KEY` |
| `groq` | `GROQ_API_KEY` |
| `fireworks` | `FIREWORKS_API_KEY` |

### Local Providers

| Provider | Default Port | Notes |
|----------|--------------|-------|
| `ds4` | 8000 | Purpose-built DeepSeek V4 Flash server |
| `ollama` | 11434 | Easy local deployment |
| `lmstudio` | 1234 | GUI-based local models |
| `mlx` | 8080 | General Apple Silicon model serving |
| `vllm` | 8000 | High-performance inference |

---

## Setting Up Providers

### Cloud Providers

```bash
# 1. Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# 2. Verify configuration
superqode providers test anthropic

# 3. Connect
superqode connect byok anthropic <anthropic-balanced-model>
```

### Local Providers (Ollama)

```bash
# 1. Start Ollama
ollama serve

# 2. Pull a model
ollama pull qwen3:8b

# 3. Connect
superqode connect local ollama qwen3:8b
```

### Local Providers (MLX)

```bash
# 1. Install MLX
pip install mlx-lm

# 2. Download model
mlx_lm.download mlx-community/Qwen2.5-Coder-3B-4bit

# 3. Start server (in separate terminal)
mlx_lm.server --model mlx-community/Qwen2.5-Coder-3B-4bit

# 4. Connect
superqode connect local mlx mlx-community/Qwen2.5-Coder-3B-4bit
```

---

## Troubleshooting

### Provider Not Configured

```json
[INCORRECT] Provider 'anthropic' is not configured

Set: ANTHROPIC_API_KEY=your-api-key
Get your API key at: https://docs.anthropic.com/
```

**Solution**: Set the required environment variable.

### Connection Failed

```json
[INCORRECT] Connection failed: Connection refused
```

**Solution for local providers**: Ensure the server is running.

```bash
# For Ollama
ollama serve

# For MLX
mlx_lm.server --model <model-id>
```

### Model Not Found

```json
[INCORRECT] Error: Model 'unknown-model' not found
```

**Solution**: Check available models for the provider.

```bash
superqode providers show anthropic
```

---

## Next Steps

- [BYOK Providers](../providers/byok.md) - Detailed BYOK provider documentation
- [Local Providers](../providers/local.md) - Local model setup guides
- [ACP Agents](../providers/acp.md) - ACP agent documentation
