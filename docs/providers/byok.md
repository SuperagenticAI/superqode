# BYOK Providers

Bring Your Own Key (BYOK) mode connects to cloud AI providers using your API keys.

!!! note "Model names are examples"
    Model identifiers in this guide, such as `<anthropic-model>` or `<openai-model>`, are
    examples and change as providers release new models. Run `superqode providers list`
    to see configured providers, then pick the latest model your provider offers.

---

## Overview

BYOK is the primary mode for production use:

- **Full control**: Use your own API keys and quotas
- **Cost management**: Pay directly to providers
- **Model selection**: Choose specific models for your tasks
- **Privacy**: Data goes directly to your chosen provider

---

## Quick Setup

```bash
# 1. Set API key. Alternative: `superqode auth login anthropic` stores the
#    key in ~/.superqode/auth.json (0600) via a masked prompt.
export ANTHROPIC_API_KEY=sk-ant-...

# 2. Verify configuration
superqode providers test anthropic

# 3. Connect
superqode connect byok anthropic <anthropic-model>
```

!!! tip "Connect by model name alone"
    In the TUI you can skip the provider: `:connect muse-spark-1.1` or
    `:connect gpt-5.6` resolves the hosting provider from the catalog
    (first-party providers are preferred over gateway mirrors). If a model has
    several available routes, such as `grok-4.5` via the xAI API or the Grok
    subscription, SuperQode lists the exact commands to choose from.

---

## Supported Providers

### Tier 1 (First-Class Support)

Full optimization and testing:

#### Anthropic (Claude)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
superqode connect byok anthropic <anthropic-balanced-model>
```

| Model | Best For |
|-------|----------|
| `<anthropic-model>` | Most capable, complex analysis |
| `<anthropic-balanced-model>` | Balanced performance |
| `<anthropic-fast-model>` | Fast, cost-effective |

**Documentation**: [docs.anthropic.com](https://docs.anthropic.com)

#### OpenAI (GPT)

```bash
export OPENAI_API_KEY=sk-...
superqode connect byok openai <openai-model>
```

| Model | Best For |
|-------|----------|
| `<openai-model>` | Most capable, complex reasoning |
| `<openai-fast-model>` | Faster, cost-effective |

**Documentation**: [platform.openai.com](https://platform.openai.com)

#### Google AI (Gemini)

```bash
export GOOGLE_API_KEY=AIza...
superqode connect byok google gemini-3.1-pro-preview
```

| Model | Best For |
|-------|----------|
| `gemini-3.1-pro-preview` | Latest Pro model from models.dev |
| `gemini-flash-latest` | Latest Flash model from models.dev |

**Documentation**: [ai.google.dev](https://ai.google.dev)

#### Z.AI (GLM)

```bash
export ZAI_API_KEY=...
superqode connect zai glm-5.2
```

The `zai` provider uses the first-party general endpoint
`https://api.z.ai/api/paas/v4`. It does not use the restricted GLM Coding Plan
endpoint. See the [Z.AI provider guide](zai.md) for the TUI connection and the
`glm52-coding` harness.

#### Meta (Muse Spark)

```bash
export META_MODEL_API_KEY=...
superqode connect byok meta muse-spark-1.1
```

| Model | Context | Best For |
|-------|---------|----------|
| `muse-spark-1.1` | 1M | Long-context coding and analysis on Meta's first-party API |

Meta's model API is OpenAI-compatible at `https://api.meta.ai/v1` (override
with `META_BASE_URL`). The model list follows models.dev, so new Meta releases
appear automatically. In the TUI, `:connect muse-spark-1.1` resolves the
provider from the catalog.

