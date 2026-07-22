"""SQLite-backed WorkOrder lifecycle and worker leasing."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .models import (
    TERMINAL_WORK_ORDER_STATUSES,
    WorkArtifact,
    WorkOrder,
    WorkOrderDecision,
    WorkOrderEvent,
    WorkOrderStatus,
    WorkOrderTask,
    WorkTaskStatus,
    generate_artifact_id,
    generate_event_id,
)
from .usage import (
    WorkOrderPolicyDecision,
    WorkOrderUsage,
    WorkOrderUsageSummary,
    evaluate_work_order_policy,
    normalize_risk,
    usage_from_artifacts,
)


class WorkOrderStore:
    """Durable local WorkOrder store with atomic task claims."""

    def __init__(self, path: str | Path = ".superqode/workorders/store.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create(self, order: WorkOrder) -> WorkOrder:
        self._validate_order(order)
        with self._transaction() as conn:
            try:
                conn.execute(
                    """
                    insert into work_orders
                        (work_order_id, status, goal, created_at, updated_at, payload)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    self._row(order),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"WorkOrder already exists: {order.work_order_id}") from exc
            self._append_event_tx(
                conn,
                order.work_order_id,
                "work.created",
                data={"status": order.status.value, "goal": order.goal},
            )
        return order

    def get(self, reference: str) -> WorkOrder:
        with closing(self._connect()) as conn:
            return self._load_tx(conn, reference)

    def list(self, *, status: WorkOrderStatus | str | None = None) -> list[WorkOrder]:
        query = "select payload from work_orders"
        params: tuple[Any, ...] = ()
        if status is not None:
            value = status.value if isinstance(status, WorkOrderStatus) else str(status)
            query += " where status = ?"
            params = (value,)
        query += " order by created_at desc"
        with closing(self._connect()) as conn:
            return [
                WorkOrder.from_dict(json.loads(row["payload"]))
                for row in conn.execute(query, params)
            ]

    def events(self, reference: str, *, limit: int | None = None) -> list[WorkOrderEvent]:
        with closing(self._connect()) as conn:
            order = self._load_tx(conn, reference)
            query = """
                select event_id, work_order_id, type, created_at, task_id, actor, data
                from work_order_events where work_order_id = ? order by sequence
            """
            events = [
                WorkOrderEvent(
                    event_id=str(row["event_id"]),
                    work_order_id=str(row["work_order_id"]),
                    type=str(row["type"]),
                    created_at=float(row["created_at"]),
                    task_id=str(row["task_id"] or ""),
                    actor=str(row["actor"] or ""),
                    data=json.loads(row["data"] or "{}"),
                )
                for row in conn.execute(query, (order.work_order_id,))
            ]
            if limit is None:
                return events
            count = max(0, int(limit))
            return events[-count:] if count else []

    def add_task(self, reference: str, task: WorkOrderTask, *, actor: str = "") -> WorkOrder:
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if order.status != WorkOrderStatus.DRAFT:
                raise ValueError("Tasks may only be added while a WorkOrder is in draft")
            if any(item.task_id == task.task_id for item in order.tasks):
                raise ValueError(f"Duplicate WorkOrder task id: {task.task_id}")
            updated = replace(order, tasks=(*order.tasks, task), updated_at=time.time())
            self._validate_order(updated)
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                updated.work_order_id,
                "task.added",
                task_id=task.task_id,
                actor=actor,
                data={"title": task.title, "dependencies": list(task.dependencies)},
            )
            return updated

    def queue(self, reference: str, *, actor: str = "") -> WorkOrder:
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if order.status not in {WorkOrderStatus.DRAFT, WorkOrderStatus.BLOCKED}:
                raise ValueError(f"Cannot queue WorkOrder from {order.status.value}")
            if not order.tasks:
                raise ValueError("A WorkOrder needs at least one task before it can be queued")
            self._validate_order(order)
            tasks = tuple(
                replace(
                    task,
                    status=WorkTaskStatus.PENDING,
                    worker_id="",
                    lease_expires_at=None,
                    heartbeat_at=None,
                    error="",
                    updated_at=time.time(),
                )
                if task.status == WorkTaskStatus.BLOCKED
                else task
                for task in order.tasks
            )
            updated = replace(
                order,
                status=WorkOrderStatus.QUEUED,
                tasks=tasks,
                updated_at=time.time(),
                error="",
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                updated.work_order_id,
                "work.queued",
                actor=actor,
                data={"task_count": len(tasks)},
            )
            return updated

    def claim_next_task(
        self,
        *,
        worker_id: str,
        reference: str = "",
        lease_seconds: int = 300,
    ) -> tuple[WorkOrder, WorkOrderTask] | None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        with self._transaction() as conn:
            orders = (
                [self._load_tx(conn, reference)]
                if reference
                else self._list_tx(
                    conn,
                    statuses=(WorkOrderStatus.QUEUED, WorkOrderStatus.RUNNING),
                    ascending=True,
                )
            )
            now = time.time()
            for order in orders:
                order = self._recover_expired_tx(conn, order, now=now)
                if order.status not in {WorkOrderStatus.QUEUED, WorkOrderStatus.RUNNING}:
                    continue
                running_count = sum(task.status == WorkTaskStatus.RUNNING for task in order.tasks)
                if (
                    order.budget.max_workers is not None
                    and running_count >= order.budget.max_workers
                ):
                    continue
                completed = {
                    task.task_id for task in order.tasks if task.status == WorkTaskStatus.SUCCEEDED
                }
                claimable = next(
                    (
                        task
                        for task in order.tasks
                        if task.status == WorkTaskStatus.PENDING
                        and set(task.dependencies).issubset(completed)
                    ),
                    None,
                )
                if claimable is None:
                    continue
                admission = evaluate_work_order_policy(
                    order,
                    phase="admission",
                    task=claimable,
                    now=now,
                )
                if not admission.allowed:
                    denied = replace(
                        claimable,
                        status=WorkTaskStatus.BLOCKED,
                        error=admission.reason,
                        ended_at=now,
                        updated_at=now,
                    )
                    updated = self._refresh_order(
                        replace(
                            order,
                            tasks=_replace_task(order.tasks, denied),
                            updated_at=now,
                            metadata={
                                **order.metadata,
                                "last_policy_decision": admission.to_dict(),
                            },
                        )
                    )
                    self._save_tx(conn, updated)
                    self._append_event_tx(
                        conn,
                        updated.work_order_id,
                        "policy.denied",
                        task_id=claimable.task_id,
                        actor=worker_id,
                        data=admission.to_dict(),
                    )
                    continue
                claimed = replace(
                    claimable,
                    status=WorkTaskStatus.RUNNING,
                    attempts=claimable.attempts + 1,
                    worker_id=worker_id,
                    lease_expires_at=now + max(1, int(lease_seconds)),
                    heartbeat_at=now,
                    started_at=claimable.started_at or now,
                    updated_at=now,
                    error="",
                )
                updated = replace(
                    order,
                    status=WorkOrderStatus.RUNNING,
                    tasks=_replace_task(order.tasks, claimed),
                    updated_at=now,
                    error="",
                )
                self._save_tx(conn, updated)
                self._append_event_tx(
                    conn,
                    updated.work_order_id,
                    "task.claimed",
                    task_id=claimed.task_id,
                    actor=worker_id,
                    data={
                        "attempt": claimed.attempts,
                        "lease_expires_at": claimed.lease_expires_at,
                    },
                )
                return updated, claimed
        return None

    def heartbeat(
        self,
        reference: str,
        task_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> WorkOrderTask:
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            task = _find_task(order, task_id)
            self._assert_running_owner(task, worker_id)
            now = time.time()
            renewed = replace(
                task,
                heartbeat_at=now,
                lease_expires_at=now + max(1, int(lease_seconds)),
                updated_at=now,
            )
            self._save_tx(
                conn,
                replace(order, tasks=_replace_task(order.tasks, renewed), updated_at=now),
            )
            self._append_event_tx(
                conn,
                order.work_order_id,
                "task.heartbeat",
                task_id=task.task_id,
                actor=worker_id,
                data={"lease_expires_at": renewed.lease_expires_at},
            )
            return renewed

    def complete_task(
        self,
        reference: str,
        task_id: str,
        *,
        worker_id: str,
        run_id: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorkOrder:
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            task = _find_task(order, task_id)
            self._assert_running_owner(task, worker_id)
            now = time.time()
            completed = replace(
                task,
                status=WorkTaskStatus.SUCCEEDED,
                worker_id="",
                lease_expires_at=None,
                heartbeat_at=now,
                run_id=run_id or task.run_id,
                session_id=session_id or task.session_id,
                ended_at=now,
                updated_at=now,
                error="",
                metadata={**task.metadata, **(metadata or {})},
            )
            updated = self._refresh_order(
                replace(order, tasks=_replace_task(order.tasks, completed), updated_at=now)
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                updated.work_order_id,
                "task.completed",
                task_id=task.task_id,
                actor=worker_id,
                data={"run_id": completed.run_id, "session_id": completed.session_id},
            )
            if updated.status == WorkOrderStatus.REVIEWING:
                self._append_event_tx(
                    conn,
                    updated.work_order_id,
                    "work.ready_for_review",
                    data={"task_count": len(updated.tasks)},
                )
            return updated

    def fail_task(
        self,
        reference: str,
        task_id: str,
        *,
        worker_id: str,
        error: str,
        retry: bool = True,
        run_id: str = "",
    ) -> WorkOrder:
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            task = _find_task(order, task_id)
            self._assert_running_owner(task, worker_id)
            now = time.time()
            will_retry = retry and task.attempts < task.max_attempts
            failed = replace(
                task,
                status=(WorkTaskStatus.PENDING if will_retry else WorkTaskStatus.FAILED),
                worker_id="",
                lease_expires_at=None,
                heartbeat_at=now,
                run_id=run_id or task.run_id,
                ended_at=(None if will_retry else now),
                updated_at=now,
                error=error,
            )
            updated = self._refresh_order(
                replace(order, tasks=_replace_task(order.tasks, failed), updated_at=now)
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                updated.work_order_id,
                "task.retry_scheduled" if will_retry else "task.failed",
                task_id=task.task_id,
                actor=worker_id,
                data={"error": error, "attempt": task.attempts, "run_id": run_id},
            )
            return updated

    def block_task(
        self,
        reference: str,
        task_id: str,
        *,
        worker_id: str,
        reason: str,
        run_id: str = "",
        session_id: str = "",
    ) -> WorkOrder:
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            task = _find_task(order, task_id)
            self._assert_running_owner(task, worker_id)
            now = time.time()
            blocked = replace(
                task,
                status=WorkTaskStatus.BLOCKED,
                worker_id="",
                lease_expires_at=None,
                heartbeat_at=now,
                run_id=run_id or task.run_id,
                session_id=session_id or task.session_id,
                updated_at=now,
                error=reason,
            )
            updated = replace(
                order,
                status=WorkOrderStatus.BLOCKED,
                tasks=_replace_task(order.tasks, blocked),
                updated_at=now,
                error=reason,
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                updated.work_order_id,
                "task.blocked",
                task_id=task.task_id,
                actor=worker_id,
                data={"reason": reason, "run_id": run_id, "session_id": session_id},
            )
            return updated

    def recover_stale(
        self,
        reference: str = "",
        *,
        stale_after_seconds: int = 300,
        actor: str = "scheduler",
        exclude_worker_ids: Iterable[str] = (),
    ) -> list[WorkOrder]:
        excluded = frozenset(str(worker_id) for worker_id in exclude_worker_ids)
        with self._transaction() as conn:
            orders = (
                [self._load_tx(conn, reference)]
                if reference
                else self._list_tx(conn, statuses=(WorkOrderStatus.RUNNING,))
            )
            now = time.time()
            recovered: list[WorkOrder] = []
            for order in orders:
                updated = self._recover_expired_tx(
                    conn,
                    order,
                    now=now,
                    stale_after_seconds=stale_after_seconds,
                    actor=actor,
                    exclude_worker_ids=excluded,
                )
                if updated != order:
                    recovered.append(updated)
            return recovered

    def add_artifact(
        self,
        reference: str,
        *,
        kind: str,
        task_id: str = "",
        path: str = "",
        content: str = "",
        digest: str = "",
        metadata: dict[str, Any] | None = None,
        actor: str = "",
    ) -> WorkArtifact:
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if task_id:
                _find_task(order, task_id)
            artifact = WorkArtifact(
                artifact_id=generate_artifact_id(),
                kind=kind.strip() or "other",
                created_at=time.time(),
                task_id=task_id,
                path=path,
                content=content,
                digest=digest,
                metadata=dict(metadata or {}),
            )
            updated = replace(
                order,
                artifacts=(*order.artifacts, artifact),
                updated_at=time.time(),
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                order.work_order_id,
                "artifact.created",
                task_id=task_id,
                actor=actor,
                data={
                    "artifact_id": artifact.artifact_id,
                    "kind": artifact.kind,
                    "path": artifact.path,
                    "digest": artifact.digest,
                },
            )
            return artifact

    def record_usage(
        self,
        reference: str,
        usage: WorkOrderUsage,
        *,
        actor: str = "usage",
    ) -> tuple[WorkArtifact, WorkOrderPolicyDecision]:
        """Persist one task-attempt usage record and apply completion gates."""
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            _find_task(order, usage.task_id)
            now = time.time()
            artifact = WorkArtifact(
                artifact_id=generate_artifact_id(),
                kind="usage",
                created_at=now,
                task_id=usage.task_id,
                metadata={"usage": usage.to_dict()},
            )
            with_usage = replace(
                order,
                artifacts=(*order.artifacts, artifact),
                updated_at=now,
            )
            decision = evaluate_work_order_policy(
                with_usage,
                phase="completion",
                task=_find_task(with_usage, usage.task_id),
                now=now,
            )
            updated = replace(
                with_usage,
                status=WorkOrderStatus.BLOCKED if not decision.allowed else with_usage.status,
                error=decision.reason if not decision.allowed else with_usage.error,
                metadata={
                    **with_usage.metadata,
                    "usage": usage_from_artifacts(with_usage.artifacts).to_dict(),
                    "last_policy_decision": decision.to_dict(),
                },
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                updated.work_order_id,
                "usage.recorded",
                task_id=usage.task_id,
                actor=actor,
                data=usage.to_dict(),
            )
            if not decision.allowed:
                self._append_event_tx(
                    conn,
                    updated.work_order_id,
                    "budget.exhausted",
                    task_id=usage.task_id,
                    actor=actor,
                    data=decision.to_dict(),
                )
            return artifact, decision

    def usage_summary(self, reference: str) -> WorkOrderUsageSummary:
        """Return cumulative normalized usage for a WorkOrder."""
        return usage_from_artifacts(self.get(reference).artifacts)

    def policy_decision(
        self,
        reference: str,
        *,
        phase: str = "admission",
        task_id: str = "",
    ) -> WorkOrderPolicyDecision:
        """Explain the current WorkOrder budget/risk policy decision."""
        order = self.get(reference)
        task = _find_task(order, task_id) if task_id else None
        return evaluate_work_order_policy(order, phase=phase, task=task)

    def record_checks(
        self,
        reference: str,
        results: Iterable[dict[str, Any]],
        *,
        actor: str = "checks",
    ) -> WorkOrder:
        rows = [dict(item) for item in results]
        passed = bool(rows) and all(item.get("status") == "passed" for item in rows)
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if order.status not in {
                WorkOrderStatus.REVIEWING,
                WorkOrderStatus.CHECKING,
                WorkOrderStatus.READY_TO_MERGE,
                WorkOrderStatus.BLOCKED,
            }:
                raise ValueError(f"Cannot record acceptance checks from {order.status.value}")
            now = time.time()
            artifact = WorkArtifact(
                artifact_id=generate_artifact_id(),
                kind="check_result",
                created_at=now,
                content=json.dumps(rows, indent=2),
                metadata={"passed": passed, "count": len(rows)},
            )
            updated = replace(
                order,
                status=WorkOrderStatus.CHECKING if passed else WorkOrderStatus.BLOCKED,
                artifacts=(*order.artifacts, artifact),
                decision=None,
                updated_at=now,
                error="" if passed else "Acceptance checks failed",
                metadata={**order.metadata, "acceptance_checks_passed": passed},
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                order.work_order_id,
                "checks.completed" if passed else "checks.failed",
                actor=actor,
                data={"passed": passed, "results": rows, "artifact_id": artifact.artifact_id},
            )
            return updated

    def mark_ready_to_merge(
        self,
        reference: str,
        *,
        candidate_artifact_id: str,
        metadata: dict[str, Any],
        actor: str = "integration",
    ) -> WorkOrder:
        """Open the human approval gate for a conflict-free candidate patch."""
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if order.status not in {
                WorkOrderStatus.REVIEWING,
                WorkOrderStatus.CHECKING,
                WorkOrderStatus.READY_TO_MERGE,
            }:
                raise ValueError(f"Cannot prepare merge from {order.status.value}")
            if not order.tasks or any(
                task.status != WorkTaskStatus.SUCCEEDED for task in order.tasks
            ):
                raise ValueError("Cannot prepare merge until every task has succeeded")
            if order.acceptance_tests and not order.metadata.get("acceptance_checks_passed"):
                raise ValueError("Cannot prepare merge until WorkOrder acceptance checks pass")
            if not any(
                artifact.artifact_id == candidate_artifact_id
                and artifact.kind == "integration_candidate"
                for artifact in order.artifacts
            ):
                raise ValueError("Integration candidate artifact is missing")
            now = time.time()
            updated = replace(
                order,
                status=WorkOrderStatus.READY_TO_MERGE,
                decision=None,
                updated_at=now,
                error="",
                metadata={
                    **order.metadata,
                    "integration_candidate_id": candidate_artifact_id,
                    "integration": dict(metadata),
                },
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                order.work_order_id,
                "work.ready_to_merge",
                actor=actor,
                data={"artifact_id": candidate_artifact_id, **dict(metadata)},
            )
            return updated

    def block_integration(
        self,
        reference: str,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
        actor: str = "integration",
    ) -> WorkOrder:
        """Block delivery without discarding the candidate or task evidence."""
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if order.status in TERMINAL_WORK_ORDER_STATUSES:
                raise ValueError(f"Cannot block integration from {order.status.value}")
            now = time.time()
            updated = replace(
                order,
                status=WorkOrderStatus.BLOCKED,
                decision=None,
                updated_at=now,
                error=reason,
                metadata={
                    **order.metadata,
                    "integration": {**dict(metadata or {}), "blocked": True},
                },
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                order.work_order_id,
                "merge.blocked",
                actor=actor,
                data={"reason": reason, **dict(metadata or {})},
            )
            return updated

    def begin_merge(
        self,
        reference: str,
        *,
        candidate_artifact_id: str,
        expected_tree: str,
        actor: str = "human",
    ) -> WorkOrder:
        """Persist merge intent before mutating the target checkout."""
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if order.status != WorkOrderStatus.READY_TO_MERGE:
                raise ValueError(f"Cannot merge WorkOrder from {order.status.value}")
            if not order.decision or order.decision.verdict != "accepted":
                raise ValueError("Cannot merge until the integration candidate is approved")
            if order.metadata.get("integration_candidate_id") != candidate_artifact_id:
                raise ValueError("Approved integration candidate is no longer current")
            now = time.time()
            updated = replace(
                order,
                status=WorkOrderStatus.MERGING,
                updated_at=now,
                metadata={
                    **order.metadata,
                    "merge_intent": {
                        "candidate_artifact_id": candidate_artifact_id,
                        "expected_tree": expected_tree,
                        "actor": actor,
                        "started_at": now,
                    },
                },
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                order.work_order_id,
                "merge.started",
                actor=actor,
                data={
                    "artifact_id": candidate_artifact_id,
                    "expected_tree": expected_tree,
                },
            )
            return updated

    def mark_merged(
        self,
        reference: str,
        *,
        result_artifact_id: str,
        metadata: dict[str, Any],
        actor: str = "human",
    ) -> WorkOrder:
        """Close a persisted merge intent after verifying the resulting tree."""
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if order.status != WorkOrderStatus.MERGING:
                raise ValueError(f"Cannot complete merge from {order.status.value}")
            now = time.time()
            updated = replace(
                order,
                status=WorkOrderStatus.MERGED,
                updated_at=now,
                error="",
                metadata={
                    **order.metadata,
                    "merge_result_id": result_artifact_id,
                    "merge": dict(metadata),
                },
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                order.work_order_id,
                "work.merged",
                actor=actor,
                data={"artifact_id": result_artifact_id, **dict(metadata)},
            )
            return updated

    def mark_rolled_back(
        self,
        reference: str,
        *,
        result_artifact_id: str,
        reason: str = "",
        actor: str = "human",
    ) -> WorkOrder:
        """Record a verified reversal of a previously merged candidate."""
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if order.status != WorkOrderStatus.MERGED:
                raise ValueError(f"Cannot roll back WorkOrder from {order.status.value}")
            now = time.time()
            decision = WorkOrderDecision(
                verdict="rolled_back",
                decided_at=now,
                actor=actor,
                reason=reason,
                metadata={"previous_verdict": "accepted"},
            )
            updated = replace(
                order,
                status=WorkOrderStatus.ROLLED_BACK,
                decision=decision,
                updated_at=now,
                error=reason,
                metadata={**order.metadata, "rollback_result_id": result_artifact_id},
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                order.work_order_id,
                "work.rolled_back",
                actor=actor,
                data={"artifact_id": result_artifact_id, "reason": reason},
            )
            return updated

    def accept(
        self,
        reference: str,
        *,
        actor: str = "human",
        reason: str = "",
    ) -> WorkOrder:
        return self._decide(reference, "accepted", actor=actor, reason=reason)

    def reject(
        self,
        reference: str,
        *,
        actor: str = "human",
        reason: str = "",
    ) -> WorkOrder:
        return self._decide(reference, "rejected", actor=actor, reason=reason)

    def cancel(
        self,
        reference: str,
        *,
        actor: str = "human",
        reason: str = "",
    ) -> WorkOrder:
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if order.status in TERMINAL_WORK_ORDER_STATUSES:
                return order
            if order.status == WorkOrderStatus.MERGING:
                raise ValueError("Cannot cancel while a persisted merge is being finalized")
            now = time.time()
            tasks = tuple(
                task
                if task.status == WorkTaskStatus.SUCCEEDED
                else replace(
                    task,
                    status=WorkTaskStatus.CANCELLED,
                    worker_id="",
                    lease_expires_at=None,
                    ended_at=now,
                    updated_at=now,
                )
                for task in order.tasks
            )
            updated = replace(
                order,
                status=WorkOrderStatus.CANCELLED,
                tasks=tasks,
                updated_at=now,
                error=reason,
                decision=WorkOrderDecision(
                    verdict="cancelled", decided_at=now, actor=actor, reason=reason
                ),
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                order.work_order_id,
                "work.cancelled",
                actor=actor,
                data={"reason": reason},
            )
            return updated

    def resume(
        self,
        reference: str,
        *,
        task_id: str = "",
        actor: str = "human",
    ) -> WorkOrder:
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if order.status != WorkOrderStatus.BLOCKED:
                raise ValueError(f"Cannot resume WorkOrder from {order.status.value}")
            now = time.time()
            tasks = []
            resumed = False
            for task in order.tasks:
                should_resume = task.status == WorkTaskStatus.BLOCKED and (
                    not task_id or task.task_id == task_id
                )
                if should_resume:
                    resumed = True
                    tasks.append(
                        replace(
                            task,
                            status=WorkTaskStatus.PENDING,
                            error="",
                            worker_id="",
                            lease_expires_at=None,
                            heartbeat_at=None,
                            updated_at=now,
                        )
                    )
                else:
                    tasks.append(task)
            if not resumed and any(task.status != WorkTaskStatus.SUCCEEDED for task in tasks):
                raise ValueError("No blocked task matched the resume request")
            resumed_status = (
                WorkOrderStatus.REVIEWING
                if tasks and all(task.status == WorkTaskStatus.SUCCEEDED for task in tasks)
                else WorkOrderStatus.QUEUED
            )
            updated = replace(
                order,
                status=resumed_status,
                tasks=tuple(tasks),
                decision=None,
                updated_at=now,
                error="",
                metadata={**order.metadata, "acceptance_checks_passed": False},
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                order.work_order_id,
                "work.resumed",
                task_id=task_id,
                actor=actor,
            )
            return updated

    def _decide(self, reference: str, verdict: str, *, actor: str, reason: str) -> WorkOrder:
        target = WorkOrderStatus(verdict)
        with self._transaction() as conn:
            order = self._load_tx(conn, reference)
            if verdict == "accepted":
                if not order.tasks or any(
                    task.status != WorkTaskStatus.SUCCEEDED for task in order.tasks
                ):
                    raise ValueError("Cannot accept until every task has succeeded")
                if order.acceptance_tests and not order.metadata.get("acceptance_checks_passed"):
                    raise ValueError("Cannot accept until WorkOrder acceptance checks pass")
                if order.status not in {
                    WorkOrderStatus.REVIEWING,
                    WorkOrderStatus.CHECKING,
                    WorkOrderStatus.READY_TO_MERGE,
                }:
                    raise ValueError(f"Cannot accept WorkOrder from {order.status.value}")
            elif (
                order.status in TERMINAL_WORK_ORDER_STATUSES
                or order.status == WorkOrderStatus.MERGING
            ):
                raise ValueError(f"Cannot reject WorkOrder from {order.status.value}")
            now = time.time()
            decision = WorkOrderDecision(
                verdict=verdict,
                decided_at=now,
                actor=actor,
                reason=reason,
            )
            updated = replace(
                order,
                status=(
                    WorkOrderStatus.READY_TO_MERGE
                    if verdict == "accepted" and order.status == WorkOrderStatus.READY_TO_MERGE
                    else target
                ),
                decision=decision,
                updated_at=now,
                error="" if verdict == "accepted" else reason,
            )
            self._save_tx(conn, updated)
            self._append_event_tx(
                conn,
                order.work_order_id,
                f"work.{verdict}",
                actor=actor,
                data={"reason": reason},
            )
            return updated

    def _recover_expired_tx(
        self,
        conn: sqlite3.Connection,
        order: WorkOrder,
        *,
        now: float,
        stale_after_seconds: int = 300,
        actor: str = "scheduler",
        exclude_worker_ids: frozenset[str] = frozenset(),
    ) -> WorkOrder:
        changed = False
        tasks: list[WorkOrderTask] = []
        for task in order.tasks:
            if task.worker_id in exclude_worker_ids:
                tasks.append(task)
                continue
            heartbeat_stale = task.heartbeat_at is not None and task.heartbeat_at <= now - max(
                0, stale_after_seconds
            )
            lease_expired = task.lease_expires_at is not None and task.lease_expires_at <= now
            if task.status != WorkTaskStatus.RUNNING or not (lease_expired or heartbeat_stale):
                tasks.append(task)
                continue
            changed = True
            retry = task.attempts < task.max_attempts
            recovered = replace(
                task,
                status=WorkTaskStatus.PENDING if retry else WorkTaskStatus.FAILED,
                worker_id="",
                lease_expires_at=None,
                heartbeat_at=None,
                ended_at=None if retry else now,
                updated_at=now,
                error=f"Worker lease expired after attempt {task.attempts}",
                metadata={**task.metadata, "recovered_from_worker": task.worker_id},
            )
            tasks.append(recovered)
            self._append_event_tx(
                conn,
                order.work_order_id,
                "task.recovered" if retry else "task.lease_failed",
                task_id=task.task_id,
                actor=actor,
                data={"worker_id": task.worker_id, "attempt": task.attempts},
            )
        if not changed:
            return order
        updated = self._refresh_order(replace(order, tasks=tuple(tasks), updated_at=now))
        self._save_tx(conn, updated)
        return updated

    @staticmethod
    def _refresh_order(order: WorkOrder) -> WorkOrder:
        statuses = {task.status for task in order.tasks}
        if order.tasks and statuses == {WorkTaskStatus.SUCCEEDED}:
            status = WorkOrderStatus.REVIEWING
            error = ""
        elif WorkTaskStatus.FAILED in statuses:
            status = WorkOrderStatus.FAILED
            error = next((task.error for task in order.tasks if task.error), "Task failed")
        elif WorkTaskStatus.BLOCKED in statuses:
            status = WorkOrderStatus.BLOCKED
            error = next((task.error for task in order.tasks if task.error), "Task blocked")
        elif WorkTaskStatus.RUNNING in statuses:
            status = WorkOrderStatus.RUNNING
            error = ""
        else:
            status = WorkOrderStatus.QUEUED
            error = ""
        return replace(order, status=status, error=error)

    def _validate_order(self, order: WorkOrder) -> None:
        if not order.work_order_id.strip():
            raise ValueError("work_order_id is required")
        if not order.goal.strip():
            raise ValueError("WorkOrder goal is required")
        ids = [task.task_id for task in order.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("WorkOrder task ids must be unique")
        known = set(ids)
        if order.budget.max_risk:
            normalize_risk(order.budget.max_risk)
        for task in order.tasks:
            if not task.task_id.strip():
                raise ValueError("WorkOrder task id is required")
            if task.task_id in task.dependencies:
                raise ValueError(f"Task {task.task_id} cannot depend on itself")
            if task.risk:
                normalize_risk(task.risk)
            missing = set(task.dependencies) - known
            if missing:
                raise ValueError(
                    f"Task {task.task_id} has unknown dependencies: {', '.join(sorted(missing))}"
                )
        self._assert_acyclic(order.tasks)

    @staticmethod
    def _assert_acyclic(tasks: tuple[WorkOrderTask, ...]) -> None:
        dependencies = {task.task_id: set(task.dependencies) for task in tasks}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            if task_id in visiting:
                raise ValueError(f"WorkOrder task dependency cycle includes {task_id}")
            visiting.add(task_id)
            for dependency in dependencies.get(task_id, set()):
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in dependencies:
            visit(task_id)

    @staticmethod
    def _assert_running_owner(task: WorkOrderTask, worker_id: str) -> None:
        if task.status != WorkTaskStatus.RUNNING:
            raise ValueError(f"Task {task.task_id} is not running")
        if not worker_id or task.worker_id != worker_id:
            raise ValueError(
                f"Task {task.task_id} is leased to {task.worker_id or '<nobody>'}, not {worker_id}"
            )

    def _initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                create table if not exists work_orders (
                    work_order_id text primary key,
                    status text not null,
                    goal text not null,
                    created_at real not null,
                    updated_at real not null,
                    payload text not null
                );
                create index if not exists idx_work_orders_status_created
                    on work_orders(status, created_at);
                create table if not exists work_order_events (
                    sequence integer primary key autoincrement,
                    event_id text not null unique,
                    work_order_id text not null,
                    type text not null,
                    created_at real not null,
                    task_id text not null default '',
                    actor text not null default '',
                    data text not null default '{}',
                    foreign key(work_order_id) references work_orders(work_order_id)
                );
                create index if not exists idx_work_order_events_order_sequence
                    on work_order_events(work_order_id, sequence);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        conn.execute("pragma journal_mode = wal")
        return conn

    def _transaction(self):
        return _ImmediateTransaction(self._connect())

    def _load_tx(self, conn: sqlite3.Connection, reference: str) -> WorkOrder:
        normalized = reference.strip()
        if not normalized:
            raise ValueError("WorkOrder id is required")
        exact = conn.execute(
            "select payload from work_orders where work_order_id = ?", (normalized,)
        ).fetchone()
        if exact is not None:
            return WorkOrder.from_dict(json.loads(exact["payload"]))
        matches = conn.execute(
            "select payload from work_orders where work_order_id like ? order by created_at desc",
            (f"{normalized}%",),
        ).fetchall()
        if not matches:
            raise KeyError(f"Unknown WorkOrder: {reference}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous WorkOrder prefix: {reference}")
        return WorkOrder.from_dict(json.loads(matches[0]["payload"]))

    def _list_tx(
        self,
        conn: sqlite3.Connection,
        *,
        statuses: tuple[WorkOrderStatus, ...],
        ascending: bool = False,
    ) -> list[WorkOrder]:
        placeholders = ", ".join("?" for _ in statuses)
        direction = "asc" if ascending else "desc"
        rows = conn.execute(
            f"select payload from work_orders where status in ({placeholders}) "
            f"order by created_at {direction}",
            tuple(item.value for item in statuses),
        )
        return [WorkOrder.from_dict(json.loads(row["payload"])) for row in rows]

    def _save_tx(self, conn: sqlite3.Connection, order: WorkOrder) -> None:
        conn.execute(
            """
            update work_orders set status = ?, goal = ?, updated_at = ?, payload = ?
            where work_order_id = ?
            """,
            (
                order.status.value,
                order.goal,
                order.updated_at,
                json.dumps(order.to_dict(), sort_keys=True),
                order.work_order_id,
            ),
        )

    @staticmethod
    def _row(order: WorkOrder) -> tuple[Any, ...]:
        return (
            order.work_order_id,
            order.status.value,
            order.goal,
            order.created_at,
            order.updated_at,
            json.dumps(order.to_dict(), sort_keys=True),
        )

    @staticmethod
    def _append_event_tx(
        conn: sqlite3.Connection,
        work_order_id: str,
        event_type: str,
        *,
        task_id: str = "",
        actor: str = "",
        data: dict[str, Any] | None = None,
    ) -> WorkOrderEvent:
        event = WorkOrderEvent(
            event_id=generate_event_id(),
            work_order_id=work_order_id,
            type=event_type,
            created_at=time.time(),
            task_id=task_id,
            actor=actor,
            data=dict(data or {}),
        )
        conn.execute(
            """
            insert into work_order_events
                (event_id, work_order_id, type, created_at, task_id, actor, data)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.work_order_id,
                event.type,
                event.created_at,
                event.task_id,
                event.actor,
                json.dumps(event.data, sort_keys=True),
            ),
        )
        return event


class _ImmediateTransaction:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("begin immediate")
        return self.conn

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()


def _find_task(order: WorkOrder, task_id: str) -> WorkOrderTask:
    matches = [task for task in order.tasks if task.task_id == task_id]
    if not matches:
        raise KeyError(f"Unknown task {task_id!r} in WorkOrder {order.work_order_id}")
    return matches[0]


def _replace_task(
    tasks: tuple[WorkOrderTask, ...], replacement: WorkOrderTask
) -> tuple[WorkOrderTask, ...]:
    return tuple(replacement if task.task_id == replacement.task_id else task for task in tasks)
