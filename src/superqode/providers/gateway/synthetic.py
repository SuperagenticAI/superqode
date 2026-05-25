"""
Synthetic Gateways - deterministic LLMs for tests and harness fixtures.

Three implementations of :class:`GatewayInterface` that never call a real
provider:

- :class:`PassthroughGateway` — echoes the last user message back as the
  assistant reply. Supports two in-band indicators in the user message:

  * ``***CALL_TOOL <name> [json_args]`` — return a single tool call
    instead of text. ``json_args`` is optional.
  * ``***FIXED_RESPONSE <text>`` — from this turn onward, return
    ``text`` verbatim as the response.

- :class:`PlaybackGateway` — pre-load a queue of assistant responses; each
  call pops the next one. Once exhausted, returns a sentinel message.

- :class:`SilentGateway` — like Passthrough but reports zero token usage,
  useful for fan-in / aggregator agents in workflows where token counting
  for intermediate replies would distort budgets.

These mirror the synthetic providers in fast-agent
(``fast_agent.llm.internal.{passthrough,playback,silent}``) so prompts and
fixtures port across without rewriting indicator syntax.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from typing import Any, AsyncIterator, Dict, List, Optional

from .base import (
    Cost,
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
    ToolDefinition,
    Usage,
)


CALL_TOOL_INDICATOR = "***CALL_TOOL"
FIXED_RESPONSE_INDICATOR = "***FIXED_RESPONSE"


def _last_user_text(messages: List[Message]) -> str:
    """Concatenate trailing user messages (most recent run only)."""
    collected: List[str] = []
    for msg in reversed(messages):
        if msg.role != "user":
            break
        collected.append(msg.content or "")
    return "\n".join(reversed(collected))


def _parse_tool_command(command: str) -> tuple[str, Optional[Dict[str, Any]]]:
    """Parse ``***CALL_TOOL <name> [json_args]`` from the first line."""
    line = command.strip().splitlines()[0]
    parts = line.split(" ", 2)
    if len(parts) < 2:
        raise ValueError(
            f"Invalid {CALL_TOOL_INDICATOR} syntax. Expected '{CALL_TOOL_INDICATOR} <tool_name> [json]'"
        )
    tool_name = parts[1].strip()
    arguments: Optional[Dict[str, Any]] = None
    if len(parts) > 2 and parts[2].strip():
        try:
            arguments = json.loads(parts[2])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON arguments for {CALL_TOOL_INDICATOR}: {exc}") from exc
    return tool_name, arguments


def _approx_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token). Synthetic gateways don't tokenize."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _build_usage(prompt_text: str, completion_text: str) -> Usage:
    prompt = _approx_tokens(prompt_text)
    completion = _approx_tokens(completion_text)
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


class PassthroughGateway(GatewayInterface):
    """Echoes the last user message back; supports tool-call and fixed-response indicators.

    State is per-instance — create a fresh gateway per test to avoid the
    fixed-response sticking across cases.
    """

    PROVIDER_NAME = "synthetic"
    MODEL_NAME = "passthrough"

    def __init__(self) -> None:
        self._fixed_response: Optional[str] = None

    def reset(self) -> None:
        """Clear sticky fixed-response state."""
        self._fixed_response = None

    def get_model_string(self, provider: str, model: str) -> str:
        return f"{provider}/{model}" if provider else model

    async def test_connection(
        self, provider: str, model: Optional[str] = None
    ) -> Dict[str, Any]:
        return {"ok": True, "provider": provider, "model": model or self.MODEL_NAME}

    def _build_response(
        self,
        messages: List[Message],
        model: str,
    ) -> GatewayResponse:
        last_text = _last_user_text(messages)

        # Sticky fixed-response indicator: once set, every subsequent turn returns it.
        if last_text.startswith(FIXED_RESPONSE_INDICATOR):
            self._fixed_response = last_text[len(FIXED_RESPONSE_INDICATOR):].strip()

        if last_text.startswith(CALL_TOOL_INDICATOR):
            tool_name, arguments = _parse_tool_command(last_text)
            tool_call = {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments or {}),
                },
            }
            usage = _build_usage(last_text, "")
            return GatewayResponse(
                content="",
                role="assistant",
                finish_reason="tool_calls",
                usage=usage,
                cost=Cost(),
                model=model,
                provider=self.PROVIDER_NAME,
                tool_calls=[tool_call],
            )

        body = self._fixed_response if self._fixed_response is not None else last_text
        usage = _build_usage(last_text, body)
        return GatewayResponse(
            content=body,
            role="assistant",
            finish_reason="stop",
            usage=usage,
            cost=Cost(),
            model=model,
            provider=self.PROVIDER_NAME,
        )

    async def chat_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> GatewayResponse:
        return self._build_response(messages, model)

    async def stream_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        return self._stream(messages, model)

    async def _stream(
        self,
        messages: List[Message],
        model: str,
    ) -> AsyncIterator[StreamChunk]:
        response = self._build_response(messages, model)
        if response.tool_calls:
            yield StreamChunk(
                content="",
                role="assistant",
                tool_calls=response.tool_calls,
            )
        elif response.content:
            yield StreamChunk(content=response.content, role="assistant")
        yield StreamChunk(
            finish_reason=response.finish_reason,
            usage=response.usage,
            cost=response.cost,
        )


class PlaybackGateway(GatewayInterface):
    """Replays a pre-loaded sequence of assistant responses.

    Usage::

        gw = PlaybackGateway()
        gw.queue("first reply", "second reply")
        gw.queue_tool_call("read", {"path": "x.py"})
        # subsequent calls pop the queue in order
    """

    PROVIDER_NAME = "synthetic"
    MODEL_NAME = "playback"

    def __init__(self) -> None:
        self._queue: deque[GatewayResponse] = deque()
        self._overage = 0

    def queue(self, *responses: str) -> None:
        """Enqueue text responses (each pops on its own turn)."""
        for text in responses:
            self._queue.append(
                GatewayResponse(
                    content=text,
                    role="assistant",
                    finish_reason="stop",
                    usage=_build_usage("", text),
                    cost=Cost(),
                    model=self.MODEL_NAME,
                    provider=self.PROVIDER_NAME,
                )
            )

    def queue_tool_call(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> None:
        """Enqueue a tool-call response."""
        tool_call = {
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(arguments or {}),
            },
        }
        self._queue.append(
            GatewayResponse(
                content="",
                role="assistant",
                finish_reason="tool_calls",
                usage=Usage(),
                cost=Cost(),
                model=self.MODEL_NAME,
                provider=self.PROVIDER_NAME,
                tool_calls=[tool_call],
            )
        )

    def reset(self) -> None:
        self._queue.clear()
        self._overage = 0

    @property
    def remaining(self) -> int:
        return len(self._queue)

    def get_model_string(self, provider: str, model: str) -> str:
        return f"{provider}/{model}" if provider else model

    async def test_connection(
        self, provider: str, model: Optional[str] = None
    ) -> Dict[str, Any]:
        return {
            "ok": True,
            "provider": provider,
            "model": model or self.MODEL_NAME,
            "queued": self.remaining,
        }

    def _pop_or_exhausted(self) -> GatewayResponse:
        if self._queue:
            return self._queue.popleft()
        self._overage += 1
        text = f"MESSAGES EXHAUSTED ({self._overage} overage)"
        return GatewayResponse(
            content=text,
            role="assistant",
            finish_reason="stop",
            usage=_build_usage("", text),
            cost=Cost(),
            model=self.MODEL_NAME,
            provider=self.PROVIDER_NAME,
        )

    async def chat_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> GatewayResponse:
        response = self._pop_or_exhausted()
        # Preserve the originally-passed model name in the response.
        return GatewayResponse(
            content=response.content,
            role=response.role,
            finish_reason=response.finish_reason,
            usage=response.usage,
            cost=response.cost,
            model=model,
            provider=self.PROVIDER_NAME,
            tool_calls=response.tool_calls,
        )

    async def stream_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        return self._stream(model)

    async def _stream(self, model: str) -> AsyncIterator[StreamChunk]:
        response = self._pop_or_exhausted()
        if response.tool_calls:
            yield StreamChunk(content="", role="assistant", tool_calls=response.tool_calls)
        elif response.content:
            yield StreamChunk(content=response.content, role="assistant")
        yield StreamChunk(
            finish_reason=response.finish_reason,
            usage=response.usage,
            cost=response.cost,
        )


class SilentGateway(PassthroughGateway):
    """Passthrough that reports zero token usage and cost.

    Use for fan-in / aggregator agents in workflows where intermediate
    bookkeeping would inflate token totals.
    """

    MODEL_NAME = "silent"

    def _build_response(
        self,
        messages: List[Message],
        model: str,
    ) -> GatewayResponse:
        response = super()._build_response(messages, model)
        return GatewayResponse(
            content=response.content,
            role=response.role,
            finish_reason=response.finish_reason,
            usage=Usage(),  # zero
            cost=Cost(),  # zero
            model=response.model,
            provider=response.provider,
            tool_calls=response.tool_calls,
        )


__all__ = [
    "CALL_TOOL_INDICATOR",
    "FIXED_RESPONSE_INDICATOR",
    "PassthroughGateway",
    "PlaybackGateway",
    "SilentGateway",
]
