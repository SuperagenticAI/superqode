"""Local CodeGem must display native streams before generation finishes."""

import asyncio
import json

import httpx
import pytest

from superqode.codegem import create_tools
from superqode.codegem.provider import CodeGemStream
from superqode.pipy.messages import UserMessage
from superqode.pipy.stream import Context, Model, StreamOptions


class PausedStream(httpx.AsyncByteStream):
    def __init__(self, protocol, chunks, *, pause=True):
        self.protocol = protocol
        self.chunks = chunks
        self.pause = pause
        self.release = asyncio.Event()
        self.closed = False

    def encode(self, payload):
        raw = json.dumps(payload)
        return (("data: " + raw + "\n\n") if self.protocol == "openai" else (raw + "\n")).encode()

    async def __aiter__(self):
        for index, payload in enumerate(self.chunks):
            yield self.encode(payload)
            if index == 0 and self.pause:
                await self.release.wait()
        if self.protocol == "openai":
            yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed = True


def frames(protocol, *, tools=False, complete=True):
    if protocol == "ollama":
        first = {"message": {"content": "Hello "}, "done": False}
        last = {
            "message": {"content": "assistant"},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 4,
            "eval_count": 2,
        }
        if tools:
            last["message"]["tool_calls"] = [
                {"id": "read-1", "function": {"name": "read", "arguments": {"path": "README.md"}}}
            ]
        return [first, *([last] if complete else [])]
    first = {"choices": [{"delta": {"content": "Hello "}, "finish_reason": None}]}
    last = {
        "choices": [
            {"delta": {"content": "assistant"}, "finish_reason": "tool_calls" if tools else "stop"}
        ]
    }
    usage = {
        "choices": [],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }
    calls = (
        [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "read-1",
                                    "function": {"name": "read", "arguments": '{"path":'},
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [{"index": 0, "function": {"arguments": '"README.md"}'}}]
                        }
                    }
                ]
            },
        ]
        if tools
        else []
    )
    return [first, *calls, *([last, usage] if complete else [])]


def source_for(protocol, wire, bodies, **config):
    provider = "ollama" if protocol == "ollama" else "lmstudio"

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={
                "content-type": "application/x-ndjson"
                if protocol == "ollama"
                else "text/event-stream"
            },
            stream=wire,
        )

    return CodeGemStream(
        {"tool_mode": "native", **config}, transport=httpx.MockTransport(respond)
    ), Model("gemma4:4b", provider)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["ollama", "openai"])
async def test_native_gemma_text_is_live_and_tools_wait_for_completion(protocol, tmp_path):
    wire = PausedStream(protocol, frames(protocol, tools=True))
    bodies = []
    source, model = source_for(protocol, wire, bodies)
    events = source(
        model, Context("", [UserMessage("Hello")], create_tools(tmp_path)), StreamOptions()
    )
    pending = None
    try:
        first = []
        while True:
            event = await asyncio.wait_for(anext(events), 1)
            first.append(event)
            if event.type == "text_delta":
                assert event.delta == "Hello "
                break
        assert not wire.release.is_set()
        assert not any(event.type == "toolcall_end" for event in first)
        assert bodies[0]["stream"] is True
        wire.release.set()
        rest = [event async for event in events]
        assert rest[-1].type == "done"
        message = rest[-1].message
        assert message.text == "Hello assistant"
        assert message.tool_calls[0].arguments == {"path": "README.md"}
        assert message.tool_calls[0].id == "read-1"
        assert message.usage.input == 4 and message.usage.output == 2
        assert [event.delta for event in first + rest if event.type == "text_delta"] == [
            "Hello ",
            "assistant",
        ]
        assert wire.closed and len(bodies) == 1
    finally:
        wire.release.set()
        await events.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["ollama", "openai"])
async def test_incomplete_native_gemma_stream_cannot_execute_tools_or_replay(protocol, tmp_path):
    wire = PausedStream(protocol, frames(protocol, tools=True, complete=False), pause=False)
    bodies = []
    source, model = source_for(protocol, wire, bodies)
    events = [
        event
        async for event in source(
            model, Context("", [UserMessage("Hello")], create_tools(tmp_path)), StreamOptions()
        )
    ]
    assert events[-1].type == "error"
    assert not any(event.type == "toolcall_end" for event in events)
    assert wire.closed and len(bodies) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["ollama", "openai"])
