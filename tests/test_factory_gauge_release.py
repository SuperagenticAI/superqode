"""SuperGauge as the Factory release quality control, with hidden evaluators."""
# ruff: noqa: F811

import json
import shutil
import subprocess

import pytest

from test_factory_definition import project, rewrite  # noqa: F401
from test_factory_verification import make_completed, simulated_probes  # noqa: F401
from test_factory_release import signed
from superqode.factory import release, verification
from superqode.factory.protection import guard_governance, hidden_paths_scope
from superqode.factory.snapshot import canonical, digest
from superqode.gauge import decide, judge_effect, release_check
from superqode.governance import load_governance
from superqode.sandbox import local_sandbox


def _authority(project):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import base64

    key = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    ).decode()
    rewrite(
        project,
        lambda d: d["governance"].update(
            release_authority={
                "method": "p256-signature",
                "keys": {"owner": {"public_key": public}},
                "challenge_ttl_seconds": 60,
            }
        ),
    )
    return key


def test_model_judges_can_hold_or_reject_but_never_approve():
    for verdict in ("ship", "approve", "pass", "accepted"):
        with pytest.raises(ValueError, match="never approve"):
            judge_effect({"id": "j", "model": "m", "verdict": verdict})
    gates = [{"id": "task.completion", "result": "pass"}]
    assert decide(gates=gates)["verdict"] == "ship"
    held = decide(gates=gates, judges=[{"id": "j", "model": "m", "verdict": "hold"}])
    assert held["verdict"] == "hold"
    rejected = decide(gates=gates, judges=[{"id": "j", "model": "m", "verdict": "reject"}])
    assert rejected["verdict"] == "reject"
    assert (
        decide(gates=gates, judges=[{"id": "j", "model": "m", "verdict": "no_objection"}])[
            "verdict"
        ]
        == "ship"
    )
    assert decide(gates=[{"id": "x", "result": "fail"}])["verdict"] == "hold"


def test_release_check_requires_record_binding_and_level():
    assert "No SuperGauge record" in release_check(None)[0]
    record = {"subject": {"factory_digest": "a", "candidate": {"id": "c", "digest": "d"}}}
    problems = release_check(record, factory_digest="b", candidate_id="c", candidate_digest="e")
    assert any("different factory revision" in p for p in problems)
    assert any("candidate digest changed" in p for p in problems)
    assert any("L1 not met" in p for p in problems)


def test_ship_record_binds_revision_candidate_and_backs_signed_release(
    project, monkeypatch, simulated_probes
):
    key = _authority(project)
    root, store, run = make_completed(project, monkeypatch)
    result = verification.verify_factory(run, root=root)
    assert result["record"]["decision"]["verdict"] == "ship"
    status = release.release_status(run, root=root)
    assert status["ready_for_signature"] is True, status["blockers"]
    assert status["human_required"] is True
    assert status["gauge"]["verdict"] == "ship"
    assert status["gauge"]["bound_to_current"] is True
    assert status["gauge"]["highest_level"] == "L2"
    challenge = release.issue_challenge(run, root=root, key_id="owner")
    assert challenge["challenge"]["gauge_record_id"] == result["record"]["record_id"]
    approved = release.authorize_release(run, signed(challenge, key), root=root)
    assert approved.decision.actor == "p256:owner"


def test_model_judge_hold_blocks_release_with_clear_reason(project, monkeypatch, simulated_probes):
    _authority(project)
    root, store, run = make_completed(project, monkeypatch)
    judge = {"id": "reviewer", "model": "local/judge", "verdict": "hold"}
    result = verification.verify_factory(run, root=root, judges=[judge])
    assert result["record"]["decision"]["verdict"] == "hold"
    status = release.release_status(run, root=root)
    assert not status["ready_for_signature"]
    assert any("SuperGauge verdict is hold" in b for b in status["blockers"])
    with pytest.raises(ValueError, match="SuperGauge blocks release"):
        release.issue_challenge(run, root=root, key_id="owner")


def test_approving_model_judge_is_refused_before_verification(completed_run):
    root, store, run = completed_run
    with pytest.raises(ValueError, match="never approve"):
        verification.verify_factory(
            run, root=root, judges=[{"id": "j", "model": "m", "verdict": "ship"}]
        )


@pytest.fixture
def completed_run(project, monkeypatch):
    return make_completed(project, monkeypatch)


def test_stale_gauge_record_blocks_release(project, monkeypatch, simulated_probes):
    _authority(project)
    root, store, run = make_completed(project, monkeypatch)
    result = verification.verify_factory(run, root=root)
    stale = json.loads(json.dumps(result["record"]))
    stale["subject"]["candidate"]["digest"] = "0" * 64
    store.add_artifact(
        run,
        kind="factory_quality_record",
        content=canonical(stale),
        digest=digest(canonical(stale)),
        metadata={
            "verification_artifact_id": store.get(run).metadata["factory_verification"][
                "artifact_id"
            ]
        },
    )
    status = release.release_status(run, root=root)
    assert any("stale" in b for b in status["blockers"])
    with pytest.raises(ValueError, match="stale"):
        release.issue_challenge(run, root=root, key_id="owner")


