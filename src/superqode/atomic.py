"""
SuperQode Atomic File Operations - Safe File Writing

Provides atomic file operations to prevent data corruption:
- Writes to temp file first, then renames
- Supports undo/rollback
- Tracks file history for recovery
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict


class AtomicWriteError(Exception):
    """An atomic write operation failed."""

    pass


class AtomicReadError(Exception):
    """An atomic read operation failed."""

    pass


@dataclass
class FileVersion:
    """A version of a file for history tracking."""

    path: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    operation: str = "write"  # "write", "create", "delete", "modify"
    backup_path: Optional[str] = None


@dataclass
class FileChange:
    """A pending file change."""

    path: str
    old_content: Optional[str]
    new_content: str
    operation: str = "write"


class AtomicFileManager:
    """Manages atomic file operations with history and undo support."""

    def __init__(self, project_dir: str = "."):
        self.project_dir = Path(project_dir).resolve()
        self.history: List[FileVersion] = []
        self.pending_changes: List[FileChange] = []
        self.max_history = 50
        self._backup_dir: Optional[Path] = None

    @property
    def backup_dir(self) -> Path:
        """Get or create the backup directory."""
        if self._backup_dir is None:
            self._backup_dir = self.project_dir / ".superqode" / "backups"
            self._backup_dir.mkdir(parents=True, exist_ok=True)
        return self._backup_dir

    def read(self, path: str) -> str:
        """Read a file safely."""
        file_path = self._resolve_path(path)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            raise AtomicReadError(f"File not found: {path}")
        except Exception as e:
            raise AtomicReadError(f"Failed to read {path}: {e}")

    def write(self, path: str, content: str, create_backup: bool = True) -> FileVersion:
        """Write a file atomically with optional backup."""
        file_path = self._resolve_path(path)
        dir_path = file_path.parent

        # Read existing content for backup
        old_content = None
        if file_path.exists() and create_backup:
            try:
                old_content = self.read(path)
            except AtomicReadError:
                pass

        # Create directory if needed
        dir_path.mkdir(parents=True, exist_ok=True)

        # Create backup if file exists
        backup_path = None
        if old_content is not None:
            backup_path = self._create_backup(path, old_content)

        # Write to temp file first
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=str(dir_path),
                prefix=f".{file_path.name}_tmp_",
                suffix=".tmp",
            ) as tmp_file:
                tmp_file.write(content)
                temp_path = tmp_file.name
        except (OSError, IOError) as e:
            raise AtomicWriteError(f"Failed to create temp file for {path}: {e}")

        # Atomic rename
        try:
            os.replace(temp_path, str(file_path))
        except OSError as e:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except OSError:
                pass  # Best effort cleanup
            raise AtomicWriteError(f"Failed to write {path}: {e}")

        # Record in history
        operation = "create" if old_content is None else "modify"
        version = FileVersion(
            path=path, content=old_content or "", operation=operation, backup_path=backup_path
        )
        self._add_to_history(version)

        return version

    def delete(self, path: str, create_backup: bool = True) -> FileVersion:
        """Delete a file with backup."""
        file_path = self._resolve_path(path)

        if not file_path.exists():
            raise AtomicWriteError(f"File not found: {path}")

        # Read content for backup
        old_content = self.read(path)

        # Create backup
        backup_path = None
        if create_backup:
            backup_path = self._create_backup(path, old_content)

        # Delete file
        try:
            os.unlink(str(file_path))
        except Exception as e:
            raise AtomicWriteError(f"Failed to delete {path}: {e}")

        # Record in history
        version = FileVersion(
            path=path, content=old_content, operation="delete", backup_path=backup_path
        )
        self._add_to_history(version)

        return version

    def undo(self) -> Optional[FileVersion]:
        """Undo the last file operation."""
        if not self.history:
            return None

        version = self.history.pop()
        file_path = self._resolve_path(version.path)

        if version.operation == "create":
            # Undo create = delete the file
            if file_path.exists():
                os.unlink(str(file_path))
        elif version.operation == "delete":
            # Undo delete = restore from backup
            if version.backup_path and Path(version.backup_path).exists():
                shutil.copy2(version.backup_path, str(file_path))
            elif version.content:
                self.write(version.path, version.content, create_backup=False)
        elif version.operation == "modify":
            # Undo modify = restore previous content
            if version.backup_path and Path(version.backup_path).exists():
                shutil.copy2(version.backup_path, str(file_path))
            elif version.content:
                self.write(version.path, version.content, create_backup=False)

        return version

    def stage_change(self, path: str, new_content: str) -> FileChange:
        """Stage a file change without applying it."""
        old_content = None
        try:
            old_content = self.read(path)
        except AtomicReadError:
            pass

        change = FileChange(
            path=path,
            old_content=old_content,
            new_content=new_content,
            operation="create" if old_content is None else "modify",
        )
        self.pending_changes.append(change)
        return change

    def apply_staged(self) -> List[FileVersion]:
        """Apply all staged changes."""
        versions = []
        for change in self.pending_changes:
            version = self.write(change.path, change.new_content)
            versions.append(version)
        self.pending_changes.clear()
        return versions

    def discard_staged(self) -> int:
        """Discard all staged changes."""
        count = len(self.pending_changes)
        self.pending_changes.clear()
        return count

    def get_history(self, limit: int = 10) -> List[FileVersion]:
        """Get recent file history."""
        return self.history[-limit:]

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to project directory."""
        p = Path(path)
        if p.is_absolute():
            return p
        return self.project_dir / p

    def _create_backup(self, path: str, content: str) -> str:
        """Create a backup of file content."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = Path(path).name.replace("/", "_").replace("\\", "_")
        backup_name = f"{safe_name}.{timestamp}.bak"
        backup_path = self.backup_dir / backup_name

        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)

        return str(backup_path)

    def _add_to_history(self, version: FileVersion) -> None:
        """Add a version to history, maintaining max size."""
        self.history.append(version)
        if len(self.history) > self.max_history:
            # Remove oldest entries
            self.history = self.history[-self.max_history :]


# Convenience functions
def atomic_write(path: str, content: str) -> None:
    """Write a file atomically (simple interface)."""
    file_path = Path(path).resolve()
    dir_path = file_path.parent

    dir_path.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(dir_path),
            prefix=f".{file_path.name}_tmp_",
            suffix=".tmp",
        ) as tmp_file:
            tmp_file.write(content)
            temp_path = tmp_file.name
    except Exception as e:
        raise AtomicWriteError(f"Failed to create temp file: {e}")

    try:
        os.replace(temp_path, str(file_path))
    except OSError as e:
        try:
            os.unlink(temp_path)
        except OSError:
            pass  # Best effort cleanup
        raise AtomicWriteError(f"Failed to write file: {e}")


def atomic_read(path: str) -> str:
    """Read a file safely."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise AtomicReadError(f"Failed to read file: {e}")
