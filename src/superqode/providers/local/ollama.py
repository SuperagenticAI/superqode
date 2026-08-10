"""Enhanced Ollama client with full API support.

This module provides comprehensive access to the Ollama API including:
- Model listing and management
- Running model detection
- Detailed model information
- Model pull/delete operations
- Tool calling capability testing
"""

import asyncio
import json
import os
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


def _tags_details_are_sparse(details: Dict[str, Any]) -> bool:
    """True when a ``/api/tags`` entry carries no usable metadata.

    GGUF models arrive fully described (family, parameter_size, context_length).
    Ollama's native safetensors models arrive with those fields present but
    empty, which is indistinguishable from "unknown" to the heuristics.
    """
    return not (
        details.get("context_length") or details.get("family") or details.get("parameter_size")
    )


def _context_from_model_info(model_info: Dict[str, Any]) -> Optional[int]:
    """Read the context window out of ``/api/show``'s ``model_info``.

    The key is architecture-scoped (``<arch>.context_length``), so it is
    resolved via ``general.architecture`` rather than a fixed model list.
    """
    architecture = model_info.get("general.architecture")
    keys = [f"{architecture}.context_length"] if architecture else []
    keys += [k for k in model_info if k.endswith(".context_length")]
    for key in keys:
        try:
            window = int(model_info[key])
        except (KeyError, TypeError, ValueError):
            continue
        if window > 0:
            return window
    return None


