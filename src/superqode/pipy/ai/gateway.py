"""SuperQode gateway bridge.

Maps SuperQode's LiteLLM gateway onto pi's assistant event stream, so PiPy runs
against every provider SuperQode already supports. This is the breadth path and
the one that makes PiPy usable the day it becomes selectable; native Anthropic
and OpenAI-compatible streams follow behind the same contract.

The gateway is imported lazily so that ``import superqode.pipy`` stays cheap and
free of the provider stack.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from ..messages import (
    AssistantMessage,
    ImageContent,
    Message,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
    content_text,
)
from ..provider_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from ..signals import is_aborted
from ..stream import Context, Model, StreamOptions
from ..tools.base import AgentTool
from .transform import transform_messages

#: Provider finish reasons mapped onto pi's stop reasons. Anything unknown
#: falls back to ``stop``, which ends the turn cleanly rather than looking like
#: a failure the model should retry.
_STOP_REASONS: dict[str, str] = {
    "stop": "stop",
    "end_turn": "stop",
    "stop_sequence": "stop",
    "length": "length",
    "max_tokens": "length",
    "tool_calls": "toolUse",
    "tool_use": "toolUse",
    "function_call": "toolUse",
}


def map_stop_reason(finish_reason: str | None, *, has_tool_calls: bool) -> str:
    """Translate a provider finish reason into a pi stop reason."""
    mapped: str | None = None
    if finish_reason:
        lowered = finish_reason.lower()
        mapped = _STOP_REASONS.get(lowered)
        if mapped is None and lowered in ("content_filter", "error"):
            mapped = "error"

    if has_tool_calls and mapped in (None, "stop"):
        # Providers disagree about how a tool turn ends. OpenAI says
        # "tool_calls", Anthropic says "tool_use", and Ollama sends a plain
        # "stop" in a chunk after the call itself. A turn carrying tool calls
        # is a tool turn whatever the provider called it.
        #
        # "length" and "error" still win, because a truncated or failed
        # message must keep that reason: the loop refuses to execute tool
        # calls from a length-truncated response.
        return "toolUse"

    return mapped or "stop"


def _tool_definitions(tools: list[AgentTool] | None) -> list[Any]:
    from superqode.providers.gateway.base import ToolDefinition

    return [
        ToolDefinition(
            name=tool.name,
            description=tool.description,
            parameters=dict(tool.parameters),
        )
        for tool in tools or []
    ]


def _gateway_messages(system_prompt: str, messages: list[Message]) -> list[Any]:
    """Convert a pi transcript into the gateway's chat message shape."""
    from superqode.providers.gateway.base import Message as GatewayMessage

    converted: list[Any] = []
    if system_prompt:
        converted.append(GatewayMessage(role="system", content=system_prompt))

    for message in transform_messages(messages):
        if isinstance(message, UserMessage):
            converted.append(GatewayMessage(role="user", content=content_text(message.content)))
        elif isinstance(message, AssistantMessage):
            tool_calls = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(dict(call.arguments)),
                    },
                }
                for call in message.tool_calls
            ]
            converted.append(
                GatewayMessage(
                    role="assistant",
                    content=message.text,
                    tool_calls=tool_calls or None,
                    reasoning_content=message.thinking_text or None,
                )
            )
        elif isinstance(message, ToolResultMessage):
            converted.append(
                GatewayMessage(
                    role="tool",
                    content=message.text or "(no output)",
                    tool_call_id=message.tool_call_id,
                )
            )
    return converted


def _usage(raw_usage: Any, raw_cost: Any) -> Usage:
    usage = Usage()
    if raw_usage is not None:
        usage.input = int(getattr(raw_usage, "prompt_tokens", 0) or 0)
        usage.output = int(getattr(raw_usage, "completion_tokens", 0) or 0)
        usage.total_tokens = int(getattr(raw_usage, "total_tokens", 0) or 0) or (
            usage.input + usage.output
        )
    if raw_cost is not None:
        usage.cost = UsageCost(
            input=float(getattr(raw_cost, "input_cost", 0.0) or 0.0),
            output=float(getattr(raw_cost, "output_cost", 0.0) or 0.0),
            total=float(getattr(raw_cost, "total_cost", 0.0) or 0.0),
        )
    return usage


class _ToolCallAccumulator:
    """Reassembles tool calls whose arguments arrive across several chunks."""

    def __init__(self) -> None:
        self._by_index: dict[int, dict[str, Any]] = {}
        self._order: list[int] = []

    def add(self, raw_calls: list[dict[str, Any]]) -> None:
        for position, raw in enumerate(raw_calls):
            index = int(raw.get("index", position) or 0)
            slot = self._by_index.get(index)
            if slot is None:
                slot = {"id": "", "name": "", "arguments": ""}
                self._by_index[index] = slot
                self._order.append(index)
            if raw.get("id"):
                slot["id"] = str(raw["id"])
            function = raw.get("function") or {}
            if function.get("name"):
                slot["name"] = str(function["name"])
            arguments = function.get("arguments")
            if arguments:
                # Deltas append; a complete payload in one chunk also appends,
                # starting from an empty buffer.
                slot["arguments"] += (
                    arguments if isinstance(arguments, str) else json.dumps(arguments)
                )

    @property
    def empty(self) -> bool:
        return not self._by_index

    def build(self) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for position, index in enumerate(self._order):
            slot = self._by_index[index]
            if not slot["name"]:
                continue
            try:
                arguments = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except json.JSONDecodeError:
                # A truncated response can leave unparsable arguments. Keep the
                # call so the loop can report it; pi refuses to execute tool
                # calls from a length-truncated message anyway.
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {"value": arguments}
            calls.append(
                ToolCall(
                    id=slot["id"] or f"call_{position}",
                    name=slot["name"],
                    arguments=arguments,
                )
            )
        return calls


