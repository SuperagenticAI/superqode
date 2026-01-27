<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode.png" alt="SuperQode Banner" />

# Session Management

Persistent session storage, sharing, and coordination for QE sessions and conversations.

---

## Overview

Session Management provides:

- **Persistence**: Save and resume QE sessions
- **Sharing**: Share sessions with team members
- **Forking**: Create branches from shared sessions
- **Snapshots**: Undo/redo with session snapshots
- **History**: Track conversation history and tool executions

---

## Session Storage

### Storage Location

Sessions stored in: `~/.superqode/sessions/`

- Compressed JSON files (`.json.gz`)
- Index file for fast listing (`index.json`)
- Share directory for shared sessions (`shares/`)

### Session Format

```json
{
  "id": "session-123",
  "title": "Fix SQL injection",
  "created_at": "2025-01-15T10:00:00",
  "updated_at": "2025-01-15T10:30:00",
  "project_path": "/path/to/project",
  "messages": [...],
  "tool_executions": [...],
  "files_modified": ["src/api/users.py"],
  "files_created": [],
  "agents_used": ["security_tester"],
  "tags": ["security", "bug-fix"],
  "snapshots": [...]
}
```

---

## Session API

### Create Session

```python
from superqode.session import SessionStore, Session, MessageRole

store = SessionStore()

session = Session(
    id="session-123",
    title="Fix SQL injection",
    project_path="/path/to/project"
)

session.add_message(
    role=MessageRole.USER,
    content="Fix the SQL injection vulnerability"
)

store.save(session)
```

### Load Session

```python
# Load by ID
session = store.load("session-123")

# Load latest
session = store.load_latest()

# List all sessions
sessions = store.list_sessions()
```

### Update Session

```python
session = store.load("session-123")
session.add_message(MessageRole.ASSISTANT, "I'll fix that...")
store.save(session)
```

---

## Message Tracking

### Message Types

| Role | Description |
|------|-------------|
| `user` | User input |
| `assistant` | Agent response |
| `system` | System messages |

### Message Format

```python
message = session.add_message(
    role=MessageRole.USER,
    content="Fix the bug",
    agent_name="security_tester",
    tool_calls=[...],
    tool_call_id="call-123"
)
```

---

## Tool Execution Tracking

Track all tool executions:

```python
execution = session.add_tool_execution(
    tool_name="read_file",
    arguments={"path": "src/api/users.py"},
    result="file content...",
    success=True,
    duration_ms=45,
    agent_name="security_tester"
)
```

### Execution History

```python
# Get all tool executions
executions = session.tool_executions

# Filter by tool
file_reads = [e for e in executions if e.tool_name == "read_file"]

# Filter by agent
agent_tools = [e for e in executions if e.agent_name == "security_tester"]
```

---

## File Tracking

Track modified and created files:

```python
# Automatically tracked
session.files_modified  # ["src/api/users.py"]
session.files_created   # ["tests/test_users.py"]
```

---

## Snapshots

Undo/redo support with snapshots:

### Create Snapshot

```python
snapshot = session.create_snapshot("Before fix")
# session.snapshots now includes snapshot
```

### Restore Snapshot

```python
# Restore to previous state
session.restore_snapshot(snapshot.id)
```

### Snapshot Format

```python
{
  "id": "snapshot-123",
  "created_at": "2025-01-15T10:15:00",
  "description": "Before SQL fix",
  "state": {
    "files_modified": [...],
    "messages": [...],
    "tool_executions": [...]
  }
}
```

---

## Session Sharing

### Create Share

```python
from superqode.session import SessionSharingManager, ShareConfig

sharing = SessionSharingManager(store)

share_config = ShareConfig(
    visibility="public",  # or "unlisted", "private"
    allow_fork=True,
    allow_view_history=True,
    expires_in=timedelta(days=7),  # Optional
    password="optional-password"  # Optional
)

share = sharing.create_share("session-123", share_config)
print(f"Share URL: {share.share_url}")
```

### Access Share