class OllamaClient(LocalProviderClient):
    """Enhanced Ollama API client.

    Provides full access to Ollama's REST API:
    - GET /api/tags - List available models
    - GET /api/ps - List running models
    - POST /api/show - Get model details
    - POST /api/pull - Pull a model
    - DELETE /api/delete - Delete a model
    - POST /api/chat - Chat completion (for tool testing)
    - GET /api/version - Get Ollama version

    Environment:
        OLLAMA_HOST: Override default host (default: http://localhost:11434)
    """

    provider_type = LocalProviderType.OLLAMA
    default_port = 11434

    def __init__(self, host: Optional[str] = None):
        """Initialize Ollama client.

        Args:
            host: Ollama host URL. Falls back to OLLAMA_HOST env var,
                  then to http://localhost:11434.
        """
        if host is None:
            host = os.environ.get("OLLAMA_HOST")
        super().__init__(host)
        self._version: Optional[str] = None

    def _request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 30.0
    ) -> Dict[str, Any]:
        """Make a request to the Ollama API.

        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint (e.g., "/api/tags")
            data: Request body for POST/DELETE
            timeout: Request timeout in seconds

        Returns:
            JSON response as dict.

        Raises:
            URLError: If request fails.
        """
        url = f"{self.host}{endpoint}"
        headers = {"Content-Type": "application/json"}

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        request = Request(url, data=body, headers=headers, method=method)

        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _async_request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 30.0
    ) -> Dict[str, Any]:
        """Async wrapper for _request."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._request(method, endpoint, data, timeout)
        )

    async def is_available(self) -> bool:
        """Check if Ollama is running."""
        try:
            await self._async_request("GET", "/api/tags", timeout=5.0)
            return True
        except Exception:
            return False

    async def get_status(self) -> ProviderStatus:
        """Get detailed Ollama status."""
        start_time = time.time()

        try:
            # Get models list
            models_response = await self._async_request("GET", "/api/tags", timeout=5.0)
            latency = (time.time() - start_time) * 1000

            models = models_response.get("models", [])

            # Get running models
            try:
                ps_response = await self._async_request("GET", "/api/ps", timeout=5.0)
                running = ps_response.get("models", [])
                running_count = len(running)
            except Exception:
                running_count = 0

            # Get version
            version = ""
            try:
                version_response = await self._async_request("GET", "/api/version", timeout=5.0)
                version = version_response.get("version", "")
            except Exception:
                pass

            return ProviderStatus(
                available=True,
                provider_type=self.provider_type,
                host=self.host,
                version=version,
                models_count=len(models),
                running_models=running_count,
                gpu_available=True,  # Ollama handles GPU detection
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
        """List all available Ollama models."""
        try:
            response = await self._async_request("GET", "/api/tags")
            models = response.get("models", [])

            result = []
            for model_data in models:
                model = self._parse_model(model_data)
                if _tags_details_are_sparse(model_data.get("details", {})):
                    await self._enrich_from_show(model)
                result.append(model)

            return result

        except Exception:
            return []

    async def _model_capabilities(self, model_id: str) -> List[str]:
        """Return Ollama's declared capabilities, or [] when unavailable."""
        try:
            show = await self._async_request("POST", "/api/show", data={"name": model_id})
        except Exception:
            return []
        return show.get("capabilities") or []

    async def _enrich_from_show(self, model: LocalModel) -> None:
        """Fill a sparse ``/api/tags`` entry from ``/api/show``.

        Ollama's non-GGUF models (``format: safetensors``, its native
        per-tensor layout) come back from ``/api/tags`` with family, size,
        quantization and context all blank, so the name-based heuristics below
        silently degrade them to a 4096-token, tool-less, text-only model.
        ``/api/show`` reports the truth for any architecture, including ones
        released after this code was written. Best-effort: a failure here
        leaves the heuristic values in place rather than dropping the model.
        """
        try:
            show = await self._async_request("POST", "/api/show", data={"name": model.id})
        except Exception:
            return

        capabilities = show.get("capabilities") or []
        if capabilities:
            model.supports_tools = "tools" in capabilities
            model.supports_vision = "vision" in capabilities
            model.details["capabilities"] = capabilities

        context = _context_from_model_info(show.get("model_info") or {})
        if context:
            model.context_window = context

        details = show.get("details") or {}
        model.family = details.get("family") or model.family
        model.parameter_count = details.get("parameter_size") or model.parameter_count
        model.quantization = details.get("quantization_level") or model.quantization

    async def list_running(self) -> List[LocalModel]:
        """List models currently loaded in memory."""
        try:
            response = await self._async_request("GET", "/api/ps")
            models = response.get("models", [])

            result = []
            for model_data in models:
                model = self._parse_running_model(model_data)
                result.append(model)

            return result

        except Exception:
            return []

    async def get_model_info(self, model_id: str) -> Optional[LocalModel]:
        """Get detailed information about a model."""
        try:
            response = await self._async_request("POST", "/api/show", data={"name": model_id})

            # Get basic model from list for size info
            models = await self.list_models()
            base_model = next((m for m in models if m.id == model_id), None)

            model = self._parse_model_show(response, model_id)

            # Merge size info from list
            if base_model:
                model.size_bytes = base_model.size_bytes
                model.modified_at = base_model.modified_at
                model.digest = base_model.digest

            # Check if running
            running = await self.list_running()
            model.running = any(m.id == model_id for m in running)

            return model

        except Exception:
            return None

    async def test_tool_calling(self, model_id: str) -> ToolTestResult:
        """Test if a model supports tool calling."""
        start_time = time.time()

        # Ollama's own capability list is authoritative and covers models this
        # code predates; the name heuristic is only the fallback when /api/show
        # says nothing (older Ollama builds omit the field).
        capabilities = await self._model_capabilities(model_id)
        if capabilities:
            if "tools" not in capabilities:
                return ToolTestResult(
                    model_id=model_id,
                    supports_tools=False,
                    notes="Ollama reports no tool capability for this model",
                )
        elif not likely_supports_tools(model_id):
            return ToolTestResult(
                model_id=model_id,
                supports_tools=False,
                notes="Model family not known to support tools",
            )

        # Test with a simple tool call
        test_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the weather for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string", "description": "City name"}},
                        "required": ["city"],
                    },
                },
            }
        ]

        test_messages = [{"role": "user", "content": "What's the weather in Paris?"}]

        try:
            response = await self._async_request(
                "POST",
                "/api/chat",
                data={
                    "model": model_id,
                    "messages": test_messages,
                    "tools": test_tools,
                    "stream": False,
                },
                timeout=60.0,
            )

            latency = (time.time() - start_time) * 1000

            message = response.get("message", {})
            tool_calls = message.get("tool_calls", [])

            if tool_calls:
                return ToolTestResult(
                    model_id=model_id,
                    supports_tools=True,
                    parallel_tools=len(tool_calls) > 1,
                    tool_choice=["auto"],
                    latency_ms=latency,
                    notes="Tool calling verified",
                )
            else:
                # Model responded but didn't call the tool
                return ToolTestResult(
                    model_id=model_id,
                    supports_tools=False,
                    latency_ms=latency,
                    notes="Model did not call tool in test",
                )

        except Exception as e:
            return ToolTestResult(
                model_id=model_id, supports_tools=False, error=str(e), notes="Tool test failed"
            )

    async def pull_model(self, model_id: str) -> bool:
        """Pull a model from Ollama registry."""
        try:
            # Note: This is a streaming endpoint in practice
            # For simplicity, we just start the pull
            await self._async_request(
                "POST",
                "/api/pull",
                data={"name": model_id, "stream": False},
                timeout=600.0,  # 10 minute timeout for downloads
            )
            return True
        except Exception:
            return False

    async def delete_model(self, model_id: str) -> bool:
        """Delete a model."""
        try:
            await self._async_request("DELETE", "/api/delete", data={"name": model_id})
            return True
        except Exception:
            return False

    def get_litellm_model_name(self, model_id: str) -> str:
        """Get LiteLLM-compatible model name."""
        # LiteLLM uses "ollama/" prefix for Ollama models
        if model_id.startswith("ollama/"):
            return model_id
        return f"ollama/{model_id}"

    def _parse_model(self, data: Dict[str, Any]) -> LocalModel:
        """Parse model from /api/tags response."""
        model_id = data.get("name", data.get("model", "unknown"))

        # Parse modified_at
        modified_at = None
        if "modified_at" in data:
            try:
                modified_at = datetime.fromisoformat(data["modified_at"].replace("Z", "+00:00"))
            except Exception:
                pass

        # Extract details
        details = data.get("details", {})
        family = details.get("family", detect_model_family(model_id))
        parameter_size = details.get("parameter_size", "")
        quant = details.get("quantization_level", detect_quantization(model_id))

        return LocalModel(
            id=model_id,
            name=self._format_model_name(model_id),
            size_bytes=data.get("size", 0),
            quantization=quant,
            context_window=self._estimate_context(model_id, details),
            supports_tools=likely_supports_tools(model_id),
            supports_vision=self._supports_vision(model_id, details),
            family=family,
            running=False,
            parameter_count=parameter_size,
            modified_at=modified_at,
            digest=data.get("digest", ""),
            details=details,
        )

    def _parse_running_model(self, data: Dict[str, Any]) -> LocalModel:
        """Parse model from /api/ps response."""
        model_id = data.get("name", data.get("model", "unknown"))

        # Running models have additional info
        size_vram = data.get("size_vram", 0)

        details = data.get("details", {})
        family = details.get("family", detect_model_family(model_id))
        parameter_size = details.get("parameter_size", "")
        quant = details.get("quantization_level", detect_quantization(model_id))

        return LocalModel(
            id=model_id,
            name=self._format_model_name(model_id),
            size_bytes=data.get("size", 0),
            quantization=quant,
            context_window=self._estimate_context(model_id, details),
            supports_tools=likely_supports_tools(model_id),
            supports_vision=self._supports_vision(model_id, details),
            family=family,
            running=True,
            vram_usage=size_vram,
            parameter_count=parameter_size,
            details=details,
        )

    def _parse_model_show(self, data: Dict[str, Any], model_id: str) -> LocalModel:
        """Parse model from /api/show response."""
        details = data.get("details", {})
        modelfile = data.get("modelfile", "")
        template = data.get("template", "")
        parameters = data.get("parameters", "")

        family = details.get("family", detect_model_family(model_id))
        parameter_size = details.get("parameter_size", "")
        quant = details.get("quantization_level", detect_quantization(model_id))

        # Ollama states what the model can do; prefer that over guessing from
        # the name, which cannot know architectures newer than this code.
        capabilities = data.get("capabilities") or []

        # A num_ctx in the Modelfile is what the server will actually apply, so
        # it wins over the architecture's maximum.
        context_window = self._extract_context_from_params(parameters)
        if context_window == 0:
            context_window = _context_from_model_info(data.get("model_info") or {}) or 0
        if context_window == 0:
            context_window = self._estimate_context(model_id, details)

        return LocalModel(
            id=model_id,
            name=self._format_model_name(model_id),
            quantization=quant,
            context_window=context_window,
            supports_tools=(
                "tools" in capabilities if capabilities else likely_supports_tools(model_id)
            ),
            supports_vision=(
                "vision" in capabilities
                if capabilities
                else self._supports_vision(model_id, details)
            ),
            family=family,
            parameter_count=parameter_size,
            details={
                **details,
                "modelfile": modelfile[:500] if modelfile else "",
                "template": template[:500] if template else "",
                "parameters": parameters,
            },
        )

    def _format_model_name(self, model_id: str) -> str:
        """Format model ID into display name."""
        # Remove tag suffix for display
        name = model_id.split(":")[0]

        # Capitalize and format
        name = name.replace("-", " ").replace("_", " ")
        return name.title()

    def _estimate_context(self, model_id: str, details: Dict) -> int:
        """Estimate context window size."""
        # Check if details has context info
        if "context_length" in details:
            return details["context_length"]

        model_lower = model_id.lower()

        # Known context sizes by model
        if "llama3" in model_lower:
            return 128000
        if "qwen2.5" in model_lower:
            return 32768
        if "mistral" in model_lower:
            return 32768
        if "phi" in model_lower:
            return 16384
        if "gemma" in model_lower:
            # Gemma 3 / Gemma 4 train at 128K; Gemma 1/2 are 8K.
            norm = model_lower.replace("_", "-").replace(" ", "-")
            if any(v in norm for v in ("gemma3", "gemma-3", "gemma4", "gemma-4")):
                return 131072
            return 8192

        # Default
        return 4096

    def _supports_vision(self, model_id: str, details: Dict) -> bool:
        """Check if model supports vision/images."""
        # Check families that support vision. Ollama returns "families": null
        # for many models, so `.get(..., [])` is not enough — coerce None to [].
        families = details.get("families") or []
        if "clip" in families or "vision" in families:
            return True

        model_lower = model_id.lower()

        # Known vision models
        vision_patterns = ["llava", "vision", "vl", "bakllava", "moondream"]
        return any(p in model_lower for p in vision_patterns)

    def _extract_context_from_params(self, parameters: str) -> int:
        """Extract num_ctx from parameters string."""
        if not parameters:
            return 0

        for line in parameters.split("\n"):
            if "num_ctx" in line:
                try:
                    # Format: "num_ctx 4096"
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        return int(parts[1])
                except Exception:
                    pass

        return 0


# Convenience function
async def get_ollama_client(host: Optional[str] = None) -> Optional[OllamaClient]:
    """Get an Ollama client if available.

    Args:
        host: Optional host override.

    Returns:
        OllamaClient if Ollama is running, None otherwise.
    """
    client = OllamaClient(host)
    if await client.is_available():
        return client
    return None
