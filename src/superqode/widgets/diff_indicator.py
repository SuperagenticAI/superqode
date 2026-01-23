"""
Diff Indicator Widget - Compact visual representation of file changes.

DiffChanges component, adapted for SuperQode's style.
Shows colored bars/indicators representing additions/deletions ratio.
"""

from __future__ import annotations

from typing import Optional
from rich.text import Text


# SuperQode colors
COLORS = {
    "addition": "#22c55e",
    "deletion": "#ef4444",
    "neutral": "#52525b",
    "text_dim": "#71717a",
    "text_muted": "#a1a1aa",
}


def render_diff_indicator(
    additions: int,
    deletions: int,
    variant: str = "bars",
    max_bars: int = 5,
) -> Text:
    """
    Render a compact diff indicator showing additions/deletions.

    Args:
        additions: Number of lines added
        deletions: Number of lines deleted
        variant: "bars" for visual bars, "text" for +X -Y text
        max_bars: Maximum number of bars to show (default 5)

    Returns:
        Rich Text object with the indicator
    """
    total = additions + deletions

    if variant == "text":
        # Simple text format: +X -Y
        text = Text()
        if additions > 0:
            text.append(f"+{additions}", style=f"bold {COLORS['addition']}")
        if deletions > 0:
            if additions > 0:
                text.append(" / ", style=COLORS["text_dim"])
            text.append(f"-{deletions}", style=f"bold {COLORS['deletion']}")
        if total == 0:
            text.append("0", style=COLORS["text_muted"])
        return text

    # Bars variant - visual representation
    if total == 0:
        # Show all neutral bars
        bars = Text()
        for _ in range(max_bars):
            bars.append("█", style=COLORS["neutral"])
        return bars

    # Calculate bar distribution
    if total < max_bars:
        # Small changes - show 1 bar each if present
        added_bars = 1 if additions > 0 else 0
        deleted_bars = 1 if deletions > 0 else 0
        neutral_bars = max_bars - added_bars - deleted_bars
    else:
        # Larger changes - proportional distribution
        percent_added = additions / total if total > 0 else 0
        percent_deleted = deletions / total if total > 0 else 0

        # Reserve at least 1 bar for each if present, but cap based on magnitude
        BLOCKS_FOR_COLORS = max_bars - 1 if total < 20 else max_bars

        added_raw = percent_added * BLOCKS_FOR_COLORS
        deleted_raw = percent_deleted * BLOCKS_FOR_COLORS

        added_bars = max(1, round(added_raw)) if additions > 0 else 0
        deleted_bars = max(1, round(deleted_raw)) if deletions > 0 else 0

        # Cap based on actual magnitude
        if additions > 0 and additions <= 5:
            added_bars = min(added_bars, 1)
        elif additions > 5 and additions <= 10:
            added_bars = min(added_bars, 2)

        if deletions > 0 and deletions <= 5:
            deleted_bars = min(deleted_bars, 1)
        elif deletions > 5 and deletions <= 10:
            deleted_bars = min(deleted_bars, 2)

        # Ensure we don't exceed max_bars
        total_allocated = added_bars + deleted_bars
        if total_allocated > BLOCKS_FOR_COLORS:
            if added_raw > deleted_raw:
                added_bars = BLOCKS_FOR_COLORS - deleted_bars
            else:
                deleted_bars = BLOCKS_FOR_COLORS - added_bars

        neutral_bars = max(0, max_bars - added_bars - deleted_bars)

    # Render bars
    bars = Text()
    for _ in range(added_bars):
        bars.append("█", style=COLORS["addition"])
    for _ in range(deleted_bars):
        bars.append("█", style=COLORS["deletion"])
    for _ in range(neutral_bars):
        bars.append("█", style=COLORS["neutral"])

    return bars


def render_diff_indicator_with_text(
    additions: int,
    deletions: int,
    show_bars: bool = True,
    show_text: bool = True,
) -> Text:
    """
    Render diff indicator with both bars and text.

    Args:
        additions: Number of lines added
        deletions: Number of lines deleted
        show_bars: Whether to show visual bars
        show_text: Whether to show +X -Y text

    Returns:
        Rich Text object with both bars and text
    """
    result = Text()

    if show_bars:
        bars = render_diff_indicator(additions, deletions, variant="bars")
        result.append(bars)
        if show_text:
            result.append("  ", style="")

    if show_text:
        text = render_diff_indicator(additions, deletions, variant="text")
        result.append(text)

    return result


__all__ = [
    "render_diff_indicator",
    "render_diff_indicator_with_text",
    "COLORS",
]
