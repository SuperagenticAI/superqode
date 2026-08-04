"""Filesystem layout for PiPy.

PiPy mirrors pi's layout under a SuperQode root. It *reads* pi's project-level
resources so an existing pi repository works unchanged, and it *writes* only
under its own root, so a real pi install can never be corrupted.

    ~/.superqode/pipy/
      sessions/
        --Users-shashi-oss-superqode--/
          2026-08-03T09-14-22-013Z_a1b2c3d4.jsonl
      skills/
      prompts/
"""

from __future__ import annotations

import os
from pathlib import Path

#: Overrides the whole PiPy root.
ENV_AGENT_DIR = "SUPERQODE_PIPY_DIR"
#: Overrides just the sessions directory.
ENV_SESSION_DIR = "SUPERQODE_PIPY_SESSION_DIR"


def agent_dir() -> Path:
    """Root for everything PiPy writes."""
    override = os.environ.get(ENV_AGENT_DIR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".superqode" / "pipy"


def sessions_root() -> Path:
    """Directory holding one subdirectory per working directory."""
    override = os.environ.get(ENV_SESSION_DIR)
    if override:
        return Path(override).expanduser()
    return agent_dir() / "sessions"


def skills_dir() -> Path:
    return agent_dir() / "skills"


def prompts_dir() -> Path:
    return agent_dir() / "prompts"


def pi_agent_dir() -> Path:
    """Where a real pi install keeps its state. PiPy never writes here."""
    override = os.environ.get("PI_CODING_AGENT_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".pi" / "agent"


def encode_cwd(cwd: str | Path) -> str:
    """Encode a working directory as a single directory name.

    Same scheme as pi: strip the leading separator, replace separators and
    colons with hyphens, wrap in double hyphens. ``/Users/x/repo`` becomes
    ``--Users-x-repo--``.
    """
    text = str(Path(cwd))
    if text[:1] in ("/", "\\"):
        text = text[1:]
    for char in ("/", "\\", ":"):
        text = text.replace(char, "-")
    return f"--{text}--"


def session_dir_for(cwd: str | Path, root: Path | None = None) -> Path:
    return (root or sessions_root()) / encode_cwd(cwd)


__all__ = [
    "ENV_AGENT_DIR",
    "ENV_SESSION_DIR",
    "agent_dir",
    "encode_cwd",
    "pi_agent_dir",
    "prompts_dir",
    "session_dir_for",
    "sessions_root",
    "skills_dir",
]
