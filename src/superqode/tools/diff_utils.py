"""Shared helpers for file-change tool diff metadata."""

from __future__ import annotations

import difflib
from typing import Tuple


def build_unified_diff(
    old_content: str,
    new_content: str,
    *,
    path: str,
    context: int = 3,
) -> str:
    """Return a unified diff between two text blobs."""
    if old_content == new_content:
        return ""
    diff = difflib.unified_diff(
        old_content.splitlines(keepends=False),
        new_content.splitlines(keepends=False),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context,
        lineterm="",
    )
    return "\n".join(diff)


def diff_stats(diff_text: str) -> Tuple[int, int]:
    """Count changed lines in a unified diff."""
    additions = sum(
        1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    deletions = sum(
        1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---")
    )
    return additions, deletions


def summarize_turn_changes(results) -> Tuple[str, str]:
    """Aggregate file changes from one turn's tool results (codex turn-diff).

    ``results`` is an iterable of objects with a ``metadata`` dict (ToolResult
    or compatible). Returns ``(summary_line, combined_diff)`` — both empty
    strings when the turn changed nothing. The summary is cheap enough to
    emit on every turn; the combined diff feeds UIs and hooks.
    """
    per_file: dict = {}
    diffs = []
    for result in results:
        metadata = getattr(result, "metadata", None) or {}
        diff_text = metadata.get("diff_text")
        if not diff_text:
            continue
        path = metadata.get("path", "?")
        additions = int(metadata.get("additions", 0) or 0)
        deletions = int(metadata.get("deletions", 0) or 0)
        prev_add, prev_del = per_file.get(path, (0, 0))
        per_file[path] = (prev_add + additions, prev_del + deletions)
        diffs.append(diff_text)
    if not per_file:
        return "", ""
    total_add = sum(a for a, _ in per_file.values())
    total_del = sum(d for _, d in per_file.values())
    names = ", ".join(sorted(per_file)[:5])
    if len(per_file) > 5:
        names += f", +{len(per_file) - 5} more"
    summary = f"Turn changed {len(per_file)} file(s) (+{total_add}/-{total_del}): {names}"
    return summary, "\n".join(diffs)
