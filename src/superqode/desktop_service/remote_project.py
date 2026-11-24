"""Bounded project projections for the private companion, without management data."""

from pathlib import PurePosixPath


def fields(record, names):
    return {
        key: value[:1000] if isinstance(value, str) else value
        for key in names
        if (value := record.get(key)) is not None
    }


def project_path(value):
    if not isinstance(value, str) or not value or len(value) > 1000:
        raise ValueError("Choose a project file")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(c in value for c in "\0\r\n\\")
        or any(p in {"..", ".git", ".ssh", ".aws"} or p.startswith(".env") for p in path.parts)
        or value.startswith(".superqode/checkpoints/")
    ):
        raise ValueError("Choose a non-sensitive relative file inside this project")
    return value


def context_paths(value):
    if not isinstance(value, list) or len(value) > 10:
        raise ValueError("Attach up to ten project text files")
    return [project_path(path) for path in value]


def queue_snapshot(value):
    from .remote_editing import revision

    return {
        "revision": revision(value),
        "running": value.get("running") is True,
        "truncated": len(value.get("items", [])) > 100,
        "items": [
            {
                **{k: row.get(k, "") for k in ("id", "state", "job", "error")},
                "request": {
                    k: str(row.get("request", {}).get(k, ""))[:2000]
                    for k in ("prompt", "harness", "provider", "model", "interaction_mode")
                },
                "prompt_truncated": len(str(row.get("request", {}).get("prompt", ""))) > 2000,
            }
            for row in value.get("items", [])[:100]
        ],
    }


def checkpoint_snapshot(value):
    items = []
    for item in value.get("items", [])[:50]:
        changes = []
        for change in item.get("changes", []):
            try:
                project_path(change.get("path"))
            except ValueError:
                continue
            changes.append({k: change.get(k) for k in ("path", "change_type")})
        items.append(
            {
                **fields(item, ("id", "name", "timestamp", "sealed")),
                "changes": changes[:500],
                "changes_truncated": len(changes) > 500,
            }
        )
    from .remote_editing import revision

    return {
        "items": items,
        "truncated": len(value.get("items", [])) > 50,
        "revision": revision(value),
        "can_undo": value.get("can_undo") is True,
        "can_redo": value.get("can_redo") is True,
    }


def workorder_snapshot(value):
    # Stored artifacts/events can contain worker internals. Expose cockpit fields,
    # never worker configuration, raw event payloads or arbitrary artifact metadata.
    return {
        "items": [
            {
                **fields(
                    item,
                    (
                        "work_order_id",
                        "status",
                        "goal",
                        "harness",
                        "elapsed_seconds",
                        "budget",
                        "usage",
                        "budget_remaining_seconds",
                        "task_counts",
                        "error",
                    ),
                ),
                "tasks": [
                    fields(
                        task,
                        (
                            "task_id",
                            "title",
                            "role",
                            "worker_id",
                            "status",
                            "error",
                            "lease_remaining_seconds",
                            "attempts",
                            "max_attempts",
                        ),
                    )
                    for task in item.get("tasks", [])[:50]
                ],
                "tasks_truncated": len(item.get("tasks", [])) > 50,
                "workers": [
                    fields(worker, ("worker_id", "status", "responsive", "updated_at"))
                    for worker in item.get("workers", [])[:50]
                ],
                "workers_truncated": len(item.get("workers", [])) > 50,
                "gates": {
                    k: item.get("gates", {}).get(k)
                    for k in (
                        "check_results",
                        "last_check_passed",
                        "reviews",
                        "approved_reviews",
                        "conflicts",
                    )
                },
            }
            for item in value.get("items", [])[:25]
        ],
        "truncated": len(value.get("items", [])) > 25,
    }


def turn_changes_snapshot(value):
    """Project per-turn file change summaries without sensitive paths."""
    files = []
    excluded = 0
    for row in value.get("files", [])[:200]:
        try:
            safe_path = project_path(row.get("path"))
        except ValueError:
            excluded += 1
            continue
        files.append(
            {
                "path": safe_path,
                "change": str(row.get("change", "modified"))[:32],
                "added": row.get("added"),
                "removed": row.get("removed"),
                "binary": row.get("binary") is True,
            }
        )
    conflicts = []
    for path in value.get("conflicts", [])[:50]:
        try:
            conflicts.append(project_path(path))
        except ValueError:
            continue
    result = {
        **fields(
            value,
            (
                "available",
                "reason",
                "checkpoint",
                "live",
                "running",
                "file_count",
                "truncated",
                "added",
                "removed",
                "can_restore",
                "restore_reason",
                "later_turns",
            ),
        ),
        "files": files,
        "conflicts": conflicts,
    }
    if excluded:
        result["excluded_count"] = excluded
        result["file_count"] = max(0, int(result.get("file_count", len(files))) - excluded)
    return result


