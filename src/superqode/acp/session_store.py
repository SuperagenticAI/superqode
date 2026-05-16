"""Persistent ACP session store (A3 from the fast-agent gap audit).

Why this exists
---------------
Without persistence, every ``superqode acp <agent>`` starts cold. The user
loses their prior conversation, and any agent that supports the ACP
``session/load`` capability (Claude Code, OpenCode, OpenHands) wastes that
capability because we can't ask "resume the last one".

This module owns a tiny SQLite table at ``~/.superqode/sessions.db`` that
records every successfully-created ACP session. The ACP client reads it
on startup to offer ``--resume`` or ``--session-id`` flows, and the CLI
exposes ``superqode acp list`` to enumerate prior sessions.

Schema rationale
----------------
- ``agent_identity`` (e.g. ``opencode.ai``) scopes the index by agent so
  switching agents doesn't show irrelevant sessions.
- ``session_id`` is the opaque string the agent returned from
  ``session/new``. The same id is sent back in ``session/load``.
- ``cwd`` is the project root the session was created in. We surface it
  to the user when listing and refuse a resume if the on-disk cwd has
  moved (mirrors fast-agent's behavior; see ``session_store.py:386`` in
  the reference).
- ``metadata_json`` is a free-form bag for agent-specific extras
  (model name, mode at last use, any future fields). Stored as TEXT so
  we don't have to migrate schema for every new key.
- ``created_at`` / ``last_used_at`` are epoch seconds (REAL) so SQLite
  ``ORDER BY`` works without parsing.

Concurrency
-----------
SQLite handles intra-process locking, and the file lives in a single
home directory — we don't try to coordinate across machines. The store
opens a fresh connection per operation (cheap) so it's safe to share
the store across asyncio tasks without holding a long-lived conn.

Soft-fail policy
----------------
A broken sessions DB must never break a live session. All write paths
catch exceptions and surface via the optional ``on_warn`` callback;
read paths return empty results on error.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional


def default_sessions_db_path() -> Path:
    """Resolve the default sessions DB path.

    Honors ``SUPERQODE_HOME`` so tests and per-project setups can
    redirect without touching the global file.
    """
    home = os.environ.get("SUPERQODE_HOME")
    if home:
        return Path(home).expanduser() / "sessions.db"
    return Path.home() / ".superqode" / "sessions.db"


@dataclass
class StoredSession:
    """A row from the sessions table.

    The dataclass exists so callers can ``.cwd`` and ``.last_used_at``
    instead of ``row[4]`` — much better at a callsite three modules away.
    """

    id: int
    agent_identity: str
    session_id: str
    name: str
    cwd: str
    created_at: float
    last_used_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: tuple) -> "StoredSession":
        meta_json = row[7] or "{}"
        try:
            metadata = json.loads(meta_json) if meta_json else {}
        except json.JSONDecodeError:
            # Corrupted metadata shouldn't blow up listing. Surface an
            # empty dict and let the row keep being useful.
            metadata = {}
        return cls(
            id=row[0],
            agent_identity=row[1],
            session_id=row[2],
            name=row[3],
            cwd=row[4],
            created_at=row[5],
            last_used_at=row[6],
            metadata=metadata,
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_identity  TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    cwd             TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL,
    last_used_at    REAL NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    UNIQUE(agent_identity, session_id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_last_used
    ON sessions(agent_identity, last_used_at DESC);
"""


