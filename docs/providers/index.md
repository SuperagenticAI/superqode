# Providers

SuperQode supports multiple provider types for connecting to AI models and agents.

---

## Provider Types

<div class="grid cards" markdown>

-   **BYOK Providers**

    ---

    Bring Your Own Key - connect to cloud AI providers using your API keys.

    [:octicons-arrow-right-24: BYOK Providers](byok.md)

-   **ACP Agents**

    ---

    Agent Client Protocol - connect to coding agents like OpenCode, Amp, Claude Code, and more.

    [:octicons-arrow-right-24: ACP Agents](acp.md)

-   **Local Providers**

    ---

    Run models locally with Ollama, LM Studio, MLX, or vLLM.

    [:octicons-arrow-right-24: Local Providers](local.md)

-   **OpenResponses**

    ---

    Use the OpenResponses gateway for enhanced capabilities.

    [:octicons-arrow-right-24: OpenResponses](openresponses.md)

</div>

---

## Execution Modes

SuperQode supports three execution modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| **BYOK** | Cloud AI providers with your API key | Production, team use |
| **ACP** | Coding agents with full capabilities | Complex tasks |
| **Local** | Self-hosted models | Privacy, cost savings |

---

## Quick Start

### BYOK (Cloud Providers)

```bash
# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Connect
superqode connect byok anthropic claude-sonnet-4
```

### ACP (Coding Agents)

```bash
# Connect to OpenCode
superqode connect acp opencode

# Connect to Amp
superqode connect acp amp
```

### Local (Self-Hosted)

```bash
# Start Ollama
ollama serve

# Connect
superqode connect local ollama qwen3:8b
```

---

## Provider Tiers

### Tier 1 (First-Class Support)

Full support with optimized prompts (Enterprise adds prompt packs):

| Provider | Models |
|----------|--------|
| Anthropic | Claude Opus 4.5, Sonnet 4, Haiku 4 |
| OpenAI | GPT-4o, o1 |
| Google | Gemini 2.5 Pro/Flash |

### Tier 2 (Supported)

Tested and supported:

| Provider | Models |
|----------|--------|
| Deepseek | Deepseek V3, R1 |
| Mistral | Mistral Large |
| xAI | Grok |

### Local Tier

Self-hosted options:

| Provider | Description |
|----------|-------------|
| Ollama | Easy local deployment |
| LM Studio | GUI-based local models |
| MLX | Apple Silicon optimized |
| vLLM | High-performance inference |

---

## Listing Providers

```bash
# List all providers
superqode providers list

# List by category
superqode providers list --category us
superqode providers list --category local

# Show configured only
superqode providers list --configured
```

---

## Testing Connections

```bash
# Test a provider
superqode providers test anthropic

# Test with specific model
superqode providers test anthropic -m claude-sonnet-4
```

---

## Configuration

### In superqode.yaml

```yaml
default:
  mode: byok
  provider: anthropic
  model: claude-sonnet-4

providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    recommended_models:
      - claude-opus-4-5
      - claude-sonnet-4

  ollama:
    base_url: http://localhost:11434
    recommended_models:
      - qwen3:8b
```

### Per-Role Configuration

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          mode: byok
          provider: anthropic
          model: claude-sonnet-4

        unit_tester:
          mode: local
          provider: ollama
          model: qwen3:8b
```

---

## Provider Categories

### US Labs

| Provider | API Key Variable | Documentation |
|----------|------------------|---------------|
| `anthropic` | `ANTHROPIC_API_KEY` | [docs.anthropic.com](https://docs.anthropic.com) |
| `openai` | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| `google` | `GOOGLE_API_KEY` | [ai.google.dev](https://ai.google.dev) |
| `xai` | `XAI_API_KEY` | [x.ai/api](https://x.ai/api) |

### China Labs

| Provider | API Key Variable |
|----------|------------------|
| `deepseek` | `DEEPSEEK_API_KEY` |
| `zhipu` | `ZHIPU_API_KEY` |
| `alibaba` | `ALIBABA_API_KEY` |

### Model Hosts

| Provider | API Key Variable | Notes |
|----------|------------------|-------|
| `openrouter` | `OPENROUTER_API_KEY` | 95+ models |
| `together` | `TOGETHER_API_KEY` | Open models |
| `groq` | `GROQ_API_KEY` | Fast inference |
| `fireworks` | `FIREWORKS_API_KEY` | Open models |

### Local Providers

| Provider | Default Port | Notes |
|----------|--------------|-------|
| `ollama` | 11434 | Easy setup |
| `lmstudio` | 1234 | GUI interface |
| `mlx` | 8080 | Apple Silicon |
| `vllm` | 8000 | Production |

---

## Free Tiers

Some providers offer free access:

```bash
# List free providers
superqode providers list --category free
```

| Provider | Free Models |
|----------|------------|
| Google AI | gemini-2.5-flash (limited) |
| Groq | llama-3.3-70b (rate limited) |
| OpenRouter | Some open models |

---

## Next Steps

- [BYOK Providers](byok.md) - Cloud provider setup
- [ACP Agents](acp.md) - Coding agent integration
- [Local Providers](local.md) - Self-hosted models
- [OpenResponses](openresponses.md) - Gateway configuration