def factory_list_snapshot(value):
    """Bounded read-only Factory runs list without filesystem paths."""
    runs = value.get("runs", [])
    revisions = value.get("revisions", [])
    return {
        "runs": [
            fields(row, ("id", "goal", "status", "factory_digest"))
            for row in runs[:50]
        ],
        "runs_truncated": len(runs) > 50,
        "revision_count": len(revisions),
    }


def factory_run_snapshot(value):
    """Bounded read-only Factory run inspection including SuperGauge evidence."""
    order = value.get("work_order") or {}
    meta = order.get("metadata") or {}
    safe_meta = {}
    if isinstance(meta.get("factory"), dict):
        safe_meta["factory"] = fields(meta["factory"], ("snapshot_digest", "name"))
    if isinstance(meta.get("factory_verification"), dict):
        safe_meta["factory_verification"] = fields(
            meta["factory_verification"],
            ("state", "sandbox", "isolation_applied", "artifact_id"),
        )
    tasks = []
    for task in (order.get("tasks") or [])[:50]:
        tmeta = task.get("metadata") or {}
        tasks.append(
            {
                **fields(task, ("task_id", "title", "role", "status", "error")),
                "metadata": {
                    k: tmeta.get(k)
                    for k in ("human_gate", "gate_digest", "gate_approval", "factory_stage")
                    if tmeta.get(k) is not None
                },
            }
        )
    evidence = []
    for item in (value.get("evidence") or [])[:25]:
        content = item.get("content")
        safe_content = content[:16000] if isinstance(content, str) else ""
        evidence.append(
            {
                **fields(item, ("id", "kind", "task_id")),
                "content": safe_content,
                "truncated": bool(item.get("truncated"))
                or (isinstance(content, str) and len(content) > 16000),
            }
        )
    diff = value.get("candidate_diff") or ""
    if not isinstance(diff, str):
        diff = ""
    diff_truncated = bool(value.get("diff_truncated")) or len(diff) > 100000
    cockpit = value.get("cockpit") or {}
    return {
        "work_order": {
            **fields(order, ("work_order_id", "goal", "status", "error", "created_at", "updated_at")),
            "metadata": safe_meta,
            "tasks": tasks,
            "tasks_truncated": len(order.get("tasks") or []) > 50,
        },
        "evidence": evidence,
        "evidence_truncated": len(value.get("evidence") or []) > 25,
        "candidate_diff": diff[:100000],
        "diff_truncated": diff_truncated,
        "candidate_id": str(value.get("candidate_id") or "")[:200],
        "candidate_digest": str(value.get("candidate_digest") or "")[:200],
        "cockpit": fields(
            cockpit,
            ("status", "elapsed_seconds", "task_counts", "budget", "usage"),
        ),
    }


def factory_trace_snapshot(value):
    """Bounded acceptance check and requirement coverage trace."""
    checks = value.get("application_checks") or []
    reqs = value.get("requirements") or []
    summary = value.get("summary") or {}
    return {
        **fields(
            value,
            (
                "format",
                "run",
                "snapshot_digest",
                "verification_bound_to_current",
                "requirements_declared",
                "covered",
                "release_authorized",
            ),
        ),
        "missing_evidence": [str(m)[:200] for m in (value.get("missing_evidence") or [])[:25]],
        "summary": {
            "checks": summary.get("checks") or {},
            "requirements": summary.get("requirements") or {},
        },
        "application_checks": [
            {
                **fields(row, ("check", "category", "status", "reason")),
                "cases": [str(c)[:200] for c in (row.get("cases") or [])[:50]],
                "failed_cases": [str(c)[:200] for c in (row.get("failed_cases") or [])[:50]],
            }
            for row in checks[:100]
        ],
        "requirements": [
            fields(row, ("id", "description", "status"))
            for row in reqs[:50]
        ],
    }
