"""
Auto Summarization for Agent Context.

Compresses conversation history when it exceeds token limits,
keeping important context while reducing size.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional


@dataclass
class SummaryConfig:
    """Configuration for auto summarization."""

    max_tokens: int = 6000
    min_messages: int = 4
    summary_prompt: str = """Summarize this conversation concisely, keeping:
- Key decisions and conclusions
- Important code changes or files
- Any bugs or issues found
- Next steps if mentioned

Return a concise summary (2-4 sentences)."""


@dataclass
class SummarizedMessage:
    """A message that has been summarized."""

    role: str
    content: str
    original_count: int = 1


class ContextSummarizer:
    """Summarizes conversation context when it gets too large."""

    def __init__(
        self,
        config: Optional[SummaryConfig] = None,
        tokenizer: Optional[Callable[[str], int]] = None,
    ):
        self.config = config or SummaryConfig()
        self._tokenizer = tokenizer or self._default_tokenizer

    def _default_tokenizer(self, text: str) -> int:
        """Simple word-based token estimate (~0.75 tokens per word)."""
        return int(len(text.split()) * 1.33)

    def should_summarize(self, messages: List[Any]) -> bool:
        """Check if messages need summarization."""
        if len(messages) < self.config.min_messages:
            return False

        total_tokens = sum(self._tokenizer(getattr(m, "content", str(m))) for m in messages)
        return total_tokens > self.config.max_tokens

    def summarize_messages(
        self,
        messages: List[Any],
        system_prompt: Optional[str] = None,
    ) -> List[SummarizedMessage]:
        """Summarize old messages, keeping recent ones intact."""
        if not messages:
            return []

        keep_recent = max(2, len(messages) // 4)
        to_summarize = messages[:-keep_recent]
        recent = messages[-keep_recent:]

        if not to_summarize:
            return [SummarizedMessage(role=getattr(m, "role", "user"), content=getattr(m, "content", str(m))) for m in messages]

        conversation_text = self._build_conversation_text(to_summarize)
        summary = self._generate_summary(conversation_text)

        result = [
            SummarizedMessage(
                role="system",
                content=f"[Earlier conversation summarized]\n{summary}",
            )
        ]

        for m in recent:
            result.append(
                SummarizedMessage(
                    role=getattr(m, "role", "user"),
                    content=getattr(m, "content", str(m)),
                )
            )

        return result

    def _build_conversation_text(self, messages: List[Any]) -> str:
        """Build conversation text for summarization."""
        parts = []
        for m in messages:
            role = getattr(m, "role", "user")
            content = getattr(m, "content", str(m))[:500]
            parts.append(f"{role}: {content}")
        return "\n".join(parts)

    def _generate_summary(self, text: str) -> str:
        """Generate summary (placeholder - model would do this)."""
        words = text.split()
        if len(words) > 100:
            return " ".join(words[:100]) + "..."
        return text


class ContextManager:
    """Manages context with auto-summarization."""

    def __init__(
        self,
        max_tokens: int = 8000,
        summarizer: Optional[ContextSummarizer] = None,
    ):
        self.max_tokens = max_tokens
        self.summarizer = summarizer or ContextSummarizer(SummaryConfig(max_tokens=max_tokens))
        self._messages: List[Any] = []
        self._system_prompt: Optional[str] = None

    @property
    def messages(self) -> List[Any]:
        return self._messages

    @messages.setter
    def messages(self, value: List[Any]):
        self._messages = value
        self._maybe_summarize()

    def add_message(self, role: str, content: str):
        """Add a message and check for summarization need."""
        self._messages.append(self._create_message(role, content))
        self._maybe_summarize()

    def _create_message(self, role: str, content: str) -> Any:
        """Create a message object."""
        from dataclasses import dataclass

        @dataclass
        class Message:
            role: str
            content: str

        return Message(role=role, content=content)

    def _maybe_summarize(self):
        """Summarize if needed."""
        if self.summarizer.should_summarize(self._messages):
            summarized = self.summarizer.summarize_messages(self._messages, self._system_prompt)
            self._messages = [
                self._create_message(m.role, m.content) for m in summarized
            ]

    def get_messages_for_model(self) -> List[Any]:
        """Get messages formatted for model."""
        return self._messages

    def clear(self):
        """Clear all messages."""
        self._messages = []


def create_context_manager(max_tokens: int = 8000) -> ContextManager:
    """Create a context manager with auto-summarization."""
    return ContextManager(max_tokens=max_tokens)