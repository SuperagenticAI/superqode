import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service import connections, local_models, local_quickstart
from superqode.local import workbench
from superqode.local.hardware import HardwareProfile
from superqode.providers.registry import PROVIDERS


def test_hf_families_remain_searchable_but_ds4_is_advanced_only(monkeypatch):
    monkeypatch.setattr(
        workbench,
        "detect_hardware",
        lambda: HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=64),
    )
    glm = workbench.search("GLM")
    assert any(
        row["id"] == "THUDM/GLM-4.5-Air" and row["format"] == "weights" and not row["engines"]
        for row in glm
    )
    deepseek = workbench.search("DeepSeek")
    assert any(row["source"] == "hf" for row in deepseek)
    assert not any("ds4" in row["engines"] for row in deepseek)
    # The full runtime catalog keeps DS4 available without suggesting it to newcomers.
    assert "ds4" in workbench.ENGINES
    assert workbench.PROVIDERS["ds4"] == "ds4"
    assert PROVIDERS["ds4"].id == "ds4"


def test_recommended_hf_formats_are_inferred_from_artifacts_not_engine_hint(monkeypatch):
    monkeypatch.setattr(
        workbench,
        "search_models",
        lambda *a, **k: [
            SimpleNamespace(
                name="Chinese family",
                role="main",
                commands=[
                    ("mlx / hf", "hf download publisher/family-GGUF"),
                    ("mlx / hf", "hf download mlx-community/family-4bit"),
                    ("mlx / hf", "hf download ../escape"),
                ],
            )
        ],
    )
    rows = workbench.search("family")
    assert {r["format"] for r in rows} == {"mlx", "gguf"}
    assert next(r for r in rows if r["format"] == "gguf")["engines"] == [
        "llama.cpp",
        "ollama",
        "lmstudio",
    ]
    assert all(r["fit"]["estimate_gb"] is None for r in rows)


def test_region_keys_do_not_overwrite_each_other_or_claim_verified_access():
    credentials = {}
    for provider, key in [("qwen-cn", "china-test-key"), ("qwen-intl", "international-test-key")]:
        connections.install(credentials, {"provider": provider, "key": key})
    env = connections.environment(credentials)
    assert env["QWEN_CN_API_KEY"] == "china-test-key"
    assert env["QWEN_INTL_API_KEY"] == "international-test-key"
    assert "DASHSCOPE_API_KEY" not in env
    rows = {r["id"]: r for r in connections.list_connections(credentials)}
    assert rows["qwen-cn"]["default_base_url"] != rows["qwen-intl"]["default_base_url"]
    for name in ("qwen-cn", "qwen-intl"):
        assert rows[name]["key_supported"] and not rows[name]["verified"]
        assert "coding" in rows[name]["notes"].lower()
        assert rows[name]["docs_url"].startswith("https://")
        assert "test-key" not in json.dumps(rows[name])


