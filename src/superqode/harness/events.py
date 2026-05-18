"""Normalized harness events."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HarnessEvent:
    """One normalized harness lifecycle event."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    session_id: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "data": dict(self.data),
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "run_id": self.run_id,
        }