**Documentation**: [dev.meta.ai/docs](https://dev.meta.ai/docs)

#### Moonshot AI (Kimi K3)

```bash
export MOONSHOT_API_KEY=...
superqode connect byok moonshot kimi-k3
```

| Model | Context | Price (in/out per 1M) | Best For |
|-------|---------|-----------------------|----------|
| `kimi-k3` | 1,048,576 | $3.00 / $15.00 | Long-horizon coding, frontend work, and large repositories |
| `kimi-k2.7-code-highspeed` | 262K | $0.95 / $4.00 | Faster iterative coding loops |

SuperQode routes this provider directly to Moonshot's global OpenAI-compatible
API at `https://api.moonshot.ai/v1` (override with `MOONSHOT_API_BASE`). K3 has
thinking permanently enabled; the current pay-as-you-go API accepts only
`reasoning_effort: max`. It automatically caches stable prompt prefixes, so
keep the same harness and reasoning effort within a session.

Use the maintained Kimi-family harness directly, or create an editable copy:

```bash
superqode --harness kimi-coding -p "Review this repository"
superqode harness init kimi-project --template kimi-coding --output harness.yaml
```

The current stable route selects `moonshot/kimi-k3`, its 1M context, max reasoning, native
parallel tools, and a longer cache-friendly session history. Full open weights
are scheduled for July 27, 2026; until compatible serving stacks publish K3
support, this preset targets Moonshot's hosted API.
Use `kimi-k3-coding` only when the project must remain explicitly pinned to K3.

**Documentation**: [Complete Kimi K3 provider and feature guide](kimi.md) ·
[Official Kimi K3 API guide](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart)

---

### Tier 1 (First-Class Support) continued

#### Deepseek

```bash
export DEEPSEEK_API_KEY=sk-...
superqode connect byok deepseek deepseek-v3
```

| Model | Best For |
|-------|----------|
| `deepseek-v3` | General use |
| `deepseek-r1` | Reasoning |

**Cost**: Very competitive pricing

#### Mistral

```bash
export MISTRAL_API_KEY=...
superqode connect byok mistral mistral-large
```

#### xAI (Grok 4.5)

```bash
export XAI_API_KEY=...
superqode connect byok xai grok-4.5
```

| Model | Context | Price (in/out per 1M) | Best For |
|-------|---------|-----------------------|----------|
| `grok-4.5` | 500K | $2.00 / $6.00 | Agentic coding, complex reasoning, and research |
| `grok-4.3` | 1M | $1.25 / $2.50 | Document-heavy work needing the largest context |
| `grok-build-0.1` | 256K | $1.00 / $2.00 | Fast agentic coding loops and iterative edits |

Grok 4.5 supports `reasoning_effort` (low / medium / high, default high) and
image + PDF input. Cached input is $0.50 per million tokens, and prompts above
200K tokens are billed at a higher tier ($4 / $12). This route uses your xAI
API account and is billed separately from a consumer subscription. Grok 4.5 is
not yet available in the xAI API console for EU users.

**Documentation**: [xAI Grok 4.5](https://docs.x.ai/developers/grok-4-5) ·
[xAI model catalog](https://docs.x.ai/developers/models)

---

## Grok Subscription (Official CLI)

For an eligible local X/SuperGrok account, the **Grok subscription** profile has
two routes on the same `grok login`:

- `:connect grok` runs **Grok Build**, xAI's own coding agent, over ACP. This
  is the default, matching the Codex and Claude subscription profiles: the
  vendor's agent owns the loop.
- `:grok api [model]` runs **SuperQode's own harness** on the subscription. It
  imports the `grok login` session and talks to the CLI chat proxy, so
  `core`/`workbench`, SuperQode's tools, and memory drive Grok 4.5.

```bash
# Install the official xAI CLI if needed (macOS/Linux/WSL)
curl -fsSL https://x.ai/cli/install.sh | bash
# Windows PowerShell: irm https://x.ai/cli/install.ps1 | iex

# Sign in locally
grok login

# Grok Build (xAI's own agent) on your subscription
superqode --connect grok
```

Inside the TUI:

```text
:connect grok                 # Grok Build, xAI's own agent (ACP), default
:grok api                     # SuperQode's harness on the subscription (opt-in)
:grok api grok-4.5            # ...pinned to a specific model
:grok model                   # ...or pick from a menu of subscription models
:grok models                  # list the signed-in CLI's model catalog
```

On SSH or another headless machine, authenticate with:

```bash
grok login --device-auth
```

Subscription access requires an eligible SuperGrok or X Premium+ plan; quotas
and regional access are determined by xAI. For cloud or automation workloads,
use `XAI_API_KEY` BYOK instead.

### How the `:grok api` harness route works

`:grok api` (the SuperQode-harness opt-in) does the following:

1. Import the session token from `~/.grok/auth.json` into SuperQode's local auth
   store (`~/.superqode/auth.json`, permissions 0600)
2. Connect the `grok-cli` provider against `https://cli-chat-proxy.grok.com/v1`
3. Send the headers xAI requires: `X-XAI-Token-Auth`, `x-grok-model-override`,
   and `x-grok-client-version` from your installed CLI (the proxy returns
   HTTP 426 when the version header is missing)

```text
:grok api off                 # remove the imported token
```

Enterprise proxies are honored via `GROK_CLI_CHAT_PROXY_BASE_URL`.

Notes:

- CLI sessions last about 7 days; when the token expires, run `grok login`
  again, then reconnect.
- Usage counts against your subscription and model eligibility is enforced by
  xAI per tier. The `:grok api` route is intended for interactive use. For
  automation or benchmarking, use `XAI_API_KEY` BYOK.
- Most proxy models are streaming-only; SuperQode's chat path streams by
  default.

---

### Model Hosts

Access multiple models through a single API:

#### OpenRouter

```bash
export OPENROUTER_API_KEY=sk-or-...
superqode connect byok openrouter anthropic/<anthropic-balanced-model>
```

- **95+ models** from various providers
- Use format: `provider/model-name`

**Documentation**: [openrouter.ai](https://openrouter.ai)

#### Hugging Face Inference Providers

Hugging Face routes many open models through partner inference providers using
one model id plus a provider suffix. SuperQode accepts the same route in the
regular BYOK provider/model fields:

```bash
export HF_TOKEN=hf_...

# Full provider/model form
superqode connect byok huggingface zai-org/GLM-5.2:fireworks-ai

# Shorthand form, useful in config and command history
superqode connect byok hf.zai-org/GLM-5.2:fireworks-ai
```

SuperQode normalizes all of these forms to the Hugging Face provider:

| Form | Resolves To |
|------|-------------|
| `hf.zai-org/GLM-5.2:fireworks-ai` | `huggingface` + `zai-org/GLM-5.2:fireworks-ai` |
| `hf/zai-org/GLM-5.2:fireworks-ai` | `huggingface` + `zai-org/GLM-5.2:fireworks-ai` |
| `huggingface/zai-org/GLM-5.2:fireworks-ai` | `huggingface` + `zai-org/GLM-5.2:fireworks-ai` |

Current GLM-5.2 routes exposed in the default config:

| Alias | Hugging Face Route |
|-------|--------------------|
| `glm52` | `hf.zai-org/GLM-5.2:fireworks-ai` |
| `glm52-hf-fireworks` | `hf.zai-org/GLM-5.2:fireworks-ai` |
| `glm52-hf-together` | `hf.zai-org/GLM-5.2:together` |
| `glm52-hf-novita` | `hf.zai-org/GLM-5.2:novita` |
| `glm52-hf-zai` | `hf.zai-org/GLM-5.2:zai-org` |
| `glm52-hf-deepinfra` | `hf.zai-org/GLM-5.2:deepinfra` |

The `:provider` suffix is generic, so other Hugging Face Inference Provider
routes work the same way when Hugging Face advertises them.

**Documentation**: [huggingface.co/inference](https://huggingface.co/inference)

#### Together AI

```bash
export TOGETHER_API_KEY=...
superqode connect byok together meta-llama/Llama-3.3-70B-Instruct
```

#### Groq

```bash
export GROQ_API_KEY=gsk-...
superqode connect byok groq llama-3.3-70b-versatile
```

- **Very fast** inference
- Free tier available

#### Fireworks

```bash
export FIREWORKS_API_KEY=...
superqode connect byok fireworks accounts/fireworks/models/llama-v3p3-70b-instruct
```

---

## Configuration

### Environment Variables

| Provider | Variable | Notes |
|----------|----------|-------|
| Anthropic | `ANTHROPIC_API_KEY` | Required |
| OpenAI | `OPENAI_API_KEY` | Required |
| Google | `GOOGLE_API_KEY` | Required |
| Deepseek | `DEEPSEEK_API_KEY` | Required |
| OpenRouter | `OPENROUTER_API_KEY` | Required |
| Hugging Face | `HF_TOKEN` or `HUGGINGFACE_API_KEY` | Required for HF Inference Providers |
| Together | `TOGETHER_API_KEY` | Required |
| Groq | `GROQ_API_KEY` | Required |
| Mistral | `MISTRAL_API_KEY` | Required |
| xAI | `XAI_API_KEY` | Required |
| Moonshot AI | `MOONSHOT_API_KEY` or `KIMI_API_KEY` | Required |

### Configuration File

```yaml
providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    recommended_models:
      - <anthropic-model>
      - <anthropic-balanced-model>
      - <anthropic-fast-model>

  openai:
    api_key_env: OPENAI_API_KEY
    recommended_models:
      - <openai-model>
      - <openai-fast-model>

  deepseek:
    api_key_env: DEEPSEEK_API_KEY
    recommended_models:
      - deepseek-v3
      - deepseek-r1

  huggingface:
    api_key_env: HF_TOKEN
    recommended_models:
      - zai-org/GLM-5.2:fireworks-ai
      - zai-org/GLM-5.2:together
      - zai-org/GLM-5.2:novita
      - zai-org/GLM-5.2:zai-org
      - zai-org/GLM-5.2:deepinfra

model_aliases:
  glm52: hf.zai-org/GLM-5.2:fireworks-ai
  glm52-hf-together: hf.zai-org/GLM-5.2:together
  glm52-hf-novita: hf.zai-org/GLM-5.2:novita
```

---

## Cost Management

### Tracking Costs

```yaml
superqode:
  cost_tracking:
    enabled: true
    show_after_task: true
```

After each task, you'll see:

```text
Cost Summary:
  Provider: anthropic
  Model: <anthropic-balanced-model>
  Input tokens: 15,234
  Output tokens: 2,456
  Estimated cost: $0.12
```

### Cost-Effective Strategies

1. **Use appropriate models**: Haiku/mini for simple tasks
2. **Use quick mode**: Shorter sessions, less tokens
3. **Local fallback**: Use local models for high-volume tasks

---

## Security Best Practices

### API Key Management

```bash
# Don't commit API keys
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
echo ".env" >> .gitignore
```

### Rotate Keys Regularly

- Anthropic: [console.anthropic.com](https://console.anthropic.com)
- OpenAI: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

### Use Project Keys

Where available, use project-specific API keys with limited scope.

---

## Troubleshooting

### "Not Configured" Error

```json
[INCORRECT] Provider 'anthropic' is not configured
```

**Solution**: Set the API key environment variable.

### "Invalid API Key"

```json
[INCORRECT] Connection failed: Invalid API key
```

**Solution**: Verify your API key is correct and has appropriate permissions.

### Rate Limiting

```json
[INCORRECT] Rate limit exceeded
```

**Solutions**:
- Wait and retry
- Use a different provider temporarily
- Upgrade your API tier

### Model Not Found

```json
[INCORRECT] Model 'claude-5' not found
```

**Solution**: Check available models:

```bash
superqode providers show anthropic
```

---

## Provider Comparison

| Provider | Speed | Cost | Models | Best For |
|----------|-------|------|--------|----------|
| Anthropic | Fast | Medium | 4 | Security, reasoning |
| OpenAI | Fast | Medium | 4 | General, reasoning |
| Google | Fast | Low | 2 | General, vision |
| Deepseek | Medium | Low | 2 | Cost-effective |
| Groq | Very Fast | Low | 3 | Speed-critical |

---

## Next Steps

- [Local Providers](local.md) - Self-hosted alternatives
- [ACP Agents](acp.md) - Coding agent integration
- [Provider Commands](../cli-reference/provider-commands.md) - CLI reference
