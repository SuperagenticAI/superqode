"""Opt-in real Strands worker tests against a local, deterministic Ollama fixture."""

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading

import pytest
import yaml

from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.strands import StrandsHarnessBackend
from superqode.harness.templates import strands_template
from superqode.harness.loader import harness_spec_to_dict
from superqode.harness.eval import run_harness_eval
from superqode.harness.acceptance import heldout_acceptance

pytestmark = pytest.mark.skipif(
    not os.environ.get("SUPERQODE_TEST_STRANDS_PYTHON"),
    reason="Set SUPERQODE_TEST_STRANDS_PYTHON to a pinned isolated Strands interpreter",
)


@pytest.fixture
def local_runtime(tmp_path, monkeypatch, request):
    provider = getattr(request, "param", "ollama")

    class Requests(list):
        status = None
        headers = []

    paths = Requests()

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            paths.append(self.path)
            paths.headers.append(self.headers.get("Authorization"))
            if paths.status:
                self.send_response(paths.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "provider-fixture-secret"}).encode())
                return
            used = any(m["role"] == "tool" for m in body.get("messages", []))
            self.send_response(200)
            if provider == "openai":
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                used = any(m.get("type") == "function_call_output" for m in body.get("input", []))
                packets = (
                    [
                        {
                            "type": "response.output_text.delta",
                            "item_id": "message",
                            "output_index": 0,
                            "content_index": 0,
                            "delta": "strands-backend-ok",
                        }
                    ]
                    if used
                    else [
                        {
                            "type": "response.output_item.added",
                            "output_index": 0,
                            "item": {
                                "type": "function_call",
                                "id": "read-item",
                                "call_id": "read-fixture",
                                "name": "read",
                                "arguments": "",
                                "status": "in_progress",
                            },
                        },
                        {
                            "type": "response.function_call_arguments.done",
                            "output_index": 0,
                            "item_id": "read-item",
                            "arguments": '{"path":"README.md"}',
                        },
                    ]
                )
                packets.append(
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "fixture",
                            "object": "response",
                            "status": "completed",
                            "output": [],
                            "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                        },
                    }
                )
                for index, packet in enumerate(packets):
                    packet["sequence_number"] = index
                    self.wfile.write(
                        (
                            "event: " + packet["type"] + "\ndata: " + json.dumps(packet) + "\n\n"
                        ).encode()
                    )
                return
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            message = {"role": "assistant", "content": "strands-backend-ok" if used else ""}
            if not used:
                message["tool_calls"] = [
                    {"function": {"name": "read", "arguments": {"path": "README.md"}}}
                ]
            for packet in [
                {"model": "fixture", "message": message, "done": False},
                {
                    "model": "fixture",
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "total_duration": 1000000,
                    "prompt_eval_count": 10,
                    "eval_count": 4,
                },
            ]:
                self.wfile.write((json.dumps(packet) + "\n").encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("SUPERQODE_STRANDS_PYTHON", os.environ["SUPERQODE_TEST_STRANDS_PYTHON"])
    monkeypatch.setenv("OLLAMA_HOST", f"http://127.0.0.1:{server.server_port}")
    if provider == "openai":
        monkeypatch.setenv("OPENAI_API_BASE", f"http://127.0.0.1:{server.server_port}/v1")
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "local-openai-fixture")
    monkeypatch.setenv("MONTY_BIN", "/does/not/exist")
    (tmp_path / "README.md").write_text("fixture-read-ok")
    spec = strands_template()
    spec = replace(
        spec,
        runtime=replace(
            spec.runtime,
            config={
                "effort": "off",
                "context_manager": False,
                "caching": False,
                "session": False,
                "max_turns": 3,
            },
        ),
    )
    try:
        yield tmp_path, spec, paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_real_isolated_worker_streams_governed_read_and_usage(local_runtime):
    root, spec, paths = local_runtime
    result = await StrandsHarnessBackend().run(
        HarnessBackendRequest(
            spec=spec,
            prompt="Read README.md.",
            provider="ollama",
            model="fixture",
            working_directory=root,
        )
    )
    assert result.response.content.strip() == "strands-backend-ok"
    assert result.response.tool_calls_made == 1
    assert result.response.total_tokens == 28
    assert result.response.cost_usd is None
    assert any(
        e.type == "tool_result" and e.data["success"] and "fixture-read-ok" in e.data["output"]
        for e in result.metadata["events"]
    )
    assert paths == ["/api/chat", "/api/chat"]


