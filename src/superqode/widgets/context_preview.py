"""Inspect the next prompt's staged inputs without sending or fetching them."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static, TextArea
from textual.widgets.option_list import Option
from rich.text import Text
from superqode.widgets.panel_shortcuts import PanelShortcuts, PanelShortcutMixin


@dataclass(frozen=True)
class ContextItem:
    label: str
    detail: str
    reference: str = ""


class ContextPreviewScreen(PanelShortcutMixin, ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "close", "Back", priority=True),
        Binding("delete", "remove_selected", "Remove", priority=True),
    ]
    CSS = """
    ContextPreviewScreen { align: center middle; }
    #context-preview { width: 94%; height: 90%; border: round #7c3aed; background: #0a0a0a; padding: 0 1; }
    #context-preview-title { height: 2; color: #a855f7; text-style: bold; }
    #context-preview-list { height: 7; max-height: 35%; }
    #context-preview-detail { height: 1fr; }
    #context-preview-buttons { height: 3; align-horizontal: right; }
    #context-preview-buttons Button { min-width: 10; margin-left: 1; }
    """

    def __init__(self, items: list[ContextItem], *, on_remove: Callable[[str], str] | None = None):
        super().__init__()
        self.items = list(items)
        self.on_remove = on_remove

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
            yield PanelShortcuts(
                {
                    "context-preview-list": "↑↓ Select · Enter Inspect · Delete Remove · Esc Back",
                    "context-preview-detail": "↑↓ Scroll · Tab Controls · Esc Back",
                },
                "Enter Activate · Tab Next control · Esc Back",
            )

    def on_mount(self):
        self.query_one("#context-preview-list", OptionList).highlighted = 0 if self.items else None
        self._update()
        self.query_one("#context-preview-list", OptionList).focus()

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
        shortcuts = self.query_one(PanelShortcuts)
        shortcuts.hints["context-preview-list"] = (
            "↑↓ Select · Enter Inspect"
            + (" · Delete Remove" if selected and selected.reference else "")
            + " · Esc Back"
        )
        shortcuts.for_focus(getattr(self.focused, "id", None))

    @on(OptionList.OptionHighlighted)
    def highlighted(self):
        self._update()

    @on(OptionList.OptionSelected, "#context-preview-list")
    def inspect_selected(self):
        self.query_one("#context-preview-detail", TextArea).focus()

    @on(Button.Pressed, "#context-preview-remove")
    def remove_selected(self):
        item = self._selected()
        if item and item.reference:
            if self.on_remove is None:
                self.dismiss(item.reference)
                return
            draft = self.on_remove(item.reference)
            options = self.query_one("#context-preview-list", OptionList)
            index = options.highlighted or 0
            self.items.remove(item)
            if self.items and self.items[0].label == "Prompt":
                self.items[0] = replace(self.items[0], detail=draft or "No prompt drafted yet.")
            options.clear_options()
            options.add_options(Option(Text(entry.label)) for entry in self.items)
            options.highlighted = min(index, len(self.items) - 1) if self.items else None
            self._update()
            options.focus()

    def action_remove_selected(self):
        self.remove_selected()

    @on(Button.Pressed, "#context-preview-back")
    def action_close(self):
        self.dismiss(None)
