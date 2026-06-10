"""Synthetic per-call system reminders (opencode/Claude Code pattern).

Reminders are short ``<system-reminder>`` notes attached to the *outgoing
request only* — they are never persisted into conversation history, so they
cost context exactly once and can't accumulate. Two built-ins:

- **Externally changed files** — a file the agent read earlier was modified
  outside the session (editor, formatter, another agent). The edit tool
  would reject the next edit anyway; telling the model *before* it tries
  saves a wasted round-trip.
- **Stale todos** — open todo items exist but haven't been touched for a
  while; a gentle nudge keeps long multi-step runs from silently dropping
  the plan. Rate-limited so it never nags every turn.

Disable everything with ``SUPERQODE_REMINDERS=0``.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

# Nudge about open todos at most every N iterations.
TODO_NUDGE_INTERVAL = 8
# Cap how many changed files one reminder lists.
MAX_CHANGED_FILES = 5


def reminders_enabled() -> bool:
    return os.environ.get("SUPERQODE_REMINDERS", "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _changed_files_reminder(session_id: str, state: Dict[str, Any]) -> str:
    """Detect files modified externally since the agent last read them."""
    try:
        from ..tools.file_tracking import list_session_reads
    except ImportError:
        return ""
    announced: Dict[str, float] = state.setdefault("announced_changes", {})
    changed: List[str] = []
    for path, recorded_mtime in list_session_reads(session_id).items():
        try:
            current = Path(path).stat().st_mtime
        except OSError:
            continue  # deleted/unreadable - the tools will surface that themselves
        if current == recorded_mtime:
            announced.pop(path, None)
            continue
        if announced.get(path) == current:
            continue  # already told the model about this exact change
        announced[path] = current
        changed.append(path)
        if len(changed) >= MAX_CHANGED_FILES:
            break
    if not changed:
        return ""
    listing = "\n".join(f"  - {p}" for p in changed)
    return (
        "These files changed on disk after you last read them (external edit):\n"
        f"{listing}\n"
        "Re-read them before editing; edits based on the old content will be rejected."
    )


def _stale_todo_reminder(
    session_id: str, working_directory: Path, iteration: int, state: Dict[str, Any]
) -> str:
    """Nudge when open todos exist and haven't been mentioned recently."""
    last = state.get("last_todo_nudge")
    if last is not None and iteration - last < TODO_NUDGE_INTERVAL:
        return ""
    try:
        from ..tools.todo_tools import _load_todos

        ctx = SimpleNamespace(session_id=session_id, working_directory=working_directory)
        todos = _load_todos(ctx)
    except Exception:
        return ""
    open_items = [
        t for t in todos if str(t.get("status", "")).lower() in ("pending", "in_progress")
    ]
    if not open_items:
        return ""
    state["last_todo_nudge"] = iteration
    listing = "\n".join(
        f"  - [{t.get('status', '?')}] {str(t.get('content', t.get('task', '')))[:80]}"
        for t in open_items[:6]
    )
    return (
        f"Your todo list has {len(open_items)} open item(s):\n{listing}\n"
        "Keep it current with todo_write - mark finished work completed, or "
        "remove items that no longer apply."
    )


def collect_reminders(
    *,
    session_id: str,
    working_directory: Path,
    iteration: int,
    state: Dict[str, Any],
) -> List[str]:
    """Gather reminder texts for the next model call. Cheap (stat calls only)."""
    if not reminders_enabled():
        return []
    out: List[str] = []
    text = _changed_files_reminder(session_id, state)
    if text:
        out.append(text)
    text = _stale_todo_reminder(session_id, working_directory, iteration, state)
    if text:
        out.append(text)
    return out


def format_reminder_message(texts: List[str]) -> str:
    """Join reminder texts into one tagged block for the outgoing request."""
    body = "\n\n".join(texts)
    return f"<system-reminder>\n{body}\n</system-reminder>"


__all__ = [
    "MAX_CHANGED_FILES",
    "TODO_NUDGE_INTERVAL",
    "collect_reminders",
    "format_reminder_message",
    "reminders_enabled",
]
