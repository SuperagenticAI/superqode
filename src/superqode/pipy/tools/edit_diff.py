"""Exact and fuzzy text replacement for the edit tool.

Ported from ``packages/coding-agent/src/core/tools/edit-diff.ts`` of
earendil-works/pi (MIT). The error strings are reproduced verbatim, because
they are what teaches a model to retry with a better anchor.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

_SMART_SINGLE_QUOTES = "‘’‚‛"
_SMART_DOUBLE_QUOTES = "“”„‟"
_DASHES = "‐‑‒–—―−"
_SPACES = "            　"

_DASH_RE = re.compile(f"[{_DASHES}]")
_SPACE_RE = re.compile(f"[{_SPACES}]")
_SINGLE_QUOTE_RE = re.compile(f"[{_SMART_SINGLE_QUOTES}]")
_DOUBLE_QUOTE_RE = re.compile(f"[{_SMART_DOUBLE_QUOTES}]")


class EditError(ValueError):
    """Raised when an edit cannot be applied. Message goes back to the model."""


def detect_line_ending(content: str) -> str:
    crlf = content.find("\r\n")
    lf = content.find("\n")
    if lf == -1 or crlf == -1:
        return "\n"
    return "\r\n" if crlf < lf else "\n"


def normalize_to_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def restore_line_endings(text: str, ending: str) -> str:
    return text.replace("\n", "\r\n") if ending == "\r\n" else text


def strip_bom(content: str) -> tuple[str, str]:
    return ("﻿", content[1:]) if content.startswith("﻿") else ("", content)


def normalize_for_fuzzy_match(text: str) -> str:
    """Make a match tolerant of the ways text is silently rewritten.

    Trailing whitespace, smart quotes, Unicode dashes and exotic spaces all
    survive a copy-paste or a model's own re-typing, and none of them should
    stop an otherwise correct edit.
    """
    text = unicodedata.normalize("NFKC", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _SINGLE_QUOTE_RE.sub("'", text)
    text = _DOUBLE_QUOTE_RE.sub('"', text)
    text = _DASH_RE.sub("-", text)
    return _SPACE_RE.sub(" ", text)


def count_occurrences(content: str, old_text: str) -> int:
    return normalize_for_fuzzy_match(content).count(normalize_for_fuzzy_match(old_text))


def _not_found_error(path: str, index: int, total: int) -> EditError:
    if total == 1:
        return EditError(
            f"Could not find the exact text in {path}. The old text must match "
            "exactly including all whitespace and newlines."
        )
    return EditError(
        f"Could not find edits[{index}] in {path}. The oldText must match exactly "
        "including all whitespace and newlines."
    )


def _duplicate_error(path: str, index: int, total: int, occurrences: int) -> EditError:
    if total == 1:
        return EditError(
            f"Found {occurrences} occurrences of the text in {path}. The text must "
            "be unique. Please provide more context to make it unique."
        )
    return EditError(
        f"Found {occurrences} occurrences of edits[{index}] in {path}. Each oldText "
        "must be unique. Please provide more context to make it unique."
    )


def _empty_old_text_error(path: str, index: int, total: int) -> EditError:
    if total == 1:
        return EditError(f"oldText must not be empty in {path}.")
    return EditError(f"edits[{index}].oldText must not be empty in {path}.")


def _no_change_error(path: str, total: int) -> EditError:
    if total == 1:
        return EditError(
            f"No changes made to {path}. The replacement produced identical content. "
            "This might indicate an issue with special characters or the text not "
            "existing as expected."
        )
    return EditError(f"No changes made to {path}. The replacements produced identical content.")


def apply_edits(path: str, content: str, edits: list[dict[str, str]]) -> str:
    """Apply every edit against the *original* content.

    Each ``old_text`` must appear exactly once and the edits must not overlap.
    Replacements are applied back to front so earlier offsets stay valid.
    """
    total = len(edits)
    if total == 0:
        raise EditError(f"No edits provided for {path}.")

    spans: list[tuple[int, int, str]] = []
    fuzzy_content = normalize_for_fuzzy_match(content)

    for index, edit in enumerate(edits):
        old_text = edit.get("oldText", "")
        new_text = edit.get("newText", "")
        if not old_text:
            raise _empty_old_text_error(path, index, total)

        exact = content.count(old_text)
        if exact == 1:
            start = content.index(old_text)
            spans.append((start, start + len(old_text), new_text))
            continue
        if exact > 1:
            raise _duplicate_error(path, index, total, exact)

        # No exact hit. Try again in fuzzy space, then map the match back onto
        # the original offsets so the untouched text is preserved byte for byte.
        fuzzy_old = normalize_for_fuzzy_match(old_text)
        fuzzy_count = fuzzy_content.count(fuzzy_old)
        if fuzzy_count == 0:
            raise _not_found_error(path, index, total)
        if fuzzy_count > 1:
            raise _duplicate_error(path, index, total, fuzzy_count)

        located = _locate_fuzzy_span(content, old_text)
        if located is None:
            raise _not_found_error(path, index, total)
        spans.append((located[0], located[1], new_text))

    spans.sort(key=lambda span: span[0])
    for (_, previous_end, _), (next_start, _, _) in zip(spans, spans[1:]):
        if next_start < previous_end:
            raise EditError(
                f"Edits overlap in {path}. Each edits[].oldText must match a distinct, "
                "non-overlapping region. Merge nearby changes into one edit."
            )

    updated = content
    for start, end, replacement in reversed(spans):
        updated = updated[:start] + replacement + updated[end:]

    if updated == content:
        raise _no_change_error(path, total)
    return updated


def _locate_fuzzy_span(content: str, old_text: str) -> tuple[int, int] | None:
    """Find where a fuzzily-matched block sits in the original content.

    Walks candidate start offsets and compares normalised windows, so an edit
    whose only difference is a smart quote still lands on the right bytes.
    """
    fuzzy_old = normalize_for_fuzzy_match(old_text)
    target_lines = fuzzy_old.count("\n") + 1
    lines = content.split("\n")

    offset = 0
    for start_line in range(len(lines)):
        end_line = start_line + target_lines
        if end_line > len(lines):
            break
        window = "\n".join(lines[start_line:end_line])
        if normalize_for_fuzzy_match(window) == fuzzy_old:
            return offset, offset + len(window)
        offset += len(lines[start_line]) + 1
    return None


def generate_unified_patch(
    path: str,
    old_content: str,
    new_content: str,
    context_lines: int = 4,
) -> str:
    """Standard unified diff, for logs and for the UI."""
    diff = difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context_lines,
    )
    return "".join(diff)


def generate_diff_string(old_content: str, new_content: str, context_lines: int = 4) -> str:
    """Display-oriented diff without the file headers."""
    diff = difflib.unified_diff(
        old_content.splitlines(),
        new_content.splitlines(),
        lineterm="",
        n=context_lines,
    )
    return "\n".join(line for line in diff if not line.startswith(("---", "+++")))


def first_changed_line(old_content: str, new_content: str) -> int | None:
    """1-indexed line of the first change, for editor navigation."""
    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")
    for index, (before, after) in enumerate(zip(old_lines, new_lines)):
        if before != after:
            return index + 1
    if len(old_lines) != len(new_lines):
        return min(len(old_lines), len(new_lines)) + 1
    return None


__all__ = [
    "EditError",
    "apply_edits",
    "count_occurrences",
    "detect_line_ending",
    "first_changed_line",
    "generate_diff_string",
    "generate_unified_patch",
    "normalize_for_fuzzy_match",
    "normalize_to_lf",
    "restore_line_endings",
    "strip_bom",
]
