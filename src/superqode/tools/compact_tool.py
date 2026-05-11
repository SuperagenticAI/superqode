"""
Context Compaction Tool for Manual Conversation Compression.

Allows users to manually compact/compress conversation history
when it gets too large.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..tools.base import Tool, ToolResult, ToolContext


@dataclass
class CompactionStats:
    """Statistics about compaction."""

    original_messages: int = 0
    compacted_messages: int = 0
    tokens_saved: int = 0


class CompactTool(Tool):
    """Tool to manually compact conversation history."""

    def __init__(self):
        self._history: List[Any] = []

    @property
    def name(self) -> str:
        return "compact"

    @property
    def description(self) -> str:
        return """Compact/summarize the conversation history to reduce token usage.

Use this when:
- Conversation has grown too long
- You're hitting token limits
- You want to start fresh while keeping context

This creates a summary of the conversation so far."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["summarize", "clear", "status", "preview"],
                    "description": "Action to perform",
                },
                "keep_recent": {
                    "type": "integer",
                    "description": "Number of recent messages to keep (default: 2)",
                    "default": 2,
                },
            },
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        action = args.get("action", "summarize")
        keep_recent = args.get("keep_recent", 2)

        if action == "clear":
            return self._clear_history()

        elif action == "status":
            return self._show_status()

        elif action == "preview":
            return self._preview_summary(keep_recent)

        else:  # summarize
            return self._summarize(keep_recent)

    def _clear_history(self) -> ToolResult:
        """Clear all conversation history."""
        count = len(self._history)
        self._history = []
        return ToolResult(
            success=True,
            output=f"Cleared {count} messages from history.",
            metadata={"cleared": count},
        )

    def _show_status(self) -> ToolResult:
        """Show current history status."""
        total = len(self._history)
        if total == 0:
            return ToolResult(
                success=True,
                output="No conversation history.",
            )

        total_chars = sum(len(getattr(m, "content", str(m))) for m in self._history)
        return ToolResult(
            success=True,
            output=f"History: {total} messages, ~{total_chars} characters",
            metadata={"messages": total, "characters": total_chars},
        )

    def _preview_summary(self, keep_recent: int) -> ToolResult:
        """Preview what a summary would look like."""
        if len(self._history) <= keep_recent:
            return ToolResult(
                success=True,
                output="History is small enough - no compaction needed.",
            )

        old_messages = self._history[:-keep_recent]
        old_text = "\n".join(
            f"{getattr(m, 'role', '?')}: {getattr(m, 'content', '')[:100]}..."
            for m in old_messages
        )

        return ToolResult(
            success=True,
            output=f"Would summarize {len(old_messages)} messages:\n\n{old_text[:500]}...",
            metadata={"to_summarize": len(old_messages)},
        )

    def _summarize(self, keep_recent: int) -> ToolResult:
        """Create a summary of older messages."""
        if len(self._history) <= keep_recent:
            return ToolResult(
                success=True,
                output="Nothing to compact - conversation is already concise.",
            )

        old_messages = self._history[:-keep_recent]
        recent = self._history[-keep_recent:]

        # Create summary placeholder (in real impl, model would do this)
        summary = f"[Earlier conversation with {len(old_messages)} messages compacted]"

        # Keep recent messages + add summary
        self._history = recent
        self._history.insert(0, type("Msg", (), {"role": "system", "content": summary})())

        return ToolResult(
            success=True,
            output=f"Compacted {len(old_messages)} messages into summary. "
            f"Kept {keep_recent} recent messages.",
            metadata={
                "compacted": len(old_messages),
                "kept": keep_recent,
            },
        )

    def set_history(self, history: List[Any]):
        """Set conversation history."""
        self._history = history

    def get_history(self) -> List[Any]:
        """Get current history."""
        return self._history


def create_compact_tool() -> CompactTool:
    """Create the compact tool."""
    return CompactTool()