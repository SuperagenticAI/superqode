"""Slash command completion overlay widget - Redesigned for accessibility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from superqode.utils.fuzzy import FuzzySearch


@dataclass
class SlashCommand:
    """A slash command definition."""

    command: str  # e.g., "/handoff"
    description: str  # e.g., "Hand off work to another role"
    shortcut: str = ""  # e.g., "Ctrl+H"
    category: str = "general"  # For grouping
    action: Callable | None = None  # Optional action callback


# Default slash commands
DEFAULT_COMMANDS: list[SlashCommand] = [
    # Role commands
    SlashCommand("/dev", "Switch to development mode", category="roles"),
    SlashCommand("/dev fullstack", "Start full-stack development", category="roles"),
    # Agent commands
    SlashCommand("/agents", "List available agents", "Ctrl+A", category="agents"),
    SlashCommand("/store", "Open agent marketplace", "Ctrl+S", category="agents"),
    SlashCommand("/agents store", "Browse agent marketplace", category="agents"),
    SlashCommand("/agents connect", "Connect to an agent", category="agents"),
    SlashCommand("/agents install", "Install an agent", category="agents"),
    # File commands
    SlashCommand("/files", "Show project files", "Ctrl+O", category="files"),
    SlashCommand("/find", "Fuzzy search files", "Ctrl+F", category="files"),
    SlashCommand("/recent", "Show recent files", category="files"),
    SlashCommand("/open", "Open a file or bookmark", category="files"),
    SlashCommand("/bookmark", "Manage bookmarks", category="files"),
    # Workflow commands
    SlashCommand("/handoff", "Hand off work to another role", "Ctrl+H", category="workflow"),
    SlashCommand("/context", "View/update work context", "Ctrl+I", category="workflow"),
    SlashCommand("/approve", "Approve a pending tool call", category="workflow"),
    SlashCommand("/reject", "Reject a pending tool call", category="workflow"),
    SlashCommand(
        ":permissions", "Show permission policy and pending approvals", category="workflow"
    ),
    SlashCommand(":policy", "Show permission policy", category="workflow"),
    SlashCommand("/harness", "Load or inspect a HarnessSpec", category="workflow"),
    SlashCommand(":harness", "Load or inspect a HarnessSpec", category="workflow"),
    SlashCommand("/harness inspect", "Summarize the active HarnessSpec", category="workflow"),
    SlashCommand(":harness inspect", "Summarize the active HarnessSpec", category="workflow"),
    SlashCommand("/harness templates", "List HarnessSpec templates", category="workflow"),
    SlashCommand(":harness templates", "List HarnessSpec templates", category="workflow"),
    SlashCommand("/harness doctor", "Check active or selected harness", category="workflow"),
    SlashCommand(":harness doctor", "Check active or selected harness", category="workflow"),
    SlashCommand("/harness graph", "Show the planned harness graph", category="workflow"),
    SlashCommand(":harness graph", "Show the planned harness graph", category="workflow"),
    SlashCommand("/harness replay", "Show replay plan for a persisted run", category="workflow"),
    SlashCommand(":harness replay", "Show replay plan for a persisted run", category="workflow"),
    SlashCommand("/harness fork", "Fork a persisted run at an event index", category="workflow"),
    SlashCommand(":harness fork", "Fork a persisted run at an event index", category="workflow"),
    SlashCommand("/harness evidence", "Show run evidence and validation", category="workflow"),
    SlashCommand(":harness evidence", "Show run evidence and validation", category="workflow"),
    SlashCommand("/harness events", "Show persisted run event timeline", category="workflow"),
    SlashCommand(":harness events", "Show persisted run event timeline", category="workflow"),
    SlashCommand("/harness runs", "List persisted harness runs", category="workflow"),
    SlashCommand(":harness runs", "List persisted harness runs", category="workflow"),
    SlashCommand("/runtime", "List or switch runtime backends", category="workflow"),
    SlashCommand(":codex", "Connect to Codex SDK runtime", category="workflow"),
    SlashCommand(":codex status", "Show Codex SDK/app-server status", category="workflow"),
    SlashCommand(":codex models", "List Codex account models", category="workflow"),
    SlashCommand(":codex model", "Pick or set Codex model for future turns", category="workflow"),
    SlashCommand(":codex effort", "Pick or set Codex reasoning effort", category="workflow"),
    SlashCommand(":codex sandbox", "Set Codex sandbox override", category="workflow"),
    SlashCommand(":codex review", "Run a read-only Codex diff review", category="workflow"),
    SlashCommand(":codex compact", "Compact the current Codex thread", category="workflow"),
    SlashCommand(":codex sessions", "List Codex sessions for this repo", category="workflow"),
    SlashCommand(":codex resume", "Resume a Codex thread", category="workflow"),
    SlashCommand(":codex fork", "Fork a Codex thread", category="workflow"),
    SlashCommand(":antigravity", "Show Antigravity CLI launch handoff", category="workflow"),
    SlashCommand(":antigravity status", "Check local agy CLI status", category="workflow"),
    SlashCommand(":antigravity migrate", "Show Gemini CLI migration steps", category="workflow"),
    SlashCommand(":agy", "Alias for Antigravity CLI commands", category="workflow"),
    SlashCommand("/status", "Show runtime, model, harness, and session", category="workflow"),
    SlashCommand("/usage", "Show latest run usage and latency", category="workflow"),
    SlashCommand("/sessions", "List saved sessions", category="workflow"),
    SlashCommand("/resume", "Resume latest or selected session", category="workflow"),
    SlashCommand(":diff", "Open current diff review", category="workflow"),
    SlashCommand(":diff files", "List changed files", category="workflow"),
    SlashCommand(":diff split", "Use side-by-side diff mode", category="workflow"),
    SlashCommand(":diff unified", "Use unified diff mode", category="workflow"),
    SlashCommand(":transcript", "Open selectable conversation transcript", category="workflow"),
    SlashCommand(":timeline", "Open session timeline replay", category="workflow"),
    SlashCommand(":rewind", "Edit & resend a previous message (Esc Esc)", category="workflow"),
    SlashCommand(":paste", "Attach an image from clipboard or path", category="workflow"),
    SlashCommand(":queue", "Show queued type-ahead messages", category="workflow"),
    SlashCommand(":queue clear", "Clear queued messages", category="workflow"),
    SlashCommand(":stash", "Restore a stashed prompt draft (Ctrl+G to stash)", category="workflow"),
    SlashCommand(":stash list", "List stashed prompt drafts", category="workflow"),
    SlashCommand(":session", "Show current session info", category="workflow"),
    SlashCommand(":session rename", "Rename the current session", category="workflow"),
    SlashCommand(":update", "Check for a newer SuperQode release", category="workflow"),
    SlashCommand(":copy transcript", "Copy the conversation transcript", category="workflow"),
    SlashCommand(
        ":select transcript", "Open selectable conversation transcript", category="workflow"
    ),
    SlashCommand("/mcp", "Show MCP status", category="workflow"),
    SlashCommand("/mcp connect", "Connect configured MCP servers", category="workflow"),
    SlashCommand("/mcp tools", "List connected MCP tools", category="workflow"),
    SlashCommand("/connect", "Choose ACP, BYOK, or local connection", category="workflow"),
    SlashCommand(":connect", "Choose ACP, BYOK, or local connection", category="workflow"),
    SlashCommand(":connect acp", "Connect to ACP agent", category="workflow"),
    SlashCommand(":connect antigravity", "Connect via local Antigravity CLI handoff", category="workflow"),
    SlashCommand("/connect byok", "Connect to BYOK provider/model", category="workflow"),
    SlashCommand(":connect byok", "Connect to BYOK provider/model", category="workflow"),
    SlashCommand("/connect local", "Connect to local model provider", category="workflow"),
    SlashCommand(":connect local", "Connect to local model provider", category="workflow"),
    SlashCommand("/model", "Show or switch models", category="workflow"),
    SlashCommand("/tools", "Show active tool profile", category="workflow"),
    SlashCommand("/skills", "List local skills", category="workflow"),
    SlashCommand("/skills add", "Create a local skill template", category="workflow"),
    SlashCommand("/skills import", "Import a local skill file or directory", category="workflow"),
    SlashCommand("/attach", "Insert file or URL reference into prompt", category="workflow"),
    SlashCommand("/prompt", "Load prompt text from a file", category="workflow"),
    # System commands
    SlashCommand("/settings", "Open settings", "Ctrl+,", category="system"),
    SlashCommand("/help", "Show help", "?", category="system"),
    SlashCommand("/disconnect", "Disconnect from agent", "Ctrl+D", category="system"),
    SlashCommand("/exit", "Exit SuperQode", "Ctrl+C", category="system"),
    SlashCommand(":exit", "Exit SuperQode", "Ctrl+C", category="system"),
    SlashCommand(":quit", "Exit SuperQode", "Ctrl+C", category="system"),
]


def _command_sort_key(query: str, command: str) -> tuple[int, str]:
    query = query.lower()
    command = command.lower()
    priority: dict[str, dict[str, int]] = {
        ":c": {
            ":connect": 0,
            ":connect acp": 1,
            ":connect antigravity": 2,
            ":connect byok": 3,
            ":connect local": 4,
            ":clear": 20,
        },
        ":co": {
            ":connect": 0,
            ":connect acp": 1,
            ":connect antigravity": 2,
            ":connect byok": 3,
            ":connect local": 4,
        },
        ":q": {
            ":quit": 0,
        },
        ":d": {
            ":diff": 0,
            ":diff files": 1,
            ":diff unified": 2,
            ":diff split": 3,
        },
        ":e": {
            ":exit": 0,
        },
        ":": {
            ":connect": 0,
            ":connect acp": 1,
            ":connect antigravity": 2,
            ":connect byok": 3,
            ":connect local": 4,
            ":exit": 5,
            ":quit": 6,
        },
    }
    for prefix, scores in priority.items():
        if query.startswith(prefix):
            return (scores.get(command, 10), command)
    return (10, command)


def filter_slash_commands(
    commands: list[SlashCommand],
    query: str,
    *,
    max_results: int = 10,
) -> list[SlashCommand]:
    """Filter slash/colon commands with prefix matches before fuzzy matches."""
    if not query:
        return commands[:max_results]

    query_lower = query.lower()
    if query_lower in {":c", ":co", ":con", ":conn", ":conne", ":connec"}:
        connect_order = [
            ":connect",
            ":connect acp",
            ":connect antigravity",
            ":connect byok",
            ":connect local",
        ]
        by_command = {command.command: command for command in commands}
        return [by_command[command] for command in connect_order if command in by_command][
            :max_results
        ]
    seen: set[str] = set()
    prefix_matches = []
    for command in commands:
        if not command.command.lower().startswith(query_lower):
            continue
        if command.command in seen:
            continue
        seen.add(command.command)
        prefix_matches.append(command)
    prefix_matches = sorted(
        prefix_matches,
        key=lambda command: _command_sort_key(query_lower, command.command),
    )
    if len(prefix_matches) >= max_results:
        return prefix_matches[:max_results]

    fuzzy = FuzzySearch()
    prefix_set = {command.command for command in prefix_matches}
    fuzzy_items = [
        (command.command, command) for command in commands if command.command not in prefix_set
    ]
    fuzzy_matches = [
        command
        for _, command in fuzzy.search_with_data(
            query,
            fuzzy_items,
            max_results=max_results - len(prefix_matches),
        )
    ]
    return [*prefix_matches, *fuzzy_matches]


class SlashCompleteItem(Widget):
    """A single slash command completion item - high contrast design."""

    DEFAULT_CSS = """
    SlashCompleteItem {
        height: 2;
        padding: 0 1;
        layout: horizontal;
        background: #0a0a0a;
        border-bottom: solid #1a1a1a;
    }

    SlashCompleteItem:hover {
        background: #1a3a5a;
    }

    SlashCompleteItem.selected {
        background: #00ffff;
    }

    SlashCompleteItem .command {
        color: #ffff00;
        text-style: bold;
        min-width: 24;
        width: 24;
    }

    SlashCompleteItem.selected .command {
        color: #000000;
        text-style: bold;
    }

    SlashCompleteItem .description {
        color: #ffffff;
    }

    SlashCompleteItem.selected .description {
        color: #000000;
        text-style: bold;
    }

    SlashCompleteItem .shortcut {
        dock: right;
        color: #00ff00;
        text-style: bold;
        min-width: 10;
    }

    SlashCompleteItem.selected .shortcut {
        color: #004400;
    }
    """

    class Click(Message):
        """Message sent when item is clicked."""

        def __init__(self, widget: "SlashCompleteItem") -> None:
            self.widget = widget
            super().__init__()

    selected: reactive[bool] = reactive(False)

    def __init__(self, command: SlashCommand, **kwargs) -> None:
        super().__init__(**kwargs)
        self.command = command

    def compose(self) -> ComposeResult:
        yield Static(self.command.command, classes="command")
        yield Static(self.command.description, classes="description")
        if self.command.shortcut:
            yield Static(self.command.shortcut, classes="shortcut")

    def watch_selected(self, selected: bool) -> None:
        self.set_class(selected, "selected")

    def on_click(self) -> None:
        self.post_message(self.Click(self))


class SlashComplete(Widget):
    """
    Slash command completion overlay - High contrast, accessible design.

    Shows when user types "/" and provides fuzzy-filtered command suggestions.
    """

    DEFAULT_CSS = """
    SlashComplete {
        layer: overlay;
        dock: bottom;
        height: auto;
        max-height: 16;
        margin: 0 2 4 2;
        background: #000000;
        border: double #00ffff;
        display: none;
    }

    SlashComplete.visible {
        display: block;
    }

    SlashComplete #slash-header {
        height: 2;
        background: #001a33;
        color: #00ffff;
        padding: 0 1;
        text-style: bold;
    }

    SlashComplete #slash-title {
        color: #00ffff;
        text-style: bold;
    }

    SlashComplete #slash-hint {
        color: #888888;
    }

    SlashComplete #slash-list {
        height: auto;
        max-height: 12;
        background: #0a0a0a;
    }

    SlashComplete .no-results {
        padding: 1;
        color: #ffff00;
        text-style: bold;
        text-align: center;
        background: #1a1a00;
    }

    SlashComplete #slash-footer {
        height: 1;
        background: #1a1a1a;
        color: #00ff00;
        padding: 0 1;
        text-align: center;
        border-top: solid #333333;
    }
    """

    class CommandSelected(Message):
        """Message sent when a command is selected."""

        def __init__(self, command: SlashCommand) -> None:
            self.command = command
            super().__init__()

    class Dismissed(Message):
        """Message sent when the overlay is dismissed."""

        pass

    # State
    is_visible: reactive[bool] = reactive(False)
    search_query: reactive[str] = reactive("")
    selected_index: reactive[int] = reactive(0)

    def __init__(
        self,
        commands: list[SlashCommand] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.commands = commands or DEFAULT_COMMANDS
        self.filtered_commands: list[SlashCommand] = []
        self.fuzzy = FuzzySearch()
        self._render_counter = 0  # Unique ID counter to prevent duplicates

    def compose(self) -> ComposeResult:
        with Vertical(id="slash-header"):
            yield Static("⚡ SLASH COMMANDS", id="slash-title")
            yield Static("Type to filter commands", id="slash-hint")
        yield VerticalScroll(id="slash-list")
        yield Static("↑↓ Navigate  │  Enter Select  │  Esc Close", id="slash-footer")

    def on_mount(self) -> None:
        """Initialize on mount."""
        self._update_filtered_commands()

    def show(self, initial_query: str = "/") -> None:
        """Show slash completion overlay."""
        self.selected_index = 0
        self.is_visible = True
        self.add_class("visible")
        # Force update if query is the same (watcher won't trigger on same value)
        if self.search_query == initial_query:
            self._update_filtered_commands()
        else:
            # Setting search_query triggers watch_search_query which calls _update_filtered_commands
            self.search_query = initial_query
        self.focus()

    def hide(self) -> None:
        """Hide slash completion overlay."""
        self.is_visible = False
        self.remove_class("visible")
        self.post_message(self.Dismissed())

    def watch_search_query(self, search_query: str) -> None:
        """React to search query changes."""
        if not self.is_mounted:
            return
        self.selected_index = 0
        self._update_filtered_commands()

    def watch_selected_index(self, index: int) -> None:
        """React to selection changes."""
        if not self.is_mounted:
            return
        self._update_selection()

    def _update_filtered_commands(self) -> None:
        """Update the filtered command list based on query."""
        self.filtered_commands = filter_slash_commands(self.commands, self.search_query)

        self._render_commands()

    def _render_commands(self) -> None:
        """Render the filtered commands in the list."""
        self._render_counter += 1
        render_id = self._render_counter

        container = self.query_one("#slash-list", VerticalScroll)
        container.remove_children()

        if not self.filtered_commands:
            container.mount(Static("No matching commands found", classes="no-results"))
            return

        for i, cmd in enumerate(self.filtered_commands):
            # Use render counter in ID to ensure uniqueness across renders
            item = SlashCompleteItem(cmd, id=f"slash-item-{render_id}-{i}")
            item.selected = i == self.selected_index
            container.mount(item)

    def _update_selection(self) -> None:
        """Update the visual selection state."""
        for i, item in enumerate(self.query("#slash-list SlashCompleteItem")):
            if isinstance(item, SlashCompleteItem):
                item.selected = i == self.selected_index

    def move_selection(self, delta: int) -> None:
        """Move selection up or down."""
        if not self.filtered_commands:
            return
        new_index = (self.selected_index + delta) % len(self.filtered_commands)
        self.selected_index = new_index

        # Scroll to make selection visible
        try:
            container = self.query_one("#slash-list", VerticalScroll)
            items = list(self.query("#slash-list SlashCompleteItem"))
            if 0 <= self.selected_index < len(items):
                container.scroll_visible(items[self.selected_index])
        except Exception:
            pass

    def select_current(self) -> SlashCommand | None:
        """Select the currently highlighted command."""
        if self.filtered_commands and 0 <= self.selected_index < len(self.filtered_commands):
            cmd = self.filtered_commands[self.selected_index]
            self.post_message(self.CommandSelected(cmd))
            self.hide()
            return cmd
        return None

    def update_query(self, query: str) -> None:
        """Update the search query."""
        self.search_query = query

    @on(SlashCompleteItem.Click)
    def on_item_click(self, event: SlashCompleteItem.Click) -> None:
        """Handle item click."""
        # Find the clicked item's index
        for i, item in enumerate(self.query("#slash-list SlashCompleteItem")):
            if item is event.widget:
                self.selected_index = i
                self.select_current()
                break
