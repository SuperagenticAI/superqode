"""External optimizers supply bounded proposals, never comparison authority."""
# ruff: noqa: F811

import json

import pytest
import yaml

from test_factory_definition import project  # noqa: F401
from test_factory_improvement import prepared  # noqa: F401
from superqode.factory import improvement
from superqode.factory.external import import_candidate


def artifact(root, plan, engine, *, widen=False):
    directory = root / ".superqode/external-optimizers" / engine / "run"
    workspace = directory / "workspace"
    workspace.mkdir(parents=True)
    proposal = yaml.safe_load(improvement.baseline_proposal(root, plan))
    proposal["agents"][0]["system_prompt"] = "Check the requested response format carefully."
    if widen:
        proposal["execution_policy"]["allow_network"] = not proposal["execution_policy"][
            "allow_network"
        ]
    (workspace / "harness.yaml").write_text(yaml.safe_dump(proposal))
    if engine == "metaharness":
        (directory / "indexes").mkdir()
        (directory / "indexes/leaderboard.json").write_text(
            json.dumps({"best_candidate_id": "c0001", "best_objective": 9999})
        )
        manifest = directory / "candidates/c0001/manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"candidate_id": "c0001", "workspace_dir": str(workspace), "accepted": True})
        )
        return directory.relative_to(root).as_posix()
    (directory / "result.json").write_text(
        json.dumps(
            {
                "staged_spec_path": str(workspace / "harness.yaml"),
                "accepted": True,
                "best_score": 9999,
            }
        )
    )
    return (directory / "result.json").relative_to(root).as_posix()


@pytest.mark.parametrize("engine", ["metaharness", "omni"])
def test_candidate_import_preserves_gates_and_does_not_trust_external_scores(prepared, engine):
    root, plan = prepared
    before = (root / ".superqode/factory.yaml").read_bytes()
    value = import_candidate(root, plan["id"], engine=engine, artifact=artifact(root, plan, engine))
    assert value["candidate"]
    assert not value["origin"]["adoption_authorized"]
    assert not value["origin"]["external_scores_authoritative"]
    assert not value["origin"]["external_usage_included"]
    assert not value["origin"]["execution_started"]
    assert improvement.budget(root, plan).summary()["request_count"] == 0
    assert not (improvement.folder(root, plan["id"]) / "comparison/receipt.json").exists()
    assert (root / ".superqode/factory.yaml").read_bytes() == before
    origins = list((improvement.folder(root, plan["id"]) / "origins").glob("*.json"))
    assert len(origins) == 1
    assert json.loads(origins[0].read_text())["source_digest"].startswith("sha256:")


@pytest.mark.parametrize("engine", ["metaharness", "omni"])
def test_external_optimizer_cannot_widen_factory_permissions(prepared, engine):
    root, plan = prepared
    with pytest.raises(ValueError, match="protected"):
        import_candidate(
            root, plan["id"], engine=engine, artifact=artifact(root, plan, engine, widen=True)
        )
    assert not (improvement.folder(root, plan["id"]) / "origins").exists()


@pytest.mark.parametrize(
    "incoming", ["../escape", "/outside", ".ssh/run", ".env/run", "experiments//run"]
)
def test_external_artifact_path_is_project_local_and_canonical(prepared, incoming):
    root, plan = prepared
    with pytest.raises(ValueError):
        import_candidate(root, plan["id"], engine="metaharness", artifact=incoming)


def test_external_workspace_symlink_and_unsafe_best_id_are_rejected(prepared):
    root, plan = prepared
    value = artifact(root, plan, "metaharness")
    directory = root / value
    manifest = directory / "candidates/c0001/manifest.json"
    data = json.loads(manifest.read_text())
    data["workspace_dir"] = str(root.parent / "outside")
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="inside"):
        import_candidate(root, plan["id"], engine="metaharness", artifact=value)
    data["workspace_dir"] = str(directory / "linked")
    manifest.write_text(json.dumps(data))
    (directory / "linked").symlink_to(directory / "workspace", target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        import_candidate(root, plan["id"], engine="metaharness", artifact=value)
    (directory / "indexes/leaderboard.json").write_text(
        json.dumps({"best_candidate_id": "../../escape"})
    )
    with pytest.raises(ValueError, match="safe best"):
        import_candidate(root, plan["id"], engine="metaharness", artifact=value)


def test_external_import_cannot_interleave_with_a_metered_action(prepared):
    root, plan = prepared
    value = artifact(root, plan, "omni")
    with improvement.budget(root, plan).action():
        with pytest.raises(ValueError, match="owns"):
            import_candidate(root, plan["id"], engine="omni", artifact=value)


def test_native_import_requires_confirmation_and_cannot_authorize_adoption(
    prepared, tmp_path, monkeypatch
):
    from superqode.desktop_service.service import DesktopService

    root, initial = prepared
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(root))["id"]

        def rpc(action, **params):
            return service.dispatch(
                "factory.improvement." + action, {"project": identity, **params}
            )

        plan = rpc(
            "prepare",
            binding="coder",
            tasks=initial["tasks"],
            fixture="fixture",
            max_evals=2,
            max_seconds=60,
            reflection_model="",
            optimizer_engine="evaluator-optimizer",
        )
        value = artifact(root, plan, "metaharness")
        with pytest.raises(ValueError, match="Explicitly"):
            rpc("external.import", plan=plan["id"], engine="metaharness", path=value)
        staged = rpc(
            "external.import", plan=plan["id"], engine="metaharness", path=value, confirmed=True
        )
        with pytest.raises(ValueError):
            rpc(
                "adopt",
                plan=plan["id"],
                candidate=staged["candidate"],
                confirmed=True,
                comparison_job="external",
            )
        assert not service.processes
    finally:
        service.close()
