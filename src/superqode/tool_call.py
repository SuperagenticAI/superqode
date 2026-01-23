"""
SuperQode Tool Call Display - Agent Tool Execution Visualization

Beautiful display for agent tool calls with:
- Expandable/collapsible content
- Status indicators
- Embedded diffs
- Syntax highlighting
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Any, Dict
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.box import ROUNDED, SIMPLE


class ToolStatus(Enum):
    """Tool call status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolKind(Enum):
    """Type of tool operation."""

    READ = "read"
    WRITE = "write"
    EDIT = "edit"
    SHELL = "shell"
    SEARCH = "search"
    OTHER = "other"


@dataclass
class ToolCallContent:
    """Content from a tool call."""

    content_type: str  # "text", "diff", "code", "markdown"
    data: Any
    language: Optional[str] = None


@dataclass
class ToolCall:
    """A tool call from the agent."""

    id: str
    name: str
    title: str
    kind: ToolKind = ToolKind.OTHER
    status: ToolStatus = ToolStatus.PENDING
    content: List[ToolCallContent] = field(default_factory=list)
    arguments: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expanded: bool = False


# SuperQode tool call colors
TOOL_COLORS = {
    # Status colors
    "pending": "#71717a",
    "in_progress": "#06b6d4",
    "completed": "#22c55e",
    "failed": "#ef4444",
    # Kind colors
    "read": "#3b82f6",
    "write": "#f97316",
    "edit": "#eab308",
    "shell": "#8b5cf6",
    "search": "#06b6d4",
    "other": "#71717a",
    # UI colors
    "header": "#a855f7",
    "border": "#2a2a2a",
    "content_bg": "#111111",
}

# Status icons
STATUS_ICONS = {
    ToolStatus.PENDING: "⏳",
    ToolStatus.IN_PROGRESS: "🔄",
    ToolStatus.COMPLETED: "✅",
    ToolStatus.FAILED: "❌",
}

# Kind icons
KIND_ICONS = {
    ToolKind.READ: "📖",
    ToolKind.WRITE: "✏️",
    ToolKind.EDIT: "📝",
    ToolKind.SHELL: "💻",
    ToolKind.SEARCH: "🔍",
    ToolKind.OTHER: "🔧",
}


