"""Conservative family defaults; serving capabilities take precedence."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CodeGemProfile:
    family: str
    generation: int | None
    native_tools: bool
    system_role: bool
    temperature: float
    thinking: bool
    thinking_level: str | None = None


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
        # Google recommends retaining the default 1.0 for Gemini 3.
        return CodeGemProfile(
            family,
            generation,
            True,
            True,
            1.0,
            generation in {2, 3},
            "high" if generation == 3 else None,
        )
    if provider.lower() not in {"ollama", "lmstudio", "llamacpp"}:
        raise ValueError("CodeGem local Gemma requires ollama, lmstudio, or llamacpp")
    modern = generation == 4
    return CodeGemProfile(family, generation, modern, modern, 1.0 if modern else 0.2, modern)
