"""
File Tools - Minimal, Transparent File Operations.

NO fancy algorithms, NO hidden context, NO opinionated formatting.
Just raw file operations that let the model do its thing.

When a workspace tracking session is active, writes are routed through the WorkspaceManager
to ensure the immutable repo guarantee.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from .base import Tool, ToolResult, ToolContext
from .validation import (
    validate_path_in_search_scope,
    validate_path_in_working_directory,
)
from .file_tracking import record_file_read
from .diff_utils import build_unified_diff, diff_stats
from .post_edit import verify_edit


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
    """Read file contents with context-economy guards.

    Local models live or die by context budget, so reads are bounded by
    default (line and byte caps), every line is prefixed with its number
    for unambiguous follow-up ranges, overlong lines are clamped, and
    binary/image files are rejected with a clear message instead of a
    decode traceback. Truncated reads tell the model exactly how to
    continue (``start_line`` of the next unread line).
    """

    DEFAULT_MAX_LINES = 2000
    DEFAULT_MAX_BYTES = 50_000
    MAX_LINE_CHARS = 2000
    # Above this size we skip total-line counting to keep reads fast.
    LARGE_FILE_BYTES = 5 * 1024 * 1024

    _IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff"}
    _BINARY_SUFFIXES = {
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".o",
        ".a",
        ".class",
        ".pyc",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".sqlite",
        ".db",
    }

    read_only = True

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a text file. Returns up to "
            f"{self.DEFAULT_MAX_LINES} lines, each prefixed with its line number as "
            "'N: content' (the prefix is not part of the file). For longer files, "
            "call again with start_line set to the next unread line. Use grep to "
            "locate content in very large files."
        )

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

    @staticmethod
    def _looks_binary(sample: bytes) -> bool:
        if b"\x00" in sample:
            return True
        if not sample:
            return False
        # High ratio of non-text bytes => binary. Tolerates UTF-8 multibyte.
        text_bytes = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13) or b >= 128)
        return (text_bytes / len(sample)) < 0.70

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        # Accept the aliases other harnesses use (Claude Code: file_path/offset/
        # limit) — local models trained on those traces emit them routinely.
        path = args.get("path") or args.get("file_path") or args.get("filename") or ""
        start_line = args.get("start_line", args.get("offset"))
        end_line = args.get("end_line")
        if end_line is None and args.get("limit") is not None:
            try:
                end_line = (int(start_line) if start_line else 1) + int(args["limit"]) - 1
            except (TypeError, ValueError):
                end_line = None

        try:
            # Reads may also target configured read-only search roots, so a
            # local model can open a file it found in a downloaded repo.
            file_path = validate_path_in_search_scope(
                path, ctx.working_directory, getattr(ctx, "search_roots", None)
            )
            if not file_path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            if file_path.is_dir():
                return ToolResult(
                    success=False, output="", error=f"Path is a directory, not a file: {path}"
                )

            suffix = file_path.suffix.lower()
            file_size = file_path.stat().st_size
            if suffix in self._IMAGE_SUFFIXES:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"{path} is an image ({suffix}, {file_size:,} bytes). "
                        "This tool reads text files only."
                    ),
                )
            if suffix in self._BINARY_SUFFIXES:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"{path} is a binary file ({suffix}, {file_size:,} bytes) "
                        "and cannot be read as text."
                    ),
                )
            with open(file_path, "rb") as fh:
                if self._looks_binary(fh.read(4096)):
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"{path} appears to be a binary file ({file_size:,} bytes) and cannot be read as text.",
                    )

            # Record file read time for edit-conflict detection
            try:
                record_file_read(
                    getattr(ctx, "session_id", "") or "",
                    str(file_path.resolve()),
                    file_path.stat().st_mtime,
                )
            except OSError:
                pass

            try:
                start = max(1, int(start_line)) if start_line else 1
            except (TypeError, ValueError):
                start = 1
            try:
                end_requested = int(end_line) if end_line else None
            except (TypeError, ValueError):
                end_requested = None

            max_lines = self.DEFAULT_MAX_LINES
            if end_requested is not None:
                max_lines = min(max_lines, max(1, end_requested - start + 1))
            byte_cap = getattr(ctx, "max_output_bytes", None) or self.DEFAULT_MAX_BYTES
            byte_cap = min(byte_cap, self.DEFAULT_MAX_BYTES)

            numbered: list[str] = []
            used_bytes = 0
            line_no = 0
            returned_last = 0
            hit_line_cap = False
            hit_byte_cap = False
            clamped_lines = 0
            with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                for raw_line in fh:
                    line_no += 1
                    if line_no < start:
                        continue
                    if len(numbered) >= max_lines:
                        hit_line_cap = True
                        break
                    text = raw_line.rstrip("\n")
                    if len(text) > self.MAX_LINE_CHARS:
                        text = text[: self.MAX_LINE_CHARS] + "… [line truncated]"
                        clamped_lines += 1
                    entry = f"{line_no}: {text}"
                    entry_bytes = len(entry.encode("utf-8", errors="replace")) + 1
                    if used_bytes + entry_bytes > byte_cap and numbered:
                        hit_byte_cap = True
                        break
                    numbered.append(entry)
                    used_bytes += entry_bytes
                    returned_last = line_no
                # Count remaining lines for accurate guidance (skip on huge files).
                total_lines: Optional[int] = line_no
                if hit_line_cap or hit_byte_cap:
                    if file_size <= self.LARGE_FILE_BYTES:
                        for _ in fh:
                            line_no += 1
                        total_lines = line_no
                    else:
                        total_lines = None

            if not numbered:
                if line_no == 0:
                    return ToolResult(
                        success=True,
                        output="[File is empty]",
                        metadata={"path": str(file_path), "total_lines": 0},
                    )
                if start > line_no:
                    return ToolResult(
                        success=False,
                        output="",
                        error=(f"start_line {start} is past the end of {path} ({line_no} lines)."),
                    )

            output = "\n".join(numbered)
            truncated = hit_line_cap or hit_byte_cap
            if truncated:
                total_text = f"of {total_lines:,} total lines " if total_lines else ""
                reason = "line limit" if hit_line_cap else "size limit"
                output += (
                    f"\n\n[Showing lines {start}-{returned_last} {total_text}({reason} reached). "
                    f'Continue with read_file(path="{path}", start_line={returned_last + 1}).]'
                )
            if clamped_lines:
                output += f"\n[{clamped_lines} overlong line(s) clamped to {self.MAX_LINE_CHARS} chars; use grep for full content.]"

            return ToolResult(
                success=True,
                output=output,
                metadata={
                    "path": str(file_path),
                    "size": file_size,
                    "start_line": start,
                    "end_line": returned_last,
                    "total_lines": total_lines,
                    "truncated": truncated,
                },
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class WriteFileTool(Tool):
    """Write content to a file. Creates directories if needed.

    When a workspace tracking session is active, writes go through the WorkspaceManager
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
            old_content = file_path.read_text() if file_path.exists() else ""
            diff_text = build_unified_diff(old_content, content, path=path)
            additions, deletions = diff_stats(diff_text)
            diff_metadata = {
                "diff_text": diff_text,
                "additions": additions,
                "deletions": deletions,
            }
            # Check if workspace tracking is active - route through workspace
            workspace = _get_workspace()
            if workspace:
                # Get relative path for workspace
                try:
                    rel_path = file_path.relative_to(workspace.project_root)
                    workspace.write_file(str(rel_path), content)
                    return ToolResult(
                        success=True,
                        output=f"Successfully wrote {len(content)} bytes to {path} (tracked for revert)",
                        metadata={
                            "path": str(file_path),
                            "size": len(content),
                            "workspace_tracked": True,
                            **diff_metadata,
                        },
                    )
                except ValueError:
                    # Path is outside project root, write directly
                    pass

            # Direct write (no workspace tracking or outside project)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

            return await verify_edit(
                ToolResult(
                    success=True,
                    output=f"Successfully wrote {len(content)} bytes to {path}",
                    metadata={"path": str(file_path), "size": len(content), **diff_metadata},
                ),
                file_path,
                ctx,
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class CreateFileTool(Tool):
    """Create a new file without overwriting an existing one."""

    @property
    def name(self) -> str:
        return "create_file"

    @property
    def description(self) -> str:
        return "Create a new file. Fails if the file already exists."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to create"},
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path", "")
        content = args.get("content", "")

        try:
            file_path = validate_path_in_working_directory(path, ctx.working_directory)
            if file_path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File already exists: {path}. Use write_file or edit_file to modify it.",
                )

            diff_text = build_unified_diff("", content, path=path)
            additions, deletions = diff_stats(diff_text)
            diff_metadata = {
                "diff_text": diff_text,
                "additions": additions,
                "deletions": deletions,
            }

            workspace = _get_workspace()
            if workspace:
                try:
                    rel_path = file_path.relative_to(workspace.project_root)
                    workspace.write_file(str(rel_path), content)
                    return ToolResult(
                        success=True,
                        output=f"Successfully created {path} ({len(content)} bytes, tracked for revert)",
                        metadata={
                            "path": str(file_path),
                            "size": len(content),
                            "workspace_tracked": True,
                            **diff_metadata,
                        },
                    )
                except ValueError:
                    pass

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

            return await verify_edit(
                ToolResult(
                    success=True,
                    output=f"Successfully created {path} ({len(content)} bytes)",
                    metadata={"path": str(file_path), "size": len(content), **diff_metadata},
                ),
                file_path,
                ctx,
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class ListDirectoryTool(Tool):
    """List directory contents."""

    read_only = True

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
            # Listing is read-only, so configured search roots are allowed too.
            dir_path = validate_path_in_search_scope(
                path, ctx.working_directory, getattr(ctx, "search_roots", None)
            )
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
