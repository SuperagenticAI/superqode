"""
SuperQode Sidebar Panels - Advanced Panel Widgets.

Provides advanced sidebar panels:
- AgentPanel: Connection info, model, tokens, cost
- ContextPanel: Files in context with token counts
- TerminalPanel: Embedded PTY terminal
- DiffPanel: Pending file changes
- HistoryPanel: Conversation history

All panels use SuperQode's unique design system.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

from rich.text import Text
from rich.syntax import Syntax
from rich.progress_bar import ProgressBar

from textual.widgets import Static, Button, Input
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.reactive import reactive
from textual.message import Message
from textual import on

if TYPE_CHECKING:
    from textual.app import App


# ============================================================================
# DESIGN SYSTEM
# ============================================================================

try:
    from superqode.design_system import COLORS as SQ_COLORS, GRADIENT_PURPLE, SUPERQODE_ICONS
except ImportError:

    class SQ_COLORS:
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

    SUPERQODE_ICONS = {
        "connected": "●",
        "disconnected": "○",
        "success": "✦",
        "error": "✕",
    }


# ============================================================================
# COMMON PANEL STYLES
# ============================================================================

PANEL_CSS = """
.panel-header {
    height: 2;
    background: #0a0a0a;
    border-bottom: solid #1a1a1a;
    padding: 0 1;
}

.panel-content {
    height: 1fr;
    background: #000000;
    padding: 1;
}

.panel-footer {
    height: 2;
    background: #0a0a0a;
    border-top: solid #1a1a1a;
    padding: 0 1;
}

.panel-item {
    height: auto;
    padding: 0 1;
    margin-bottom: 1;
}

.panel-item:hover {
    background: #0a0a0a;
}

.panel-item.selected {
    background: #7c3aed20;
    border-left: solid #7c3aed;
}

.panel-empty {
    text-align: center;
    color: #52525b;
    padding: 2;
}
"""


# ============================================================================
# AGENT PANEL
# ============================================================================


@dataclass
class AgentInfo:
    """Agent connection information."""

    name: str = ""
    model: str = ""
    provider: str = ""
    connection_type: str = ""  # "acp", "byok", "local"
    connected: bool = False
    connected_at: Optional[datetime] = None

    # Session stats
    message_count: int = 0
    tool_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0

    # Session duration
    @property
    def duration_str(self) -> str:
        if not self.connected_at:
            return "-"
        delta = datetime.now() - self.connected_at
        mins = int(delta.total_seconds() // 60)
        secs = int(delta.total_seconds() % 60)
        return f"{mins}m {secs}s"


class AgentPanel(Container):
    """
    Panel showing connected agent information.

    Features:
    - Connection status indicator
    - Agent name and model
    - Token usage (prompt/completion)
    - Cost tracking
    - Session stats
    - Disconnect button
    """

    DEFAULT_CSS = (
        PANEL_CSS
        + """
    AgentPanel {
        height: 100%;
        background: #000000;
    }

    AgentPanel #agent-status {
        height: auto;
        padding: 1;
    }

    AgentPanel #agent-stats {
        height: auto;
        padding: 1;
        border-top: solid #1a1a1a;
    }

    AgentPanel #agent-tokens {
        height: auto;
        padding: 1;
        border-top: solid #1a1a1a;
    }

    AgentPanel .stat-row {
        height: 1;
    }

    AgentPanel .stat-label {
        width: 12;
        color: #71717a;
    }

    AgentPanel .stat-value {
        width: 1fr;
        color: #e4e4e7;
    }

    AgentPanel #disconnect-btn {
        margin-top: 1;
        width: 100%;
    }
    """
    )

    class DisconnectRequested(Message):
        """Posted when disconnect button is clicked."""

        pass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._agent_info = AgentInfo()

    def compose(self):
        """Compose the agent panel."""
        yield Static(self._render_header(), id="panel-header", classes="panel-header")

        with ScrollableContainer(id="panel-content", classes="panel-content"):
            yield Static(self._render_status(), id="agent-status")
            yield Static(self._render_stats(), id="agent-stats")
            yield Static(self._render_tokens(), id="agent-tokens")
            yield Button("Disconnect", id="disconnect-btn", variant="error")

    def _render_header(self) -> Text:
        """Render panel header."""
        text = Text()
        text.append("◈ ", style=f"bold {SQ_COLORS.primary}")
        text.append("Agent", style=f"bold {SQ_COLORS.text_secondary}")
        return text

    def _render_status(self) -> Text:
        """Render connection status."""
        info = self._agent_info
        text = Text()

        # Connection indicator
        if info.connected:
            text.append("● ", style=f"bold {SQ_COLORS.success}")
            text.append("Connected\n", style=SQ_COLORS.success)
        else:
            text.append("○ ", style=SQ_COLORS.text_dim)
            text.append("Not connected\n", style=SQ_COLORS.text_dim)
            return text

        # Agent name
        text.append("\n")
        text.append("Agent: ", style=SQ_COLORS.text_dim)
        text.append(f"{info.name}\n", style=f"bold {SQ_COLORS.text_primary}")

        # Model
        text.append("Model: ", style=SQ_COLORS.text_dim)
        text.append(f"{info.model}\n", style=SQ_COLORS.info)

        # Connection type
        conn_colors = {"acp": SQ_COLORS.success, "byok": SQ_COLORS.info, "local": SQ_COLORS.warning}
        text.append("Type:  ", style=SQ_COLORS.text_dim)
        text.append(
            f"{info.connection_type.upper()}\n",
            style=conn_colors.get(info.connection_type, SQ_COLORS.text_muted),
        )

        # Duration
        text.append("Time:  ", style=SQ_COLORS.text_dim)
        text.append(f"{info.duration_str}\n", style=SQ_COLORS.text_muted)

        return text

    def _render_stats(self) -> Text:
        """Render session stats."""
        info = self._agent_info
        text = Text()

        text.append("Session Stats\n", style=f"bold {SQ_COLORS.text_muted}")
        text.append("\n")

        text.append("Messages: ", style=SQ_COLORS.text_dim)
        text.append(f"{info.message_count}\n", style=SQ_COLORS.text_secondary)

        text.append("Tools:    ", style=SQ_COLORS.text_dim)
        text.append(f"{info.tool_count}\n", style=SQ_COLORS.text_secondary)

        return text

    def _render_tokens(self) -> Text:
        """Render token usage."""
        info = self._agent_info
        text = Text()

        text.append("Token Usage\n", style=f"bold {SQ_COLORS.text_muted}")
        text.append("\n")

        text.append("Prompt:     ", style=SQ_COLORS.text_dim)
        text.append(f"{info.prompt_tokens:,}\n", style=SQ_COLORS.text_secondary)

        text.append("Completion: ", style=SQ_COLORS.text_dim)
        text.append(f"{info.completion_tokens:,}\n", style=SQ_COLORS.text_secondary)

        total = info.prompt_tokens + info.completion_tokens
        text.append("Total:      ", style=SQ_COLORS.text_dim)
        text.append(f"{total:,}\n", style=f"bold {SQ_COLORS.text_primary}")

        if info.total_cost > 0:
            text.append("\nCost: ", style=SQ_COLORS.text_dim)
            text.append(f"${info.total_cost:.4f}", style=f"bold {SQ_COLORS.warning}")

        return text

    def update_agent(self, **kwargs) -> None:
        """Update agent information."""
        for key, value in kwargs.items():
            if hasattr(self._agent_info, key):
                setattr(self._agent_info, key, value)
        self._refresh()

    def set_agent(self, info: AgentInfo) -> None:
        """Set agent info directly."""
        self._agent_info = info
        self._refresh()

    def clear(self) -> None:
        """Clear agent info (disconnect)."""
        self._agent_info = AgentInfo()
        self._refresh()

    def _refresh(self) -> None:
        """Refresh all displays."""
        try:
            self.query_one("#agent-status", Static).update(self._render_status())
            self.query_one("#agent-stats", Static).update(self._render_stats())
            self.query_one("#agent-tokens", Static).update(self._render_tokens())
        except Exception:
            pass

    @on(Button.Pressed, "#disconnect-btn")
    def _on_disconnect(self) -> None:
        """Handle disconnect button."""
        self.post_message(self.DisconnectRequested())


# ============================================================================
# CONTEXT PANEL
# ============================================================================


@dataclass
class ContextFile:
    """A file in the agent's context."""

    path: str
    name: str
    token_count: int = 0
    added_at: Optional[datetime] = None


