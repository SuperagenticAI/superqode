"""
SuperQode Undo Manager - Guarded Task Undo/Redo.

Retains bounded task snapshots without changing Git's index or commits.
Restoration refuses to overwrite subsequent developer edits.

Features:
- Automatic checkpoint creation before agent operations
- Named checkpoints for easier navigation
- Restore specific files or entire state
- View diff between checkpoints
- Stack-based undo/redo

Usage:
    from superqode.undo_manager import UndoManager

    undo = UndoManager()

    # Before agent operation
    checkpoint_id = undo.create_checkpoint("Before edit")

    # After operation, if user wants to undo
    undo.undo()

    # Or restore a specific checkpoint
    undo.restore(checkpoint_id)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class Checkpoint:
    """A checkpoint representing a point in time."""

    id: str  # Task snapshot identifier
    name: str
    timestamp: datetime
    message: str = ""
    files_changed: List[str] = field(default_factory=list)
    is_stash: bool = False


@dataclass
class FileChange:
    """A file change between checkpoints."""

    path: str
    change_type: str  # "added", "modified", "deleted"
    old_content: str = ""
    new_content: str = ""


# ============================================================================
# UNDO MANAGER
# ============================================================================


class UndoManager:
    """Guarded task snapshots with durable undo and redo; Git stays read-only."""

    def __init__(self, working_dir: Optional[Path] = None):
        self.working_dir = (working_dir or Path.cwd()).resolve()
        self._checkpoints: List[Checkpoint] = []
        self._tasks = {}
        self._redo_stack: List[Checkpoint] = []
        self._current_index = -1
        self._initialized = False
        self.last_error = ""
        self._directory = self.working_dir / ".superqode" / "checkpoints"

    def _run_git(self, args, capture_output=True):
        return subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=self.working_dir,
            capture_output=capture_output,
            text=True,
            timeout=10,
        )

    def initialize(self) -> bool:
        if self._initialized:
            return True
        try:
            if self._run_git(["rev-parse", "--git-dir"]).returncode:
                return False
            self._git_root = Path(
                self._run_git(["rev-parse", "--show-toplevel"]).stdout.strip()
            ).resolve()
            self._initialized = True
            self._load()
            return True
        except (OSError, ValueError, subprocess.SubprocessError):
            return False

    def register_task(self, task, name="Agent task", message=""):
        if not task.available:
            return None
        checkpoint = Checkpoint(task.id, name, datetime.now(), message)
        previous = (
            self._checkpoints[:],
            self._tasks.copy(),
            self._redo_stack[:],
            self._current_index,
        )
        self._checkpoints = self._checkpoints[: self._current_index + 1]
        self._checkpoints.append(checkpoint)
        self._tasks[checkpoint.id] = task
        self._redo_stack.clear()
        self._current_index = len(self._checkpoints) - 1
        try:
            self._save()
        except (OSError, ValueError):
            self._checkpoints, self._tasks, self._redo_stack, self._current_index = previous
            raise
        return checkpoint.id

    def create_checkpoint(self, name="", message=""):
        from .app.task_changes import TaskChanges

        if not self.initialize():
            return None
        task = TaskChanges(self.working_dir).capture()
        return self.register_task(task, name or "Checkpoint", message)

    def create_commit_checkpoint(self, name="", message=""):
        # Compatibility API: checkpoints never create commits or stage files.
        return self.create_checkpoint(name, message)

    def seal_task(self, task):
        if task.id in self._tasks:
            checkpoint = next(cp for cp in self._checkpoints if cp.id == task.id)
            checkpoint.files_changed = list(task.after)
            self._save()

    def _target(self, checkpoint):
        task = self._tasks.get(checkpoint.id)
        if task is not None and not task.finished:
            task.finish([])
            self.seal_task(task)
        return task

    def _apply(self, task, *, redo=False, names=None):
        expected = task.before if redo else task.after
        target = task.after if redo else task.before
        paths = list(names if names is not None else task.after)
        self.last_error = ""
        try:
            if not paths:
                return False
            # Validate the whole operation before changing any file.
            for name in paths:
                if expected.get(name) is None or target.get(name) is None:
                    raise ValueError("A file has no restorable baseline.")
                if task._read(name) != expected[name]:
                    raise ValueError(
                        f"{name} changed after the task. Review the newer edits before undo or redo."
                    )
            changed = []
            try:
                for name in paths:
                    self._write(task, name, target[name])
                    changed.append(name)
            except OSError:
                # Every original state is in the durable checkpoint even if
                # an I/O failure prevents rollback from finishing.
                for name in reversed(changed):
                    self._write(task, name, expected[name])
                raise
            return True
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            return False

    @staticmethod
    def _write(task, name, state):
        import tempfile

        path = task._path(name)
        if state.content is None:
            if path.exists():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".superqode-restore-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(state.content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, state.mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def undo(self):
        while self.can_undo():
            checkpoint = self._checkpoints[self._current_index]
            result = self._transition(checkpoint)
            if result or self.last_error:
                return result
            # A completed turn without file changes is not an undo operation.
            self._current_index -= 1
        return None

    def redo(self):
        if not self._redo_stack:
            return None
        checkpoint = self._redo_stack[-1]
        return self._transition(checkpoint, redo=True)

    def _transition(self, checkpoint, *, redo=False):
        previous_index, previous_redo = self._current_index, self._redo_stack[:]
        try:
            task = self._target(checkpoint)
            # Detect unavailable storage before touching the working tree.
            self._save()
        except (OSError, ValueError) as exc:
            self.last_error = f"Checkpoint could not be saved. Files were unchanged: {exc}"
            return None
        if task is None:
            self.last_error = "This checkpoint has no restorable task baseline."
            return None
        if not self._apply(task, redo=redo):
            return None
        if redo:
            self._redo_stack.pop()
            self._current_index += 1
        else:
            self._redo_stack.append(checkpoint)
            self._current_index -= 1
        try:
            self._save("redo" if redo else "undo", checkpoint.id)
        except (OSError, ValueError):
            rolled_back = self._apply(task, redo=not redo)
            self._current_index, self._redo_stack = previous_index, previous_redo
            self.last_error = (
                "Checkpoint could not be saved. The restoration was rolled back."
                if rolled_back
                else "Checkpoint storage failed during restoration. Review files against the retained checkpoint."
            )
            return None
        return checkpoint

    def restore(self, checkpoint_id):
        for index, checkpoint in enumerate(self._checkpoints):
            if checkpoint.id == checkpoint_id:
                previous_index, previous_redo = self._current_index, self._redo_stack[:]
                try:
                    task = self._target(checkpoint)
                    self._save()
                except (OSError, ValueError) as exc:
                    self.last_error = f"Checkpoint could not be saved. Files were unchanged: {exc}"
                    return False
                if not task or not self._apply(task):
                    return False
                self._current_index = index - 1
                self._redo_stack = [checkpoint]
                try:
                    self._save("restore", checkpoint_id)
                    return True
                except (OSError, ValueError):
                    rolled_back = self._apply(task, redo=True)
                    self._current_index, self._redo_stack = previous_index, previous_redo
                    self.last_error = (
                        "Checkpoint could not be saved. The restoration was rolled back."
                        if rolled_back
                        else "Checkpoint storage failed during restoration. Review files against the retained checkpoint."
                    )
                    return False
        return False

    def restore_file(self, checkpoint_id, file_path):
        checkpoint = next((cp for cp in self._checkpoints if cp.id == checkpoint_id), None)
        try:
            task = self._target(checkpoint) if checkpoint else None
            if task is None or file_path not in task.after:
                return False
            self._save()
        except (OSError, ValueError) as exc:
            self.last_error = f"Checkpoint could not be saved. Files were unchanged: {exc}"
            return False
        if not self._apply(task, names=[file_path]):
            return False
        previous_after = task.after.pop(file_path)
        previous_undone = task.undone.copy()
        previous_files = checkpoint.files_changed[:]
        task.undone.add(file_path)
        checkpoint.files_changed = list(task.after)
        try:
            self._save("restore-file", checkpoint_id)
            return True
        except (OSError, ValueError):
            task.after[file_path] = previous_after
            task.undone = previous_undone
            checkpoint.files_changed = previous_files
            rolled_back = self._apply(task, redo=True, names=[file_path])
            self.last_error = (
                "Checkpoint could not be saved. The restoration was rolled back."
                if rolled_back
                else "Checkpoint storage failed during restoration. Review files against the retained checkpoint."
            )
            return False

    def get_checkpoints(self, limit=20):
        return self._checkpoints[-limit:]

    def get_current_checkpoint(self):
        return self._checkpoints[self._current_index] if self.can_undo() else None

    def can_undo(self):
        return self._current_index >= 0

    def can_redo(self):
        return bool(self._redo_stack)

    def get_changes_since(self, checkpoint_id):
        checkpoint = next((cp for cp in self._checkpoints if cp.id == checkpoint_id), None)
        task = self._target(checkpoint) if checkpoint else None
        if task is None:
            return []
        return [
            FileChange(
                name,
                "added"
                if task.before[name].content is None
                else "deleted"
                if state.content is None
                else "modified",
            )
            for name, state in task.after.items()
        ]

    def get_file_diff(self, checkpoint_id, file_path):
        task = self._tasks.get(checkpoint_id)
        if task is None:
            return "", ""
        before = task._baseline(file_path)
        after = task._read(file_path)
        return (
            (before.content or b"").decode(errors="replace") if before else "",
            (after.content or b"").decode(errors="replace"),
        )

    def clear_old_checkpoints(self, keep_count=50):
        keep_count = max(1, keep_count)
        removed = max(0, len(self._checkpoints) - keep_count)
        self._checkpoints = self._checkpoints[removed:]
        self._current_index = max(-1, self._current_index - removed)
        self._tasks = {cp.id: self._tasks[cp.id] for cp in self._checkpoints}
        self._redo_stack = [cp for cp in self._redo_stack if cp.id in self._tasks]
        self._save()
        return removed

    def _save(self, action="", checkpoint_id=""):
        import base64
        import json
        import tempfile

        if self._directory.resolve() != self._directory.absolute():
            raise ValueError("Checkpoint storage must not be a symbolic link.")
        self._directory.mkdir(parents=True, exist_ok=True)

        def state(value):
            return (
                None
                if value is None
                else {
                    "content": base64.b64encode(value.content).decode()
                    if value.content is not None
                    else None,
                    "mode": value.mode,
                }
            )

        records = []
        for checkpoint in self._checkpoints:
            task = self._tasks[checkpoint.id]
            records.append(
                {
                    "id": checkpoint.id,
                    "name": checkpoint.name,
                    "timestamp": checkpoint.timestamp.isoformat(),
                    "message": checkpoint.message,
                    "root": str(task.root),
                    "index": task.index,
                    "before": {name: state(value) for name, value in task.before.items()},
                    "after": {name: state(value) for name, value in task.after.items()},
                    "finished": task.finished,
                    "undone": sorted(task.undone),
                }
            )
        data = {
            "checkpoints": records,
            "current_index": self._current_index,
            "redo": [cp.id for cp in self._redo_stack],
        }
        # Keep the manifest below the read limit, including base64 overhead.
        # Retention always preserves the newest task and its redo state.
        removed = 0
        while len(records) > 1 and (
            len(records) > 50 or len(json.dumps(data).encode()) > 60_000_000
        ):
            records.pop(0)
            removed += 1
            data["current_index"] = max(-1, data["current_index"] - 1)
            retained = {row["id"] for row in records}
            data["redo"] = [key for key in data["redo"] if key in retained]
        payload = json.dumps(data)
        if len(payload.encode()) > 64_000_000:
            raise ValueError("This task exceeds checkpoint storage limits.")
        descriptor, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=self._directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._directory / "state.json")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if removed:
            self._checkpoints = self._checkpoints[removed:]
            self._current_index = data["current_index"]
            self._tasks = {cp.id: self._tasks[cp.id] for cp in self._checkpoints}
            self._redo_stack = [cp for cp in self._redo_stack if cp.id in self._tasks]
        if action:
            try:
                descriptor = os.open(
                    self._directory / "actions.jsonl",
                    os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "action": action,
                                "checkpoint": checkpoint_id,
                                "timestamp": datetime.now().isoformat(),
                            }
                        )
                        + "\n"
                    )

            except OSError:
                import logging

                logging.getLogger("superqode.undo").warning(
                    "Checkpoint action journal unavailable; checkpoint state retained."
                )

    def _load(self):
        import base64
        import json
        from .app.task_changes import FileState, TaskChanges

        path = self._directory / "state.json"
        if (
            path.resolve() != path.absolute()
            or not path.exists()
            or path.stat().st_size > 64_000_000
        ):
            return
        try:
            data = json.loads(path.read_text())

            def state(value):
                return (
                    None
                    if value is None
                    else FileState(
                        base64.b64decode(value["content"])
                        if value["content"] is not None
                        else None,
                        value["mode"],
                    )
                )

            for row in data["checkpoints"]:
                task = TaskChanges(self.working_dir)
                task.root = Path(row.get("root", str(self.working_dir))).resolve()
                if task.root != self._git_root:
                    raise ValueError("Checkpoint belongs to a different workspace")
                task.id = row["id"]
                task.index = row["index"]
                task.before = {name: state(value) for name, value in row["before"].items()}
                task.after = {name: state(value) for name, value in row["after"].items()}
                for name in task.before.keys() | task.after.keys() | task.index.keys():
                    task._path(name)
                task.finished = row["finished"]
                task.undone = set(row.get("undone", []))
                if not task.undone.issubset(task.before):
                    raise ValueError("Checkpoint contains unknown undone paths")
                task.available = True
                self._tasks[task.id] = task
                self._checkpoints.append(
                    Checkpoint(
                        task.id,
                        row["name"],
                        datetime.fromisoformat(row["timestamp"]),
                        row["message"],
                        list(task.after),
                    )
                )
            self._current_index = int(data["current_index"])
            if not -1 <= self._current_index < len(self._checkpoints):
                raise ValueError("Checkpoint position is invalid")
            self._redo_stack = [
                next(cp for cp in self._checkpoints if cp.id == key) for key in data["redo"]
            ]
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            self._checkpoints = []
            self._tasks = {}
            self._redo_stack = []
            self._current_index = -1


# ============================================================================
# ASYNC VERSION
# ============================================================================


class AsyncUndoManager:
    """Async wrapper for UndoManager."""

    def __init__(self, working_dir: Optional[Path] = None):
        self._sync_manager = UndoManager(working_dir)

    async def initialize(self) -> bool:
        """Initialize the undo manager."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_manager.initialize)

    async def create_checkpoint(self, name: str = "", message: str = "") -> Optional[str]:
        """Create a checkpoint."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._sync_manager.create_checkpoint(name, message)
        )

    async def undo(self) -> Optional[Checkpoint]:
        """Undo to previous checkpoint."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_manager.undo)

    async def redo(self) -> Optional[Checkpoint]:
        """Redo previously undone checkpoint."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_manager.redo)

    async def restore(self, checkpoint_id: str) -> bool:
        """Restore to a specific checkpoint."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self._sync_manager.restore(checkpoint_id))


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "Checkpoint",
    "FileChange",
    "UndoManager",
    "AsyncUndoManager",
]
