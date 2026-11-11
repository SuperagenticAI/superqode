"""A finished Gemini response must not wait for a lingering HTTP connection."""

import asyncio
import json

import httpx
import pytest

from superqode.codegem.provider import CodeGemStream
from superqode.pipy.messages import UserMessage
from superqode.pipy.provider_events import AssistantDoneEvent, TextDeltaEvent
from superqode.pipy.stream import Context, Model, StreamOptions


def chunk(text="Hello", *, finish="STOP"):
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}
        ],
        "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 1, "totalTokenCount": 5},
    }


class LingeringStream(httpx.AsyncByteStream):
    def __init__(self, payload):
        self.payload = payload
        self.release = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        yield ("data: " + json.dumps(self.payload) + "\n\n").encode()
        await self.release.wait()

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_codegem_finishes_on_gemini_stop_without_waiting_for_http_eof():
    wire = LingeringStream(chunk())
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=wire)

    stream = CodeGemStream(transport=httpx.MockTransport(respond))
    events = stream(
        Model(id="gemini-4-argon", provider="google"),
        Context(system_prompt="", messages=[UserMessage("Hello")]),
        StreamOptions(api_key="fixture-key"),
    )
    while True:
        event = await anext(events)
        if isinstance(event, TextDeltaEvent):
            assert event.delta == "Hello"
            break

    async def collect():
        return [event async for event in events]

    pending = asyncio.create_task(collect())
    try:
        rest = await asyncio.wait_for(asyncio.shield(pending), 0.5)
        assert any(isinstance(event, AssistantDoneEvent) for event in rest)
        assert wire.closed
        assert not wire.release.is_set()
        assert len(requests) == 1
    finally:
        wire.release.set()
        await pending


@pytest.mark.asyncio
async def test_codegem_respects_per_request_reasoning_and_output_limit():
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=chunk())

    source = CodeGemStream(transport=httpx.MockTransport(respond))
    events = [
        event
        async for event in source(
            Model(id="gemini-4-argon", provider="google"),
            Context(system_prompt="", messages=[UserMessage("Hello")]),
            StreamOptions(api_key="fixture", reasoning="low", max_tokens=256),
        )
    ]
    assert any(isinstance(event, AssistantDoneEvent) for event in events)
    assert bodies[0]["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "LOW"
    assert bodies[0]["generationConfig"]["maxOutputTokens"] == 256


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["MAX_TOKENS", "CONTINUATION"])
async def test_explicit_output_limit_does_not_trigger_more_decode_calls(reason):
    bodies = []
    payload = chunk("Truncated", finish=reason)
    payload["candidates"][0]["continuationToken"] = "continue-here"

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    source = CodeGemStream(transport=httpx.MockTransport(respond))
    events = [
        event
        async for event in source(
            Model("gemini-4-argon", "google"),
            Context("", [UserMessage("Hello")]),
            StreamOptions(api_key="fixture", max_tokens=256),
        )
    ]
    assert len(bodies) == 1
    assert events[-1].type == "done"
    assert events[-1].message.stop_reason == "length"
    assert events[-1].message.text == "Truncated"


