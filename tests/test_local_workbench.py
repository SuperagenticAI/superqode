from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from superqode.local import workbench
from superqode.local.hardware import HardwareProfile
from test_desktop_service import desktop  # noqa: F401


@pytest.fixture
def model_hub(monkeypatch):
    import huggingface_hub

    files = [
        SimpleNamespace(rfilename=name, size=size)
        for name, size in [
            ("model-Q4_K_M-00001-of-00002.gguf", 100),
            ("model-Q4_K_M-00002-of-00002.gguf", 90),
            ("config.json", 5),
            ("model.safetensors", 120),
            ("model.py", 10),
            ("../escape.gguf", 1),
        ]
    ]
    monkeypatch.setattr(
        huggingface_hub.HfApi,
        "model_info",
        lambda *a, **k: SimpleNamespace(sha="a" * 40, siblings=files, gated=False),
    )
    monkeypatch.setattr(
        workbench,
        "detect_hardware",
        lambda: HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=16),
    )
    return files


def test_pinned_download_plan_includes_all_shards_and_never_transfers_weights(
    model_hub, monkeypatch, tmp_path
):
    from superqode.providers.huggingface import fetch

    monkeypatch.setattr(
        fetch, "download_file", lambda *a, **k: pytest.fail("prepare downloaded weights")
    )
    plan = workbench.prepare(
        {
            "action": "download",
            "source": "hf",
            "model": "publisher/model-GGUF",
            "engine": "llama.cpp",
            "filename": "model-Q4_K_M-00002-of-00002.gguf",
        },
        tmp_path,
    )
    assert plan["revision"] == "a" * 40
    assert len(plan["files"]) == 2 and plan["total_bytes"] == 190
    assert plan["files"][0]["name"].endswith("00001-of-00002.gguf")
    assert plan["fit"]["likely_fits"]


def test_wrong_quantization_missing_shards_and_path_escape_are_rejected(model_hub, tmp_path):
    files = workbench.manifest("publisher/model")["files"]
    assert all(".." not in row["name"] for row in files)
    with pytest.raises(ValueError, match="advertised GGUF"):
        workbench.gguf_group(files, "other.gguf")
    with pytest.raises(ValueError, match="missing GGUF"):
        workbench.gguf_group(files[:1], files[0]["name"])
    with pytest.raises(ValueError, match="publisher/repository"):
        workbench.manifest("../escape")


def test_mlx_snapshot_excludes_repository_code(model_hub, tmp_path):
    plan = workbench.prepare(
        {"action": "download", "model": "mlx-community/model", "engine": "mlx", "format": "mlx"},
        tmp_path,
    )
    names = [row["name"] for row in plan["files"]]
    assert "config.json" in names and "model.safetensors" in names
    assert not any(name.endswith((".py", ".gguf")) for name in names)


def test_shared_cache_controls_are_typed_and_no_unsupported_flags_are_invented():
    assert workbench.cache_options("ollama", "q8_0")[1] == {
        "OLLAMA_KV_CACHE_TYPE": "q8_0",
        "OLLAMA_FLASH_ATTENTION": "1",
    }
    assert "--cache-type-v" in workbench.cache_options("llama.cpp", "q4_0")[0]
    assert workbench.cache_options("mlx", "auto") == ([], {})
    with pytest.raises(ValueError):
        workbench.cache_options("lmstudio", "q8_0")
    with pytest.raises(ValueError):
        workbench.cache_options("ollama", "q8_0; touch /tmp/no")


def test_exact_pinned_files_are_reused_during_execution(model_hub, monkeypatch, tmp_path):
    from superqode.providers.huggingface import fetch

    plan = workbench.prepare(
        {
            "action": "download",
            "source": "hf",
            "model": "publisher/model-GGUF",
            "engine": "llama.cpp",
            "filename": "model-Q4_K_M-00001-of-00002.gguf",
        },
        tmp_path,
    )
    calls = []

    def download(repo, file, **kwargs):
        calls.append((repo, file, kwargs))
        return tmp_path / file

    monkeypatch.setattr(fetch, "download_file", download)
    events = []
    result = workbench.run(plan, tmp_path, lambda kind, data: events.append((kind, data)))
    assert len(calls) == 2 and all(call[2]["revision"] == "a" * 40 for call in calls)
    assert result["serve_model"].endswith("00001-of-00002.gguf")
    assert events[-1][0] == "result"


def test_lmstudio_import_keeps_originals_and_uses_unambiguous_namespace(
    model_hub, monkeypatch, tmp_path
):
    from superqode.providers.huggingface import fetch

    plan = workbench.prepare(
        {
            "action": "download",
            "source": "hf",
            "model": "publisher/model-GGUF",
            "engine": "lmstudio",
            "filename": "model-Q4_K_M-00001-of-00002.gguf",
        },
        tmp_path,
    )
    monkeypatch.setattr(fetch, "download_file", lambda repo, file, **k: tmp_path / file)
    commands = []
    monkeypatch.setattr(workbench, "_command", lambda argv, emit: commands.append(argv))
    result = workbench.run(plan, tmp_path, lambda *a: None)
    assert len(commands) == 2
    assert all("--symbolic-link" in argv and "--user-repo" in argv for argv in commands)
    assert result["serve_model"].startswith("publisher/model-GGUF/")


