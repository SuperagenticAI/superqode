"""Command palette widget (Ctrl+K) for quick command access - Redesigned for accessibility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static

from superqode.utils.fuzzy import FuzzySearch


@dataclass
class PaletteCommand:
    """A command palette item."""

    id: str
    label: str
    description: str
    icon: str = ""
    shortcut: str = ""
    category: str = "general"
    action: Callable | None = None


# Default palette commands
DEFAULT_PALETTE_COMMANDS: list[PaletteCommand] = [
    # Agent commands
    PaletteCommand(
        "connect_agent",
        "Connect to Agent",
        "Connect to an AI coding agent",
        "🤖",
        "Ctrl+A",
        "agents",
    ),
    PaletteCommand(
        "agent_store", "Agent Store", "Browse available agents", "🛍️", "Ctrl+S", "agents"
    ),
    PaletteCommand(
        "disconnect", "Disconnect", "Disconnect from current agent", "🔌", "Ctrl+D", "agents"
    ),
    # Role commands
    PaletteCommand(
        "dev_mode", "Development Mode", "Switch to dev.fullstack role", "💻", "", "roles"
    ),
    # File commands
    PaletteCommand("open_file", "Open File", "Open a file from project", "📁", "Ctrl+O", "files"),
    PaletteCommand("find_file", "Find File", "Fuzzy search for files", "🔍", "Ctrl+F", "files"),
    PaletteCommand("recent_files", "Recent Files", "Show recently opened files", "📋", "", "files"),
    PaletteCommand("bookmarks", "Bookmarks", "Manage file bookmarks", "🔖", "", "files"),
    # Workflow commands
    PaletteCommand(
        "handoff", "Handoff Work", "Hand off work to another role", "🤝", "Ctrl+H", "workflow"
    ),
    PaletteCommand(
        "context", "View Context", "Show current work context", "📋", "Ctrl+I", "workflow"
    ),
    PaletteCommand("approve", "Approve Work", "Approve work for deployment", "✅", "", "workflow"),
    PaletteCommand("sessions", "View Sessions", "Show pending handoffs", "📂", "", "workflow"),
    # System commands
    PaletteCommand("settings", "Settings", "Open settings", "⚙️", "Ctrl+,", "system"),
    PaletteCommand("help", "Help", "Show help documentation", "❓", "?", "system"),
    PaletteCommand("exit", "Exit", "Exit SuperQode", "🚪", "Ctrl+C", "system"),
]


class PaletteItem(Widget):
    """A single command palette item - high contrast design."""

    DEFAULT_CSS = """
    PaletteItem {
        height: 3;
        padding: 0 1;
        layout: horizontal;
        background: #0a0a0a;
        border-bottom: solid #222222;
    }

    PaletteItem:hover {
        background: #1a3a5a;
    }

    PaletteItem.selected {
        background: #00aaff;
    }

    PaletteItem .icon {
        width: 4;
        height: 3;
        content-align: center middle;
        color: #ffffff;
    }

    PaletteItem .content {
        height: 3;
        padding-left: 1;
    }

    PaletteItem .label {
        text-style: bold;
        color: #ffffff;
    }

    PaletteItem.selected .label {
        color: #000000;
    }

    PaletteItem .description {
        color: #aaaaaa;
    }

    PaletteItem.selected .description {
        color: #000000;
    }

    PaletteItem .shortcut {
        dock: right;
        color: #00ff00;
        text-style: bold;
        width: auto;
        padding-right: 1;
        content-align: center middle;
    }

    PaletteItem.selected .shortcut {
        color: #004400;
    }
    """

    class Selected(Message):
        """Message sent when item is selected."""

        def __init__(self, command: PaletteCommand) -> None:
            self.command = command
            super().__init__()

    selected: reactive[bool] = reactive(False)

    def __init__(self, command: PaletteCommand, **kwargs) -> None:
        super().__init__(**kwargs)
        self.command = command

    def compose(self) -> ComposeResult:
        yield Static(self.command.icon, classes="icon")
        with Vertical(classes="content"):
            yield Static(self.command.label, classes="label")
            yield Static(self.command.description, classes="description")
        if self.command.shortcut:
            yield Static(self.command.shortcut, classes="shortcut")

    def watch_selected(self, selected: bool) -> None:
        self.set_class(selected, "selected")

    def on_click(self) -> None:
        self.post_message(self.Selected(self.command))


class CommandPalette(Widget):
    """
    Command palette overlay (Ctrl+K) - High contrast, accessible design.

    Provides fuzzy-searchable access to all commands.
    """

    DEFAULT_CSS = """
    CommandPalette {
        layer: overlay;
        align: center top;
        margin-top: 3;
        width: 70;
        height: auto;
        max-height: 25;
        background: #000000;
        border: double #00ffff;
        display: none;
    }

    CommandPalette.show-palette {
        display: block;
    }

    CommandPalette #palette-title-bar {
        height: 3;
        background: #001a33;
        padding: 1;
    }

    CommandPalette #palette-title {
        text-style: bold;
        color: #00ffff;
        text-align: center;
    }

    CommandPalette #palette-subtitle {
        color: #888888;
        text-align: center;
    }

    CommandPalette #palette-search-container {
        height: 3;
        padding: 0 1;
        background: #0a0a0a;
        border-bottom: solid #333333;
    }

    CommandPalette #palette-search {
        width: 100%;
        background: #1a1a1a;
        border: tall #00ffff;
        color: #ffffff;
    }

    CommandPalette #palette-search:focus {
        border: tall #00ff00;
        background: #0a1a0a;
    }

    CommandPalette #palette-results {
        height: auto;
        max-height: 16;
        background: #0a0a0a;
    }

    CommandPalette .no-results {
        padding: 2;
        color: #ffff00;
        text-style: bold;
        text-align: center;
        background: #1a1a00;
    }

    CommandPalette #palette-footer {
        height: 2;
        background: #1a1a1a;
        color: #00ff00;
        padding: 0 1;
        border-top: solid #333333;
    }

    CommandPalette #footer-hints {
        text-align: center;
        color: #00ff00;
    }
    """

    class CommandSelected(Message):
        """Message sent when a command is selected."""

        def __init__(self, command: PaletteCommand) -> None:
            self.command = command
            super().__init__()

    class Dismissed(Message):
        """Message sent when palette is dismissed."""

        pass

    # State
    is_visible: reactive[bool] = reactive(False)
    search_text: reactive[str] = reactive("")
    selected_index: reactive[int] = reactive(0)

    def __init__(
        self,
        commands: list[PaletteCommand] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.commands = commands or DEFAULT_PALETTE_COMMANDS
        self.filtered_commands: list[PaletteCommand] = []
        self.fuzzy = FuzzySearch()

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-title-bar"):
            yield Static("🔍 COMMAND PALETTE", id="palette-title")
            yield Static("Type to search commands", id="palette-subtitle")
        with Vertical(id="palette-search-container"):
            yield Input(placeholder="Search commands...", id="palette-search")
        yield VerticalScroll(id="palette-results")
        with Vertical(id="palette-footer"):
            yield Static("↑↓ Navigate  │  Enter Select  │  Esc Close", id="footer-hints")

    def on_mount(self) -> None:
        """Initialize on mount."""
        self._update_filtered_commands()

    def show(self) -> None:
        """Show command palette."""
        self.search_text = ""
        self.selected_index = 0
        self.is_visible = True
        self.add_class("show-palette")
        self._update_filtered_commands()

        # Focus search input
        search_input = self.query_one("#palette-search", Input)
        search_input.value = ""
        search_input.focus()

    def hide(self) -> None:
        """Hide command palette."""
        self.is_visible = False
        self.remove_class("show-palette")
        self.post_message(self.Dismissed())

    def toggle(self) -> None:
        """Toggle palette visibility."""
        if self.is_visible:
            self.hide()
        else:
            self.show()

    @on(Input.Changed, "#palette-search")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        self.search_text = event.value
        self.selected_index = 0
        self._update_filtered_commands()

    @on(Input.Submitted, "#palette-search")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        """Handle search submission."""
        self.select_current()

    def _update_filtered_commands(self) -> None:
        """Update filtered commands based on search text."""
        if self.search_text:
            # Build searchable items (search both label and description)
            items = [(f"{cmd.label} {cmd.description}", cmd) for cmd in self.commands]
            results = self.fuzzy.search_with_data(self.search_text, items, max_results=10)
            self.filtered_commands = [cmd for _, cmd in results]
        else:
            self.filtered_commands = self.commands[:10]

        self._render_commands()

    def _render_commands(self) -> None:
        """Render filtered commands."""
        container = self.query_one("#palette-results", VerticalScroll)
        container.remove_children()

        if not self.filtered_commands:
            container.mount(Static("No matching commands found", classes="no-results"))
            return

        for i, cmd in enumerate(self.filtered_commands):
            item = PaletteItem(cmd, id=f"palette-item-{i}")
            item.selected = i == self.selected_index
            container.mount(item)

    def _update_selection(self) -> None:
        """Update visual selection state."""
        for i, item in enumerate(self.query("#palette-results PaletteItem")):
            if isinstance(item, PaletteItem):
                item.selected = i == self.selected_index

    def move_selection(self, delta: int) -> None:
        """Move selection up or down."""
        if not self.filtered_commands:
            return
        new_index = (self.selected_index + delta) % len(self.filtered_commands)
        self.selected_index = new_index
        self._update_selection()

        # Scroll to make selection visible
        try:
            container = self.query_one("#palette-results", VerticalScroll)
            selected_item = self.query_one(f"#palette-item-{self.selected_index}")
            if selected_item:
                container.scroll_visible(selected_item)
        except Exception:
            pass

    def select_current(self) -> PaletteCommand | None:
        """Select current command."""
        if self.filtered_commands and 0 <= self.selected_index < len(self.filtered_commands):
            cmd = self.filtered_commands[self.selected_index]
            self.post_message(self.CommandSelected(cmd))
            self.hide()
            return cmd
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

    @on(PaletteItem.Selected)
    def on_item_selected(self, event: PaletteItem.Selected) -> None:
        """Handle item selection via click."""
        self.post_message(self.CommandSelected(event.command))
        self.hide()
