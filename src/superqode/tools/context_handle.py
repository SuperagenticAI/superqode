"""Tool wrapper for local recursive context handles."""

from __future__ import annotations

from typing import Any

from ..harness.context_handles import (
    chunk_context_handle,
    grep_context_handle,
    peek_context_handle,
    resolve_context_handle,
)
from .base import Tool, ToolContext, ToolResult


class ContextHandleTool(Tool):
    """Inspect local context handles without loading all content into context."""

    read_only = True

    @property
    def name(self) -> str:
        return "context_handle"

    @property
    def description(self) -> str:
        return (
            "Inspect large local artifacts by handle without stuffing them into the prompt. "
            "Supports file:path, repo:glob, diff:working-tree, and run:<run_id>. "
            "Actions: peek, grep, chunk, info."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["peek", "grep", "chunk", "info"],
                    "description": "Operation to perform on the handle.",
                },
                "handle": {
                    "type": "string",
                    "description": "Context handle, e.g. file:ci.log, repo:src/**/*.py, diff:working-tree, run:<id>.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern for grep action.",
                },
                "offset": {"type": "integer", "description": "Character offset for peek."},
                "limit": {"type": "integer", "description": "Max chars or grep matches."},
                "chunk_chars": {
                    "type": "integer",
                    "description": "Approximate characters per chunk for chunk action.",
                },
                "max_chunks": {
                    "type": "integer",
                    "description": "Maximum chunks to return for chunk action.",
                },
            },
            "required": ["action", "handle"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        action = str(args.get("action") or "").strip().lower()
        handle = str(args.get("handle") or "").strip()
        if not action:
            return ToolResult(success=False, output="", error="action is required")
        if not handle:
            return ToolResult(success=False, output="", error="handle is required")

        try:
            if action == "info":
                text = resolve_context_handle(handle, ctx.working_directory)
                return ToolResult(
                    success=True,
                    output=f"Handle: {handle}\nCharacters: {len(text)}",
                    metadata={"handle": handle, "chars": len(text)},
                )
            if action == "peek":
                text = peek_context_handle(
                    handle,
                    ctx.working_directory,
                    offset=int(args.get("offset", 0) or 0),
                    limit=int(args.get("limit", 4000) or 4000),
                )
                return ToolResult(success=True, output=text, metadata={"handle": handle})
            if action == "grep":
                matches = grep_context_handle(
                    handle,
                    str(args.get("pattern") or ""),
                    ctx.working_directory,
                    limit=int(args.get("limit", 50) or 50),
                )
                output = "\n".join(
                    f"{item['line']}:{item['text']}" for item in matches
                ) or "No matches"
                return ToolResult(
                    success=True,
                    output=output,
                    metadata={"handle": handle, "matches": len(matches)},
                )
            if action == "chunk":
                chunks = chunk_context_handle(
                    handle,
                    ctx.working_directory,
                    chunk_chars=int(args.get("chunk_chars", 12000) or 12000),
                    max_chunks=int(args.get("max_chunks", 20) or 20),
                )
                output = "\n".join(
                    f"{chunk.chunk_id} offset={chunk.offset} chars={len(chunk.text)} preview={chunk.text[:120]!r}"
                    for chunk in chunks
                )
                return ToolResult(
                    success=True,
                    output=output or "No chunks",
                    metadata={"handle": handle, "chunks": [chunk.to_dict() for chunk in chunks]},
                )
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))


__all__ = ["ContextHandleTool"]
