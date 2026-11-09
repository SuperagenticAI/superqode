"""
Context Manager for SuperQode.

Handles token counting, message pruning, and summarization to keep
agent conversations within model context limits.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class ContextManager:
    """Manages agent conversation context."""

    def __init__(
        self,
        max_tokens: int = 8000,
        summarize_at: float = 0.8,
        model_name: str = "gpt-4",
    ):
        self.max_tokens = max_tokens
        self.summarize_at = int(max_tokens * summarize_at)
        self.model_name = model_name
        self._last_summary: Optional[str] = None

    def count_tokens(self, messages: List[Dict[str, Any]], tools=None) -> int:
        """Count structured messages and optional tool schemas conservatively."""
        from superqode.local.context_contract import estimate_tokens

        return estimate_tokens(messages, tools)

    def prune_history(
        self, messages: List[Dict[str, Any]], reserve_tokens: int = 1000
    ) -> List[Dict[str, Any]]:
        """Prune messages if they exceed the limit, keeping the system prompt."""
        if not messages:
            return []

        token_count = self.count_tokens(messages)
        if token_count <= (self.max_tokens - reserve_tokens):
            return messages

        # Keep system prompt (index 0) and prune from the beginning of history
        system_prompt = messages[0] if messages[0].get("role") == "system" else None
        history = messages[1:] if system_prompt else messages

        while (
            self.count_tokens(history) > (self.max_tokens - reserve_tokens - 500)
            and len(history) > 2
        ):
            history.pop(0)

        return [system_prompt] + history if system_prompt else history

    async def summarize_history(
        self, messages: List[Dict[str, Any]], summarizer_fn: Any
    ) -> List[Dict[str, Any]]:
        """Summarize older messages to save context space."""
        if len(messages) <= 5:
            return messages

        # Keep first (system) and last 3 messages
        to_summarize = messages[1:-3]
        keep_last = messages[-3:]
        system_msg = [messages[0]] if messages[0].get("role") == "system" else []

        summary_text = await summarizer_fn(to_summarize)
        self._last_summary = summary_text

        summary_msg = {
            "role": "system",
            "content": f"Summary of previous conversation: {summary_text}",
        }

        return system_msg + [summary_msg] + keep_last
