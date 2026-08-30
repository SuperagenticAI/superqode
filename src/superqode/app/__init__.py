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

    plain = bool(os.environ.get("NO_COLOR")) or os.environ.get("TERM", "") in {"", "dumb"}

    def paint(text: str, colours) -> str:
        if plain:
            return text
        out = []
        for index, char in enumerate(text):
            red, green, blue = (
                int(colours[index % len(colours)][slice_], 16)
                for slice_ in (slice(1, 3), slice(3, 5), slice(5, 7))
            )
            out.append(f"\033[1;38;2;{red};{green};{blue}m{char}")
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


def run_textual_app():
    """Run the SuperQode Textual TUI application."""
    _print_launch_splash()

    # Import from parent module to avoid duplication
    from superqode.app_main import SuperQodeApp

    app = SuperQodeApp()
    app.run()


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
