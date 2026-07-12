"""Welcome/home-screen renderer and small display helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from rich.console import Group
from rich.text import Text

from superqode.app.constants import ASCII_LOGO, GRADIENT, THEME

if TYPE_CHECKING:
    from superqode.app.models import AgentInfo


def render_welcome(
    agents: List[AgentInfo],
    team_name: str = "Development Team",
    width: Optional[int] = None,
) -> Group:
    from rich.align import Align

    # Responsive layout: the ASCII logo and feature columns have a natural
    # width (~62 cols). When the terminal is wider we centre everything in the
    # middle of the screen; when it's narrower we left-align (and let text wrap)
    # so nothing is clipped off the left edge. `width` is the usable log width;
    # None means "unknown" → assume wide and centre.
    logo_lines = [line for line in ASCII_LOGO.strip().split("\n") if line]
    logo_width = max((len(line) for line in logo_lines), default=0)
    content_width = max(logo_width, 62)
    centered = width is None or width >= content_width
    align = "center" if centered else "left"

    def place(renderable):
        return Align.center(renderable) if centered else renderable

    items = []

    # ═══════════════════════════════════════════════════════════════════════
    # BIG ASCII LOGO with gradient - the hero element
    # ═══════════════════════════════════════════════════════════════════════
    logo_text = Text()
    # Extra top padding so the logo sits nearer the vertical middle on open.
    logo_text.append("\n\n", style="")
    if width is not None and width < logo_width:
        # Too narrow for the ASCII art - fall back to a compact wordmark so the
        # banner never gets chopped mid-glyph.
        logo_text.append("✦ ", style=f"bold {GRADIENT[0]}")
        logo_text.append("SuperQode", style=f"bold {GRADIENT[3 % len(GRADIENT)]}")
        logo_text.append(" ✦\n", style=f"bold {GRADIENT[-1]}")
    else:
        for i, line in enumerate(logo_lines):
            color = GRADIENT[i % len(GRADIENT)]
            logo_text.append(f"{line}\n", style=f"bold {color}")
    items.append(place(logo_text))

    # Spacing
    items.append(Text("\n", style=""))

    # ═══════════════════════════════════════════════════════════════════════
    # DESCRIPTION SECTION - keep the home screen quiet and focused.
    # ═══════════════════════════════════════════════════════════════════════
    desc_text = Text(justify=align)
    desc_text.append("Harness Engineering frameworks for Coding Agents\n", style="bold #ffffff")
    desc_text.append("\n", style="")
    desc_text.append("Optimized for Local and Open Models", style=f"bold {THEME['cyan']}")
    desc_text.append("  ·  ", style=THEME["dim"])
    desc_text.append("Build and Optimize Your Harness\n\n", style=f"bold {THEME['gold']}")
    desc_text.append("Connect Anything", style=f"bold {THEME['purple']}")
    desc_text.append("  ·  ", style=THEME["dim"])
    desc_text.append("Local · ACP · MCP · A2A · BYOK · SDKs", style=THEME["muted"])
    desc_text.append("\n", style="")
    items.append(place(desc_text))

    # Spacing
    items.append(Text("\n", style=""))

    # ═══════════════════════════════════════════════════════════════════════
    # QUICK START + KEYS - centered, one entry per line (no column padding so
    # justify=center keeps every row visually centered). Local connection leads.
    # ═══════════════════════════════════════════════════════════════════════
    # Header - centered above the rows.
    header_text = Text(justify=align)
    header_text.append("Quick Start", style=f"bold {THEME['text']}")
    items.append(place(header_text))

    # Rows - left-justified as ONE block so the [n], command and → columns line
    # up; place() then centers the whole block. Pad the command column to a
    # fixed width so every arrow aligns vertically (center-justifying each row
    # independently is what made these drift out of alignment).
    starts = [
        ("1", ":connect", "choose local, BYOK, or an agent", THEME["cyan"]),
        ("2", ":mode", "switch chat / build / plan", THEME["success"]),
        ("3", ":help", "Explore the possibilities of SuperQode", THEME["purple"]),
    ]
    cmd_width = max(len(cmd) for _, cmd, _, _ in starts)
    rows_text = Text(justify="left")
    for idx, (num, cmd, desc, color) in enumerate(starts):
        rows_text.append(f"[{num}] ", style=THEME["dim"])
        rows_text.append(cmd, style=f"bold {color}")
        rows_text.append(" " * (cmd_width - len(cmd)), style="")
        rows_text.append("  →  ", style=THEME["dim"])
        rows_text.append(desc, style=THEME["muted"])
        if idx < len(starts) - 1:
            rows_text.append("\n", style="")
    items.append(place(rows_text))
    items.append(Text("\n\n", style=""))

    # Keys hint - centered.
    keys_text = Text(justify=align)
    keys_text.append("Keys: ", style=THEME["muted"])
    keys_text.append("Ctrl+K", style=f"bold {THEME['cyan']}")
    keys_text.append(" commands  •  ", style=THEME["muted"])
    keys_text.append("Ctrl+B", style=f"bold {THEME['cyan']}")
    keys_text.append(" sidebar  •  ", style=THEME["muted"])
    keys_text.append(":help", style=f"bold {THEME['cyan']}")
    keys_text.append(" reference", style=THEME["muted"])
    items.append(place(keys_text))

    return Group(*items)


def _harness_display_name(name) -> str:
    """Human form of a harness id for TUI labels ("core" -> "Core")."""
    text = str(name or "").strip()
    return text[:1].upper() + text[1:] if text else "-"
