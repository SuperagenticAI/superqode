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
    return {
        "running": value.get("running") is True,
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
    return {"items": items}


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
