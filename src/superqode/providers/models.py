"""
SuperQode Model Database - Model pricing, features, and metadata.

Provides detailed information about LLM models including:
- Pricing (input/output per 1M tokens)
- Context window size
- Feature support (tools, vision, etc.)
- Recommendations

Usage:
    from superqode.providers.models import get_model_info, MODELS

    info = get_model_info("anthropic", "claude-sonnet-4")
    print(f"Price: ${info.input_price}/${info.output_price} per 1M tokens")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple


# ============================================================================
# MODEL INFO
# ============================================================================


class ModelCapability(Enum):
    """Model capabilities."""

    TOOLS = auto()  # Function calling / tools
    VISION = auto()  # Image input
    STREAMING = auto()  # Streaming output
    JSON_MODE = auto()  # Structured JSON output
    REASONING = auto()  # Extended thinking / reasoning
    CODE = auto()  # Optimized for code
    LONG_CONTEXT = auto()  # > 100K context


@dataclass
class ModelInfo:
    """Detailed model information."""

    id: str  # Model identifier
    name: str  # Human-readable name
    provider: str  # Provider ID

    # Pricing (per 1M tokens, USD)
    input_price: float = 0.0
    output_price: float = 0.0

    # Context
    context_window: int = 128000  # Max tokens
    max_output: int = 4096  # Max output tokens

    # Capabilities
    capabilities: List[ModelCapability] = field(default_factory=list)

    # Metadata
    description: str = ""
    recommended_for: List[str] = field(default_factory=list)
    released: str = ""  # Release date

    @property
    def supports_tools(self) -> bool:
        return ModelCapability.TOOLS in self.capabilities

    @property
    def supports_vision(self) -> bool:
        return ModelCapability.VISION in self.capabilities

    @property
    def supports_reasoning(self) -> bool:
        return ModelCapability.REASONING in self.capabilities

    @property
    def is_code_optimized(self) -> bool:
        return ModelCapability.CODE in self.capabilities

    @property
    def price_display(self) -> str:
        """Display-friendly pricing."""
        if self.input_price == 0 and self.output_price == 0:
            return "Free"
        return f"${self.input_price:.2f}/${self.output_price:.2f}"

    @property
    def context_display(self) -> str:
        """Display-friendly context window."""
        if self.context_window >= 1000000:
            return f"{self.context_window // 1000000}M"
        elif self.context_window >= 1000:
            return f"{self.context_window // 1000}K"
        return str(self.context_window)

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for given token counts."""
        input_cost = (input_tokens / 1_000_000) * self.input_price
        output_cost = (output_tokens / 1_000_000) * self.output_price
        return input_cost + output_cost


# ============================================================================
# MODEL DATABASE
# ============================================================================

