"""Repairs applied on the way to a provider, and nowhere else.

Ported from ``packages/ai/src/api/transform-messages.ts`` of earendil-works/pi
(MIT).

The session tree records what actually happened, including turns that failed
half way and tool calls that never got a result. Those transcripts are true but
not always legal input for a provider, so the repair happens here, at the
boundary, leaving history untouched.
"""

from __future__ import annotations

from ..messages import (
    AssistantMessage,
    Message,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

#: What a tool call that never returned is reported as.
NO_RESULT_TEXT = "No result provided"


def transform_messages(messages: list[Message]) -> list[Message]:
    """Make a transcript safe to send.

    Three repairs, in one pass:

    - every tool call gets a result, synthesised if the run was interrupted
      before the tool finished (P1)
    - assistant turns that ended in ``error`` or ``aborted`` are dropped, since
      replaying a partial turn makes providers reject the whole request (P2)
    - assistant turns with no content at all are dropped, because an empty
      assistant message is not valid input anywhere (P3)
    """
    result: list[Message] = []
    pending_tool_calls: list[ToolCall] = []
    returned_ids: set[str] = set()

    def flush_synthetic() -> None:
        nonlocal pending_tool_calls, returned_ids
        if not pending_tool_calls:
            return
        for call in pending_tool_calls:
            if call.id in returned_ids:
                continue
            result.append(
                ToolResultMessage(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    content=[TextContent(text=NO_RESULT_TEXT)],
                    is_error=True,
                )
            )
        pending_tool_calls = []
        returned_ids = set()

    for message in messages:
        if isinstance(message, AssistantMessage):
            flush_synthetic()
            if message.stop_reason in ("error", "aborted"):
                continue
            if not message.content:
                continue
            calls = list(message.tool_calls)
            if calls:
                pending_tool_calls = calls
                returned_ids = set()
            result.append(message)
        elif isinstance(message, ToolResultMessage):
            returned_ids.add(message.tool_call_id)
            result.append(message)
        elif isinstance(message, UserMessage):
            # A user message interrupts the tool flow, so anything still
            # outstanding has to be answered before it.
            flush_synthetic()
            result.append(message)
        else:
            result.append(message)

    flush_synthetic()
    return result


__all__ = ["NO_RESULT_TEXT", "transform_messages"]
