"""Real loopback transport regressions: first output must precede model completion."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from superqode.providers.gateway.base import Message
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


@pytest.fixture
def streaming_server(monkeypatch):
    first = threading.Event()
    finish = threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(request)
            self.send_response(200)
            streaming = request.get("stream") is True and request.get("model") != "legacy"
            self.send_header(
                "Content-Type", "text/event-stream" if streaming else "application/json"
            )
            self.end_headers()
            if streaming:
                self.wfile.write(
                    b'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"Hello "},"finish_reason":null}]}\n\n'
                )
                self.wfile.flush()
            first.set()
            if request.get("model") == "disconnect":
                return
            if request.get("model") == "cancel":
                self.connection.settimeout(2)
                request["client_closed"] = self.rfile.read(1) == b""
                return
            finish.wait(5)
            try:
                if streaming:
                    self.wfile.write(
                        b'data: {"choices":[{"index":0,"delta":{"content":"assistant"},"finish_reason":null}]}\n\n'
                    )
                    self.wfile.write(
                        b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}\n\ndata: [DONE]\n\n'
                    )
                else:
                    self.wfile.write(
                        json.dumps(
                            {
                                "choices": [
                                    {
                                        "message": {
                                            "role": "assistant",
                                            "content": "Hello assistant",
                                        },
                                        "finish_reason": "stop",
                                    }
                                ]
                            }
                        ).encode()
                    )
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("MLX_HOST", f"http://127.0.0.1:{server.server_port}")
    try:
        yield first, finish, requests
    finally:
        finish.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_mlx_delivers_text_before_generation_finishes(streaming_server):
    first, finish, requests = streaming_server
    chunks = LiteLLMGateway().stream_completion(
        messages=[Message(role="user", content="Hello")], provider="mlx", model="fixture"
    )
    pending = asyncio.create_task(anext(chunks))
    try:
        assert await asyncio.to_thread(first.wait, 2), "The model request did not arrive"
        chunk = await asyncio.wait_for(pending, 0.5)
        assert chunk.content == "Hello "
        assert not finish.is_set(), "First text must arrive while the model is still generating"
        finish.set()
        remaining = [chunk async for chunk in chunks]
        assert "".join([chunk.content, *(item.content for item in remaining)]) == "Hello assistant"
        assert remaining[-1].finish_reason == "stop"
        assert remaining[-1].usage.total_tokens == 6
        assert len(requests) == 1
        assert requests[0]["stream"] is True
    finally:
        finish.set()
        if not pending.done():
            pending.cancel()
        await chunks.aclose()


@pytest.mark.asyncio
async def test_context_probe_timeouts_do_not_stack(monkeypatch):
    from superqode.providers.local import context_probe

    active = 0
    peak = 0

    def stalled(_url, _timeout):
        import time

        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        time.sleep(0.05)
        active -= 1
        return None

    monkeypatch.setattr(context_probe, "_http_get_json", stalled)
    assert await context_probe.probe_base_url("http://127.0.0.1:1234", "fixture") is None
    assert peak > 1, (
        "Independent metadata timeouts must overlap rather than delaying inference serially"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", ["no-tool", "pipy"])
async def test_desktop_records_partial_local_response_while_model_is_running(
    streaming_server, tmp_path, harness
):
    import subprocess
    import time
    from superqode.desktop_service.service import DesktopService

    first, finish, requests = streaming_server
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    service = DesktopService(tmp_path / "state")
    try:
        project = service.open_project(str(root))
        job = service.dispatch(
            "tasks.start",
            {
                "project": project["id"],
                "harness": harness,
                "provider": "mlx",
                "model": "fixture",
                "prompt": "Hello",
            },
        )
        assert await asyncio.to_thread(first.wait, 20), "The desktop did not send its model request"
        partial = None
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            partial = service.dispatch("jobs.get", {"id": job["id"]})
            if any(
                event.get("type") == "harness_event"
                and event.get("data", {}).get("event") == "model_delta"
                and "Hello" in str(event.get("data", {}).get("payload", {}))
                for event in partial["events"]
            ):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("The Mac engine buffered the response instead of recording live text")
        assert partial["status"] == "running"
        assert not finish.is_set()
        finish.set()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            complete = service.dispatch("jobs.get", {"id": job["id"]})
            if complete["status"] not in {"running", "needs_approval"}:
                break
            await asyncio.sleep(0.05)
        assert complete["status"] == "completed", complete
        assert len(requests) == 1
    finally:
        finish.set()
        service.close()


@pytest.mark.asyncio
async def test_known_local_provider_avoids_unrelated_metadata_endpoints(monkeypatch):
    from superqode.providers.local import context_probe

    seen = []

    def metadata(url, _timeout):
        seen.append(url)
        return {"models": [{"name": "fixture", "context_length": 4096}]}

    monkeypatch.setattr(context_probe, "_http_get_json", metadata)
    assert await context_probe.probe_base_url(
        "http://localhost:11434", "fixture", provider="ollama"
    ) == (4096, "/api/ps")
    assert seen == ["http://localhost:11434/api/ps"]


@pytest.mark.asyncio
async def test_mlx_interrupted_stream_is_not_replayed(streaming_server):
    from superqode.providers.gateway.base import GatewayError

    _, finish, requests = streaming_server
    chunks = LiteLLMGateway().stream_completion(
        messages=[Message(role="user", content="Hello")], provider="mlx", model="disconnect"
    )
    assert (await anext(chunks)).content == "Hello "
    with pytest.raises(GatewayError, match="not replayed"):
        await anext(chunks)
    finish.set()
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_mlx_legacy_json_response_does_not_trigger_second_request(streaming_server):
    _, finish, requests = streaming_server
    finish.set()
    chunks = [
        chunk
        async for chunk in LiteLLMGateway().stream_completion(
            messages=[Message(role="user", content="Hello")], provider="mlx", model="legacy"
        )
    ]
    assert "".join(chunk.content for chunk in chunks) == "Hello assistant"
    assert chunks[-1].finish_reason == "stop"
    assert len(requests) == 1
    assert requests[0]["stream"] is True


@pytest.mark.asyncio
async def test_mlx_timeout_after_partial_text_does_not_repeat_generation(streaming_server):
    from superqode.providers.gateway.base import GatewayError

    _, finish, requests = streaming_server
    stream = LiteLLMGateway(timeout=0.2).stream_completion(
        messages=[Message(role="user", content="Hello")], provider="mlx", model="fixture"
    )
    assert (await anext(stream)).content == "Hello "
    with pytest.raises(GatewayError, match="timed out"):
        await anext(stream)
    finish.set()
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["tool_calls", "length"])
async def test_mlx_fragmented_native_tools_wait_for_complete_arguments(monkeypatch, finish):
    from superqode.providers.local.mlx import MLXClient

    async def packets(self, endpoint, data, timeout):
        assert data["stream"] is True
        yield {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {"name": "read", "arguments": '{"path":'},
                            }
                        ]
                    }
                }
            ]
        }
        yield {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"arguments": '"file.py"}'}}]
                    },
                    "finish_reason": finish,
                }
            ]
        }
        yield {
            "choices": [],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        }

    monkeypatch.setattr(MLXClient, "_async_stream_request", packets)
    chunks = [
        chunk
        async for chunk in LiteLLMGateway().stream_completion(
            messages=[Message(role="user", content="read file")], provider="mlx", model="fixture"
        )
    ]
    assert len(chunks) == 1
    assert chunks[0].tool_calls[0]["id"] == "call-1"
    assert json.loads(chunks[0].tool_calls[0]["function"]["arguments"]) == {"path": "file.py"}
    assert chunks[0].finish_reason == finish
    assert chunks[0].usage.total_tokens == 12


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parts",
    [
        ["<tool_", 'call>{"name":"read","arguments":{"path":"x"}}', "</tool_call>"],
        ['```json\n{"name":"read",', '"arguments":{"path":"x"}}\n```'],
        ['{"name"', ':"read","arguments":{"path":"x"}}'],
    ],
)
async def test_mlx_inline_tool_fragments_remain_hidden_until_complete(monkeypatch, parts):
    from superqode.providers.local.mlx import MLXClient

    async def packets(self, endpoint, data, timeout):
        for content in parts:
            yield {"choices": [{"delta": {"content": content}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {}}

    monkeypatch.setattr(MLXClient, "_async_stream_request", packets)
    chunks = [
        chunk
        async for chunk in LiteLLMGateway().stream_completion(
            messages=[Message(role="user", content="read file")], provider="mlx", model="fixture"
        )
    ]
    assert "".join(chunk.content for chunk in chunks) == ""
    assert chunks[-1].finish_reason == "tool_calls"
    assert chunks[-1].tool_calls[0]["function"]["name"] == "read"
    assert chunks[-1].usage is None


@pytest.mark.asyncio
async def test_context_probe_preserves_loaded_window_precedence(monkeypatch):
    import time
    from superqode.providers.local import context_probe

    def metadata(url, _timeout):
        if url.endswith("/api/ps"):
            time.sleep(0.04)
            return {"models": [{"name": "fixture", "context_length": 4096}]}
        return {"data": [{"id": "fixture", "max_model_len": 131072}]}

    monkeypatch.setattr(context_probe, "_http_get_json", metadata)
    assert await context_probe.probe_base_url("http://localhost:1234", "fixture") == (
        4096,
        "/api/ps",
    )


@pytest.mark.asyncio
async def test_context_probe_does_not_cache_a_window_after_model_reload(monkeypatch):
    from superqode.providers.local import context_probe

    window = 8192

    def metadata(_url, _timeout):
        return {"models": [{"name": "fixture", "context_length": window}]}

    monkeypatch.setattr(context_probe, "_http_get_json", metadata)
    assert (
        await context_probe.probe_base_url("http://localhost:11434", "fixture", provider="ollama")
    )[0] == 8192
    window = 2048
    assert (
        await context_probe.probe_base_url("http://localhost:11434", "fixture", provider="ollama")
    )[0] == 2048


@pytest.mark.asyncio
async def test_closing_mlx_stream_closes_transport_without_waiting_for_generation(streaming_server):
    import time

    _, finish, requests = streaming_server
    stream = LiteLLMGateway().stream_completion(
        messages=[Message(role="user", content="Hello")], provider="mlx", model="cancel"
    )
    assert (await anext(stream)).content == "Hello "
    await asyncio.wait_for(stream.aclose(), 0.5)
    deadline = time.monotonic() + 1
    while not requests[0].get("client_closed") and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert requests[0].get("client_closed")
    assert not finish.is_set()
    assert len(requests) == 1
