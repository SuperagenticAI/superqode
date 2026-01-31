"""HuggingFace ecosystem integration for SuperQode.

This module provides comprehensive HuggingFace support including:
- HF Hub API for model discovery and download
- HF Inference API for serverless inference
- HF Inference Endpoints for dedicated deployments
- Local transformers runner for pure Python inference
"""

from superqode.providers.huggingface.hub import (
    HFModel,
    GGUFFile,
    HuggingFaceHub,
    discover_cached_models,
    get_hf_hub,
)
from superqode.providers.huggingface.inference import (
    InferenceResponse,
    HFInferenceClient,
    get_hf_inference_client,
    RECOMMENDED_MODELS,
)
from superqode.providers.huggingface.endpoints import (
    EndpointState,
    EndpointType,
    InferenceEndpoint,
    EndpointResponse,
    HFEndpointsClient,
    get_hf_endpoints_client,
)
from superqode.providers.huggingface.transformers_runner import (
    TransformersConfig,
    GenerationResult,
    LoadedModel,
    TransformersRunner,
    get_transformers_runner,
)
from superqode.providers.huggingface.downloader import (
    DownloadProgress,
    DownloadResult,
    HFDownloader,
    get_hf_downloader,
)

__all__ = [
    # Data classes
    "HFModel",
    "GGUFFile",
    "InferenceResponse",
    "InferenceEndpoint",
    "EndpointResponse",
    "EndpointState",
    "EndpointType",
    "TransformersConfig",
    "GenerationResult",
    "LoadedModel",
    # Hub client
    "HuggingFaceHub",
    "discover_cached_models",
    "get_hf_hub",
    # Inference client
    "HFInferenceClient",
    "get_hf_inference_client",
    "RECOMMENDED_MODELS",
    # Endpoints client
    "HFEndpointsClient",
    "get_hf_endpoints_client",
    # Transformers runner
    "TransformersRunner",
    "get_transformers_runner",
    # Downloader
    "DownloadProgress",
    "DownloadResult",
    "HFDownloader",
    "get_hf_downloader",
]
