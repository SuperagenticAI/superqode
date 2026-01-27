<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Workspace Internals

The workspace system is the foundation of SuperQode's sandbox-first approach. This document explains how ephemeral workspaces provide safe, isolated environments for quality engineering.

Note: Workspace management commands shown in this document are available in SuperQode Enterprise only.

---

## Overview

The workspace manager creates isolated environments where agents can freely modify, test, and break code without affecting your original files. All changes are tracked and reverted after the session completes.

```
┌─────────────────────────────────────────────────────────────┐
│                    WORKSPACE LIFECYCLE                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Original Code ──► Create Snapshot ──► Run QE Session       │
│        │                                      │              │
│        │                                      ▼              │
│        │                              Agents Modify Code     │
│        │                                      │              │
│        │                                      ▼              │
│        │                              Track All Changes      │
│        │                                      │              │
│        │                                      ▼              │
│        │                              Generate Reports       │
│        │                                      │              │
│        │                                      ▼              │
│        └───────────────────────────── Revert Changes         │
│                                              │              │
│                                              ▼              │
│                                      Preserve Artifacts      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Isolation Modes

SuperQode supports three isolation modes:

### 1. Git Worktree Mode (Optional)

Uses Git's worktree feature to create a separate working directory:

```bash
# SuperQode creates:
.git/worktrees/superqode-qe-abc123/
├── HEAD
├── index
└── ...

# And a working directory:
~/.superqode/working/<repo>/qe/<session-id>/
├── src/
├── tests/
└── ...
```

**Advantages:**
- Fast creation (no file copying)
- Full git history available
- True isolation from main working tree
- Efficient disk usage

**When Used:**
- Enabled with `superqe run . --worktree`
- Project is a git repository
- Git version >= 2.15

### 2. Snapshot Mode

Creates a complete copy of the project directory:

```bash
# Original:
/path/to/project/
├── src/
├── tests/
└── ...

# Snapshot:
/tmp/superqode-snapshot-abc123/
├── src/
├── tests/
└── ...
```

**Advantages:**
- Works with non-git projects
- Simple and reliable
- Complete isolation

**When Used:**
- Not a git repository
- Git worktree unavailable
- Explicitly requested

### 3. Git Snapshot Mode

Uses git stash to save and restore state:

```bash
# Before QE:
git stash push -m "superqode-backup-abc123"

# After QE:
git stash pop
```

**Advantages:**
- Lightweight
- Fast
- Preserves uncommitted changes

**When Used:**
- Simple QE sessions
- Quick rollback needed

---

## Component Details

### Workspace Manager

The manager (`workspace/manager.py`) orchestrates the workspace lifecycle:

```python
class WorkspaceManager:
    def create_workspace(self, mode: str) -> Workspace:
        """Create isolated workspace."""

    def enter_workspace(self) -> None:
        """Switch to workspace context."""

    def exit_workspace(self, preserve: bool = False) -> None:
        """Exit and optionally preserve workspace."""

    def revert(self) -> None:
        """Revert all changes."""

    def get_artifacts(self) -> list[Artifact]:
        """Get generated artifacts."""
```

### Snapshot System

The snapshot system (`workspace/snapshot.py`) handles file copying:

| Method | Description |
|--------|-------------|
| `create_snapshot()` | Copy project to temp directory |
| `restore_snapshot()` | Restore original state |
| `get_diff()` | Get changes since snapshot |
| `cleanup()` | Remove snapshot directory |

### Git Worktree System

The worktree system (`workspace/worktree.py`) manages git worktrees:

| Method | Description |
|--------|-------------|
| `create_worktree()` | Create new git worktree |
| `remove_worktree()` | Remove worktree |
| `sync_changes()` | Sync changes to main tree |
| `get_worktree_path()` | Get worktree directory path |

---

## Git Guard

The Git Guard (`workspace/git_guard.py`) prevents accidental git operations:

### Protected Operations

| Operation | Behavior |
|-----------|----------|
| `git commit` | Blocked with warning |
| `git push` | Blocked with warning |
| `git checkout` | Allowed (read-only) |
| `git stash` | Blocked (managed by SuperQode) |
| `git reset --hard` | Blocked |

### Implementation

```python
class GitGuard:
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self._install_hooks()

    def _install_hooks(self):
        """Install pre-commit/pre-push hooks."""
        # Hooks block dangerous operations

    def allow_operation(self, operation: str) -> bool:
        """Check if git operation is allowed."""
```

### Bypass for Advanced Users

```bash
# Force allow git operations (use with caution)
superqe run . --allow-git-operations
```

---

## Diff Tracking

The diff tracker (`workspace/diff_tracker.py`) monitors all file changes:

### Tracked Information

| Field | Description |
|-------|-------------|
| `file_path` | Relative path to file |
| `change_type` | created, modified, deleted |
| `original_content` | Content before change |
| `new_content` | Content after change |
| `timestamp` | When change occurred |
| `agent_id` | Which agent made the change |

### Usage

```python
tracker = DiffTracker(workspace)

