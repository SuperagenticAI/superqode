import json
from types import SimpleNamespace

import pytest

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service import local_models, local_quickstart
from superqode.local.hardware import HardwareProfile


@pytest.fixture
def setup(desktop, monkeypatch):
    service, project, root = desktop
    status = dict(
        id="ollama",
        name="Ollama",
        installed=False,
        running=False,
        install={"automatic": True, "docs_url": "https://ollama.com/download"},
    )
    monkeypatch.setattr("superqode.local.context_contract.save_contract", lambda *args: None)
    models = []
    monkeypatch.setattr(
        "superqode.local.hardware.detect_hardware",
        lambda: HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=16),
    )
    monkeypatch.setattr(local_models, "servers", lambda service: [status])
    monkeypatch.setattr(local_models, "available", lambda engine: {"models": list(models)})
    monkeypatch.setattr("superqode.local.inventory.installed_chat_models", lambda: [])

    def prepare(service, options):
        plan = {**options, "id": options["action"], "digest": options["action"]}
        service._write(
            "INSERT OR REPLACE INTO local_model_plans VALUES(?,?,?)",
            (plan["id"], json.dumps(plan), 0),
        )
        return plan

    def start(service, params):
        assert params["expected_digest"] == params["plan"]
        identity = "job-" + params["command_id"]
        service._write(
            "INSERT INTO jobs(id,project,kind,status,request) VALUES(?,?,'local','running','{}')",
            (identity, project["id"]),
        )
        return {"id": identity}

    monkeypatch.setattr(local_models, "prepare", prepare)
    monkeypatch.setattr(local_models, "start", start)
    choices = service.dispatch("local.models.quickstart.catalog", {"project": project["id"]})[
        "choices"
    ]
    params = {"project": project["id"], "choice": choices[0]["id"]}
    return service, params, status, models, choices


def advance(service, params, step, result=None):
    reviewed = service.dispatch("local.models.quickstart.prepare", params)
    assert reviewed["step"] == step
    request = {
        **params,
        "plan": reviewed["plan"]["id"],
        "expected_digest": reviewed["plan"]["digest"],
        "command_id": step,
    }
    job = service.dispatch("local.models.quickstart.start", request)
    assert service.dispatch("local.models.quickstart.start", request) == job
    assert service.dispatch("local.models.quickstart.prepare", params)["step"] == "working"
    service._write(
        "UPDATE jobs SET status='completed',result=? WHERE id=?",
        (json.dumps(result or {}), job["id"]),
    )
    return job


def test_guided_chain_keeps_existing_steps_and_verified_selection_after_restart(setup):
    service, params, status, models, choices = setup
    advance(service, params, "install")
    status["installed"] = True
    advance(service, params, "serve")
    status["running"] = True
    advance(service, params, "download")
    models.append(choices[0]["model"])
    advance(
        service,
        params,
        "verify",
        {"verification": {"status": "passed", "readiness": {"status": "ready"}}},
    )
    assert service.dispatch("local.models.quickstart.prepare", params)["step"] == "ready"
    # Recreate the desktop service using the same persisted database.
    from superqode.desktop_service.service import DesktopService

    directory = service.root
    service.close()
    restored = DesktopService(directory)
    try:
        assert restored.dispatch("local.models.quickstart.prepare", params)["step"] == "ready"
        assert (
            restored.dispatch("local.models.quickstart.catalog", {"project": params["project"]})[
                "selected"
            ]
            == params["choice"]
        )
    finally:
        restored.close()


def test_failed_verification_requires_explicit_retry_without_redownload(setup):
    service, params, status, models, choices = setup
    status.update(installed=True, running=True)
    models.append(choices[0]["model"])
    advance(service, params, "verify", {"verification": {"status": "failed"}})
    assert service.dispatch("local.models.quickstart.prepare", params)["step"] == "retry"
    assert (
        service.dispatch("local.models.quickstart.prepare", {**params, "retry": True})["step"]
        == "verify"
    )