def test_model_studio_endpoint_applies_to_discovery_and_worker_without_saving_preview_key(
    desktop, monkeypatch
):
    from superqode.providers import live_models
    from superqode.providers.models import ModelInfo, ModelCapability

    service, _, _ = desktop
    endpoint = "https://ws-demo.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    preview = "https://ws-preview.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"

    async def discover(provider, *, api_key, base_url):
        assert provider == "qwen-intl" and api_key == "sk-entered-for-discovery"
        assert base_url == preview
        return live_models.LiveDiscoveryResult(
            provider,
            [
                ModelInfo(
                    id="qwen3.8-flash",
                    name="Qwen Flash",
                    provider=provider,
                    context_window=256000,
                    max_output=16384,
                    capabilities=[ModelCapability.TOOLS],
                    pricing_known=False,
                )
            ],
            "live",
        )

    monkeypatch.setattr(live_models, "discover_provider_models", discover)
    monkeypatch.delenv("QWEN_INTL_API_BASE", raising=False)
    service.dispatch("providers.credentials.set", {"provider": "qwen-intl", "key": "sk-saved"})
    service.dispatch("providers.endpoint.set", {"provider": "qwen-intl", "endpoint": endpoint})
    result = service.dispatch(
        "providers.models",
        {"provider": "qwen-intl", "key": "sk-entered-for-discovery", "endpoint": preview},
    )
    assert result["source"] == "live" and result["models"] == ["qwen3.8-flash"]
    assert result["error"] is None
    detail = result["model_details"][0]
    assert detail["context_window"] == 256000 and detail["max_output"] == 16384
    assert detail["capabilities"] == ["tools"] and not detail["pricing_known"]
    assert detail["thinking_policy"] == "configurable"
    assert service.credential_environment({"qwen-intl"}) == {
        "QWEN_INTL_API_KEY": "sk-saved",
        "QWEN_INTL_API_BASE": endpoint,
    }
    assert service.credential_environment({"qwen-cn"}) == {}
    with pytest.raises(ValueError, match="OpenAI-compatible"):
        service.dispatch(
            "providers.endpoint.set",
            {
                "provider": "qwen-intl",
                "endpoint": endpoint.replace("aliyuncs.com", "example.com"),
            },
        )
    assert service.credential_environment({"qwen-intl"})["QWEN_INTL_API_BASE"] == endpoint
    service.dispatch("providers.endpoint.set", {"provider": "qwen-intl", "endpoint": ""})
    assert "QWEN_INTL_API_BASE" not in service.credential_environment({"qwen-intl"})


def test_workspace_model_details_do_not_claim_unknown_capabilities_or_optional_glm_thinking(
    monkeypatch,
):
    from superqode.providers import live_models

    async def discover(provider, **kwargs):
        return live_models.LiveDiscoveryResult(
            provider,
            [
                live_models._model_studio_info(provider, "glm-5.3"),
                live_models._model_studio_info(provider, "future-workspace-model"),
            ],
            "live",
        )

    monkeypatch.setattr(live_models, "discover_provider_models", discover)
    result = connections.list_workspace_models({}, {"provider": "qwen-intl"})
    glm, unknown = result["model_details"]
    assert glm["thinking_policy"] == "required"
    assert unknown["thinking_policy"] == "unknown"
    assert unknown["context_window"] is None and unknown["max_output"] is None
    assert unknown["capabilities"] == [] and not unknown["pricing_known"]


@pytest.mark.parametrize("model", ["deepseek-v4-pro", "deepseek-v4.1-flash-1017"])
def test_current_deepseek_workspace_aliases_can_disable_thinking(model):
    from superqode.providers.model_studio import thinking_options, thinking_policy

    assert thinking_options(model, "off") == {"enable_thinking": False}
    assert thinking_policy(model) == "configurable"


@pytest.mark.parametrize("reference", ["qwen-code", "acp:qwen"])
def test_qwen_setup_launches_interactive_cli_not_acp_or_removed_auth(
    desktop, monkeypatch, reference
):
    service, project, _ = desktop
    monkeypatch.setattr("shutil.which", lambda name: "/vendor/qwen" if name == "qwen" else None)
    menu = service.dispatch("connect.menu", {"project": project["id"], "menu": "vendors"})
    row = next(row for row in menu["rows"] if row["id"] == "qwen-code")
    assert row["route"]["id"] == "qwen-code" and row["route"]["agent_id"] == "qwen"
    assert row["route"]["command"] == "qwen --acp"
    plan = service.dispatch(
        "connect.acp.login.plan", {"project": project["id"], "reference": reference}
    )
    assert plan["interactive"] and plan["argv"] == ["/vendor/qwen"]
    assert plan["env"] == {}
    assert "/auth" in plan["instructions"] and "region" in plan["instructions"]
    assert "Token Plan" in plan["instructions"] and "Coding Plan" in plan["instructions"]


