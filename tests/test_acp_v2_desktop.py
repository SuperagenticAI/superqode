"""Desktop v2 transport lifetime, native approvals, host MCP and transcript fidelity."""

import asyncio
from pathlib import Path
import sys
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from test_desktop_service import desktop, wait_job  # noqa: F401
from superqode.acp.protocol import ProtocolError
from superqode.desktop_service.acp_worker import DesktopACPClient
from superqode.desktop_service.acp_mcp import HostMcpBridge
from superqode.desktop_service.conversations import visible_answer

FIXTURE = Path(__file__).parent / "fixtures" / "acp_v2_agent.py"


def route(desktop):
    service, project, root = desktop
    return service.dispatch(
        "connect.acp.custom.save",
        {
            "project": project["id"],
            "name": "V2 fixture",
            "argv": [sys.executable, str(FIXTURE), str(root / "agent.sqlite3")],
        },
    )


def test_v2_native_worker_keeps_child_transcripts_separate(desktop):
    service, project, root = desktop
    agent = route(desktop)
    job = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": agent["id"],
            "prompt": "child",
            "acp_options": {"protocol_version": 2, "config": {"thoughts": False}},
        },
    )
    result = wait_job(service, job["id"])
    assert result["status"] == "completed", result
    assert result["result"]["protocol_version"] == 2
    assert visible_answer(result["events"]) == "answer:child"
    assert any(row.get("data", {}).get("event") == "acp_update" for row in result["events"])


def test_foreground_completion_does_not_stop_background_worker(desktop):
    service, project, root = desktop
    agent = route(desktop)
    job = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": agent["id"],
            "prompt": "background",
            "acp_options": {"protocol_version": 2},
        },
    )
    deadline = time.monotonic() + 10
    current = None
    while time.monotonic() < deadline:
        current = service.dispatch("jobs.get", {"id": job["id"]})
        if any(row["type"] == "foreground_complete" for row in current["events"]):
            break
        time.sleep(0.02)
    assert current["status"] == "running", current
    assert not current.get("result")
    foreground = next(
        row["data"] for row in current["events"] if row["type"] == "foreground_complete"
    )
    service.dispatch(
        "jobs.acp.control",
        {
            "id": job["id"],
            "action": "tool",
            "session_id": foreground["session_id"],
            "item_id": "fixture-bg",
        },
    )
    finished = wait_job(service, job["id"])
    assert finished["status"] == "completed", finished
    assert any(
        row["type"] == "acp_control" and row["data"].get("accepted") for row in finished["events"]
    )


async def test_removed_v1_methods_cannot_write_before_v2_dispatch(tmp_path):
    instance = DesktopACPClient(tmp_path, "unused", protocol_version=2)
    instance.negotiated_version = 2
    instance.on_permission_request = AsyncMock(return_value="allow")
    with pytest.raises(ProtocolError) as error:
        await instance._handle_agent_request(
            "fs/write_text_file", {"path": "must-not-exist", "content": "bad"}
        )
    assert error.value.code == -32601
    assert not (tmp_path / "must-not-exist").exists()
    instance.on_permission_request.assert_not_called()


async def test_host_mcp_requires_auth_and_preserves_root_and_approval(tmp_path):
    permission = AsyncMock(return_value="deny")
    bridge = HostMcpBridge(tmp_path, permission, None)
    try:
        with pytest.raises(PermissionError):
            await bridge.write_text_file("denied", "text")
        assert not (tmp_path / "denied").exists()
        for name in [".env", ".ENV", ".git/config", "../outside"]:
            with pytest.raises(PermissionError):
                await bridge.write_text_file(name, "text")
        permission.return_value = "allow"
        await bridge.write_text_file("allowed.txt", "safe")
        assert await bridge.read_text_file("allowed.txt") == "safe"
        config = await bridge.start()
        async with httpx.AsyncClient() as http:
            response = await http.post(
                config["url"],
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
            assert response.status_code == 401
            headers = {
                "Authorization": "Bearer " + bridge.token,
                "Accept": "application/json, text/event-stream",
            }
            response = await http.post(
                config["url"],
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
            assert response.status_code == 200, response.text
            assert "result" in response.json()
    finally:
        await bridge.close()


def test_whole_response_snapshots_replace_in_saved_transcript():
    def event(name, value):
        return {"type": "harness_event", "data": {"event": name, "payload": value}}

    assert (
        visible_answer(
            [
                event("acp_message", {"text": "old"}),
                event(
                    "acp_update",
                    {
                        "sessionId": "child",
                        "update": {
                            "sessionUpdate": "agent_message",
                            "content": [{"type": "text", "text": "child"}],
                        },
                    },
                ),
                event("acp_message", {"text": "new"}),
            ]
        )
        == "new"
    )
    assert (
        visible_answer([event("acp_message", {"text": "old"}), event("acp_message", {"text": ""})])
        == ""
    )
