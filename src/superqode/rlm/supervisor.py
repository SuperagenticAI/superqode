"""Live recursive-agent supervision for the native RLM harness."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar, cast
from uuid import uuid4

from .identity import (
    RUNTIME_IDENTITY_VERSION,
    KernelIdentity,
    SandboxIdentity,
    WorkerIdentity,
    execution_alive,
    process_alive,
)

AgentStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]
_AGENT_STATUSES = {
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
}
AgentRunner = Callable[["AgentRecord"], Awaitable[str]]
AgentEventSink = Callable[[dict[str, Any]], None]
T = TypeVar("T")


@dataclass(slots=True)
class AgentRecord:
    """Mutable supervisor-owned state for one child RLM session."""

    id: str
    prompt: str
    parent_id: str
    model: str | None = None
    status: AgentStatus = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    result: str | None = None
    error: str | None = None
    session_id: str | None = None
    worker_pid: int | None = None
    worker_request_path: str | None = None
    worker_result_path: str | None = None
    worker_control_path: str | None = None
    sandbox: SandboxIdentity = field(default_factory=SandboxIdentity)
    kernel: KernelIdentity = field(default_factory=KernelIdentity)
    usage: dict[str, Any] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)
    pending_messages: list[str] = field(default_factory=list)
    pending_steering: list[str] = field(default_factory=list)
    session: Any | None = field(default=None, repr=False)

    @property
    def worker(self) -> WorkerIdentity:
        """A typed view of the process identity kept in the flat fields.

        The flat fields stay authoritative so released journals and every
        existing call site keep working; this is the handle recovery and the
        sandboxed kernel read.
        """
        return WorkerIdentity(
            pid=self.worker_pid,
            request_path=self.worker_request_path,
            result_path=self.worker_result_path,
            control_path=self.worker_control_path,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "parent_id": self.parent_id,
            "model": self.model,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
            "session_id": self.session_id,
            "worker_pid": self.worker_pid,
            "worker_request_path": self.worker_request_path,
            "worker_result_path": self.worker_result_path,
            "worker_control_path": self.worker_control_path,
            "sandbox": self.sandbox.to_dict(),
            "kernel": self.kernel.to_dict(),
            "identity_version": RUNTIME_IDENTITY_VERSION,
            "usage": dict(self.usage),
            "children": list(self.children),
        }


class AgentHandle:
    """Synchronous child handle designed for use inside the Python kernel."""

    def __init__(self, supervisor: "AgentSupervisor", agent_id: str) -> None:
        self._supervisor = supervisor
        self.id = agent_id

    @property
    def parent_id(self) -> str:
        return str(self.status().get("parent_id") or "")

    def status(self) -> dict[str, Any]:
        return self._supervisor.snapshot(self.id)

    def send(self, message: str) -> None:
        self._supervisor.call(self._supervisor.send(self.id, message))

    def steer(self, instruction: str) -> None:
        self._supervisor.call(self._supervisor.steer(self.id, instruction))

    def wait(self, timeout: float | None = None) -> str:
        return self._supervisor.call(self._supervisor.wait(self.id), timeout=timeout)

    def cancel(self) -> None:
        self._supervisor.call(self._supervisor.cancel(self.id))

    def delete(self) -> None:
        self._supervisor.delete(self.id)

    def __repr__(self) -> str:
        state = self.status()
        return f"AgentHandle(id={self.id!r}, status={state['status']!r})"


class AgentSupervisor:
    """Own live child tasks and bridge synchronous Python to the async runtime."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        runner: AgentRunner | None = None,
        *,
        max_depth: int = 3,
        max_children: int = 8,
        max_parallel: int = 4,
        event_sink: AgentEventSink | None = None,
        journal_path: str | Path | None = None,
    ) -> None:
        self.loop = loop
        self._loop_thread = threading.get_ident()
        self._runner = runner
        self.max_depth = max(0, max_depth)
        self.max_children = max(1, max_children)
        self.max_parallel = max(1, max_parallel)
        self._event_sink = event_sink
        self.journal_path = Path(journal_path).expanduser() if journal_path else None
        self._records: dict[str, AgentRecord] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._events: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._capacity = asyncio.Semaphore(self.max_parallel)
        self._recoverable_ids: list[str] = []
        self._recover()

    def set_runner(self, runner: AgentRunner) -> None:
        self._runner = runner
        for agent_id in self._recoverable_ids:
            if threading.get_ident() == self._loop_thread:
                self._start(agent_id, True)
            else:
                self.loop.call_soon_threadsafe(self._start, agent_id, True)
        self._recoverable_ids.clear()

    def mark_worker(
        self,
        agent_id: str,
        *,
        pid: int,
        request_path: str | Path,
        result_path: str | Path,
        control_path: str | Path,
        sandbox: SandboxIdentity | None = None,
    ) -> None:
        with self._lock:
            record = self._record(agent_id)
            record.worker_pid = pid
            record.worker_request_path = str(request_path)
            record.worker_result_path = str(result_path)
            record.worker_control_path = str(control_path)
            if sandbox is not None:
                record.sandbox = sandbox
            # A child gets its own namespace even when it shares a sandbox.
            record.kernel = KernelIdentity(kernel_id=agent_id, sandbox_id=record.sandbox.sandbox_id)
        self._emit("agent.worker_started", record)

    def spawn(
        self, prompt: str, *, parent_id: str = "root", model: str | None = None
    ) -> AgentHandle:
        text = str(prompt).strip()
        if not text:
            raise ValueError("Child prompt cannot be empty")
        with self._lock:
            if len(self._records) >= self.max_children:
                raise RuntimeError(f"RLM child limit reached ({self.max_children})")
            self._validate_depth(parent_id)
            agent_id = f"agent-{uuid4().hex[:10]}"
            record = AgentRecord(id=agent_id, prompt=text, parent_id=parent_id, model=model)
            self._records[agent_id] = record
            parent = self._records.get(parent_id)
            if parent is not None:
                parent.children.append(agent_id)
        self._emit("agent.spawned", record)
        if threading.get_ident() == self._loop_thread:
            self._start(agent_id)
        else:
            self.loop.call_soon_threadsafe(self._start, agent_id)
        return AgentHandle(self, agent_id)

    def spawn_batch(
        self,
        prompts: Sequence[str],
        *,
        parent_id: str = "root",
        model: str | None = None,
    ) -> list[AgentHandle]:
        return [self.spawn(prompt, parent_id=parent_id, model=model) for prompt in prompts]

    def handles(self, *, parent_id: str | None = None) -> list[AgentHandle]:
        with self._lock:
            identifiers = [
                record.id
                for record in self._records.values()
                if parent_id is None or record.parent_id == parent_id
            ]
        return [AgentHandle(self, agent_id) for agent_id in identifiers]

    def snapshot(self, agent_id: str) -> dict[str, Any]:
        with self._lock:
            return self._record(agent_id).snapshot()

    def depth(self, agent_id: str) -> int:
        with self._lock:
            depth = 0
            cursor = agent_id
            while cursor != "root":
                record = self._record(cursor)
                depth += 1
                cursor = record.parent_id
            return depth

    def snapshots(self, *, parent_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return [
                record.snapshot()
                for record in self._records.values()
                if parent_id is None or record.parent_id == parent_id
            ]

    def event_count(self) -> int:
        with self._lock:
            return len(self._events)

    def events_since(self, cursor: int) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            return [dict(event) for event in self._events[max(0, cursor) :]], len(self._events)

    async def attach_session(self, agent_id: str, session: Any) -> None:
        with self._lock:
            record = self._record(agent_id)
            record.session = session
            record.session_id = str((await session.info()).id)
            messages = list(record.pending_messages)
            steering = list(record.pending_steering)
            record.pending_messages.clear()
            record.pending_steering.clear()
        for message in steering:
            await session.steer(message)
        for message in messages:
            await session.follow_up(message)

    async def send(self, agent_id: str, message: str) -> None:
        text = str(message).strip()
        if not text:
            raise ValueError("Agent message cannot be empty")
        with self._lock:
            record = self._record(agent_id)
            if record.status in {"completed", "failed", "cancelled", "interrupted"}:
                raise RuntimeError(f"Agent {agent_id} is already {record.status}")
            session = record.session
            if session is None:
                if record.worker_control_path:
                    self._write_worker_control(record, "follow_up", text)
                else:
                    record.pending_messages.append(text)
        if session is not None:
            await session.follow_up(text)
        self._emit("agent.message", record, message=text, mode="follow_up")

    async def steer(self, agent_id: str, instruction: str) -> None:
        text = str(instruction).strip()
        if not text:
            raise ValueError("Steering instruction cannot be empty")
        with self._lock:
            record = self._record(agent_id)
            if record.status in {"completed", "failed", "cancelled", "interrupted"}:
                raise RuntimeError(f"Agent {agent_id} is already {record.status}")
            session = record.session
            if session is None:
                if record.worker_control_path:
                    self._write_worker_control(record, "steer", text)
                else:
                    record.pending_steering.append(text)
        if session is not None:
            await session.steer(text)
        self._emit("agent.message", record, message=text, mode="steer")

    async def wait(self, agent_id: str) -> str:
        while True:
            with self._lock:
                record = self._record(agent_id)
                task = self._tasks.get(agent_id)
                queued = record.status == "queued"
            if task is not None or not queued:
                break
            await asyncio.sleep(0)
        if task is not None:
            await asyncio.shield(task)
        with self._lock:
            record = self._record(agent_id)
            if record.status == "completed":
                return record.result or ""
            if record.status == "cancelled":
                raise asyncio.CancelledError(f"Agent {agent_id} was cancelled")
            raise RuntimeError(record.error or f"Agent {agent_id} failed")

    async def wait_all(self, agent_ids: Sequence[str]) -> list[str]:
        return list(await asyncio.gather(*(self.wait(agent_id) for agent_id in agent_ids)))

    async def cancel(self, agent_id: str) -> None:
        with self._lock:
            record = self._record(agent_id)
            session = record.session
            task = self._tasks.get(agent_id)
            worker_control_path = record.worker_control_path
        if session is not None:
            await session.abort()
        elif worker_control_path:
            self._write_worker_control(record, "cancel", "")
        if task is not None and not task.done():
            if worker_control_path:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5)
                except TimeoutError:
                    task.cancel()
            else:
                task.cancel()
        with self._lock:
            changed = record.status != "cancelled"
            if changed:
                record.status = "cancelled"
                record.completed_at = time.time()
        if changed:
            self._emit("agent.cancelled", record)

    def delete(self, agent_id: str) -> None:
        with self._lock:
            record = self._record(agent_id)
            if record.status in {"queued", "running"}:
                raise RuntimeError(f"Cannot delete active agent {agent_id}")
            self._records.pop(agent_id)
            self._tasks.pop(agent_id, None)
            parent = self._records.get(record.parent_id)
            if parent is not None and agent_id in parent.children:
                parent.children.remove(agent_id)
        self._emit("agent.deleted", record)

    def call(self, coroutine: Coroutine[Any, Any, T], *, timeout: float | None = None) -> T:
        """Run an async supervisor operation from a Python-kernel worker thread."""
        if threading.get_ident() == self._loop_thread:
            coroutine.close()
            raise RuntimeError("Blocking RLM handle operations must run inside the Python tool")
        future: concurrent.futures.Future[T] = asyncio.run_coroutine_threadsafe(
            coroutine, self.loop
        )
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError("Timed out waiting for RLM agent operation") from exc

    def _start(self, agent_id: str, resumed: bool = False) -> None:
        self._tasks[agent_id] = self.loop.create_task(self._drive(agent_id, resumed=resumed))

    async def _drive(self, agent_id: str, *, resumed: bool = False) -> None:
        with self._lock:
            record = self._record(agent_id)
            record.status = "running"
            if record.started_at is None:
                record.started_at = time.time()
        self._emit("agent.reattached" if resumed else "agent.started", record)
        try:
            if self._runner is None:
                raise RuntimeError("RLM child runner is not configured")
            async with self._capacity:
                result = await self._runner(record)
        except asyncio.CancelledError:
            with self._lock:
                detached = execution_alive(record.worker, record.sandbox)
                if not detached:
                    record.status = "cancelled"
                    record.completed_at = time.time()
            self._emit("agent.detached" if detached else "agent.cancelled", record)
            return
        except BaseException as exc:  # noqa: BLE001 - child failure is durable state
            with self._lock:
                record.status = "failed"
                record.error = str(exc)
                record.completed_at = time.time()
            self._emit("agent.failed", record, error=str(exc), error_type=type(exc).__name__)
            return
        with self._lock:
            record.status = "completed"
            record.result = str(result)
            record.completed_at = time.time()
        self._emit("agent.completed", record, result=record.result)

    def _record(self, agent_id: str) -> AgentRecord:
        try:
            return self._records[agent_id]
        except KeyError as exc:
            raise KeyError(f"Unknown RLM agent: {agent_id}") from exc

    def _validate_depth(self, parent_id: str) -> None:
        depth = 1
        cursor = parent_id
        while cursor != "root":
            parent = self._records.get(cursor)
            if parent is None:
                raise KeyError(f"Unknown parent RLM agent: {cursor}")
            depth += 1
            cursor = parent.parent_id
        if depth > self.max_depth:
            raise RuntimeError(f"RLM recursion depth limit reached ({self.max_depth})")

    def _emit(self, event_type: str, record: AgentRecord, **data: Any) -> None:
        event = {
            "type": event_type,
            "timestamp": time.time(),
            "agent": record.snapshot(),
            **data,
        }
        with self._lock:
            self._events.append(event)
            self._append_journal(event)
        if self._event_sink is None:
            return
        self._event_sink(dict(event))

    def _recover(self) -> None:
        path = self.journal_path
        if path is None or not path.is_file():
            return
        latest: dict[str, dict[str, Any]] = {}
        deleted: set[str] = set()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(event, dict):
                continue
            agent = event.get("agent")
            if not isinstance(agent, dict) or not agent.get("id"):
                continue
            agent_id = str(agent["id"])
            if event.get("type") == "agent.deleted":
                deleted.add(agent_id)
                latest.pop(agent_id, None)
                continue
            if agent_id not in deleted:
                latest[agent_id] = agent
        for agent_id, data in latest.items():
            status = str(data.get("status") or "failed")
            error = str(data.get("error") or "") or None
            # A journal written before identities were recorded has no sandbox
            # section, which resolves to the host profile it was written under.
            sandbox_identity = SandboxIdentity.from_dict(data.get("sandbox"))
            runtime_identity = _read_worker_sandbox_identity(data)
            if runtime_identity is not None:
                sandbox_identity = runtime_identity
            kernel_identity = KernelIdentity.from_dict(data.get("kernel"))
            if status in {"queued", "running"}:
                worker_pid = _optional_int(data.get("worker_pid"))
                result_path = str(data.get("worker_result_path") or "")
                recovered_result = _read_worker_result(result_path)
                if recovered_result is not None:
                    status = str(recovered_result.get("status") or "failed")
                    error = str(recovered_result.get("error") or "") or None
                    data["result"] = recovered_result.get("result")
                    data["usage"] = recovered_result.get("usage") or {}
                    data["completed_at"] = recovered_result.get("completed_at") or time.time()
                elif execution_alive(
                    WorkerIdentity(pid=worker_pid), sandbox_identity
                ) and _worker_identity_matches(agent_id, data, cast(int, worker_pid)):
                    status = "running"
                    self._recoverable_ids.append(agent_id)
                else:
                    status = "interrupted"
                    error = "Agent was interrupted by a supervisor process restart"
            elif status not in _AGENT_STATUSES:
                status = "failed"
                error = error or "Agent journal contains an unknown status"
            record = AgentRecord(
                id=agent_id,
                prompt=str(data.get("prompt") or ""),
                parent_id=str(data.get("parent_id") or "root"),
                model=str(data.get("model")) if data.get("model") is not None else None,
                status=cast(AgentStatus, status),
                created_at=float(data.get("created_at") or time.time()),
                started_at=_optional_float(data.get("started_at")),
                completed_at=_optional_float(data.get("completed_at")),
                result=str(data.get("result")) if data.get("result") is not None else None,
                error=error,
                session_id=(
                    str(data.get("session_id")) if data.get("session_id") is not None else None
                ),
                worker_pid=_optional_int(data.get("worker_pid")),
                worker_request_path=(
                    str(data.get("worker_request_path"))
                    if data.get("worker_request_path") is not None
                    else None
                ),
                worker_result_path=(
                    str(data.get("worker_result_path"))
                    if data.get("worker_result_path") is not None
                    else None
                ),
                worker_control_path=(
                    str(data.get("worker_control_path"))
                    if data.get("worker_control_path") is not None
                    else None
                ),
                sandbox=sandbox_identity,
                kernel=kernel_identity,
                usage=(
                    dict(data.get("usage") or {}) if isinstance(data.get("usage"), dict) else {}
                ),
                children=[str(item) for item in data.get("children") or []],
            )
            self._records[agent_id] = record
        for record in self._records.values():
            record.children = [
                child_id for child_id in record.children if child_id in self._records
            ]

    def _append_journal(self, event: dict[str, Any]) -> None:
        path = self.journal_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")
        except OSError:
            return

    @staticmethod
    def _write_worker_control(record: AgentRecord, operation: str, message: str) -> None:
        if not record.worker_control_path:
            return
        path = Path(record.worker_control_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"operation": operation, "message": message, "timestamp": time.time()},
                    separators=(",", ":"),
                )
                + "\n"
            )


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _read_worker_result(path: str) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _read_worker_sandbox_identity(data: dict[str, Any]) -> SandboxIdentity | None:
    """Read the boundary identity published by a detached worker.

    The file is metadata only. It is JSON, never executable state, and lets a
    new supervisor verify the actual container rather than trusting a PID or a
    container name reconstructed from stale configuration.
    """
    request_path = str(data.get("worker_request_path") or "")
    if not request_path:
        return None
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        runtime_path = str(request.get("runtime_path") or "")
        runtime = json.loads(Path(runtime_path).read_text(encoding="utf-8"))
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if not isinstance(runtime, dict):
        return None
    identity = SandboxIdentity.from_dict(runtime.get("sandbox"))
    return identity if identity.backend else None


def _worker_identity_matches(agent_id: str, data: dict[str, Any], pid: int) -> bool:
    request_path = str(data.get("worker_request_path") or "")
    if not request_path:
        return True
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(request, dict) or str(request.get("agent_id") or "") != agent_id:
        return False
    try:
        recorded_pid = int(request.get("worker_pid") or 0)
    except (TypeError, ValueError):
        return False
    return recorded_pid == pid


__all__ = [
    "AgentHandle",
    "AgentRecord",
    "AgentRunner",
    "AgentStatus",
    "AgentSupervisor",
]
