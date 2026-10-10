"""One palette for CSS, Rich output, previews, custom files and exports."""

from __future__ import annotations

import json
from pathlib import Path

from superqode import design_system as ds
from superqode.app.constants import THEME
from superqode.theming import (
    ThemeError,
    atomic_json,
    load_theme_file,
    native_document,
    palette_tokens,
    system_theme,
    terminal_appearance,
)

_CONFIG_PATH = Path.home() / ".superqode" / "config.json"
_theme_errors: list[str] = []
_terminal_colors: dict[str, str] = {}
MAX_CONFIG_BYTES = 1024 * 1024


def _read_theme_config():
    if not _CONFIG_PATH.exists():
        return {}
    if not _CONFIG_PATH.is_file():
        raise ThemeError("Theme preferences must be a regular JSON file")
    with _CONFIG_PATH.open("rb") as stream:
        content = stream.read(MAX_CONFIG_BYTES + 1)
    if len(content) > MAX_CONFIG_BYTES:
        raise ThemeError("Theme preferences exceed 1 MiB; existing configuration was retained")
    return json.loads(content.decode("utf-8"))


def theme_directory() -> Path:
    return _CONFIG_PATH.parent / "themes"


def discover_themes() -> list[str]:
    """Retain last-good themes on invalid/deleted files; report collisions."""
    errors = []
    directory = theme_directory()
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError as exc:
        paths = []
        errors.append(str(exc))
    seen = {}
    for path in paths:
        try:
            theme = load_theme_file(path)
            # Watch the installed link itself, including when dotfiles managers
            # repoint it to a new palette file outside the theme directory.
            theme.source = str(path.absolute())
            existing = ds.THEMES.get(theme.name)
            if theme.name in seen or (
                existing and existing.source not in {"built-in", theme.source}
            ):
                raise ThemeError(f"Duplicate theme name: {theme.name}")
            seen[theme.name] = path
            ds.THEMES[theme.name] = theme
        except ThemeError as exc:
            errors.append(f"{path.name}: {exc}")
    _theme_errors[:] = errors
    ds.THEMES["system"] = system_theme(_terminal_colors)
    update_auto_theme()
    return errors


def theme_errors() -> list[str]:
    return list(_theme_errors)


def _palette_to_theme(colors: ds.ColorPalette) -> dict[str, str]:
    theme = next((t for t in ds.THEMES.values() if t.colors is colors), None)
    return palette_tokens(theme or ds.Theme("palette", "", colors))


def resolve_selection(selection: str) -> str:
    appearance = ds.THEMES["system"].appearance
    if selection == "auto":
        return "light" if appearance == "light" else "superqode"
    if "/" in selection:
        names = selection.split("/")
        if len(names) != 2 or any(name not in ds.THEMES for name in names):
            return ""
        return names[0] if appearance == "light" else names[1]
    return selection if selection in ds.THEMES else ""


def apply_theme(name: str) -> bool:
    selected = resolve_selection(name)
    if not selected:
        return False
    theme = ds.THEMES[selected]
    try:
        tokens = palette_tokens(theme)
    except ThemeError as exc:
        _theme_errors.append(f"{name}: {exc}")
        return False
    ds.set_theme(selected)
    THEME.update(tokens)
    # Legacy widgets import COLORS by reference. Give them the same readable
    # values as CSS/Rich roles while retaining the raw preset for export/editing.
    field_roles = {
        "bg_void": "bg",
        "bg_surface": "surface",
        "bg_elevated": "surface2",
        "bg_hover": "hover",
        "bg_active": "active",
        "code_bg": "code_bg",
        "border_subtle": "border",
        "border_default": "border_muted",
        "border_focus": "border_active",
        "text_primary": "text",
        "text_secondary": "text",
        "text_muted": "muted",
        "text_dim": "dim",
        "text_ghost": "dim",
        "diff_add": "diff_add",
        "diff_remove": "diff_remove",
        "diff_change": "warning",
    }
    for prefix, role in (
        ("primary", "purple"),
        ("secondary", "pink"),
        ("success", "success"),
        ("warning", "warning"),
        ("error", "error"),
        ("info", "cyan"),
    ):
        for field_name in vars(ds.COLORS):
            if field_name == prefix or field_name.startswith(prefix + "_"):
                field_roles[field_name] = role
    for field_name, role in field_roles.items():
        setattr(ds.COLORS, field_name, tokens[role])
    return True


