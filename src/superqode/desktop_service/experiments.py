"""Read-only suite diagnostics used before native experiment execution."""

from pathlib import Path
import hashlib
import shlex

from superqode.harness.eval import eval_pack_path, filter_eval_tasks, load_eval_tasks
from superqode.harness.loader import load_harness_spec


def candidate_paths(request, root):
    values = request.get("variants", [])
    if (
        not isinstance(values, list)
        or len(values) > 8
        or any(not isinstance(v, str) for v in values)
    ):
        raise ValueError("Choose up to eight candidate HarnessSpec files")
    legacy = request.get("variant")
    if legacy is not None and not isinstance(legacy, str):
        raise ValueError("Choose a candidate HarnessSpec file")
    values = [*values, *([legacy] if legacy else [])]
    if len(values) > 8:
        raise ValueError("Choose up to eight candidate HarnessSpec files")
    paths = []
    for value in values:
        path = Path(value).expanduser()
        path = (root / path).resolve() if not path.is_absolute() else path.resolve()
        load_harness_spec(path)
        if path not in paths:
            paths.append(path)
    return paths


def inspect_suite(root, params):
    value = str(params.get("tasks") or "")
    path = eval_pack_path(str(root / value) if (root / value).exists() else value)
    if path.stat().st_size > 1_000_000:
        raise ValueError("Choose a suite smaller than 1 MB")
    data = load_eval_tasks(path)
    tasks = filter_eval_tasks(data["tasks"], params.get("split") or "all")
    smoke = [
        str(task["id"])
        for task in data["tasks"]
        if (task.get("evaluator") or {}).get(
            "type", "contains" if task.get("expect_contains") else "non_empty"
        )
        == "non_empty"
    ]
    candidates = candidate_paths(params, root)
    suite_candidates = [
        row["spec"] for row in data["variants"] if isinstance(row, dict) and row.get("spec")
    ]
    for value in suite_candidates:
        path = Path(value).expanduser()
        load_harness_spec(path if path.is_absolute() else root / path)
    warnings = []
    if suite_candidates:
        warnings.append(
            f"The suite declares {len(suite_candidates)} additional candidate configuration(s); live evaluation also executes these."
        )
    if smoke:
        warnings.append(
            "Smoke-only tasks do not establish quality or authorize candidate adoption."
        )
    if not data["split_counts"]["held-out"] or not data["split_counts"]["held-in"]:
        warnings.append("Optimization needs both held-in training and sealed held-out tasks.")
    if not tasks:
        warnings.append("No tasks match the selected split.")
    repository_checks = []
    for task in tasks:
        grader = task.get("evaluator") or {}
        if grader.get("type") == "repository":
            repository_checks.append(
                {
                    "id": str(task["id"]),
                    "commands": [shlex.join(c["argv"]) for c in grader.get("commands", [])],
                    "file_assertions": [f["path"] for f in grader.get("files", [])],
                    "require_changes": grader.get("require_changes", False),
                }
            )
    return {
        "tasks_hash": data["tasks_hash"],
        "task_count": len(tasks),
        "split_counts": data["split_counts"],
        "split": params.get("split") or "all",
        "candidate_count": len(candidates) + len(suite_candidates),
        "smoke_task_ids": smoke,
        "warnings": warnings,
        "repository_checks": repository_checks,
        "optimization_ready": bool(
            data["split_counts"]["held-in"] and data["split_counts"]["held-out"] and not smoke
        ),
    }


def reviewed_suite(root, params):
    """Pin suite bytes so later edits cannot change reviewed verifier commands."""
    inspection = inspect_suite(root, params)
    value = str(params.get("tasks") or "")
    path = eval_pack_path(str(root / value) if (root / value).exists() else value)
    raw = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if digest != inspection["tasks_hash"]:
        raise ValueError("The evaluation suite changed. Review it again before starting.")
    expected = params.get("tasks_hash")
    if expected and expected != digest:
        raise ValueError(
            "The evaluation suite changed since review. Check its verifier commands again."
        )
    if params.get("live") is True and inspection["repository_checks"] and expected != digest:
        raise ValueError("Review the repository verifier commands before starting this live suite.")
    return raw.decode("utf-8")
