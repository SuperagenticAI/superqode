"""
SuperQode Resizable Sidebar - Draggable and Keyboard Resizing.

Provides a resizable sidebar container with:
- Draggable divider for mouse resize
- Keyboard shortcuts (Ctrl+[ / Ctrl+]) for resize
- Min/max width constraints
- Smooth resize animation

Usage:
    from superqode.widgets.resizable_sidebar import (
        ResizableDivider, ResizableSidebarContainer
    )
"""

from __future__ import annotations

from typing import Callable, Optional

from textual.widgets import Static
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.events import MouseDown, MouseMove, MouseUp
from textual.binding import Binding
from textual.message import Message

from rich.text import Text


# ============================================================================
# DESIGN SYSTEM
# ============================================================================

try:
    from superqode.design_system import COLORS as SQ_COLORS, GRADIENT_PURPLE
except ImportError:

    class SQ_COLORS:
        primary = "#7c3aed"
        primary_light = "#a855f7"
        text_primary = "#fafafa"
        text_secondary = "#e4e4e7"
        text_muted = "#a1a1aa"
        text_dim = "#71717a"
        text_ghost = "#52525b"
        border_subtle = "#1a1a1a"
        border_default = "#27272a"

    GRADIENT_PURPLE = ["#6d28d9", "#7c3aed", "#8b5cf6", "#a855f7"]


# ============================================================================
# RESIZABLE DIVIDER
# ============================================================================


class ResizableDivider(Static):
    """
    Draggable divider for resizing adjacent panels.

    SuperQode style: Minimal, purple highlight on hover/drag.
    """

    DEFAULT_CSS = """
    ResizableDivider {
        width: 1;
        height: 100%;
        background: #1a1a1a;
    }

    ResizableDivider:hover {
        background: #7c3aed;
    }

    ResizableDivider.dragging {
        background: #a855f7;
    }
    """

    # Messages
    class Resized(Message):
        """Posted when divider is dragged."""

        def __init__(self, delta_x: int, screen_x: int) -> None:
            self.delta_x = delta_x
            self.screen_x = screen_x
            super().__init__()

    class ResizeStart(Message):
        """Posted when resize starts."""

        pass

    class ResizeEnd(Message):
        """Posted when resize ends."""

        pass

    # State
    dragging: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._start_x: int = 0
        self._last_x: int = 0

    def watch_dragging(self, dragging: bool) -> None:
        """Update visual state when dragging changes."""
        if dragging:
            self.add_class("dragging")
        else:
            self.remove_class("dragging")

    def on_mouse_down(self, event: MouseDown) -> None:
        """Start dragging."""
        self.dragging = True
        self._start_x = event.screen_x
        self._last_x = event.screen_x
        self.capture_mouse()
        self.post_message(self.ResizeStart())
        event.stop()

    def on_mouse_move(self, event: MouseMove) -> None:
        """Handle drag movement."""
        if self.dragging:
            delta = event.screen_x - self._last_x
            if delta != 0:
                self.post_message(self.Resized(delta, event.screen_x))
                self._last_x = event.screen_x
            event.stop()

    def on_mouse_up(self, event: MouseUp) -> None:
        """Stop dragging."""
        if self.dragging:
            self.dragging = False
            self.release_mouse()
            self.post_message(self.ResizeEnd())
            event.stop()

    def render(self) -> Text:
        """Render the divider."""
        # Just a vertical line character
        return Text("│", style=SQ_COLORS.primary if self.dragging else SQ_COLORS.border_subtle)


# ============================================================================
# RESIZABLE SIDEBAR CONTAINER
# ============================================================================


