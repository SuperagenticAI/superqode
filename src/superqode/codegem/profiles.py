"""Conservative family defaults; serving capabilities take precedence."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Google's documented default thinking level and supported levels per model
# (https://ai.google.dev/gemini-api/docs/thinking). CodeGem does not send a
# thinking level unless the user asks for one, so Google's default applies.
# Longest prefix wins, so "gemini-3.1-pro" matches before "gemini-3-pro".
_LEVELS_LMH = ("low", "medium", "high")
_LEVELS_ALL = ("minimal", "low", "medium", "high")
GEMINI_THINKING: dict[str, tuple[str, tuple[str, ...]]] = {
    "gemini-4-argon": ("medium", _LEVELS_LMH),
    "gemini-3.8-flash": ("medium", _LEVELS_LMH),
    "gemini-3.6-flash": ("medium", _LEVELS_ALL),
    "gemini-3.5-flash-lite": ("minimal", _LEVELS_ALL),
    "gemini-3.1-pro": ("high", _LEVELS_LMH),
    "gemini-3-flash": ("high", _LEVELS_ALL),
    "gemini-3-pro": ("high", ("low", "high")),
}


@dataclass(frozen=True)
class CodeGemProfile:
    family: str
    generation: int | None
    native_tools: bool
    system_role: bool
    temperature: float
    thinking: bool
    # Google's documented default, reported only; it is never forced.
    thinking_level: str | None = None
    # Levels Google documents for this model; None means unknown.
    thinking_levels: tuple[str, ...] | None = None


def _gemini_thinking(name: str):
    for prefix in sorted(GEMINI_THINKING, key=len, reverse=True):
        if name == prefix or name.startswith(prefix + "-"):
            return GEMINI_THINKING[prefix]
    return None, None


def resolve_profile(model: str, provider: str) -> CodeGemProfile:
    """Accept Google's families, including repository and quantization prefixes.

    Unknown generations use conservative defaults, never guessed context sizes
    or future-generation thinking parameters. Context is supplied by the host.
    """
    name = model.lower().split("/")[-1]
    match = re.match(r"(gemini|(?:code)?gemma)[-_.]?(\d+)?n?(?:\b|[-_.:])", name)
    if not match:
        raise ValueError("CodeGem supports only Gemini and Gemma model identities")
    family = "gemini" if match[1] == "gemini" else "gemma"
    generation = int(match[2]) if match[2] else None
    if family == "gemini":
        if provider.lower() not in {"google", "gemini"}:
            raise ValueError("CodeGem Gemini requires the google provider (Gemini API)")
        default, levels = _gemini_thinking(name)
        # Google recommends retaining the default 1.0 for Gemini 3.
        return CodeGemProfile(
            family,
            generation,
            True,
            True,
            1.0,
            generation in {2, 3, 4},
            default,
            levels,
        )
    if provider.lower() not in {"ollama", "lmstudio", "llamacpp"}:
        raise ValueError("CodeGem local Gemma requires ollama, lmstudio, or llamacpp")
    modern = generation == 4
    return CodeGemProfile(family, generation, modern, modern, 1.0 if modern else 0.2, modern)


def gemini_thinking_level(model: str, profile: CodeGemProfile, level: str) -> str:
    """Validate an explicit reasoning choice for a Gemini model.

    Returns the API value (upper case). Raises ValueError with the supported
    levels when the model does not document the requested level.
    """
    level = str(level).lower()
    if profile.generation not in {3, 4}:
        raise ValueError(
            f"CodeGem cannot map reasoning '{level}' for {model}; use "
            "runtime.config.thinking_config for this model's native thinking controls"
        )
    allowed = profile.thinking_levels or _LEVELS_LMH
    if level not in allowed:
        source = "documents" if profile.thinking_levels else "assumes, for an unlisted model,"
        raise ValueError(
            f"Thinking level '{level}' is not supported for {model}. Google {source} "
            f"these levels: {', '.join(allowed)}. Choose one of them, or set "
            "runtime.config.thinking_config to pass a raw value."
        )
    return level.upper()


def supports_model(model: str, provider: str) -> bool:
    """Use the execution contract when filtering model pickers."""
    try:
        resolve_profile(model, provider)
    except ValueError:
        return False
    return True
