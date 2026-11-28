"""Connection policies, pre-task fallback and desktop session version boundaries."""

import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest

from superqode.acp.client import ACPClient
from superqode.acp.client_v2 import V1FallbackRequired
from superqode.acp.protocol import ProtocolError, protocol_policy
from superqode.desktop_service.connection_probe import probe_route
from test_acp_v2 import client
from test_desktop_service import desktop, wait_job  # noqa: F401

FIXTURE = Path(__file__).parent / "fixtures" / "acp_v2_agent.py"


@pytest.mark.parametrize("policy,version", [("auto", 2), ("v1", 1), ("v2", 2)])
async def test_explicit_policy_negotiates_the_requested_version(
    tmp_path, monkeypatch, policy, version
):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    instance = client(tmp_path, version=version, protocol_policy=policy)
    try:
        assert await instance.start(), instance.last_startup_error
        assert await instance.send_prompt("hello") == "end_turn"
        info = instance.get_initialization_info()
        assert info["protocol_policy"] == policy
        assert info["requested_protocol_version"] == info["negotiated_protocol_version"] == version
        assert not info["fallback"]
    finally:
        await instance.stop()


async def test_auto_fallback_reports_reason_and_strict_v2_does_not_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    for policy in ["auto", "v2"]:
        instance = client(tmp_path, v1_only=True, protocol_policy=policy)
        try:
            assert await instance.start() == (policy == "auto"), instance.last_startup_error
            if policy == "auto":
                info = instance.get_initialization_info()
                assert info["requested_protocol_version"] == 2
                assert info["negotiated_protocol_version"] == 1
                assert info["fallback"] and "selected ACP v1" in info["fallback_reason"]
            else:
                assert "v2 is required" in instance.last_startup_error
                assert not instance._v1_fallback
        finally:
            await instance.stop()


@pytest.mark.parametrize("code,allow_fallback", [(-32022, True), (-32000, False), (-32602, False)])
async def test_fallback_only_handles_explicit_protocol_rejection(tmp_path, code, allow_fallback):
    instance = ACPClient(tmp_path, "unused", protocol_policy="auto")
    instance._call_method = AsyncMock(side_effect=ProtocolError(code, "fixture"))
    with pytest.raises(V1FallbackRequired if allow_fallback else ProtocolError):
        await instance._initialize_v2()
    assert instance._call_method.await_count == 1


def test_invalid_or_conflicting_policies_are_rejected():
    for policy in ["best", 2, False, {}]:
        with pytest.raises(ValueError):
            protocol_policy(policy)
    with pytest.raises(ValueError):
        ACPClient(Path.cwd(), "unused", protocol_policy="v1", protocol_version=2)
    with pytest.raises(ValueError):
        ACPClient(Path.cwd(), "unused", protocol_policy="v2", session_protocol_version=1)


async def test_auto_pins_existing_v1_session_during_reconnect(tmp_path):
    instance = ACPClient(tmp_path, "unused", protocol_policy="auto")
    instance._session_id = "existing"
    instance.negotiated_version = 1
    instance.stop = AsyncMock()
    instance._initialize_traffic_log = AsyncMock()

    # A real process is unnecessary: verify the binding passed into startup.
    async def start():
        assert instance.resume_session_id == "existing"
        assert instance.session_protocol_version == 1
        assert instance.require_resume
        return True

    instance.start = start
    assert await instance.reconnect()


def register_route(desktop, *, v1_only=False):
    service, project, root = desktop
    argv = [sys.executable, str(FIXTURE), str(root / "agent.sqlite3")]
    if v1_only:
        argv.append("--v1-only")
    return service.dispatch(
        "connect.acp.custom.save",
        {
            "project": project["id"],
            "name": "Protocol policy fixture",
            "argv": argv,
        },
    )


def test_setup_check_honors_selected_policy_without_sending_prompt(desktop, monkeypatch):
    service, project, root = desktop
    monkeypatch.setenv("SUPERQODE_HOME", str(root / "home"))
    route = register_route(desktop, v1_only=True)
    auto = asyncio.run(probe_route(root, route, lambda _: None, protocol_policy="auto"))
    assert auto["connected"] and auto["protocol_policy"] == "auto"
    assert auto["initialization"]["negotiated_protocol_version"] == 1
    assert auto["initialization"]["fallback"]
    with pytest.raises(ValueError, match="v2 is required"):
        asyncio.run(probe_route(root, route, lambda _: None, protocol_policy="v2"))
    assert not service.dispatch("jobs.list", {})


