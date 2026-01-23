"""HuggingFace Text Generation Inference (TGI) client.

TGI is HuggingFace's production-grade inference server for LLMs.
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


class TGIClient(LocalProviderClient):
    """HuggingFace Text Generation Inference client.

    TGI provides:
    - Flash Attention and Paged Attention
    - Continuous batching
    - Tensor parallelism for multi-GPU
    - Token streaming
    - Tool/function calling support

    API Endpoints:
    - GET /info - Model info
    - GET /health - Health check
    - POST /generate - Text generation
    - POST /v1/chat/completions - OpenAI-compatible chat

    Environment:
        TGI_HOST: Override default host (default: http://localhost:8080)
    """

    provider_type = LocalProviderType.TGI
    default_port = 8080

    def __init__(self, host: Optional[str] = None):
        """Initialize TGI client.

        Args:
            host: TGI host URL. Falls back to TGI_HOST env var.
        """
        if host is None:
            host = os.environ.get("TGI_HOST")
        super().__init__(host)

    def _request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 30.0
    ) -> Any:
        """Make a request to the TGI API."""
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
        """Check if TGI is running."""
        try:
            await self._async_request("GET", "/health", timeout=5.0)
            return True
        except Exception:
            try:
                await self._async_request("GET", "/info", timeout=5.0)
                return True
            except Exception:
                return False

    async def get_status(self) -> ProviderStatus:
        """Get detailed TGI status."""
        start_time = time.time()

        try:
            # Get model info
            info = await self._async_request("GET", "/info", timeout=5.0)
            latency = (time.time() - start_time) * 1000

            model_id = info.get("model_id", "")
            version = info.get("version", "")

            return ProviderStatus(
                available=True,
                provider_type=self.provider_type,
                host=self.host,
                version=version,
                models_count=1,  # TGI serves one model
                running_models=1,
                gpu_available=True,
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
        """List available models (TGI serves one model)."""
        try:
            info = await self._async_request("GET", "/info")
            model_id = info.get("model_id", "")

            if not model_id:
                return []

            # Extract context length if available
            max_input = info.get("max_input_length", 4096)
            max_total = info.get("max_total_tokens", 8192)

            return [
                LocalModel(
                    id=model_id,
                    name=model_id.split("/")[-1],
                    context_window=max_total,
                    family=detect_model_family(model_id),
                    supports_tools=likely_supports_tools(model_id),
                    running=True,
                    details={
                        "max_input_length": max_input,
                        "max_total_tokens": max_total,
                        "max_batch_total_tokens": info.get("max_batch_total_tokens"),
                    },
                )
            ]

        except Exception:
            return []

    async def list_running(self) -> List[LocalModel]:
        """List running models."""
        return await self.list_models()

    async def get_model_info(self, model_id: str) -> Optional[LocalModel]:
        """Get model information."""
        models = await self.list_models()
        if models:
            return models[0]
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
                    "model": "tgi",
                    "messages": [{"role": "user", "content": "What's the weather in Paris?"}],
                    "tools": test_tools,
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
        if model_id.startswith("huggingface/"):
            return model_id
        return f"huggingface/{model_id}"


async def get_tgi_client(host: Optional[str] = None) -> Optional[TGIClient]:
    """Get a TGI client if available.

    Args:
        host: Optional host override.

    Returns:
        TGIClient if TGI is running, None otherwise.
    """
    client = TGIClient(host)
    if await client.is_available():
        return client
    return None
