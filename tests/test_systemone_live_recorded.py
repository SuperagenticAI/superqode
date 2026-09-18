"""Recorded live tool_gate bake-off. Skips without TYPESAFE_API_KEY.

First key spend: three frozen traces, pin jev-1.13.0, write request/response
and the composed verdict. YAML deny is asserted with zero HTTP.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from superqode.systemone.compose import GateAction, evaluate_tool_gate
from superqode.systemone.config import DEFAULT_MODEL, LIVE_API_KEY_ENV
from superqode.systemone.live import LiveSystemOneClient
from superqode.systemone.pack import load_pack
from superqode.systemone.state import REDACTED, ToolGateState

TRACES = Path(__file__).parent / "fixtures" / "systemone" / "traces"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get(LIVE_API_KEY_ENV, "").strip(),
        reason=f"{LIVE_API_KEY_ENV} is unset; skipping recorded live evaluate",
    ),
]


def _load(name: str) -> dict:
    return json.loads((TRACES / f"{name}.json").read_text(encoding="utf-8"))


def _record_root(tmp_path: Path) -> Path:
    override = os.environ.get("SYSTEMONE_LIVE_RECORD_DIR", "").strip()
    root = Path(override) if override else tmp_path / "systemone-live"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.mark.parametrize(
    ("trace_id", "allowed"),
    [
        ("pytest-on-repo", {GateAction.ALLOW, GateAction.ASK}),
        ("make-deploy", {GateAction.ASK, GateAction.DENY}),
        ("curl-token-exfil", {GateAction.DENY, GateAction.ASK}),
    ],
)
async def test_recorded_live_tool_gate(tmp_path, trace_id, allowed):
    pack = load_pack("tool_gate")
    trace = _load(trace_id)
    state = ToolGateState.model_validate(trace["state"])
    record_dir = _record_root(tmp_path) / trace_id
    client = LiveSystemOneClient(
        model=DEFAULT_MODEL,
        timeout_ms=15_000,
        record_dir=record_dir,
    )
    decision = await evaluate_tool_gate(client, state, pack)
    assert decision.skipped_client is False
    assert decision.reason != "client_error", decision.message
    assert decision.action in allowed
    assert len(client.calls) == 1
    assert client.calls[0][1]  # wire questions
    payload = state.to_payload()
    if trace_id == "curl-token-exfil":
        dumped = json.dumps(payload)
        assert "sk-live-secret" not in dumped
        assert REDACTED in dumped

    files = sorted(record_dir.glob("*.json"))
    assert files, "live client did not write a record"
    recorded = json.loads(files[0].read_text(encoding="utf-8"))
    assert recorded["request"]["model"] == DEFAULT_MODEL
    assert set(recorded["request"]["questions"]) == set(pack.questions)
    summary = {
        "id": trace_id,
        "action": decision.action.value,
        "reason": decision.reason,
        "fixture_expect": trace.get("expect"),
        "metadata": decision.metadata(),
        "record": files[0].name,
    }
    (record_dir / "verdict.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


async def test_yaml_deny_does_not_call_live(tmp_path):
    pack = load_pack("tool_gate")
    trace = _load("git-push-yaml-deny")
    state = ToolGateState.model_validate(trace["state"])
    client = LiveSystemOneClient(
        model=DEFAULT_MODEL,
        timeout_ms=15_000,
        record_dir=_record_root(tmp_path) / "git-push-yaml-deny",
    )
    decision = await evaluate_tool_gate(client, state, pack, hard_deny=True)
    assert decision.action is GateAction.DENY
    assert decision.reason == "hard_deny"
    assert decision.skipped_client is True
    assert client.calls == []
    assert list((_record_root(tmp_path) / "git-push-yaml-deny").glob("*.json")) == []
