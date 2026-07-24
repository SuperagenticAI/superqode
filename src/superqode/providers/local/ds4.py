"""DwarfStar client for its supported local model families.

DwarfStar exposes OpenAI- and Anthropic-compatible APIs, usually at ``/v1``.
"""

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from superqode.local.laguna import LAGUNA_CONTEXT_WINDOW, is_laguna_model
from superqode.providers.local.base import (
    LocalModel,
    LocalProviderClient,
    LocalProviderType,
    ProviderStatus,
    ToolTestResult,
)


DEFAULT_DS4_HOST = "http://127.0.0.1:8000/v1"
DS4_MODEL_DISPLAY_NAMES = {
    "laguna-s-2.1": "Poolside Laguna S 2.1 (default)",
    "laguna-s-2.1-chat": "Poolside Laguna S 2.1 Chat (thinking off)",
    "laguna-s-2.1-reasoner": "Poolside Laguna S 2.1 Reasoner (thinking on)",
}
DEFAULT_DS4_MODELS = (
    ("deepseek-v4-flash", "DeepSeek V4 Flash"),
    ("deepseek-chat", "DeepSeek V4 Flash (no thinking)"),
    *DS4_MODEL_DISPLAY_NAMES.items(),
)
DEFAULT_DS4_HEALTH_TIMEOUT = 1.0
DEFAULT_DS4_MODELS_TIMEOUT = 1.5


def _extract_context_length(model_data: Dict[str, Any]) -> Optional[int]:
    """Pull the context window from a ``/v1/models`` entry.

    ds4-server reports the live window (``--ctx``) as ``context_length`` and
    mirrors it under ``top_provider``. Returns ``None`` when absent so callers
    can fall back to a default.
    """
    candidates = [
        model_data.get("context_length"),
        (model_data.get("top_provider") or {}).get("context_length"),
    ]
    for value in candidates:
        try:
            window = int(value)
        except (TypeError, ValueError):
            continue
        if window > 0:
            return window
    return None


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


class DS4Client(LocalProviderClient):
    """DwarfStar OpenAI-compatible local API client."""

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
            await self._async_request(
                "GET",
                "/models",
                timeout=_env_float("DS4_HEALTH_TIMEOUT", DEFAULT_DS4_HEALTH_TIMEOUT),
            )
            return True
        except Exception:
            return False

    async def get_status(self) -> ProviderStatus:
        """Get detailed DS4 status."""
        start_time = time.time()

        try:
            response = await self._async_request(
                "GET",
                "/models",
                timeout=_env_float("DS4_HEALTH_TIMEOUT", DEFAULT_DS4_HEALTH_TIMEOUT),
            )
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
            response = await self._async_request(
                "GET",
                "/models",
                timeout=_env_float("DS4_MODELS_TIMEOUT", DEFAULT_DS4_MODELS_TIMEOUT),
            )
            models = response.get("data", [])
            result = []
            for model_data in models:
                model_id = model_data.get("id", "")
                if not model_id:
                    continue
                result.append(
                    self._model_from_id(
                        model_id,
                        name=model_data.get("name"),
                        running=True,
                        context_window=_extract_context_length(model_data),
                    )
                )
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
        """Get DwarfStar model information."""
        models = await self.list_models()
        for model in models:
            if model.id == model_id:
                return model
        return None

    async def warmup(self, model: Optional[str] = None, timeout: float = 600.0) -> Dict[str, Any]:
        """Trigger the model load with a 1-token completion.

        DwarfStar mmaps a large GGUF and pays a one-time cost paging it in on
        the first inference. Calling this right after connect moves that cost to
        connect time (with progress feedback) instead of the user's first real
        prompt. Best-effort: returns timing/error rather than raising.

        Returns a dict: ``{"ok": bool, "elapsed": float, "error": str | None}``.
        """
        start = time.time()
        try:
            await self._async_request(
                "POST",
                "/chat/completions",
                data={
                    "model": model or DEFAULT_DS4_MODELS[0][0],
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "stream": False,
                },
                timeout=timeout,
            )
            return {"ok": True, "elapsed": time.time() - start, "error": None}
        except Exception as e:  # noqa: BLE001 - report, don't raise into connect UI
            return {"ok": False, "elapsed": time.time() - start, "error": str(e)}

    async def test_tool_calling(self, model_id: str) -> ToolTestResult:
        """DwarfStar's compatible endpoints support tool schemas in SuperQode."""
        return ToolTestResult(
            model_id=model_id,
            supports_tools=True,
            parallel_tools=False,
            tool_choice=["auto"],
            notes="DwarfStar is treated as a tool-capable local inference provider.",
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
        self,
        model_id: str,
        name: Optional[str] = None,
        running: bool = False,
        context_window: Optional[int] = None,
    ) -> LocalModel:
        laguna = is_laguna_model(model_id)
        display_name = DS4_MODEL_DISPLAY_NAMES.get(
            model_id,
            name or model_id.split("/")[-1],
        )
        return LocalModel(
            id=model_id,
            name=display_name,
            quantization="Q4_K_M" if laguna else "GGUF",
            # Honor the server-reported window (set by ds4-server --ctx) when
            # known; the harness budgets iterations/compaction against this, so
            # a stale 1M default would overflow a server started at --ctx 100000.
            context_window=context_window or (LAGUNA_CONTEXT_WINDOW if laguna else 1_000_000),
            supports_tools=True,
            supports_vision=False,
            family="laguna" if laguna else "deepseek",
            running=running,
            parameter_count="118B-A8B" if laguna else "",
            details={
                "host": self.host,
                "provider": "ds4",
                "engine": "dwarfstar",
                "reasoning_preservation": laguna,
                "thinking_mode": (
                    "off"
                    if model_id == "laguna-s-2.1-chat"
                    else "on"
                    if model_id == "laguna-s-2.1-reasoner"
                    else "request-controlled"
                    if laguna
                    else ""
                ),
            },
        )


def get_ds4_client(host: Optional[str] = None) -> DS4Client:
    """Get a DS4 client instance."""
    return DS4Client(host=host)
