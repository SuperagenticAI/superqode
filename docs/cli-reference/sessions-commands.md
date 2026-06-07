# Sessions Commands

Manage SuperQode coding sessions. Sessions are stored as JSONL files in `.superqode/sessions/`, one file per session with structured turn-by-turn logs.

---

## sessions list

List stored sessions.

```bash
superqode sessions list [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--json` | Emit JSON output |

### Output

```
ID         Provider    Model               Turns  Created
abc123     anthropic   claude-sonnet-4      12    2026-06-01T10:00:00
def456     openai      gpt-4o               8    2026-06-02T14:30:00
```

---

## sessions tree

Show session fork lineage as a tree.

```bash
superqode sessions tree
```

Displays parent-child relationships between sessions created via `--fork`. Each session shows its ID, provider, model, and creation time indented under its parent.

---

## sessions show

Show stored session details.

```bash
superqode sessions show <id>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `id` | Session ID to inspect |

Displays session metadata, message count, and a summary of the conversation. Use the TUI `:history` panel for full turn-by-turn review.

---

## sessions export

Export a session to a portable format.

```bash
superqode sessions export <id> [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `id` | Session ID to export |

### Options

| Option | Description |
|--------|-------------|
| `--format` | Output format: `markdown` or `json` (default: markdown) |
| `--output`, `-o` | Output file path (prints to stdout if omitted) |

### Examples

```bash
superqode sessions export abc123 --format markdown --output session.md
superqode sessions export abc123 --format json
```

---

## sessions delete

Delete a stored session.

```bash
superqode sessions delete <id>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `id` | Session ID to delete |

Removes the session JSONL file from `.superqode/sessions/`.

---

## Session Storage

Sessions are persisted as newline-delimited JSON (JSONL) files:

```
.superqode/sessions/
  abc123.jsonl
  def456.jsonl
  ...
```

Each line is one turn with fields for role, content, tool calls, metadata, and timestamps. The format is append-only: sessions are never modified in place, only created, read, or deleted.
