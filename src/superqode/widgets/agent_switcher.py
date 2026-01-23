"""Agent switcher modal widget (Ctrl+A) - Redesigned for accessibility."""

from __future__ import annotations

from dataclasses import dataclass
import uuid

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


@dataclass
class AgentInfo:
    """Information about an agent."""

    identity: str
    name: str
    short_name: str
    description: str
    installed: bool = False
    connected: bool = False
    agent_type: str = "coding"
    provider: str = ""  # e.g., "OpenCode", "Gemini", "OpenAI"


class AgentItem(Widget):
    """A single agent item in the switcher - high contrast design."""

    DEFAULT_CSS = """
    AgentItem {
        height: auto;
        min-height: 5;
        padding: 1;
        margin: 0 0 1 0;
        background: #1a1a1a;
        border: solid #444444;
        layout: vertical;
    }

    AgentItem:hover {
        border: solid #00ffff;
        background: #2a2a2a;
    }

    AgentItem.selected {
        border: double #00ff00;
        background: #002200;
    }

    AgentItem.connected {
        border: solid #00ff00;
        background: #002200;
    }

    AgentItem .agent-header {
        height: 1;
        width: 100%;
    }

    AgentItem .status-icon {
        width: 4;
        color: #ffffff;
    }

    AgentItem .agent-name {
        text-style: bold;
        color: #ffffff;
    }

    AgentItem .agent-status-text {
        dock: right;
        color: #00ff00;
        text-style: bold;
        padding-right: 1;
    }

    AgentItem .agent-provider {
        color: #00ffff;
        text-style: bold;
        padding-left: 4;
        height: 1;
    }

    AgentItem .agent-description {
        color: #aaaaaa;
        padding-left: 4;
        height: 1;
    }

    AgentItem .agent-type {
        color: #888888;
        padding-left: 4;
        text-style: italic;
    }

    AgentItem.not-installed .agent-name {
        color: #888888;
    }

    AgentItem.not-installed .agent-status-text {
        color: #ffaa00;
    }
    """

    class Selected(Message):
        """Message sent when agent is selected."""

        def __init__(self, agent: AgentInfo) -> None:
            self.agent = agent
            super().__init__()

    selected: reactive[bool] = reactive(False)

    def __init__(self, agent: AgentInfo, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def compose(self) -> ComposeResult:
        # Header row with icon, name, and status
        with Horizontal(classes="agent-header"):
            # Status icon - clear and visible
            if self.agent.connected:
                icon = "🟢"
                status_text = "CONNECTED"
            elif self.agent.installed:
                icon = "✅"
                status_text = "READY"
            else:
                icon = "📦"
                status_text = "INSTALL"

            yield Static(icon, classes="status-icon")
            yield Static(f"{self.agent.name}", classes="agent-name")
            yield Static(status_text, classes="agent-status-text")

        # Provider/Coding Agent info
        provider_text = self.agent.provider or self.agent.short_name.upper()
        yield Static(f"🤖 Coding Agent: {provider_text}", classes="agent-provider")

        # Description
        desc = (
            self.agent.description[:55] + "..."
            if len(self.agent.description) > 55
            else self.agent.description
        )
        yield Static(desc if desc else "No description", classes="agent-description")

        # Agent type
        yield Static(f"Type: {self.agent.agent_type}", classes="agent-type")

    def on_mount(self) -> None:
        """Set classes on mount."""
        self.set_class(self.agent.connected, "connected")
        self.set_class(not self.agent.installed, "not-installed")

    def watch_selected(self, selected: bool) -> None:
        self.set_class(selected, "selected")

    def on_click(self) -> None:
        self.post_message(self.Selected(self.agent))


class AgentSwitcher(Widget):
    """
    Quick agent switcher modal (Ctrl+A) - High contrast, accessible design.

    Shows available agents with their status and allows quick switching.
    """

    DEFAULT_CSS = """
    AgentSwitcher {
        layer: overlay;
        align: center middle;
        width: 75;
        height: auto;
        max-height: 28;
        background: #000000;
        border: double #00ffff;
        display: none;
    }

    AgentSwitcher.visible {
        display: block;
    }

    AgentSwitcher #switcher-title-bar {
        height: 3;
        background: #001a33;
        padding: 1;
    }

    AgentSwitcher #switcher-title {
        text-style: bold;
        color: #00ffff;
        text-align: center;
    }

    AgentSwitcher #switcher-subtitle {
        color: #888888;
        text-align: center;
    }

    AgentSwitcher #agent-list {
        height: auto;
        max-height: 21;
        padding: 1;
        background: #0a0a0a;
    }

    AgentSwitcher #switcher-footer {
        height: 2;
        background: #1a1a1a;
        color: #00ffff;
        padding: 0 1;
        border-top: solid #333333;
    }

    AgentSwitcher #footer-hints {
        text-align: center;
        color: #00ff00;
    }

    AgentSwitcher .empty-message {
        padding: 2;
        color: #ffff00;
        text-style: bold;
        text-align: center;
        background: #1a1a00;
        border: solid #ffff00;
        margin: 1;
    }

    AgentSwitcher .agent-count {
        dock: right;
        color: #00ff00;
    }
    """

    class AgentSelected(Message):
        """Message sent when an agent is selected."""

        def __init__(self, agent: AgentInfo) -> None:
            self.agent = agent
            super().__init__()

    class Dismissed(Message):
        """Message sent when switcher is dismissed."""

    # State
    is_visible: reactive[bool] = reactive(False)
    selected_index: reactive[int] = reactive(0)

    def __init__(self, agents: list[AgentInfo] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agents: list[AgentInfo] = agents or []
        self._render_id = ""  # Unique ID for each render

    def compose(self) -> ComposeResult:
        with Vertical(id="switcher-title-bar"):
            yield Static("🤖 AGENT SWITCHER", id="switcher-title")
            yield Static("Select a coding agent to connect", id="switcher-subtitle")
        yield VerticalScroll(id="agent-list")
        with Vertical(id="switcher-footer"):
            yield Static("↑↓ Navigate  │  Enter Connect  │  Esc Close", id="footer-hints")

    def show(self, agents: list[AgentInfo] | None = None) -> None:
        """Show agent switcher."""
        if agents is not None:
            self.agents = agents
        self.selected_index = 0
        self.is_visible = True
        self.add_class("visible")
        self._render_agents()
        self.focus()

    def hide(self) -> None:
        """Hide agent switcher."""
        self.is_visible = False
        self.remove_class("visible")
        self.post_message(self.Dismissed())

    def toggle(self, agents: list[AgentInfo] | None = None) -> None:
        """Toggle visibility."""
        if self.is_visible:
            self.hide()
        else:
            self.show(agents)

    def _render_agents(self) -> None:
        """Render the agent list with clear visibility."""
        # Generate unique ID for this render to avoid duplicate widget IDs
        self._render_id = uuid.uuid4().hex[:8]

        container = self.query_one("#agent-list", VerticalScroll)
        container.remove_children()

        if not self.agents:
            container.mount(
                Static(
                    "No agents found!\nUse /store to browse and install agents.",
                    classes="empty-message",
                )
            )
            return

        # Sort: connected first, then installed, then others
        sorted_agents = sorted(
            self.agents,
            key=lambda a: (not a.connected, not a.installed, a.name),
        )

        for i, agent in enumerate(sorted_agents):
            # Use unique render_id + index to ensure unique widget IDs
            item = AgentItem(agent, id=f"agent-{self._render_id}-{i}")
            item.selected = i == self.selected_index
            container.mount(item)

        # Update title to show count
        title = self.query_one("#switcher-title", Static)
        installed = sum(1 for a in self.agents if a.installed)
        connected = sum(1 for a in self.agents if a.connected)
        title.update(f"🤖 CODING AGENTS ({installed} installed, {connected} connected)")

    def _update_selection(self) -> None:
        """Update visual selection state."""
        items = list(self.query("#agent-list AgentItem"))
        for i, item in enumerate(items):
            if isinstance(item, AgentItem):
                item.selected = i == self.selected_index

    def move_selection(self, delta: int) -> None:
        """Move selection up or down."""
        if not self.agents:
            return
        new_index = (self.selected_index + delta) % len(self.agents)
        self.selected_index = new_index
        self._update_selection()

        # Scroll to make selection visible
        try:
            container = self.query_one("#agent-list", VerticalScroll)
            items = list(self.query("#agent-list AgentItem"))
            if 0 <= self.selected_index < len(items):
                container.scroll_visible(items[self.selected_index])
        except Exception:
            pass

    def select_current(self) -> AgentInfo | None:
        """Select the current agent."""
        if self.agents and 0 <= self.selected_index < len(self.agents):
            # Get sorted agents (same order as rendered)
            sorted_agents = sorted(
                self.agents,
                key=lambda a: (not a.connected, not a.installed, a.name),
            )
            agent = sorted_agents[self.selected_index]
            self.post_message(self.AgentSelected(agent))
            self.hide()
            return agent
        return None

    def on_key(self, event) -> None:
        """Handle key events."""
        if not self.is_visible:
            return

        if event.key == "escape":
            self.hide()
            event.stop()
        elif event.key == "up":
            self.move_selection(-1)
            event.stop()
        elif event.key == "down":
            self.move_selection(1)
            event.stop()
        elif event.key == "enter":
            self.select_current()
            event.stop()

    @on(AgentItem.Selected)
    def on_agent_item_selected(self, event: AgentItem.Selected) -> None:
        """Handle agent selection via click."""
        self.post_message(self.AgentSelected(event.agent))
        self.hide()

    def update_agents(self, agents: list[AgentInfo]) -> None:
        """Update the agent list."""
        self.agents = agents
        if self.is_visible:
            self._render_agents()
