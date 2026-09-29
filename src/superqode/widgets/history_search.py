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
from superqode.app.constants import THEME
from superqode.utils.fuzzy import FuzzySearch

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
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter", "confirm", "Select", show=False, priority=True),
    ]

    CSS = """
    HistorySearchModal {
        align: center middle;
    }

    HistorySearchModal > Vertical {
        width: 95%;
        max-width: 82;
        height: 85%;
        max-height: 24;
        background: #0a0a0a;
        border: round #7c3aed;
        padding: 0 1;
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
        height: 1fr;
        min-height: 1;
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
        self._fuzzy = FuzzySearch()
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
        self.refresh_theme_colors()
        search_input = self.query_one("#history-search-input", Input)
        search_input.focus()

    def refresh_theme_colors(self) -> None:
        box = self.query_one(Vertical)
        box.styles.background = THEME["surface2"]
        box.styles.border = ("round", THEME["purple"])
        for widget in self.query("Static, Input, OptionList"):
            widget.styles.color = THEME["text"]
            widget.styles.background = THEME["surface2"]
        for widget in self.query("Input, OptionList"):
            widget.styles.border = ("solid", THEME["purple"])

    def _build_options(self, query: str) -> list[Option]:
        query_lower = query.lower().strip()
        items = [(" ".join(entry[0].splitlines()), entry) for entry in self._all_entries]
        ranked = self._fuzzy.search_with_data(
            query_lower, items, max_results=len(items), threshold=float("-inf")
        )
        ranked = [
            (match, entry)
            for match, entry in ranked
            if not query_lower or len(match.positions) == len(query_lower)
        ]
        # Exact substrings beat scattered matches; recency breaks equal scores.
        if query_lower:
            ranked.sort(
                key=lambda row: (query_lower in row[0].text.lower(), row[0].score), reverse=True
            )
        filtered = [entry for _, entry in ranked[:50]]
        positions = {entry[0]: match.positions for match, entry in ranked[:50]}

        self._filtered_entries = filtered
        options: list[Option] = []

        if not filtered:
            msg = Text("  No matching history", style=THEME["muted"])
            options.append(Option(msg, disabled=True))
            return options

        for text, ts, mode in filtered:
            opt_text = Text()
            # Timestamp or bullet
            if ts:
                try:
                    dt = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
                    opt_text.append(f"{dt} ", style=THEME["muted"])
                except Exception:
                    opt_text.append("• ", style=THEME["muted"])
            else:
                opt_text.append("• ", style=THEME["muted"])

            # Highlight query matches in text
            display_text = " ".join(text.splitlines())
            matched = positions.get(text, [])
            exact = display_text.lower().find(query_lower) if query_lower else -1
            if exact >= 0:
                matched = list(range(exact, exact + len(query_lower)))
            start = max(0, matched[0] - 12) if matched else 0
            display = Text("…" if start else "", style=THEME["text"])
            offset = len(display)
            display.append(display_text[start : start + 60])
            for position in matched:
                if start <= position < start + 60:
                    display.stylize(
                        f"bold {THEME['purple']}",
                        offset + position - start,
                        offset + position - start + 1,
                    )
            if len(display_text) > start + 60:
                display.append("…")
            opt_text.append_text(display)

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
        if not self._filtered_entries:
            return
        option_list = self.query_one("#history-list", OptionList)
        if option_list.highlighted is not None and 0 <= option_list.highlighted < len(
            self._filtered_entries
        ):
            selected_text = self._filtered_entries[option_list.highlighted][0]
            self.dismiss(selected_text)
            return

        self.dismiss(self._filtered_entries[0][0])

    def action_cancel(self) -> None:
        """Cancel selection."""
        self.dismiss(None)
