"""Status bar widget showing current state, connection, and shortcuts - High contrast design."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from superqode.app_main import SuperQodeApp


class StatusBar(Widget):
    """
    Bottom status bar showing:
    - Current runtime/mode
    - Connected agent and status
    - Current project directory
    - Keyboard shortcut hints

    High contrast, accessible design.
    """

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 2;
        background: #001a33;
    }

    StatusBar > Horizontal {
        width: 100%;
        height: 2;
        background: #001a33;
    }

    StatusBar .status-section {
        height: 2;
        padding: 0 2;
        background: #001a33;
        content-align: center middle;
    }

    StatusBar #mode-indicator {
        color: #00ffff;
        text-style: bold;
        background: #003366;
        min-width: 20;
    }

    StatusBar #agent-indicator {
        color: #00ff00;
        text-style: bold;
        min-width: 25;
    }

    StatusBar #agent-indicator.disconnected {
        color: #ffaa00;
    }

    StatusBar #project-indicator {
        color: #ffffff;
        min-width: 20;
    }

    StatusBar #shortcuts-indicator {
        dock: right;
        color: #00ff00;
        text-style: bold;
    }
    """

    # Reactive properties
    mode: reactive[str] = reactive("HOME")
    agent_name: reactive[str] = reactive("")
    agent_connected: reactive[bool] = reactive(False)
    project_path: reactive[str] = reactive("")
    task_count: reactive[int] = reactive(0)
    runtime_name: reactive[str] = reactive("builtin")
    model: reactive[str] = reactive("")  # active model, shown next to the runtime

    def __init__(
        self,
        mode: str = "HOME",
        agent_name: str = "",
        agent_connected: bool = False,
        project_path: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.mode = mode
        self.agent_name = agent_name
        self.agent_connected = agent_connected
        self.project_path = project_path or Path.cwd().name

    def compose(self) -> ComposeResult:
        """Compose the status bar layout."""
        with Horizontal():
            yield Static(self._get_mode_text(), id="mode-indicator", classes="status-section")
            yield Static(self._get_agent_text(), id="agent-indicator", classes="status-section")
            yield Static(self._get_runtime_text(), id="runtime-indicator", classes="status-section")
            yield Static(self._get_project_text(), id="project-indicator", classes="status-section")
            yield Static(
                self._get_shortcuts_text(), id="shortcuts-indicator", classes="status-section"
            )

    def _get_mode_text(self) -> str:
        """Get the mode indicator text."""
        mode_icons = {
            "HOME": "🏠",
            "DEV": "💻",
            "DEVOPS": "⚙️",
        }
        # Extract base mode for icon
        base_mode = self.mode.split(".")[0].upper() if "." in self.mode else self.mode.upper()
        icon = mode_icons.get(base_mode, "🔧")
        return f"{icon} {self.mode}"

    def _get_agent_text(self) -> str:
        """Get the agent indicator text."""
        if self.agent_connected and self.agent_name:
            return f"🟢 {self.agent_name} CONNECTED"
        elif self.agent_name:
            return f"⚪ {self.agent_name} READY"
        else:
            return "🔌 No Agent"

    def _get_runtime_text(self) -> str:
        """Get the runtime badge text (with active model when known)."""
        if self.model:
            return f"🔧 {self.runtime_name} · {self.model}"
        return f"🔧 {self.runtime_name}"

    def _get_project_text(self) -> str:
        """Get the project indicator text."""
        if self.task_count > 0:
            return f"📁 {self.project_path} │ ⏱ {self.task_count} tasks"
        return f"📁 {self.project_path}"

    def _get_shortcuts_text(self) -> str:
        """Get the keyboard shortcuts hint text."""
        return "Ctrl+K commands │ Ctrl+A agents │ / slash │ ? help"

    def watch_mode(self, mode: str) -> None:
        """React to mode changes."""
        if not self.is_mounted:
            return
        try:
            mode_widget = self.query_one("#mode-indicator", Static)
            mode_widget.update(self._get_mode_text())
        except Exception:
            pass

    def watch_runtime_name(self, _runtime: str) -> None:
        """React to runtime swaps."""
        if not self.is_mounted:
            return
        try:
            widget = self.query_one("#runtime-indicator", Static)
            widget.update(self._get_runtime_text())
        except Exception:
            pass

    def watch_model(self, _model: str) -> None:
        """React to active-model changes (shown in the runtime badge)."""
        if not self.is_mounted:
            return
        try:
            widget = self.query_one("#runtime-indicator", Static)
            widget.update(self._get_runtime_text())
        except Exception:
            pass

    def watch_agent_name(self, agent_name: str) -> None:
        """React to agent name changes."""
        if not self.is_mounted:
            return
        self._update_agent_indicator()

    def watch_agent_connected(self, connected: bool) -> None:
        """React to connection state changes."""
        if not self.is_mounted:
            return
        self._update_agent_indicator()

    def _update_agent_indicator(self) -> None:
        """Update the agent indicator widget."""
        try:
            agent_widget = self.query_one("#agent-indicator", Static)
            agent_widget.update(self._get_agent_text())
            agent_widget.set_class(not self.agent_connected, "disconnected")
        except Exception:
            pass

    def watch_project_path(self, path: str) -> None:
        """React to project path changes."""
        if not self.is_mounted:
            return
        try:
            project_widget = self.query_one("#project-indicator", Static)
            project_widget.update(self._get_project_text())
        except Exception:
            pass

    def watch_task_count(self, count: int) -> None:
        """React to task count changes."""
        if not self.is_mounted:
            return
        try:
            project_widget = self.query_one("#project-indicator", Static)
            project_widget.update(self._get_project_text())
        except Exception:
            pass

    def set_connected(self, agent_name: str, connected: bool = True) -> None:
        """Set the connection state."""
        self.agent_name = agent_name
        self.agent_connected = connected

    def set_mode(self, mode: str) -> None:
        """Set the current mode."""
        self.mode = mode

    def set_tasks(self, count: int) -> None:
        """Set the task count."""
        self.task_count = count
