"""
SuperQode Diff View - Beautiful Code Diff Display

A unique diff visualization with:
- Gradient-styled headers
- Side-by-side and unified views
- Syntax highlighting
- Line-level change indicators
- Textual widget with synchronized scrolling
- Auto-detection of split/unified based on terminal width
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Tuple, Optional

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED, SIMPLE, MINIMAL

# Textual imports for widget-based diff view
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.widgets import Static
from textual.reactive import reactive, var
from textual.message import Message
from textual.binding import Binding
from textual import on


class DiffMode(Enum):
    """Diff display mode."""

    UNIFIED = "unified"
    SPLIT = "split"
    COMPACT = "compact"


@dataclass
class DiffLine:
    """A single line in a diff."""

    line_no_old: Optional[int]
    line_no_new: Optional[int]
    content: str
    change_type: str  # '+', '-', ' ', '~' (modified)


@dataclass
class DiffHunk:
    """A group of related changes."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[DiffLine]


@dataclass
class FileDiff:
    """Complete diff for a file."""

    path: str
    old_content: str
    new_content: str
    hunks: List[DiffHunk]
    additions: int
    deletions: int
    is_new: bool
    is_deleted: bool


# SuperQode gradient colors
DIFF_COLORS = {
    "header_gradient": ["#a855f7", "#ec4899", "#f97316"],
    "addition": "#22c55e",
    "addition_bg": "#22c55e15",
    "deletion": "#ef4444",
    "deletion_bg": "#ef444415",
    "context": "#71717a",
    "line_no": "#52525b",
    "border": "#2a2a2a",
    "highlight_add": "#22c55e30",
    "highlight_del": "#ef444430",
}

# Icons for diff display
DIFF_ICONS = {
    "file": "📄",
    "new_file": "✨",
    "deleted_file": "🗑️",
    "modified": "📝",
    "addition": "➕",
    "deletion": "➖",
    "unchanged": "│",
    "hunk": "┄",
}


