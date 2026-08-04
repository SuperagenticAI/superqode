"""Steering and follow-up queue parity with pi (checklist L3, L4)."""

from __future__ import annotations

from conftest import call, config, context, echo_tool

from superqode.pipy import UserMessage, run_agent_loop
from superqode.pipy.ai import FakeStream, text_response, tool_response


def draining(*batches):
    """A queue getter that returns each batch once, then nothing."""
    queue = [list(batch) for batch in batches]

    def get():
        return queue.pop(0) if queue else []

    return get


async def test_steering_polled_before_the_first_turn(model, recorder):
    """L3: a message typed while the previous run finished is injected first."""
    stream = FakeStream([text_response("ok")])

    await run_agent_loop(
        [UserMessage(content="prompt")],
        context(),
        config(model, get_steering_messages=draining([UserMessage(content="steered")])),
        recorder,
        None,
        stream,
    )

    sent = [message.text for message in stream.calls[0].messages]
    assert sent == ["prompt", "steered"]
    starts = [event.message.text for event in recorder.of_type("message_start")]
    assert starts[:2] == ["prompt", "steered"]


async def test_steering_injected_between_turns(model, recorder):
    script = [tool_response(call("echo", value="x")), text_response("after steer")]
    stream = FakeStream(script)

    await run_agent_loop(
        [UserMessage(content="prompt")],
        context(tools=[echo_tool()]),
        config(model, get_steering_messages=draining([], [UserMessage(content="mid-run")])),
        recorder,
        None,
        stream,
    )

    second_turn = [message.text for message in stream.calls[1].messages]
    assert second_turn[-1] == "mid-run"


async def test_steering_keeps_the_loop_running_without_tool_calls(model, recorder):
    """A steering message alone is enough for another turn."""
    stream = FakeStream([text_response("first"), text_response("second")])

    await run_agent_loop(
        [UserMessage(content="prompt")],
        context(),
        config(model, get_steering_messages=draining([], [UserMessage(content="more")])),
        recorder,
        None,
        stream,
    )

    assert stream.index == 2
    assert recorder.types.count("turn_start") == 2


async def test_follow_up_drains_only_when_the_agent_would_stop(model, recorder):
    """L4: follow-ups wait for the tool phase to finish."""
    follow_ups = draining([UserMessage(content="follow up")])
    script = [
        tool_response(call("echo", value="x")),
        text_response("tools done"),
        text_response("after follow up"),
    ]
    stream = FakeStream(script)

    await run_agent_loop(
        [UserMessage(content="prompt")],
        context(tools=[echo_tool()]),
        config(model, get_follow_up_messages=follow_ups),
        recorder,
        None,
        stream,
    )

    assert stream.index == 3
    # Injected only once the second turn had no tool calls left.
    assert [message.text for message in stream.calls[2].messages][-1] == "follow up"


async def test_follow_up_empty_ends_the_run(model, recorder):
    stream = FakeStream([text_response("only turn")])

    await run_agent_loop(
        [UserMessage(content="prompt")],
        context(),
        config(model, get_follow_up_messages=lambda: []),
        recorder,
        None,
        stream,
    )

    assert recorder.types[-1] == "agent_end"
    assert stream.index == 1


async def test_queued_messages_appear_in_the_returned_messages(model, recorder):
    stream = FakeStream([text_response("first"), text_response("second")])

    messages = await run_agent_loop(
        [UserMessage(content="prompt")],
        context(),
        config(model, get_follow_up_messages=draining([UserMessage(content="queued")])),
        recorder,
        None,
        stream,
    )

    texts = [message.text for message in messages]
    assert texts == ["prompt", "first", "queued", "second"]
