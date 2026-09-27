"""SuperQode brand code theme (purple / pink / orange).

Pygments style used for all agent-output code blocks so code never
renders in blue with a grey highlight. Background is deep plum
(#0f0a1a) to match the response panels.
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
    background_color = "#0f0a1a"
    highlight_color = "#2a1a3e"
    line_number_color = "#ec4899"
    line_number_background_color = "#0f0a1a"
    line_number_special_color = "#f97316"
    line_number_special_background_color = "#2a1a3e"

    styles = {
        Token: "#e4e4e7",
        Comment: "italic #a855f7",
        Comment.Preproc: "#c084fc",
        Keyword: "bold #a855f7",
        Keyword.Constant: "#ec4899",
        Keyword.Declaration: "bold #d946ef",
        Keyword.Namespace: "bold #a855f7",
        Keyword.Type: "#f97316",
        Operator: "#ec4899",
        Operator.Word: "bold #a855f7",
        Name: "#e4e4e7",
        Name.Builtin: "#f97316",
        Name.Function: "bold #f97316",
        Name.Function.Magic: "bold #ec4899",
        Name.Class: "bold #a855f7",
        Name.Decorator: "#ec4899",
        Name.Variable: "#e4e4e7",
        Name.Constant: "#ec4899",
        Name.Attribute: "#f97316",
        Name.Tag: "#a855f7",
        String: "#ec4899",
        String.Doc: "italic #c084fc",
        String.Escape: "bold #f97316",
        String.Interpol: "#f97316",
        Number: "bold #f97316",
        Generic.Heading: "bold #a855f7",
        Generic.Subheading: "bold #ec4899",
        Generic.Deleted: "#fb7185",
        Generic.Inserted: "#f97316",
        Generic.Error: "#fb7185",
        Generic.Emph: "italic #ec4899",
        Generic.Strong: "bold #f97316",
        Generic.Prompt: "bold #a855f7",
        Generic.Output: "#e4e4e7",
        Generic.Traceback: "#fb7185",
        Error: "bold #fb7185 bg:#2a1a3e",
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
