"""First-run guidance is shared, read-only and grounded in verification evidence."""
# ruff: noqa: F811

import json

from click.testing import CliRunner

from test_factory_definition import project, admitted, rewrite, git  # noqa: F401
from test_factory_verification import completed, simulated_probes  # noqa: F401
from test_factory_studio import studio  # noqa: F401
from superqode.commands.factory import factory
from superqode.factory.onboarding import inspect_setup, verified_trial
from superqode.factory.verification import verify_factory


def step(report, identity):
    return next(row for row in report["steps"] if row["id"] == identity)


def test_fresh_directory_explains_first_action_without_creating_state(tmp_path):
    report = inspect_setup(tmp_path)
    assert report["next_step"]["id"] == "definition"
    assert report["next_step"]["command"][2:5] == ["init", "--template", "fix-and-verify"]
    assert report["written"] is False and report["model_calls"] == 0
    assert not list(tmp_path.iterdir())


def test_route_only_policy_gets_safe_upgrade_guidance(project):
    path = project / ".superqode/factory.yaml"
    text = "default_route: private\nroutes: {}\n"
    path.write_text(text)
    report = inspect_setup(project)
    assert report["next_step"]["command"][2] == "init"
    assert "keep these routes" in report["next_step"]["detail"]
    assert path.read_text() == text


def test_starter_requires_protected_checks_and_never_claims_verified(project):
    original = (project / ".superqode/factory.yaml").read_bytes()
    report = inspect_setup(project)
    assert step(report, "definition")["status"] == "configured"
    assert step(report, "acceptance")["status"] == "missing"
    assert not report["verified_trial"]
    assert not (project / ".superqode/workorders").exists()
    assert (project / ".superqode/factory.yaml").read_bytes() == original


def test_unsaved_native_draft_points_to_review_and_save(project):
    path = project / ".superqode/factory.yaml"
    original = path.read_text()
    report = inspect_setup(project, yaml_text=original + "\n# Reviewed draft\n")
    assert report["next_step"]["id"] == "definition"
    assert report["next_step"]["status"] == "needs_save"
    assert report["next_step"]["destination"] == "Definition"
    assert path.read_text() == original


def test_missing_connection_is_actionable_and_does_not_rebind_models(project):
    checked = []

    def connection(*args):
        checked.append(args)
        return {"ready": False, "state": "missing-credential", "message": "Connect the provider."}

    report = inspect_setup(project, check_connection=connection)
    assert checked
    assert step(report, "models")["status"] == "missing"
    assert step(report, "models")["command"][2:4] == ["models", "--check-connections"]
    assert all(not row["inference_verified"] for row in report["models"]["execution"])


def test_cli_and_desktop_use_shared_checklist(studio):
    rpc, root, _ = studio
    expected = inspect_setup(root)
    result = CliRunner().invoke(factory, ["start", "--project", str(root), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == expected
    assert rpc("onboarding.inspect") == expected
    draft = rpc("open")["yaml"]
    assert rpc("onboarding.inspect", yaml=draft)["written"] is False


def test_queued_trial_points_to_worker_not_verification(project):
    _, _, order = admitted(project)
    report = inspect_setup(project)
    assert step(report, "trial")["command"][2:5] == ["worker", order.work_order_id, "--live"]
    assert not verified_trial(order)


def test_receipt_required_and_candidate_tampering_invalidates_progress(completed, simulated_probes):
    root, store, identity = completed
    before = inspect_setup(root)
    assert step(before, "acceptance")["status"] == "configured"
    assert not before["verified_trial"]
    assert step(before, "trial")["command"][2:5] == ["verify", identity, "--execute"]
    verify_factory(identity, root=root)
    after = inspect_setup(root)
    assert after["verified_trial"]
    assert step(after, "trial")["command"][2:5] == ["evidence", "trace", identity]
    order = store.get(identity)
    candidate = next(a for a in reversed(order.artifacts) if a.kind == "integration_candidate")
    candidate.metadata["candidate_tree"] = "tampered"
    assert not verified_trial(order)


def test_definition_drift_does_not_reuse_previous_trial(completed, simulated_probes):
    root, _, identity = completed
    verify_factory(identity, root=root)
    rewrite(root, lambda d: d["metadata"].update(name="Changed Factory"))
    assert not inspect_setup(root)["verified_trial"]


def test_new_application_baseline_requires_a_new_trial(completed, simulated_probes):
    root, _, identity = completed
    verify_factory(identity, root=root)
    (root / "another.py").write_text("print('new baseline')\n")
    git(root, "add", "another.py")
    git(root, "commit", "-qm", "New application baseline")
    report = inspect_setup(root)
    assert not report["verified_trial"]
    assert step(report, "trial")["command"][2] == "trial"
