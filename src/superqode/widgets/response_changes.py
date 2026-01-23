"""
Response Changes Widget - File changes section for final response display.

Shows a compact list of modified files with diff indicators,
with hints to view in sidebar for full diff exploration.
"""

from __future__ import annotations

from typing import List, Dict, Optional
from rich.text import Text
from rich.console import Group

from superqode.widgets.diff_indicator import render_diff_indicator_with_text, COLORS


# SuperQode colors
SQ_COLORS = {
    "success": "#22c55e",
    "info": "#06b6d4",
    "text_primary": "#fafafa",
    "text_secondary": "#e4e4e7",
    "text_muted": "#a1a1aa",
    "text_dim": "#71717a",
    "text_ghost": "#52525b",
    "border_subtle": "#1a1a1a",
    "primary_light": "#a855f7",
}


def render_file_changes_section(
    files_modified: List[str],
    file_diffs: Dict[str, Dict[str, int]],
    max_files: int = 10,
) -> Group:
    """
    Render the file changes section for the final response.

    Args:
        files_modified: List of modified file paths
        file_diffs: Dict mapping file_path -> {"additions": int, "deletions": int}
        max_files: Maximum number of files to show (default 10)

    Returns:
        Rich Group with the file changes section
    """
    items = []

    if not files_modified:
        return Group()

    # Calculate totals
    total_additions = sum(file_diffs.get(f, {}).get("additions", 0) for f in files_modified)
    total_deletions = sum(file_diffs.get(f, {}).get("deletions", 0) for f in files_modified)

    # Enhanced header with panel design
    header = Text()
    header.append("\n  ", style="")
    header.append("┌─ ", style=SQ_COLORS["border_subtle"])
    header.append("📝 File Changes", style=f"bold {SQ_COLORS['text_primary']}")
    header.append(" ─", style=SQ_COLORS["border_subtle"])

    # Summary stats in header
    summary_parts = []
    summary_parts.append(f"{len(files_modified)} file{'s' if len(files_modified) != 1 else ''}")
    if total_additions > 0 or total_deletions > 0:
        change_parts = []
        if total_additions > 0:
            change_parts.append(f"+{total_additions}")
        if total_deletions > 0:
            change_parts.append(f"-{total_deletions}")
        summary_parts.append(" ".join(change_parts))

    summary_text = " • ".join(summary_parts)
    remaining_width = 65 - len(summary_text) - 3
    header.append("─" * max(1, remaining_width), style=SQ_COLORS["border_subtle"])
    header.append(" ", style="")
    header.append(summary_text, style=SQ_COLORS["text_muted"])
    header.append(" ─┐\n", style=SQ_COLORS["border_subtle"])

    items.append(header)

    # File list
    files_text = Text()

    # Calculate max path length for alignment (but don't truncate)
    max_path_len = max(len(fp) for fp in files_modified[:max_files]) if files_modified else 0

    for i, file_path in enumerate(files_modified[:max_files]):
        # Panel border for each file item
        files_text.append("  │ ", style=SQ_COLORS["border_subtle"])

        # Selection indicator (first file)
        if i == 0:
            files_text.append("▸ ", style=f"bold {SQ_COLORS['primary_light']}")
        else:
            files_text.append("  ", style="")

        # Get diff data
        diff_data = file_diffs.get(file_path, {})
        additions = diff_data.get("additions", 0)
        deletions = diff_data.get("deletions", 0)

        # File icon based on change type
        if additions > deletions * 2:
            file_icon = "📄"
        elif deletions > additions * 2:
            file_icon = "🗑"
        else:
            file_icon = "✏️"
        files_text.append(f"{file_icon} ", style=SQ_COLORS["text_muted"])

        # File path - show FULL path (no truncation)
        files_text.append(file_path, style=SQ_COLORS["text_secondary"])

        # Spacing for alignment (but allow wrapping if path is very long)
        # Use reasonable padding, but don't force alignment if paths are extremely long
        if max_path_len < 80:  # Only align if paths are reasonably sized
            padding = max(1, max_path_len + 5 - len(file_path))
            files_text.append(" " * padding, style="")
        else:
            # For very long paths, just add minimal spacing
            files_text.append("  ", style="")

        # Diff indicator
        indicator = render_diff_indicator_with_text(
            additions, deletions, show_bars=True, show_text=True
        )
        files_text.append(indicator)

        # Sidebar hint - more subtle
        files_text.append("  ", style="")
        files_text.append("→", style=SQ_COLORS["text_ghost"])

        files_text.append("\n", style="")

    # Show "and X more" if there are more files - enhanced
    if len(files_modified) > max_files:
        files_text.append("  │ ", style=SQ_COLORS["border_subtle"])
        files_text.append("  ", style="")
        files_text.append("⋯ ", style=SQ_COLORS["text_dim"])
        files_text.append(
            f"{len(files_modified) - max_files} more file", style=SQ_COLORS["text_dim"]
        )
        if len(files_modified) - max_files != 1:
            files_text.append("s", style=SQ_COLORS["text_dim"])
        files_text.append(" (use :sidebar to view all)", style=SQ_COLORS["text_ghost"])
        files_text.append("\n", style="")

    # Close file list panel
    files_text.append("  └", style=SQ_COLORS["border_subtle"])
    files_text.append("─" * 65, style=SQ_COLORS["border_subtle"])
    files_text.append("┘\n", style=SQ_COLORS["border_subtle"])

    items.append(files_text)

    # Enhanced footer hint
    footer = Text()
    footer.append("  │ ", style=SQ_COLORS["border_subtle"])
    footer.append("💡 ", style=SQ_COLORS["info"])
    footer.append("Tip: ", style=SQ_COLORS["text_muted"])
    footer.append(":sidebar", style=f"bold {SQ_COLORS['info']}")
    footer.append(" to explore all changes", style=SQ_COLORS["text_muted"])
    footer.append("\n", style="")

    items.append(footer)

    return Group(*items)


def render_file_changes_compact(
    files_modified: List[str],
    file_diffs: Dict[str, Dict[str, int]],
) -> Text:
    """
    Render a very compact file changes summary (for completion summary).

    Args:
        files_modified: List of modified file paths
        file_diffs: Dict mapping file_path -> {"additions": int, "deletions": int}

    Returns:
        Rich Text with compact summary
    """
    if not files_modified:
        return Text()

    text = Text()

    # Calculate totals
    total_additions = sum(file_diffs.get(f, {}).get("additions", 0) for f in files_modified)
    total_deletions = sum(file_diffs.get(f, {}).get("deletions", 0) for f in files_modified)

    text.append("  📝 ", style=f"bold {SQ_COLORS['success']}")
    text.append(f"{len(files_modified)} file", style=SQ_COLORS["text_secondary"])
    if len(files_modified) != 1:
        text.append("s", style=SQ_COLORS["text_secondary"])
    text.append(" modified", style=SQ_COLORS["text_muted"])

    if total_additions > 0 or total_deletions > 0:
        text.append("  (", style=SQ_COLORS["text_dim"])
        if total_additions > 0:
            text.append(f"+{total_additions}", style=f"bold {COLORS['addition']}")
        if total_deletions > 0:
            if total_additions > 0:
                text.append(" / ", style=SQ_COLORS["text_dim"])
            text.append(f"-{total_deletions}", style=f"bold {COLORS['deletion']}")
        text.append(")", style=SQ_COLORS["text_dim"])

    text.append("\n", style="")

    return text


__all__ = [
    "render_file_changes_section",
    "render_file_changes_compact",
]
