"""Provider contract for PiPy's portable agent layer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from .messages import AgentMessage
from .provider_events import AssistantMessageEvent
from .tools_base import AgentTool


class CancellationToken(Protocol):
    def is_cancelled(self) -> bool: ...


class ModelProvider(Protocol):
    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationToken | None = None,
    ) -> AsyncIterator[AssistantMessageEvent]:
        """Stream one model response as assistant message events."""
        ...
