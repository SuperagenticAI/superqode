# Share Commands

Create portable session artifacts for handoff between SuperQode instances.

---

## share create

Create a portable share artifact from a stored session.

```bash
superqode share create <session_id> [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `session_id` | Source session ID |

### Options

| Option | Description |
|--------|-------------|
| `--output`, `-o` | Output path for the share artifact (default: `.superqode/shares/share-<session_id>.superqode-share.json`) |

Writes a share artifact in `superqode-share-v1` format to `.superqode/shares/`.

---

## share export

Export a session to a human-readable format.

```bash
superqode share export <session_id> [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `session_id` | Session ID to export |

### Options

| Option | Description |
|--------|-------------|
| `--format` | Output format: `markdown` or `json` (default: markdown) |
| `--output`, `-o` | Output file path (prints to stdout if omitted) |

### Examples

```bash
superqode share export abc123 --format markdown --output session.md
superqode share export abc123 --format json
```

---

## share import

Import a share artifact as a new session.

```bash
superqode share import <artifact> [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `artifact` | Path to a `.superqode-share.json` file |

### Options

| Option | Description |
|--------|-------------|
| `--session-id` | Assign a specific session ID (auto-generated if omitted) |

Imports the artifact into `.superqode/sessions/` as a runnable session. Use the TUI `:history` or `:resume <id>` to continue from the imported session.

---

## share list

List share artifacts.

```bash
superqode share list [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--json` | Emit JSON output |

Lists all `.superqode-share.json` files in `.superqode/shares/`.

---

## share revoke

Delete a share artifact.

```bash
superqode share revoke <artifact>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `artifact` | Artifact filename or path (e.g., `share-abc123.superqode-share.json`) |

Removes the share artifact file from `.superqode/shares/`.

---

## superqode-share-v1 Format

Share artifacts use the `superqode-share-v1` envelope format:

```json
{
  "format": "superqode-share-v1",
  "created_at": "2026-06-07T12:00:00Z",
  "source_id": "abc123",
  "metadata": {
    "provider": "anthropic",
    "model": "<anthropic-balanced-model>",
    "turn_count": 12
  },
  "turns": [...]
}
```

- `format` identifies the schema version for forward compatibility
- `metadata` captures origin context without requiring provider auth
- `turns` contains the full ordered sequence of messages and tool calls
- The artifact is self-contained and portable between machines
