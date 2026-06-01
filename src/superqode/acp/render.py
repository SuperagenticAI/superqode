"""ACP tool-call rendering helpers.

Why this module exists
----------------------
Before this, ``on_tool_update`` in ``app_main.py`` pulled ``rawOutput`` out
of an ACP ``tool_call_update`` and dumped it into the TUI. That had two
problems:

1. **Noisy** — full stdout/stderr/JSON for every Read, Edit, Bash, etc.
   A 60-line file read swamped the screen.
2. **No diff** — Edits arrive in the spec-canonical channel
   (``content: [{type: "diff", ...}]``), but we never looked there. So
   users couldn't actually *see* what changed.

This module fixes both: it extracts diff blocks from the ACP content
array and renders them as a compact unified diff. Display verbosity is
threaded through so normal mode shows a 2-line summary (file +adds
-dels) while verbose mode shows the full hunks.

Why pure functions
------------------
No Textual imports here. The TUI layer is the one place that knows
about ``Text`` / ``RichLog``; this module just produces strings. That
keeps it trivially unit-testable and means a future ``--print`` /
headless renderer can reuse the same logic without dragging in
``textual``.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, List, Optional, Tuple


# Display modes mirror the ones already wired into ``ConversationLog``:
# ``minimal`` (status only), ``normal`` (summary), ``verbose`` (full).
# Keeping the strings identical means the toggle is a no-op rename
# rather than a parallel taxonomy.
DisplayMode = str


# Defaults are intentionally conservative. Diffs longer than this in
# normal mode collapse to a summary line; verbose mode honors the full
# patch. The numbers come from a quick survey of fast-agent
# (``apply_patch_preview.py`` defaults to 120) and what fits in a
# typical terminal pane without scrolling away the next tool call.
NORMAL_DIFF_MAX_LINES = 24
VERBOSE_DIFF_MAX_LINES = 200


def normalize_acp_tool_status(status: Any) -> str:
    """Normalize ACP agent status spellings into TUI lifecycle states."""
    value = str(status or "").strip().lower().replace("-", "_")
    if value in {"completed", "complete", "done", "success", "succeeded", "finished"}:
        return "completed"
    if value in {"failed", "fail", "error", "errored", "cancelled", "canceled"}:
        return "failed"
    if value in {"running", "started", "in_progress", "pending", "queued"}:
        return "running"
    return value or "running"


def display_title_from_update(update: dict[str, Any]) -> str:
    """Pick a useful display title from an ACP tool update/call."""
    for key in ("title", "name", "tool", "kind", "type"):
        value = update.get(key)
        if value:
            return str(value)
    return "Tool"


def extract_tool_arguments(update: dict[str, Any]) -> dict[str, Any]:
    """Return normalized argument/input mapping from ACP tool events."""
    for key in ("rawInput", "input", "arguments", "args", "params"):
        value = update.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def extract_raw_output_text(raw_output: Any, *, mode: DisplayMode = "normal") -> Optional[str]:
    """Convert raw ACP output into useful text without dumping noisy objects."""
    if raw_output is None:
        return None
    if isinstance(raw_output, str):
        return raw_output
    if isinstance(raw_output, dict):
        for key in ("output", "stdout", "stderr", "text", "message", "error", "result"):
            value = raw_output.get(key)
            if value not in (None, ""):
                return str(value)
        if mode == "verbose":
            return json.dumps(raw_output, indent=2, sort_keys=True, default=str)
        return json.dumps(raw_output, sort_keys=True, default=str)
    if isinstance(raw_output, list):
        if mode == "verbose":
            return json.dumps(raw_output, indent=2, default=str)
        return json.dumps(raw_output, default=str)
    return str(raw_output)


def extract_diff_blocks(content: Any) -> List[Tuple[str, str, str]]:
    """Pull ``(path, old_text, new_text)`` tuples out of an ACP content array.

    Tolerant to:
    - ``content`` being ``None`` (no content yet) or a non-list (some
      servers send a single block instead of an array).
    - Missing ``oldText`` (for create operations) — coerced to ``""``.
    - Unknown ``type`` values (skipped silently — we'd rather render
      what we can than reject the whole update over one weird block).
    """
    if content is None:
        return []
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        return []
    out: List[Tuple[str, str, str]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "diff":
            continue
        path = str(block.get("path", "") or "")
        new_text = str(block.get("newText", "") or "")
        old_text = str(block.get("oldText") or "")
        out.append((path, old_text, new_text))
    return out


def extract_text_blocks(content: Any) -> str:
    """Concatenate ``type=text`` blocks from an ACP content array.

    Used as the fallback when a tool's output isn't a diff — e.g. Read
    returning file contents, or Bash returning stdout — and the agent
    chose to surface it via ``content`` rather than ``rawOutput``.
    """
    if content is None:
        return ""
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        return ""
    parts: List[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", block.get("content", "")) or ""))
    return "".join(parts)


def count_line_changes(old_text: str, new_text: str) -> Tuple[int, int]:
    """Return ``(additions, deletions)`` for a pair of texts.

    This uses a line-set difference rather than a true LCS diff because
    we only need counts, not alignment. For typical edits (small,
    contiguous changes) the numbers match what ``git diff --stat``
    would report; for re-ordering edits they overcount, which is the
    safer direction (we don't want to hide a large change behind a
    "+0 -0" line).
    """
    if not old_text and new_text:
        return new_text.count("\n") + (0 if new_text.endswith("\n") else 1), 0
    if old_text and not new_text:
        return 0, old_text.count("\n") + (0 if old_text.endswith("\n") else 1)
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    # Lines that appear in exactly one side.
    old_set: dict[str, int] = {}
    new_set: dict[str, int] = {}
    for line in old_lines:
        old_set[line] = old_set.get(line, 0) + 1
    for line in new_lines:
        new_set[line] = new_set.get(line, 0) + 1
    additions = 0
    deletions = 0
    for line, count in new_set.items():
        diff = count - old_set.get(line, 0)
        if diff > 0:
            additions += diff
    for line, count in old_set.items():
        diff = count - new_set.get(line, 0)
        if diff > 0:
            deletions += diff
    return additions, deletions


def render_unified_diff(
    old_text: str,
    new_text: str,
    path: str = "",
    *,
    context: int = 2,
    max_lines: int = NORMAL_DIFF_MAX_LINES,
) -> str:
    """Produce a compact unified-diff string.

    Uses ``difflib.unified_diff`` for hunk layout. The leading file
    headers (``--- a/...`` / ``+++ b/...``) are dropped — they're noisy
    when we already show the path in the tool-call header above.

    Lines beyond ``max_lines`` are replaced with a single
    ``... N more lines ...`` marker so a 500-line edit doesn't blow
    the TUI buffer. The marker is placed at the cut point, not the
    end, so the user still sees the *start* of the change (which is
    usually the most informative).
    """
    import difflib

    if old_text == new_text:
        return ""

    diff_iter = difflib.unified_diff(
        old_text.splitlines(keepends=False),
        new_text.splitlines(keepends=False),
        n=context,
        lineterm="",
    )

    lines: List[str] = []
    omitted = 0
    cut = max_lines
    for line in diff_iter:
        # Skip the synthetic file headers — we render our own.
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if len(lines) < cut:
            lines.append(line)
        else:
            omitted += 1

    if omitted:
        lines.append(f"... {omitted} more line{'s' if omitted != 1 else ''} ...")

    return "\n".join(lines)


def summarize_diff_blocks(
    blocks: Iterable[Tuple[str, str, str]],
    mode: DisplayMode = "normal",
) -> str:
    """Render diff blocks for display, honoring the verbosity ``mode``.

    Output shape:
    - ``minimal``: ``""`` — caller falls back to the tool's status line.
    - ``normal``: one line per file, ``path +A -B`` (counts from
      :func:`count_line_changes`). If there's exactly one block, also
      include a tight unified diff capped at ``NORMAL_DIFF_MAX_LINES``.
    - ``verbose``: full unified diff per block, capped at
      ``VERBOSE_DIFF_MAX_LINES`` per block (still capped — runaway
      tool outputs are nobody's friend even in verbose mode).
    """
    blocks_list = list(blocks)
    if not blocks_list:
        return ""

    if mode == "minimal":
        return ""

    if mode == "verbose":
        chunks: List[str] = []
        for path, old_text, new_text in blocks_list:
            adds, dels = count_line_changes(old_text, new_text)
            header = f"{path}  +{adds} -{dels}" if path else f"+{adds} -{dels}"
            body = render_unified_diff(
                old_text,
                new_text,
                path,
                context=3,
                max_lines=VERBOSE_DIFF_MAX_LINES,
            )
            chunks.append(header + ("\n" + body if body else ""))
        return "\n\n".join(chunks)

    # normal mode
    summaries: List[str] = []
    for path, old_text, new_text in blocks_list:
        adds, dels = count_line_changes(old_text, new_text)
        label = path or "(unnamed)"
        summaries.append(f"{label}  +{adds} -{dels}")
    head = "\n".join(summaries)

    if len(blocks_list) == 1:
        path, old_text, new_text = blocks_list[0]
        body = render_unified_diff(
            old_text,
            new_text,
            path,
            context=2,
            max_lines=NORMAL_DIFF_MAX_LINES,
        )
        if body:
            return head + "\n" + body
    return head


def should_suppress_output(kind: str, status: str, mode: DisplayMode) -> bool:
    """Return True when the raw ``rawOutput`` for a tool call should be hidden.

    In ``normal`` mode, completed Read / Execute calls are best
    represented by their one-liner action row (``read foo.py``,
    ``run pytest``) — the actual stdout is signal-poor when the agent's
    next message will already cite the relevant pieces. Errors and
    non-zero exits are *always* shown regardless.

    In ``verbose`` mode nothing is suppressed.
    """
    if mode == "verbose":
        return False
    if status != "completed":
        return False
    k = (kind or "").lower()
    return k in ("read", "execute", "search", "fetch")


def render_acp_tool_output(
    *,
    kind: str,
    status: str,
    content: Any,
    raw_output: Any,
    mode: DisplayMode = "normal",
) -> Optional[str]:
    """Build the output string to pass to ``log.add_tool_call``.

    Resolution order:

    1. If ``content`` carries diff blocks, render them via
       :func:`summarize_diff_blocks` (and ignore ``raw_output``,
       which for Edit calls typically just duplicates the new
       content).
    2. If ``content`` carries text blocks and we're not suppressing
       them, return that text.
    3. Otherwise fall back to ``raw_output`` (the legacy path), unless
       :func:`should_suppress_output` says to hide it.

    Returns ``None`` when the caller should pass an empty output —
    distinct from an empty string so callers can choose whether to
    skip the output line entirely.
    """
    diffs = extract_diff_blocks(content)
    if diffs:
        rendered = summarize_diff_blocks(diffs, mode=mode)
        return rendered if rendered else None

    if should_suppress_output(kind, status, mode):
        return None

    text = extract_text_blocks(content)
    if text:
        return text

    if raw_output is None:
        return None
    return extract_raw_output_text(raw_output, mode=mode)