def test_newcomer_shows_only_primary_engines_with_installed_models_first(desktop, monkeypatch):
    service, project, _ = desktop
    engines = workbench.ENGINES
    monkeypatch.setattr(
        "superqode.local.hardware.detect_hardware",
        lambda: HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=64),
    )
    monkeypatch.setattr(
        local_models, "servers", lambda _: [{"id": e, "name": e, "running": True} for e in engines]
    )
    monkeypatch.setattr(local_models, "available", lambda e: {"models": [e + "-existing-model"]})
    monkeypatch.setattr("superqode.local.inventory.installed_chat_models", lambda: [])
    result = local_quickstart.catalog(service, project["id"])
    rows = result["choices"]
    assert {row["engine"] for row in rows} == {"ollama", "lmstudio"}
    assert {row["id"] for row in result["engines"]} == {"ollama", "lmstudio"}
    assert {row["id"] for row in result["other_engines"]} == {"mlx", "llama.cpp", "ds4"}
    assert all(row["installed"] for row in rows[:2])
    assert all(not row["installed"] for row in rows[2:])
    assert {row["engine"] for row in rows[:2]} == {"ollama", "lmstudio"}
    assert all(row["preset"] == "suggested" and row["fit"]["rating"] == "Fits" for row in rows[2:])
    # Advanced server controls still expose all configured engines and running states.
    advanced = local_models.servers(service)
    assert {row["id"] for row in advanced} == set(engines)
    assert all(row["running"] for row in advanced)


def test_quickstart_records_context_and_tool_probes_alongside_actual_core_check(
    tmp_path, monkeypatch
):
    from superqode.local import bench, smoke, coding_check

    monkeypatch.setattr(workbench, "ServerManager", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(bench, "list_endpoint_models", lambda endpoint: ["my-glm"])
    monkeypatch.setattr(
        smoke,
        "run_smoke",
        lambda **kwargs: SimpleNamespace(
            to_dict=lambda: {
                "status": "warning",
                "checks": [{"name": "read_file_tool", "ok": True, "detail": "tool call shape"}],
                "warnings": ["Context must stay conservative"],
                "context_window": None,
            }
        ),
    )

    async def core(*args):
        return {"status": "passed", "checks": [{"name": "read executed successfully", "ok": True}]}

    async def context(*args):
        return 8192, "fixture server"

    monkeypatch.setattr(coding_check, "run", core)
    monkeypatch.setattr("superqode.providers.local.context_probe.probe_base_url", context)
    result = workbench.run(
        {
            "action": "verify",
            "engine": "ollama",
            "model": "my-glm",
            "provider": "ollama",
            "endpoint": "http://127.0.0.1:11434/v1",
            "check": "quickstart",
            "title": "Readiness",
        },
        tmp_path,
        lambda *args: None,
    )
    report = result["verification"]
    assert report["status"] == "passed"
    assert report["readiness"]["context_window"] == 8192
    assert report["readiness"]["checks"][0]["name"] == "read_file_tool"
    assert report["readiness"]["warnings"]
    assert result["scope"] == "local-coding-readiness"
    assert result["harness_certified"] is False


def test_advanced_server_rpc_keeps_other_engines_and_manual_ds4_setup(desktop, monkeypatch):
    from superqode.local import servers

    service, _, _ = desktop

    class Manager:
        def __init__(self, **kwargs):
            pass

        def precheck(self, engine):
            return servers.LocalReadiness(
                engine, False, False, "http://127.0.0.1", "missing", "", True
            )

        def _load(self, engine):
            return None

        def _ds4_binary(self):
            return None

    monkeypatch.setattr(servers, "ServerManager", Manager)
    rows = service.dispatch("local.models.servers", {})
    assert {row["id"] for row in rows} == set(workbench.ENGINES)
    ds4 = next(row for row in rows if row["id"] == "ds4")
    assert not ds4["install"]["automatic"]
    assert ds4["install"]["docs_url"] == "https://github.com/antirez/ds4"
