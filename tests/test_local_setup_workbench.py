"""Local onboarding boundaries: isolated install, cache intent and ephemeral Hub access."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from superqode.local import install, storage, workbench, servers
from superqode.desktop_service import hub_access
from superqode.desktop_service.environment import selected_providers, job_environment
from test_desktop_service import desktop  # noqa: F401


@pytest.fixture
def home(monkeypatch, tmp_path):
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: folder))
    return folder


@pytest.mark.parametrize("uv", [True, False])
def test_mlx_install_never_targets_app_packages(home, monkeypatch, uv):
    monkeypatch.setattr(install.sys, "platform", "darwin")
    monkeypatch.setattr(install.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        install.shutil, "which", lambda name: "/bin/uv" if uv and name == "uv" else None
    )
    plan = install.install_plan("mlx")
    target = home / ".superqode/runtimes/mlx"
    assert str(target) in plan.steps[0]
    assert str(target / "bin/python") in plan.steps[1]
    assert plan.steps[-1][-1] == servers.MLX_REQUIREMENT
    assert "--system" not in plan.command and "site-packages" not in plan.command
    if not uv:
        assert plan.steps[0][:4] == (install.sys.executable, "-m", "venv", "--symlinks")
        assert plan.steps[1][1:4] == ("-I", "-m", "pip")


def test_mlx_server_uses_verified_managed_interpreter(home, monkeypatch, tmp_path):
    python = install.runtime_python("mlx")
    python.parent.mkdir(parents=True)
    python.write_text("fixture")
    probes = []
    monkeypatch.setattr(
        install.subprocess,
        "run",
        lambda argv, **kw: probes.append(argv) or SimpleNamespace(returncode=0),
    )
    install._MLX_PROBES.clear()
    manager = servers.ServerManager(registry_dir=tmp_path)
    assert manager.is_installed("mlx")
    argv, _, _ = manager.build_command("mlx", host="127.0.0.1", port=8080, model="/weights")
    assert argv[0] == str(python) and argv[1:3] == ["-m", "mlx_lm.server"]
    assert probes[0][1] == "-I"
    assert len(probes) == 1  # Short status refreshes do not repeatedly import MLX.


def test_failed_managed_mlx_import_does_not_report_installed(home, monkeypatch):
    python = install.runtime_python("mlx")
    python.parent.mkdir(parents=True)
    python.write_text("fixture")
    monkeypatch.setattr(install.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    assert not install.managed_mlx_installed(refresh=True)


def test_storage_change_preserves_files_and_is_shared_with_inventory(home, tmp_path):
    from superqode.local.inventory import _hf_cache_root

    old = home / "old-weights.gguf"
    old.write_text("keep")
    target = tmp_path / "model cache" / "hub"
    saved = storage.save(str(target))
    assert saved["custom"] and storage.cache_directory() == target
    assert _hf_cache_root() == target
    assert old.read_text() == "keep" and not target.exists()
    assert storage._file().stat().st_mode & 0o777 == 0o600
    storage.save("")
    assert not storage.status()["custom"] and old.exists()


@pytest.mark.parametrize(
    "value", ["relative/models", "/", "/Applications/Example.app/Contents/models", "bad\npath"]
)
def test_storage_rejects_invalid_or_bundle_paths(home, value):
    with pytest.raises(ValueError):
        storage.save(value)
    assert not storage._file().exists()


def test_storage_change_invalidates_reviews_but_not_weights(desktop, home, tmp_path):
    service, _, _ = desktop
    service._write(
        "INSERT INTO local_model_plans VALUES(?,?,?)", ("review", json.dumps({"source": "hf"}), 1)
    )
    service.dispatch("local.models.storage.set", {"hf_cache": str(tmp_path / "new-hub")})
    assert not service._all("SELECT * FROM local_model_plans")
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("active", "project", "local", "download", "running", "{}", None, 1, 1),
    )
    with pytest.raises(ValueError, match="Finish or cancel"):
        service.dispatch("local.models.storage.set", {"hf_cache": ""})
    assert storage.cache_directory() == tmp_path / "new-hub"


def test_late_download_review_cannot_restore_an_old_storage_destination(desktop, home, tmp_path):
    service, _, _ = desktop
    storage.save(str(tmp_path / "new-hub"))
    plan = {"action": "download", "source": "hf", "cache_dir": str(tmp_path / "old-hub")}
    digest = workbench.fingerprint(plan)
    service._write(
        "INSERT INTO local_model_plans VALUES(?,?,?)", (digest, json.dumps(plan), time.time())
    )
    with pytest.raises(ValueError, match="storage location changed"):
        service.dispatch("local.models.start", {"plan": digest, "expected_digest": digest})
    assert not service.dispatch("local.models.jobs", {})


def test_explicit_cache_is_used_for_review_and_download(home, monkeypatch, tmp_path):
    import huggingface_hub
    from superqode.providers.huggingface import fetch

    cache = tmp_path / "hub"
    storage.save(str(cache))
    monkeypatch.setattr(
        huggingface_hub.HfApi,
        "model_info",
        lambda *a, **k: SimpleNamespace(
            sha="a" * 40, gated=False, siblings=[SimpleNamespace(rfilename="model.gguf", size=100)]
        ),
    )
    lookups = []
    monkeypatch.setattr(
        huggingface_hub, "try_to_load_from_cache", lambda *a, **k: lookups.append(k) or None
    )
    plan = workbench.prepare(
        {
            "action": "download",
            "engine": "llama.cpp",
            "model": "publisher/model",
            "filename": "model.gguf",
        },
        tmp_path,
    )
    assert plan["cache_dir"] == str(cache) and lookups[0]["cache_dir"] == str(cache)
    calls = []
    monkeypatch.setattr(
        fetch, "download_file", lambda *a, **k: calls.append(k) or tmp_path / "model.gguf"
    )
    # The reviewed destination is immutable even if a preference changes later.
    storage.save(str(tmp_path / "other-hub"))
    workbench.run(plan, tmp_path, lambda *a: None)
    assert calls[0]["cache_dir"] == str(cache)


def test_hub_account_check_never_saves_or_returns_the_token(desktop, monkeypatch):
    import huggingface_hub

    service, _, _ = desktop
    secret = "hf_private_fixture"
    calls = []

    class API:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def whoami(self):
            return {"name": "fixture-user", "auth": {"accessToken": secret}}

    monkeypatch.setattr(huggingface_hub, "HfApi", API)
    result = service.dispatch("local.models.hub.verify", {"token": secret})
    assert result["name"] == "fixture-user" and secret not in json.dumps(result)
    assert calls == [{"endpoint": "https://huggingface.co", "token": secret}]
    assert not service.credentials
    assert secret not in json.dumps(service.dispatch("settings.get", {}))
    service.dispatch("providers.credentials.set", {"provider": "huggingface", "key": secret})
    assert hub_access.token(service) == secret
    assert service.dispatch("local.models.hub.status", {})["source"] == "App session / Keychain"


def test_hub_failure_hides_vendor_error_details(desktop, monkeypatch):
    import huggingface_hub

    service, _, _ = desktop

    class API:
        def __init__(self, **kwargs):
            pass

        def whoami(self):
            raise RuntimeError("Authorization: Bearer hf_secret_fixture")

    monkeypatch.setattr(huggingface_hub, "HfApi", API)
    with pytest.raises(ValueError) as error:
        service.dispatch("local.models.hub.verify", {"token": "hf_secret_fixture"})
    assert "hf_secret_fixture" not in str(error.value) and not service.credentials


def test_app_hub_token_reaches_metadata_and_worker_environment_but_never_plan(
    desktop, home, monkeypatch
):
    import huggingface_hub

    service, _, _ = desktop
    secret = "hf_private_metadata_fixture"
    service.dispatch("providers.credentials.set", {"provider": "huggingface", "key": secret})
    received = []

    class API:
        def __init__(self, **kwargs):
            received.append(kwargs)

        def model_info(self, *args, **kwargs):
            return SimpleNamespace(
                sha="a" * 40,
                gated=True,
                siblings=[SimpleNamespace(rfilename="model.gguf", size=100)],
            )

    monkeypatch.setattr(huggingface_hub, "HfApi", API)
    plan = service.dispatch(
        "local.models.prepare",
        {
            "action": "download",
            "source": "hf",
            "engine": "llama.cpp",
            "model": "publisher/model",
            "filename": "model.gguf",
        },
    )
    assert received == [{"token": secret}]
    assert plan["gated"] and secret not in json.dumps(plan)
    assert secret not in service._all("SELECT plan FROM local_model_plans")[0]["plan"]
    credentials = service.credential_environment(selected_providers("local", {"local_plan": plan}))
    assert credentials["HF_TOKEN"] == secret
    assert not service.credential_environment(
        selected_providers("local", {"local_plan": {"action": "install"}})
    )


def test_only_hub_download_workers_get_hub_credentials():
    for action, source, expected in [
        ("download", "hf", {"huggingface"}),
        ("download", "ollama", set()),
        ("install", None, set()),
        ("verify", None, set()),
    ]:
        assert (
            selected_providers("local", {"local_plan": {"action": action, "source": source}})
            == expected
        )
    assert job_environment({"HF_TOKEN": "secret", "OPENAI_API_KEY": "cloud"}, {}, allowed=()) == {}


def test_tui_inline_and_named_cache_options_use_server_contract(monkeypatch, tmp_path):
    from superqode.app_main import SuperQodeApp

    action, inline, error = servers.parse_inline_start(
        'ctx=8192 kv=q8_0 model="/model cache/one.gguf"'
    )
    assert action == "start" and not error and inline["kv_cache"] == "q8_0"
    engine, opts = SuperQodeApp._parse_serve_args("ollama --ctx 8192 --kv-cache q8_0")
    assert opts["kv_cache"] == inline["kv_cache"]
    manager = servers.ServerManager(registry_dir=tmp_path)
    _, env, _ = manager.build_command(engine, host="127.0.0.1", port=11434, **opts)
    assert env["OLLAMA_KV_CACHE_TYPE"] == "q8_0" and env["OLLAMA_CONTEXT_LENGTH"] == "8192"
    with pytest.raises(ValueError, match="not exposed"):
        SuperQodeApp._parse_serve_args("mlx --kv-cache q8_0")
    assert servers.parse_inline_start("kv=bogus")[0] == "error"
    assert servers.parse_inline_start("port=99999")[0] == "error"
    with pytest.raises(ValueError, match="needs a value"):
        SuperQodeApp._parse_serve_args("ollama --kv-cache")


def test_compatibility_includes_every_registered_runtime_without_certification(desktop):
    from superqode.runtime.registry import known_runtime_names
    from superqode.harness.backends.registry import known_harness_backend_names

    service, project, _ = desktop
    report = service.dispatch("local.models.compatibility", {"project": project["id"]})
    assert {row["id"] for row in report["backends"]} == set(known_runtime_names()) | set(
        known_harness_backend_names()
    )
    assert len(report["backends"]) == 28
    assert {row["id"] for row in report["backends"] if row["auto_route"]} == {
        "builtin",
        "pipy",
        "rlm",
        "adk",
        "openai-agents",
        "pydanticai",
    }
    assert all("Not certified" in row["verification"] for row in report["backends"])
    assert report["checks"] == []


def test_model_readiness_probes_require_review_and_keep_harness_status_unknown(
    monkeypatch, tmp_path
):
    from superqode.local import bench, smoke

    plan = workbench.prepare(
        {"action": "verify", "engine": "lmstudio", "model": "fixture-model"}, tmp_path
    )
    assert plan["endpoint"] == "http://127.0.0.1:1234/v1"
    monkeypatch.setattr(bench, "list_endpoint_models", lambda endpoint: ["fixture-model"])
    monkeypatch.setattr(
        smoke,
        "run_smoke",
        lambda **kw: smoke.SmokeReport(status="ready", endpoint=kw["endpoint"], model=kw["model"]),
    )
    result = workbench.run(plan, tmp_path, lambda *a: None)
    assert result["verification"]["status"] == "ready"
    assert result["harness_certified"] is False
    monkeypatch.setattr(bench, "list_endpoint_models", lambda endpoint: [])
    with pytest.raises(ValueError, match="no longer advertises"):
        workbench.run(plan, tmp_path, lambda *a: None)