def compute_diff(old_content: str, new_content: str, path: str = "file") -> FileDiff:
    """
    Compute the diff between two versions of content.

    Args:
        old_content: Original content
        new_content: New content
        path: File path for display

    Returns:
        FileDiff object with all diff information
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    # Handle edge cases
    is_new = not old_content.strip()
    is_deleted = not new_content.strip()

    # Get unified diff
    differ = difflib.unified_diff(
        old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""
    )

    hunks: List[DiffHunk] = []
    current_hunk: Optional[DiffHunk] = None
    additions = 0
    deletions = 0

    old_line_no = 0
    new_line_no = 0

    for line in differ:
        if line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            if current_hunk:
                hunks.append(current_hunk)

            parts = line.split()
            old_info = parts[1][1:].split(",")
            new_info = parts[2][1:].split(",")

            old_start = int(old_info[0])
            old_count = int(old_info[1]) if len(old_info) > 1 else 1
            new_start = int(new_info[0])
            new_count = int(new_info[1]) if len(new_info) > 1 else 1

            current_hunk = DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=[],
            )
            old_line_no = old_start
            new_line_no = new_start

        elif line.startswith("---") or line.startswith("+++"):
            continue

        elif current_hunk is not None:
            content = line[1:] if len(line) > 1 else ""

            if line.startswith("+"):
                current_hunk.lines.append(
                    DiffLine(
                        line_no_old=None,
                        line_no_new=new_line_no,
                        content=content.rstrip("\n"),
                        change_type="+",
                    )
                )
                new_line_no += 1
                additions += 1

            elif line.startswith("-"):
                current_hunk.lines.append(
                    DiffLine(
                        line_no_old=old_line_no,
                        line_no_new=None,
                        content=content.rstrip("\n"),
                        change_type="-",
                    )
                )
                old_line_no += 1
                deletions += 1

            else:
                current_hunk.lines.append(
                    DiffLine(
                        line_no_old=old_line_no,
                        line_no_new=new_line_no,
                        content=content.rstrip("\n"),
                        change_type=" ",
                    )
                )
                old_line_no += 1
                new_line_no += 1

    if current_hunk:
        hunks.append(current_hunk)

    return FileDiff(
        path=path,
        old_content=old_content,
        new_content=new_content,
        hunks=hunks,
        additions=additions,
        deletions=deletions,
        is_new=is_new,
        is_deleted=is_deleted,
    )


def render_diff_header(diff: FileDiff, console: Console) -> None:
    """Render a beautiful diff header."""
    # Determine icon and status
    if diff.is_new:
        icon = DIFF_ICONS["new_file"]
        status = "New File"
        status_color = DIFF_COLORS["addition"]
    elif diff.is_deleted:
        icon = DIFF_ICONS["deleted_file"]
        status = "Deleted"
        status_color = DIFF_COLORS["deletion"]
    else:
        icon = DIFF_ICONS["modified"]
        status = "Modified"
        status_color = "#f97316"

    # Build header text
    header = Text()
    header.append(f" {icon} ", style="bold")
    header.append(diff.path, style="bold white")
    header.append("  ", style="")
    header.append(f"[{status}]", style=f"bold {status_color}")
    header.append("  ", style="")
    header.append(f"+{diff.additions}", style=f"bold {DIFF_COLORS['addition']}")
    header.append(" / ", style="dim")
    header.append(f"-{diff.deletions}", style=f"bold {DIFF_COLORS['deletion']}")

    console.print(Panel(header, border_style=DIFF_COLORS["border"], box=ROUNDED, padding=(0, 1)))


def render_diff_unified(diff: FileDiff, console: Console, context_lines: int = 3) -> None:
    """Render diff in unified format."""
    render_diff_header(diff, console)

    if not diff.hunks:
        console.print("  [dim]No changes[/dim]")
        return

    for hunk in diff.hunks:
        # Hunk separator
        hunk_header = Text()
        hunk_header.append(f" {DIFF_ICONS['hunk']} ", style="dim cyan")
        hunk_header.append(
            f"@@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@",
            style="dim cyan",
        )
        console.print(hunk_header)

        # Render lines
        for line in hunk.lines:
            line_text = Text()

            # Line numbers
            old_no = f"{line.line_no_old:>4}" if line.line_no_old else "    "
            new_no = f"{line.line_no_new:>4}" if line.line_no_new else "    "
            line_text.append(f" {old_no} {new_no} ", style=DIFF_COLORS["line_no"])

            # Change indicator and content
            if line.change_type == "+":
                line_text.append("│", style=DIFF_COLORS["addition"])
                line_text.append(f" {line.content}", style=f"on {DIFF_COLORS['addition_bg']}")
            elif line.change_type == "-":
                line_text.append("│", style=DIFF_COLORS["deletion"])
                line_text.append(f" {line.content}", style=f"on {DIFF_COLORS['deletion_bg']}")
            else:
                line_text.append("│", style="dim")
                line_text.append(f" {line.content}", style="")

            console.print(line_text)

    console.print()


def render_diff_split(diff: FileDiff, console: Console, width: int = 80) -> None:
    """Render diff in side-by-side split format."""
    render_diff_header(diff, console)

    if not diff.hunks:
        console.print("  [dim]No changes[/dim]")
        return

    half_width = (width - 10) // 2

    for hunk in diff.hunks:
        # Collect old and new lines separately
        old_lines: List[Tuple[Optional[int], str, str]] = []
        new_lines: List[Tuple[Optional[int], str, str]] = []

        for line in hunk.lines:
            if line.change_type == "-":
                old_lines.append((line.line_no_old, line.content, "-"))
            elif line.change_type == "+":
                new_lines.append((line.line_no_new, line.content, "+"))
            else:
                old_lines.append((line.line_no_old, line.content, " "))
                new_lines.append((line.line_no_new, line.content, " "))

        # Pad to same length
        max_len = max(len(old_lines), len(new_lines))
        while len(old_lines) < max_len:
            old_lines.append((None, "", "/"))
        while len(new_lines) < max_len:
            new_lines.append((None, "", "/"))

        # Render side by side
        for (old_no, old_content, old_type), (new_no, new_content, new_type) in zip(
            old_lines, new_lines
        ):
            line_text = Text()

            # Old side
            old_no_str = f"{old_no:>4}" if old_no else "    "
            line_text.append(f" {old_no_str} ", style=DIFF_COLORS["line_no"])

            if old_type == "-":
                line_text.append("─", style=DIFF_COLORS["deletion"])
                content = old_content[:half_width].ljust(half_width)
                line_text.append(content, style=f"on {DIFF_COLORS['deletion_bg']}")
            elif old_type == "/":
                line_text.append("╲", style="dim")
                line_text.append("╲" * half_width, style="dim")
            else:
                line_text.append("│", style="dim")
                line_text.append(old_content[:half_width].ljust(half_width), style="")

            line_text.append(" │ ", style="dim")

            # New side
            new_no_str = f"{new_no:>4}" if new_no else "    "
            line_text.append(f"{new_no_str} ", style=DIFF_COLORS["line_no"])

            if new_type == "+":
                line_text.append("─", style=DIFF_COLORS["addition"])
                content = new_content[:half_width].ljust(half_width)
                line_text.append(content, style=f"on {DIFF_COLORS['addition_bg']}")
            elif new_type == "/":
                line_text.append("╲", style="dim")
                line_text.append("╲" * half_width, style="dim")
            else:
                line_text.append("│", style="dim")
                line_text.append(new_content[:half_width].ljust(half_width), style="")

            console.print(line_text)

    console.print()


def render_diff_compact(diff: FileDiff, console: Console) -> None:
    """Render a compact summary of changes."""
    # Determine icon and status
    if diff.is_new:
        icon = DIFF_ICONS["new_file"]
        status_style = f"bold {DIFF_COLORS['addition']}"
    elif diff.is_deleted:
        icon = DIFF_ICONS["deleted_file"]
        status_style = f"bold {DIFF_COLORS['deletion']}"
    else:
        icon = DIFF_ICONS["modified"]
        status_style = "bold #f97316"

    line = Text()
    line.append(f"  {icon} ", style="")
    line.append(diff.path, style=status_style)
    line.append("  ", style="")
    line.append(f"+{diff.additions}", style=f"bold {DIFF_COLORS['addition']}")
    line.append("/", style="dim")
    line.append(f"-{diff.deletions}", style=f"bold {DIFF_COLORS['deletion']}")

    console.print(line)


def render_diff(
    diff: FileDiff, console: Console, mode: DiffMode = DiffMode.UNIFIED, width: int = 80
) -> None:
    """Render a diff with the specified mode."""
    if mode == DiffMode.UNIFIED:
        render_diff_unified(diff, console)
    elif mode == DiffMode.SPLIT:
        render_diff_split(diff, console, width)
    else:
        render_diff_compact(diff, console)


class DiffViewer:
    """Interactive diff viewer for multiple files."""

    def __init__(self, console: Console):
        self.console = console
        self.diffs: List[FileDiff] = []
        self.current_index = 0
        self.mode = DiffMode.UNIFIED

    def add_diff(self, old_content: str, new_content: str, path: str) -> FileDiff:
        """Add a file diff to the viewer."""
        diff = compute_diff(old_content, new_content, path)
        self.diffs.append(diff)
        return diff

    def render_all(self) -> None:
        """Render all diffs."""
        if not self.diffs:
            self.console.print("  [dim]No changes to display[/dim]")
            return

        # Summary header
        total_additions = sum(d.additions for d in self.diffs)
        total_deletions = sum(d.deletions for d in self.diffs)

        header = Text()
        header.append(f" 📊 ", style="bold")
        header.append(f"{len(self.diffs)} file(s) changed", style="bold white")
        header.append("  ", style="")
        header.append(f"+{total_additions}", style=f"bold {DIFF_COLORS['addition']}")
        header.append(" / ", style="dim")
        header.append(f"-{total_deletions}", style=f"bold {DIFF_COLORS['deletion']}")

        self.console.print(Panel(header, border_style="#a855f7", box=ROUNDED, padding=(0, 1)))
        self.console.print()

        # Render each diff
        for diff in self.diffs:
            render_diff(diff, self.console, self.mode)

    def render_summary(self) -> None:
        """Render a compact summary of all changes."""
        if not self.diffs:
            self.console.print("  [dim]No changes[/dim]")
            return

        for diff in self.diffs:
            render_diff_compact(diff, self.console)

    def set_mode(self, mode: DiffMode) -> None:
        """Set the display mode."""
        self.mode = mode


# ============================================================================
# TEXTUAL WIDGET-BASED DIFF VIEW WITH SYNCHRONIZED SCROLLING
# ============================================================================


class DiffScrollPane(ScrollableContainer):
    """Scrollable pane for diff content with scroll synchronization."""

    DEFAULT_CSS = """
    DiffScrollPane {
        width: 1fr;
        height: 100%;
        background: #000000;
        scrollbar-size: 1 1;
        overflow-x: auto;
        overflow-y: scroll;
    }
    """

    scroll_link: var[Optional["DiffScrollPane"]] = var(None)

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Synchronize vertical scroll with linked pane."""
        super().watch_scroll_y(old_value, new_value)
        if self.scroll_link and self.scroll_link.scroll_y != new_value:
            self.scroll_link.scroll_y = new_value

    def watch_scroll_x(self, old_value: float, new_value: float) -> None:
        """Synchronize horizontal scroll with linked pane."""
        super().watch_scroll_x(old_value, new_value)
        if self.scroll_link and self.scroll_link.scroll_x != new_value:
            self.scroll_link.scroll_x = new_value


