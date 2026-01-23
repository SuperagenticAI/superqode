"""Loading throbber/spinner widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, LoadingIndicator


class Throbber(Widget):
    """
    Loading overlay with spinner and message.

    Used during async operations like agent connection.
    """

    DEFAULT_CSS = """
    Throbber {
        layer: overlay;
        align: center middle;
        width: auto;
        height: auto;
        background: $surface 90%;
        border: round $primary;
        padding: 1 2;
        display: none;
    }

    Throbber.visible {
        display: block;
    }

    Throbber > Horizontal {
        width: auto;
        height: auto;
    }

    Throbber LoadingIndicator {
        width: 4;
        height: 1;
        color: $primary;
    }

    Throbber #throbber-text {
        margin-left: 1;
        color: $text;
    }
    """

    # State
    visible: reactive[bool] = reactive(False)
    message: reactive[str] = reactive("Loading...")

    def __init__(self, message: str = "Loading...", **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield LoadingIndicator()
            yield Static(self.message, id="throbber-text")

    def show(self, message: str | None = None) -> None:
        """Show the throbber with optional message."""
        if message:
            self.message = message
        self.visible = True
        self.add_class("visible")

    def hide(self) -> None:
        """Hide the throbber."""
        self.visible = False
        self.remove_class("visible")

    def watch_message(self, message: str) -> None:
        """React to message changes."""
        try:
            text_widget = self.query_one("#throbber-text", Static)
            text_widget.update(message)
        except Exception:
            pass  # Widget might not be mounted yet

    def update_message(self, message: str) -> None:
        """Update the loading message."""
        self.message = message
