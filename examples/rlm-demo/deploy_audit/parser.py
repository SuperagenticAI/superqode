"""Strict parsing for the append-only deployment feed."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class DeploymentEvent:
    service: str
    deployment_id: str
    attempt: int
    status: str
    duration_seconds: int
    timestamp: datetime


def parse_events(lines: Iterable[str]) -> tuple[list[DeploymentEvent], int]:
    events: list[DeploymentEvent] = []
    ignored = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            event = DeploymentEvent(
                service=str(raw["service"]).strip(),
                deployment_id=str(raw["deployment_id"]).strip(),
                attempt=int(raw["attempt"]),
                status=str(raw["status"]).strip().lower(),
                duration_seconds=int(raw["duration_seconds"]),
                timestamp=datetime.fromisoformat(str(raw["timestamp"]).replace("Z", "+00:00")),
            )
            if (
                not event.service
                or not event.deployment_id
                or event.attempt < 1
                or event.duration_seconds < 0
                or event.status not in {"succeeded", "failed", "cancelled"}
            ):
                raise ValueError("invalid deployment event")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            ignored += 1
            continue
        events.append(event)
    return events, ignored


def load_events(path: str | Path) -> tuple[list[DeploymentEvent], int]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return parse_events(handle)


__all__ = ["DeploymentEvent", "load_events", "parse_events"]
