"""Filesystem layout for the native RLM harness."""

from __future__ import annotations

import os
from pathlib import Path

from superqode.pipy.config import encode_cwd

ENV_AGENT_DIR = "SUPERQODE_RLM_DIR"
ENV_SESSION_DIR = "SUPERQODE_RLM_SESSION_DIR"
SESSION_INDEX_NAME = "superqode-index.json"


def agent_dir() -> Path:
    override = os.environ.get(ENV_AGENT_DIR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".superqode" / "rlm"


def sessions_root() -> Path:
    override = os.environ.get(ENV_SESSION_DIR)
    if override:
        return Path(override).expanduser()
    return agent_dir() / "sessions"


def session_dir_for(cwd: str | Path) -> Path:
    return sessions_root() / encode_cwd(cwd)


def session_index_for(cwd: str | Path) -> Path:
    return session_dir_for(cwd) / SESSION_INDEX_NAME


__all__ = [
    "ENV_AGENT_DIR",
    "ENV_SESSION_DIR",
    "SESSION_INDEX_NAME",
    "agent_dir",
    "session_dir_for",
    "session_index_for",
    "sessions_root",
]
