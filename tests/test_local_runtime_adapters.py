"""Local compatible endpoints must stay local and preserve stream contracts."""

import asyncio
import json

import httpx
import pytest

from superqode.local import runtimes
from superqode.providers.gateway.base import Message, ToolDefinition


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "http://192.168.1.2:8000/v1",
        "http://0.0.0.0:8000/v1",
        "http://user:key@127.0.0.1/v1",
        "http://127.0.0.1/v1?key=secret",
        "http://127.0.0.1/v1#secret",
        "file:///tmp/server",
        "http://127.0.0.1:8000/v1/chat/completions",
    ],
)
def test_remote_hosts_and_embedded_credentials_are_rejected(url):
    with pytest.raises(ValueError):
        runtimes.loopback_url(url)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8000/v1", "http://localhost:1337/v1", "http://[::1]:8000/v1"]
)
def test_explicit_loopback_endpoints_work(url):
    assert runtimes.loopback_url(url + "/") == url


@pytest.mark.asyncio
async def test_discovery_never_follows_a_redirect_with_the_local_key():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com/capture"})

    spec = runtimes.validate({"id": "test", "name": "Test", "endpoint": "http://127.0.0.1:8000/v1"})
    with pytest.raises(ValueError, match="redirect"):
        await runtimes.models(spec, "private-local-key", transport=httpx.MockTransport(respond))
    assert len(requests) == 1
    assert requests[0].url.host == "127.0.0.1"


@pytest.mark.asyncio
async def test_context_trimming_is_applied_to_the_actual_request_and_json_is_not_replayed():
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    spec = runtimes.validate(
        {"id": "test", "endpoint": "http://127.0.0.1:8000/v1", "context": 2048}
    )
    chunks = [
        chunk
        async for chunk in runtimes.stream(
            spec,
            [
                Message("user", "old " * 1800),
                Message("assistant", "old answer"),
                Message("user", "Hello"),
            ],
            "fixture",
            transport=httpx.MockTransport(respond),
        )
    ]
    assert "".join(c.content for c in chunks) == "Hello"
    assert len(bodies) == 1
    assert bodies[0]["messages"] == [{"role": "user", "content": "Hello"}]
    assert chunks[-1].usage.total_tokens == 3


class Paused(httpx.AsyncByteStream):
    def __init__(self):
        self.release = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
        await self.release.wait()
        yield b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"r","function":{"name":"read_probe","arguments":"{\\"path\\":\\"fixture\\"}"}}]},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}\n\n'

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_generic_adapter_streams_text_and_waits_for_valid_tool_arguments():
    wire = Paused()
    spec = runtimes.validate({"id": "test", "endpoint": "http://127.0.0.1:8000/v1"})
    events = runtimes.stream(
        spec,
        [Message("user", "Hello")],
        "fixture",
        tools=[ToolDefinition("read_probe", "Read", {"type": "object"})],
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=wire
            )
        ),
    )
    try:
        first = await asyncio.wait_for(anext(events), 1)
        assert first.content == "Hello " and first.tool_calls is None and not wire.release.is_set()
        wire.release.set()
        rest = [chunk async for chunk in events]
        assert rest[-1].tool_calls[0]["function"]["arguments"] == '{"path":"fixture"}'
        assert rest[-1].finish_reason == "tool_calls" and wire.closed
    finally:
        wire.release.set()
        await events.aclose()
