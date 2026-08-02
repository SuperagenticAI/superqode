"""Pi-compatible provider-neutral content and transcript messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Literal

from .types import JSONValue


def current_timestamp_ms() -> int:
    """Return the current Unix timestamp in milliseconds."""
    return int(time() * 1000)


@dataclass(slots=True)
class UsageCost:
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "total": self.total,
        }


@dataclass(slots=True)
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int | None = None
    total_tokens: int = 0
    cost: UsageCost = field(default_factory=UsageCost)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "reasoning": self.reasoning,
            "total_tokens": self.total_tokens,
            "cost": self.cost.to_dict(),
        }


@dataclass(slots=True)
class TextContent:
    text: str
    type: Literal["text"] = "text"
    text_signature: str | None = None


@dataclass(slots=True)
class ThinkingContent:
    thinking: str
    type: Literal["thinking"] = "thinking"
    thinking_signature: str | None = None
    redacted: bool = False


@dataclass(slots=True)
class ImageContent:
    data: str
    mime_type: str
    type: Literal["image"] = "image"


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, JSONValue] = field(default_factory=dict)
    type: Literal["toolCall"] = "toolCall"
    thought_signature: str | None = None


StopReason = Literal["stop", "length", "toolUse", "error", "aborted"]
UserContent = str | list[TextContent | ImageContent]
AssistantContent = TextContent | ThinkingContent | ToolCall
ToolResultContent = TextContent | ImageContent


@dataclass(slots=True)
class UserMessage:
    content: UserContent
    role: Literal["user"] = "user"
    timestamp: int = field(default_factory=current_timestamp_ms)

    @property
    def text(self) -> str:
        return content_text(self.content)


@dataclass(slots=True)
class AssistantMessage:
    content: list[AssistantContent] = field(default_factory=list)
    role: Literal["assistant"] = "assistant"
    api: str = "unknown"
    provider: str = "unknown"
    model: str = "unknown"
    usage: Usage = field(default_factory=Usage)
    stop_reason: StopReason = "stop"
    error_message: str | None = None
    timestamp: int = field(default_factory=current_timestamp_ms)

    def __post_init__(self) -> None:
        if isinstance(self.content, str):
            text = self.content
            object.__setattr__(
                self,
                "content",
                [TextContent(text=text)] if text else [],
            )

    @property
    def text(self) -> str:
        return "".join(block.text for block in self.content if isinstance(block, TextContent))

    @property
    def thinking_text(self) -> str:
        return "".join(
            block.thinking for block in self.content if isinstance(block, ThinkingContent)
        )

    @property
    def tool_calls(self) -> tuple[ToolCall, ...]:
        return tuple(block for block in self.content if isinstance(block, ToolCall))


@dataclass(slots=True)
class ToolResultMessage:
    tool_call_id: str
    tool_name: str
    content: list[ToolResultContent] = field(default_factory=list)
    role: Literal["toolResult"] = "toolResult"
    details: JSONValue = None
    added_tool_names: list[str] | None = None
    is_error: bool = False
    timestamp: int = field(default_factory=current_timestamp_ms)

    def __post_init__(self) -> None:
        if isinstance(self.content, str):
            text = self.content
            object.__setattr__(
                self,
                "content",
                [TextContent(text=text)] if text else [],
            )

    @property
    def text(self) -> str:
        return content_text(self.content)


@dataclass(slots=True)
class BranchSummaryMessage:
    summary: str
    from_id: str
    role: Literal["branchSummary"] = "branchSummary"
    timestamp: int = field(default_factory=current_timestamp_ms)


@dataclass(slots=True)
class CompactionSummaryMessage:
    summary: str
    tokens_before: int
    role: Literal["compactionSummary"] = "compactionSummary"
    timestamp: int = field(default_factory=current_timestamp_ms)


AgentMessage = (
    UserMessage
    | AssistantMessage
    | ToolResultMessage
    | BranchSummaryMessage
    | CompactionSummaryMessage
)


def content_text(content: str | list[Any]) -> str:
    if isinstance(content, str):
        return content
    return "".join(block.text for block in content if isinstance(block, TextContent))


def message_text(message: AgentMessage) -> str:
    if isinstance(message, (UserMessage, AssistantMessage, ToolResultMessage)):
        return message.text
    if isinstance(message, (BranchSummaryMessage, CompactionSummaryMessage)):
        return message.summary
    return ""


def assistant_content(
    text: str,
    tool_calls: list[ToolCall] | tuple[ToolCall, ...] = (),
) -> list[AssistantContent]:
    blocks: list[AssistantContent] = [TextContent(text=text)] if text else []
    blocks.extend(tool_calls)
    return blocks
