"""Opt-in System One gate on the native permission path. Stub only, no network."""

from __future__ import annotations

import pytest

from superqode.agent.hooks import HookRegistry
from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.harness.spec import HarnessSpec, SystemOneSpec
from superqode.systemone.client import StubSystemOneClient
from superqode.systemone.config import LIVE_API_KEY_ENV, SYSTEMONE_ENV
from superqode.systemone.pack import load_pack
from superqode.tools.base import ToolRegistry
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager


@pytest.fixture(autouse=True)
def _isolate_systemone_environment(monkeypatch):
    """Loop tests use explicit modes and never call the network."""
    monkeypatch.delenv(LIVE_API_KEY_ENV, raising=False)
    monkeypatch.delenv("SUPERQODE_SYSTEMONE_MODE", raising=False)
    monkeypatch.delenv("SUPERQODE_SYSTEMONE_TRACE_DIR", raising=False)


_ALLOW_ANSWERS = {
    "in_grant": {"noul": 0.95},
    "args_plausible": {"noul": 0.94},
    "destructive": {"noul": 0.04},
    "exfil_risk": {"noul": 0.03},
    "on_task": {"noul": 0.93},
    "disposition": {
        "choice": "allow",
        "probabilities": {"allow": 0.90, "deny": 0.04, "ask": 0.06},
        "confidence": 0.88,
    },
}

_DENY_ANSWERS = {
    "in_grant": {"noul": 0.90},
    "args_plausible": {"noul": 0.70},
    "destructive": {"noul": 0.86},
    "exfil_risk": {"noul": 0.05},
    "on_task": {"noul": 0.40},
    "disposition": {
        "choice": "deny",
        "probabilities": {"allow": 0.05, "deny": 0.85, "ask": 0.10},
        "confidence": 0.82,
    },
}


def _loop(tmp_path, *, spec=None, systemone=None, client=None, default=Permission.ALLOW):
    loop = AgentLoop.__new__(AgentLoop)
    loop.config = AgentConfig(
        provider="x",
        model="y",
        working_directory=tmp_path,
        harness_spec=spec,
        systemone=systemone,
    )
    loop.hooks = HookRegistry()
    loop.session_id = "t"
    loop._current_iteration = 0
    loop._current_messages = []
    loop.last_turn_diff = ""
    loop.permission_manager = PermissionManager(PermissionConfig(default=default))
    loop._approved_tool_call_ids = set()
    loop.pause_on_approval = False
    loop.tools = ToolRegistry.empty()
    loop._systemone_client = client
    return loop


@pytest.mark.asyncio
async def test_systemone_disabled_by_default_does_not_call_client(tmp_path):
    client = StubSystemOneClient(_DENY_ANSWERS)
    loop = _loop(tmp_path, client=client)
    result = await loop._check_tool_permission("bash", {"command": "echo hi"})
    assert result is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_systemone_deny_blocks_auto_allow_and_stores_metadata(tmp_path):
    client = StubSystemOneClient(_DENY_ANSWERS)
    loop = _loop(tmp_path, systemone=SystemOneSpec(enabled=True), client=client)
    denied = await loop._check_tool_permission("bash", {"command": "echo hi"})
    assert denied is not None
    assert denied.success is False
    assert denied.metadata["permission"] == "systemone"
    assert denied.metadata["pack"].startswith("tool_gate@")
    assert denied.metadata["reason"] == "destructive"
    assert denied.metadata["nouls"]["destructive"] >= 0.7
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_systemone_allow_preapproves_ask(tmp_path):
    client = StubSystemOneClient(_ALLOW_ANSWERS)
    loop = _loop(
        tmp_path,
        systemone=SystemOneSpec(enabled=True),
        client=client,
        default=Permission.ASK,
    )
    result = await loop._check_tool_permission("bash", {"command": "pytest"})
    assert result is None
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_yaml_deny_never_calls_systemone(tmp_path, monkeypatch):
    policy_file = tmp_path / "execpolicy.yaml"
    policy_file.write_text(
        "rules:\n  - pattern: 'git push*'\n    action: deny\n    reason: no push\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUPERQODE_EXEC_POLICY", str(policy_file))
    client = StubSystemOneClient(_ALLOW_ANSWERS)
    loop = _loop(tmp_path, systemone=SystemOneSpec(enabled=True), client=client)
    denied = await loop._check_tool_permission("bash", {"command": "git push origin main"})
    assert denied is not None
    assert denied.metadata["permission"] == "exec_policy_deny"
    assert client.calls == []


@pytest.mark.asyncio
async def test_airplane_skips_systemone_silently(tmp_path):
    spec = HarnessSpec(
        name="offline",
        metadata={"airplane_mode": True},
        systemone=SystemOneSpec(enabled=True),
    )
    client = StubSystemOneClient(_DENY_ANSWERS)
    loop = _loop(tmp_path, spec=spec, client=client)
    result = await loop._check_tool_permission("bash", {"command": "echo hi"})
    assert result is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_env_enables_stub_without_spec(tmp_path, monkeypatch):
    monkeypatch.setenv(SYSTEMONE_ENV, "stub")
    client = StubSystemOneClient(_DENY_ANSWERS)
    loop = _loop(tmp_path, client=client)
    denied = await loop._check_tool_permission("bash", {"command": "echo hi"})
    assert denied is not None
    assert denied.metadata["permission"] == "systemone"


