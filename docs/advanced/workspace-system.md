# Workspace System

The workspace system protects your repository by tracking all file changes, blocking destructive git operations, and reverting everything when the session ends. Only generated artifacts (patches, tests, reports) persist.

---

## Overview

SuperQode's workspace system provides ephemeral edit isolation with an immutable repo guarantee during agent sessions. Every file change is captured against a baseline, destructive git commands are blocked at the shell level, and all modifications are reverted when the session completes. The repository itself is never permanently modified by an agent session only explicitly persisted artifacts survive.

---

## Components

### GitGuard

GitGuard intercepts and filters git commands during a session to prevent accidental or malicious repository mutation.

- Blocks git write/destructive operations: commit, push, merge, rebase, reset, checkout, clean, add, rm, and similar commands.
- Allows read-only operations: status, log, diff, show, branch --list.
- Unknown git commands are blocked by default for safety.
- Raises `GitOperationBlocked` with a suggested alternative when a command is blocked.

### DiffTracker

DiffTracker captures file baselines before any modification and produces git-format unified diffs from the changes made during a session.

- Captures file content before modification.
- Generates git-format unified diffs from captured changes.
- Tracks adds, deletes, modifies, and renames.
- Outputs patch files to `.superqode/artifacts/patches/`.

### SnapshotManager

SnapshotManager preserves file state before changes and performs a full reversion when the session ends.

- Captures file state before modification (in-memory, with disk backup for files over 10MB).
- Full reversion on session end: restored modified files, recreated deleted files.
- Idempotent capture first capture only per file per session.

### GitSnapshotManager

GitSnapshotManager uses the git object database for robust snapshot management.

- Creates git-backed snapshots of tracked files.
- Supports restore, diff against snapshot, and cleanup of old snapshots.

### GitWorktreeManager

GitWorktreeManager creates isolated git worktrees pinned to a specific commit.

- Creates isolated git worktrees pinned to a specific commit.
- Optionally copies uncommitted changes and preserves gitignored files such as build caches.
- Worktrees stored in `~/.superqode/working/{repo-name}/qe/`.
- Automatic stale cleanup after 24 hours.

### DirectoryWatcher / PollingWatcher

Real-time file change detection with configurable behavior.

- Real-time change detection via watchdog with automatic polling fallback.
- Configurable ignore patterns, extension filters, and debounce interval.
- Callbacks for sync and async change handling.
- Async generator interface for streaming changes.

### WorkspaceCoordinator

WorkspaceCoordinator provides locking and an epoch system to prevent concurrent deep sessions.

- Only one deep session per repository at a time; quick scans can run in parallel.
- Auto-cleans stale locks from dead processes.
- Epoch-based staleness detection.

### ArtifactManager

ArtifactManager persists artifacts that survive workspace reset.

- Preserves patches, generated tests, reports, and logs.
- Organized under `.superqode/artifacts/` with a JSON manifest index.
- Supported artifact types: PATCH, SUGGESTED_FIX, TEST_UNIT, TEST_INTEGRATION, TEST_E2E, QR (Quality Report), COVERAGE, SUMMARY, LOG, TRACE, ERROR.

### change_summary

Captures git-visible changes and renders summaries in multiple formats.

- Captures changes via `git status --porcelain` and `git diff --numstat`.
- Render modes:
  - `summary`: one-liner overview.
  - `files`: file list with per-file statistics.
  - `diff`: full unified diff.
  - `none`: no output.

---

## CLI Integration

The workspace system is controlled through the SuperQode CLI:

- `--changes` flag: controls change summary output. Values are `summary` (default), `files`, `diff`, `none`.
- `--sandbox git-worktree` flag: creates a git worktree for full filesystem isolation.
- `superqode trust status` and `superqode doctor` check workspace sensitivity and report any issues.

---

## Python API

```python
from superqode.workspace import WorkspaceManager, DiffTracker, GitGuard

# Guard against git operations
guard = GitGuard()
if guard.is_blocked("git commit -m 'test'"):
    analysis = guard.analyze("git commit -m 'test'")

# Track file diffs
tracker = DiffTracker(project_root)
tracker.capture_baseline("src/main.py")
# ... make changes ...
diff = tracker.get_unified_diff()

# Context manager for workspace sessions
wm = WorkspaceManager(project_root)
async with wm.qe_session("session-001") as session:
    session.write_file("src/main.py", "new content")
    content = session.read_file("src/utils.py")
```

---

## See Also

- [Session Management](session-management.md) - Session lifecycle and configuration
- [Safety & Permissions](safety-permissions.md) - Sandbox and approval policy
- [Advanced Features Index](index.md) - All advanced features
