"""Thin accessors bridging the TUI to the CLI module-level session/mode
state in superqode.main (kept lazy to avoid import cycles)."""

from __future__ import annotations


def get_session():
    from superqode.main import session

    return session


def get_mode():
    from superqode.main import current_mode

    return current_mode


def set_mode(mode: str):
    import superqode.main as m

    m.current_mode = mode
