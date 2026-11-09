"""Per-turn file change summaries for the desktop transcript.

Read-only. Uses the checkpoint recorded at the start of a coding turn. A
finished turn reports its sealed changes; a running turn compares the
baseline with the working tree without sealing or modifying the checkpoint.
"""

from __future__ import annotations

import difflib
import json
import subprocess

TERMINAL = {"completed", "failed", "cancelled", "interrupted", "regressed"}
MAX_FILES = 200


def _unavailable(reason: str, **extra) -> dict:
    return {"available": False, "reason": reason, "files": [], **extra}


def _baseline_checkpoint(service, job_id: str) -> str | None:
    rows = service._all(
        "SELECT payload FROM events WHERE job=? AND json_extract(payload,'$.type')='checkpoint' ORDER BY seq",
        (job_id,),
    )
    for row in rows:
        data = json.loads(row["payload"]).get("data") or {}
        if data.get("phase") == "baseline" and data.get("id"):
            return str(data["id"])
    return None


def _line_counts(before, after) -> tuple[int | None, int | None]:
    old = (before.content if before else None) or b""
    new = (after.content if after else None) or b""
    if b"\0" in old or b"\0" in new:
        return None, None
    added = removed = 0
    for line in difflib.unified_diff(
        old.decode("utf-8", errors="replace").splitlines(),
        new.decode("utf-8", errors="replace").splitlines(),
        lineterm="",
        n=0,
    ):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _change(before, after) -> str:
    if before is None or before.content is None:
        return "added"
    if after is None or after.content is None:
        return "deleted"
    return "modified"


def summary(service, root, job_id: str) -> dict:
    rows = service._all("SELECT project,kind,status FROM jobs WHERE id=?", (job_id,))
    if not rows or rows[0]["kind"] != "task":
        return _unavailable("Select a coding turn to see its file changes.")
    status = rows[0]["status"]
    running = status not in TERMINAL or job_id in service.processes
    checkpoint = _baseline_checkpoint(service, job_id)
    if not checkpoint:
        return _unavailable("This turn has no local checkpoint.", running=running)
    try:
        from .checkpoints import manager_for

        manager = manager_for(root)
    except (OSError, ValueError) as exc:
        return _unavailable(str(exc), running=running)
    task = manager._tasks.get(checkpoint)
    if task is None:
        return _unavailable("The checkpoint for this turn is no longer stored.", running=running)

    pairs = []
    if task.finished:
        for name in sorted(task.after):
            pairs.append((name, task.before.get(name), task.after[name]))
    elif running:
        try:
            names = task._changed_paths()
            names.update(
                name
                for name in task._git("diff", "--cached", "--name-only", "-z").decode().split("\0")
                if name
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            names = set()
        for name in sorted(names):
            if name.startswith(".superqode/checkpoints/"):
                continue
            try:
                before, after = task._baseline(name), task._read(name)
            except (OSError, ValueError, subprocess.SubprocessError):
                continue
            if before is None or before == after:
                continue
            pairs.append((name, before, after))
    else:
        return _unavailable(
            "This turn stopped before its checkpoint was sealed. Review project changes instead.",
            running=False,
        )

    files = []
    total_added = total_removed = 0
    for name, before, after in pairs[:MAX_FILES]:
        added, removed = _line_counts(before, after)
        total_added += added or 0
        total_removed += removed or 0
        files.append(
            {
                "path": name,
                "change": _change(before, after),
                "added": added,
                "removed": removed,
                "binary": added is None,
            }
        )

    result = {
        "available": True,
        "checkpoint": checkpoint,
        "live": not task.finished,
        "running": running,
        "files": files,
        "file_count": len(pairs),
        "truncated": len(pairs) > MAX_FILES,
        "added": total_added,
        "removed": total_removed,
        "can_restore": False,
        "later_turns": 0,
        "conflicts": [],
    }
    if not task.finished or running:
        result["restore_reason"] = "Wait for the turn to finish."
        return result
    index = next((i for i, cp in enumerate(manager._checkpoints) if cp.id == checkpoint), -1)
    result["later_turns"] = max(0, len(manager._checkpoints) - index - 1) if index >= 0 else 0
    if index < 0 or index > manager._current_index:
        result["restore_reason"] = "This turn was already undone."
        return result
    if not task.after:
        result["restore_reason"] = "This turn did not change files."
        return result
    conflicts = []
    for name, expected in task.after.items():
        try:
            if task._read(name) != expected:
                conflicts.append(name)
        except (OSError, ValueError):
            conflicts.append(name)
    result["conflicts"] = sorted(conflicts)
    if conflicts:
        result["restore_reason"] = (
            "Some files changed after this turn. Undo would overwrite newer edits, so it is blocked."
        )
        return result
    result["can_restore"] = True
    return result