async def test_json_tool_envelope_is_hidden_until_complete(protocol, tmp_path):
    text = '{"content":"Reading", "tool_calls":[{"name":"read","arguments":{"path":"README.md"}}]}'
    chunks = frames(protocol)
    if protocol == "ollama":
        chunks[0]["message"]["content"] = text[:20]
        chunks[1]["message"]["content"] = text[20:]
    else:
        chunks[0]["choices"][0]["delta"]["content"] = text[:20]
        chunks[1]["choices"][0]["delta"]["content"] = text[20:]
    wire = PausedStream(protocol, chunks)
    bodies = []
    source, model = source_for(protocol, wire, bodies, tool_mode="json")
    seen = []

    async def collect():
        async for event in source(
            model, Context("", [UserMessage("Hello")], create_tools(tmp_path)), StreamOptions()
        ):
            seen.append(event)

    running = asyncio.create_task(collect())
    try:
        await asyncio.sleep(0.05)
        assert not any(event.type in {"text_delta", "toolcall_end"} for event in seen)
        wire.release.set()
        await asyncio.wait_for(running, 1)
        assert seen[-1].type == "done"
        assert seen[-1].message.text == "Reading"
        assert seen[-1].message.tool_calls[0].arguments == {"path": "README.md"}
        assert len(bodies) == 1
    finally:
        wire.release.set()
        await running


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["ollama", "openai"])
async def test_closing_a_partial_local_stream_closes_http_transport(protocol):
    wire = PausedStream(protocol, frames(protocol))
    bodies = []
    source, model = source_for(protocol, wire, bodies)
    events = source(model, Context("", [UserMessage("Hello")]), StreamOptions(max_tokens=128))
    try:
        while (event := await asyncio.wait_for(anext(events), 1)).type != "text_delta":
            pass
        await events.aclose()
        assert wire.closed
        limit = (
            bodies[0]["options"]["num_predict"] if protocol == "ollama" else bodies[0]["max_tokens"]
        )
        assert limit == 128
        assert len(bodies) == 1
    finally:
        wire.release.set()
        await events.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["ollama", "openai"])
async def test_desktop_codegem_local_text_arrives_before_generation_finishes(tmp_path, protocol):
    import subprocess
    import threading
    import time
    from dataclasses import replace
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from superqode.desktop_service.service import DesktopService
    from superqode.harness.loader import save_harness_spec
    from superqode.harness.templates import codegem_template

    began, finish, release = threading.Event(), threading.Event(), threading.Event()
    bodies = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/x-ndjson" if protocol == "ollama" else "text/event-stream",
            )
            self.end_headers()
            wire = PausedStream(protocol, [])
            first, *tail = frames(protocol)
            self.wfile.write(wire.encode(first))
            self.wfile.flush()
            began.set()
            if not finish.wait(20):
                return
            try:
                for payload in tail:
                    self.wfile.write(wire.encode(payload))
                    self.wfile.flush()
                # Generation has ended, but the connection stays open.
                release.wait(20)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    provider = "ollama" if protocol == "ollama" else "lmstudio"
    base = f"http://127.0.0.1:{server.server_port}"
    config = {
        "tool_mode": "native",
        "context_window": 4096,
        "ollama_base_url": base,
        "base_url": base + "/v1",
        "context_files": False,
        "skill_directories": [],
        "include_prompt_templates": False,
    }
    spec = codegem_template(name="local-stream-codegem")
    spec = replace(spec, runtime=replace(spec.runtime, config=config))
    save_harness_spec(spec, root / "harness.yaml")
    service = DesktopService(tmp_path / "state")
    try:
        project = service.open_project(str(root))
        job = service.dispatch(
            "tasks.start",
            {
                "project": project["id"],
                "harness": spec.name,
                "provider": provider,
                "model": "gemma4:4b",
                "prompt": "Hello",
                "max_tokens": 256,
            },
        )
        assert await asyncio.to_thread(began.wait, 20), "The model request never arrived"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            detail = service.dispatch("jobs.get", {"id": job["id"]})
            if any(
                event.get("data", {}).get("event") == "model_delta" for event in detail["events"]
            ):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("The desktop buffered local Gemma text until generation finished")
        assert detail["status"] == "running" and not finish.is_set()
        finish.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            detail = service.dispatch("jobs.get", {"id": job["id"]})
            if detail["status"] not in {"running", "queued", "needs_approval", "cancelling"}:
                break
            await asyncio.sleep(0.02)
        assert detail["status"] == "completed", detail
        assert not release.is_set()
        assert len(bodies) == 1
        limit = (
            bodies[0]["options"]["num_predict"] if protocol == "ollama" else bodies[0]["max_tokens"]
        )
        assert limit == 256
    finally:
        finish.set()
        release.set()
        service.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
