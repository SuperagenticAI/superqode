"""Search the active keymap without changing the composer's draft."""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from rich.text import Text


class HotkeysScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Back", priority=True)]
    CSS = """
    HotkeysScreen { align: center middle; background: $sq-bg; }
    #hotkeys-panel { width: 90%; height: 85%; border: round $sq-purple; background: $sq-bg; padding: 1 2; }
    #hotkeys-title { height: 2; text-style: bold; }
    #hotkeys-list { height: 1fr; }
    #hotkeys-footer { height: 2; }
    """

    def __init__(self, rows, warnings=()):
        super().__init__()
        self.rows = list(rows)
        self.warnings = list(warnings)

    def compose(self) -> ComposeResult:
        with Vertical(id="hotkeys-panel"):
            yield Static("Keyboard shortcuts · active scopes", id="hotkeys-title")
            yield Input(placeholder="Search key, action, scope or description", id="hotkeys-search")
            yield OptionList(id="hotkeys-list")
            yield Static("Esc Back · Configure ~/.superqode/keybindings.json", id="hotkeys-footer")

    def on_mount(self):
        self._filter("")
        self.query_one(Input).focus()

    @on(Input.Changed)
    def _changed(self, event):
        self._filter(event.value)

    def _filter(self, query):
        values = self.query_one(OptionList)
        values.clear_options()
        for scope, key, action, description in self.rows:
            if query.casefold() in " ".join((scope, key, action, description)).casefold():
                values.add_option(Option(Text(f"{key:18} {description or action}  [{scope}]")))
        if self.warnings:
            self.query_one("#hotkeys-footer", Static).update(Text(" · ".join(self.warnings)))

    def action_close(self):
        self.dismiss()
