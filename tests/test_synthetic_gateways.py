"""Tests for the synthetic gateways (passthrough / playback / silent).

These gateways implement GatewayInterface without making real network calls,
so the harness can be exercised deterministically in CI.
"""

from __future__ import annotations

import json

import pytest

from superqode.providers.gateway import (
    CALL_TOOL_INDICATOR,
    FIXED_RESPONSE_INDICATOR,
    GatewayFactory,
    Message,
    PassthroughGateway,
    PlaybackGateway,
    SilentGateway,
)


# ---------------------------------------------------------------------------
# Factory registration
# ---------------------------------------------------------------------------


def test_factory_registers_synthetic_gateways():
    for name, cls in (
        ("passthrough", PassthroughGateway),
        ("playback", PlaybackGateway),
        ("silent", SilentGateway),
    ):
        gw = GatewayFactory.create(name)
        assert isinstance(gw, cls)


# ---------------------------------------------------------------------------
# PassthroughGateway
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passthrough_echoes_last_user_message():
    gw = PassthroughGateway()
    messages = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="ignored"),
        Message(role="user", content="how are you"),
    ]
    response = await gw.chat_completion(messages=messages, model="passthrough")
    assert response.content == "how are you"
    assert response.role == "assistant"
    assert response.finish_reason == "stop"
    assert response.tool_calls is None
    assert response.usage is not None
    assert response.usage.completion_tokens > 0


@pytest.mark.asyncio
async def test_passthrough_concatenates_trailing_user_messages():
    gw = PassthroughGateway()
    messages = [
        Message(role="user", content="first"),
        Message(role="user", content="second"),
    ]
    response = await gw.chat_completion(messages=messages, model="passthrough")
    assert response.content == "first\nsecond"


@pytest.mark.asyncio
async def test_passthrough_fixed_response_is_sticky():
    gw = PassthroughGateway()
    await gw.chat_completion(
        messages=[Message(role="user", content=f"{FIXED_RESPONSE_INDICATOR} pinned")],
        model="passthrough",
    )
    # Subsequent turns return the pinned response regardless of input.
    response = await gw.chat_completion(
        messages=[Message(role="user", content="anything")],
        model="passthrough",
    )
    assert response.content == "pinned"


@pytest.mark.asyncio
async def test_passthrough_call_tool_indicator():
    gw = PassthroughGateway()
    args = {"path": "src/foo.py"}
    user_msg = f'{CALL_TOOL_INDICATOR} read_file {json.dumps(args)}'
    response = await gw.chat_completion(
        messages=[Message(role="user", content=user_msg)],
        model="passthrough",
    )
    assert response.finish_reason == "tool_calls"
    assert response.content == ""
    assert response.tool_calls and len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call["function"]["name"] == "read_file"
    assert json.loads(call["function"]["arguments"]) == args


@pytest.mark.asyncio
async def test_passthrough_call_tool_without_args():
    gw = PassthroughGateway()
    response = await gw.chat_completion(
        messages=[Message(role="user", content=f"{CALL_TOOL_INDICATOR} list_files")],
        model="passthrough",
    )
    call = response.tool_calls[0]
    assert call["function"]["name"] == "list_files"
    assert json.loads(call["function"]["arguments"]) == {}


@pytest.mark.asyncio
async def test_passthrough_stream_yields_content_then_finish():
    gw = PassthroughGateway()
    chunks = []
    async for chunk in await _to_async_iter(
        gw.stream_completion(
            messages=[Message(role="user", content="streamed")],
            model="passthrough",
        )
    ):
        chunks.append(chunk)
    # one content chunk + one finish/usage chunk
    assert any(c.content == "streamed" for c in chunks)
    assert any(c.finish_reason == "stop" for c in chunks)


@pytest.mark.asyncio
async def test_passthrough_reset_clears_fixed_response():
    gw = PassthroughGateway()
    await gw.chat_completion(
        messages=[Message(role="user", content=f"{FIXED_RESPONSE_INDICATOR} pinned")],
        model="passthrough",
    )
    gw.reset()
    response = await gw.chat_completion(
        messages=[Message(role="user", content="back to echo")],
        model="passthrough",
    )
    assert response.content == "back to echo"


# ---------------------------------------------------------------------------
# PlaybackGateway
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_playback_replays_queue_in_order():
    gw = PlaybackGateway()
    gw.queue("first", "second", "third")
    msgs = [Message(role="user", content="x")]
    assert (await gw.chat_completion(messages=msgs, model="playback")).content == "first"
    assert (await gw.chat_completion(messages=msgs, model="playback")).content == "second"
    assert (await gw.chat_completion(messages=msgs, model="playback")).content == "third"


@pytest.mark.asyncio
async def test_playback_exhaustion_returns_sentinel():
    gw = PlaybackGateway()
    gw.queue("only")
    msgs = [Message(role="user", content="x")]
    assert (await gw.chat_completion(messages=msgs, model="playback")).content == "only"
    overflow = await gw.chat_completion(messages=msgs, model="playback")
    assert "EXHAUSTED" in overflow.content
    second_overflow = await gw.chat_completion(messages=msgs, model="playback")
    assert "2 overage" in second_overflow.content


@pytest.mark.asyncio
async def test_playback_tool_call_queue():
    gw = PlaybackGateway()
    gw.queue_tool_call("write_file", {"path": "x.py", "content": "y"})
    response = await gw.chat_completion(
        messages=[Message(role="user", content="x")], model="playback"
    )
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0]["function"]["name"] == "write_file"


def test_playback_reset_and_remaining():
    gw = PlaybackGateway()
    gw.queue("a", "b")
    assert gw.remaining == 2
    gw.reset()
    assert gw.remaining == 0


# ---------------------------------------------------------------------------
# SilentGateway
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_silent_reports_zero_usage_but_still_echoes():
    gw = SilentGateway()
    response = await gw.chat_completion(
        messages=[Message(role="user", content="hi")], model="silent"
    )
    assert response.content == "hi"
    assert response.usage.prompt_tokens == 0
    assert response.usage.completion_tokens == 0
    assert response.usage.total_tokens == 0
    assert response.cost.total_cost == 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _to_async_iter(awaitable_or_iter):
    """Resolve `stream_completion` whether it's already a generator or awaited."""
    result = awaitable_or_iter
    if hasattr(result, "__await__"):
        result = await result
    return result
