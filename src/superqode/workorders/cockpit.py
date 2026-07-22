"""Read-only terminal cockpit for WorkOrders and worker services."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from .models import WorkOrder, WorkTaskStatus
from .store import WorkOrderStore
from .usage import effective_task_risk
from .worker import list_worker_snapshots


def build_cockpit_snapshot(
    store: WorkOrderStore,
    reference: str,
    *,
    event_limit: int = 8,
    now: float | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe operational view of one WorkOrder."""
    observed_at = time.time() if now is None else now
    order = store.get(reference)
    usage = store.usage_summary(reference)
    policy = store.policy_decision(reference)
    status_counts = Counter(task.status.value for task in order.tasks)
    artifacts = Counter(artifact.kind for artifact in order.artifacts)
    reviews = [artifact for artifact in order.artifacts if artifact.kind == "review"]
    check_results = [artifact for artifact in order.artifacts if artifact.kind == "check_result"]
    conflict_paths = sorted(
        {
            str(path)
            for artifact in order.artifacts
            for path in artifact.metadata.get("conflicts") or ()
        }
    )
    workers = []
    active_worker_ids = {task.worker_id for task in order.tasks if task.worker_id}
    for worker in list_worker_snapshots(store):
        active_here = any(
            item.get("work_order_id") == order.work_order_id for item in worker.active
        )
        owns_lease = any(
            worker.worker_id == worker_id.split("/", maxsplit=1)[0]
            for worker_id in active_worker_ids
        )
        payload = worker.to_dict()
        poll_interval = float(worker.config.get("poll_interval") or 1.0)
        payload["responsive"] = (
            worker.status == "running"
            and observed_at - worker.updated_at <= max(10.0, poll_interval * 4)
        )
        watches_order = worker.reference == order.work_order_id
        watches_global_queue = worker.reference == "" and payload["responsive"]
        if not (active_here or owns_lease or watches_order or watches_global_queue):
            continue
        workers.append(payload)

    tasks: list[dict[str, Any]] = []
    for task in order.tasks:
        lease_remaining = None
        if task.lease_expires_at is not None:
            lease_remaining = max(0.0, task.lease_expires_at - observed_at)
        tasks.append(
            {
                "task_id": task.task_id,
                "title": task.title,
                "role": task.role.value,
                "risk": effective_task_risk(task),
                "status": task.status.value,
                "dependencies": list(task.dependencies),
                "attempts": task.attempts,
                "max_attempts": task.max_attempts,
                "worker_id": task.worker_id,
                "lease_remaining_seconds": lease_remaining,
                "run_id": task.run_id,
                "session_id": task.session_id,
                "error": task.error,
            }
        )

    elapsed = max(0.0, observed_at - order.created_at)
    remaining = None
    if order.budget.max_seconds is not None:
        remaining = max(0.0, float(order.budget.max_seconds) - elapsed)
    latest_candidate = next(
        (
            artifact
            for artifact in reversed(order.artifacts)
            if artifact.kind == "integration_candidate"
        ),
        None,
    )
    return {
        "observed_at": observed_at,
        "work_order_id": order.work_order_id,
        "status": order.status.value,
        "goal": order.goal,
        "repository": order.repository,
        "harness": order.harness,
        "harness_version": order.harness_version,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "elapsed_seconds": elapsed,
        "budget": order.budget.to_dict(),
        "usage": usage.to_dict(),
        "policy": policy.to_dict(),
        "budget_remaining_seconds": remaining,
        "task_counts": dict(status_counts),
        "tasks": tasks,
        "gates": {
            "acceptance_tests": list(order.acceptance_tests),
            "check_results": len(check_results),
            "last_check_passed": bool(check_results)
            and bool(check_results[-1].metadata.get("passed")),
            "reviews": len(reviews),
            "approved_reviews": sum(
                artifact.metadata.get("review_verdict") == "approved" for artifact in reviews
            ),
            "conflicts": conflict_paths,
            "candidate_id": latest_candidate.artifact_id if latest_candidate else "",
            "candidate_digest": latest_candidate.digest if latest_candidate else "",
            "decision": order.decision.to_dict() if order.decision else None,
        },
        "artifact_counts": dict(artifacts),
        "workers": workers,
        "events": [event.to_dict() for event in store.events(reference, limit=event_limit)],
        "error": order.error,
    }