class ContextPanel(Container):
    """
    Panel showing files in agent context.

    Features:
    - List of files with token counts
    - Progress bar showing context usage
    - Add/remove file buttons
    - Clear all button
    """

    DEFAULT_CSS = (
        PANEL_CSS
        + """
    ContextPanel {
        height: 100%;
        background: #000000;
    }

    ContextPanel #context-usage {
        height: auto;
        padding: 1;
        border-bottom: solid #1a1a1a;
    }

    ContextPanel #context-files {
        height: 1fr;
    }

    ContextPanel .context-file {
        height: 2;
        padding: 0 1;
        border-bottom: solid #0a0a0a;
    }

    ContextPanel .context-file:hover {
        background: #0a0a0a;
    }

    ContextPanel #context-actions {
        height: 3;
        padding: 1;
        border-top: solid #1a1a1a;
    }
    """
    )

    class FileRemoved(Message):
        """Posted when a file is removed from context."""

        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    class ContextCleared(Message):
        """Posted when context is cleared."""

        pass

    def __init__(self, context_window: int = 128000, **kwargs):
        super().__init__(**kwargs)
        self._files: List[ContextFile] = []
        self._context_window = context_window

    def compose(self):
        """Compose the context panel."""
        yield Static(self._render_header(), id="panel-header", classes="panel-header")
        yield Static(self._render_usage(), id="context-usage")

        with ScrollableContainer(id="context-files", classes="panel-content"):
            yield Static(self._render_files(), id="files-list")

        with Horizontal(id="context-actions"):
            yield Button("Clear All", id="clear-btn", variant="warning")

    def _render_header(self) -> Text:
        """Render panel header."""
        text = Text()
        text.append("◈ ", style=f"bold {SQ_COLORS.primary}")
        text.append("Context", style=f"bold {SQ_COLORS.text_secondary}")
        text.append(f"  ({len(self._files)} files)", style=SQ_COLORS.text_dim)
        return text

    def _render_usage(self) -> Text:
        """Render context usage bar."""
        total_tokens = sum(f.token_count for f in self._files)
        usage_pct = (total_tokens / self._context_window) * 100 if self._context_window > 0 else 0

        text = Text()
        text.append("Context Usage\n", style=f"bold {SQ_COLORS.text_muted}")

        # Progress bar
        bar_width = 20
        filled = int((usage_pct / 100) * bar_width)
        empty = bar_width - filled

        # Color based on usage
        if usage_pct < 50:
            bar_color = SQ_COLORS.success
        elif usage_pct < 80:
            bar_color = SQ_COLORS.warning
        else:
            bar_color = SQ_COLORS.error

        text.append("[", style=SQ_COLORS.text_dim)
        text.append("█" * filled, style=bar_color)
        text.append("░" * empty, style=SQ_COLORS.text_ghost)
        text.append("]", style=SQ_COLORS.text_dim)
        text.append(f" {usage_pct:.1f}%\n", style=SQ_COLORS.text_muted)

        text.append(f"{total_tokens:,} / {self._context_window:,} tokens", style=SQ_COLORS.text_dim)

        return text

    def _render_files(self) -> Text:
        """Render file list."""
        if not self._files:
            text = Text()
            text.append("\n  No files in context\n", style=SQ_COLORS.text_ghost)
            text.append("  Files are added automatically\n", style=SQ_COLORS.text_ghost)
            return text

        text = Text()
        for f in self._files:
            text.append("  ↳ ", style=SQ_COLORS.info)

            # File name
            name = f.name if len(f.name) <= 20 else f.name[:17] + "..."
            text.append(name, style=SQ_COLORS.text_secondary)

            # Token count
            text.append(f"  {f.token_count:,}t\n", style=SQ_COLORS.text_dim)

        return text

    def add_file(self, path: str, token_count: int = 0) -> None:
        """Add a file to context."""
        # Check if already exists
        for f in self._files:
            if f.path == path:
                f.token_count = token_count
                self._refresh()
                return

        self._files.append(
            ContextFile(
                path=path,
                name=Path(path).name,
                token_count=token_count,
                added_at=datetime.now(),
            )
        )
        self._refresh()

    def remove_file(self, path: str) -> None:
        """Remove a file from context."""
        self._files = [f for f in self._files if f.path != path]
        self._refresh()
        self.post_message(self.FileRemoved(path))

    def clear(self) -> None:
        """Clear all files from context."""
        self._files.clear()
        self._refresh()
        self.post_message(self.ContextCleared())

    def _refresh(self) -> None:
        """Refresh displays."""
        try:
            self.query_one("#panel-header", Static).update(self._render_header())
            self.query_one("#context-usage", Static).update(self._render_usage())
            self.query_one("#files-list", Static).update(self._render_files())
        except Exception:
            pass

    @on(Button.Pressed, "#clear-btn")
    def _on_clear(self) -> None:
        """Handle clear button."""
        self.clear()


