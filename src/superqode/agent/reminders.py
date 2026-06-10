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

A third built-in is opt-in: **memory recall** (``SUPERQODE_AUTO_RECALL=1``)
searches the local memory store with the run's prompt and surfaces the top
hits once per prompt. Only the local provider is read - it lives under the
user's home directory and contains only what the user (or opt-in
auto-capture) stored, so an untrusted repository can never plant content
into the agent's context through it.

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
# Memory recall: opt-in env, relevance floor, and result cap.
AUTO_RECALL_ENV = "SUPERQODE_AUTO_RECALL"
RECALL_MIN_SCORE = 0.34
RECALL_MAX_RESULTS = 4
_RECALL_SNIPPET_CHARS = 240


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


def auto_recall_enabled() -> bool:
    return os.environ.get(AUTO_RECALL_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _memory_recall_reminder(
    working_directory: Path, user_message: str, state: Dict[str, Any]
) -> str:
    """Surface relevant local memories for this prompt, once per prompt.

    Reads only the local provider: it lives under the user's home directory
    and holds only user-stored (or opt-in auto-captured) notes, so untrusted
    repository content can never reach the agent through this path.
    """
    if not auto_recall_enabled():
        return ""
    prompt = (user_message or "").strip()
    if len(prompt) < 8:
        return ""
    import hashlib

    prompt_key = hashlib.sha256(prompt.encode("utf-8", errors="replace")).hexdigest()[:16]
    if state.get("recalled_for") == prompt_key:
        return ""
    state["recalled_for"] = prompt_key
    try:
        from ..memory.providers import LocalAgentMemoryProvider

        results = LocalAgentMemoryProvider(project_root=working_directory).search(
            prompt, limit=RECALL_MAX_RESULTS * 2
        )
    except Exception:
        return ""
    hits = [r for r in results if r.score >= RECALL_MIN_SCORE][:RECALL_MAX_RESULTS]
    if not hits:
        return ""
    lines = []
    for hit in hits:
        content = " ".join(str(hit.record.content).split())
        if len(content) > _RECALL_SNIPPET_CHARS:
            content = content[: _RECALL_SNIPPET_CHARS - 3] + "..."
        lines.append(f"  - [{hit.record.kind}] {content}")
    listing = "\n".join(lines)
    return (
        "Saved project memory relevant to this task (from `superqode memory`; "
        "background context, verify before relying on it):\n"
        f"{listing}"
    )


def collect_reminders(
    *,
    session_id: str,
    working_directory: Path,
    iteration: int,
    state: Dict[str, Any],
    user_message: str = "",
) -> List[str]:
    """Gather reminder texts for the next model call. Cheap (stat calls only)."""
    if not reminders_enabled():
        return []
    out: List[str] = []
    text = _memory_recall_reminder(working_directory, user_message, state)
    if text:
        out.append(text)
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
    "AUTO_RECALL_ENV",
    "MAX_CHANGED_FILES",
    "RECALL_MAX_RESULTS",
    "RECALL_MIN_SCORE",
    "TODO_NUDGE_INTERVAL",
    "auto_recall_enabled",
    "collect_reminders",
    "format_reminder_message",
    "reminders_enabled",
]
