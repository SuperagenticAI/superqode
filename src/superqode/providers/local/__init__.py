"""Local LLM provider clients and utilities.

This module provides clients for self-hosted LLM servers including:
- Ollama
- LM Studio
- vLLM
- SGLang
- MLX-LM
- TGI (Text Generation Inference)
- llama.cpp server
- Generic OpenAI-compatible servers
"""

from superqode.providers.local.base import (
    LocalProviderType,
    Quantization,
    LocalModel,
    ProviderStatus,
    ToolTestResult,
    GenerationConfig,
    LocalProviderClient,
    MODEL_FAMILIES,
    TOOL_CAPABLE_FAMILIES,
    detect_model_family,
    detect_quantization,
    likely_supports_tools,
)
from superqode.providers.local.ollama import OllamaClient, get_ollama_client
from superqode.providers.local.vllm import VLLMClient, get_vllm_client
from superqode.providers.local.sglang import SGLangClient, get_sglang_client
from superqode.providers.local.mlx import MLXClient, get_mlx_client
from superqode.providers.local.tgi import TGIClient, get_tgi_client
from superqode.providers.local.lmstudio import LMStudioClient, get_lmstudio_client
from superqode.providers.local.discovery import (
    DiscoveredProvider,
    LocalProviderDiscovery,
    get_discovery_service,
    quick_scan,
    DEFAULT_PORTS,
    ALL_PORTS,
)
from superqode.providers.local.tool_support import (
    ToolCapabilityInfo,
    TOOL_CAPABLE_MODELS,
    TOOL_QUIRKS,
    NO_TOOL_SUPPORT,
    get_tool_capability_info,
    test_tool_calling,
    get_recommended_coding_models,
    estimate_tool_support,
)

__all__ = [
    # Enums
    "LocalProviderType",
    "Quantization",
    # Data classes
    "LocalModel",
    "ProviderStatus",
    "ToolTestResult",
    "GenerationConfig",
    "DiscoveredProvider",
    # Base class
    "LocalProviderClient",
    # Clients
    "OllamaClient",
    "get_ollama_client",
    "VLLMClient",
    "get_vllm_client",
    "SGLangClient",
    "get_sglang_client",
    "MLXClient",
    "get_mlx_client",
    "TGIClient",
    "get_tgi_client",
    "LMStudioClient",
    "get_lmstudio_client",
    # Discovery
    "LocalProviderDiscovery",
    "get_discovery_service",
    "quick_scan",
    "DEFAULT_PORTS",
    "ALL_PORTS",
    # Constants
    "MODEL_FAMILIES",
    "TOOL_CAPABLE_FAMILIES",
    # Utilities
    "detect_model_family",
    "detect_quantization",
    "likely_supports_tools",
    # Tool support
    "ToolCapabilityInfo",
    "TOOL_CAPABLE_MODELS",
    "TOOL_QUIRKS",
    "NO_TOOL_SUPPORT",
    "get_tool_capability_info",
    "test_tool_calling",
    "get_recommended_coding_models",
    "estimate_tool_support",
]
