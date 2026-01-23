"""
Edit Tools - File Editing Operations.

Provides multiple editing strategies:
- EditFileTool: Simple string replacement (exact match)
- InsertTextTool: Insert at line number
- PatchTool: Apply unified diffs (like git patches)
- MultiEditTool: Batch multiple edits atomically

When a QE session is active, edits are tracked through the WorkspaceManager
to ensure the immutable repo guarantee.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re

from .base import Tool, ToolResult, ToolContext
from .validation import validate_path_in_working_directory
from .file_tracking import check_file_unchanged
from ..agent.edit_strategies import replace_with_strategies


def _get_workspace():
    """Get the active workspace manager if available."""
    try:
        from superqode.workspace.manager import get_workspace

        workspace = get_workspace()
        if workspace and workspace.is_active:
            return workspace
    except ImportError:
        pass
    return None


class EditFileTool(Tool):
    """Edit a file by replacing text.

    Performs string replacements with fallback strategies when exact match fails
    (e.g., line-trimmed, indentation-flexible). Read the file before editing.
    """

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return """Performs string replacements in files.

Usage:
- Use read_file at least once before editing. The tool will error if the file was modified externally since last read.
- When editing text from read_file output, preserve exact indentation. If the output uses a line-number prefix (e.g. spaces + line number + tab), everything after the tab is the actual file content to match. Never include the line-number prefix in old_text or new_text.
- Prefer editing existing files. Only create new files when explicitly required.
- The edit will FAIL if old_text is not found (error: 'old_string not found in content').
- The edit will FAIL if old_text matches multiple times. Provide more surrounding lines to make it unique, or use replace_all=true to change every instance.
- Use replace_all for renaming variables or replacing across the whole file."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to edit"},
                "old_text": {
                    "type": "string",
                    "description": "The text to find and replace. Must match exactly (including whitespace) or a fallback strategy may match. Include 3-5 lines of context for unique matching.",
                },
                "new_text": {
                    "type": "string",
                    "description": "The text to replace it with (must be different from old_text)",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false). Use for renaming or changing every instance.",
                },
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path", "")
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")
        replace_all = args.get("replace_all", False)

        try:
            # Validate and resolve path - ensures it stays within working directory
            file_path = validate_path_in_working_directory(path, ctx.working_directory)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            if not file_path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            content = file_path.read_text()

            # Check file unchanged since last read (avoid external-edit conflicts)
            mtime = file_path.stat().st_mtime
            ok, err = check_file_unchanged(
                getattr(ctx, "session_id", "") or "", str(file_path.resolve()), mtime
            )
            if not ok and err:
                return ToolResult(success=False, output="", error=err)

            # Use advanced edit strategies (exact match first, then fallbacks)
            try:
                new_content, replaced_count = replace_with_strategies(
                    content, old_text, new_text, replace_all
                )
            except ValueError as e:
                return ToolResult(success=False, output="", error=str(e))

            # Check if QE session is active - route through workspace
            workspace = _get_workspace()
            if workspace:
                try:
                    rel_path = file_path.relative_to(workspace.project_root)
                    workspace.write_file(str(rel_path), new_content)
                    return ToolResult(
                        success=True,
                        output=f"Replaced {replaced_count} occurrence(s) in {path} (tracked for QE revert)",
                        metadata={
                            "path": str(file_path),
                            "replacements": replaced_count,
                            "qe_tracked": True,
                        },
                    )
                except ValueError:
                    # Path is outside project root, write directly
                    pass

            # Write back (no QE session or outside project)
            file_path.write_text(new_content)

            return ToolResult(
                success=True,
                output=f"Replaced {replaced_count} occurrence(s) in {path}",
                metadata={"path": str(file_path), "replacements": replaced_count},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class InsertTextTool(Tool):
    """Insert text at a specific line number."""

    @property
    def name(self) -> str:
        return "insert_text"

    @property
    def description(self) -> str:
        return "Insert text at a specific line number in a file."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "line": {"type": "integer", "description": "Line number to insert at (1-indexed)"},
                "text": {"type": "string", "description": "Text to insert"},
            },
            "required": ["path", "line", "text"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path", "")
        line_num = args.get("line", 1)
        text = args.get("text", "")

        try:
            # Validate and resolve path - ensures it stays within working directory
            file_path = validate_path_in_working_directory(path, ctx.working_directory)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            if not file_path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            lines = file_path.read_text().split("\n")

            # Check file unchanged since last read
            mtime = file_path.stat().st_mtime
            ok, err = check_file_unchanged(
                getattr(ctx, "session_id", "") or "", str(file_path.resolve()), mtime
            )
            if not ok and err:
                return ToolResult(success=False, output="", error=err)

            # Validate line number
            if line_num < 1 or line_num > len(lines) + 1:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Invalid line number {line_num}. File has {len(lines)} lines.",
                )

            # Insert at position (convert to 0-indexed)
            lines.insert(line_num - 1, text)
            new_content = "\n".join(lines)

            # Check if QE session is active - route through workspace
            workspace = _get_workspace()
            if workspace:
                try:
                    rel_path = file_path.relative_to(workspace.project_root)
                    workspace.write_file(str(rel_path), new_content)
                    return ToolResult(
                        success=True,
                        output=f"Inserted text at line {line_num} in {path} (tracked for QE revert)",
                        metadata={"path": str(file_path), "line": line_num, "qe_tracked": True},
                    )
                except ValueError:
                    pass

            # Write back (no QE session or outside project)
            file_path.write_text(new_content)

            return ToolResult(
                success=True,
                output=f"Inserted text at line {line_num} in {path}",
                metadata={"path": str(file_path), "line": line_num},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class PatchTool(Tool):
    """
    Apply unified diff patches to files.

    Supports standard unified diff format (like git diff output).
    Can apply patches to single or multiple files.

    Features:
    - Parse unified diff format
    - Context line matching with configurable fuzz factor
    - Support for multiple files in one patch
    - Detailed success/failure reporting per hunk
    """

    @property
    def name(self) -> str:
        return "patch"

    @property
    def description(self) -> str:
        return "Apply a unified diff patch to files. Accepts standard diff format (like git diff output)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "The unified diff patch content to apply",
                },
                "path": {
                    "type": "string",
                    "description": "Optional: specific file to patch (overrides file paths in patch)",
                },
                "fuzz": {
                    "type": "integer",
                    "description": "Fuzz factor for context matching (0-3, default: 0 for exact match)",
                },
                "reverse": {
                    "type": "boolean",
                    "description": "Apply patch in reverse (default: false)",
                },
            },
            "required": ["patch"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        patch_content = args.get("patch", "")
        target_path = args.get("path")
        fuzz = args.get("fuzz", 0)
        reverse = args.get("reverse", False)

        if not patch_content.strip():
            return ToolResult(success=False, output="", error="Empty patch content")

        try:
            # Parse the patch into file hunks
            file_patches = self._parse_unified_diff(patch_content)

            if not file_patches:
                return ToolResult(
                    success=False,
                    output="",
                    error="Could not parse patch. Expected unified diff format.",
                )

            results = []
            total_hunks = 0
            applied_hunks = 0

            workspace = _get_workspace()

            for file_path_str, hunks in file_patches.items():
                # Override path if specified
                if target_path:
                    file_path_str = target_path

                # Validate and resolve path - ensures it stays within working directory
                try:
                    file_path = validate_path_in_working_directory(
                        file_path_str, ctx.working_directory
                    )
                except ValueError as e:
                    results.append(f"✗ {file_path_str}: {str(e)}")
                    continue

                # Read current content
                if file_path.exists():
                    content = file_path.read_text()
                    lines = content.split("\n")
                    # Check file unchanged since last read
                    mtime = file_path.stat().st_mtime
                    ok, err = check_file_unchanged(
                        getattr(ctx, "session_id", "") or "", str(file_path.resolve()), mtime
                    )
                    if not ok and err:
                        results.append(f"✗ {file_path_str}: {err}")
                        total_hunks += len(hunks)
                        continue
                else:
                    # New file (no prior read to check)
                    lines = []

                # Apply hunks
                hunk_results = []
                for hunk in hunks:
                    total_hunks += 1
                    success, new_lines, msg = self._apply_hunk(
                        lines, hunk, fuzz=fuzz, reverse=reverse
                    )
                    if success:
                        lines = new_lines
                        applied_hunks += 1
                        hunk_results.append(
                            f"  ✓ Hunk @@ {hunk['old_start']},{hunk['old_count']} @@"
                        )
                    else:
                        hunk_results.append(
                            f"  ✗ Hunk @@ {hunk['old_start']},{hunk['old_count']} @@: {msg}"
                        )

                # Write result
                new_content = "\n".join(lines)

                if workspace:
                    try:
                        rel_path = file_path.relative_to(workspace.project_root)
                        workspace.write_file(str(rel_path), new_content)
                    except ValueError:
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(new_content)
                else:
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(new_content)

                results.append(f"{file_path_str}:")
                results.extend(hunk_results)

            success = applied_hunks == total_hunks
            output = "\n".join(results)
            output += f"\n\nApplied {applied_hunks}/{total_hunks} hunks"

            if workspace:
                output += " (tracked for QE revert)"

            return ToolResult(
                success=success,
                output=output,
                error=None if success else f"Failed to apply {total_hunks - applied_hunks} hunks",
                metadata={
                    "total_hunks": total_hunks,
                    "applied_hunks": applied_hunks,
                    "files": list(file_patches.keys()),
                },
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=f"Patch error: {str(e)}")

    def _parse_unified_diff(self, patch: str) -> Dict[str, List[Dict]]:
        """Parse unified diff into file -> hunks mapping."""
        files: Dict[str, List[Dict]] = {}
        current_file = None
        current_hunk = None

        lines = patch.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # File header: --- a/path or --- path
            if line.startswith("--- "):
                # Next line should be +++
                if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                    # Extract path (remove a/ or b/ prefix if present)
                    old_path = line[4:].split("\t")[0].strip()
                    new_path = lines[i + 1][4:].split("\t")[0].strip()

                    # Remove a/ b/ prefixes
                    if old_path.startswith("a/"):
                        old_path = old_path[2:]
                    if new_path.startswith("b/"):
                        new_path = new_path[2:]

                    # Use new path (or old if it's /dev/null for new files)
                    current_file = new_path if new_path != "/dev/null" else old_path
                    if current_file not in files:
                        files[current_file] = []

                    i += 2
                    continue

            # Hunk header: @@ -start,count +start,count @@
            hunk_match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if hunk_match and current_file:
                if current_hunk:
                    files[current_file].append(current_hunk)

                current_hunk = {
                    "old_start": int(hunk_match.group(1)),
                    "old_count": int(hunk_match.group(2) or 1),
                    "new_start": int(hunk_match.group(3)),
                    "new_count": int(hunk_match.group(4) or 1),
                    "lines": [],
                }
                i += 1
                continue

            # Hunk content
            if current_hunk is not None:
                if (
                    line.startswith("+")
                    or line.startswith("-")
                    or line.startswith(" ")
                    or line == ""
                ):
                    current_hunk["lines"].append(line)

            i += 1

        # Add last hunk
        if current_hunk and current_file:
            files[current_file].append(current_hunk)

        return files

    def _apply_hunk(
        self, lines: List[str], hunk: Dict, fuzz: int = 0, reverse: bool = False
    ) -> Tuple[bool, List[str], str]:
        """Apply a single hunk to lines."""
        old_lines = []
        new_lines = []

        for line in hunk["lines"]:
            if line.startswith("-"):
                old_lines.append(line[1:])
            elif line.startswith("+"):
                new_lines.append(line[1:])
            elif line.startswith(" "):
                old_lines.append(line[1:])
                new_lines.append(line[1:])
            elif line == "":
                # Empty context line
                old_lines.append("")
                new_lines.append("")

        if reverse:
            old_lines, new_lines = new_lines, old_lines

        # Find the location to apply (1-indexed in diff, 0-indexed in list)
        start_line = hunk["old_start"] - 1

        # Try exact match first, then with fuzz
        for fuzz_offset in range(fuzz + 1):
            for offset in [0, -fuzz_offset, fuzz_offset]:
                pos = start_line + offset
                if pos < 0:
                    continue

                # Check if old_lines match at this position
                if self._lines_match(lines, pos, old_lines, fuzz_offset):
                    # Apply the change
                    result = lines[:pos] + new_lines + lines[pos + len(old_lines) :]
                    return True, result, "Applied"

        return False, lines, "Context mismatch"

    def _lines_match(
        self, content: List[str], start: int, expected: List[str], fuzz: int = 0
    ) -> bool:
        """Check if lines match at position (with optional fuzz)."""
        if start + len(expected) > len(content):
            return False

        for i, exp_line in enumerate(expected):
            actual_line = content[start + i]

            if fuzz == 0:
                if actual_line != exp_line:
                    return False
            else:
                # With fuzz, allow whitespace differences
                if actual_line.strip() != exp_line.strip():
                    return False

        return True


class MultiEditTool(Tool):
    """
    Apply multiple edits to a file atomically.

    More efficient than multiple edit_file calls when making
    several changes to the same file. All edits are validated
    before any are applied.
    """

    @property
    def name(self) -> str:
        return "multi_edit"

    @property
    def description(self) -> str:
        return "Apply multiple text replacements to a file atomically. All edits must succeed or none are applied."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to edit"},
                "edits": {
                    "type": "array",
                    "description": "Array of edit operations to apply",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_text": {"type": "string", "description": "Text to find"},
                            "new_text": {"type": "string", "description": "Text to replace with"},
                        },
                        "required": ["old_text", "new_text"],
                    },
                },
            },
            "required": ["path", "edits"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path", "")
        edits = args.get("edits", [])

        if not edits:
            return ToolResult(success=False, output="", error="No edits provided")

        try:
            # Validate and resolve path - ensures it stays within working directory
            file_path = validate_path_in_working_directory(path, ctx.working_directory)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            if not file_path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            content = file_path.read_text()

            # Check file unchanged since last read
            mtime = file_path.stat().st_mtime
            ok, err = check_file_unchanged(
                getattr(ctx, "session_id", "") or "", str(file_path.resolve()), mtime
            )
            if not ok and err:
                return ToolResult(success=False, output="", error=err)

            # Validate all edits first
            validation_errors = []
            for i, edit in enumerate(edits):
                old_text = edit.get("old_text", "")
                if old_text not in content:
                    validation_errors.append(f"Edit {i + 1}: Text not found: {old_text[:50]}...")
                elif content.count(old_text) > 1:
                    validation_errors.append(
                        f"Edit {i + 1}: Multiple occurrences found for: {old_text[:50]}..."
                    )

            if validation_errors:
                return ToolResult(
                    success=False,
                    output="",
                    error="Validation failed:\n" + "\n".join(validation_errors),
                )

            # Apply all edits (we need to be careful about order to avoid overlaps)
            # Sort edits by position in file (descending) to avoid offset issues
            positioned_edits = []
            for edit in edits:
                old_text = edit.get("old_text", "")
                pos = content.find(old_text)
                positioned_edits.append((pos, edit))

            # Sort by position descending (apply from end to start)
            positioned_edits.sort(key=lambda x: x[0], reverse=True)

            # Apply edits
            for pos, edit in positioned_edits:
                old_text = edit.get("old_text", "")
                new_text = edit.get("new_text", "")
                content = content[:pos] + new_text + content[pos + len(old_text) :]

            # Write result
            workspace = _get_workspace()
            if workspace:
                try:
                    rel_path = file_path.relative_to(workspace.project_root)
                    workspace.write_file(str(rel_path), content)
                    return ToolResult(
                        success=True,
                        output=f"Applied {len(edits)} edits to {path} (tracked for QE revert)",
                        metadata={
                            "path": str(file_path),
                            "edit_count": len(edits),
                            "qe_tracked": True,
                        },
                    )
                except ValueError:
                    pass

            file_path.write_text(content)

            return ToolResult(
                success=True,
                output=f"Applied {len(edits)} edits to {path}",
                metadata={"path": str(file_path), "edit_count": len(edits)},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
