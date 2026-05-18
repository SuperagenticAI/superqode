"""Harness backend registry."""

from __future__ import annotations

from .base import HarnessBackend
from .deepagents import DeepAgentsHarnessBackend
from .runtime import RuntimeHarnessBackend

_RUNTIME_BACKENDS = {"builtin", "adk", "openai-agents"}
_OPTIONAL_BACKENDS = {"deepagents"}


def create_harness_backend(name: str | None) -> HarnessBackend:
    """Create a harness backend by name."""
    resolved = (name or "builtin").strip().lower()
    if resolved in _RUNTIME_BACKENDS:
        return RuntimeHarnessBackend(resolved)
    if resolved == "deepagents":
        return DeepAgentsHarnessBackend()
    valid = ", ".join(known_harness_backend_names())
    raise ValueError(f"Unknown harness backend {name!r}. Known: {valid}")


def known_harness_backend_names() -> list[str]:
    """Return known harness backend names."""
    return sorted(_RUNTIME_BACKENDS | _OPTIONAL_BACKENDS)
