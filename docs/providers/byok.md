<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# BYOK Providers

Bring Your Own Key (BYOK) mode connects to cloud AI providers using your API keys.

---

## Overview

BYOK is the primary mode for production use:

- **Full control**: Use your own API keys and quotas
- **Cost management**: Pay directly to providers
- **Model selection**: Choose specific models for roles
- **Privacy**: Data goes directly to your chosen provider

---

## Quick Setup

```bash
# 1. Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# 2. Verify configuration
superqode providers test anthropic

# 3. Connect
superqode connect byok anthropic claude-sonnet-4
```

---

## Supported Providers

### Tier 1 (First-Class Support)

Full optimization and testing:

#### Anthropic (Claude)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
superqode connect byok anthropic claude-sonnet-4
```

| Model | Best For |
|-------|----------|
| `claude-opus-4-5` | Complex analysis |
| `claude-sonnet-4-5` | Balanced performance |
| `claude-sonnet-4` | General use |
| `claude-haiku-4-5` | Fast, cost-effective |

**Documentation**: [docs.anthropic.com](https://docs.anthropic.com)

#### OpenAI (GPT)

```bash
export OPENAI_API_KEY=sk-...
superqode connect byok openai gpt-4o
```

| Model | Best For |
|-------|----------|
| `gpt-4o` | General use |
| `gpt-4o-mini` | Cost-effective |
| `o1` | Complex reasoning |
| `o1-mini` | Fast reasoning |

**Documentation**: [platform.openai.com](https://platform.openai.com)

#### Google AI (Gemini)

```bash
export GOOGLE_API_KEY=AIza...
superqode connect byok google gemini-2.5-pro
```

| Model | Best For |
|-------|----------|
| `gemini-2.5-pro` | Complex tasks |
| `gemini-2.5-flash` | Fast, cost-effective |

**Documentation**: [ai.google.dev](https://ai.google.dev)

---

### Tier 2 (Supported)

Tested and working:

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

#### xAI (Grok)

```bash
export XAI_API_KEY=...
superqode connect byok xai grok
```

---

### Model Hosts

Access multiple models through a single API:

#### OpenRouter

```bash
export OPENROUTER_API_KEY=sk-or-...
superqode connect byok openrouter anthropic/claude-sonnet-4
```

- **95+ models** from various providers
- Use format: `provider/model-name`

**Documentation**: [openrouter.ai](https://openrouter.ai)

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
| Together | `TOGETHER_API_KEY` | Required |
| Groq | `GROQ_API_KEY` | Required |
| Mistral | `MISTRAL_API_KEY` | Required |
| xAI | `XAI_API_KEY` | Required |

### Configuration File

```yaml
providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    recommended_models:
      - claude-opus-4-5
      - claude-sonnet-4-5
      - claude-sonnet-4
      - claude-haiku-4-5

  openai:
    api_key_env: OPENAI_API_KEY
    recommended_models:
      - gpt-4o
      - gpt-4o-mini
      - o1
      - o1-mini

  deepseek:
    api_key_env: DEEPSEEK_API_KEY
    recommended_models:
      - deepseek-v3
      - deepseek-r1
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

        performance_tester:
          mode: byok
          provider: openai
          model: gpt-4o
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

```
Cost Summary:
  Provider: anthropic
  Model: claude-sonnet-4
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

```
[INCORRECT] Provider 'anthropic' is not configured
```

**Solution**: Set the API key environment variable.

### "Invalid API Key"

```
[INCORRECT] Connection failed: Invalid API key
```

**Solution**: Verify your API key is correct and has appropriate permissions.

### Rate Limiting

```
[INCORRECT] Rate limit exceeded
```

**Solutions**:
- Wait and retry
- Use a different provider temporarily
- Upgrade your API tier

### Model Not Found

```
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
