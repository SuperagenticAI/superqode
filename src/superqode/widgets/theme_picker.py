"""Theme picker overlay (`/theme`).

Lists the design-system themes (superqode, tokyonight, dracula, …) with a live
swatch preview and returns the chosen theme name. Applying/persisting happens in
the app via ``app.theme_bridge`` so there is one source of truth.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from superqode import design_system as ds


class ThemePicker(ModalScreen[str | None]):
    """Modal listing themes; dismisses with the chosen name."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Apply", show=False),
    ]

    CSS = """
    ThemePicker {
        align: center middle;
    }

    ThemePicker > Vertical {
        width: 72;
        height: auto;
        max-height: 80%;
        background: #0a0a0a;
        border: round #7c3aed;
        padding: 1 2;
    }

    ThemePicker .title {
        text-align: center;
        color: #a855f7;
        text-style: bold;
        height: 1;
    }

    ThemePicker .subtitle {
        text-align: center;
        color: #71717a;
        height: 2;
    }

    ThemePicker #theme-list {
        height: auto;
        max-height: 14;
        background: #050505;
        border: solid #27272a;
    }

    ThemePicker #theme-list:focus {
        border: solid #7c3aed;
    }

    ThemePicker .hints {
        text-align: center;
        color: #71717a;
        height: 1;
        margin-top: 1;
    }
    """

    def __init__(self, current: str | None = None) -> None:
        super().__init__()
        self._current = current
        self._names = [name for name, _ in ds.list_themes()]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("🎨  Choose a theme", classes="title")
            yield Static(
                "Applies live — restart not required.",
                classes="subtitle",
            )
            yield OptionList(*self._build_options(), id="theme-list")
            yield Static("↑↓ choose   •   Enter apply   •   Esc cancel", classes="hints")

    def on_mount(self) -> None:
        option_list = self.query_one("#theme-list", OptionList)
        option_list.focus()
        if self._current in self._names:
            option_list.highlighted = self._names.index(self._current)

    def _build_options(self) -> list[Option]:
        options: list[Option] = []
        for name, description in ds.list_themes():
            colors = ds.get_theme(name).colors
            label = Text()
            mark = "● " if name == self._current else "  "
            label.append(mark, style="#22c55e")
            label.append(f"{name:<11}", style="bold #e4e4e7")
            for hex_color in (
                colors.primary_bright,
                colors.secondary,
                colors.info,
                colors.success,
                colors.warning,
            ):
                label.append("██", style=hex_color)
            label.append(f"  {description}", style="#71717a")
            options.append(Option(label, id=name))
        return options

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_confirm(self) -> None:
        option_list = self.query_one("#theme-list", OptionList)
        if option_list.highlighted is None:
            self.dismiss(None)
            return
        option = option_list.get_option_at_index(option_list.highlighted)
        self.dismiss(option.id if option else None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)
