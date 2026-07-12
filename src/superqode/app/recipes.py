"""Small dataclasses used by the TUI: prompt-completion candidates and
local reusable workflow recipes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PromptCompletionCandidate:
    """A contextual prompt completion candidate."""

    value: str
    label: str
    description: str = ""
    kind: str = "command"
@dataclass
class LocalRecipe:
    """A local reusable TUI workflow recipe."""

    name: str
    description: str = ""
    path: Path | None = None
    prompt: str = ""
    prompt_file: str = ""
    provider: str = ""
    model: str = ""
    mode: str = ""
    role: str = ""
    skills: tuple[str, ...] = ()
    attachments: tuple[str, ...] = ()
    mcp_resources: tuple[str, ...] = ()
    harness: str = ""
    variables: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)
