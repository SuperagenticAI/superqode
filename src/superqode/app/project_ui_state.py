"""Per-project TUI layout and last-session preferences.

Stored under ``.superqode/ui-state.json`` in the project working directory so
returning to a repo restores the sidebar width and last selected session id
without sending a prompt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


UI_STATE_FILENAME = "ui-state.json"
DEFAULT_SIDEBAR_WIDTH = 34


def ui_state_path(cwd: str | Path | None = None) -> Path:
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    return root / ".superqode" / UI_STATE_FILENAME


def load_ui_state(cwd: str | Path | None = None) -> dict[str, Any]:
    path = ui_state_path(cwd)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_ui_state(updates: dict[str, Any], *, cwd: str | Path | None = None) -> dict[str, Any]:
    path = ui_state_path(cwd)
    current = load_ui_state(cwd)
    current.update({key: value for key, value in updates.items() if value is not None})
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            stream.write(json.dumps(current, indent=2, sort_keys=True) + "\n")
            stream.flush()
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return current


def get_last_session_id(cwd: str | Path | None = None) -> str:
    return str(load_ui_state(cwd).get("last_session_id") or "").strip()


def set_last_session_id(session_id: str, *, cwd: str | Path | None = None) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    save_ui_state({"last_session_id": sid}, cwd=cwd)


def get_sidebar_width(cwd: str | Path | None = None, default: int = DEFAULT_SIDEBAR_WIDTH) -> int:
    raw = load_ui_state(cwd).get("sidebar_width", default)
    try:
        return max(30, min(150, int(raw)))
    except (TypeError, ValueError):
        return default


def set_sidebar_width(width: int, *, cwd: str | Path | None = None) -> None:
    try:
        value = max(30, min(150, int(width)))
    except (TypeError, ValueError):
        return
    save_ui_state({"sidebar_width": value}, cwd=cwd)


def get_connection_preferences(cwd: str | Path | None = None) -> tuple[list[str], list[str]]:
    """Only profile ids are stored; credentials and endpoint URLs never enter UI state."""
    state = load_ui_state(cwd)

    def ids(key: str) -> list[str]:
        value = state.get(key)
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(v for v in value if isinstance(v, str) and 0 < len(v) < 128))[:30]

    return ids("favorite_connections"), ids("recent_connections")


def set_connection_favorites(ids: list[str], *, cwd: str | Path | None = None) -> None:
    save_ui_state({"favorite_connections": list(dict.fromkeys(ids))[:30]}, cwd=cwd)


def remember_connection(profile_id: str, *, cwd: str | Path | None = None) -> None:
    if not profile_id:
        return
    _, recent = get_connection_preferences(cwd)
    save_ui_state(
        {"recent_connections": [profile_id, *[i for i in recent if i != profile_id]][:30]}, cwd=cwd
    )


__all__ = [
    "DEFAULT_SIDEBAR_WIDTH",
    "UI_STATE_FILENAME",
    "get_connection_preferences",
    "set_connection_favorites",
    "remember_connection",
    "get_last_session_id",
    "get_sidebar_width",
    "load_ui_state",
    "save_ui_state",
    "set_last_session_id",
    "set_sidebar_width",
    "ui_state_path",
]
