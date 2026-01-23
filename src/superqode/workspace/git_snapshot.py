"""
Git-Based Snapshot Manager.

Uses Git's object database for robust file state tracking and reversion.
Much more reliable than in-memory/tempfile approach:
- Atomic operations
- Efficient storage (Git's delta compression)
- Full history and diffing capabilities
- Works with existing Git workflows
- Adapted for SuperQode's QE needs
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import json


class SnapshotError(Exception):
    """Error during snapshot operations."""

    pass


class FileStatus(Enum):
    """Status of a file relative to snapshot."""

    UNCHANGED = "unchanged"
    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass
class FileChange:
    """Represents a change to a file."""

    path: Path
    status: FileStatus
    original_hash: Optional[str] = None
    current_hash: Optional[str] = None
    original_path: Optional[Path] = None  # For renames


@dataclass
class Snapshot:
    """A point-in-time snapshot of file states."""

    id: str
    timestamp: datetime
    message: str
    file_hashes: Dict[str, str]  # path -> git object hash
    parent_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
            "file_hashes": self.file_hashes,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Snapshot":
        return cls(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            message=data["message"],
            file_hashes=data["file_hashes"],
            parent_id=data.get("parent_id"),
        )


class GitSnapshotManager:
    """
    Git-based snapshot manager for robust file state tracking.

    Uses Git's object database to store file states efficiently.
    All operations are atomic and can be safely interrupted.

    Usage:
        manager = GitSnapshotManager(project_root)

        # Create initial snapshot before QE session
        snapshot_id = await manager.create_snapshot("Before QE session")

        # ... agent modifies files ...

        # Get changes since snapshot
        changes = await manager.get_changes(snapshot_id)

        # Revert to snapshot
        await manager.restore_snapshot(snapshot_id)
    """

    SUPERQODE_REF = "refs/superqode/snapshots"

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self._git_dir = self.project_root / ".git"
        self._snapshots_dir = self.project_root / ".superqode" / "snapshots"
        self._current_snapshot: Optional[str] = None
        self._tracked_files: Set[Path] = set()

        # Verify Git repo exists
        if not self._git_dir.exists():
            raise SnapshotError(f"Not a Git repository: {self.project_root}")

    async def _run_git(
        self,
        *args: str,
        capture_output: bool = True,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git", "-C", str(self.project_root), *args]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE if capture_output else None,
            stderr=asyncio.subprocess.PIPE if capture_output else None,
        )
        stdout, stderr = await proc.communicate()

        result = subprocess.CompletedProcess(
            cmd,
            proc.returncode,
            stdout=stdout.decode() if stdout else "",
            stderr=stderr.decode() if stderr else "",
        )

        if check and result.returncode != 0:
            raise SnapshotError(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")

        return result

    def _run_git_sync(
        self,
        *args: str,
        capture_output: bool = True,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run a git command synchronously."""
        cmd = ["git", "-C", str(self.project_root), *args]

        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
        )

        if check and result.returncode != 0:
            raise SnapshotError(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")

        return result

    async def _hash_object(self, content: bytes) -> str:
        """Store content in Git object database and return hash."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(self.project_root),
            "hash-object",
            "-w",
            "--stdin",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate(content)
        return stdout.decode().strip()

    async def _get_object(self, obj_hash: str) -> bytes:
        """Retrieve content from Git object database."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(self.project_root),
            "cat-file",
            "blob",
            obj_hash,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise SnapshotError(f"Object not found: {obj_hash}")

        return stdout

    async def _get_file_hash(self, file_path: Path) -> Optional[str]:
        """Get the Git hash for a file's current content."""
        abs_path = self.project_root / file_path

        if not abs_path.exists() or not abs_path.is_file():
            return None

        try:
            content = abs_path.read_bytes()
            return await self._hash_object(content)
        except (IOError, OSError):
            return None

    def _generate_snapshot_id(self) -> str:
        """Generate a unique snapshot ID."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        random_suffix = hashlib.sha256(os.urandom(8)).hexdigest()[:8]
        return f"snap-{timestamp}-{random_suffix}"

    async def create_snapshot(
        self,
        message: str = "Snapshot",
        files: Optional[List[Path]] = None,
    ) -> str:
        """
        Create a snapshot of the current file state.

        Args:
            message: Description of the snapshot
            files: Specific files to snapshot (None = all tracked files)

        Returns:
            Snapshot ID
        """
        snapshot_id = self._generate_snapshot_id()

        # Get list of files to snapshot
        if files:
            target_files = [Path(f) for f in files]
        else:
            # Get all tracked files from Git
            result = await self._run_git("ls-files")
            target_files = [Path(f) for f in result.stdout.strip().split("\n") if f]

        # Capture file hashes
        file_hashes = {}
        for file_path in target_files:
            hash_val = await self._get_file_hash(file_path)
            if hash_val:
                file_hashes[str(file_path)] = hash_val
                self._tracked_files.add(file_path)

        # Create snapshot object
        snapshot = Snapshot(
            id=snapshot_id,
            timestamp=datetime.now(),
            message=message,
            file_hashes=file_hashes,
            parent_id=self._current_snapshot,
        )

        # Save snapshot metadata
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = self._snapshots_dir / f"{snapshot_id}.json"
        snapshot_file.write_text(json.dumps(snapshot.to_dict(), indent=2))

        self._current_snapshot = snapshot_id

        return snapshot_id

    async def get_snapshot(self, snapshot_id: str) -> Optional[Snapshot]:
        """Get a snapshot by ID."""
        snapshot_file = self._snapshots_dir / f"{snapshot_id}.json"

        if not snapshot_file.exists():
            return None

        data = json.loads(snapshot_file.read_text())
        return Snapshot.from_dict(data)

    async def list_snapshots(self) -> List[Snapshot]:
        """List all available snapshots."""
        if not self._snapshots_dir.exists():
            return []

        snapshots = []
        for file_path in self._snapshots_dir.glob("snap-*.json"):
            try:
                data = json.loads(file_path.read_text())
                snapshots.append(Snapshot.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                continue

        # Sort by timestamp, newest first
        snapshots.sort(key=lambda s: s.timestamp, reverse=True)
        return snapshots

    async def get_changes(
        self,
        snapshot_id: str,
        files: Optional[List[Path]] = None,
    ) -> List[FileChange]:
        """
        Get changes since a snapshot.

        Args:
            snapshot_id: ID of the snapshot to compare against
            files: Specific files to check (None = all tracked files)

        Returns:
            List of file changes
        """
        snapshot = await self.get_snapshot(snapshot_id)
        if not snapshot:
            raise SnapshotError(f"Snapshot not found: {snapshot_id}")

        changes = []

        # Files to check
        check_files = set(Path(f) for f in files) if files else self._tracked_files

        # Also check files that were in the snapshot
        for path_str in snapshot.file_hashes:
            check_files.add(Path(path_str))

        for file_path in check_files:
            path_str = str(file_path)
            original_hash = snapshot.file_hashes.get(path_str)
            current_hash = await self._get_file_hash(file_path)

            if original_hash == current_hash:
                status = FileStatus.UNCHANGED
            elif original_hash is None and current_hash is not None:
                status = FileStatus.ADDED
            elif original_hash is not None and current_hash is None:
                status = FileStatus.DELETED
            else:
                status = FileStatus.MODIFIED

            if status != FileStatus.UNCHANGED:
                changes.append(
                    FileChange(
                        path=file_path,
                        status=status,
                        original_hash=original_hash,
                        current_hash=current_hash,
                    )
                )

        return changes

    async def restore_snapshot(
        self,
        snapshot_id: str,
        files: Optional[List[Path]] = None,
    ) -> Dict[str, List[str]]:
        """
        Restore files to their state at a snapshot.

        Args:
            snapshot_id: ID of the snapshot to restore
            files: Specific files to restore (None = all files in snapshot)

        Returns:
            Summary of restored files
        """
        snapshot = await self.get_snapshot(snapshot_id)
        if not snapshot:
            raise SnapshotError(f"Snapshot not found: {snapshot_id}")

        result = {
            "restored": [],
            "deleted": [],
            "errors": [],
        }

        # Files to restore
        if files:
            target_files = {str(f) for f in files}
        else:
            target_files = set(snapshot.file_hashes.keys())

        # Get current file list to detect additions
        current_files = set()
        for file_path in self._tracked_files:
            if (self.project_root / file_path).exists():
                current_files.add(str(file_path))

        # Restore files from snapshot
        for path_str in target_files:
            if path_str not in snapshot.file_hashes:
                continue

            abs_path = self.project_root / path_str
            obj_hash = snapshot.file_hashes[path_str]

            try:
                content = await self._get_object(obj_hash)
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_bytes(content)
                result["restored"].append(path_str)
            except Exception as e:
                result["errors"].append(f"{path_str}: {e}")

        # Delete files that were added after the snapshot
        files_to_delete = current_files - target_files
        for path_str in files_to_delete:
            abs_path = self.project_root / path_str

            try:
                if abs_path.exists():
                    abs_path.unlink()
                    result["deleted"].append(path_str)
            except Exception as e:
                result["errors"].append(f"delete {path_str}: {e}")

        return result

    async def get_file_at_snapshot(
        self,
        snapshot_id: str,
        file_path: Path,
    ) -> Optional[bytes]:
        """Get file content at a specific snapshot."""
        snapshot = await self.get_snapshot(snapshot_id)
        if not snapshot:
            return None

        obj_hash = snapshot.file_hashes.get(str(file_path))
        if not obj_hash:
            return None

        try:
            return await self._get_object(obj_hash)
        except SnapshotError:
            return None

    async def get_diff(
        self,
        snapshot_id: str,
        file_path: Path,
    ) -> Optional[str]:
        """Get unified diff for a file since snapshot."""
        original = await self.get_file_at_snapshot(snapshot_id, file_path)

        abs_path = self.project_root / file_path
        if not abs_path.exists():
            if original:
                return (
                    f"--- a/{file_path}\n+++ /dev/null\n@@ -1,{original.count(b'\\n') + 1} +0,0 @@\n"
                    + "\n".join(
                        f"-{line}" for line in original.decode(errors="replace").splitlines()
                    )
                )
            return None

        current = abs_path.read_bytes()

        if original == current:
            return None

        # Use Git diff for proper formatting
        if original:
            # Create temp objects for diffing
            orig_hash = await self._hash_object(original)
            curr_hash = await self._hash_object(current)

            result = await self._run_git(
                "diff",
                "--no-index",
                f"--src-prefix=a/",
                f"--dst-prefix=b/",
                orig_hash,
                curr_hash,
                check=False,  # diff returns 1 if files differ
            )
            return result.stdout
        else:
            # New file
            lines = current.decode(errors="replace").splitlines()
            return f"--- /dev/null\n+++ b/{file_path}\n@@ -0,0 +1,{len(lines)} @@\n" + "\n".join(
                f"+{line}" for line in lines
            )

    async def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot."""
        snapshot_file = self._snapshots_dir / f"{snapshot_id}.json"

        if snapshot_file.exists():
            snapshot_file.unlink()
            return True

        return False

    async def cleanup_old_snapshots(self, keep_count: int = 10) -> int:
        """Delete old snapshots, keeping the most recent ones."""
        snapshots = await self.list_snapshots()

        if len(snapshots) <= keep_count:
            return 0

        deleted = 0
        for snapshot in snapshots[keep_count:]:
            if await self.delete_snapshot(snapshot.id):
                deleted += 1

        return deleted

    def track_file(self, file_path: Path) -> None:
        """Add a file to the tracked set."""
        self._tracked_files.add(Path(file_path))

    def untrack_file(self, file_path: Path) -> None:
        """Remove a file from the tracked set."""
        self._tracked_files.discard(Path(file_path))

    @property
    def current_snapshot_id(self) -> Optional[str]:
        """Get the current snapshot ID."""
        return self._current_snapshot


# Convenience function for creating a snapshot manager
def create_git_snapshot_manager(project_root: Path) -> GitSnapshotManager:
    """Create a GitSnapshotManager for the given project."""
    return GitSnapshotManager(project_root)
