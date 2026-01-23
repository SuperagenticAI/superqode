"""
File Tools - Minimal, Transparent File Operations.

NO fancy algorithms, NO hidden context, NO opinionated formatting.
Just raw file operations that let the model do its thing.

When a QE session is active, writes are routed through the WorkspaceManager
to ensure the immutable repo guarantee.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from .base import Tool, ToolResult, ToolContext
from .validation import validate_path_in_working_directory
from .file_tracking import record_file_read


def _get_workspace():
    """Get the active workspace manager if available."""
    try:
        from superqode.workspace import WorkspaceManager
        from superqode.workspace.manager import get_workspace

        workspace = get_workspace()
        if workspace and workspace.is_active:
            return workspace
    except ImportError:
        pass
    return None


class ReadFileTool(Tool):
    """Read file contents. Simple, no magic."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        # Minimal description - let the model figure out when to use it
        return "Read the contents of a file."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"},
                "start_line": {
                    "type": "integer",
                    "description": "Starting line number (1-indexed, optional)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Ending line number (inclusive, optional)",
                },
            },
            "required": ["path"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path", "")
        start_line = args.get("start_line")
        end_line = args.get("end_line")

        try:
            # Validate and resolve path - ensures it stays within working directory
            file_path = validate_path_in_working_directory(path, ctx.working_directory)
            if not file_path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            if file_path.is_dir():
                return ToolResult(
                    success=False, output="", error=f"Path is a directory, not a file: {path}"
                )

            content = file_path.read_text()

            # Record file read time for edit-conflict detection
            try:
                record_file_read(
                    getattr(ctx, "session_id", "") or "",
                    str(file_path.resolve()),
                    file_path.stat().st_mtime,
                )
            except OSError:
                pass

            # Handle line range if specified
            if start_line is not None or end_line is not None:
                lines = content.split("\n")
                start = (start_line - 1) if start_line else 0
                end = end_line if end_line else len(lines)
                content = "\n".join(lines[start:end])

            return ToolResult(
                success=True,
                output=content,
                metadata={"path": str(file_path), "size": len(content)},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class WriteFileTool(Tool):
    """Write content to a file. Creates directories if needed.

    When a QE session is active, writes go through the WorkspaceManager
    to ensure changes can be tracked and reverted.
    """

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. Creates the file and parent directories if they don't exist."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path", "")
        content = args.get("content", "")

        try:
            # Validate and resolve path - ensures it stays within working directory
            file_path = validate_path_in_working_directory(path, ctx.working_directory)
            # Check if QE session is active - route through workspace
            workspace = _get_workspace()
            if workspace:
                # Get relative path for workspace
                try:
                    rel_path = file_path.relative_to(workspace.project_root)
                    workspace.write_file(str(rel_path), content)
                    return ToolResult(
                        success=True,
                        output=f"Successfully wrote {len(content)} bytes to {path} (tracked for QE revert)",
                        metadata={"path": str(file_path), "size": len(content), "qe_tracked": True},
                    )
                except ValueError:
                    # Path is outside project root, write directly
                    pass

            # Direct write (no QE session or outside project)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} bytes to {path}",
                metadata={"path": str(file_path), "size": len(content)},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class ListDirectoryTool(Tool):
    """List directory contents."""

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return "List files and directories in a path."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list (default: current directory)",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "List recursively (default: false)",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum depth for recursive listing (default: 3)",
                },
            },
            "required": [],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path", ".")
        recursive = args.get("recursive", False)
        max_depth = args.get("max_depth", 3)

        try:
            # Validate and resolve path - ensures it stays within working directory
            dir_path = validate_path_in_working_directory(path, ctx.working_directory)
            if not dir_path.exists():
                return ToolResult(success=False, output="", error=f"Directory not found: {path}")

            if not dir_path.is_dir():
                return ToolResult(
                    success=False, output="", error=f"Path is not a directory: {path}"
                )

            entries = []

            if recursive:
                entries = self._list_recursive(dir_path, dir_path, max_depth, 0)
            else:
                for entry in sorted(dir_path.iterdir()):
                    prefix = "[DIR] " if entry.is_dir() else "[FILE]"
                    entries.append(f"{prefix} {entry.name}")

            output = "\n".join(entries) if entries else "(empty directory)"

            return ToolResult(
                success=True, output=output, metadata={"path": str(dir_path), "count": len(entries)}
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def _list_recursive(self, base: Path, current: Path, max_depth: int, depth: int) -> list:
        """Recursively list directory contents."""
        if depth >= max_depth:
            return []

        entries = []
        indent = "  " * depth

        try:
            for entry in sorted(current.iterdir()):
                # Skip hidden and common ignore patterns
                if entry.name.startswith(".") or entry.name in (
                    "node_modules",
                    "__pycache__",
                    "venv",
                    ".git",
                ):
                    continue

                rel_path = entry.relative_to(base)

                if entry.is_dir():
                    entries.append(f"{indent}[DIR] {rel_path}/")
                    entries.extend(self._list_recursive(base, entry, max_depth, depth + 1))
                else:
                    entries.append(f"{indent}[FILE] {rel_path}")
        except PermissionError:
            pass

        return entries
