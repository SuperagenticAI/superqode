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


__all__ = ["GetContextRemainingTool"]
