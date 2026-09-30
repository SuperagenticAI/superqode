"""Inspect the next prompt's staged inputs without sending or fetching them."""

from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static, TextArea
from textual.widgets.option_list import Option
from rich.text import Text


@dataclass(frozen=True)
class ContextItem:
    label: str
    detail: str
    reference: str = ""


class ContextPreviewScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "close", "Back", priority=True)]
    CSS = """
    ContextPreviewScreen { align: center middle; }
    #context-preview { width: 94%; height: 90%; border: round #7c3aed; background: #0a0a0a; padding: 0 1; }
    #context-preview-title { height: 2; color: #a855f7; text-style: bold; }
    #context-preview-list { height: 7; max-height: 35%; }
    #context-preview-detail { height: 1fr; }
    #context-preview-buttons { height: 3; align-horizontal: right; }
    #context-preview-buttons Button { min-width: 10; margin-left: 1; }
    """

    def __init__(self, items: list[ContextItem]):
        super().__init__()
        self.items = items

    def compose(self) -> ComposeResult:
        with Vertical(id="context-preview"):
            yield Static("Current Context · next prompt", id="context-preview-title")
            yield OptionList(
                *(Option(Text(i.label)) for i in self.items), id="context-preview-list"
            )
            yield TextArea(
                self.items[0].detail if self.items else "No staged context.",
                read_only=True,
                id="context-preview-detail",
            )
            with Horizontal(id="context-preview-buttons"):
                yield Button("Remove", id="context-preview-remove", disabled=True)
                yield Button("Back", id="context-preview-back")

    def on_mount(self):
        self.query_one("#context-preview-list", OptionList).highlighted = 0 if self.items else None
        self._update()

    def _selected(self):
        index = self.query_one("#context-preview-list", OptionList).highlighted
        return self.items[index] if index is not None and 0 <= index < len(self.items) else None

    def _update(self):
        selected = self._selected()
        self.query_one("#context-preview-detail", TextArea).load_text(
            selected.detail if selected else "No staged context."
        )
        self.query_one("#context-preview-remove", Button).disabled = not bool(
            selected and selected.reference
        )

    @on(OptionList.OptionHighlighted)
    def highlighted(self):
        self._update()

    @on(Button.Pressed, "#context-preview-remove")
    def remove_selected(self):
        item = self._selected()
        if item and item.reference:
            self.dismiss(item.reference)

    @on(Button.Pressed, "#context-preview-back")
    def action_close(self):
        self.dismiss(None)