def set_terminal_colors(colors: dict[str, str]) -> None:
    _terminal_colors.update(colors)
    ds.THEMES["system"] = system_theme(_terminal_colors)
    update_auto_theme()


def update_auto_theme() -> None:
    base = ds.get_theme("light" if ds.THEMES["system"].appearance == "light" else "superqode")
    ds.THEMES["auto"] = ds.Theme(
        "auto",
        "Choose SuperQode dark or light with terminal appearance",
        base.colors,
        base.appearance,
        palette_tokens(base),
    )


def available_themes() -> list[tuple[str, str]]:
    return ds.list_themes()


def theme_names() -> list[str]:
    return [name for name, _ in ds.list_themes()]


def active_theme_name() -> str:
    return ds.get_active_theme_name()


def theme_display_name(name: str) -> str:
    """A readable label for a selected palette, including the product spelling."""
    return {"superqode": "SuperQode", "tokyonight": "TokyoNight"}.get(
        name, name.replace("-", " ").title()
    )


def brand_style(color: str):
    """Keep the logo's gradient readable and repaintable on every canvas."""
    from rich.style import Style
    from superqode.theming import readable

    return Style(
        color=readable(color, [THEME["bg"], THEME["surface"]]),
        bold=True,
        meta={"sq_brand": color},
    )


def save_theme(name: str) -> str | None:
    """Return an error if selection applies but cannot be persisted."""
    if not resolve_selection(name):
        return "Unknown theme selection"
    try:
        config = _read_theme_config()
        if not isinstance(config, dict):
            return "Configuration must be an object; existing file was retained"
        # A startup file is temporary, but an explicit Save must also work on
        # the next launch, when project palettes are not discovered implicitly.
        for selected in name.split("/"):
            theme = ds.THEMES[selected]
            if theme.source in {"built-in", "bundled"}:
                continue
            if Path(theme.source).parent.resolve() == theme_directory().resolve():
                continue
            destination = theme_directory() / f"{theme.name}.json"
            atomic_json(destination, native_document(theme), overwrite=False)
            theme.source = str(destination.absolute())
        config["theme"] = name
        atomic_json(_CONFIG_PATH, config)
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        return f"Theme applied but could not be saved: {exc}"
    return None


def load_saved_theme() -> str:
    discover_themes()
    try:
        data = _read_theme_config()
        name = data.get("theme")
        if isinstance(name, str) and resolve_selection(name):
            return name
    except (OSError, ValueError, AttributeError, UnicodeError, RecursionError) as exc:
        _theme_errors.append(
            f"Could not read theme preference; existing configuration retained: {exc}"
        )
    return "superqode"


def import_theme(path: Path) -> str:
    """Import palette data only; convert to our native, versioned document."""
    theme = load_theme_file(path.expanduser())
    if theme.name in ds.THEMES:
        raise ThemeError(f"Theme {theme.name!r} already exists; choose a new name")
    destination = theme_directory() / f"{theme.name}.json"
    if destination.exists():
        raise ThemeError(f"Theme file already exists: {destination}")
    try:
        atomic_json(destination, native_document(theme), overwrite=False)
    except OSError as exc:
        raise ThemeError(f"Could not import theme: {exc}") from exc
    theme.source = str(destination.absolute())
    ds.THEMES[theme.name] = theme
    return theme.name


