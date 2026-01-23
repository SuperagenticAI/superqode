"""Smart prompt widget with completion support."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static

from superqode.widgets.slash_complete import SlashComplete, SlashCommand


class SmartPrompt(Widget):
    """
    Smart input prompt with:
    - Slash command completion (/)
    - Path completion (Tab)
    - History navigation (Up/Down)
    - Multi-line support (Shift+Enter)
    """

    DEFAULT_CSS = """
    SmartPrompt {
        dock: bottom;
        height: auto;
        max-height: 8;
        padding: 0 1 1 1;
        background: #0a0a0a;
    }

    SmartPrompt #prompt-row {
        height: auto;
        min-height: 3;
        background: #0a0a0a;
    }

    SmartPrompt #prompt-prefix {
        height: 3;
        width: auto;
        color: #00ffff;
        text-style: bold;
        padding: 0 1 0 0;
        background: #001a33;
        content-align: center middle;
    }

    SmartPrompt #prompt-input {
        height: auto;
        min-height: 3;
        background: #1a1a1a;
        border: double #00ffff;
        padding: 0 1;
        color: #ffffff;
    }

    SmartPrompt #prompt-input:focus {
        border: double #00ff00;
        background: #0a1a0a;
    }

    SmartPrompt #suggestions-row {
        height: auto;
        max-height: 3;
        margin-top: 1;
        display: none;
        background: #1a1a1a;
    }

    SmartPrompt #suggestions-row.visible {
        display: block;
    }

    SmartPrompt .suggestion {
        color: #00ff00;
        padding: 0 1;
        background: #1a1a1a;
    }

    SmartPrompt .suggestion.selected {
        color: #00ffff;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("enter", "submit", "Submit", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("up", "history_prev", "Previous", show=False),
        Binding("down", "history_next", "Next", show=False),
        Binding("tab", "complete", "Complete", show=False),
    ]

    class Submitted(Message):
        """Message sent when input is submitted."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    class SlashTriggered(Message):
        """Message sent when slash command mode is triggered."""

        def __init__(self, query: str) -> None:
            self.query = query
            super().__init__()

    # State
    value: reactive[str] = reactive("")
    prefix: reactive[str] = reactive("superqode")
    mode_suffix: reactive[str] = reactive("HOME")
    placeholder: reactive[str] = reactive("Type a message or / for commands...")

    def __init__(
        self,
        prefix: str = "superqode",
        mode_suffix: str = "HOME",
        placeholder: str = "Type a message or / for commands...",
        on_submit: Callable[[str], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.prefix = prefix
        self.mode_suffix = mode_suffix
        self.placeholder = placeholder
        self._on_submit = on_submit
        self._history: list[str] = []
        self._history_index: int = -1
        self._suggestions: list[str] = []
        self._suggestion_index: int = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="prompt-row"):
                yield Static(self._get_prefix_text(), id="prompt-prefix")
                yield Input(
                    placeholder=self.placeholder,
                    id="prompt-input",
                )
            with Horizontal(id="suggestions-row"):
                yield Static("", id="suggestions-display", classes="suggestion")

    def _get_prefix_text(self) -> str:
        """Get the formatted prefix text."""
        return f"{self.prefix} {self.mode_suffix} >"

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one("#prompt-input", Input).focus()

    def watch_prefix(self, prefix: str) -> None:
        """React to prefix changes."""
        self._update_prefix()

    def watch_mode_suffix(self, mode_suffix: str) -> None:
        """React to mode suffix changes."""
        self._update_prefix()

    def _update_prefix(self) -> None:
        """Update the prefix display."""
        try:
            prefix_widget = self.query_one("#prompt-prefix", Static)
            prefix_widget.update(self._get_prefix_text())
        except Exception:
            # Widget not yet composed
            pass

    @on(Input.Changed, "#prompt-input")
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes."""
        self.value = event.value

        # Check for slash command trigger
        if event.value.startswith("/"):
            self.post_message(self.SlashTriggered(event.value))

    @on(Input.Submitted, "#prompt-input")
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        value = event.value.strip()
        if value:
            # Add to history
            if not self._history or self._history[-1] != value:
                self._history.append(value)
            self._history_index = -1

            # Clear input
            input_widget = self.query_one("#prompt-input", Input)
            input_widget.value = ""

            # Post message
            self.post_message(self.Submitted(value))

            # Call callback if provided
            if self._on_submit:
                self._on_submit(value)

    def action_submit(self) -> None:
        """Submit the current input."""
        input_widget = self.query_one("#prompt-input", Input)
        if input_widget.value.strip():
            self.on_input_submitted(Input.Submitted(input_widget, input_widget.value))

    def action_cancel(self) -> None:
        """Cancel current input / close completions."""
        input_widget = self.query_one("#prompt-input", Input)
        input_widget.value = ""
        self._hide_suggestions()

    def action_history_prev(self) -> None:
        """Navigate to previous history item."""
        if not self._history:
            return

        if self._history_index < 0:
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1

        input_widget = self.query_one("#prompt-input", Input)
        input_widget.value = self._history[self._history_index]
        input_widget.cursor_position = len(input_widget.value)

    def action_history_next(self) -> None:
        """Navigate to next history item."""
        if not self._history or self._history_index < 0:
            return

        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            input_widget = self.query_one("#prompt-input", Input)
            input_widget.value = self._history[self._history_index]
            input_widget.cursor_position = len(input_widget.value)
        else:
            self._history_index = -1
            input_widget = self.query_one("#prompt-input", Input)
            input_widget.value = ""

    def action_complete(self) -> None:
        """Trigger tab completion."""
        input_widget = self.query_one("#prompt-input", Input)
        value = input_widget.value

        # If we have suggestions, cycle through them
        if self._suggestions:
            self._suggestion_index = (self._suggestion_index + 1) % len(self._suggestions)
            # Apply suggestion
            suggestion = self._suggestions[self._suggestion_index]
            input_widget.value = suggestion
            input_widget.cursor_position = len(suggestion)
            self._show_suggestions()
            return

        # Try path completion
        if " " in value:
            # Complete the last token as a path
            parts = value.rsplit(" ", 1)
            prefix = parts[0] + " "
            path_query = parts[1] if len(parts) > 1 else ""
            completions = self._get_path_completions(path_query)
            if completions:
                self._suggestions = [prefix + c for c in completions]
                self._suggestion_index = 0
                input_widget.value = self._suggestions[0]
                input_widget.cursor_position = len(input_widget.value)
                self._show_suggestions()

    def _get_path_completions(self, query: str) -> list[str]:
        """Get file path completions for the query."""
        try:
            if not query:
                # List current directory
                cwd = Path.cwd()
                return [p.name + ("/" if p.is_dir() else "") for p in cwd.iterdir()][:10]

            # Expand path
            path = Path(query).expanduser()

            if path.is_dir():
                # List directory contents
                return [
                    query.rstrip("/") + "/" + p.name + ("/" if p.is_dir() else "")
                    for p in path.iterdir()
                ][:10]

            # Complete partial filename
            parent = path.parent
            prefix = path.name

            if parent.is_dir():
                matches = [
                    str(parent / p.name) + ("/" if p.is_dir() else "")
                    for p in parent.iterdir()
                    if p.name.lower().startswith(prefix.lower())
                ]
                return matches[:10]

        except (OSError, PermissionError):
            pass

        return []

    def _show_suggestions(self) -> None:
        """Show the suggestions display."""
        if not self._suggestions:
            self._hide_suggestions()
            return

        suggestions_row = self.query_one("#suggestions-row", Horizontal)
        suggestions_row.add_class("visible")

        display = self.query_one("#suggestions-display", Static)
        # Show current suggestion index and total
        text = f"Tab: {self._suggestion_index + 1}/{len(self._suggestions)}"
        display.update(text)

    def _hide_suggestions(self) -> None:
        """Hide the suggestions display."""
        self._suggestions = []
        self._suggestion_index = 0
        suggestions_row = self.query_one("#suggestions-row", Horizontal)
        suggestions_row.remove_class("visible")

    def set_value(self, value: str) -> None:
        """Set the input value programmatically."""
        input_widget = self.query_one("#prompt-input", Input)
        input_widget.value = value
        input_widget.cursor_position = len(value)
        self.value = value

    def clear(self) -> None:
        """Clear the input."""
        input_widget = self.query_one("#prompt-input", Input)
        input_widget.value = ""
        self.value = ""
        self._hide_suggestions()

    def focus_input(self) -> None:
        """Focus the input widget."""
        self.query_one("#prompt-input", Input).focus()

    def set_mode(self, mode: str) -> None:
        """Set the mode suffix."""
        self.mode_suffix = mode

    def insert_command(self, command: str) -> None:
        """Insert a slash command into the input."""
        input_widget = self.query_one("#prompt-input", Input)
        input_widget.value = command
        input_widget.cursor_position = len(command)
        self.value = command
        input_widget.focus()
