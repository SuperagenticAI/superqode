"""Pi-compatible assistant stream events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .messages import AssistantMessage, ToolCall

DoneReason = Literal["stop", "length", "toolUse"]
ErrorReason = Literal["aborted", "error"]


@dataclass(slots=True)
class AssistantStartEvent:
    partial: AssistantMessage
    type: Literal["start"] = "start"


@dataclass(slots=True)
class TextStartEvent:
    content_index: int
    partial: AssistantMessage
    type: Literal["text_start"] = "text_start"


@dataclass(slots=True)
class TextDeltaEvent:
    content_index: int
    delta: str
    partial: AssistantMessage
    type: Literal["text_delta"] = "text_delta"


@dataclass(slots=True)
class TextEndEvent:
    content_index: int
    content: str
    partial: AssistantMessage
    type: Literal["text_end"] = "text_end"


@dataclass(slots=True)
class ThinkingStartEvent:
    content_index: int
    partial: AssistantMessage
    type: Literal["thinking_start"] = "thinking_start"


@dataclass(slots=True)
class ThinkingDeltaEvent:
    content_index: int
    delta: str
    partial: AssistantMessage
    type: Literal["thinking_delta"] = "thinking_delta"


@dataclass(slots=True)
class ThinkingEndEvent:
    content_index: int
    content: str
    partial: AssistantMessage
    type: Literal["thinking_end"] = "thinking_end"


@dataclass(slots=True)
class ToolCallStartEvent:
    content_index: int
    partial: AssistantMessage
    type: Literal["toolcall_start"] = "toolcall_start"


@dataclass(slots=True)
class ToolCallDeltaEvent:
    content_index: int
    delta: str
    partial: AssistantMessage
    type: Literal["toolcall_delta"] = "toolcall_delta"


@dataclass(slots=True)
class ToolCallEndEvent:
    content_index: int
    tool_call: ToolCall
    partial: AssistantMessage
    type: Literal["toolcall_end"] = "toolcall_end"


@dataclass(slots=True)
class AssistantDoneEvent:
    reason: DoneReason
    message: AssistantMessage
    type: Literal["done"] = "done"


@dataclass(slots=True)
class AssistantErrorEvent:
    reason: ErrorReason
    error: AssistantMessage
    type: Literal["error"] = "error"


AssistantMessageEvent = (
    AssistantStartEvent
    | TextStartEvent
    | TextDeltaEvent
    | TextEndEvent
    | ThinkingStartEvent
    | ThinkingDeltaEvent
    | ThinkingEndEvent
    | ToolCallStartEvent
    | ToolCallDeltaEvent
    | ToolCallEndEvent
    | AssistantDoneEvent
    | AssistantErrorEvent
)
