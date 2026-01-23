"""
Agent Collaboration View - Multi-Agent Pipeline Visualization.

A SuperQode-original widget showing the flow of work between
multiple QE agents. Displays agent states, handoffs, and
current activities in a visual pipeline.

Design: Unique SuperQode visualization for multi-agent collaboration
that emphasizes the "team of agents" concept.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static
from textual.timer import Timer


class AgentState(Enum):
    """State of an agent in the pipeline."""

    IDLE = "idle"  # ○ Gray - waiting
    ACTIVE = "active"  # ● Blue - currently working
    COMPLETE = "complete"  # ✓ Green - finished successfully
    ERROR = "error"  # ✗ Red - encountered error
    PENDING = "pending"  # ◐ Yellow - about to start


@dataclass
class AgentNode:
    """An agent in the collaboration pipeline."""

    id: str
    name: str
    role: str  # e.g., "Scout", "Verifier", "Reviewer"
    state: AgentState = AgentState.IDLE
    current_task: str = ""
    issues_found: int = 0
    issues_verified: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get duration in seconds if completed."""
        if self.started_at:
            end = self.completed_at or datetime.now()
            return (end - self.started_at).total_seconds()
        return None


@dataclass
class Handoff:
    """A handoff between agents."""

    from_agent: str
    to_agent: str
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    issue_count: int = 0


# Agent role colors and icons - SuperQode branding
AGENT_STYLES = {
    "Scout": {"color": "#f59e0b", "icon": "🔍"},  # Orange - discovery
    "Verifier": {"color": "#3b82f6", "icon": "✓"},  # Blue - validation
    "Reviewer": {"color": "#8b5cf6", "icon": "📝"},  # Purple - review
    "Fixer": {"color": "#22c55e", "icon": "🔧"},  # Green - fix
    "Tester": {"color": "#06b6d4", "icon": "🧪"},  # Cyan - test
    "Guardian": {"color": "#ef4444", "icon": "🛡️"},  # Red - security
}

STATE_SYMBOLS = {
    AgentState.IDLE: ("○", "#6b7280"),
    AgentState.ACTIVE: ("●", "#3b82f6"),
    AgentState.COMPLETE: ("✓", "#22c55e"),
    AgentState.ERROR: ("✗", "#ef4444"),
    AgentState.PENDING: ("◐", "#eab308"),
}


