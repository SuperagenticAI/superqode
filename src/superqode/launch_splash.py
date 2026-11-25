"""Zero-dependency animated launch splash for the SuperQode terminal UI.

Kept outside ``superqode.app`` so ``superqode.main`` can start the spinner
before Textual, Rich, or any widget module is imported.
"""

from __future__ import annotations

import os
import sys
import threading
import time

#: Wordmark gradient, matching the status bar so the splash and the first
#: frame read as the same product rather than two different screens.
_SPLASH_SUPER = ("#a855f7", "#b366f9", "#c177fb", "#cf88fd", "#dd99ff")
_SPLASH_QODE = ("#ec4899", "#f472b6", "#f97316", "#fb923c")
_SPINNER_FRAMES = ("◇", "◈", "◆", "✦", "✧", "✦", "◆", "◈")
_SPINNER_COLORS = (
    "#a855f7",
    "#c177fb",
    "#dd99ff",
    "#ec4899",
    "#f472b6",
    "#f97316",
    "#fb923c",
    "#ec4899",
)
_STATUS_DOTS = ("   ", ".  ", ".. ", "...")

_ACTIVE_SPLASH_LOCK = threading.Lock()
_ACTIVE_SPLASH: LaunchSplash | None = None


def color_mode(environ=None) -> str:
    """Return "none", "standard", "256" or "truecolor".

    NO_COLOR (a non-empty value, per no-color.org) and TERM=dumb disable colour.
    COLORTERM=truecolor/24bit or a *-direct TERM enables 24-bit colour;
    otherwise a 256-colour TERM (including screen/tmux profiles) gets the
    xterm 256-colour palette and anything else the 16 standard colours.
    """
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


def _paint_wordmark(mode: str, *, shimmer_index: int = -1) -> str:
    if mode == "none":
        return "SuperQode"
    palette = _SPLASH_SUPER + _SPLASH_QODE
    word = "SuperQode"
    out = []
    for index, char in enumerate(word):
        if index == shimmer_index:
            color = "#ffffff"
        else:
            color = palette[index % len(palette)]
        out.append(f"\033[1m{sgr_foreground(color, mode)}{char}")
    out.append("\033[0m")
    return "".join(out)


def _format_splash_frame(frame: int, mode: str) -> str:
    if mode == "none":
        return "  <> SuperQode  starting the terminal interface"
    glyph = _SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]
    glyph_color = sgr_foreground(_SPINNER_COLORS[frame % len(_SPINNER_COLORS)], mode)
    bracket_color = sgr_foreground("#c177fb", mode)
    dim = "\033[2;37m"
    reset = "\033[0m"
    shimmer = frame % 14
    wordmark = _paint_wordmark(mode, shimmer_index=shimmer if shimmer < 9 else -1)
    dots = _STATUS_DOTS[(frame // 2) % len(_STATUS_DOTS)]
    return (
        f"  {bracket_color}<{glyph_color}{glyph}{bracket_color}>{reset} "
        f"{wordmark}{dim}  starting the terminal interface{dots}{reset}"
    )


def _can_draw_splash(stream) -> bool:
    try:
        if not stream.isatty():
            return False
    except Exception:  # noqa: BLE001 - a splash must never break a launch
        return False
    if os.environ.get("SUPERQODE_NO_SPLASH"):
        return False
    return True


def _print_launch_splash() -> None:
    """Fill the gap between the shell and the first Textual frame.

    Deliberately dependency-free: anything imported to draw it would add to the
    very delay it exists to cover.
    """
    stream = sys.stdout
    if not _can_draw_splash(stream):
        return

    mode = color_mode()
    try:
        stream.write(f"\n{_format_splash_frame(0, mode)}\n")
        stream.flush()
    except Exception:  # noqa: BLE001 - a splash must never break a launch
        pass


class LaunchSplash:
    """Lightweight animated terminal spinner while the TUI loads."""

    def __init__(self, stream=None, interval: float = 0.08) -> None:
        self._stream = sys.stdout if stream is None else stream
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._animated = False

    def start(self) -> LaunchSplash:
        if self._started or not _can_draw_splash(self._stream):
            return self
        mode = color_mode()
        self._started = True
        if mode == "none":
            try:
                self._stream.write(f"\n{_format_splash_frame(0, mode)}\n")
                self._stream.flush()
            except Exception:  # noqa: BLE001
                pass
            return self

        self._animated = True
        try:
            self._stream.write(f"\033[?25l\r\033[2K{_format_splash_frame(0, mode)}")
            self._stream.flush()
        except Exception:  # noqa: BLE001
            self._animated = False
            return self

        def _animate() -> None:
            frame = 1
            while not self._stop.wait(self._interval):
                try:
                    self._stream.write(f"\r\033[2K{_format_splash_frame(frame, mode)}")
                    self._stream.flush()
                except Exception:  # noqa: BLE001
                    break
                frame += 1

        self._thread = threading.Thread(
            target=_animate,
            name="superqode-launch-splash",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if not self._started:
            return
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.15)
        self._thread = None
        if self._animated:
            try:
                self._stream.write("\r\033[2K\033[?25h")
                self._stream.flush()
            except Exception:  # noqa: BLE001
                pass
            self._animated = False
        self._started = False


def start_launch_splash() -> LaunchSplash:
    """Start (or reuse) the singleton animated launch splash."""
    global _ACTIVE_SPLASH
    with _ACTIVE_SPLASH_LOCK:
        if _ACTIVE_SPLASH is None:
            _ACTIVE_SPLASH = LaunchSplash().start()
        return _ACTIVE_SPLASH


def stop_launch_splash() -> None:
    """Stop and clear any active launch splash before Textual takes over."""
    global _ACTIVE_SPLASH
    with _ACTIVE_SPLASH_LOCK:
        splash = _ACTIVE_SPLASH
        _ACTIVE_SPLASH = None
    if splash is not None:
        splash.stop()