class ToolCallManager:
    """Manages tool call display and tracking."""

    def __init__(self):
        self.calls: List[ToolCall] = []
        self.auto_expand: str = "both"  # "always", "never", "success", "fail", "both"
        self._call_counter = 0

    def _generate_id(self) -> str:
        """Generate a unique tool call ID."""
        self._call_counter += 1
        return f"tool_{self._call_counter}"

    def add_call(
        self,
        name: str,
        title: str,
        kind: ToolKind = ToolKind.OTHER,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> ToolCall:
        """Add a new tool call."""
        call = ToolCall(
            id=self._generate_id(),
            name=name,
            title=title,
            kind=kind,
            arguments=arguments or {},
            started_at=datetime.now(),
        )
        self.calls.append(call)
        return call

    def update_status(self, call_id: str, status: ToolStatus) -> bool:
        """Update a tool call's status."""
        for call in self.calls:
            if call.id == call_id:
                call.status = status
                if status in (ToolStatus.COMPLETED, ToolStatus.FAILED):
                    call.completed_at = datetime.now()
                    # Auto-expand based on settings
                    call.expanded = self._should_expand(call)
                return True
        return False

    def _should_expand(self, call: ToolCall) -> bool:
        """Determine if a call should auto-expand."""
        if self.auto_expand == "always":
            return True
        if self.auto_expand == "never":
            return False
        if self.auto_expand == "success":
            return call.status == ToolStatus.COMPLETED
        if self.auto_expand == "fail":
            return call.status == ToolStatus.FAILED
        if self.auto_expand == "both":
            return call.status in (ToolStatus.COMPLETED, ToolStatus.FAILED)
        return False

    def add_content(
        self, call_id: str, content_type: str, data: Any, language: Optional[str] = None
    ) -> bool:
        """Add content to a tool call."""
        for call in self.calls:
            if call.id == call_id:
                call.content.append(
                    ToolCallContent(content_type=content_type, data=data, language=language)
                )
                return True
        return False

    def complete(self, call_id: str, result: Optional[str] = None) -> bool:
        """Mark a tool call as completed."""
        for call in self.calls:
            if call.id == call_id:
                call.status = ToolStatus.COMPLETED
                call.result = result
                call.completed_at = datetime.now()
                call.expanded = self._should_expand(call)
                return True
        return False

    def fail(self, call_id: str, error: str) -> bool:
        """Mark a tool call as failed."""
        for call in self.calls:
            if call.id == call_id:
                call.status = ToolStatus.FAILED
                call.error = error
                call.completed_at = datetime.now()
                call.expanded = self._should_expand(call)
                return True
        return False

    def toggle_expand(self, call_id: str) -> bool:
        """Toggle expansion state of a tool call."""
        for call in self.calls:
            if call.id == call_id:
                call.expanded = not call.expanded
                return True
        return False

    def get_recent(self, count: int = 10) -> List[ToolCall]:
        """Get the most recent tool calls."""
        return self.calls[-count:]

    def clear(self) -> None:
        """Clear all tool calls."""
        self.calls.clear()
        self._call_counter = 0


def render_tool_call(call: ToolCall, console: Console, show_content: bool = True) -> None:
    """Render a single tool call."""
    status_icon = STATUS_ICONS.get(call.status, "🔧")
    kind_icon = KIND_ICONS.get(call.kind, "🔧")
    status_color = TOOL_COLORS.get(call.status.value, TOOL_COLORS["pending"])
    kind_color = TOOL_COLORS.get(call.kind.value, TOOL_COLORS["other"])

    # Header line
    header = Text()

    # Expand indicator
    if call.content:
        expand_icon = "▼" if call.expanded else "▶"
        header.append(f"{expand_icon} ", style="dim")
    else:
        header.append("  ", style="")

    # Kind icon and title
    header.append(f"{kind_icon} ", style=kind_color)
    header.append(call.title, style=f"bold {status_color}")

    # Status indicator
    header.append("  ", style="")
    if call.status == ToolStatus.PENDING:
        header.append("⏳", style=status_color)
    elif call.status == ToolStatus.IN_PROGRESS:
        header.append("🔄", style=status_color)
    elif call.status == ToolStatus.COMPLETED:
        header.append("✔", style=status_color)
    elif call.status == ToolStatus.FAILED:
        header.append("✗", style=status_color)

    # Duration
    if call.completed_at and call.started_at:
        duration = (call.completed_at - call.started_at).total_seconds()
        header.append(f" ({duration:.2f}s)", style="dim")

    console.print(header)

    # Content (if expanded)
    if show_content and call.expanded and call.content:
        render_tool_content(call, console)

    # Error message
    if call.error:
        console.print(f"    [red]Error: {call.error}[/red]")


def render_tool_content(call: ToolCall, console: Console) -> None:
    """Render the content of a tool call."""
    for content in call.content:
        if content.content_type == "text":
            # Plain text
            text = str(content.data)
            if len(text) > 500:
                text = text[:500] + "..."
            console.print(f"    [dim]{text}[/dim]")

        elif content.content_type == "code":
            # Syntax highlighted code
            lang = content.language or "text"
            syntax = Syntax(
                str(content.data),
                lang,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
                background_color="#000000",
            )
            console.print(
                Panel(syntax, border_style=TOOL_COLORS["border"], box=SIMPLE, padding=(0, 1))
            )

        elif content.content_type == "diff":
            # Diff display
            from superqode.diff_view import compute_diff, render_diff_unified

            if isinstance(content.data, dict):
                diff = compute_diff(
                    content.data.get("old", ""),
                    content.data.get("new", ""),
                    content.data.get("path", "file"),
                )
                render_diff_unified(diff, console)

        elif content.content_type == "markdown":
            # Markdown content
            md = Markdown(str(content.data))
            console.print(Panel(md, border_style=TOOL_COLORS["border"], box=SIMPLE, padding=(0, 1)))


def render_tool_calls(manager: ToolCallManager, console: Console, limit: int = 10) -> None:
    """Render recent tool calls."""
    calls = manager.get_recent(limit)

    if not calls:
        console.print("  [dim]No tool calls yet[/dim]")
        return

    # Header
    header = Text()
    header.append(" 🔧 ", style="bold")
    header.append("Tool Calls", style="bold white")
    header.append(f" ({len(calls)})", style="dim")

    console.print(Panel(header, border_style=TOOL_COLORS["header"], box=ROUNDED, padding=(0, 1)))

    # Render each call
    for call in calls:
        render_tool_call(call, console)


def render_tool_summary(manager: ToolCallManager, console: Console) -> None:
    """Render a compact summary of tool calls."""
    if not manager.calls:
        return

    completed = sum(1 for c in manager.calls if c.status == ToolStatus.COMPLETED)
    failed = sum(1 for c in manager.calls if c.status == ToolStatus.FAILED)
    pending = sum(
        1 for c in manager.calls if c.status in (ToolStatus.PENDING, ToolStatus.IN_PROGRESS)
    )

    line = Text()
    line.append("🔧 ", style="")
    line.append(f"{completed}", style=f"bold {TOOL_COLORS['completed']}")
    line.append("✔ ", style=TOOL_COLORS["completed"])

    if failed:
        line.append(f"{failed}", style=f"bold {TOOL_COLORS['failed']}")
        line.append("✗ ", style=TOOL_COLORS["failed"])

    if pending:
        line.append(f"{pending}", style=f"bold {TOOL_COLORS['pending']}")
        line.append("⏳", style=TOOL_COLORS["pending"])

    console.print(line)
