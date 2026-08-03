"""In-memory session storage.

Ported from ``packages/agent/src/harness/session/memory-repo.ts`` of
earendil-works/pi (MIT). Used by tests and by callers that want a session tree
without touching disk.
"""

from __future__ import annotations

from uuid import uuid4

from .entries import (
    LabelEntry,
    LeafEntry,
    MessageEntry,
    SessionInfoEntry,
    SessionMetadata,
    SessionStats,
    SessionTreeEntry,
    current_timestamp,
)


class MemorySessionStorage:
    """Holds a session tree in a list, in append order."""

    def __init__(self, *, session_id: str | None = None, cwd: str = "") -> None:
        self._metadata = SessionMetadata(id=session_id or uuid4().hex[:12], cwd=cwd)
        self._entries: list[SessionTreeEntry] = []
        self._by_id: dict[str, SessionTreeEntry] = {}
        self._leaf_id: str | None = None

    @property
    def metadata(self) -> SessionMetadata:
        return self._metadata

    async def read_head(self) -> str | None:
        return self._leaf_id

    async def read_entry(self, entry_id: str) -> SessionTreeEntry | None:
        return self._by_id.get(entry_id)

    async def read_entries(self) -> list[SessionTreeEntry]:
        return list(self._entries)

    async def read_path_to_root(self, leaf_id: str | None) -> list[SessionTreeEntry]:
        path: list[SessionTreeEntry] = []
        seen: set[str] = set()
        current = leaf_id
        while current is not None:
            entry = self._by_id.get(current)
            if entry is None or entry.id in seen:
                break
            seen.add(entry.id)
            path.append(entry)
            current = entry.parent_id
        path.reverse()
        return path

    async def append_entry(self, entry: SessionTreeEntry) -> None:
        self._entries.append(entry)
        self._by_id[entry.id] = entry
        # A leaf entry moves the pointer instead of extending the branch, which
        # is what makes navigating away from a branch non-destructive.
        self._leaf_id = entry.target_id if isinstance(entry, LeafEntry) else entry.id

    async def get_label(self, entry_id: str) -> str | None:
        label: str | None = None
        for entry in self._entries:
            if isinstance(entry, LabelEntry) and entry.target_id == entry_id:
                label = entry.label
        return label

    async def get_name(self) -> str | None:
        name: str | None = None
        for entry in self._entries:
            if isinstance(entry, SessionInfoEntry):
                name = entry.name
        return name

    async def get_stats(self) -> SessionStats:
        return SessionStats(
            entry_count=len(self._entries),
            message_count=sum(1 for entry in self._entries if isinstance(entry, MessageEntry)),
        )

    def _next_timestamp(self) -> str:
        return current_timestamp()


__all__ = ["MemorySessionStorage"]
