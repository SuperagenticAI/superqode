# Providers

SuperQode supports hosted model providers, local model servers, external coding
agents, vendor SDK runtimes, MCP tool servers, and A2A agent services. The
[Connection Methods and Vendors](../concepts/modes.md) page lists every
connection method, product-level shortcut, built-in provider, local engine, and
bundled ACP agent in one place.

!!! note "Model names are examples"
    Model identifiers in these provider docs, such as `<anthropic-model>` or
    `<openai-model>`, are examples and change as providers release new models. Run
    `superqode providers list` to see configured providers, then pick the latest
    model your provider offers.

---

## Provider Types

<div class="grid cards" markdown>

-   **BYOK Providers**

    ---

    Bring Your Own Key - connect to cloud AI providers using your API keys.

    [:octicons-arrow-right-24: BYOK Providers](byok.md)

-   **ACP Agents**

    ---

    Agent Client Protocol - connect to coding agents like OpenCode, Grok Build, Amp, Claude Code, and more.

    [:octicons-arrow-right-24: ACP Agents](acp.md)

-   **Local Providers**

    ---

    Run models locally with DS4, Ollama, LM Studio, MLX, or vLLM.

    [:octicons-arrow-right-24: Local Providers](local.md)

-   **OpenResponses**

    ---

    Use the OpenResponses gateway for enhanced capabilities.

    [:octicons-arrow-right-24: OpenResponses](openresponses.md)

-   **Model Profiles**

    ---

    Per-provider and per-model tuning: prompt suffixes, tool exclusions, init kwargs, pre-init hooks.

    [:octicons-arrow-right-24: Model Profiles](profiles.md)

-   **SDK Runtimes**

    Vendor agent SDKs and authenticated clients, including Codex, Claude,
    GitHub Copilot, and Antigravity.

    [:octicons-arrow-right-24: Runtime Backends](../runtimes.md)

-   **MCP and A2A**

    Connect tool servers through MCP and remote agent services through A2A.

    [:octicons-arrow-right-24: MCP Configuration](../configuration/mcp-config.md)
    [:octicons-arrow-right-24: A2A Providers](a2a.md)

-   **Unified Harness Protocol**

    Run harnesses hosted on a UHP server through one HTTP contract.

    [:octicons-arrow-right-24: UHP](uhp.md)

</div>

---

## Connection Methods

`:connect` opens a three-option screen, one per rung of the ownership ladder:

| Option | Description | Selection |
|------|-------------|----------|
| **Use an agent you already have** | Vendor coding agents, the ACP catalog, and optional harness integrations | `:connect agents` |
| **Run a SuperQode harness on a model you choose** | Local engines, your API key, or a plan endpoint | `:connect models` |
| **Build your own harness for this repo** | Import, preset, wizard, or blank HarnessSpec | `:connect build` |

Each rung opens the specific methods underneath it:

| Method | Description | Selection |
|------|-------------|----------|
| **Local** | Local and self-hosted model servers | `:connect local` |
| **ACP (Agent Client Protocol)** | External coding agents with their own model and tools | `:connect acp` |
| **BYOK (Bring Your Own Key)** | Hosted model providers using your API key | `:connect byok` |
| **Plan endpoints** | A subscription that exposes a model endpoint to our harness | `:connect plan` |
| **Other harnesses** | Optional non-ACP harness integrations | `:connect other-harnesses` |
| **UHP** | Harnesses hosted on a Unified Harness Protocol server | `:connect uhp` |

Build routes are listed separately because they produce a repository artifact
rather than a connection:

| Build route | Description | Selection |
|------|-------------|----------|
| **Import** | Turn existing agent configuration into a HarnessSpec | `:connect build-import` |
| **Preset** | Clone a tuned built-in template into the repository | `:connect build-preset` |
| **Wizard** | Answer a few questions and generate a spec | `:connect build-wizard` |
| **Blank** | Write a minimal valid `harness.yaml` | `:connect build-blank` |

Tool and agent interoperability stays on its own commands: `:mcp` for Model
Context Protocol servers and `:a2a` for remote agent services.

Inside the TUI, `:explore` lists every capability category with its live state
on this machine, and `:tour` walks the ladder above.

### Ready-made agents

`:connect agents` lists the vendor coding agents that sign in with their
own account or licence. Every entry is also reachable by name, so the submenu is
a browsing aid rather than a required step. The legacy name `:connect
subscriptions` still opens the same screen:

| Vendor agent | Selection |
|------|----------|
| OpenAI Codex | `:connect codex` |
| Cursor | `:connect cursor` |
| Amp | `:connect amp` |
| Google Antigravity | `:connect antigravity` |
| xAI Grok | `:connect grok` |
| GitHub Copilot | `:connect copilot` |
| Cognition Devin | `:connect devin` |
| Factory Droid | `:connect droid` |
| Kiro / Amazon Q Developer | `:connect kiro` |
| GLM Coding Plan | `:connect glm-cli` |
| Qwen Code | `:connect qwen-code` |
| Kimi Code | `:connect kimi-code` |
| Vercel fx | `:connect fx`, `:connect fx-key`, `:fx` |

API-key-only integrations, including the Anthropic and Z.AI general APIs, are
listed under BYOK rather than Subscriptions. Factory Droid's own key is a
Closed harness, not BYOK: `:connect droid-key`.

Claude Pro and Max are intentionally not listed as SuperQode subscription
connections. Anthropic documents those plans for its first-party Claude Code
client, while API usage is billed separately. Use Anthropic BYOK or the
Claude Agent SDK runtime in SuperQode.