MODELS: Dict[str, Dict[str, ModelInfo]] = {
    # =========================================================================
    # ANTHROPIC
    # =========================================================================
    "anthropic": {
        "claude-opus-4-5-20251101": ModelInfo(
            id="claude-opus-4-5-20251101",
            name="Claude Opus 4.5",
            provider="anthropic",
            input_price=15.0,
            output_price=75.0,
            context_window=200000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Most capable Claude model - latest flagship",
            recommended_for=["complex reasoning", "research", "difficult coding"],
            released="2025-11",
        ),
        "claude-sonnet-4-5-20250929": ModelInfo(
            id="claude-sonnet-4-5-20250929",
            name="Claude Sonnet 4.5",
            provider="anthropic",
            input_price=3.0,
            output_price=15.0,
            context_window=200000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Best balance of intelligence and speed",
            recommended_for=["coding", "analysis", "general"],
            released="2025-09",
        ),
        "claude-haiku-4-5-20251001": ModelInfo(
            id="claude-haiku-4-5-20251001",
            name="Claude Haiku 4.5",
            provider="anthropic",
            input_price=0.25,
            output_price=1.25,
            context_window=200000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Fastest and most cost-effective",
            recommended_for=["quick tasks", "high volume"],
            released="2025-10",
        ),
        "claude-sonnet-4-20250514": ModelInfo(
            id="claude-sonnet-4-20250514",
            name="Claude Sonnet 4",
            provider="anthropic",
            input_price=3.0,
            output_price=15.0,
            context_window=200000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Previous Sonnet generation",
            recommended_for=["coding", "analysis", "general"],
            released="2025-05",
        ),
        "claude-opus-4-20250514": ModelInfo(
            id="claude-opus-4-20250514",
            name="Claude Opus 4",
            provider="anthropic",
            input_price=15.0,
            output_price=75.0,
            context_window=200000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Previous Opus generation",
            recommended_for=["complex reasoning", "research", "difficult coding"],
            released="2025-05",
        ),
        "claude-haiku-4-20250514": ModelInfo(
            id="claude-haiku-4-20250514",
            name="Claude Haiku 4",
            provider="anthropic",
            input_price=0.25,
            output_price=1.25,
            context_window=200000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Previous Haiku generation",
            recommended_for=["quick tasks", "high volume"],
            released="2025-05",
        ),
    },
    # =========================================================================
    # OPENAI
    # =========================================================================
    "openai": {
        "gpt-5.2": ModelInfo(
            id="gpt-5.2",
            name="GPT-5.2",
            provider="openai",
            input_price=5.0,
            output_price=20.0,
            context_window=256000,
            max_output=32768,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Latest GPT-5 flagship with reasoning",
            recommended_for=["complex reasoning", "coding", "research"],
            released="2025-12",
        ),
        "gpt-5.2-pro": ModelInfo(
            id="gpt-5.2-pro",
            name="GPT-5.2 Pro",
            provider="openai",
            input_price=6.0,
            output_price=24.0,
            context_window=256000,
            max_output=32768,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="GPT-5.2 Pro variant - enhanced capabilities",
            recommended_for=["complex reasoning", "coding", "research"],
            released="2025-12",
        ),
        "gpt-5.2-codex": ModelInfo(
            id="gpt-5.2-codex",
            name="GPT-5.2 Codex",
            provider="openai",
            input_price=5.5,
            output_price=22.0,
            context_window=256000,
            max_output=32768,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="GPT-5.2 Codex variant - optimized for code",
            recommended_for=["coding", "code generation", "code review"],
            released="2025-12",
        ),
        "gpt-5.1": ModelInfo(
            id="gpt-5.1",
            name="GPT-5.1",
            provider="openai",
            input_price=4.0,
            output_price=16.0,
            context_window=200000,
            max_output=32768,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="GPT-5 series - highly capable",
            recommended_for=["general", "coding", "analysis"],
            released="2025-11",
        ),
        "gpt-5.1-codex": ModelInfo(
            id="gpt-5.1-codex",
            name="GPT-5.1 Codex",
            provider="openai",
            input_price=4.5,
            output_price=18.0,
            context_window=200000,
            max_output=32768,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="GPT-5.1 Codex variant - optimized for code",
            recommended_for=["coding", "code generation"],
            released="2025-11",
        ),
        "gpt-5.1-codex-mini": ModelInfo(
            id="gpt-5.1-codex-mini",
            name="GPT-5.1 Codex Mini",
            provider="openai",
            input_price=2.0,
            output_price=8.0,
            context_window=200000,
            max_output=16384,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="GPT-5.1 Codex Mini - fast and efficient for code",
            recommended_for=["quick coding", "code completion"],
            released="2025-11",
        ),
        "gpt-4o-2024-11-20": ModelInfo(
            id="gpt-4o-2024-11-20",
            name="GPT-4o (Nov 2024)",
            provider="openai",
            input_price=2.50,
            output_price=10.0,
            context_window=128000,
            max_output=16384,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="GPT-4o latest stable version",
            recommended_for=["general", "coding", "vision"],
            released="2024-11",
        ),
        "gpt-4o": ModelInfo(
            id="gpt-4o",
            name="GPT-4o",
            provider="openai",
            input_price=2.50,
            output_price=10.0,
            context_window=128000,
            max_output=16384,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Most capable GPT-4 variant",
            recommended_for=["general", "coding", "vision"],
            released="2024-05",
        ),
        "gpt-4o-mini": ModelInfo(
            id="gpt-4o-mini",
            name="GPT-4o Mini",
            provider="openai",
            input_price=0.15,
            output_price=0.60,
            context_window=128000,
            max_output=16384,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Fast and cost-effective",
            recommended_for=["quick tasks", "high volume"],
            released="2024-07",
        ),
        "o1": ModelInfo(
            id="o1",
            name="o1",
            provider="openai",
            input_price=15.0,
            output_price=60.0,
            context_window=200000,
            max_output=100000,
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Advanced reasoning model",
            recommended_for=["complex reasoning", "math", "science"],
            released="2024-09",
        ),
        "o1-mini": ModelInfo(
            id="o1-mini",
            name="o1-mini",
            provider="openai",
            input_price=3.0,
            output_price=12.0,
            context_window=128000,
            max_output=65536,
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Smaller reasoning model",
            recommended_for=["coding", "math"],
            released="2024-09",
        ),
    },
    # =========================================================================
    # GOOGLE
    # =========================================================================
    "google": {
        "gemini-3-pro-preview": ModelInfo(
            id="gemini-3-pro-preview",
            name="Gemini 3 Pro Preview",
            provider="google",
            input_price=2.0,
            output_price=8.0,
            context_window=2000000,
            max_output=16384,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Latest Gemini 3 flagship - most capable (2M context)",
            recommended_for=["complex reasoning", "large codebases", "research"],
            released="2025-12",
        ),
        "gemini-3-flash-preview": ModelInfo(
            id="gemini-3-flash-preview",
            name="Gemini 3 Flash Preview",
            provider="google",
            input_price=0.15,
            output_price=0.60,
            context_window=1000000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Gemini 3 fast model - 1M context (Latest)",
            recommended_for=["quick tasks", "high volume", "coding"],
            released="2025-12",
        ),
        "gemini-2.5-pro": ModelInfo(
            id="gemini-2.5-pro",
            name="Gemini 2.5 Pro",
            provider="google",
            input_price=1.25,
            output_price=5.0,
            context_window=2000000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Gemini 2.5 Pro with 2M context",
            recommended_for=["large codebases", "long documents"],
            released="2025-01",
        ),
        "gemini-2.5-flash": ModelInfo(
            id="gemini-2.5-flash",
            name="Gemini 2.5 Flash",
            provider="google",
            input_price=0.075,
            output_price=0.30,
            context_window=1000000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Fast and efficient with 1M context",
            recommended_for=["quick tasks", "high volume"],
            released="2025-01",
        ),
        "gemini-2.0-flash": ModelInfo(
            id="gemini-2.0-flash",
            name="Gemini 2.0 Flash",
            provider="google",
            input_price=0.10,
            output_price=0.40,
            context_window=1000000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Previous Flash generation",
            recommended_for=["general tasks"],
            released="2024-12",
        ),
    },
    # =========================================================================
    # DEEPSEEK
    # =========================================================================
    "deepseek": {
        "deepseek-ai/DeepSeek-V3.2": ModelInfo(
            id="deepseek-ai/DeepSeek-V3.2",
            name="DeepSeek V3.2",
            provider="deepseek",
            input_price=0.27,
            output_price=1.10,
            context_window=128000,
            max_output=16384,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Latest DeepSeek V3.2 - most capable",
            recommended_for=["complex reasoning", "coding", "research"],
            released="2025-12",
        ),
        "deepseek-ai/DeepSeek-R1": ModelInfo(
            id="deepseek-ai/DeepSeek-R1",
            name="DeepSeek R1",
            provider="deepseek",
            input_price=0.55,
            output_price=2.19,
            context_window=64000,
            max_output=8192,
            capabilities=[
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
                ModelCapability.CODE,
            ],
            description="Advanced reasoning model - R1 series",
            recommended_for=["complex reasoning", "math", "coding"],
            released="2025-01",
        ),
        "deepseek-chat": ModelInfo(
            id="deepseek-chat",
            name="DeepSeek Chat (V3)",
            provider="deepseek",
            input_price=0.14,
            output_price=0.28,
            context_window=64000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
            ],
            description="Very cost-effective general model",
            recommended_for=["general", "budget-conscious"],
            released="2024-12",
        ),
        "deepseek-coder": ModelInfo(
            id="deepseek-coder",
            name="DeepSeek Coder",
            provider="deepseek",
            input_price=0.14,
            output_price=0.28,
            context_window=64000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
            ],
            description="Specialized for coding tasks",
            recommended_for=["coding", "code review"],
            released="2024-12",
        ),
        "deepseek-reasoner": ModelInfo(
            id="deepseek-reasoner",
            name="DeepSeek Reasoner",
            provider="deepseek",
            input_price=0.55,
            output_price=2.19,
            context_window=64000,
            max_output=8192,
            capabilities=[
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
                ModelCapability.CODE,
            ],
            description="Advanced reasoning model",
            recommended_for=["complex reasoning", "math"],
            released="2025-01",
        ),
    },
    # =========================================================================
    # GROQ
    # =========================================================================
    "groq": {
        "llama-3.3-70b-versatile": ModelInfo(
            id="llama-3.3-70b-versatile",
            name="Llama 3.3 70B",
            provider="groq",
            input_price=0.59,
            output_price=0.79,
            context_window=128000,
            max_output=32768,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Very fast inference via Groq LPU",
            recommended_for=["speed-critical", "coding"],
            released="2024-12",
        ),
        "llama-3.1-8b-instant": ModelInfo(
            id="llama-3.1-8b-instant",
            name="Llama 3.1 8B Instant",
            provider="groq",
            input_price=0.05,
            output_price=0.08,
            context_window=128000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Ultra-fast small model",
            recommended_for=["quick tasks", "prototyping"],
            released="2024-07",
        ),
    },
    # =========================================================================
    # OPENROUTER
    # =========================================================================
    "openrouter": {
        "anthropic/claude-sonnet-4": ModelInfo(
            id="anthropic/claude-sonnet-4",
            name="Claude Sonnet 4 (via OpenRouter)",
            provider="openrouter",
            input_price=3.0,
            output_price=15.0,
            context_window=200000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Claude via OpenRouter",
            recommended_for=["coding", "general"],
        ),
        "openai/gpt-4o": ModelInfo(
            id="openai/gpt-4o",
            name="GPT-4o (via OpenRouter)",
            provider="openrouter",
            input_price=2.50,
            output_price=10.0,
            context_window=128000,
            max_output=16384,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="GPT-4o via OpenRouter",
            recommended_for=["general", "coding"],
        ),
        "google/gemini-2.0-flash": ModelInfo(
            id="google/gemini-2.0-flash",
            name="Gemini 2.0 Flash (via OpenRouter)",
            provider="openrouter",
            input_price=0.10,
            output_price=0.40,
            context_window=1000000,
            max_output=8192,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Gemini via OpenRouter",
            recommended_for=["long context"],
        ),
    },
    # =========================================================================
    # OLLAMA (Local - Free)
    # =========================================================================
    "ollama": {
        "llama3.2:3b": ModelInfo(
            id="llama3.2:3b",
            name="Llama 3.2 3B",
            provider="ollama",
            input_price=0.0,
            output_price=0.0,
            context_window=128000,
            max_output=4096,
            capabilities=[
                ModelCapability.STREAMING,
            ],
            description="Small local model",
            recommended_for=["quick local tasks"],
        ),
        "qwen2.5-coder:7b": ModelInfo(
            id="qwen2.5-coder:7b",
            name="Qwen 2.5 Coder 7B",
            provider="ollama",
            input_price=0.0,
            output_price=0.0,
            context_window=32000,
            max_output=4096,
            capabilities=[
                ModelCapability.STREAMING,
                ModelCapability.CODE,
            ],
            description="Local coding model",
            recommended_for=["local coding"],
        ),
        "qwen2.5-coder:32b": ModelInfo(
            id="qwen2.5-coder:32b",
            name="Qwen 2.5 Coder 32B",
            provider="ollama",
            input_price=0.0,
            output_price=0.0,
            context_window=32000,
            max_output=4096,
            capabilities=[
                ModelCapability.STREAMING,
                ModelCapability.CODE,
            ],
            description="Larger local coding model",
            recommended_for=["local coding", "complex tasks"],
        ),
    },
}


