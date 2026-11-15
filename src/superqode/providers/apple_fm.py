"""Apple Foundation Models as a zero-cost utility model.

On Apple Silicon with Apple Intelligence enabled, the on-device system
model is available through the ``apple-fm-sdk`` Python package (the
Python mirror of the Swift FoundationModels API). It is a small model,
unsuited to driving the main coding loop, but ideal for utility calls:
rubric grading, memory extraction, and summaries, at zero token cost and
with no server to manage.

Everything here degrades gracefully: if the SDK is missing, the OS is too
old, or Apple Intelligence is disabled, ``apple_fm_available()`` is False
and callers fall back to their normal model.
"""

from __future__ import annotations

import os
from typing import Any, Optional

_availability_cache: Optional[bool] = None


def _load_sdk() -> Any:
    import apple_fm_sdk

    return apple_fm_sdk


def apple_fm_available() -> bool:
    """True when the on-device system model can answer requests right now."""
    global _availability_cache
    if os.environ.get("SUPERQODE_APPLE_HELPER"):
        from superqode.local.apple import status

        return status().get("available") is True
    if _availability_cache is not None:
        return _availability_cache
    try:
        sdk = _load_sdk()
        available, _reason = sdk.SystemLanguageModel().is_available()
        _availability_cache = bool(available)
    except Exception:
        _availability_cache = False
    return _availability_cache


async def apple_fm_generate(prompt: str, system: str = "", max_tokens: int = 600) -> str:
    """One on-device completion. Raises on failure."""
    if os.environ.get("SUPERQODE_APPLE_HELPER"):
        from .gateway.litellm_gateway import LiteLLMGateway
        from .gateway.base import Message

        result = await LiteLLMGateway().chat_completion(
            messages=[Message("system", system), Message("user", prompt)],
            model="system-on-device",
            provider="apple-foundation",
            max_tokens=max_tokens,
        )
        return result.content
    sdk = _load_sdk()
    session = sdk.LanguageModelSession(**({"instructions": system} if system else {}))
    options = sdk.GenerationOptions(temperature=0.0, maximum_response_tokens=max_tokens)
    response = await session.respond(prompt, options=options)
    return str(getattr(response, "content", response) or "")


__all__ = ["apple_fm_available", "apple_fm_generate"]