class DiffLineNumbers(Static):
    """Widget showing line numbers for a diff pane."""

    DEFAULT_CSS = """
    DiffLineNumbers {
        width: 5;
        height: auto;
        background: #0a0a0a;
        padding: 0;
    }
    """

    def __init__(self, numbers: List[Optional[int]], styles: List[str], **kwargs):
        super().__init__(**kwargs)
        self.numbers = numbers
        self.styles = styles

    def render(self) -> Text:
        """Render line numbers with appropriate colors."""
        t = Text()
        for i, (num, style) in enumerate(zip(self.numbers, self.styles)):
            if num is None:
                t.append("     \n", style="#1a1a1a")
            else:
                if style == "+":
                    t.append(f"{num:>4} \n", style=f"bold on {DIFF_COLORS['addition_bg']}")
                elif style == "-":
                    t.append(f"{num:>4} \n", style=f"bold on {DIFF_COLORS['deletion_bg']}")
                else:
                    t.append(f"{num:>4} \n", style=DIFF_COLORS["line_no"])
        return t


class DiffAnnotations(Static):
    """Widget showing +/- annotations for diff lines."""

    DEFAULT_CSS = """
    DiffAnnotations {
        width: 3;
        height: auto;
        background: #000000;
        padding: 0;
    }
    """

    def __init__(self, annotations: List[str], **kwargs):
        super().__init__(**kwargs)
        self.annotations = annotations

    def render(self) -> Text:
        """Render annotations with colors."""
        t = Text()
        for ann in self.annotations:
            if ann == "+":
                t.append(f" {ann} \n", style=f"bold {DIFF_COLORS['addition']}")
            elif ann == "-":
                t.append(f" {ann} \n", style=f"bold {DIFF_COLORS['deletion']}")
            elif ann == "/":
                t.append(" ╲ \n", style="#1a1a1a")
            else:
                t.append("   \n", style="")
        return t


