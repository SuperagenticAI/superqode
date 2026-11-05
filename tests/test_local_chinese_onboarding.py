import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service import connections, local_models, local_quickstart
from superqode.local import workbench
from superqode.local.hardware import HardwareProfile
from superqode.providers.registry import PROVIDERS


def test_hf_families_and_ds4_survive_recommended_projection(monkeypatch):
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
    assert any(row.get("manual_setup") and row["engines"] == ["ds4"] for row in deepseek)


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


def test_qwen_setup_launches_interactive_cli_not_acp_or_removed_auth(desktop, monkeypatch):
    service, project, _ = desktop
    monkeypatch.setattr("shutil.which", lambda name: "/vendor/qwen" if name == "qwen" else None)
    plan = service.dispatch(
        "connect.acp.login.plan", {"project": project["id"], "reference": "acp:qwen"}
    )
    assert plan["interactive"] and plan["argv"] == ["/vendor/qwen"]
    assert "/auth" in plan["instructions"] and "region" in plan["instructions"]


def test_all_running_engines_precede_hardware_presets(desktop, monkeypatch):
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
    rows = local_quickstart.catalog(service, project["id"])["choices"]
    assert {r["engine"] for r in rows[:5]} == set(engines)
    presets = {r["preset"]: r for r in rows[5:]}
    assert {"fast", "balanced", "capable"} <= presets.keys()
    assert presets["fast"]["suggested_context"] < presets["capable"]["suggested_context"]


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
