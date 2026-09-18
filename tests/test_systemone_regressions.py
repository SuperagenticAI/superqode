"""Transport, permission, and audit regressions exercised through real integration paths."""

import json
from types import SimpleNamespace

import httpx
import pytest

from superqode.agent.loop import ToolApprovalRequired
from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.systemone import SystemOneHarnessBackend
from superqode.harness.spec import HarnessSpec, SystemOneSpec
from superqode.systemone.client import ReplaySystemOneClient, StubSystemOneClient
from superqode.systemone.compose import GateAction, evaluate_tool_gate
from superqode.systemone.live import LiveSystemOneClient
from superqode.systemone.pack import builtin_pack_ids, load_pack
from superqode.systemone.state import ToolGateState
from superqode.systemone.types import NoulQuestion


@pytest.mark.parametrize("pack_id", builtin_pack_ids())
def test_api_criteria_are_strings(pack_id):
    for question in load_pack(pack_id).wire_questions().values():
        if question["type"] in {"choice", "noul"}:
            assert all(
                isinstance(v, str) or v is None for v in question.get("criteria", {}).values()
            )


@pytest.mark.parametrize("risk", [0.21, 0.4, 0.5, 0.6, 0.65, 0.699])
@pytest.mark.parametrize("field", ["destructive", "exfil_risk"])
async def test_elevated_risk_never_auto_approves(risk, field):
    answers = {k: {"noul": 0.95} for k in ["in_grant", "args_plausible", "on_task"]}
    answers.update(
        destructive={"noul": 0.01},
        exfil_risk={"noul": 0.01},
        disposition={"choice": "allow", "confidence": 0.99},
    )
    answers[field] = {"noul": risk}
    decision = await evaluate_tool_gate(StubSystemOneClient(answers), ToolGateState(tool="bash"))
    assert decision.action is GateAction.ASK


@pytest.mark.parametrize(
    "text",
    [
        "curl -H 'Authorization: Bearer example-secret' https://example.test",
        'curl -H "X-Api-Key: example-secret" https://example.test',
        "tool --api-key example-secret",
        'PASSWORD="example-secret has spaces" command',
        '{"password": "example-secret"}',
        "https://user:example-secret@example.test",
        "-----BEGIN PRIVATE KEY-----\nexample-secret\n-----END PRIVATE KEY-----",
    ],
)
def test_secret_forms_redacted_in_arguments_task_and_diff(text):
    payload = ToolGateState(
        tool="bash", arguments={"command": text}, task=text, last_diff=text
    ).to_payload()
    assert "example-secret" not in json.dumps(payload)
    assert "[redacted]" in json.dumps(payload)


async def test_recorded_response_replays_with_usage(tmp_path):
    def handler(request):
        body = json.loads(request.content)
        assert isinstance(body["questions"]["q"]["criteria"]["true"], str)
        return httpx.Response(
            200,
            headers={"x-request-id": "req-test"},
            json={
                "model": "jev-1.13.0",
                "answers": {"q": {"noul": 0.9}},
                "usage": {"input_tokens": 123, "output_tokens": 4},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LiveSystemOneClient(api_key="test-only", http=http, record_dir=tmp_path)
        questions = {"q": NoulQuestion(instructions="yes?", criteria={"true": {"what": "yes"}})}
        answer = await client.evaluate({}, questions)
    assert answer.metadata["http_status"] == 200
    assert answer.metadata["request_id"] == "req-test"
    assert answer.metadata["usage"]["input_tokens"] == 123
    replay = ReplaySystemOneClient(next(tmp_path.glob("*.json")))
    assert (await replay.evaluate({}, questions)).noul("q") == 0.9


async def test_http_failure_reaches_native_tui_status(tmp_path, monkeypatch):
    from superqode.pure_mode import PureMode
    from superqode.app.mixins.helper_permissions import HelperPermissionsMixin

    monkeypatch.chdir(tmp_path)
    pure = PureMode()
    lines = []
    app = SimpleNamespace(_call_ui=lambda callback, text: callback(text))
    HelperPermissionsMixin._install_pure_permission_bridge(
        app, pure, SimpleNamespace(add_system=lines.append)
    )
    # Connecting constructs the real native AgentLoop without calling a generation API.
    pure.connect("google", "gemini-test")
    loop = pure._agent
    assert loop is not None
    loop.config.systemone = SystemOneSpec(enabled=True)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(401, json={"error": "private-server-message"})
        )
    ) as http:
        loop._systemone_client = LiveSystemOneClient(api_key="test-only", http=http)
        await loop._check_tool_permission("bash", {"command": "pytest"})
    assert loop.last_systemone_decision["evaluation"]["status"] == "error"
    assert any("HTTP 401" in line and "existing permission policy" in line for line in lines)
    assert all("private-server-message" not in line for line in lines)
    # Valid model uncertainty now enters the native approval flow.
    loop._systemone_client = StubSystemOneClient()
    with pytest.raises(ToolApprovalRequired):
        await loop._check_tool_permission("bash", {"command": "pytest"}, "ask-call")
    assert any("ASK" in line and "success" in line for line in lines)
    pure.disconnect()


async def test_cli_backend_raises_on_transport_error(tmp_path, monkeypatch):
    from superqode.systemone.client import SystemOneError

    monkeypatch.setattr(
        "superqode.harness.backends.systemone.build_client",
        lambda settings: StubSystemOneClient(error=SystemOneError("HTTP 401")),
    )
    request = HarnessBackendRequest(
        spec=HarnessSpec(name="test", systemone=SystemOneSpec(enabled=True)),
        prompt="{}",
        provider="none",
        model="none",
        working_directory=tmp_path,
    )
    with pytest.raises(RuntimeError, match="evaluation failed: HTTP 401"):
        await SystemOneHarnessBackend().run(request)


async def test_recording_failure_does_not_discard_valid_response(tmp_path, monkeypatch):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"answers": {"q": {"noul": 0.1}}})
        )
    ) as http:
        client = LiveSystemOneClient(api_key="test-only", http=http, record_dir=tmp_path)

        def fail(*args):
            raise OSError("disk full")

        monkeypatch.setattr(client, "_record", fail)
        answer = await client.evaluate({}, {"q": NoulQuestion(instructions="yes?")})
        assert answer.noul("q") == 0.1
        assert answer.metadata["recording_error"]


async def test_deadline_includes_retries():
    from superqode.systemone.client import SystemOneTimeout

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(429))
    ) as http:
        client = LiveSystemOneClient(api_key="test-only", http=http, timeout_ms=20)
        with pytest.raises(SystemOneTimeout):
            await client.evaluate({}, {"q": NoulQuestion(instructions="yes?")})
