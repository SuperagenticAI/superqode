"""Real local worker/kernel/tool roundtrip against a controlled loopback model."""

from dataclasses import replace
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from test_desktop_service import desktop, wait_job  # noqa: F401
from superqode.local import servers


@pytest.mark.parametrize("attempt_escape", [False, True])
def test_core_read_check_executes_one_tool_and_keeps_project_untouched(
    desktop, monkeypatch, attempt_escape
):
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
            tool_output = next(
                (m["content"] for m in body["messages"] if m["role"] == "tool"), None
            )
            if tool_output:
                found = re.search(r"SUPERQODE_READ_CHECK_[a-f0-9]+", str(tool_output))
                marker = found[0] if found else "No accessible marker"
                delta, finish = {"role": "assistant", "content": marker}, "stop"
            else:
                path = str(root / "hello.txt") if attempt_escape else "verification.txt"
                delta = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "fixture-read",
                            "type": "function",
                            "function": {"name": "read", "arguments": json.dumps({"path": path})},
                        }
                    ],
                }
                finish = "tool_calls"
            self.send_response(200)
            if not body.get("stream"):
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if delta.get("tool_calls"):
                    for call in delta["tool_calls"]:
                        call.pop("index", None)
                self.wfile.write(
                    json.dumps(
                        {
                            "id": "fixture-check",
                            "object": "chat.completion",
                            "created": 1,
                            "model": "fixture-model",
                            "choices": [{"index": 0, "message": delta, "finish_reason": finish}],
                        }
                    ).encode()
                )
                return
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for change, reason in [(delta, None), ({}, finish)]:
                packet = {
                    "id": "fixture-check",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": change, "finish_reason": reason}],
                }
                self.wfile.write(("data: " + json.dumps(packet) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")

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
        plan = service.dispatch(
            "local.models.prepare",
            {
                "action": "verify",
                "check": "core-read",
                "engine": "lmstudio",
                "model": "fixture-model",
            },
        )
        assert not calls and not service.dispatch("local.models.jobs", {})
        request = {
            "plan": plan["id"],
            "expected_digest": plan["digest"],
            "command_id": "one-core-read-check",
        }
        started = service.dispatch("local.models.start", request)
        completed = wait_job(service, started["id"])
        assert completed["status"] == "completed", completed
        result = completed["result"]
        assert result["scope"] == "core-read-tool"
        assert result["verification"]["status"] == ("failed" if attempt_escape else "passed"), (
            json.dumps({"result": result, "calls": calls}, indent=2)
        )
        assert all(
            check["ok"] == (not attempt_escape) for check in result["verification"]["checks"]
        )
        assert result["harness_certified"] is False
        assert len(calls) == 2
        assert [tool["function"]["name"] for tool in calls[0]["tools"]] == ["read"]
        assert "SUPERQODE_READ_CHECK_" not in json.dumps(calls[0])
        assert service.dispatch("local.models.start", request) == started
        assert len(calls) == 2
        assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before
        assert not list(service.root.glob("core-read-check-*"))
        evidence = service.dispatch("local.models.compatibility", {"project": project["id"]})
        assert evidence["checks"][0]["id"] == started["id"]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    "stop,error,schema_errors",
    [
        ("error", "fixture failure", None),
        ("cancelled", None, None),
        ("max_iterations", None, None),
        ("complete", "fixture failure", None),
        ("complete", None, ["invalid output"]),
    ],
)
@pytest.mark.asyncio
async def test_matching_read_evidence_cannot_hide_failed_execution(
    tmp_path, monkeypatch, stop, error, schema_errors
):
    from superqode.agent.loop import AgentResponse
    from superqode.local.coding_check import run

    class Session:
        async def run(self, request):
            marker = (request.working_directory / "verification.txt").read_text().strip()
            return SimpleNamespace(
                response=AgentResponse(
                    content=marker,
                    messages=[],
                    tool_calls_made=1,
                    iterations=1,
                    stopped_reason=stop,
                    error=error,
                    schema_errors=schema_errors,
                ),
                content=marker,
                events=[
                    SimpleNamespace(
                        type="tool_result",
                        data={"tool_name": "read", "success": True, "output": marker},
                    )
                ],
                iterations=1,
                tool_calls_made=1,
                tokens_in=10,
                tokens_out=2,
            )

    class Kernel:
        async def session(self):
            return Session()

    async def initialize(*args, **kwargs):
        return Kernel()

    monkeypatch.setattr("superqode.harness.init_harness", initialize)
    report = await run(
        "lmstudio", "fixture-model", "http://127.0.0.1:1234/v1", tmp_path, lambda *args: None
    )
    assert all(check["ok"] for check in report["checks"])
    assert report["status"] == "failed"
    assert report["execution_complete"] is False
    assert report["stopped_reason"] == stop
    assert report["tokens_in"] == 10
    assert report["tokens_out"] == 2
    assert not list(tmp_path.glob("core-read-check-*"))

@pytest.mark.asyncio
async def test_successful_read_passes_when_reasoning_leaves_empty_content(
    tmp_path, monkeypatch
):
    """Reasoning models may burn the token budget after a successful tool read."""
    from superqode.agent.loop import AgentResponse
    from superqode.local.coding_check import run

    class Session:
        async def run(self, request):
            marker = (request.working_directory / "verification.txt").read_text().strip()
            return SimpleNamespace(
                response=AgentResponse(
                    content="",
                    messages=[],
                    tool_calls_made=1,
                    iterations=2,
                    stopped_reason="complete",
                    error=None,
                    schema_errors=None,
                ),
                content="",
                events=[
                    SimpleNamespace(
                        type="tool_result",
                        data={"tool_name": "read", "success": True, "output": marker + "\n"},
                    )
                ],
                iterations=2,
                tool_calls_made=1,
                tokens_in=40,
                tokens_out=384,
            )

    class Kernel:
        async def session(self):
            return Session()

    async def initialize(*args, **kwargs):
        return Kernel()

    monkeypatch.setattr("superqode.harness.init_harness", initialize)
    report = await run(
        "ollama", "qwen3:8b", "http://127.0.0.1:11434/v1", tmp_path, lambda *args: None
    )
    assert report["status"] == "passed"
    assert report["execution_complete"] is True
    assert all(check["ok"] for check in report["checks"])

