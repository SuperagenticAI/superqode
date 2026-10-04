"""Bounded, permission-aware data for the WorkOrder inspector."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from superqode.governance import governance_scope, load_governance
from superqode.systemone.state import redact_evidence
from .cockpit import build_cockpit_snapshot
from .evidence import dependency_catalog, read_workorder_evidence
from .store import WorkOrderStore


def _bounded(value, depth=0):
    if depth > 6:
        return "[preview depth limit]"
    if isinstance(value, str):
        return value[:4000] + (" [truncated]" if len(value) > 4000 else "")
    if isinstance(value, dict):
        return {str(k): _bounded(v, depth + 1) for k, v in list(value.items())[:64]}
    if isinstance(value, (list, tuple)):
        return [_bounded(v, depth + 1) for v in value[:64]]
    return value


def recovery_state(record, task, now):
    """Describe availability, never promise replay solely from a safe flag."""
    if record["status"] == "completed":
        return "reuse admitted" if record.get("reuse_count") else "committed"
    if record["status"] == "retry":
        return "retry authorized"
    if (
        record["status"] == "intent"
        and task
        and task.status.value == "running"
        and record["attempt"] == task.attempts
        and (task.lease_expires_at or 0) > now
    ):
        return "in flight"
    return "retry eligible" if record["replay_safe"] else "reconcile needed"


def inspect_work_order(path, reference, *, task_id=""):
    if not Path(path).is_file():
        raise FileNotFoundError("WorkOrder store does not exist")
    store = WorkOrderStore(path)
    order = store.get(reference)
    snapshot = build_cockpit_snapshot(store, reference)
    task = next((t for t in order.tasks if t.task_id == task_id), None)
    if task is None:
        task = next(
            (t for t in order.tasks if t.dependencies), order.tasks[0] if order.tasks else None
        )
    root = Path(order.repository)
    if task:
        workspace = next(
            (
                a
                for a in reversed(order.artifacts)
                if a.kind == "workspace" and a.task_id == task.task_id
            ),
            None,
        )
        if workspace and Path(workspace.path).is_dir():
            root = Path(workspace.path)
    with governance_scope(load_governance(root, work_order=order)):
        evidence = dependency_catalog(order, task, root) if task else []
    tasks = {t.task_id: t for t in order.tasks}
    records = store.invocation_records(reference)
    snapshot.update(
        selected_task=task.task_id if task else "",
        workspace=str(root),
        evidence=evidence[:128],
        evidence_count=len(evidence),
        recovery=[
            {**r, "state": recovery_state(r, tasks.get(r["task_id"]), snapshot["observed_at"])}
            for r in records
        ],
        review=[
            _bounded({**redact_evidence(a.to_dict()), "content_truncated": len(a.content) > 4000})
            for a in order.artifacts
            if a.kind in {"check_result", "review", "integration_candidate", "patch"}
        ][-128:],
    )
    return redact_evidence(snapshot)


def read_inspected_evidence(path, reference, task_id, evidence_reference, *, offset=0):
    snapshot = inspect_work_order(path, reference, task_id=task_id)
    store = WorkOrderStore(path)
    order = store.get(reference)
    root = Path(snapshot["workspace"])
    with governance_scope(load_governance(root, work_order=order)):
        return read_workorder_evidence(
            SimpleNamespace(store=store, work_order_id=order.work_order_id, task_id=task_id),
            evidence_reference,
            root,
            offset=offset,
            limit=4000,
        )


def inspected_diff(path, reference):
    order = WorkOrderStore(path).get(reference)
    candidate = next(
        (a for a in reversed(order.artifacts) if a.kind == "integration_candidate"), None
    )
    if candidate is None:
        raise LookupError("Prepare an integration candidate before opening its diff")
    if hashlib.sha256(candidate.content.encode()).hexdigest() != candidate.digest:
        raise ValueError("Candidate content failed its integrity check")
    text = redact_evidence(candidate.content)
    complete = len(text) <= 64000 and text == candidate.content
    return (
        text[:64000]
        + (
            "\n[Preview truncated or redacted; inspect the full candidate with :work diff and approve through the CLI]"
            if not complete
            else ""
        ),
        candidate.digest,
        candidate.artifact_id,
        complete,
    )
