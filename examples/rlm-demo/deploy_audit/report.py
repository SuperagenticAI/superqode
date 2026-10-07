"""Release-health report assembled from parsed deployment events."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .parser import load_events


def build_release_health(path: str | Path) -> dict[str, Any]:
    """Return the deterministic release-health summary defined by RUNBOOK.md."""
    events, ignored = load_events(path)

    # Group valid records by (service, deployment_id)
    deployments: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for event in events:
        deployments[(event.service, event.deployment_id)].append(event)

    # For each deployment, determine the authoritative event:
    # highest numbered attempt; tie-breaker: latest timestamp.
    auth_per_service: dict[str, list[Any]] = defaultdict(list)
    for (service, _), dep_events in deployments.items():
        auth_event = max(dep_events, key=lambda e: (e.attempt, e.timestamp))
        auth_per_service[service].append(auth_event)

    healthy: list[str] = []
    unhealthy: dict[str, str] = {}

    for service in sorted(auth_per_service.keys()):
        # Most recent deployment ordered by authoritative record's timestamp
        latest_event = max(auth_per_service[service], key=lambda e: e.timestamp)
        if latest_event.status == "succeeded":
            if latest_event.duration_seconds <= 300:
                healthy.append(service)
            else:
                unhealthy[service] = "slow"
        else:
            unhealthy[service] = latest_event.status

    return {
        "services": len(healthy) + len(unhealthy),
        "healthy": healthy,
        "unhealthy": unhealthy,
        "ignored_records": ignored,
    }


__all__ = ["build_release_health"]