Each row shows live status on the screen itself, either `ready` or `needs setup`
with the exact command that fixes it.

---

## Quick Start

### BYOK (Cloud Providers)

```bash
# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Connect
superqode connect byok anthropic <anthropic-model>
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
# Start a local OpenAI-compatible server.
# Example: Ollama
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
| Anthropic | Claude Opus 4.8, Sonnet 4.6, Haiku 4.5 |
| OpenAI | GPT-5.5, GPT-5.4 |
| Google | Gemini 3.1 Pro/Flash |
| Deepseek | Deepseek V3, R1 |
| Mistral | Mistral Large |
| xAI | Grok 4.5, Grok 4.3, Grok Build 0.1 |
| Meta | Muse Spark 1.1 |

### Tier 2 (Supported)

Tested and supported:

| Provider | Models |
|----------|--------|
| (Model hosts and smaller providers) | Various models |

### Local Tier

Self-hosted options:

| Provider | Description |
|----------|-------------|
| DS4 | Purpose-built DeepSeek V4 Flash server for local coding and long-context work |
| Ollama | Easy local deployment |
| LM Studio | GUI-based local models |
| MLX | General Apple Silicon model serving |
| vLLM | High-performance inference |
| SGLang | Efficient structured generation |
| TGI | Text Generation Inference |
| llama.cpp | Lightweight CPU-first inference |

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
superqode providers test anthropic -m <anthropic-model>
```

---

## Configuration

### In superqode.yaml

```yaml
default:
  mode: byok
  provider: anthropic
  model: <anthropic-model>

providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    recommended_models:
      - <anthropic-model>
      - <anthropic-balanced-model>

  ollama:
    base_url: http://localhost:11434
    recommended_models:
      - qwen3:8b
```

---

## Provider Categories

### US Labs

| Provider | API Key Variable | Documentation |
|----------|------------------|---------------|
| `anthropic` | `ANTHROPIC_API_KEY` | [docs.anthropic.com](https://docs.anthropic.com) |
| `openai` | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| `google` | `GOOGLE_API_KEY` | [ai.google.dev](https://ai.google.dev) |
| `meta` | `META_MODEL_API_KEY` | [dev.meta.ai/docs](https://dev.meta.ai/docs) |
| `xai` | `XAI_API_KEY` | [x.ai/api](https://x.ai/api) |

### China Labs

| Provider | API Key Variable |
|----------|------------------|
| `deepseek` | `DEEPSEEK_API_KEY` |
| `zai` | `ZAI_API_KEY` ([setup](zai.md)) |
| `zhipu` | `ZHIPU_API_KEY` |
| `alibaba` | `ALIBABA_API_KEY` |

### Model Hosts

| Provider | API Key Variable | Notes |
|----------|------------------|-------|
| `baseten` | `BASETEN_API_KEY` | OpenAI-compatible Model APIs and dedicated inference |
| `openrouter` | `OPENROUTER_API_KEY` | 95+ models |
| `together` | `TOGETHER_API_KEY` | Open models |
| `groq` | `GROQ_API_KEY` | Fast inference |
| `fireworks` | `FIREWORKS_API_KEY` | Open models |
| `modal` | `MODAL_API_KEY` | Serverless GPUs; set `MODAL_BASE_URL` to your own deployment |

### Kimi K3

Kimi K3 is an open-weight model, so the same weights are served under a
different id by each host. Use the id belonging to the provider you connect to:

| Provider | Model id |
|----------|----------|
| `moonshot` | `kimi-k3` |
| `baseten` | `moonshot-ai/Kimi-K3` |
| `fireworks` | `accounts/fireworks/models/kimi-k3` |
| `together` | `moonshotai/Kimi-K3` |
| `openrouter` | `moonshotai/kimi-k3` |
| `siliconflow` | `moonshotai/Kimi-K3` |
| `vllm`, `sglang` | `moonshotai/Kimi-K3-MXFP4` |

Self-hosting is a datacenter exercise rather than a laptop one: the MXFP4
weights are roughly 594GB and Moonshot recommends 64 or more accelerators, so
`vllm` and `sglang` are the supported self-serve paths. Whichever route is
used, SuperQode applies the same `kimi` model pack (maximum reasoning,
parallel tools).

### Local Providers

| Provider | Default Port | Notes |
|----------|--------------|-------|
| `ollama` | 11434 | Easy setup |
| `lmstudio` | 1234 | GUI interface |
| `mlx` | 8080 | Apple Silicon |
| `vllm` | 8000 | Production |
| `sglang` | 30000 | Structured generation |
| `tgi` | 8080 | Hugging Face TGI |
| `llamacpp` | 8080 | Lightweight CPU inference |
| `ds4` | 8000 | Local DS4 server |

---

## Free Tiers

Some providers offer free access:

```bash
# List free providers
superqode providers list --category free
```

| Provider | Free Models |
|----------|------------|
| Google AI | gemini-flash-latest (limited) |
| Groq | llama-3.3-70b (rate limited) |
| OpenRouter | Some open models |

---

## Next Steps

- [BYOK Providers](byok.md) - Cloud provider setup
- [ACP Agents](acp.md) - Coding agent integration
- [Local Providers](local.md) - Self-hosted models
- [OpenResponses](openresponses.md) - Gateway configuration
- [Unified Harness Protocol](uhp.md) - Harnesses on a UHP server
