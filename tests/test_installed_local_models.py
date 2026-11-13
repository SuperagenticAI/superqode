"""Installed Ollama and LM Studio models stay selectable without a download."""

import time

import pytest
from test_desktop_service import desktop  # noqa: F401

from superqode.desktop_service import local_models
from superqode.local.inventory import installed_chat_models


def test_disk_library_lists_ollama_and_lmstudio_without_a_running_server(tmp_path, monkeypatch):
    manifest = tmp_path / "manifests" / "registry.ollama.ai" / "library"
    (manifest / "qwen3").mkdir(parents=True)
    (manifest / "qwen3" / "8b").write_text("{}", encoding="utf-8")
    (manifest / "nomic-embed-text").mkdir()
    (manifest / "nomic-embed-text" / "latest").write_text("{}", encoding="utf-8")
    weights = tmp_path / "lmstudio" / "lmstudio-community" / "Qwen2.5-Coder-7B-GGUF"
    weights.mkdir(parents=True)
    (weights / "Qwen2.5-Coder-7B-Q4_K_M.gguf").write_bytes(b"GGUF")
    monkeypatch.setattr(
        "superqode.local.inventory._ollama_manifest_root", lambda: tmp_path / "manifests"
    )
    monkeypatch.setattr(
        "superqode.local.inventory._lmstudio_model_roots", lambda: [tmp_path / "lmstudio"]
    )
    monkeypatch.setattr("superqode.local.inventory.ollama_advertised_models", lambda: [])
    monkeypatch.setattr("superqode.local.inventory.lmstudio_advertised_models", lambda: [])

    rows = installed_chat_models()

    assert {row["model"] for row in rows} == {
        "qwen3:8b",
        "lmstudio-community/Qwen2.5-Coder-7B-GGUF/Qwen2.5-Coder-7B-Q4_K_M.gguf",
    }
    assert all(row["on_disk"] and not row["advertised"] for row in rows)


def test_advertised_server_model_wins_over_the_same_disk_entry(monkeypatch):
    monkeypatch.setattr(
        "superqode.local.inventory.ollama_advertised_models",
        lambda: [
            {
                "engine": "ollama",
                "model": "qwen3:8b",
                "name": "qwen3:8b",
                "loaded": True,
                "advertised": True,
                "on_disk": True,
                "size_gb": 4.8,
            }
        ],
    )
    monkeypatch.setattr(
        "superqode.local.inventory.ollama_disk_models",
        lambda limit=200: [
            {
                "engine": "ollama",
                "model": "qwen3:8b",
                "name": "qwen3:8b",
                "loaded": False,
                "advertised": False,
                "on_disk": True,
                "size_gb": None,
            }
        ],
    )
    monkeypatch.setattr("superqode.local.inventory.lmstudio_advertised_models", lambda: [])
    monkeypatch.setattr("superqode.local.inventory.lmstudio_disk_models", lambda limit=200: [])

    rows = installed_chat_models()

    assert len(rows) == 1
    assert rows[0]["advertised"] and rows[0]["loaded"]


def test_ollama_listing_survives_an_empty_openai_endpoint(monkeypatch):
    monkeypatch.setattr(
        "superqode.local.inventory.ollama_advertised_models",
        lambda: [{"model": "qwen3:8b", "loaded": False}],
    )

    def unavailable(*args, **kwargs):
        raise OSError("openai listing unavailable")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    route = local_models.available("ollama")
    assert route["models"] == ["qwen3:8b"]
    assert route["loaded_models"] == []
    assert route["provider"] == "ollama"


def test_installed_rpc_reports_engine_state(desktop, monkeypatch):
    service, _, _ = desktop
    monkeypatch.setattr(
        "superqode.local.inventory.installed_chat_models",
        lambda: [
            {
                "id": "installed-qwen",
                "engine": "lmstudio",
                "model": "publisher/model/file.gguf",
                "name": "file.gguf",
                "advertised": True,
                "on_disk": True,
                "loaded": False,
                "metadata": {"key": "do-not-ship"},
            }
        ],
    )
    monkeypatch.setattr(
        local_models,
        "servers",
        lambda service: [
            {"id": "ollama", "installed": True, "running": False},
            {"id": "lmstudio", "installed": True, "running": True},
        ],
    )

    result = service.dispatch("local.models.installed", {})

    assert result["models"][0]["model"] == "publisher/model/file.gguf"
    assert result["models"][0]["server_running"] is True
    assert "metadata" not in result["models"][0]
    assert {row["id"] for row in result["engines"]} == {"ollama", "lmstudio"}


def test_local_harness_list_keeps_native_runners_and_hides_acp_agents(desktop):
    service, project, _ = desktop
    rows = local_models.harnesses(service, project["id"])
    assert any(row["id"] == "core" and row["selectable"] for row in rows)
    assert rows
    # Core is the recommended default and always listed first.
    assert rows[0]["id"] == "core" and rows[0]["recommended"] is True
    assert sum(1 for row in rows if row["recommended"]) == 1
    ready = [row["selectable"] for row in rows[1:]]
    assert ready == sorted(ready, reverse=True)
    assert all(row["group"] == "superqode" for row in rows)
    assert all(not row["id"].startswith("attach:") for row in rows)
    assert all("fast-agent" not in row["id"] and "opencode" not in row["id"] for row in rows)
    with pytest.raises(ValueError, match="itself"):
        local_models.use(
            service,
            {
                "project": project["id"],
                "harness": "attach:fast-agent",
                "engine": "ollama",
                "model": "qwen3:8b",
            },
        )


def test_warmup_stays_on_the_local_machine_and_finishes_in_the_background(desktop, monkeypatch):
    service, _, _ = desktop
    with pytest.raises(ValueError, match="local"):
        local_models.warm(service, {"endpoint": "https://example.com/v1", "model": "qwen"})
    seen = {}

    def fake_bench(endpoint, model, prompt, max_tokens, extra):
        seen["endpoint"] = endpoint
        seen["model"] = model
        seen["extra"] = extra

        class Result:
            ok = True
            error = ""

        return Result()

    monkeypatch.setattr("superqode.local.bench.run_bench", fake_bench)
    started = local_models.warm(
        service,
        {"endpoint": "http://127.0.0.1:11434/v1", "model": "qwen3:8b", "engine": "ollama"},
    )
    status = started
    for _ in range(100):
        if status["status"] != "running":
            break
        time.sleep(0.01)
        status = local_models.warm_status(service, {"id": started["id"]})
    assert status["status"] == "completed", status
    assert seen["endpoint"] == "http://127.0.0.1:11434/v1"
    assert seen["model"] == "qwen3:8b"
    assert seen["extra"] == {"think": False}


def test_use_binds_whichever_native_harness_was_selected(desktop, monkeypatch):
    service, project, _ = desktop
    monkeypatch.setattr(
        local_models,
        "available",
        lambda engine: {
            "models": ["qwen3:8b"],
            "endpoint": "http://127.0.0.1:11434/v1",
            "provider": "ollama",
        },
    )
    choices = [
        row
        for row in local_models.harnesses(service, project["id"])
        if row["selectable"] and row["id"] != "core"
    ]
    selected = choices[0]["id"] if choices else "core"
    result = service.dispatch(
        "local.models.use",
        {
            "project": project["id"],
            "engine": "ollama",
            "model": "qwen3:8b",
            "harness": selected,
        },
    )
    assert result["harness"] == selected
    assert result["model"] == "qwen3:8b"
    assert result["provider"] == "ollama"
