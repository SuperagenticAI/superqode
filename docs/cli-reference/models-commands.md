# Models Commands

Browse, search, and download models from the models.dev catalog and Hugging Face Hub.

Results are cached at `~/.superqode/models_cache.json` with a 1-hour TTL. Use `--refresh` to force an update. Use `--live` to query the provider's `/v1/models` endpoint directly instead of the catalog.

---

## models (default)

Browse or search the models.dev catalog of 5000+ models from 130+ providers.

```bash
superqode models [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--search`, `-s` | Search query (name, provider, or description) |
| `--provider`, `-p` | Filter by provider ID |
| `--cap` | Filter by capability: `tools`, `vision`, `reasoning`, `code`, `long`, `json` |
| `--free` | Show only free (no-cost) models |
| `--max-price` | Maximum price per million input tokens |
| `--curated` | Show only curated/recommended models |
| `--sort` | Sort order: `provider`, `price`, `context` |
| `--limit` | Maximum results (default 50, 0 for all) |
| `--refresh` | Bypass cache and fetch fresh data |
| `--live` | Query provider's `/v1/models` endpoint directly |
| `--json` | Emit JSON output |

### Examples

```bash
# Browse default view
superqode models

# Search for models
superqode models -s claude

# Filter by provider and capability
superqode models -p anthropic --cap tools

# Free models with reasoning
superqode models --free --cap reasoning

# Sort by context window
superqode models --sort context --limit 10

# Live query of provider endpoint
superqode models -p openai --live --json

# All models, no limit
superqode models --limit 0
```

---

## models providers

List all providers available in the models.dev catalog.

```bash
superqode models providers [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--json` | Emit JSON output |

### Examples

```bash
superqode models providers
superqode models providers --json
```

---

## models show

Show detailed information for a specific provider/model combination: context window, pricing, capabilities, and required API key environment variables.

```bash
superqode models show PROVIDER/MODEL
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROVIDER/MODEL` | Provider and model ID (e.g., `anthropic/claude-sonnet-4`) |

### Examples

```bash
superqode models show anthropic/claude-sonnet-4
superqode models show openai/gpt-4o
```

---

## models hub

Search the Hugging Face Hub for models.

```bash
superqode models hub [QUERY] [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `QUERY` | Optional search query |

### Options

| Option | Description |
|--------|-------------|
| `--gguf` | Filter for GGUF format models |
| `--mlx` | Filter for MLX format models |
| `--sort` | Sort order: `downloads`, `likes`, `trending_score`, `created_at` |
| `--limit` | Maximum results (default 25) |
| `--json` | Emit JSON output |

### Examples

```bash
# Search Hugging Face
superqode models hub qwen

# Filter by format
superqode models hub --gguf qwen
superqode models hub --mlx deepseek

# Sort by downloads
superqode models hub --sort downloads --limit 10

# Full JSON output
superqode models hub --json
```

---

## models download

Download a model from Hugging Face Hub.

```bash
superqode models download REPO_ID [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `REPO_ID` | Hugging Face repository ID (e.g., `QuantFactory/Qwen3-8B-GGUF`) |

### Options

| Option | Description |
|--------|-------------|
| `--to` | Target format: `auto`, `ollama`, `mlx`, `transformers` |
| `--quant` | Quantization (default `Q4_K_M`) |
| `--dir` | Target download directory |
| `--name` | Custom model name for registration |
| `--register` / `--no-register` | Register model with superqode after download |
| `--yes` | Skip confirmation prompts |

### Examples

```bash
# Download with defaults
superqode models download QuantFactory/Qwen3-8B-GGUF

# Download for Ollama with custom name
superqode models download QuantFactory/Qwen3-8B-GGUF --to ollama --name qwen3-8b

# Download to specific directory, no register
superqode models download mlx-community/Qwen2.5-Coder-3B-4bit --to mlx --dir ~/models --no-register

# Non-interactive
superqode models download QuantFactory/Qwen3-8B-GGUF --yes
```

---

## models convert-mlx

Convert a Hugging Face model to MLX format.

```bash
superqode models convert-mlx HF_PATH [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `HF_PATH` | Hugging Face model path |

### Options

| Option | Description |
|--------|-------------|
| `--q-bits` | Quantization bits: `4` or `8` |
| `--no-quantize` | Skip quantization (keep float16/float32) |
| `--out` | Output directory |
| `--upload` | Upload result to Hugging Face Hub |

### Examples

```bash
# Convert with 4-bit quantization
superqode models convert-mlx Qwen/Qwen3-8B --q-bits 4

# Convert without quantization
superqode models convert-mlx Qwen/Qwen3-8B --no-quantize --out ./mlx-model

# Convert and upload
superqode models convert-mlx Qwen/Qwen3-8B --q-bits 8 --upload
```

---

## models cached

List models cached locally from Hugging Face.

```bash
superqode models cached [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--json` | Emit JSON output |

### Examples

```bash
superqode models cached
superqode models cached --json
```

---

## models rm

Delete cached models matching a pattern.

```bash
superqode models rm PATTERN [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PATTERN` | Pattern to match cached model names |

### Options

| Option | Description |
|--------|-------------|
| `--yes` | Skip confirmation prompts |

### Examples

```bash
# Remove matching cached models (with confirmation)
superqode models rm qwen

# Force remove without confirmation
superqode models rm qwen --yes
```
