"""Read-only terminal capabilities; no escape probes or clipboard contents."""

from __future__ import annotations

import os
import shutil
import sys


def terminal_report():
    env = os.environ
    ssh = bool(env.get("SSH_CONNECTION") or env.get("SSH_TTY"))
    tmux = bool(env.get("TMUX"))
    term = env.get("TERM", "unknown")
    program = env.get("TERM_PROGRAM", "unknown")
    size = shutil.get_terminal_size(fallback=(80, 24))
    notes = []
    if term in {"dumb", "unknown"}:
        notes.append(
            "Use a terminal with ANSI color and cursor support for the TUI; headless mode remains available."
        )
    if ssh:
        notes.append(
            "Remote clipboard forwarding depends on your terminal's OSC 52 support and policy."
        )
    if tmux:
        notes.append(
            "If colors or shortcuts differ, check tmux truecolor, escape-time, and clipboard settings."
        )
    return {
        "term": term,
        "program": program,
        "color": env.get("COLORTERM", "unknown"),
        "interactive": sys.stdin.isatty() and sys.stdout.isatty(),
        "width": size.columns,
        "height": size.lines,
        "ssh": ssh,
        "tmux": tmux,
        "screen": bool(env.get("STY")),
        "editor_available": bool(env.get("VISUAL") or env.get("EDITOR")),
        "notes": notes,
        "capabilities_verified": False,
    }
