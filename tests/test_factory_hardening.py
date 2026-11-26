"""Factory privacy, evidence freshness and worker isolation contracts."""
# ruff: noqa: F401, F811

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest
import yaml

from test_factory_definition import project, rewrite, git
from test_factory_verification import make_completed, simulated_probes
from superqode.factory import authoring, verification
from superqode.factory.operations import readiness
from superqode.factory.protection import hidden_paths_scope, mask_targets, worker_scope
from superqode.factory.rlm_architect import architect_factory
from superqode.providers.gateway.base import GatewayResponse, Usage, Cost


@pytest.mark.parametrize("kind", ["legacy", "default", "versioned"])
async def test_architect_applies_effective_private_policy_before_model_calls(project, kind):
    class Gateway:
        async def chat_completion(self, **kwargs):
            pytest.fail("Private repository reached a cloud gateway")

    path = project / ".superqode/factory.yaml"
    if kind == "legacy":
        path.write_text("default_route: private\nroutes:\n  private:\n    allow_cloud: false\n")
    if kind == "default":
        path.unlink()
    result = await authoring.architect(
        project, provider="openai", model="fixture-model", gateway=Gateway()
    )
    assert result["rlm_lineage"]["mode"] == "rlm-local-inspect"
    assert result["usage"] is None
    assert any("Private route" in s for s in result["assumptions"])


@pytest.mark.parametrize("fail_second", [False, True])
async def test_architect_accounts_for_spend_and_durably_records_unknown_requests(
    project, fail_second
):
    rewrite(project, lambda d: d.update(default_route="best"))
    calls = []

    class Gateway:
        async def chat_completion(self, **kwargs):
            receipts = list((project / ".superqode/factory-studio/generation-usage").glob("*.json"))
            assert len(receipts) == 1
            assert any(
                c["state"] == "intent"
                for c in json.loads(receipts[0].read_text())["calls"].values()
            )
            calls.append(kwargs)
            if fail_second and len(calls) == 2:
                raise TimeoutError("controlled timeout")
            return GatewayResponse(
                content="{}",
                usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                cost=Cost(total_cost=0.25),
            )

    before = (project / ".superqode/factory.yaml").read_bytes()
    result = await authoring.architect(
        project, provider="openai", model="fixture-model", gateway=Gateway()
    )
    assert len(calls) == 2
    assert result["cost"]["total"] == (None if fail_second else 0.5)
    assert result["usage"]["unknown_cost_calls"] == int(fail_second)
    assert result["usage"]["calls"] == 2
    receipt = json.loads((project / result["generation_receipt"]).read_text())
    assert receipt["status"] == "complete"
    assert receipt["calls"]["subcall-2"]["state"] == ("uncertain" if fail_second else "recorded")
    draft = json.loads(
        (project / f".superqode/factory-studio/drafts/{result['digest']}.json").read_text()
    )
    assert draft["rlm_lineage"] == result["rlm_lineage"]
    assert draft["generation_receipt"] == result["generation_receipt"]
    assert (project / ".superqode/factory.yaml").read_bytes() == before


async def test_cancelled_architect_keeps_request_uncertainty(project):
    rewrite(project, lambda d: d.update(default_route="best"))

    class Gateway:
        async def chat_completion(self, **kwargs):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await authoring.architect(
            project, provider="openai", model="fixture-model", gateway=Gateway()
        )
    receipt = json.loads(
        next((project / ".superqode/factory-studio/generation-usage").glob("*.json")).read_text()
    )
    assert receipt["status"] == "incomplete"
    assert receipt["calls"]["subcall-1"]["state"] == "uncertain"
    assert receipt["calls"]["subcall-1"]["cost_usd"] is None


