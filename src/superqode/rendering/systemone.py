"""Theme-aware JSON presentation for typed System One decisions."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from rich.box import ROUNDED
from rich.panel import Panel
from rich.text import Text

_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?')
_IMPORTANT = {
    "status",
    "action",
    "outputs",
    "answers",
    "choice",
    "score",
    "noul",
    "confidence",
    "probabilities",
    "abstained",
    "reason",
}


def render_systemone_json(content: str, theme: Mapping[str, str]) -> Panel | None:
    """Render recognised decision JSON; ordinary prose and JSON use their usual path."""
    try:
        payload = json.loads(content)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or not metadata.get("pack"):
        return None
    if metadata.get("permission") != "systemone" and not (
        payload.get("status") in {"decided", "abstain"}
        and isinstance(payload.get("answers"), dict)
        and isinstance(payload.get("outputs"), dict)
    ):
        return None
    formatted = json.dumps(payload, ensure_ascii=False, indent=2)
    body = Text(formatted, style=theme["muted"], overflow="fold")
    for token in _TOKEN.finditer(formatted):
        raw = token.group()
        is_key = formatted[token.end() :].lstrip().startswith(":")
        if raw.startswith('"'):
            value = json.loads(raw)
            if is_key:
                style = f"bold {theme['cyan']}" if value in _IMPORTANT else theme["purple"]
            elif value in {"deny", "needs_revision"}:
                style = f"bold {theme['error']}"
            elif value in {"ask", "abstain", "ungraded"}:
                style = f"bold {theme['warning']}"
            elif value in {"allow", "satisfied", "decided"}:
                style = f"bold {theme['success']}"
            else:
                style = theme["text"]
        elif raw == "null":
            style = f"bold {theme['warning']}"
        elif raw in {"true", "false"}:
            style = theme["cyan"]
        else:
            style = theme["gold"]
        body.stylize(style, token.start(), token.end())
    return Panel(
        body,
        title=Text("Jev · System One decision", style=f"bold {theme['cyan']}"),
        border_style=theme["purple"],
        box=ROUNDED,
        padding=(1, 2),
        expand=True,
    )
