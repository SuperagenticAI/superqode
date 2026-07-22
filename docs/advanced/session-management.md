# Session Management

SuperQode provides comprehensive session management with JSONL-based storage, auto-summarization, and manual compaction options.

---

## Overview

Session management in SuperQode includes:

- **JSONL Storage**: Fast, append-only conversation history
- **Durable Session Graph**: Parent sessions, child agents, forks, handoffs, approvals, and share trees
- **Software Factory Metadata**: Model, provider, runtime, harness, and route lineage for portable work
- **Auto-summarization**: Automatic context compression when tokens exceed limit
- **Manual Compaction**: Use `/compact` command to compress context
- **Large Output Handling**: Saves large responses to files automatically

---

## Session Storage

### How It Works

Sessions are stored in JSONL format in `.superqode/sessions/`:

```text
.superqode/sessions/
├── abc12345.jsonl      # Conversation messages
├── abc12345.meta.json # Session metadata
├── def67890.jsonl
└── def67890.meta.json
```

Each line in the JSONL file is a single message:

```json
{"role": "user", "content": "Fix the bug", "timestamp": "2026-05-11T10:00:00"}
{"role": "assistant", "content": "I'll help fix the bug", "timestamp": "2026-05-11T10:00:01"}
{"role": "tool", "tool_name": "read_file", "content": "file contents...", "timestamp": "2026-05-11T10:00:02"}
```

### Enabling Session Storage

Enable session storage in your agent configuration:

```python
from superqode.agent import AgentConfig

config = AgentConfig(
    provider="openai",
    model="<openai-model>",
    enable_session_storage=True,
    session_storage_dir=".superqode/sessions",
)
```

---

## TUI Commands

### Switch Harnesses Within a Session

Each stored session records its harness, provider, model, conversation history,
and harness transition history. Switching activates another harness while
keeping the same session ID. SuperQode uses its normalized session history to
replay context through the selected harness.

Use `:harness` or `:harness switch` to select a harness interactively. Enter
continues the current session under the highlighted harness. Press `F` instead
to create an independent branch before switching. The picker reports whether
the runtime provides exact resume, context replay, or a fresh runtime session.

```text
:harness switch workbench
:harness switch kimi-coding
```

Create an independent branch when the original harness path must remain
unchanged:

```text
:harness switch workbench --fork
```

The fork copies the stored messages, records the parent session ID, and changes
the harness only on the new session.

Open the session switcher to return to any saved session:

```text
:sessions switch
```

The picker shows the latest harness for every session. Resuming a session
restores its harness, provider, model, and stored messages. A direct switch is
also available:

```text
:sessions switch <session-id>
```

This is the terminal session-switching workflow. No web or mobile control plane
is required.

The picker covers sessions stored in SuperQode's normalized JSONL session
store. Vendor-owned thread stores remain available through their runtime
commands, including `:codex sessions` and `:claude sessions`. The catalog uses
`context replay`, `exact resume`, or `fresh session` to state the continuity a
harness adapter can provide.

### List Sessions

```text
/sessions
```

Shows recent sessions with harness metadata:

```text
Recent Sessions:
--------------------------------------------------
1. abc12345 | workbench  | <openai-model> | 5 msgs
2. def67890 | code-review | <anthropic-balanced-model> | 12 msgs
--------------------------------------------------
Use :sessions switch <id> to restore its harness and continue
```

### Resume Session

```text
/resume <session_id>
```

Resumes a previous session and restores the same harness, provider, model, and
conversation history.

### Compact Context

```text
/compact
```

Manually compresses the conversation history to reduce token usage. Keeps recent messages and summarizes older ones.

---

## Switchboard And Factory

SuperQode stores conversation messages in `.superqode/sessions/` and graph metadata in
`.superqode/session_graph.json`.

Use the switchboard when you want to move between sessions:

```text
:switchboard
:sw switch <id>
:sw handoff <source> --to <target> --goal "continue this work"
:sw share-tree <id>
```

Use the Software Factory layer when you want to move work between models, providers, runtimes, or
harnesses without losing the session graph:

```text
:factory mode no-subscription
:factory switch-model ollama/qwen3-coder
:factory switch-harness review
:factory fork-model --model local/deepseek-coder --role coder
:factory lineage
```

See [Software Factory](software-factory.md) for the full concept and command flow.

---

## Auto Summarization

When enabled, SuperQode automatically summarizes conversation history when it exceeds a token threshold.

### Configuration

```python
config = AgentConfig(
    enable_summarization=True,
    max_context_tokens=8000,  # Summarize when exceeded
)
```

### How It Works

1. After each agent turn, the system checks total tokens
2. If tokens exceed `max_context_tokens`, older messages are summarized
3. A summary replaces multiple messages, preserving key context
4. Recent messages (configurable) are kept intact

### Token Estimation

Token count is estimated at approximately 1 token per 4 characters:

```python
estimated_tokens = len(message_content) // 4
```

---

## Large Output Handling

When agent responses exceed a size threshold, they are saved to a file rather than displayed inline.

### How It Works

Large outputs are saved to `.superqode/outputs/`:

```text
.superqode/outputs/
├── output_20260511_100000_a1b2c3d4.txt
└── output_20260511_100500_e5f6g7h8.txt
```

### Configuration

```python
from superqode.agent.output_handler import OutputConfig, LargeOutputHandler

config = OutputConfig(
    max_output_size=50000,           # Max chars before saving
    save_to_file_threshold=10000,   # Save to file if exceeded
    output_dir=".superqode/outputs",
)

handler = LargeOutputHandler(config=config)
```

### Output Behavior

When output exceeds the threshold:

1. Content is saved to a timestamped file
2. Display shows preview (first 500 characters)
3. File path is shown for full content access

---

## Session API

### Python Usage

```python
from superqode.agent.session_manager import SessionManager, SessionMessage

# Create session manager
manager = SessionManager(storage_dir=".superqode/sessions")

# Start new session
session_id = manager.start_session(
    provider="openai",
    model="<openai-model>",
)

# Add messages
manager.add_user_message("Fix the bug")
manager.add_assistant_message("I'll help")
manager.add_tool_result("read_file", "file content")

# Get all messages
messages = manager.get_messages()

# List all sessions
sessions = manager.list_all_sessions()

# Delete old sessions
manager.cleanup_old_sessions(max_sessions=100)
```

---

## Session Metadata

Each session includes metadata:

```json
{
  "session_id": "abc12345",
  "created_at": "2026-05-11T10:00:00",
  "updated_at": "2026-05-11T10:05:00",
  "provider": "openai",
  "model": "<openai-model>",
  "message_count": 15,
  "total_tokens": 4500
}
```

---

## Pure Mode Integration

Session storage integrates with Pure Mode for minimal harness testing:

```python
from superqode.pure_mode import PureMode

pm = PureMode()
pm.connect(provider="openai", model="<openai-model>")

# Sessions are auto-enabled
print(pm.get_current_session_id())

# List sessions
sessions = pm.list_sessions()

# Resume a session
messages = pm.resume_session("abc12345")
```

---

## See Also

- [Advanced Tools](tools-system.md) - Tool registry and permissions
- [A2A Protocol](../providers/a2a.md) - Multi-agent communication
