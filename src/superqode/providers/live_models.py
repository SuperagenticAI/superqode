"""Live model discovery from a provider's own ``/v1/models`` endpoint.

This is the freshest possible source: it asks the provider directly, so a model
shows up the moment the provider serves it — no manual list updates, and no
waiting on models.dev to catalog it. Works for any OpenAI-compatible endpoint
(local runtimes and most BYOK hosts/aggregators).

Resolution for :func:`discover_provider_models`:

1. Provider's live ``/v1/models`` (when an OpenAI-compatible base URL is known),
   enriched with models.dev metadata (pricing/caps) where ids match.
2. models.dev catalog for that provider (auto-refreshing).
3. Empty — caller falls back to the curated list.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from .dynamic import provider_api_key, resolve_base_url, resolve_provider_def
from .model_studio import (
    METERED_PROVIDERS,
    is_plan_model,
    validate_metered_route,
    workspace_catalog_url,
)
from .models import ModelCapability, ModelInfo

logger = logging.getLogger(__name__)


@dataclass
class LiveDiscoveryResult:
    """Outcome of a provider model discovery."""

    provider: str
    models: List[ModelInfo]
    source: str  # "live" | "models.dev" | "examples" | "none"
    endpoint: Optional[str] = None
    error: Optional[str] = None


def _models_endpoints(base_url: str) -> List[str]:
    """Candidate ``/models`` URLs for a base that may or may not include ``/v1``."""
    base = base_url.rstrip("/")
    candidates = []
    if base.endswith("/v1"):
        candidates.append(f"{base}/models")
    else:
        candidates.append(f"{base}/v1/models")
        candidates.append(f"{base}/models")
    # De-dup, preserve order.
    seen: set[str] = set()
    return [u for u in candidates if not (u in seen or seen.add(u))]


def _parse_models_payload(payload: object) -> List[str]:
    """Extract model ids from an OpenAI-style ``/models`` response."""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id")]
        # Ollama-style {"models": [{"name": ...}]}
        models = payload.get("models")
        if isinstance(models, list):
            ids = []
            for m in models:
                if isinstance(m, dict):
                    ids.append(str(m.get("id") or m.get("name") or ""))
            return [i for i in ids if i]
    if isinstance(payload, list):
        return [str(m.get("id")) for m in payload if isinstance(m, dict) and m.get("id")]
    return []


async def discover_openai_compatible_models(
    base_url: str,
    api_key: Optional[str] = None,
    timeout: float = 8.0,
) -> List[str]:
    """Return model ids from an OpenAI-compatible ``/v1/models`` endpoint.

    Tries httpx if available, else a urllib fetch in a thread. Returns ``[]``
    on any failure (caller decides the fallback).
    """
    headers = {"User-Agent": "SuperQode/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    for url in _models_endpoints(base_url):
        payload = await _fetch_json(url, headers, timeout)
        ids = _parse_models_payload(payload) if payload is not None else []
        if ids:
            return sorted(set(ids))
    return []


async def _fetch_json(url: str, headers: dict, timeout: float) -> Optional[object]:
    try:
        import httpx  # type: ignore

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            logger.debug("GET %s -> %s", url, resp.status_code)
            return None
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - network is best-effort
        logger.debug("httpx GET %s failed: %s", url, exc)
        return None

    # urllib fallback in a thread.
    def _sync() -> Optional[object]:
        import urllib.request

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        req = urllib.request.Request(url, headers=headers)
        try:
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("urllib GET %s failed: %s", url, exc)
        return None

    return await asyncio.get_event_loop().run_in_executor(None, _sync)


def _model_studio_info(provider: str, model_id: str, row: dict | None = None) -> ModelInfo:
    row = row or {}
    info = row.get("model_info")
    info = info if isinstance(info, dict) else {}
    features = row.get("features")
    features = features if isinstance(features, list) else []

    def token_limit(field: str) -> int:
        value = info.get(field)
        return value if type(value) is int and value > 0 else 0

    context = token_limit("context_window")
    capabilities = []
    if "function-calling" in features:
        capabilities.append(ModelCapability.TOOLS)
    if "structured-outputs" in features:
        capabilities.append(ModelCapability.JSON_MODE)
    if token_limit("max_reasoning_tokens"):
        capabilities.append(ModelCapability.REASONING)
    if context > 100_000:
        capabilities.append(ModelCapability.LONG_CONTEXT)
    name = row.get("name")
    return ModelInfo(
        id=model_id,
        name=name if isinstance(name, str) and name else model_id,
        provider=provider,
        context_window=context,
        max_output=token_limit("max_output_tokens"),
        capabilities=capabilities,
        pricing_known=False,  # Pricing varies by workspace region and usage tier.
    )


async def _workspace_chat_models(url: str, key: str, timeout: float) -> dict[str, dict]:
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "SuperQode/1.0"}
    models: dict[str, dict] = {}
    for page in range(1, 51):
        payload = await _fetch_json(
            f"{url}?capabilities=TG&page_no={page}&page_size=20", headers, timeout
        )
        if not isinstance(payload, dict) or payload.get("success") is not True:
            return {}
        output = payload.get("output")
        if not isinstance(output, dict) or not isinstance(output.get("models"), list):
            return {}
        rows = output["models"]
        models.update(
            (row["model"], row)
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("model"), str) and row["model"]
        )
        total, size = output.get("total"), output.get("page_size")
        if (
            not rows
            or not isinstance(total, int)
            or not isinstance(size, int)
            or size <= 0
            or page * size >= total
        ):
            return models
    return {}  # Fall back instead of presenting a truncated list as complete.


async def _discover_model_studio(provider_id, base_url, key, examples, timeout):
    error = "Set the API key issued for this Model Studio region."
    if base_url and key:
        try:
            validate_metered_route(base_url, key)
        except ValueError as exc:
            error = str(exc)
        else:
            native_url = workspace_catalog_url(base_url)
            rows = {}
            if native_url:
                try:
                    rows = await asyncio.wait_for(
                        _workspace_chat_models(native_url, key, timeout), timeout
                    )
                except TimeoutError:
                    pass
            if not rows:
                ids = await discover_openai_compatible_models(base_url, key, timeout)
                rows = dict.fromkeys(ids)
            models = [
                _model_studio_info(provider_id, model, rows[model])
                for model in sorted(rows)
                if not is_plan_model(model)
            ]
            if models:
                return LiveDiscoveryResult(provider_id, models, "live", base_url)
            error = "Could not list models. Check the region, workspace endpoint, and API key."
    return LiveDiscoveryResult(
        provider_id,
        [_model_studio_info(provider_id, m) for m in examples],
        "examples",
        base_url,
        error,
    )


def _enrich_from_catalog(provider_id: str, model_ids: List[str]) -> List[ModelInfo]:
    """Turn live model ids into ModelInfo, borrowing models.dev metadata by id."""
    from .models_dev import get_models_dev

    client = get_models_dev()
    client.ensure_cache_loaded()
    catalog = client.get_models_for_provider(provider_id)

    out: List[ModelInfo] = []
    for mid in model_ids:
        meta = catalog.get(mid)
        if meta is not None:
            out.append(meta)
        else:
            # New / uncatalogued model — expose it with safe defaults so it is
            # selectable the moment the provider serves it.
            out.append(ModelInfo(id=mid, name=mid, provider=provider_id))
    return out


async def discover_provider_models(
    provider_id: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 8.0,
) -> LiveDiscoveryResult:
    """Discover a provider's models, freshest source first.

    Live ``/v1/models`` when an OpenAI-compatible base URL is available, else the
    models.dev catalog, else empty.
    """
    pdef = resolve_provider_def(provider_id)
    effective_base = base_url or (resolve_base_url(pdef) if pdef else None)
    effective_key = api_key or (provider_api_key(pdef) if pdef else None)

    if provider_id in METERED_PROVIDERS and pdef:
        return await _discover_model_studio(
            provider_id, effective_base, effective_key, pdef.example_models, timeout
        )

    if effective_base:
        try:
            ids = await discover_openai_compatible_models(effective_base, effective_key, timeout)
        except Exception as exc:  # noqa: BLE001
            ids = []
            live_error = str(exc)
        else:
            live_error = None
        if ids:
            return LiveDiscoveryResult(
                provider=provider_id,
                models=_enrich_from_catalog(provider_id, ids),
                source="live",
                endpoint=effective_base,
            )
    else:
        live_error = None

    # Fallback: models.dev catalog.
    from .models_dev import get_models_dev

    client = get_models_dev()
    client.ensure_cache_loaded()
    catalog = list(client.get_models_for_provider(provider_id).values())
    if catalog:
        return LiveDiscoveryResult(
            provider=provider_id,
            models=catalog,
            source="models.dev",
            endpoint=effective_base,
            error=live_error,
        )
    return LiveDiscoveryResult(
        provider=provider_id, models=[], source="none", endpoint=effective_base, error=live_error
    )


__all__ = [
    "LiveDiscoveryResult",
    "discover_openai_compatible_models",
    "discover_provider_models",
]
