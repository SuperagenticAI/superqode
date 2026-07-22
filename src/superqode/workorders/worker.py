"""Persistent headless workers for the durable WorkOrder queue."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import secrets
import socket
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TextIO

from .runner import WorkTaskExecution, execute_claimed_task
from .store import WorkOrderStore


@dataclass(frozen=True)
class WorkOrderWorkerConfig:
    """Runtime configuration for one persistent WorkOrder worker."""

    worker_id: str = ""
    reference: str = ""
    concurrency: int = 1
    poll_interval: float = 1.0
    lease_seconds: int = 300
    stale_after_seconds: int = 300
    provider: str = ""
    model: str = ""
    runtime: str = ""
    sandbox: str = ""
    isolation: str = "auto"
    retry: bool = True
    once: bool = False
    max_tasks: int = 0

    def normalized(self) -> "WorkOrderWorkerConfig":
        worker_id = self.worker_id.strip() or default_worker_id()
        return WorkOrderWorkerConfig(
            worker_id=worker_id,
            reference=self.reference.strip(),
            concurrency=max(1, int(self.concurrency)),
            poll_interval=max(0.05, float(self.poll_interval)),
            lease_seconds=max(1, int(self.lease_seconds)),
            stale_after_seconds=max(0, int(self.stale_after_seconds)),
            provider=self.provider.strip(),
            model=self.model.strip(),
            runtime=self.runtime.strip(),
            sandbox=self.sandbox.strip(),
            isolation=self.isolation.strip() or "auto",
            retry=bool(self.retry),
            once=bool(self.once),
            max_tasks=max(0, int(self.max_tasks)),
        )


@dataclass
class WorkOrderWorkerStats:
    """Observable counters for one worker process."""

    started_at: float = field(default_factory=time.time)
    claimed: int = 0
    succeeded: int = 0
    blocked: int = 0
    failed: int = 0
    cancelled: int = 0
    recovered_orders: int = 0
    execution_errors: int = 0
    last_activity_at: float = field(default_factory=time.time)
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkOrderWorkerSnapshot:
    """Last durable heartbeat emitted by a worker service."""

    worker_id: str
    status: str
    pid: int
    hostname: str
    started_at: float
    updated_at: float
    reference: str = ""
    active: tuple[dict[str, Any], ...] = ()
    stats: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["active"] = [dict(item) for item in self.active]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkOrderWorkerSnapshot":
        return cls(
            worker_id=str(data.get("worker_id") or ""),
            status=str(data.get("status") or "unknown"),
            pid=int(data.get("pid") or 0),
            hostname=str(data.get("hostname") or ""),
            started_at=float(data.get("started_at") or 0),
            updated_at=float(data.get("updated_at") or 0),
            reference=str(data.get("reference") or ""),
            active=tuple(dict(item) for item in data.get("active") or ()),
            stats=dict(data.get("stats") or {}),
            config=dict(data.get("config") or {}),
        )


class WorkOrderWorker:
    """Continuously claim and execute WorkOrder tasks with bounded concurrency."""

    def __init__(self, store: WorkOrderStore, config: WorkOrderWorkerConfig) -> None:
        self.store = store
        self.config = config.normalized()
        self.stats = WorkOrderWorkerStats()
        self._active: dict[asyncio.Task[WorkTaskExecution], dict[str, Any]] = {}
        self._lock: TextIO | None = None
        self._state_status = "starting"

    async def run(self, *, stop: asyncio.Event | None = None) -> WorkOrderWorkerStats:
        """Run until stopped, or until the queue is drained in ``once`` mode."""
        stop = stop or asyncio.Event()
        self._lock = _acquire_worker_lock(self.store, self.config.worker_id)
        self._state_status = "running"
        self._write_snapshot()
        next_recovery = 0.0
        try:
            while True:
                now = time.time()
                if now >= next_recovery:
                    await self._recover_stale()
                    recovery_interval = max(
                        self.config.poll_interval,
                        min(30.0, max(1.0, self.config.stale_after_seconds / 3)),
                    )
                    next_recovery = now + recovery_interval

                await self._collect_finished()
                reached_limit = (
                    self.config.max_tasks > 0 and self.stats.claimed >= self.config.max_tasks
                )
                claimed_this_scan = False
                while (
                    not stop.is_set()
                    and not reached_limit
                    and len(self._active) < self.config.concurrency
                ):
                    claimed = await asyncio.to_thread(
                        self.store.claim_next_task,
                        worker_id=self._lease_owner(self.stats.claimed + 1),
                        reference=self.config.reference,
                        lease_seconds=self.config.lease_seconds,
                    )
                    if claimed is None:
                        break
                    order, task = claimed
                    lease_owner = task.worker_id
                    execution = asyncio.create_task(
                        execute_claimed_task(
                            self.store,
                            order=order,
                            task=task,
                            worker_id=lease_owner,
                            lease_seconds=self.config.lease_seconds,
                            provider=self.config.provider,
                            model=self.config.model,
                            runtime=self.config.runtime,
                            sandbox=self.config.sandbox,
                            isolation=self.config.isolation,
                            retry=self.config.retry,
                        ),
                        name=f"workorder:{order.work_order_id}:{task.task_id}",
                    )
                    self._active[execution] = {
                        "work_order_id": order.work_order_id,
                        "task_id": task.task_id,
                        "role": task.role.value,
                        "worker_id": lease_owner,
                        "claimed_at": time.time(),
                        "lease_expires_at": task.lease_expires_at,
                    }
                    self.stats.claimed += 1
                    self.stats.last_activity_at = time.time()
                    claimed_this_scan = True
                    reached_limit = (
                        self.config.max_tasks > 0 and self.stats.claimed >= self.config.max_tasks
                    )
                    self._write_snapshot()

                if not self._active and (
                    stop.is_set() or reached_limit or (self.config.once and not claimed_this_scan)
                ):
                    break

                self._write_snapshot()
                if self._active:
                    await asyncio.wait(
                        tuple(self._active),
                        timeout=self.config.poll_interval,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                else:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=self.config.poll_interval)
                    except TimeoutError:
                        pass

            await self._collect_finished()
            return self.stats
        finally:
            self._state_status = "stopped"
            self._write_snapshot()
            if self._lock is not None:
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
                self._lock.close()
                self._lock = None

    async def _collect_finished(self) -> None:
        finished = [execution for execution in self._active if execution.done()]
        for execution in finished:
            self._active.pop(execution)
            try:
                result = execution.result()
            except asyncio.CancelledError:
                self.stats.cancelled += 1
            except Exception as exc:  # a worker must survive one broken task runner
                self.stats.execution_errors += 1
                self.stats.last_error = str(exc)
            else:
                if result.status == "succeeded":
                    self.stats.succeeded += 1
                elif result.status == "blocked":
                    self.stats.blocked += 1
                elif result.status == "cancelled":
                    self.stats.cancelled += 1
                else:
                    self.stats.failed += 1
                    self.stats.last_error = result.error
            self.stats.last_activity_at = time.time()
        if finished:
            self._write_snapshot()

    async def _recover_stale(self) -> None:
        recovered = await asyncio.to_thread(
            self.store.recover_stale,
            self.config.reference,
            stale_after_seconds=self.config.stale_after_seconds,
            actor=self.config.worker_id,
            exclude_worker_ids=tuple(str(item["worker_id"]) for item in self._active.values()),
        )
        if recovered:
            self.stats.recovered_orders += len(recovered)
            self.stats.last_activity_at = time.time()

    def _lease_owner(self, sequence: int) -> str:
        return f"{self.config.worker_id}/{sequence}"

    def _write_snapshot(self) -> None:
        path = worker_state_path(self.store, self.config.worker_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        public_config = asdict(self.config)
        snapshot = WorkOrderWorkerSnapshot(
            worker_id=self.config.worker_id,
            status=self._state_status,
            pid=os.getpid(),
            hostname=socket.gethostname(),
            started_at=self.stats.started_at,
            updated_at=time.time(),
            reference=self.config.reference,
            active=tuple(self._active.values()),
            stats=self.stats.to_dict(),
            config=public_config,
        )
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(snapshot.to_dict(), indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)


def default_worker_id() -> str:
    """Return a collision-resistant, operator-readable worker identity."""
    host = socket.gethostname().split(".", maxsplit=1)[0] or "host"
    return f"{host}-{os.getpid()}-{secrets.token_hex(2)}"


def worker_state_directory(store: WorkOrderStore) -> Path:
    return store.path.parent / "workers"


def worker_state_path(store: WorkOrderStore, worker_id: str) -> Path:
    return worker_state_directory(store) / f"{_safe_worker_id(worker_id)}.json"


def list_worker_snapshots(store: WorkOrderStore) -> list[WorkOrderWorkerSnapshot]:
    """Read every durable worker heartbeat, newest first."""
    directory = worker_state_directory(store)
    if not directory.is_dir():
        return []
    snapshots: list[WorkOrderWorkerSnapshot] = []
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            snapshots.append(WorkOrderWorkerSnapshot.from_dict(payload))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return sorted(snapshots, key=lambda item: item.updated_at, reverse=True)


def _acquire_worker_lock(store: WorkOrderStore, worker_id: str) -> TextIO:
    directory = worker_state_directory(store)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_safe_worker_id(worker_id)}.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError(f"WorkOrder worker is already running: {worker_id}") from exc
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def _safe_worker_id(worker_id: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in "-." else "-"
        for character in worker_id.strip()
    ).strip("-.")
    if not normalized:
        raise ValueError("worker_id is required")
    return normalized[:120]
