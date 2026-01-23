"""
Enhanced Toast/Flash System - Rich Notifications.

Provides a comprehensive notification system with:
- Multiple toast types (success, warning, error, info, progress)
- Stacking and queuing
- Progress toasts with updates
- Interactive toasts with actions
- Auto-dismiss with configurable timeouts

Enhances the basic toast widget with production-ready features.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional
from uuid import uuid4

from rich.console import RenderableType
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static
from textual.containers import Container
from textual.timer import Timer
from textual import events


class ToastType(Enum):
    """Type of toast notification."""

    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"
    PROGRESS = "progress"
    ACTION = "action"


@dataclass
class ToastConfig:
    """Configuration for toast behavior."""

    # Timing
    default_timeout: float = 5.0
    error_timeout: float = 10.0
    progress_timeout: float = 30.0

    # Display
    max_visible: int = 5
    position: str = "bottom-right"  # top-right, top-left, bottom-right, bottom-left
    animation: bool = True

    # Sound (if terminal supports)
    sound_enabled: bool = False


@dataclass
class Toast:
    """A single toast notification."""

    id: str
    type: ToastType
    title: str
    message: str = ""
    timeout: float = 5.0
    created_at: datetime = field(default_factory=datetime.now)

    # Progress toast specific
    progress: float = 0.0  # 0.0 to 1.0
    progress_text: str = ""

    # Action toast specific
    actions: List[Dict] = field(default_factory=list)  # [{"label": "...", "callback": ...}]

    # State
    dismissed: bool = False
    pinned: bool = False  # Don't auto-dismiss

    @property
    def is_expired(self) -> bool:
        """Check if toast has expired."""
        if self.pinned or self.dismissed:
            return False
        if self.type == ToastType.PROGRESS and self.progress < 1.0:
            return False
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed >= self.timeout


# Toast type styling
TOAST_STYLES = {
    ToastType.SUCCESS: {
        "icon": "✓",
        "color": "#22c55e",
        "border": "#16a34a",
        "bg": "#052e16",
    },
    ToastType.WARNING: {
        "icon": "⚠",
        "color": "#eab308",
        "border": "#ca8a04",
        "bg": "#422006",
    },
    ToastType.ERROR: {
        "icon": "✗",
        "color": "#ef4444",
        "border": "#dc2626",
        "bg": "#450a0a",
    },
    ToastType.INFO: {
        "icon": "ℹ",
        "color": "#3b82f6",
        "border": "#2563eb",
        "bg": "#172554",
    },
    ToastType.PROGRESS: {
        "icon": "◐",
        "color": "#8b5cf6",
        "border": "#7c3aed",
        "bg": "#2e1065",
    },
    ToastType.ACTION: {
        "icon": "▶",
        "color": "#06b6d4",
        "border": "#0891b2",
        "bg": "#083344",
    },
}


class ToastWidget(Static):
    """Single toast notification widget."""

    DEFAULT_CSS = """
    ToastWidget {
        width: 50;
        height: auto;
        margin: 0 0 1 0;
        layer: notification;
    }
    """

    def __init__(self, toast: Toast, on_dismiss: Callable[[], None], **kwargs):
        super().__init__(**kwargs)
        self.toast = toast
        self._on_dismiss = on_dismiss
        self._animation_frame = 0

    def on_click(self, event: events.Click) -> None:
        """Dismiss on click."""
        if self.toast.type != ToastType.ACTION:
            self._on_dismiss()

    def on_key(self, event: events.Key) -> None:
        """Handle key events for actions."""
        if self.toast.type == ToastType.ACTION and self.toast.actions:
            for i, action in enumerate(self.toast.actions):
                if event.key == str(i + 1):
                    callback = action.get("callback")
                    if callback:
                        callback()
                    self._on_dismiss()
                    event.prevent_default()
                    return

    def update_progress(self, progress: float, text: str = "") -> None:
        """Update progress toast."""
        self.toast.progress = progress
        if text:
            self.toast.progress_text = text
        self.refresh()

    def _get_spinner(self) -> str:
        """Get spinner character for progress."""
        spinners = ["◐", "◓", "◑", "◒"]
        return spinners[self._animation_frame % len(spinners)]

    def render(self) -> RenderableType:
        """Render the toast."""
        style = TOAST_STYLES.get(self.toast.type, TOAST_STYLES[ToastType.INFO])

        content = Text()

        # Icon
        icon = style["icon"]
        if self.toast.type == ToastType.PROGRESS and self.toast.progress < 1.0:
            icon = self._get_spinner()

        content.append(f" {icon} ", style=f"bold {style['color']}")

        # Title
        content.append(self.toast.title, style=f"bold {style['color']}")

        # Message
        if self.toast.message:
            content.append(f"\n   {self.toast.message}", style="#a1a1aa")

        # Progress bar
        if self.toast.type == ToastType.PROGRESS:
            content.append("\n   ")

            bar_width = 30
            filled = int(self.toast.progress * bar_width)

            content.append("[", style="#3f3f46")
            content.append("█" * filled, style=f"bold {style['color']}")
            content.append("░" * (bar_width - filled), style="#27272a")
            content.append("]", style="#3f3f46")

            pct = int(self.toast.progress * 100)
            content.append(f" {pct}%", style="#6b7280")

            if self.toast.progress_text:
                content.append(f"\n   {self.toast.progress_text}", style="#6b7280")

        # Actions
        if self.toast.type == ToastType.ACTION and self.toast.actions:
            content.append("\n   ")
            for i, action in enumerate(self.toast.actions):
                content.append(f"[{i + 1}] ", style=f"bold {style['color']}")
                content.append(f"{action['label']}  ", style="#a1a1aa")

        return Panel(
            content,
            border_style=style["border"],
            padding=(0, 1),
        )


class ToastContainer(Container):
    """
    Container for managing multiple toast notifications.

    Usage:
        # In your App
        def compose(self):
            yield ToastContainer(id="toasts")

        # Show toasts
        toasts = self.query_one("#toasts", ToastContainer)
        toasts.success("File saved!")
        toasts.error("Connection failed", "Could not reach server")

        # Progress toast
        toast_id = toasts.progress("Uploading...", "Starting upload")
        toasts.update_progress(toast_id, 0.5, "50% complete")
        toasts.update_progress(toast_id, 1.0, "Done!")
    """

    DEFAULT_CSS = """
    ToastContainer {
        dock: bottom;
        width: 100%;
        height: auto;
        max-height: 50%;
        align: right bottom;
        padding: 1;
        layer: notification;
    }
    """

    def __init__(
        self,
        config: Optional[ToastConfig] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.config = config or ToastConfig()
        self._toasts: Dict[str, Toast] = {}
        self._widgets: Dict[str, ToastWidget] = {}
        self._timer: Optional[Timer] = None

    def on_mount(self) -> None:
        """Start cleanup timer."""
        self._timer = self.set_interval(1.0, self._cleanup_expired)

    def _cleanup_expired(self) -> None:
        """Remove expired toasts."""
        expired = [tid for tid, toast in self._toasts.items() if toast.is_expired]

        for tid in expired:
            self._remove_toast(tid)

    def _add_toast(self, toast: Toast) -> str:
        """Add a toast to the container."""
        # Limit visible toasts
        while len(self._toasts) >= self.config.max_visible:
            oldest = min(self._toasts.values(), key=lambda t: t.created_at)
            self._remove_toast(oldest.id)

        self._toasts[toast.id] = toast

        # Create widget
        widget = ToastWidget(
            toast,
            on_dismiss=lambda: self._remove_toast(toast.id),
            id=f"toast-{toast.id}",
        )
        self._widgets[toast.id] = widget
        self.mount(widget)

        return toast.id

    def _remove_toast(self, toast_id: str) -> None:
        """Remove a toast."""
        toast = self._toasts.pop(toast_id, None)
        widget = self._widgets.pop(toast_id, None)

        if widget:
            widget.remove()

        if toast:
            toast.dismissed = True

    def success(self, title: str, message: str = "", timeout: float = None) -> str:
        """Show a success toast."""
        toast = Toast(
            id=str(uuid4())[:8],
            type=ToastType.SUCCESS,
            title=title,
            message=message,
            timeout=timeout or self.config.default_timeout,
        )
        return self._add_toast(toast)

    def warning(self, title: str, message: str = "", timeout: float = None) -> str:
        """Show a warning toast."""
        toast = Toast(
            id=str(uuid4())[:8],
            type=ToastType.WARNING,
            title=title,
            message=message,
            timeout=timeout or self.config.default_timeout,
        )
        return self._add_toast(toast)

    def error(self, title: str, message: str = "", timeout: float = None) -> str:
        """Show an error toast."""
        toast = Toast(
            id=str(uuid4())[:8],
            type=ToastType.ERROR,
            title=title,
            message=message,
            timeout=timeout or self.config.error_timeout,
        )
        return self._add_toast(toast)

    def info(self, title: str, message: str = "", timeout: float = None) -> str:
        """Show an info toast."""
        toast = Toast(
            id=str(uuid4())[:8],
            type=ToastType.INFO,
            title=title,
            message=message,
            timeout=timeout or self.config.default_timeout,
        )
        return self._add_toast(toast)

    def progress(
        self,
        title: str,
        message: str = "",
        initial_progress: float = 0.0,
    ) -> str:
        """Show a progress toast."""
        toast = Toast(
            id=str(uuid4())[:8],
            type=ToastType.PROGRESS,
            title=title,
            message=message,
            progress=initial_progress,
            timeout=self.config.progress_timeout,
            pinned=True,
        )
        return self._add_toast(toast)

    def update_progress(
        self,
        toast_id: str,
        progress: float,
        text: str = "",
    ) -> None:
        """Update a progress toast."""
        toast = self._toasts.get(toast_id)
        if toast and toast.type == ToastType.PROGRESS:
            toast.progress = progress
            if text:
                toast.progress_text = text

            # Auto-dismiss when complete
            if progress >= 1.0:
                toast.pinned = False
                toast.timeout = 3.0
                toast.created_at = datetime.now()

            widget = self._widgets.get(toast_id)
            if widget:
                widget.refresh()

    def action(
        self,
        title: str,
        message: str = "",
        actions: List[Dict] = None,
    ) -> str:
        """Show an action toast with buttons."""
        toast = Toast(
            id=str(uuid4())[:8],
            type=ToastType.ACTION,
            title=title,
            message=message,
            actions=actions or [],
            pinned=True,  # Don't auto-dismiss action toasts
            timeout=30.0,
        )
        return self._add_toast(toast)

    def dismiss(self, toast_id: str) -> None:
        """Manually dismiss a toast."""
        self._remove_toast(toast_id)

    def dismiss_all(self) -> None:
        """Dismiss all toasts."""
        for toast_id in list(self._toasts.keys()):
            self._remove_toast(toast_id)


# Convenience functions for module-level usage
_global_container: Optional[ToastContainer] = None


def set_toast_container(container: ToastContainer) -> None:
    """Set the global toast container."""
    global _global_container
    _global_container = container


def toast_success(title: str, message: str = "") -> Optional[str]:
    """Show a success toast."""
    if _global_container:
        return _global_container.success(title, message)
    return None


def toast_warning(title: str, message: str = "") -> Optional[str]:
    """Show a warning toast."""
    if _global_container:
        return _global_container.warning(title, message)
    return None


def toast_error(title: str, message: str = "") -> Optional[str]:
    """Show an error toast."""
    if _global_container:
        return _global_container.error(title, message)
    return None


def toast_info(title: str, message: str = "") -> Optional[str]:
    """Show an info toast."""
    if _global_container:
        return _global_container.info(title, message)
    return None


def toast_progress(title: str, message: str = "") -> Optional[str]:
    """Show a progress toast."""
    if _global_container:
        return _global_container.progress(title, message)
    return None