class ResizableSidebarContainer(Container):
    """
    Container that wraps a sidebar and provides resize functionality.

    Features:
    - Drag-to-resize with ResizableDivider
    - Keyboard shortcuts (Ctrl+[ / Ctrl+])
    - Min/max width constraints
    - Collapse/expand toggle
    """

    DEFAULT_CSS = """
    ResizableSidebarContainer {
        height: 100%;
        layout: horizontal;
    }

    ResizableSidebarContainer #rsb-sidebar {
        height: 100%;
        background: #000000;
    }

    ResizableSidebarContainer #rsb-sidebar.collapsed {
        width: 0;
        display: none;
    }

    ResizableSidebarContainer #rsb-divider {
        width: 1;
    }

    ResizableSidebarContainer #rsb-divider.hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+[", "shrink_sidebar", "Shrink", show=False),
        Binding("ctrl+]", "expand_sidebar", "Expand", show=False),
    ]

    # State
    sidebar_width: reactive[int] = reactive(80)
    sidebar_visible: reactive[bool] = reactive(True)

    # Config
    min_width: int = 30
    max_width: int = 150
    resize_step: int = 10

    def __init__(
        self,
        sidebar_content: Container,
        min_width: int = 30,
        max_width: int = 150,
        initial_width: int = 80,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._sidebar_content = sidebar_content
        self.min_width = min_width
        self.max_width = max_width
        self.sidebar_width = initial_width

    def compose(self):
        """Compose the resizable sidebar."""
        # Sidebar container
        with Container(id="rsb-sidebar"):
            yield self._sidebar_content

        # Divider
        yield ResizableDivider(id="rsb-divider")

    def on_mount(self) -> None:
        """Initialize sidebar width."""
        self._update_sidebar_width()

    def watch_sidebar_width(self, width: int) -> None:
        """Update sidebar width when changed."""
        self._update_sidebar_width()

    def watch_sidebar_visible(self, visible: bool) -> None:
        """Toggle sidebar visibility."""
        try:
            sidebar = self.query_one("#rsb-sidebar")
            divider = self.query_one("#rsb-divider")

            if visible:
                sidebar.remove_class("collapsed")
                divider.remove_class("hidden")
            else:
                sidebar.add_class("collapsed")
                divider.add_class("hidden")
        except Exception:
            pass

    def _update_sidebar_width(self) -> None:
        """Apply the current width to the sidebar."""
        try:
            sidebar = self.query_one("#rsb-sidebar")
            sidebar.styles.width = self.sidebar_width
        except Exception:
            pass

    def on_resizable_divider_resized(self, event: ResizableDivider.Resized) -> None:
        """Handle divider drag."""
        new_width = self.sidebar_width + event.delta_x
        new_width = max(self.min_width, min(self.max_width, new_width))
        self.sidebar_width = new_width

    def action_shrink_sidebar(self) -> None:
        """Shrink sidebar by step size."""
        new_width = self.sidebar_width - self.resize_step
        self.sidebar_width = max(self.min_width, new_width)

    def action_expand_sidebar(self) -> None:
        """Expand sidebar by step size."""
        new_width = self.sidebar_width + self.resize_step
        self.sidebar_width = min(self.max_width, new_width)

    def toggle_sidebar(self) -> None:
        """Toggle sidebar visibility."""
        self.sidebar_visible = not self.sidebar_visible

    def set_width(self, width: int) -> None:
        """Set sidebar width directly."""
        self.sidebar_width = max(self.min_width, min(self.max_width, width))

    def get_width(self) -> int:
        """Get current sidebar width."""
        return self.sidebar_width


# ============================================================================
# SIDEBAR TAB BAR
# ============================================================================


class SidebarTabBar(Static):
    """
    Tab bar for switching between sidebar panels.

    SuperQode style: Minimal tabs with purple active indicator.
    """

    DEFAULT_CSS = """
    SidebarTabBar {
        height: 2;
        background: #0a0a0a;
        border-bottom: solid #1a1a1a;
        padding: 0;
    }
    """

    class TabSelected(Message):
        """Posted when a tab is selected."""

        def __init__(self, tab_id: str, index: int) -> None:
            self.tab_id = tab_id
            self.index = index
            super().__init__()

    active_tab: reactive[int] = reactive(0)

    def __init__(self, tabs: list[str], **kwargs):
        super().__init__("", **kwargs)
        self._tabs = tabs

    def watch_active_tab(self, index: int) -> None:
        """Update display when active tab changes."""
        self.refresh()
        if 0 <= index < len(self._tabs):
            self.post_message(self.TabSelected(self._tabs[index].lower(), index))

    def select_tab(self, index: int) -> None:
        """Select a tab by index."""
        if 0 <= index < len(self._tabs):
            self.active_tab = index

    def select_tab_by_name(self, name: str) -> None:
        """Select a tab by name."""
        name_lower = name.lower()
        for i, tab in enumerate(self._tabs):
            if tab.lower() == name_lower:
                self.active_tab = i
                break

    def render(self) -> Text:
        """Render the tab bar."""
        text = Text()

        for i, tab in enumerate(self._tabs):
            is_active = i == self.active_tab

            # Tab separator
            if i > 0:
                text.append(" ", style="")

            # Tab name (abbreviated for space)
            short_name = tab[:3] if len(tab) > 4 else tab

            if is_active:
                text.append(f"[{short_name}]", style=f"bold {SQ_COLORS.primary}")
            else:
                text.append(f" {short_name} ", style=SQ_COLORS.text_dim)

        return text

    def on_click(self, event) -> None:
        """Handle click to select tab."""
        # Calculate which tab was clicked based on x position
        # Each tab is roughly 5 characters wide
        tab_width = 5
        index = event.x // tab_width
        if 0 <= index < len(self._tabs):
            self.active_tab = index


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ResizableDivider",
    "ResizableSidebarContainer",
    "SidebarTabBar",
]
