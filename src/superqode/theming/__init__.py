"""Validated, contrast-aware palettes shared by terminal and export renderers."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import asdict, fields
from pathlib import Path

from superqode import design_system as ds


class ThemeError(ValueError):
    """An invalid palette or an unsuccessful theme operation."""


def luminance(value: str) -> float:
    channels = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(foreground: str, background: str) -> float:
    first, second = sorted((luminance(foreground), luminance(background)))
    return (second + 0.05) / (first + 0.05)


def blend(first: str, second: str, amount: float) -> str:
    return "#" + "".join(
        f"{round(int(first[i : i + 2], 16) * (1 - amount) + int(second[i : i + 2], 16) * amount):02x}"
        for i in (1, 3, 5)
    )


def readable(color: str, backgrounds: list[str], minimum: float = 4.5) -> str:
    """Preserve the source colour when readable; otherwise minimally lift it."""
    if all(contrast(color, bg) >= minimum for bg in backgrounds):
        return color
    target = max(
        ("#ffffff", "#000000"),
        key=lambda candidate: min(contrast(candidate, bg) for bg in backgrounds),
    )
    if min(contrast(target, bg) for bg in backgrounds) < minimum:
        raise ThemeError("Theme surfaces span light and dark; text cannot remain readable on both")
    low, high = 0.0, 1.0
    for _ in range(16):
        midpoint = (low + high) / 2
        if min(contrast(blend(color, target, midpoint), bg) for bg in backgrounds) >= minimum:
            high = midpoint
        else:
            low = midpoint
    return blend(color, target, high)


LIGHT = ds.Theme(
    "light",
    "Light canvas with restrained violet accents",
    ds.ColorPalette(
        bg_void="#fafafa",
        bg_surface="#f4f4f5",
        bg_elevated="#eeeeef",
        bg_hover="#e8e8eb",
        bg_active="#e0e0e5",
        border_subtle="#d4d4d8",
        border_default="#a1a1aa",
        border_strong="#71717a",
        border_focus="#6d28d9",
        primary_dark="#4c1d95",
        primary="#6d28d9",
        primary_light="#7c3aed",
        primary_bright="#6d28d9",
        primary_glow="#7c3aed",
        secondary_dark="#9d174d",
        secondary="#be185d",
        secondary_light="#be185d",
        success="#166534",
        success_light="#166534",
        warning="#854d0e",
        warning_light="#854d0e",
        error="#b91c1c",
        error_light="#b91c1c",
        info="#334155",
        info_light="#334155",
        text_primary="#18181b",
        text_secondary="#27272a",
        text_muted="#52525b",
        text_dim="#52525b",
        text_ghost="#71717a",
        code_bg="#f4f4f5",
        diff_add="#166534",
        diff_remove="#b91c1c",
        diff_change="#854d0e",
    ),
    appearance="light",
)
ds.THEMES.setdefault("light", LIGHT)
BUILTINS = dict(ds.THEMES)

PI_MAP = {
    "accent": "purple",
    "border": "border",
    "borderAccent": "border_active",
    "borderMuted": "border_muted",
    "success": "success",
    "error": "error",
    "warning": "warning",
    "text": "text",
    "muted": "muted",
    "dim": "dim",
    "thinkingText": "thinking",
    "selectedBg": "selected_bg",
    "userMessageBg": "user_bg",
    "userMessageText": "user_text",
    "customMessageBg": "custom_bg",
    "customMessageText": "custom_text",
    "customMessageLabel": "custom_label",
    "toolPendingBg": "tool_pending_bg",
    "toolSuccessBg": "tool_success_bg",
    "toolErrorBg": "tool_error_bg",
    "toolTitle": "tool_title",
    "toolOutput": "tool_output",
    "mdHeading": "md_heading",
    "mdLink": "link",
    "mdLinkUrl": "md_link_url",
    "mdCode": "md_code",
    "mdCodeBlock": "md_code_block",
    "mdCodeBlockBorder": "md_code_border",
    "mdQuote": "md_quote",
    "mdQuoteBorder": "md_quote_border",
    "mdHr": "md_hr",
    "mdListBullet": "md_bullet",
    "toolDiffAdded": "diff_add",
    "toolDiffRemoved": "diff_remove",
    "toolDiffContext": "diff_context",
    **{
        f"syntax{kind.title()}": f"syntax_{kind}"
        for kind in (
            "comment",
            "keyword",
            "function",
            "variable",
            "string",
            "number",
            "type",
            "operator",
            "punctuation",
        )
    },
    **{
        f"thinking{kind.title()}": f"thinking_{kind}"
        for kind in (
            "off",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        )
    },
    "bashMode": "bash_mode",
    "scrollbarTrack": "scrollbar_track",
    "scrollbarThumb": "scrollbar_thumb",
    "searchMatchBg": "search_bg",
    "searchMatchText": "search_text",
}
PI_OPTIONAL = {
    "thinkingMax",
    "scrollbarTrack",
    "scrollbarThumb",
    "searchMatchBg",
    "searchMatchText",
}
PALETTE_FIELDS = {field.name for field in fields(ds.ColorPalette)}
TOKEN_KEYS = set(PI_MAP.values()) | {
    "bg",
    "surface",
    "surface2",
    "hover",
    "active",
    "magenta",
    "pink",
    "rose",
    "orange",
    "gold",
    "yellow",
    "cyan",
    "teal",
    "green",
    "code_bg",
    "selected_text",
    "export_bg",
    "export_card_bg",
    "export_info_bg",
}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MAX_THEME_BYTES = 256 * 1024


def palette_tokens(theme: ds.Theme) -> dict[str, str]:
    c = theme.colors
    result = {
        "bg": c.bg_void,
        "surface": c.bg_surface,
        "surface2": c.bg_elevated,
        "hover": c.bg_hover,
        "active": c.bg_active,
        "border": c.border_subtle,
        "border_active": c.border_focus,
        "border_muted": c.border_default,
        "purple": c.primary_bright,
        "magenta": c.secondary,
        "pink": c.secondary_light,
        "rose": c.error_light,
        "orange": c.warning,
        "gold": c.warning_light,
        "yellow": c.warning_light,
        "cyan": c.info,
        "teal": c.info,
        "green": c.success,
        "success": c.success,
        "error": c.error,
        "warning": c.warning,
        "code_bg": c.code_bg,
        "diff_add": c.diff_add,
        "diff_remove": c.diff_remove,
        "diff_context": c.text_muted,
        "text": c.text_secondary,
        "muted": c.text_muted,
        "dim": c.text_dim,
        "link": c.info,
        "thinking": c.text_dim,
        "user_bg": c.bg_void,
        "user_text": c.text_secondary,
        "custom_bg": c.bg_surface,
        "custom_text": c.text_secondary,
        "custom_label": c.primary_bright,
        "tool_pending_bg": c.bg_elevated,
        "tool_success_bg": c.bg_surface,
        "tool_error_bg": c.bg_surface,
        "tool_title": c.text_secondary,
        "tool_output": c.text_secondary,
        "md_heading": c.text_secondary,
        "md_link_url": c.info,
        "md_code": "#7fb069",
        "md_code_block": c.text_secondary,
        "md_code_border": "#7fb069",
        "md_quote": c.text_muted,
        "md_quote_border": c.border_default,
        "md_hr": c.border_default,
        "md_bullet": c.text_secondary,
        "selected_bg": c.bg_active,
        "selected_text": c.text_primary,
        "search_bg": c.warning_light,
        "search_text": "#18181b" if theme.appearance == "dark" else "#ffffff",
        "scrollbar_track": c.border_subtle,
        "scrollbar_thumb": c.text_muted,
        "bash_mode": c.warning,
        "export_bg": c.bg_void,
        "export_card_bg": c.bg_elevated,
        "export_info_bg": c.bg_surface,
    }
    syntax = {
        "comment": "#8fa398",
        "keyword": "#7fb069",
        "function": "#f97316",
        "variable": c.text_secondary,
        "string": "#eab308",
        "number": "#f97316",
        "type": "#56c2c2",
        "operator": c.text_secondary,
        "punctuation": c.text_muted,
    }
    if theme.name != "superqode":
        syntax.update(
            keyword=c.primary_bright,
            function=c.warning,
            string=c.success,
            number=c.secondary,
            type=c.info,
            comment=c.text_muted,
        )
        result.update(md_code=c.info, md_code_border=c.info)
    result.update({f"syntax_{key}": value for key, value in syntax.items()})
    result.update(
        {
            f"thinking_{key}": c.primary_bright
            for key in (
                "off",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
            )
        }
    )
    result.update(theme.tokens)
    # All small instructional text must work on actual raised surfaces too.
    surfaces = [
        result[key]
        for key in (
            "bg",
            "surface",
            "surface2",
            "hover",
            "active",
            "code_bg",
            "user_bg",
            "custom_bg",
            "tool_pending_bg",
            "tool_success_bg",
            "tool_error_bg",
            "export_bg",
            "export_card_bg",
            "export_info_bg",
        )
    ]
    body_keys = {
        "text",
        "muted",
        "dim",
        "success",
        "error",
        "warning",
        "link",
        "cyan",
        "teal",
        "green",
        "rose",
        "orange",
        "gold",
        "yellow",
        "purple",
        "magenta",
        "pink",
        "thinking",
        "user_text",
        "custom_text",
        "custom_label",
        "tool_title",
        "tool_output",
        "md_heading",
        "md_link_url",
        "md_code",
        "md_code_block",
        "md_quote",
        "md_bullet",
        "diff_add",
        "diff_remove",
        "diff_context",
    } | {key for key in result if key.startswith(("syntax_", "thinking_"))}
    for key in body_keys:
        result[key] = readable(result[key], surfaces)
    result["selected_text"] = readable(result["selected_text"], [result["selected_bg"]])
    result["search_text"] = readable(result["search_text"], [result["search_bg"]])
    return result


def terminal_appearance() -> str:
    background = os.environ.get("SUPERQODE_TERMINAL_BACKGROUND", "")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", background):
        return "light" if luminance(background) > 0.5 else "dark"
    try:
        index = int(os.environ.get("COLORFGBG", "").split(";")[-1])
        return "light" if index in (7, 15) else "dark"
    except ValueError:
        return "dark"


def system_theme(terminal: dict[str, str] | None = None) -> ds.Theme:
    terminal = terminal or {}
    background = terminal.get("bg") or os.environ.get("SUPERQODE_TERMINAL_BACKGROUND", "")
    foreground = terminal.get("fg") or os.environ.get("SUPERQODE_TERMINAL_FOREGROUND", "")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
        background = ""
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", foreground):
        foreground = ""
    appearance = (
        ("light" if luminance(background) > 0.5 else "dark")
        if background
        else terminal_appearance()
    )
    base = LIGHT if appearance == "light" else BUILTINS["superqode"]
    bg = background or base.colors.bg_void
    fg = foreground or base.colors.text_secondary
    target = "#000000" if appearance == "light" else "#ffffff"
    backgrounds = [bg, *(blend(bg, target, amount) for amount in (0.025, 0.04, 0.06, 0.08))]
    if not any(
        all(contrast(endpoint, surface) >= 4.5 for surface in backgrounds)
        for endpoint in ("#000000", "#ffffff")
    ):
        # Near middle gray, raising a surface can cross the point where the
        # readable foreground changes from white to black. Shade away from
        # that boundary so one foreground remains readable on every surface.
        foreground_endpoint = max(("#000000", "#ffffff"), key=lambda color: contrast(color, bg))
        target = "#ffffff" if foreground_endpoint == "#000000" else "#000000"
    values = asdict(base.colors)
    values.update(
        bg_void=bg,
        bg_surface=blend(bg, target, 0.025),
        bg_elevated=blend(bg, target, 0.04),
        bg_hover=blend(bg, target, 0.06),
        bg_active=blend(bg, target, 0.08),
        code_bg=blend(bg, target, 0.025),
        text_secondary=fg,
        text_primary=fg,
        text_muted=blend(fg, bg, 0.2),
        text_dim=blend(fg, bg, 0.35),
    )
    for index, attrs in {
        1: ("error", "error_light", "diff_remove"),
        2: ("success", "success_light", "diff_add"),
        3: ("warning", "warning_light"),
        4: ("info", "info_light"),
        5: ("primary_bright", "secondary", "secondary_light"),
    }.items():
        if str(index) in terminal:
            values.update({key: terminal[str(index)] for key in attrs})
    return ds.Theme(
        "system", "Follow terminal colours and appearance", ds.ColorPalette(**values), appearance
    )


def resolve_colors(values: dict, variables: dict, appearance: str) -> dict[str, str]:
    """Resolve Pi/native colour forms; cycles and invalid inputs are errors."""
    from rich.color import Color as RichColor

    def resolve(value, trail: tuple[str, ...] = (), *, background: bool = False) -> str:
        if isinstance(value, bool):
            raise ThemeError("Boolean is not a colour")
        if isinstance(value, int):
            if not 0 <= value <= 255:
                raise ThemeError("ANSI colour index must be between 0 and 255")
            rgb = RichColor.from_ansi(value).get_truecolor()
            return f"#{rgb.red:02x}{rgb.green:02x}{rgb.blue:02x}"
        if not isinstance(value, str):
            raise ThemeError("Colour must be a string or an ANSI index")
        if not value:
            base = LIGHT if appearance == "light" else BUILTINS["superqode"]
            return base.colors.bg_void if background else base.colors.text_secondary
        if value in variables:
            if value in trail or len(trail) >= 64:
                raise ThemeError(f"Circular colour variable: {' -> '.join((*trail, value))}")
            return resolve(variables[value], (*trail, value), background=background)
        if re.fullmatch(r"#[0-9a-fA-F]{3}", value):
            return "#" + "".join(char * 2 for char in value[1:].lower())
        if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            return value.lower()
        if value.startswith(("oklch(", "okhsl(")):
            from coloraide import Color as BaseColor
            from coloraide.spaces.okhsl import Okhsl

            class Color(BaseColor):
                pass

            Color.register(Okhsl())
            try:
                if value.startswith("okhsl("):
                    parts = value[6:-1].split()
                    if len(parts) != 3 or not value.endswith(")"):
                        raise ValueError("Expected hue, saturation and lightness")
                    coordinates = [
                        float(part[:-1]) / 100 if part.endswith("%") else float(part)
                        for part in parts
                    ]
                    if not all(math.isfinite(c) for c in coordinates):
                        raise ValueError("Non-finite coordinate")
                    color = Color("okhsl", coordinates)
                else:
                    color = Color(value)
                if color.alpha() != 1:
                    raise ValueError("Transparent theme colours are unsupported")
                return color.convert("srgb").fit().to_string(hex=True).lower()
            except (ValueError, TypeError) as exc:
                raise ThemeError(f"Invalid perceptual colour: {value}") from exc
        raise ThemeError(f"Unknown colour or variable: {value!r}")

    return {
        key: resolve(
            value,
            background=key.endswith("_bg")
            or key.startswith("bg_")
            or key
            in {
                "bg",
                "surface",
                "surface2",
                "hover",
                "active",
                "selectedBg",
                "userMessageBg",
                "customMessageBg",
                "toolPendingBg",
                "toolSuccessBg",
                "toolErrorBg",
                "searchMatchBg",
                "pageBg",
                "cardBg",
                "infoBg",
            },
        )
        for key, value in values.items()
    }


def load_theme_file(path: Path) -> ds.Theme:
    try:
        if not path.is_file():
            raise ThemeError(f"Choose a regular JSON file: {path}")
        raw = path.open("rb")
        with raw:
            content = raw.read(MAX_THEME_BYTES + 1)
        if len(content) > MAX_THEME_BYTES:
            raise ThemeError("Theme file exceeds 256 KiB")
        data = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ThemeError(f"Cannot read theme: {exc}") from exc
    if not isinstance(data, dict):
        raise ThemeError("Theme must be a JSON object")
    name = data.get("name", "")
    if (
        not isinstance(name, str)
        or not NAME_RE.fullmatch(name)
        or name in {*BUILTINS, "system", "auto"}
    ):
        raise ThemeError("Theme name must be a unique lowercase slug; built-in names are reserved")
    colors, variables = data.get("colors"), data.get("vars", {})
    if not isinstance(colors, dict) or not isinstance(variables, dict):
        raise ThemeError("colors and vars must be objects")
    is_pi = "accent" in colors
    allowed = (
        {"$schema", "name", "appearance", "vars", "colors", "export"}
        if is_pi
        else {
            "$schema",
            "version",
            "name",
            "description",
            "appearance",
            "vars",
            "colors",
            "tokens",
            "extensions",
        }
    )
    if set(data) - allowed:
        raise ThemeError(f"Unknown theme properties: {', '.join(sorted(set(data) - allowed))}")
    if not is_pi and data.get("version") != 1:
        raise ThemeError("Native themes require version: 1")
    if not is_pi:
        from jsonschema import Draft202012Validator

        schema = json.loads((Path(__file__).parents[1] / "data/themes/schema.json").read_text())
        error = next(Draft202012Validator(schema).iter_errors(data), None)
        if error:
            raise ThemeError(
                f"{'.'.join(map(str, error.absolute_path)) or 'theme'}: {error.message}"
            )
    appearance = data.get("appearance")
    if appearance is None:
        export = data.get("export", {})
        candidate = (
            export.get("pageBg", variables.get("bg", ""))
            if is_pi and isinstance(export, dict)
            else colors.get("bg_void", "")
        )
        background = resolve_colors({"bg": candidate}, variables, "dark")["bg"]
        appearance = "light" if luminance(background) > 0.5 else "dark"
    if not isinstance(appearance, str) or appearance not in {"dark", "light"}:
        raise ThemeError("appearance must be dark or light")
    resolve_colors(variables, variables, appearance)
    unknown = set(colors) - (set(PI_MAP) if is_pi else PALETTE_FIELDS)
    if unknown and not is_pi:
        raise ThemeError(f"Unknown colours: {', '.join(sorted(unknown))}")
    if is_pi and (missing := set(PI_MAP) - PI_OPTIONAL - set(colors)):
        raise ThemeError(f"Missing Pi colours: {', '.join(sorted(missing))}")
    resolved = resolve_colors(
        {key: value for key, value in colors.items() if key not in unknown}, variables, appearance
    )
    extension_values = (
        {key: colors[key] for key in unknown} if is_pi else data.get("extensions", {})
    )
    if not isinstance(extension_values, dict) or any(
        not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key) for key in extension_values
    ):
        raise ThemeError("Invalid extension colour names")
    extensions = resolve_colors(extension_values, variables, appearance)
    base = LIGHT if appearance == "light" else BUILTINS["superqode"]
    tokens = {}
    palette = asdict(base.colors)
    if is_pi:
        tokens = {PI_MAP[key]: value for key, value in resolved.items()}
        exports = data.get("export", {})
        if not isinstance(exports, dict) or set(exports) - {"pageBg", "cardBg", "infoBg"}:
            raise ThemeError("export accepts only pageBg, cardBg and infoBg")
        export_colors = resolve_colors(exports, variables, appearance)
        tokens.update(
            {
                f"export_{key}": value
                for key, value in (
                    ("bg", export_colors.get("pageBg", base.colors.bg_void)),
                    ("card_bg", export_colors.get("cardBg", tokens["user_bg"])),
                    ("info_bg", export_colors.get("infoBg", tokens["custom_bg"])),
                )
            }
        )
        # Pi has no general terminal-background token. Prefer an explicit page
        # background, then the appearance default; message panels stay distinct.
        palette["bg_void"] = tokens["export_bg"]
        palette.update(bg_surface=tokens["custom_bg"], bg_elevated=tokens["user_bg"])
        tokens.setdefault("thinking_max", tokens["thinking_xhigh"])
        tokens.setdefault("scrollbar_track", tokens["muted"])
        tokens.setdefault("scrollbar_thumb", tokens["text"])
        tokens.setdefault("search_bg", tokens["selected_bg"])
        tokens.setdefault("search_text", tokens["text"])
        tokens.update(cyan=tokens["link"], teal=tokens["link"], green=tokens["success"])
        tokens.update(magenta=tokens["purple"], pink=tokens["purple"])
    else:
        palette.update(resolved)
        raw_tokens = data.get("tokens", {})
        if not isinstance(raw_tokens, dict) or set(raw_tokens) - TOKEN_KEYS:
            raise ThemeError("Unknown semantic tokens")
        tokens = resolve_colors(raw_tokens, variables, appearance)
    theme = ds.Theme(
        name,
        str(data.get("description", f"Imported Pi palette: {name}" if is_pi else name))[:160],
        ds.ColorPalette(**palette),
        appearance,
        tokens,
        str(path.resolve()),
        extensions,
    )
    palette_tokens(theme)  # Validate surface contrast before replacing a working theme.
    return theme


def atomic_json(path: Path, data: dict, *, overwrite: bool = True) -> None:
    """Replace only a complete document, with private user-config permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            temporary = Path(file.name)
            json.dump(data, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            # Publish the complete document only if the destination is absent.
            # A concurrent import must never overwrite another developer's file.
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def native_document(theme: ds.Theme) -> dict:
    return {
        "version": 1,
        "name": theme.name,
        "description": theme.description,
        "appearance": theme.appearance,
        "colors": asdict(theme.colors),
        "tokens": theme.tokens,
        "extensions": theme.extensions,
    }