# ============================================================================
# TERMINAL PANEL
# ============================================================================


class TerminalPanel(Container):
    """
    Panel with embedded terminal.

    Features:
    - PTY terminal emulation
    - Quick command buttons
    - Output history
    """

    DEFAULT_CSS = (
        PANEL_CSS
        + """
    TerminalPanel {
        height: 100%;
        background: #000000;
    }

    TerminalPanel #terminal-output {
        height: 1fr;
        background: #0c0c0c;
        padding: 1;
        overflow-y: auto;
    }

    TerminalPanel #terminal-input {
        height: 3;
        border-top: solid #1a1a1a;
        padding: 1;
    }

    TerminalPanel #terminal-input Input {
        width: 100%;
    }

    TerminalPanel #quick-commands {
        height: 2;
        border-top: solid #1a1a1a;
        padding: 0 1;
    }
    """
    )

    class CommandSubmitted(Message):
        """Posted when a command is submitted."""

        def __init__(self, command: str) -> None:
            self.command = command
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._output_lines: List[str] = []
        self._max_lines = 500

    def compose(self):
        """Compose the terminal panel."""
        yield Static(self._render_header(), id="panel-header", classes="panel-header")

        with ScrollableContainer(id="terminal-output"):
            yield Static(self._render_output(), id="output-content")

        with Container(id="terminal-input"):
            yield Input(placeholder="$ Enter command...", id="cmd-input")

        yield Static(self._render_quick_commands(), id="quick-commands")

    def _render_header(self) -> Text:
        """Render panel header."""
        text = Text()
        text.append("▸ ", style=f"bold {SQ_COLORS.warning}")
        text.append("Terminal", style=f"bold {SQ_COLORS.text_secondary}")
        return text

    def _render_output(self) -> Text:
        """Render terminal output."""
        if not self._output_lines:
            text = Text()
            text.append("Terminal ready.\n", style=SQ_COLORS.text_dim)
            text.append("Type a command or use quick buttons.\n", style=SQ_COLORS.text_ghost)
            return text

        text = Text()
        for line in self._output_lines[-100:]:  # Show last 100 lines
            text.append(f"{line}\n", style=SQ_COLORS.text_secondary)

        return text

    def _render_quick_commands(self) -> Text:
        """Render quick command buttons."""
        text = Text()

        commands = ["git status", "npm test", "ls -la"]
        for i, cmd in enumerate(commands):
            if i > 0:
                text.append(" │ ", style=SQ_COLORS.text_ghost)
            text.append(cmd, style=SQ_COLORS.info)

        return text

    def add_output(self, text: str) -> None:
        """Add output to terminal."""
        lines = text.split("\n")
        self._output_lines.extend(lines)

        # Trim if too long
        if len(self._output_lines) > self._max_lines:
            self._output_lines = self._output_lines[-self._max_lines :]

        self._refresh()

    def add_command(self, cmd: str, output: str = "", success: bool = True) -> None:
        """Add a command and its output."""
        self._output_lines.append(f"$ {cmd}")
        if output:
            self._output_lines.extend(output.split("\n"))
        self._refresh()

    def clear(self) -> None:
        """Clear terminal output."""
        self._output_lines.clear()
        self._refresh()

    def _refresh(self) -> None:
        """Refresh output display."""
        try:
            self.query_one("#output-content", Static).update(self._render_output())
        except Exception:
            pass

    @on(Input.Submitted, "#cmd-input")
    def _on_command(self, event: Input.Submitted) -> None:
        """Handle command submission."""
        cmd = event.value.strip()
        if cmd:
            event.input.value = ""
            self.post_message(self.CommandSubmitted(cmd))


# ============================================================================
# DIFF PANEL
# ============================================================================


@dataclass
class FileDiff:
    """A file with pending changes."""

    path: str
    name: str
    status: str = "modified"  # "modified", "added", "deleted"
    additions: int = 0
    deletions: int = 0
    diff_text: str = ""


