"""Base classes and data structures for local LLM providers.

This module provides the foundation for interacting with self-hosted LLM servers
like Ollama, vLLM, SGLang, LM Studio, MLX, TGI, and llama.cpp.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime


class LocalProviderType(Enum):
    """Types of local LLM providers."""

    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"
    VLLM = "vllm"
    SGLANG = "sglang"
    MLX = "mlx"
    TGI = "tgi"
    LLAMACPP = "llamacpp"
    OPENAI_COMPAT = "openai_compatible"


class Quantization(Enum):
    """Common quantization formats."""

    F32 = "F32"  # Full precision
    F16 = "F16"  # Half precision
    BF16 = "BF16"  # Brain float 16
    Q8_0 = "Q8_0"  # 8-bit quantization
    Q6_K = "Q6_K"  # 6-bit K-quant
    Q5_K_M = "Q5_K_M"  # 5-bit K-quant medium
    Q5_K_S = "Q5_K_S"  # 5-bit K-quant small
    Q4_K_M = "Q4_K_M"  # 4-bit K-quant medium
    Q4_K_S = "Q4_K_S"  # 4-bit K-quant small
    Q4_0 = "Q4_0"  # 4-bit quantization
    Q3_K_M = "Q3_K_M"  # 3-bit K-quant medium
    Q3_K_S = "Q3_K_S"  # 3-bit K-quant small
    Q2_K = "Q2_K"  # 2-bit K-quant
    IQ4_XS = "IQ4_XS"  # Importance quantization 4-bit
    IQ3_XS = "IQ3_XS"  # Importance quantization 3-bit
    IQ2_XS = "IQ2_XS"  # Importance quantization 2-bit
    GPTQ = "GPTQ"  # GPTQ quantization
    AWQ = "AWQ"  # AWQ quantization
    GGUF = "GGUF"  # Generic GGUF (unknown quant)
    UNKNOWN = "unknown"


@dataclass
class LocalModel:
    """Represents a model available on a local provider.

    Attributes:
        id: Unique model identifier (e.g., "llama3.2:latest")
        name: Human-readable name (e.g., "Llama 3.2")
        size_bytes: Model file size in bytes
        quantization: Quantization format (Q4_K_M, Q8_0, F16, etc.)
        context_window: Maximum context length in tokens
        supports_tools: Whether model supports function/tool calling
        supports_vision: Whether model supports image inputs
        family: Model family (llama, qwen, mistral, phi, etc.)
        running: Whether model is currently loaded in memory
        gpu_layers: Number of layers offloaded to GPU
        vram_usage: VRAM usage in bytes when loaded
        parameter_count: Number of parameters (e.g., "8B", "70B")
        modified_at: Last modification timestamp
        digest: Model file digest/hash
        details: Additional provider-specific details
    """

    id: str
    name: str
    size_bytes: int = 0
    quantization: str = "unknown"
    context_window: int = 4096
    supports_tools: bool = False
    supports_vision: bool = False
    family: str = "unknown"
    running: bool = False
    gpu_layers: int = 0
    vram_usage: int = 0
    parameter_count: str = ""
    modified_at: Optional[datetime] = None
    digest: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def size_display(self) -> str:
        """Human-readable size."""
        if self.size_bytes == 0:
            return "unknown"
        gb = self.size_bytes / (1024**3)
        if gb >= 1:
            return f"{gb:.1f}GB"
        mb = self.size_bytes / (1024**2)
        return f"{mb:.0f}MB"

    @property
    def vram_display(self) -> str:
        """Human-readable VRAM usage."""
        if self.vram_usage == 0:
            return "unknown"
        gb = self.vram_usage / (1024**3)
        if gb >= 1:
            return f"{gb:.1f}GB"
        mb = self.vram_usage / (1024**2)
        return f"{mb:.0f}MB"


@dataclass
class ProviderStatus:
    """Status of a local provider.

    Attributes:
        available: Whether the provider is reachable
        provider_type: Type of provider
        host: Provider host URL
        version: Provider version string
        models_count: Number of available models
        running_models: Number of currently loaded models
        gpu_available: Whether GPU acceleration is available
        error: Error message if not available
        latency_ms: Response latency in milliseconds
        last_checked: When status was last checked
    """

    available: bool
    provider_type: LocalProviderType
    host: str
    version: str = ""
    models_count: int = 0
    running_models: int = 0
    gpu_available: bool = False
    error: str = ""
    latency_ms: float = 0.0
    last_checked: Optional[datetime] = None


@dataclass
class ToolTestResult:
    """Result of testing tool-calling capability.

    Attributes:
        model_id: Model that was tested
        supports_tools: Whether tool calling works
        parallel_tools: Whether parallel tool calls work
        tool_choice: Supported tool_choice modes
        error: Error message if test failed
        latency_ms: Test execution time
        notes: Additional notes about capability
    """

    model_id: str
    supports_tools: bool
    parallel_tools: bool = False
    tool_choice: List[str] = field(default_factory=list)  # "auto", "required", "none"
    error: str = ""
    latency_ms: float = 0.0
    notes: str = ""


@dataclass
class GenerationConfig:
    """Configuration for text generation.

    Attributes:
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature (0.0-2.0)
        top_p: Nucleus sampling threshold
        top_k: Top-k sampling
        stop: Stop sequences
        num_ctx: Context window size (Ollama-specific)
        num_gpu: GPU layers to use
        repeat_penalty: Repetition penalty
        seed: Random seed for reproducibility
    """

    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    stop: List[str] = field(default_factory=list)
    num_ctx: int = 0  # 0 = use model default
    num_gpu: int = -1  # -1 = auto, 0 = CPU only
    repeat_penalty: float = 1.1
    seed: Optional[int] = None


class LocalProviderClient(ABC):
    """Abstract base class for local LLM provider clients.

    All local provider clients (Ollama, vLLM, LM Studio, etc.) should
    inherit from this class and implement the required methods.
    """

    provider_type: LocalProviderType = LocalProviderType.OPENAI_COMPAT
    default_port: int = 8080

    def __init__(self, host: Optional[str] = None):
        """Initialize the client.

        Args:
            host: Provider host URL. If not provided, uses default.
        """
        self._host = host

    @property
    def host(self) -> str:
        """Get the provider host URL."""
        if self._host:
            return self._host.rstrip("/")
        return f"http://localhost:{self.default_port}"

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the provider is running and reachable.

        Returns:
            True if provider is available, False otherwise.
        """
        pass

    @abstractmethod
    async def get_status(self) -> ProviderStatus:
        """Get detailed provider status.

        Returns:
            ProviderStatus with availability and capability info.
        """
        pass

    @abstractmethod
    async def list_models(self) -> List[LocalModel]:
        """List all available models on this provider.

        Returns:
            List of LocalModel objects.
        """
        pass

    @abstractmethod
    async def list_running(self) -> List[LocalModel]:
        """List models currently loaded in memory.

        Returns:
            List of LocalModel objects that are running.
        """
        pass

    @abstractmethod
    async def get_model_info(self, model_id: str) -> Optional[LocalModel]:
        """Get detailed information about a specific model.

        Args:
            model_id: The model identifier.

        Returns:
            LocalModel with detailed info, or None if not found.
        """
        pass

    async def test_tool_calling(self, model_id: str) -> ToolTestResult:
        """Test if a model supports tool/function calling.

        Default implementation assumes no tool support.
        Subclasses should override for providers that support tools.

        Args:
            model_id: The model identifier to test.

        Returns:
            ToolTestResult with capability information.
        """
        return ToolTestResult(
            model_id=model_id,
            supports_tools=False,
            notes="Tool testing not implemented for this provider",
        )

    async def pull_model(self, model_id: str) -> bool:
        """Pull/download a model.

        Not all providers support this. Default returns False.

        Args:
            model_id: The model to pull.

        Returns:
            True if pull succeeded, False otherwise.
        """
        return False

    async def delete_model(self, model_id: str) -> bool:
        """Delete a model.

        Not all providers support this. Default returns False.

        Args:
            model_id: The model to delete.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        return False

    def get_litellm_model_name(self, model_id: str) -> str:
        """Get the LiteLLM-compatible model name.

        Args:
            model_id: Local model identifier.

        Returns:
            Model name formatted for LiteLLM.
        """
        # Default: just return the model ID
        # Subclasses should override with proper prefixes
        return model_id


# Model family detection patterns
MODEL_FAMILIES = {
    "llama": ["llama", "codellama", "tinyllama"],
    "qwen": ["qwen"],
    "mistral": ["mistral", "mixtral"],
    "phi": ["phi"],
    "gemma": ["gemma"],
    "deepseek": ["deepseek"],
    "starcoder": ["starcoder", "starcode"],
    "codestral": ["codestral"],
    "yi": ["yi-"],
    "vicuna": ["vicuna"],
    "wizard": ["wizard"],
    "openchat": ["openchat"],
    "neural": ["neural"],
    "dolphin": ["dolphin"],
    "orca": ["orca"],
    "nous": ["nous"],
    "hermes": ["hermes"],
    "zephyr": ["zephyr"],
    "solar": ["solar"],
    "command": ["command-r"],
}

# Models known to support tool calling
TOOL_CAPABLE_FAMILIES = {
    "llama",  # Llama 3.1+
    "qwen",  # Qwen 2.5+
    "mistral",  # Mistral/Mixtral
    "deepseek",  # DeepSeek
    "command",  # Command-R
    "hermes",  # Hermes (fine-tuned for tools)
}


def detect_model_family(model_id: str) -> str:
    """Detect the model family from model ID.

    Args:
        model_id: Model identifier (e.g., "llama3.2:8b-instruct-q4_K_M")

    Returns:
        Family name or "unknown".
    """
    model_lower = model_id.lower()
    for family, patterns in MODEL_FAMILIES.items():
        for pattern in patterns:
            if pattern in model_lower:
                return family
    return "unknown"


def detect_quantization(model_id: str) -> str:
    """Detect quantization from model ID.

    Args:
        model_id: Model identifier.

    Returns:
        Quantization string or "unknown".
    """
    model_upper = model_id.upper()

    # Check for known quantization patterns
    for quant in Quantization:
        if quant.value in model_upper:
            return quant.value

    # Check common suffixes
    if "FP16" in model_upper or "F16" in model_upper:
        return "F16"
    if "FP32" in model_upper or "F32" in model_upper:
        return "F32"
    if "BF16" in model_upper:
        return "BF16"

    return "unknown"


def likely_supports_tools(model_id: str) -> bool:
    """Estimate if a model likely supports tool calling.

    Based on model family and version heuristics.

    Args:
        model_id: Model identifier.

    Returns:
        True if model likely supports tools.
    """
    family = detect_model_family(model_id)
    model_lower = model_id.lower()

    if family not in TOOL_CAPABLE_FAMILIES:
        return False

    # Version-specific checks
    if family == "llama":
        # Llama 3.1+ supports tools
        if "llama3.1" in model_lower or "llama3.2" in model_lower or "llama3.3" in model_lower:
            return True
        if "llama-3.1" in model_lower or "llama-3.2" in model_lower or "llama-3.3" in model_lower:
            return True
        return False

    if family == "qwen":
        # Qwen 2.5+ supports tools well
        if "qwen2.5" in model_lower or "qwen2-5" in model_lower:
            return True
        return False

    # Mistral/Mixtral generally support tools
    if family in ("mistral", "command", "hermes", "deepseek"):
        return True

    return False
