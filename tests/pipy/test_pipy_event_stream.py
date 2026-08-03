"""EventStream semantics used by the loop's stream entry points."""

from __future__ import annotations

import asyncio

import pytest

from superqode.pipy import EventStream


def make_stream() -> EventStream[dict, str]:
    return EventStream(lambda event: event["type"] == "end", lambda event: event["result"])


async def test_terminal_event_settles_the_result():
    stream = make_stream()
    stream.push({"type": "tick"})
    stream.push({"type": "end", "result": "done"})

    events = [event async for event in stream]

    assert [event["type"] for event in events] == ["tick", "end"]
    assert await stream.result() == "done"


async def test_pushes_after_the_end_are_ignored():
    stream = make_stream()
    stream.push({"type": "end", "result": "first"})
    stream.push({"type": "tick"})

    events = [event async for event in stream]

    assert len(events) == 1
    assert await stream.result() == "first"


async def test_explicit_end_without_a_terminal_event():
    stream = make_stream()
    stream.push({"type": "tick"})
    stream.end("manual")

    events = [event async for event in stream]

    assert [event["type"] for event in events] == ["tick"]
    assert await stream.result() == "manual"


async def test_failure_raises_to_iterators_and_awaiters():
    stream = make_stream()
    stream.push({"type": "tick"})
    stream.fail(RuntimeError("broken"))

    with pytest.raises(RuntimeError, match="broken"):
        async for _ in stream:
            pass

    with pytest.raises(RuntimeError, match="broken"):
        await stream.result()


async def test_consumer_can_await_before_the_producer_finishes():
    stream = make_stream()

    async def produce():
        await asyncio.sleep(0.01)
        stream.push({"type": "end", "result": "late"})

    task = asyncio.ensure_future(produce())
    assert await stream.result() == "late"
    await task