class DiffPanel(Container):
    """
    Panel showing pending file changes.

    Features:
    - List of modified files
    - Click to see diff
    - Accept/reject buttons
    - Stage for commit
    """

    DEFAULT_CSS = (
        PANEL_CSS
        + """
    DiffPanel {
        height: 100%;
        background: #000000;
    }

    DiffPanel #diff-files {
        height: 50%;
        border-bottom: solid #1a1a1a;
    }

    DiffPanel #diff-preview {
        height: 50%;
        background: #0c0c0c;
        padding: 1;
        overflow: auto;
    }

    DiffPanel #diff-actions {
        height: 3;
        padding: 1;
        border-top: solid #1a1a1a;
    }

    DiffPanel .diff-file {
        height: 2;
        padding: 0 1;
    }

    DiffPanel .diff-file:hover {
        background: #0a0a0a;
    }

    DiffPanel .diff-file.selected {
        background: #7c3aed20;
    }
    """
    )

    class FileAccepted(Message):
        """Posted when a file change is accepted."""

        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    class FileRejected(Message):
        """Posted when a file change is rejected."""

        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    class AllAccepted(Message):
        """Posted when all changes are accepted."""

        pass

    class AllRejected(Message):
        """Posted when all changes are rejected."""

        pass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._files: List[FileDiff] = []
        self._selected_index: int = -1

    def compose(self):
        """Compose the diff panel."""
        yield Static(self._render_header(), id="panel-header", classes="panel-header")

        with ScrollableContainer(id="diff-files"):
            yield Static(self._render_files(), id="files-list")

        with ScrollableContainer(id="diff-preview"):
            yield Static(self._render_preview(), id="preview-content")

        with Horizontal(id="diff-actions"):
            yield Button("Accept All", id="accept-all-btn", variant="success")
            yield Button("Reject All", id="reject-all-btn", variant="error")

    def _render_header(self) -> Text:
        """Render panel header."""
        text = Text()
        text.append("⟳ ", style=f"bold {SQ_COLORS.warning}")
        text.append("Changes", style=f"bold {SQ_COLORS.text_secondary}")

        if self._files:
            adds = sum(f.additions for f in self._files)
            dels = sum(f.deletions for f in self._files)
            text.append(f"  +{adds}", style=SQ_COLORS.success)
            text.append(f" -{dels}", style=SQ_COLORS.error)

        return text

    def _render_files(self) -> Text:
        """Render file list."""
        if not self._files:
            text = Text()
            text.append("\n  No pending changes\n", style=SQ_COLORS.text_ghost)
            return text

        text = Text()
        for i, f in enumerate(self._files):
            is_selected = i == self._selected_index

            # Status icon
            status_icons = {"modified": "⟳", "added": "+", "deleted": "−"}
            status_colors = {
                "modified": SQ_COLORS.warning,
                "added": SQ_COLORS.success,
                "deleted": SQ_COLORS.error,
            }

            icon = status_icons.get(f.status, "•")
            color = status_colors.get(f.status, SQ_COLORS.text_muted)

            if is_selected:
                text.append("▸ ", style=f"bold {SQ_COLORS.primary}")
            else:
                text.append("  ", style="")

            text.append(f"{icon} ", style=f"bold {color}")
            text.append(
                f"{f.name}", style=SQ_COLORS.text_secondary if is_selected else SQ_COLORS.text_muted
            )
            text.append(f"  +{f.additions}", style=SQ_COLORS.success)
            text.append(f" -{f.deletions}\n", style=SQ_COLORS.error)

        return text

    def _render_preview(self) -> Text:
        """Render diff preview."""
        if self._selected_index < 0 or self._selected_index >= len(self._files):
            text = Text()
            text.append("Select a file to preview diff", style=SQ_COLORS.text_ghost)
            return text

        f = self._files[self._selected_index]

        if not f.diff_text:
            text = Text()
            text.append(f"No diff available for {f.name}", style=SQ_COLORS.text_ghost)
            return text

        # Render diff with colors
        text = Text()
        for line in f.diff_text.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                text.append(f"{line}\n", style=SQ_COLORS.success)
            elif line.startswith("-") and not line.startswith("---"):
                text.append(f"{line}\n", style=SQ_COLORS.error)
            elif line.startswith("@@"):
                text.append(f"{line}\n", style=SQ_COLORS.info)
            else:
                text.append(f"{line}\n", style=SQ_COLORS.text_dim)

        return text

    def add_file(
        self,
        path: str,
        status: str = "modified",
        additions: int = 0,
        deletions: int = 0,
        diff_text: str = "",
    ) -> None:
        """Add a file to the diff list."""
        # Check if exists
        for f in self._files:
            if f.path == path:
                f.status = status
                f.additions = additions
                f.deletions = deletions
                f.diff_text = diff_text
                self._refresh()
                return

        self._files.append(
            FileDiff(
                path=path,
                name=Path(path).name,
                status=status,
                additions=additions,
                deletions=deletions,
                diff_text=diff_text,
            )
        )
        self._refresh()

    def remove_file(self, path: str) -> None:
        """Remove a file from the list."""
        self._files = [f for f in self._files if f.path != path]
        if self._selected_index >= len(self._files):
            self._selected_index = len(self._files) - 1
        self._refresh()

    def select_file(self, index: int) -> None:
        """Select a file by index."""
        if 0 <= index < len(self._files):
            self._selected_index = index
            self._refresh()

    def clear(self) -> None:
        """Clear all files."""
        self._files.clear()
        self._selected_index = -1
        self._refresh()

    def _refresh(self) -> None:
        """Refresh displays."""
        try:
            self.query_one("#panel-header", Static).update(self._render_header())
            self.query_one("#files-list", Static).update(self._render_files())
            self.query_one("#preview-content", Static).update(self._render_preview())
        except Exception:
            pass

    @on(Button.Pressed, "#accept-all-btn")
    def _on_accept_all(self) -> None:
        """Handle accept all."""
        self.post_message(self.AllAccepted())

    @on(Button.Pressed, "#reject-all-btn")
    def _on_reject_all(self) -> None:
        """Handle reject all."""
        self.post_message(self.AllRejected())


# ============================================================================
# HISTORY PANEL
# ============================================================================


@dataclass
class HistoryMessage:
    """A message in history."""

    id: str
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime
    agent_name: str = ""
    token_count: int = 0