def render_cockpit(snapshot: dict[str, Any]) -> str:
    """Render a compact terminal-native WorkOrder dashboard."""
    width = 88
    lines = [
        f"SuperQode WorkOrder Cockpit  {snapshot['work_order_id']}",
        "=" * width,
        f"{str(snapshot['status']).upper():<18} {_preview(snapshot['goal'], 67)}",
        f"repo  {_preview(snapshot['repository'], 80)}",
        _render_budget(snapshot),
        "",
        "TASKS",
    ]
    tasks = snapshot.get("tasks") or []
    if not tasks:
        lines.append("  - no tasks")
    for task in tasks:
        symbol = _task_symbol(str(task["status"]))
        dependency = ",".join(task.get("dependencies") or ()) or "-"
        worker = task.get("worker_id") or "-"
        lease = task.get("lease_remaining_seconds")
        lease_text = f" lease={_duration(lease)}" if lease is not None else ""
        lines.append(
            f"  {symbol} {task['task_id']:<18} {task['role']:<12} "
            f"{task['status']:<10} risk={task['risk']:<8} "
            f"try={task['attempts']}/{task['max_attempts']} "
            f"after={dependency}"
        )
        if worker != "-" or task.get("run_id") or task.get("error"):
            lines.append(
                f"      worker={worker}{lease_text} run={task.get('run_id') or '-'}"
                + (f" error={_preview(task['error'], 42)}" if task.get("error") else "")
            )

    gates = snapshot.get("gates") or {}
    policy = snapshot.get("policy") or {}
    conflicts = gates.get("conflicts") or []
    lines.extend(
        [
            "",
            "GATES & EVIDENCE",
            f"  checks={gates.get('check_results', 0)} "
            f"reviews={gates.get('approved_reviews', 0)}/{gates.get('reviews', 0)} approved "
            f"conflicts={len(conflicts)} candidate={gates.get('candidate_id') or '-'}",
            f"  policy={'ALLOW' if policy.get('allowed', True) else 'DENY'} "
            f"phase={policy.get('phase') or '-'}"
            + (f" reason={_preview(policy.get('reason'), 58)}" if policy.get("reason") else ""),
            "  artifacts=" + _counter_text(snapshot.get("artifact_counts") or {}),
        ]
    )
    if conflicts:
        lines.append("  conflict paths: " + ", ".join(conflicts))

    lines.extend(["", "WORKERS"])
    workers = snapshot.get("workers") or []
    if not workers:
        lines.append("  - no worker heartbeat")
    for worker in workers:
        health = (
            "live"
            if worker.get("responsive")
            else "stale"
            if worker.get("status") == "running"
            else worker.get("status", "unknown")
        )
        stats = worker.get("stats") or {}
        lines.append(
            f"  {worker['worker_id']:<28} {health:<8} pid={worker.get('pid', 0)} "
            f"active={len(worker.get('active') or [])} "
            f"ok={stats.get('succeeded', 0)} fail={stats.get('failed', 0)}"
        )

    lines.extend(["", "RECENT EVENTS"])
    events = snapshot.get("events") or []
    if not events:
        lines.append("  - no events")
    for event in events:
        age = max(0.0, float(snapshot["observed_at"]) - float(event["created_at"]))
        task = f" [{event['task_id']}]" if event.get("task_id") else ""
        actor = f" @{event['actor']}" if event.get("actor") else ""
        lines.append(f"  {_duration(age):>7} ago  {event['type']}{task}{actor}")
    if snapshot.get("error"):
        lines.extend(["", "ERROR", f"  {snapshot['error']}"])
    return "\n".join(lines)


def _render_budget(snapshot: dict[str, Any]) -> str:
    budget = snapshot.get("budget") or {}
    usage = snapshot.get("usage") or {}
    elapsed = _duration(snapshot.get("elapsed_seconds"))
    remaining = snapshot.get("budget_remaining_seconds")
    time_text = f"elapsed={elapsed}"
    if remaining is not None:
        time_text += f" remaining={_duration(remaining)}"
    limits = [
        f"workers={budget['max_workers']}" if budget.get("max_workers") is not None else "",
        (
            f"cost=${float(usage.get('cost_usd') or 0):.4f}/"
            f"${budget['max_cost_usd']:.2f}"
            if budget.get("max_cost_usd") is not None
            else f"cost=${float(usage.get('cost_usd') or 0):.4f}"
        ),
        (
            f"tokens={int(usage.get('total_tokens') or 0)}/{budget['max_tokens']}"
            if budget.get("max_tokens") is not None
            else f"tokens={int(usage.get('total_tokens') or 0)}"
        ),
        (
            f"tools={int(usage.get('tool_calls') or 0)}/{budget['max_tool_calls']}"
            if budget.get("max_tool_calls") is not None
            else f"tools={int(usage.get('tool_calls') or 0)}"
        ),
    ]
    return "budget " + " ".join([time_text, *(item for item in limits if item)])


def _task_symbol(status: str) -> str:
    return {
        WorkTaskStatus.PENDING.value: "○",
        WorkTaskStatus.RUNNING.value: "●",
        WorkTaskStatus.SUCCEEDED.value: "✓",
        WorkTaskStatus.BLOCKED.value: "!",
        WorkTaskStatus.FAILED.value: "×",
        WorkTaskStatus.CANCELLED.value: "-",
    }.get(status, "?")


def _counter_text(values: dict[str, Any]) -> str:
    if not values:
        return "-"
    return " ".join(f"{key}:{value}" for key, value in sorted(values.items()))


def _duration(value: Any) -> str:
    seconds = max(0, int(float(value or 0)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _preview(value: Any, limit: int) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"