def test_readiness_executes_current_application_after_old_verification(
    project, monkeypatch, simulated_probes
):
    rewrite(
        project,
        lambda d: d["improvement"]["checks"]["regression"].update(
            category="health", command="exit 7"
        ),
    )
    root, _, run = make_completed(project, monkeypatch)
    verification.verify_factory(run, root=root)
    (root / "app.py").write_text("raise RuntimeError('new revision')\n")
    git(root, "add", "app.py")
    git(root, "commit", "-qm", "Changed application after verification")
    row = next(
        r
        for r in readiness(root, application=True, timeout=5)["application"]
        if r["id"] == "regression"
    )
    assert row["label"] == "execution_tested"
    assert row["status"] == "failed"
    assert row["evidence"]["returncode"] == 7


def test_task_repository_has_no_evaluator_objects_or_shared_alternates(project, monkeypatch):
    root, store, run = make_completed(project, monkeypatch)
    blob = git(root, "rev-parse", "HEAD:protected/probes.json")
    workspaces = [
        a
        for a in store.get(run).artifacts
        if a.kind == "workspace" and a.metadata.get("scope") == "task"
    ]
    for item in workspaces:
        worker = Path(item.path)
        assert (worker / ".git").is_dir()
        assert not (worker / ".git/objects/info/alternates").exists()
        assert git(worker, "rev-list", "--count", "HEAD") == "1"
        assert (
            subprocess.run(
                ["git", "-C", str(worker), "cat-file", "-e", blob], capture_output=True
            ).returncode
            != 0
        )
        assert item.metadata["worker_boundary"] == "sanitized-repository/1"


def test_evaluator_cannot_be_loaded_as_worker_context(project):
    from superqode.harness.templates import core_template
    from superqode.harness.loader import harness_spec_to_dict
    from superqode.factory import compile_factory, load_factory, resolve_factory

    asset = ".superqode/evaluators/acceptance.json"
    target = project / asset
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "format": "superqode.factory-probes/1",
                "cases": [{"id": "acceptance", "argv": ["python", "app.py"], "stdout": "READY\n"}],
            }
        )
    )
    spec = harness_spec_to_dict(core_template())
    spec["context"]["instruction_files"] = [asset]
    harness = project / ".superqode/components/coder.yaml"
    harness.parent.mkdir()
    harness.write_text(yaml.safe_dump(spec))
    rewrite(
        project,
        lambda d: (
            d["data_context"]["files"].update(acceptance={"purpose": "evaluator", "path": asset}),
            d["improvement"]["checks"]["regression"].update(evaluator="acceptance"),
            d["inference"]["harnesses"].update(
                coder={"path": ".superqode/components/coder.yaml", "model": "ollama/fixture-model"}
            ),
        ),
    )
    with pytest.raises(ValueError, match="worker instructions"):
        compile_factory(resolve_factory(load_factory(root=project)), root=project, goal="Fixture")


def test_legacy_shared_git_provenance_cannot_establish_independence(
    project, monkeypatch, simulated_probes
):
    root, store, run = make_completed(project, monkeypatch)
    order = store.get(run)
    artifacts = tuple(
        replace(a, metadata={k: v for k, v in a.metadata.items() if k != "worker_boundary"})
        if a.kind == "workspace"
        else a
        for a in order.artifacts
    )
    with store._transaction() as conn:
        store._save_tx(conn, replace(order, artifacts=artifacts))
    record = verification.verify_factory(run, root=root)["record"]
    assert record["assurance"]["evaluator_independent"] is False
    assert record["decision"]["verdict"] != "ship"


def test_previously_stored_quality_record_needs_current_boundary_proof(
    project, monkeypatch, simulated_probes
):
    from superqode.factory import release

    root, store, run = make_completed(project, monkeypatch)
    assert verification.verify_factory(run, root=root)["record"]["decision"]["verdict"] == "ship"
    order = store.get(run)
    artifacts = tuple(
        replace(a, metadata={k: v for k, v in a.metadata.items() if k != "worker_boundary"})
        if a.kind == "workspace"
        else a
        for a in order.artifacts
    )
    with store._transaction() as conn:
        store._save_tx(conn, replace(order, artifacts=artifacts))
    status = release.release_status(run, root=root)
    assert not status["ready_for_signature"]
    assert any("worker boundary" in s for s in status["blockers"])


