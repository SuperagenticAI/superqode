"""vLLM client for high-performance local inference.

vLLM is a high-throughput LLM inference engine that supports
OpenAI-compatible API endpoints.
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
    likely_supports_tools,
)


class VLLMClient(LocalProviderClient):
    """vLLM OpenAI-compatible API client.

    vLLM provides high-throughput inference with:
    - PagedAttention for efficient memory management
    - Continuous batching
    - OpenAI-compatible API at /v1/*

    API Endpoints:
    - GET /health - Health check
    - GET /v1/models - List available models
    - POST /v1/chat/completions - Chat completion
    - POST /v1/completions - Text completion

    Environment:
        VLLM_HOST: Override default host (default: http://localhost:8000)
    """

    provider_type = LocalProviderType.VLLM
    default_port = 8000

    def __init__(self, host: Optional[str] = None):
        """Initialize vLLM client.

        Args:
            host: vLLM host URL. Falls back to VLLM_HOST env var.
        """
        if host is None:
            host = os.environ.get("VLLM_HOST")
        super().__init__(host)

    def _request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 30.0
    ) -> Any:
        """Make a request to the vLLM API."""
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
    ) -> Any:
        """Async wrapper for _request."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._request(method, endpoint, data, timeout)
        )

    async def is_available(self) -> bool:
        """Check if vLLM is running."""
        try:
            await self._async_request("GET", "/health", timeout=5.0)
            return True
        except Exception:
            # Try /v1/models as fallback
            try:
                await self._async_request("GET", "/v1/models", timeout=5.0)
                return True
            except Exception:
                return False

    async def get_status(self) -> ProviderStatus:
        """Get detailed vLLM status."""
        start_time = time.time()

        try:
            # Check health
            await self._async_request("GET", "/health", timeout=5.0)

            # Get models
            models_response = await self._async_request("GET", "/v1/models", timeout=5.0)
            latency = (time.time() - start_time) * 1000

            models = models_response.get("data", [])

            return ProviderStatus(
                available=True,
                provider_type=self.provider_type,
                host=self.host,
                models_count=len(models),
                running_models=len(models),  # vLLM loads models on startup
                gpu_available=True,  # vLLM is GPU-focused
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
        """List available models."""
        try:
            response = await self._async_request("GET", "/v1/models")
            models = response.get("data", [])

            result = []
            for model_data in models:
                model_id = model_data.get("id", "")
                result.append(
                    LocalModel(
                        id=model_id,
                        name=model_id.split("/")[-1],
                        family=detect_model_family(model_id),
                        supports_tools=likely_supports_tools(model_id),
                        running=True,  # If listed, it's loaded
                    )
                )

            return result

        except Exception:
            return []

    async def list_running(self) -> List[LocalModel]:
        """List running models (same as list_models for vLLM)."""
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
        start_time = time.time()

        if not likely_supports_tools(model_id):
            return ToolTestResult(
                model_id=model_id,
                supports_tools=False,
                notes="Model family not known to support tools",
            )

        test_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            }
        ]

        try:
            response = await self._async_request(
                "POST",
                "/v1/chat/completions",
                data={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "What's the weather in Paris?"}],
                    "tools": test_tools,
                    "tool_choice": "auto",
                },
                timeout=60.0,
            )

            latency = (time.time() - start_time) * 1000

            choices = response.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
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

            return ToolTestResult(
                model_id=model_id,
                supports_tools=False,
                latency_ms=latency,
                notes="Model did not use tools in test",
            )

        except Exception as e:
            return ToolTestResult(
                model_id=model_id,
                supports_tools=False,
                error=str(e),
            )

    def get_litellm_model_name(self, model_id: str) -> str:
        """Get LiteLLM-compatible model name."""
        if model_id.startswith("hosted_vllm/"):
            return model_id
        return f"hosted_vllm/{model_id}"


async def get_vllm_client(host: Optional[str] = None) -> Optional[VLLMClient]:
    """Get a vLLM client if available.

    Args:
        host: Optional host override.

    Returns:
        VLLMClient if vLLM is running, None otherwise.
    """
    client = VLLMClient(host)
    if await client.is_available():
        return client
    return None
