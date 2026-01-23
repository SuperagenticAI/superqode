# Ephemeral Workspace

SuperQode uses ephemeral workspaces to ensure your code is never modified without consent. This page explains how workspace isolation works and why it's critical for safe QE.

---

## The Workspace Guarantee

!!! success "Core Guarantee"
    **Your original code is ALWAYS preserved.** SuperQode tests in an isolated sandbox and reverts all changes after each session.

```
┌─────────────────────────────────────────────────────────────┐
│                    QE SESSION LIFECYCLE                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. SNAPSHOT         Original code preserved                 │
│        ↓                                                     │
│  2. QE SANDBOX       Agents freely modify, inject tests,    │
│        │             run experiments, break things           │
│        ↓                                                     │
│  3. REPORT           Document what was done, what was found │
│        ↓                                                     │
│  4. REVERT           All changes removed, original restored │
│        ↓                                                     │
│  5. ARTIFACTS        Patches, tests, reports preserved      │
│                      (in .superqode/qe-artifacts/)          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Why Ephemeral Workspaces?

### 1. Safety

Agents can test destructively without risk:

- Inject test code
- Modify configurations
- Stress systems
- Break things intentionally

All without affecting your actual codebase.

### 2. Freedom

In the sandbox, agents can:

- Perform destructive testing
- Simulate malicious inputs
- Run load tests
- Explore edge cases aggressively

### 3. Reproducibility

The original state is always known:

- Every session starts from a clean state
- Results are reproducible
- No accumulated drift

### 4. Trust

You can trust SuperQode because:

- Default behavior is read-only
- Changes require explicit consent
- Revert is automatic and guaranteed

---

## Workspace Isolation Methods

SuperQode supports multiple isolation methods:

### 1. Git Worktree Isolation (Optional)

Uses Git worktrees for lightweight isolation when enabled with `--worktree`:

```bash
# SuperQode creates a worktree internally
git worktree add ~/.superqode/working/<repo>/qe/<session-id> HEAD

# QE runs in the worktree
# Original repository is untouched

# After QE, worktree is cleaned up
git worktree remove ~/.superqode/working/<repo>/qe/<session-id>
```

**Advantages:**
- Fast setup
- Low disk usage (uses Git's COW)
- Perfect isolation for Git repositories

**Usage:** Enable with `superqe run . --worktree` in Git repositories.
**Note:** Worktree isolation writes to `.git/worktrees`. Use it only if you are comfortable with git metadata changes.

### 2. Directory Snapshot

For non-Git projects, creates a directory copy:

```bash
# SuperQode snapshots the directory
cp -r . .superqode/sandbox

# QE runs in the sandbox
# Original directory is untouched

# After QE, sandbox is removed
rm -rf .superqode/sandbox
```

**Advantages:**
- Works with any project
- Simple and reliable

---

## Snapshot System

### What Gets Snapshotted

| Item | Snapshotted | Notes |
|------|-------------|-------|
| Source code files | ✓ | All tracked files |
| Configuration files | ✓ | .env, config files |
| Test files | ✓ | Existing tests |
| Dependencies | ✗ | node_modules, venv |
| Build artifacts | ✗ | dist, build |
| Git history | ✓ | Full history preserved |

### Snapshot Metadata

Each snapshot includes:

```json
{
  "snapshot_id": "snap-20240118-143022",
  "created_at": "2024-01-18T14:30:22Z",
  "method": "git_worktree",
  "base_commit": "abc123def",
  "files_count": 142,
  "total_size_bytes": 2458624
}
```

---

## Change Tracking

During QE, all changes are tracked:

### File Changes

```json
{
  "file_path": "src/api/users.py",
  "change_type": "modified",
  "original_hash": "sha256:abc...",
  "modified_hash": "sha256:def...",
  "diff_lines": 15,
  "timestamp": "2024-01-18T14:32:45Z"
}
```

### Change Types

| Type | Description |
|------|-------------|
| `created` | New file added |
| `modified` | Existing file changed |
| `deleted` | File removed |
| `renamed` | File moved/renamed |

---

## Git Guard

During QE sessions, dangerous Git operations are blocked:

### Blocked Operations

| Operation | Status | Reason |
|-----------|--------|--------|
| `git commit` | Blocked | Prevents accidental commits |
| `git push` | Blocked | Prevents pushing test changes |
| `git checkout` | Blocked | Prevents branch switching |
| `git reset --hard` | Blocked | Prevents destructive resets |

### Allowed Operations

| Operation | Status | Purpose |
|-----------|--------|---------|
| `git status` | Allowed | View changes |
| `git diff` | Allowed | Inspect modifications |
| `git log` | Allowed | View history |
| `git show` | Allowed | View commits |

### Git Guard Configuration

```yaml
# superqode.yaml
qe:
  git_guard:
    enabled: true
    allow_status: true
    allow_diff: true
    block_commit: true
    block_push: true