# ============================================================================
# LIVE DATA INTEGRATION (models.dev)
# ============================================================================

# Flag to track if live data is available
_live_models: Optional[Dict[str, Dict[str, ModelInfo]]] = None
_use_live_data: bool = False


def set_live_models(models: Dict[str, Dict[str, ModelInfo]]) -> None:
    """
    Set live model data from models.dev.

    Called by the models_dev module after fetching fresh data.
    """
    global _live_models, _use_live_data
    _live_models = models
    _use_live_data = True


def get_effective_models() -> Dict[str, Dict[str, ModelInfo]]:
    """
    Get the effective models database.

    Returns live data if available, otherwise falls back to hardcoded MODELS.
    """
    if _use_live_data and _live_models:
        # Merge: live data takes precedence, but keep hardcoded for missing providers
        merged = MODELS.copy()
        for provider_id, models in _live_models.items():
            if provider_id in merged:
                # Merge models within provider (live takes precedence)
                merged[provider_id] = {**merged[provider_id], **models}
            else:
                merged[provider_id] = models
        return merged
    return MODELS


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_model_info(provider_id: str, model_id: str) -> Optional[ModelInfo]:
    """Get model info by provider and model ID."""
    models = get_effective_models()
    provider_models = models.get(provider_id, {})

    # Try exact match first
    if model_id in provider_models:
        return provider_models[model_id]

    # Try fuzzy match (partial ID match)
    for mid, info in provider_models.items():
        if model_id in mid or mid in model_id:
            return info

    return None


