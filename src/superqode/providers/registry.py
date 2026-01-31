"""
Provider Registry for SuperQode BYOK (Bring Your Own Key) mode.

This module defines all supported LLM providers with their configuration,
environment variables, and metadata. Providers are organized into tiers
and categories for easy discovery.

SECURITY PRINCIPLE: SuperQode NEVER stores API keys.
All keys are read from user's environment variables at runtime.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ProviderTier(Enum):
    """Provider support tier."""

    TIER1 = 1  # First-class: Tested, documented, recommended
    TIER2 = 2  # Supported: Works via LiteLLM, basic docs
    FREE = 3  # Free tier providers (deprecated - use free_models instead)
    LOCAL = 4  # Local / self-hosted: needs URL only


class ProviderCategory(Enum):
    """Provider category for organization."""

    US_LABS = "US Labs"
    CHINA_LABS = "China Labs"
    OTHER_LABS = "Other Labs"
    MODEL_HOSTS = "Model Hosts"
    LOCAL = "Local / Self-Hosted"


@dataclass
class ProviderDef:
    """Definition of an LLM provider."""

    id: str
    name: str
    tier: ProviderTier
    category: ProviderCategory
    env_vars: List[str]
    litellm_prefix: str
    docs_url: str
    example_models: List[str] = field(default_factory=list)
    optional_env: List[str] = field(default_factory=list)
    base_url_env: Optional[str] = None
    default_base_url: Optional[str] = None
    notes: Optional[str] = None
    free_models: List[str] = field(default_factory=list)
    # Optional hint for how this provider is deployed (for LOCAL providers that also have cloud)
    # Values: "local", "cloud", or None
    deployment_mode: Optional[str] = None


# =============================================================================
# PROVIDER REGISTRY
# =============================================================================

PROVIDERS: Dict[str, ProviderDef] = {
    # =========================================================================
    # 🇺🇸 US LABS - Tier 1
    # =========================================================================
    "anthropic": ProviderDef(
        id="anthropic",
        name="Anthropic",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.US_LABS,
        env_vars=["ANTHROPIC_API_KEY"],
        litellm_prefix="anthropic/",
        docs_url="https://console.anthropic.com/",
        example_models=[
            "claude-opus-4-5-20251101",
            "claude-sonnet-4-5-20250929",
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-20250514",
            "claude-opus-4-20250514",
            "claude-haiku-4-20250514",
        ],
        notes="Best for coding tasks. Supports extended thinking.",
    ),
    "openai": ProviderDef(
        id="openai",
        name="OpenAI",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.US_LABS,
        env_vars=["OPENAI_API_KEY"],
        litellm_prefix="",
        base_url_env="OPENAI_API_BASE",
        docs_url="https://platform.openai.com/",
        example_models=[
            "gpt-5.2",
            "gpt-5.2-pro",
            "gpt-5.2-codex",
            "gpt-5.1",
            "gpt-5.1-codex",
            "gpt-5.1-codex-mini",
            "gpt-4o-2024-11-20",
            "gpt-4o",
            "gpt-4o-mini",
            "o1",
            "o1-mini",
        ],
        notes="Most popular. GPT-5.x for latest models, o1 for reasoning tasks.",
    ),
    "google": ProviderDef(
        id="google",
        name="Google AI (Gemini)",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.US_LABS,
        env_vars=["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        litellm_prefix="gemini/",
        docs_url="https://aistudio.google.com/",
        example_models=[
            "gemini-3-pro-preview",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-flash-latest",
        ],
        notes="2M token context. Gemini 3 is the latest. Great for large codebases.",
    ),
    "xai": ProviderDef(
        id="xai",
        name="xAI (Grok)",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.US_LABS,
        env_vars=["XAI_API_KEY"],
        litellm_prefix="xai/",
        docs_url="https://console.x.ai/",
        example_models=[
            "grok-3",
            "grok-3-mini",
            "grok-2",
            "grok-beta",
        ],
        notes="Good for coding. Fast inference.",
    ),
    "mistral": ProviderDef(
        id="mistral",
        name="Mistral AI",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.OTHER_LABS,
        env_vars=["MISTRAL_API_KEY"],
        litellm_prefix="mistral/",
        docs_url="https://console.mistral.ai/",
        example_models=[
            "mistral-large-2411",
            "mistral-medium-2505",
            "mistral-nemo",
            "codestral-latest",
            "mistral-small-latest",
        ],
        notes="Codestral is excellent for code generation.",
    ),
    "deepseek": ProviderDef(
        id="deepseek",
        name="DeepSeek",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.CHINA_LABS,
        env_vars=["DEEPSEEK_API_KEY"],
        litellm_prefix="deepseek/",
        docs_url="https://platform.deepseek.com/",
        example_models=[
            "deepseek-ai/DeepSeek-V3.2",
            "deepseek-ai/DeepSeek-R1",
            "deepseek-chat",
            "deepseek-coder",
            "deepseek-reasoner",
        ],
        notes="Extremely cost-effective. V3.2 is latest, R1 for reasoning.",
    ),
    # =========================================================================
    # 🇨🇳 CHINA LABS - Tier 1
    # =========================================================================
    "zhipu": ProviderDef(
        id="zhipu",
        name="Z.AI / Zhipu AI (GLM)",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.CHINA_LABS,
        env_vars=["ZHIPU_API_KEY", "GLM_API_KEY"],
        litellm_prefix="zhipuai/",
        docs_url="https://open.bigmodel.cn/",
        example_models=[
            "glm-4-plus",
            "glm-4",
            "glm-4-air",
            "glm-4-flash",
            "codegeex-4",
        ],
        notes="GLM-4 series. CodeGeeX for coding.",
    ),
    "alibaba": ProviderDef(
        id="alibaba",
        name="Alibaba (Qwen/DashScope)",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.CHINA_LABS,
        env_vars=["DASHSCOPE_API_KEY", "QWEN_API_KEY"],
        litellm_prefix="dashscope/",
        docs_url="https://dashscope.aliyun.com/",
        example_models=[
            "qwen-max",
            "qwen-plus",
            "qwen-turbo",
            "qwen2.5-coder-32b-instruct",
            "qwen2.5-72b-instruct",
        ],
        notes="Qwen 2.5 Coder is excellent. Long context support.",
    ),
    "minimax": ProviderDef(
        id="minimax",
        name="MiniMax",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.CHINA_LABS,
        env_vars=["MINIMAX_API_KEY"],
        optional_env=["MINIMAX_GROUP_ID"],
        litellm_prefix="minimax/",
        docs_url="https://api.minimax.chat/",
        example_models=[
            "abab6.5s-chat",
            "abab6.5-chat",
            "abab5.5-chat",
        ],
        notes="Good multilingual support.",
    ),
    "moonshot": ProviderDef(
        id="moonshot",
        name="Moonshot AI (Kimi)",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.CHINA_LABS,
        env_vars=["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        litellm_prefix="moonshot/",
        docs_url="https://platform.moonshot.cn/",
        example_models=[
            "moonshot-v1-128k",
            "moonshot-v1-32k",
            "moonshot-v1-8k",
            "kimi-k2",
        ],
        notes="Kimi K2 is their latest. 128K context.",
    ),
    "siliconflow": ProviderDef(
        id="siliconflow",
        name="Silicon Flow",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["SILICONFLOW_API_KEY", "SILICON_API_KEY"],
        litellm_prefix="siliconflow/",
        docs_url="https://siliconflow.cn/",
        example_models=[
            "deepseek-ai/DeepSeek-V3",
            "Qwen/Qwen2.5-72B-Instruct",
            "meta-llama/Llama-3.3-70B-Instruct",
        ],
        notes="Chinese model aggregator. Good pricing.",
    ),
    "baidu": ProviderDef(
        id="baidu",
        name="Baidu (ERNIE)",
        tier=ProviderTier.TIER2,
        category=ProviderCategory.CHINA_LABS,
        env_vars=["QIANFAN_API_KEY"],
        optional_env=["QIANFAN_SECRET_KEY"],
        litellm_prefix="qianfan/",
        docs_url="https://cloud.baidu.com/product/wenxinworkshop",
        example_models=[
            "ernie-4.0-8k",
            "ernie-3.5-8k",
            "ernie-speed-8k",
        ],
        notes="ERNIE series from Baidu.",
    ),
    "doubao": ProviderDef(
        id="doubao",
        name="ByteDance (Doubao)",
        tier=ProviderTier.TIER2,
        category=ProviderCategory.CHINA_LABS,
        env_vars=["DOUBAO_API_KEY", "VOLCENGINE_API_KEY"],
        litellm_prefix="volcengine/",
        docs_url="https://www.volcengine.com/product/doubao",
        example_models=[
            "doubao-pro-32k",
            "doubao-lite-32k",
        ],
        notes="ByteDance's LLM offering.",
    ),
    # =========================================================================
    # 🌐 MODEL HOSTS / AGGREGATORS - Tier 1
    # =========================================================================
    "openrouter": ProviderDef(
        id="openrouter",
        name="OpenRouter",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["OPENROUTER_API_KEY"],
        litellm_prefix="openrouter/",
        docs_url="https://openrouter.ai/",
        example_models=[
            "anthropic/claude-sonnet-4",
            "openai/gpt-4o",
            "google/gemini-2.0-flash",
            "meta-llama/llama-3.3-70b-instruct",
        ],
        notes="Access 200+ models. Single API key. Auto-fallback.",
    ),
    "together": ProviderDef(
        id="together",
        name="Together AI",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["TOGETHER_API_KEY", "TOGETHERAI_API_KEY"],
        litellm_prefix="together_ai/",
        docs_url="https://api.together.xyz/",
        example_models=[
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "Qwen/Qwen2.5-Coder-32B-Instruct",
            "deepseek-ai/DeepSeek-R1",
            "mistralai/Mixtral-8x22B-Instruct-v0.1",
        ],
        notes="Fast inference. Good for open-source models.",
    ),
    "groq": ProviderDef(
        id="groq",
        name="Groq",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["GROQ_API_KEY"],
        litellm_prefix="groq/",
        docs_url="https://console.groq.com/",
        example_models=[
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ],
        free_models=[
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ],
        notes="Fastest inference. LPU hardware. Free tier available.",
    ),
    "fireworks": ProviderDef(
        id="fireworks",
        name="Fireworks AI",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["FIREWORKS_API_KEY"],
        litellm_prefix="fireworks_ai/",
        docs_url="https://fireworks.ai/",
        example_models=[
            "accounts/fireworks/models/llama-v3p3-70b-instruct",
            "accounts/fireworks/models/qwen2p5-coder-32b-instruct",
            "accounts/fireworks/models/deepseek-r1",
        ],
        notes="Fast inference. Good function calling support.",
    ),
    "huggingface": ProviderDef(
        id="huggingface",
        name="Hugging Face",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["HUGGINGFACE_API_KEY", "HF_TOKEN"],
        litellm_prefix="huggingface/",
        docs_url="https://huggingface.co/inference-api",
        example_models=[
            "meta-llama/Llama-3.3-70B-Instruct",
            "Qwen/Qwen2.5-72B-Instruct",
            "mistralai/Mistral-7B-Instruct-v0.3",
        ],
        notes="Inference API. Access to most open models.",
    ),
    "cerebras": ProviderDef(
        id="cerebras",
        name="Cerebras",
        tier=ProviderTier.TIER2,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["CEREBRAS_API_KEY"],
        litellm_prefix="cerebras/",
        docs_url="https://cloud.cerebras.ai/",
        example_models=[
            "llama3.1-8b",
            "llama3.1-70b",
        ],
        notes="Wafer-scale inference. Very fast.",
    ),
    "perplexity": ProviderDef(
        id="perplexity",
        name="Perplexity",
        tier=ProviderTier.TIER2,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["PERPLEXITY_API_KEY"],
        litellm_prefix="perplexity/",
        docs_url="https://docs.perplexity.ai/",
        example_models=[
            "sonar-pro",
            "sonar",
            "sonar-reasoning",
        ],
        notes="Built-in web search. Good for research tasks.",
    ),
    "cohere": ProviderDef(
        id="cohere",
        name="Cohere",
        tier=ProviderTier.TIER2,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["COHERE_API_KEY"],
        litellm_prefix="cohere/",
        docs_url="https://dashboard.cohere.com/",
        example_models=[
            "command-r-plus",
            "command-r",
            "command",
        ],
        notes="Good for RAG and enterprise use cases.",
    ),
    # =========================================================================
    # 🆓 FREE TIER PROVIDERS (by pricing) - Tier 1
    # =========================================================================
    "opencode": ProviderDef(
        id="opencode",
        name="OpenCode Zen",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["OPENCODE_API_KEY"],
        litellm_prefix="openai/",
        base_url_env="OPENCODE_BASE_URL",
        default_base_url="https://api.opencode.ai/v1",
        docs_url="https://opencode.ai/docs/providers/opencode-zen",
        example_models=[
            "glm-4.7-free",
            "grok-code",
            "kimi-k2.5-free",
            "gpt-5-nano",
            "minimax-m2.1-free",
            "big-pickle",
        ],
        free_models=[
            "glm-4.7-free",
            "grok-code",
            "kimi-k2.5-free",
            "gpt-5-nano",
            "minimax-m2.1-free",
            "big-pickle",
        ],
        notes="Free models from OpenCode. Some require API key for paid tiers.",
    ),
    "github-copilot": ProviderDef(
        id="github-copilot",
        name="GitHub Copilot",
        tier=ProviderTier.TIER1,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["GITHUB_TOKEN"],
        litellm_prefix="github/",
        docs_url="https://github.com/features/copilot",
        example_models=[
            "gpt-4o",
            "claude-3.5-sonnet",
            "o1-mini",
            "o1-preview",
        ],
        notes="Requires GitHub Pro/Enterprise subscription. OAuth flow required.",
    ),
    # =========================================================================
    # ☁️ CLOUD PLATFORMS / MODEL HOSTS - Tier 2
    # =========================================================================
    "amazon-bedrock": ProviderDef(
        id="amazon-bedrock",
        name="Amazon Bedrock",
        tier=ProviderTier.TIER2,
        category=ProviderCategory.US_LABS,
        env_vars=["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
        optional_env=["AWS_REGION", "AWS_PROFILE", "AWS_BEARER_TOKEN_BEDROCK"],
        litellm_prefix="bedrock/",
        docs_url="https://aws.amazon.com/bedrock/",
        example_models=[
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "anthropic.claude-3-haiku-20240307-v1:0",
            "amazon.nova-pro-v1:0",
            "meta.llama3-1-70b-instruct-v1:0",
        ],
        notes="AWS managed. Supports Claude, Llama, Nova.",
    ),
    "azure": ProviderDef(
        id="azure",
        name="Azure OpenAI",
        tier=ProviderTier.TIER2,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["AZURE_API_KEY", "AZURE_API_BASE"],
        optional_env=["AZURE_API_VERSION", "AZURE_DEPLOYMENT_NAME"],
        litellm_prefix="azure/",
        docs_url="https://azure.microsoft.com/products/ai-services/openai-service",
        example_models=[
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-35-turbo",
        ],
        notes="Enterprise Azure. Use deployment names as model IDs.",
    ),
    "vertex": ProviderDef(
        id="vertex",
        name="Google Vertex AI",
        tier=ProviderTier.TIER2,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["GOOGLE_APPLICATION_CREDENTIALS"],
        optional_env=["VERTEX_PROJECT", "VERTEX_LOCATION"],
        litellm_prefix="vertex_ai/",
        docs_url="https://cloud.google.com/vertex-ai",
        example_models=[
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "claude-3-5-sonnet@20241022",
        ],
        notes="GCP managed. Supports Gemini and Claude.",
    ),
    "cloudflare": ProviderDef(
        id="cloudflare",
        name="Cloudflare AI Gateway",
        tier=ProviderTier.TIER2,
        category=ProviderCategory.MODEL_HOSTS,
        env_vars=["CLOUDFLARE_API_TOKEN"],
        optional_env=["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_GATEWAY_ID"],
        litellm_prefix="cloudflare/",
        docs_url="https://developers.cloudflare.com/ai-gateway/",
        example_models=[
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
            "@cf/qwen/qwen2.5-coder-32b-instruct",
        ],
        notes="Edge inference. Unified billing across providers.",
    ),
    # =========================================================================
    # 🏠 LOCAL/SELF-HOSTED - Local Tier
    # =========================================================================
    "ollama": ProviderDef(
        id="ollama",
        name="Ollama",
        tier=ProviderTier.LOCAL,
        category=ProviderCategory.LOCAL,
        env_vars=[],
        base_url_env="OLLAMA_HOST",
        default_base_url="http://localhost:11434",
        litellm_prefix="ollama/",
        docs_url="https://ollama.ai/",
        example_models=[
            "llama3.2:3b",
            "llama3.2:1b",
            "qwen2.5-coder:7b",
            "qwen2.5-coder:32b",
            "codellama:7b",
            "deepseek-coder-v2:16b",
            "mistral:7b",
        ],
        notes="Local models. Run: ollama pull <model>",
        deployment_mode="local",
    ),
    "ollama-cloud": ProviderDef(
        id="ollama-cloud",
        name="Ollama Cloud",
        tier=ProviderTier.LOCAL,
        category=ProviderCategory.LOCAL,
        env_vars=["OLLAMA_API_KEY"],
        litellm_prefix="ollama/",
        base_url_env="OLLAMA_HOST",
        default_base_url="https://api.ollama.com",
        docs_url="https://ollama.com/",
        example_models=[
            "llama3.2:3b",
            "qwen2.5-coder:7b",
        ],
        notes="Ollama's hosted cloud service.",
        deployment_mode="cloud",
    ),
    "lmstudio": ProviderDef(
        id="lmstudio",
        name="LM Studio",
        tier=ProviderTier.LOCAL,
        category=ProviderCategory.LOCAL,
        env_vars=[],
        base_url_env="LMSTUDIO_HOST",
        default_base_url="http://localhost:1234/v1",  # LM Studio serves at /v1
        litellm_prefix="openai/",
        docs_url="https://lmstudio.ai/",
        example_models=[
            "local-model",
        ],
        notes="GUI for local models. OpenAI-compatible API. Default: http://localhost:1234/v1",
    ),
    "mlx": ProviderDef(
        id="mlx",
        name="MLX (Apple Silicon)",
        tier=ProviderTier.LOCAL,
        category=ProviderCategory.LOCAL,
        env_vars=[],
        base_url_env="MLX_HOST",
        default_base_url="http://localhost:8080/v1",
        litellm_prefix="openai/",
        docs_url="https://github.com/ml-explore/mlx-lm",
        example_models=[
            "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit",
            "mlx-community/Mistral-7B-Instruct-v0.1",
            "mlx-community/Llama-2-7b-chat-hf",
            "SuperagenticAI/gpt-oss-20b-8bit-mlx",
            "mlx-community/Phi-2",
            "mlx-community/OpenHermes-2.5-Mistral-7B",
        ],
        notes="Apple Silicon optimized. Run: mlx_lm.server --model <model-id>",
    ),
    "vllm": ProviderDef(
        id="vllm",
        name="vLLM",
        tier=ProviderTier.LOCAL,
        category=ProviderCategory.LOCAL,
        env_vars=[],
        base_url_env="VLLM_HOST",
        default_base_url="http://localhost:8000/v1",
        litellm_prefix="openai/",
        docs_url="https://docs.vllm.ai/",
        example_models=[
            "meta-llama/Llama-3.3-70B-Instruct",
        ],
        notes="High-throughput serving. PagedAttention.",
    ),
    "sglang": ProviderDef(
        id="sglang",
        name="SGLang",
        tier=ProviderTier.LOCAL,
        category=ProviderCategory.LOCAL,
        env_vars=[],
        base_url_env="SGLANG_HOST",
        default_base_url="http://localhost:30000/v1",
        litellm_prefix="openai/",
        docs_url="https://github.com/sgl-project/sglang",
        example_models=[
            "meta-llama/Llama-3.3-70B-Instruct",
        ],
        notes="Fast structured generation. RadixAttention.",
    ),
    "tgi": ProviderDef(
        id="tgi",
        name="TGI (Text Generation Inference)",
        tier=ProviderTier.LOCAL,
        category=ProviderCategory.LOCAL,
        env_vars=[],
        base_url_env="TGI_HOST",
        default_base_url="http://localhost:8080",
        litellm_prefix="huggingface/",
        docs_url="https://huggingface.co/docs/text-generation-inference",
        example_models=[
            "meta-llama/Llama-3.3-70B-Instruct",
        ],
        notes="HuggingFace's inference server. Production-ready.",
    ),
    "llamacpp": ProviderDef(
        id="llamacpp",
        name="llama.cpp Server",
        tier=ProviderTier.LOCAL,
        category=ProviderCategory.LOCAL,
        env_vars=[],
        base_url_env="LLAMACPP_HOST",
        default_base_url="http://localhost:8080/v1",
        litellm_prefix="openai/",
        docs_url="https://github.com/ggerganov/llama.cpp",
        example_models=[
            "local-model",
        ],
        notes="CPU/GPU inference. GGUF format models.",
    ),
    "openai-compatible": ProviderDef(
        id="openai-compatible",
        name="OpenAI-Compatible (Custom)",
        tier=ProviderTier.LOCAL,
        category=ProviderCategory.LOCAL,
        env_vars=["OPENAI_COMPATIBLE_API_KEY"],
        base_url_env="OPENAI_COMPATIBLE_BASE_URL",
        litellm_prefix="openai/",
        docs_url="",
        example_models=[],
        notes="Any OpenAI-compatible API endpoint.",
    ),
    "huggingface-local": ProviderDef(
        id="huggingface-local",
        name="Hugging Face (Local Cache)",
        tier=ProviderTier.LOCAL,
        category=ProviderCategory.LOCAL,
        env_vars=[],
        litellm_prefix="huggingface/",
        docs_url="https://huggingface.co/docs/hub/index",
        example_models=[],
        notes="Select locally cached HF models; routes to a local runtime (mlx/tgi/vllm/sglang).",
    ),
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_provider(provider_id: str) -> Optional[ProviderDef]:
    """Get a provider definition by ID."""
    return PROVIDERS.get(provider_id)


def get_providers_by_category(category: ProviderCategory) -> Dict[str, ProviderDef]:
    """Get all providers in a category."""
    return {k: v for k, v in PROVIDERS.items() if v.category == category}


def get_providers_by_tier(tier: ProviderTier) -> Dict[str, ProviderDef]:
    """Get all providers in a tier."""
    return {k: v for k, v in PROVIDERS.items() if v.tier == tier}


def get_all_provider_ids() -> List[str]:
    """Get all provider IDs."""
    return list(PROVIDERS.keys())


def get_free_providers() -> Dict[str, ProviderDef]:
    """Get providers with free tiers or free models."""
    return {k: v for k, v in PROVIDERS.items() if v.free_models}


def get_local_providers() -> Dict[str, ProviderDef]:
    """Get local/self-hosted providers."""
    return {k: v for k, v in PROVIDERS.items() if v.category == ProviderCategory.LOCAL}
