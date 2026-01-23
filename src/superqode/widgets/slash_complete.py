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
    SlashCommand("/approve", "Approve work for deployment", category="workflow"),
    # System commands
    SlashCommand("/settings", "Open settings", "Ctrl+,", category="system"),
    SlashCommand("/help", "Show help", "?", category="system"),
    SlashCommand("/disconnect", "Disconnect from agent", "Ctrl+D", category="system"),
    SlashCommand("/exit", "Exit SuperQode", "Ctrl+C", category="system"),
]


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
        # Remove leading "/" for search
        search_text = self.search_query.lstrip("/")

        # Build searchable items
        items = [(cmd.command.lstrip("/"), cmd) for cmd in self.commands]

        if search_text:
            # Fuzzy search
            results = self.fuzzy.search_with_data(
                search_text,
                items,
                max_results=10,
            )
            self.filtered_commands = [cmd for _, cmd in results]
        else:
            # Show all commands (limited)
            self.filtered_commands = self.commands[:10]

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