def get_models_for_provider(provider_id: str) -> Dict[str, ModelInfo]:
    """Get all models for a provider, filtered to ensure they belong to that provider."""
    models = get_effective_models().get(provider_id, {})

    # Filter models to ensure they actually belong to this provider
    # This prevents models from other providers (e.g., GPT OSS) from appearing in Google's list
    filtered = {}
    for model_id, model_info in models.items():
        # Ensure the model's provider field matches the requested provider
        if model_info.provider == provider_id:
            filtered[model_id] = model_info
        # Special case for Google: only include Gemini models
        elif provider_id == "google":
            model_id_lower = model_id.lower()
            model_name_lower = model_info.name.lower() if model_info.name else ""
            # Only include if it's clearly a Gemini model
            if (
                ("gemini" in model_id_lower or "gemini" in model_name_lower)
                and "gpt" not in model_id_lower
                and "gpt" not in model_name_lower
            ):
                filtered[model_id] = model_info

    return filtered


def get_all_models() -> List[ModelInfo]:
    """Get all models across all providers."""
    all_models = []
    for provider_models in get_effective_models().values():
        all_models.extend(provider_models.values())
    return all_models


def get_all_providers() -> List[str]:
    """Get all available provider IDs."""
    return list(get_effective_models().keys())


def get_cheapest_models(limit: int = 5) -> List[ModelInfo]:
    """Get the cheapest models by input price."""
    all_models = get_all_models()
    sorted_models = sorted(all_models, key=lambda m: m.input_price)
    return sorted_models[:limit]


