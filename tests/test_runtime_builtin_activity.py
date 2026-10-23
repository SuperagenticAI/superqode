"""Activity must reach the client while a tool is still running, without text tokens."""

import asyncio
from types import SimpleNamespace

import pytest

from superqode.runtime.builtin import BuiltinRuntime


@pytest.mark.asyncio
async def test_tool_start_is_delivered_before_tool_finishes_and_close_cleans_up():
    finished = asyncio.Event()
    cancelled = asyncio.Event()

    async def streaming(prompt, **kwargs):
        loop.on_tool_call("bash", {"command": "sleep 10"})
        try:
            await finished.wait()
            yield "done"
        finally:
            cancelled.set()

    loop = SimpleNamespace(on_tool_call=None, on_tool_result=None, on_thinking=None)
    loop.run_streaming = streaming
    runtime = object.__new__(BuiltinRuntime)
    runtime._loop = loop
    stream = runtime.run_harness_events("work")
    assert (await anext(stream)).type == "model_request"
    event = await asyncio.wait_for(anext(stream), 1)
    assert event.type == "tool_call"
    assert event.data["arguments"]["command"] == "sleep 10"
    assert not finished.is_set()
    await stream.aclose()
    assert cancelled.is_set()
    assert loop.on_tool_call is None
    assert loop.on_tool_result is None
    assert loop.on_thinking is None


@pytest.mark.asyncio
async def test_runtime_failure_is_not_hidden_by_activity_stream():
    async def streaming(prompt, **kwargs):
        await loop.on_thinking("checking")
        raise RuntimeError("fixture failure")
        yield  # make this an async generator

    loop = SimpleNamespace(on_tool_call=None, on_tool_result=None, on_thinking=None)
    loop.run_streaming = streaming
    runtime = object.__new__(BuiltinRuntime)
    runtime._loop = loop
    stream = runtime.run_harness_events("work")
    assert (await anext(stream)).type == "model_request"
    assert (await anext(stream)).type == "thinking"
    with pytest.raises(RuntimeError, match="fixture failure"):
        await anext(stream)
    assert loop.on_thinking is None
