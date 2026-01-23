"""SGLang client for structured generation.

SGLang is a fast serving framework for large language models and vision
language models with a focus on structured generation.
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


class SGLangClient(LocalProviderClient):
    """SGLang server client.

    SGLang provides:
    - RadixAttention for fast KV cache reuse
    - Compressed FSM for structured outputs
    - OpenAI-compatible API endpoints

    API Endpoints:
    - GET /health - Health check
    - GET /v1/models - List models
    - POST /v1/chat/completions - Chat completion
    - POST /generate - Native generation endpoint

    Environment:
        SGLANG_HOST: Override default host (default: http://localhost:30000)
    """

    provider_type = LocalProviderType.SGLANG
    default_port = 30000

    def __init__(self, host: Optional[str] = None):
        """Initialize SGLang client.

        Args:
            host: SGLang host URL. Falls back to SGLANG_HOST env var.
        """
        if host is None:
            host = os.environ.get("SGLANG_HOST")
        super().__init__(host)

    def _request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 30.0
    ) -> Any:
        """Make a request to the SGLang API."""
        url = f"{self.host}{endpoint}"
        headers = {"Content-Type": "application/json"}

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        request = Request(url, data=body, headers=headers, method=method)

        with urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8")
            if content:
                return json.loads(content)
            return {}

    async def _async_request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 30.0
    ) -> Any:
        """Async wrapper for _request."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._request(method, endpoint, data, timeout)
        )

    async def is_available(self) -> bool:
        """Check if SGLang is running."""
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
        """Get detailed SGLang status."""
        start_time = time.time()

        try:
            # Check health
            await self._async_request("GET", "/health", timeout=5.0)

            # Get models
            models_response = await self._async_request("GET", "/v1/models", timeout=5.0)
            latency = (time.time() - start_time) * 1000

            models = models_response.get("data", [])

            # Try to get server info
            version = ""
            try:
                info = await self._async_request("GET", "/get_server_info", timeout=5.0)
                version = info.get("version", "")
            except Exception:
                pass

            return ProviderStatus(
                available=True,
                provider_type=self.provider_type,
                host=self.host,
                version=version,
                models_count=len(models),
                running_models=len(models),
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
                        running=True,
                    )
                )

            return result

        except Exception:
            return []

    async def list_running(self) -> List[LocalModel]:
        """List running models (same as list_models for SGLang)."""
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
        # SGLang uses OpenAI-compatible format
        return model_id


async def get_sglang_client(host: Optional[str] = None) -> Optional[SGLangClient]:
    """Get an SGLang client if available.

    Args:
        host: Optional host override.

    Returns:
        SGLangClient if SGLang is running, None otherwise.
    """
    client = SGLangClient(host)
    if await client.is_available():
        return client
    return None
