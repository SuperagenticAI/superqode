"""Host-owned immutable evidence. References grant no authority to their contents."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from superqode.governance import evaluate_active_policy
from superqode.systemone.state import redact_evidence

MAX_PAGE_CHARS = 12_000
MAX_PAGE_BYTES = 48_000


def originating_tool(metadata):
    tool = str(metadata.get("tool") or "read_context_chunk")
    return {
        "read": "read_file",
        "write": "write_file",
        "edit": "edit_file",
        "mcp_call": "mcp_execute",
    }.get(tool, tool)


def default_artifact_path() -> Path:
    return Path(
        os.environ.get("SUPERQODE_CONTEXT_STORE")
        or Path.home() / ".superqode" / "context" / "artifacts.sqlite3"
    ).expanduser()


@dataclass(frozen=True)
class ContextArtifact:
    reference: str
    scope: str
    entry_id: str
    digest: str
    chars: int
    bytes: int
    created_at: float
    expires_at: float | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ContextPage:
    reference: str
    text: str
    offset: int
    next_offset: int
    total_chars: int
    digest: str
    eof: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def authorize_artifact(metadata: dict[str, Any], text: str | None = None) -> bool:
    """Recheck the originating call and result under current host policy."""
    tool = originating_tool(metadata)
    args = metadata.get("arguments") or {}
    if not isinstance(args, dict):
        return False
    from superqode.tools.permissions import TOOL_GROUPS

    group = TOOL_GROUPS.get(tool)
    group_name = group.value if group else "read"
    for name, arguments in ((tool, args), ("read_context_chunk", {"source_tool": tool})):
        if (
            evaluate_active_policy(
                "tool_call",
                tool=name,
                tool_group=group_name if name == tool else "read",
                arguments=arguments,
            ).action
            != "allow"
        ):
            return False
    if text is not None:
        for name in (tool, "read_context_chunk"):
            if (
                evaluate_active_policy(
                    "tool_result",
                    tool=name,
                    tool_group=group_name if name == tool else "read",
                    arguments={
                        "output": text,
                        "output_length": len(text),
                        "success": metadata.get("success", True),
                    },
                ).action
                != "allow"
            ):
                return False
    return True


class ContextArtifactStore:
    """Atomic SQLite records, owner quotas, integrity checks and bounded pages.

    Callers supply their trusted session/WorkOrder scope, never a model-provided
    scope. Content and metadata are sanitized before they reach disk.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        max_artifact_bytes: int = 2_000_000,
        max_scope_bytes: int = 20_000_000,
        authorize: Callable[[dict[str, Any], str | None], bool] = authorize_artifact,
    ):
        self.path = Path(path) if path is not None else default_artifact_path()
        self.max_artifact_bytes = max_artifact_bytes
        self.max_scope_bytes = max_scope_bytes
        self.authorize = authorize
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError("Artifact database must not be a symlink")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS context_artifacts (
                reference TEXT PRIMARY KEY, scope TEXT NOT NULL, entry_id TEXT NOT NULL,
                digest TEXT NOT NULL, chars INTEGER NOT NULL, bytes INTEGER NOT NULL,
                created_at REAL NOT NULL, expires_at REAL, metadata TEXT NOT NULL,
                content TEXT NOT NULL, UNIQUE(scope, entry_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS context_aliases (
                scope TEXT NOT NULL, alias TEXT NOT NULL, reference TEXT NOT NULL,
                PRIMARY KEY(scope,alias))""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(
        self,
        scope: str,
        entry_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
        expires_at: float | None = None,
    ) -> ContextArtifact:
        if not scope or not entry_id or not isinstance(text, str):
            raise ValueError("Scope, entry identity and text are required")
        text = redact_evidence(text)
        meta = redact_evidence(metadata or {})
        if not self.authorize(meta, text):
            raise PermissionError("Evidence persistence denied by current policy")
        blob = text.encode("utf-8")
        if len(blob) > self.max_artifact_bytes:
            raise ValueError("Evidence exceeds artifact quota")
        if expires_at is not None and (
            not isinstance(expires_at, (int, float)) or not time.time() < expires_at < float("inf")
        ):
            raise ValueError("Expiry must be a future finite timestamp")
        digest = hashlib.sha256(blob).hexdigest()
        encoded_meta = json.dumps(meta, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if len(encoded_meta.encode()) > 512_000:
            raise ValueError("Evidence metadata exceeds limit")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM context_artifacts WHERE scope=? AND entry_id=?", (scope, entry_id)
            ).fetchone()
            if row:
                if row[3] != digest or row[8] != encoded_meta:
                    raise ValueError(
                        "Evidence entry identity already has different content or provenance"
                    )
                if row[7] is not None and row[7] <= time.time():
                    raise ValueError("Evidence entry has expired")
                return self._record(row)
            total = db.execute(
                "SELECT COALESCE(SUM(bytes+length(CAST(metadata AS BLOB))),0) FROM context_artifacts WHERE scope=?",
                (scope,),
            ).fetchone()[0]
            if total + len(blob) + len(encoded_meta.encode()) > self.max_scope_bytes:
                raise ValueError("Evidence exceeds owner quota")
            record = ContextArtifact(
                "ctx_" + uuid4().hex,
                scope,
                entry_id,
                digest,
                len(text),
                len(blob),
                time.time(),
                expires_at,
                meta,
            )
            db.execute(
                "INSERT INTO context_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    record.reference,
                    scope,
                    entry_id,
                    digest,
                    len(text),
                    len(blob),
                    record.created_at,
                    expires_at,
                    encoded_meta,
                    text,
                ),
            )
        return record

    def bind_alias(self, scope: str, alias: str, reference: str) -> None:
        self.describe(scope, reference)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT reference FROM context_aliases WHERE scope=? AND alias=?", (scope, alias)
            ).fetchone()
            if row and row[0] != reference:
                raise ValueError("Context alias already identifies different evidence")
            db.execute(
                "INSERT OR IGNORE INTO context_aliases VALUES (?,?,?)", (scope, alias, reference)
            )

    def resolve_alias(self, scope: str, alias: str) -> str:
        with self._connect() as db:
            row = db.execute(
                "SELECT reference FROM context_aliases WHERE scope=? AND alias=?", (scope, alias)
            ).fetchone()
        if not row:
            raise LookupError("Context alias unavailable")
        return row[0]

    @staticmethod
    def _record(row) -> ContextArtifact:
        return ContextArtifact(*row[:8], json.loads(row[8]))

    def _load(self, scope: str, reference: str):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM context_artifacts WHERE scope=? AND reference=?", (scope, reference)
            ).fetchone()
        if not row or (row[7] is not None and row[7] <= time.time()):
            raise LookupError("Evidence is unavailable")
        record = self._record(row)
        if not self.authorize(record.metadata, None):
            raise PermissionError("Evidence access denied by current policy")
        if hashlib.sha256(row[9].encode()).hexdigest() != record.digest:
            raise ValueError("Evidence integrity check failed")
        text = redact_evidence(row[9])
        if text != row[9]:
            # Changing sanitizers cannot change paging offsets for the same reference.
            raise PermissionError("Evidence requires re-sanitization")
        if not self.authorize(record.metadata, text):
            raise PermissionError("Evidence result denied by current policy")
        return record, text

    def describe(self, scope: str, reference: str) -> ContextArtifact:
        return self._load(scope, reference)[0]

    def read_page(
        self, scope: str, reference: str, *, offset: int = 0, limit: int = 4000
    ) -> ContextPage:
        for name, value in (("offset", offset), ("limit", limit)):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < (0 if name == "offset" else 1)
            ):
                raise ValueError(f"{name} must be a valid integer")
        record, text = self._load(scope, reference)
        if offset > record.chars:
            raise ValueError("Offset exceeds evidence length")
        shown = text[offset : offset + min(limit, MAX_PAGE_CHARS)]
        shown = shown.encode()[:MAX_PAGE_BYTES].decode("utf-8", errors="ignore")
        end = offset + len(shown)
        return ContextPage(
            reference, shown, offset, end, len(text), record.digest, end == len(text)
        )

    def delete(self, scope: str, reference: str) -> bool:
        self._load(scope, reference)
        with self._connect() as db:
            return bool(
                db.execute(
                    "DELETE FROM context_artifacts WHERE scope=? AND reference=?",
                    (scope, reference),
                ).rowcount
            )

    def expire(self, *, now: float | None = None) -> int:
        with self._connect() as db:
            return db.execute(
                "DELETE FROM context_artifacts WHERE expires_at IS NOT NULL AND expires_at<=?",
                (time.time() if now is None else now,),
            ).rowcount
