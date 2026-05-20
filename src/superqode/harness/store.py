"""Persistent run/session store for the v2 harness layer."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .events import HarnessEvent
from .spec import HarnessSpec

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_run_id() -> str:
    """Return a time-sortable run id."""
    ms = int(time.time() * 1000)
    time_part = _encode_base32(ms, 10)
    rand_part = "".join(_ULID_ALPHABET[b % 32] for b in secrets.token_bytes(16))
    return f"run_{time_part}{rand_part}"


@dataclass(frozen=True)
class HarnessSessionRecord:
    """Durable metadata for a harness session."""

    session_id: str
    harness: str
    flavor: str
    created_at: float
    updated_at: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "harness": self.harness,
            "flavor": self.flavor,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HarnessSessionRecord":
        return cls(
            session_id=str(data["session_id"]),
            harness=str(data["harness"]),
            flavor=str(data["flavor"]),
            created_at=float(data["created_at"]),
            updated_at=float(data["updated_at"]),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class HarnessRunRecord:
    """Durable metadata and event log for one harness prompt run."""

    run_id: str
    session_id: str
    harness: str
    flavor: str
    provider: str
    model: str
    runtime: str
    status: str
    started_at: float
    ended_at: float | None = None
    prompt_preview: str = ""
    events: tuple[HarnessEvent, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "harness": self.harness,
            "flavor": self.flavor,
            "provider": self.provider,
            "model": self.model,
            "runtime": self.runtime,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "prompt_preview": self.prompt_preview,
            "events": [event.to_dict() for event in self.events],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HarnessRunRecord":
        return cls(
            run_id=str(data["run_id"]),
            session_id=str(data["session_id"]),
            harness=str(data["harness"]),
            flavor=str(data["flavor"]),
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            runtime=str(data.get("runtime") or ""),
            status=str(data.get("status") or "running"),
            started_at=float(data["started_at"]),
            ended_at=float(data["ended_at"]) if data.get("ended_at") is not None else None,
            prompt_preview=str(data.get("prompt_preview") or ""),
            events=tuple(_event_from_dict(item) for item in data.get("events", [])),
            metadata=dict(data.get("metadata") or {}),
        )


class FileHarnessStore:
    """File-backed harness store.

    The store writes small JSON records under ``.superqode/harness`` by default.
    It is intentionally separate from the existing agent conversation JSONL
    store while the v2 kernel is introduced.
    """

    def __init__(self, root: str | Path = ".superqode/harness") -> None:
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"
        self.runs_dir = self.root / "runs"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def open_session(
        self,
        session_id: str,
        spec: HarnessSpec,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> HarnessSessionRecord:
        """Create or update a harness session record."""
        path = self._session_path(session_id)
        now = time.time()
        existing = self.get_session(session_id)
        created_at = existing.created_at if existing else now
        merged_metadata = dict(existing.metadata if existing else {})
        merged_metadata.update(metadata or {})
        record = HarnessSessionRecord(
            session_id=session_id,
            harness=spec.name,
            flavor=spec.flavor.value,
            created_at=created_at,
            updated_at=now,
            metadata=merged_metadata,
        )
        self._write_json(path, record.to_dict())
        return record

    def get_session(self, session_id: str) -> HarnessSessionRecord | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        return HarnessSessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_sessions(self) -> list[HarnessSessionRecord]:
        records: list[HarnessSessionRecord] = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                records.append(
                    HarnessSessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
                )
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return records

    def start_run(
        self,
        *,
        session_id: str,
        spec: HarnessSpec,
        provider: str,
        model: str,
        runtime: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> HarnessRunRecord:
        run_id = generate_run_id()
        record = HarnessRunRecord(
            run_id=run_id,
            session_id=session_id,
            harness=spec.name,
            flavor=spec.flavor.value,
            provider=provider,
            model=model,
            runtime=runtime,
            status="running",
            started_at=time.time(),
            prompt_preview=_preview(prompt),
            metadata=dict(metadata or {}),
        )
        self._write_json(self._run_path(run_id), record.to_dict())
        return record

    def append_event(self, run_id: str, event: HarnessEvent) -> HarnessRunRecord:
        record = self._require_run(run_id)
        updated = HarnessRunRecord(
            **{
                **record.__dict__,
                "events": (*record.events, event),
            }
        )
        self._write_json(self._run_path(run_id), updated.to_dict())
        return updated

    def end_run(
        self,
        run_id: str,
        *,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> HarnessRunRecord:
        record = self._require_run(run_id)
        merged_metadata = dict(record.metadata)
        merged_metadata.update(metadata or {})
        updated = HarnessRunRecord(
            **{
                **record.__dict__,
                "status": status,
                "ended_at": time.time(),
                "metadata": merged_metadata,
            }
        )
        self._write_json(self._run_path(run_id), updated.to_dict())
        return updated

    def get_run(self, run_id: str) -> HarnessRunRecord | None:
        path = self._run_path(run_id)
        if not path.exists():
            return None
        return HarnessRunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_runs(self, *, session_id: str | None = None) -> list[HarnessRunRecord]:
        records: list[HarnessRunRecord] = []
        for path in self.runs_dir.glob("*.json"):
            try:
                record = HarnessRunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
            if session_id is None or record.session_id == session_id:
                records.append(record)
        records.sort(key=lambda item: item.started_at, reverse=True)
        return records

    def get_events(self, run_id: str, *, after: int = 0) -> list[HarnessEvent]:
        record = self._require_run(run_id)
        return list(record.events[after:])

    def _require_run(self, run_id: str) -> HarnessRunRecord:
        record = self.get_run(run_id)
        if record is None:
            raise KeyError(f"Unknown harness run: {run_id}")
        return record

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{_safe_id(session_id)}.json"

    def _run_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{_safe_id(run_id)}.json"

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)


class SQLiteHarnessStore:
    """SQLite-backed harness store for indexed run/session history."""

    def __init__(self, path: str | Path = ".superqode/harness/store.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def open_session(
        self,
        session_id: str,
        spec: HarnessSpec,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> HarnessSessionRecord:
        now = time.time()
        existing = self.get_session(session_id)
        created_at = existing.created_at if existing else now
        merged_metadata = dict(existing.metadata if existing else {})
        merged_metadata.update(metadata or {})
        record = HarnessSessionRecord(
            session_id=session_id,
            harness=spec.name,
            flavor=spec.flavor.value,
            created_at=created_at,
            updated_at=now,
            metadata=merged_metadata,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into sessions(session_id, harness, flavor, created_at, updated_at, metadata)
                values (?, ?, ?, ?, ?, ?)
                on conflict(session_id) do update set
                    harness=excluded.harness,
                    flavor=excluded.flavor,
                    updated_at=excluded.updated_at,
                    metadata=excluded.metadata
                """,
                (
                    record.session_id,
                    record.harness,
                    record.flavor,
                    record.created_at,
                    record.updated_at,
                    json.dumps(record.metadata, sort_keys=True),
                ),
            )
        return record

    def get_session(self, session_id: str) -> HarnessSessionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from sessions where session_id = ?",
                (session_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def list_sessions(self) -> list[HarnessSessionRecord]:
        with self._connect() as conn:
            rows = conn.execute("select * from sessions order by updated_at desc").fetchall()
        return [_session_from_row(row) for row in rows]

    def start_run(
        self,
        *,
        session_id: str,
        spec: HarnessSpec,
        provider: str,
        model: str,
        runtime: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> HarnessRunRecord:
        record = HarnessRunRecord(
            run_id=generate_run_id(),
            session_id=session_id,
            harness=spec.name,
            flavor=spec.flavor.value,
            provider=provider,
            model=model,
            runtime=runtime,
            status="running",
            started_at=time.time(),
            prompt_preview=_preview(prompt),
            metadata=dict(metadata or {}),
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into runs(
                    run_id, session_id, harness, flavor, provider, model, runtime, status,
                    started_at, ended_at, prompt_preview, metadata
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.session_id,
                    record.harness,
                    record.flavor,
                    record.provider,
                    record.model,
                    record.runtime,
                    record.status,
                    record.started_at,
                    record.ended_at,
                    record.prompt_preview,
                    json.dumps(record.metadata, sort_keys=True),
                ),
            )
        return record

    def append_event(self, run_id: str, event: HarnessEvent) -> HarnessRunRecord:
        self._require_run(run_id)
        with self._connect() as conn:
            row = conn.execute(
                "select coalesce(max(position), -1) + 1 as position from events where run_id = ?",
                (run_id,),
            ).fetchone()
            conn.execute(
                """
                insert into events(run_id, position, type, timestamp, session_id, data)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    int(row["position"]),
                    event.type,
                    event.timestamp,
                    event.session_id,
                    json.dumps(event.data, sort_keys=True),
                ),
            )
        return self._require_run(run_id)

    def end_run(
        self,
        run_id: str,
        *,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> HarnessRunRecord:
        record = self._require_run(run_id)
        merged_metadata = dict(record.metadata)
        merged_metadata.update(metadata or {})
        with self._connect() as conn:
            conn.execute(
                "update runs set status = ?, ended_at = ?, metadata = ? where run_id = ?",
                (status, time.time(), json.dumps(merged_metadata, sort_keys=True), run_id),
            )
        return self._require_run(run_id)

    def get_run(self, run_id: str) -> HarnessRunRecord | None:
        with self._connect() as conn:
            row = conn.execute("select * from runs where run_id = ?", (run_id,)).fetchone()
        return self._run_from_row(row) if row else None

    def list_runs(self, *, session_id: str | None = None) -> list[HarnessRunRecord]:
        with self._connect() as conn:
            if session_id is None:
                rows = conn.execute("select * from runs order by started_at desc").fetchall()
            else:
                rows = conn.execute(
                    "select * from runs where session_id = ? order by started_at desc",
                    (session_id,),
                ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def get_events(self, run_id: str, *, after: int = 0) -> list[HarnessEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from events where run_id = ? and position >= ? order by position",
                (run_id, after),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def _require_run(self, run_id: str) -> HarnessRunRecord:
        record = self.get_run(run_id)
        if record is None:
            raise KeyError(f"Unknown harness run: {run_id}")
        return record

    def _run_from_row(self, row: sqlite3.Row) -> HarnessRunRecord:
        return HarnessRunRecord(
            run_id=row["run_id"],
            session_id=row["session_id"],
            harness=row["harness"],
            flavor=row["flavor"],
            provider=row["provider"],
            model=row["model"],
            runtime=row["runtime"],
            status=row["status"],
            started_at=float(row["started_at"]),
            ended_at=float(row["ended_at"]) if row["ended_at"] is not None else None,
            prompt_preview=row["prompt_preview"] or "",
            events=tuple(self.get_events(row["run_id"])),
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists sessions (
                    session_id text primary key,
                    harness text not null,
                    flavor text not null,
                    created_at real not null,
                    updated_at real not null,
                    metadata text not null
                );
                create table if not exists runs (
                    run_id text primary key,
                    session_id text not null,
                    harness text not null,
                    flavor text not null,
                    provider text not null,
                    model text not null,
                    runtime text not null,
                    status text not null,
                    started_at real not null,
                    ended_at real,
                    prompt_preview text not null,
                    metadata text not null
                );
                create index if not exists idx_runs_session_started
                    on runs(session_id, started_at desc);
                create table if not exists events (
                    run_id text not null,
                    position integer not null,
                    type text not null,
                    timestamp real not null,
                    session_id text,
                    data text not null,
                    primary key(run_id, position)
                );
                create index if not exists idx_events_run_position
                    on events(run_id, position);
                """
            )


def _encode_base32(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ULID_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", ".", ":"} else "_" for ch in value)


def _preview(prompt: str, limit: int = 240) -> str:
    normalized = " ".join(prompt.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _event_from_dict(data: dict[str, Any]) -> HarnessEvent:
    return HarnessEvent(
        type=str(data["type"]),
        data=dict(data.get("data") or {}),
        timestamp=float(data.get("timestamp") or time.time()),
        session_id=data.get("session_id"),
        run_id=data.get("run_id"),
    )


def _session_from_row(row: sqlite3.Row) -> HarnessSessionRecord:
    return HarnessSessionRecord(
        session_id=row["session_id"],
        harness=row["harness"],
        flavor=row["flavor"],
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        metadata=json.loads(row["metadata"] or "{}"),
    )


def _event_from_row(row: sqlite3.Row) -> HarnessEvent:
    return HarnessEvent(
        type=row["type"],
        data=json.loads(row["data"] or "{}"),
        timestamp=float(row["timestamp"]),
        session_id=row["session_id"],
        run_id=row["run_id"],
    )
