# Model Catalog

SuperQode integrates with models.dev to provide a live catalog of 5000+ models across 130+ providers. The catalog is fetched on demand, cached locally at `~/.superqode/models_cache.json` with a 1-hour TTL, and serves as the single source of truth for model discovery.

Use `--refresh` to force re-fetch.

## Live Model Discovery

Use `--live` to query a provider's `/v1/models` endpoint directly for the freshest model list. Falls back to the cached catalog if the endpoint is unreachable. Any OpenAI-compatible endpoint works without registration.

## Curated and Dynamic Providers

- ~38 hand-curated providers in the registry with tuned definitions
- 130+ additional providers synthesized dynamically from models.dev metadata
- OpenAI-compatible routing for providers with `api_url`
- Native LiteLLM routing for providers without `api_url`
- Curated providers always take precedence over synthesized ones

## CLI Usage

```bash
# Browse the catalog
superqode models
superqode models --search claude
superqode models --provider anthropic
superqode models --cap tools --free
superqode models --sort price --limit 20
superqode models --refresh
superqode models --provider ollama --live

# List providers
superqode models providers
superqode models providers --json

# Model details
superqode models show anthropic/claude-sonnet-4
superqode models show gpt-4o

# Hugging Face Hub
superqode models hub qwen
superqode models hub --gguf --sort downloads
superqode models hub deepseek --mlx --limit 10

# Download models
superqode models download deepseek-ai/DeepSeek-V4-GGUF
superqode models download THUDM/GLM-4.5-Air --to transformers

# Check local readiness
superqode local smoke --repo .

# Convert to MLX
superqode models convert-mlx mlx-community/Qwen3-8B-4bit

# Manage cache
superqode models cached
superqode models rm deepseek --yes
```

## Provider Resolution

The three-tier resolution:

1. Hand-curated provider definition (always wins)
2. Dynamically synthesized from models.dev metadata
3. None (provider unknown)

For synthesized OpenAI-compatible providers, base URL can be overridden via `{PROVIDER_ID}_BASE_URL` env var.