@pytest.mark.asyncio
async def test_live_client_skips_until_a_key_exists(tmp_path):
    client = StubSystemOneClient(_DENY_ANSWERS)
    loop = _loop(
        tmp_path,
        systemone=SystemOneSpec(enabled=True, client="live"),
        client=client,
    )
    result = await loop._check_tool_permission("bash", {"command": "echo hi"})
    assert result is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_uncertain_result_requires_approval_even_with_auto_allow(tmp_path):
    pack = load_pack("tool_gate")
    client = StubSystemOneClient()  # missing answers → ASK
    loop = _loop(tmp_path, systemone=SystemOneSpec(enabled=True), client=client)
    from superqode.agent.loop import ToolApprovalRequired

    loop.pause_on_approval = True
    with pytest.raises(ToolApprovalRequired):
        await loop._check_tool_permission("bash", {"command": "echo hi"}, "call-1")
    assert len(client.calls) == 1
    assert loop.last_systemone_decision["action"] == "ask"
    loop._approved_tool_call_ids.add("call-1")
    assert await loop._check_tool_permission("bash", {"command": "echo hi"}, "call-1") is None
    assert pack.id == "tool_gate"


@pytest.mark.asyncio
async def test_harness_spec_enables_the_gate(tmp_path):
    spec = HarnessSpec(name="core-so", systemone=SystemOneSpec(enabled=True))
    client = StubSystemOneClient(_DENY_ANSWERS)
    loop = _loop(tmp_path, spec=spec, client=client)
    denied = await loop._check_tool_permission("bash", {"command": "echo hi"})
    assert denied is not None
    assert denied.metadata["pack"].startswith("tool_gate@")


@pytest.mark.asyncio
@pytest.mark.parametrize("answers", [_ALLOW_ANSWERS, _DENY_ANSWERS])
async def test_shadow_preserves_auto_allow_and_records_full_answers(tmp_path, answers):
    import json

    client = StubSystemOneClient(answers)
    loop = _loop(
        tmp_path,
        systemone=SystemOneSpec(enabled=True, mode="shadow", trace_dir=str(tmp_path / "traces")),
        client=client,
    )
    assert await loop._check_tool_permission("bash", {"command": "echo token=secret"}, "c1") is None
    event = json.loads(next((tmp_path / "traces").glob("*.json")).read_text())
    assert event["policyAction"] == event["permissionAction"] == "allow"
    assert (
        event["answers"]["disposition"]["probabilities"] == answers["disposition"]["probabilities"]
    )
    assert "secret" not in json.dumps(event)
    assert "humanAction" not in event


@pytest.mark.asyncio
async def test_shadow_allow_cannot_preapprove_policy_ask(tmp_path):
    from superqode.agent.loop import ToolApprovalRequired

    loop = _loop(
        tmp_path,
        systemone=SystemOneSpec(enabled=True, mode="shadow"),
        client=StubSystemOneClient(_ALLOW_ANSWERS),
        default=Permission.ASK,
    )
    loop.pause_on_approval = True
    with pytest.raises(ToolApprovalRequired):
        await loop._check_tool_permission("bash", {"command": "pytest"}, "c1")
    assert loop.last_systemone_decision["intendedAction"] == "allow"
    assert loop.last_systemone_decision["permissionAction"] == "ask"


@pytest.mark.asyncio
async def test_shadow_hard_deny_records_skip_without_model_call(tmp_path, monkeypatch):
    import json

    policy = tmp_path / "policy.yaml"
    policy.write_text("rules:\n  - pattern: 'git push*'\n    action: deny\n")
    monkeypatch.setenv("SUPERQODE_EXEC_POLICY", str(policy))
    client = StubSystemOneClient(_ALLOW_ANSWERS)
    loop = _loop(
        tmp_path,
        systemone=SystemOneSpec(enabled=True, mode="shadow", trace_dir=str(tmp_path / "traces")),
        client=client,
    )
    assert await loop._check_tool_permission("bash", {"command": "git push"}) is not None
    event = json.loads(next((tmp_path / "traces").glob("*.json")).read_text())
    assert client.calls == []
    assert event["intendedAction"] is None
    assert event["evaluation"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_shadow_recording_failure_cannot_change_permissions(tmp_path):
    path = tmp_path / "not-a-directory"
    path.write_text("occupied")
    loop = _loop(
        tmp_path,
        systemone=SystemOneSpec(enabled=True, mode="shadow", trace_dir=str(path)),
        client=StubSystemOneClient(_DENY_ANSWERS),
    )
    assert await loop._check_tool_permission("bash", {"command": "echo hi"}) is None
