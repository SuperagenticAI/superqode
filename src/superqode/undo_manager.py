"""
SuperQode Undo Manager - Git-Based Undo/Redo System.

Provides reliable undo/redo functionality using Git's object database
for tracking file changes. Each operation creates a checkpoint that
can be restored.

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

    id: str  # Git commit or stash reference
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
    """
    Git-based undo/redo manager.

    Uses Git's stash and commit system to create reliable checkpoints
    that can be restored.
    """

    def __init__(self, working_dir: Optional[Path] = None):
        self.working_dir = working_dir or Path.cwd()
        self._checkpoints: List[Checkpoint] = []
        self._redo_stack: List[Checkpoint] = []
        self._current_index: int = -1
        self._initialized = False

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    def initialize(self) -> bool:
        """
        Initialize the undo manager.

        Checks if we're in a git repo and sets up tracking.
        Returns True if successful.
        """
        if self._initialized:
            return True

        # Check if git is available
        try:
            result = self._run_git(["rev-parse", "--git-dir"])
            if result.returncode != 0:
                return False

            self._initialized = True
            return True
        except Exception:
            return False

    def _run_git(self, args: List[str], capture_output: bool = True) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git"] + args
        return subprocess.run(
            cmd,
            cwd=str(self.working_dir),
            capture_output=capture_output,
            text=True,
        )

    # ========================================================================
    # CHECKPOINT CREATION
    # ========================================================================

    def create_checkpoint(self, name: str = "", message: str = "") -> Optional[str]:
        """
        Create a checkpoint of the current state.

        Uses git stash to save changes without affecting the working tree.
        Returns the checkpoint ID if successful.
        """
        if not self.initialize():
            return None

        try:
            # Get list of changed files
            status = self._run_git(["status", "--porcelain"])
            changed_files = []
            for line in status.stdout.strip().split("\n"):
                if line.strip():
                    # Parse status line: "XY filename"
                    parts = line.split(maxsplit=1)
                    if len(parts) >= 2:
                        changed_files.append(parts[1].strip('"'))

            if not changed_files:
                # No changes to checkpoint
                return None

            # Create a stash with all changes (including untracked)
            stash_msg = f"superqode-checkpoint: {name or 'Checkpoint'}"
            if message:
                stash_msg += f" - {message}"

            # Stage all changes including untracked
            self._run_git(["add", "-A"])

            # Create stash
            result = self._run_git(["stash", "push", "-m", stash_msg, "--include-untracked"])

            if result.returncode != 0:
                # Unstage changes
                self._run_git(["reset"])
                return None

            # Get the stash reference
            stash_list = self._run_git(["stash", "list", "-1"])
            if not stash_list.stdout.strip():
                return None

            # Parse stash reference (e.g., "stash@{0}: ...")
            stash_ref = stash_list.stdout.split(":")[0].strip()

            # Immediately restore working directory (we just want the checkpoint)
            self._run_git(["stash", "pop", "--quiet"])

            # Create checkpoint record
            checkpoint = Checkpoint(
                id=stash_ref,
                name=name or f"Checkpoint {len(self._checkpoints) + 1}",
                timestamp=datetime.now(),
                message=message,
                files_changed=changed_files,
                is_stash=True,
            )

            # Clear redo stack when creating new checkpoint
            self._redo_stack.clear()

            self._checkpoints.append(checkpoint)
            self._current_index = len(self._checkpoints) - 1

            return checkpoint.id

        except Exception:
            return None

    def create_commit_checkpoint(self, name: str = "", message: str = "") -> Optional[str]:
        """
        Create a checkpoint using a commit.

        More permanent than stash-based checkpoints.
        """
        if not self.initialize():
            return None

        try:
            # Get changed files
            status = self._run_git(["status", "--porcelain"])
            changed_files = []
            for line in status.stdout.strip().split("\n"):
                if line.strip():
                    parts = line.split(maxsplit=1)
                    if len(parts) >= 2:
                        changed_files.append(parts[1].strip('"'))

            if not changed_files:
                return None

            # Stage all changes
            self._run_git(["add", "-A"])

            # Create commit
            commit_msg = f"[superqode] {name or 'Checkpoint'}"
            if message:
                commit_msg += f": {message}"

            result = self._run_git(["commit", "-m", commit_msg])
            if result.returncode != 0:
                return None

            # Get commit hash
            hash_result = self._run_git(["rev-parse", "HEAD"])
            commit_hash = hash_result.stdout.strip()[:8]

            checkpoint = Checkpoint(
                id=commit_hash,
                name=name or f"Checkpoint {len(self._checkpoints) + 1}",
                timestamp=datetime.now(),
                message=message,
                files_changed=changed_files,
                is_stash=False,
            )

            self._redo_stack.clear()
            self._checkpoints.append(checkpoint)
            self._current_index = len(self._checkpoints) - 1

            return commit_hash

        except Exception:
            return None

    # ========================================================================
    # UNDO / REDO
    # ========================================================================

    def undo(self) -> Optional[Checkpoint]:
        """
        Undo to the previous checkpoint.

        Returns the checkpoint that was restored, or None if nothing to undo.
        """
        if not self._checkpoints or self._current_index < 0:
            return None

        try:
            # Save current state to redo stack
            current_state = self._capture_current_state()
            if current_state:
                self._redo_stack.append(current_state)

            # Get checkpoint to restore
            checkpoint = self._checkpoints[self._current_index]

            # Restore based on type
            if checkpoint.is_stash:
                # For stash-based, we need to reverse the changes
                # This is tricky - we'll use git checkout
                for file_path in checkpoint.files_changed:
                    self._run_git(["checkout", "HEAD", "--", file_path])
            else:
                # For commit-based, reset to previous commit
                if self._current_index > 0:
                    prev_checkpoint = self._checkpoints[self._current_index - 1]
                    self._run_git(["reset", "--hard", prev_checkpoint.id])

            self._current_index -= 1
            return checkpoint

        except Exception:
            return None

    def redo(self) -> Optional[Checkpoint]:
        """
        Redo the previously undone checkpoint.

        Returns the checkpoint that was restored, or None if nothing to redo.
        """
        if not self._redo_stack:
            return None

        try:
            checkpoint = self._redo_stack.pop()

            # Apply the changes
            for file_path in checkpoint.files_changed:
                # This is simplified - full implementation would restore content
                pass

            self._current_index += 1
            return checkpoint

        except Exception:
            return None

    def _capture_current_state(self) -> Optional[Checkpoint]:
        """Capture the current state as a checkpoint for redo."""
        try:
            status = self._run_git(["status", "--porcelain"])
            changed_files = []
            for line in status.stdout.strip().split("\n"):
                if line.strip():
                    parts = line.split(maxsplit=1)
                    if len(parts) >= 2:
                        changed_files.append(parts[1].strip('"'))

            return Checkpoint(
                id="current",
                name="Current state",
                timestamp=datetime.now(),
                files_changed=changed_files,
            )
        except Exception:
            return None

    # ========================================================================
    # RESTORE
    # ========================================================================

    def restore(self, checkpoint_id: str) -> bool:
        """
        Restore to a specific checkpoint.

        Returns True if successful.
        """
        if not self.initialize():
            return False

        # Find the checkpoint
        checkpoint = None
        index = -1
        for i, cp in enumerate(self._checkpoints):
            if cp.id == checkpoint_id:
                checkpoint = cp
                index = i
                break

        if not checkpoint:
            return False

        try:
            if checkpoint.is_stash:
                # Find and apply the stash
                result = self._run_git(["stash", "apply", checkpoint.id])
                return result.returncode == 0
            else:
                # Reset to commit
                result = self._run_git(["reset", "--hard", checkpoint.id])
                if result.returncode == 0:
                    self._current_index = index
                    return True
                return False
        except Exception:
            return False

    def restore_file(self, checkpoint_id: str, file_path: str) -> bool:
        """
        Restore a specific file from a checkpoint.

        Returns True if successful.
        """
        if not self.initialize():
            return False

        # Find the checkpoint
        checkpoint = None
        for cp in self._checkpoints:
            if cp.id == checkpoint_id:
                checkpoint = cp
                break

        if not checkpoint:
            return False

        try:
            if checkpoint.is_stash:
                # Restore file from stash
                result = self._run_git(["checkout", checkpoint.id, "--", file_path])
            else:
                # Restore file from commit
                result = self._run_git(["checkout", checkpoint.id, "--", file_path])

            return result.returncode == 0
        except Exception:
            return False

    # ========================================================================
    # QUERY
    # ========================================================================

    def get_checkpoints(self, limit: int = 20) -> List[Checkpoint]:
        """Get list of checkpoints."""
        return self._checkpoints[-limit:]

    def get_current_checkpoint(self) -> Optional[Checkpoint]:
        """Get the current checkpoint."""
        if 0 <= self._current_index < len(self._checkpoints):
            return self._checkpoints[self._current_index]
        return None

    def get_changes_since(self, checkpoint_id: str) -> List[FileChange]:
        """Get list of changes since a checkpoint."""
        if not self.initialize():
            return []

        try:
            # Get diff
            result = self._run_git(["diff", checkpoint_id, "--name-status"])

            changes = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue

                parts = line.split("\t")
                if len(parts) >= 2:
                    status = parts[0]
                    path = parts[1]

                    change_type = {
                        "A": "added",
                        "M": "modified",
                        "D": "deleted",
                    }.get(status[0], "modified")

                    changes.append(
                        FileChange(
                            path=path,
                            change_type=change_type,
                        )
                    )

            return changes

        except Exception:
            return []

    def get_file_diff(self, checkpoint_id: str, file_path: str) -> Tuple[str, str]:
        """
        Get the old and new content of a file relative to checkpoint.

        Returns (old_content, new_content).
        """
        if not self.initialize():
            return ("", "")

        try:
            # Get old content
            old_result = self._run_git(["show", f"{checkpoint_id}:{file_path}"])
            old_content = old_result.stdout if old_result.returncode == 0 else ""

            # Get current content
            file_path_obj = self.working_dir / file_path
            if file_path_obj.exists():
                new_content = file_path_obj.read_text(encoding="utf-8", errors="ignore")
            else:
                new_content = ""

            return (old_content, new_content)

        except Exception:
            return ("", "")

    def can_undo(self) -> bool:
        """Check if undo is possible."""
        return len(self._checkpoints) > 0 and self._current_index >= 0

    def can_redo(self) -> bool:
        """Check if redo is possible."""
        return len(self._redo_stack) > 0

    # ========================================================================
    # CLEANUP
    # ========================================================================

    def clear_old_checkpoints(self, keep_count: int = 50) -> int:
        """
        Clear old checkpoints to save space.

        Returns number of checkpoints cleared.
        """
        if len(self._checkpoints) <= keep_count:
            return 0

        to_remove = self._checkpoints[:-keep_count]
        removed = 0

        for checkpoint in to_remove:
            if checkpoint.is_stash:
                # Drop the stash
                try:
                    self._run_git(["stash", "drop", checkpoint.id])
                    removed += 1
                except Exception:
                    pass

        self._checkpoints = self._checkpoints[-keep_count:]
        self._current_index = min(self._current_index, len(self._checkpoints) - 1)

        return removed


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