@pytest.mark.asyncio
async def test_explicit_harness_thinking_and_lower_output_cap_keep_precedence():
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=chunk())

    source = CodeGemStream(
        {"thinking_config": {"thinkingLevel": "HIGH"}, "max_output_tokens": 128},
        transport=httpx.MockTransport(respond),
    )
    events = [
        event
        async for event in source(
            Model("gemini-4-argon", "google"),
            Context("", [UserMessage("Hello")]),
            StreamOptions(api_key="fixture", reasoning="low", max_tokens=256),
        )
    ]
    assert events[-1].type == "done"
    assert bodies[0]["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "HIGH"
    assert bodies[0]["generationConfig"]["maxOutputTokens"] == 128


@pytest.mark.asyncio
@pytest.mark.parametrize("use_tool", [False, True])
async def test_desktop_codegem_completes_while_google_http_stream_lingers(
    tmp_path, monkeypatch, use_tool
):
    import subprocess
    import threading
    import time
    from dataclasses import replace
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from superqode.desktop_service.service import DesktopService
    from superqode.harness.loader import save_harness_spec
    from superqode.harness.templates import codegem_template

    started = threading.Event()
    finish = threading.Event()
    release = threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            first = len(requests) == 1
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def send(payload):
                self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())
                self.wfile.flush()

            try:
                if first:
                    send(chunk("Reading" if use_tool else "Hello", finish=None))
                    started.set()
                    if not finish.wait(20):
                        return
                final = chunk("Done" if not first else "")
                if first and use_tool:
                    final["candidates"][0]["content"]["parts"] = [
                        {
                            "functionCall": {
                                "name": "read",
                                "id": "read-1",
                                "args": {"path": "README.md"},
                            },
                            "thoughtSignature": "fixture-signature",
                        }
                    ]
                send(final)
                # Each completed model turn keeps its HTTP stream open. A tool
                # turn must still execute read and make the next model request.
                release.wait(20)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-key")
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("local read fixture")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    spec = codegem_template(name="latency-codegem")
    spec = replace(
        spec,
        runtime=replace(
            spec.runtime,
            config={
                **spec.runtime.config,
                "gemini_base_url": f"http://127.0.0.1:{server.server_port}",
                "context_files": False,
                "skill_directories": [],
                "include_prompt_templates": False,
            },
        ),
    )
    save_harness_spec(spec, root / "harness.yaml")
    service = DesktopService(tmp_path / "state")
    try:
        project = service.open_project(str(root))
        job = service.dispatch(
            "tasks.start",
            {
                "project": project["id"],
                "harness": "latency-codegem",
                "provider": "google",
                "model": "gemini-4-argon",
                "prompt": "Hello",
                "max_tokens": 256,
            },
        )
        assert await asyncio.to_thread(started.wait, 20), "No Gemini model request arrived"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            detail = service.dispatch("jobs.get", {"id": job["id"]})
            if any(
                event.get("data", {}).get("event") == "model_delta" for event in detail["events"]
            ):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("The app's worker buffered Gemini's live text")
        assert detail["status"] == "running"
        finish.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            detail = service.dispatch("jobs.get", {"id": job["id"]})
            if detail["status"] not in {"running", "needs_approval", "queued", "cancelling"}:
                break
            await asyncio.sleep(0.02)
        assert detail["status"] == "completed", detail
        assert not release.is_set(), "Completion must not need model HTTP EOF"
        assert len(requests) == (2 if use_tool else 1)
        assert all(body["generationConfig"]["maxOutputTokens"] == 256 for body in requests)
        if use_tool:
            assert "local read fixture" in json.dumps(requests[1]["contents"])
    finally:
        finish.set()
        release.set()
        service.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_long_decode_moves_to_next_hop_without_waiting_for_http_eof():
    first = chunk("First ", finish="CONTINUATION")
    first["candidates"][0]["continuationToken"] = "continue-here"
    wires = [LingeringStream(first), LingeringStream(chunk("Second"))]
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=wires[len(bodies) - 1]
        )

    source = CodeGemStream(transport=httpx.MockTransport(respond))

    async def collect():
        return [
            event
            async for event in source(
                Model("gemini-4-argon", "google"),
                Context("", [UserMessage("Hello")]),
                StreamOptions(api_key="fixture"),
            )
        ]

    pending = asyncio.create_task(collect())
    try:
        events = await asyncio.wait_for(asyncio.shield(pending), 1)
        assert events[-1].type == "done"
        assert events[-1].message.text == "First Second"
        assert events[-1].message.usage.input == 8
        assert events[-1].message.usage.output == 2
        assert bodies[1]["continuationToken"] == "continue-here"
        assert all(wire.closed and not wire.release.is_set() for wire in wires)
    finally:
        for wire in wires:
            wire.release.set()
        await pending


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, True, "256"])
async def test_invalid_explicit_output_limit_fails_before_sending_request(limit):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=chunk())

    source = CodeGemStream(transport=httpx.MockTransport(respond))
    events = [
        event
        async for event in source(
            Model("gemini-4-argon", "google"),
            Context("", [UserMessage("Hello")]),
            StreamOptions(api_key="fixture", max_tokens=limit),
        )
    ]
    assert not requests
    assert events[-1].type == "error"
    assert "positive integer" in events[-1].error.error_message


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_prompt", [False, True])
async def test_blocked_gemini_response_reports_error_without_waiting_for_http_eof(blocked_prompt):
    payload = (
        {"promptFeedback": {"blockReason": "SAFETY"}}
        if blocked_prompt
        else chunk("", finish="SAFETY")
    )
    wire = LingeringStream(payload)
    source = CodeGemStream(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=wire,
            )
        )
    )

    async def collect():
        return [
            event
            async for event in source(
                Model("gemini-4-argon", "google"),
                Context("", [UserMessage("Hello")]),
                StreamOptions(api_key="fixture"),
            )
        ]

    pending = asyncio.create_task(collect())
    try:
        events = await asyncio.wait_for(asyncio.shield(pending), 1)
        assert events[-1].type == "error"
        assert "SAFETY" in events[-1].error.error_message
        assert wire.closed and not wire.release.is_set()
    finally:
        wire.release.set()
        await pending
