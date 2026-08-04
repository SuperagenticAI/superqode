"""Harness-own events and hook results.

Ported from ``packages/agent/src/harness/types.ts`` of earendil-works/pi (MIT).

Two channels, as in pi:

- **Subscribers** see everything, agent events and harness events alike, and
  return nothing. This is what a UI attaches to.
- **Hooks** are registered per event type and may return a patch that changes
  what happens next. This is what an extension attaches to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .messages import AgentMessage, ImageContent, TextContent, Usage
from .stream import Model, StreamOptions
from .types import JSONValue

# --------------------------------------------------------------------------- #
# Notification events: subscribers only, no return value
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class QueueUpdateEvent:
    steer: list[AgentMessage] = field(default_factory=list)
    follow_up: list[AgentMessage] = field(default_factory=list)
    next_turn: list[AgentMessage] = field(default_factory=list)
    type: Literal["queue_update"] = "queue_update"


@dataclass(slots=True)
class SavePointEvent:
    """Emitted after a turn's session writes have been flushed."""

    had_pending_mutations: bool = False
    type: Literal["save_point"] = "save_point"


@dataclass(slots=True)
class AbortEvent:
    cleared_steer: list[AgentMessage] = field(default_factory=list)
    cleared_follow_up: list[AgentMessage] = field(default_factory=list)
    type: Literal["abort"] = "abort"


@dataclass(slots=True)
class SettledEvent:
    """Emitted when a run is fully settled and the harness is idle again."""

    next_turn_count: int = 0
    type: Literal["settled"] = "settled"


@dataclass(slots=True)
class ModelUpdateEvent:
    model: Model
    type: Literal["model_update"] = "model_update"


@dataclass(slots=True)
class ThinkingLevelUpdateEvent:
    thinking_level: str
    type: Literal["thinking_level_update"] = "thinking_level_update"


@dataclass(slots=True)
class ToolsUpdateEvent:
    tool_names: list[str] = field(default_factory=list)
    active_tool_names: list[str] = field(default_factory=list)
    type: Literal["tools_update"] = "tools_update"


@dataclass(slots=True)
class AfterProviderResponseEvent:
    status: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    type: Literal["after_provider_response"] = "after_provider_response"


# --------------------------------------------------------------------------- #
# Hook events: may return a patch
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class BeforeAgentStartEvent:
    prompt: str
    system_prompt: str
    images: list[ImageContent] = field(default_factory=list)
    type: Literal["before_agent_start"] = "before_agent_start"


@dataclass(slots=True)
class BeforeAgentStartResult:
    #: Replaces the system prompt for this run only.
    system_prompt: str | None = None
    #: Appended after the user's prompt message.
    messages: list[AgentMessage] | None = None


@dataclass(slots=True)
class ContextEvent:
    messages: list[AgentMessage] = field(default_factory=list)
    type: Literal["context"] = "context"


@dataclass(slots=True)
class ContextResult:
    messages: list[AgentMessage] | None = None


@dataclass(slots=True)
class ToolCallEvent:
    tool_call_id: str
    tool_name: str
    input: dict[str, JSONValue] = field(default_factory=dict)
    type: Literal["tool_call"] = "tool_call"


@dataclass(slots=True)
class ToolCallResult:
    block: bool = False
    reason: str | None = None


@dataclass(slots=True)
class ToolResultEvent:
    tool_call_id: str
    tool_name: str
    input: dict[str, JSONValue] = field(default_factory=dict)
    content: list[TextContent | ImageContent] = field(default_factory=list)
    details: JSONValue = None
    is_error: bool = False
    usage: Usage | None = None
    type: Literal["tool_result"] = "tool_result"


@dataclass(slots=True)
class ToolResultPatch:
    content: list[TextContent | ImageContent] | None = None
    details: JSONValue = None
    is_error: bool | None = None
    usage: Usage | None = None
    terminate: bool | None = None


@dataclass(slots=True)
class BeforeProviderRequestEvent:
    model: Model
    session_id: str
    stream_options: StreamOptions
    type: Literal["before_provider_request"] = "before_provider_request"


@dataclass(slots=True)
class BeforeProviderRequestResult:
    stream_options: StreamOptions | None = None


HarnessOwnEvent = (
    QueueUpdateEvent
    | SavePointEvent
    | AbortEvent
    | SettledEvent
    | ModelUpdateEvent
    | ThinkingLevelUpdateEvent
    | ToolsUpdateEvent
    | AfterProviderResponseEvent
    | BeforeAgentStartEvent
    | ContextEvent
    | ToolCallEvent
    | ToolResultEvent
    | BeforeProviderRequestEvent
)


@dataclass(slots=True)
class AbortResult:
    cleared_steer: list[AgentMessage] = field(default_factory=list)
    cleared_follow_up: list[AgentMessage] = field(default_factory=list)


class AgentHarnessError(RuntimeError):
    """Error raised by the harness, tagged with a stable code.

    Codes: ``busy``, ``invalid_state``, ``invalid_argument``, ``hook``,
    ``session``, ``compaction``, ``branch_summary``, ``unknown``.
    """

    def __init__(self, code: str, message: str, cause: BaseException | None = None) -> None:
        self.code = code
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause


def to_error(value: Any) -> BaseException:
    return value if isinstance(value, BaseException) else RuntimeError(str(value))


__all__ = [
    "AbortEvent",
    "AbortResult",
    "AfterProviderResponseEvent",
    "AgentHarnessError",
    "BeforeAgentStartEvent",
    "BeforeAgentStartResult",
    "BeforeProviderRequestEvent",
    "BeforeProviderRequestResult",
    "ContextEvent",
    "ContextResult",
    "HarnessOwnEvent",
    "ModelUpdateEvent",
    "QueueUpdateEvent",
    "SavePointEvent",
    "SettledEvent",
    "ThinkingLevelUpdateEvent",
    "ToolCallEvent",
    "ToolCallResult",
    "ToolResultEvent",
    "ToolResultPatch",
    "ToolsUpdateEvent",
    "to_error",
]
