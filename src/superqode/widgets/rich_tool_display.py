"""
Rich Tool Display Widget - Beautiful Tool Call Visualization.

Displays tool calls with:
- Collapsible sections
- File diff previews with syntax highlighting
- Progress indicators and animations
- Grouped by type (file, shell, search, etc.)
- Status badges and duration tracking

Uses SuperQode's signature style and design system.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rich.console import RenderableType, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED, SIMPLE
from textual.reactive import reactive
from textual.widgets import Static, Collapsible
from textual.containers import Container, Vertical, Horizontal
from textual.timer import Timer
from textual import events


class ToolKind(Enum):
    """Type of tool operation."""

    FILE_READ = "read"
    FILE_WRITE = "write"
    FILE_EDIT = "edit"
    FILE_DELETE = "delete"
    SHELL = "shell"
    SEARCH = "search"
    GLOB = "glob"
    LSP = "lsp"
    BROWSER = "browser"
    MCP = "mcp"
    OTHER = "other"


class ToolState(Enum):
    """State of a tool call."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


# Tool styling configuration
TOOL_STYLES = {
    ToolKind.FILE_READ: {"icon": "📖", "color": "#3b82f6", "label": "Read"},
    ToolKind.FILE_WRITE: {"icon": "✏️", "color": "#22c55e", "label": "Write"},
    ToolKind.FILE_EDIT: {"icon": "🔧", "color": "#f59e0b", "label": "Edit"},
    ToolKind.FILE_DELETE: {"icon": "🗑️", "color": "#ef4444", "label": "Delete"},
    ToolKind.SHELL: {"icon": "💻", "color": "#8b5cf6", "label": "Shell"},
    ToolKind.SEARCH: {"icon": "🔍", "color": "#06b6d4", "label": "Search"},
    ToolKind.GLOB: {"icon": "📁", "color": "#14b8a6", "label": "Glob"},
    ToolKind.LSP: {"icon": "🔬", "color": "#ec4899", "label": "LSP"},
    ToolKind.BROWSER: {"icon": "🌐", "color": "#f97316", "label": "Browser"},
    ToolKind.MCP: {"icon": "🔌", "color": "#a855f7", "label": "MCP"},
    ToolKind.OTHER: {"icon": "⚡", "color": "#71717a", "label": "Tool"},
}

STATE_STYLES = {
    ToolState.PENDING: {"icon": "○", "color": "#71717a", "animate": False},
    ToolState.RUNNING: {"icon": "◐", "color": "#fbbf24", "animate": True},
    ToolState.SUCCESS: {"icon": "✓", "color": "#22c55e", "animate": False},
    ToolState.ERROR: {"icon": "✗", "color": "#ef4444", "animate": False},
    ToolState.CANCELLED: {"icon": "⊘", "color": "#71717a", "animate": False},
}


@dataclass
class DiffContent:
    """Diff content for file operations."""

    path: str
    old_text: str = ""
    new_text: str = ""
    language: str = "text"


