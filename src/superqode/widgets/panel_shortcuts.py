"""One compact shortcut line, updated only when panel focus changes."""

from textual.widgets import Static


class PanelShortcuts(Static):
    DEFAULT_CSS = """
    PanelShortcuts { height: 1; color: #a1a1aa; text-overflow: ellipsis; }
    """

    def __init__(self, hints: dict[str, str], default: str):
        super().__init__(default, classes="panel-shortcuts")
        self.hints = hints
        self.default = default

    def for_focus(self, widget_id: str | None):
        self.update(self.hints.get(widget_id, self.default))


class PanelShortcutMixin:
    def on_descendant_focus(self, event):
        self.query_one(PanelShortcuts).for_focus(event.widget.id)
