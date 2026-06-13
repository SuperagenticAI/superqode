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

import asyncio
from typing import Any, Optional

_availability_cache: Optional[bool] = None


def _load_sdk() -> Any:
    import apple_fm

    return apple_fm


def apple_fm_available() -> bool:
    """True when the on-device system model can answer requests right now."""
    global _availability_cache
    if _availability_cache is not None:
        return _availability_cache
    try:
        sdk = _load_sdk()
        model = sdk.SystemLanguageModel.default
        availability = getattr(model, "availability", None)
        if availability is None:
            available = bool(getattr(model, "is_available", False))
        else:
            # Availability mirrors the Swift enum; "available" as a string or
            # an object whose truthiness/name says so.
            name = str(getattr(availability, "name", availability)).lower()
            available = "unavailable" not in name and "available" in name
        _availability_cache = available
    except Exception:
        _availability_cache = False
    return _availability_cache


def _generate_sync(prompt: str, system: str = "", max_tokens: int = 600) -> str:
    sdk = _load_sdk()
    model = sdk.SystemLanguageModel.default
    kwargs: dict = {}
    if system:
        kwargs["instructions"] = system
    session = sdk.LanguageModelSession(model, **kwargs)
    options = None
    options_cls = getattr(sdk, "GenerationOptions", None)
    if options_cls is not None:
        try:
            options = options_cls(temperature=0.0, maximum_response_tokens=max_tokens)
        except TypeError:
            options = None
    if options is not None:
        response = session.respond(prompt, options=options)
    else:
        response = session.respond(prompt)
    return str(getattr(response, "content", response) or "")


async def apple_fm_generate(prompt: str, system: str = "", max_tokens: int = 600) -> str:
    """One on-device completion, off the event loop. Raises on failure."""
    return await asyncio.to_thread(_generate_sync, prompt, system, max_tokens)


__all__ = ["apple_fm_available", "apple_fm_generate"]
