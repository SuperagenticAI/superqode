"""
Tool Display Widget - Shows tool calls with status.

Displays tool invocations in a clear, structured format:
- Tool name and type
- Arguments (truncated for readability)
- Status (pending, running, complete, error)
- Duration and result summary
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED


class ToolStatus(Enum):
    """Status of a tool call."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class ToolCall:
    """Represents a single tool invocation."""

    name: str
    tool_type: str  # e.g., "file_read", "shell_exec", "edit"
    arguments: Dict[str, Any] = field(default_factory=dict)
    status: ToolStatus = ToolStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    result_summary: str = ""
    error_message: str = ""

    @property
    def duration_ms(self) -> Optional[float]:
        """Get duration in milliseconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None

    @property
    def duration_str(self) -> str:
        """Get human-readable duration."""
        if self.duration_ms is None:
            return "-"
        if self.duration_ms < 1000:
            return f"{self.duration_ms:.0f}ms"
        return f"{self.duration_ms / 1000:.1f}s"

    @property
    def status_icon(self) -> str:
        """Get status icon."""
        return {
            ToolStatus.PENDING: "[dim]○[/dim]",
            ToolStatus.RUNNING: "[yellow]⟳[/yellow]",
            ToolStatus.COMPLETE: "[green]✓[/green]",
            ToolStatus.ERROR: "[red]✗[/red]",
        }.get(self.status, "?")


class ToolDisplay:
    """
    Widget for displaying tool calls in the TUI.

    Shows a panel with recent tool invocations and their status.
    """

    def __init__(self, max_display: int = 5, show_arguments: bool = False):
        """
        Initialize the tool display.

        Args:
            max_display: Maximum number of tools to show
            show_arguments: Whether to show tool arguments
        """
        self.max_display = max_display
        self.show_arguments = show_arguments
        self.calls: List[ToolCall] = []
        self.console = Console()

    def add_call(self, call: ToolCall) -> None:
        """Add a new tool call."""
        self.calls.append(call)
        # Keep only the most recent calls
        if len(self.calls) > self.max_display * 2:
            self.calls = self.calls[-self.max_display :]

    def start_call(self, name: str, tool_type: str, arguments: Dict[str, Any] = None) -> ToolCall:
        """Create and start a new tool call."""
        call = ToolCall(
            name=name,
            tool_type=tool_type,
            arguments=arguments or {},
            status=ToolStatus.RUNNING,
            start_time=datetime.now(),
        )
        self.add_call(call)
        return call

    def complete_call(self, call: ToolCall, result_summary: str = "") -> None:
        """Mark a tool call as complete."""
        call.status = ToolStatus.COMPLETE
        call.end_time = datetime.now()
        call.result_summary = result_summary

    def error_call(self, call: ToolCall, error_message: str) -> None:
        """Mark a tool call as errored."""
        call.status = ToolStatus.ERROR
        call.end_time = datetime.now()
        call.error_message = error_message

    def _truncate(self, text: str, max_len: int = 50) -> str:
        """Truncate text to max length."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def _format_arguments(self, args: Dict[str, Any]) -> str:
        """Format arguments for display."""
        if not args:
            return ""
        parts = []
        for key, value in args.items():
            if isinstance(value, str):
                parts.append(f"{key}={self._truncate(repr(value), 30)}")
            else:
                parts.append(f"{key}={value}")
        return ", ".join(parts[:3])  # Show at most 3 args

    def render(self) -> Panel:
        """Render the tool display as a Rich Panel."""
        recent = self.calls[-self.max_display :]

        if not recent:
            content = Text("No tool calls yet", style="dim")
        else:
            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("Status", width=3)
            table.add_column("Tool", style="cyan")
            table.add_column("Info", style="dim")
            table.add_column("Time", width=8, justify="right")

            for call in recent:
                # Build info column
                if call.status == ToolStatus.ERROR:
                    info = Text(self._truncate(call.error_message, 40), style="red")
                elif call.result_summary:
                    info = Text(self._truncate(call.result_summary, 40))
                elif self.show_arguments:
                    info = Text(self._truncate(self._format_arguments(call.arguments), 40))
                else:
                    info = Text(call.tool_type, style="dim")

                table.add_row(
                    call.status_icon,
                    call.name,
                    info,
                    call.duration_str,
                )

            content = table

        return Panel(
            content,
            title="[bold]Tool Calls[/bold]",
            border_style="dim",
            box=ROUNDED,
        )

    def print(self) -> None:
        """Print the tool display to console."""
        self.console.print(self.render())


def create_tool_display(max_display: int = 5) -> ToolDisplay:
    """Factory function to create a ToolDisplay."""
    return ToolDisplay(max_display=max_display)