def load_project_theme(path: Path) -> str:
    """Explicitly load project palette data without changing saved preferences."""
    path = path.expanduser()
    theme = load_theme_file(path)
    existing = ds.THEMES.get(theme.name)
    if existing:
        if (
            existing.source in {"built-in", "bundled"}
            or Path(existing.source).resolve() != path.resolve()
        ):
            raise ThemeError(f"Theme name collision: {theme.name}")
        theme.source = existing.source
    ds.THEMES[theme.name] = theme
    return theme.name


def css_variables() -> dict[str, str]:
    return {"sq-" + key.replace("_", "-"): value for key, value in THEME.items()}


def textual_theme():
    from textual.theme import Theme

    return Theme(
        name="superqode-live",
        primary=THEME["purple"],
        secondary=THEME["pink"],
        warning=THEME["warning"],
        error=THEME["error"],
        success=THEME["success"],
        foreground=THEME["text"],
        background=THEME["bg"],
        surface=THEME["surface"],
        panel=THEME["surface2"],
        dark=ds.get_theme().appearance == "dark",
        variables=css_variables(),
        text_alpha=1,
    )


def bind_strip(strip):
    """Tag owned colours once; later paints resolve roles without replaying state."""
    from rich.segment import Segment
    from rich.style import Style
    from textual.strip import Strip

    roles = {}
    for key in (
        "text",
        "muted",
        "dim",
        "error",
        "warning",
        "success",
        "purple",
        "pink",
        "cyan",
        "diff_add",
        "diff_remove",
        *THEME,
    ):
        roles.setdefault(THEME[key].lower(), key)
    segments = []
    for segment in strip:
        style = segment.style
        if style:
            meta = {}
            for attribute, meta_key in (("color", "sq_fg"), ("bgcolor", "sq_bg")):
                color = getattr(style, attribute)
                if color and color.type.name == "TRUECOLOR" and color.name.lower() in roles:
                    meta[meta_key] = roles[color.name.lower()]
            if meta:
                style = style + Style.from_meta({**meta, **style.meta})
                if style.dim:
                    style = style + Style(dim=False)
        segments.append(Segment(segment.text, style, segment.control))
    return Strip(segments, strip.cell_length)


def recolor_strip(strip):
    from rich.segment import Segment
    from rich.style import Style
    from textual.strip import Strip

    segments = []
    for segment in strip:
        style = segment.style
        if style:
            fg, bg = style.meta.get("sq_fg"), style.meta.get("sq_bg")
            if fg or bg:
                style = style + Style(color=THEME.get(fg), bgcolor=THEME.get(bg))
            if brand := style.meta.get("sq_brand"):
                style = style + brand_style(brand)
        segments.append(Segment(segment.text, style, segment.control))
    return Strip(segments, strip.cell_length)


def theme_legacy_text(text):
    """Recolour legacy status chrome while retaining links and typography."""
    from rich.style import Style
    from rich.text import Span
    from superqode.theming.css import color_role

    if active_theme_name() == "superqode":
        return text

    def restyle(style):
        if isinstance(style, str):
            style = Style.parse(style)
        if not style or not style.color:
            return style
        rgb = style.color.get_truecolor()
        color = f"#{rgb.red:02x}{rgb.green:02x}{rgb.blue:02x}"
        key = color_role(color).replace("-", "_")
        return style + Style(color=THEME.get(key, THEME["text"]))

    result = text.copy()
    result.style = restyle(result.style)
    result.spans = [Span(span.start, span.end, restyle(span.style)) for span in result.spans]
    return result


def load_bundled_themes() -> None:
    directory = Path(__file__).parents[1] / "data" / "themes"
    for path in sorted(directory.glob("*.json")):
        if path.name == "schema.json":
            continue
        try:
            theme = load_theme_file(path)
            theme.source = "bundled"
            ds.THEMES.setdefault(theme.name, theme)
        except ThemeError as exc:
            _theme_errors.append(f"{path.name}: {exc}")


ds.THEMES["system"] = system_theme()
update_auto_theme()
load_bundled_themes()
apply_theme("superqode")
