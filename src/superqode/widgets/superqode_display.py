"""
SuperQode Display Widgets - Enhanced Display Components.

Provides enhanced display widgets for the main app that use
SuperQode's unique design system. Drop-in replacements for
existing display functions.

Usage in app_main.py:
    from superqode.widgets.superqode_display import (
        EnhancedToolPanel, EnhancedThinkingBar, EnhancedResponsePanel,
        EnhancedStatusHeader, show_tool_call, show_thinking, show_response,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from rich.text import Text
from rich.panel import Panel
from rich.syntax import Syntax
from rich.console import Group
from rich.markdown import Markdown

from textual.widgets import Static, RichLog
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.timer import Timer

if TYPE_CHECKING:
    from textual.app import App


# ============================================================================
# DESIGN SYSTEM IMPORTS
# ============================================================================

try:
    from superqode.design_system import (
        COLORS,
        GRADIENT_PURPLE,
        GRADIENT_QUANTUM,
        SUPERQODE_ICONS,
        BORDER_CHARS,
        render_gradient_text,
        render_status_indicator,
        render_tool_indicator,
        render_thinking_line,
        render_message_header,
        get_animation_frame,
    )
except ImportError:
    # Fallback colors
    class COLORS:
        primary = "#7c3aed"
        primary_light = "#a855f7"
        secondary = "#ec4899"
        success = "#10b981"
        error = "#f43f5e"
        warning = "#f59e0b"
        info = "#06b6d4"
        text_primary = "#fafafa"
        text_secondary = "#e4e4e7"
        text_muted = "#a1a1aa"
        text_dim = "#71717a"
        text_ghost = "#52525b"
        bg_surface = "#050505"
        border_subtle = "#1a1a1a"

    GRADIENT_PURPLE = ["#6d28d9", "#7c3aed", "#8b5cf6", "#a855f7"]
    SUPERQODE_ICONS = {"thinking": "◈", "success": "✦", "error": "✕"}


# ============================================================================
# ENUMS
# ============================================================================


class ToolStatus(Enum):
    """Tool execution status."""

    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    ERROR = auto()


class AgentState(Enum):
    """Agent execution state."""

    IDLE = auto()
    THINKING = auto()
    STREAMING = auto()
    TOOL_CALL = auto()
    WAITING = auto()


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class ToolCallInfo:
    """Information about a tool call."""

    id: str
    name: str
    kind: str = "other"
    status: ToolStatus = ToolStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    result: str = ""
    error: str = ""
    file_path: str = ""


@dataclass
class SessionStats:
    """Session statistics."""

    message_count: int = 0
    tool_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0
    files_read: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)


# ============================================================================
# ENHANCED STATUS HEADER
# ============================================================================


class EnhancedStatusHeader(Static):
    """
    Enhanced status header showing connection, model, and session info.

    SuperQode style: Clean, minimal, informative.
    """

    DEFAULT_CSS = """
    EnhancedStatusHeader {
        height: 1;
        background: #0a0a0a;
        border-bottom: solid #1a1a1a;
        padding: 0 1;
    }
    """

    # Reactive state
    connected: reactive[bool] = reactive(False)
    agent_name: reactive[str] = reactive("")
    model_name: reactive[str] = reactive("")
    connection_type: reactive[str] = reactive("")
    state: reactive[AgentState] = reactive(AgentState.IDLE)
    approval_mode: reactive[str] = reactive("ask")

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._stats = SessionStats()
        self._animation_tick = 0
        self._timer: Optional[Timer] = None

    def on_mount(self) -> None:
        """Start animation timer."""
        self._timer = self.set_interval(0.5, self._animate)

    def _animate(self) -> None:
        """Animation tick."""
        self._animation_tick += 1
        if self.state in (AgentState.THINKING, AgentState.STREAMING, AgentState.TOOL_CALL):
            self.refresh()

    def update_stats(self, **kwargs) -> None:
        """Update session statistics."""
        for key, value in kwargs.items():
            if hasattr(self._stats, key):
                setattr(self._stats, key, value)
        self.refresh()

    def render(self) -> Text:
        """Render the status header."""
        text = Text()

        # Connection indicator
        if self.connected:
            text.append("● ", style=f"bold {COLORS.success}")
            if self.agent_name:
                text.append(self.agent_name, style=f"bold {COLORS.text_secondary}")
            if self.model_name:
                text.append(" → ", style=COLORS.text_dim)
                text.append(self.model_name, style=COLORS.text_muted)
            if self.connection_type:
                conn_colors = {"acp": COLORS.success, "byok": COLORS.info, "local": COLORS.warning}
                text.append(
                    f" [{self.connection_type.upper()}]",
                    style=conn_colors.get(self.connection_type, COLORS.text_muted),
                )
        else:
            text.append("○ ", style=COLORS.text_dim)
            text.append("Not connected", style=COLORS.text_dim)

        text.append("  │  ", style=COLORS.text_ghost)

        # State indicator with animation
        state_text = {
            AgentState.IDLE: ("◇", "Idle", COLORS.text_dim),
            AgentState.THINKING: ("◈", "Thinking", COLORS.primary_light),
            AgentState.STREAMING: ("▸", "Streaming", COLORS.secondary),
            AgentState.TOOL_CALL: ("⚡", "Running", COLORS.warning),
            AgentState.WAITING: ("⏸", "Waiting", COLORS.info),
        }
        icon, label, color = state_text.get(self.state, ("◇", "Idle", COLORS.text_dim))

        # Animate icon for active states
        if self.state in (AgentState.THINKING, AgentState.STREAMING, AgentState.TOOL_CALL):
            frames = ["◇", "◆", "◈", "◆"]
            icon = frames[self._animation_tick % len(frames)]

        text.append(f"{icon} ", style=f"bold {color}")
        text.append(label, style=color)

        text.append("  │  ", style=COLORS.text_ghost)

        # Approval mode
        mode_styles = {
            "auto": ("●", "AUTO", COLORS.success),
            "ask": ("●", "ASK", COLORS.warning),
            "deny": ("●", "DENY", COLORS.error),
        }
        m_icon, m_label, m_color = mode_styles.get(self.approval_mode, ("●", "ASK", COLORS.warning))
        text.append(f"{m_icon} ", style=m_color)
        text.append(m_label, style=f"bold {m_color}")

        # Stats
        if self._stats.tool_count > 0 or self._stats.message_count > 0:
            text.append("  │  ", style=COLORS.text_ghost)
            text.append(f"{self._stats.message_count} msgs", style=COLORS.text_dim)
            if self._stats.tool_count > 0:
                text.append(f" · {self._stats.tool_count} tools", style=COLORS.text_dim)

        # Tokens/cost
        total_tokens = self._stats.prompt_tokens + self._stats.completion_tokens
        if total_tokens > 0:
            text.append("  │  ", style=COLORS.text_ghost)
            text.append(f"{total_tokens:,} tokens", style=COLORS.text_dim)
            if self._stats.total_cost > 0:
                text.append(f" · ${self._stats.total_cost:.4f}", style=COLORS.text_dim)

        return text


# ============================================================================
# ENHANCED TOOL PANEL
# ============================================================================


class EnhancedToolPanel(Container):
    """
    Enhanced tool panel showing tool calls with minimal, clean styling.

    SuperQode style: Left-border indicators, compact layout.
    """

    DEFAULT_CSS = """
    EnhancedToolPanel {
        height: auto;
        max-height: 30%;
        background: #050505;
        border-bottom: solid #1a1a1a;
        padding: 0 1;
    }

    EnhancedToolPanel.collapsed {
        max-height: 1;
        overflow: hidden;
    }

    EnhancedToolPanel .tool-header {
        height: 1;
        color: #71717a;
    }

    EnhancedToolPanel .tool-list {
        height: auto;
        max-height: 100%;
    }
    """

    collapsed: reactive[bool] = reactive(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tools: Dict[str, ToolCallInfo] = {}
        self._tool_order: List[str] = []

    def compose(self):
        """Compose the tool panel."""
        yield Static(self._render_header(), id="tool-header", classes="tool-header")
        yield Static("", id="tool-list", classes="tool-list")

    def _render_header(self) -> Text:
        """Render the header."""
        text = Text()
        icon = "▾" if not self.collapsed else "▸"
        text.append(f"{icon} ", style=COLORS.text_dim)
        text.append("Tools", style=COLORS.text_muted)

        running = sum(1 for t in self._tools.values() if t.status == ToolStatus.RUNNING)
        if running > 0:
            text.append(f"  ({running} running)", style=f"bold {COLORS.warning}")
        elif len(self._tools) > 0:
            text.append(f"  ({len(self._tools)} total)", style=COLORS.text_dim)

        return text

    def _render_tools(self) -> Text:
        """Render the tool list."""
        if self.collapsed:
            return Text()

        text = Text()

        # Show last 5 tools
        for tool_id in self._tool_order[-5:]:
            tool = self._tools.get(tool_id)
            if not tool:
                continue

            # Status icon and color
            status_map = {
                ToolStatus.PENDING: ("○", COLORS.text_dim),
                ToolStatus.RUNNING: ("◐", COLORS.primary_light),
                ToolStatus.SUCCESS: ("✦", COLORS.success),
                ToolStatus.ERROR: ("✕", COLORS.error),
            }
            icon, color = status_map.get(tool.status, ("•", COLORS.text_dim))

            # Tool kind icon
            kind_icons = {
                "read": "↳",
                "write": "↲",
                "edit": "⟳",
                "shell": "▸",
                "search": "⌕",
                "glob": "⋮",
            }
            kind_icon = kind_icons.get(tool.kind.lower(), "•")

            text.append(f"  {icon} ", style=f"bold {color}")
            text.append(f"{kind_icon} ", style=COLORS.text_dim)
            text.append(tool.name, style=COLORS.text_secondary)

            if tool.file_path:
                text.append(f"  {tool.file_path}", style=COLORS.text_ghost)

            # Duration for completed tools
            if (
                tool.status in (ToolStatus.SUCCESS, ToolStatus.ERROR)
                and tool.end_time
                and tool.start_time
            ):
                duration = (tool.end_time - tool.start_time).total_seconds()
                text.append(f"  ({duration:.1f}s)", style=COLORS.text_ghost)

            text.append("\n")

        return text

    def add_tool(
        self, tool_id: str, name: str, kind: str = "other", arguments: Dict[str, Any] = None
    ) -> None:
        """Add a new tool call."""
        file_path = ""
        if arguments:
            file_path = arguments.get(
                "path", arguments.get("file_path", arguments.get("filePath", ""))
            )

        tool = ToolCallInfo(
            id=tool_id,
            name=name,
            kind=kind,
            status=ToolStatus.RUNNING,
            start_time=datetime.now(),
            arguments=arguments or {},
            file_path=file_path,
        )

        self._tools[tool_id] = tool
        if tool_id not in self._tool_order:
            self._tool_order.append(tool_id)

        # Auto-expand when tools are running
        self.collapsed = False
        self._refresh()

    def complete_tool(self, tool_id: str, result: str = "", error: str = "") -> None:
        """Mark a tool as complete."""
        tool = self._tools.get(tool_id)
        if tool:
            tool.end_time = datetime.now()
            tool.status = ToolStatus.ERROR if error else ToolStatus.SUCCESS
            tool.result = result
            tool.error = error
            self._refresh()

    def clear(self) -> None:
        """Clear all tools."""
        self._tools.clear()
        self._tool_order.clear()
        self._refresh()

    def _refresh(self) -> None:
        """Refresh the display."""
        try:
            self.query_one("#tool-header", Static).update(self._render_header())
            self.query_one("#tool-list", Static).update(self._render_tools())
        except Exception:
            pass


# ============================================================================
# ENHANCED THINKING BAR
# ============================================================================


class EnhancedThinkingBar(Static):
    """
    Enhanced thinking indicator with subtle animation.

    SuperQode style: Minimal, one-line, quantum-inspired animation.
    """

    DEFAULT_CSS = """
    EnhancedThinkingBar {
        height: 1;
        background: #050505;
        padding: 0 1;
        display: none;
    }

    EnhancedThinkingBar.visible {
        display: block;
    }
    """

    visible: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._text = ""
        self._tick = 0
        self._timer: Optional[Timer] = None

    def watch_visible(self, visible: bool) -> None:
        """Handle visibility change."""
        if visible:
            self.add_class("visible")
            self._timer = self.set_interval(0.15, self._animate)
        else:
            self.remove_class("visible")
            if self._timer:
                self._timer.stop()
                self._timer = None

    def _animate(self) -> None:
        """Animation tick."""
        self._tick += 1
        self.refresh()

    def set_text(self, text: str) -> None:
        """Set the thinking text."""
        self._text = text
        self.refresh()

    def render(self) -> Text:
        """Render the thinking bar."""
        result = Text()

        # Animated quantum dots
        frames = [
            "◇ ◇ ◇",
            "◆ ◇ ◇",
            "◇ ◆ ◇",
            "◇ ◇ ◆",
            "◇ ◆ ◇",
            "◆ ◇ ◇",
        ]
        frame = frames[self._tick % len(frames)]

        # Color cycling
        colors = GRADIENT_PURPLE
        color = colors[self._tick % len(colors)]

        result.append(f"{frame} ", style=f"bold {color}")

        # Thinking text
        display_text = self._text or "Processing..."
        if len(display_text) > 60:
            display_text = display_text[:57] + "..."

        result.append(display_text, style=f"italic {COLORS.text_muted}")

        return result


# ============================================================================
# DISPLAY HELPER FUNCTIONS
# ============================================================================


def show_agent_header(
    name: str,
    model: str,
    approval_mode: str = "ask",
) -> Text:
    """
    Create a SuperQode-style agent header.

    Clean, minimal, informative.
    """
    text = Text()
    text.append("\n")

    # Gradient line
    line = "─" * 60
    for i, char in enumerate(line):
        color = GRADIENT_PURPLE[i % len(GRADIENT_PURPLE)]
        text.append(char, style=color)
    text.append("\n")

    # Agent name
    text.append("  ◈ ", style=f"bold {COLORS.primary}")
    text.append(name.upper(), style=f"bold {COLORS.text_primary}")
    text.append(" is working\n", style=COLORS.text_muted)

    # Model
    text.append("  Model: ", style=COLORS.text_dim)
    text.append(model, style=f"bold {COLORS.info}")

    # Approval mode
    mode_styles = {
        "auto": (COLORS.success, "AUTO"),
        "ask": (COLORS.warning, "ASK"),
        "deny": (COLORS.error, "DENY"),
    }
    color, label = mode_styles.get(approval_mode, (COLORS.warning, "ASK"))
    text.append("  │  ", style=COLORS.text_ghost)
    text.append(f"● {label}", style=f"bold {color}")

    text.append("\n")

    return text


def show_tool_call(
    name: str,
    kind: str,
    arguments: Dict[str, Any] = None,
    status: str = "running",
) -> Text:
    """
    Create a SuperQode-style tool call display.

    Minimal, left-border indicator, clean.
    """
    text = Text()

    # Status icon
    status_map = {
        "pending": ("○", COLORS.text_dim),
        "running": ("◐", COLORS.primary_light),
        "success": ("✦", COLORS.success),
        "error": ("✕", COLORS.error),
    }
    icon, color = status_map.get(status, ("•", COLORS.text_dim))

    # Kind icon
    kind_icons = {
        "read": "↳",
        "write": "↲",
        "edit": "⟳",
        "shell": "▸",
        "search": "⌕",
        "glob": "⋮",
    }
    kind_icon = kind_icons.get(kind.lower(), "•")

    text.append(f"  {icon} ", style=f"bold {color}")
    text.append(f"{kind_icon} ", style=COLORS.text_dim)
    text.append(name, style=COLORS.text_secondary)

    # File path if present
    if arguments:
        path = arguments.get("path", arguments.get("file_path", arguments.get("filePath", "")))
        if path:
            text.append(f"  {path}", style=COLORS.text_ghost)

        # Command for shell
        cmd = arguments.get("command", "")
        if cmd:
            cmd_short = cmd[:40] + "..." if len(cmd) > 40 else cmd
            text.append(f"  $ {cmd_short}", style=COLORS.text_ghost)

    text.append("\n")
    return text


def show_thinking(text: str, tick: int = 0) -> Text:
    """
    Create a SuperQode-style thinking line.

    Animated quantum dots, minimal.
    """
    result = Text()

    # Animated prefix
    frames = ["◇", "◆", "◈", "◆"]
    frame = frames[tick % len(frames)]
    color = GRADIENT_PURPLE[tick % len(GRADIENT_PURPLE)]

    result.append(f"  {frame} ", style=f"bold {color}")

    # Text
    display = text[:70] + "..." if len(text) > 70 else text
    result.append(display, style=f"italic {COLORS.text_muted}")
    result.append("\n")

    return result


def show_response(
    content: str,
    agent_name: str = "",
    duration: float = 0,
    token_count: int = 0,
    tool_count: int = 0,
    files_modified: List[str] = None,
) -> Group:
    """
    Create a SuperQode-style response display.

    Clean header, markdown content, stats footer.
    """
    items = []

    # Success header
    header = Text()
    header.append("\n")

    # Gradient line
    line = "─" * 60
    for i, char in enumerate(line):
        color = ["#10b981", "#14b8a6", "#06b6d4", "#0ea5e9"][i % 4]
        header.append(char, style=color)
    header.append("\n")

    # Agent name with checkmark
    header.append("  ✦ ", style=f"bold {COLORS.success}")
    if agent_name:
        header.append(agent_name, style=f"bold {COLORS.text_primary}")
        header.append(" completed", style=COLORS.text_muted)
    else:
        header.append("Task completed", style=f"bold {COLORS.text_primary}")
    header.append("\n")

    items.append(header)

    # Stats line
    stats = Text()
    stats.append("  ")

    if duration > 0:
        stats.append(f"⏱ {duration:.1f}s", style=COLORS.text_dim)

    if tool_count > 0:
        stats.append(f"  │  🔧 {tool_count} tools", style=COLORS.text_dim)

    if files_modified:
        stats.append(f"  │  📝 {len(files_modified)} files", style=COLORS.text_dim)

    if token_count > 0:
        stats.append(f"  │  📊 {token_count} tokens", style=COLORS.text_dim)

    stats.append("\n\n")
    items.append(stats)

    # Content
    if content.strip():
        # Try to render as markdown
        try:
            md = Markdown(content)
            items.append(md)
        except Exception:
            items.append(Text(content, style=COLORS.text_secondary))

    # Footer line
    footer = Text()
    footer.append("\n")
    for i, char in enumerate("─" * 60):
        footer.append(char, style=COLORS.text_ghost)
    footer.append("\n")
    items.append(footer)

    return Group(*items)


def show_completion_summary(
    agent_name: str,
    duration: float,
    tool_count: int,
    files_modified: List[str] = None,
    files_read: List[str] = None,
) -> Text:
    """
    Show a brief completion summary when there's no text response.
    """
    text = Text()
    text.append("\n")

    # Success line
    for i, char in enumerate("─" * 40):
        color = ["#10b981", "#14b8a6", "#06b6d4"][i % 3]
        text.append(char, style=color)
    text.append("\n")

    text.append("  ✦ ", style=f"bold {COLORS.success}")
    text.append(f"{agent_name} ", style=f"bold {COLORS.text_primary}")
    text.append("finished", style=COLORS.text_muted)

    # Stats
    stats = []
    if duration > 0:
        stats.append(f"{duration:.1f}s")
    if tool_count > 0:
        stats.append(f"{tool_count} tools")
    if files_modified:
        stats.append(f"{len(files_modified)} files modified")

    if stats:
        text.append(f"  ({', '.join(stats)})", style=COLORS.text_dim)

    text.append("\n")

    # File list if any
    if files_modified:
        text.append("\n  📝 Modified:\n", style=COLORS.text_muted)
        for f in files_modified[:5]:
            text.append(f"     {f}\n", style=COLORS.text_dim)
        if len(files_modified) > 5:
            text.append(f"     ... and {len(files_modified) - 5} more\n", style=COLORS.text_ghost)

    return text


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Enums
    "ToolStatus",
    "AgentState",
    # Data classes
    "ToolCallInfo",
    "SessionStats",
    # Widgets
    "EnhancedStatusHeader",
    "EnhancedToolPanel",
    "EnhancedThinkingBar",
    # Functions
    "show_agent_header",
    "show_tool_call",
    "show_thinking",
    "show_response",
    "show_completion_summary",
]