```

---

## Revert Mechanism

### Automatic Revert

After every QE session:

1. **Change Detection**: All modifications identified
2. **Artifact Extraction**: Patches and tests saved
3. **State Restoration**: Original files restored
4. **Verification**: Hash comparison confirms restore

### Manual Revert

If needed, manually trigger revert:

```bash
# View pending changes
superqe status

# Force revert
superqe revert --force
```

### Revert Verification

SuperQode verifies the revert succeeded:

```
✓ Revert Complete
  Files restored: 12
  Original hash: sha256:abc123...
  Current hash: sha256:abc123...
  Status: Verified
```

---

## Artifact Preservation

While changes are reverted, artifacts are preserved:

### Artifact Location

```
.superqode/qe-artifacts/
├── manifest.json
├── qr/
│   ├── qr-<date>-<session>.md
│   └── qr-<date>-<session>.json
├── patches/
│   └── ...                         # Suggested patch files (when available)
├── generated-tests/
│   └── ...                         # Generated tests (when available)
├── logs/
│   └── ...                         # Execution logs / work logs (if enabled)
└── evidence/
    └── ...                         # Screenshots, traces, captured outputs
```

### Patch Format

Patches are in unified diff format:

```diff
--- a/src/api/users.py
+++ b/src/api/users.py
@@ -42,7 +42,7 @@ def search_users(query: str):
-    sql = f"SELECT * FROM users WHERE name LIKE '%{query}%'"
+    sql = "SELECT * FROM users WHERE name LIKE ?"
+    params = (f"%{query}%",)
     cursor.execute(sql, params)
```

### Applying Patches

After review, apply patches manually:

```bash
# Preview the patch
cat .superqode/qe-artifacts/patches/fix-sql-injection.patch

# Apply the patch
git apply .superqode/qe-artifacts/patches/fix-sql-injection.patch

# Or use SuperQode
superqode suggestions apply fix-sql-injection
```

---

## Session Recovery

If a session is interrupted:

### Automatic Recovery

SuperQode detects incomplete sessions:

```
WARNING:  Incomplete QE session detected
    Session: qe-session-20240118-143022
    Status: interrupted

Options:
  1. Resume session
  2. Revert and discard
  3. View changes before deciding

Choice: _
```

### Manual Recovery

```bash
# List sessions
superqe status --all

# Recover specific session
superqe recover qe-session-20240118-143022

# Force clean (discard session)
superqe clean --force
```

---

## Workspace Configuration

### Default Settings

```yaml
# superqode.yaml
qe:
  workspace:
    method: auto  # auto, git_worktree, snapshot
    location: .superqode/sandbox
    preserve_artifacts: true
    cleanup_on_success: true
    cleanup_on_failure: false
```

### Method Selection

| Method | When Used |
|--------|-----------|
| `auto` | Snapshot isolation unless worktree is explicitly enabled |
| `git_worktree` | Use worktree isolation (Git repos only) |
| `snapshot` | Non-Git directory |

### Custom Location

```yaml
qe:
  workspace:
    location: /tmp/superqode-sandbox
```

---

## Best Practices

### 1. Use Git Repositories

Git worktree isolation is the most efficient:

```bash
# Initialize Git if not already
git init
git add .
git commit -m "Initial commit"
```

### 2. Configure Ignores

Exclude large files from snapshots:

```
# .superqodeignore
node_modules/
venv/
.venv/
dist/
build/
*.log
```

### 3. Clean Up Artifacts

Periodically clean old artifacts:

```bash
# Clean artifacts older than 7 days
superqe artifacts --clean --older-than 7d
```

### 4. Verify Reverts

After critical sessions, verify the revert:

```bash
git status
git diff
```

---

## Troubleshooting

??? question "Session didn't revert properly"

    ```bash
    # Check for remaining changes
    git status

    # Force revert
    git checkout -- .
    git clean -fd

    # Or use SuperQode recovery
    superqe revert --force
    ```

??? question "Snapshot taking too long"

    Exclude large directories:

    ```yaml
    qe:
      workspace:
        exclude:
          - node_modules
          - .venv
          - build
    ```

??? question "Git worktree conflicts"

    ```bash
    # List worktrees
    git worktree list

    # Remove stale worktrees
    git worktree prune
    ```

---

## Advanced Workspace Features

### Git Worktree Manager

Detailed worktree-based isolation for Git repositories.

#### Benefits

- **Preserves build caches**: `node_modules/`, `target/`, `__pycache__/` shared between worktrees
- **Fast setup**: Git handles copying efficiently (copy-on-write)
- **Multiple parallel sessions**: Create multiple worktrees for parallel QE
- **Commit testing**: Test specific commits without affecting working tree
- **Native Git integration**: Works seamlessly with Git workflows

#### Worktree Location

Worktrees stored in: `~/.superqode/working/{repo-name}/qe/{session-id}`

- Isolated from main repository
- Session-specific directories
- Automatic cleanup after QE

#### Creating Worktrees

```python
from superqode.workspace import GitWorktreeManager

