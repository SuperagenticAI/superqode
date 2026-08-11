"""Release-health report assembled from parsed deployment events."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .parser import load_events


def build_release_health(path: str | Path) -> dict[str, Any]:
    """Return the deterministic release-health summary defined by RUNBOOK.md."""
    events, ignored = load_events(path)
    raise NotImplementedError(
        f"summarise {len(events)} valid deployment events and {ignored} ignored records"
    )


__all__ = ["build_release_health"]
