"""Append-only JSONL session storage.

Ported from ``packages/agent/src/harness/session/jsonl-repo.ts`` of
earendil-works/pi (MIT).

File layout, byte-compatible with pi:

- line 1 is a session header, ``{"type":"session","version":3, ...}``
- every later line is one tree entry, appended and never rewritten
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .codec import SessionCodecError, decode_entry, encode_entry
from .entries import LeafEntry, MessageEntry, SessionMetadata, SessionStats, SessionTreeEntry
from .storage import SessionError

SESSION_FORMAT_VERSION = 3


def _invalid_session(path: Path, message: str) -> SessionError:
    return SessionError("invalid_session", f"Invalid JSONL session file {path}: {message}")


def _invalid_entry(path: Path, line_number: int, message: str) -> SessionError:
    return SessionError(
        "invalid_entry", f"Invalid JSONL session file {path}: line {line_number} {message}"
    )


def encode_header(metadata: SessionMetadata) -> dict[str, Any]:
    header: dict[str, Any] = {
        "type": "session",
        "version": SESSION_FORMAT_VERSION,
        "id": metadata.id,
        "timestamp": metadata.timestamp,
        "cwd": metadata.cwd,
    }
    if metadata.parent_session:
        header["parentSession"] = metadata.parent_session
    if metadata.metadata:
        header["metadata"] = dict(metadata.metadata)
    return header


def decode_header(line: str, path: Path) -> SessionMetadata:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as error:
        raise _invalid_session(path, "first line is not a valid session header") from error
    if not isinstance(payload, dict):
        raise _invalid_session(path, "first line is not a valid session header")
    if payload.get("type") != "session":
        raise _invalid_session(path, "first line is not a valid session header")
    if payload.get("version") != SESSION_FORMAT_VERSION:
        raise _invalid_session(path, "unsupported session version")
    session_id = payload.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise _invalid_session(path, "session header is missing id")
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        raise _invalid_session(path, "session header is missing timestamp")
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise _invalid_session(path, "session header is missing cwd")
    parent = payload.get("parentSession")
    if parent is not None and not isinstance(parent, str):
        raise _invalid_session(path, "session header parentSession must be a string")
    extra = payload.get("metadata")
    if extra is not None and not isinstance(extra, dict):
        raise _invalid_session(path, "session header metadata must be an object")
    return SessionMetadata(
        id=session_id,
        cwd=cwd,
        timestamp=timestamp,
        parent_session=parent,
        metadata=dict(extra or {}),
    )


def read_session_metadata(path: Path) -> SessionMetadata:
    """Read only the header. Cheap enough to run over a whole directory."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            first = handle.readline()
    except OSError as error:
        raise SessionError("not_found", f"Failed to read session header {path}") from error
    if not first.strip():
        raise _invalid_session(path, "missing session header")
    return decode_header(first, path)


class JsonlSessionStorage:
    """One session file, indexed in memory and appended to on disk."""

    def __init__(self, path: Path, metadata: SessionMetadata) -> None:
        self.path = path
        self._metadata = metadata
        self._entries: list[SessionTreeEntry] = []
        self._by_id: dict[str, SessionTreeEntry] = {}
        self._leaf_id: str | None = None
        self._write_lock = asyncio.Lock()

    @property
    def metadata(self) -> SessionMetadata:
        return self._metadata

    # -- construction ----------------------------------------------------- #

    @classmethod
    def create(cls, path: Path, metadata: SessionMetadata) -> JsonlSessionStorage:
        """Create a new session file with just its header."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise SessionError("invalid_session", f"Session already exists: {path}")
        with path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(encode_header(metadata), separators=(",", ":")) + "\n")
        return cls(path, metadata)

    @classmethod
    def open(cls, path: Path) -> JsonlSessionStorage:
        """Open an existing session file and replay it into memory."""
        if not path.is_file():
            raise SessionError("not_found", f"Session not found: {path}")
        lines = [line for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
        if not lines:
            raise _invalid_session(path, "missing session header")
        metadata = decode_header(lines[0], path)
        storage = cls(path, metadata)
        for offset, line in enumerate(lines[1:]):
            line_number = offset + 2
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise _invalid_entry(path, line_number, "is not valid JSON") from error
            try:
                entry = decode_entry(payload)
            except SessionCodecError as error:
                raise _invalid_entry(path, line_number, str(error)) from error
            if entry.id in storage._by_id:
                raise _invalid_session(path, f"duplicate entry id {entry.id}")
            storage._index(entry)
        return storage

    def _index(self, entry: SessionTreeEntry) -> None:
        self._entries.append(entry)
        self._by_id[entry.id] = entry
        self._leaf_id = entry.target_id if isinstance(entry, LeafEntry) else entry.id

    # -- SessionStorage --------------------------------------------------- #

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
        async with self._write_lock:
            if entry.id in self._by_id:
                raise SessionError("invalid_entry", f"Entry {entry.id} already exists")
            line = json.dumps(encode_entry(entry), separators=(",", ":"))
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._index(entry)

    async def get_label(self, entry_id: str) -> str | None:
        from .entries import LabelEntry

        label: str | None = None
        for entry in self._entries:
            if isinstance(entry, LabelEntry) and entry.target_id == entry_id:
                label = entry.label
        return label

    async def get_name(self) -> str | None:
        from .entries import SessionInfoEntry

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


__all__ = [
    "SESSION_FORMAT_VERSION",
    "JsonlSessionStorage",
    "decode_header",
    "encode_header",
    "read_session_metadata",
]