manager = GitWorktreeManager(project_root)

worktree = await manager.create_qe_worktree(
    session_id="qe-20250115",
    base_ref="HEAD",
    copy_uncommitted=True,
    keep_gitignored=True
)
```

#### Worktree Options

- `base_ref`: Git ref (commit, branch, tag) to base worktree on
- `copy_uncommitted`: Copy uncommitted changes to worktree
- `keep_gitignored`: Preserve gitignored files (build caches)

#### Removing Worktrees

```python
await manager.remove_worktree(worktree)
```

Automatically cleaned up after QE session completion.

---

### Git Snapshot Manager

Git-based snapshots for robust file state tracking.

#### How It Works

Uses Git's object database to store file states:

- **Efficient storage**: Git's delta compression
- **Atomic operations**: All-or-nothing snapshot creation
- **Full history**: Track snapshot lineage
- **Diffing capabilities**: Compare any two snapshots

#### Creating Snapshots

```python
from superqode.workspace import GitSnapshotManager

manager = GitSnapshotManager(project_root)

snapshot_id = await manager.create_snapshot(
    message="Before QE session",
    files=None  # None = all tracked files
)
```

#### Snapshot Format

```python
{
  "id": "snap-20250115-143022-abc123",
  "timestamp": "2025-01-15T14:30:22",
  "message": "Before QE session",
  "file_hashes": {
    "src/api/users.py": "sha256:abc...",
    "src/api/orders.py": "sha256:def..."
  },
  "parent_id": null
}
```

#### Getting Changes

```python
changes = await manager.get_changes(snapshot_id)
# Returns: List of FileChange objects
```

#### Restoring Snapshots

```python
await manager.restore_snapshot(snapshot_id)
# Restores all files to snapshot state
```

---

### QE Coordinator

Session coordination with locking and epoch system.

#### Locking System

Prevents concurrent deep QE runs:

- **Deep QE**: Exclusive lock (blocks other sessions)
- **Quick Scan**: Shared lock (multiple can run)
- **Automatic cleanup**: Stale locks from dead processes removed

#### Acquiring Locks

```python
from superqode.workspace import QECoordinator

coordinator = QECoordinator(project_root)

lock = coordinator.acquire_lock(
    session_id="qe-20250115",
    mode="deep",  # or "quick"
    intent="Security audit"
)

if lock is None:
    print("Another session is running")
    return

try:
    # Run QE...
finally:
    coordinator.release_lock(lock)
```

#### Context Manager

```python
with coordinator.session("qe-20250115", mode="deep") as lock:
    if lock:
        # Run QE...
    # Lock automatically released
```

#### Epoch System

Detects if code changed during QE:

```python
# Check if results are stale
if coordinator.is_result_stale(lock):
    print("Warning: Code changed during QE")

# Bump epoch when files change
coordinator.bump_snapshot_epoch()
```

**Epoch increments** when:
- Files are modified
- Git operations occur
- External changes detected

---

### Diff Tracker

Track file changes for patch generation.

#### Capturing Baselines

```python
from superqode.workspace import DiffTracker

tracker = DiffTracker(project_root)

# Before modifying a file
tracker.capture_baseline(Path("src/api/users.py"))

# ... agent modifies file ...

# Get unified diff
patch = tracker.get_unified_diff()
```

#### Change Types

| Type | Description |
|------|-------------|
| `ADD` | File created |
| `DELETE` | File removed |
| `MODIFY` | File content changed |
| `RENAME` | File moved/renamed |

#### Generating Patches

```python
# Get unified diff (Git format)
patch = tracker.get_unified_diff()

# Get summary
summary = tracker.get_changes_summary()
# {
#   "total_changes": 5,
#   "additions": 1,
#   "deletions": 0,
#   "modifications": 3,
#   "renames": 1,
#   ...
# }
```

#### Patch Format

Unified diff format compatible with `git apply`:

```diff
--- a/src/api/users.py
+++ b/src/api/users.py
@@ -42,7 +42,9 @@ def search_users(query: str):
-    sql = f"SELECT * FROM users WHERE name LIKE '%{query}%'"
+    sql = "SELECT * FROM users WHERE name LIKE ?"
+    params = (f"%{query}%",)
     cursor.execute(sql, params)
