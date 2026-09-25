"""get_context_remaining: let the model see its own context budget.

The loop already manages context for the model (adaptive compaction, tool
output pruning), but the model itself flies blind: it cannot tell whether
it has room for one more big file read or should summarize and wrap up.
This tool reports the live numbers so the model can plan its remaining
work deliberately. Especially useful on local models, where the loaded
window is small and every read counts.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import Tool, ToolContext, ToolResult


class GetContextRemainingTool(Tool):
    """Report the context window, current usage, and remaining budget."""

    read_only = True

    @property
    def name(self) -> str:
        return "get_context_remaining"

    @property
    def description(self) -> str:
        return (
            "Check how much of the context window is used and how much "
            "remains before automatic compaction. Use this to decide whether "
            "to read more material or to consolidate and finish."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        status_fn = getattr(ctx, "context_status", None)
        if status_fn is None:
            return ToolResult(
                success=False,
                output="",
                error="Context status is not available in this run.",
            )
        try:
            status = status_fn() or {}
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Context status failed: {e}")

        window = int(status.get("window") or 0)
        used = status.get("used")
        threshold = int(status.get("compaction_threshold") or 0)
        if not window:
            return ToolResult(success=False, output="", error="Context window is not known yet.")
        if used is None:
            return ToolResult(
                success=True,
                output=f"Context window: {window:,} tokens. Usage is not measurable right now.",
                metadata={"window": window},
            )
        used = int(used)
        remaining = max(0, (threshold or window) - used)
        percent = min(100, round(used * 100 / window)) if window else 0
        lines = [
            f"Context window: {window:,} tokens",
            f"Used: ~{used:,} tokens ({percent}%)",
            f"Remaining before automatic compaction: ~{remaining:,} tokens",
        ]
        if threshold:
            lines.append(
                f"Compaction triggers near ~{threshold:,} tokens; stale tool outputs are pruned first, so finishing soon preserves the most context."
            )
        return ToolResult(
            success=True,
            output="\n".join(lines),
            metadata={
                "window": window,
                "used": used,
                "remaining": remaining,
                "compaction_threshold": threshold,
                "percent_used": percent,
            },
        )


class ReadContextChunkTool(Tool):
    """Return a tool output that context prune kept outside the prompt."""

    read_only = True

    @property
    def name(self) -> str:
        return "read_context_chunk"

    @property
    def description(self) -> str:
        return (
            "Read the original text of a tool output that was stubbed to save "
            "context. Pass the chunk_id from the stub. This reads only that "
            "saved output. It does not read files."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "chunk_id": {
                    "type": "string",
                    "description": "Id from the stub, such as tool-call-1.",
                }
            },
            "required": ["chunk_id"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        chunk_id = str(args.get("chunk_id") or "").strip()
        if not chunk_id:
            return ToolResult(success=False, output="", error="chunk_id is required.")
        lookup = getattr(ctx, "context_chunk", None)
        if lookup is None:
            return ToolResult(
                success=False,
                output="",
                error="No retained context chunks are available in this run.",
            )
        try:
            text = lookup(chunk_id)
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Context chunk lookup failed: {exc}")
        if not isinstance(text, str):
            return ToolResult(
                success=False,
                output="",
                error=f"No retained output for chunk {chunk_id}.",
            )
        limit = int(getattr(ctx, "max_output_bytes", None) or 100_000)
        if limit > 0 and len(text) > limit:
            shown = text[:limit]
            return ToolResult(
                success=True,
                output=(
                    f"{shown}\n[chunk {chunk_id}: showing {limit:,} of {len(text):,} characters]"
                ),
                metadata={"chunk_id": chunk_id, "chars": len(text), "truncated": True},
            )
        return ToolResult(
            success=True,
            output=text,
            metadata={"chunk_id": chunk_id, "chars": len(text), "truncated": False},
        )


__all__ = ["GetContextRemainingTool", "ReadContextChunkTool"]
