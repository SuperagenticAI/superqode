"""Bridge between the rich ``design_system`` themes and the render-time palette.

The TUI reads colors at render time from the flat ``THEME`` dict in
``app/constants.py`` (~2000 lookups), while full themes (superqode, tokyonight,
dracula, nord, monokai, gruvbox) are defined as ``ColorPalette`` objects in
``design_system``. Historically ``:theme`` changed the design-system palette but
not ``THEME``, so it required a restart.

This bridge maps a selected ``ColorPalette`` onto ``THEME`` *in place* so theme
changes apply live, and persists the choice to ``~/.superqode/config.json``
(the same file the legacy ``:theme`` command already used).
"""

from __future__ import annotations

import json
from pathlib import Path

from superqode.app.constants import THEME
from superqode import design_system as ds

_CONFIG_PATH = Path.home() / ".superqode" / "config.json"


def _palette_to_theme(colors: "ds.ColorPalette") -> dict[str, str]:
    """Map a design-system ColorPalette onto the flat THEME keys."""
    return {
        "bg": colors.bg_void,
        "surface": colors.bg_void,
        "surface2": colors.bg_elevated,
        "border": colors.border_subtle,
        "border_active": colors.border_default,
        "purple": colors.primary_bright,
        "magenta": colors.secondary,
        "pink": colors.secondary_light,
        "rose": colors.error_light,
        "orange": colors.warning,
        "gold": colors.warning_light,
        "yellow": colors.warning_light,
        "cyan": colors.info,
        "teal": colors.info,
        "green": colors.success,
        "success": colors.success,
        "error": colors.error,
        "warning": colors.warning,
        "text": colors.text_secondary,
        "muted": colors.text_dim,
        "dim": colors.text_ghost,
    }


def apply_theme(name: str) -> bool:
    """Activate the named design-system theme and sync it onto THEME live.

    Returns True if the theme exists, False otherwise.
    """
    if not ds.set_theme(name):
        return False
    THEME.update(_palette_to_theme(ds.get_theme(name).colors))
    return True


def available_themes() -> list[tuple[str, str]]:
    """List ``(name, description)`` for every theme."""
    return ds.list_themes()


def theme_names() -> list[str]:
    return [name for name, _ in ds.list_themes()]


def active_theme_name() -> str:
    return ds.get_active_theme_name()


def save_theme(name: str) -> None:
    """Persist the chosen theme to ``~/.superqode/config.json``."""
    if name not in dict(ds.list_themes()):
        return
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        config: dict = {}
        if _CONFIG_PATH.exists():
            try:
                config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                config = {}
        config["theme"] = name
        _CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_saved_theme() -> str:
    """Return the persisted theme name, or the default ('superqode')."""
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        name = data.get("theme")
        if name in dict(ds.list_themes()):
            return name
    except Exception:
        pass
    return ds.get_active_theme_name()
