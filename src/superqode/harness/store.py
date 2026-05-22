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


@dataclass(frozen=True)
class HarnessGraphNode:
    """One normalized node in a harness run event graph."""

    node_id: str
    run_id: str
    type: str
    label: str
    timestamp: float
    event_index: int
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "run_id": self.run_id,
            "type": self.type,
            "label": self.label,
            "timestamp": self.timestamp,
            "event_index": self.event_index,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HarnessGraphNode":
        return cls(
            node_id=str(data["node_id"]),
            run_id=str(data["run_id"]),
            type=str(data["type"]),
            label=str(data["label"]),
            timestamp=float(data["timestamp"]),
            event_index=int(data["event_index"]),
            data=dict(data.get("data") or {}),
        )


@dataclass(frozen=True)
class HarnessGraphEdge:
    """Directed relationship between two harness graph nodes."""

    source: str
    target: str
    type: str = "next"
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HarnessGraphEdge":
        return cls(
            source=str(data["source"]),
            target=str(data["target"]),
            type=str(data.get("type") or "next"),
            data=dict(data.get("data") or {}),
        )


@dataclass(frozen=True)
class HarnessEventGraph:
    """Persisted graph view of one harness run."""

    run_id: str
    nodes: tuple[HarnessGraphNode, ...] = ()
    edges: tuple[HarnessGraphEdge, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


class MemoryHarnessStore:
    """In-memory harness store for ephemeral runs."""

    def __init__(self) -> None:
        self._sessions: dict[str, HarnessSessionRecord] = {}
        self._runs: dict[str, HarnessRunRecord] = {}
        self._graphs: dict[str, HarnessEventGraph] = {}

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
        self._sessions[session_id] = record
        return record

    def get_session(self, session_id: str) -> HarnessSessionRecord | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[HarnessSessionRecord]:
        records = list(self._sessions.values())
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
        self._runs[record.run_id] = record
        self._graphs[record.run_id] = HarnessEventGraph(run_id=record.run_id)
        return record

    def append_event(self, run_id: str, event: HarnessEvent) -> HarnessRunRecord:
        record = self._require_run(run_id)
        event_index = len(record.events)
        node = _graph_node_from_event(run_id, event_index, event)
        graph = self.get_event_graph(run_id)
        edges = list(graph.edges)
        if graph.nodes:
            edges.append(
                HarnessGraphEdge(
                    source=graph.nodes[-1].node_id,
                    target=node.node_id,
                    type=_edge_type(graph.nodes[-1], node),
                )
            )
        updated = HarnessRunRecord(
            **{
                **record.__dict__,
                "events": (*record.events, event),
            }
        )
        self._runs[run_id] = updated
        self._graphs[run_id] = HarnessEventGraph(
            run_id=run_id,
            nodes=(*graph.nodes, node),
            edges=tuple(edges),
        )
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
        self._runs[run_id] = updated
        return updated

    def get_run(self, run_id: str) -> HarnessRunRecord | None:
        return self._runs.get(run_id)

    def list_runs(self, *, session_id: str | None = None) -> list[HarnessRunRecord]:
        records = [
            record
            for record in self._runs.values()
            if session_id is None or record.session_id == session_id
        ]
        records.sort(key=lambda item: item.started_at, reverse=True)
        return records

    def get_events(self, run_id: str, *, after: int = 0) -> list[HarnessEvent]:
        record = self._require_run(run_id)
        return list(record.events[after:])

    def get_event_graph(self, run_id: str) -> HarnessEventGraph:
        self._require_run(run_id)
        return self._graphs.get(run_id) or HarnessEventGraph(run_id=run_id)

    def _require_run(self, run_id: str) -> HarnessRunRecord:
        record = self.get_run(run_id)
        if record is None:
            raise KeyError(f"Unknown harness run: {run_id}")
        return record


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
        event_index = len(record.events)
        node = _graph_node_from_event(run_id, event_index, event)
        graph = self.get_event_graph(run_id)
        edges = list(graph.edges)
        if graph.nodes:
            edges.append(
                HarnessGraphEdge(
                    source=graph.nodes[-1].node_id,
                    target=node.node_id,
                    type=_edge_type(graph.nodes[-1], node),
                )
            )
        updated = HarnessRunRecord(
            **{
                **record.__dict__,
                "events": (*record.events, event),
            }
        )
        data = updated.to_dict()
        data["graph"] = HarnessEventGraph(
            run_id=run_id,
            nodes=(*graph.nodes, node),
            edges=tuple(edges),
        ).to_dict()
        self._write_json(self._run_path(run_id), data)
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

    def get_event_graph(self, run_id: str) -> HarnessEventGraph:
        record = self._require_run(run_id)
        path = self._run_path(run_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        graph_data = data.get("graph")
        if isinstance(graph_data, dict):
            return HarnessEventGraph(
                run_id=run_id,
                nodes=tuple(
                    HarnessGraphNode.from_dict(item) for item in graph_data.get("nodes", [])
                ),
                edges=tuple(
                    HarnessGraphEdge.from_dict(item) for item in graph_data.get("edges", [])
                ),
            )
        return _graph_from_events(run_id, record.events)

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
            position = int(row["position"])
            node = _graph_node_from_event(run_id, position, event)
            previous = conn.execute(
                """
                select node_id, type, label, timestamp, event_index, data
                from graph_nodes where run_id = ? order by event_index desc limit 1
                """,
                (run_id,),
            ).fetchone()
            conn.execute(
                """
                insert into events(run_id, position, type, timestamp, session_id, data)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    position,
                    event.type,
                    event.timestamp,
                    event.session_id,
                    json.dumps(event.data, sort_keys=True),
                ),
            )
            conn.execute(
                """
                insert into graph_nodes(
                    node_id, run_id, type, label, timestamp, event_index, data
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.node_id,
                    node.run_id,
                    node.type,
                    node.label,
                    node.timestamp,
                    node.event_index,
                    json.dumps(node.data, sort_keys=True),
                ),
            )
            if previous is not None:
                previous_node = _graph_node_from_row(previous, run_id=run_id)
                conn.execute(
                    """
                    insert into graph_edges(source, target, type, data)
                    values (?, ?, ?, ?)
                    """,
                    (
                        previous_node.node_id,
                        node.node_id,
                        _edge_type(previous_node, node),
                        "{}",
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

    def get_event_graph(self, run_id: str) -> HarnessEventGraph:
        self._require_run(run_id)
        with self._connect() as conn:
            node_rows = conn.execute(
                "select * from graph_nodes where run_id = ? order by event_index",
                (run_id,),
            ).fetchall()
            edge_rows = conn.execute(
                """
                select graph_edges.*
                from graph_edges
                join graph_nodes on graph_nodes.node_id = graph_edges.source
                where graph_nodes.run_id = ?
                order by graph_nodes.event_index
                """,
                (run_id,),
            ).fetchall()
        if not node_rows:
            return _graph_from_events(run_id, self.get_events(run_id))
        return HarnessEventGraph(
            run_id=run_id,
            nodes=tuple(_graph_node_from_row(row) for row in node_rows),
            edges=tuple(_graph_edge_from_row(row) for row in edge_rows),
        )

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
                create table if not exists graph_nodes (
                    node_id text primary key,
                    run_id text not null,
                    type text not null,
                    label text not null,
                    timestamp real not null,
                    event_index integer not null,
                    data text not null
                );
                create index if not exists idx_graph_nodes_run_index
                    on graph_nodes(run_id, event_index);
                create table if not exists graph_edges (
                    source text not null,
                    target text not null,
                    type text not null,
                    data text not null,
                    primary key(source, target, type)
                );
                """
            )


def create_harness_store(
    store: str | None = None,
    path: str | Path | None = None,
) -> MemoryHarnessStore | FileHarnessStore | SQLiteHarnessStore:
    """Create a harness run store from a spec/CLI setting."""
    store_name = (store or "memory").strip().lower()
    if store_name == "memory":
        return MemoryHarnessStore()
    if store_name == "file":
        return FileHarnessStore(path or ".superqode/harness")
    if store_name == "sqlite":
        sqlite_path = Path(path or ".superqode/harness/store.sqlite3")
        if sqlite_path.exists() and sqlite_path.is_dir():
            sqlite_path = sqlite_path / "store.sqlite3"
        return SQLiteHarnessStore(sqlite_path)
    raise ValueError(f"Unknown harness run store: {store!r}. Expected memory, file, or sqlite.")


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


def _graph_from_events(run_id: str, events: tuple[HarnessEvent, ...]) -> HarnessEventGraph:
    nodes = tuple(
        _graph_node_from_event(run_id, index, event) for index, event in enumerate(events)
    )
    edges = tuple(
        HarnessGraphEdge(
            source=nodes[index - 1].node_id,
            target=nodes[index].node_id,
            type=_edge_type(nodes[index - 1], nodes[index]),
        )
        for index in range(1, len(nodes))
    )
    return HarnessEventGraph(run_id=run_id, nodes=nodes, edges=edges)


def _graph_node_from_event(
    run_id: str,
    event_index: int,
    event: HarnessEvent,
) -> HarnessGraphNode:
    return HarnessGraphNode(
        node_id=f"{run_id}:n{event_index}",
        run_id=run_id,
        type=_node_type(event.type),
        label=event.type,
        timestamp=event.timestamp,
        event_index=event_index,
        data=event.to_dict(),
    )


def _node_type(event_type: str) -> str:
    if event_type in {"run_start", "run_end"}:
        return "run"
    if event_type in {"delta", "thinking"} or event_type.startswith("model_"):
        return "model"
    if event_type.startswith("tool_"):
        return "tool"
    if event_type.startswith("approval_") or event_type == "approval_required":
        return "approval"
    if event_type.startswith("sandbox_"):
        return "sandbox"
    if event_type.startswith("mcp_"):
        return "mcp"
    if event_type.startswith("subagent_"):
        return "subagent"
    if event_type.startswith("validation_"):
        return "validation"
    if event_type.startswith("typed_output"):
        return "typed_output"
    return "event"


def _edge_type(source: HarnessGraphNode, target: HarnessGraphNode) -> str:
    if source.type == "approval" and target.label == "approval_resumed":
        return "resume"
    if target.type == "approval":
        return "pause"
    if target.type in {"tool", "sandbox", "mcp", "subagent"}:
        return "calls"
    return "next"


def _graph_node_from_row(
    row: sqlite3.Row,
    *,
    run_id: str | None = None,
) -> HarnessGraphNode:
    return HarnessGraphNode(
        node_id=row["node_id"],
        run_id=run_id or row["run_id"],
        type=row["type"],
        label=row["label"],
        timestamp=float(row["timestamp"]),
        event_index=int(row["event_index"]),
        data=json.loads(row["data"] or "{}"),
    )


def _graph_edge_from_row(row: sqlite3.Row) -> HarnessGraphEdge:
    return HarnessGraphEdge(
        source=row["source"],
        target=row["target"],
        type=row["type"],
        data=json.loads(row["data"] or "{}"),
    )
