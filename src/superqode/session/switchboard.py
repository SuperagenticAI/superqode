"""Durable session graph and cross-agent handoff helpers.

The switchboard is intentionally local-first: it records a graph sidecar next
to the JSONL session store so the TUI, CLI, share artifacts, and local API all
see the same sessions without requiring a server runtime.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from superqode.agent.session_manager import SessionManager, SessionMessage, SessionMetadata

GRAPH_FORMAT = "superqode-session-graph-v1"
HANDOFF_FORMAT = "superqode-handoff-v1"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._:-" else "-" for ch in value)


def graph_path_for_storage(storage_dir: str | Path = ".superqode/sessions") -> Path:
    """Return the sidecar graph path for a JSONL session store."""
    base = Path(storage_dir)
    if base.name == "sessions":
        return base.parent / "session_graph.json"
    return base / "session_graph.json"


@dataclass
class SessionGraphRecord:
    """One node in the local session graph."""

    session_id: str
    kind: str = "default"
    parent_session_id: str | None = None
    root_session_id: str | None = None
    agent_id: str = ""
    agent_name: str = ""
    title: str = ""
    status: str = "idle"
    closed: bool = False
    provider: str = ""
    model: str = ""
    backend: str = ""
    workspace: str = ""
    git_branch: str = ""
    external_session_id: str = ""
    last_result_preview: str = ""
    pending_approvals_count: int = 0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "kind": self.kind,
            "parent_session_id": self.parent_session_id,
            "root_session_id": self.root_session_id or self.session_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "title": self.title,
            "status": self.status,
            "closed": self.closed,
            "provider": self.provider,
            "model": self.model,
            "backend": self.backend,
            "workspace": self.workspace,
            "git_branch": self.git_branch,
            "external_session_id": self.external_session_id,
            "last_result_preview": self.last_result_preview,
            "pending_approvals_count": self.pending_approvals_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionGraphRecord":
        return cls(
            session_id=str(data["session_id"]),
            kind=str(data.get("kind") or "default"),
            parent_session_id=data.get("parent_session_id"),
            root_session_id=data.get("root_session_id"),
            agent_id=str(data.get("agent_id") or ""),
            agent_name=str(data.get("agent_name") or ""),
            title=str(data.get("title") or ""),
            status=str(data.get("status") or "idle"),
            closed=bool(data.get("closed", False)),
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            backend=str(data.get("backend") or ""),
            workspace=str(data.get("workspace") or ""),
            git_branch=str(data.get("git_branch") or ""),
            external_session_id=str(data.get("external_session_id") or ""),
            last_result_preview=str(data.get("last_result_preview") or ""),
            pending_approvals_count=int(data.get("pending_approvals_count") or 0),
            created_at=str(data.get("created_at") or _now()),
            updated_at=str(data.get("updated_at") or _now()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class HandoffPacket:
    """Structured context sent from one session to another."""

    id: str
    source_session_id: str
    target_session_id: str = ""
    target_agent: str = ""
    goal: str = ""
    reason: str = ""
    transcript_tail: list[dict[str, Any]] = field(default_factory=list)
    graph_context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": HANDOFF_FORMAT,
            "id": self.id,
            "source_session_id": self.source_session_id,
            "target_session_id": self.target_session_id,
            "target_agent": self.target_agent,
            "goal": self.goal,
            "reason": self.reason,
            "transcript_tail": list(self.transcript_tail),
            "graph_context": dict(self.graph_context),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    def to_message(self) -> str:
        body = [
            f"SuperQode handoff packet {self.id}",
            f"Source session: {self.source_session_id}",
        ]
        if self.target_agent:
            body.append(f"Target agent: {self.target_agent}")
        if self.goal:
            body.extend(["", "Goal:", self.goal])
        if self.reason:
            body.extend(["", "Reason:", self.reason])
        if self.transcript_tail:
            body.append("")
            body.append("Recent transcript:")
            for item in self.transcript_tail:
                role = str(item.get("role") or "?")
                content = " ".join(str(item.get("content") or "").split())
                if len(content) > 800:
                    content = content[:797] + "..."
                body.append(f"- {role}: {content}")
        return "\n".join(body).strip() + "\n"


class SessionGraphStore:
    """JSON-backed graph store for local sessions."""

    def __init__(
        self,
        storage_dir: str | Path = ".superqode/sessions",
        graph_path: str | Path | None = None,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.graph_path = (
            Path(graph_path) if graph_path else graph_path_for_storage(self.storage_dir)
        )
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.graph_path.exists():
            return {"format": GRAPH_FORMAT, "active_session_id": "", "sessions": {}}
        try:
            data = json.loads(self.graph_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"format": GRAPH_FORMAT, "active_session_id": "", "sessions": {}}
        if not isinstance(data, dict):
            return {"format": GRAPH_FORMAT, "active_session_id": "", "sessions": {}}
        data.setdefault("format", GRAPH_FORMAT)
        data.setdefault("active_session_id", "")
        data.setdefault("sessions", {})
        return data

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.graph_path.with_suffix(self.graph_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.graph_path)

    def _records_map(self, data: dict[str, Any]) -> dict[str, SessionGraphRecord]:
        raw = data.get("sessions") or {}
        records: dict[str, SessionGraphRecord] = {}
        if isinstance(raw, dict):
            for session_id, item in raw.items():
                if isinstance(item, dict):
                    try:
                        records[str(session_id)] = SessionGraphRecord.from_dict(item)
                    except (KeyError, TypeError, ValueError):
                        continue
        return records

    def upsert(
        self,
        session_id: str,
        *,
        metadata: SessionMetadata | None = None,
        **updates: Any,
    ) -> SessionGraphRecord:
        data = self._load()
        records = self._records_map(data)
        existing = records.get(session_id)
        now = _now()
        if existing is None:
            existing = SessionGraphRecord(
                session_id=session_id,
                created_at=getattr(metadata, "created_at", now) if metadata else now,
            )
        if metadata is not None:
            existing.provider = metadata.provider or existing.provider
            existing.model = metadata.model or existing.model
            existing.title = metadata.title or existing.title
            existing.parent_session_id = metadata.parent_session_id or existing.parent_session_id
            existing.updated_at = metadata.updated_at or existing.updated_at
        record_metadata = updates.pop("record_metadata", None)
        if isinstance(record_metadata, dict):
            existing.metadata.update(record_metadata)
        has_updates = bool(updates) or record_metadata is not None
        for key, value in updates.items():
            if value is not None and hasattr(existing, key):
                setattr(existing, key, value)
        existing.root_session_id = existing.root_session_id or self._resolve_root(
            records,
            existing.parent_session_id,
            session_id,
        )
        existing.updated_at = str(
            updates.get("updated_at") or (now if has_updates else existing.updated_at) or now
        )
        records[session_id] = existing
        data["sessions"] = {sid: rec.to_dict() for sid, rec in records.items()}
        self._save(data)
        return existing

    def ingest_metadata(self, metadata: SessionMetadata) -> SessionGraphRecord:
        return self.upsert(metadata.session_id, metadata=metadata)

    def sync_from_session_store(self) -> list[SessionGraphRecord]:
        manager = SessionManager(storage_dir=str(self.storage_dir))
        records = [self.ingest_metadata(item) for item in manager.list_all_sessions()]
        return records

    def get(self, session_id: str) -> SessionGraphRecord | None:
        return self._records_map(self._load()).get(session_id)

    def list(self, *, include_closed: bool = True) -> list[SessionGraphRecord]:
        self.sync_from_session_store()
        records = list(self._records_map(self._load()).values())
        if not include_closed:
            records = [item for item in records if not item.closed]
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return records

    def children(
        self, parent_session_id: str, *, include_closed: bool = True
    ) -> list[SessionGraphRecord]:
        return [
            item
            for item in self.list(include_closed=include_closed)
            if item.parent_session_id == parent_session_id
        ]

    def tree(self, *, include_closed: bool = True) -> list[dict[str, Any]]:
        records = self.list(include_closed=include_closed)
        by_parent: dict[str | None, list[SessionGraphRecord]] = {}
        ids = {item.session_id for item in records}
        for item in records:
            parent = item.parent_session_id if item.parent_session_id in ids else None
            by_parent.setdefault(parent, []).append(item)

        def node(record: SessionGraphRecord) -> dict[str, Any]:
            payload = record.to_dict()
            payload["children"] = [node(child) for child in by_parent.get(record.session_id, [])]
            return payload

        return [node(item) for item in by_parent.get(None, [])]

    def find_named_child(
        self,
        parent_session_id: str,
        agent_id: str,
        title: str,
    ) -> SessionGraphRecord | None:
        normalized_title = title.strip()
        for item in self.children(parent_session_id, include_closed=False):
            if item.agent_id == agent_id and item.title == normalized_title:
                return item
        return None

    def set_active(self, session_id: str) -> SessionGraphRecord:
        record = self.get(session_id)
        if record is None:
            metadata = SessionManager(storage_dir=str(self.storage_dir)).get_session_info(
                session_id
            )
            if metadata is None:
                raise KeyError(f"Session not found: {session_id}")
            record = self.ingest_metadata(metadata)
        data = self._load()
        data["active_session_id"] = session_id
        self._save(data)
        return record

    def get_active(self) -> str:
        return str(self._load().get("active_session_id") or "")

    def close(self, session_id: str) -> SessionGraphRecord:
        return self.upsert(session_id, status="closed", closed=True)

    def _resolve_root(
        self,
        records: dict[str, SessionGraphRecord],
        parent_session_id: str | None,
        fallback: str,
    ) -> str:
        if not parent_session_id:
            return fallback
        parent = records.get(parent_session_id)
        if parent is None:
            return parent_session_id
        return parent.root_session_id or parent.session_id


class SessionSwitchboard:
    """High-level operations used by CLI, TUI, tools, and local API."""

    def __init__(self, storage_dir: str | Path = ".superqode/sessions") -> None:
        self.storage_dir = Path(storage_dir)
        self.graph = SessionGraphStore(self.storage_dir)
        self.manager = SessionManager(storage_dir=str(self.storage_dir))

    def list_sessions(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self.graph.list()]

    def graph_tree(self) -> list[dict[str, Any]]:
        return self.graph.tree()

    def switch(self, session_id: str) -> dict[str, Any]:
        resolved = self.resolve_session_id(session_id)
        return self.graph.set_active(resolved).to_dict()

    def active(self) -> str:
        return self.graph.get_active()

    def info(self, session_id: str) -> dict[str, Any]:
        resolved = self.resolve_session_id(session_id)
        record = self.graph.get(resolved)
        metadata = self.manager.get_session_info(resolved)
        if record is None and metadata is None:
            raise KeyError(f"Session not found: {session_id}")
        if record is None and metadata is not None:
            record = self.graph.ingest_metadata(metadata)
        payload = record.to_dict() if record else {}
        if metadata is not None:
            payload["message_count"] = metadata.message_count
            payload["total_tokens"] = metadata.total_tokens
        payload["children"] = [child.to_dict() for child in self.graph.children(resolved)]
        return payload

    def history(self, session_id: str, *, limit: int = 20) -> dict[str, Any]:
        resolved = self.resolve_session_id(session_id)
        metadata = self.manager.get_session_info(resolved)
        if metadata is None:
            raise KeyError(f"Session not found: {session_id}")
        messages = self.manager.store.get_messages(resolved, limit=limit)
        return {
            "session_id": resolved,
            "messages": [message.__dict__ for message in messages],
        }

    def children(self, session_id: str) -> list[dict[str, Any]]:
        resolved = self.resolve_session_id(session_id)
        return [child.to_dict() for child in self.graph.children(resolved)]

    def make_handoff(
        self,
        source_session_id: str,
        *,
        target_session_id: str = "",
        target_agent: str = "",
        goal: str = "",
        reason: str = "",
        tail: int = 8,
    ) -> HandoffPacket:
        source = self.resolve_session_id(source_session_id)
        history = self.history(source, limit=tail)
        return HandoffPacket(
            id=f"handoff-{uuid.uuid4().hex[:8]}",
            source_session_id=source,
            target_session_id=target_session_id,
            target_agent=target_agent,
            goal=goal,
            reason=reason,
            transcript_tail=history["messages"],
            graph_context=self.info(source),
        )

    def handoff_to_session(
        self,
        source_session_id: str,
        target_session_id: str,
        *,
        goal: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        target = self.resolve_session_id(target_session_id)
        packet = self.make_handoff(
            source_session_id,
            target_session_id=target,
            goal=goal,
            reason=reason,
        )
        self.manager.store.append_message(
            target,
            SessionMessage(role="user", content=packet.to_message()),
        )
        self.graph.upsert(target, status="idle", last_result_preview="handoff received")
        return packet.to_dict()

    def fork_to_agent(
        self,
        source_session_id: str,
        *,
        agent: str,
        new_session_id: str = "",
        title: str = "",
        goal: str = "",
    ) -> dict[str, Any]:
        source = self.resolve_session_id(source_session_id)
        fork_id = new_session_id or f"{_safe_id(source)}-{_safe_id(agent)}-{uuid.uuid4().hex[:4]}"
        metadata = self.manager.store.fork_session(source, fork_id)
        if title:
            metadata.title = title
            self.manager.store._save_metadata(metadata)
        packet = self.make_handoff(source, target_session_id=fork_id, target_agent=agent, goal=goal)
        self.manager.store.append_message(
            fork_id,
            SessionMessage(role="user", content=packet.to_message()),
        )
        record = self.graph.upsert(
            fork_id,
            metadata=metadata,
            kind="fork",
            agent_id=agent,
            agent_name=agent,
            title=title or metadata.title or f"{agent} fork of {source}",
            parent_session_id=source,
            root_session_id=self.info(source).get("root_session_id") or source,
            status="idle",
            record_metadata={"handoff_packet_id": packet.id, "forked_to_agent": agent},
        )
        return {"session": record.to_dict(), "handoff": packet.to_dict()}

    def resolve_session_id(self, session_id_or_prefix: str) -> str:
        candidate = session_id_or_prefix.strip()
        if not candidate:
            active = self.active()
            if active:
                return active
            raise KeyError("No session id supplied and no active session recorded")
        sessions = self.manager.list_all_sessions()
        exact = [item.session_id for item in sessions if item.session_id == candidate]
        if exact:
            return exact[0]
        matches = [item.session_id for item in sessions if item.session_id.startswith(candidate)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            record = self.graph.get(candidate)
            if record is not None:
                return record.session_id
            raise KeyError(f"Session not found: {candidate}")
        raise KeyError(f"Ambiguous session prefix: {candidate}")