def test_cloud_tags_are_not_local_and_mlx_plan_is_isolated(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="cloud model"):
        workbench.prepare(
            {"action": "download", "source": "ollama", "model": "model:cloud", "engine": "ollama"},
            tmp_path,
        )
    from superqode.local import install

    monkeypatch.setattr(install.sys, "platform", "darwin")
    monkeypatch.setattr(install.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(install.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(workbench.ServerManager, "is_running", lambda *args: False)
    plan = workbench.prepare({"action": "install", "engine": "mlx"}, tmp_path)
    assert str(tmp_path / ".superqode/runtimes/mlx") in plan["command"]
    assert plan["steps"][-1][-1] == "mlx-lm>=0.31.0,<0.32.0"
    assert "not modified" in plan["guidance"]


def test_reviewed_plans_require_digest_and_expire_without_creating_jobs(
    desktop, monkeypatch, model_hub
):
    service, _, _ = desktop
    plan = service.dispatch(
        "local.models.prepare",
        {"action": "download", "source": "ollama", "model": "model:8b", "engine": "ollama"},
    )
    assert not service.dispatch("local.models.jobs", {})
    with pytest.raises(ValueError, match="changed"):
        service.dispatch("local.models.start", {"plan": plan["id"], "expected_digest": "wrong"})
    service._write("UPDATE local_model_plans SET created=0")
    with pytest.raises(ValueError, match="expired"):
        service.dispatch(
            "local.models.start", {"plan": plan["id"], "expected_digest": plan["digest"]}
        )
    assert not service.dispatch("jobs.list", {})


def test_local_endpoint_selection_requires_advertised_model_and_eligible_harness(
    desktop, monkeypatch
):
    from superqode.desktop_service import local_models

    service, project, _ = desktop
    monkeypatch.setattr(
        local_models,
        "available",
        lambda engine: {
            "endpoint": "http://127.0.0.1:11434/v1",
            "provider": "ollama",
            "models": ["fixture:8b", "embed-fixture"],
        },
    )
    rows = service.dispatch("local.models.harnesses", {"project": project["id"]})
    assert next(row for row in rows if row["id"] == "core")["selectable"]
    params = {
        "project": project["id"],
        "engine": "ollama",
        "harness": "core",
        "model": "fixture:8b",
    }
    route = service.dispatch("local.models.use", params)
    assert route["endpoint"].startswith("http://127.0.0.1:")
    assert not service.dispatch("jobs.list", {})
    for replacement in [
        {"model": "not-advertised"},
        {"model": "embed-fixture"},
        {"harness": "codex-cli"},
    ]:
        with pytest.raises(ValueError):
            service.dispatch("local.models.use", {**params, **replacement})
    bindings = service._all("SELECT * FROM local_model_bindings")
    assert {row["harness"] for row in bindings} == {"core", "no-tool"}


def test_unknown_size_and_memory_are_not_a_fit_guarantee(monkeypatch):
    monkeypatch.setattr(workbench, "detect_hardware", lambda: HardwareProfile(platform="darwin"))
    report = workbench.fit("mystery")
    assert report["estimate_gb"] is None and not report["likely_fits"]


def test_q8_weights_are_not_recommended_as_q4_on_a_32gb_mac(monkeypatch):
    monkeypatch.setattr(
        workbench,
        "detect_hardware",
        lambda: HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=32),
    )
    report = workbench.fit("Qwen-30B-Q8_0")
    assert report["weights_gb"] == 31.5
    assert report["estimate_gb"] > 31.5
    assert not report["likely_fits"]


def test_native_install_job_is_projectless_idempotent_and_gets_no_provider_secrets(
    desktop, monkeypatch, tmp_path
):
    import os
    import sys
    from superqode.local.install import InstallPlan
    from test_desktop_service import wait_job

    service, _, _ = desktop
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "ollama").write_text("#!/bin/sh\nexit 0\n")
    (binary / "ollama").chmod(0o755)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("OPENAI_API_KEY", "private-cloud-fixture")
    monkeypatch.setenv("HF_TOKEN", "private-hub-fixture")
    marker = tmp_path / "installed.json"
    script = (
        "import json,os; from pathlib import Path; Path("
        + repr(str(marker))
        + ").write_text(json.dumps({'cloud':bool(os.environ.get('OPENAI_API_KEY')),'hub':bool(os.environ.get('HF_TOKEN'))}))"
    )
    monkeypatch.setattr(
        workbench,
        "install_plan",
        lambda engine: InstallPlan(
            engine,
            "Fixture runtime",
            ((sys.executable, "-c", script),),
            "Fixture only",
            "https://example.invalid",
        ),
    )
    plan = service.dispatch("local.models.prepare", {"action": "install", "engine": "ollama"})
    params = {"plan": plan["id"], "expected_digest": plan["digest"], "command_id": "one-install"}
    first = service.dispatch("local.models.start", params)
    assert service.dispatch("local.models.start", params) == first
    result = wait_job(service, first["id"])
    assert result["status"] == "completed", result
    assert json.loads(marker.read_text()) == {"cloud": False, "hub": False}
    assert len(service.dispatch("local.models.jobs", {})) == 1
    assert all(
        project["id"] != "local-model-workspace"
        for project in service.dispatch("projects.list", {})
    )
