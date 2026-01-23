"""
Diff Tracker - Track file changes during QE for patch generation.

Inspired by EveryCode's turn_diff_tracker.rs implementation.

Features:
- Capture baseline snapshots before modifications
- Generate unified diffs comparing baseline to current
- Support add, delete, update, rename/move operations
- Git-compatible diff format for easy review

Usage:
    tracker = DiffTracker(project_root)

    # Before modifying a file
    tracker.capture_baseline(Path("src/main.py"))

    # After QE session
    patch = tracker.get_unified_diff()
    print(patch)
"""

import difflib
import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class ChangeType(Enum):
    """Type of file change."""

    ADD = "add"
    DELETE = "delete"
    MODIFY = "modify"
    RENAME = "rename"


@dataclass
class FileBaseline:
    """Baseline state of a file."""

    original_path: Path
    content: Optional[bytes]  # None = file didn't exist
    mode: int  # File mode (permissions)
    oid: str  # Content hash (git-style blob SHA)

    @property
    def exists(self) -> bool:
        return self.content is not None


@dataclass
class FileChange:
    """Tracked change to a file."""

    change_type: ChangeType
    original_path: Path
    current_path: Path  # May differ for renames
    baseline: FileBaseline

    # For display
    original_display: str = ""
    current_display: str = ""