# Track a change
tracker.record_change(
    file_path="src/api.py",
    change_type="modified",
    original=original_content,
    new=new_content
)

# Get all changes
changes = tracker.get_all_changes()

# Generate unified diff
diff = tracker.generate_unified_diff()
```

---

## Artifact Storage

Artifacts are stored in `.superqode/qe-artifacts/`:

```
.superqode/qe-artifacts/
├── manifest.json
├── qr/
│   ├── qr-<date>-<session>.json    # Quality Report (JSON)
│   └── qr-<date>-<session>.md      # Quality Report (Markdown)
├── patches/
│   └── ...                         # Suggested patch files (when available)
├── generated-tests/
│   └── ...                         # Generated tests (when available)
├── logs/
│   └── ...                         # Execution logs / work logs (if enabled)
└── evidence/
    └── ...                         # Screenshots, traces, captured outputs
```

### Artifact Types

| Type | Extension | Description |
|------|-----------|-------------|
| **Quality Report** | `.json` | Structured findings |
| **Markdown Report** | `.md` | Human-readable report |
| **Patches** | `.patch` | Suggested fixes (when available) |
| **Generated Tests** | `.py`, `.js` | New test files (when available) |
| **Logs / Evidence** | varies | Captured outputs, traces, logs (if enabled) |
| **Manifest** | `.json` | Artifact index (`manifest.json`) |

---

## Coordinator

The coordinator (`workspace/coordinator.py`) manages multi-agent sessions:

### Responsibilities

- Prevent conflicting file edits
- Serialize access to shared resources
- Merge changes from multiple agents
- Resolve conflicts

### Conflict Resolution

```
Agent A: Edit src/api.py (lines 10-20)
Agent B: Edit src/api.py (lines 50-60)
         ──► No conflict, both allowed

Agent A: Edit src/api.py (lines 10-20)
Agent B: Edit src/api.py (lines 15-25)
         ──► Conflict detected!
         ──► Agent B must wait or merge
```

---

## File Watcher

The watcher (`workspace/watcher.py`) monitors filesystem changes:

### Features

- Real-time change detection
- Debounced notifications
- Ignore patterns (node_modules, .git)
- Event types: created, modified, deleted, moved

### Configuration

```yaml
workspace:
  watcher:
    enabled: true
    debounce_ms: 100
    ignore_patterns:
      - "node_modules/**"
      - ".git/**"
      - "*.pyc"
      - "__pycache__/**"
```

---

## Revert Guarantees

SuperQode guarantees original code is preserved:

### Revert Process

1. **Session Ends** - QE session completes (success or error)
2. **Artifacts Saved** - All findings/patches stored
3. **Changes Reverted** - Workspace changes undone
4. **Worktree Removed** - Temporary worktree deleted
5. **Original Restored** - Main working tree unchanged

### Error Handling

```
Session Error
     │
     ▼
Save Artifacts (if possible)
     │
     ▼
Attempt Revert
     │
     ├──► Success: Clean state
     │
     └──► Failure: Preserve workspace for debugging
                   Log recovery instructions
```

### Manual Recovery

If automatic revert fails:

```bash
# List preserved workspaces
superqode workspace list

# Manually revert a workspace
superqode workspace revert --session abc123

# Force cleanup (dangerous)
superqode workspace cleanup --force
```

---

## Debugging Options

### Preserve Workspace

Keep the workspace after session for debugging:

```bash
superqe run . --preserve-workspace
```

### Skip Revert

Don't revert changes (for applying fixes):

```bash
superqe run . --no-revert
```

### Workspace Info

Inspect current workspace state:

```bash
superqode workspace info

# Output:
# Workspace: /tmp/superqode-qe-abc123
# Mode: worktree
# Created: 2024-01-15 10:30:45
# Changes: 5 files modified
# Status: active
```

### View Changes

See all changes made in workspace:

```bash
superqode workspace diff

# Or for specific session
superqode workspace diff --session abc123
```

---

## Configuration

```yaml
workspace:
  # Default isolation mode: snapshot, worktree, git_snapshot
  default_mode: snapshot

  # Preserve on error for debugging
  preserve_on_error: true

  # Cleanup old workspaces after N hours
  cleanup_after_hours: 24

  # Maximum workspace size (MB)
  max_size_mb: 1000

  # Files to exclude from snapshot
  exclude_patterns:
    - "node_modules/**"
    - ".git/**"
    - "*.pyc"
    - "venv/**"
    - ".venv/**"
```

---

## Related Documentation

- [Architecture Overview](architecture.md) - System architecture
- [Safety & Permissions](safety-permissions.md) - Security model
- [Ephemeral Workspace Concept](../concepts/workspace.md) - User guide
- [Session Management](session-management.md) - Session handling
