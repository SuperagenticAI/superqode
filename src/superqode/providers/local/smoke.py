"""Shared local-provider health and smoke helpers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from superqode.providers.local.base import LocalProviderClient, LocalModel, ToolTestResult
from superqode.providers.registry import PROVIDERS, ProviderCategory


LOCAL_CLIENTS: dict[str, Callable[[], LocalProviderClient]] = {}


def _load_local_clients() -> dict[str, Callable[[], LocalProviderClient]]:
    """Load local client classes lazily to keep CLI startup light."""
    if LOCAL_CLIENTS:
        return LOCAL_CLIENTS

    from superqode.providers.local.ds4 import DS4Client
    from superqode.providers.local.lmstudio import LMStudioClient
    from superqode.providers.local.mlx import MLXClient
    from superqode.providers.local.ollama import OllamaClient
    from superqode.providers.local.sglang import SGLangClient
    from superqode.providers.local.tgi import TGIClient
    from superqode.providers.local.vllm import VLLMClient

    LOCAL_CLIENTS.update(
        {
            "ds4": DS4Client,
            "lmstudio": LMStudioClient,
            "mlx": MLXClient,
            "ollama": OllamaClient,
            "sglang": SGLangClient,
            "tgi": TGIClient,
            "vllm": VLLMClient,
        }
    )
    return LOCAL_CLIENTS


def supported_local_smoke_providers() -> list[str]:
    """Return local providers with smoke-test client support."""
    return sorted(_load_local_clients())


def all_local_provider_ids() -> list[str]:
    """Return all registry local/self-hosted provider IDs."""
    return sorted(
        pid for pid, provider in PROVIDERS.items() if provider.category == ProviderCategory.LOCAL
    )


def default_model_for_provider(provider_id: str, models: list[LocalModel]) -> str:
    """Pick a practical default model for smoke checks."""
    if models:
        running = next((model for model in models if model.running), None)
        return (running or models[0]).id

    provider = PROVIDERS.get(provider_id)
    if provider and provider.example_models:
        return provider.example_models[0]
    return ""


async def smoke_local_provider(
    provider_id: str,
    model: str | None = None,
    *,
    run_prompt: bool = False,
    prompt: str = "Reply with: ok",
    tool_test: bool = True,
) -> dict[str, Any]:
    """Run a structured local provider smoke check.

    The default check is intentionally cheap: instantiate the provider client,
    check server reachability, list models, and run the provider-specific tool
    capability probe when possible. A real completion only runs with
    ``run_prompt=True``.
    """
    provider = PROVIDERS.get(provider_id)
    if not provider:
        return {
            "provider": provider_id,
            "name": provider_id,
            "registered": False,
            "supported": False,
            "available": False,
            "error": f"Provider not found: {provider_id}",
        }

    client_factory = _load_local_clients().get(provider_id)
    if provider.category != ProviderCategory.LOCAL or client_factory is None:
        return {
            "provider": provider_id,
            "name": provider.name,
            "registered": True,
            "supported": False,
            "available": False,
            "model": model or "",
            "models": [],
            "tool_support": False,
            "completion_ran": False,
            "completion_ok": False,
            "response_preview": "",
            "setup_hint": provider.notes,
            "error": "No local smoke client is available for this provider yet",
        }

    client = client_factory()
    available = await client.is_available()

    try:
        status = await client.get_status()
        status_payload = asdict(status)
        if hasattr(status_payload.get("provider_type"), "value"):
            status_payload["provider_type"] = status_payload["provider_type"].value
        if status_payload.get("last_checked") is not None:
            status_payload["last_checked"] = status_payload["last_checked"].isoformat()
        status_error = status_payload.get("error", "")
    except Exception as exc:
        status_payload = {}
        status_error = str(exc)

    try:
        models = await client.list_models()
    except Exception as exc:
        models = []
        status_error = status_error or str(exc)

    selected_model = model or default_model_for_provider(provider_id, models)

    tool_result = ToolTestResult(model_id=selected_model, supports_tools=False)
    if tool_test and selected_model:
        try:
            tool_result = await client.test_tool_calling(selected_model)
        except Exception as exc:
            tool_result = ToolTestResult(
                model_id=selected_model,
                supports_tools=False,
                error=str(exc),
            )

    payload: dict[str, Any] = {
        "provider": provider_id,
        "name": provider.name,
        "host": getattr(client, "host", provider.default_base_url or ""),
        "registered": True,
        "supported": True,
        "available": available,
        "model": selected_model,
        "models": [item.id for item in models],
        "running_models": [item.id for item in models if item.running],
        "tool_support": tool_result.supports_tools,
        "tool_result": asdict(tool_result),
        "status": status_payload,
        "completion_ran": False,
        "completion_ok": False,
        "response_preview": "",
        "setup_hint": provider.notes,
    }

    if status_error:
        payload["status_error"] = status_error

    if run_prompt:
        payload["completion_ran"] = True
        if not available:
            payload["error"] = f"{provider.name} server is not reachable"
            return payload
        if not selected_model:
            payload["error"] = "No model specified and no models were discovered"
            return payload

        try:
            from superqode.providers.gateway.base import Message
            from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

            gateway = LiteLLMGateway()
            response = await gateway.chat_completion(
                messages=[Message(role="user", content=prompt)],
                model=selected_model,
                provider=provider_id,
                max_tokens=32,
                temperature=0,
            )
            content = response.content or ""
            payload["completion_ok"] = bool(content)
            payload["response_preview"] = content[:200]
        except Exception as exc:
            payload["error"] = str(exc)

    return payload
