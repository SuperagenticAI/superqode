"""Routing for utility model calls: grading, memory extraction, summaries.

These calls are small, frequent, and quality-tolerant, so they should not
burn main-model tokens or main-model latency. ``SUPERQODE_UTILITY_PROVIDER``
redirects them:

- ``apple-fm``: the on-device Apple Foundation Model (free, instant, macOS)
- ``provider/model`` (for example ``ollama/gemma4:e4b``): any gateway route
- unset: utility calls use the session's own provider and model

Routing fails open: if the utility route errors, the call falls back to the
session model rather than failing the feature.
"""

from __future__ import annotations

import os
from typing import Any, Optional, Tuple

UTILITY_PROVIDER_ENV = "SUPERQODE_UTILITY_PROVIDER"


def utility_route() -> Optional[Tuple[str, str]]:
    """The configured (provider, model) override, or None.

    ``apple-fm`` maps to ("apple-fm", ""); ``provider/model`` splits on the
    first slash; a bare provider name means "that provider, default model".
    """
    raw = os.environ.get(UTILITY_PROVIDER_ENV, "").strip()
    if not raw:
        return None
    if raw.lower() in ("apple-fm", "apple_fm", "applefm"):
        return ("apple-fm", "")
    if "/" in raw:
        provider, model = raw.split("/", 1)
        return (provider.strip(), model.strip())
    return (raw, "")


async def utility_completion(
    gateway: Any,
    provider: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 600,
) -> str:
    """One utility completion, routed per SUPERQODE_UTILITY_PROVIDER.

    ``provider``/``model`` are the session's own route, used when no utility
    override is set and as the fallback when the override fails.
    """
    route = utility_route()
    if route is not None:
        route_provider, route_model = route
        if route_provider == "apple-fm":
            try:
                from ..providers.apple_fm import apple_fm_available, apple_fm_generate

                if apple_fm_available():
                    return await apple_fm_generate(user, system=system, max_tokens=max_tokens)
            except Exception:
                pass  # fall through to the session model
        else:
            try:
                return await _gateway_completion(
                    gateway, route_provider, route_model or model, system, user, max_tokens
                )
            except Exception:
                pass  # fall through to the session model

    return await _gateway_completion(gateway, provider, model, system, user, max_tokens)


async def _gateway_completion(
    gateway: Any,
    provider: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
) -> str:
    from ..providers.gateway.base import Message

    response = await gateway.chat_completion(
        messages=[
            Message(role="system", content=system),
            Message(role="user", content=user),
        ],
        model=model,
        provider=provider,
        temperature=0.0,
        max_tokens=max_tokens,
    )
    return getattr(response, "content", "") or ""


__all__ = ["UTILITY_PROVIDER_ENV", "utility_completion", "utility_route"]
