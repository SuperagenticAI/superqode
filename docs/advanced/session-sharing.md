# Session Sharing

## Overview

SuperQode supports four export formats: portable share artifacts (superqode-share-v1), session JSON, Markdown transcripts, and self-contained HTML transcripts.

## Share Artifacts (superqode-share-v1)

Portable JSON files with .superqode-share.json suffix. Contain the full session including messages, tool calls, and results. Stored in .superqode/shares/.

```bash
superqode share create <session-id>
superqode share import artifact.superqode-share.json --session-id new-session
superqode share list
superqode share revoke artifact.superqode-share.json
```

## Session Export

Export sessions as Markdown or JSON for external consumption.

```bash
superqode sessions export <id> --format markdown --output session.md
superqode sessions export <id> --format json --output session.json
superqode share export <id> --format markdown --output session.md
```

## HTML Transcript Export

Self-contained HTML documents with dark theme, role-colored message blocks, basic Markdown rendering (code blocks, headings, lists, bold). Accessible via Python API:

```python
from superqode.rendering.html_export import render_transcript_html

html = render_transcript_html(messages, title="My Session")
```

## Markdown Transcript Export

```python
from superqode.rendering.transcript_export import render_transcript_markdown

md = render_transcript_markdown(messages, metadata=metadata)
```

## JSON Transcript Export

JSON format marked as superqode-transcript-v1 with metadata and messages arrays.

```python
from superqode.rendering.transcript_export import render_transcript_json

json_str = render_transcript_json(messages, metadata=metadata)
```

## Advanced Sharing (SessionSharingManager)

For server-side sharing with access controls:
- Visibility levels: PRIVATE, UNLISTED, PUBLIC
- Password protection with SHA-256 hashing
- Expiry times
- Fork counting and access tracking
- Compressed/base64 export for URL-based sharing

## Undo/Redo

Git-based checkpoint system. Each checkpoint snapshots working tree state. Supports undo (restore from current checkpoint), redo, and restore to any named checkpoint. Uses git stash for lightweight checkpoints or git commits for permanent ones.

```python
from superqode.undo_manager import UndoManager

um = UndoManager(working_dir)
um.initialize()
um.create_checkpoint("before-refactor", "Snapshot before large refactor")
# ... make changes ...
um.undo()  # Restore to checkpoint
```

## File Locations

- Share artifacts: .superqode/shares/
- Session storage: .superqode/sessions/ (JSONL)
- Checkpoints: git stash or git commits with [superqode] prefix
