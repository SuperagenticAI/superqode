"""Visible text from an A2A task, shared by the CLI, TUI, and :a2a call."""

from __future__ import annotations


def task_reply(task) -> str:
    """Best text the agent returned: artifacts, then status, then history."""
    chunks: list[str] = []
    for artifact in getattr(task, "artifacts", None) or []:
        for part in getattr(artifact, "parts", None) or []:
            text = getattr(part, "text", None)
            if text:
                chunks.append(str(text))
    if chunks:
        return "\n".join(chunks).strip()
    status = getattr(task, "status", None)
    message = getattr(status, "message", None) if status is not None else None
    if message:
        return str(message).strip()
    for item in reversed(getattr(task, "history", None) or []):
        role = str(getattr(getattr(item, "role", None), "value", getattr(item, "role", "")))
        if "agent" not in role.lower():
            continue
        texts = [
            str(part.text)
            for part in (getattr(item, "parts", None) or [])
            if getattr(part, "text", None)
        ]
        if texts:
            return "\n".join(texts).strip()
    return ""
