---
title: Models and Inference
description: Connect hosted model gateways and local inference servers.
---

# Models and inference

These routes assign ownership of tools, context, memory, approvals, evaluation,
and workflow to the SuperQode harness.

## Hosted model gateways

| Integration | Dependency and authentication | Start | Verify | Detailed guide |
| --- | --- | --- | --- | --- |
| LiteLLM gateway | **Included**; set the selected provider's API key | `:connect byok <provider> <model>` | `superqode providers doctor <provider>` | [BYOK Providers](../providers/byok.md) |
| OpenResponses gateway | **Included**; configure a compatible endpoint and credential | Select `openresponses` in `superqode.yaml` | `superqode config validate` | [OpenResponses](../providers/openresponses.md) |
| Hugging Face Hub | `uv tool install "superqode[hf]"`; use `HF_TOKEN` for gated models | `superqode models hub <query>` | `superqode models show <model>` | [Model Catalog](../advanced/model-catalog.md) |
| Exa search client | `uv tool install "superqode[extras]"`, then set the Exa credential | Enable an Exa-backed search route | Run the configured search tool | [Airplane Mode and External Search](../advanced/airplane-mode.md) |

The provider catalog includes OpenAI, Anthropic, Google, xAI, DeepSeek,
Mistral, Moonshot, Qwen, Z.AI, MiniMax, OpenRouter, Together, Groq, Fireworks,
Hugging Face, Cerebras, Cohere, Bedrock, Azure, Vertex AI, Cloudflare, and
other supported LiteLLM or OpenAI-compatible routes. Query the live catalog
instead of copying a static model identifier:

```bash
superqode providers list
superqode providers models <provider>
superqode providers doctor <provider>
```

See [Providers](../providers/index.md) for provider tiers, authentication, and
the complete model-provider catalog.

## Local inference

| Integration | Install or service | Start | Verify | Detailed guide |
| --- | --- | --- | --- | --- |
| Ollama | Install and start Ollama | `:connect local ollama <model>` | `superqode local doctor` | [Local Providers](../providers/local.md) |
| LM Studio | Start the local OpenAI-compatible server | `:connect local lmstudio <model>` | `superqode local doctor` | [Local Providers](../providers/local.md) |
| vLLM | Start a vLLM OpenAI-compatible endpoint | `:connect local vllm <model>` | `superqode local doctor` | [Local Providers](../providers/local.md) |
| SGLang | Start an SGLang endpoint | `:connect local sglang <model>` | `superqode local doctor` | [Local Providers](../providers/local.md) |
| Hugging Face TGI | Start a TGI endpoint | `:connect local tgi <model>` | `superqode local doctor` | [Local Providers](../providers/local.md) |
| MLX and MLX-VLM | `uv tool install "superqode[mlx]"` on supported Apple Silicon | `:connect local mlx <model>` | `superqode local doctor` | [Local Providers](../providers/local.md) |
| DwarfStar | Install and start a compatible DwarfStar server | Select the discovered local route | `superqode local doctor` | [Local Providers](../providers/local.md#dwarfstar-ds4) |
| Apple Foundation Models | Install `apple-fm-sdk` on supported Apple Silicon with Apple Intelligence | Set `SUPERQODE_UTILITY_PROVIDER=apple-fm` | `superqode local doctor` | [Local Stack Doctor](../advanced/local-stack.md) |
| Transformers | Install `transformers`, `accelerate`, and the required compute framework | Select the local Transformers route | `superqode local doctor` | [Local Stack Doctor](../advanced/local-stack.md) |
| EmbeddingGemma 2 for CodeGem | `uv tool install "superqode[semantic-local]"`; weights download from Google/Hugging Face on first use | Set CodeGem `embedding.provider` to `sentence-transformers` | Use `superqode-codegem-index . --provider sentence-transformers --query "your code question"` | [CodeGem](../advanced/codegem.md#add-local-embeddinggemma-search) |

Generate a repository-owned local harness after the server is ready:

```bash
superqode local init --repo .
superqode --harness superqode.local.yaml
```
