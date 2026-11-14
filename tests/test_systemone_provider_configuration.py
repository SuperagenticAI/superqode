"""Provider isolation and cross-surface selection; no live API requests."""

from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
from pathlib import Path

from click.testing import CliRunner
import httpx
import pytest

from superqode.systemone.config import SELECTION_ENV, build_client, resolve_systemone
from superqode.systemone.providers import PROVIDERS, get_provider
from superqode.harness.loader import harness_spec_from_dict, harness_spec_to_dict, load_harness_spec
from superqode.harness.spec import HarnessSpec, SystemOneSpec
from superqode.systemone.types import NoulQuestion
from superqode.systemone.client import StubSystemOneClient
from superqode.systemone.tool_router import build_tool_router, ToolRoutingSettings
from superqode.commands.harness._group import harness
from superqode.systemone.audit import disagreement_report
from superqode.systemone import tune


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for name in (
        *SELECTION_ENV,
        "SUPERQODE_SYSTEMONE",
        "SUPERQODE_TOOL_ROUTING",
        "SUPERQODE_SYSTEMONE_API_KEY",
        "TYPESAFE_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_factory_defaults_keys_and_round_trip(provider):
    definition = get_provider(provider)
    spec = harness_spec_from_dict(
        {"name": "fixture", "systemone": {"enabled": True, "client": "live", "provider": provider}}
    )
    settings = resolve_systemone(spec=spec, environ={definition.api_key_env: "test-only"})
    assert settings.provider == provider
    assert settings.model == definition.model
    assert settings.endpoint == definition.endpoint
    assert settings.api_key_env == definition.api_key_env
    assert settings.mode == ("enforce" if provider == "typesafe" else "shadow")
    assert harness_spec_from_dict(harness_spec_to_dict(spec)).systemone == spec.systemone
    assert build_client(settings, api_key="explicit-fixture").api_key == "explicit-fixture"


@pytest.mark.parametrize("provider", ["google", "openai"])
def test_model_and_endpoint_switch_does_not_inherit_jev_or_review(provider):
    definition = get_provider(provider)
    settings = resolve_systemone(
        explicit=SystemOneSpec(enabled=True, client="live", policy_reviewed=True),
        environ={"SUPERQODE_SYSTEMONE_PROVIDER": provider, definition.api_key_env: "fixture"},
    )
    assert settings.model == definition.model and settings.endpoint == definition.endpoint
    assert not settings.policy_reviewed and settings.mode == "shadow"


@pytest.mark.parametrize("provider", ["google", "openai"])
def test_reviewed_enforcement_is_explicit_and_pinned_profiles_ignore_other_selection(provider):
    definition = get_provider(provider)
    spec = harness_spec_from_dict(
        {
            "name": "pinned",
            "metadata": {"decision_provider_pinned": True},
            "systemone": {
                "enabled": True,
                "client": "live",
                "provider": provider,
                "policy_reviewed": True,
                "mode": "enforce",
            },
        }
    )
    settings = resolve_systemone(
        spec=spec,
        environ={
            "SUPERQODE_SYSTEMONE_PROVIDER": "typesafe",
            "SUPERQODE_SYSTEMONE_MODEL": "jev-1.14.0",
            "SUPERQODE_SYSTEMONE_POLICY_REVIEWED": "false",
            definition.api_key_env: "fixture",
        },
    )
    assert settings.provider == provider and settings.model == definition.model
    assert settings.mode == "enforce" and settings.policy_reviewed
    offline = replace(spec, metadata={**spec.metadata, "airplane_mode": True})
    assert (
        resolve_systemone(spec=offline, environ={definition.api_key_env: "fixture"}).skip_reason
        == "airplane"
    )
    assert build_client(resolve_systemone(spec=offline), api_key="fixture") is None


@pytest.mark.parametrize("provider", PROVIDERS)
def test_missing_key_explicit_key_and_dedicated_key_do_not_mutate_coding_key(provider, monkeypatch):
    definition = get_provider(provider)
    spec = SystemOneSpec(enabled=True, client="live", provider=provider)
    missing = resolve_systemone(explicit=spec, environ={})
    assert missing.skip_reason == "live_unavailable" and build_client(missing) is None
    assert build_client(missing, api_key="explicit-only").api_key == "explicit-only"
    monkeypatch.setenv(definition.api_key_env, "coding-key")
    monkeypatch.setenv("SUPERQODE_SYSTEMONE_API_KEY", "decision-key")
    selected = resolve_systemone(explicit=spec)
    assert build_client(selected).api_key == "decision-key"
    assert __import__("os").environ[definition.api_key_env] == "coding-key"


def test_custom_no_auth_systemone_endpoint_retains_legacy_contract():
    spec = harness_spec_from_dict(
        {
            "name": "local",
            "systemone": {
                "enabled": True,
                "client": "live",
                "endpoint": "http://127.0.0.1:9000/v1/systemone",
                "model": "local-fixture",
                "api_key_env": "",
            },
        }
    )
    settings = resolve_systemone(spec=spec, environ={})
    client = build_client(settings)
    assert client.url == "http://127.0.0.1:9000/v1/systemone"
    assert "Authorization" not in client._headers()


@pytest.mark.parametrize("provider", ["google", "openai"])
def test_router_uses_selected_engine_and_stays_shadow_until_reviewed(provider, monkeypatch):
    definition = get_provider(provider)
    monkeypatch.setenv(definition.api_key_env, "fixture")
    for reviewed, mode, expected in [
        (False, "enforce", "shadow"),
        (True, "shadow", "shadow"),
        (True, "enforce", "enforce"),
    ]:
        settings = resolve_systemone(
            explicit=SystemOneSpec(
                enabled=True, client="live", provider=provider, policy_reviewed=reviewed, mode=mode
            )
        )
        router = build_tool_router(ToolRoutingSettings(mode="enforce"), decision_settings=settings)
        assert router.provider.client.provider == provider
        assert router.settings.mode == expected


@pytest.mark.parametrize("provider", PROVIDERS)
def test_cli_provider_listing_is_offline_and_decision_uses_selected_provider(provider, monkeypatch):
    definition = get_provider(provider)
    from superqode.commands.harness import systemone as commands

    seen = []
    monkeypatch.setenv(definition.api_key_env, "fixture")

    def client(settings):
        seen.append(settings)
        return StubSystemOneClient({"route": {"choice": "review", "confidence": 0.99}})

    monkeypatch.setattr("superqode.systemone.config.build_client", client)
    runner = CliRunner()
    listing = runner.invoke(harness, ["decision-providers"])
    assert listing.exit_code == 0 and len(json.loads(listing.output)) == 3 and not seen
    result = runner.invoke(harness, ["decision", "--provider", provider, "-p", "Review code"])
    assert result.exit_code == 0, result.output
    assert seen[0].provider == provider and seen[0].model == definition.model
    assert "fixture" not in result.output


def test_reports_separate_provider_and_observed_model():
    events = [
        {
            "provider": p,
            "model": "requested",
            "intendedAction": "ask",
            "policyAction": "deny",
            "evaluation": {"status": "success", "resolved_model": m},
        }
        for p, m in [("google", "gemini-decision-1"), ("openai", "gpt-6-luna")]
    ]
    report = disagreement_report(events)
    assert set(report["by_decision_engine"]) == {"google/gemini-decision-1", "openai/gpt-6-luna"}
    assert all(row["total"] == 1 for row in report["by_decision_engine"].values())


@pytest.mark.parametrize("provider", PROVIDERS)
def test_tune_freezes_provider_and_model_before_calls(provider, monkeypatch):
    options = tune.TuneOptions(decision_provider=provider)
    pack, spec = tune.load_tune_pack(options)
    monkeypatch.setenv(
        "SUPERQODE_SYSTEMONE_PROVIDER", "openai" if provider != "openai" else "google"
    )
    settings = resolve_systemone(spec=spec)
    assert settings.provider == provider and settings.model == get_provider(provider).model
    assert spec.metadata["decision_provider_pinned"] is True
    assert pack.id == "factory_route"


@pytest.mark.parametrize(
    "provider,model",
    [
        ("typesafe", "jev-1.13.0"),
        ("typesafe", "jev-1.14.0"),
        ("google", "gemini-decision-1"),
        ("openai", "gpt-6-luna"),
    ],
)
async def test_real_backend_gate_and_rubric_use_native_adapter(
    provider, model, monkeypatch, tmp_path
):
    from test_systemone_provider_apis import CLIENTS, success_body
    from superqode.harness.backends.base import HarnessBackendRequest
    from superqode.harness.backends.systemone import SystemOneHarnessBackend
    from superqode.systemone.pack import load_pack
    from superqode.systemone.compose import evaluate_tool_gate, GateAction
    from superqode.systemone.state import ToolGateState
    from superqode.agent.rubric import evaluate_jev_rubric

    current_pack = load_pack("factory_route")
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=success_body(provider, model, current_pack.questions))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CLIENTS[provider](
            api_key="fixture", model=model, http=http, record_dir=tmp_path / "records"
        )
        monkeypatch.setattr(
            "superqode.harness.backends.systemone.build_client", lambda settings: client
        )
        spec = harness_spec_from_dict(
            {
                "name": "decision-integration",
                "flavor": "decision",
                "runtime": {"backend": "systemone"},
                "systemone": {
                    "enabled": True,
                    "client": "live",
                    "provider": provider,
                    "model": model,
                    "pack": "factory_route",
                },
            }
        )
        request = HarnessBackendRequest(
            spec=spec, prompt="Review code", provider="", model="", working_directory=tmp_path
        )
        result = await SystemOneHarnessBackend().run(request)
        assert result.response.structured_output["status"] == "decided"
        assert result.response.structured_output["metadata"]["evaluation"]["provider"] == provider
        assert result.response.input_tokens == 123 and result.response.output_tokens == 0
        events = [event async for event in SystemOneHarnessBackend().stream(request)]
        assert events[0].type == "model_delta"
        current_pack = load_pack("tool_gate")
        gate = await evaluate_tool_gate(
            client,
            ToolGateState(tool="bash", arguments={"command": "pytest"}, task="Run tests"),
            current_pack,
        )
        assert (
            gate.action is GateAction.DENY
        )  # Fixture explicitly reports high destructive/exfil risk.
        current_pack = load_pack("rubric")
        grade = await evaluate_jev_rubric(
            "Code meets requirements", "Reviewed code", spec=spec, client=client
        )
        assert grade["verdict"] == "satisfied"
        assert grade["decision"]["metadata"]["evaluation"]["provider"] == provider
    assert len(captured) == 4 and len(list((tmp_path / "records").glob("*.json"))) == 4


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.parametrize("pack_id", ["factory_route", "provider_check"])
async def test_mounted_tui_selects_provider_and_evaluates_pack(
    provider, pack_id, monkeypatch, tmp_path
):
    from superqode.app_main import SuperQodeApp, SelectionAwareInput
    from superqode.app.widgets import ConversationLog
    from superqode.systemone.pack import load_pack

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    monkeypatch.setenv(get_provider(provider).api_key_env, "test-only-key")
    monkeypatch.setattr(SuperQodeApp, "_prewarm_litellm", lambda self: None)
    monkeypatch.setattr(SuperQodeApp, "_start_models_dev_refresh", lambda self: None)
    client = StubSystemOneClient({"route": {"choice": "review", "confidence": 0.98}})
    settings_seen = []

    def factory(settings):
        settings_seen.append(settings)
        return client

    monkeypatch.setattr("superqode.harness.backends.systemone.build_client", factory)
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
        entry.value = f":systemone provider {provider}"
        await pilot.press("enter")
        await pilot.pause()
        assert app._pure_mode._harness_spec.systemone.provider == provider
        assert app._pure_mode._harness_spec.systemone.mode == "shadow"
        entry.value = f":systemone connect {pack_id} --provider {provider}"
        await pilot.press("enter")
        await pilot.pause()
        assert app._pure_mode.session.connected
        entry.value = "Review this patch"
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.1)
            if client.calls and not app.is_busy:
                break
        assert client.calls and settings_seen[-1].provider == provider
        assert set(client.calls[-1][1]) == set(load_pack(pack_id).questions)
        text = "\n".join(line.text for line in log.lines)
        assert "review" in text and "Not connected." not in text
        await app._pure_mode.aclose()
