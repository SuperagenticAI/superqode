"""Trusted project Markdown prompts with optional permission narrowing."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import re
import yaml

from .project_trust import get_project_trust

_LIMITS = ContextVar("superqode_project_command_tools", default=None)


@dataclass(frozen=True)
class ProjectCommand:
    name: str
    description: str
    body: str
    allowed_tools: frozenset[str] | None = None

    def expand(self, arguments: str) -> str:
        return self.body.replace("$ARGUMENTS", arguments)


def discover_project_commands(root: Path, reserved=()) -> dict[str, ProjectCommand]:
    from superqode.command_registry import COMMANDS, TUI_COMMAND_ALIASES

    reserved = set(reserved) | {value[1:].split()[0] for value in (*COMMANDS, *TUI_COMMAND_ALIASES)}
    root = root.resolve()
    if not get_project_trust(root).trusted:
        return {}
    directory = root / ".superqode" / "commands"
    if directory.resolve() != directory.absolute():
        return {}
    commands = {}
    for path in sorted(directory.glob("*.md"))[:100]:
        if (
            path.is_symlink()
            or path.resolve() != path.absolute()
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", path.stem)
            or path.stem in reserved
        ):
            continue
        try:
            if path.stat().st_size > 64_000:
                continue
            text = path.read_text(encoding="utf-8")
            metadata = {}
            body = text
            lines = text.splitlines(keepends=True)
            if lines and lines[0].strip() == "---":
                boundary = next(
                    (index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"),
                    None,
                )
                if boundary is None:
                    continue
                metadata = yaml.safe_load("".join(lines[1:boundary])) or {}
                body = "".join(lines[boundary + 1 :])
                if not isinstance(metadata, dict):
                    continue
                if "description" in metadata and not isinstance(metadata["description"], str):
                    continue
            # A command is a prompt, never executable configuration. Reject
            # permission/model/runtime settings rather than ignoring them.
            if set(metadata) - {"description", "allowed_tools"}:
                continue
            tools = metadata.get("allowed_tools")
            if tools is not None and (
                not isinstance(tools, list)
                or not all(isinstance(item, str) and item for item in tools)
            ):
                continue
            if body.strip():
                commands[path.stem] = ProjectCommand(
                    path.stem,
                    str(metadata.get("description") or f"Project command: {path.stem}"),
                    body.strip(),
                    frozenset(tools) if tools is not None else None,
                )
        except (OSError, ValueError, TypeError, yaml.YAMLError):
            continue
    return commands


def command_tool_allowed(name: str) -> bool:
    limits = _LIMITS.get()
    return limits is None or name in limits


@contextmanager
def command_scope(limits):
    current = _LIMITS.get()
    effective = limits if current is None else current if limits is None else current & limits
    token = _LIMITS.set(effective)
    try:
        yield
    finally:
        _LIMITS.reset(token)
