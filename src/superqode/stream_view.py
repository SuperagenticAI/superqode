"""
SuperQode Stream View - Real-time Agent Output Display

Colorful widgets for displaying streaming agent output including:
- Message chunks (agent responses)
- Thinking/reasoning
- Tool calls with status
- Plans with task tracking
- Permission requests
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from time import monotonic

from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Static, RichLog, Button
from textual.reactive import reactive
from textual.message import Message

from rich.text import Text
from rich.panel import Panel
from rich.box import ROUNDED
from rich.syntax import Syntax

from superqode.agent_stream import (
    StreamEvent,
    StreamEventType,
    StreamMessage,
    StreamThought,
    StreamToolCall,
    StreamPlan,
    StreamPermission,
    PlanTask,
    ToolKind,
    ToolStatus,
    TaskStatus,
    TaskPriority,
    get_tool_icon,
    get_status_icon,
    get_status_color,
    get_task_icon,
    get_task_color,
    STREAM_COLORS,
    STREAM_ICONS,
)


# ============================================================================
# THEME
# ============================================================================

THEME = {
    "bg": "#0a0a0a",
    "surface": "#111111",
    "border": "#2a2a2a",
    "purple": "#a855f7",
    "pink": "#ec4899",
    "orange": "#f97316",
    "cyan": "#06b6d4",
    "green": "#22c55e",
    "red": "#ef4444",
    "yellow": "#fbbf24",
    "text": "#e4e4e7",
    "muted": "#71717a",
    "dim": "#52525b",
}


# ============================================================================
# STREAMING MESSAGE WIDGET
# ============================================================================


class StreamingMessage(Static):
    """Widget that displays streaming text with typing effect."""

    text_content = reactive("")
    is_complete = reactive(False)

    def __init__(self, agent_name: str = "Agent", **kwargs):
        super().__init__(**kwargs)
        self.agent_name = agent_name
        self._buffer = ""

    def append_text(self, text: str):
        """Append text to the message."""
        self._buffer += text
        self.text_content = self._buffer

    def mark_complete(self):
        """Mark the message as complete."""
        self.is_complete = True

    def render(self) -> Text:
        result = Text()

        # Header with agent name
        color = STREAM_COLORS["message"]
        result.append(f"💬 {self.agent_name}", style=f"bold {color}")

        if not self.is_complete:
            result.append(" ●", style=f"bold {STREAM_COLORS['progress']}")

        result.append("\n", style="")

        # Message content
        if self.text_content:
            result.append(self.text_content, style=THEME["text"])
        else:
            result.append("...", style=f"italic {THEME['muted']}")

        return result


class ThinkingBubble(Static):
    """Widget that displays agent's thinking process."""

    thought = reactive("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._thoughts: List[str] = []

    def add_thought(self, text: str):
        """Add a thought."""
        self._thoughts.append(text)
        self.thought = text

    def render(self) -> Text:
        result = Text()

        color = STREAM_COLORS["thought"]
        result.append(f"💭 ", style=f"bold {color}")
        result.append("Thinking", style=f"italic {color}")
        result.append("\n", style="")

        # Show last few thoughts
        for thought in self._thoughts[-3:]:
            thought_short = thought[:100] + "..." if len(thought) > 100 else thought
            result.append(f"  • {thought_short}\n", style=f"italic {THEME['muted']}")

        return result


# ============================================================================
# TOOL CALL WIDGET
# ============================================================================


class ToolCallWidget(Static):
    """Widget displaying a tool call with status and content."""

    status = reactive(ToolStatus.PENDING)

    def __init__(self, tool_call: StreamToolCall, **kwargs):
        super().__init__(**kwargs)
        self.tool_call = tool_call

    def update_tool(self, tool_call: StreamToolCall):
        """Update the tool call data."""
        self.tool_call = tool_call
        self.status = tool_call.status

    def render(self) -> Text:
        result = Text()
        tc = self.tool_call

        # Status icon and color
        status_icon = get_status_icon(tc.status)
        status_color = get_status_color(tc.status)
        tool_icon = get_tool_icon(tc.kind)

        # Header line
        result.append(f"{status_icon} ", style=status_color)
        result.append(f"{tool_icon} ", style=STREAM_COLORS["tool"])
        result.append(tc.title, style=f"bold {status_color}")

        # Location info
        if tc.locations:
            loc = tc.locations[0]
            path = loc.get("path", "")
            line = loc.get("line")
            if path:
                result.append(f"  📍 {path}", style=THEME["muted"])
                if line:
                    result.append(f":{line}", style=THEME["dim"])

        result.append("\n", style="")

        # Content preview
        for content in tc.content[:2]:  # Show first 2 content items
            if content.type == "diff":
                data = content.data
                path = data.get("path", "")
                old_text = data.get("oldText", "")
                new_text = data.get("newText", "")

                result.append(f"  📄 {path}\n", style=THEME["cyan"])

                # Show diff preview
                if old_text:
                    old_lines = old_text.split("\n")[:3]
                    for line in old_lines:
                        result.append(f"  - {line[:60]}\n", style=f"on #2d1f1f {THEME['red']}")
                if new_text:
                    new_lines = new_text.split("\n")[:3]
                    for line in new_lines:
                        result.append(f"  + {line[:60]}\n", style=f"on #1f2d1f {THEME['green']}")

            elif content.type == "terminal":
                terminal_id = content.data.get("terminalId", "")
                result.append(f"  🖥️ Terminal: {terminal_id}\n", style=THEME["muted"])

            elif content.type == "content":
                text = content.data.get("text", "")
                if text:
                    preview = text[:100] + "..." if len(text) > 100 else text
                    result.append(f"  {preview}\n", style=THEME["dim"])

        return result


# ============================================================================
# PLAN WIDGET
# ============================================================================


class PlanWidget(Static):
    """Widget displaying agent's plan with task status."""

    def __init__(self, plan: StreamPlan, **kwargs):
        super().__init__(**kwargs)
        self.plan = plan

    def update_plan(self, plan: StreamPlan):
        """Update the plan."""
        self.plan = plan
        self.refresh()

    def render(self) -> Text:
        result = Text()

        # Header
        result.append(f"📋 ", style=f"bold {STREAM_COLORS['plan']}")
        result.append("Plan", style=f"bold {STREAM_COLORS['plan']}")

        # Progress
        completed = sum(1 for t in self.plan.tasks if t.status == TaskStatus.COMPLETED)
        total = len(self.plan.tasks)
        if total > 0:
            result.append(f"  ({completed}/{total})", style=THEME["muted"])

        result.append("\n", style="")

        # Tasks
        for i, task in enumerate(self.plan.tasks, 1):
            icon = get_task_icon(task.status)
            color = get_task_color(task.status)

            # Priority indicator
            priority_icon = ""
            if task.priority == TaskPriority.HIGH:
                priority_icon = "🔴 "
            elif task.priority == TaskPriority.LOW:
                priority_icon = "🔵 "

            result.append(f"  {icon} ", style=color)
            result.append(f"{priority_icon}", style="")
            result.append(f"{i}. ", style=THEME["muted"])

            # Strike through completed tasks
            if task.status == TaskStatus.COMPLETED:
                result.append(task.content, style=f"strike {THEME['dim']}")
            else:
                result.append(
                    task.content,
                    style=color if task.status == TaskStatus.IN_PROGRESS else THEME["text"],
                )

            result.append("\n", style="")

        return result


# ============================================================================
# PERMISSION REQUEST WIDGET
# ============================================================================


class PermissionRequest(Message):
    """Message sent when user responds to permission request."""

    def __init__(self, option_id: str):
        self.option_id = option_id
        super().__init__()


class PermissionWidget(Static):
    """Widget for permission requests with action buttons."""

    DEFAULT_CSS = """
    PermissionWidget {
        height: auto;
        padding: 1;
        background: #1a1a1a;
        border: round #f97316;
    }

    PermissionWidget .permission-buttons {
        height: auto;
        margin-top: 1;
    }

    PermissionWidget Button {
        margin-right: 1;
    }

    PermissionWidget Button.allow {
        background: #22c55e;
    }

    PermissionWidget Button.reject {
        background: #ef4444;
    }
    """

    def __init__(self, permission: StreamPermission, **kwargs):
        super().__init__(**kwargs)
        self.permission = permission

    def compose(self) -> ComposeResult:
        yield Static(self._render_header(), id="permission-header")
        yield Static(self._render_tool_info(), id="permission-tool")

        with Horizontal(classes="permission-buttons"):
            for option in self.permission.options:
                btn_class = "allow" if "allow" in option.kind else "reject"
                yield Button(
                    option.name,
                    id=f"perm-{option.option_id}",
                    classes=btn_class,
                )

    def _render_header(self) -> Text:
        result = Text()
        result.append("🔐 ", style=f"bold {STREAM_COLORS['warning']}")
        result.append("Permission Required", style=f"bold {STREAM_COLORS['warning']}")
        return result

    def _render_tool_info(self) -> Text:
        result = Text()
        tc = self.permission.tool_call

        tool_icon = get_tool_icon(tc.kind)
        result.append(f"\n{tool_icon} ", style=STREAM_COLORS["tool"])
        result.append(tc.title, style=f"bold {THEME['text']}")

        if tc.locations:
            loc = tc.locations[0]
            path = loc.get("path", "")
            if path:
                result.append(f"\n📍 {path}", style=THEME["muted"])

        return result

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        button_id = event.button.id or ""
        if button_id.startswith("perm-"):
            option_id = button_id[5:]  # Remove "perm-" prefix

            # Resolve the future
            if self.permission.result_future and not self.permission.result_future.done():
                self.permission.result_future.set_result(option_id)

            # Post message
            self.post_message(PermissionRequest(option_id))

            # Remove widget
            self.remove()


# ============================================================================
# STREAM VIEW CONTAINER
# ============================================================================


class StreamView(Container):
    """
    Container for displaying streaming agent output.

    Manages multiple streaming widgets and updates them in real-time.
    """

    DEFAULT_CSS = """
    StreamView {
        height: auto;
        padding: 0 1;
    }

    StreamView .stream-message {
        margin-bottom: 1;
    }

    StreamView .stream-thinking {
        margin-bottom: 1;
        padding: 0 1;
        background: #1a1a1a;
        border-left: tall #ec4899;
    }

    StreamView .stream-tool {
        margin-bottom: 1;
        padding: 0 1;
        background: #1a1a1a;
        border-left: tall #f97316;
    }

    StreamView .stream-plan {
        margin-bottom: 1;
        padding: 0 1;
        background: #1a1a1a;
        border-left: tall #06b6d4;
    }
    """

    def __init__(self, agent_name: str = "Agent", **kwargs):
        super().__init__(**kwargs)
        self.agent_name = agent_name
        self._current_message: Optional[StreamingMessage] = None
        self._thinking: Optional[ThinkingBubble] = None
        self._plan: Optional[PlanWidget] = None
        self._tool_widgets: Dict[str, ToolCallWidget] = {}

    def handle_event(self, event: StreamEvent):
        """Handle a streaming event."""
        if event.event_type == StreamEventType.MESSAGE_CHUNK:
            self._handle_message(event.data)
        elif event.event_type == StreamEventType.THOUGHT_CHUNK:
            self._handle_thought(event.data)
        elif event.event_type == StreamEventType.TOOL_CALL:
            self._handle_tool_call(event.data)
        elif event.event_type == StreamEventType.TOOL_UPDATE:
            self._handle_tool_update(event.data)
        elif event.event_type == StreamEventType.PLAN:
            self._handle_plan(event.data)
        elif event.event_type == StreamEventType.PERMISSION:
            self._handle_permission(event.data)
        elif event.event_type == StreamEventType.ERROR:
            self._handle_error(event.data)
        elif event.event_type == StreamEventType.COMPLETE:
            self._handle_complete()

    def _handle_message(self, msg: StreamMessage):
        """Handle message chunk."""
        if msg.is_complete:
            if self._current_message:
                self._current_message.mark_complete()
                self._current_message = None
            return

        if not self._current_message:
            self._current_message = StreamingMessage(
                agent_name=self.agent_name, classes="stream-message"
            )
            self.mount(self._current_message)

        self._current_message.append_text(msg.text)

    def _handle_thought(self, thought: StreamThought):
        """Handle thought chunk."""
        if not self._thinking:
            self._thinking = ThinkingBubble(classes="stream-thinking")
            self.mount(self._thinking)

        self._thinking.add_thought(thought.text)

    def _handle_tool_call(self, tool_call: StreamToolCall):
        """Handle new tool call."""
        widget = ToolCallWidget(tool_call, classes="stream-tool")
        self._tool_widgets[tool_call.tool_id] = widget
        self.mount(widget)

    def _handle_tool_update(self, tool_call: StreamToolCall):
        """Handle tool call update."""
        if tool_call.tool_id in self._tool_widgets:
            self._tool_widgets[tool_call.tool_id].update_tool(tool_call)

    def _handle_plan(self, plan: StreamPlan):
        """Handle plan update."""
        if not self._plan:
            self._plan = PlanWidget(plan, classes="stream-plan")
            self.mount(self._plan)
        else:
            self._plan.update_plan(plan)

    def _handle_permission(self, permission: StreamPermission):
        """Handle permission request."""
        widget = PermissionWidget(permission)
        self.mount(widget)

    def _handle_error(self, error: str):
        """Handle error."""
        error_widget = Static(
            Text(f"❌ {error}", style=STREAM_COLORS["error"]), classes="stream-error"
        )
        self.mount(error_widget)

    def _handle_complete(self):
        """Handle completion."""
        # Clear thinking bubble
        if self._thinking:
            self._thinking.remove()
            self._thinking = None

        # Mark message complete
        if self._current_message:
            self._current_message.mark_complete()
            self._current_message = None

    def clear(self):
        """Clear all streaming content."""
        self._current_message = None
        self._thinking = None
        self._plan = None
        self._tool_widgets.clear()
        self.remove_children()


# ============================================================================
# STREAMING STATUS BAR
# ============================================================================


class StreamStatusBar(Static):
    """Status bar showing streaming progress with colorful indicators."""

    DEFAULT_CSS = """
    StreamStatusBar {
        height: 1;
        background: #111111;
        padding: 0 1;
    }
    """

    status = reactive("idle")
    agent_name = reactive("Agent")
    tool_count = reactive(0)
    message_length = reactive(0)

    def render(self) -> Text:
        result = Text()

        # Agent indicator
        result.append(f"🤖 {self.agent_name}", style=f"bold {STREAM_COLORS['message']}")
        result.append("  │  ", style=THEME["dim"])

        # Status with color
        status_styles = {
            "idle": ("○", THEME["muted"]),
            "connecting": ("◌", STREAM_COLORS["warning"]),
            "streaming": ("●", STREAM_COLORS["success"]),
            "thinking": ("◐", STREAM_COLORS["thought"]),
            "tool": ("◑", STREAM_COLORS["tool"]),
            "complete": ("✓", STREAM_COLORS["success"]),
            "error": ("✗", STREAM_COLORS["error"]),
        }
        icon, color = status_styles.get(self.status, ("○", THEME["muted"]))
        result.append(f"{icon} ", style=color)
        result.append(self.status.title(), style=color)

        # Stats
        if self.tool_count > 0:
            result.append("  │  ", style=THEME["dim"])
            result.append(f"🔧 {self.tool_count}", style=STREAM_COLORS["tool"])

        if self.message_length > 0:
            result.append("  │  ", style=THEME["dim"])
            result.append(f"💬 {self.message_length} chars", style=THEME["muted"])

        return result


# ============================================================================
# COLORFUL DIFF PREVIEW
# ============================================================================


class StreamDiffPreview(Static):
    """Colorful diff preview for file changes."""

    DEFAULT_CSS = """
    StreamDiffPreview {
        height: auto;
        padding: 1;
        background: #0d0d0d;
        border: round #2a2a2a;
        margin: 1 0;
    }
    """

    def __init__(self, path: str, old_text: str, new_text: str, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.old_text = old_text
        self.new_text = new_text

    def render(self) -> Text:
        result = Text()

        # Header
        result.append("📄 ", style=f"bold {THEME['cyan']}")
        result.append(self.path, style=f"bold {THEME['cyan']}")
        result.append("\n", style="")

        # Calculate stats
        old_lines = self.old_text.split("\n") if self.old_text else []
        new_lines = self.new_text.split("\n") if self.new_text else []

        result.append(f"  ", style="")
        result.append(f"+{len(new_lines)}", style=f"bold {THEME['green']}")
        result.append(" / ", style=THEME["muted"])
        result.append(f"-{len(old_lines)}", style=f"bold {THEME['red']}")
        result.append(" lines\n\n", style=THEME["muted"])

        # Show diff preview (first few lines)
        for line in old_lines[:3]:
            line_preview = line[:60] + "..." if len(line) > 60 else line
            result.append(f"  - {line_preview}\n", style=f"on #2d1f1f {THEME['red']}")

        if len(old_lines) > 3:
            result.append(f"  ... ({len(old_lines) - 3} more lines)\n", style=THEME["dim"])

        result.append("\n", style="")

        for line in new_lines[:3]:
            line_preview = line[:60] + "..." if len(line) > 60 else line
            result.append(f"  + {line_preview}\n", style=f"on #1f2d1f {THEME['green']}")

        if len(new_lines) > 3:
            result.append(f"  ... ({len(new_lines) - 3} more lines)\n", style=THEME["dim"])

        return result
