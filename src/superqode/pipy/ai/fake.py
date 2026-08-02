"""Deterministic fake provider for PiPy tests and offline runs."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from ..messages import AgentMessage, AssistantMessage, TextContent, ToolCall, assistant_content
from ..provider import CancellationToken
from ..provider_events import (
    AssistantDoneEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from ..tools_base import AgentTool


class FakeProvider:
    """Replay a scripted list of assistant messages as Pi stream events."""

    def __init__(self, responses: Sequence[AssistantMessage | str | dict]) -> None:
        self._responses = list(responses)
        self._index = 0

    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationToken | None = None,
    ) -> AsyncIterator[AssistantMessageEvent]:
        del system, messages, tools
        return self._stream(model=model, signal=signal)

    async def _stream(
        self,
        *,
        model: str,
        signal: CancellationToken | None,
    ) -> AsyncIterator[AssistantMessageEvent]:
        if signal is not None and signal.is_cancelled():
            error = AssistantMessage(
                model=model,
                provider="fake",
                content=[],
                stop_reason="aborted",
                error_message="aborted",
            )
            yield AssistantStartEvent(partial=error)
            from ..provider_events import AssistantErrorEvent

            yield AssistantErrorEvent(reason="aborted", error=error)
            return

        if self._index >= len(self._responses):
            message = AssistantMessage(
                model=model,
                provider="fake",
                content=[TextContent(text="")],
                stop_reason="stop",
            )
        else:
            message = _normalize(self._responses[self._index], model=model)
            self._index += 1

        partial = AssistantMessage(
            model=message.model,
            provider=message.provider,
            api=message.api,
            content=[],
            stop_reason=message.stop_reason,
        )
        yield AssistantStartEvent(partial=partial)

        text_parts = [b for b in message.content if isinstance(b, TextContent)]
        tool_parts = [b for b in message.content if isinstance(b, ToolCall)]
        content_index = 0
        for block in text_parts:
            partial.content = list(partial.content) + [TextContent(text="")]
            yield TextStartEvent(content_index=content_index, partial=partial)
            partial.content[content_index] = TextContent(text=block.text)
            if block.text:
                yield TextDeltaEvent(
                    content_index=content_index,
                    delta=block.text,
                    partial=partial,
                )
            yield TextEndEvent(
                content_index=content_index,
                content=block.text,
                partial=partial,
            )
            content_index += 1

        for call in tool_parts:
            partial.content = list(partial.content) + [call]
            yield ToolCallStartEvent(content_index=content_index, partial=partial)
            yield ToolCallEndEvent(
                content_index=content_index,
                tool_call=call,
                partial=partial,
            )
            content_index += 1

        final = AssistantMessage(
            model=message.model,
            provider=message.provider,
            api=message.api,
            content=list(message.content),
            usage=message.usage,
            stop_reason=message.stop_reason,
            error_message=message.error_message,
        )
        reason = (
            "toolUse"
            if final.tool_calls
            else ("length" if final.stop_reason == "length" else "stop")
        )
        if final.stop_reason in {"error", "aborted"}:
            from ..provider_events import AssistantErrorEvent

            yield AssistantErrorEvent(
                reason="error" if final.stop_reason == "error" else "aborted",
                error=final,
            )
            return
        yield AssistantDoneEvent(reason=reason, message=final)  # type: ignore[arg-type]


def _normalize(item: AssistantMessage | str | dict, *, model: str) -> AssistantMessage:
    if isinstance(item, AssistantMessage):
        if item.model == "unknown":
            item.model = model
        if item.provider == "unknown":
            item.provider = "fake"
        return item
    if isinstance(item, str):
        return AssistantMessage(
            model=model,
            provider="fake",
            content=[TextContent(text=item)],
            stop_reason="stop",
        )
    text = str(item.get("text") or "")
    calls_raw = item.get("tool_calls") or item.get("toolCalls") or []
    calls: list[ToolCall] = []
    for raw in calls_raw:
        if isinstance(raw, ToolCall):
            calls.append(raw)
            continue
        calls.append(
            ToolCall(
                id=str(raw.get("id") or f"call_{len(calls)}"),
                name=str(raw.get("name") or "unknown"),
                arguments=dict(raw.get("arguments") or {}),
            )
        )
    stop = str(item.get("stop_reason") or item.get("stopReason") or "stop")
    return AssistantMessage(
        model=str(item.get("model") or model),
        provider=str(item.get("provider") or "fake"),
        content=assistant_content(text, calls),
        stop_reason=stop,  # type: ignore[arg-type]
        error_message=item.get("error_message") or item.get("errorMessage"),
    )