class AgentCollabView(Static):
    """Agent Collaboration Pipeline Widget.

    Displays the flow of work between multiple QE agents in a visual
    pipeline format, showing states, handoffs, and current activities.

    Usage:
        collab = AgentCollabView()
        collab.add_agent(AgentNode("scout", "Scout Agent", "Scout"))
        collab.add_agent(AgentNode("verifier", "Verifier Agent", "Verifier"))
        collab.set_agent_state("scout", AgentState.ACTIVE, "Scanning codebase...")
    """

    DEFAULT_CSS = """
    AgentCollabView {
        height: auto;
        border: solid #3f3f46;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    # Reactive state
    current_handoff: reactive[Optional[Handoff]] = reactive(None)
    status_message: reactive[str] = reactive("")

    def __init__(
        self,
        title: str = "Agent Orchestra",
        show_details: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.title = title
        self.show_details = show_details
        self._agents: Dict[str, AgentNode] = {}
        self._pipeline_order: List[str] = []  # Order of agents in pipeline
        self._handoffs: List[Handoff] = []
        self._animation_frame = 0
        self._timer: Optional[Timer] = None

    def on_mount(self) -> None:
        """Start animation timer when mounted."""
        self._timer = self.set_interval(0.2, self._tick, pause=True)

    def _tick(self) -> None:
        """Animation tick."""
        self._animation_frame += 1
        # Only refresh if we have an active agent
        if any(a.state == AgentState.ACTIVE for a in self._agents.values()):
            self.refresh()

    def add_agent(self, agent: AgentNode) -> None:
        """Add an agent to the pipeline."""
        self._agents[agent.id] = agent
        if agent.id not in self._pipeline_order:
            self._pipeline_order.append(agent.id)
        self.refresh()

    def set_pipeline_order(self, order: List[str]) -> None:
        """Set the order of agents in the pipeline."""
        self._pipeline_order = order
        self.refresh()

    def set_agent_state(
        self,
        agent_id: str,
        state: AgentState,
        task: str = "",
    ) -> None:
        """Update an agent's state."""
        if agent_id in self._agents:
            agent = self._agents[agent_id]
            old_state = agent.state
            agent.state = state
            agent.current_task = task

            if state == AgentState.ACTIVE and old_state != AgentState.ACTIVE:
                agent.started_at = datetime.now()
                if self._timer:
                    self._timer.resume()
            elif state in (AgentState.COMPLETE, AgentState.ERROR):
                agent.completed_at = datetime.now()
                # Pause timer if no agents are active
                if not any(a.state == AgentState.ACTIVE for a in self._agents.values()):
                    if self._timer:
                        self._timer.pause()

            self.refresh()

    def record_handoff(
        self,
        from_agent: str,
        to_agent: str,
        message: str = "",
        issue_count: int = 0,
    ) -> None:
        """Record a handoff between agents."""
        handoff = Handoff(
            from_agent=from_agent,
            to_agent=to_agent,
            message=message,
            issue_count=issue_count,
        )
        self._handoffs.append(handoff)
        self.current_handoff = handoff

        # Update issue counts
        if from_agent in self._agents:
            self._agents[from_agent].issues_found = issue_count

        self.refresh()

    def set_status(self, message: str) -> None:
        """Set the status message."""
        self.status_message = message
        self.refresh()

    def update_issues(self, agent_id: str, found: int = 0, verified: int = 0) -> None:
        """Update issue counts for an agent."""
        if agent_id in self._agents:
            if found:
                self._agents[agent_id].issues_found = found
            if verified:
                self._agents[agent_id].issues_verified = verified
            self.refresh()

    def clear(self) -> None:
        """Reset all agents to idle."""
        for agent in self._agents.values():
            agent.state = AgentState.IDLE
            agent.current_task = ""
            agent.started_at = None
            agent.completed_at = None
        self._handoffs.clear()
        self.current_handoff = None
        self.status_message = ""
        if self._timer:
            self._timer.pause()
        self.refresh()

    def _get_active_indicator(self) -> str:
        """Get animated indicator for active state."""
        indicators = ["◐", "◓", "◑", "◒"]
        return indicators[self._animation_frame % len(indicators)]

    def _render_agent_box(self, agent: AgentNode, is_current: bool = False) -> Text:
        """Render a single agent box."""
        style = AGENT_STYLES.get(agent.role, {"color": "#6b7280", "icon": "◆"})
        color = style["color"]
        symbol, symbol_color = STATE_SYMBOLS[agent.state]

        # Use animated symbol for active state
        if agent.state == AgentState.ACTIVE:
            symbol = self._get_active_indicator()

        result = Text()

        # Box top
        box_width = 10
        result.append("┌" + "─" * box_width + "┐\n", style="#3f3f46")

        # Agent name (centered)
        name = agent.role[:box_width]
        padding = (box_width - len(name)) // 2
        result.append("│", style="#3f3f46")
        result.append(
            " " * padding + name + " " * (box_width - len(name) - padding), style=f"bold {color}"
        )
        result.append("│\n", style="#3f3f46")

        # State symbol (centered)
        result.append("│", style="#3f3f46")
        result.append(
            " " * (box_width // 2) + symbol + " " * (box_width - box_width // 2 - 1),
            style=f"bold {symbol_color}",
        )
        result.append("│\n", style="#3f3f46")

        # Box bottom
        result.append("└" + "─" * box_width + "┘", style="#3f3f46")

        return result

    def _render_arrow(self, active: bool = False) -> Text:
        """Render an arrow between agents."""
        result = Text()
        if active:
            result.append("───▶", style="bold #3b82f6")
        else:
            result.append("───▶", style="#3f3f46")
        return result

    def render(self) -> RenderableType:
        """Render the collaboration view."""
        content = Text()

        if not self._agents:
            content.append("No agents configured", style="#6b7280")
            return Panel(
                content,
                title=f"[bold #8b5cf6]{self.title}[/]",
                border_style="#3f3f46",
            )

        content.append("\n")

        # Get ordered agents
        ordered_agents = [self._agents[aid] for aid in self._pipeline_order if aid in self._agents]

        # Add any agents not in pipeline order
        for aid, agent in self._agents.items():
            if aid not in self._pipeline_order:
                ordered_agents.append(agent)

        # Build pipeline visualization (horizontal boxes with arrows)
        # We'll render as text since Textual doesn't easily support side-by-side widgets

        # Line 1: Box tops
        for i, agent in enumerate(ordered_agents):
            style = AGENT_STYLES.get(agent.role, {"color": "#6b7280"})
            content.append("  ┌─────────┐", style="#3f3f46")
            if i < len(ordered_agents) - 1:
                content.append("    ")
        content.append("\n")

        # Line 2: Agent names
        for i, agent in enumerate(ordered_agents):
            style = AGENT_STYLES.get(agent.role, {"color": "#6b7280"})
            color = style["color"]
            name = agent.role[:9].center(9)
            content.append("  │", style="#3f3f46")
            content.append(name, style=f"bold {color}")
            content.append("│", style="#3f3f46")
            if i < len(ordered_agents) - 1:
                # Arrow between agents
                is_handoff = self.current_handoff and self.current_handoff.from_agent == agent.id
                if is_handoff:
                    content.append("───▶", style="bold #3b82f6")
                else:
                    content.append("───▶", style="#52525b")
        content.append("\n")

        # Line 3: State symbols
        for i, agent in enumerate(ordered_agents):
            symbol, symbol_color = STATE_SYMBOLS[agent.state]
            if agent.state == AgentState.ACTIVE:
                symbol = self._get_active_indicator()
            content.append("  │", style="#3f3f46")
            content.append(f"    {symbol}    ", style=f"bold {symbol_color}")
            content.append("│", style="#3f3f46")
            if i < len(ordered_agents) - 1:
                content.append("    ")
        content.append("\n")

        # Line 4: Box bottoms
        for i, agent in enumerate(ordered_agents):
            content.append("  └─────────┘", style="#3f3f46")
            if i < len(ordered_agents) - 1:
                content.append("    ")
        content.append("\n")

        # Status section
        if self.show_details:
            content.append("\n")

            # Current handoff info
            if self.current_handoff:
                from_name = self._agents.get(self.current_handoff.from_agent)
                to_name = self._agents.get(self.current_handoff.to_agent)

                if from_name and to_name:
                    content.append(f"  {from_name.role}", style="bold #f59e0b")
                    if self.current_handoff.issue_count:
                        content.append(
                            f" found {self.current_handoff.issue_count} issues", style="#a1a1aa"
                        )
                    content.append(" → ", style="#6b7280")
                    content.append(f"{to_name.role}", style="bold #3b82f6")
                    if to_name.current_task:
                        content.append(f" {to_name.current_task}", style="#a1a1aa")
                    content.append("\n")

            # Active agent task
            active_agents = [a for a in ordered_agents if a.state == AgentState.ACTIVE]
            if active_agents and not self.current_handoff:
                agent = active_agents[0]
                style = AGENT_STYLES.get(agent.role, {"color": "#6b7280", "icon": "◆"})
                content.append(f"  [{style['icon']} {agent.role}] ", style=f"bold {style['color']}")
                content.append(agent.current_task or "Working...", style="#a1a1aa")
                content.append("\n")

            # Status message
            if self.status_message:
                content.append(f"  {self.status_message}", style="#6b7280")

        return Panel(
            content,
            title=f"[bold #8b5cf6]{self.title}[/]",
            border_style="#3f3f46",
            padding=(0, 0),
        )
