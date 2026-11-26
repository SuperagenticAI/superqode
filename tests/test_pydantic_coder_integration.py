"""Opt-in real Coder ACP worker checks with no paid provider requests."""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest

from superqode.acp.client import ACPClient, cancel_prompt_with_grace
from superqode.pydantic_coder import worker

INTERPRETER = os.environ.get("SUPERQODE_TEST_PYDANTIC_CODER_PYTHON")
pytestmark = pytest.mark.skipif(
    not INTERPRETER, reason="Set SUPERQODE_TEST_PYDANTIC_CODER_PYTHON to the isolated runtime"
)
FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_connect_starts_installed_worker_without_a_console_script_on_path(tmp_path):
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from superqode.main import cli_main; cli_main()",
            "connect",
            "acp",
            "pydantic-coder",
            "--project-dir",
            str(tmp_path),
        ],
        input="/quit\n",
        text=True,
        capture_output=True,
        timeout=20,
        env={
            **os.environ,
            "SUPERQODE_PYDANTIC_CODER_PYTHON": INTERPRETER,
            "SUPERQODE_STATE_DIR": str(tmp_path / "state"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Pydantic Coder connected" in result.stdout


@pytest.mark.asyncio
async def test_real_worker_approvals_history_restart_and_cancel(tmp_path, monkeypatch):
    from superqode.mcp import config

    monkeypatch.setattr(config, "get_acp_mcp_servers", lambda: [])
    project = tmp_path / "project"
    project.mkdir()
    (project / "marker.txt").write_text("coder-marker")
    chunks, permissions, calls = [], [], []
    decision = "reject_once"

    async def message(text):
        chunks.append(text)

    async def permission(options, call):
        permissions.append({"decision": decision, "existed": (project / "written.txt").exists()})
        return next(o["optionId"] for o in options if o["kind"] == decision)

    async def tool(call):
        calls.append(call)

    def client(resume=None):
        return ACPClient(
            project,
            "coder-fixture",
            launch_argv=[
                INTERPRETER,
                "-I",
                str(FIXTURES / "pydantic_coder_agent.py"),
                worker.__file__,
                str(tmp_path / "state"),
            ],
            own_process_group=True,
            on_message=message,
            on_permission_request=permission,
            on_tool_call=tool,
            traffic_log_enabled=False,
            resume_session_id=resume,
            require_resume=bool(resume),
            startup_timeout=15,
            prompt_timeout=15,
        )

    active = client()

    async def ask(prompt):
        chunks.clear()
        assert await active.send_prompt(prompt) == "end_turn"
        return "".join(chunks)

    try:
        assert await active.start(), active.last_startup_error
        assert "coder-marker" in await ask("READ")
        assert any(c["kind"] == "read" for c in calls)
        await ask("WRITE deny")
        assert permissions[-1]["decision"] == "reject_once"
        assert not (project / "written.txt").exists()
        decision = "allow_once"
        await ask("WRITE approve")
        assert not permissions[-1]["existed"]
        assert (project / "written.txt").read_text() == "coder-approved"
        assert "coder-shell" in await ask("SHELL")
        assert "USER_TURNS=5" in await ask("HISTORY")
        options = active.get_session_config_options()
        assert any(o["id"] == "model" for o in options)
        selected_model = next(
            o["value"] for o in options[0]["options"] if o["value"].startswith("anthropic:")
        )
        assert await active.set_config_option("model", selected_model)
        session = active.get_session_id()
        await active.stop()
        active = client(session)
        assert await active.start(), active.last_startup_error
        assert "USER_TURNS=6" in await ask("HISTORY_AFTER_RESTART")
        assert (
            next(o for o in active.get_session_config_options() if o["id"] == "model")[
                "currentValue"
            ]
            == selected_model
        )
        pending = asyncio.create_task(active.send_prompt("SLOW"))
        await asyncio.sleep(0.2)
        assert await cancel_prompt_with_grace(active, pending, timeout=3)
        assert "USER_TURNS=" in await ask("AFTER_CANCEL")
    finally:
        await active.stop()


@pytest.mark.asyncio
async def test_real_worker_connects_client_mcp_and_asks_before_call(tmp_path, monkeypatch):
    from superqode.mcp import config

    monkeypatch.setattr(
        config,
        "get_acp_mcp_servers",
        lambda: [
            {
                "name": "echo",
                "command": INTERPRETER,
                "args": [str(FIXTURES / "pydantic_coder_mcp.py")],
                "env": [],
            }
        ],
    )
    chunks, permissions = [], []

    async def message(text):
        chunks.append(text)

    async def permit(options, call):
        permissions.append(call)
        return next(o["optionId"] for o in options if o["kind"] == "allow_once")

    client = ACPClient(
        tmp_path,
        "coder-mcp-fixture",
        launch_argv=[
            INTERPRETER,
            "-I",
            str(FIXTURES / "pydantic_coder_agent.py"),
            worker.__file__,
            str(tmp_path / "state"),
        ],
        own_process_group=True,
        on_message=message,
        on_permission_request=permit,
        traffic_log_enabled=False,
        startup_timeout=15,
        prompt_timeout=20,
    )
    try:
        assert await client.start(), client.last_startup_error
        assert await client.send_prompt("MCP") == "end_turn"
        assert "coder-mcp" in "".join(chunks)
        assert len(permissions) == 1
    finally:
        await client.stop()


def test_native_job_uses_packaged_launcher_and_app_key_without_a_paid_request(
    tmp_path, monkeypatch
):
    from superqode.desktop_service.service import DesktopService
    from superqode.desktop_service.connection_probe import probe_route
    from test_desktop_service import wait_job

    requests = []

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": body,
                }
            )
            message = {
                "type": "message",
                "id": "msg_coder",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "coder-native-ok", "annotations": []}],
            }
            response = {
                "id": "resp_coder",
                "object": "response",
                "created_at": 1,
                "model": body["model"],
                "status": "completed",
                "output": [message],
                "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
            }
            events = [
                {
                    "type": "response.created",
                    "response": {**response, "status": "in_progress", "output": []},
                },
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {**message, "content": [], "status": "in_progress"},
                },
                {
                    "type": "response.content_part.added",
                    "item_id": "msg_coder",
                    "output_index": 0,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": "", "annotations": []},
                },
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_coder",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "coder-native-ok",
                },
                {"type": "response.output_item.done", "output_index": 0, "item": message},
                {"type": "response.completed", "response": response},
            ]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event in events:
                self.wfile.write(
                    ("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode()
                )
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setenv("SUPERQODE_PYDANTIC_CODER_PYTHON", INTERPRETER)
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = DesktopService(tmp_path / "app-state")
    try:
        project = service.open_project(str(root))
        route = next(
            r
            for r in service.dispatch("routes.list", {"project": project["id"]})
            if r["id"] == "acp:pydantic-coder"
        )
        checked = asyncio.run(probe_route(root, route, lambda message: None))
        assert checked["connected"] is True
        assert not requests  # Installation/session checks must never call a provider.
        key = "sk-coder-native-fixture"
        service.dispatch("providers.credentials.set", {"provider": "openai", "key": key})
        job = wait_job(
            service,
            service.dispatch(
                "tasks.start",
                {
                    "project": project["id"],
                    "harness": route["id"],
                    "prompt": "Say coder-native-ok",
                    "model": "openai:gpt-4.1",
                },
            )["id"],
        )
        assert job["status"] == "completed", job
        assert job["result"]["protocol"] == "ACP"
        assert job["result"]["acp_continuity"] is True
        assert len(requests) == 1 and requests[0]["path"] == "/v1/responses"
        assert requests[0]["authorization"] == "Bearer " + key
        assert key not in json.dumps(job)
    finally:
        service.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
