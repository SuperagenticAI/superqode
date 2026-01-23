"""
SuperQode Flash Notifications - Temporary Status Messages

Beautiful flash notifications with:
- Semantic styles (success, warning, error, info)
- Auto-hide with configurable duration
- Gradient animations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable
from datetime import datetime
import threading
import time

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.box import ROUNDED


class FlashStyle(Enum):
    """Flash notification styles."""

    DEFAULT = "default"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


@dataclass
class FlashMessage:
    """A flash notification message."""

    content: str
    style: FlashStyle = FlashStyle.DEFAULT
    duration: float = 3.0
    created_at: datetime = field(default_factory=datetime.now)
    dismissed: bool = False


# SuperQode flash colors
FLASH_COLORS = {
    FlashStyle.DEFAULT: {
        "icon": "💬",
        "color": "#a855f7",
        "bg": "#a855f720",
        "border": "#a855f7",
    },
    FlashStyle.SUCCESS: {
        "icon": "✅",
        "color": "#22c55e",
        "bg": "#22c55e20",
        "border": "#22c55e",
    },
    FlashStyle.WARNING: {
        "icon": "⚠️",
        "color": "#f59e0b",
        "bg": "#f59e0b20",
        "border": "#f59e0b",
    },
    FlashStyle.ERROR: {
        "icon": "❌",
        "color": "#ef4444",
        "bg": "#ef444420",
        "border": "#ef4444",
    },
    FlashStyle.INFO: {
        "icon": "ℹ️",
        "color": "#06b6d4",
        "bg": "#06b6d420",
        "border": "#06b6d4",
    },
}


class FlashManager:
    """Manages flash notifications."""

    def __init__(self, console: Console, default_duration: float = 3.0):
        self.console = console
        self.default_duration = default_duration
        self.messages: list[FlashMessage] = []
        self.history: list[FlashMessage] = []
        self._timer: Optional[threading.Timer] = None

    def flash(
        self, content: str, style: FlashStyle = FlashStyle.DEFAULT, duration: Optional[float] = None
    ) -> FlashMessage:
        """Show a flash notification."""
        msg = FlashMessage(content=content, style=style, duration=duration or self.default_duration)
        self.messages.append(msg)
        self._render_flash(msg)

        # Schedule auto-dismiss
        if msg.duration > 0:
            self._schedule_dismiss(msg)

        return msg

    def success(self, content: str, duration: Optional[float] = None) -> FlashMessage:
        """Show a success flash."""
        return self.flash(content, FlashStyle.SUCCESS, duration)

    def warning(self, content: str, duration: Optional[float] = None) -> FlashMessage:
        """Show a warning flash."""
        return self.flash(content, FlashStyle.WARNING, duration)

    def error(self, content: str, duration: Optional[float] = None) -> FlashMessage:
        """Show an error flash."""
        return self.flash(content, FlashStyle.ERROR, duration)

    def info(self, content: str, duration: Optional[float] = None) -> FlashMessage:
        """Show an info flash."""
        return self.flash(content, FlashStyle.INFO, duration)

    def dismiss(self, msg: FlashMessage) -> None:
        """Dismiss a flash message."""
        msg.dismissed = True
        if msg in self.messages:
            self.messages.remove(msg)
            self.history.append(msg)

    def dismiss_all(self) -> None:
        """Dismiss all flash messages."""
        for msg in list(self.messages):
            self.dismiss(msg)

    def _schedule_dismiss(self, msg: FlashMessage) -> None:
        """Schedule auto-dismiss of a message."""

        def auto_dismiss():
            if not msg.dismissed:
                self.dismiss(msg)

        timer = threading.Timer(msg.duration, auto_dismiss)
        timer.daemon = True
        timer.start()

    def _render_flash(self, msg: FlashMessage) -> None:
        """Render a flash message."""
        style_config = FLASH_COLORS.get(msg.style, FLASH_COLORS[FlashStyle.DEFAULT])

        text = Text()
        text.append(f" {style_config['icon']} ", style=f"bold {style_config['color']}")
        text.append(msg.content, style=style_config["color"])

        self.console.print(text)


def render_flash(console: Console, content: str, style: FlashStyle = FlashStyle.DEFAULT) -> None:
    """Render a simple flash message (stateless)."""
    style_config = FLASH_COLORS.get(style, FLASH_COLORS[FlashStyle.DEFAULT])

    text = Text()
    text.append(f" {style_config['icon']} ", style=f"bold {style_config['color']}")
    text.append(content, style=style_config["color"])

    console.print(text)


def flash_success(console: Console, content: str) -> None:
    """Show a success flash."""
    render_flash(console, content, FlashStyle.SUCCESS)


def flash_warning(console: Console, content: str) -> None:
    """Show a warning flash."""
    render_flash(console, content, FlashStyle.WARNING)


def flash_error(console: Console, content: str) -> None:
    """Show an error flash."""
    render_flash(console, content, FlashStyle.ERROR)


def flash_info(console: Console, content: str) -> None:
    """Show an info flash."""
    render_flash(console, content, FlashStyle.INFO)
