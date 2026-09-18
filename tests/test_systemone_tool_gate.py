"""Tool-gate pack, compose, and fixture traces. No model, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from superqode.session.factory import FACTORY_ROUTES
from superqode.systemone.client import StubSystemOneClient, SystemOneTimeout
from superqode.systemone.compose import GateAction, compose_tool_gate, evaluate_tool_gate
from superqode.systemone.pack import builtin_pack_ids, load_pack
from superqode.systemone.state import DIFF_CHARS, ToolGateState

TRACES_DIR = Path(__file__).parent / "fixtures" / "systemone" / "traces"
TRACE_PATHS = sorted(TRACES_DIR.glob("*.json"))


def _load_trace(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_builtin_packs_load():
    ids = builtin_pack_ids()
    assert ids == ("factory_route", "rubric", "tool_gate")
    for pack_id in ids:
        pack = load_pack(pack_id)
        assert pack.id == pack_id
        assert pack.questions
        assert pack.content_hash().startswith("sha256:")
        assert pack.content_hash() == load_pack(pack_id).content_hash()


def test_factory_route_pack_matches_factory_presets():
    pack = load_pack("factory_route")
    assert pack.questions["route"].type == "choice"
    assert set(pack.questions["route"].options) == set(FACTORY_ROUTES)


def test_rubric_pack_matches_grader_verdicts():
    from superqode.agent.rubric import VERDICTS

    pack = load_pack("rubric")
    assert pack.questions["verdict"].type == "choice"
    assert set(pack.questions["verdict"].options) == set(VERDICTS)


def test_tool_gate_pack_has_the_six_questions():
    pack = load_pack("tool_gate")
    assert set(pack.questions) == {
        "in_grant",
        "args_plausible",
        "destructive",
        "exfil_risk",
        "on_task",
        "disposition",
    }
    assert pack.questions["disposition"].type == "choice"
    assert set(pack.questions["disposition"].options) == {"allow", "deny", "ask"}
    assert pack.thresholds.deny_noul == 0.7


def test_tool_gate_state_clips_diff_and_omits_none():
    state = ToolGateState(
        tool="edit",
        arguments={"path": "a.py"},
        last_diff="x" * (DIFF_CHARS + 50),
    )
    payload = state.to_payload()
    assert payload["last_diff"].endswith("…")
    assert len(payload["last_diff"]) == DIFF_CHARS
    assert "secret" not in payload


@pytest.mark.parametrize("path", TRACE_PATHS, ids=lambda p: p.stem)
async def test_tool_gate_fixture_trace(path: Path):
    trace = _load_trace(path)
    pack = load_pack("tool_gate")
    state = ToolGateState.model_validate(trace["state"])
    client = StubSystemOneClient(trace.get("answers") or {})
    decision = await evaluate_tool_gate(
        client,
        state,
        pack,
        hard_deny=bool(trace.get("hard_deny")),
        skipped=bool(trace.get("skipped")),
    )
    assert decision.action == GateAction(trace["expect"]), (
        f"{trace['id']}: {decision.action.value} != {trace['expect']} ({decision.reason})"
    )
    if trace.get("hard_deny") or trace.get("skipped"):
        assert decision.skipped_client is True
        assert client.calls == []
    else:
        assert decision.skipped_client is False
        assert len(client.calls) == 1
    meta = decision.metadata()
    assert meta["permission"] == "systemone"
    assert meta["pack"].startswith("tool_gate@")
    assert meta["pack_hash"].startswith("sha256:")


async def test_hard_deny_never_calls_the_client():
    pack = load_pack("tool_gate")
    client = StubSystemOneClient(
        {
            "disposition": {
                "choice": "allow",
                "probabilities": {"allow": 1.0, "deny": 0.0, "ask": 0.0},
                "confidence": 1.0,
            }
        }
    )
    state = ToolGateState(tool="bash", arguments={"command": "git push origin main"})
    decision = await evaluate_tool_gate(client, state, pack, hard_deny=True)
    assert decision.action is GateAction.DENY
    assert decision.reason == "hard_deny"
    assert decision.skipped_client is True
    assert client.calls == []


async def test_timeout_fail_opens_to_ask():
    pack = load_pack("tool_gate")
    client = StubSystemOneClient(error=SystemOneTimeout("stub timeout"))
    state = ToolGateState(tool="bash", arguments={"command": "pytest"})
    decision = await evaluate_tool_gate(client, state, pack)
    assert decision.action is GateAction.ASK
    assert decision.reason == "client_error"
    assert "timeout" in decision.message.lower()


async def test_airplane_skip_fail_opens_to_ask_without_a_call():
    pack = load_pack("tool_gate")
    client = StubSystemOneClient()
    state = ToolGateState(tool="bash", arguments={"command": "pytest"})
    decision = await evaluate_tool_gate(client, state, pack, skipped=True, skip_reason="airplane")
    assert decision.action is GateAction.ASK
    assert decision.reason == "airplane"
    assert decision.skipped_client is True
    assert client.calls == []


async def test_schema_violation_fail_opens_to_ask():
    pack = load_pack("tool_gate")
    client = StubSystemOneClient({"disposition": {"choice": "ship_it"}})
    state = ToolGateState(tool="bash", arguments={"command": "pytest"})
    decision = await evaluate_tool_gate(client, state, pack)
    assert decision.action is GateAction.ASK
    assert decision.reason == "client_error"


async def test_compose_uses_pack_thresholds():
    pack = load_pack("tool_gate")
    client = StubSystemOneClient(
        {
            "in_grant": {"noul": 0.95},
            "args_plausible": {"noul": 0.95},
            "destructive": {"noul": 0.71},
            "exfil_risk": {"noul": 0.01},
            "on_task": {"noul": 0.95},
            "disposition": {
                "choice": "allow",
                "probabilities": {"allow": 1.0, "deny": 0.0, "ask": 0.0},
                "confidence": 0.99,
            },
        }
    )
    answers = await client.evaluate({"tool": "bash"}, pack.questions)
    decision = compose_tool_gate(answers, pack)
    assert decision.action is GateAction.DENY
    assert decision.reason == "destructive"
    assert decision.nouls["destructive"] == 0.71