def test_active_setup_cannot_switch_models_or_admit_duplicate_work(setup):
    service, params, _, _, choices = setup
    review = service.dispatch("local.models.quickstart.prepare", params)
    service.dispatch(
        "local.models.quickstart.start",
        {
            **params,
            "plan": review["plan"]["id"],
            "expected_digest": review["plan"]["digest"],
            "command_id": "active",
        },
    )
    with pytest.raises(ValueError, match="Finish or cancel"):
        service.dispatch("local.models.quickstart.prepare", {**params, "choice": choices[1]["id"]})
    service._write("UPDATE jobs SET status='cancelled' WHERE id='job-active'")
    assert service.dispatch("local.models.quickstart.prepare", params)["step"] == "retry"


def test_manual_install_retains_selection_and_stale_review_is_rejected(setup):
    service, params, status, _, choices = setup
    status["install"]["automatic"] = False
    assert service.dispatch("local.models.quickstart.prepare", params)["step"] == "manual"
    assert local_quickstart._read(service, params["project"])["choice"] == params["choice"]
    status["install"]["automatic"] = True
    review = service.dispatch("local.models.quickstart.prepare", params)
    service.dispatch("local.models.quickstart.prepare", {**params, "choice": choices[1]["id"]})
    with pytest.raises(ValueError, match="selected model"):
        service.dispatch("local.models.quickstart.start", {**params, "plan": review["plan"]["id"]})


def test_existing_models_first_and_cloud_embedding_routes_excluded(setup):
    service, params, status, models, _ = setup
    status.update(installed=True, running=True)
    models.extend(["glm-local", "deepseek-local", "embeddinggemma", "qwen-cloud"])
    rows = service.dispatch("local.models.quickstart.catalog", {"project": params["project"]})[
        "choices"
    ]
    assert [row["model"] for row in rows[:2]] == ["glm-local", "deepseek-local"]
    assert not any(row["model"] in {"embeddinggemma", "qwen-cloud"} for row in rows)
    assert (
        service.dispatch("local.models.quickstart.prepare", {**params, "choice": rows[0]["id"]})[
            "step"
        ]
        == "verify"
    )


def test_disappearing_server_keeps_active_setup_observable(setup):
    service, params, status, models, _ = setup
    status.update(installed=True, running=True)
    models.append("my-local-glm")
    row = service.dispatch("local.models.quickstart.catalog", {"project": params["project"]})[
        "choices"
    ][0]
    params = {**params, "choice": row["id"]}
    review = service.dispatch("local.models.quickstart.prepare", params)
    job = service.dispatch(
        "local.models.quickstart.start",
        {
            **params,
            "plan": review["plan"]["id"],
            "expected_digest": review["plan"]["digest"],
            "command_id": "server-loss",
        },
    )
    status["running"] = False
    models.clear()
    catalog = service.dispatch("local.models.quickstart.catalog", {"project": params["project"]})
    assert any(choice["id"] == params["choice"] for choice in catalog["choices"])
    assert service.dispatch("local.models.quickstart.prepare", params) == {
        "step": "working",
        "job": job["id"],
    }


def test_running_server_needs_no_cli_installation(setup):
    service, params, status, models, choices = setup
    status.update(installed=False, running=True)
    models.append(choices[0]["model"])
    assert service.dispatch("local.models.quickstart.prepare", params)["step"] == "verify"


def test_lmstudio_guided_install_download_load_verify_chain(setup, monkeypatch):
    service, params, status, models, _ = setup
    status.update(id="lmstudio", name="LM Studio", cli_available=False)
    loaded = []
    monkeypatch.setattr(
        local_models,
        "available",
        lambda engine: {"models": list(models), "loaded_models": list(loaded)},
    )
    monkeypatch.setattr("shutil.which", lambda name: "/fixture/lms")
    choices = local_quickstart.catalog(service, params["project"])["choices"]
    row = next(r for r in choices if r["model"] == "qwen/qwen3.5-4b")
    params = {**params, "choice": row["id"]}
    advance(service, params, "install")
    status.update(installed=True, cli_available=True)
    review = local_quickstart.prepare(service, params)
    assert review["plan"]["model"] == ""  # Start before downloading, no accidental load.
    advance(service, params, "serve")
    status["running"] = True
    advance(service, params, "download")
    models.append(row["model"])
    advance(service, params, "load")
    loaded.append(row["model"])
    advance(
        service,
        params,
        "verify",
        {"verification": {"status": "passed", "readiness": {"status": "ready"}}},
    )
    assert local_quickstart.prepare(service, params)["step"] == "ready"


