"""End-to-end streaming, continuity and acknowledged remote cancellation."""

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from superqode.desktop_service.service import DesktopService


@pytest.fixture(params=["a2a", "uhp"])
def remote(request, tmp_path):
    protocol = request.param
    received = []
    cancel = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, data):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def event(self, name, data):
            self.wfile.write(("event: " + name + "\ndata: " + json.dumps(data) + "\n\n").encode())
            self.wfile.flush()

        def do_GET(self):
            if self.path == "/v1/harnesses":
                self.reply({"data": [{"id": "code", "name": "Coding"}]})
            else:
                self.reply(
                    {
                        "name": "Streaming agent",
                        "description": "Fixture",
                        "url": f"http://127.0.0.1:{self.server.server_port}/rpc",
                        "version": "1",
                        "protocolVersion": "0.3.0",
                        "capabilities": {"streaming": True},
                        "skills": [],
                    }
                )

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or "{}")
            received.append((self.path, body))
            method = body.get("method", "")
            if self.path.endswith("/cancel") or method == "tasks/cancel":
                cancel.set()
                if protocol == "uhp":
                    self.reply({"id": "response-1", "status": "cancelled"})
                else:
                    self.reply(
                        {
                            "jsonrpc": "2.0",
                            "id": body["id"],
                            "result": {
                                "kind": "task",
                                "id": "task-1",
                                "contextId": "conversation-1",
                                "status": {"state": "canceled"},
                            },
                        }
                    )
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if protocol == "uhp":
                self.event(
                    "response.created",
                    {
                        "type": "response.created",
                        "response": {"id": "response-1", "status": "in_progress"},
                    },
                )
                self.event(
                    "response.output_text.delta",
                    {"type": "response.output_text.delta", "delta": "Live coding output"},
                )
                wait = body.get("input") == "wait"
            else:
                self.event(
                    "message",
                    {
                        "jsonrpc": "2.0",
                        "result": {
                            "kind": "status-update",
                            "taskId": "task-1",
                            "contextId": "conversation-1",
                            "status": {"state": "working"},
                        },
                    },
                )
                self.event(
                    "message",
                    {
                        "jsonrpc": "2.0",
                        "result": {
                            "kind": "artifact-update",
                            "taskId": "task-1",
                            "contextId": "conversation-1",
                            "artifact": {
                                "artifactId": "code",
                                "parts": [{"kind": "text", "text": "Live coding output"}],
                            },
                        },
                    },
                )
                wait = body["params"]["message"]["parts"][0]["text"] == "wait"
            if wait:
                cancel.wait(10)
                return
            if protocol == "uhp":
                self.event(
                    "response.completed",
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "response-1",
                            "status": "completed",
                            "session_id": "conversation-1",
                        },
                    },
                )
            else:
                self.event(
                    "message",
                    {
                        "jsonrpc": "2.0",
                        "result": {
                            "kind": "status-update",
                            "taskId": "task-1",
                            "contextId": "conversation-1",
                            "final": True,
                            "status": {"state": "completed"},
                        },
                    },
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    service = DesktopService(tmp_path / "state")
    opened = service.open_project(str(project))
    discovery = service.dispatch(
        "connect.protocol",
        {
            "project": opened["id"],
            "protocol": protocol,
            "url": f"http://127.0.0.1:{server.server_port}",
        },
    )
    route = service.dispatch(
        "connect.protocol.select",
        {"project": opened["id"], "connection": discovery["connection"], "harness": "code"},
    )
    yield service, opened["id"], route["id"], protocol, received, cancel
    service.close()
    cancel.set()
    server.shutdown()
    server.server_close()


def wait(service, identity, terminal=True):
    for _ in range(300):
        record = service.dispatch("jobs.get", {"id": identity})
        if terminal and record["status"] not in {"running", "needs_approval", "cancelling"}:
            return record
        if not terminal and any(
            e["type"] == "harness_event" and e["data"]["event"] == "message.delta"
            for e in record["events"]
        ):
            return record
        time.sleep(0.03)
    pytest.fail(str(record))


def test_live_stream_is_visible_before_completion_and_cancel_is_acknowledged(remote):
    service, project, route, _, received, cancellation = remote
    identity = service.dispatch(
        "tasks.start",
        {"project": project, "harness": route, "prompt": "wait", "command_id": "cancel-test"},
    )["id"]
    record = wait(service, identity, terminal=False)
    assert record["status"] == "running"
    assert "Live coding output" in json.dumps(record["events"])
    result = service.dispatch("jobs.cancel", {"id": identity})
    assert result["state"] == "cancelling"
    finished = wait(service, identity)
    assert finished["status"] == "cancelled", finished
    assert finished["result"]["remote_cancel_acknowledged"]
    assert cancellation.is_set()
    assert len(received) == 2


def test_streamed_conversation_continues_without_replay(remote):
    service, project, route, protocol, received, _ = remote
    first = service.dispatch(
        "tasks.start",
        {"project": project, "harness": route, "prompt": "code", "command_id": "first"},
    )["id"]
    result = wait(service, first)
    assert result["status"] == "completed", result
    assert result["result"]["remote_continuity"]
    second = service.dispatch(
        "tasks.start",
        {
            "project": project,
            "harness": route,
            "prompt": "follow up",
            "parent_id": first,
            "command_id": "second",
        },
    )["id"]
    assert wait(service, second)["status"] == "completed"
    assert len(received) == 2
    if protocol == "uhp":
        assert received[-1][1]["previous_response_id"] == "response-1"
    else:
        assert received[-1][1]["params"]["message"]["contextId"] == "conversation-1"


def test_reconnecting_after_app_restart_preserves_remote_route_and_context(remote):
    service, project, route, protocol, received, _ = remote
    first = service.dispatch(
        "tasks.start",
        {"project": project, "harness": route, "prompt": "code", "command_id": "before-restart"},
    )["id"]
    record = wait(service, first)
    assert record["status"] == "completed"
    endpoint = record["request"]["_desktop_connection"]["url"]
    service.close()
    restored = DesktopService(service.root)
    try:
        routes = restored.dispatch("routes.list", {"project": project})
        assert next(r for r in routes if r["id"] == route)["available"] is False
        discovery = restored.dispatch(
            "connect.protocol", {"project": project, "protocol": protocol, "url": endpoint}
        )
        reconnected = restored.dispatch(
            "connect.protocol.select",
            {"project": project, "connection": discovery["connection"], "harness": "code"},
        )
        assert reconnected["id"] == route
        second = restored.dispatch(
            "tasks.start",
            {
                "project": project,
                "harness": route,
                "prompt": "follow-up",
                "parent_id": first,
                "command_id": "after-restart",
            },
        )["id"]
        assert wait(restored, second)["status"] == "completed"
        assert len(received) == 2
    finally:
        restored.close()
