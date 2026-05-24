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