```python
# Get shared session
shared_session = sharing.get_session_for_share(
    share_token="abc123",
    password="optional-password"
)
```

### Fork Session

```python
# Create fork from shared session
forked = await sharing.fork_session(
    share_token="abc123",
    title="My Fork"
)
```

---

## Export/Import

### Export Session

```python
from superqode.session import ExportedSession

# Export to JSON
exported = sharing.export_session("session-123")
with open("session.json", "w") as f:
    f.write(exported.to_json())

# Export to base64 (for sharing)
b64 = exported.to_base64()
```

### Import Session

```python
# Import from JSON
with open("session.json") as f:
    exported = ExportedSession.from_json(f.read())

# Import from base64
exported = ExportedSession.from_base64(b64_str)

# Restore session
session = exported.to_session()
store.save(session)
```

---

## Share Configuration

### Visibility

| Level | Description |
|-------|-------------|
| `public` | Anyone with link can access |
| `unlisted` | Accessible via link, not in lists |
| `private` | Password-protected access |

### Options

```python
ShareConfig(
    visibility="public",
    allow_fork=True,           # Allow forking
    allow_view_history=True,   # Show conversation history
    expires_in=timedelta(days=7),  # Auto-expire
    password="secret"          # Optional password
)
```

---

## Session Metadata

### Tags

Organize sessions with tags:

```python
session.tags = ["security", "bug-fix", "urgent"]
```

### Agents Used

Track which agents participated:

```python
session.agents_used  # ["security_tester", "api_tester"]
```

### Parent Session

Track session relationships:

```python
# Forked session
forked.parent_session_id = "session-123"
```

---

## Best Practices

### 1. Regular Saves

Save sessions regularly:

```python
# Auto-save after each message
session.add_message(...)
store.save(session)
```

### 2. Meaningful Titles

Use descriptive titles:

```python
session.title = "Fix SQL injection in users.py"  # Good
session.title = "Session 1"  # Bad
```

### 3. Create Snapshots

Snapshot before major changes:

```python
session.create_snapshot("Before refactoring")
# ... make changes ...
```

### 4. Clean Up Old Sessions

```python
# Delete old sessions
store.delete("old-session-id")
```

### 5. Secure Sharing

Use passwords for sensitive sessions:

```python
ShareConfig(
    visibility="private",
    password="strong-password"
)
```

---

## Use Cases

### 1. Resume Work

```python
# Continue from last session
session = store.load_latest()
# Resume work...
```

### 2. Share Solutions

```python
# Share successful fix with team
share = sharing.create_share("session-123", ShareConfig(visibility="public"))
# Share URL with team
```

### 3. Fork and Experiment

```python
# Fork shared session to experiment
forked = await sharing.fork_session(share_token, "My experiment")
# Experiment without affecting original
```

### 4. Session History

```python
# Review what was done
session = store.load("session-123")
for execution in session.tool_executions:
    print(f"{execution.tool_name}: {execution.result}")
```

---

## Integration

### With QE Sessions

Sessions automatically saved during QE:

```python
# QE session automatically creates/updates session
qe_session = QESession(...)
# Session saved to store automatically
```

### With TUI

TUI uses sessions for persistence:

- Auto-save after each interaction
- Resume last session on startup
- Session history in TUI

---

## Troubleshooting

### Session Not Found

**Solution**: Check session ID:

```python
# List all sessions
sessions = store.list_sessions()
```

### Share Expired

**Solution**: Create new share:

```python
# Shares expire based on config
share = sharing.create_share(session_id, ShareConfig(expires_in=None))
```

### Import Failed

**Solution**: Check export format:

```python
# Ensure valid JSON
exported = ExportedSession.from_json(json_string)
```

---

## Related Features

- [Memory & Learning](memory.md) - Persistent learnings
- [QE Features](../qe-features/index.md) - QE workflows

---

## Next Steps

- [Advanced Features Index](index.md) - All advanced features
- [Session Persistence](https://github.com/Shashikant86/superqode/tree/14dc05cf7ae0fbf95b55c33078b1852a45f10fc0/src/superqode/session) - Source code
