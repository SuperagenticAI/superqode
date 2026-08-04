"""The read, write and edit tools.

Ported from ``packages/coding-agent/src/core/tools/`` of earendil-works/pi
(MIT). These execute directly against the filesystem with the permissions of
the process, exactly as pi does. There is no approval manager and no sandbox in
this path by design; see ``superqode/pipy/permissions.py``.
"""

from __future__ import annotations

import base64
from pathlib import Path

from ..messages import ImageContent, TextContent
from ..signals import AbortSignal, is_aborted
from ..types import JSONObject
from .base import AgentTool, AgentToolResult, ToolUpdateCallback
from .edit_diff import (
    EditError,
    detect_line_ending,
    first_changed_line,
    generate_diff_string,
    generate_unified_patch,
    normalize_to_lf,
    restore_line_endings,
    strip_bom,
)
from .paths import display_path, json_schema, resolve_to_cwd, with_file_mutation_queue
from .truncate import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES, format_size, truncate_head

_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def detect_image_mime_type(data: bytes) -> str | None:
    """Sniff a supported image type from its magic bytes."""
    for signature, mime_type in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return mime_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _abort_if_needed(signal: AbortSignal | None) -> None:
    if is_aborted(signal):
        raise RuntimeError("Operation aborted")


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #

READ_DESCRIPTION = (
    "Read the contents of a file. Supports text files and images (jpg, png, gif, "
    f"webp, bmp). Images are sent as attachments. For text files, output is truncated "
    f"to {DEFAULT_MAX_LINES} lines or {DEFAULT_MAX_BYTES // 1024}KB (whichever is hit "
    "first). Use offset/limit for large files. When you need the full file, continue "
    "with offset until complete."
)


def create_read_tool(cwd: str | Path) -> AgentTool:
    async def execute(
        tool_call_id: str,
        args: JSONObject,
        signal: AbortSignal | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        _abort_if_needed(signal)
        path_arg = str(args["path"])
        offset = args.get("offset")
        limit = args.get("limit")
        absolute = resolve_to_cwd(path_arg, cwd)

        data = absolute.read_bytes()
        mime_type = detect_image_mime_type(data)
        if mime_type:
            return AgentToolResult(
                content=[
                    TextContent(text=f"Read image file [{mime_type}]"),
                    ImageContent(data=base64.b64encode(data).decode("ascii"), mime_type=mime_type),
                ],
                details=None,
            )

        text = data.decode("utf-8", errors="replace")
        all_lines = text.split("\n")
        total_lines = len(all_lines)

        start = max(0, int(offset) - 1) if offset else 0
        start_display = start + 1
        if start >= total_lines:
            raise ValueError(f"Offset {offset} is beyond end of file ({total_lines} lines total)")

        user_limited: int | None = None
        if limit is not None:
            end = min(start + int(limit), total_lines)
            selected = "\n".join(all_lines[start:end])
            user_limited = end - start
        else:
            selected = "\n".join(all_lines[start:])

        truncation = truncate_head(selected)
        details: JSONObject | None = None

        if truncation.first_line_exceeds_limit:
            size = format_size(len(all_lines[start].encode("utf-8")))
            output = (
                f"[Line {start_display} is {size}, exceeds {format_size(DEFAULT_MAX_BYTES)} "
                f"limit. Use bash: sed -n '{start_display}p' {path_arg} | "
                f"head -c {DEFAULT_MAX_BYTES}]"
            )
            details = {"truncated": True, "reason": "first_line_exceeds_limit"}
        elif truncation.truncated:
            end_display = start_display + truncation.output_lines - 1
            next_offset = end_display + 1
            output = truncation.content
            if truncation.truncated_by == "lines":
                output += (
                    f"\n\n[Showing lines {start_display}-{end_display} of {total_lines}. "
                    f"Use offset={next_offset} to continue.]"
                )
            else:
                output += (
                    f"\n\n[Showing lines {start_display}-{end_display} of {total_lines} "
                    f"({format_size(DEFAULT_MAX_BYTES)} limit). "
                    f"Use offset={next_offset} to continue.]"
                )
            details = {"truncated": True, "truncated_by": truncation.truncated_by}
        elif user_limited is not None and start + user_limited < total_lines:
            remaining = total_lines - (start + user_limited)
            next_offset = start + user_limited + 1
            output = (
                f"{truncation.content}\n\n[{remaining} more lines in file. "
                f"Use offset={next_offset} to continue.]"
            )
        else:
            output = truncation.content

        return AgentToolResult(content=[TextContent(text=output)], details=details)

    return AgentTool(
        name="read",
        label="read",
        description=READ_DESCRIPTION,
        parameters=json_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative or absolute)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-indexed)",
                },
                "limit": {"type": "integer", "description": "Maximum number of lines to read"},
            },
            ["path"],
        ),
        execute_fn=execute,
        prompt_snippet="Read file contents",
        prompt_guidelines=("Use read to examine files instead of cat or sed.",),
    )


# --------------------------------------------------------------------------- #
# write
# --------------------------------------------------------------------------- #


def create_write_tool(cwd: str | Path) -> AgentTool:
    async def execute(
        tool_call_id: str,
        args: JSONObject,
        signal: AbortSignal | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        _abort_if_needed(signal)
        path_arg = str(args["path"])
        content = str(args["content"])
        absolute = resolve_to_cwd(path_arg, cwd)

        async def run() -> AgentToolResult:
            _abort_if_needed(signal)
            absolute.parent.mkdir(parents=True, exist_ok=True)
            absolute.write_text(content, encoding="utf-8")
            return AgentToolResult(
                content=[
                    TextContent(text=f"Successfully wrote {len(content)} bytes to {path_arg}")
                ],
                details={"path": str(absolute), "bytes": len(content)},
            )

        return await with_file_mutation_queue(absolute, run)

    return AgentTool(
        name="write",
        label="write",
        description=(
            "Write content to a file. Creates the file if it does not exist, "
            "overwrites it if it does. Parent directories are created as needed."
        ),
        parameters=json_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write (relative or absolute)",
                },
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            ["path", "content"],
        ),
        execute_fn=execute,
        prompt_snippet="Create or overwrite files",
        prompt_guidelines=("Use write only for new files or complete rewrites.",),
    )