class DiffTracker:
    """
    Track file changes during a QE session for patch generation.

    Maintains baseline snapshots of files before first modification,
    then generates unified diffs comparing baseline to current state.
    """

    ZERO_OID = "0" * 40
    DEV_NULL = "/dev/null"

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()

        # Baseline snapshots: path -> baseline
        self._baselines: Dict[Path, FileBaseline] = {}

        # Path mappings for renames: original -> current
        self._path_mappings: Dict[Path, Path] = {}

        # Git root for relative paths
        self._git_root: Optional[Path] = None

    @property
    def git_root(self) -> Path:
        """Find git root for relative path display."""
        if self._git_root is None:
            current = self.project_root
            while current != current.parent:
                if (current / ".git").exists():
                    self._git_root = current
                    break
                current = current.parent

            if self._git_root is None:
                self._git_root = self.project_root

        return self._git_root

    def capture_baseline(self, file_path: Path) -> None:
        """
        Capture the baseline state of a file before modification.

        Call this before any file operation (write, delete, rename).
        """
        abs_path = self._resolve_path(file_path)

        # Only capture first time
        if abs_path in self._baselines:
            return

        if abs_path.exists():
            try:
                content = abs_path.read_bytes()
                mode = self._get_file_mode(abs_path)
                oid = self._compute_blob_oid(content)
            except (OSError, IOError) as e:
                logger.warning(f"Failed to capture baseline for {file_path}: {e}")
                content = None
                mode = 0o644
                oid = self.ZERO_OID
        else:
            # File doesn't exist - will be treated as add
            content = None
            mode = 0o644
            oid = self.ZERO_OID

        self._baselines[abs_path] = FileBaseline(
            original_path=abs_path,
            content=content,
            mode=mode,
            oid=oid,
        )

        # Initialize path mapping
        self._path_mappings[abs_path] = abs_path

    def record_rename(self, old_path: Path, new_path: Path) -> None:
        """Record a file rename/move."""
        old_abs = self._resolve_path(old_path)
        new_abs = self._resolve_path(new_path)

        # Ensure baseline is captured
        if old_abs not in self._baselines:
            self.capture_baseline(old_path)

        # Update path mapping
        self._path_mappings[old_abs] = new_abs

    def get_unified_diff(self) -> Optional[str]:
        """
        Generate a unified diff of all changes.

        Returns:
            Git-format unified diff string, or None if no changes
        """
        changes = self._compute_changes()

        if not changes:
            return None

        # Sort by path for deterministic output
        changes.sort(key=lambda c: str(c.original_path))

        diff_parts = []
        for change in changes:
            diff = self._generate_file_diff(change)
            if diff:
                diff_parts.append(diff)

        if not diff_parts:
            return None

        return "\n".join(diff_parts)

    def get_changes_summary(self) -> Dict[str, Any]:
        """Get a summary of all tracked changes."""
        changes = self._compute_changes()

        adds = [c for c in changes if c.change_type == ChangeType.ADD]
        deletes = [c for c in changes if c.change_type == ChangeType.DELETE]
        modifies = [c for c in changes if c.change_type == ChangeType.MODIFY]
        renames = [c for c in changes if c.change_type == ChangeType.RENAME]

        return {
            "total_changes": len(changes),
            "additions": len(adds),
            "deletions": len(deletes),
            "modifications": len(modifies),
            "renames": len(renames),
            "files_added": [str(c.current_path) for c in adds],
            "files_deleted": [str(c.original_path) for c in deletes],
            "files_modified": [str(c.current_path) for c in modifies],
            "files_renamed": [(str(c.original_path), str(c.current_path)) for c in renames],
        }

    def _resolve_path(self, file_path: Path) -> Path:
        """Resolve to absolute path."""
        if file_path.is_absolute():
            return file_path
        return self.project_root / file_path

    def _relative_path(self, abs_path: Path) -> str:
        """Get path relative to git root for display."""
        try:
            return str(abs_path.relative_to(self.git_root))
        except ValueError:
            return str(abs_path)

    def _compute_changes(self) -> List[FileChange]:
        """Compute all file changes from baselines to current state."""
        changes = []

        for original_path, baseline in self._baselines.items():
            current_path = self._path_mappings.get(original_path, original_path)

            # Determine change type
            current_exists = current_path.exists()
            baseline_exists = baseline.exists
            is_rename = original_path != current_path

            if not baseline_exists and current_exists:
                change_type = ChangeType.ADD
            elif baseline_exists and not current_exists:
                change_type = ChangeType.DELETE
            elif is_rename:
                change_type = ChangeType.RENAME
            else:
                # Check if content changed
                if current_exists:
                    try:
                        current_content = current_path.read_bytes()
                        if current_content == baseline.content:
                            continue  # No change
                    except (OSError, IOError):
                        continue
                change_type = ChangeType.MODIFY

            changes.append(
                FileChange(
                    change_type=change_type,
                    original_path=original_path,
                    current_path=current_path,
                    baseline=baseline,
                    original_display=self._relative_path(original_path),
                    current_display=self._relative_path(current_path),
                )
            )

        return changes

    def _generate_file_diff(self, change: FileChange) -> str:
        """Generate unified diff for a single file change."""
        lines = []

        # Git diff header
        a_path = f"a/{change.original_display}"
        b_path = f"b/{change.current_display}"

        lines.append(f"diff --git {a_path} {b_path}")

        # Handle different change types
        if change.change_type == ChangeType.ADD:
            current_mode = self._get_file_mode(change.current_path)
            lines.append(f"new file mode {current_mode:o}")

            current_content = self._read_file_safe(change.current_path)
            current_oid = (
                self._compute_blob_oid(current_content) if current_content else self.ZERO_OID
            )

            lines.append(f"index {self.ZERO_OID}..{current_oid}")
            lines.append(f"--- {self.DEV_NULL}")
            lines.append(f"+++ {b_path}")

            if current_content:
                lines.extend(self._text_diff("", current_content.decode("utf-8", errors="replace")))

        elif change.change_type == ChangeType.DELETE:
            lines.append(f"deleted file mode {change.baseline.mode:o}")
            lines.append(f"index {change.baseline.oid}..{self.ZERO_OID}")
            lines.append(f"--- {a_path}")
            lines.append(f"+++ {self.DEV_NULL}")

            if change.baseline.content:
                lines.extend(
                    self._text_diff(change.baseline.content.decode("utf-8", errors="replace"), "")
                )

        else:  # MODIFY or RENAME
            current_content = self._read_file_safe(change.current_path)
            current_oid = (
                self._compute_blob_oid(current_content) if current_content else self.ZERO_OID
            )
            current_mode = self._get_file_mode(change.current_path)

            # Mode change
            if change.baseline.mode != current_mode:
                lines.append(f"old mode {change.baseline.mode:o}")
                lines.append(f"new mode {current_mode:o}")

            lines.append(f"index {change.baseline.oid}..{current_oid}")
            lines.append(f"--- {a_path}")
            lines.append(f"+++ {b_path}")

            # Content diff
            old_text = ""
            new_text = ""

            if change.baseline.content:
                old_text = change.baseline.content.decode("utf-8", errors="replace")
            if current_content:
                new_text = current_content.decode("utf-8", errors="replace")

            lines.extend(self._text_diff(old_text, new_text))

        return "\n".join(lines)

    def _text_diff(self, old_text: str, new_text: str) -> List[str]:
        """Generate unified diff hunks for text content."""
        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm="",
        )

        # Skip the header lines (--- and +++)
        result = []
        for i, line in enumerate(diff):
            if i < 2:  # Skip header
                continue
            # Remove trailing newline for clean output
            result.append(line.rstrip("\n\r"))

        return result

    def _read_file_safe(self, file_path: Path) -> Optional[bytes]:
        """Safely read file content."""
        try:
            if file_path.exists():
                return file_path.read_bytes()
        except (OSError, IOError):
            pass
        return None

    def _get_file_mode(self, file_path: Path) -> int:
        """Get file mode (permissions)."""
        try:
            stat = file_path.stat()
            # Check if executable
            if stat.st_mode & 0o111:
                return 0o100755
            return 0o100644
        except (OSError, IOError):
            return 0o100644

    def _compute_blob_oid(self, content: bytes) -> str:
        """Compute git-style blob SHA-1."""
        # Git blob format: "blob <size>\0<content>"
        header = f"blob {len(content)}\0".encode()
        data = header + content
        return hashlib.sha1(data).hexdigest()

    def clear(self) -> None:
        """Clear all tracked baselines."""
        self._baselines.clear()
        self._path_mappings.clear()


class DiffTrackerContext:
    """Context manager for automatic diff tracking."""

    def __init__(self, project_root: Path):
        self.tracker = DiffTracker(project_root)

    def __enter__(self) -> DiffTracker:
        return self.tracker

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass  # Tracker is preserved for getting diff after context


def generate_patch_file(
    project_root: Path,
    tracker: DiffTracker,
    output_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Generate a patch file from tracked changes.

    Args:
        project_root: Project root directory
        tracker: DiffTracker with captured changes
        output_path: Optional output path for patch file

    Returns:
        Path to generated patch file, or None if no changes
    """
    diff = tracker.get_unified_diff()

    if not diff:
        return None

    if output_path is None:
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = (
            project_root / ".superqode" / "qe-artifacts" / "patches" / f"qe-{timestamp}.patch"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(diff)

    return output_path
