"""Normalized harness events."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

HARNESS_PROTOCOL_VERSION = "1.0"


def generate_event_id() -> str:
    """Return an opaque identifier for one durable harness event."""
    return f"evt_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class HarnessEvent:
    """One normalized harness lifecycle event.

    The protocol envelope fields are additive.  Legacy callers can continue to
    construct events with only ``type`` and ``data``; stores fill the sequence
    and run context when the event is appended.
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    session_id: str | None = None
    run_id: str | None = None
    protocol_version: str = HARNESS_PROTOCOL_VERSION
    event_id: str = field(default_factory=generate_event_id)
    sequence: int = 0
    harness_id: str | None = None
    parent_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "data": dict(self.data),
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "protocol_version": self.protocol_version,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "harness_id": self.harness_id,
            "parent_event_id": self.parent_event_id,
        }
