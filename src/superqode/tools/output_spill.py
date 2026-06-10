"""Spill oversized tool output to disk instead of destroying it.

Hard truncation loses exactly the bytes a model usually needs next (the
failing assertion at the end of a test run, the one error line in a build
log). Instead of discarding it, oversized output is written in
full to a spill file and the model receives a bounded preview plus the
path, so it can come back with ``read_file`` (start_line/end_line) or
``grep`` instead of re-running the command.

Spill files live under ``~/.superqode/tool-output`` (override with the
``SUPERQODE_TOOL_OUTPUT_DIR`` env var) and are pruned after 7 days. The
directory is automatically part of the read-only search scope so read and
search tools can access spilled files without extra configuration.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Optional, Tuple

SPILL_DIR_ENV = "SUPERQODE_TOOL_OUTPUT_DIR"
RETENTION_SECONDS = 7 * 24 * 3600
SPILL_FILE_PREFIX = "tool_"

# Never keep more than this in memory per tool call, even for the spill
# file. Beyond it the producer is treated as runaway and the rest dropped.
SPILL_HARD_CAP_BYTES = 5 * 1024 * 1024

# Fraction of the preview budget spent on the head; the rest shows the tail.
# Tail-heavy because the end of command output (failures, summaries, exit
# state) is usually what the model needs next.
_HEAD_FRACTION = 0.3

_cleanup_done = False


def get_spill_dir() -> Path:
    """Directory for spilled tool output (not created until first spill)."""
    raw = os.environ.get(SPILL_DIR_ENV, "").strip()
    if raw:
        return Path(os.path.abspath(os.path.expanduser(raw)))
    return Path.home() / ".superqode" / "tool-output"


def cleanup_spill_dir(now: Optional[float] = None) -> int:
    """Delete spill files older than the retention window. Returns count."""
    directory = get_spill_dir()
    if not directory.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - RETENTION_SECONDS
    removed = 0
    try:
        entries = list(directory.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.name.startswith(SPILL_FILE_PREFIX):
            continue
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def spill_output(text: str, prefix: str = "tool") -> Optional[Path]:
    """Write full output to a spill file. Returns the path, or None on failure."""
    global _cleanup_done
    directory = get_spill_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if not _cleanup_done:
            _cleanup_done = True
            cleanup_spill_dir()
        name = f"{SPILL_FILE_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}_{prefix}_{uuid.uuid4().hex[:8]}.txt"
        path = directory / name
        path.write_text(text, encoding="utf-8", errors="replace")
        return path
    except OSError:
        return None


def _cut_at_line_boundary(text: str, limit: int, from_end: bool) -> str:
    """Cut text to at most ``limit`` bytes, preferring a line boundary."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text
    if from_end:
        piece = encoded[-limit:].decode("utf-8", errors="replace")
        newline = piece.find("\n")
        if 0 <= newline < len(piece) - 1:
            piece = piece[newline + 1 :]
        return piece
    piece = encoded[:limit].decode("utf-8", errors="replace")
    newline = piece.rfind("\n")
    if newline > 0:
        piece = piece[:newline]
    return piece


def truncate_with_spill(
    text: str,
    *,
    max_bytes: int,
    label: str = "output",
    prefix: str = "tool",
    direction: str = "head_tail",
) -> Tuple[str, bool, Optional[Path]]:
    """Bound ``text`` to ``max_bytes``, spilling the full content to disk.

    Returns ``(content, truncated, spill_path)``. When the text fits, it is
    returned unchanged. Otherwise the full text is written to a spill file
    and the returned content is a head/tail (or head, or tail) preview with
    an inline note telling the model where the full output lives and how to
    inspect it. If the spill write fails the preview still carries the
    truncation note, just without a path.
    """
    if max_bytes <= 0:
        return text, False, None
    total_bytes = len(text.encode("utf-8", errors="replace"))
    if total_bytes <= max_bytes:
        return text, False, None

    spill_path = spill_output(text[: SPILL_HARD_CAP_BYTES * 4], prefix=prefix)

    if direction == "head":
        head = _cut_at_line_boundary(text, max_bytes, from_end=False)
        tail = ""
    elif direction == "tail":
        head = ""
        tail = _cut_at_line_boundary(text, max_bytes, from_end=True)
    else:  # head_tail
        head_budget = max(256, int(max_bytes * _HEAD_FRACTION))
        tail_budget = max(256, max_bytes - head_budget)
        head = _cut_at_line_boundary(text, head_budget, from_end=False)
        tail = _cut_at_line_boundary(text, tail_budget, from_end=True)

    shown = len(head.encode("utf-8", errors="replace")) + len(
        tail.encode("utf-8", errors="replace")
    )
    omitted = max(0, total_bytes - shown)
    if spill_path is not None:
        note = (
            f"\n\n[{label} truncated: {omitted:,} of {total_bytes:,} bytes omitted. "
            f"Full output saved to: {spill_path}\n"
            f"Inspect it with read_file (start_line/end_line) or grep on that path "
            f"instead of re-running the command.]\n\n"
        )
    else:
        note = f"\n\n[{label} truncated: {omitted:,} of {total_bytes:,} bytes omitted.]\n\n"

    if direction == "head":
        content = head + note.rstrip("\n")
    elif direction == "tail":
        content = note.lstrip("\n") + tail
    else:
        content = head + note + tail
    return content, True, spill_path


__all__ = [
    "SPILL_DIR_ENV",
    "SPILL_HARD_CAP_BYTES",
    "cleanup_spill_dir",
    "get_spill_dir",
    "spill_output",
    "truncate_with_spill",
]
