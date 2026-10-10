"""Reversible workspace previews and developer appearance entry points."""

from __future__ import annotations

from dataclasses import replace

from superqode import design_system as ds
from superqode.app.appearance import load_appearance
from superqode.app.theme_bridge import apply_theme, resolve_selection
from superqode.theming import palette_tokens


class AppearanceMixin:
    def _begin_theme_preview(self, owner) -> None:
        frames = self._theme_previews
        if frames and frames[-1]["owner"] is owner:
            return
        frames.append(
            {"owner": owner, "original": ds.get_theme(), "entries": {}, "fingerprint": None}
        )

    def _preview_workspace_theme(self, owner, theme: ds.Theme) -> None:
        if not self._theme_previews or self._theme_previews[-1]["owner"] is not owner:
            return
        frame = self._theme_previews[-1]
        fingerprint = (theme.name, tuple(sorted(palette_tokens(theme).items())))
        if frame["fingerprint"] == fingerprint:
            return
        frame["fingerprint"] = fingerprint
        if ds.THEMES.get(theme.name) is not theme:
            frame["entries"].setdefault(theme.name, ds.THEMES.get(theme.name))
            ds.THEMES[theme.name] = replace(theme, source="preview")
        apply_theme(theme.name)
        self._refresh_theme_view()

    def _preview_workspace_selection(self, owner, selection: str) -> bool:
        name = resolve_selection(selection)
        if not name:
            return False
        self._preview_workspace_theme(owner, ds.THEMES[name])
        return True

    def _end_theme_preview(self, owner) -> None:
        if not any(frame["owner"] is owner for frame in self._theme_previews):
            return
        while self._theme_previews:
            frame = self._theme_previews.pop()
            for name, original in frame["entries"].items():
                if original is None:
                    ds.THEMES.pop(name, None)
                else:
                    ds.THEMES[name] = original
            original = frame["original"]
            ds.THEMES[original.name] = original
            apply_theme(original.name)
            if frame["owner"] is owner:
                break
        self._refresh_theme_view()
        if not self._theme_previews:
            from superqode.app.theme_bridge import set_terminal_colors, _terminal_colors

            set_terminal_colors(dict(_terminal_colors))
            self._finish_terminal_theme()

    def _apply_appearance(self, preferences) -> None:
        self._appearance = preferences
        if not self.is_running:
            return
        self.default_screen.set_class(preferences.density == "compact", "compact-appearance")
        self.default_screen.set_class(preferences.icons == "ascii", "simple-icons")
        manager = getattr(self, "_animation_manager", None)
        if manager:
            manager.set_low_power(preferences.motion == "reduced")
        if preferences.motion == "reduced":
            self._stop_wave_bursts()
        elif getattr(self, "is_busy", False):
            self._begin_wave_bursts()
        for selector in ("#streaming-thinking", "#status-bar", "#hints", "#mode-badge"):
            for widget in self.query(selector):
                widget.refresh(layout=True)
        for widget in self.query("#streaming-thinking"):
            widget.auto_refresh = (
                None if preferences.motion == "reduced" else (0.5 if widget.is_active else None)
            )
        for widget in self.query("#prompt-input"):
            widget._sync_working_animation()

    def _appearance_cmd(self, log) -> None:
        from superqode.widgets.appearance_settings import AppearanceSettings

        self.push_screen(AppearanceSettings(), callback=lambda _: self._ensure_input_focus())

    def _restore_previous_theme(self, log) -> None:
        previous = getattr(self, "_previous_theme", "") or load_appearance().previous_theme
        if not resolve_selection(previous):
            log.add_info("No previous theme is available yet. Apply another theme first.")
        elif self._apply_and_persist_theme(previous):
            self._report_theme_change(previous, log)

    def _cycle_favorite_theme(self, log) -> None:
        from superqode.theming.library import theme_rows, install_theme
        from superqode.theming import ThemeError

        available = {row["name"] for row in theme_rows()}
        names = [name for name in load_appearance().favorite_themes if name in available]
        if not names:
            log.add_info("Favorite a theme in :theme with Ctrl+S, then use :theme next.")
            return
        current = self._current_theme
        index = (names.index(current) + 1) % len(names) if current in names else 0
        try:
            if not resolve_selection(names[index]):
                install_theme(names[index])
        except ThemeError as exc:
            log.add_error(str(exc))
            return
        if self._apply_and_persist_theme(names[index]):
            self._report_theme_change(names[index], log)

    def _customize_theme(self, log) -> None:
        from superqode.widgets.theme_customizer import ThemeCustomizer

        def chosen(name):
            self._ensure_input_focus()
            if name and self._apply_and_persist_theme(name):
                self._report_theme_change(name, log)

        self.push_screen(ThemeCustomizer(ds.get_theme()), callback=chosen)
