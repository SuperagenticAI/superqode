"""Storage protocol behind a session tree.

Ported from ``packages/agent/src/harness/session/repository.ts`` of
earendil-works/pi (MIT). Phase 2 ships the in-memory implementation; phase 3
adds the JSONL one behind the same protocol.
"""

from __future__ import annotations

from typing import Protocol

from .entries import SessionMetadata, SessionStats, SessionTreeEntry


class SessionError(RuntimeError):
    """Raised for missing entries, invalid files and unusable session state."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SessionStorage(Protocol):
    """Append-only entry store for one session."""

    @property
    def metadata(self) -> SessionMetadata: ...

    async def read_head(self) -> str | None:
        """Return the current leaf id, or None when the session is empty."""
        ...

    async def read_entry(self, entry_id: str) -> SessionTreeEntry | None: ...

    async def read_entries(self) -> list[SessionTreeEntry]:
        """Every entry in append order, across all branches."""
        ...

    async def read_path_to_root(self, leaf_id: str | None) -> list[SessionTreeEntry]:
        """Entries from the root to ``leaf_id``, in order.

        pi's storage method is ``readPathToRootOrCompaction`` and stops early at
        a compaction entry as an optimisation. PiPy returns the full path and
        lets the context builder apply the compaction cut, which is equivalent
        and keeps the storage protocol smaller.
        """
        ...

    async def append_entry(self, entry: SessionTreeEntry) -> None: ...

    async def get_label(self, entry_id: str) -> str | None: ...

    async def get_name(self) -> str | None: ...

    async def get_stats(self) -> SessionStats: ...


__all__ = ["SessionError", "SessionStorage"]
