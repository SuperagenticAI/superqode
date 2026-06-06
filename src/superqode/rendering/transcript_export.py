"""Export conversation transcripts to portable text formats."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


TranscriptMessage = tuple[str, str, str]


def normalize_transcript_messages(messages: list[TranscriptMessage]) -> list[dict[str, str]]:
    """Convert ConversationLog tuples into stable export records."""
    records: list[dict[str, str]] = []
    for role, content, agent in messages:
        if role == "info":
            continue
        records.append(
            {
                "role": str(role or "message"),
                "agent": str(agent or ""),
                "content": str(content),
            }
        )
    return records


def default_transcript_metadata(
    *,
    cwd: str = "",
    runtime: str = "",
    provider: str = "",
    model: str = "",
    title: str = "SuperQode Transcript",
) -> dict[str, Any]:
    """Build metadata shared by Markdown and JSON exports."""
    return {
        "title": title,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "cwd": cwd,
        "runtime": runtime,
        "provider": provider,
        "model": model,
    }


def render_transcript_markdown(
    messages: list[TranscriptMessage],
    *,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a transcript as plain Markdown."""
    metadata = metadata or default_transcript_metadata()
    records = normalize_transcript_messages(messages)
    lines = [f"# {metadata.get('title') or 'SuperQode Transcript'}", ""]
    details = [
        ("Exported", metadata.get("exported_at")),
        ("Runtime", metadata.get("runtime")),
        ("Provider", metadata.get("provider")),
        ("Model", metadata.get("model")),
        ("Workspace", metadata.get("cwd")),
    ]
    for label, value in details:
        if value:
            lines.append(f"- **{label}:** {value}")
    if len(lines) > 2:
        lines.append("")
    if not records:
        lines.append("_Empty transcript._")
        lines.append("")
        return "\n".join(lines)
    for record in records:
        label = record["agent"] if record["role"] in {"agent", "assistant"} and record["agent"] else record["role"]
        lines.append(f"## {label}")
        lines.append("")
        lines.append(record["content"].rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_transcript_json(
    messages: list[TranscriptMessage],
    *,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a transcript as structured JSON."""
    records = normalize_transcript_messages(messages)
    payload = {
        "format": "superqode-transcript-v1",
        "metadata": metadata or default_transcript_metadata(),
        "messages": records,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
