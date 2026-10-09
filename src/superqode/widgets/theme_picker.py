"""Search, preview and install palettes without disrupting a coding session."""

from __future__ import annotations

from pathlib import Path

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key, Resize
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from superqode import design_system as ds
from superqode.theming import ThemeError, contrast, load_theme_file, palette_tokens
from superqode.theming.library import install_theme, library_theme, theme_rows


def theme_preview(theme: str | ds.Theme):
    if isinstance(theme, str):
        theme = ds.get_theme(theme)
    palette = palette_tokens(theme)
    swatches = Text("Palette  ")
    for role in ("purple", "cyan", "success", "warning", "error", "diff_add", "diff_remove"):
        swatches.append("● ", style=palette[role])
    code = Text("Python   ", style=palette["muted"])
    code.append("return ", style=palette["syntax_keyword"])
    code.append("a + b", style=palette["syntax_variable"])
    return Group(
        swatches,
        Text("You      Fix the failing test", style=palette["user_text"]),
        Text("Agent    I found the missing return.", style=palette["text"]),
        Text(
            "Tool     pytest -q  •  12 passed",
            style=palette["success"] + " on " + palette["tool_success_bg"],
        ),
        code,
        Text("- return None", style=palette["diff_remove"])
        + Text("  |  + return a + b", style=palette["diff_add"]),
        Text("Warning: review changes before committing", style=palette["warning"]),
    )


def paint_preview(preview: RichLog, theme: ds.Theme) -> None:
    palette = palette_tokens(theme)
    preview.clear()
    preview.styles.background = palette["bg"]
    preview.styles.color = palette["text"]
    preview.write(theme_preview(theme))