class ACPSessionStore:
    """SQLite-backed store of ACP session metadata.

    Most operations are simple wrappers around tiny SQL statements;
    they're async-shaped because every callsite is async and we don't
    want to block the event loop on disk I/O. Each call opens a fresh
    connection via ``asyncio.to_thread`` so we can stay lock-free in
    Python while SQLite handles file-level locking.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        on_warn: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        self._path: Path = path or default_sessions_db_path()
        self._on_warn = on_warn
        self._initialized = False
        self._init_lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    async def _warn(self, msg: str) -> None:
        if self._on_warn is not None:
            try:
                await self._on_warn(msg)
            except Exception:
                pass

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(self._init_sync)
                self._initialized = True
            except Exception as e:
                await self._warn(
                    f"[session_store] failed to initialize {self._path}: {e}"
                )

    def _init_sync(self) -> None:
        conn = sqlite3.connect(self._path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def record(
        self,
        agent_identity: str,
        session_id: str,
        cwd: str,
        *,
        name: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[StoredSession]:
        """Insert or update (upsert) a session record. Returns the row.

        The unique constraint on ``(agent_identity, session_id)`` means
        re-recording the same session — say, after a resume — just bumps
        ``last_used_at`` without creating a duplicate row.
        """
        await self._ensure_initialized()
        now = time.time()
        meta_json = json.dumps(metadata or {})

        try:
            await asyncio.to_thread(
                self._upsert_sync,
                agent_identity,
                session_id,
                name,
                cwd,
                now,
                meta_json,
            )
        except Exception as e:
            await self._warn(f"[session_store] failed to record session: {e}")
            return None
        return await self.get(agent_identity, session_id)

    def _upsert_sync(
        self,
        agent_identity: str,
        session_id: str,
        name: str,
        cwd: str,
        now: float,
        meta_json: str,
    ) -> None:
        conn = sqlite3.connect(self._path)
        try:
            # SQLite ``ON CONFLICT`` upsert: existing rows keep their
            # ``created_at`` and ``name`` if the caller didn't supply
            # new values, but always bump ``last_used_at`` and merge
            # cwd/metadata if present.
            conn.execute(
                """
                INSERT INTO sessions
                    (agent_identity, session_id, name, cwd,
                     created_at, last_used_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_identity, session_id) DO UPDATE SET
                    last_used_at = excluded.last_used_at,
                    cwd = CASE
                        WHEN length(excluded.cwd) > 0 THEN excluded.cwd
                        ELSE sessions.cwd
                    END,
                    name = CASE
                        WHEN length(excluded.name) > 0 THEN excluded.name
                        ELSE sessions.name
                    END,
                    metadata_json = excluded.metadata_json
                """,
                (
                    agent_identity,
                    session_id,
                    name,
                    cwd,
                    now,
                    now,
                    meta_json,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    async def touch(self, agent_identity: str, session_id: str) -> None:
        """Bump ``last_used_at`` without touching anything else.

        Called after every successful prompt turn so the "most recent
        session" listing reflects actual user activity, not just the
        session creation time.
        """
        await self._ensure_initialized()
        try:
            await asyncio.to_thread(
                self._touch_sync, agent_identity, session_id, time.time()
            )
        except Exception as e:
            await self._warn(f"[session_store] failed to touch session: {e}")

    def _touch_sync(
        self, agent_identity: str, session_id: str, now: float
    ) -> None:
        conn = sqlite3.connect(self._path)
        try:
            conn.execute(
                "UPDATE sessions SET last_used_at = ? "
                "WHERE agent_identity = ? AND session_id = ?",
                (now, agent_identity, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    async def update_name(
        self, agent_identity: str, session_id: str, name: str
    ) -> None:
        """Rename a session — useful for the CLI ``acp rename`` flow."""
        await self._ensure_initialized()
        try:
            await asyncio.to_thread(
                self._update_name_sync, agent_identity, session_id, name
            )
        except Exception as e:
            await self._warn(f"[session_store] failed to rename: {e}")

    def _update_name_sync(
        self, agent_identity: str, session_id: str, name: str
    ) -> None:
        conn = sqlite3.connect(self._path)
        try:
            conn.execute(
                "UPDATE sessions SET name = ? "
                "WHERE agent_identity = ? AND session_id = ?",
                (name, agent_identity, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    async def delete(self, agent_identity: str, session_id: str) -> bool:
        """Remove a single session row. Returns True if a row was removed."""
        await self._ensure_initialized()
        try:
            removed = await asyncio.to_thread(
                self._delete_sync, agent_identity, session_id
            )
            return bool(removed)
        except Exception as e:
            await self._warn(f"[session_store] failed to delete: {e}")
            return False

    def _delete_sync(self, agent_identity: str, session_id: str) -> int:
        conn = sqlite3.connect(self._path)
        try:
            cur = conn.execute(
                "DELETE FROM sessions "
                "WHERE agent_identity = ? AND session_id = ?",
                (agent_identity, session_id),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    async def clear_all(self) -> None:
        """Wipe every row. Mostly exists for tests + a future ``acp clear``."""
        await self._ensure_initialized()
        try:
            await asyncio.to_thread(self._clear_sync)
        except Exception as e:
            await self._warn(f"[session_store] failed to clear: {e}")

    def _clear_sync(self) -> None:
        conn = sqlite3.connect(self._path)
        try:
            conn.execute("DELETE FROM sessions")
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get(
        self, agent_identity: str, session_id: str
    ) -> Optional[StoredSession]:
        """Fetch a single row by ``(agent_identity, session_id)``."""
        await self._ensure_initialized()
        try:
            row = await asyncio.to_thread(
                self._get_sync, agent_identity, session_id
            )
        except Exception as e:
            await self._warn(f"[session_store] read failed: {e}")
            return None
        return StoredSession.from_row(row) if row else None

    def _get_sync(
        self, agent_identity: str, session_id: str
    ) -> Optional[tuple]:
        conn = sqlite3.connect(self._path)
        try:
            cur = conn.execute(
                "SELECT id, agent_identity, session_id, name, cwd, "
                "created_at, last_used_at, metadata_json FROM sessions "
                "WHERE agent_identity = ? AND session_id = ? LIMIT 1",
                (agent_identity, session_id),
            )
            return cur.fetchone()
        finally:
            conn.close()

    async def list_for_agent(
        self,
        agent_identity: str,
        *,
        cwd: Optional[str] = None,
        limit: int = 50,
    ) -> List[StoredSession]:
        """List sessions for one agent, newest first.

        ``cwd`` filter is optional — without it, we return every session
        for the agent across all working directories. The CLI uses
        ``cwd=str(Path.cwd())`` so "sessions in this project" is the
        natural default.
        """
        await self._ensure_initialized()
        try:
            rows = await asyncio.to_thread(
                self._list_sync, agent_identity, cwd, limit
            )
        except Exception as e:
            await self._warn(f"[session_store] list failed: {e}")
            return []
        return [StoredSession.from_row(r) for r in rows]

    def _list_sync(
        self,
        agent_identity: str,
        cwd: Optional[str],
        limit: int,
    ) -> List[tuple]:
        conn = sqlite3.connect(self._path)
        try:
            if cwd is not None:
                cur = conn.execute(
                    "SELECT id, agent_identity, session_id, name, cwd, "
                    "created_at, last_used_at, metadata_json FROM sessions "
                    "WHERE agent_identity = ? AND cwd = ? "
                    "ORDER BY last_used_at DESC LIMIT ?",
                    (agent_identity, cwd, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT id, agent_identity, session_id, name, cwd, "
                    "created_at, last_used_at, metadata_json FROM sessions "
                    "WHERE agent_identity = ? "
                    "ORDER BY last_used_at DESC LIMIT ?",
                    (agent_identity, limit),
                )
            return cur.fetchall()
        finally:
            conn.close()

    async def list_all(self, *, limit: int = 100) -> List[StoredSession]:
        """Every session across every agent, newest first."""
        await self._ensure_initialized()
        try:
            rows = await asyncio.to_thread(self._list_all_sync, limit)
        except Exception as e:
            await self._warn(f"[session_store] list_all failed: {e}")
            return []
        return [StoredSession.from_row(r) for r in rows]

    def _list_all_sync(self, limit: int) -> List[tuple]:
        conn = sqlite3.connect(self._path)
        try:
            cur = conn.execute(
                "SELECT id, agent_identity, session_id, name, cwd, "
                "created_at, last_used_at, metadata_json FROM sessions "
                "ORDER BY last_used_at DESC LIMIT ?",
                (limit,),
            )
            return cur.fetchall()
        finally:
            conn.close()

    async def most_recent_for_agent(
        self, agent_identity: str, *, cwd: Optional[str] = None
    ) -> Optional[StoredSession]:
        """Convenience for the common "resume the latest" flow."""
        rows = await self.list_for_agent(agent_identity, cwd=cwd, limit=1)
        return rows[0] if rows else None