@dataclass
class ToolCallData:
    """Data for a tool call."""

    id: str
    name: str
    kind: ToolKind
    state: ToolState = ToolState.PENDING

    # Timing
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # Arguments
    arguments: Dict[str, Any] = field(default_factory=dict)

    # Results
    result: str = ""
    error: str = ""

    # File operations
    file_path: Optional[str] = None
    diff: Optional[DiffContent] = None

    # Shell operations
    command: Optional[str] = None
    exit_code: Optional[int] = None
    output: str = ""

    # Search operations
    matches: List[Dict] = field(default_factory=list)

    @property
    def duration_ms(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None

    @property
    def duration_str(self) -> str:
        ms = self.duration_ms
        if ms is None:
            return "..."
        if ms < 1000:
            return f"{ms:.0f}ms"
        if ms < 60000:
            return f"{ms / 1000:.1f}s"
        return f"{ms / 60000:.1f}m"

    @property
    def display_title(self) -> str:
        """Get display title for the tool call."""
        if self.file_path:
            return Path(self.file_path).name
        if self.command:
            cmd_short = self.command[:40] + "..." if len(self.command) > 40 else self.command
            return cmd_short
        return self.name


def detect_language(path: str) -> str:
    """Detect language from file extension."""
    ext_map = {
        ".py": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".html": "html",
        ".css": "css",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".md": "markdown",
        ".sql": "sql",
        ".sh": "bash",
    }
    ext = Path(path).suffix.lower()
    return ext_map.get(ext, "text")


class SingleToolDisplay(Static):
    """Display widget for a single tool call."""

    DEFAULT_CSS = """
    SingleToolDisplay {
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
    }

    SingleToolDisplay.expanded {
        height: auto;
    }
    """

    expanded: reactive[bool] = reactive(False)

    def __init__(self, tool: ToolCallData, **kwargs):
        super().__init__(**kwargs)
        self.tool = tool
        self._spinner_frame = 0

    def update_tool(self, tool: ToolCallData) -> None:
        """Update tool data."""
        self.tool = tool
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        """Toggle expansion on click."""
        self.expanded = not self.expanded
        self.refresh()

    def _get_spinner(self) -> str:
        """Get animated spinner character."""
        spinners = ["◐", "◓", "◑", "◒"]
        return spinners[self._spinner_frame % len(spinners)]

    def _render_diff(self) -> Text:
        """Render file diff."""
        if not self.tool.diff:
            return Text()

        result = Text()
        diff = self.tool.diff

        old_lines = diff.old_text.splitlines() if diff.old_text else []
        new_lines = diff.new_text.splitlines() if diff.new_text else []

        # Show stats
        result.append("    ")
        if old_lines:
            result.append(f"-{len(old_lines)} ", style="bold #ef4444")
        if new_lines:
            result.append(f"+{len(new_lines)}", style="bold #22c55e")
        result.append(" lines\n\n")

        # Show diff preview (limited)
        max_lines = 8
        shown = 0

        for line in old_lines[: max_lines // 2]:
            line_preview = line[:70] + "..." if len(line) > 70 else line
            result.append(f"    -{line_preview}\n", style="on #2d1f1f #ef4444")
            shown += 1

        if len(old_lines) > max_lines // 2:
            result.append(
                f"    ... {len(old_lines) - max_lines // 2} more removed\n", style="#71717a"
            )

        for line in new_lines[: max_lines // 2]:
            line_preview = line[:70] + "..." if len(line) > 70 else line
            result.append(f"    +{line_preview}\n", style="on #1f2d1f #22c55e")
            shown += 1

        if len(new_lines) > max_lines // 2:
            result.append(
                f"    ... {len(new_lines) - max_lines // 2} more added\n", style="#71717a"
            )

        return result

    def _render_shell_output(self) -> Text:
        """Render shell command output."""
        result = Text()

        if self.tool.command:
            result.append(f"    $ {self.tool.command}\n", style="bold #a1a1aa")

        if self.tool.output:
            lines = self.tool.output.splitlines()[:10]
            for line in lines:
                line_preview = line[:70] + "..." if len(line) > 70 else line
                result.append(f"    {line_preview}\n", style="#6b7280")

            if len(self.tool.output.splitlines()) > 10:
                result.append(
                    f"    ... {len(self.tool.output.splitlines()) - 10} more lines\n",
                    style="#52525b",
                )

        if self.tool.exit_code is not None:
            style = "#22c55e" if self.tool.exit_code == 0 else "#ef4444"
            result.append(f"    Exit: {self.tool.exit_code}\n", style=style)

        return result

    def _render_search_results(self) -> Text:
        """Render search results."""
        result = Text()

        matches = self.tool.matches[:5]
        for match in matches:
            path = match.get("path", "")
            line = match.get("line", "")
            preview = match.get("preview", "")[:50]

            result.append(f"    {path}", style="#3b82f6")
            if line:
                result.append(f":{line}", style="#6b7280")
            result.append("\n")
            if preview:
                result.append(f"      {preview}\n", style="#a1a1aa")

        if len(self.tool.matches) > 5:
            result.append(f"    ... {len(self.tool.matches) - 5} more matches\n", style="#52525b")

        return result

    def render(self) -> RenderableType:
        """Render the tool call."""
        content = Text()

        tool_style = TOOL_STYLES.get(self.tool.kind, TOOL_STYLES[ToolKind.OTHER])
        state_style = STATE_STYLES.get(self.tool.state, STATE_STYLES[ToolState.PENDING])

        # Status icon
        state_icon = self._get_spinner() if state_style["animate"] else state_style["icon"]
        content.append(f"{state_icon} ", style=f"bold {state_style['color']}")

        # Tool icon and type
        content.append(f"{tool_style['icon']} ", style=tool_style["color"])
        content.append(f"{tool_style['label']}: ", style=f"bold {tool_style['color']}")

        # Title/path
        content.append(self.tool.display_title, style="#e4e4e7")

        # Duration
        if self.tool.duration_ms is not None:
            content.append(f"  ({self.tool.duration_str})", style="#6b7280")

        # Expand indicator
        expand_icon = "▼" if self.expanded else "▶"
        content.append(f"  {expand_icon}", style="#52525b")

        content.append("\n")

        # Expanded content
        if self.expanded:
            if self.tool.error:
                content.append(f"    ❌ {self.tool.error}\n", style="#ef4444")

            if self.tool.diff:
                content.append(self._render_diff())

            if self.tool.kind == ToolKind.SHELL:
                content.append(self._render_shell_output())

            if self.tool.matches:
                content.append(self._render_search_results())

            if self.tool.result and not self.tool.diff and self.tool.kind != ToolKind.SHELL:
                result_preview = (
                    self.tool.result[:200] + "..."
                    if len(self.tool.result) > 200
                    else self.tool.result
                )
                content.append(f"    {result_preview}\n", style="#a1a1aa")

        return content


class ToolCallPanel(Container):
    """
    Panel displaying all tool calls with grouping and filtering.

    Features:
    - Groups tool calls by type
    - Collapsible sections
    - Progress indicators
    - Summary statistics
    """

    DEFAULT_CSS = """
    ToolCallPanel {
        height: auto;
        max-height: 50%;
        border: solid #27272a;
        background: #0a0a0a;
        padding: 1;
        margin: 0 0 1 0;
    }

    ToolCallPanel .tools-header {
        height: 1;
        margin-bottom: 1;
    }

    ToolCallPanel .tools-content {
        height: auto;
        overflow-y: auto;
    }

    ToolCallPanel .tools-stats {
        height: 1;
        margin-top: 1;
    }
    """

    collapsed: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tools: Dict[str, ToolCallData] = {}
        self._widgets: Dict[str, SingleToolDisplay] = {}
        self._timer: Optional[Timer] = None

    def on_mount(self) -> None:
        """Start animation timer."""
        self._timer = self.set_interval(0.25, self._tick)

    def _tick(self) -> None:
        """Animation tick for running tools."""
        for widget in self._widgets.values():
            if widget.tool.state == ToolState.RUNNING:
                widget._spinner_frame += 1
                widget.refresh()

    def add_tool(self, tool: ToolCallData) -> None:
        """Add or update a tool call."""
        self._tools[tool.id] = tool

        if tool.id not in self._widgets:
            widget = SingleToolDisplay(tool, id=f"tool-{tool.id}")
            self._widgets[tool.id] = widget

            content = self.query_one(".tools-content", Container)
            content.mount(widget)
        else:
            self._widgets[tool.id].update_tool(tool)

        self._update_header()

    def update_tool(self, tool_id: str, **updates) -> None:
        """Update a tool call."""
        if tool_id in self._tools:
            tool = self._tools[tool_id]
            for key, value in updates.items():
                if hasattr(tool, key):
                    setattr(tool, key, value)

            if tool_id in self._widgets:
                self._widgets[tool_id].update_tool(tool)

        self._update_header()

    def complete_tool(self, tool_id: str, result: str = "", error: str = "") -> None:
        """Mark a tool as complete."""
        if tool_id in self._tools:
            tool = self._tools[tool_id]
            tool.end_time = datetime.now()
            tool.state = ToolState.ERROR if error else ToolState.SUCCESS
            tool.result = result
            tool.error = error

            if tool_id in self._widgets:
                self._widgets[tool_id].update_tool(tool)

        self._update_header()

    def _update_header(self) -> None:
        """Update the header with current stats."""
        header = self.query_one(".tools-header", Static)

        total = len(self._tools)
        running = sum(1 for t in self._tools.values() if t.state == ToolState.RUNNING)
        success = sum(1 for t in self._tools.values() if t.state == ToolState.SUCCESS)
        errors = sum(1 for t in self._tools.values() if t.state == ToolState.ERROR)

        text = Text()
        text.append("🔧 ", style="bold #f59e0b")
        text.append("Tool Calls", style="bold #e4e4e7")
        text.append(f"  ({total})", style="#6b7280")

        if running > 0:
            text.append(f"  ◐ {running}", style="#fbbf24")
        if success > 0:
            text.append(f"  ✓ {success}", style="#22c55e")
        if errors > 0:
            text.append(f"  ✗ {errors}", style="#ef4444")

        header.update(text)

    def clear(self) -> None:
        """Clear all tool calls."""
        self._tools.clear()

        content = self.query_one(".tools-content", Container)
        for widget in self._widgets.values():
            widget.remove()
        self._widgets.clear()

        self._update_header()

    def compose(self):
        """Compose the panel layout."""
        yield Static("", classes="tools-header")
        with Container(classes="tools-content"):
            pass


class CompactToolIndicator(Static):
    """Compact tool call indicator for status bar."""

    DEFAULT_CSS = """
    CompactToolIndicator {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._running = 0
        self._completed = 0
        self._errors = 0

    def update_counts(self, running: int, completed: int, errors: int) -> None:
        """Update the counts."""
        self._running = running
        self._completed = completed
        self._errors = errors
        self.refresh()

    def render(self) -> Text:
        text = Text()

        text.append("🔧 ", style="#f59e0b")

        total = self._running + self._completed + self._errors
        if total == 0:
            text.append("-", style="#52525b")
        else:
            if self._running > 0:
                text.append(f"◐{self._running} ", style="bold #fbbf24")
            if self._completed > 0:
                text.append(f"✓{self._completed} ", style="#22c55e")
            if self._errors > 0:
                text.append(f"✗{self._errors}", style="#ef4444")

        return text


# Helper functions for creating tool data


def create_file_read_tool(tool_id: str, path: str) -> ToolCallData:
    """Create a file read tool call."""
    return ToolCallData(
        id=tool_id,
        name="read_file",
        kind=ToolKind.FILE_READ,
        state=ToolState.RUNNING,
        start_time=datetime.now(),
        file_path=path,
    )


def create_file_write_tool(
    tool_id: str,
    path: str,
    old_content: str = "",
    new_content: str = "",
) -> ToolCallData:
    """Create a file write tool call."""
    return ToolCallData(
        id=tool_id,
        name="write_file",
        kind=ToolKind.FILE_WRITE,
        state=ToolState.RUNNING,
        start_time=datetime.now(),
        file_path=path,
        diff=DiffContent(
            path=path,
            old_text=old_content,
            new_text=new_content,
            language=detect_language(path),
        ),
    )


def create_shell_tool(tool_id: str, command: str) -> ToolCallData:
    """Create a shell command tool call."""
    return ToolCallData(
        id=tool_id,
        name="bash",
        kind=ToolKind.SHELL,
        state=ToolState.RUNNING,
        start_time=datetime.now(),
        command=command,
    )


def create_search_tool(tool_id: str, pattern: str) -> ToolCallData:
    """Create a search tool call."""
    return ToolCallData(
        id=tool_id,
        name="grep",
        kind=ToolKind.SEARCH,
        state=ToolState.RUNNING,
        start_time=datetime.now(),
        arguments={"pattern": pattern},
    )
