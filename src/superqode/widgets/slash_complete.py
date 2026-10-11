"""Slash command completion overlay widget - Redesigned for accessibility."""

from __future__ import annotations


from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from superqode.app.constants import CONNECT_COMPLETION_COMMANDS
from superqode.utils.fuzzy import FuzzySearch


from superqode.command_registry import DEFAULT_COMMANDS, SlashCommand


def _command_sort_key(query: str, command: str) -> tuple[int, str]:
    query = query.lower()
    command = command.lower()
    priority: dict[str, dict[str, int]] = {
        # Mirrors the root :connect screen: the three ways to run a model,
        # then the subscription submenu.
        ":c": {
            ":connect": 0,
            ":connect local": 1,
            ":connect acp": 2,
            ":connect byok": 3,
            ":connect subscriptions": 4,
            ":clear": 20,
        },
        ":co": {
            ":connect": 0,
            ":connect local": 1,
            ":connect acp": 2,
            ":connect byok": 3,
            ":connect subscriptions": 4,
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
            ":connect local": 1,
            ":connect acp": 2,
            ":connect byok": 3,
            ":connect subscriptions": 4,
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
        connect_order = list(CONNECT_COMPLETION_COMMANDS)
        by_command = {command.command: command for command in commands}
        ordered = [by_command[command] for command in connect_order if command in by_command]
        ordered.extend(
            command
            for command in commands
            if command.command.startswith(":connect ") and command.command not in connect_order
        )
        return ordered[:max_results]
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
        background: #2a1a3a;
    }

    SlashCompleteItem.selected {
        background: #a855f7;
    }

    SlashCompleteItem .command {
        color: #ec4899;
        text-style: bold;
        min-width: 24;
        width: 24;
    }

    SlashCompleteItem.selected .command {
        color: #ffffff;
        text-style: bold;
    }

    SlashCompleteItem .description {
        color: #ffffff;
    }

    SlashCompleteItem.selected .description {
        color: #ffffff;
        text-style: bold;
    }

    SlashCompleteItem .shortcut {
        dock: right;
        color: #fbbf24;
        text-style: bold;
        min-width: 10;
    }

    SlashCompleteItem.selected .shortcut {
        color: #ffffff;
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

    def on_mount(self) -> None:
        """Apply live colors after composed child widgets are available."""
        self.refresh_theme_colors()

    def refresh_theme_colors(self) -> None:
        """Re-resolve brand colors from the live THEME palette.

        Widget CSS is static, so a ``:theme`` switch would otherwise leave
        this overlay on the old palette until restart. Called on mount,
        on selection change, and by the app after a theme switch.
        """
        try:
            from superqode.app.constants import THEME

            selected = bool(self.selected)
            self.styles.background = THEME.get("purple", "#a855f7") if selected else "#0a0a0a"
            for child in self.query(Static):
                classes = child.classes
                if "command" in classes:
                    child.styles.color = "#ffffff" if selected else THEME.get("pink", "#ec4899")
                elif "description" in classes:
                    child.styles.color = "#ffffff"
                elif "shortcut" in classes:
                    child.styles.color = "#ffffff" if selected else THEME.get("gold", "#fbbf24")
        except Exception:
            pass

    def watch_selected(self, selected: bool) -> None:
        self.set_class(selected, "selected")
        if self.is_mounted:
            self.refresh_theme_colors()

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
        border: double #a855f7;
        display: none;
    }

    SlashComplete.visible {
        display: block;
    }

    SlashComplete #slash-header {
        height: 2;
        background: #1a0f2e;
        color: #ec4899;
        padding: 0 1;
        text-style: bold;
    }

    SlashComplete #slash-title {
        color: #ec4899;
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
        color: #fbbf24;
        text-style: bold;
        text-align: center;
        background: #2a1f0a;
    }

    SlashComplete #slash-footer {
        height: 1;
        background: #1a1a1a;
        color: #f97316;
        padding: 0 1;
        text-align: center;
        border-top: solid #a855f7;
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
        self.refresh_theme_colors()

    def refresh_theme_colors(self) -> None:
        """Re-resolve container chrome from the live THEME palette.

        Called on mount, on every show (so it is always current), and by
        the app after a ``:theme`` switch.
        """
        try:
            from superqode.app.constants import THEME

            purple = THEME.get("purple", "#a855f7")
            self.styles.border = ("double", purple)
            header = self.query_one("#slash-header", Vertical)
            header.styles.color = THEME.get("pink", "#ec4899")
            self.query_one("#slash-title", Static).styles.color = THEME.get("pink", "#ec4899")
            self.query_one("#slash-hint", Static).styles.color = THEME.get("muted", "#888888")
            footer = self.query_one("#slash-footer", Static)
            footer.styles.color = THEME.get("orange", "#f97316")
            footer.styles.border_top = ("solid", purple)
            for item in self.query("SlashCompleteItem"):
                if isinstance(item, SlashCompleteItem):
                    item.refresh_theme_colors()
        except Exception:
            pass

    def show(self, initial_query: str = "/") -> None:
        """Show slash completion overlay."""
        self.selected_index = 0
        self.is_visible = True
        self.add_class("visible")
        self.refresh_theme_colors()
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