@pytest.mark.asyncio
async def test_real_worker_reaches_shared_eval_and_acceptance_contract(local_runtime):
    root, spec, paths = local_runtime
    baseline = root / "baseline.yaml"
    candidate = root / "candidate.yaml"
    baseline.write_text(yaml.safe_dump(harness_spec_to_dict(spec)))
    candidate.write_text(
        yaml.safe_dump(harness_spec_to_dict(replace(spec, name="strands-candidate")))
    )
    tasks = root / "tasks.yaml"
    tasks.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "id": "fixture",
                        "prompt": "Read README.md.",
                        "split": "held-out",
                        "evaluator": {"type": "contains", "expected": "strands-backend-ok"},
                    }
                ]
            }
        )
    )
    report = await run_harness_eval(
        spec_paths=[baseline, candidate],
        tasks_path=tasks,
        provider="ollama",
        model="fixture",
        working_dir=root,
        live=True,
        eval_split="held-out",
    )
    assert report["status"] == "passed"
    assert report["variants"][0]["score"] == 1.0
    assert report["variants"][1]["score"] == 1.0
    assert heldout_acceptance(report)["accepted"]
    assert len(paths) == 4


@pytest.mark.asyncio
async def test_real_sdk_token_limit_cannot_be_reported_as_success(local_runtime):
    root, spec, _ = local_runtime
    spec = replace(
        spec, runtime=replace(spec.runtime, config={**spec.runtime.config, "total_tokens": 1})
    )
    with pytest.raises(RuntimeError, match="did not complete: max_tokens"):
        await StrandsHarnessBackend().run(
            HarnessBackendRequest(
                spec=spec,
                prompt="Read README.md",
                provider="ollama",
                model="fixture",
                working_directory=root,
            )
        )


@pytest.mark.asyncio
async def test_real_worker_restores_project_session(local_runtime, monkeypatch):
    from superqode.harness.backends import strands

    root, spec, paths = local_runtime
    monkeypatch.setattr(strands.Path, "home", classmethod(lambda cls: root / "private-home"))
    spec = replace(
        spec, runtime=replace(spec.runtime, config={**spec.runtime.config, "session": True})
    )
    request = HarnessBackendRequest(
        spec=spec,
        prompt="Read README.md.",
        provider="ollama",
        model="fixture",
        working_directory=root,
        session_id="stable-session",
    )
    first = await StrandsHarnessBackend().run(request)
    second = await StrandsHarnessBackend().run(request)
    assert first.response.tool_calls_made == 1
    assert second.response.tool_calls_made == 0
    assert second.response.content.strip() == "strands-backend-ok"
    # Reopening starts with the previous tool result rather than silently
    # resetting the conversation and re-executing the first read.
    assert len(paths) == 3


@pytest.mark.parametrize("status,hint", [(401, "authentication failed"), (404, "not found")])
@pytest.mark.asyncio
async def test_real_worker_provider_failures_are_actionable_and_redacted(
    local_runtime, status, hint
):
    root, spec, paths = local_runtime
    paths.status = status
    request = HarnessBackendRequest(
        spec=spec, prompt="fixture", provider="ollama", model="fixture", working_directory=root
    )
    with pytest.raises(RuntimeError, match=hint) as error:
        await StrandsHarnessBackend().run(request)
    assert "provider-fixture-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_real_worker_uses_saved_key_for_local_provider(local_runtime, tmp_path, monkeypatch):
    from superqode import auth

    root, spec, paths = local_runtime
    storage = auth.LocalAuthStorage(tmp_path / "auth.json")
    storage.set("ollama", auth.ApiAuth(key="saved-ollama-fixture"))
    monkeypatch.setattr(auth, "_storage", storage)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    request = HarnessBackendRequest(
        spec=spec,
        prompt="Read README.md",
        provider="ollama",
        model="fixture",
        working_directory=root,
    )
    await StrandsHarnessBackend().run(request)
    assert paths.headers == ["Bearer saved-ollama-fixture", "Bearer saved-ollama-fixture"]


@pytest.mark.parametrize("local_runtime", ["openai"], indirect=True)
@pytest.mark.asyncio
async def test_real_openai_sdk_uses_shared_endpoint_and_governed_tools(local_runtime):
    root, spec, paths = local_runtime
    result = await StrandsHarnessBackend().run(
        HarnessBackendRequest(
            spec=spec,
            prompt="Read README.md",
            provider="openai",
            model="fixture",
            working_directory=root,
        )
    )
    assert result.response.content.strip() == "strands-backend-ok"
    assert result.response.tool_calls_made == 1
    assert paths == ["/v1/responses", "/v1/responses"]
    assert paths.headers == ["Bearer local-openai-fixture"] * 2


