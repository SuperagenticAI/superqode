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
from typing import Any, Dict, List, Optional, Tuple

LATEST_GOOGLE_PRO_MODEL = "gemini-3.1-pro-preview"
LATEST_GOOGLE_FLASH_MODEL = "gemini-flash-latest"
LATEST_GOOGLE_MODEL_IDS = (LATEST_GOOGLE_PRO_MODEL, LATEST_GOOGLE_FLASH_MODEL)
CURRENT_MODEL_LIMIT = 6
LOCAL_MODEL_PROVIDERS = {
    "ds4",
    "ollama",
    "lmstudio",
    "mlx",
    "vllm",
    "sglang",
    "tgi",
    "llamacpp",
    "huggingface-local",
    "openai-compatible",
}
NON_CHAT_MODEL_MARKERS = (
    "audio",
    "caption",
    "classif",
    "embed",
    "image",
    "moderation",
    "realtime",
    "rerank",
    "speech",
    "tts",
    "video",
    "vision-preview",
)


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
        "claude-opus-4-8": ModelInfo(
            id="claude-opus-4-8",
            name="Claude Opus 4.8",
            provider="anthropic",
            input_price=5.0,
            output_price=25.0,
            context_window=1000000,
            max_output=128000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Latest Claude Opus model from models.dev",
            recommended_for=["complex reasoning", "research", "difficult coding"],
            released="2026-05",
        ),
        "claude-opus-4-7": ModelInfo(
            id="claude-opus-4-7",
            name="Claude Opus 4.7",
            provider="anthropic",
            input_price=5.0,
            output_price=25.0,
            context_window=1000000,
            max_output=128000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Recent Claude Opus model with 1M context",
            recommended_for=["complex reasoning", "research", "difficult coding"],
            released="2026-04",
        ),
        "claude-sonnet-4-6": ModelInfo(
            id="claude-sonnet-4-6",
            name="Claude Sonnet 4.6",
            provider="anthropic",
            input_price=3.0,
            output_price=15.0,
            context_window=1000000,
            max_output=64000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Latest Claude Sonnet coding model with 1M context",
            recommended_for=["coding", "analysis", "general"],
            released="2026-02",
        ),
        "claude-opus-4-6": ModelInfo(
            id="claude-opus-4-6",
            name="Claude Opus 4.6",
            provider="anthropic",
            input_price=5.0,
            output_price=25.0,
            context_window=1000000,
            max_output=128000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Previous Claude Opus model with 1M context",
            recommended_for=["complex reasoning", "research", "difficult coding"],
            released="2026-02",
        ),
        "claude-opus-4-5": ModelInfo(
            id="claude-opus-4-5",
            name="Claude Opus 4.5",
            provider="anthropic",
            input_price=5.0,
            output_price=25.0,
            context_window=200000,
            max_output=64000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Claude Opus 4.5 alias from models.dev",
            recommended_for=["complex reasoning", "research", "difficult coding"],
            released="2025-11",
        ),
        "claude-haiku-4-5": ModelInfo(
            id="claude-haiku-4-5",
            name="Claude Haiku 4.5",
            provider="anthropic",
            input_price=1.0,
            output_price=5.0,
            context_window=200000,
            max_output=64000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Fast and cost-effective Claude model",
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
        "gpt-5.4": ModelInfo(
            id="gpt-5.4",
            name="GPT-5.4",
            provider="openai",
            input_price=2.5,
            output_price=15.0,
            context_window=1000000,
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
            description="Latest GPT-5 flagship with stronger coding, agentic workflows, and 1M-token context",
            recommended_for=["coding", "agentic tasks", "research", "complex reasoning"],
            released="2026-03",
        ),
        "gpt-5.4-pro": ModelInfo(
            id="gpt-5.4-pro",
            name="GPT-5.4 Pro",
            provider="openai",
            input_price=30.0,
            output_price=180.0,
            context_window=1000000,
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
            description="Highest-capability GPT-5.4 tier for demanding reasoning and coding workloads",
            recommended_for=["frontier reasoning", "hard coding", "complex research"],
            released="2026-03",
        ),
        "gpt-5.3-codex": ModelInfo(
            id="gpt-5.3-codex",
            name="GPT-5.3 Codex",
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
            description="Previous GPT Codex-specialized model optimized for coding",
            recommended_for=["coding", "code generation", "code review"],
            released="2026-01",
        ),
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
            description="Prior GPT-5 flagship with reasoning",
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
        "gemini-3.1-pro-preview": ModelInfo(
            id="gemini-3.1-pro-preview",
            name="Gemini 3.1 Pro Preview",
            provider="google",
            input_price=2.0,
            output_price=8.0,
            context_window=2000000,
            max_output=65536,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Latest general Gemini Pro model listed by models.dev",
            recommended_for=["complex reasoning", "large codebases", "research"],
            released="2026-02",
        ),
        "gemini-flash-latest": ModelInfo(
            id="gemini-flash-latest",
            name="Gemini Flash Latest",
            provider="google",
            input_price=0.15,
            output_price=0.60,
            context_window=1000000,
            max_output=65536,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Latest Gemini Flash alias listed by models.dev",
            recommended_for=["quick tasks", "high volume", "coding"],
            released="2025-09",
        ),
    },
    # =========================================================================
    # xAI
    # =========================================================================
    "xai": {
        "grok-4.5": ModelInfo(
            id="grok-4.5",
            name="Grok 4.5",
            provider="xai",
            input_price=2.0,
            output_price=6.0,
            context_window=500000,
            max_output=500000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="xAI's flagship model for agentic coding and reasoning (effort low/medium/high).",
            recommended_for=["agentic coding", "complex reasoning", "research"],
            released="2026-07-08",
        ),
        "grok-4.3": ModelInfo(
            id="grok-4.3",
            name="Grok 4.3",
            provider="xai",
            input_price=1.25,
            output_price=2.5,
            context_window=1000000,
            max_output=30000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="1M-context Grok for document-heavy work at a lower price than Grok 4.5.",
            recommended_for=["long context", "coding", "document analysis"],
            released="2026-04-17",
        ),
        "grok-build-0.1": ModelInfo(
            id="grok-build-0.1",
            name="Grok Build 0.1",
            provider="xai",
            input_price=1.0,
            output_price=2.0,
            context_window=256000,
            max_output=256000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.JSON_MODE,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Fast coding model behind Grok Build, tuned for agentic engineering loops.",
            recommended_for=["coding", "iterative edits", "fast agentic loops"],
            released="2026-04-16",
        ),
    },
    # =========================================================================
    # GROK CLI SUBSCRIPTION (direct API via the local `grok login` session)
    # =========================================================================
    "grok-cli": {
        "grok-build": ModelInfo(
            id="grok-build",
            name="Grok Build (default)",
            provider="grok-cli",
            context_window=500000,
            max_output=500000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="The CLI's default-model alias (currently Grok 4.5); included with the subscription.",
            recommended_for=["coding", "agentic coding"],
            released="2026-07-08",
        ),
        "grok-4.5": ModelInfo(
            id="grok-4.5",
            name="Grok 4.5",
            provider="grok-cli",
            context_window=500000,
            max_output=500000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Flagship Grok on your subscription (eligibility decided by xAI).",
            recommended_for=["agentic coding", "complex reasoning"],
            released="2026-07-08",
        ),
        "grok-4.3": ModelInfo(
            id="grok-4.3",
            name="Grok 4.3",
            provider="grok-cli",
            context_window=1000000,
            max_output=30000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="1M-context Grok on your subscription.",
            recommended_for=["long context", "document analysis"],
            released="2026-04-17",
        ),
        "grok-build-0.1": ModelInfo(
            id="grok-build-0.1",
            name="Grok Build 0.1",
            provider="grok-cli",
            context_window=256000,
            max_output=256000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Fast coding model on your subscription.",
            recommended_for=["coding", "fast agentic loops"],
            released="2026-04-16",
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
        "google/gemini-flash-latest": ModelInfo(
            id="google/gemini-flash-latest",
            name="Gemini Flash Latest (via OpenRouter)",
            provider="openrouter",
            input_price=0.15,
            output_price=0.60,
            context_window=1000000,
            max_output=65536,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.VISION,
                ModelCapability.STREAMING,
                ModelCapability.LONG_CONTEXT,
            ],
            description="Latest Gemini Flash via OpenRouter",
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
    # =========================================================================
    # DS4 / DEEPSEEK V4 FLASH (Local - Free)
    # =========================================================================
    "ds4": {
        "deepseek-v4-flash": ModelInfo(
            id="deepseek-v4-flash",
            name="DeepSeek V4 Flash",
            provider="ds4",
            input_price=0.0,
            output_price=0.0,
            context_window=1000000,
            max_output=384000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="DeepSeek V4 Flash served locally by antirez/ds4.",
            recommended_for=["coding", "large-context", "local coding", "agentic tasks"],
        ),
        "deepseek-chat": ModelInfo(
            id="deepseek-chat",
            name="DeepSeek V4 Flash (no thinking)",
            provider="ds4",
            input_price=0.0,
            output_price=0.0,
            context_window=1000000,
            max_output=384000,
            capabilities=[
                ModelCapability.TOOLS,
                ModelCapability.STREAMING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            description="DS4 non-thinking model alias for direct replies.",
            recommended_for=["coding", "quick local tasks", "local coding"],
        ),
    },
}


# ============================================================================
# LIVE DATA INTEGRATION (models.dev)
# ============================================================================

# Flag to track if live data is available
_live_models: Optional[Dict[str, Dict[str, ModelInfo]]] = None
_use_live_data: bool = False


_live_autoload_attempted: bool = False


def set_live_models(models: Dict[str, Dict[str, ModelInfo]]) -> None:
    """
    Set live model data from models.dev.

    Called by the models_dev module after fetching fresh data.
    """
    global _live_models, _use_live_data
    _live_models = models
    _use_live_data = True


def _maybe_autoload_live_models() -> None:
    """Populate live models from the on-disk models.dev cache, once, on demand.

    This is what makes new models appear automatically: any consumer of the
    model lists (CLI, TUI, pickers) transparently picks up the latest models.dev
    cache without a manual list update or explicit wiring. Sync + offline (reads
    the cache only); a fresh network refresh still happens via the normal
    ``models_dev`` paths and overrides this.
    """
    global _live_autoload_attempted
    if _use_live_data or _live_autoload_attempted:
        return
    _live_autoload_attempted = True
    try:
        from .models_dev import get_models_dev

        client = get_models_dev()
        if not client.ensure_cache_loaded():
            return
        live: Dict[str, Dict[str, ModelInfo]] = {}
        for provider_id in client.get_providers():
            models = client.get_models_for_provider(provider_id)
            if models:
                live[provider_id] = models
        if live:
            set_live_models(live)
    except Exception:  # noqa: BLE001 - live data is optional
        pass


def _newest_release(models: Dict[str, ModelInfo]) -> str:
    """Newest ISO release date in a provider's model list ('' if none dated)."""
    return max((m.released or "" for m in models.values()), default="")


def get_effective_models() -> Dict[str, Dict[str, ModelInfo]]:
    """
    Get the effective models database.

    Returns live data if available, otherwise falls back to hardcoded MODELS.
    Lazily self-loads the models.dev cache on first use so new models surface
    automatically.
    """
    _maybe_autoload_live_models()
    if _use_live_data and _live_models:
        # Live data replaces provider model lists. Keep built-ins only for providers
        # absent from models.dev/cache so stale built-in models do not leak into BYOK.
        merged = MODELS.copy()
        for provider_id, models in _live_models.items():
            # A stale models.dev cache (e.g. a CLI session on a machine whose
            # TUI hasn't refreshed in months) must not shadow a curated builtin
            # list that already knows about newer models. When both sides have
            # release dates, whichever list has the newer model wins; a fresh
            # cache always satisfies this and replaces the builtin as before.
            builtin = merged.get(provider_id)
            if builtin:
                live_newest = _newest_release(models)
                if live_newest and _newest_release(builtin) > live_newest:
                    continue
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


def get_models_for_provider(provider_id: str, *, include_all: bool = False) -> Dict[str, ModelInfo]:
    """Get provider models, optionally retaining the complete live catalog.

    The default remains compact for recommendations and small status surfaces.
    BYOK selection, direct connection completion, and catalog browsing pass
    ``include_all=True`` so a new models.dev entry cannot be hidden by that
    presentation-oriented trimming.
    """
    # The Grok subscription catalog is whatever the signed-in CLI reports;
    # its order matches the CLI's own /model picker, so return it as-is.
    if provider_id == "grok-cli":
        live_cli = _grok_cli_live_catalog()
        if live_cli:
            return live_cli

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

    if include_all:
        if provider_id not in LOCAL_MODEL_PROVIDERS:
            # Full catalogs read newest-first too (pickers, search, completion).
            # Local server tags have no release dates; keep their server order.
            ordered = sorted(filtered.values(), key=_hosted_model_sort_key, reverse=True)
            return {model.id: model for model in ordered}
        return filtered
    if provider_id == "google":
        return _latest_google_models(filtered)
    if provider_id not in LOCAL_MODEL_PROVIDERS:
        return _current_hosted_models(filtered)

    return filtered


def _latest_google_models(models: Dict[str, ModelInfo]) -> Dict[str, ModelInfo]:
    """Keep BYOK Google model lists focused on the current Pro and Flash choices."""
    latest: Dict[str, ModelInfo] = {}

    pro = _select_google_model(models, kind="pro")
    flash = _select_google_model(models, kind="flash")

    if pro:
        latest[pro.id] = pro
    if flash and flash.id not in latest:
        latest[flash.id] = flash
    return latest


def _select_google_model(models: Dict[str, ModelInfo], *, kind: str) -> ModelInfo | None:
    alias = "gemini-pro-latest" if kind == "pro" else LATEST_GOOGLE_FLASH_MODEL
    if alias in models:
        return models[alias]

    candidates: list[ModelInfo] = []
    for model in models.values():
        model_id = model.id.lower()
        name = model.name.lower()
        text = f"{model_id} {name}"
        if "gemini" not in text or kind not in text:
            continue
        if any(skip in text for skip in ("lite", "image", "tts", "customtools")):
            continue
        candidates.append(model)

    if not candidates:
        fallback = LATEST_GOOGLE_PRO_MODEL if kind == "pro" else LATEST_GOOGLE_FLASH_MODEL
        return models.get(fallback)

    return max(candidates, key=_model_recency_key)


def _model_recency_key(model: ModelInfo) -> tuple[str, str]:
    return (model.released or "", model.id)


def _current_hosted_models(models: Dict[str, ModelInfo]) -> Dict[str, ModelInfo]:
    """Derive compact current hosted-model lists from models.dev metadata.

    Newest releases lead. "-latest" rolling aliases are kept alongside real
    models (they win date ties) but no longer replace them — the old
    exclusive-alias rule hid brand-new flagships (e.g. the GPT-5.6 family)
    behind stale ``gpt-5.x-chat-latest`` entries.
    """
    chat_models = [model for model in models.values() if _is_chat_model(model)]
    if not chat_models:
        chat_models = list(models.values())

    selected = sorted(chat_models, key=_hosted_model_sort_key, reverse=True)[:CURRENT_MODEL_LIMIT]
    return {model.id: model for model in selected}


def _is_chat_model(model: ModelInfo) -> bool:
    text = f"{model.id} {model.name}".lower()
    return not any(marker in text for marker in NON_CHAT_MODEL_MARKERS)


def _is_latest_alias(model: ModelInfo) -> bool:
    text = f"{model.id} {model.name}".lower()
    return "latest" in text


def _hosted_model_sort_key(model: ModelInfo) -> tuple[str, int, int, int, float, str]:
    return (
        model.released or "",
        1 if _is_latest_alias(model) else 0,  # rolling aliases win date ties
        1 if model.supports_tools else 0,
        model.context_window,
        -(model.input_price + model.output_price),
        model.id,
    )


def _grok_cli_live_catalog() -> Dict[str, ModelInfo]:
    """Subscription models as reported by the installed Grok CLI.

    ``grok models`` is the source of truth for what the signed-in account can
    use; a hardcoded list goes stale the first time xAI ships a new family
    (grok-composer did exactly that). Metadata for known ids is copied from
    the builtin catalogs; unknown ids are explicitly marked unknown. Returns an
    empty dict when the CLI is missing or logged out, in which case the
    builtin grok-cli entries apply.
    """
    try:
        from .grok_cli_auth import cached_cli_models

        listing = cached_cli_models()
    except Exception:  # noqa: BLE001 - CLI probing is best-effort
        return {}
    ids = list(listing.get("models") or [])
    if not ids:
        return {}
    default_id = str(listing.get("default") or "")
    if default_id and default_id not in ids:
        ids.insert(0, default_id)

    effective = get_effective_models()
    templates = {**effective.get("xai", {}), **MODELS.get("grok-cli", {})}
    catalog: Dict[str, ModelInfo] = {}
    for model_id in ids:
        template = templates.get(model_id)
        if template is not None:
            catalog[model_id] = ModelInfo(
                id=model_id,
                name=template.name,
                provider="grok-cli",
                context_window=template.context_window,
                max_output=template.max_output,
                capabilities=list(template.capabilities),
                description=template.description,
                recommended_for=list(template.recommended_for),
                released=template.released,
            )
        else:
            catalog[model_id] = ModelInfo(
                id=model_id,
                name=model_id,
                provider="grok-cli",
                context_window=0,
                max_output=0,
                capabilities=[],
                description=(
                    "Subscription model reported by `grok models`; context and "
                    "capabilities have not been verified."
                ),
            )
    return catalog


def find_providers_for_model(model_id: str) -> List[str]:
    """Hosted provider ids whose catalog contains exactly this model id.

    Powers bare-model connects (":connect gpt-5.6-sol") — a unique match lets
    the TUI resolve the provider for the user. Local providers are excluded:
    their tags are machine-specific and connect via :connect local.
    """
    needle = (model_id or "").strip().lower()
    if not needle:
        return []
    matches = []
    for provider_id, models in get_effective_models().items():
        if provider_id in LOCAL_MODEL_PROVIDERS:
            continue
        for mid, info in models.items():
            if mid.lower() == needle and info.provider == provider_id:
                matches.append(provider_id)
                break
    return sorted(matches)


def sort_models_newest_first(models: List[Any]) -> List[Any]:
    """Order heterogeneous picker entries newest-release-first (stable).

    ACP pickers hold plain dicts (Codex account models, OpenCode ids like
    ``deepseek/deepseek-v4``); release dates come from the effective catalog.
    Entries without a known date keep their advertised relative order, after
    the dated ones.
    """
    released_by_id: Dict[str, str] = {}
    for provider_models in get_effective_models().values():
        for mid, info in provider_models.items():
            if info.released:
                existing = released_by_id.get(mid.lower(), "")
                if info.released > existing:
                    released_by_id[mid.lower()] = info.released

    def _released(entry: Any) -> str:
        raw_id = entry.get("id", "") if isinstance(entry, dict) else getattr(entry, "id", "")
        model_id = str(raw_id or "").lower()
        if not model_id:
            return ""
        direct = released_by_id.get(model_id, "")
        if direct:
            return direct
        # "provider/model" pair ids (OpenCode) — match on the model part.
        if "/" in model_id:
            return released_by_id.get(model_id.rsplit("/", 1)[1], "")
        return ""

    return sorted(models, key=_released, reverse=True)


def get_all_models() -> List[ModelInfo]:
    """Get all models across all providers."""
    all_models = []
    for provider_id in get_effective_models().keys():
        all_models.extend(get_models_for_provider(provider_id).values())
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
