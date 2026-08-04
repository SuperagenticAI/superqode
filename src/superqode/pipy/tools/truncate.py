"""Output truncation shared by every tool.

Ported from ``packages/coding-agent/src/core/tools/truncate.ts`` of
earendil-works/pi (MIT). Limits are byte-based, never character-based, because
what matters is the payload sent to the model.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024
#: Max characters kept per grep match line.
GREP_MAX_LINE_LENGTH = 500


@dataclass(slots=True)
class TruncationResult:
    content: str
    truncated: bool = False
    #: Which limit was hit: ``lines``, ``bytes``, or None.
    truncated_by: str | None = None
    total_lines: int = 0
    total_bytes: int = 0
    output_lines: int = 0
    output_bytes: int = 0
    #: Only set by tail truncation, when a single line had to be cut mid-way.
    last_line_partial: bool = False
    #: Set when the very first line alone exceeds the byte limit.
    first_line_exceeds_limit: bool = False
    max_lines: int | None = None
    max_bytes: int | None = None


def format_size(num_bytes: int) -> str:
    """Human-readable size, matching pi's rounding exactly."""
    if num_bytes < 1024:
        return f"{num_bytes}B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f}KB"
    return f"{num_bytes / (1024 * 1024):.1f}MB"


def _byte_length(text: str) -> int:
    return len(text.encode("utf-8"))


def truncate_line(text: str, max_length: int = GREP_MAX_LINE_LENGTH) -> tuple[str, bool]:
    """Cut one long line, reporting whether it was cut."""
    if len(text) <= max_length:
        return text, False
    return text[:max_length], True


def truncate_head(
    content: str,
    *,
    max_lines: int | None = None,
    max_bytes: int | None = None,
) -> TruncationResult:
    """Keep the beginning. Used for file reads.

    Never returns a partial line: if the first line alone exceeds the byte
    limit, the content comes back empty with ``first_line_exceeds_limit`` set,
    so the caller can point the model at a bash fallback instead of handing it
    a corrupt fragment.
    """
    limit_lines = DEFAULT_MAX_LINES if max_lines is None else max_lines
    limit_bytes = DEFAULT_MAX_BYTES if max_bytes is None else max_bytes

    lines = content.split("\n")
    total_lines = len(lines)
    total_bytes = _byte_length(content)

    if total_lines <= limit_lines and total_bytes <= limit_bytes:
        return TruncationResult(
            content=content,
            truncated=False,
            truncated_by=None,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )

    kept: list[str] = []
    kept_bytes = 0
    truncated_by = "lines"
    for index, line in enumerate(lines):
        if index >= limit_lines:
            truncated_by = "lines"
            break
        # +1 for the newline that rejoining will add.
        addition = _byte_length(line) + (1 if kept else 0)
        if kept_bytes + addition > limit_bytes:
            truncated_by = "bytes"
            break
        kept.append(line)
        kept_bytes += addition

    if not kept:
        return TruncationResult(
            content="",
            truncated=True,
            truncated_by="bytes",
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=0,
            output_bytes=0,
            first_line_exceeds_limit=True,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )

    text = "\n".join(kept)
    return TruncationResult(
        content=text,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(kept),
        output_bytes=_byte_length(text),
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


def truncate_tail(
    content: str,
    *,
    max_lines: int | None = None,
    max_bytes: int | None = None,
) -> TruncationResult:
    """Keep the end. Used for command output, where the tail is what matters."""
    limit_lines = DEFAULT_MAX_LINES if max_lines is None else max_lines
    limit_bytes = DEFAULT_MAX_BYTES if max_bytes is None else max_bytes

    lines = content.split("\n")
    total_lines = len(lines)
    total_bytes = _byte_length(content)

    if total_lines <= limit_lines and total_bytes <= limit_bytes:
        return TruncationResult(
            content=content,
            truncated=False,
            truncated_by=None,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )

    kept: list[str] = []
    kept_bytes = 0
    truncated_by = "lines"
    last_line_partial = False

    for line in reversed(lines):
        if len(kept) >= limit_lines:
            truncated_by = "lines"
            break
        addition = _byte_length(line) + (1 if kept else 0)
        if kept_bytes + addition > limit_bytes:
            truncated_by = "bytes"
            if not kept:
                # A single line larger than the whole budget: keep its tail
                # rather than returning nothing, since for command output the
                # end of the line is the interesting part.
                encoded = line.encode("utf-8")[-limit_bytes:]
                partial = encoded.decode("utf-8", errors="ignore")
                kept.append(partial)
                kept_bytes = _byte_length(partial)
                last_line_partial = True
            break
        kept.append(line)
        kept_bytes += addition

    kept.reverse()
    text = "\n".join(kept)
    return TruncationResult(
        content=text,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(kept),
        output_bytes=_byte_length(text),
        last_line_partial=last_line_partial,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_LINES",
    "GREP_MAX_LINE_LENGTH",
    "TruncationResult",
    "format_size",
    "truncate_head",
    "truncate_line",
    "truncate_tail",
]
