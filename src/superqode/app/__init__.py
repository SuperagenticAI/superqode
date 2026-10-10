"""
SuperQode Textual App Package.

This package contains the TUI application components for SuperQode.
Modules:
- constants.py: Theme, icons, colors, messages
- css.py: Textual CSS styles
- models.py: Data models (AgentInfo, AgentStatus)
- suggester.py: Command autocompletion
- widgets.py: UI widget classes

The main SuperQodeApp class is kept in the parent app.py for now
to maintain backward compatibility, but imports from these modules.
"""

from .constants import (
    ASCII_LOGO,
    COMPACT_LOGO,
    TAGLINE_PART1,
    TAGLINE_PART2,
    GRADIENT,
    RAINBOW,
    THEME,
    ICONS,
    AGENT_COLORS,
    AGENT_ICONS,
    THINKING_MSGS,
    COMMANDS,
)
from .css import APP_CSS
from .models import AgentStatus, AgentInfo, check_installed, load_agents_sync
from .suggester import CommandSuggester
from .widgets import (
    GradientLogo,
    ColorfulStatusBar,
    GradientTagline,
    PulseWaveBar,
    RainbowProgressBar,
    ScanningLine,
    TopScanningLine,
    BottomScanningLine,
    ProgressChase,
    SparkleTrail,
    ThinkingWave,
    StreamingThinkingIndicator,
    ModeBadge,
    HintsBar,
    ConversationLog,
    ApprovalWidget,
    DiffDisplay,
    PlanDisplay,
    ToolCallDisplay,
    FlashMessage,
    DangerWarning,
)


#: Wordmark gradient, matching the status bar so the splash and the first
#: frame read as the same product rather than two different screens.
_SPLASH_SUPER = ("#a855f7", "#b366f9", "#c177fb", "#cf88fd", "#dd99ff")
_SPLASH_QODE = ("#ec4899", "#f472b6", "#f97316", "#fb923c")


def color_mode(environ=None) -> str:
    """Return "none", "standard", "256" or "truecolor".

    NO_COLOR (a non-empty value, per no-color.org) and TERM=dumb disable colour.
    COLORTERM=truecolor/24bit or a *-direct TERM enables 24-bit colour;
    otherwise a 256-colour TERM (including screen/tmux profiles) gets the
    xterm 256-colour palette and anything else the 16 standard colours.
    """
    import os

    environ = os.environ if environ is None else environ
    term = environ.get("TERM", "").lower()
    if environ.get("NO_COLOR") or term in {"", "dumb"}:
        return "none"
    colorterm = environ.get("COLORTERM", "").lower()
    if colorterm in {"truecolor", "24bit"} or term.endswith("-direct"):
        return "truecolor"
    if environ.get("WT_SESSION") or environ.get("TERM_PROGRAM") in {"iTerm.app", "WezTerm"}:
        # Windows Terminal, iTerm2 and WezTerm support 24-bit colour but do
        # not always export COLORTERM, notably over SSH.
        return "truecolor"
    if "256color" in term:
        return "256"
    return "standard"


def _cube(value: int) -> int:
    return 0 if value < 48 else 1 if value < 115 else (value - 35) // 40


def sgr_foreground(hex_color: str, mode: str) -> str:
    """SGR foreground for a #rrggbb colour in the given mode ("" for none)."""
    red, green, blue = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    if mode == "none":
        return ""
    if mode == "truecolor":
        return f"\033[38;2;{red};{green};{blue}m"
    if mode == "256":
        return f"\033[38;5;{16 + 36 * _cube(red) + 6 * _cube(green) + _cube(blue)}m"
    bright = max(red, green, blue) > 160
    code = (1 if red > 127 else 0) + (2 if green > 127 else 0) + (4 if blue > 127 else 0)
    return f"\033[{(90 if bright else 30) + (code or 7)}m"


def _print_launch_splash() -> None:
    """Fill the gap between the shell and the first Textual frame.

    Importing the app and building its widget tree takes most of a second, and
    the terminal sits blank for all of it. Textual switches to the alternate
    screen when it starts, which discards whatever is here, so this is visible
    for exactly the wait and never competes with the real interface.

    Deliberately dependency-free: anything imported to draw it would add to the
    very delay it exists to cover.
    """
    import os
    import sys

    stream = sys.stdout
    try:
        if not stream.isatty():
            return
    except Exception:  # noqa: BLE001 - a splash must never break a launch
        return
    if os.environ.get("SUPERQODE_NO_SPLASH"):
        return

    mode = color_mode()
    plain = mode == "none"

    def paint(text: str, colours) -> str:
        if plain:
            return text
        out = []
        for index, char in enumerate(text):
            out.append(f"\033[1m{sgr_foreground(colours[index % len(colours)], mode)}{char}")
        out.append("\033[0m")
        return "".join(out)

    dim = "" if plain else "\033[2;37m"
    reset = "" if plain else "\033[0m"
    try:
        stream.write(
            f"\n  {paint('Super', _SPLASH_SUPER)}{paint('Qode', _SPLASH_QODE)}"
            f"{dim}  starting the terminal interface{reset}\n"
        )
        stream.flush()
    except Exception:  # noqa: BLE001 - a splash must never break a launch
        pass


def run_textual_app(**startup):
    """Run the SuperQode Textual TUI application."""
    from superqode.app.colormode import configure_textual_colors

    configure_textual_colors()
    _print_launch_splash()

    # Import from parent module to avoid duplication
    from superqode.app_main import SuperQodeApp

    app = SuperQodeApp(**startup)
    try:
        app.run()
    finally:
        from superqode.app.herdr import close

        close(app)


__all__ = [
    # Constants
    "ASCII_LOGO",
    "COMPACT_LOGO",
    "TAGLINE_PART1",
    "TAGLINE_PART2",
    "GRADIENT",
    "RAINBOW",
    "THEME",
    "ICONS",
    "AGENT_COLORS",
    "AGENT_ICONS",
    "THINKING_MSGS",
    "COMMANDS",
    # CSS
    "APP_CSS",
    # Models
    "AgentStatus",
    "AgentInfo",
    "check_installed",
    "load_agents_sync",
    # Suggester
    "CommandSuggester",
    # Widgets
    "GradientLogo",
    "ColorfulStatusBar",
    "GradientTagline",
    "PulseWaveBar",
    "RainbowProgressBar",
    "ScanningLine",
    "TopScanningLine",
    "BottomScanningLine",
    "StreamingThinkingIndicator",
    "ModeBadge",
    "HintsBar",
    "ConversationLog",
    "ApprovalWidget",
    "DiffDisplay",
    "PlanDisplay",
    "ToolCallDisplay",
    "FlashMessage",
    "DangerWarning",
    # Main function
    "run_textual_app",
]
