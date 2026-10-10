"""Terminal colour capability detection applied to Textual before startup.

color_mode and sgr_foreground live in superqode.app so the launch splash can
use them without importing anything.
"""

from __future__ import annotations

import os

from superqode.app import _cube, color_mode, sgr_foreground  # noqa: F401

_TEXTUAL_SYSTEM = {"truecolor": "truecolor", "256": "256", "standard": "standard"}


def configure_textual_colors(environ=None) -> str:
    """Apply the detected mode to Textual before the app is constructed.

    An explicit TEXTUAL_COLOR_SYSTEM always wins. TERM=dumb is mapped to
    NO_COLOR so Textual renders monochrome.
    """
    environ = os.environ if environ is None else environ
    mode = color_mode(environ)
    if mode == "none":
        # Textual renders NO_COLOR as monochrome. Pair it with the 16-colour
        # system so dumb terminals get basic SGR, never 24-bit sequences.
        environ.setdefault("NO_COLOR", "1")
    system = environ.get("TEXTUAL_COLOR_SYSTEM") or _TEXTUAL_SYSTEM.get(mode, "standard")
    environ.setdefault("TEXTUAL_COLOR_SYSTEM", system)
    import sys

    constants = sys.modules.get("textual.constants")
    if constants is not None and environ is os.environ:
        constants.COLOR_SYSTEM = environ["TEXTUAL_COLOR_SYSTEM"]
    return mode