def test_policy_switch_uses_fresh_session_and_preserves_conversation(desktop, monkeypatch):
    service, project, root = desktop
    monkeypatch.setenv("SUPERQODE_HOME", str(root / "home"))
    route = register_route(desktop)
    request = {"project": project["id"], "harness": route["id"], "prompt": "first"}
    first = wait_job(
        service,
        service.dispatch(
            "tasks.start",
            {
                **request,
                "acp_options": {"protocol_policy": "auto"},
            },
        )["id"],
    )
    assert first["status"] == "completed", first
    wire = next(
        row["data"]["payload"]
        for row in first["events"]
        if row.get("data", {}).get("event") == "acp_session"
    )
    assert wire["protocol_policy"] == "auto" and wire["negotiated_protocol_version"] == 2
    assert wire["session_id"] == first["result"]["session_id"]
    second = wait_job(
        service,
        service.dispatch(
            "tasks.start",
            {
                **request,
                "prompt": "next",
                "parent_id": first["id"],
                "acp_options": {"protocol_policy": "v1"},
            },
        )["id"],
    )
    assert second["status"] == "completed", second
    assert second["result"]["protocol_version"] == 1
    assert second["result"]["session_id"] != first["result"]["session_id"]
    assert second["request"]["_continuity"]["mode"] == "handoff"
    assert second["request"]["_continuity"]["protocol_switch"]
    assert second["conversation_id"] == first["conversation_id"]
    assert "session_id" not in second["request"]


def test_auto_continuation_keeps_negotiated_v1_binding(desktop, monkeypatch):
    service, project, root = desktop
    monkeypatch.setenv("SUPERQODE_HOME", str(root / "home"))
    fixture = Path(__file__).parent / "fixtures" / "desktop_acp_agent.py"
    route = service.dispatch(
        "connect.acp.custom.save",
        {
            "project": project["id"],
            "name": "Resumable v1 fixture",
            "argv": [sys.executable, str(fixture)],
        },
    )
    request = {
        "project": project["id"],
        "harness": route["id"],
        "prompt": "controls",
        "acp_options": {"protocol_policy": "auto", "protocol_version": 2},
    }
    first = wait_job(service, service.dispatch("tasks.start", request)["id"])
    assert first["status"] == "completed", first
    assert first["result"]["protocol_status"]["fallback"]
    second = wait_job(
        service, service.dispatch("tasks.start", {**request, "parent_id": first["id"]})["id"]
    )
    assert second["status"] == "completed", second
    assert second["request"]["_continuity"]["mode"] == "resume"
    assert second["request"]["_acp_resume_protocol_version"] == 1
    assert second["result"]["session_id"] == first["result"]["session_id"]
    info = second["result"]["protocol_status"]
    assert info["protocol_policy"] == "auto" and info["preferred_protocol_version"] == 2
    assert info["requested_protocol_version"] == info["negotiated_protocol_version"] == 1
    assert info["resumed_protocol"] == 1 and not info["fallback"]


@pytest.mark.parametrize("policy,version", [("auto", 2), ("v1", 1), ("v2", 2)])
def test_service_probe_forwards_policy_and_never_creates_a_task(
    desktop, monkeypatch, policy, version
):
    from test_desktop_acp_setup import wait_action

    service, project, root = desktop
    monkeypatch.setenv("SUPERQODE_HOME", str(root / "home"))
    route = register_route(desktop)
    operation = service.dispatch(
        "connect.auth.start",
        {
            "action": "probe",
            "project": project["id"],
            "reference": route["id"],
            "protocol_policy": policy,
        },
    )
    result = wait_action(service, operation)
    assert result["state"] == "completed", result
    metadata = result["result"]
    assert metadata["connected"] and metadata["protocol_policy"] == policy
    assert metadata["project_id"] == project["id"]
    assert metadata["initialization"]["negotiated_protocol_version"] == version
    assert not service.dispatch("jobs.list", {})


def test_runtime_error_never_falls_back_or_resubmits(desktop, monkeypatch):
    import sqlite3

    service, project, root = desktop
    monkeypatch.setenv("SUPERQODE_HOME", str(root / "home"))
    route = register_route(desktop)
    job = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": route["id"],
            "prompt": "error",
            "acp_options": {"protocol_policy": "auto"},
        },
    )
    result = wait_job(service, job["id"])
    assert result["status"] == "failed", result
    with sqlite3.connect(root / "agent.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM insertions").fetchone()[0] == 1
    sessions = [
        row for row in result["events"] if row.get("data", {}).get("event") == "acp_session"
    ]
    assert len(sessions) == 1
    assert sessions[0]["data"]["payload"]["negotiated_protocol_version"] == 2
