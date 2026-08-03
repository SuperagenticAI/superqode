"""Event lifecycle parity with pi's agent loop (checklist L1, L2, L5, L21)."""

from __future__ import annotations

import pytest
from conftest import EventRecorder, call, config, context, echo_tool

from superqode.pipy import (
    AssistantMessage,
    TextContent,
    ToolResultMessage,
    UserMessage,
    agent_loop,
    run_agent_loop,
    run_agent_loop_continue,
)
from superqode.pipy.ai import FakeStream, text_response, tool_response


async def test_prompt_event_order(model, recorder):
    stream = FakeStream([text_response("hello")])
    prompt = UserMessage(content="hi")

    messages = await run_agent_loop([prompt], context(), config(model), recorder, None, stream)

    assert recorder.types == [
        "agent_start",
        "turn_start",
        "message_start",
        "message_end",
        "message_start",
        "message_update",
        "message_update",
        "message_update",
        "message_end",
        "turn_end",
        "agent_end",
    ]
    assert messages[0] is prompt
    assert isinstance(messages[-1], AssistantMessage)
    assert messages[-1].text == "hello"


async def test_prompt_messages_appended_to_context(model, recorder):
    ctx = context(messages=[UserMessage(content="earlier")])
    stream = FakeStream([text_response("ok")])

    await run_agent_loop([UserMessage(content="hi")], ctx, config(model), recorder, None, stream)

    # pi copies the context, so the caller's list is untouched by the run.
    assert len(ctx.messages) == 1
    assert stream.calls[0].messages[0].text == "earlier"
    assert stream.calls[0].messages[1].text == "hi"


async def test_continue_runs_without_a_new_prompt(model, recorder):
    ctx = context(messages=[UserMessage(content="already here")])
    stream = FakeStream([text_response("continued")])

    messages = await run_agent_loop_continue(ctx, config(model), recorder, None, stream)

    assert recorder.types[:2] == ["agent_start", "turn_start"]
    # No prompt message events, and only the assistant message is new.
    assert len(messages) == 1
    assert messages[0].text == "continued"


async def test_continue_rejects_empty_context(model, recorder):
    with pytest.raises(ValueError, match="no messages in context"):
        await run_agent_loop_continue(context(), config(model), recorder, None, FakeStream())


async def test_continue_rejects_assistant_tail(model, recorder):
    ctx = context(messages=[AssistantMessage(content=[TextContent(text="hi")])])

    with pytest.raises(ValueError, match="Cannot continue from message role: assistant"):
        await run_agent_loop_continue(ctx, config(model), recorder, None, FakeStream())


async def test_continue_accepts_tool_result_tail(model, recorder):
    ctx = context(
        messages=[
            UserMessage(content="hi"),
            ToolResultMessage(tool_call_id="c1", tool_name="echo", content="done"),
        ]
    )
    stream = FakeStream([text_response("after tool")])

    messages = await run_agent_loop_continue(ctx, config(model), recorder, None, stream)

    assert messages[-1].text == "after tool"


@pytest.mark.parametrize("stop_reason", ["error", "aborted"])
async def test_error_stop_reason_ends_run(model, recorder, stop_reason):
    failure = AssistantMessage(content=[], stop_reason=stop_reason, error_message="boom")
    stream = FakeStream([failure, text_response("never reached")])

    await run_agent_loop(
        [UserMessage(content="hi")], context(), config(model), recorder, None, stream
    )

    assert recorder.types[-2:] == ["turn_end", "agent_end"]
    assert recorder.of_type("turn_end")[0].tool_results == []
    # The second scripted response must not have been consumed.
    assert stream.index == 1


async def test_partial_message_replaced_in_place(model, recorder):
    """L21: the streaming partial is swapped for the final, never appended twice."""
    script = [tool_response(call("echo", value="x")), text_response("second turn")]
    stream = FakeStream(script)

    await run_agent_loop(
        [UserMessage(content="hi")],
        context(tools=[echo_tool()]),
        config(model),
        recorder,
        None,
        stream,
    )

    # The second provider call must see exactly one assistant message from the
    # first turn: the final one, not a leftover partial alongside it.
    assistants = [m for m in stream.calls[1].messages if isinstance(m, AssistantMessage)]
    assert len(assistants) == 1
    assert assistants[0].tool_calls


async def test_transform_context_sees_the_live_partial(model, recorder):
    """The partial is visible in context while streaming, as in pi."""
    snapshots: list[int] = []

    async def transform(messages, signal):
        snapshots.append(len(messages))
        return messages

    script = [tool_response(call("echo", value="x")), text_response("done")]
    stream = FakeStream(script)

    await run_agent_loop(
        [UserMessage(content="hi")],
        context(tools=[echo_tool()]),
        config(model, transform_context=transform),
        recorder,
        None,
        stream,
    )

    # Turn 1 sees the prompt. Turn 2 sees prompt, final assistant, tool result.
    assert snapshots == [1, 3]


async def test_agent_loop_returns_a_consumable_stream(model):
    stream = FakeStream([text_response("via stream")])

    events = agent_loop([UserMessage(content="hi")], context(), config(model), None, stream)

    collected = [event.type async for event in events]
    assert collected[0] == "agent_start"
    assert collected[-1] == "agent_end"

    messages = await events.result()
    assert messages[-1].text == "via stream"


async def test_async_event_sink_is_awaited(model):
    recorder = EventRecorder()
    stream = FakeStream([text_response("ok")])

    await run_agent_loop(
        [UserMessage(content="hi")], context(), config(model), recorder.async_sink, None, stream
    )

    assert recorder.types[0] == "agent_start"
    assert recorder.types[-1] == "agent_end"


async def test_missing_terminal_event_becomes_an_error_message(model, recorder):
    async def broken_stream(model_arg, context_arg, options):
        return _empty()

    async def _empty():
        return
        yield  # pragma: no cover - makes this an async generator

    await run_agent_loop(
        [UserMessage(content="hi")], context(), config(model), recorder, None, broken_stream
    )

    final = recorder.of_type("message_end")[-1].message
    assert final.stop_reason == "error"
    assert "terminal done or error event" in (final.error_message or "")
