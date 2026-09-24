"""General decision packs through evaluation, harness, and native TUI paths."""

from pathlib import Path
import json

import httpx
import pytest

from superqode.harness.loader import harness_spec_from_dict, load_harness_spec, harness_spec_to_dict
from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.systemone import SystemOneHarnessBackend
from superqode.systemone.client import StubSystemOneClient
from superqode.systemone.config import resolve_systemone, build_client
from superqode.systemone.decision import evaluate_decision, parse_state
from superqode.systemone.pack import load_pack, QuestionPack

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "examples/systemone/ticket-triage-pack.yaml"


async def test_general_pack_returns_all_primitives_and_abstains():
    pack = load_pack(PACK)
    client = StubSystemOneClient(
        {
            "department": {"choice": "technical", "confidence": 0.95},
            "severity": {"score": 2.5, "confidence": 0.6},
            "urgent": {"noul": 0.99},
        }
    )
    result = await evaluate_decision(client, "The service is down. Fix it immediately.", pack)
    assert result.outputs == {"department": "technical", "severity": None, "urgent": True}
    assert result.status == "abstain"
    assert result.abstained == ["severity"]
    assert result.answers["severity"]["score"] == 2.5
    assert result.metadata["pack_hash"] == pack.content_hash()


async def test_invalid_or_oversized_state_never_calls_client():
    pack = load_pack("rubric")
    client = StubSystemOneClient()
    with pytest.raises(ValueError, match="schema"):
        await evaluate_decision(client, {"task": "wrong shape"}, pack)
    with pytest.raises(ValueError, match="32000"):
        await evaluate_decision(client, {"rubric": "r", "work": "x" * 32001}, pack)
    assert not client.calls


async def test_general_state_redaction_and_custom_array_schema():
    pack = QuestionPack.model_validate(
        {
            "id": "items",
            "version": "1",
            "state_schema": {"type": "array"},
            "questions": {"ok": {"type": "noul", "instructions": "Are all entries valid?"}},
        }
    )
    client = StubSystemOneClient({"ok": {"noul": 0.1}})
    result = await evaluate_decision(client, [{"token": "secret-value"}], pack)
    assert result.outputs == {"ok": False}
    assert client.calls[0][0] == [{"token": "[redacted]"}]


def test_schema_disallows_external_references():
    with pytest.raises(ValueError, match="local references"):
        QuestionPack.model_validate(
            {
                "id": "test",
                "version": "1",
                "questions": {},
                "state_schema": {"$ref": "https://example.test/schema"},
            }
        )


def test_pack_hash_changes_with_policy():
    pack = load_pack("factory_route")
    before = pack.content_hash()
    pack.decision_policy.min_confidence = 0.99
    assert pack.content_hash() != before


def test_text_mapping_and_bad_json():
    pack = load_pack("factory_route")
    assert parse_state("Review this patch", pack) == {"task": "Review this patch"}
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_state("{broken", pack)


async def test_general_backend_preserves_arbitrary_state_and_streams(monkeypatch, tmp_path):
    client = StubSystemOneClient({"verdict": {"choice": "satisfied", "confidence": 0.99}})
    monkeypatch.setattr(
        "superqode.harness.backends.systemone.build_client", lambda settings: client
    )
    spec = harness_spec_from_dict(
        {
            "name": "rubric",
            "flavor": "decision",
            "runtime": {"backend": "systemone"},
            "systemone": {"enabled": True, "pack": "rubric"},
        }
    )
    request = HarnessBackendRequest(
        spec=spec,
        prompt=json.dumps({"rubric": "Tests pass", "work": "All tests pass"}),
        provider="",
        model="",
        working_directory=tmp_path,
    )
    backend = SystemOneHarnessBackend()
    result = await backend.run(request)
    assert result.response.structured_output["outputs"]["verdict"] == "satisfied"
    assert client.calls[0][0]["work"] == "All tests pass"
    chunks = [e.data["text"] async for e in backend.stream(request)]
    assert json.loads("".join(chunks))["status"] == "decided"


