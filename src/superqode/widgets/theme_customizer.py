"""Create and export a palette without risking the active workspace."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RichLog, Static

from superqode import design_system as ds
from superqode.app.theme_bridge import theme_directory
from superqode.theming import (
    ThemeError,
    atomic_json,
    load_theme_file,
    native_document,
    palette_tokens,
)
from superqode.theming.customizer import customize_theme
from superqode.widgets.theme_picker import paint_preview


class ThemeCustomizer(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("f4", "workspace", "View workspace", priority=True),
        Binding("w", "workspace", "View workspace", show=False),
    ]
    CSS = """
    ThemeCustomizer { align: center middle; background: transparent; }
    ThemeCustomizer > Vertical { width: 86; max-width: 96%; height: 92%; padding: 0 1; background: $sq-bg; border: round $sq-purple; }
    ThemeCustomizer .title { height: 1; color: $sq-purple; text-style: bold; }
    ThemeCustomizer #custom-body { height: 1fr; }
    ThemeCustomizer Label { height: 1; margin-top: 1; }
    ThemeCustomizer #custom-presets { height: 3; }
    ThemeCustomizer #custom-fields { height: auto; margin: 1 0; }
    ThemeCustomizer .custom-field { height: 1; }
    ThemeCustomizer .custom-field Label { width: 20; height: 1; margin: 0; }
    ThemeCustomizer .custom-field Input, ThemeCustomizer .custom-field Input:focus {
        height: 1; min-height: 1; border: none; padding: 0 1; width: 1fr;
    }
    ThemeCustomizer .custom-field .swatch { width: 2; height: 1; margin-left: 1; }
    ThemeCustomizer #custom-preview { height: 7; }
    ThemeCustomizer #custom-status { height: 3; color: $sq-muted; }
    ThemeCustomizer #custom-actions { height: 3; }
    ThemeCustomizer Button { min-width: 8; width: auto; margin-right: 1; }
    ThemeCustomizer.workspace-view { align: center bottom; }
    ThemeCustomizer.workspace-view > Vertical { height: 9; width: 100%; max-width: 100%; }
    ThemeCustomizer.workspace-view #custom-body { display: none; }
    """

    def __init__(self, base: ds.Theme):
        super().__init__()
        self.base = base
        self.palette = palette_tokens(base)
        self._ready = False
        self._workspace = False
        self._candidate = None

    def compose(self) -> ComposeResult:
        name = self.base.name[:48].rstrip("-_") + "-custom"
        stem, counter = name, 2
        while name in ds.THEMES or (theme_directory() / f"{name}.json").exists():
            name = f"{stem}-{counter}"
            counter += 1
        with Vertical():
            yield Static("Create your theme", classes="title")
            with VerticalScroll(id="custom-body"):
                yield Static(
                    "Edit hex colors. Readability is corrected automatically in the preview."
                )
                with Horizontal(id="custom-presets"):
                    yield Button("Dark canvas", id="custom-dark")
                    yield Button("Light canvas", id="custom-light")
                with Vertical(id="custom-fields"):
                    for label, key, value in (
                        ("Name · slug", "name", name),
                        ("Accent", "accent", self.palette["purple"]),
                        ("Background", "background", self.palette["bg"]),
                        ("Panel background", "surface", self.palette["surface"]),
                        ("Text", "text", self.palette["text"]),
                    ):
                        with Horizontal(classes="custom-field"):
                            yield Label(label)
                            yield Input(value=value, id=f"custom-{key}")
                            yield Static("", id=f"custom-swatch-{key}", classes="swatch")
                yield RichLog(id="custom-preview", wrap=True, min_width=1, auto_scroll=False)
                yield Label("Export JSON path · existing files are retained")
                yield Input(value=f"~/{name}.json", id="custom-export-path")
            yield Static("", id="custom-status", markup=False)
            with Horizontal(id="custom-actions"):
                yield Button("Save & apply", id="custom-save", variant="primary")
                yield Button("Export JSON", id="custom-export")
                yield Button("View F4", id="custom-workspace")
                yield Button("Cancel", id="custom-cancel")

    def on_mount(self):
        self.app._begin_theme_preview(self)
        self._ready = True
        self._update()

    def _update(self):
        if not self._ready:
            return
        self._candidate = None
        status = self.query_one("#custom-status", Static)
        try:
            name = self.query_one("#custom-name", Input).value.strip()
            if name in ds.THEMES and ds.THEMES[name].source != "preview":
                raise ThemeError("This name is installed. Choose a new name to save a copy.")
            theme, requested, rendered = customize_theme(
                self.base,
                name,
                **{
                    key: self.query_one(f"#custom-{key}", Input).value.strip()
                    for key in ("accent", "background", "surface", "text")
                },
            )
            self._candidate = theme
            palette = palette_tokens(theme)
            for key, role in (
                ("accent", "purple"),
                ("background", "bg"),
                ("surface", "surface"),
                ("text", "text"),
            ):
                self.query_one(f"#custom-swatch-{key}", Static).styles.background = palette[role]
            paint_preview(self.query_one("#custom-preview", RichLog), theme)
            self.app._preview_workspace_theme(self, theme)
            from superqode.theming import readability_adjustments

            adjusted = readability_adjustments(theme)
            correction = (
                f" · readability correction changed {len(adjusted)} colour role(s)"
                if adjusted
                else ""
            )
            status.update(
                f"{theme.name} · {theme.appearance}{correction}\nRequested text {requested:.1f}:1 · Displayed text ≥ {rendered:.1f}:1\nF4 views your workspace · Esc restores the original"
            )
        except ThemeError as exc:
            status.update(f"{exc}\nYour last working preview is retained.")
        for name in ("save", "export"):
            self.query_one(f"#custom-{name}", Button).disabled = self._candidate is None

    def on_input_changed(self, event: Input.Changed):
        if event.input.id != "custom-export-path":
            self._update()

    def on_button_pressed(self, event: Button.Pressed):
        name = event.button.id.removeprefix("custom-")
        if name in {"dark", "light"}:
            values = (
                {"background": "#fafafa", "surface": "#f4f4f5", "text": "#18181b"}
                if name == "light"
                else {"background": "#0a0a0a", "surface": "#15151a", "text": "#e4e4e7"}
            )
            for key, value in values.items():
                self.query_one(f"#custom-{key}", Input).value = value
            self._update()
        elif name == "save":
            self.action_save()
        elif name == "export":
            self.action_export()
        elif name == "workspace":
            self.action_workspace()
        elif name == "cancel":
            self.action_cancel()

    def action_workspace(self):
        self._workspace = not self._workspace
        self.set_class(self._workspace, "workspace-view")

    def action_export(self):
        if self._candidate is None:
            return
        from pathlib import Path

        value = self.query_one("#custom-export-path", Input).value.strip()
        if not value:
            self.query_one("#custom-status", Static).update("Choose an export file path first.")
            return
        try:
            path = Path(value).expanduser()
            atomic_json(path, native_document(self._candidate), overwrite=False)
        except (OSError, ValueError) as exc:
            self.query_one("#custom-status", Static).update(f"Could not export: {exc}")
            return
        self.query_one("#custom-status", Static).update(
            f"Exported JSON to {path}\nThe current workspace is still a preview; Esc restores it."
        )

    def action_save(self):
        if self._candidate is None:
            return
        theme = self._candidate
        try:
            path = theme_directory() / f"{theme.name}.json"
            atomic_json(path, native_document(theme), overwrite=False)
            installed = load_theme_file(path)
        except (OSError, ValueError) as exc:
            self.query_one("#custom-status", Static).update(f"Could not save: {exc}")
            return
        self.app._end_theme_preview(self)
        ds.THEMES[installed.name] = installed
        self.dismiss(installed.name)

    def action_cancel(self):
        self.app._end_theme_preview(self)
        self.dismiss(None)

    def on_unmount(self):
        self.app._end_theme_preview(self)
