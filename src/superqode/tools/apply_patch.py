"""Patch-envelope ``apply_patch`` tool.

Several model families (GPT-5.x hosted, gpt-oss locally) are trained to emit
file edits in the ``*** Begin Patch`` envelope grammar rather than unified
diffs. Supporting it natively means those models — increasingly common as
*local* models via Ollama/MLX — can edit files in their preferred format
instead of being forced through string-replacement calls they were not
tuned for.

Grammar (one or more file sections inside the envelope):

    *** Begin Patch
    *** Add File: <path>
    +<line>
    *** Delete File: <path>
    *** Update File: <path>
    *** Move to: <new path>          (optional, directly after Update File)
    @@ <optional locator, e.g. a def/class line>
     <context line>
    -<removed line>
    +<added line>
    *** End of File                  (optional: hunk anchored at EOF)
    *** End Patch

Context matching is deliberately forgiving: exact first, then
trailing-whitespace-insensitive, then fully trimmed. The actual file lines
are preserved for context rows, so a fuzzy match never rewrites untouched
lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import Tool, ToolContext, ToolResult
from .diff_utils import build_unified_diff, diff_stats
from .file_tracking import check_file_unchanged, record_file_read
from .post_edit import verify_edit
from .validation import validate_path_in_working_directory

BEGIN_MARKER = "*** Begin Patch"
END_MARKER = "*** End Patch"
ADD_PREFIX = "*** Add File: "
DELETE_PREFIX = "*** Delete File: "
UPDATE_PREFIX = "*** Update File: "
MOVE_PREFIX = "*** Move to: "
EOF_MARKER = "*** End of File"

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n```\s*$", re.DOTALL)

_HEREDOC_RE = re.compile(
    r"^\s*apply_patch\s+<<-?\s*(?P<q>['\"]?)(?P<tag>\w+)(?P=q)\s*\n(?P<body>.*?)\n\s*(?P=tag)\s*$",
    re.DOTALL,
)


@dataclass
class Hunk:
    """One change block inside an Update File section."""

    locators: List[str] = field(default_factory=list)
    # (prefix, text) with prefix in {' ', '-', '+'}
    lines: List[Tuple[str, str]] = field(default_factory=list)
    anchored_at_eof: bool = False


@dataclass
class FileOp:
    kind: str  # "add" | "delete" | "update"
    path: str
    move_to: Optional[str] = None
    content_lines: List[str] = field(default_factory=list)  # for add
    hunks: List[Hunk] = field(default_factory=list)  # for update


def extract_heredoc_patch(command: str) -> Optional[str]:
    """Extract a patch body from a shell ``apply_patch <<EOF`` invocation.

    Models trained on this dialect often wrap the patch in a bash heredoc instead of
    calling the tool directly. Returns the patch text when the command is
    such an invocation, else None.
    """
    match = _HEREDOC_RE.match(command.strip())
    if not match:
        return None
    body = match.group("body")
    return body if BEGIN_MARKER in body else None


def _strip_envelope_noise(text: str) -> str:
    """Remove markdown fences and surrounding prose around the envelope."""
    text = text.strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    begin = text.find(BEGIN_MARKER)
    if begin > 0:
        text = text[begin:]
    end = text.rfind(END_MARKER)
    if end != -1:
        text = text[: end + len(END_MARKER)]
    return text


def parse_patch(text: str) -> List[FileOp]:
    """Parse a Begin/End Patch envelope. Raises ValueError on malformed input."""
    text = _strip_envelope_noise(text)
    lines = text.split("\n")
    if not lines or lines[0].strip() != BEGIN_MARKER:
        raise ValueError(f"Patch must start with '{BEGIN_MARKER}'")
    if lines[-1].strip() != END_MARKER:
        raise ValueError(f"Patch must end with '{END_MARKER}'")

    ops: List[FileOp] = []
    current: Optional[FileOp] = None
    hunk: Optional[Hunk] = None
    pending_locators: List[str] = []

    def close_hunk() -> None:
        nonlocal hunk
        if hunk is not None and (hunk.lines or hunk.locators):
            current.hunks.append(hunk)
        hunk = None

    def close_op() -> None:
        nonlocal current, pending_locators
        close_hunk()
        if current is not None:
            if current.kind == "update" and not current.hunks:
                raise ValueError(f"Update File '{current.path}' has no change hunks")
            ops.append(current)
        current = None
        pending_locators = []

    for raw in lines[1:-1]:
        if raw.startswith(ADD_PREFIX):
            close_op()
            current = FileOp(kind="add", path=raw[len(ADD_PREFIX) :].strip())
            continue
        if raw.startswith(DELETE_PREFIX):
            close_op()
            current = FileOp(kind="delete", path=raw[len(DELETE_PREFIX) :].strip())
            continue
        if raw.startswith(UPDATE_PREFIX):
            close_op()
            current = FileOp(kind="update", path=raw[len(UPDATE_PREFIX) :].strip())
            continue
        if raw.startswith(MOVE_PREFIX):
            if current is None or current.kind != "update":
                raise ValueError("'*** Move to:' must follow '*** Update File:'")
            current.move_to = raw[len(MOVE_PREFIX) :].strip()
            continue
        if raw.strip() == EOF_MARKER:
            if current is None or current.kind != "update" or hunk is None:
                raise ValueError(f"'{EOF_MARKER}' outside of an update hunk")
            hunk.anchored_at_eof = True
            close_hunk()
            continue
        if raw.startswith("***"):
            raise ValueError(f"Unknown patch directive: {raw!r}")

        if current is None:
            if not raw.strip():
                continue
            raise ValueError(f"Patch content before any file section: {raw!r}")

        if current.kind == "add":
            if raw.startswith("+"):
                current.content_lines.append(raw[1:])
            elif not raw.strip():
                current.content_lines.append("")
            else:
                raise ValueError(f"Add File lines must start with '+': {raw!r}")
            continue

        if current.kind == "delete":
            if raw.strip():
                raise ValueError(f"Delete File section must have no body: {raw!r}")
            continue

        # update section
        if raw.startswith("@@"):
            close_hunk()
            locator = raw[2:].strip()
            hunk = Hunk()
            if locator:
                hunk.locators.append(locator)
            hunk.locators = pending_locators + hunk.locators
            pending_locators = []
            continue
        if hunk is None:
            hunk = Hunk(locators=pending_locators)
            pending_locators = []
        if raw.startswith(("+", "-", " ")):
            hunk.lines.append((raw[0], raw[1:]))
        elif not raw:
            # Lenient: a bare empty line inside a hunk is an empty context line.
            hunk.lines.append((" ", ""))
        else:
            raise ValueError(
                f"Hunk lines must start with ' ', '+' or '-' (got {raw!r}). "
                "Make sure context lines keep their leading space."
            )

    close_op()
    if not ops:
        raise ValueError("Patch contains no file sections")
    return ops


def _lines_equal(a: str, b: str, mode: int) -> bool:
    if mode == 0:
        return a == b
    if mode == 1:
        return a.rstrip() == b.rstrip()
    return a.strip() == b.strip()


def _seek_sequence(lines: List[str], pattern: List[str], start: int, eof: bool) -> int:
    """Find ``pattern`` in ``lines`` at/after ``start``. Returns index or -1."""
    if not pattern:
        return len(lines) if eof else start
    if eof:
        anchor = len(lines) - len(pattern)
        if anchor >= 0:
            for mode in (0, 1, 2):
                if all(
                    _lines_equal(lines[anchor + i], pattern[i], mode) for i in range(len(pattern))
                ):
                    return anchor
        return -1
    for mode in (0, 1, 2):
        for idx in range(start, len(lines) - len(pattern) + 1):
            if all(_lines_equal(lines[idx + i], pattern[i], mode) for i in range(len(pattern))):
                return idx
    return -1


def _seek_locator(lines: List[str], locator: str, start: int) -> int:
    """Find a ``@@`` locator line (e.g. a def/class header) at/after start."""
    for mode in (0, 1, 2):
        for idx in range(start, len(lines)):
            if _lines_equal(lines[idx], locator, mode):
                return idx
    return -1


def apply_hunks(content: str, hunks: List[Hunk], path: str) -> str:
    """Apply update hunks to ``content``, preserving matched context lines."""
    lines = content.split("\n")
    cursor = 0
    for hunk in hunks:
        for locator in hunk.locators:
            loc = _seek_locator(lines, locator, cursor)
            if loc < 0:
                raise ValueError(f"Could not find '@@ {locator}' in {path}")
            cursor = loc + 1
        pattern = [text for prefix, text in hunk.lines if prefix in (" ", "-")]
        idx = _seek_sequence(lines, pattern, cursor, hunk.anchored_at_eof)
        if idx < 0:
            preview = "\n".join(pattern[:3])
            raise ValueError(
                f"Could not locate hunk context in {path}:\n{preview}\n"
                "(the file may have changed - re-read it and regenerate the patch)"
            )
        replacement: List[str] = []
        file_off = idx
        for prefix, text in hunk.lines:
            if prefix == " ":
                # Keep the file's actual line so fuzzy matches never rewrite context.
                replacement.append(lines[file_off] if file_off < len(lines) else text)
                file_off += 1
            elif prefix == "-":
                file_off += 1
            else:
                replacement.append(text)
        lines[idx:file_off] = replacement
        cursor = idx + len(replacement)
    return "\n".join(lines)


def _get_workspace():
    try:
        from superqode.workspace.manager import get_workspace

        workspace = get_workspace()
        if workspace and workspace.is_active:
            return workspace
    except ImportError:
        pass
    return None


class ApplyPatchTool(Tool):
    """Apply a patch envelope (add/delete/update/move files)."""

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return (
            "Edit files using a patch envelope. Format:\n"
            "*** Begin Patch\n"
            "*** Update File: path/to/file.py\n"
            "@@ def some_function():\n"
            " context line (unchanged, starts with one space)\n"
            "-removed line\n"
            "+added line\n"
            "*** End Patch\n"
            "Also supports '*** Add File: <path>' (every line prefixed '+'), "
            "'*** Delete File: <path>', and '*** Move to: <path>' after Update File. "
            "Context lines must match the file; re-read the file if the patch is rejected."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "The full patch, from '*** Begin Patch' to '*** End Patch'.",
                },
            },
            "required": ["input"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        raw = args.get("input") or args.get("patch") or args.get("content") or ""
        if not str(raw).strip():
            return ToolResult(success=False, output="", error="Empty patch")

        try:
            ops = parse_patch(str(raw))
        except ValueError as e:
            return ToolResult(success=False, output="", error=f"Invalid patch: {e}")

        session_id = getattr(ctx, "session_id", "") or ""

        # Phase 1: validate everything and compute new contents before any
        # write, so a failed hunk in file 3 doesn't leave files 1-2 half-applied.
        planned: List[Tuple[FileOp, Path, Optional[Path], Optional[str], Optional[str]]] = []
        for op in ops:
            try:
                file_path = validate_path_in_working_directory(op.path, ctx.working_directory)
                move_path = (
                    validate_path_in_working_directory(op.move_to, ctx.working_directory)
                    if op.move_to
                    else None
                )
            except ValueError as e:
                return ToolResult(success=False, output="", error=str(e))

            if op.kind == "add":
                if file_path.exists():
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Cannot add {op.path}: file already exists (use Update File)",
                    )
                new_content = "\n".join(op.content_lines)
                if new_content and not new_content.endswith("\n"):
                    new_content += "\n"
                planned.append((op, file_path, None, None, new_content))
                continue

            if not file_path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {op.path}")
            if op.kind == "delete":
                planned.append((op, file_path, None, None, None))
                continue

            # update
            old_content = file_path.read_text()
            ok, err = check_file_unchanged(
                session_id, str(file_path.resolve()), file_path.stat().st_mtime
            )
            if not ok and err:
                return ToolResult(success=False, output="", error=err)
            try:
                new_content = apply_hunks(old_content, op.hunks, op.path)
            except ValueError as e:
                return ToolResult(success=False, output="", error=str(e))
            planned.append((op, file_path, move_path, old_content, new_content))

        # Phase 2: apply.
        workspace = _get_workspace()
        summary: List[str] = []
        diffs: List[str] = []
        total_add = total_del = 0
        result = ToolResult(success=True, output="")
        for op, file_path, move_path, old_content, new_content in planned:
            if op.kind == "delete":
                file_path.unlink()
                summary.append(f"D {op.path}")
                continue

            diff_text = build_unified_diff(old_content or "", new_content or "", path=op.path)
            additions, deletions = diff_stats(diff_text)
            total_add += additions
            total_del += deletions
            diffs.append(diff_text)

            target = move_path or file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            wrote_via_workspace = False
            if workspace:
                try:
                    rel = target.relative_to(workspace.project_root)
                    workspace.write_file(str(rel), new_content or "")
                    wrote_via_workspace = True
                except ValueError:
                    pass
            if not wrote_via_workspace:
                target.write_text(new_content or "")
            if move_path is not None and move_path != file_path:
                file_path.unlink()
                summary.append(f"M {op.path} -> {op.move_to}")
            else:
                summary.append(("A " if op.kind == "add" else "M ") + op.path)
            try:
                record_file_read(session_id, str(target.resolve()), target.stat().st_mtime)
            except OSError:
                pass
            result = await verify_edit(result, target, ctx)

        output = "Done. Applied patch to {} file(s):\n{}".format(len(planned), "\n".join(summary))
        if total_add or total_del:
            output += f"\n(+{total_add}/-{total_del} lines)"
        if result.output:
            output += f"\n{result.output}"
        return ToolResult(
            success=result.success if result.error is None else False,
            output=output,
            error=result.error,
            metadata={
                "files": summary,
                "additions": total_add,
                "deletions": total_del,
                "diff_text": "\n".join(diffs),
                **(result.metadata or {}),
            },
        )


__all__ = [
    "ApplyPatchTool",
    "FileOp",
    "Hunk",
    "apply_hunks",
    "extract_heredoc_patch",
    "parse_patch",
]
