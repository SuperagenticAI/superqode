"""Checkpoint evaluation cases on the existing WorkOrder store."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from superqode.workorders.models import WorkOrder, WorkOrderTask, WorkTaskStatus
from superqode.workorders.store import WorkOrderStore
from superqode.workorders.recovery import (
    RecoveryScope,
    input_fingerprint,
    recovery_scope,
    workspace_fingerprint,
)
from superqode.workorders.usage import usage_from_result


class EvaluationRecovery:
    """One immutable configuration/dataset identity, with case-level commits.

    Unknown live calls are unsafe by default, including unknown paid usage.
    A blocked case requires explicit WorkOrder reconciliation before resume.
    Concurrent workers do not share one variant's mutable workspace.
    """

    def __init__(
        self,
        store: WorkOrderStore,
        *,
        configuration: dict[str, Any],
        tasks: list[dict[str, Any]],
        working_directory: Path,
        lease_seconds: int = 300,
    ) -> None:
        self.store = store
        self.root = working_directory.resolve()
        self.identity = input_fingerprint(
            {"configuration": configuration, "tasks": tasks, "workspace": str(self.root)}
        )
        self.order_id = "eval-" + self.identity[:24]
        self.worker = f"eval-{os.getpid()}-{uuid4().hex[:12]}"
        self.lease_seconds = lease_seconds
        self.case_ids = {
            str(t["id"]): "case-" + input_fingerprint(str(t["id"]))[:16] for t in tasks
        }
        self.task_inputs = {str(t["id"]): t for t in tasks}
        try:
            store.get(self.order_id)
        except KeyError:
            order = WorkOrder(
                work_order_id=self.order_id,
                goal="Evaluate immutable harness cases",
                repository=str(self.root),
                metadata={"evaluation_identity": self.identity},
                tasks=tuple(
                    WorkOrderTask(
                        task_id=self.case_ids[str(t["id"])],
                        title=str(t["id"]),
                        goal=str(t["prompt"]),
                        max_attempts=10,
                    )
                    for t in tasks
                ),
            )
            store.create(order)
            store.queue(self.order_id)
        store.recover_stale(self.order_id)
        outcomes = [
            row
            for row in store.invocations(self.order_id)
            if row["status"] == "completed" and row["invocation_id"] == "evaluation-case"
        ]
        if outcomes and outcomes[-1]["workspace"] != workspace_fingerprint(
            self.root, exclude_paths=(store.path,)
        ):
            raise ValueError(
                "Evaluation workspace changed since the last committed case; reconciliation required"
            )

    async def run_case(
        self, case_id: str, execute: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        task_id = self.case_ids[case_id]
        order = self.store.get(self.order_id)
        task = next(t for t in order.tasks if t.task_id == task_id)
        rows = self.store.invocations(self.order_id, task_id)
        completed = next(
            (
                r
                for r in rows
                if r["status"] == "completed" and r["invocation_id"] == "evaluation-case"
            ),
            None,
        )
        if task.status == WorkTaskStatus.SUCCEEDED and completed:
            return {**completed["result"], "recovery": "reused"}
        if task.status == WorkTaskStatus.BLOCKED:
            raise ValueError(f"Evaluation case {case_id} requires reconciliation: {task.error}")
        claimed = self.store.claim_next_task(
            worker_id=self.worker, reference=self.order_id, lease_seconds=self.lease_seconds
        )
        if claimed is None:
            raise ValueError(f"Evaluation case {case_id} is owned by a live lease or blocked")
        _, task = claimed
        if task.task_id != task_id:
            self.store.fail_task(
                self.order_id,
                task.task_id,
                worker_id=self.worker,
                attempt=task.attempts,
                error="Evaluation claim order mismatch",
                retry=True,
            )
            raise ValueError("Evaluation recovery must process the declared case order")
        stop = asyncio.Event()

        async def heartbeat():
            while True:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=max(0.1, self.lease_seconds / 3))
                    return
                except asyncio.TimeoutError:
                    self.store.heartbeat(
                        self.order_id,
                        task_id,
                        worker_id=self.worker,
                        attempt=task.attempts,
                        lease_seconds=self.lease_seconds,
                    )

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            admission = self.store.begin_invocation(
                self.order_id,
                task_id,
                worker_id=self.worker,
                attempt=task.attempts,
                invocation_id="evaluation-case",
                operation="evaluation.case",
                fingerprint=input_fingerprint(
                    {"identity": self.identity, "task": self.task_inputs[case_id]}
                ),
                replay_safe=False,
                workspace=await asyncio.to_thread(
                    workspace_fingerprint, self.root, exclude_paths=(self.store.path,)
                ),
            )
            if admission["action"] == "reuse":
                result = admission["result"]
            else:
                with recovery_scope(
                    RecoveryScope(self.store, self.order_id, task_id, self.worker, task.attempts)
                ):
                    result = await execute()
                self.store.finish_invocation(
                    self.order_id,
                    task_id,
                    worker_id=self.worker,
                    attempt=task.attempts,
                    invocation_id="evaluation-case",
                    result=result,
                    workspace=await asyncio.to_thread(
                        workspace_fingerprint, self.root, exclude_paths=(self.store.path,)
                    ),
                )
            usage = usage_from_result(
                result, task=task, latency_ms=int(float(result.get("duration_seconds", 0)) * 1000)
            )
            _, decision = self.store.record_usage(
                self.order_id, usage, actor=self.worker, invocation_id="evaluation-case"
            )
            if not decision.allowed:
                self.store.block_task(
                    self.order_id,
                    task_id,
                    worker_id=self.worker,
                    attempt=task.attempts,
                    reason=decision.reason,
                )
                raise ValueError(decision.reason)
            self.store.complete_task(
                self.order_id, task_id, worker_id=self.worker, attempt=task.attempts
            )
            return {
                **result,
                "recovery": "reused" if admission["action"] == "reuse" else "committed",
            }
        except Exception as exc:
            current = next(t for t in self.store.get(self.order_id).tasks if t.task_id == task_id)
            if current.status == WorkTaskStatus.RUNNING:
                self.store.block_task(
                    self.order_id,
                    task_id,
                    worker_id=self.worker,
                    attempt=task.attempts,
                    reason=str(exc),
                )
            raise
        finally:
            stop.set()
            await heartbeat_task
