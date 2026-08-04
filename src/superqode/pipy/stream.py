"""Provider stream contract for the PiPy loop.

Port of the ``StreamFn`` / ``Context`` / ``Model`` boundary in
``packages/agent/src/types.ts`` and ``packages/ai/src/types.ts`` of
earendil-works/pi (MIT).

Phase 1 keeps ``Model`` minimal: the loop only needs an identity to send and a
provider name for key resolution. Phase 6 enriches it with the catalog metadata
(context window, pricing, reasoning support) that pi carries.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from .messages import Message
from .provider_events import AssistantMessageEvent
from .signals import AbortSignal
from .tools.base import AgentTool
from .types import ThinkingLevel


@dataclass(frozen=True, slots=True)
class Model:
    """Identity of the model a turn is sent to."""

    id: str
    provider: str = "unknown"
    api: str = "unknown"
    #: Whether the model accepts a reasoning/thinking level.
    supports_reasoning: bool = False
    #: Tokens the model accepts. Zero means unknown, which disables
    #: automatic compaction rather than guessing a limit.
    context_window: int = 0


@dataclass(slots=True)
class Context:
    """One provider request: prompt, transcript and callable tools."""

    system_prompt: str
    messages: list[Message]
    tools: list[AgentTool] | None = None


@dataclass(slots=True)
class StreamOptions:
    """Per-request options handed to the stream function."""

    api_key: str | None = None
    reasoning: ThinkingLevel | None = None
    signal: AbortSignal | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    headers: Mapping[str, str] | None = None
    metadata: Mapping[str, str] | None = None
    session_id: str | None = None
    timeout_seconds: float | None = None
    max_retries: int | None = None
    extra: dict[str, object] = field(default_factory=dict)


AssistantEventSource = AsyncIterator[AssistantMessageEvent]


class StreamFn(Protocol):
    """Stream one assistant response as pi-compatible assistant events.

    Contract, unchanged from pi:

    - Must not raise for request, model or runtime failures.
    - Failures are encoded in the stream, ending with an
      :class:`~superqode.pipy.provider_events.AssistantErrorEvent` whose message
      carries stop reason ``error`` or ``aborted`` and an ``error_message``.
    - The terminal ``done`` or ``error`` event carries the final assistant
      message. pi exposes this through ``EventStream.result()``; PiPy reads it
      off the terminal event, which is equivalent.
    """

    def __call__(
        self,
        model: Model,
        context: Context,
        options: StreamOptions,
    ) -> AssistantEventSource | Awaitable[AssistantEventSource]: ...


__all__ = [
    "AssistantEventSource",
    "Context",
    "Model",
    "StreamFn",
    "StreamOptions",
]