class GatewayStream:
    """A :class:`~superqode.pipy.stream.StreamFn` backed by SuperQode's gateway.

    Honours the pi contract: it never raises for a provider failure. Errors
    become a terminal error event carrying an assistant message with stop
    reason ``error``, which is what lets the loop end a run cleanly.
    """

    def __init__(self, gateway: Any | None = None) -> None:
        self._gateway = gateway

    def _resolve_gateway(self) -> Any:
        if self._gateway is None:
            from superqode.providers.gateway import GatewayFactory

            self._gateway = GatewayFactory.create("litellm")
        return self._gateway

    def __call__(
        self,
        model: Model,
        context: Context,
        options: StreamOptions,
    ) -> AsyncIterator[AssistantMessageEvent]:
        return self._stream(model, context, options)

    async def _stream(
        self,
        model: Model,
        context: Context,
        options: StreamOptions,
    ) -> AsyncIterator[AssistantMessageEvent]:
        def snapshot(content: list[Any], stop_reason: str = "stop") -> AssistantMessage:
            return AssistantMessage(
                content=list(content),
                api=model.api,
                provider=model.provider,
                model=model.id,
                stop_reason=stop_reason,  # type: ignore[arg-type]
            )

        if is_aborted(options.signal):
            aborted = snapshot([], "aborted")
            aborted.error_message = "Operation aborted"
            yield AssistantStartEvent(partial=snapshot([], "aborted"))
            yield AssistantErrorEvent(reason="aborted", error=aborted)
            return

        content: list[Any] = []
        text_index: int | None = None
        thinking_index: int | None = None
        text_buffer = ""
        thinking_buffer = ""
        tool_calls = _ToolCallAccumulator()
        usage = Usage()
        finish_reason: str | None = None

        yield AssistantStartEvent(partial=snapshot([]))

        try:
            stream = self._resolve_gateway().stream_completion(
                messages=_gateway_messages(context.system_prompt, context.messages),
                model=model.id,
                provider=model.provider or None,
                temperature=options.temperature,
                max_tokens=options.max_tokens,
                tools=_tool_definitions(context.tools) or None,
                tool_choice="auto" if context.tools else None,
            )

            async for chunk in stream:
                if is_aborted(options.signal):
                    aborted = snapshot(content, "aborted")
                    aborted.error_message = "Operation aborted"
                    yield AssistantErrorEvent(reason="aborted", error=aborted)
                    return

                thinking = getattr(chunk, "thinking_content", None)
                if thinking:
                    if thinking_index is None:
                        thinking_index = len(content)
                        content.append(ThinkingContent(thinking=""))
                        yield ThinkingStartEvent(
                            content_index=thinking_index, partial=snapshot(content)
                        )
                    thinking_buffer += thinking
                    content[thinking_index] = ThinkingContent(thinking=thinking_buffer)
                    yield ThinkingDeltaEvent(
                        content_index=thinking_index,
                        delta=thinking,
                        partial=snapshot(content),
                    )

                text = getattr(chunk, "content", "") or ""
                if text:
                    if thinking_index is not None and thinking_buffer:
                        yield ThinkingEndEvent(
                            content_index=thinking_index,
                            content=thinking_buffer,
                            partial=snapshot(content),
                        )
                        thinking_index = None
                    if text_index is None:
                        text_index = len(content)
                        content.append(TextContent(text=""))
                        yield TextStartEvent(content_index=text_index, partial=snapshot(content))
                    text_buffer += text
                    content[text_index] = TextContent(text=text_buffer)
                    yield TextDeltaEvent(
                        content_index=text_index, delta=text, partial=snapshot(content)
                    )

                raw_calls = getattr(chunk, "tool_calls", None)
                if raw_calls:
                    tool_calls.add(list(raw_calls))

                chunk_usage = getattr(chunk, "usage", None)
                chunk_cost = getattr(chunk, "cost", None)
                if chunk_usage is not None or chunk_cost is not None:
                    usage = _usage(chunk_usage, chunk_cost)

                if getattr(chunk, "finish_reason", None):
                    finish_reason = chunk.finish_reason

        except Exception as error:  # noqa: BLE001 - the contract forbids raising
            failed = snapshot(content, "error")
            failed.error_message = str(error) or error.__class__.__name__
            failed.usage = usage
            yield AssistantErrorEvent(reason="error", error=failed)
            return

        if thinking_index is not None and thinking_buffer:
            yield ThinkingEndEvent(
                content_index=thinking_index,
                content=thinking_buffer,
                partial=snapshot(content),
            )
        if text_index is not None:
            yield TextEndEvent(
                content_index=text_index, content=text_buffer, partial=snapshot(content)
            )

        for call in tool_calls.build():
            index = len(content)
            content.append(call)
            yield ToolCallStartEvent(content_index=index, partial=snapshot(content))
            yield ToolCallEndEvent(content_index=index, tool_call=call, partial=snapshot(content))

        stop_reason = map_stop_reason(finish_reason, has_tool_calls=not tool_calls.empty)
        final = snapshot(content, stop_reason)
        final.usage = usage
        yield AssistantDoneEvent(reason=stop_reason, message=final)  # type: ignore[arg-type]


def create_gateway_stream(gateway: Any | None = None) -> GatewayStream:
    """Build the default stream function for PiPy."""
    return GatewayStream(gateway)


__all__ = ["GatewayStream", "create_gateway_stream", "map_stop_reason"]
