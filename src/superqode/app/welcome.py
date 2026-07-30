"""Welcome/home-screen renderer and small display helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

from rich.console import Group
from rich.text import Text

from superqode.app.constants import ASCII_LOGO, GRADIENT, THEME

if TYPE_CHECKING:
    from superqode.app.models import AgentInfo


@dataclass(frozen=True)
class WelcomeState:
    """Operational state displayed on the terminal home screen."""

    repository: str = ""
    harness: str = ""
    connection: str = ""
    runtime: str = ""
    mode: str = "build"
    approval: str = "ask"

    @property
    def connected(self) -> bool:
        """Return whether a model, agent, or self-contained runtime is active."""
        return bool(self.connection or self.runtime)


def _truncate_middle(value: str, limit: int) -> str:
    """Return a bounded label while retaining both ends of long paths."""
    value = str(value or "")
    if len(value) <= limit:
        return value
    if limit < 8:
        return value[: max(1, limit - 1)] + "…"
    left = (limit - 1) // 2
    right = limit - left - 1
    return f"{value[:left]}…{value[-right:]}"


def render_welcome(
    agents: List[AgentInfo],
    team_name: str = "Development Team",
    width: Optional[int] = None,
    state: Optional[WelcomeState] = None,
) -> Group:
    from rich.align import Align

    del agents  # Retained in the public renderer signature for compatibility.
    state = state or WelcomeState(repository=team_name)

    # The full logo and operational table need approximately 62 columns.
    logo_lines = [line for line in ASCII_LOGO.strip().split("\n") if line]
    logo_width = max((len(line) for line in logo_lines), default=0)
    content_width = max(logo_width, 62)
    centered = width is None or width >= content_width
    narrow = width is not None and width < content_width
    align = "center" if centered else "left"

    def place(renderable):
        return Align.center(renderable) if centered else renderable

    items = []

    logo_text = Text()
    if narrow or (width is not None and width < logo_width):
        logo_text.append("SuperQode", style=f"bold {GRADIENT[3 % len(GRADIENT)]}")
        logo_text.append("\n", style="")
    else:
        for i, line in enumerate(logo_lines):
            color = GRADIENT[i % len(GRADIENT)]
            logo_text.append(f"{line}\n", style=f"bold {color}")
    items.append(place(logo_text))

    desc_text = Text(justify=align)
    if width is None or width >= 48:
        headline = "AGENT ENGINEERING FOR YOUR CODE FACTORY"
    elif width >= 33:
        headline = "YOUR CODE FACTORY"
    elif width >= 19:
        headline = "AGENT ENGINEERING"
    else:
        headline = "SUPERQODE"
    desc_text.append(f"{headline}\n", style="bold #ffffff")
    if not narrow:
        desc_text.append("\n", style="")
        desc_text.append(
            "Harnesses · Context · Memory · Tools · Evaluations · Control loops\n",
            style=f"bold {THEME['cyan']}",
        )
        desc_text.append("\n", style="")
        desc_text.append(
            "Build · Connect · Orchestrate · Evaluate · Optimize\n",
            style=f"bold {THEME['gold']}",
        )
        desc_text.append("\n", style="")
    desc_text.append("Terminal-first · Any agent or model\n", style=f"bold {THEME['purple']}")
    if not narrow:
        desc_text.append("\n", style="")
    interoperability = "Local · ACP · MCP · A2A · BYOK · SDKs"
    if narrow:
        desc_text.append(interoperability, style=THEME["muted"])
    else:
        desc_text.append("Interoperability: ", style=THEME["dim"])
        desc_text.append(interoperability, style=THEME["muted"])
    desc_text.append("\n", style="")
    items.append(place(desc_text))

    if not narrow:
        state_text = Text(justify="left")
        state_text.append("Current workspace\n", style=f"bold {THEME['text']}")
        state_rows = [
            ("Repository", _truncate_middle(state.repository or team_name, 46)),
            ("Harness", state.harness or "Not selected"),
            ("Agent/model", state.connection or state.runtime or "Not connected"),
            ("Policy", f"Approval {state.approval or 'ask'}"),
        ]
        if state.runtime and state.connection:
            state_rows.append(("Runtime", state.runtime))
        label_width = max(len(label) for label, _ in state_rows)
        for index, (label, value) in enumerate(state_rows):
            state_text.append(f"{label:<{label_width}}  ", style=THEME["dim"])
            value_color = (
                THEME["text"] if value not in {"Not selected", "Not connected"} else THEME["muted"]
            )
            state_text.append(_truncate_middle(value, 46), style=value_color)
            state_text.append("\n")
        items.append(place(state_text))

    next_text = Text(justify="left")
    next_text.append("Next step\n", style=f"bold {THEME['text']}")
    steps = [(":connect", "select a local, BYOK, or ACP connection", THEME["cyan"])]
    command_width = max(len(command) for command, _, _ in steps)
    for index, (command, description, color) in enumerate(steps):
        next_text.append(f"{command:<{command_width}}", style=f"bold {color}")
        if not narrow:
            next_text.append("  ", style="")
            next_text.append(description, style=THEME["muted"])
        next_text.append("\n")
    items.append(place(next_text))

    keys_text = Text(justify=align)
    keys_text.append("Ctrl+K", style=f"bold {THEME['cyan']}")
    keys_text.append(" commands  •  ", style=THEME["muted"])
    keys_text.append("Ctrl+B", style=f"bold {THEME['cyan']}")
    keys_text.append(" sidebar  •  ", style=THEME["muted"])
    keys_text.append("Ctrl+C", style=f"bold {THEME['cyan']}")
    keys_text.append(" exit", style=THEME["muted"])
    items.append(place(keys_text))

    home_text = Text(justify=align)
    home_text.append("Return here anytime: ", style=THEME["muted"])
    home_text.append(":home", style=f"bold {THEME['cyan']}")
    items.append(place(home_text))

    return Group(*items)


def _harness_display_name(name) -> str:
    """Human form of a harness id for TUI labels ("core" -> "Core")."""
    text = str(name or "").strip()
    return text[:1].upper() + text[1:] if text else "-"
