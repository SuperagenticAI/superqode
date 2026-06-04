"""models.dev-driven BYOK provider resolution.

SuperQode curates ~38 first-class providers in :mod:`registry`. models.dev
catalogs 130+ providers (and 5000+ models), the long tail of which are
OpenAI-compatible aggregators/hosts. Rather than hardcode all of them, this
module synthesizes a :class:`ProviderDef` on demand from models.dev metadata
(``env`` key vars + ``api`` base URL), routing them as OpenAI-compatible.

Resolution order (see :func:`resolve_provider_def`):

1. Curated registry entry (first-class, hand-tuned) — always wins.
2. Synthesized def from cached models.dev metadata (OpenAI-compatible).
3. ``None`` when the id is unknown to both.

Synthesized providers carry ``dynamic=True`` so the gateway passes
``api_base``/``api_key`` explicitly instead of mutating global ``OPENAI_*``
env (which would clobber a user's real OpenAI credentials).
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from .models_dev import PROVIDER_ID_MAP, get_models_dev
from .registry import PROVIDERS, ProviderCategory, ProviderDef, ProviderTier

# models.dev provider ids that are local runtimes — synthesize as LOCAL so the
# UI/categorization stays sensible even when not in the curated registry.
_LOCAL_IDS = {"ollama", "ollama-cloud", "lmstudio", "llamacpp", "llama-cpp", "mlx", "vllm", "sglang", "tgi"}


def _base_url_env_name(provider_id: str) -> str:
    """Deterministic per-provider base-URL env var (e.g. ``DEEPINFRA_BASE_URL``)."""
    slug = provider_id.upper().replace("-", "_").replace(".", "_")
    return f"{slug}_BASE_URL"


def synthesize_provider_def(provider_id: str) -> Optional[ProviderDef]:
    """Build a ProviderDef from cached models.dev metadata, or ``None``.

    Uses OpenAI-compatible routing: ``litellm_prefix='openai/'`` with the base
    URL taken from the provider's models.dev ``api`` field. The API key is read
    from the first of the provider's models.dev ``env`` vars at call time.
    """
    client = get_models_dev()
    client.ensure_cache_loaded()
    info = client.get_provider(provider_id)
    if info is None:
        return None

    # Use the normalized id models.dev reports (handles aliases like x-ai->xai).
    resolved_id = PROVIDER_ID_MAP.get(provider_id, info.id or provider_id)
    is_local = resolved_id in _LOCAL_IDS
    api_url = info.api_url or ""

    if api_url:
        # We have an explicit endpoint -> route as OpenAI-compatible against it.
        prefix = "openai/"
        base_url_env: Optional[str] = _base_url_env_name(resolved_id)
        default_base_url: Optional[str] = api_url
        notes = "Auto-configured from models.dev (OpenAI-compatible routing)."
    else:
        # No endpoint advertised -> rely on LiteLLM's built-in routing for this
        # provider id (covers natively-supported hosts like deepinfra/novita).
        prefix = f"{resolved_id}/"
        base_url_env = None
        default_base_url = None
        notes = "Auto-configured from models.dev (native LiteLLM routing)."

    return ProviderDef(
        id=resolved_id,
        name=info.name or resolved_id,
        tier=ProviderTier.LOCAL if is_local else ProviderTier.TIER2,
        category=ProviderCategory.LOCAL if is_local else ProviderCategory.MODEL_HOSTS,
        env_vars=list(info.env_vars or []),
        litellm_prefix=prefix,
        docs_url=info.doc_url or "",
        base_url_env=base_url_env,
        default_base_url=default_base_url,
        notes=notes,
        dynamic=True,
    )


def resolve_provider_def(provider_id: Optional[str]) -> Optional[ProviderDef]:
    """Curated registry entry, else a synthesized models.dev def, else ``None``."""
    if not provider_id:
        return None
    curated = PROVIDERS.get(provider_id)
    if curated is not None:
        return curated
    return synthesize_provider_def(provider_id)


def provider_api_key(provider_def: ProviderDef) -> Optional[str]:
    """First non-empty value among the provider's API-key env vars."""
    for env_name in provider_def.env_vars or []:
        value = os.environ.get(env_name)
        if value:
            return value
    return None


def resolve_base_url(provider_def: ProviderDef) -> Optional[str]:
    """Effective base URL: env override, then the def's default."""
    if provider_def.base_url_env:
        override = os.environ.get(provider_def.base_url_env)
        if override:
            return override
    return provider_def.default_base_url


def all_provider_ids() -> List[str]:
    """Curated ids unioned with every provider models.dev knows about."""
    client = get_models_dev()
    client.ensure_cache_loaded()
    ids: Dict[str, None] = {pid: None for pid in PROVIDERS}
    for pid in client.get_providers():
        ids.setdefault(pid, None)
    return list(ids)


def is_curated_provider(provider_id: str) -> bool:
    """True when ``provider_id`` is a first-class (hand-tuned) registry entry."""
    return provider_id in PROVIDERS


__all__ = [
    "synthesize_provider_def",
    "resolve_provider_def",
    "provider_api_key",
    "resolve_base_url",
    "all_provider_ids",
    "is_curated_provider",
]
