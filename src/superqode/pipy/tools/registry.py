"""Tool factories and the sets pi ships.

Ported from ``packages/coding-agent/src/core/tools/index.ts`` of
earendil-works/pi (MIT).
"""

from __future__ import annotations

from pathlib import Path

from .base import AgentTool
from .files import create_edit_tool, create_read_tool, create_write_tool
from .search import create_find_tool, create_grep_tool, create_ls_tool
from .shell import create_bash_tool

ALL_TOOL_NAMES: tuple[str, ...] = ("read", "bash", "edit", "write", "grep", "find", "ls")

#: The four tools pi enables by default.
CODING_TOOL_NAMES: tuple[str, ...] = ("read", "bash", "edit", "write")

#: Everything that cannot mutate the workspace.
READ_ONLY_TOOL_NAMES: tuple[str, ...] = ("read", "grep", "find", "ls")

_FACTORIES = {
    "read": create_read_tool,
    "write": create_write_tool,
    "edit": create_edit_tool,
    "bash": create_bash_tool,
    "grep": create_grep_tool,
    "find": create_find_tool,
    "ls": create_ls_tool,
}


def create_tool(name: str, cwd: str | Path) -> AgentTool:
    factory = _FACTORIES.get(name)
    if factory is None:
        raise ValueError(f"Unknown tool name: {name}")
    return factory(cwd)


def create_tools(names: tuple[str, ...], cwd: str | Path) -> list[AgentTool]:
    return [create_tool(name, cwd) for name in names]


def create_coding_tools(cwd: str | Path) -> list[AgentTool]:
    """pi's default four."""
    return create_tools(CODING_TOOL_NAMES, cwd)


def create_read_only_tools(cwd: str | Path) -> list[AgentTool]:
    return create_tools(READ_ONLY_TOOL_NAMES, cwd)


def create_all_tools(cwd: str | Path) -> list[AgentTool]:
    return create_tools(ALL_TOOL_NAMES, cwd)


__all__ = [
    "ALL_TOOL_NAMES",
    "CODING_TOOL_NAMES",
    "READ_ONLY_TOOL_NAMES",
    "create_all_tools",
    "create_coding_tools",
    "create_read_only_tools",
    "create_tool",
    "create_tools",
]