class HistoryPanel(Container):
    """
    Panel showing conversation history.

    Features:
    - Message timeline
    - Filter by user/agent
    - Search box
    - Click to scroll to message
    - Export to markdown
    """

    DEFAULT_CSS = (
        PANEL_CSS
        + """
    HistoryPanel {
        height: 100%;
        background: #000000;
    }

    HistoryPanel #history-search {
        height: 3;
        padding: 1;
        border-bottom: solid #1a1a1a;
    }

    HistoryPanel #history-search Input {
        width: 100%;
    }

    HistoryPanel #history-messages {
        height: 1fr;
    }

    HistoryPanel #history-actions {
        height: 2;
        padding: 0 1;
        border-top: solid #1a1a1a;
    }

    HistoryPanel .history-message {
        height: auto;
        padding: 1;
        border-bottom: solid #0a0a0a;
    }

    HistoryPanel .history-message:hover {
        background: #0a0a0a;
    }
    """
    )

    class MessageSelected(Message):
        """Posted when a message is selected."""

        def __init__(self, message_id: str) -> None:
            self.message_id = message_id
            super().__init__()

    class ExportRequested(Message):
        """Posted when export is requested."""

        pass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._messages: List[HistoryMessage] = []
        self._filter: str = ""  # "", "user", "assistant"
        self._search: str = ""

    def compose(self):
        """Compose the history panel."""
        yield Static(self._render_header(), id="panel-header", classes="panel-header")

        with Container(id="history-search"):
            yield Input(placeholder="Search messages...", id="search-input")

        with ScrollableContainer(id="history-messages", classes="panel-content"):
            yield Static(self._render_messages(), id="messages-list")

        yield Static(self._render_actions(), id="history-actions")

    def _render_header(self) -> Text:
        """Render panel header."""
        text = Text()
        text.append("◇ ", style=f"bold {SQ_COLORS.secondary}")
        text.append("History", style=f"bold {SQ_COLORS.text_secondary}")
        text.append(f"  ({len(self._messages)} msgs)", style=SQ_COLORS.text_dim)
        return text

    def _render_messages(self) -> Text:
        """Render message list."""
        messages = self._get_filtered_messages()

        if not messages:
            text = Text()
            if self._search:
                text.append("\n  No messages match search\n", style=SQ_COLORS.text_ghost)
            else:
                text.append("\n  No messages yet\n", style=SQ_COLORS.text_ghost)
            return text

        text = Text()
        for msg in messages[-20:]:  # Show last 20
            # Time
            time_str = msg.timestamp.strftime("%H:%M")
            text.append(f"{time_str} ", style=SQ_COLORS.text_ghost)

            # Role indicator
            if msg.role == "user":
                text.append("▸ ", style=f"bold {SQ_COLORS.primary}")
                text.append("You: ", style=SQ_COLORS.primary)
            elif msg.role == "assistant":
                text.append("◇ ", style=f"bold {SQ_COLORS.secondary}")
                if msg.agent_name:
                    text.append(f"{msg.agent_name}: ", style=SQ_COLORS.secondary)
                else:
                    text.append("Agent: ", style=SQ_COLORS.secondary)
            else:
                text.append("• ", style=SQ_COLORS.text_dim)
                text.append("System: ", style=SQ_COLORS.text_dim)

            # Content preview
            preview = msg.content[:40] + "..." if len(msg.content) > 40 else msg.content
            preview = preview.replace("\n", " ")
            text.append(f"{preview}\n", style=SQ_COLORS.text_muted)

        return text

    def _render_actions(self) -> Text:
        """Render action buttons."""
        text = Text()
        text.append("Filter: ", style=SQ_COLORS.text_ghost)
        text.append(
            "[All]", style=f"bold {SQ_COLORS.info}" if not self._filter else SQ_COLORS.text_dim
        )
        text.append(" ", style="")
        text.append(
            "[User]",
            style=f"bold {SQ_COLORS.info}" if self._filter == "user" else SQ_COLORS.text_dim,
        )
        text.append(" ", style="")
        text.append(
            "[Agent]",
            style=f"bold {SQ_COLORS.info}" if self._filter == "assistant" else SQ_COLORS.text_dim,
        )
        return text

    def _get_filtered_messages(self) -> List[HistoryMessage]:
        """Get messages with current filter and search."""
        messages = self._messages

        if self._filter:
            messages = [m for m in messages if m.role == self._filter]

        if self._search:
            search_lower = self._search.lower()
            messages = [m for m in messages if search_lower in m.content.lower()]

        return messages

    def add_message(
        self, role: str, content: str, agent_name: str = "", token_count: int = 0
    ) -> None:
        """Add a message to history."""
        msg = HistoryMessage(
            id=f"msg-{len(self._messages)}",
            role=role,
            content=content,
            timestamp=datetime.now(),
            agent_name=agent_name,
            token_count=token_count,
        )
        self._messages.append(msg)
        self._refresh()

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()
        self._refresh()

    def set_filter(self, filter_type: str) -> None:
        """Set message filter."""
        self._filter = filter_type if filter_type in ("user", "assistant") else ""
        self._refresh()

    def _refresh(self) -> None:
        """Refresh displays."""
        try:
            self.query_one("#panel-header", Static).update(self._render_header())
            self.query_one("#messages-list", Static).update(self._render_messages())
            self.query_one("#history-actions", Static).update(self._render_actions())
        except Exception:
            pass

    @on(Input.Changed, "#search-input")
    def _on_search(self, event: Input.Changed) -> None:
        """Handle search input."""
        self._search = event.value
        self._refresh()