def test_profile_level_above_record_blocks_release(project, monkeypatch, simulated_probes):
    _authority(project)
    rewrite(project, lambda d: d["governance"].update(release_gauge={"level": "L3"}))
    root, store, run = make_completed(project, monkeypatch)
    verification.verify_factory(run, root=root)
    status = release.release_status(run, root=root)
    assert status["gauge"]["required_level"] == "L3"
    assert any("L3 not met" in b for b in status["blockers"])


def test_missing_verification_is_a_clear_blocker(project, monkeypatch):
    _authority(project)
    root, store, run = make_completed(project, monkeypatch)
    status = release.release_status(run, root=root)
    assert "Protected verification has not run" in status["blockers"]
    assert any("No SuperGauge record" in b for b in status["blockers"])


def test_worker_working_copy_never_contains_evaluators(project, monkeypatch, simulated_probes):
    seen = []
    root, store, run = make_completed(project, monkeypatch, peek=seen)
    assert seen == [False]
    order = store.get(run)
    tasks = [
        a for a in order.artifacts if a.kind == "workspace" and a.metadata.get("scope") == "task"
    ]
    assert tasks and all(a.metadata["evaluators_hidden"] for a in tasks)
    assert "protected/probes.json" in tasks[0].metadata["hidden_paths"]
    record = verification.verify_factory(run, root=root)["record"]
    provenance = record["assurance"]["evaluator_provenance"]
    assert provenance["hidden_from_workers"] is True
    assert provenance["evaluators"]["regression"]["source_digest"].startswith("sha256:")
    # The application checkout keeps its evaluator.
    assert (root / "protected/probes.json").exists()


def test_worker_edit_to_protected_evaluator_is_dropped_flagged_and_rejected(
    project, monkeypatch, simulated_probes
):
    _authority(project)
    root, store, run = make_completed(project, monkeypatch, tamper=True)
    order = store.get(run)
    flags = [a for a in order.artifacts if a.kind == "factory_protected_write"]
    assert flags and json.loads(flags[0].content)["paths"] == ["protected/probes.json"]
    result = verification.verify_factory(run, root=root)
    candidate = next(a for a in store.get(run).artifacts if a.kind == "integration_candidate")
    assert "protected/probes.json" not in candidate.metadata["files"]
    assert result["record"]["decision"]["verdict"] == "reject"
    assert any("modify protected" in r for r in result["record"]["decision"]["reasons"])
    assert not release.release_status(run, root=root)["ready_for_signature"]


def test_protected_paths_are_denied_to_tools_and_recorded(project, monkeypatch):
    root, store, run = make_completed(project, monkeypatch)
    order = store.get(run)
    bundle, hits = guard_governance(load_governance(root), order)
    decision = bundle.engine.evaluate(
        __import__("superqode.governance", fromlist=["PolicyRequest"]).PolicyRequest(
            phase="tool_call", tool="read_file", arguments={"path": "../../protected/probes.json"}
        )
    )
    assert decision.action == "deny"
    assert hits == [{"tool": "read_file", "phase": "tool_call"}]


def _bwrap_usable():
    if shutil.which("bwrap") is None:
        return False
    probe = subprocess.run(
        ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "true"],
        capture_output=True,
    )
    return probe.returncode == 0


@pytest.mark.skipif(not _bwrap_usable(), reason="Requires a working Bubblewrap sandbox")
def test_worker_sandbox_cannot_see_evaluator_files(monkeypatch):
    import tempfile
    from pathlib import Path

    monkeypatch.setattr(local_sandbox, "_backend_for_platform", lambda: "bwrap")
    # The sandbox replaces /tmp, so place the fixture elsewhere on the host.
    base = Path("/var/tmp")
    if not base.is_dir() or base.resolve().is_relative_to("/tmp"):
        pytest.skip("Needs a host directory outside /tmp")
    with tempfile.TemporaryDirectory(dir=base) as folder:
        _check_hidden(Path(folder))


def _check_hidden(tmp_path):
    workspace = tmp_path / "work"
    workspace.mkdir()
    evaluators = tmp_path / "repo/.superqode/evaluators"
    evaluators.mkdir(parents=True)
    (evaluators / "probes.json").write_text("SECRET-EXPECTATION")
    single = tmp_path / "repo/protected.json"
    single.write_text("SECRET-FILE")
    command = f"cat {evaluators}/probes.json; cat {single}; echo done"
    open_plan = local_sandbox.build_sandboxed_command(command, workspace, mode="workspace-write")
    visible = subprocess.run(open_plan.argv, capture_output=True, text=True, cwd=workspace)
    assert "SECRET-EXPECTATION" in visible.stdout
    with hidden_paths_scope([str(evaluators), str(single)]):
        plan = local_sandbox.build_sandboxed_command(command, workspace, mode="workspace-write")
    hidden = subprocess.run(plan.argv, capture_output=True, text=True, cwd=workspace)
    assert "SECRET" not in hidden.stdout
    assert "done" in hidden.stdout


def test_seatbelt_profile_denies_hidden_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(local_sandbox, "_backend_for_platform", lambda: "seatbelt")
    with hidden_paths_scope([str(tmp_path / "evaluators")]):
        plan = local_sandbox.build_sandboxed_command("true", tmp_path, mode="workspace-write")
    profile = plan.argv[2]
    assert f'(deny file-read* file-write* (subpath "{tmp_path / "evaluators"}"))' in profile
