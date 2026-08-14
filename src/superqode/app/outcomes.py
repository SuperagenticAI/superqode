"""Structured user-visible outcomes for the terminal product surfaces.

Conversation messages and product outcomes are different things.  A command
result may need a focused screen, a transient notification, an activity entry,
and a compact transcript receipt.  Keeping the result structured lets each
surface render it without reparsing prose from ``ConversationLog``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from itertools import count


class OutcomeSeverity(str, Enum):
    """Visual and behavioural importance of an outcome."""

    SUCCESS = "success"
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class OutcomeAction:
    """One action offered from an outcome screen."""

    id: str
    label: str
    command: str = ""
    primary: bool = False


_OUTCOME_IDS = count(1)


@dataclass(frozen=True)
class Outcome:
    """A completed or actionable product event."""

    title: str
    summary: str
    details: tuple[str, ...] = ()
    severity: OutcomeSeverity = OutcomeSeverity.INFORMATION
    actions: tuple[OutcomeAction, ...] = ()
    source: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: f"outcome-{next(_OUTCOME_IDS)}")

    @property
    def receipt(self) -> str:
        """Compact text suitable for the durable conversation transcript."""
        return f"{self.title}: {self.summary}"


class OutcomeStore:
    """Small in-process activity history.

    The transcript remains the durable record.  This store exists so a result
    can be revisited during the current terminal session without searching the
    transcript.  It intentionally has a hard cap so integrations cannot grow
    memory indefinitely.
    """

    def __init__(self, limit: int = 100) -> None:
        self.limit = max(1, int(limit))
        self._items: list[Outcome] = []
        self._read: set[str] = set()

    def add(self, outcome: Outcome, *, read: bool = False) -> Outcome:
        self._items.append(outcome)
        if read:
            self._read.add(outcome.id)
        if len(self._items) > self.limit:
            removed = self._items.pop(0)
            self._read.discard(removed.id)
        return outcome

    def list(self) -> list[Outcome]:
        return list(reversed(self._items))

    def mark_read(self, outcome_id: str) -> None:
        self._read.add(outcome_id)

    @property
    def unread_count(self) -> int:
        return sum(item.id not in self._read for item in self._items)


__all__ = [
    "Outcome",
    "OutcomeAction",
    "OutcomeSeverity",
    "OutcomeStore",
]
