"""
SuperQode Workspace Module.

Provides ephemeral-edit workspace with immutable repo guarantee.
Agents can freely modify code for QA without touching the repo permanently.

Features:
- Git worktree-based isolation
- QE session coordination with locking
- Diff tracking for patch generation
- Artifact management
- Git-based snapshots for robust state tracking
- Real-time file system watching
"""

from .manager import WorkspaceManager, WorkspaceState
from .artifacts import ArtifactManager, ArtifactType
from .git_guard import GitGuard, GitOperationBlocked
from .snapshot import SnapshotManager
from .worktree import GitWorktreeManager, WorktreeInfo, prepare_qe_worktree
from .coordinator import QECoordinator, QELock, notify_file_change
from .diff_tracker import DiffTracker, ChangeType, generate_patch_file

# New advanced features
from .git_snapshot import (
    GitSnapshotManager,
    Snapshot,
    FileChange as SnapshotFileChange,
    FileStatus,
    create_git_snapshot_manager,
)
from .watcher import (
    DirectoryWatcher,
    PollingWatcher,
    WatcherConfig,
    FileChange as WatcherFileChange,
    ChangeType as WatcherChangeType,
    create_watcher,
)

__all__ = [
    # Core managers
    "WorkspaceManager",
    "WorkspaceState",
    "ArtifactManager",
    "ArtifactType",
    "GitGuard",
    "GitOperationBlocked",
    "SnapshotManager",
    # Git worktree
    "GitWorktreeManager",
    "WorktreeInfo",
    "prepare_qe_worktree",
    # Coordination
    "QECoordinator",
    "QELock",
    "notify_file_change",
    # Diff tracking
    "DiffTracker",
    "ChangeType",
    "generate_patch_file",
    # Git-based snapshots
    "GitSnapshotManager",
    "Snapshot",
    "SnapshotFileChange",
    "FileStatus",
    "create_git_snapshot_manager",
    # Directory watching
    "DirectoryWatcher",
    "PollingWatcher",
    "WatcherConfig",
    "WatcherFileChange",
    "WatcherChangeType",
    "create_watcher",
]
