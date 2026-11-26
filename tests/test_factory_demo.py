"""Disposable onboarding projects use the real Factory and protected probe engine."""
# ruff: noqa: F811

import json
import os
from pathlib import Path
import subprocess

from click.testing import CliRunner
import pytest
import yaml

from test_factory_definition import project, admitted  # noqa: F401
from test_factory_studio import studio  # noqa: F401
from test_factory_verification import completed, simulated_probes  # noqa: F401
from superqode.commands.factory import factory
from superqode.factory import demo
from superqode.factory.authoring import parse
from superqode.factory.onboarding import inspect_setup, save_draft, load_draft, result_summary
from superqode.factory.verification import verify_factory


def test_create_is_self_contained_and_queues_no_work(tmp_path):
    root = tmp_path / "First Run"
    result = demo.create(root, confirmed=True)
    assert result["model_calls"] == 0 and not result["execution_started"]
    definition, snapshot = parse(root, (root / ".superqode/factory.yaml").read_text())
    assert snapshot.digest
    assert definition["improvement"]["checks"]["regression"]["evaluator"] == "acceptance"
    assert definition["orchestration"]["stages"][-1]["human_gate"]
    assert not (root / ".superqode/workorders").exists()
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=root) == b""
    assert inspect_setup(root)["demo_goal"] == demo.GOAL
    assert (root / "protected/acceptance.json").is_file()


def test_creation_requires_confirmation_and_refuses_existing_paths(tmp_path):
    root = tmp_path / "new"
    with pytest.raises(ValueError, match="Confirm"):
        demo.create(root)
    assert not root.exists()
    root.mkdir()
    (root / "keep").write_text("unchanged")
    with pytest.raises(ValueError, match="existing paths"):
        demo.create(root, confirmed=True)
    assert (root / "keep").read_text() == "unchanged"
    link = tmp_path / "dangling"
    link.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="existing paths"):
        demo.create(link, confirmed=True)
    assert link.is_symlink()


def test_creation_ignores_inherited_git_repository_environment(tmp_path, monkeypatch):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.setenv("GIT_DIR", str(unrelated))
    monkeypatch.setenv("GIT_WORK_TREE", str(unrelated))
    root = tmp_path / "demo"
    demo.create(root, confirmed=True)
    assert (root / ".git/HEAD").is_file()
    assert not list(unrelated.iterdir())


def test_cloud_model_requires_explicit_permission_before_writing(tmp_path):
    root = tmp_path / "cloud"
    with pytest.raises(ValueError, match="--allow-cloud"):
        demo.create(root, confirmed=True, model="openai/coder")
    assert not root.exists()
    demo.create(root, confirmed=True, model="openai/coder", allow_cloud=True)
    data = yaml.safe_load((root / ".superqode/factory.yaml").read_text())
    assert data["default_route"] == "best"
    assert data["inference"]["harnesses"]["coder"]["model"] == "openai/coder"


