"""One compact shortcut line, updated only when panel focus changes."""

from textual.containers import ScrollableContainer
from textual.scroll_view import ScrollView
from textual.widgets import Button, Checkbox, OptionList, Select, Static


def navigate_panel(focused, motion: str) -> None:
    """Move only the focused panel control; never activate or submit it."""
    if isinstance(focused, OptionList):
        action = {
            "down": "action_cursor_down",
            "up": "action_cursor_up",
            "first": "action_first",
            "last": "action_last",
            "page_up": "action_page_up",
            "page_down": "action_page_down",
        }[motion]
        getattr(focused, action)()
        return

    if isinstance(focused, (Button, Checkbox, Select)) and motion in {"down", "up"}:
        focused.screen.focus_next() if motion == "down" else focused.screen.focus_previous()
        return

    # Read-only text, diffs and nested detail panes may be scroll views or
    # content inside a scrollable container. Editable text is excluded by the
    # app before these actions are enabled.
    scroller = next(
        (
            node
            for node in focused.ancestors_with_self
            if isinstance(node, (ScrollView, ScrollableContainer))
        ),
        None,
    )
    if scroller is not None:
        if motion in {"down", "up"}:
            scroller.scroll_relative(y=1 if motion == "down" else -1, animate=False)
        elif motion in {"first", "last"}:
            scroller.scroll_home(animate=False) if motion == "first" else scroller.scroll_end(
                animate=False
            )
        else:
            scroller.scroll_page_up(
                animate=False
            ) if motion == "page_up" else scroller.scroll_page_down(animate=False)
    elif motion in {"down", "up"}:
        focused.screen.focus_next() if motion == "down" else focused.screen.focus_previous()


class PanelShortcuts(Static):
    DEFAULT_CSS = """
    PanelShortcuts { height: 1; color: #a1a1aa; text-overflow: ellipsis; }
    """

    def __init__(self, hints: dict[str, str], default: str):
        super().__init__(default, classes="panel-shortcuts")
        self.hints = hints
        self.default = default

    def for_focus(self, widget_id: str | None, *, vim: bool = False):
        hint = self.hints.get(widget_id, self.default)
        self.update(hint.replace("↑↓", "j/k or ↑↓") if vim else hint)


class PanelShortcutMixin:
    def on_descendant_focus(self, event):
        target = getattr(self.app, "_panel_vim_target", lambda: None)()
        self.query_one(PanelShortcuts).for_focus(event.widget.id, vim=target is not None)