def get_models_with_capability(capability: ModelCapability) -> List[ModelInfo]:
    """Get models that have a specific capability."""
    return [m for m in get_all_models() if capability in m.capabilities]


def get_recommended_for_coding() -> List[ModelInfo]:
    """Get models recommended for coding."""
    return [m for m in get_all_models() if "coding" in m.recommended_for or m.is_code_optimized]


def search_models(query: str, limit: int = 20) -> List[ModelInfo]:
    """
    Search models by name, ID, or provider.

    Args:
        query: Search string (case-insensitive)
        limit: Maximum results to return
    """
    query_lower = query.lower()
    results = []

    for model in get_all_models():
        score = 0
        # Exact ID match
        if query_lower == model.id.lower():
            score = 100
        # ID contains query
        elif query_lower in model.id.lower():
            score = 80
        # Name contains query
        elif query_lower in model.name.lower():
            score = 60
        # Provider contains query
        elif query_lower in model.provider.lower():
            score = 40
        # Description contains query
        elif model.description and query_lower in model.description.lower():
            score = 20

        if score > 0:
            results.append((score, model))

    # Sort by score descending, then by name
    results.sort(key=lambda x: (-x[0], x[1].name))
    return [model for _, model in results[:limit]]


def estimate_session_cost(
    provider_id: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
) -> Tuple[float, str]:
    """
    Estimate cost for a session.

    Returns:
        (cost, formatted_string)
    """
    info = get_model_info(provider_id, model_id)
    if info:
        cost = info.estimate_cost(input_tokens, output_tokens)
        return cost, f"${cost:.4f}"
    return 0.0, "Unknown"


def is_using_live_data() -> bool:
    """Check if live models.dev data is being used."""
    return _use_live_data and _live_models is not None


def get_data_source() -> str:
    """Get a description of the current data source."""
    if is_using_live_data():
        return "models.dev (live)"
    return "built-in (offline)"


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ModelInfo",
    "ModelCapability",
    "MODELS",
    "get_model_info",
    "get_models_for_provider",
    "get_all_models",
    "get_all_providers",
    "get_cheapest_models",
    "get_models_with_capability",
    "get_recommended_for_coding",
    "search_models",
    "estimate_session_cost",
    "set_live_models",
    "get_effective_models",
    "is_using_live_data",
    "get_data_source",
]
