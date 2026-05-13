"""DS4 client for local DeepSeek V4 Flash inference.

DS4 exposes an OpenAI-compatible API, usually at ``/v1``.
"""

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from superqode.providers.local.base import (
    LocalModel,
    LocalProviderClient,
    LocalProviderType,
    ProviderStatus,
    ToolTestResult,
)


DEFAULT_DS4_HOST = "http://127.0.0.1:8000/v1"
DEFAULT_DS4_MODELS = (
    ("deepseek-v4-flash", "DeepSeek V4 Flash"),
    ("deepseek-chat", "DeepSeek V4 Flash (no thinking)"),
)


class DS4Client(LocalProviderClient):
    """DS4 OpenAI-compatible local API client."""

    provider_type = LocalProviderType.OPENAI_COMPAT
    default_port = 8000

    def __init__(self, host: Optional[str] = None):
        """Initialize DS4 client.

        Args:
            host: DS4 OpenAI-compatible base URL. Falls back to DS4_HOST.
        """
        if host is None:
            host = os.environ.get("DS4_HOST", DEFAULT_DS4_HOST)
        super().__init__(host)

    def _request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 10.0
    ) -> Any:
        """Make a request to the DS4 API."""
        url = f"{self.host}{endpoint}"
        headers = {"Content-Type": "application/json"}
        body = json.dumps(data).encode("utf-8") if data is not None else None
        request = Request(url, data=body, headers=headers, method=method)

        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _async_request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, timeout: float = 10.0
    ) -> Any:
        """Async wrapper for blocking urllib calls."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._request(method, endpoint, data, timeout)
        )

    async def is_available(self) -> bool:
        """Check whether DS4 is reachable."""
        try:
            await self._async_request("GET", "/models", timeout=5.0)
            return True
        except Exception:
            return False

    async def get_status(self) -> ProviderStatus:
        """Get detailed DS4 status."""
        start_time = time.time()

        try:
            response = await self._async_request("GET", "/models", timeout=5.0)
            models = response.get("data", [])
            latency = (time.time() - start_time) * 1000
            return ProviderStatus(
                available=True,
                provider_type=self.provider_type,
                host=self.host,
                models_count=len(models),
                running_models=len(models),
                gpu_available=False,
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
        """List DS4 models, falling back to known aliases when server is offline."""
        try:
            response = await self._async_request("GET", "/models")
            models = response.get("data", [])
            result = []
            for model_data in models:
                model_id = model_data.get("id", "")
                if not model_id:
                    continue
                result.append(self._model_from_id(model_id, running=True))
            return result or self._fallback_models()
        except Exception:
            return self._fallback_models()

    async def list_running(self) -> List[LocalModel]:
        """List running DS4 models."""
        if not await self.is_available():
            return []
        models = await self.list_models()
        for model in models:
            model.running = True
        return models

    async def get_model_info(self, model_id: str) -> Optional[LocalModel]:
        """Get DS4 model information."""
        models = await self.list_models()
        for model in models:
            if model.id == model_id:
                return model
        return None

    async def test_tool_calling(self, model_id: str) -> ToolTestResult:
        """DS4's OpenAI-compatible endpoint supports tool schemas in SuperQode."""
        return ToolTestResult(
            model_id=model_id,
            supports_tools=True,
            parallel_tools=False,
            tool_choice=["auto"],
            notes="DS4 is treated as a tool-capable local DeepSeek provider.",
        )

    def get_litellm_model_name(self, model_id: str) -> str:
        """Get the LiteLLM-compatible model name."""
        return f"openai/{model_id}"

    def _fallback_models(self) -> List[LocalModel]:
        return [
            self._model_from_id(model_id, name=name, running=False)
            for model_id, name in DEFAULT_DS4_MODELS
        ]

    def _model_from_id(
        self, model_id: str, name: Optional[str] = None, running: bool = False
    ) -> LocalModel:
        return LocalModel(
            id=model_id,
            name=name or model_id.split("/")[-1],
            quantization="GGUF",
            context_window=1_000_000,
            supports_tools=True,
            supports_vision=False,
            family="deepseek",
            running=running,
            details={"host": self.host, "provider": "ds4"},
        )


def get_ds4_client(host: Optional[str] = None) -> DS4Client:
    """Get a DS4 client instance."""
    return DS4Client(host=host)
