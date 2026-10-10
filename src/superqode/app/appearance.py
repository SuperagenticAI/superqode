"""Private appearance preferences; previews never write configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from superqode.app import theme_bridge
from superqode.theming import ThemeError, atomic_json


@dataclass
class AppearancePreferences:
    density: str = "comfortable"
    motion: str = "full"
    icons: str = "unicode"
    favorite_themes: list[str] = field(default_factory=list)
    recent_themes: list[str] = field(default_factory=list)
    previous_theme: str = ""

    @classmethod
    def from_dict(cls, raw) -> AppearancePreferences:
        raw = raw if isinstance(raw, dict) else {}

        def choice(key, choices, default):
            value = raw.get(key)
            return value if isinstance(value, str) and value in choices else default

        def names(key):
            value = raw.get(key)
            if not isinstance(value, list):
                return []
            return list(
                dict.fromkeys(
                    name for name in value if isinstance(name, str) and 0 < len(name) <= 193
                )
            )[:30]

        previous = raw.get("previous_theme", "")
        return cls(
            density=choice("density", {"comfortable", "compact"}, "comfortable"),
            motion=choice("motion", {"full", "reduced"}, "full"),
            icons=choice("icons", {"unicode", "ascii"}, "unicode"),
            favorite_themes=names("favorite_themes"),
            recent_themes=names("recent_themes"),
            previous_theme=previous if isinstance(previous, str) and len(previous) <= 193 else "",
        )


def load_appearance() -> AppearancePreferences:
    try:
        config = theme_bridge._read_theme_config()
        return AppearancePreferences.from_dict(config.get("appearance"))
    except (OSError, ValueError, UnicodeError, RecursionError, AttributeError):
        return AppearancePreferences()


def save_appearance(updates: dict) -> str | None:
    try:
        config = theme_bridge._read_theme_config()
        if not isinstance(config, dict):
            raise ThemeError("Configuration must be an object; existing file was retained")
        raw = config.get("appearance")
        raw = dict(raw) if isinstance(raw, dict) else {}
        raw.update(updates)
        config["appearance"] = {**raw, **asdict(AppearancePreferences.from_dict(raw))}
        atomic_json(theme_bridge._CONFIG_PATH, config)
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        return f"Appearance could not be saved: {exc}"
    return None


def toggle_favorite(name: str) -> str | None:
    names = load_appearance().favorite_themes
    names = [item for item in names if item != name] if name in names else [name, *names][:30]
    return save_appearance({"favorite_themes": names})


def simple_text(text):
    """Replace product chrome glyphs while preserving Rich spans and hit widths."""
    from rich.text import Text
    from rich.console import Console

    replacements = {
        "🔌": "+ ",
        "⚓": "# ",
        "⏻": "x",
        "⏏": "-",
        "↑": "^",
        "↓": "v",
        "●": "*",
        "○": "o",
        "✓": "+",
        "✗": "x",
        "⟳": "~",
        "⎇": "g",
        "│": "|",
        "·": ".",
        "…": ".",
        "★": "*",
        "☆": "+",
        "↗": ">",
        "🤖": "@ ",
        "🧪": "T ",
        "📊": "M ",
        "🔗": "= ",
        "🐍": "P ",
        "⚡": "! ",
        "◆": "*",
        "☁": "~",
        "🟢": "+ ",
        "🟡": "? ",
        "🔴": "x ",
        "🏠": "H ",
        "›": ">",
        "◇": "o",
        "◈": "#",
        "🧠": "M ",
        "🧭": "> ",
        "•": ".",
        "️": "",
    }
    result = Text()
    console = Console()
    for index, character in enumerate(text.plain):
        result.append(
            replacements.get(character, character), style=text.get_style_at_offset(console, index)
        )
    return result


def appearance_text(widget, text):
    from textual._context import NoActiveAppError

    try:
        preferences = getattr(widget.app, "_appearance", None)
    except NoActiveAppError:
        return text
    return simple_text(text) if getattr(preferences, "icons", "unicode") == "ascii" else text
