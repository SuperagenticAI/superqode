"""One keyboard-accessible screen for palette and terminal preferences."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Select, Static

from superqode import design_system as ds
from superqode.app.appearance import load_appearance
from superqode.app.theme_bridge import apply_theme, save_theme, theme_display_name


class AppearanceSettings(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("f4", "workspace", "View workspace", priority=True),
    ]
    CSS = """
    AppearanceSettings { align: center middle; background: transparent; }
    AppearanceSettings > Vertical {
        width: 82; max-width: 96%; height: 92%; padding: 0 1;
        background: $sq-bg; border: round $sq-purple;
    }
    AppearanceSettings .title { height: 1; text-style: bold; color: $sq-purple; }
    AppearanceSettings #appearance-body { height: 1fr; }
    AppearanceSettings Label { height: 1; margin-top: 1; }
    AppearanceSettings #appearance-status { height: 2; color: $sq-muted; }
    AppearanceSettings #appearance-actions { height: 3; }
    AppearanceSettings Button { min-width: 9; width: auto; margin-right: 1; }
    AppearanceSettings.workspace-view { align: center bottom; }
    AppearanceSettings.workspace-view > Vertical { height: 8; width: 100%; max-width: 100%; }
    AppearanceSettings.workspace-view #appearance-body { display: none; }
    """

    def __init__(self):
        super().__init__()
        self._ready = False
        self._accepted = False
        self._workspace = False

    def compose(self) -> ComposeResult:
        self.original = deepcopy(self.app._appearance)
        self.original_selection = self.app._current_theme
        selection = self.original_selection
        self.fixed_theme = ds.get_theme().name
        paired = selection.split("/") if "/" in selection else ["light", "superqode"]
        mode = (
            "pair"
            if "/" in selection
            else selection
            if selection in {"auto", "system"}
            else "fixed"
        )
        with Vertical():
            yield Static("Appearance settings", classes="title")
            with VerticalScroll(id="appearance-body"):
                yield Static(
                    "Changes preview live. Apply & save keeps them; Esc restores your appearance."
                )
                yield Label("Theme behavior")
                yield Select(
                    [
                        ("One selected theme", "fixed"),
                        ("Automatic SuperQode light/dark", "auto"),
                        ("Match terminal colors", "system"),
                        ("Choose a light/dark pair", "pair"),
                    ],
                    value=mode,
                    allow_blank=False,
                    id="appearance-mode",
                )
                yield Button(
                    f"Theme: {theme_display_name(self.fixed_theme)}", id="appearance-gallery"
                )
                yield Label("Light appearance theme")
                yield Select(
                    self._theme_options("light", paired[0]),
                    value=paired[0],
                    allow_blank=False,
                    id="appearance-light",
                )
                yield Label("Dark appearance theme")
                yield Select(
                    self._theme_options("dark", paired[1]),
                    value=paired[1],
                    allow_blank=False,
                    id="appearance-dark",
                )
                yield Label("Spacing")
                yield Select(
                    [("Comfortable", "comfortable"), ("Compact", "compact")],
                    value=self.original.density,
                    allow_blank=False,
                    id="appearance-density",
                )
                yield Label("Animation")
                yield Select(
                    [("Normal", "full"), ("Reduced · steady status, no sweeps", "reduced")],
                    value=self.original.motion,
                    allow_blank=False,
                    id="appearance-motion",
                )
                yield Label("Terminal icons")
                yield Select(
                    [("Unicode", "unicode"), ("Simple · ASCII status icons", "ascii")],
                    value=self.original.icons,
                    allow_blank=False,
                    id="appearance-icons",
                )
            yield Static("", id="appearance-status", markup=False)
            with Horizontal(id="appearance-actions"):
                yield Button("Apply & save", id="appearance-save", variant="primary")
                yield Button("View F4", id="appearance-workspace")
                yield Button("Cancel", id="appearance-cancel")

    @staticmethod
    def _theme_options(appearance, current=None):
        options = [
            (theme_display_name(name), name)
            for name, theme in ds.THEMES.items()
            if theme.source != "preview"
            and name not in {"system", "auto"}
            and theme.appearance == appearance
        ]
        if current in ds.THEMES and current not in {value for _, value in options}:
            options.append((f"{theme_display_name(current)} (current selection)", current))
        return options

    def on_mount(self):
        self.app._begin_theme_preview(self)
        self._ready = True
        self._stage()

    def _selection(self):
        mode = self.query_one("#appearance-mode", Select).value
        if mode == "pair":
            return f"{self.query_one('#appearance-light', Select).value}/{self.query_one('#appearance-dark', Select).value}"
        return self.fixed_theme if mode == "fixed" else str(mode)

    def _preferences(self):
        return replace(
            self.original,
            **{
                key: str(self.query_one(f"#appearance-{key}", Select).value)
                for key in ("density", "motion", "icons")
            },
        )

    def _stage(self):
        if not self._ready:
            return
        paired = self.query_one("#appearance-mode", Select).value == "pair"
        for name in ("light", "dark"):
            self.query_one(f"#appearance-{name}", Select).disabled = not paired
        selection = self._selection()
        if self.app._preview_workspace_selection(self, selection):
            self.app._apply_appearance(self._preferences())
            self.query_one("#appearance-status", Static).update(
                f"Preview: {selection}\nF4 shows your workspace · Esc restores the original"
            )

    def on_select_changed(self, event: Select.Changed):
        if event.value is not Select.NULL:
            self._stage()

    def refresh_terminal_preview(self):
        self._stage()

    def _chosen_theme(self, name):
        if name == ":previous":
            name = getattr(self.app, "_previous_theme", "") or load_appearance().previous_theme
        if name:
            from superqode.app.theme_bridge import resolve_selection

            resolved = resolve_selection(name)
            if resolved:
                self.fixed_theme = resolved
                mode = "pair" if "/" in name else name if name in {"system", "auto"} else "fixed"
                self.query_one("#appearance-mode", Select).value = mode
                self.query_one(
                    "#appearance-gallery", Button
                ).label = f"Theme: {theme_display_name(resolved)}"
                for appearance in ("light", "dark"):
                    select = self.query_one(f"#appearance-{appearance}", Select)
                    old = select.value
                    if mode == "pair":
                        old = name.split("/")[0 if appearance == "light" else 1]
                    select.set_options(self._theme_options(appearance, old))
                    select.value = old
        self._stage()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "appearance-gallery":
            from superqode.widgets.theme_picker import ThemePicker

            self.app.push_screen(
                ThemePicker(
                    current=ds.get_theme().name, confirm_label="uses this theme in settings"
                ),
                callback=self._chosen_theme,
            )
        elif event.button.id == "appearance-save":
            self.action_save()
        elif event.button.id == "appearance-cancel":
            self.action_cancel()
        elif event.button.id == "appearance-workspace":
            self.action_workspace()

    def action_workspace(self):
        self._workspace = not self._workspace
        self.set_class(self._workspace, "workspace-view")

    def action_save(self):
        selection, preferences = self._selection(), self._preferences()
        error = save_theme(
            selection, appearance=asdict(preferences), previous_selection=self.original_selection
        )
        if error:
            self.query_one("#appearance-status", Static).update(error)
            return
        self._accepted = True
        self.app._end_theme_preview(self)
        if selection != self.original_selection:
            self.app._previous_theme = self.original_selection
        self.app._current_theme = selection
        apply_theme(selection)
        self.app._apply_appearance(load_appearance())
        self.app._refresh_theme_view()
        self.app._query_terminal_theme()
        self.app._announce_transition(
            title="Appearance saved",
            primary=theme_display_name(ds.get_theme().name),
            detail=f"{preferences.density.title()} spacing · {preferences.motion.title()} animation · {preferences.icons.upper()} icons",
            severity="success",
            popup=True,
            modal=False,
            timeout=3,
        )
        self.dismiss(True)

    def action_cancel(self):
        self.app._end_theme_preview(self)
        self.app._apply_appearance(self.original)
        self.dismiss(False)

    def on_unmount(self):
        self.app._end_theme_preview(self)
        if not self._accepted:
            self.app._apply_appearance(self.original)
