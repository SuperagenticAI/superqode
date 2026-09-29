"""SuperQode brand code theme (green / yellow / orange / cyan).

Pygments style used for all agent-output code blocks so code never
renders in blue. No background fill: every Syntax caller passes
``background_color="default"`` so blocks blend into the terminal.
"""

from __future__ import annotations

from pygments.style import Style
from pygments.token import (
    Comment,
    Error,
    Generic,
    Keyword,
    Name,
    Number,
    Operator,
    String,
    Token,
)


class SuperQodeStyle(Style):
    background_color = "#101014"
    highlight_color = "#232329"
    line_number_color = "#ec4899"
    line_number_background_color = "#101014"
    line_number_special_color = "#f97316"
    line_number_special_background_color = "#232329"

    styles = {
        Token: "#e4e4e7",
        Comment: "italic #8fa398",
        Comment.Preproc: "#eab308",
        Keyword: "#7fb069",
        Keyword.Constant: "#eab308",
        Keyword.Declaration: "#56c2c2",
        Keyword.Namespace: "#7fb069",
        Keyword.Type: "#56c2c2",
        Operator: "#d4d4d8",
        Operator.Word: "#7fb069",
        Name: "#e4e4e7",
        Name.Builtin: "#56c2c2",
        Name.Function: "bold #f97316",
        Name.Function.Magic: "#ec4899",
        Name.Class: "#fbbf24",
        Name.Decorator: "#ec4899",
        Name.Variable: "#e4e4e7",
        Name.Constant: "#56c2c2",
        Name.Attribute: "#fb923c",
        Name.Tag: "#7fb069",
        String: "#eab308",
        String.Doc: "italic #8fa398",
        String.Escape: "bold #f97316",
        String.Interpol: "#fb923c",
        Number: "bold #f97316",
        Generic.Heading: "#7fb069",
        Generic.Subheading: "#ec4899",
        Generic.Deleted: "#fb7185",
        Generic.Inserted: "#7fb069",
        Generic.Error: "#fb7185",
        Generic.Emph: "italic #ec4899",
        Generic.Strong: "bold #fbbf24",
        Generic.Prompt: "#eab308",
        Generic.Output: "#e4e4e7",
        Generic.Traceback: "#fb7185",
        Error: "bold #fb7185",
    }


def register() -> None:
    """Register ``superqode`` as a Pygments style name (idempotent)."""
    try:
        from pygments.styles import STYLE_MAP, _STYLE_NAME_TO_MODULE_MAP

        STYLE_MAP["superqode"] = "superqode.code_theme::SuperQodeStyle"
        _STYLE_NAME_TO_MODULE_MAP["superqode"] = (
            "superqode.code_theme",
            "SuperQodeStyle",
        )
    except Exception:
        pass


register()
