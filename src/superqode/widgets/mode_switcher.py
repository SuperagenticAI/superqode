"""
Mode Switcher Widget - Beautiful Mode Transitions.

Provides a polished UI for switching between different
SuperQode modes (home, QE, agent, etc.) with visual feedback.

Features:
- Animated transitions
- Visual mode indicators
- Quick keyboard shortcuts
- Recent modes history
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static
from textual.containers import Container, Horizontal, Vertical
from textual.timer import Timer
from textual import events


class AppMode(Enum):
    """Application modes."""

    HOME = "home"
    QE = "qe"
    AGENT = "agent"
    CHAT = "chat"
    REVIEW = "review"
    DEBUG = "debug"


@dataclass
class ModeInfo:
    """Information about a mode."""

    id: str
    name: str
    icon: str
    color: str
    description: str
    shortcut: str = ""


# Mode definitions
MODES = {
    AppMode.HOME: ModeInfo(
        id="home",
        name="Home",
        icon="🏠",
        color="#3b82f6",
        description="Main dashboard and navigation",
        shortcut="h",
    ),
    AppMode.QE: ModeInfo(
        id="qe",
        name="Quality Engineering",
        icon="🔍",
        color="#22c55e",
        description="Run QE sessions with multi-agent analysis",
        shortcut="q",
    ),
    AppMode.AGENT: ModeInfo(
        id="agent",
        name="Agent Mode",
        icon="🤖",
        color="#8b5cf6",
        description="Direct interaction with coding agents",
        shortcut="a",
    ),
    AppMode.CHAT: ModeInfo(
        id="chat",
        name="Chat",
        icon="💬",
        color="#06b6d4",
        description="Conversational coding assistance",
        shortcut="c",
    ),
    AppMode.REVIEW: ModeInfo(
        id="review",
        name="Code Review",
        icon="📝",
        color="#f59e0b",
        description="Review and approve changes",
        shortcut="r",
    ),
    AppMode.DEBUG: ModeInfo(
        id="debug",
        name="Debug",
        icon="🐛",
        color="#ef4444",
        description="Debug and troubleshoot issues",
        shortcut="d",
    ),
}


class ModeTile(Static):
    """Single mode tile in the switcher."""

    DEFAULT_CSS = """
    ModeTile {
        width: 24;
        height: 7;
        border: solid #3f3f46;
        padding: 0 1;
        margin: 0 1;
    }

    ModeTile:hover {
        border: solid #6b7280;
    }

    ModeTile.selected {
        border: double #3b82f6;
    }

    ModeTile.current {
        border: solid #22c55e;
    }
    """

    selected: reactive[bool] = reactive(False)

    def __init__(
        self,
        mode: AppMode,
        is_current: bool = False,
        on_select: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.mode = mode
        self.info = MODES[mode]
        self._is_current = is_current
        self._on_select = on_select

        if is_current:
            self.add_class("current")

    def on_click(self, event: events.Click) -> None:
        """Handle click."""
        if self._on_select:
            self._on_select()

    def watch_selected(self, selected: bool) -> None:
        """React to selection changes."""
        if selected:
            self.add_class("selected")
        else:
            self.remove_class("selected")

    def render(self) -> RenderableType:
        """Render the mode tile."""
        content = Text()

        # Icon and name
        content.append(f"\n  {self.info.icon} ", style="")
        content.append(f"{self.info.name}\n", style=f"bold {self.info.color}")

        # Shortcut
        if self.info.shortcut:
            content.append(f"  [{self.info.shortcut}]\n", style="#6b7280")

        # Current indicator
        if self._is_current:
            content.append("  ● Current\n", style="bold #22c55e")
        else:
            content.append("\n", style="")

        border_style = self.info.color if self.selected else "#3f3f46"
        if self._is_current:
            border_style = "#22c55e"

        return Panel(
            content,
            border_style=border_style,
            padding=(0, 0),
        )


class ModeSwitcher(Container):
    """
    Mode switcher widget for navigating between app modes.

    Shows all available modes in a grid with visual indicators
    for the current mode and keyboard shortcuts.

    Usage:
        switcher = ModeSwitcher(
            current_mode=AppMode.HOME,
            on_mode_change=lambda mode: print(f"Switched to {mode}"),
        )
    """

    DEFAULT_CSS = """
    ModeSwitcher {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 2;
    }

    ModeSwitcher .header {
        width: 100%;
        height: 3;
        text-align: center;
        margin-bottom: 2;
    }

    ModeSwitcher .modes-row {
        width: auto;
        height: auto;
        align: center middle;
    }

    ModeSwitcher .footer {
        width: 100%;
        height: 2;
        text-align: center;
        margin-top: 2;
    }
    """

    selected_index: reactive[int] = reactive(0)

    def __init__(
        self,
        current_mode: AppMode = AppMode.HOME,
        on_mode_change: Optional[Callable[[AppMode], None]] = None,
        available_modes: Optional[List[AppMode]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.current_mode = current_mode
        self._on_mode_change = on_mode_change
        self.available_modes = available_modes or list(AppMode)
        self._tiles: List[ModeTile] = []

    def compose(self):
        """Compose the switcher layout."""
        # Header
        yield Static(
            "[bold #3b82f6]Switch Mode[/]\n[#6b7280]Select a mode or press its shortcut key[/]",
            classes="header",
        )

        # Mode tiles
        with Horizontal(classes="modes-row"):
            for i, mode in enumerate(self.available_modes):
                tile = ModeTile(
                    mode,
                    is_current=(mode == self.current_mode),
                    on_select=lambda m=mode: self._select_mode(m),
                    id=f"tile-{mode.value}",
                )
                self._tiles.append(tile)
                yield tile

        # Footer with shortcuts
        shortcuts = " ".join(
            f"[{MODES[m].shortcut}]{MODES[m].name[0]}"
            for m in self.available_modes
            if MODES[m].shortcut
        )
        yield Static(
            f"[#6b7280]Shortcuts: {shortcuts}  [Enter] Select  [Esc] Cancel[/]",
            classes="footer",
        )

    def on_mount(self) -> None:
        """Initialize selection."""
        self._update_selection()

    def _update_selection(self) -> None:
        """Update tile selection state."""
        for i, tile in enumerate(self._tiles):
            tile.selected = i == self.selected_index

    def _select_mode(self, mode: AppMode) -> None:
        """Select a mode."""
        if self._on_mode_change:
            self._on_mode_change(mode)

    def on_key(self, event: events.Key) -> None:
        """Handle keyboard navigation."""
        # Arrow navigation
        if event.key == "left":
            self.selected_index = max(0, self.selected_index - 1)
            self._update_selection()
            event.prevent_default()

        elif event.key == "right":
            self.selected_index = min(len(self._tiles) - 1, self.selected_index + 1)
            self._update_selection()
            event.prevent_default()

        elif event.key == "enter":
            mode = self.available_modes[self.selected_index]
            self._select_mode(mode)
            event.prevent_default()

        # Shortcut keys
        else:
            for mode in self.available_modes:
                info = MODES[mode]
                if event.key == info.shortcut:
                    self._select_mode(mode)
                    event.prevent_default()
                    return


class ModeIndicator(Static):
    """
    Compact mode indicator for status bar.

    Shows current mode with icon and allows quick switching.
    """

    DEFAULT_CSS = """
    ModeIndicator {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        mode: AppMode = AppMode.HOME,
        on_click_switch: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._mode = mode
        self._on_click_switch = on_click_switch

    @property
    def mode(self) -> AppMode:
        return self._mode

    @mode.setter
    def mode(self, value: AppMode) -> None:
        self._mode = value
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        """Handle click to open switcher."""
        if self._on_click_switch:
            self._on_click_switch()

    def render(self) -> RenderableType:
        """Render the indicator."""
        info = MODES[self._mode]

        text = Text()
        text.append(f"{info.icon} ", style=info.color)
        text.append(info.name, style=f"bold {info.color}")

        return text


class ModeTransition(Static):
    """
    Animated mode transition overlay.

    Shows a brief animation when switching modes.
    """

    DEFAULT_CSS = """
    ModeTransition {
        width: 100%;
        height: 100%;
        align: center middle;
        layer: overlay;
        background: rgba(0, 0, 0, 0.8);
    }
    """

    def __init__(
        self,
        from_mode: AppMode,
        to_mode: AppMode,
        on_complete: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.from_mode = from_mode
        self.to_mode = to_mode
        self._on_complete = on_complete
        self._frame = 0
        self._timer: Optional[Timer] = None

    def on_mount(self) -> None:
        """Start animation."""
        self._timer = self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        """Animation tick."""
        self._frame += 1
        self.refresh()

        if self._frame >= 10:  # 1 second animation
            if self._timer:
                self._timer.stop()
            if self._on_complete:
                self._on_complete()
            self.remove()

    def render(self) -> RenderableType:
        """Render the transition animation."""
        from_info = MODES[self.from_mode]
        to_info = MODES[self.to_mode]

        content = Text()

        # Fade out old mode, fade in new mode
        if self._frame < 5:
            # Show old mode fading
            content.append(f"\n\n  {from_info.icon} ", style=from_info.color)
            content.append(f"{from_info.name}\n", style=f"bold {from_info.color}")
            content.append("  → Switching...\n", style="#6b7280")
        else:
            # Show new mode appearing
            content.append(f"\n\n  {to_info.icon} ", style=to_info.color)
            content.append(f"{to_info.name}\n", style=f"bold {to_info.color}")
            content.append("  ✓ Ready\n", style="#22c55e")

        return Panel(
            content,
            title="[bold #3b82f6]Mode Transition[/]",
            border_style="#3f3f46",
            width=40,
            height=10,
        )
