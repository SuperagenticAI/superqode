"""
SuperQode Split View - Code + Chat Side by Side.

Provides a resizable split view for showing code/files alongside
the chat conversation. Essential for a full coding agent experience.

Features:
- Draggable divider
- Keyboard shortcuts for resizing
- Tab support for multiple files
- Syntax highlighting
- Line numbers

Usage:
    from superqode.widgets.split_view import SplitView

    split = SplitView()
    split.open_file("src/main.py")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

from rich.text import Text
from rich.syntax import Syntax

from textual.widgets import Static, TextArea
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.events import MouseMove, MouseDown, MouseUp
from textual import on

if TYPE_CHECKING:
    from textual.app import App


# ============================================================================
# IMPORTS
# ============================================================================

try:
    from superqode.design_system import COLORS, GRADIENT_PURPLE, SUPERQODE_ICONS
except ImportError:

    class COLORS:
        primary = "#7c3aed"
        primary_light = "#a855f7"
        secondary = "#ec4899"
        success = "#10b981"
        error = "#f43f5e"
        text_primary = "#fafafa"
        text_secondary = "#e4e4e7"
        text_muted = "#a1a1aa"
        text_dim = "#71717a"
        text_ghost = "#52525b"
        bg_surface = "#050505"
        border_subtle = "#1a1a1a"
        code_bg = "#0c0c0c"

    SUPERQODE_ICONS = {}


# ============================================================================
# FILE TAB
# ============================================================================


@dataclass
class FileTab:
    """Information about an open file tab."""

    path: str
    name: str
    language: str = ""
    content: str = ""
    modified: bool = False
    scroll_pos: int = 0
    cursor_line: int = 0


class TabBar(Static):
    """
    Tab bar for open files.

    SuperQode style: Minimal tabs with close buttons.
    """

    DEFAULT_CSS = """
    TabBar {
        height: 1;
        background: #0a0a0a;
        border-bottom: solid #1a1a1a;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._tabs: List[FileTab] = []
        self._active: int = -1
        self._on_select: Optional[Callable[[int], None]] = None
        self._on_close: Optional[Callable[[int], None]] = None

    def add_tab(self, tab: FileTab) -> int:
        """Add a new tab."""
        self._tabs.append(tab)
        self._active = len(self._tabs) - 1
        self.refresh()
        return self._active

    def remove_tab(self, index: int) -> None:
        """Remove a tab."""
        if 0 <= index < len(self._tabs):
            self._tabs.pop(index)
            if self._active >= len(self._tabs):
                self._active = len(self._tabs) - 1
            self.refresh()

    def select_tab(self, index: int) -> None:
        """Select a tab."""
        if 0 <= index < len(self._tabs):
            self._active = index
            self.refresh()
            if self._on_select:
                self._on_select(index)

    def get_active_tab(self) -> Optional[FileTab]:
        """Get the active tab."""
        if 0 <= self._active < len(self._tabs):
            return self._tabs[self._active]
        return None

    def render(self) -> Text:
        """Render the tab bar."""
        text = Text()

        if not self._tabs:
            text.append("  No files open", style=COLORS.text_dim)
            return text

        for i, tab in enumerate(self._tabs):
            is_active = i == self._active

            # Tab indicator
            if is_active:
                text.append("▸ ", style=f"bold {COLORS.primary}")
            else:
                text.append("  ", style="")

            # File name
            style = COLORS.text_primary if is_active else COLORS.text_muted
            text.append(tab.name, style=style)

            # Modified indicator
            if tab.modified:
                text.append(" ●", style=COLORS.warning)

            text.append("  ", style="")

        return text


# ============================================================================
# CODE VIEWER
# ============================================================================


class CodeViewer(ScrollableContainer):
    """
    Code viewer with syntax highlighting and line numbers.

    SuperQode style: Clean, minimal, focused on code.
    """

    DEFAULT_CSS = """
    CodeViewer {
        background: #0c0c0c;
        padding: 0;
    }

    CodeViewer .code-content {
        width: 100%;
    }

    CodeViewer .line-numbers {
        width: 5;
        background: #0a0a0a;
        border-right: solid #1a1a1a;
        padding-right: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._content = ""
        self._language = "text"
        self._highlight_lines: List[int] = []

    def compose(self):
        """Compose the viewer."""
        with Horizontal():
            yield Static("", id="line-numbers", classes="line-numbers")
            yield Static("", id="code-content", classes="code-content")

    def set_content(self, content: str, language: str = "text") -> None:
        """Set the code content."""
        self._content = content
        self._language = language
        self._render()

    def highlight_lines(self, lines: List[int]) -> None:
        """Highlight specific lines."""
        self._highlight_lines = lines
        self._render()

    def _render(self) -> None:
        """Render the code."""
        try:
            lines = self._content.split("\n")

            # Line numbers
            ln_text = Text()
            for i, _ in enumerate(lines, 1):
                style = COLORS.primary if i in self._highlight_lines else COLORS.text_ghost
                ln_text.append(f"{i:4} \n", style=style)

            self.query_one("#line-numbers", Static).update(ln_text)

            # Code content with syntax highlighting
            try:
                syntax = Syntax(
                    self._content,
                    self._language,
                    theme="monokai",
                    line_numbers=False,
                    word_wrap=False,
                )
                self.query_one("#code-content", Static).update(syntax)
            except Exception:
                self.query_one("#code-content", Static).update(
                    Text(self._content, style=COLORS.text_secondary)
                )
        except Exception:
            pass


# ============================================================================
# SPLIT DIVIDER
# ============================================================================


class SplitDivider(Static):
    """
    Draggable divider for split view.

    SuperQode style: Minimal, changes color on hover.
    """

    DEFAULT_CSS = """
    SplitDivider {
        width: 1;
        background: #1a1a1a;
    }

    SplitDivider:hover {
        background: #7c3aed;
    }

    SplitDivider.dragging {
        background: #a855f7;
    }
    """

    dragging: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._on_drag: Optional[Callable[[int], None]] = None

    def on_mouse_down(self, event: MouseDown) -> None:
        """Start dragging."""
        self.dragging = True
        self.add_class("dragging")
        self.capture_mouse()

    def on_mouse_up(self, event: MouseUp) -> None:
        """Stop dragging."""
        self.dragging = False
        self.remove_class("dragging")
        self.release_mouse()

    def on_mouse_move(self, event: MouseMove) -> None:
        """Handle drag."""
        if self.dragging and self._on_drag:
            self._on_drag(event.screen_x)

    def render(self) -> Text:
        """Render the divider."""
        # Just a vertical line
        return Text("│", style=COLORS.border_subtle if not self.dragging else COLORS.primary)


# ============================================================================
# SPLIT VIEW
# ============================================================================


class SplitView(Container):
    """
    Split view container with code viewer and chat.

    Layout:
    ┌────────────────────┬─┬────────────────────┐
    │ [Tab Bar]          │ │                    │
    ├────────────────────┤ │                    │
    │                    │D│   Chat/Content     │
    │   Code Viewer      │I│                    │
    │                    │V│                    │
    │                    │ │                    │
    └────────────────────┴─┴────────────────────┘
    """

    DEFAULT_CSS = """
    SplitView {
        height: 100%;
        width: 100%;
    }

    SplitView #split-main {
        height: 100%;
    }

    SplitView #split-left {
        width: 50%;
        background: #050505;
    }

    SplitView #split-right {
        width: 1fr;
    }

    SplitView #split-left.collapsed {
        width: 0;
        display: none;
    }

    SplitView #code-header {
        height: 2;
        background: #0a0a0a;
        border-bottom: solid #1a1a1a;
        padding: 0 1;
    }
    """

    # State
    split_visible: reactive[bool] = reactive(False)
    split_position: reactive[int] = reactive(50)  # Percentage

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tabs: List[FileTab] = []
        self._active_tab: int = -1
        self._on_file_select: Optional[Callable[[str], None]] = None

    def compose(self):
        """Compose the split view."""
        with Horizontal(id="split-main"):
            # Left side - Code
            with Vertical(id="split-left", classes="collapsed"):
                yield Static(self._render_header(), id="code-header")
                yield TabBar(id="tab-bar")
                yield CodeViewer(id="code-viewer")

            # Divider
            yield SplitDivider(id="split-divider")

            # Right side - Chat (content provided by parent)
            yield Container(id="split-right")

    def _render_header(self) -> Text:
        """Render the code header."""
        text = Text()
        text.append("◇ ", style=f"bold {COLORS.primary}")
        text.append("Code", style=COLORS.text_secondary)
        text.append("  [Ctrl+\\ to close]", style=COLORS.text_ghost)
        return text

    def on_mount(self) -> None:
        """Set up event handlers."""
        try:
            divider = self.query_one("#split-divider", SplitDivider)
            divider._on_drag = self._handle_drag

            tab_bar = self.query_one("#tab-bar", TabBar)
            tab_bar._on_select = self._handle_tab_select
            tab_bar._on_close = self._handle_tab_close
        except Exception:
            pass

    def _handle_drag(self, x: int) -> None:
        """Handle divider drag."""
        # Calculate percentage
        width = self.size.width
        if width > 0:
            pct = int((x / width) * 100)
            pct = max(20, min(80, pct))  # Clamp between 20-80%
            self.split_position = pct
            self._update_widths()

    def _update_widths(self) -> None:
        """Update split widths."""
        try:
            left = self.query_one("#split-left")
            left.styles.width = f"{self.split_position}%"
        except Exception:
            pass

    def _handle_tab_select(self, index: int) -> None:
        """Handle tab selection."""
        if 0 <= index < len(self._tabs):
            self._active_tab = index
            tab = self._tabs[index]
            self._show_content(tab)

    def _handle_tab_close(self, index: int) -> None:
        """Handle tab close."""
        if 0 <= index < len(self._tabs):
            self._tabs.pop(index)
            if self._active_tab >= len(self._tabs):
                self._active_tab = len(self._tabs) - 1

            if self._tabs and self._active_tab >= 0:
                self._show_content(self._tabs[self._active_tab])
            else:
                self.hide_split()

    def _show_content(self, tab: FileTab) -> None:
        """Show file content."""
        try:
            viewer = self.query_one("#code-viewer", CodeViewer)
            viewer.set_content(tab.content, tab.language)
        except Exception:
            pass

    def show_split(self) -> None:
        """Show the split view."""
        self.split_visible = True
        try:
            left = self.query_one("#split-left")
            left.remove_class("collapsed")
        except Exception:
            pass

    def hide_split(self) -> None:
        """Hide the split view."""
        self.split_visible = False
        try:
            left = self.query_one("#split-left")
            left.add_class("collapsed")
        except Exception:
            pass

    def toggle_split(self) -> None:
        """Toggle the split view."""
        if self.split_visible:
            self.hide_split()
        else:
            self.show_split()

    def open_file(self, path: str) -> bool:
        """
        Open a file in the split view.

        Returns True if successful.
        """
        try:
            file_path = Path(path)
            if not file_path.exists():
                return False

            # Check if already open
            for i, tab in enumerate(self._tabs):
                if tab.path == str(file_path):
                    self._active_tab = i
                    try:
                        tab_bar = self.query_one("#tab-bar", TabBar)
                        tab_bar.select_tab(i)
                    except Exception:
                        pass
                    self._show_content(tab)
                    self.show_split()
                    return True

            # Read file
            content = file_path.read_text(encoding="utf-8", errors="ignore")

            # Detect language
            language = self._detect_language(file_path)

            # Create tab
            tab = FileTab(
                path=str(file_path),
                name=file_path.name,
                language=language,
                content=content,
            )

            self._tabs.append(tab)
            self._active_tab = len(self._tabs) - 1

            try:
                tab_bar = self.query_one("#tab-bar", TabBar)
                tab_bar.add_tab(tab)
            except Exception:
                pass

            self._show_content(tab)
            self.show_split()
            return True

        except Exception:
            return False

    def _detect_language(self, path: Path) -> str:
        """Detect language from file extension."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "jsx",
            ".tsx": "tsx",
            ".html": "html",
            ".css": "css",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".rb": "ruby",
            ".sh": "bash",
            ".sql": "sql",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
        }
        return ext_map.get(path.suffix.lower(), "text")

    def show_diff(
        self,
        file_path: str,
        old_content: str,
        new_content: str,
    ) -> None:
        """
        Show a diff in the split view.
        """
        # Create unified diff
        import difflib

        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )

        diff_text = "".join(diff)

        # Create a diff tab
        tab = FileTab(
            path=f"diff:{file_path}",
            name=f"Δ {Path(file_path).name}",
            language="diff",
            content=diff_text,
        )

        self._tabs.append(tab)
        self._active_tab = len(self._tabs) - 1

        try:
            tab_bar = self.query_one("#tab-bar", TabBar)
            tab_bar.add_tab(tab)
        except Exception:
            pass

        self._show_content(tab)
        self.show_split()

    def get_right_container(self) -> Container:
        """Get the right side container for adding chat content."""
        return self.query_one("#split-right", Container)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "FileTab",
    "TabBar",
    "CodeViewer",
    "SplitDivider",
    "SplitView",
]