def test_lmstudio_catalog_alias_resolves_exact_downloaded_artifact(setup, monkeypatch):
    service, params, status, models, _ = setup
    status.update(id="lmstudio", name="LM Studio", installed=True, running=True)
    key = "lmstudio-community/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf"
    models.append(key)
    monkeypatch.setattr(
        local_models, "available", lambda engine: {"models": list(models), "loaded_models": []}
    )
    rows = local_quickstart.catalog(service, params["project"])["choices"]
    row = next(r for r in rows if r["model"] == "qwen/qwen3.5-4b")
    review = local_quickstart.prepare(service, {**params, "choice": row["id"]})
    assert review["step"] == "load"
    assert review["plan"]["model"] == key


def test_installed_disk_model_starts_or_refreshes_instead_of_downloading(setup, monkeypatch):
    service, params, status, _, _ = setup
    monkeypatch.setattr(
        "superqode.local.inventory.installed_chat_models",
        lambda: [{"engine": "ollama", "model": "qwen3:8b", "name": "qwen3:8b"}],
    )
    status.update(installed=True, running=False)
    rows = local_quickstart.catalog(service, params["project"])["choices"]
    row = next(item for item in rows if item["model"] == "qwen3:8b")
    assert row["installed"] is True
    assert row["preset"] != "suggested"
    reviewed = local_quickstart.prepare(service, {**params, "choice": row["id"]})
    assert reviewed["step"] == "serve"

    status["running"] = True
    reviewed = local_quickstart.prepare(service, {**params, "choice": row["id"]})
    assert reviewed["step"] == "manual"
    assert "will not download" in reviewed["message"]


def test_installed_lmstudio_weight_loads_instead_of_downloading(setup, monkeypatch):
    service, params, status, _, _ = setup
    status.update(id="lmstudio", name="LM Studio", installed=True, running=True)
    monkeypatch.setattr(
        local_models, "available", lambda engine: {"models": [], "loaded_models": []}
    )
    monkeypatch.setattr(
        "superqode.local.inventory.installed_chat_models",
        lambda: [
            {
                "engine": "lmstudio",
                "model": "publisher/model/file.gguf",
                "name": "file.gguf",
            }
        ],
    )
    rows = local_quickstart.catalog(service, params["project"])["choices"]
    row = next(item for item in rows if item["model"] == "publisher/model/file.gguf")
    assert local_quickstart.prepare(service, {**params, "choice": row["id"]})["step"] == "load"


def test_curated_tested_list_preserves_installed_models_and_previous_selection(setup, monkeypatch):
    from test_local_starter_registry import passing_report

    service, params, status, models, original = setup
    previous = original[0]
    local_quickstart._save(
        service, params["project"], {"choice": previous["id"], "selection": previous}
    )
    monkeypatch.setattr(
        "superqode.local.starter_registry.load_evidence", lambda *args: [passing_report()]
    )
    status.update(installed=True, running=True)
    models.append("custom-local-model")
    result = local_quickstart.catalog(service, params["project"])
    rows = result["choices"]
    recommended = [r for r in rows if r["preset"] == "suggested"]
    assert [r["model"] for r in recommended] == ["qwen3.5:4b"]
    assert recommended[0]["evaluation_status"] == "tested"
    assert "Tested in a local five-task run" in recommended[0]["detail"]
    assert rows[0]["model"] == "custom-local-model" and rows[0]["installed"]
    assert result["selected"] == previous["id"]
    assert next(r for r in rows if r["id"] == previous["id"])["preset"] == "previous"
