"""Deterministic stream function for PiPy tests and offline runs.

Replays scripted assistant messages as pi-compatible assistant events, so loop
and harness tests never touch a network.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from ..messages import AssistantMessage, TextContent, ThinkingContent, ToolCall
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

Script = Sequence["AssistantMessage | str"]


class FakeStream:
    """A :class:`~superqode.pipy.stream.StreamFn` that replays a script.

    Each call consumes the next scripted response. Running past the end of the
    script yields an empty ``stop`` message, which ends a loop cleanly rather
    than hanging it.
    """

    def __init__(self, responses: Script = ()) -> None:
        self._responses = list(responses)
        self.index = 0
        self.calls: list[Context] = []

    def __call__(
        self,
        model: Model,
        context: Context,
        options: StreamOptions,
    ) -> AsyncIterator[AssistantMessageEvent]:
        self.calls.append(context)
        return self._stream(model, options)

    async def _stream(
        self,
        model: Model,
        options: StreamOptions,
    ) -> AsyncIterator[AssistantMessageEvent]:
        if is_aborted(options.signal):
            aborted = _message(model, [], "aborted", error_message="Operation aborted")
            yield AssistantStartEvent(partial=_message(model, [], "aborted"))
            yield AssistantErrorEvent(reason="aborted", error=aborted)
            return

        if self.index >= len(self._responses):
            final = _message(model, [], "stop")
        else:
            final = _normalize(self._responses[self.index], model)
            self.index += 1

        if final.stop_reason in ("error", "aborted"):
            yield AssistantStartEvent(partial=_message(model, [], final.stop_reason))
            yield AssistantErrorEvent(reason=final.stop_reason, error=final)
            return

        partial = _message(model, [], final.stop_reason)
        yield AssistantStartEvent(partial=partial)

        for index, block in enumerate(final.content):
            if isinstance(block, TextContent):
                partial = _message(model, [*partial.content, TextContent(text="")], "stop")
                yield TextStartEvent(content_index=index, partial=partial)
                partial = _message(model, [*partial.content[:-1], block], "stop")
                yield TextDeltaEvent(content_index=index, delta=block.text, partial=partial)
                yield TextEndEvent(content_index=index, content=block.text, partial=partial)
            elif isinstance(block, ThinkingContent):
                partial = _message(model, [*partial.content, ThinkingContent(thinking="")], "stop")
                yield ThinkingStartEvent(content_index=index, partial=partial)
                partial = _message(model, [*partial.content[:-1], block], "stop")
                yield ThinkingDeltaEvent(content_index=index, delta=block.thinking, partial=partial)
                yield ThinkingEndEvent(content_index=index, content=block.thinking, partial=partial)
            elif isinstance(block, ToolCall):
                partial = _message(model, [*partial.content, block], "stop")
                yield ToolCallStartEvent(content_index=index, partial=partial)
                yield ToolCallEndEvent(content_index=index, tool_call=block, partial=partial)

        yield AssistantDoneEvent(reason=final.stop_reason, message=final)


def _message(
    model: Model,
    content: list,
    stop_reason: str,
    *,
    error_message: str | None = None,
) -> AssistantMessage:
    return AssistantMessage(
        content=list(content),
        api=model.api,
        provider=model.provider,
        model=model.id,
        stop_reason=stop_reason,  # type: ignore[arg-type]
        error_message=error_message,
    )


def _normalize(response: AssistantMessage | str, model: Model) -> AssistantMessage:
    if isinstance(response, str):
        return _message(model, [TextContent(text=response)], "stop")
    if not response.model or response.model == "unknown":
        response.model = model.id
    if not response.provider or response.provider == "unknown":
        response.provider = model.provider
    if not response.api or response.api == "unknown":
        response.api = model.api
    return response


def text_response(text: str) -> AssistantMessage:
    """Build a plain text assistant message for a script."""
    return AssistantMessage(content=[TextContent(text=text)], stop_reason="stop")


def tool_response(
    *calls: ToolCall, text: str = "", stop_reason: str = "toolUse"
) -> AssistantMessage:
    """Build an assistant message that requests tool calls."""
    content: list = [TextContent(text=text)] if text else []
    content.extend(calls)
    return AssistantMessage(content=content, stop_reason=stop_reason)  # type: ignore[arg-type]


__all__ = ["FakeStream", "text_response", "tool_response"]
