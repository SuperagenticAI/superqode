"""
QE Coordinator - Session coordination with locking and epoch system.

Inspired by EveryCode's review_coord.rs implementation.

Features:
- Lock-based coordination prevents concurrent deep QE runs
- Snapshot epochs detect if files changed during QE (stale results)
- Per-repo scoping using path hash
- Automatic cleanup of stale locks from dead processes

Usage:
    coordinator = QECoordinator(project_root)

    # Try to acquire lock
    lock = coordinator.acquire_lock("qe-session-001", mode="deep")
    if lock is None:
        print("Another QE session is running")
        return

    try:
        # Run QE...

        # Check if results are stale
        if coordinator.is_result_stale(lock):
            print("Warning: Code changed during QE run")
    finally:
        coordinator.release_lock(lock)
"""

import hashlib
import json
import os
import signal
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class QELock:
    """Lock information for a QE session."""

    session_id: str
    pid: int
    started_at: str  # ISO format
    mode: str  # "quick" or "deep"
    git_head: Optional[str]
    snapshot_epoch: int
    intent: str  # Description of the QE task

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QELock":
        return cls(**data)


class QECoordinator:
    """
    Coordinate QE sessions to prevent conflicts and detect stale results.

    Guarantees:
    - Only one deep QE session at a time per repository
    - Quick scans can run in parallel
    - Detects if code changed during QE (stale results)
    - Auto-cleanup of locks from dead processes
    """

    STATE_DIR = Path.home() / ".superqode" / "state" / "qe"

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self._scope_dir: Optional[Path] = None

    @property
    def scope_key(self) -> str:
        """Get a unique key for this repository scope."""
        # Use CRC32-like hash of path for uniqueness
        path_bytes = str(self.project_root).encode()
        return hashlib.md5(path_bytes).hexdigest()[:8]

    @property
    def scope_dir(self) -> Path:
        """Get the state directory for this repository scope."""
        if self._scope_dir is None:
            state_dir = Path(os.environ.get("SUPERQODE_STATE_DIR", self.STATE_DIR))
            self._scope_dir = state_dir / f"repo-{self.scope_key}"
            self._scope_dir.mkdir(parents=True, exist_ok=True)
        return self._scope_dir

    @property
    def lock_file(self) -> Path:
        return self.scope_dir / "qe.lock"

    @property
    def epoch_file(self) -> Path:
        return self.scope_dir / "snapshot.epoch"

    # =========================================================================
    # Epoch System - Detect file changes during QE
    # =========================================================================

    def get_snapshot_epoch(self) -> int:
        """Get the current snapshot epoch."""
        if not self.epoch_file.exists():
            return 0
        try:
            return int(self.epoch_file.read_text().strip())
        except (ValueError, OSError):
            return 0

    def bump_snapshot_epoch(self) -> int:
        """
        Increment the snapshot epoch.

        Call this whenever files change (git operations, file edits, etc.)
        """
        current = self.get_snapshot_epoch()
        new_epoch = current + 1
        self.epoch_file.write_text(str(new_epoch))
        return new_epoch

    def is_result_stale(self, lock: QELock) -> bool:
        """
        Check if QE results are stale due to code changes.

        Returns True if the snapshot epoch changed since the lock was acquired.
        """
        current_epoch = self.get_snapshot_epoch()
        return current_epoch > lock.snapshot_epoch

    # =========================================================================
    # Locking System - Coordinate QE sessions
    # =========================================================================

    def acquire_lock(
        self,
        session_id: str,
        mode: str = "quick",
        intent: str = "QE session",
    ) -> Optional[QELock]:
        """
        Try to acquire a QE lock.

        Args:
            session_id: Unique session identifier
            mode: "quick" or "deep"
            intent: Description of the QE task

        Returns:
            QELock if acquired, None if another session holds the lock
        """
        # Clean up stale locks first
        self._clear_stale_locks()

        # Check existing lock
        existing = self.read_lock()
        if existing is not None:
            # Deep QE blocks everything
            if existing.mode == "deep":
                logger.info(f"Blocked by deep QE session: {existing.session_id}")
                return None

            # New deep QE blocks if any session exists
            if mode == "deep":
                logger.info(f"Cannot start deep QE - session active: {existing.session_id}")
                return None

        # Create new lock
        lock = QELock(
            session_id=session_id,
            pid=os.getpid(),
            started_at=datetime.now().isoformat(),
            mode=mode,
            git_head=self._get_git_head(),
            snapshot_epoch=self.get_snapshot_epoch(),
            intent=intent,
        )

        try:
            # Atomic write - create new file only
            fd = os.open(
                str(self.lock_file),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
            with os.fdopen(fd, "w") as f:
                json.dump(lock.to_dict(), f, indent=2)

            logger.info(f"Acquired QE lock: {session_id} ({mode})")
            return lock

        except FileExistsError:
            # Another process acquired the lock between check and create
            logger.info("Lock acquisition race - another session won")
            return None

    def release_lock(self, lock: QELock) -> None:
        """Release a QE lock."""
        if not self.lock_file.exists():
            return

        try:
            current = self.read_lock()
            if current and current.session_id == lock.session_id:
                self.lock_file.unlink()
                logger.info(f"Released QE lock: {lock.session_id}")
        except OSError as e:
            logger.warning(f"Failed to release lock: {e}")

    def read_lock(self) -> Optional[QELock]:
        """Read the current lock if any."""
        if not self.lock_file.exists():
            return None

        try:
            data = json.loads(self.lock_file.read_text())
            return QELock.from_dict(data)
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def _clear_stale_locks(self) -> bool:
        """
        Remove stale locks from dead processes.

        Returns True if a stale lock was cleared.
        """
        lock = self.read_lock()
        if lock is None:
            return False

        if self._is_process_alive(lock.pid):
            return False

        # Process is dead - remove stale lock
        try:
            self.lock_file.unlink()
            logger.info(f"Cleared stale lock from dead process: PID {lock.pid}")
            return True
        except OSError:
            return False

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            # Signal 0 checks if process exists without sending signal
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we don't have permission
            return True

    def _get_git_head(self) -> Optional[str]:
        """Get the current git HEAD commit."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            pass
        return None

    # =========================================================================
    # Context Manager Support
    # =========================================================================

    def session(
        self,
        session_id: str,
        mode: str = "quick",
        intent: str = "QE session",
    ) -> "QESessionContext":
        """
        Context manager for QE sessions.

        Usage:
            with coordinator.session("my-session", mode="deep") as lock:
                if lock:
                    # Run QE...
        """
        return QESessionContext(self, session_id, mode, intent)


class QESessionContext:
    """Context manager for QE sessions with automatic lock management."""

    def __init__(
        self,
        coordinator: QECoordinator,
        session_id: str,
        mode: str,
        intent: str,
    ):
        self.coordinator = coordinator
        self.session_id = session_id
        self.mode = mode
        self.intent = intent
        self.lock: Optional[QELock] = None

    def __enter__(self) -> Optional[QELock]:
        self.lock = self.coordinator.acquire_lock(
            self.session_id,
            self.mode,
            self.intent,
        )
        return self.lock

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.lock:
            self.coordinator.release_lock(self.lock)


# =============================================================================
# Global Epoch Notification
# =============================================================================

_global_coordinator: Optional[QECoordinator] = None


def set_global_coordinator(coordinator: QECoordinator) -> None:
    """Set the global coordinator for epoch notifications."""
    global _global_coordinator
    _global_coordinator = coordinator


def notify_file_change() -> None:
    """
    Notify that files have changed.

    Call this from file write operations to update the epoch.
    """
    if _global_coordinator:
        _global_coordinator.bump_snapshot_epoch()


def get_global_coordinator() -> Optional[QECoordinator]:
    """Get the global coordinator if set."""
    return _global_coordinator
