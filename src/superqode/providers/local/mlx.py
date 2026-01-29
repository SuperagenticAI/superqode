"""MLX-LM client for Apple Silicon inference.

MLX-LM is a framework for running large language models locally
on Apple Silicon Macs using the MLX framework.
"""

import asyncio
import glob
import json
import os
import pathlib
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from superqode.providers.local.base import (
    LocalProviderClient,
    LocalProviderType,
    LocalModel,
    ProviderStatus,
    ToolTestResult,
    detect_model_family,
    detect_quantization,
    likely_supports_tools,
)


class MLXClient(LocalProviderClient):
    """MLX-LM server client for Apple Silicon.

    MLX-LM provides:
    - Native Apple Silicon acceleration
    - Efficient memory management on unified memory
    - OpenAI-compatible API via mlx_lm.server

    Start server with:
        mlx_lm.server --model <model-path>

    API Endpoints (OpenAI-compatible):
    - GET /v1/models - List models
    - POST /v1/chat/completions - Chat completion
    - POST /v1/completions - Text completion

    Environment:
        MLX_HOST: Override default host (default: http://localhost:8080)
    """

    provider_type = LocalProviderType.MLX
    default_port = 8080

    @staticmethod
    def is_model_supported(model_id: str) -> bool:
        """Check if a model is supported by MLX.

        Args:
            model_id: HuggingFace model ID

        Returns:
            True if the model is supported, False otherwise
        """
        # Known non-working models (MoE architecture issues)
        non_working_patterns = [
            "gpt-oss",  # SuperagenticAI gpt-oss models have MoE issues
            "mixtral",  # Mixtral MoE models not supported
        ]

        model_lower = model_id.lower()
        for pattern in non_working_patterns:
            if pattern in model_lower:
                return False

        # Known working model families
        working_families = [
            "qwen",
            "llama",
            "mistral",
            "phi",
            "gemma",
            "openhermes",
        ]

        # Check if it's from a known working org/family
        for family in working_families:
            if family in model_lower:
                return True

        # Models from mlx-community are generally well-tested
        if "mlx-community" in model_id:
            return True

        # Default to supported for unknown models (let user try)
        return True

    @staticmethod
    def discover_huggingface_models() -> List[Dict[str, Any]]:
        """Discover MLX models from HuggingFace cache.

        Returns:
            List of model info dicts with keys: id, path, size, modified
        """
        models = []

        # Common HuggingFace cache locations
        cache_dirs = [
            os.path.expanduser("~/.cache/huggingface/hub"),
            os.path.expanduser("~/.cache/transformers"),
            # Add more potential locations
        ]

        for cache_dir in cache_dirs:
            if os.path.exists(cache_dir):
                # Look for MLX model directories (often contain 'mlx' in path)
                mlx_pattern = os.path.join(cache_dir, "**/*mlx*")
                for model_path in glob.glob(mlx_pattern, recursive=True):
                    if os.path.isdir(model_path):
                        try:
                            # Extract model ID from path
                            # Path format: .../models--org--model-name/snapshots/hash/
                            path_parts = model_path.split(os.sep)
                            if "models--" in model_path:
                                # Convert HF cache format to model ID
                                model_id = model_path.split("models--")[-1]
                                model_id = model_id.split(os.sep)[0]
                                model_id = model_id.replace("--", "/")

                                # Get model info
                                stat = os.stat(model_path)
                                size = MLXClient._get_directory_size(model_path)

                                models.append(
                                    {
                                        "id": model_id,
                                        "path": model_path,
                                        "size_bytes": size,
                                        "modified": datetime.fromtimestamp(stat.st_mtime),
                                    }
                                )
                        except Exception:
                            continue

        return models

    @staticmethod
    def _model_from_cache(model_info: Dict[str, Any], running: bool = False) -> LocalModel:
        """Build a LocalModel from cached HuggingFace model metadata."""
        model_id = model_info["id"]

        format_note = ""
        if "mlx" in model_id.lower():
            format_note = " (MLX format)"
        elif "4bit" in model_id.lower() or "8bit" in model_id.lower():
            format_note = " (quantized)"

        return LocalModel(
            id=model_id,
            name=f"{model_id.split('/')[-1]} (cached){format_note}",
            size_bytes=model_info["size_bytes"],
            quantization=detect_quantization(model_id),
            context_window=4096,
            supports_tools=likely_supports_tools(model_id),
            supports_vision=False,
            family=detect_model_family(model_id),
            running=running,
            modified_at=model_info.get("modified"),
            details={
                "cached_path": model_info.get("path"),
                "source": "huggingface_cache",
                "supported_formats": ["MLX", "safetensors"],
                "notes": "Works with mlx_lm.convert and mlx_lm.server",
            },
        )

    @staticmethod
    def _get_directory_size(path: str) -> int:
        """Get total size of directory in bytes."""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except OSError:
                    continue
        return total_size

    @staticmethod
    def get_available_models() -> List[LocalModel]:
        """Get all available MLX models (both from server and cache)."""
        models = []

        # First try to get models from running server
        async def get_server_models():
            try:
                client = MLXClient()
                if await client.is_available():
                    return await client.list_models()
            except Exception:
                pass
            return []

        # Run async function in sync context
        import asyncio

        try:
            server_models = asyncio.run(get_server_models())
            models.extend(server_models)
        except Exception:
            pass

        # Add models from HuggingFace cache (only supported ones)
        cache_models = MLXClient.discover_huggingface_models()
        for model_info in cache_models:
            model_id = model_info["id"]

            # Only include supported models
            if not MLXClient.is_model_supported(model_id):
                continue

            # Check if we already have this model from server
            if not any(m.id == model_id for m in models):
                # Add note about supported formats
                format_note = ""
                if "mlx" in model_id.lower():
                    format_note = " (MLX format)"
                elif "4bit" in model_id.lower() or "8bit" in model_id.lower():
                    format_note = " (quantized)"

                models.append(
                    LocalModel(
                        id=model_id,
                        name=f"{model_id.split('/')[-1]} (cached){format_note}",
                        size_bytes=model_info["size_bytes"],
                        quantization=detect_quantization(model_id),
                        context_window=4096,  # Default, would need model config
                        supports_tools=likely_supports_tools(model_id),
                        supports_vision=False,  # MLX vision support varies
                        family=detect_model_family(model_id),
                        running=False,  # Not running unless server says so
                        modified_at=model_info["modified"],
                        details={
                            "cached_path": model_info["path"],
                            "source": "huggingface_cache",
                            "supported_formats": ["MLX", "safetensors"],
                            "notes": "Works with mlx_lm.convert and mlx_lm.server",
                        },
                    )
                )

        return models

    def __init__(self, host: Optional[str] = None):
        """Initialize MLX client.

        Args:
            host: MLX server host URL. Falls back to MLX_HOST env var.
        """
        if host is None:
            host = os.environ.get("MLX_HOST")
        super().__init__(host)

    def _request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 30.0
    ) -> Any:
        """Make a request to the MLX API."""
        url = f"{self.host}{endpoint}"
        headers = {"Content-Type": "application/json"}

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        request = Request(url, data=body, headers=headers, method=method)

        with urlopen(request, timeout=timeout) as response:
            response_data = response.read().decode("utf-8")

            # Try to parse as JSON
            try:
                return json.loads(response_data)
            except json.JSONDecodeError as e:
                # If not valid JSON, check if it's an error response
                if response.status >= 400:
                    raise URLError(f"MLX server error ({response.status}): {response_data[:200]}")
                else:
                    # Return the raw response for debugging
                    raise URLError(f"Invalid JSON response from MLX server: {response_data[:200]}")

    async def _async_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        timeout: float = 120.0,  # Increased timeout for large MLX models
    ) -> Any:
        """Async wrapper for _request."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._request(method, endpoint, data, timeout)
        )

    async def is_available(self) -> bool:
        """Check if MLX server is running."""
        try:
            await self._async_request("GET", "/v1/models", timeout=5.0)
            return True
        except Exception:
            return False

    async def get_status(self) -> ProviderStatus:
        """Get detailed MLX status."""
        start_time = time.time()

        try:
            models_response = await self._async_request("GET", "/v1/models", timeout=5.0)
            latency = (time.time() - start_time) * 1000

            models = models_response.get("data", [])

            return ProviderStatus(
                available=True,
                provider_type=self.provider_type,
                host=self.host,
                models_count=len(models),
                running_models=len(models),
                gpu_available=True,  # Apple Silicon GPU
                latency_ms=latency,
                last_checked=datetime.now(),
            )

        except Exception as e:
            return ProviderStatus(
                available=False,
                provider_type=self.provider_type,
                host=self.host,
                error=str(e),
                last_checked=datetime.now(),
            )

    async def list_models(self) -> List[LocalModel]:
        """List available models from MLX server."""
        try:
            response = await self._async_request("GET", "/v1/models", timeout=8.0)
            models = response.get("data", [])

            result = []
            for model_data in models:
                model_id = model_data.get("id", "")
                # MLX server might return model path, extract model name
                model_name = model_id.split("/")[-1] if "/" in model_id else model_id

                # Try to get model info if available
                model_info = await self._get_model_info_safe(model_id)

                result.append(
                    LocalModel(
                        id=model_id,
                        name=model_name,
                        size_bytes=model_info.get("size_bytes", 0),
                        quantization=model_info.get("quantization", detect_quantization(model_id)),
                        context_window=model_info.get("context_window", 4096),
                        supports_tools=likely_supports_tools(model_id),
                        supports_vision=model_info.get("supports_vision", False),
                        family=detect_model_family(model_id),
                        running=True,
                        parameter_count=model_info.get("parameter_count", ""),
                        modified_at=model_info.get("modified_at"),
                        details=model_info,
                    )
                )

            return result

        except Exception:
            return []

    async def _get_model_info_safe(self, model_id: str) -> Dict[str, Any]:
        """Safely get model info without failing if endpoint doesn't exist."""
        try:
            # Try to get model info from server if available
            response = await self._async_request("GET", f"/v1/models/{model_id}")
            return response.get("model_info", {})
        except Exception:
            # Fallback to basic info
            return {
                "context_window": 4096,
                "supports_vision": False,
                "quantization": detect_quantization(model_id),
            }

    async def list_running(self) -> List[LocalModel]:
        """List running models."""
        models = await self.list_models()
        for m in models:
            m.running = True
        return models

    async def get_model_info(self, model_id: str) -> Optional[LocalModel]:
        """Get model information."""
        models = await self.list_models()
        for m in models:
            if m.id == model_id or m.id.endswith(f"/{model_id}"):
                return m
        return None

    async def test_tool_calling(self, model_id: str) -> ToolTestResult:
        """Test tool calling capability."""
        # MLX-LM tool support varies by model and server version
        return ToolTestResult(
            model_id=model_id,
            supports_tools=False,
            notes="MLX-LM tool support requires server configuration",
        )

    def get_litellm_model_name(self, model_id: str) -> str:
        """Get LiteLLM-compatible model name."""
        # MLX uses OpenAI-compatible format
        return model_id

    @staticmethod
    def get_server_command(model_path: str, host: str = "localhost", port: int = 8080) -> List[str]:
        """Get command to start MLX server.

        Args:
            model_path: Path or HuggingFace model ID
            host: Server host (default: localhost)
            port: Server port (default: 8080)

        Returns:
            Command list for subprocess
        """
        return [
            "mlx_lm.server",
            "--model",
            model_path,
            "--host",
            host,
            "--port",
            str(port),
        ]

    @staticmethod
    def suggest_models() -> List[str]:
        """Suggest popular MLX models that work well.

        Only includes models known to work with MLX (no MoE architecture issues).
        """
        return [
            "mlx-community/Mistral-7B-Instruct-v0.1",  # ✅ Standard transformer
            "mlx-community/Llama-2-7b-chat-hf",  # ✅ Standard transformer
            "mlx-community/Llama-3.2-1B-Instruct-4bit",  # ✅ Quantized Llama
            "mlx-community/Llama-3.2-3B-Instruct-4bit",  # ✅ Quantized Llama
            "mlx-community/Phi-2",  # ✅ Microsoft Phi
            "mlx-community/Qwen2.5-Coder-7B-Instruct",  # ✅ QWen coder model
            "mlx-community/OpenHermes-2.5-Mistral-7B",  # ✅ Fine-tuned Mistral
            "superagenticai/qwen3-0.6b-mlx-q4",  # ✅ Small QWen model
        ]

    @staticmethod
    async def check_mlx_lm_installed() -> bool:
        """Check if mlx_lm is installed."""
        import subprocess

        try:
            result = await asyncio.create_subprocess_exec(
                "mlx_lm.server", "--help", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            await result.wait()
            return result.returncode == 0
        except FileNotFoundError:
            return False


async def get_mlx_client(host: Optional[str] = None) -> Optional[MLXClient]:
    """Get an MLX client if available.

    Args:
        host: Optional host override.

    Returns:
        MLXClient if MLX server is running, None otherwise.
    """
    client = MLXClient(host)
    if await client.is_available():
        return client
    return None
