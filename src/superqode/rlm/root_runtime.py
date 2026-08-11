"""Resident root-worker transport for the native RLM harness.

The terminal is a client, not the owner of an RLM turn.  One detached Python
worker owns the root session, its persistent kernel and the complete recursive
agent tree.  Commands and events use append-only JSONL files so disconnecting a
client cannot cancel work and a replacement client can replay from sequence 0.

This is lifecycle isolation, not a security boundary.  Model-written Python is
confined only when the session selects Docker or Monty.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from superqode.harness.events import HarnessEvent

from .config import agent_dir
from .identity import process_alive

ROOT_RUNTIME_PROTOCOL = "1.0"
_TERMINAL_RECORD = "runtime.command_completed"
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def runtime_dir(session_id: str, working_directory: str | Path | None = None) -> Path:
    safe = _UNSAFE.sub("-", str(session_id)).strip(".-")[:96] or "session"
    root = str(Path(working_directory or Path.cwd()).expanduser().resolve())
    scope = hashlib.sha256(root.encode()).hexdigest()[:12]
    return agent_dir() / "runtime" / f"{scope}-{safe}"


@dataclass(frozen=True, slots=True)
class RootRuntimeStatus:
    session_id: str
    generation: str = ""
    pid: int = 0
    state: str = "stopped"
    active_command: str = ""
    session_path: str = ""
    external_session_id: str = ""
    heartbeat: float = 0.0
    error: str = ""

    @property
    def alive(self) -> bool:
        # PID reuse must not make stale state look like our worker. The worker
        # refreshes this once a second; a process with the same PID but a stale
        # generation file cannot pass the freshness check.
        fresh = self.heartbeat > 0 and time.time() - self.heartbeat < 30
        return fresh and self.pid > 0 and process_alive(self.pid)

    @classmethod
    def from_dict(cls, session_id: str, value: Mapping[str, Any] | None) -> "RootRuntimeStatus":
        data = dict(value or {})
        return cls(
            session_id=session_id,
            generation=str(data.get("generation") or ""),
            pid=int(data.get("pid") or 0),
            state=str(data.get("state") or "stopped"),
            active_command=str(data.get("active_command") or ""),
            session_path=str(data.get("session_path") or ""),
            external_session_id=str(data.get("external_session_id") or ""),
            heartbeat=float(data.get("heartbeat") or 0.0),
            error=str(data.get("error") or ""),
        )


class RootRuntimeError(RuntimeError):
    """The resident root worker could not start or complete an operation."""


class RootRuntimeClient:
    """Attachable client for one resident native-RLM root worker."""

    def __init__(self, session_id: str, manifest: Mapping[str, Any]) -> None:
        self.session_id = str(session_id)
        self.manifest = {**dict(manifest), "protocol": ROOT_RUNTIME_PROTOCOL}
        self.directory = runtime_dir(self.session_id, self.manifest.get("working_directory"))
        self.manifest_path = self.directory / "manifest.json"
        self.commands_path = self.directory / "commands.jsonl"
        self.controls_path = self.directory / "controls.jsonl"
        self.events_path = self.directory / "events.jsonl"
        self.state_path = self.directory / "state.json"
        self.log_path = self.directory / "worker.log"
        self.lock_path = self.directory / "launch.lock"

    def status(self) -> RootRuntimeStatus:
        return RootRuntimeStatus.from_dict(self.session_id, _read_json(self.state_path))

    async def ensure(self, *, timeout: float = 15.0) -> RootRuntimeStatus:
        """Start the worker once and wait for an authoritative ready state."""
        self.directory.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._ensure_started)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.status()
            if status.alive and status.state in {"ready", "running"}:
                return status
            if status.state == "failed":
                raise RootRuntimeError(status.error or "RLM root worker failed during startup")
            await asyncio.sleep(0.05)
        status = self.status()
        raise RootRuntimeError(
            f"RLM root worker did not become ready within {timeout:g}s"
            + (f": {status.error}" if status.error else "")
        )

    def _ensure_started(self) -> None:
        with _launch_lock(self.lock_path):
            current = self.status()
            if current.alive:
                return
            if current.active_command:
                complete_runtime_command(
                    self.events_path,
                    current.active_command,
                    status="failed",
                    error="Resident RLM worker exited before the command completed",
                )
            _atomic_json(self.manifest_path, self.manifest)
            generation = uuid4().hex
            _atomic_json(
                self.state_path,
                {
                    "protocol": ROOT_RUNTIME_PROTOCOL,
                    "session_id": self.session_id,
                    "generation": generation,
                    "pid": 0,
                    "state": "starting",
                    "heartbeat": time.time(),
                },
            )
            with self.log_path.open("ab") as log:
                process = subprocess.Popen(  # noqa: S603 - fixed module invocation
                    [
                        sys.executable,
                        "-m",
                        "superqode.rlm.root_worker",
                        str(self.manifest_path),
                        "--generation",
                        generation,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
            state = _read_json(self.state_path) or {}
            state.update({"pid": process.pid, "generation": generation, "heartbeat": time.time()})
            _atomic_json(self.state_path, state)

    async def submit(self, operation: str, payload: Mapping[str, Any] | None = None) -> str:
        status = await self.ensure()
        command_id = f"cmd_{uuid4().hex}"
        _append_jsonl(
            self.commands_path,
            {
                "protocol": ROOT_RUNTIME_PROTOCOL,
                "id": command_id,
                "operation": operation,
                "payload": dict(payload or {}),
                "generation": status.generation,
                "created_at": time.time(),
            },
        )
        return command_id

    async def control(self, operation: str, payload: Mapping[str, Any] | None = None) -> None:
        status = await self.ensure()
        _append_jsonl(
            self.controls_path,
            {
                "protocol": ROOT_RUNTIME_PROTOCOL,
                "id": f"ctl_{uuid4().hex}",
                "operation": operation,
                "payload": dict(payload or {}),
                "generation": status.generation,
                "created_at": time.time(),
            },
        )

    async def events(
        self,
        command_id: str,
        *,
        poll_interval: float = 0.05,
    ) -> AsyncIterator[HarnessEvent]:
        """Replay and then follow one command without owning its lifetime."""
        offset = 0
        while True:
            records, offset = _read_jsonl_since(self.events_path, offset)
            for record in records:
                if str(record.get("command_id") or "") != command_id:
                    continue
                if record.get("type") == _TERMINAL_RECORD:
                    if str(record.get("status") or "") == "failed":
                        raise RootRuntimeError(str(record.get("error") or "RLM command failed"))
                    return
                raw = record.get("event")
                if isinstance(raw, dict):
                    yield _event_from_dict(raw)
            status = self.status()
            if not status.alive:
                raise RootRuntimeError(
                    status.error or f"RLM root worker stopped while {command_id} was active"
                )
            await asyncio.sleep(poll_interval)

    async def request(
        self,
        operation: str,
        payload: Mapping[str, Any] | None = None,
    ) -> list[HarnessEvent]:
        command_id = await self.submit(operation, payload)
        return [event async for event in self.events(command_id)]


def append_runtime_event(path: Path, command_id: str, event: HarnessEvent) -> None:
    _append_jsonl(
        path,
        {"command_id": command_id, "type": "event", "event": event.to_dict()},
    )


def complete_runtime_command(
    path: Path,
    command_id: str,
    *,
    status: str = "completed",
    error: str = "",
) -> None:
    _append_jsonl(
        path,
        {
            "command_id": command_id,
            "type": _TERMINAL_RECORD,
            "status": status,
            "error": error,
            "completed_at": time.time(),
        },
    )


def _event_from_dict(data: Mapping[str, Any]) -> HarnessEvent:
    return HarnessEvent(
        type=str(data.get("type") or "error"),
        data=dict(data.get("data") or {}),
        timestamp=float(data.get("timestamp") or time.time()),
        session_id=data.get("session_id"),
        run_id=data.get("run_id"),
        protocol_version=str(data.get("protocol_version") or "1.0"),
        event_id=str(data.get("event_id") or f"evt_{uuid4().hex}"),
        sequence=int(data.get("sequence") or 0),
        harness_id=data.get("harness_id"),
        parent_event_id=data.get("parent_event_id"),
    )


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(dict(value), default=str, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_jsonl_since(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            lines = handle.readlines()
            position = handle.tell()
    except OSError:
        return [], offset
    values: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values, position


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


@contextmanager
def _launch_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


__all__ = [
    "ROOT_RUNTIME_PROTOCOL",
    "RootRuntimeClient",
    "RootRuntimeError",
    "RootRuntimeStatus",
    "append_runtime_event",
    "complete_runtime_command",
    "runtime_dir",
]
