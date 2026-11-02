"""Real Core/PiPy checks through desktop workers and loopback model fixtures."""

from dataclasses import replace
import importlib.util
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_desktop_service import desktop, wait_job  # noqa: F401
from test_desktop_studio import review
from superqode.local import servers


@pytest.mark.parametrize(
    "backend,escape",
    [
        ("builtin", False),
        ("pipy", False),
        ("pipy", True),
        ("adk", False),
        ("openai-agents", False),
        ("pydanticai", False),
    ],
)
def test_real_backend_read_edit_repeats_and_escape_boundary(desktop, monkeypatch, backend, escape):
    sdk = {"adk": "google.adk", "openai-agents": "agents", "pydanticai": "pydantic_ai"}.get(backend)
    if sdk:
        try:
            installed = importlib.util.find_spec(sdk) is not None
        except ModuleNotFoundError:
            installed = False
        if not installed:
            pytest.skip(f"{backend} SDK is not installed")
    service, project, root = desktop
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": [{"id": "fixture-model"}]}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            tools = {tool["function"]["name"]: tool["function"] for tool in body.get("tools", [])}
            outputs = [str(m["content"]) for m in body["messages"] if m["role"] == "tool"]
            marker = re.search(r"STUDIO_MARKER_[a-f0-9]+", " ".join(outputs))
            name, args = "", {}
            if not outputs:
                name, args = (
                    "read",
                    {"path": str(root / "hello.txt") if escape else "verification.txt"},
                )
            elif escape:
                content = "No accessible marker"
            elif len(outputs) == 1:
                name, args = "read", {"path": "sample.py"}
            elif len(outputs) == 2:
                properties = tools["edit"]["parameters"]["properties"]
                args = {"path": "sample.py"}
                if "edits" in properties:
                    args["edits"] = [{"oldText": "return 1", "newText": "return 2"}]
                else:
                    args.update(old_text="return 1", new_text="return 2")
                name = "edit"
            else:
                content = marker[0] if marker else "No marker"
            if name:
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-" + str(len(outputs)),
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                    ],
                }
                finish = "tool_calls"
            else:
                message, finish = {"role": "assistant", "content": content}, "stop"
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/event-stream" if body.get("stream") else "application/json"
            )
            self.end_headers()
            if body.get("stream"):
                delta = dict(message)
                if delta.get("tool_calls"):
                    delta["tool_calls"][0]["index"] = 0
                for change, reason in [(delta, None), ({}, finish)]:
                    packet = {
                        "id": "studio-fixture",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "fixture-model",
                        "choices": [{"index": 0, "delta": change, "finish_reason": reason}],
                    }
                    self.wfile.write(("data: " + json.dumps(packet) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.wfile.write(
                    json.dumps(
                        {
                            "id": "studio-fixture",
                            "object": "chat.completion",
                            "created": 1,
                            "model": "fixture-model",
                            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                        }
                    ).encode()
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setitem(
        servers.SPECS,
        "lmstudio",
        replace(servers.SPECS["lmstudio"], default_port=server.server_port),
    )
    monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("SUPERQODE_SEARCH_ROOTS", str(root))
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    try:
        inspected = review(
            service,
            project["id"],
            backend=backend,
            route={"source": "local", "engine": "lmstudio", "model": "fixture-model"},
        )
        plan = service.dispatch(
            "studio.check.prepare",
            {
                "project": project["id"],
                "review": inspected["review"],
                "digest": inspected["digest"],
                "check": "edit",
                "repeats": 2,
            },
        )
        assert not calls
        params = {
            "project": project["id"],
            "plan": plan["plan"],
            "digest": plan["digest"],
            "command_id": "one-studio-check",
        }
        started = service.dispatch("studio.check.start", params)
        completed = wait_job(service, started["id"])
        assert completed["status"] == "completed", completed
        result = completed["result"]
        assert result["source_digest"] == inspected["digest"] and result["backend"] == backend
        assert result["summary"]["attempts"] == 2
        assert result["summary"]["passed"] == (0 if escape else 2), json.dumps(result, indent=2)
        if not escape:
            assert all(all(c["ok"] for c in attempt["checks"]) for attempt in result["attempts"])
            assert len({attempt["profile_digest"] for attempt in result["attempts"]}) == 1
        assert all(
            {t["function"]["name"] for t in request["tools"]} == {"read", "edit"}
            for request in calls
        )
        assert all(
            request.get("max_tokens", request.get("max_completion_tokens")) == 768
            for request in calls
        ), calls
        call_count = len(calls)
        assert (
            service.dispatch("studio.check.start", params) == started and len(calls) == call_count
        )
        assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before
        evidence = service.dispatch(
            "studio.evidence", {"project": project["id"], "digest": inspected["digest"]}
        )
        assert len(evidence) == 1 and evidence[0]["id"] == started["id"]
    finally:
        server.shutdown()
        server.server_close()
