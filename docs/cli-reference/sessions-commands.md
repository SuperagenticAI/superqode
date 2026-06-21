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

```text
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

## sessions graph

Show the durable switchboard graph: parent sessions, child agents, forks, handoffs, status, and titles.

```bash
superqode sessions graph [--json]
```

Use this when you want the richer graph view rather than only legacy fork lineage.

---

## sessions switch

Set the active switchboard session.

```bash
superqode sessions switch [SESSION_ID] [--json]
```

If no session id is provided, SuperQode resolves the current active graph session when possible.

---

## sessions info

Show graph metadata for a session.

```bash
superqode sessions info [SESSION_ID]
```

Includes parent/root ids, status, agent id, provider/model, message counts, and children.

---

## sessions history

Show recent messages for a session.

```bash
superqode sessions history [SESSION_ID] [--limit 20] [--json]
```

---

## sessions children

List child/fork/agent sessions for a session.

```bash
superqode sessions children [SESSION_ID] [--json]
```

---

## sessions handoff

Create or deliver a cross-session handoff packet.

```bash
superqode sessions handoff [SOURCE_SESSION_ID] --agent reviewer --goal "review this patch"
superqode sessions handoff [SOURCE_SESSION_ID] --target-session-id target --deliver --goal "continue here"
```

---

## sessions fork-agent

Fork a session and tag the fork for another coding agent.

```bash
superqode sessions fork-agent [SOURCE_SESSION_ID] --agent reviewer --goal "review this patch"
```

This is the lower-level graph primitive used by `superqode factory fork-model` and
`superqode factory fork-harness`.

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

```text
.superqode/sessions/
  abc123.jsonl
  def456.jsonl
  ...
```

Each line is one turn with fields for role, content, tool calls, metadata, and timestamps. The format is append-only: sessions are never modified in place, only created, read, or deleted.