def test_factory_file_tools_reject_controller_roots_and_symlink_aliases(tmp_path):
    from superqode.tools.validation import validate_path_in_search_scope
    from superqode.pipy.tools.paths import resolve_to_cwd

    root, worker = tmp_path / "controller", tmp_path / "worker"
    root.mkdir()
    worker.mkdir()
    secret = root / "synthetic.txt"
    secret.write_text("private fixture")
    (worker / "alias").symlink_to(root, target_is_directory=True)
    with worker_scope(worker, root):
        for path in (str(secret), "alias/synthetic.txt", "../controller/synthetic.txt"):
            with pytest.raises(ValueError, match="isolated repository"):
                validate_path_in_search_scope(path, worker, search_roots=[root])
            with pytest.raises(ValueError, match="isolated repository"):
                resolve_to_cwd(path, worker)
        with pytest.raises(ValueError, match="Git metadata"):
            resolve_to_cwd(".git/config", worker)
        with pytest.raises(ValueError, match="Git metadata"):
            resolve_to_cwd(".GIT/config", worker)
    assert validate_path_in_search_scope(str(secret), worker, search_roots=[root]) == secret


async def test_factory_shell_never_falls_back_to_host_execution(tmp_path, monkeypatch):
    from superqode.sandbox import local_sandbox
    from superqode.tools.shell_tools import BashTool

    monkeypatch.setattr(local_sandbox, "_backend_for_platform", lambda: "none")
    with worker_scope(tmp_path, tmp_path.parent):
        with pytest.raises(RuntimeError, match="OS sandbox"):
            await BashTool._spawn("echo forbidden", tmp_path)


@pytest.mark.skipif(
    os.environ.get("SUPERQODE_VERIFY_NATIVE") != "1", reason="Real OS boundary probes"
)
def test_native_worker_cannot_read_controller_or_process_root(project, monkeypatch):
    from superqode.sandbox.local_sandbox import build_sandboxed_argv

    root, store, run = make_completed(project, monkeypatch)
    order = store.get(run)
    worker = Path(
        next(
            a.path
            for a in order.artifacts
            if a.kind == "workspace"
            and a.task_id == "implement"
            and a.metadata.get("scope") == "task"
        )
    )
    snapshot = Path(order.metadata["factory"]["snapshot_directory"]) / "snapshot.json"
    script = """
import json, pathlib, subprocess, sys
def readable(name):
    try:
        pathlib.Path(name).read_bytes()
        return True
    except OSError:
        return False
print(json.dumps({'app': readable('app.py'), 'snapshot': readable(sys.argv[1]),
 'controller': readable(sys.argv[2]), 'process_root': readable(sys.argv[3]),
 'git': subprocess.run(['git','status','--porcelain'],capture_output=True).returncode,
 'diff_visible': b'app.py' in subprocess.run(['git','diff','--stat'],capture_output=True).stdout,
 'metadata_writable': subprocess.run(['git','config','core.fsmonitor','true'],capture_output=True).returncode == 0}))
"""
    # Copy the invocation into a real command scope. The project may be under
    # /tmp or /workspace; the boundary must hold independently of that location.
    proc_path = f"/proc/{os.getpid()}/root{root}/protected/probes.json"
    import sys

    with hidden_paths_scope(mask_targets(order)), worker_scope(worker, root):
        plan = build_sandboxed_argv(
            [
                sys.executable,
                "-c",
                script,
                str(snapshot),
                str(root / "protected/probes.json"),
                proc_path,
            ],
            worker,
            mode="off",
        )
        probe = subprocess.run(plan.argv, cwd=worker, capture_output=True, text=True, timeout=10)
    assert probe.returncode == 0, probe.stderr
    result = json.loads(probe.stdout)
    assert result == {
        "app": True,
        "snapshot": False,
        "controller": False,
        "process_root": False,
        "git": 0,
        "diff_visible": True,
        "metadata_writable": False,
    }