class ThemePicker(ModalScreen[str | None]):
    """Preview is isolated; Enter installs if needed and returns a selection."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter", "confirm", "Apply", show=False),
        Binding("f2", "import_file", "Import JSON", show=False, priority=True),
    ]

    CSS = """
    ThemePicker { align: center middle; }
    ThemePicker > Vertical {
        width: 86; max-width: 96%; height: 92%;
        background: #0a0a0a; border: round #7c3aed; padding: 0 1;
    }
    ThemePicker .title { text-align: center; color: #a855f7; text-style: bold; height: 1; }
    ThemePicker #theme-tools { height: 1; align-horizontal: center; }
    ThemePicker #theme-tools Button {
        height: 1; min-height: 1; width: auto; min-width: 0; border: none;
        padding: 0 1; margin: 0 1 0 0;
    }
    ThemePicker #theme-search { height: 3; margin: 0; }
    ThemePicker #theme-list { height: 4; background: #000000; }
    ThemePicker #theme-preview { height: 1fr; min-height: 3; padding: 0 1; }
    ThemePicker #theme-detail { height: 2; color: #a1a1aa; }
    ThemePicker .hints { height: 1; text-align: center; color: #a1a1aa; }
    """

    def __init__(self, current: str | None = None, *, installed_only: bool = False) -> None:
        super().__init__()
        from superqode.app.theme_bridge import resolve_selection

        self._current = current if current in ds.THEMES else resolve_selection(current or "")
        self._installed_only = installed_only
        self._names = [row["name"] for row in theme_rows(installed_only=installed_only)]
        self._preview_name = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Themes · preview before you apply", classes="title")
            with Horizontal(id="theme-tools"):
                yield Button(f"All themes ({len(theme_rows())})", id="theme-all", variant="primary")
                yield Button(f"Installed ({len(ds.THEMES)})", id="theme-installed")
                yield Button("Import JSON… (F2)", id="theme-import")
            yield Input(
                placeholder="Search name, light/dark, custom or collection", id="theme-search"
            )
            yield OptionList(*self._build_options(), id="theme-list")
            yield RichLog(id="theme-preview", wrap=True, min_width=1, auto_scroll=False)
            yield Static("", id="theme-detail", markup=False)
            yield Static(
                "↑↓ preview · Enter apply/install · Tab search · Esc cancel", classes="hints"
            )

    def on_mount(self) -> None:
        options = self.query_one("#theme-list", OptionList)
        options.focus()
        options.highlighted = (
            self._names.index(self._current) if self._current in self._names else 0
        )
        self._update_preview()

    def on_resize(self, event: Resize) -> None:
        # Keep the full seven-line preview on small terminals, and use the
        # extra room on larger terminals to browse more than two entries.
        for options in self.query("#theme-list"):
            options.styles.height = max(4, min(12, event.size.height - 19))

    def _build_options(self, query="") -> list[Option]:
        rows = theme_rows(query, installed_only=self._installed_only)
        self._names = [row["name"] for row in rows]
        return [
            Option(
                Text(
                    f"{'●' if row['name'] == self._current else ' '} {row['name']}"
                    f"  ·  {row['appearance']}  ·  {'installed' if row['installed'] else 'install'}"
                ),
                id=row["name"],
            )
            for row in rows
        ]

    def _refilter(self) -> None:
        options = self.query_one("#theme-list", OptionList)
        options.clear_options()
        options.add_options(self._build_options(self.query_one("#theme-search", Input).value))
        options.highlighted = 0 if options.option_count else None
        self.query_one("#theme-all", Button).variant = (
            "default" if self._installed_only else "primary"
        )
        self.query_one("#theme-installed", Button).variant = (
            "primary" if self._installed_only else "default"
        )
        self._update_preview()

    def refresh_theme_colors(self) -> None:
        if self.is_running and self.query("#theme-preview"):
            self._update_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "theme-search":
            self._refilter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "theme-search":
            self.action_confirm()

    def on_key(self, event: Key) -> None:
        if getattr(self.focused, "id", None) == "theme-search" and event.key in {"up", "down"}:
            event.stop()
            event.prevent_default()
            options = self.query_one("#theme-list", OptionList)
            options.focus()
            if event.key == "down":
                options.action_cursor_down()
            else:
                options.action_cursor_up()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "theme-import":
            self.action_import_file()
        elif event.button.id in {"theme-all", "theme-installed"}:
            self._installed_only = event.button.id == "theme-installed"
            self._refilter()
            self.query_one("#theme-list", OptionList).focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._update_preview()

    def _selected_name(self):
        options = self.query_one("#theme-list", OptionList)
        if options.highlighted is None:
            return None
        return options.get_option_at_index(options.highlighted).id

    def _update_preview(self):
        name = self._selected_name()
        preview = self.query_one("#theme-preview", RichLog)
        preview.clear()
        detail = self.query_one("#theme-detail", Static)
        if not name:
            detail.update("No matching themes. Clear the search or choose All themes.")
            return
        try:
            theme = ds.THEMES.get(name) or library_theme(name)
            paint_preview(preview, theme)
        except ThemeError as exc:
            detail.update(str(exc))
            return
        palette = palette_tokens(theme)
        ratio = min(
            contrast(palette["text"], palette[key]) for key in ("bg", "surface", "surface2")
        )
        action = (
            "Enter applies and saves" if name in ds.THEMES else "Enter installs, applies and saves"
        )
        credit = "Awesome Pi Themes · MIT" if name not in ds.THEMES else theme.description
        detail.update(f"{credit}\nText ≥ {ratio:.1f}:1 · {action}")
        self._preview_name = name

    def action_import_file(self) -> None:
        self.app.push_screen(ThemeImportDialog(), callback=self._imported)

    def _imported(self, name: str | None) -> None:
        if name:
            self.dismiss(name)
        else:
            self.query_one("#theme-list", OptionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_confirm(self) -> None:
        name = self._selected_name()
        if not name:
            return
        try:
            if name not in ds.THEMES:
                install_theme(name)
        except ThemeError as exc:
            self.query_one("#theme-detail", Static).update(str(exc))
            return
        self.dismiss(name)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_confirm()


class ThemeImportDialog(ModalScreen[str | None]):
    """Validate and preview a local native/Pi JSON file before importing it."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]
    CSS = """
    ThemeImportDialog { align: center middle; }
    ThemeImportDialog > Vertical {
        width: 86; max-width: 96%; height: 92%; padding: 0 1;
        background: #0a0a0a; border: round #7c3aed;
    }
    ThemeImportDialog .title { height: 1; text-style: bold; text-align: center; color: #a855f7; }
    ThemeImportDialog #import-help { height: 2; color: #a1a1aa; }
    ThemeImportDialog #import-path { height: 3; }
    ThemeImportDialog #import-preview { height: 1fr; min-height: 3; padding: 0 1; }
    ThemeImportDialog #import-status { height: 2; color: #a1a1aa; }
    ThemeImportDialog #import-actions { height: 3; align-horizontal: center; }
    ThemeImportDialog #import-actions Button { margin: 0 1; }
    ThemeImportDialog .hints { height: 1; text-align: center; color: #a1a1aa; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Import a theme", classes="title")
            yield Static(
                "Paste a native SuperQode or Pi JSON file path.\nPaths with spaces work here without quotes.",
                id="import-help",
            )
            yield Input(placeholder="~/Downloads/my-theme.json", id="import-path")
            yield RichLog(id="import-preview", wrap=True, min_width=1, auto_scroll=False)
            yield Static(
                "Preview a file, then import and apply. Existing themes are retained.",
                id="import-status",
                markup=False,
            )
            with Horizontal(id="import-actions"):
                yield Button(
                    "Import & apply", id="import-confirm", variant="primary", disabled=True
                )
                yield Button("Cancel", id="import-cancel")
            yield Static("Enter import & apply · Esc cancel", classes="hints")

    def on_mount(self) -> None:
        self.query_one("#import-path", Input).focus()

    def _path(self) -> Path:
        value = self.query_one("#import-path", Input).value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return Path(value).expanduser()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "import-path":
            return
        preview = self.query_one("#import-preview", RichLog)
        preview.clear()
        button = self.query_one("#import-confirm", Button)
        button.disabled = True
        try:
            theme = load_theme_file(self._path())
            paint_preview(preview, theme)
            if theme.name in ds.THEMES:
                raise ThemeError(
                    f"Theme {theme.name!r} already exists. Change its JSON name to import a copy."
                )
        except ThemeError as exc:
            self.query_one("#import-status", Static).update(str(exc)[:300])
            return
        self.query_one("#import-status", Static).update(
            f"{theme.name} · {theme.appearance} · valid\nImport copies into ~/.superqode/themes/ and saves your selection."
        )
        button.disabled = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "import-cancel":
            self.action_cancel()
        elif event.button.id == "import-confirm":
            self._confirm()

    def _confirm(self) -> None:
        from superqode.app.theme_bridge import import_theme

        if not self.query_one("#import-path", Input).value.strip():
            self.query_one("#import-status", Static).update("Paste a JSON file path first.")
            return
        try:
            name = import_theme(self._path())
        except ThemeError as exc:
            self.query_one("#import-status", Static).update(str(exc)[:300])
            return
        self.dismiss(name)

    def action_cancel(self) -> None:
        self.dismiss(None)