def test_cli_and_desktop_create_without_an_existing_project(tmp_path, studio):
    rpc, _, service = studio
    result = CliRunner().invoke(factory, ["demo", "create", str(tmp_path / "cli"), "--confirm"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["model_calls"] == 0
    created = service.dispatch(
        "factory.demo.create", {"destination": str(tmp_path / "desktop"), "confirmed": True}
    )
    assert Path(created["project"]).is_dir()
    assert not service.processes


def test_probe_diagnostic_is_explicit_and_fails_closed_without_isolation(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    demo.create(root, confirmed=True)
    with pytest.raises(ValueError, match="--execute"):
        demo.check(root)
    monkeypatch.setattr(
        demo,
        "run_python_probe",
        lambda *args, **kwargs: {
            "kind": "completed",
            "backend": "none",
            "returncode": 0,
            "stdout": "5\n",
        },
    )
    result = demo.check(root, execute=True)
    assert result["status"] == "blocked"
    assert not result["release_authorized"]
    assert not (root / ".superqode/workorders").exists()


@pytest.mark.skipif(
    os.environ.get("SUPERQODE_VERIFY_NATIVE") != "1", reason="Real protected OS probes"
)
def test_native_sample_fails_then_repair_passes_without_creating_quality_evidence(tmp_path):
    root = tmp_path / "demo"
    demo.create(root, confirmed=True)
    original = (root / ".superqode/factory.yaml").read_bytes()
    before = demo.check(root, execute=True)
    assert before["status"] == "failed"
    assert [r["status"] for r in before["cases"]] == ["failed", "failed", "passed"]
    path = root / "app.py"
    path.write_text(path.read_text().replace("result = value", "result += value"))
    after = demo.check(root, execute=True)
    assert after["status"] == "passed"
    assert after["model_calls"] == 0 and not after["release_authorized"]
    assert (root / ".superqode/factory.yaml").read_bytes() == original
    assert not (root / ".superqode/workorders").exists()


def test_draft_survives_sessions_without_activating_and_rejects_base_drift(project):
    path = project / ".superqode/factory.yaml"
    original = path.read_text()
    draft = original + "\n# Next session\n"
    with pytest.raises(ValueError, match="confirm"):
        save_draft(project, yaml_text=draft)
    assert not inspect_setup(project)["draft_available"]
    assert (
        save_draft(
            project,
            yaml_text=draft,
            confirmed=True,
            description="Repair exports",
            drafting_model="ollama/coder",
        )["activated"]
        is False
    )
    restored = load_draft(project)
    assert restored["yaml"] == draft
    assert restored["description"] == "Repair exports"
    assert restored["drafting_model"] == "ollama/coder"
    assert path.read_text() == original
    stored = project / ".superqode/factory-studio/onboarding-draft.json"
    assert stored.stat().st_mode & 0o077 == 0
    path.write_text(original + "\n# Changed independently\n")
    with pytest.raises(ValueError, match="saved Factory changed"):
        load_draft(project)
    assert stored.exists()


def test_invalid_draft_cannot_replace_previous_checkpoint(project):
    text = (project / ".superqode/factory.yaml").read_text()
    save_draft(project, yaml_text=text, confirmed=True)
    with pytest.raises(ValueError):
        save_draft(project, yaml_text="api_key: pasted-credential", confirmed=True)
    assert load_draft(project)["yaml"] == text


def test_desktop_connection_findings_link_to_setup_only_after_explicit_check(studio, monkeypatch):
    rpc, _, service = studio
    original = service.dispatch
    calls = []

    def dispatch(method, params):
        if method == "providers.check":
            calls.append(params)
            return {
                "ready": False,
                "state": "model-unavailable",
                "message": "Start your local model server.",
            }
        return original(method, params)

    monkeypatch.setattr(service, "dispatch", dispatch)
    rpc("onboarding.inspect")
    assert not calls
    report = rpc("onboarding.inspect", check_connections=True)
    assert calls and all(row["harness"] == "coder" for row in calls)
    assert any(a["connection"] == "source:local" for a in report["actions"])
    assert report["model_calls"] == 0


def test_queued_summary_is_honest_about_unknown_cost_and_human_release(project):
    _, _, order = admitted(project)
    summary = result_summary(project, order.work_order_id)
    assert not summary["verified"]
    assert summary["usage"]["cost_usd"] is None
    assert "Unknown cost" in summary["text"]
    assert not summary["release"]["authorized"]
    assert not summary["written"]


def test_verified_summary_shared_with_cli_and_desktop(completed, simulated_probes, tmp_path):
    root, _, identity = completed
    verify_factory(identity, root=root)
    summary = result_summary(root, identity)
    assert summary["verified"]
    assert summary["changed_files"] == ["app.py"]
    assert "SuperGauge: ship" in summary["text"]
    assert not summary["release"]["authorized"]
    result = CliRunner().invoke(factory, ["evidence", "summary", identity, "--project", str(root)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == json.loads(json.dumps(summary))
    from superqode.desktop_service.service import DesktopService

    service = DesktopService(tmp_path / "summary-desktop")
    try:
        project_id = service.open_project(str(root))["id"]
        assert (
            service.dispatch("factory.onboarding.result", {"project": project_id, "run": identity})
            == summary
        )
    finally:
        service.close()


@pytest.mark.skipif(
    os.environ.get("SUPERQODE_VERIFY_NATIVE") != "1", reason="Real protected OS probes"
)
async def test_sample_runs_through_real_worker_gate_and_protected_verification(
    tmp_path, monkeypatch
):
    from superqode.workorders import runner

    root = tmp_path / "sample"
    demo.create(root, confirmed=True)
    _, store, order = admitted(root)

    async def execute(order, task, *, working_directory, **kwargs):
        assert not (working_directory / "protected/acceptance.json").exists()
        if task.task_id == "implement":
            path = working_directory / "app.py"
            path.write_text(path.read_text().replace("result = value", "result += value"))
        return {
            "content": "Controlled response for onboarding lifecycle test",
            "stopped_reason": "complete",
            "tool_calls": 1,
        }

    monkeypatch.setattr(runner, "_execute_harness_task", execute)
    first = await runner.run_until_idle(store, work_order_id=order.work_order_id)
    assert [r.status for r in first] == ["succeeded", "succeeded"]
    waiting = store.get(order.work_order_id)
    assert waiting.tasks[-1].status.value == "waiting_for_human"
    assert result_summary(root, order.work_order_id)["pending_human_gates"] == ["verify"]
    store.decide_gate(
        order.work_order_id,
        "verify",
        expected_digest=waiting.tasks[-1].metadata["gate_digest"],
        decision="approve",
        actor="test-owner",
    )
    final = await runner.run_until_idle(store, work_order_id=order.work_order_id)
    assert [r.status for r in final] == ["succeeded"]
    verify_factory(order.work_order_id, root=root)
    summary = result_summary(root, order.work_order_id)
    assert summary["verified"]
    assert summary["checks"]["passed"] == 1
    assert not summary["release"]["authorized"]
    assert inspect_setup(root)["verified_trial"]
