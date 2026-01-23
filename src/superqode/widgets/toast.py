"""Toast notification widgets."""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static


class ToastType(Enum):
    """Types of toast notifications."""

    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Toast(Widget):
    """
    A single toast notification.

    Auto-dismisses after a configurable duration.
    """

    DEFAULT_CSS = """
    Toast {
        width: auto;
        max-width: 60;
        height: auto;
        padding: 0 2;
        margin: 0 0 1 0;
        background: $surface;
        border: round $primary;
    }

    Toast.success {
        border: round $success;
    }

    Toast.success .toast-icon {
        color: $success;
    }

    Toast.error {
        border: round $error;
    }

    Toast.error .toast-icon {
        color: $error;
    }

    Toast.warning {
        border: round $warning;
    }

    Toast.warning .toast-icon {
        color: $warning;
    }

    Toast.info {
        border: round $primary;
    }

    Toast.info .toast-icon {
        color: $primary;
    }

    Toast .toast-content {
        layout: horizontal;
        height: auto;
    }

    Toast .toast-icon {
        width: 3;
    }

    Toast .toast-message {
        color: $text;
    }
    """

    ICONS: ClassVar[dict[ToastType, str]] = {
        ToastType.SUCCESS: "✓",
        ToastType.ERROR: "✗",
        ToastType.WARNING: "⚠",
        ToastType.INFO: "ℹ",
    }

    class Dismissed(Message):
        """Message sent when toast is dismissed."""

        def __init__(self, toast: "Toast") -> None:
            self.toast = toast
            super().__init__()

    def __init__(
        self,
        message: str,
        toast_type: ToastType = ToastType.INFO,
        duration: float = 3.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.message = message
        self.toast_type = toast_type
        self.duration = duration
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        icon = self.ICONS.get(self.toast_type, "ℹ")
        with Vertical(classes="toast-content"):
            yield Static(f"{icon} {self.message}", classes="toast-message")

    def on_mount(self) -> None:
        """Start auto-dismiss timer on mount."""
        self.add_class(self.toast_type.value)
        if self.duration > 0:
            self._timer = self.set_timer(self.duration, self._dismiss)

    def _dismiss(self) -> None:
        """Dismiss the toast."""
        self.post_message(self.Dismissed(self))
        self.remove()

    def dismiss(self) -> None:
        """Manually dismiss the toast."""
        if self._timer:
            self._timer.stop()
        self._dismiss()

    def on_click(self) -> None:
        """Dismiss on click."""
        self.dismiss()


class ToastContainer(Widget):
    """
    Container for toast notifications.

    Manages multiple toasts with stacking.
    """

    DEFAULT_CSS = """
    ToastContainer {
        layer: notification;
        dock: top;
        align: center top;
        height: auto;
        width: auto;
        margin-top: 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._toasts: list[Toast] = []

    def compose(self) -> ComposeResult:
        yield from []  # Start empty

    def show_toast(
        self,
        message: str,
        toast_type: ToastType = ToastType.INFO,
        duration: float = 3.0,
    ) -> Toast:
        """Show a new toast notification."""
        toast = Toast(message, toast_type, duration)
        self._toasts.append(toast)
        self.mount(toast)
        return toast

    def success(self, message: str, duration: float = 3.0) -> Toast:
        """Show a success toast."""
        return self.show_toast(message, ToastType.SUCCESS, duration)

    def error(self, message: str, duration: float = 5.0) -> Toast:
        """Show an error toast."""
        return self.show_toast(message, ToastType.ERROR, duration)

    def warning(self, message: str, duration: float = 4.0) -> Toast:
        """Show a warning toast."""
        return self.show_toast(message, ToastType.WARNING, duration)

    def info(self, message: str, duration: float = 3.0) -> Toast:
        """Show an info toast."""
        return self.show_toast(message, ToastType.INFO, duration)

    def on_toast_dismissed(self, event: Toast.Dismissed) -> None:
        """Handle toast dismissal."""
        if event.toast in self._toasts:
            self._toasts.remove(event.toast)

    def clear_all(self) -> None:
        """Clear all toasts."""
        for toast in list(self._toasts):
            toast.dismiss()
        self._toasts.clear()
