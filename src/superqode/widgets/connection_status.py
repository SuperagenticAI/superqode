"""
Connection Status Widget - ACP/BYOK Agent Connection Display.

Shows the current connection status to coding agents:
- ACP connections (OpenCode, Claude Code, etc.)
- BYOK (Bring Your Own Key) provider connections
- Connection health and latency
- Model information and token usage
- Cost tracking

Makes it clear what agent/model you're connected to.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED, SIMPLE
from textual.reactive import reactive
from textual.widgets import Static
from textual.containers import Container, Horizontal, Vertical
from textual.timer import Timer
from textual.message import Message
from textual import events


class ConnectionType(Enum):
    """Type of agent connection."""

    ACP = "acp"  # Agent Client Protocol
    BYOK = "byok"  # Bring Your Own Key (direct API)
    MCP = "mcp"  # Model Context Protocol
    LOCAL = "local"  # Local model


class ConnectionState(Enum):
    """State of the connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    BUSY = "busy"  # Agent is processing


@dataclass
class TokenUsage:
    """Token usage tracking."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Cost tracking (if available)
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0


@dataclass
class ConnectionInfo:
    """Information about the current connection."""

    connection_type: ConnectionType
    state: ConnectionState = ConnectionState.DISCONNECTED

    # Agent info
    agent_name: str = ""
    agent_version: str = ""
    agent_command: str = ""  # For ACP

    # Model info
    model_name: str = ""
    provider: str = ""  # anthropic, openai, etc.

    # Session info
    session_id: str = ""
    connected_at: Optional[datetime] = None

    # Stats
    messages_sent: int = 0
    messages_received: int = 0
    tool_calls: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)

    # Health
    latency_ms: Optional[float] = None
    last_error: str = ""


# Provider styling
PROVIDER_STYLES = {
    "anthropic": {"icon": "🧠", "color": "#d4a27f", "name": "Anthropic"},
    "openai": {"icon": "🤖", "color": "#10a37f", "name": "OpenAI"},
    "google": {"icon": "🔮", "color": "#4285f4", "name": "Google"},
    "mistral": {"icon": "🌊", "color": "#ff7000", "name": "Mistral"},
    "groq": {"icon": "⚡", "color": "#f55036", "name": "Groq"},
    "ollama": {"icon": "🦙", "color": "#ffffff", "name": "Ollama"},
    "opencode": {"icon": "💻", "color": "#3b82f6", "name": "OpenCode"},
    "toad": {"icon": "🐸", "color": "#22c55e", "name": "Toad"},
    "cursor": {"icon": "✨", "color": "#a855f7", "name": "Cursor"},
}

STATE_STYLES = {
    ConnectionState.DISCONNECTED: {"icon": "○", "color": "#52525b"},
    ConnectionState.CONNECTING: {"icon": "◐", "color": "#fbbf24"},
    ConnectionState.CONNECTED: {"icon": "●", "color": "#22c55e"},
    ConnectionState.ERROR: {"icon": "✗", "color": "#ef4444"},
    ConnectionState.BUSY: {"icon": "◑", "color": "#3b82f6"},
}

TYPE_STYLES = {
    ConnectionType.ACP: {"icon": "🔌", "label": "ACP"},
    ConnectionType.BYOK: {"icon": "🔑", "label": "BYOK"},
    ConnectionType.MCP: {"icon": "🔗", "label": "MCP"},
    ConnectionType.LOCAL: {"icon": "💻", "label": "Local"},
}


class ConnectionIndicator(Static):
    """
    Compact connection indicator for status bar.

    Shows:
    - Connection state icon
    - Agent/model name
    - Provider badge
    """

    DEFAULT_CSS = """
    ConnectionIndicator {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._info: Optional[ConnectionInfo] = None
        self._frame = 0

    def set_connection(self, info: ConnectionInfo) -> None:
        """Set connection info."""
        self._info = info
        self.refresh()

    def animate(self) -> None:
        """Advance animation frame."""
        self._frame += 1
        if self._info and self._info.state in (ConnectionState.CONNECTING, ConnectionState.BUSY):
            self.refresh()

    def render(self) -> Text:
        text = Text()

        if not self._info:
            text.append("○ ", style="#52525b")
            text.append("Not connected", style="#52525b")
            return text

        info = self._info
        state_style = STATE_STYLES.get(info.state, STATE_STYLES[ConnectionState.DISCONNECTED])

        # Animated state icon for connecting/busy
        if info.state in (ConnectionState.CONNECTING, ConnectionState.BUSY):
            icons = ["◐", "◓", "◑", "◒"]
            icon = icons[self._frame % len(icons)]
        else:
            icon = state_style["icon"]

        text.append(f"{icon} ", style=f"bold {state_style['color']}")

        # Provider icon and name
        provider_style = PROVIDER_STYLES.get(
            info.provider.lower(), {"icon": "🤖", "color": "#a1a1aa", "name": info.provider}
        )

        if info.agent_name:
            text.append(f"{provider_style['icon']} ", style=provider_style["color"])
            text.append(info.agent_name, style=provider_style["color"])
        elif info.model_name:
            text.append(f"{provider_style['icon']} ", style=provider_style["color"])
            text.append(info.model_name, style=provider_style["color"])
        else:
            text.append(info.state.value.title(), style="#a1a1aa")

        # Connection type badge
        type_style = TYPE_STYLES.get(info.connection_type, TYPE_STYLES[ConnectionType.BYOK])
        text.append(f" [{type_style['label']}]", style="#6b7280")

        return text


class ConnectionPanel(Container):
    """
    Full connection status panel.

    Shows detailed connection information including:
    - Agent/model info
    - Session stats
    - Token usage and cost
    - Connection health
    """

    DEFAULT_CSS = """
    ConnectionPanel {
        height: auto;
        border: solid #27272a;
        background: #0a0a0a;
        padding: 1;
        margin: 0 0 1 0;
    }

    ConnectionPanel.connected {
        border: solid #22c55e;
    }

    ConnectionPanel.error {
        border: solid #ef4444;
    }

    ConnectionPanel .panel-header {
        height: 2;
        margin-bottom: 1;
    }

    ConnectionPanel .panel-content {
        height: auto;
    }

    ConnectionPanel .panel-stats {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._info: Optional[ConnectionInfo] = None

    def set_connection(self, info: ConnectionInfo) -> None:
        """Set connection info."""
        self._info = info

        # Update CSS class
        self.remove_class("connected", "error")
        if info.state == ConnectionState.CONNECTED:
            self.add_class("connected")
        elif info.state == ConnectionState.ERROR:
            self.add_class("error")

        self._update_display()

    def _update_display(self) -> None:
        """Update the display."""
        try:
            header = self.query_one(".panel-header", Static)
            content = self.query_one(".panel-content", Static)
            stats = self.query_one(".panel-stats", Static)
        except Exception:
            return

        if not self._info:
            header.update(Text("No connection", style="#52525b"))
            content.update("")
            stats.update("")
            return

        info = self._info

        # Header
        header_text = Text()
        state_style = STATE_STYLES.get(info.state, STATE_STYLES[ConnectionState.DISCONNECTED])
        type_style = TYPE_STYLES.get(info.connection_type, TYPE_STYLES[ConnectionType.BYOK])

        header_text.append(f"{type_style['icon']} ", style="#6b7280")
        header_text.append(f"{type_style['label']} Connection", style="bold #e4e4e7")
        header_text.append(f"  {state_style['icon']} ", style=state_style["color"])
        header_text.append(info.state.value.title(), style=state_style["color"])

        header.update(header_text)

        # Content - connection details
        content_text = Text()

        if info.agent_name:
            provider_style = PROVIDER_STYLES.get(
                info.provider.lower(), {"icon": "🤖", "color": "#a1a1aa"}
            )
            content_text.append(f"  {provider_style['icon']} Agent: ", style="#6b7280")
            content_text.append(f"{info.agent_name}", style=provider_style["color"])
            if info.agent_version:
                content_text.append(f" v{info.agent_version}", style="#52525b")
            content_text.append("\n")

        if info.model_name:
            content_text.append("  🧠 Model: ", style="#6b7280")
            content_text.append(f"{info.model_name}", style="#e4e4e7")
            content_text.append("\n")

        if info.provider:
            content_text.append("  🏢 Provider: ", style="#6b7280")
            content_text.append(f"{info.provider.title()}", style="#a1a1aa")
            content_text.append("\n")

        if info.session_id:
            content_text.append("  📋 Session: ", style="#6b7280")
            content_text.append(f"{info.session_id[:12]}...", style="#52525b")
            content_text.append("\n")

        if info.connected_at:
            duration = (datetime.now() - info.connected_at).total_seconds()
            if duration < 60:
                dur_str = f"{duration:.0f}s"
            elif duration < 3600:
                dur_str = f"{duration / 60:.0f}m"
            else:
                dur_str = f"{duration / 3600:.1f}h"
            content_text.append("  ⏱️ Connected: ", style="#6b7280")
            content_text.append(dur_str, style="#a1a1aa")
            content_text.append("\n")

        if info.last_error:
            content_text.append("  ❌ Error: ", style="#ef4444")
            content_text.append(info.last_error[:50], style="#ef4444")
            content_text.append("\n")

        content.update(content_text)

        # Stats
        stats_text = Text()
        stats_text.append("  ─────────────────────────────\n", style="#27272a")

        # Message counts
        stats_text.append("  💬 ", style="#6b7280")
        stats_text.append(f"{info.messages_sent}↑ ", style="#3b82f6")
        stats_text.append(f"{info.messages_received}↓ ", style="#22c55e")

        # Tool calls
        stats_text.append(" │  🔧 ", style="#27272a")
        stats_text.append(f"{info.tool_calls}", style="#f59e0b")

        # Token usage
        if info.token_usage.total_tokens > 0:
            stats_text.append("\n  📊 Tokens: ", style="#6b7280")
            stats_text.append(f"{info.token_usage.prompt_tokens:,}", style="#3b82f6")
            stats_text.append(" → ", style="#52525b")
            stats_text.append(f"{info.token_usage.completion_tokens:,}", style="#22c55e")
            stats_text.append(f" ({info.token_usage.total_tokens:,} total)", style="#52525b")

        # Cost
        if info.token_usage.total_cost > 0:
            stats_text.append("\n  💰 Cost: ", style="#6b7280")
            stats_text.append(f"${info.token_usage.total_cost:.4f}", style="#fbbf24")

        # Latency
        if info.latency_ms is not None:
            stats_text.append("\n  📶 Latency: ", style="#6b7280")
            latency_color = (
                "#22c55e"
                if info.latency_ms < 200
                else "#f59e0b"
                if info.latency_ms < 500
                else "#ef4444"
            )
            stats_text.append(f"{info.latency_ms:.0f}ms", style=latency_color)

        stats.update(stats_text)

    def compose(self):
        """Compose the panel."""
        yield Static("", classes="panel-header")
        yield Static("", classes="panel-content")
        yield Static("", classes="panel-stats")


class ModelChanged(Message):
    """
    Message posted when user changes the model.

    When a user selects a new model, this message is posted to inform
    the parent app that it should reset the session with the new model.
    """

    def __init__(self, model_info: Dict[str, str]) -> None:
        """
        Initialize ModelChanged message.

        Args:
            model_info: Dictionary with model details:
                - name: Display name of the model
                - provider: Provider name (anthropic, openai, etc.)
                - id: Model identifier for API calls
        """
        super().__init__()
        self.model_info = model_info
        self.model_name = model_info.get("name", "")
        self.model_id = model_info.get("id", "")
        self.provider = model_info.get("provider", "")


class ModelSelector(Container):
    """
    Model selection widget.

    Allows switching between available models/providers.
    Posts ModelChanged message when user selects a new model.
    """

    DEFAULT_CSS = """
    ModelSelector {
        height: auto;
        border: solid #27272a;
        background: #0a0a0a;
        padding: 1;
    }

    ModelSelector .selector-header {
        height: 1;
        margin-bottom: 1;
    }

    ModelSelector .model-list {
        height: auto;
    }

    ModelSelector .model-item {
        height: 1;
        padding: 0 1;
    }

    ModelSelector .model-item:hover {
        background: #1a1a1a;
    }

    ModelSelector .model-item.selected {
        background: #1a1a2a;
        border-left: tall #3b82f6;
    }
    """

    selected_index: reactive[int] = reactive(0)

    def __init__(
        self,
        models: List[Dict[str, str]],
        on_select: Optional[Callable[[Dict[str, str]], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.models = models  # [{"name": "...", "provider": "...", "id": "..."}]
        self._on_select = on_select
        self._current_model_id: Optional[str] = None

    def on_key(self, event: events.Key) -> None:
        """Handle key events."""
        if event.key == "up":
            self.selected_index = max(0, self.selected_index - 1)
            event.prevent_default()
        elif event.key == "down":
            self.selected_index = min(len(self.models) - 1, self.selected_index + 1)
            event.prevent_default()
        elif event.key == "enter":
            if self.models:
                selected_model = self.models[self.selected_index]
                new_model_id = selected_model.get("id", "")

                # Only trigger if model actually changed
                if new_model_id != self._current_model_id:
                    self._current_model_id = new_model_id

                    # Post ModelChanged message for parent app to handle
                    self.post_message(ModelChanged(selected_model))

                # Also call callback if provided
                if self._on_select:
                    self._on_select(selected_model)

            event.prevent_default()

    def set_current_model(self, model_id: str) -> None:
        """Set the current model ID (to detect actual changes)."""
        self._current_model_id = model_id

        # Update selected index to match
        for i, model in enumerate(self.models):
            if model.get("id") == model_id:
                self.selected_index = i
                break

    def watch_selected_index(self, index: int) -> None:
        """React to selection changes."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the display."""
        try:
            model_list = self.query_one(".model-list", Container)
        except Exception:
            return

        model_list.remove_children()

        for i, model in enumerate(self.models):
            provider_style = PROVIDER_STYLES.get(
                model.get("provider", "").lower(), {"icon": "🤖", "color": "#a1a1aa"}
            )

            text = Text()
            text.append(f" {provider_style['icon']} ", style=provider_style["color"])
            text.append(model.get("name", "Unknown"), style="#e4e4e7")
            text.append(f"  ({model.get('provider', '')})", style="#6b7280")

            item = Static(text, classes="model-item")
            if i == self.selected_index:
                item.add_class("selected")

            model_list.mount(item)

    def compose(self):
        """Compose the selector."""
        yield Static(Text("🧠 Select Model", style="bold #e4e4e7"), classes="selector-header")
        with Container(classes="model-list"):
            pass

    def on_mount(self) -> None:
        """Initialize display."""
        self._update_display()
