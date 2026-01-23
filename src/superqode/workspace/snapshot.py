"""
Snapshot Manager for Ephemeral Workspace.

Captures the state of modified files and enables full reversion
after QE session completes. Uses efficient in-memory tracking
with disk backup for large files.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
import json


@dataclass
class FileSnapshot:
    """Snapshot of a single file's state."""

    path: Path
    original_content: Optional[bytes]  # None if file didn't exist
    original_hash: Optional[str]
    existed: bool
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def was_created(self) -> bool:
        """True if this file was created (didn't exist before)."""
        return not self.existed

    def content_changed(self, current_content: bytes) -> bool:
        """Check if content has changed from original."""
        if self.original_content is None:
            return True
        current_hash = hashlib.sha256(current_content).hexdigest()
        return current_hash != self.original_hash


@dataclass
class DirectorySnapshot:
    """Snapshot of a directory that was created."""

    path: Path
    existed: bool
    timestamp: datetime = field(default_factory=datetime.now)


class SnapshotManager:
    """
    Manages file snapshots for ephemeral workspace.

    Tracks all file modifications during a QE session and enables
    complete reversion to original state.

    Usage:
        snapshot = SnapshotManager(project_root)
        snapshot.start_session()

        # Track file before modification
        snapshot.capture_file(Path("src/main.py"))

        # ... agent modifies files ...

        # Revert everything
        snapshot.revert_all()
    """

    # Files larger than this are backed up to disk
    LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.session_id: Optional[str] = None
        self.session_start: Optional[datetime] = None

        # Tracking state
        self._file_snapshots: Dict[Path, FileSnapshot] = {}
        self._dir_snapshots: Dict[Path, DirectorySnapshot] = {}
        self._large_file_backup_dir: Optional[Path] = None

        # Statistics
        self._files_modified: Set[Path] = set()
        self._files_created: Set[Path] = set()
        self._files_deleted: Set[Path] = set()
        self._dirs_created: Set[Path] = set()

    def start_session(self, session_id: Optional[str] = None) -> str:
        """Start a new snapshot session."""
        if self.session_id:
            raise RuntimeError("Session already active. Call revert_all() or end_session() first.")

        self.session_id = session_id or f"qe-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.session_start = datetime.now()

        # Create temp dir for large file backups
        self._large_file_backup_dir = Path(tempfile.mkdtemp(prefix=f"superqode-{self.session_id}-"))

        # Reset tracking
        self._file_snapshots.clear()
        self._dir_snapshots.clear()
        self._files_modified.clear()
        self._files_created.clear()
        self._files_deleted.clear()
        self._dirs_created.clear()

        return self.session_id

    def capture_file(self, file_path: Path) -> FileSnapshot:
        """
        Capture a file's state before modification.

        Call this BEFORE any modification to the file.
        """
        if not self.session_id:
            raise RuntimeError("No active session. Call start_session() first.")

        abs_path = (self.project_root / file_path).resolve()
        rel_path = abs_path.relative_to(self.project_root)

        # Already captured
        if rel_path in self._file_snapshots:
            return self._file_snapshots[rel_path]

        # Capture current state
        if abs_path.exists() and abs_path.is_file():
            content = abs_path.read_bytes()
            content_hash = hashlib.sha256(content).hexdigest()

            # Large files go to disk backup
            if len(content) > self.LARGE_FILE_THRESHOLD:
                backup_path = self._large_file_backup_dir / rel_path
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(abs_path, backup_path)
                original_content = None  # Don't keep in memory
            else:
                original_content = content

            snapshot = FileSnapshot(
                path=rel_path,
                original_content=original_content,
                original_hash=content_hash,
                existed=True,
            )
        else:
            # File doesn't exist yet
            snapshot = FileSnapshot(
                path=rel_path,
                original_content=None,
                original_hash=None,
                existed=False,
            )

        self._file_snapshots[rel_path] = snapshot
        return snapshot

    def capture_directory(self, dir_path: Path) -> DirectorySnapshot:
        """Capture a directory's existence state before creation."""
        if not self.session_id:
            raise RuntimeError("No active session. Call start_session() first.")

        abs_path = (self.project_root / dir_path).resolve()
        rel_path = abs_path.relative_to(self.project_root)

        if rel_path in self._dir_snapshots:
            return self._dir_snapshots[rel_path]

        snapshot = DirectorySnapshot(
            path=rel_path,
            existed=abs_path.exists(),
        )
        self._dir_snapshots[rel_path] = snapshot

        if not snapshot.existed:
            self._dirs_created.add(rel_path)

        return snapshot

    def record_modification(self, file_path: Path) -> None:
        """Record that a file was modified (after capturing)."""
        rel_path = Path(file_path)
        if rel_path in self._file_snapshots:
            snapshot = self._file_snapshots[rel_path]
            if snapshot.existed:
                self._files_modified.add(rel_path)
            else:
                self._files_created.add(rel_path)

    def record_deletion(self, file_path: Path) -> None:
        """Record that a file was deleted."""
        rel_path = Path(file_path)
        if rel_path in self._file_snapshots and self._file_snapshots[rel_path].existed:
            self._files_deleted.add(rel_path)

    def revert_file(self, file_path: Path) -> bool:
        """Revert a single file to its original state."""
        rel_path = Path(file_path)
        if rel_path not in self._file_snapshots:
            return False

        snapshot = self._file_snapshots[rel_path]
        abs_path = self.project_root / rel_path

        if not snapshot.existed:
            # File was created during session - delete it
            if abs_path.exists():
                abs_path.unlink()
            return True

        # Restore original content
        if snapshot.original_content is not None:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_bytes(snapshot.original_content)
        else:
            # Large file - restore from backup
            backup_path = self._large_file_backup_dir / rel_path
            if backup_path.exists():
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, abs_path)

        return True

    def revert_all(self) -> Dict[str, List[str]]:
        """
        Revert ALL changes made during the session.

        Returns a summary of what was reverted.
        """
        if not self.session_id:
            return {"error": "No active session"}

        reverted = {
            "files_restored": [],
            "files_deleted": [],
            "dirs_deleted": [],
            "errors": [],
        }

        # Revert files
        for rel_path, snapshot in self._file_snapshots.items():
            abs_path = self.project_root / rel_path

            try:
                if not snapshot.existed:
                    # Delete files that were created
                    if abs_path.exists():
                        abs_path.unlink()
                        reverted["files_deleted"].append(str(rel_path))
                else:
                    # Restore original content
                    if snapshot.original_content is not None:
                        abs_path.parent.mkdir(parents=True, exist_ok=True)
                        abs_path.write_bytes(snapshot.original_content)
                    else:
                        # Large file from backup
                        backup_path = self._large_file_backup_dir / rel_path
                        if backup_path.exists():
                            abs_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(backup_path, abs_path)
                    reverted["files_restored"].append(str(rel_path))
            except Exception as e:
                reverted["errors"].append(f"{rel_path}: {e}")

        # Remove created directories (in reverse order - deepest first)
        created_dirs = sorted(self._dirs_created, key=lambda p: len(p.parts), reverse=True)
        for rel_path in created_dirs:
            abs_path = self.project_root / rel_path
            try:
                if abs_path.exists() and abs_path.is_dir():
                    # Only remove if empty
                    if not any(abs_path.iterdir()):
                        abs_path.rmdir()
                        reverted["dirs_deleted"].append(str(rel_path))
            except Exception as e:
                reverted["errors"].append(f"dir {rel_path}: {e}")

        return reverted

    def end_session(self, revert: bool = True) -> Dict[str, any]:
        """
        End the current session.

        Args:
            revert: If True, revert all changes. If False, keep changes.
        """
        if not self.session_id:
            return {"error": "No active session"}

        result = {
            "session_id": self.session_id,
            "duration_seconds": (datetime.now() - self.session_start).total_seconds(),
            "files_tracked": len(self._file_snapshots),
            "files_modified": list(str(p) for p in self._files_modified),
            "files_created": list(str(p) for p in self._files_created),
            "files_deleted": list(str(p) for p in self._files_deleted),
            "dirs_created": list(str(p) for p in self._dirs_created),
        }

        if revert:
            revert_result = self.revert_all()
            result["revert_result"] = revert_result

        # Cleanup temp backup dir
        if self._large_file_backup_dir and self._large_file_backup_dir.exists():
            shutil.rmtree(self._large_file_backup_dir, ignore_errors=True)

        # Reset state
        self.session_id = None
        self.session_start = None
        self._file_snapshots.clear()
        self._dir_snapshots.clear()
        self._large_file_backup_dir = None

        return result

    def get_changes_summary(self) -> Dict[str, any]:
        """Get a summary of all changes in the current session."""
        return {
            "session_id": self.session_id,
            "files_tracked": len(self._file_snapshots),
            "files_modified": [str(p) for p in self._files_modified],
            "files_created": [str(p) for p in self._files_created],
            "files_deleted": [str(p) for p in self._files_deleted],
            "dirs_created": [str(p) for p in self._dirs_created],
        }

    def get_modified_content(self, file_path: Path) -> Optional[bytes]:
        """Get the current (modified) content of a tracked file."""
        abs_path = self.project_root / file_path
        if abs_path.exists():
            return abs_path.read_bytes()
        return None

    def get_original_content(self, file_path: Path) -> Optional[bytes]:
        """Get the original content of a tracked file."""
        rel_path = Path(file_path)
        if rel_path not in self._file_snapshots:
            return None

        snapshot = self._file_snapshots[rel_path]

        if not snapshot.existed:
            return None

        if snapshot.original_content is not None:
            return snapshot.original_content

        # Large file from backup
        backup_path = self._large_file_backup_dir / rel_path
        if backup_path.exists():
            return backup_path.read_bytes()

        return None
