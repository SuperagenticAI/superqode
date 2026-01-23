"""
Enhanced Status Bar - Comprehensive Information Display.

A beautiful, information-rich status bar showing:
- Connection status (ACP/BYOK)
- Model and provider info
- Token usage and cost
- Tool call progress
- Thinking indicator
- Mode indicator
- Conversation count
- Latency/performance

Brings together all status information in one place.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from rich.console import RenderableType
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static
from textual.containers import Horizontal
from textual.timer import Timer
from textual import events


class AgentStatus(Enum):
    """Status of the agent."""

    IDLE = "idle"
    CONNECTING = "connecting"
    THINKING = "thinking"
    STREAMING = "streaming"
    TOOL_CALL = "tool_call"
    WAITING = "waiting"
    ERROR = "error"


@dataclass
class StatusBarState:
    """State for the enhanced status bar."""

    # Connection
    connected: bool = False
    connection_type: str = ""  # "acp", "byok", "local"

    # Agent/Model
    agent_name: str = ""
    model_name: str = ""
    provider: str = ""

    # Status
    status: AgentStatus = AgentStatus.IDLE
    status_message: str = ""

    # Progress
    tool_count: int = 0
    tools_running: int = 0
    tools_complete: int = 0
    tools_error: int = 0

    # Tokens
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0

    # Conversation
    message_count: int = 0

    # Mode
    mode: str = "home"

    # Performance
    latency_ms: Optional[float] = None
    last_response_time: Optional[float] = None


# Status styling
STATUS_STYLES = {
    AgentStatus.IDLE: {"icon": "○", "color": "#52525b", "animate": False},
    AgentStatus.CONNECTING: {"icon": "◐", "color": "#fbbf24", "animate": True},
    AgentStatus.THINKING: {"icon": "💭", "color": "#ec4899", "animate": True},
    AgentStatus.STREAMING: {"icon": "●", "color": "#22c55e", "animate": True},
    AgentStatus.TOOL_CALL: {"icon": "🔧", "color": "#f59e0b", "animate": True},
    AgentStatus.WAITING: {"icon": "⏳", "color": "#3b82f6", "animate": False},
    AgentStatus.ERROR: {"icon": "✗", "color": "#ef4444", "animate": False},
}

PROVIDER_ICONS = {
    "anthropic": "🧠",
    "openai": "🤖",
    "google": "🔮",
    "mistral": "🌊",
    "groq": "⚡",
    "ollama": "🦙",
    "opencode": "💻",
    "local": "💻",
}


class EnhancedStatusBar(Static):
    """
    Enhanced status bar with comprehensive information.

    Displays all key information in a compact, beautiful format.
    """

    DEFAULT_CSS = """
    EnhancedStatusBar {
        height: 1;
        background: #0f0f0f;
        border-top: solid #27272a;
        padding: 0 1;
    }

    EnhancedStatusBar.error {
        background: #1a0f0f;
    }

    EnhancedStatusBar.active {
        background: #0f1a0f;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state = StatusBarState()
        self._frame = 0
        self._timer: Optional[Timer] = None

    def on_mount(self) -> None:
        """Start animation timer."""
        self._timer = self.set_interval(0.25, self._tick)

    def _tick(self) -> None:
        """Animation tick."""
        self._frame += 1
        status_style = STATUS_STYLES.get(self._state.status, STATUS_STYLES[AgentStatus.IDLE])
        if status_style["animate"]:
            self.refresh()

    def update_state(self, **kwargs) -> None:
        """Update status bar state."""
        for key, value in kwargs.items():
            if hasattr(self._state, key):
                setattr(self._state, key, value)

        # Update CSS classes
        self.remove_class("error", "active")
        if self._state.status == AgentStatus.ERROR:
            self.add_class("error")
        elif self._state.status in (
            AgentStatus.STREAMING,
            AgentStatus.THINKING,
            AgentStatus.TOOL_CALL,
        ):
            self.add_class("active")

        self.refresh()

    def set_status(self, status: AgentStatus, message: str = "") -> None:
        """Set the current status."""
        self.update_state(status=status, status_message=message)

    def _get_animated_icon(self) -> str:
        """Get animated status icon."""
        status_style = STATUS_STYLES.get(self._state.status, STATUS_STYLES[AgentStatus.IDLE])

        if not status_style["animate"]:
            return status_style["icon"]

        if self._state.status == AgentStatus.THINKING:
            frames = ["💭", "💬", "💭", "💬"]
            return frames[self._frame % len(frames)]
        elif self._state.status == AgentStatus.STREAMING:
            frames = ["●", "◐", "○", "◑"]
            return frames[self._frame % len(frames)]
        elif self._state.status == AgentStatus.TOOL_CALL:
            frames = ["🔧", "⚙️", "🔧", "⚙️"]
            return frames[self._frame % len(frames)]
        else:
            frames = ["◐", "◓", "◑", "◒"]
            return frames[self._frame % len(frames)]

    def render(self) -> Text:
        state = self._state
        result = Text()

        # ═══════════════════════════════════════════════════════════════════
        # LEFT SECTION - Connection & Model
        # ═══════════════════════════════════════════════════════════════════

        # Connection indicator
        if state.connected:
            result.append("● ", style="bold #22c55e")
        else:
            result.append("○ ", style="#52525b")

        # Connection type badge
        if state.connection_type:
            type_label = state.connection_type.upper()
            result.append(f"[{type_label}] ", style="#6b7280")

        # Provider/Agent icon and name
        provider_icon = PROVIDER_ICONS.get(state.provider.lower(), "🤖")
        if state.agent_name:
            result.append(f"{provider_icon} ", style="#a855f7")
            result.append(state.agent_name, style="#a855f7")
        elif state.model_name:
            result.append(f"{provider_icon} ", style="#6b7280")
            # Truncate long model names
            model_display = state.model_name
            if len(model_display) > 20:
                model_display = model_display[:17] + "..."
            result.append(model_display, style="#a1a1aa")
        else:
            result.append("No agent", style="#52525b")

        result.append("  │  ", style="#27272a")

        # ═══════════════════════════════════════════════════════════════════
        # CENTER SECTION - Status
        # ═══════════════════════════════════════════════════════════════════

        status_style = STATUS_STYLES.get(state.status, STATUS_STYLES[AgentStatus.IDLE])
        status_icon = self._get_animated_icon()

        result.append(f"{status_icon} ", style=f"bold {status_style['color']}")

        # Status text
        if state.status_message:
            result.append(state.status_message[:30], style=status_style["color"])
        else:
            result.append(state.status.value.replace("_", " ").title(), style=status_style["color"])

        result.append("  │  ", style="#27272a")

        # ═══════════════════════════════════════════════════════════════════
        # TOOL PROGRESS
        # ═══════════════════════════════════════════════════════════════════

        if state.tool_count > 0 or state.tools_running > 0:
            result.append("🔧 ", style="#f59e0b")

            if state.tools_running > 0:
                result.append(f"◐{state.tools_running} ", style="bold #fbbf24")
            if state.tools_complete > 0:
                result.append(f"✓{state.tools_complete} ", style="#22c55e")
            if state.tools_error > 0:
                result.append(f"✗{state.tools_error} ", style="#ef4444")

            result.append(" │  ", style="#27272a")

        # ═══════════════════════════════════════════════════════════════════
        # RIGHT SECTION - Stats
        # ═══════════════════════════════════════════════════════════════════

        # Token usage
        total_tokens = state.prompt_tokens + state.completion_tokens
        if total_tokens > 0:
            result.append("📊 ", style="#6b7280")
            result.append(f"{total_tokens:,}", style="#a1a1aa")
            result.append("  ", style="")

        # Cost
        if state.total_cost > 0:
            result.append("💰 ", style="#6b7280")
            result.append(f"${state.total_cost:.3f}", style="#fbbf24")
            result.append("  ", style="")

        # Message count
        if state.message_count > 0:
            result.append("💬 ", style="#6b7280")
            result.append(f"{state.message_count}", style="#a1a1aa")
            result.append("  ", style="")

        # Latency
        if state.latency_ms is not None:
            latency_color = (
                "#22c55e"
                if state.latency_ms < 200
                else "#f59e0b"
                if state.latency_ms < 500
                else "#ef4444"
            )
            result.append("📶 ", style="#6b7280")
            result.append(f"{state.latency_ms:.0f}ms", style=latency_color)
            result.append("  ", style="")

        # Mode indicator
        result.append("│  ", style="#27272a")
        mode_icons = {
            "home": "🏠",
            "qe": "🔍",
            "agent": "🤖",
            "chat": "💬",
            "review": "📝",
        }
        mode_icon = mode_icons.get(state.mode.lower(), "📌")
        result.append(f"{mode_icon} ", style="#3b82f6")
        result.append(state.mode.upper(), style="bold #3b82f6")

        return result


class MiniStatusIndicator(Static):
    """
    Mini status indicator for compact displays.

    Shows essential status in minimal space.
    """

    DEFAULT_CSS = """
    MiniStatusIndicator {
        width: auto;
        height: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._connected = False
        self._status = AgentStatus.IDLE
        self._model = ""
        self._frame = 0

    def update(
        self,
        connected: bool = None,
        status: AgentStatus = None,
        model: str = None,
    ) -> None:
        """Update the indicator."""
        if connected is not None:
            self._connected = connected
        if status is not None:
            self._status = status
        if model is not None:
            self._model = model
        self.refresh()

    def animate(self) -> None:
        """Advance animation frame."""
        self._frame += 1
        self.refresh()

    def render(self) -> Text:
        result = Text()

        # Connection dot
        if self._connected:
            result.append("● ", style="bold #22c55e")
        else:
            result.append("○ ", style="#52525b")

        # Status icon
        status_style = STATUS_STYLES.get(self._status, STATUS_STYLES[AgentStatus.IDLE])
        if status_style["animate"]:
            frames = ["◐", "◓", "◑", "◒"]
            icon = frames[self._frame % len(frames)]
        else:
            icon = status_style["icon"]

        result.append(f"{icon} ", style=status_style["color"])

        # Model name (short)
        if self._model:
            model_short = self._model[:15] + "..." if len(self._model) > 15 else self._model
            result.append(model_short, style="#6b7280")

        return result


def create_default_status_bar() -> EnhancedStatusBar:
    """Create a default enhanced status bar."""
    bar = EnhancedStatusBar()
    bar.update_state(mode="home")
    return bar
