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
    """Highlight previews the workspace; Esc rolls back; Enter commits."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter", "confirm", "Apply", show=False),
        Binding("f2", "import_file", "Import JSON", show=False, priority=True),
        Binding("f3", "customize", "Customize", show=False, priority=True),
        Binding("f4", "workspace", "View workspace", priority=True),
        Binding("ctrl+s", "favorite", "Favorite", priority=True),
        # Letter alternatives for terminals that eat function keys or Ctrl+S
        # (macOS Terminal, tmux, XON/XOFF). Not priority: they act only when the
        # list or a button has focus, so typing in the search box is unaffected.
        Binding("e", "customize", "Customize", show=False),
        Binding("w", "workspace", "View workspace", show=False),
        Binding("f", "favorite", "Favorite", show=False),
    ]
    CSS = """
    ThemePicker { align: center middle; background: transparent; }
    ThemePicker > Vertical {
        width: 86; max-width: 96%; height: 92%;
        background: $sq-bg; border: round $sq-purple; padding: 0 1;
    }
    ThemePicker .title { text-align: center; color: $sq-purple; text-style: bold; height: 1; }
    ThemePicker .theme-toolbar { height: 1; align-horizontal: center; }
    ThemePicker .theme-toolbar Button {
        height: 1; min-height: 1; width: auto; min-width: 0; border: none;
        padding: 0 1; margin: 0 1 0 0;
    }
    ThemePicker #theme-search { height: 3; margin: 0; }
    ThemePicker #theme-list { height: 3; background: $sq-bg; }
    ThemePicker #theme-preview { height: 1fr; min-height: 3; padding: 0 1; }
    ThemePicker #theme-detail { height: 2; color: $sq-muted; }
    ThemePicker .hints { height: 1; text-align: center; color: $sq-muted; }
    ThemePicker.workspace-view { align: center bottom; }
    ThemePicker.workspace-view > Vertical { height: 5; width: 100%; max-width: 100%; }
    ThemePicker.workspace-view .title { display: none; }
    ThemePicker.workspace-view #theme-detail { height: 1; }
    ThemePicker.workspace-view #theme-tools,
    ThemePicker.workspace-view #theme-filters,
    ThemePicker.workspace-view #theme-search,
    ThemePicker.workspace-view #theme-list,
    ThemePicker.workspace-view #theme-preview { display: none; }
    """

    def __init__(self, current=None, *, installed_only=False, confirm_label="applies and saves"):
        super().__init__()
        from superqode.app.theme_bridge import resolve_selection

        self._current = current if current in ds.THEMES else resolve_selection(current or "")
        self._installed_only = installed_only
        self._appearance_filter = "all"
        self._scope = "all"
        self._workspace = False
        self._confirm_label = confirm_label
        self._names = []
        self._preview_name = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Themes · preview your workspace", classes="title")
            with Horizontal(id="theme-tools", classes="theme-toolbar"):
                yield Button(f"All ({len(theme_rows())})", id="theme-all", variant="primary")
                yield Button(
                    f"Installed ({len(theme_rows(installed_only=True))})", id="theme-installed"
                )
                yield Button("Import F2", id="theme-import")
            with Horizontal(id="theme-filters", classes="theme-toolbar"):
                for label, name in (
                    ("Light", "light"),
                    ("Dark", "dark"),
                    ("Favorites", "favorites"),
                    ("Recent", "recent"),
                ):
                    yield Button(label, id=f"theme-{name}")
            with Horizontal(id="theme-actions", classes="theme-toolbar"):
                yield Button("Favorite", id="theme-favorite")
                yield Button("Workspace F4", id="theme-workspace")
                yield Button("Edit F3", id="theme-customize")
                yield Button("Undo", id="theme-undo")
            yield Input(placeholder="Search name, appearance or collection", id="theme-search")
            yield OptionList(*self._build_options(), id="theme-list")
            yield RichLog(id="theme-preview", wrap=True, min_width=1, auto_scroll=False)
            yield Static("", id="theme-detail", markup=False)
            yield Static("↑↓ preview · Enter apply · F4 workspace · Esc cancel", classes="hints")

    def _begin_preview(self):
        begin = getattr(self.app, "_begin_theme_preview", None)
        if callable(begin):
            begin(self)

    def _end_preview(self):
        end = getattr(self.app, "_end_theme_preview", None)
        if callable(end):
            end(self)

    def on_mount(self):
        self._begin_preview()
        options = self.query_one("#theme-list", OptionList)
        options.focus()
        options.highlighted = (
            self._names.index(self._current)
            if self._current in self._names
            else (0 if self._names else None)
        )
        self._update_preview()

    def on_unmount(self):
        self._end_preview()

    def on_resize(self, event: Resize):
        for options in self.query("#theme-list"):
            options.styles.height = max(3, min(12, event.size.height - 22))

    def _build_options(self, query=""):
        from superqode.app.appearance import load_appearance

        preferences = load_appearance()
        favorites = preferences.favorite_themes
        recent = list(
            dict.fromkeys(name for item in preferences.recent_themes for name in item.split("/"))
        )
        rows = theme_rows(query, installed_only=self._installed_only)
        rows = [
            row
            for row in rows
            if (self._appearance_filter == "all" or row["appearance"] == self._appearance_filter)
            and (
                self._scope == "all"
                or row["name"] in (favorites if self._scope == "favorites" else recent)
            )
        ]
        rows.sort(
            key=lambda row: (
                row["name"] not in favorites,
                recent.index(row["name"]) if row["name"] in recent else len(recent),
                row["name"].casefold(),
            )
        )
        self._names = [row["name"] for row in rows]
        return [
            Option(
                Text(
                    f"{'*' if row['name'] in favorites else '●' if row['name'] == self._current else ' '} {row['name']}"
                    f" · {row['appearance']} · {'installed' if row['installed'] else 'install'}"
                ),
                id=row["name"],
            )
            for row in rows
        ]

    def _refilter(self, keep=None):
        options = self.query_one("#theme-list", OptionList)
        options.clear_options()
        options.add_options(self._build_options(self.query_one("#theme-search", Input).value))
        options.highlighted = (
            self._names.index(keep) if keep in self._names else (0 if self._names else None)
        )
        active = {
            "all": not self._installed_only
            and self._scope == "all"
            and self._appearance_filter == "all",
            "installed": self._installed_only,
            "light": self._appearance_filter == "light",
            "dark": self._appearance_filter == "dark",
            "favorites": self._scope == "favorites",
            "recent": self._scope == "recent",
        }
        for name, selected in active.items():
            self.query_one(f"#theme-{name}", Button).variant = "primary" if selected else "default"
        self._update_preview()

    def refresh_theme_colors(self):
        if self.is_running and self.query("#theme-preview"):
            self._update_preview()

    def refresh_terminal_preview(self):
        self._update_preview()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "theme-search":
            self._refilter()

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "theme-search":
            self.action_confirm()

    def on_key(self, event: Key):
        if self._workspace and event.key == "enter":
            event.stop()
            event.prevent_default()
            self.action_confirm()
        elif event.key in {"up", "down"} and (
            self._workspace or getattr(self.focused, "id", None) == "theme-search"
        ):
            event.stop()
            event.prevent_default()
            options = self.query_one("#theme-list", OptionList)
            if not self._workspace:
                options.focus()
            options.action_cursor_down() if event.key == "down" else options.action_cursor_up()

    def on_button_pressed(self, event: Button.Pressed):
        name = event.button.id.removeprefix("theme-")
        if name in {"import", "workspace", "favorite", "customize"}:
            getattr(self, f"action_{'import_file' if name == 'import' else name}")()
        elif name == "undo":
            self._end_preview()
            self.dismiss(":previous")
        else:
            keep = self._selected_name()
            if name == "all":
                self._installed_only, self._scope, self._appearance_filter = False, "all", "all"
            elif name == "installed":
                self._installed_only = not self._installed_only
            elif name in {"light", "dark"}:
                self._appearance_filter = "all" if self._appearance_filter == name else name
            elif name in {"favorites", "recent"}:
                self._scope = "all" if self._scope == name else name
            self._refilter(keep)
            self.query_one("#theme-list", OptionList).focus()

    def on_option_list_option_highlighted(self, event):
        self._update_preview()

    def _selected_name(self):
        options = self.query_one("#theme-list", OptionList)
        return (
            None
            if options.highlighted is None
            else options.get_option_at_index(options.highlighted).id
        )

    def _update_preview(self):
        name = self._selected_name()
        preview = self.query_one("#theme-preview", RichLog)
        detail = self.query_one("#theme-detail", Static)
        if not name:
            preview.clear()
            detail.update("No matching themes. Clear the search or choose All.")
            restore = getattr(self.app, "_preview_workspace_selection", None)
            if callable(restore):
                restore(self, self._current or "superqode")
            return
        try:
            theme = ds.THEMES.get(name) or library_theme(name)
            paint_preview(preview, theme)
            preview_workspace = getattr(self.app, "_preview_workspace_theme", None)
            if callable(preview_workspace):
                preview_workspace(self, theme)
            palette = palette_tokens(theme)
        except ThemeError as exc:
            detail.update(str(exc))
            return
        ratio = min(
            contrast(palette["text"], palette[key]) for key in ("bg", "surface", "surface2")
        )
        installed = theme.source != "preview" and name in ds.THEMES
        action = (
            f"Enter {self._confirm_label}"
            if installed
            else f"Enter installs and {self._confirm_label}"
        )
        detail.update(
            f"{name} · {theme.appearance} · Text ≥ {ratio:.1f}:1\n{action} · Ctrl+S favorite · F4 view workspace"
        )
        self._preview_name = name

    def action_workspace(self):
        self._workspace = not self._workspace
        self.set_class(self._workspace, "workspace-view")
        self.query_one("#theme-workspace", Button).label = (
            "Gallery F4" if self._workspace else "Workspace F4"
        )
        if not self._workspace:
            self.query_one("#theme-list", OptionList).focus()

    def action_favorite(self):
        from superqode.app.appearance import toggle_favorite

        name = self._selected_name()
        if name:
            error = toggle_favorite(name)
            if error:
                self.query_one("#theme-detail", Static).update(error)
            else:
                self._refilter(name)

    def action_import_file(self):
        self._end_preview()
        self.app.push_screen(ThemeImportDialog(), callback=self._imported)

    def action_customize(self):
        from superqode.widgets.theme_customizer import ThemeCustomizer

        name = self._selected_name()
        theme = ds.THEMES.get(name) or (library_theme(name) if name else ds.get_theme())
        self._end_preview()
        self.app.push_screen(ThemeCustomizer(theme), callback=self._imported)

    def _imported(self, name):
        if name:
            self.dismiss(name)
        else:
            self._begin_preview()
            self.query_one("#theme-list", OptionList).focus()
            self._update_preview()

    def action_cancel(self):
        self._end_preview()
        self.dismiss(None)

    def action_confirm(self):
        name = self._selected_name()
        if not name:
            return
        self._end_preview()
        try:
            if name not in ds.THEMES:
                install_theme(name)
        except ThemeError as exc:
            self._begin_preview()
            self.query_one("#theme-detail", Static).update(str(exc))
            return
        self.dismiss(name)

    def on_option_list_option_selected(self, event):
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
        from superqode.theming import adjustment_warning

        warning = adjustment_warning(ds.THEMES[name])
        if warning:
            self.app.notify(warning[:300], title="Theme imported", severity="warning", markup=False)
        self.dismiss(name)

    def action_cancel(self) -> None:
        self.dismiss(None)