# --------------------------------------------------------------------------- #
# edit
# --------------------------------------------------------------------------- #

EDIT_DESCRIPTION = (
    "Edit a single file using exact text replacement. Every edits[].oldText must "
    "match a unique, non-overlapping region of the original file. If two changes "
    "affect the same block or nearby lines, merge them into one edit instead of "
    "emitting overlapping edits. Do not include large unchanged regions just to "
    "connect distant changes."
)

EDIT_GUIDELINES = (
    "Use edit for precise changes (edits[].oldText must match exactly)",
    "When changing multiple separate locations in one file, use one edit call with "
    "multiple entries in edits[] instead of multiple edit calls",
    "Each edits[].oldText is matched against the original file, not after earlier "
    "edits are applied. Do not emit overlapping or nested edits. Merge nearby "
    "changes into one edit.",
    "Keep edits[].oldText as small as possible while still being unique in the file. "
    "Do not pad with large unchanged regions.",
)


def _prepare_edit_arguments(args: JSONObject) -> JSONObject:
    """Accept the older single-edit shape some models still emit."""
    if "edits" in args:
        return args
    if "oldText" in args and "newText" in args:
        prepared = {key: value for key, value in args.items() if key not in ("oldText", "newText")}
        prepared["edits"] = [{"oldText": args["oldText"], "newText": args["newText"]}]
        return prepared
    if "old_text" in args and "new_text" in args:
        prepared = {
            key: value for key, value in args.items() if key not in ("old_text", "new_text")
        }
        prepared["edits"] = [{"oldText": args["old_text"], "newText": args["new_text"]}]
        return prepared
    return args


def create_edit_tool(cwd: str | Path) -> AgentTool:
    async def execute(
        tool_call_id: str,
        args: JSONObject,
        signal: AbortSignal | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        _abort_if_needed(signal)
        path_arg = str(args["path"])
        edits = [dict(edit) for edit in args["edits"]]  # type: ignore[union-attr]
        absolute = resolve_to_cwd(path_arg, cwd)

        async def run() -> AgentToolResult:
            _abort_if_needed(signal)
            if not absolute.exists():
                raise EditError(f"Could not edit file: {path_arg}. Error code: ENOENT.")

            # Read and write bytes, not text. Python's universal newlines would
            # rewrite CRLF to LF on the way in, so the original ending could
            # never be detected and every edit would silently reformat the file.
            raw = absolute.read_bytes().decode("utf-8")
            bom, body = strip_bom(raw)
            ending = detect_line_ending(body)
            normalized = normalize_to_lf(body)

            # Edits are authored against LF text; the file's own ending is
            # restored on the way back out so an edit never rewrites every line
            # of a CRLF file.
            updated = apply_edits_normalized(path_arg, normalized, edits)

            _abort_if_needed(signal)
            absolute.write_bytes((bom + restore_line_endings(updated, ending)).encode("utf-8"))

            return AgentToolResult(
                content=[
                    TextContent(
                        text=(
                            f"Successfully applied {len(edits)} "
                            f"edit{'s' if len(edits) != 1 else ''} to {path_arg}"
                        )
                    )
                ],
                details={
                    "diff": generate_diff_string(normalized, updated),
                    "patch": generate_unified_patch(
                        display_path(absolute, cwd), normalized, updated
                    ),
                    "first_changed_line": first_changed_line(normalized, updated),
                },
            )

        return await with_file_mutation_queue(absolute, run)

    return AgentTool(
        name="edit",
        label="edit",
        description=EDIT_DESCRIPTION,
        parameters=json_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit (relative or absolute)",
                },
                "edits": {
                    "type": "array",
                    "description": (
                        "One or more targeted replacements. Each edit is matched against "
                        "the original file, not incrementally. Do not include overlapping "
                        "or nested edits. If two changes touch the same block or nearby "
                        "lines, merge them into one edit instead."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "oldText": {
                                "type": "string",
                                "description": (
                                    "Exact text for one targeted replacement. It must be "
                                    "unique in the original file and must not overlap with "
                                    "any other edits[].oldText in the same call."
                                ),
                            },
                            "newText": {
                                "type": "string",
                                "description": "Replacement text for this targeted edit.",
                            },
                        },
                        "required": ["oldText", "newText"],
                        "additionalProperties": False,
                    },
                },
            },
            ["path", "edits"],
        ),
        execute_fn=execute,
        prepare_arguments=_prepare_edit_arguments,
        prompt_snippet=(
            "Make precise file edits with exact text replacement, including multiple "
            "disjoint edits in one call"
        ),
        prompt_guidelines=EDIT_GUIDELINES,
        # Two edits to the same file must not interleave their read and write.
        execution_mode="sequential",
    )


def apply_edits_normalized(path: str, content: str, edits: list[dict]) -> str:
    from .edit_diff import apply_edits

    return apply_edits(path, content, [{k: str(v) for k, v in edit.items()} for edit in edits])


__all__ = [
    "EDIT_DESCRIPTION",
    "READ_DESCRIPTION",
    "create_edit_tool",
    "create_read_tool",
    "create_write_tool",
    "detect_image_mime_type",
]
