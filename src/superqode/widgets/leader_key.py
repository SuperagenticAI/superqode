"""
SuperQode Leader Key Widget - Ctrl+X prefix shortcuts.

Implements leader key shortcuts where pressing Ctrl+X
shows available actions and waits for a second key.

Usage:
    Ctrl+X → shows leader key popup
    then press:
        H - Help
        E - Edit (open editor)
        C - Copy response
        S - Select text
        T - Theme picker
        D - Diagnostics
        Q - Quit
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, TYPE_CHECKING

from rich.text import Text

from textual.widgets import Static
from textual.containers import Container
from textual.reactive import reactive
from textual.message import Message

if TYPE_CHECKING:
    from textual.app import App


# ============================================================================
# DESIGN
# ============================================================================

try:
    from superqode.design_system import COLORS as SQ_COLORS
except ImportError:

    class SQ_COLORS:
        primary = "#7c3aed"
        primary_light = "#a855f7"
        text_primary = "#fafafa"
        text_secondary = "#e4e4e7"
        text_muted = "#a1a1aa"
        text_dim = "#71717a"
        bg_elevated = "#0a0a0a"
        border_default = "#27272a"


# ============================================================================
# LEADER KEY DEFINITIONS
# ============================================================================

LEADER_KEYS = {
    "h": {
        "label": "Help",
        "description": "Show help",
        "action": "show_help",
    },
    "e": {
        "label": "Edit",
        "description": "Open external editor",
        "action": "open_editor",
    },
    "c": {
        "label": "Copy",
        "description": "Copy last response",
        "action": "copy_response",
    },
    "s": {
        "label": "Select",
        "description": "Open selectable view",
        "action": "show_select",
    },
    "t": {
        "label": "Theme",
        "description": "Change theme",
        "action": "show_theme",
    },
    "d": {
        "label": "Diagnostics",
        "description": "Show diagnostics",
        "action": "show_diagnostics",
    },
    "b": {
        "label": "Sidebar",
        "description": "Toggle sidebar",
        "action": "toggle_sidebar",
    },
    "q": {
        "label": "Quit",
        "description": "Exit application",
        "action": "quit_app",
    },
}


# ============================================================================
# LEADER KEY WIDGET
# ============================================================================


class LeaderKeyPopup(Static):
    """
    Popup showing available leader key commands.

    Appears when user presses Ctrl+X and waits for second key.
    """

    DEFAULT_CSS = """
    LeaderKeyPopup {
        layer: overlay;
        width: auto;
        height: auto;
        background: #0a0a0a;
        border: round #7c3aed;
        padding: 1 2;
        display: none;
    }

    LeaderKeyPopup.visible {
        display: block;
    }
    """

    class KeyPressed(Message):
        """Posted when a leader key is pressed."""

        def __init__(self, key: str, action: str) -> None:
            self.key = key
            self.action = action
            super().__init__()

    class Cancelled(Message):
        """Posted when leader mode is cancelled."""

        pass

    visible: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)

    def watch_visible(self, visible: bool) -> None:
        """Toggle visibility."""
        if visible:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def show(self) -> None:
        """Show the leader key popup."""
        self.visible = True
        self.focus()

    def hide(self) -> None:
        """Hide the popup."""
        self.visible = False

    def render(self) -> Text:
        """Render the leader key options."""
        t = Text()
        t.append("◈ Leader: Ctrl+X + ...\n", style=f"bold {SQ_COLORS.primary}")
        t.append("\n", style="")

        for key, info in LEADER_KEYS.items():
            t.append(f"  [{key.upper()}]", style=f"bold {SQ_COLORS.primary_light}")
            t.append(f"  {info['label']:<12}", style=SQ_COLORS.text_secondary)
            t.append(f"  {info['description']}\n", style=SQ_COLORS.text_dim)

        t.append("\n", style="")
        t.append("  [Esc] Cancel", style=SQ_COLORS.text_muted)

        return t

    def on_key(self, event) -> None:
        """Handle key press in leader mode."""
        key = event.key.lower()

        if key == "escape":
            self.hide()
            self.post_message(self.Cancelled())
            event.stop()
            return

        if key in LEADER_KEYS:
            action = LEADER_KEYS[key]["action"]
            self.hide()
            self.post_message(self.KeyPressed(key, action))
            event.stop()


# ============================================================================
# LEADER KEY MIXIN
# ============================================================================


class LeaderKeyMixin:
    """
    Mixin to add leader key support to an App.

    Usage:
        class MyApp(App, LeaderKeyMixin):
            def __init__(self):
                super().__init__()
                self._init_leader_key()
    """

    _leader_mode: bool = False
    _leader_popup: Optional[LeaderKeyPopup] = None

    def _init_leader_key(self) -> None:
        """Initialize leader key support."""
        self._leader_mode = False

    def action_leader_key(self) -> None:
        """Activate leader key mode (Ctrl+X)."""
        if hasattr(self, "_leader_popup") and self._leader_popup:
            self._leader_popup.show()
            self._leader_mode = True

    def _handle_leader_action(self, action: str) -> None:
        """Handle a leader key action."""
        self._leader_mode = False

        # Map actions to app methods
        action_map = {
            "show_help": "action_show_help",
            "open_editor": "action_open_editor",
            "copy_response": "action_copy_response",
            "show_select": "_show_select",
            "show_theme": "_show_theme",
            "show_diagnostics": "_show_diagnostics",
            "toggle_sidebar": "action_toggle_sidebar",
            "quit_app": "action_quit",
        }

        method_name = action_map.get(action)
        if method_name and hasattr(self, method_name):
            method = getattr(self, method_name)
            if callable(method):
                method()

    def on_leader_key_popup_key_pressed(self, event: LeaderKeyPopup.KeyPressed) -> None:
        """Handle leader key selection."""
        self._handle_leader_action(event.action)

    def on_leader_key_popup_cancelled(self, event: LeaderKeyPopup.Cancelled) -> None:
        """Handle leader mode cancelled."""
        self._leader_mode = False


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "LEADER_KEYS",
    "LeaderKeyPopup",
    "LeaderKeyMixin",
]
