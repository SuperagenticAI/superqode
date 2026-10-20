"""Native checkpoint actions reuse the terminal's guarded durable UndoManager."""

from dataclasses import asdict
from pathlib import Path


def manager_for(root):
    from superqode.undo_manager import UndoManager

    manager = UndoManager(root)
    if not manager.initialize() or manager._git_root != root:
        raise ValueError("Open the Git repository root to use task checkpoints")
    if not (root / ".superqode/checkpoints").resolve().is_relative_to(root):
        raise ValueError("Checkpoint storage must stay inside the project")
    return manager


def begin_task(root, title):
    from superqode.app.task_changes import TaskChanges

    manager = manager_for(Path(root))
    task = TaskChanges(Path(root)).capture()
    identity = manager.register_task(task, title[:120])
    return manager, task, identity


def finish_task(capture):
    manager, task, identity = capture
    task.finish([])
    manager.seal_task(task)
    return identity


def action(root, method, params):
    manager = manager_for(root)
    if method == "checkpoints.list":
        rows = []
        for checkpoint in manager.get_checkpoints(50):
            row = asdict(checkpoint)
            row["timestamp"] = checkpoint.timestamp.isoformat()
            row["sealed"] = manager._tasks[checkpoint.id].finished
            row["changes"] = (
                [asdict(change) for change in manager.get_changes_since(checkpoint.id)]
                if row["sealed"]
                else []
            )
            rows.append(row)
        current = manager.get_current_checkpoint()
        return {
            "items": rows,
            "can_undo": bool(
                current and manager._tasks[current.id].finished and manager._tasks[current.id].after
            ),
            "can_redo": bool(
                manager._redo_stack and manager._tasks[manager._redo_stack[-1].id].finished
            ),
        }
    if method == "checkpoints.diff":
        before, after = manager.get_file_diff(str(params["id"]), str(params["path"]))
        import difflib

        return {
            "diff": "".join(
                difflib.unified_diff(
                    before.splitlines(True),
                    after.splitlines(True),
                    fromfile="checkpoint/" + params["path"],
                    tofile="working/" + params["path"],
                )
            )[:1_000_000]
        }
    if method in {"checkpoints.undo", "checkpoints.redo", "checkpoints.restore"}:
        checkpoint = (
            manager.get_current_checkpoint()
            if method == "checkpoints.undo"
            else (manager._redo_stack[-1] if manager._redo_stack else None)
            if method == "checkpoints.redo"
            else next((cp for cp in manager.get_checkpoints(50) if cp.id == params.get("id")), None)
        )
        if checkpoint and not manager._tasks[checkpoint.id].finished:
            raise ValueError(
                "This interrupted checkpoint has no sealed after-state; review changes manually"
            )
    if method == "checkpoints.undo":
        result = manager.undo()
    elif method == "checkpoints.redo":
        result = manager.redo()
    elif method == "checkpoints.restore":
        result = manager.restore(str(params["id"]))
    else:
        raise ValueError("Unknown checkpoint action")
    if not result:
        raise ValueError(manager.last_error or "No eligible checkpoint; files were not restored")
    return {"ok": True}
