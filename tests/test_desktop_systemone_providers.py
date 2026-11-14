"""The actual native RPC/configuration and worker boundary, without vendor calls."""

import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from test_desktop_service import desktop, wait_job
from superqode.harness.loader import load_harness_spec
from superqode.systemone.providers import PROVIDERS, get_provider
from superqode.systemone.pack import load_pack
from superqode.tools.env_policy import build_shell_env
from test_systemone_provider_apis import success_body, CLIENTS


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for name in list(os.environ):
        if name.startswith("SUPERQODE_SYSTEMONE") or name in {
            "TYPESAFE_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
        }:
            monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_native_config_save_and_provider_catalog_are_offline_and_secret_free(desktop, provider):
    service, project, root = desktop
    service.dispatch("connect.systemone.key", {"provider": provider, "key": "PRIVATE_API_KEY"})
    catalog = service.dispatch("connect.systemone.providers", {})
    assert {row["id"] for row in catalog} == set(PROVIDERS)
    result = service.dispatch(
        "connect.systemone.configure",
        {"project": project["id"], "provider": provider, "record_decisions": True},
    )
    spec = load_harness_spec(result["path"])
    definition = get_provider(provider)
    assert spec.systemone.provider == provider and spec.systemone.model == definition.model
    assert spec.systemone.mode == "shadow" and not spec.systemone.policy_reviewed
    assert Path(spec.systemone.record_dir).is_relative_to(service.root / "decision-records")
    assert spec.metadata["decision_provider_pinned"] is True
    assert "PRIVATE_API_KEY" not in Path(result["path"]).read_text()
    assert b"PRIVATE_API_KEY" not in (service.root / "desktop.sqlite").read_bytes()
    assert not list((service.root / "decision-records").glob("**/*.json"))


@pytest.mark.parametrize("provider", ["google", "openai"])
def test_native_enforcement_requires_review_and_invalid_choices_never_save(desktop, provider):
    service, project, root = desktop
    params = {"project": project["id"], "provider": provider, "mode": "enforce"}
    with pytest.raises(ValueError, match="Review"):
        service.dispatch("connect.systemone.configure", params)
    with pytest.raises(ValueError):
        service.dispatch("connect.systemone.configure", {**params, "policy_reviewed": "true"})
    with pytest.raises(ValueError):
        service.dispatch(
            "connect.systemone.configure",
            {**params, "policy_reviewed": True, "model": "unsupported"},
        )
    result = service.dispatch("connect.systemone.configure", {**params, "policy_reviewed": True})
    spec = load_harness_spec(result["path"])
    assert spec.systemone.mode == "enforce" and spec.systemone.policy_reviewed
    assert spec.tool_discovery.judge["mode"] == "rerank"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_native_connectivity_action_uses_only_synthetic_input(desktop, provider, monkeypatch):
    service, project, root = desktop
    real_init = CLIENTS[provider].__init__
    seen = []

    def handler(request):
        seen.append(request)
        payload = json.loads(request.content)
        body = success_body(
            provider,
            get_provider(provider).model,
            load_pack("provider_check").questions,
        )
        assert "Please review this code change" in json.dumps(payload)
        return httpx.Response(200, json=body)

    def initialize(self, **kwargs):
        kwargs["http"] = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        real_init(self, **kwargs)

    monkeypatch.setattr(CLIENTS[provider], "__init__", initialize)
    result = service.dispatch(
        "connect.systemone.test", {"provider": provider, "key": "PRIVATE_API_KEY"}
    )
    assert result["status"] == "connected" and result["provider"] == provider
    assert result["checked_primitives"] == ["noul", "choice", "score"]
    assert len(seen) == 1 and "PRIVATE_API_KEY" not in json.dumps(result)
    assert not service._all("SELECT * FROM jobs")


@pytest.mark.parametrize("decision_provider", ["google", "openai"])
def test_actual_worker_spawn_keeps_coding_and_decision_keys_separate(
    desktop, decision_provider, monkeypatch
):
    service, project, root = desktop
    service.dispatch("providers.credentials.set", {"provider": "openai", "key": "CODING_PRIVATE"})
    for provider in PROVIDERS:
        service.dispatch(
            "connect.systemone.key", {"provider": provider, "key": "DECISION_PRIVATE_" + provider}
        )
    profile = service.dispatch(
        "connect.systemone.configure", {"project": project["id"], "provider": decision_provider}
    )
    seen = []
    original = subprocess.Popen

    def spawn(args, **kwargs):
        if args[-2:] == ["-m", "superqode.desktop_service.worker"]:
            seen.append(kwargs["env"].copy())
            return original([sys.executable, "-c", "import sys;sys.stdin.readline()"], **kwargs)
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spawn)
    job = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": profile["id"],
            "provider": "openai",
            "model": "gpt-4o-mini",
            "prompt": "Review code",
            "permission_mode": "ask",
        },
    )
    wait_job(service, job["id"])
    assert len(seen) == 1
    env = seen[0]
    assert env["OPENAI_API_KEY"] == "CODING_PRIVATE"
    assert env["SUPERQODE_SYSTEMONE_API_KEY"] == "DECISION_PRIVATE_" + decision_provider
    assert env["SUPERQODE_SYSTEMONE_PROVIDER"] == decision_provider
    for provider in PROVIDERS:
        if provider != decision_provider:
            assert "DECISION_PRIVATE_" + provider not in env.values()
    key_names = json.loads(env["SUPERQODE_DESKTOP_KEY_VARS"])
    assert "SUPERQODE_SYSTEMONE_MODEL" not in key_names
    saved = json.dumps(service.dispatch("jobs.get", {"id": job["id"]}))
    assert "PRIVATE" not in saved


@pytest.mark.parametrize("policy", ["inherit", "filter-secrets"])
def test_decision_key_never_inherits_into_model_spawned_shells(policy, monkeypatch):
    monkeypatch.setenv("SUPERQODE_SYSTEMONE_API_KEY", "PRIVATE_DECISION")
    monkeypatch.setenv("SUPERQODE_SHELL_ENV_POLICY", policy)
    monkeypatch.setenv("SUPERQODE_SHELL_ENV_ALLOW", "SUPERQODE_SYSTEMONE_API_KEY")
    env = build_shell_env()
    assert env is not None and "SUPERQODE_SYSTEMONE_API_KEY" not in env
    assert os.environ["SUPERQODE_SYSTEMONE_API_KEY"] == "PRIVATE_DECISION"
    supplied = build_shell_env({"PATH": "/bin", "SUPERQODE_SYSTEMONE_API_KEY": "PRIVATE_DECISION"})
    assert supplied == {"PATH": "/bin"}
