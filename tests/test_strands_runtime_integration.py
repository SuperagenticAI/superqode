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
def local_runtime(tmp_path, monkeypatch):
    paths = []

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            paths.append(self.path)
            used = any(m["role"] == "tool" for m in body.get("messages", []))
            self.send_response(200)
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