def test_desktop_job_runs_actual_strands_worker(local_runtime, monkeypatch):
    import subprocess
    import time
    from superqode.desktop_service.service import DesktopService

    root, _, paths = local_runtime
    monkeypatch.setenv("HOME", str(root / "isolated-home"))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    service = DesktopService(root / "desktop-state")
    try:
        project = service.open_project(str(root))
        job = service.dispatch(
            "tasks.start",
            {
                "project": project["id"],
                "harness": "strands",
                "provider": "ollama",
                "model": "fixture",
                "prompt": "Read README.md",
                "command_id": "strands-native-worker",
            },
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            detail = service.dispatch("jobs.get", {"id": job["id"]})
            if detail["status"] not in {"running", "needs_approval"}:
                break
            time.sleep(0.05)
        assert detail["status"] == "completed", detail
        assert paths == ["/api/chat", "/api/chat"]
        first_session = detail["result"]["session_id"]
        assert detail["result"]["native_continuity"] is True
        followup = service.dispatch(
            "tasks.start",
            {
                "project": project["id"],
                "harness": "strands",
                "provider": "ollama",
                "model": "fixture",
                "prompt": "Continue the same session",
                "parent_id": job["id"],
                "command_id": "strands-native-followup",
            },
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            detail = service.dispatch("jobs.get", {"id": followup["id"]})
            if detail["status"] not in {"running", "needs_approval"}:
                break
            time.sleep(0.05)
        assert detail["status"] == "completed", detail
        assert detail["result"]["session_id"] == first_session
        assert len(paths) == 3  # Restored tool history avoids re-executing the read.
    finally:
        service.close()


@pytest.mark.parametrize("reference", ["strands", "aws-strands"])
def test_cli_runs_named_strands_harness(local_runtime, monkeypatch, reference):
    from click.testing import CliRunner
    from superqode.commands.harness import harness

    root, _, paths = local_runtime
    monkeypatch.setenv("HOME", str(root / "private-home"))
    result = CliRunner().invoke(
        harness,
        [
            "run",
            reference,
            "--provider",
            "ollama",
            "--model",
            "fixture",
            "--working-dir",
            str(root),
            "--store",
            "memory",
            "--json",
            "-p",
            "Read README.md",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["harness"] == "strands"
    assert data["content"].strip() == "strands-backend-ok"
    assert paths == ["/api/chat", "/api/chat"]


@pytest.mark.asyncio
async def test_acp_stdio_runs_strands_and_restores_followup(local_runtime):
    import shlex
    import sys
    from superqode.acp.client import ACPClient

    root, _, paths = local_runtime
    messages, tools = [], []

    async def message(text):
        messages.append(text)

    async def tool(call):
        tools.append(call)

    source = Path(__file__).resolve().parents[1] / "src"
    command = shlex.join(
        [
            sys.executable,
            "-c",
            "from superqode.main import cli_main; cli_main()",
            "serve",
            "acp",
            "--harness",
            "strands",
            "--provider",
            "ollama",
            "--model",
            "fixture",
        ]
    )
    client = ACPClient(
        project_root=root,
        command=command,
        on_message=message,
        on_tool_call=tool,
        extra_env={
            "PYTHONPATH": str(source),
            "HOME": str(root / "private-home"),
            "SUPERQODE_ACP_SPEC": "",
            "SUPERQODE_ACP_HARNESS": "",
        },
        startup_timeout=15,
        request_timeout=15,
        prompt_timeout=20,
    )
    try:
        assert await client.start(), client.last_startup_error
        assert await client.send_prompt("Read README.md") == "end_turn"
        session_id = client._session_id
        assert "strands-backend-ok" in "".join(messages)
        assert tools
        assert paths == ["/api/chat", "/api/chat"]
        assert await client.send_prompt("Continue this session") == "end_turn"
        assert client._session_id == session_id
        assert len(paths) == 3
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_tui_execution_streams_tools_once_and_records_usage(local_runtime, monkeypatch):
    from superqode.pure_mode import PureMode

    root, _, paths = local_runtime
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(root / "private-home"))
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)
    pure = PureMode()
    calls, results = [], []
    pure.on_tool_call = lambda name, arguments: calls.append((name, arguments))
    pure.on_tool_result = lambda name, result: results.append((name, result))
    pure.select_harness("strands")
    assert pure.connect("ollama", "fixture", working_directory=root)
    chunks = [chunk async for chunk in pure.run_streaming("Read README.md")]
    assert "strands-backend-ok" in "".join(chunks)
    assert len(calls) == len(results) == 1
    assert calls[0][0] == results[0][0] == "read"
    assert results[0][1].success
    assert pure.get_status()["stats"]["total_tokens"] == 28
    assert pure.get_status()["stats"]["cost_usd"] is None
    assert pure.session.total_tool_calls == 1
    assert paths == ["/api/chat", "/api/chat"]