class HarnessPanel(Container):
    """Harness workbench panel for active spec, readiness, graph, and evidence."""

    DEFAULT_CSS = (
        PANEL_CSS
        + """
    HarnessPanel {
        height: 100%;
        background: #000000;
    }

    HarnessPanel #harness-summary {
        height: 1fr;
        padding: 1;
        background: #000000;
    }
    """
    )

    def compose(self):
        """Compose the harness overview panel."""
        yield Static(self._render_header(), id="panel-header", classes="panel-header")
        with ScrollableContainer(id="harness-summary", classes="panel-content"):
            yield Static(self._render_summary(), id="harness-content")

    def on_mount(self) -> None:
        """Refresh after mount so filesystem/provider state is current."""
        self.refresh_summary()

    def _render_header(self) -> Text:
        text = Text()
        text.append("▣ ", style=f"bold {SQ_COLORS.primary}")
        text.append("Harness", style=f"bold {SQ_COLORS.text_secondary}")
        return text

    def _render_summary(self) -> Text:
        text = Text()
        text.append("Harness Workbench\n\n", style=f"bold {SQ_COLORS.text_primary}")

        spec, path, load_error = self._load_active_harness()
        if spec is None:
            text.append("Active Harness\n", style=f"bold {SQ_COLORS.primary_light}")
            text.append("  none loaded\n", style=SQ_COLORS.warning)
            if path:
                text.append(f"  {path}\n", style=SQ_COLORS.text_dim)
            if load_error:
                text.append(f"  {load_error}\n", style=SQ_COLORS.error)
            text.append("  Load with :harness <spec.yaml>\n", style=SQ_COLORS.text_dim)
            text.append("  Start with :harness templates\n", style=SQ_COLORS.text_dim)
            text.append("\n")
        else:
            self._append_active_harness(text, spec, path)

        text.append("\nProviders\n", style=f"bold {SQ_COLORS.primary_light}")
        try:
            from superqode.providers.recommendations import provider_doctor_cards

            cards = provider_doctor_cards(["ds4", "ollama", "openai", "anthropic", "google"])
            for card in cards:
                status = "ready" if card["configured"] else "missing"
                style = SQ_COLORS.success if card["configured"] else SQ_COLORS.warning
                text.append(f"  {card['provider']:<10}", style=SQ_COLORS.info)
                text.append(f"{status:<8}", style=style)
                text.append(f"{card['setup_hint']}\n", style=SQ_COLORS.text_dim)
        except Exception as exc:
            text.append(f"  Provider status unavailable: {exc}\n", style=SQ_COLORS.text_dim)

        text.append("\nSandboxes\n", style=f"bold {SQ_COLORS.primary_light}")
        try:
            from superqode.sandbox import sandbox_provider_status

            for backend in ("docker", "e2b", "daytona", "modal", "vercel"):
                status = sandbox_provider_status(backend)
                style = SQ_COLORS.success if status.available else SQ_COLORS.warning
                text.append(f"  {backend:<10}", style=SQ_COLORS.info)
                text.append(f"{'ready' if status.available else 'missing':<8}", style=style)
                text.append(f"{status.detail}\n", style=SQ_COLORS.text_dim)
        except Exception as exc:
            text.append(f"  Sandbox status unavailable: {exc}\n", style=SQ_COLORS.text_dim)

        text.append("\nPlugins\n", style=f"bold {SQ_COLORS.primary_light}")
        try:
            from superqode.plugins import load_plugins

            plugins = load_plugins(Path.cwd())
            if plugins:
                for plugin in plugins[:5]:
                    text.append(f"  {plugin.id:<18}", style=SQ_COLORS.info)
                    text.append(f"{plugin.version}\n", style=SQ_COLORS.text_dim)
            else:
                text.append("  No plugin manifests found.\n", style=SQ_COLORS.text_dim)
        except Exception as exc:
            text.append(f"  Plugin status unavailable: {exc}\n", style=SQ_COLORS.text_dim)

        text.append("\nBenchmarks\n", style=f"bold {SQ_COLORS.primary_light}")
        try:
            from superqode.benchmarks import DEFAULT_TARGETS, is_target_available

            for name, target in DEFAULT_TARGETS.items():
                available = is_target_available(target)
                style = SQ_COLORS.success if available else SQ_COLORS.warning
                text.append(f"  {name:<10}", style=SQ_COLORS.info)
                text.append(f"{'available' if available else 'missing'}\n", style=style)
        except Exception as exc:
            text.append(f"  Benchmark status unavailable: {exc}\n", style=SQ_COLORS.text_dim)

        text.append("\nCommands\n", style=f"bold {SQ_COLORS.primary_light}")
        text.append("  :harness inspect    :harness doctor\n", style=SQ_COLORS.text_dim)
        text.append("  :harness graph      :harness runs\n", style=SQ_COLORS.text_dim)
        text.append("  :workflow preview   :workflow run <task>\n", style=SQ_COLORS.text_dim)
        return text

    def _load_active_harness(self):
        """Load the active harness from env, then fall back to local harness.yaml."""
        import os

        env_path = os.getenv("SUPERQODE_HARNESS", "").strip()
        candidates = [env_path] if env_path else []
        if not candidates and Path("harness.yaml").exists():
            candidates.append("harness.yaml")
        if not candidates and Path("harness.yml").exists():
            candidates.append("harness.yml")
        if not candidates:
            return None, "", ""
        path = candidates[0]
        try:
            from superqode.harness import load_harness_spec

            return load_harness_spec(path), path, ""
        except Exception as exc:  # noqa: BLE001
            return None, path, str(exc)

    def _append_active_harness(self, text: Text, spec, path: str) -> None:
        """Append the active harness workbench summary."""
        try:
            from superqode.harness import (
                FileHarnessStore,
                build_harness_evidence,
                doctor_harness,
                inspect_harness,
                plan_harness_graph,
            )

            summary = inspect_harness(spec)
            report = doctor_harness(spec)
            graph = plan_harness_graph(spec)
        except Exception as exc:  # noqa: BLE001
            text.append("Active Harness\n", style=f"bold {SQ_COLORS.primary_light}")
            text.append(f"  {spec.name}\n", style=SQ_COLORS.info)
            text.append(f"  Workbench unavailable: {exc}\n", style=SQ_COLORS.error)
            return

        ready_style = SQ_COLORS.success if report.status == "ok" else SQ_COLORS.warning
        if report.status == "error":
            ready_style = SQ_COLORS.error
        report_dict = report.to_dict()
        report_summary = report_dict["summary"]

        text.append("Active Harness\n", style=f"bold {SQ_COLORS.primary_light}")
        text.append(f"  {summary['name']} ", style=f"bold {SQ_COLORS.info}")
        text.append(f"v{summary['version']}  ", style=SQ_COLORS.text_dim)
        text.append(f"{summary['flavor']}\n", style=SQ_COLORS.text_secondary)
        if path:
            text.append(f"  {path}\n", style=SQ_COLORS.text_dim)
        text.append("  readiness ", style=SQ_COLORS.text_dim)
        text.append(
            "ready" if report.status != "error" else "blocked",
            style=f"bold {ready_style}",
        )
        text.append(
            f"  {report_summary['blockers']} blocker(s), {report_summary['warnings']} warning(s)\n",
            style=SQ_COLORS.text_dim,
        )

        workflow = summary["workflow"]
        model = summary["model_policy"]
        permissions = summary["permissions"]
        text.append("\nRuntime\n", style=f"bold {SQ_COLORS.primary_light}")
        text.append(f"  backend     {summary['runtime']['backend']}\n", style=SQ_COLORS.text_secondary)
        text.append(
            f"  workflow    {workflow['mode']}"
            + (f" / {workflow['preset']}" if workflow["preset"] else "")
            + f"  p={workflow['parallelism']}\n",
            style=SQ_COLORS.text_secondary,
        )
        text.append(
            f"  model       {model['primary'] or 'connection default'}\n",
            style=SQ_COLORS.text_secondary,
        )

        text.append("\nPermissions\n", style=f"bold {SQ_COLORS.primary_light}")
        text.append(
            "  "
            f"read={permissions['allow_read']}  "
            f"write={permissions['allow_write']}  "
            f"shell={permissions['allow_shell']}  "
            f"net={permissions['allow_network']}\n",
            style=SQ_COLORS.text_secondary,
        )
        text.append(f"  approvals={permissions['approval_profile']}\n", style=SQ_COLORS.text_dim)
        self._append_permission_rules(text, permissions.get("rules") or [])
        self._append_remembered_permission_rules(text, permissions.get("remembered_rules") or [])
        self._append_hooks(text, summary.get("hooks") or {})

        text.append("\nTools & Skills\n", style=f"bold {SQ_COLORS.primary_light}")
        text.append(self._preview_line("tools", summary["tools"]), style=SQ_COLORS.text_secondary)
        text.append(self._preview_line("skills", summary["skills"]), style=SQ_COLORS.text_secondary)

        text.append("\nMCP / Validation\n", style=f"bold {SQ_COLORS.primary_light}")
        mcp_servers = summary["mcp"]["servers"]
        text.append(
            f"  mcp         {', '.join(mcp_servers) if mcp_servers else 'none declared'}\n",
            style=SQ_COLORS.text_secondary,
        )
        validation = summary["validation"]
        text.append(
            f"  validation  {'enabled' if validation['enabled'] else 'disabled'}"
            f"  {len(validation['steps'])} step(s)\n",
            style=SQ_COLORS.text_secondary,
        )
        text.append(f"  store       {summary['observability']['run_store']}\n", style=SQ_COLORS.text_dim)

        issue_checks = [check for check in report.checks if check.status in {"error", "warning"}]
        if issue_checks:
            text.append("\nDoctor\n", style=f"bold {SQ_COLORS.primary_light}")
            for check in issue_checks[:4]:
                style = SQ_COLORS.error if check.status == "error" else SQ_COLORS.warning
                text.append(f"  {check.status:<7}", style=style)
                text.append(f"{check.name}  ", style=SQ_COLORS.info)
                text.append(f"{check.message}\n", style=SQ_COLORS.text_secondary)
                fix = check.data.get("fix")
                if fix and fix != "No action needed.":
                    text.append(f"    fix: {fix}\n", style=SQ_COLORS.text_dim)

        text.append("\nPlanned Graph\n", style=f"bold {SQ_COLORS.primary_light}")
        labels = [node.label for node in graph.nodes]
        text.append(f"  {' -> '.join(labels) if labels else 'empty'}\n", style=SQ_COLORS.text_secondary)

        evidence = self._latest_evidence(FileHarnessStore, build_harness_evidence, spec)
        text.append("\nLast Run\n", style=f"bold {SQ_COLORS.primary_light}")
        if evidence is None:
            text.append("  no persisted harness run yet\n", style=SQ_COLORS.text_dim)
        else:
            run = evidence["run"]
            changes = evidence["changes"] if isinstance(evidence["changes"], dict) else {}
            validation_result = evidence["validation"] if isinstance(evidence["validation"], dict) else {}
            text.append(f"  {run['run_id']}\n", style=SQ_COLORS.info)
            text.append(f"  status      {run['status']}\n", style=SQ_COLORS.text_secondary)
            text.append(
                f"  changes     {int(changes.get('file_count') or 0)} file(s)"
                f" (+{int(changes.get('additions') or 0)} -{int(changes.get('deletions') or 0)})\n",
                style=SQ_COLORS.text_secondary,
            )
            text.append(
                f"  validation  {validation_result.get('status') or 'unknown'}\n",
                style=SQ_COLORS.text_secondary,
            )
            text.append(f"  :harness evidence {run['run_id']}\n", style=SQ_COLORS.text_dim)
            self._append_recent_harness_events(text, FileHarnessStore, spec, run["run_id"])

    def _latest_evidence(self, store_cls, evidence_fn, spec):
        """Return latest persisted evidence for the active spec, if available."""
        try:
            store = store_cls(Path(spec.context.session_storage))
            runs = store.list_runs()
            if not runs:
                return None
            return evidence_fn(store, runs[0].run_id)
        except Exception:
            return None

    def _append_permission_rules(self, text: Text, rules: list[dict]) -> None:
        """Append compact rule-based permission policy details."""
        if not rules:
            text.append("  rules=none\n", style=SQ_COLORS.text_dim)
            return
        text.append(f"  rules={len(rules)}\n", style=SQ_COLORS.text_dim)
        for rule in rules[:4]:
            target = str(rule.get("tool") or "*")
            if rule.get("argument"):
                target += f" {rule['argument']}"
            pattern = rule.get("pattern")
            if pattern:
                target += f"~{pattern}"
            action = str(rule.get("action") or "ask")
            style = (
                SQ_COLORS.error
                if action == "deny"
                else SQ_COLORS.success
                if action == "allow"
                else SQ_COLORS.warning
            )
            text.append("    ", style="")
            text.append(f"{action:<5}", style=style)
            text.append(f" {target}\n", style=SQ_COLORS.text_secondary)
        if len(rules) > 4:
            text.append(f"    +{len(rules) - 4} more rule(s)\n", style=SQ_COLORS.text_dim)

    def _append_remembered_permission_rules(self, text: Text, rules: list[dict]) -> None:
        """Append persisted approval-memory decisions."""
        if not rules:
            return
        text.append(f"  remembered={len(rules)}\n", style=SQ_COLORS.text_dim)
        for rule in rules[:3]:
            action = str(rule.get("action") or "ask")
            style = SQ_COLORS.error if action == "deny" else SQ_COLORS.success
            target = str(rule.get("tool") or "*")
            if rule.get("argument"):
                target += f" {rule['argument']}"
            if rule.get("pattern"):
                target += f"~{rule['pattern']}"
            text.append("    ", style="")
            text.append(f"{action:<5}", style=style)
            text.append(f" remembered {target}\n", style=SQ_COLORS.text_secondary)
        if len(rules) > 3:
            text.append(f"    +{len(rules) - 3} more remembered\n", style=SQ_COLORS.text_dim)

    def _append_hooks(self, text: Text, hooks: dict) -> None:
        """Append declared and built-in hook policy details."""
        declared = list(hooks.get("declared") or [])
        builtin = list(hooks.get("builtin") or [])
        count = int(hooks.get("count") or 0)
        if count <= 0 and hooks.get("enabled", True):
            text.append("  hooks=none\n", style=SQ_COLORS.text_dim)
            return
        state = "enabled" if hooks.get("enabled", True) else "disabled"
        text.append(f"  hooks={count} ({state})\n", style=SQ_COLORS.text_dim)
        for entry in builtin[:2]:
            text.append("    policy ", style=SQ_COLORS.success)
            text.append(
                f"{entry.get('point')}  {entry.get('rules', 0)} rule(s)\n",
                style=SQ_COLORS.text_secondary,
            )
        for entry in declared[:3]:
            text.append("    hook   ", style=SQ_COLORS.info)
            text.append(str(entry.get("point") or "-"), style=SQ_COLORS.text_secondary)
            if entry.get("matcher"):
                text.append(f"  {entry['matcher']}", style=SQ_COLORS.text_dim)
            if entry.get("name"):
                text.append(f"  {entry['name']}", style=SQ_COLORS.text_dim)
            text.append("\n", style="")
        remaining = max(0, len(declared) + len(builtin) - 5)
        if remaining:
            text.append(f"    +{remaining} more hook(s)\n", style=SQ_COLORS.text_dim)

    def _append_recent_harness_events(self, text: Text, store_cls, spec, run_id: str) -> None:
        """Append recent hook/permission harness events for the latest run."""
        try:
            store = store_cls(Path(spec.context.session_storage))
            events = store.get_events(run_id)
        except Exception:
            return
        interesting = [
            event
            for event in events
            if event.type
            in {
                "harness.permission.check",
                "harness.hook.error",
                "harness.compaction.start",
                "harness.compaction.end",
                "harness.stop",
            }
        ]
        if not interesting:
            return
        text.append("  signals\n", style=SQ_COLORS.text_dim)
        for event in interesting[-5:]:
            style = SQ_COLORS.error if event.type == "harness.hook.error" else SQ_COLORS.info
            text.append("    ", style="")
            text.append(event.type.replace("harness.", ""), style=style)
            preview = self._event_preview(event)
            if preview:
                text.append(f"  {preview}", style=SQ_COLORS.text_dim)
            text.append("\n", style="")

    def _event_preview(self, event) -> str:
        """One-line summary for harness sidebar events."""
        data = getattr(event, "data", {}) or {}
        if event.type == "harness.permission.check":
            args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
            keys = args.get("keys") or []
            keys_text = ",".join(str(k) for k in keys[:4])
            return f"{data.get('tool') or '-'} keys={keys_text or '-'}"
        if event.type == "harness.hook.error":
            return f"{data.get('point') or '-'} {data.get('handler') or '-'}"
        if event.type == "harness.stop":
            return str(data.get("stopped_reason") or "-")
        if event.type.startswith("harness.compaction."):
            return str(data.get("strategy") or data.get("tokens") or "")
        return ""

    def _preview_line(self, label: str, values: list[str]) -> str:
        """Render a compact list line for narrow sidebars."""
        if not values:
            return f"  {label:<10}-\n"
        preview = ", ".join(values[:6])
        if len(values) > 6:
            preview += f", +{len(values) - 6}"
        return f"  {label:<10}{preview}\n"

    def refresh_summary(self) -> None:
        """Refresh panel content."""
        try:
            self.query_one("#harness-content", Static).update(self._render_summary())
        except Exception:
            pass


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Data classes
    "AgentInfo",
    "ContextFile",
    "FileDiff",
    "HistoryMessage",
    # Panels
    "AgentPanel",
    "ContextPanel",
    "TerminalPanel",
    "DiffPanel",
    "HistoryPanel",
    "HarnessPanel",
]
