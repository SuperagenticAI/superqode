"""Persistent run/session store for the v2 harness layer."""

from __future__ import annotations

import json
import secrets
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