```

---

### Directory Watcher

Real-time file system monitoring.

#### Watchdog Integration

Uses `watchdog` library for efficient monitoring:

- **Native OS events**: Uses platform-specific file system events
- **Debouncing**: Combines rapid successive changes
- **Pattern filtering**: Ignore patterns (`.git`, `node_modules`, etc.)
- **Async support**: Async/await compatible

#### Basic Usage

```python
from superqode.workspace import DirectoryWatcher

watcher = DirectoryWatcher(project_root)

@watcher.on_change
def handle_change(change: FileChange):
    print(f"{change.change_type}: {change.path}")

watcher.start()
# ... monitoring active ...
watcher.stop()
```

#### Async Usage

```python
async def monitor_changes():
    watcher = DirectoryWatcher(project_root)

    async for change in watcher.async_changes():
        print(f"{change.change_type}: {change.path}")
```

#### Configuration

```python
from superqode.workspace import WatcherConfig

config = WatcherConfig(
    ignore_patterns=[
        "*.pyc",
        "__pycache__",
        ".git/*",
        "node_modules/*"
    ],
    watch_extensions=[".py", ".ts", ".js"],
    debounce_interval=0.5,  # seconds
    recursive=True
)

watcher = DirectoryWatcher(project_root, config=config)
```

#### Change Events

| Event | Description |
|-------|-------------|
| `CREATED` | File/directory created |
| `MODIFIED` | File modified |
| `DELETED` | File/directory deleted |
| `MOVED` | File/directory moved/renamed |

---

### Git Guard Details

Comprehensive protection against Git operations.

#### Safe Commands

Read-only operations allowed:

```bash
# Allowed
git status
git log
git diff
git show
git branch -l  # Listing only
git remote -v  # Viewing only
```

#### Blocked Commands

Write operations blocked:

```bash
# Blocked
git commit
git push
git add
git checkout -- file
git reset --hard
git clean -f
```

#### Command Analysis

Detailed analysis of Git commands:

```python
from superqode.workspace import GitGuard

guard = GitGuard()

analysis = guard.analyze("git commit -m 'test'")
# Returns: GitCommandAnalysis with reason and suggestion

if analysis.is_blocked:
    print(f"Blocked: {analysis.reason}")
    print(f"Suggestion: {analysis.suggestion}")
```

#### Block Reasons

Human-readable reasons for blocking:

- **commit**: "Commits would permanently alter repository history"
- **push**: "Push would send changes to remote repository"
- **reset**: "Reset could lose tracked changes"

#### Safe Variants

Some commands have safe variants:

```bash
# Blocked: git branch new-feature
# Allowed: git branch -l  (listing)

# Blocked: git tag v1.0
# Allowed: git tag -l  (listing)
```

---

## Integration

All workspace features work together:

1. **Coordinator** manages session locking
2. **Git Worktree** creates isolated workspace
3. **Git Snapshot** captures initial state
4. **Diff Tracker** monitors changes
5. **Directory Watcher** provides real-time updates
6. **Git Guard** prevents dangerous operations
7. **Snapshot Manager** enables revert

---

## Best Practices

### 1. Use Git Worktree for Git Repos

Most efficient for Git repositories:

```bash
# Ensure you're in a Git repo
git init  # if needed
```

### 2. Monitor with Watchers

Enable real-time monitoring:

```python
watcher = DirectoryWatcher(project_root)
watcher.start()
```

### 3. Use Coordinator for Safety

Always coordinate sessions:

```python
with coordinator.session("my-session") as lock:
    if lock:
        # Safe to run QE
```

### 4. Check Stale Results

Verify results aren't stale:

```python
if coordinator.is_result_stale(lock):
    print("Results may be outdated")
```

---

## Troubleshooting

### Worktree Conflicts

**Symptom**: "Worktree already exists"

**Solution**:
```bash
git worktree list
git worktree prune  # Remove stale worktrees
```

### Stale Locks

**Symptom**: Lock persists after session ends

**Solution**: Coordinator auto-cleans stale locks, but you can manually:
```python
coordinator._clear_stale_locks()
```

### Watcher Not Working

**Symptom**: Changes not detected

**Solution**: Ensure `watchdog` installed:
```bash
pip install watchdog
```

---

## Next Steps

- [QE Roles](roles.md) - Understanding testing roles
- [Quality Reports](qr.md) - Report format and structure
- [Allow Suggestions](suggestions.md) - Fix demonstration workflow
