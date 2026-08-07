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


def _inventory_lines() -> List[tuple[str, str]]:
    """Return the Active/Available rows, if a probe has already run.

    Never probes: counting installed capabilities imports runtime adapters and
    walks registries, which is too slow for the startup path. ``:explore``
    fills the cache; until then these rows are omitted.
    """
    try:
        from superqode.app.capabilities import cached_inventory

        by_id = {capability.id: capability for capability in cached_inventory()}
    except Exception:  # noqa: BLE001 - the home screen must always render
        return []
    if not by_id:
        return []

    def count(key: str, attribute: str) -> int:
        capability = by_id.get(key)
        return int(getattr(capability, attribute, 0)) if capability else 0

    active_parts = []
    memory = by_id.get("memory")
    if memory and memory.active:
        active_parts.append(f"memory {memory.active} on")
    local = by_id.get("local")
    if local and local.active:
        active_parts.append(f"{local.active} local engines")
    tools = count("tools", "total")
    if tools:
        active_parts.append(f"{tools} tools")

    # Four categories overflow the 46-column value budget, and runtimes are an
    # advanced dial rather than a headline number. The full inventory is one
    # keystroke away in :explore.
    available_parts = []
    for key, noun in (
        ("agents", "agents"),
        ("providers", "providers"),
        ("harnesses", "harnesses"),
    ):
        total = count(key, "total")
        if total:
            available_parts.append(f"{total} {noun}")

    rows = []
    if active_parts:
        rows.append(("Active", " · ".join(active_parts)))
    if available_parts:
        rows.append(("Available", " · ".join(available_parts)))
    return rows


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


def _next_steps(state: WelcomeState) -> List[tuple[str, str, str]]:
    """Return the next step matching the user's recorded progress."""
    if not state.connected:
        return [
            (":connect", "choose who runs the coding loop", THEME["cyan"]),
            (":help", "see every command", THEME["cyan"]),
        ]

    try:
        from superqode.app.progress import load_progress

        milestones = load_progress().milestones
    except Exception:  # noqa: BLE001 - the home screen must always render
        milestones = set()

    if "built_harness" in milestones and "ran_eval" not in milestones:
        return [(":eval", "measure the harness you built", THEME["cyan"])]
    if "compared_harnesses" in milestones:
        return [(":eval", "score the harnesses you compared", THEME["cyan"])]
    if "task_completed" in milestones:
        return [(":harness", "swap the tool loop, keep the session", THEME["cyan"])]
    return [("just type", "describe what you want built", THEME["cyan"])]


def render_welcome(
    agents: List[AgentInfo],
    team_name: str = "Development Team",
    width: Optional[int] = None,
    state: Optional[WelcomeState] = None,
) -> Group:
    from rich.align import Align

    del agents  # Retained in the public renderer signature for compatibility.
    state = state or WelcomeState(repository=team_name)

    # Once a connection exists, the home screen is an operational checkpoint,
    # not an onboarding page. Keep the full product story for first use and
    # give returning users only their current state and one useful next action.
    if state.connected:
        value_limit = max(18, min(46, int(width or 100) - 18))
        items = []

        title = Text()
        title.append("SuperQode\n", style=f"bold {GRADIENT[3 % len(GRADIENT)]}")
        items.append(title)

        workspace = Text()
        workspace.append("Current workspace\n", style=f"bold {THEME['text']}")
        rows = [
            ("Repository", state.repository or team_name),
            ("Harness", state.harness or "Not selected"),
            ("Agent/model", state.connection or state.runtime),
            ("Policy", f"Approval {state.approval or 'ask'}"),
        ]
        if state.runtime and state.connection:
            rows.append(("Runtime", state.runtime))
        label_width = max(len(label) for label, _value in rows)
        for label, value in rows:
            workspace.append(f"{label:<{label_width}}  ", style=THEME["dim"])
            workspace.append(_truncate_middle(value, value_limit), style=THEME["text"])
            workspace.append("\n")
        items.append(workspace)

        command, description, color = _next_steps(state)[0]
        next_text = Text()
        next_text.append("Next  ", style=f"bold {THEME['text']}")
        next_text.append(command, style=f"bold {color}")
        if width is None or width >= 48:
            next_text.append(f"  {description}", style=THEME["muted"])
        next_text.append("\n")
        items.append(next_text)

        footer = Text()
        footer.append(":explore", style=f"bold {THEME['cyan']}")
        footer.append(" capabilities  •  ", style=THEME["muted"])
        footer.append(":tour", style=f"bold {THEME['cyan']}")
        footer.append(" progress  •  ", style=THEME["muted"])
        footer.append(":home", style=f"bold {THEME['cyan']}")
        footer.append(" refresh  •  ", style=THEME["muted"])
        footer.append(":disconnect", style=f"bold {THEME['pink']}")
        footer.append(" end session", style=THEME["muted"])
        items.append(footer)

        return Group(*items)

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
        state_rows = [("Repository", _truncate_middle(state.repository or team_name, 46))]
        # Before anything is connected these rows only report absence, which is
        # what the next step already says. They appear once they carry news.
        if state.connected:
            state_rows.extend(
                [
                    ("Harness", state.harness or "Not selected"),
                    ("Agent/model", state.connection or state.runtime or "Not connected"),
                    ("Policy", f"Approval {state.approval or 'ask'}"),
                ]
            )
            if state.runtime and state.connection:
                state_rows.append(("Runtime", state.runtime))
        state_rows.extend(_inventory_lines())
        label_width = max(len(label) for label, _ in state_rows)
        for index, (label, value) in enumerate(state_rows):
            state_text.append(f"{label:<{label_width}}  ", style=THEME["dim"])
            value_color = (
                THEME["text"] if value not in {"Not selected", "Not connected"} else THEME["muted"]
            )
            state_text.append(_truncate_middle(value, 46), style=value_color)
            state_text.append("\n")
        items.append(place(state_text))

    # No next step and no key list here. The prompt placeholder names the
    # first command, and the bar directly under it carries the same commands
    # as clickable controls, so repeating them on the home screen was noise
    # between the product and the box the user types into.
    if not narrow:
        # Neither input style is discoverable on its own: mouse users do not
        # try clicking a terminal, and Vim users do not expect one to answer j/k.
        drive_text = Text(justify=align)
        drive_text.append("Browse it like a browser", style=f"bold {THEME['cyan']}")
        drive_text.append(" with your mouse", style=THEME["dim"])
        drive_text.append("  ·  or drive it like a pro with ", style=THEME["muted"])
        drive_text.append(":", style=f"bold {THEME['success']}")
        drive_text.append(" and ", style=THEME["muted"])
        drive_text.append(":vim on", style=f"bold {THEME['success']}")
        items.append(place(drive_text))

    return Group(*items)


#: Harness ids whose product name is not simply the id capitalised.
_HARNESS_NAME_OVERRIDES = {"pipy": "PiPy", "prime-agent": "Prime Agent"}


def _harness_display_name(name) -> str:
    """Human form of a harness id for TUI labels ("core" -> "Core")."""
    text = str(name or "").strip()
    if not text:
        return "-"
    override = _HARNESS_NAME_OVERRIDES.get(text.lower())
    return override or (text[:1].upper() + text[1:])
