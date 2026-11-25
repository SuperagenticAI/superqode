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


from superqode.launch_splash import (
    _SPLASH_QODE,
    _SPLASH_SUPER,
    _print_launch_splash,
    color_mode,
    sgr_foreground,
    start_launch_splash,
    stop_launch_splash,
)


def run_textual_app(**startup):
    """Run the SuperQode Textual TUI application."""
    from superqode.app.colormode import configure_textual_colors

    configure_textual_colors()
    start_launch_splash()
    try:
        # Import from parent module to avoid duplication
        from superqode.app_main import SuperQodeApp

        app = SuperQodeApp(**startup)
    except BaseException:
        stop_launch_splash()
        raise
    stop_launch_splash()
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