class DiffCodeContent(Static):
    """Widget showing code content for a diff pane."""

    DEFAULT_CSS = """
    DiffCodeContent {
        width: 1fr;
        height: auto;
        background: #000000;
        padding: 0;
    }
    """

    def __init__(self, lines: List[Tuple[str, str]], **kwargs):
        """
        Args:
            lines: List of (content, change_type) tuples
        """
        super().__init__(**kwargs)
        self.lines = lines

    def render(self) -> Text:
        """Render code lines with appropriate styling."""
        t = Text()
        for content, change_type in self.lines:
            if change_type == "+":
                t.append(f"{content}\n", style=f"on {DIFF_COLORS['addition_bg']}")
            elif change_type == "-":
                t.append(f"{content}\n", style=f"on {DIFF_COLORS['deletion_bg']}")
            elif change_type == "/":
                # Hatch pattern for missing lines
                hatch = "╲" * max(1, len(content) if content else 40)
                t.append(f"{hatch}\n", style="#1a1a1a")
            else:
                t.append(f"{content}\n", style="")
        return t


class SplitDiffWidget(Container):
    """
    Interactive split diff view with synchronized scrolling.

    Features:
    - Side-by-side comparison
    - Synchronized scroll between panes
    - Line annotations with colors (+/-)
    - Auto-detection of split vs unified based on width
    - Toggle between split and unified modes
    """

    DEFAULT_CSS = """
    SplitDiffWidget {
        width: 100%;
        height: auto;
        min-height: 5;
        max-height: 30;
        background: #000000;
        border: solid #1a1a1a;
        padding: 0;
    }

    SplitDiffWidget #diff-header {
        height: 2;
        background: #0a0a0a;
        border-bottom: solid #1a1a1a;
        padding: 0 1;
    }

    SplitDiffWidget #diff-content {
        height: 1fr;
        layout: horizontal;
    }

    SplitDiffWidget .diff-pane {
        width: 1fr;
        height: 100%;
        layout: horizontal;
    }

    SplitDiffWidget .diff-pane-left {
        border-right: solid #1a1a1a;
    }

    SplitDiffWidget #unified-content {
        width: 100%;
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("d", "toggle_mode", "Toggle split/unified", show=True),
    ]

    split_mode: reactive[bool] = reactive(True)
    auto_detect: var[bool] = var(True)

    class ModeToggled(Message):
        """Message when mode is toggled."""

        def __init__(self, is_split: bool) -> None:
            self.is_split = is_split
            super().__init__()

    def __init__(self, old_content: str, new_content: str, path: str = "file", **kwargs):
        super().__init__(**kwargs)
        self.old_content = old_content
        self.new_content = new_content
        self.path = path
        self._diff = compute_diff(old_content, new_content, path)

    def compose(self) -> ComposeResult:
        """Compose the diff widget."""
        # Header
        yield Static(self._render_header(), id="diff-header")

        # Content area
        with Container(id="diff-content"):
            if self.split_mode:
                yield from self._compose_split()
            else:
                yield from self._compose_unified()

    def _render_header(self) -> Text:
        """Render the diff header."""
        t = Text()
        t.append("\n", style="")

        # File icon based on status
        if self._diff.is_new:
            t.append(" ✨ ", style="bold #22c55e")
            status = "New File"
            status_color = "#22c55e"
        elif self._diff.is_deleted:
            t.append(" 🗑️ ", style="bold #ef4444")
            status = "Deleted"
            status_color = "#ef4444"
        else:
            t.append(" 📝 ", style="bold #f97316")
            status = "Modified"
            status_color = "#f97316"

        t.append(self._diff.path, style="bold white")
        t.append(f"  [{status}]", style=f"bold {status_color}")
        t.append("  ", style="")
        t.append(f"+{self._diff.additions}", style=f"bold {DIFF_COLORS['addition']}")
        t.append(" / ", style="#52525b")
        t.append(f"-{self._diff.deletions}", style=f"bold {DIFF_COLORS['deletion']}")
        t.append("  ", style="")
        mode_text = "split" if self.split_mode else "unified"
        t.append(f"[{mode_text}]", style="#52525b")
        t.append("  ", style="")
        t.append("d", style="bold #a855f7")
        t.append(" toggle", style="#3f3f46")

        return t

    def _compose_split(self) -> ComposeResult:
        """Compose split view with synchronized scroll."""
        # Collect lines for old and new content
        old_lines: List[Tuple[Optional[int], str, str]] = []
        new_lines: List[Tuple[Optional[int], str, str]] = []

        for hunk in self._diff.hunks:
            for line in hunk.lines:
                if line.change_type == "-":
                    old_lines.append((line.line_no_old, line.content, "-"))
                elif line.change_type == "+":
                    new_lines.append((line.line_no_new, line.content, "+"))
                else:
                    old_lines.append((line.line_no_old, line.content, " "))
                    new_lines.append((line.line_no_new, line.content, " "))

        # Pad to same length
        max_len = max(len(old_lines), len(new_lines))
        while len(old_lines) < max_len:
            old_lines.append((None, "", "/"))
        while len(new_lines) < max_len:
            new_lines.append((None, "", "/"))

        # Build the panes
        old_numbers = [x[0] for x in old_lines]
        old_annotations = [x[2] for x in old_lines]
        old_code = [(x[1], x[2]) for x in old_lines]

        new_numbers = [x[0] for x in new_lines]
        new_annotations = [x[2] for x in new_lines]
        new_code = [(x[1], x[2]) for x in new_lines]

        # Left pane (old)
        with DiffScrollPane(id="left-pane", classes="diff-pane diff-pane-left") as left_pane:
            yield DiffLineNumbers(old_numbers, old_annotations, id="left-numbers")
            yield DiffAnnotations(old_annotations, id="left-annotations")
            yield DiffCodeContent(old_code, id="left-code")

        # Right pane (new)
        with DiffScrollPane(id="right-pane", classes="diff-pane") as right_pane:
            yield DiffLineNumbers(new_numbers, new_annotations, id="right-numbers")
            yield DiffAnnotations(new_annotations, id="right-annotations")
            yield DiffCodeContent(new_code, id="right-code")

    def _compose_unified(self) -> ComposeResult:
        """Compose unified view."""
        lines: List[Tuple[Optional[int], Optional[int], str, str]] = []

        for hunk in self._diff.hunks:
            for line in hunk.lines:
                lines.append((line.line_no_old, line.line_no_new, line.content, line.change_type))

        # Render unified content
        t = Text()
        for old_no, new_no, content, change_type in lines:
            # Line numbers
            old_str = f"{old_no:>4}" if old_no else "    "
            new_str = f"{new_no:>4}" if new_no else "    "
            t.append(f" {old_str} {new_str} ", style=DIFF_COLORS["line_no"])

            # Change indicator and content
            if change_type == "+":
                t.append("│", style=DIFF_COLORS["addition"])
                t.append(f" {content}\n", style=f"on {DIFF_COLORS['addition_bg']}")
            elif change_type == "-":
                t.append("│", style=DIFF_COLORS["deletion"])
                t.append(f" {content}\n", style=f"on {DIFF_COLORS['deletion_bg']}")
            else:
                t.append("│", style="#3f3f46")
                t.append(f" {content}\n", style="")

        with ScrollableContainer(id="unified-content"):
            yield Static(t, id="unified-text")

    def on_mount(self) -> None:
        """Link the scroll panes after mount."""
        if self.split_mode:
            self._link_scroll_panes()

    def _link_scroll_panes(self) -> None:
        """Link the two scroll panes for synchronized scrolling."""
        try:
            left = self.query_one("#left-pane", DiffScrollPane)
            right = self.query_one("#right-pane", DiffScrollPane)
            left.scroll_link = right
            right.scroll_link = left
        except Exception:
            pass

    def watch_split_mode(self, split_mode: bool) -> None:
        """Recompose when mode changes."""
        # Remove old content and recompose
        try:
            content = self.query_one("#diff-content", Container)
            content.remove_children()
            if split_mode:
                for widget in self._compose_split():
                    content.mount(widget)
                self._link_scroll_panes()
            else:
                for widget in self._compose_unified():
                    content.mount(widget)
            # Update header
            self.query_one("#diff-header", Static).update(self._render_header())
        except Exception:
            pass

    def action_toggle_mode(self) -> None:
        """Toggle between split and unified mode."""
        self.split_mode = not self.split_mode
        self.post_message(self.ModeToggled(self.split_mode))

    def on_resize(self, event) -> None:
        """Auto-detect best mode based on width."""
        if self.auto_detect:
            # If terminal is narrow, use unified mode
            if event.size.width < 100:
                if self.split_mode:
                    self.split_mode = False
            else:
                if not self.split_mode:
                    self.split_mode = True


class UnifiedDiffWidget(Container):
    """Simpler unified diff widget for display in conversation."""

    DEFAULT_CSS = """
    UnifiedDiffWidget {
        width: 100%;
        height: auto;
        max-height: 25;
        background: #0a0a0a;
        border: solid #1a1a1a;
        padding: 0;
    }

    UnifiedDiffWidget #unified-header {
        height: 2;
        background: #0a0a0a;
        border-bottom: solid #1a1a1a;
        padding: 0 1;
    }

    UnifiedDiffWidget #unified-body {
        height: 1fr;
        overflow-y: auto;
        padding: 0;
    }
    """

    def __init__(self, diff: FileDiff, **kwargs):
        super().__init__(**kwargs)
        self._diff = diff

    def compose(self) -> ComposeResult:
        """Compose the unified diff widget."""
        yield Static(self._render_header(), id="unified-header")
        with ScrollableContainer(id="unified-body"):
            yield Static(self._render_content(), id="unified-content")

    def _render_header(self) -> Text:
        """Render header."""
        t = Text()
        t.append("\n", style="")

        if self._diff.is_new:
            t.append(" ✨ ", style="bold #22c55e")
        elif self._diff.is_deleted:
            t.append(" 🗑️ ", style="bold #ef4444")
        else:
            t.append(" 📝 ", style="bold #f97316")

        t.append(self._diff.path, style="bold white")
        t.append("  ", style="")
        t.append(f"+{self._diff.additions}", style=f"bold {DIFF_COLORS['addition']}")
        t.append("/", style="#52525b")
        t.append(f"-{self._diff.deletions}", style=f"bold {DIFF_COLORS['deletion']}")

        return t

    def _render_content(self) -> Text:
        """Render unified diff content."""
        t = Text()

        for hunk in self._diff.hunks:
            # Hunk header
            t.append(
                f" @@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@\n",
                style="#06b6d4",
            )

            for line in hunk.lines:
                old_str = f"{line.line_no_old:>4}" if line.line_no_old else "    "
                new_str = f"{line.line_no_new:>4}" if line.line_no_new else "    "
                t.append(f" {old_str} {new_str} ", style=DIFF_COLORS["line_no"])

                if line.change_type == "+":
                    t.append("│", style=DIFF_COLORS["addition"])
                    t.append(f" {line.content}\n", style=f"on {DIFF_COLORS['addition_bg']}")
                elif line.change_type == "-":
                    t.append("│", style=DIFF_COLORS["deletion"])
                    t.append(f" {line.content}\n", style=f"on {DIFF_COLORS['deletion_bg']}")
                else:
                    t.append("│", style="#3f3f46")
                    t.append(f" {line.content}\n", style="")

        return t