def test_compatible_endpoint_roundtrip_and_no_default_key_leak(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "must-not-be-used")
    spec = harness_spec_from_dict(
        {
            "name": "local",
            "systemone": {
                "enabled": True,
                "client": "live",
                "endpoint": "http://localhost:9000/v1/systemone",
                "api_key_env": "",
                "model": "local-classifier",
            },
        }
    )
    restored = harness_spec_from_dict(harness_spec_to_dict(spec))
    settings = resolve_systemone(spec=restored)
    assert not settings.skip_client
    client = build_client(settings)
    assert client.url == "http://localhost:9000/v1/systemone"
    assert client.model == "local-classifier"
    assert "Authorization" not in client._headers()
    offline = harness_spec_from_dict(
        {**harness_spec_to_dict(spec), "metadata": {"airplane_mode": True}}
    )
    assert resolve_systemone(spec=offline).skip_reason == "airplane"


def test_example_pack_path_is_relative_to_spec(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    spec = load_harness_spec(ROOT / "examples/harnesses/systemone/ticket-triage.yaml")
    assert load_pack(spec.systemone.pack).id == "ticket_triage"


async def test_connect_decision_needs_no_coding_provider(monkeypatch, tmp_path):
    from superqode.pure_mode import PureMode

    monkeypatch.chdir(tmp_path)
    client = StubSystemOneClient({"route": {"choice": "review", "confidence": 0.98}})
    monkeypatch.setattr(
        "superqode.harness.backends.systemone.build_client", lambda settings: client
    )
    spec = harness_spec_from_dict(
        {
            "name": "route",
            "flavor": "decision",
            "runtime": {"backend": "systemone"},
            "systemone": {"enabled": True, "client": "stub", "pack": "factory_route"},
        }
    )
    pure = PureMode()
    pure.connect_decision(spec=spec)
    assert pure.session.connected
    assert pure._agent is None
    output = "".join([chunk async for chunk in pure.run_streaming("Review this patch")])
    assert json.loads(output)["outputs"]["route"] == "review"
    await pure.aclose()


async def test_mounted_tui_connects_decision_pack_and_evaluates_input(monkeypatch, tmp_path):
    from superqode.app_main import SuperQodeApp, SelectionAwareInput
    from superqode.app.widgets import ConversationLog, ColorfulStatusBar

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-test-key")
    monkeypatch.setattr(SuperQodeApp, "_prewarm_litellm", lambda self: None)
    monkeypatch.setattr(SuperQodeApp, "_start_models_dev_refresh", lambda self: None)
    client = StubSystemOneClient({"route": {"choice": "review", "confidence": 0.98}})
    monkeypatch.setattr(
        "superqode.harness.backends.systemone.build_client", lambda settings: client
    )
    app = SuperQodeApp()
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(6):
            await pilot.pause()
        app._welcome_active = False
        app._prompts.clear()
        app._reset_connect_selection_states()
        log = app.query_one("#log", ConversationLog)
        log.clear()
        entry = app.query_one("#prompt-input", SelectionAwareInput)
        entry.value = ":systemone live"
        await pilot.press("enter")
        await pilot.pause()
        text = "\n".join(line.text for line in log.lines)
        assert "coding provider" in text
        assert not app._pure_mode.session.connected
        entry.value = ":connect systemone factory_route"
        await pilot.press("enter")
        await pilot.pause()
        assert app._pure_mode.session.connected
        assert app.query_one("#status-bar", ColorfulStatusBar).active_runtime == "systemone"
        entry.value = "Review this patch"
        await pilot.press("enter")
        for _ in range(25):
            await pilot.pause(0.1)
            if client.calls and not app.is_busy:
                break
        assert client.calls
        assert client.calls[-1][0]["task"] == "Review this patch"
        text = "\n".join(line.text for line in log.lines)
        assert "review" in text
        assert "outputs" in text
        assert "Not connected." not in text
        await app._pure_mode.aclose()


async def test_application_client_cannot_omit_answers():
    from superqode.systemone.types import Answers
    from superqode.systemone.client import SystemOneError

    class BrokenClient:
        name = "application-client"

        async def evaluate(self, state, questions):
            return Answers(answers={})

    with pytest.raises(SystemOneError, match="no decision"):
        await evaluate_decision(BrokenClient(), "Review this patch", load_pack(PACK))
