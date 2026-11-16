"""Shared picker fields for harness rows sent to the desktop and phone apps."""

from __future__ import annotations

from pathlib import Path

# Profiles that run with Apple's on-device model without a separate model binding.
APPLE_PROFILES = frozenset({"silicon", "apple-local"})


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def harness_source(definition, root) -> str:
    """Where a harness comes from: ``project``, ``user`` or ``built-in``."""
    path = definition.path
    if definition.source in {"file", "registry"}:
        if path is not None and root is not None and _within(Path(path), Path(root)):
            return "project"
        return "user"
    return "built-in"


def picker_fields(definition, root, names: dict[str, str] | None = None) -> dict:
    """Row metadata the harness pickers use to group and filter harnesses.

    ``names`` maps harness ids to display names so ``based_on_name`` can read
    "Silicon Harness" rather than the raw ``inherits`` value.
    """
    profile = str(definition.spec.model_policy.profile or "").strip().lower()
    inherits = str(getattr(definition.spec, "inherits", None) or "").strip()
    based_on_name = ""
    if inherits:
        based_on_name = (names or {}).get(inherits) or Path(inherits).stem or inherits
    return {
        "profile": profile,
        "source": harness_source(definition, root),
        "category": definition.category,
        "apple_compatible": profile in APPLE_PROFILES,
        "based_on": inherits,
        "based_on_name": based_on_name,
        "path": str(definition.path) if definition.path else None,
    }


def display_names(definitions) -> dict[str, str]:
    return {definition.id: definition.display_name for definition in definitions}
