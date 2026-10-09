"""Adapt owned legacy CSS to semantic variables at the stylesheet boundary."""

from __future__ import annotations

import re
from pathlib import Path

from textual.css.stylesheet import Stylesheet

from superqode.theming import luminance

HEX = re.compile(r"#[0-9a-fA-F]{6}(?![0-9a-fA-F])|#[0-9a-fA-F]{3}(?![0-9a-fA-F])")
DECLARATION = re.compile(r"(?<![\w#.-])([\w-]+)\s*:\s*([^;{}]+)")
COLOR_PROPERTIES = {
    "color",
    "background",
    "background-tint",
    "border",
    "border-top",
    "border-bottom",
    "border-left",
    "border-right",
    "outline",
    "outline-top",
    "outline-bottom",
    "outline-left",
    "outline-right",
    "scrollbar-color",
    "scrollbar-color-active",
    "scrollbar-color-hover",
    "scrollbar-background",
    "scrollbar-background-active",
    "scrollbar-background-hover",
    "scrollbar-corner-color",
    "link-color",
    "link-background",
    "link-color-hover",
    "link-background-hover",
}


def color_role(value: str, property_name: str = "color") -> str:
    color = value.lower()
    if len(color) == 4:
        color = "#" + "".join(c * 2 for c in color[1:])
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    neutral = max(red, green, blue) - min(red, green, blue) < 35
    if "background" in property_name:
        if color == "#2563eb":
            return "selected-bg"
        if neutral or luminance(color) < 0.04:
            return (
                "bg"
                if max(red, green, blue) < 9
                else "surface2"
                if max(red, green, blue) > 24
                else "surface"
            )
        if red > green * 1.5 and red > blue * 1.5:
            return "tool-error-bg"
        if green > red * 1.4 and green > blue:
            return "tool-success-bg"
        return "active"
    if "border" in property_name:
        if neutral:
            return "border" if max(red, green, blue) < 48 else "border-muted"
        return "border-active"
    if neutral:
        return (
            "text"
            if max(red, green, blue) >= 190
            else "muted"
            if max(red, green, blue) >= 140
            else "dim"
        )
    if red > 160 and green > 110 and blue < green:
        return "warning"
    if blue > 80 and blue > green * 1.2:
        return "pink" if red > blue else "purple"
    if red > green * 1.5 and red > blue:
        return "error"
    if green > red * 1.2 and green > blue * 0.8:
        return "success"
    if blue > red * 1.2 and green > red:
        return "cyan"
    return "pink" if red > blue else "purple"


def theme_css(css: str) -> str:
    return DECLARATION.sub(
        lambda declaration: declaration[1]
        + ": "
        + HEX.sub(lambda color: "$sq-" + color_role(color[0], declaration[1]), declaration[2])
        if declaration[1] in COLOR_PROPERTIES and HEX.search(declaration[2])
        else declaration[0],
        css,
    )


class ThemeStylesheet(Stylesheet):
    """Transform only SuperQode styles; third-party CSS retains its semantics."""

    def add_source(self, css, read_from=None, *args, **kwargs):
        if read_from and str(read_from[0]).replace("\\", "/").startswith(
            str(Path(__file__).parents[1]).replace("\\", "/") + "/"
        ):
            css = theme_css(css)
        return super().add_source(css, read_from, *args, **kwargs)

    def copy(self):
        stylesheet = type(self)(variables=self._variables.copy())
        stylesheet.source = self.source.copy()
        return stylesheet
