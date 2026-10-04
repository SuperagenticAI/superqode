"""Actual inbound SDK requests must cross entitlement and credit admission."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("a2a.server.routes")
from fastapi.testclient import TestClient
from superqode.a2a.billing import CreditLedger
from superqode.a2a.keys import mint_key, decide_access
from superqode.a2a.server import A2AServer, A2AServerConfig
from superqode.harness import DirectPythonHarnessAdapter, HarnessProtocolController
from superqode.harness.store import MemoryHarnessStore

SECRET = "a-test-secret-long-enough-for-customer-key-signing"


def request(message, task=None):
    value = {
        "message": {
            "messageId": message,
            "role": "ROLE_USER",
            "parts": [{"text": message}],
            "metadata": {"superqodeSkill": "superqode-harness"},
        },
        "configuration": {"acceptedOutputModes": ["text/plain"]},
    }
    if task:
        value["message"]["contextId"] = task["contextId"]
    return value


def test_unentitled_keys_refuse_before_creating_sessions_and_settle_once(tmp_path):
    invocations = []

    async def handler(message, session):
        invocations.append(session.session_id)
        return "verified local result"

    store = MemoryHarnessStore()
    controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("test", handler)], store=store
    )
    path = tmp_path / "credits.sqlite3"
    server = A2AServer(
        controller,
        A2AServerConfig(
            provider="test",
            model="test",
            working_directory=Path("."),
            key_secret=SECRET,
            credit_store_path=path,
            require_harness_entitlement=True,
            understand_requests=True,
            task_store_path=tmp_path / "tasks.sqlite3",
        ),
    )
    ledger = CreditLedger(path)
    token, _ = mint_key("trial", secret=SECRET)
    headers = {"A2A-Version": "1.0", "Authorization": f"Bearer {token}"}
    client = TestClient(server.app)
    denied = client.post("/message:send", headers=headers, json=request("unentitled")).json()[
        "task"
    ]
    assert denied["status"]["state"] == "TASK_STATE_FAILED"
    assert invocations == [] and controller.store.list_sessions() == []
    anon = client.post(
        "/message:send", headers={"A2A-Version": "1.0"}, json=request("anonymous")
    ).json()["task"]
    assert anon["status"]["state"] == "TASK_STATE_FAILED" and invocations == []
    ledger.grant("trial", 1, skills=["superqode-harness"], expires_at=time.time() + 100)
    accepted = client.post("/message:send", headers=headers, json=request("entitled")).json()[
        "task"
    ]
    assert accepted["status"]["state"] == "TASK_STATE_COMPLETED"
    assert len(invocations) == 1 and ledger.account("trial")["available"] == 0
    for _ in range(2):
        assert client.get(f"/tasks/{accepted['id']}", headers=headers).status_code == 200
    assert ledger.account("trial")["balance"] == 0 and ledger.account("trial")["reserved"] == 0
    denied = client.post(
        "/message:send", headers=headers, json=request("exhausted", accepted)
    ).json()["task"]
    assert denied["status"]["state"] == "TASK_STATE_FAILED" and len(invocations) == 1
    other, _ = mint_key("other", secret=SECRET)
    assert client.get(
        f"/tasks/{accepted['id']}",
        headers={"A2A-Version": "1.0", "Authorization": f"Bearer {other}"},
    ).status_code in {403, 404}


def test_signed_operator_tier_never_grants_operator_exemption():
    token, _ = mint_key("customer", tier="operator", secret=SECRET)
    decision = decide_access(f"Bearer {token}", secret=SECRET)
    assert decision.allowed and decision.tier != "operator"


def test_credit_reconciliation_persists_reason(tmp_path):
    ledger = CreditLedger(tmp_path / "ledger.sqlite3")
    ledger.grant("paid", 2, skills=["review"], expires_at=time.time() + 100)
    ledger.reserve("paid", "uncertain", "fingerprint", skill="review", credits=2)
    ledger.settle("paid", "uncertain", 0, reason="Peer confirmed no model call")
    with ledger.transaction() as conn:
        row = conn.execute("select data from a2a_credit_audit where action='settle'").fetchone()
    assert "Peer confirmed no model call" in row[0]
    assert ledger.account("paid")["available"] == 2


async def test_standard_a2a_client_can_execute_native_one_tool_rlm(tmp_path):
    import httpx
    from superqode.a2a.client import A2AClient
    from superqode.pipy.ai import FakeStream, tool_response, text_response
    from superqode.pipy import ToolCall
    from superqode.pipy.stream import Model
    from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions
    from superqode.harness.rlm_adapter import RLMHarnessProtocolAdapter

    (tmp_path / "evidence.txt").write_text("selected evidence")

    async def factory(request, cwd, path):
        return await RLMCodingSession.create(
            RLMCodingSessionOptions(
                cwd=cwd,
                session_root=tmp_path / "sessions",
                model=Model(id="fake", provider="fake"),
                stream_fn=FakeStream(
                    [
                        tool_response(
                            ToolCall("py", "python", {"code": 'context.read("evidence.txt")'})
                        ),
                        text_response("Evidence verified in native RLM"),
                    ]
                ),
                durable_children=False,
            )
        )

    adapter = RLMHarnessProtocolAdapter(session_factory=factory)
    controller = HarnessProtocolController([adapter], store=MemoryHarnessStore())
    server = A2AServer(
        controller,
        A2AServerConfig(
            url="http://test",
            working_directory=tmp_path,
            provider="fake",
            model="fake",
            task_store_path=None,
        ),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app)) as http:
        client = A2AClient("http://test", http_client=http)
        response = await client.send_message("Inspect the evidence")
        assert response.status.state.value == "completed"
        assert response.artifacts[0].parts[0].text == "Evidence verified in native RLM"
        assert len(adapter._sessions) == 1
        for ref in list(adapter._refs.values()):
            assert [
                tool.name for tool in adapter._sessions[ref.session_id].harness.get_tools()
            ] == ["python"]
            await adapter.close(ref)


def test_paid_native_factory_caps_specialist_and_refuses_host_root():
    from superqode.a2a.server import _hosted_rlm_specialist
    from superqode.harness.templates import rlm_template, rlm_monty_template

    with pytest.raises(ValueError, match="isolated"):
        _hosted_rlm_specialist(rlm_template())
    bounded = _hosted_rlm_specialist(rlm_monty_template())
    assert bounded.runtime.config["max_depth"] == 0
    assert bounded.runtime.config["subcall_max_calls"] <= 16
    assert bounded.runtime.config["subcall_max_prompt_chars"] <= 32000
    assert bounded.runtime.config["a2a"]["enabled"] is False


def test_hosted_tariff_cannot_exceed_declared_client_credit_ceiling(tmp_path):
    calls = []

    async def handler(message, session):
        calls.append(message.content)
        return "result"

    controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("test", handler)], store=MemoryHarnessStore()
    )
    path = tmp_path / "credits.sqlite3"
    ledger = CreditLedger(path)
    ledger.grant("paid", 10, skills=["superqode-harness"], expires_at=time.time() + 60)
    server = A2AServer(
        controller,
        A2AServerConfig(
            key_secret=SECRET,
            credit_store_path=path,
            require_harness_entitlement=True,
            harness_credit_cost=2,
            task_store_path=None,
        ),
    )
    key, _ = mint_key("paid", secret=SECRET)
    payload = request("budgeted")
    payload["message"]["metadata"].update({"superqodeBudgetVersion": 1, "superqodeMaxCredits": 1})
    response = (
        TestClient(server.app)
        .post(
            "/message:send",
            headers={"A2A-Version": "1.0", "Authorization": f"Bearer {key}"},
            json=payload,
        )
        .json()["task"]
    )
    assert response["status"]["state"] == "TASK_STATE_FAILED" and calls == []
    assert ledger.account("paid")["available"] == 10
    payload = request("compatible budget")
    payload["message"]["metadata"].update({"superqodeBudgetVersion": 1, "superqodeMaxCredits": 2})
    response = (
        TestClient(server.app)
        .post(
            "/message:send",
            headers={"A2A-Version": "1.0", "Authorization": f"Bearer {key}"},
            json=payload,
        )
        .json()["task"]
    )
    assert response["status"]["state"] == "TASK_STATE_COMPLETED" and len(calls) == 1
    assert ledger.account("paid")["available"] == 8
