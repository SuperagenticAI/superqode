"""Compact model-facing tools for the native core harness.

These adapters intentionally reuse the established SuperQode tools.  Their
job is to present a small, stable contract to the model without weakening the
existing path validation, permissions, sandbox, tracking, diff, and output
guards behind that contract.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import Tool, ToolContext, ToolResult
from .edit_tools import EditFileTool
from .file_tools import ReadFileTool, WriteFileTool
from .shell_tools import BashTool


class CoreReadTool(Tool):
    """Read bounded text with optional line offset and limit."""

    read_only = True

    def __init__(self) -> None:
        self._delegate = ReadFileTool()

    @property
    def name(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return "Read a text file. Lines are numbered; use offset and limit for large files."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "offset": {"type": "integer", "description": "First line, 1-based"},
                "limit": {"type": "integer", "description": "Maximum lines to return"},
            },
            "required": ["path"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        return await self._delegate.execute(args, ctx)


class CoreWriteTool(Tool):
    """Create or replace one file."""

    def __init__(self) -> None:
        self._delegate = WriteFileTool()

    @property
    def name(self) -> str:
        return "write"

    @property
    def description(self) -> str:
        return "Create or replace a file with the provided content."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Complete file content"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        return await self._delegate.execute(args, ctx)


class CoreEditTool(Tool):
    """Replace one unique text occurrence in an existing file."""

    def __init__(self) -> None:
        self._delegate = EditFileTool()

    @property
    def name(self) -> str:
        return "edit"

    @property
    def description(self) -> str:
        return "Replace one unique block of text in a file. Read the file first."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_text": {"type": "string", "description": "Exact text to replace"},
                "new_text": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        # Core deliberately does not expose replace_all. Ambiguous edits fail
        # and the model must provide a more specific block.
        forwarded = dict(args)
        forwarded["replace_all"] = False
        return await self._delegate.execute(forwarded, ctx)


class CoreBashTool(Tool):
    """Run a foreground repository command."""

    def __init__(self) -> None:
        self._delegate = BashTool()

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Run a shell command for search, inspection, tests, builds, or git status."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
            },
            "required": ["command"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        forwarded = {key: value for key, value in args.items() if key in {"command", "timeout"}}
        return await self._delegate.execute(forwarded, ctx)


__all__ = ["CoreBashTool", "CoreEditTool", "CoreReadTool", "CoreWriteTool"]
