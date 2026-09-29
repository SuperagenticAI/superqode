"""Interactive prompt history search modal.

Allows searching past prompts and commands using substring/fuzzy filtering.
Selecting an entry loads it directly into the prompt input box.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence, Union

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from superqode.history import HistoryEntry

try:
    from superqode.design_system import COLORS as SQ_COLORS
except ImportError:

    class SQ_COLORS:
        primary = "#7c3aed"
        primary_light = "#a855f7"
        text_primary = "#fafafa"
        text_secondary = "#e4e4e7"
        text_muted = "#a1a1aa"
        text_dim = "#71717a"
        bg_elevated = "#0a0a0a"
        border_default = "#27272a"
        accent_blue = "#06b6d4"


class HistorySearchModal(ModalScreen[Optional[str]]):
    """Fuzzy/interactive search over prompt history."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Select", show=False),
    ]

    CSS = """
    HistorySearchModal {
        align: center middle;
    }

    HistorySearchModal > Vertical {
        width: 82;
        height: auto;
        max-height: 85%;
        background: #0a0a0a;
        border: round #7c3aed;
        padding: 1 2;
    }

    HistorySearchModal .title {
        text-align: center;
        color: #a855f7;
        text-style: bold;
        height: 1;
    }

    HistorySearchModal .subtitle {
        text-align: center;
        color: #a1a1aa;
        height: 1;
        margin-bottom: 1;
    }

    HistorySearchModal #history-search-input {
        background: #18181b;
        border: solid #3f3f46;
        color: #fafafa;
        margin-bottom: 1;
    }

    HistorySearchModal #history-search-input:focus {
        border: solid #a855f7;
    }

    HistorySearchModal #history-list {
        height: auto;
        max-height: 14;
        background: #000000;
        border: solid #27272a;
    }

    HistorySearchModal #history-list:focus {
        border: solid #7c3aed;
    }

    HistorySearchModal .hints {
        text-align: center;
        color: #71717a;
        height: 1;
        margin-top: 1;
    }
    """

    def __init__(self, entries: Sequence[Union[HistoryEntry, str]] = ()) -> None:
        super().__init__()
        # De-duplicate while preserving reverse chronological order
        seen = set()
        clean_entries: list[tuple[str, Optional[float], str]] = []
        for item in reversed(entries):
            if isinstance(item, HistoryEntry):
                text = item.input.strip()
                ts = item.timestamp
                mode = item.mode
            else:
                text = str(item).strip()
                ts = None
                mode = "build"

            if text and text not in seen:
                seen.add(text)
                clean_entries.append((text, ts, mode))

        self._all_entries = clean_entries
        self._filtered_entries: list[tuple[str, Optional[float], str]] = list(clean_entries[:100])

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("📜  Prompt History Search", classes="title")
            yield Static("Search previous prompts and commands", classes="subtitle")
            yield Input(
                placeholder="Type to filter history...",
                id="history-search-input",
            )
            yield OptionList(*self._build_options(""), id="history-list")
            yield Static(
                "↑↓ navigate   •   Enter select   •   Esc cancel",
                classes="hints",
            )

    def on_mount(self) -> None:
        search_input = self.query_one("#history-search-input", Input)
        search_input.focus()

    def _build_options(self, query: str) -> list[Option]:
        query_lower = query.lower().strip()
        filtered: list[tuple[str, Optional[float], str]] = []

        for text, ts, mode in self._all_entries:
            if not query_lower or query_lower in text.lower():
                filtered.append((text, ts, mode))
                if len(filtered) >= 50:
                    break

        self._filtered_entries = filtered
        options: list[Option] = []

        if not filtered:
            msg = Text("  No matching history", style="#71717a")
            options.append(Option(msg, disabled=True))
            return options

        for text, ts, mode in filtered:
            opt_text = Text()
            # Timestamp or bullet
            if ts:
                try:
                    dt = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
                    opt_text.append(f"{dt} ", style="#71717a")
                except Exception:
                    opt_text.append("• ", style="#71717a")
            else:
                opt_text.append("• ", style="#71717a")

            # Highlight query matches in text
            display_text = " ".join(text.splitlines())
            if len(display_text) > 60:
                display_text = display_text[:59] + "…"

            if query_lower and query_lower in display_text.lower():
                idx = display_text.lower().find(query_lower)
                opt_text.append(display_text[:idx], style="#e4e4e7")
                opt_text.append(display_text[idx : idx + len(query_lower)], style="bold #fbbf24")
                opt_text.append(display_text[idx + len(query_lower) :], style="#e4e4e7")
            else:
                opt_text.append(display_text, style="#e4e4e7")

            options.append(Option(opt_text))

        return options

    @on(Input.Changed, "#history-search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Filter options as query is typed."""
        option_list = self.query_one("#history-list", OptionList)
        option_list.clear_options()
        new_options = self._build_options(event.value)
        option_list.add_options(new_options)
        if self._filtered_entries:
            option_list.highlighted = 0
        else:
            option_list.highlighted = None

    def on_key(self, event: events.Key) -> None:
        """Allow arrow keys to navigate the option list while input is focused."""
        option_list = self.query_one("#history-list", OptionList)

        if event.key == "down":
            event.stop()
            event.prevent_default()
            if option_list.option_count > 0:
                current = option_list.highlighted if option_list.highlighted is not None else -1
                next_idx = min(option_list.option_count - 1, current + 1)
                option_list.highlighted = next_idx
        elif event.key == "up":
            event.stop()
            event.prevent_default()
            if option_list.option_count > 0:
                current = option_list.highlighted if option_list.highlighted is not None else 1
                prev_idx = max(0, current - 1)
                option_list.highlighted = prev_idx

    @on(OptionList.OptionSelected, "#history-list")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        """User selected an option from the list."""
        if 0 <= event.option_index < len(self._filtered_entries):
            selected_text = self._filtered_entries[event.option_index][0]
            self.dismiss(selected_text)

    def action_confirm(self) -> None:
        """Confirm selection."""
        option_list = self.query_one("#history-list", OptionList)
        search_input = self.query_one("#history-search-input", Input)

        if option_list.highlighted is not None and 0 <= option_list.highlighted < len(
            self._filtered_entries
        ):
            selected_text = self._filtered_entries[option_list.highlighted][0]
            self.dismiss(selected_text)
            return

        query = search_input.value.strip()
        if self._filtered_entries:
            self.dismiss(self._filtered_entries[0][0])
        elif query:
            self.dismiss(query)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel selection."""
        self.dismiss(None)
