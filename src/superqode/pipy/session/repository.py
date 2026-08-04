"""Finding, creating and forking sessions on disk.

Ported from ``packages/agent/src/harness/session/`` of earendil-works/pi (MIT).

Sessions live under one directory per working directory, so listing the
sessions for a repository is a single directory read rather than a scan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from ..config import pi_agent_dir, session_dir_for, sessions_root
from .codec import encode_entry
from .entries import SessionMetadata, SessionTreeEntry, current_timestamp
from .jsonl import JsonlSessionStorage, encode_header, read_session_metadata
from .session import CustomEntryProjector, Session, create_session
from .storage import SessionError


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """A session file on disk, identified without loading its entries."""

    path: Path
    metadata: SessionMetadata

    @property
    def id(self) -> str:
        return self.metadata.id

    @property
    def created_at(self) -> str:
        return self.metadata.timestamp


def _file_name(session_id: str, timestamp: str) -> str:
    """``2026-08-03T09-14-22-013Z_<id>.jsonl``, the same shape pi writes."""
    stamp = timestamp.replace(":", "-").replace(".", "-")
    return f"{stamp}_{quote(session_id, safe='')}.jsonl"


def _iso_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    )


class SessionRepository:
    """Sessions for one root directory, grouped by working directory."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        projectors: dict[str, CustomEntryProjector] | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else sessions_root()
        self._projectors = dict(projectors or {})

    # -- create and open -------------------------------------------------- #

    async def create(
        self,
        cwd: str | Path,
        *,
        session_id: str | None = None,
        parent_session: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Session, Path]:
        """Create a new session file for a working directory."""
        resolved = str(Path(cwd).expanduser().resolve())
        identifier = session_id or uuid4().hex[:12]
        if not identifier:
            raise SessionError("invalid_session", "Session id cannot be empty")
        timestamp = _iso_timestamp()
        directory = session_dir_for(resolved, self.root)
        path = directory / _file_name(identifier, timestamp)
        storage = JsonlSessionStorage.create(
            path,
            SessionMetadata(
                id=identifier,
                cwd=resolved,
                timestamp=timestamp,
                parent_session=parent_session,
                metadata=dict(metadata or {}),
            ),
        )
        return await create_session(storage, projectors=self._projectors), path

    async def open(self, path: str | Path) -> Session:
        """Open a session file, resuming at its current leaf."""
        storage = JsonlSessionStorage.open(Path(path))
        return await create_session(storage, projectors=self._projectors)

    # -- discovery -------------------------------------------------------- #

    def list(self, cwd: str | Path | None = None) -> list[SessionRecord]:
        """List sessions, newest first. Unreadable files are skipped.

        A single corrupt session must not make the picker unusable, which is
        why a bad header is skipped here rather than raised. Opening that same
        file still reports the precise error.
        """
        directories: list[Path]
        if cwd is not None:
            directories = [session_dir_for(Path(cwd).expanduser().resolve(), self.root)]
        elif self.root.is_dir():
            directories = sorted(item for item in self.root.iterdir() if item.is_dir())
        else:
            directories = []

        records: list[SessionRecord] = []
        for directory in directories:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.jsonl")):
                try:
                    records.append(SessionRecord(path=path, metadata=read_session_metadata(path)))
                except SessionError:
                    continue
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records

    def latest(self, cwd: str | Path) -> SessionRecord | None:
        records = self.list(cwd)
        return records[0] if records else None

    async def resume_latest(self, cwd: str | Path) -> Session | None:
        record = self.latest(cwd)
        return await self.open(record.path) if record is not None else None

    # -- forking ---------------------------------------------------------- #

    async def fork(
        self,
        source: str | Path,
        *,
        up_to_entry_id: str | None = None,
        session_id: str | None = None,
    ) -> tuple[Session, Path]:
        """Copy a session's branch into a new file.

        The new session records the source path in its header, so the lineage
        of an experiment stays visible. The source file is never modified.
        """
        source_path = Path(source)
        storage = JsonlSessionStorage.open(source_path)
        leaf = await storage.read_head() if up_to_entry_id is None else up_to_entry_id
        if up_to_entry_id is not None and await storage.read_entry(up_to_entry_id) is None:
            raise SessionError("not_found", f"Entry {up_to_entry_id} not found")
        branch = await storage.read_path_to_root(leaf)

        session, path = await self.create(
            storage.metadata.cwd,
            session_id=session_id,
            parent_session=str(source_path),
            metadata=dict(storage.metadata.metadata),
        )
        target = JsonlSessionStorage.open(path)
        for entry in branch:
            await target.append_entry(entry)
        return await create_session(target, projectors=self._projectors), path


def import_pi_sessions(cwd: str | Path) -> list[SessionRecord]:
    """List a real pi install's sessions for a working directory, read only.

    The formats are identical, so these can be opened with
    :meth:`SessionRepository.open`. PiPy never writes into pi's directory; fork
    a session first if you want to continue one.
    """
    root = pi_agent_dir() / "sessions"
    if not root.is_dir():
        return []
    return SessionRepository(root).list(cwd)


def write_session_file(
    path: Path,
    metadata: SessionMetadata,
    entries: list[SessionTreeEntry],
) -> None:
    """Write a complete session file in one pass. Used by tests and exports."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(encode_header(metadata), separators=(",", ":"))]
    lines.extend(json.dumps(encode_entry(entry), separators=(",", ":")) for entry in entries)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = [
    "SessionRecord",
    "SessionRepository",
    "current_timestamp",
    "import_pi_sessions",
    "write_session_file",
]
