import subprocess
from types import SimpleNamespace

import pytest

from superqode.workorders.evidence import (
    source_manifest,
    evidence_validity,
    publish_evidence,
    dependency_catalog,
    read_workorder_evidence,
)
from superqode.workorders.models import WorkOrder, WorkOrderTask
from superqode.workorders.store import WorkOrderStore


def setup(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "app.py").write_text("original")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-qm",
            "Initial",
        ],
        check=True,
    )
    monkeypatch.setenv("SUPERQODE_CONTEXT_STORE", str(tmp_path / "context.sqlite"))
    store = WorkOrderStore(tmp_path / "work.sqlite")
    investigator = WorkOrderTask("investigate", "Investigate", "Find failure")
    dependent = WorkOrderTask(
        "implement", "Implement", "Fix failure", dependencies=("investigate",)
    )
    order = store.create(
        WorkOrder(
            "work-test",
            "Fix failure",
            str(root),
            tasks=(investigator, dependent),
            metadata={"evidence_reuse": True},
        )
    )
    return root, store, order, investigator, dependent


def test_publish_reuse_restart_staleness_and_scope(tmp_path, monkeypatch):
    root, store, order, investigator, dependent = setup(tmp_path, monkeypatch)
    artifact = publish_evidence(store, order, investigator, "Failure is in app.py", root)
    order = WorkOrderStore(store.path).get(order.work_order_id)
    catalog = dependency_catalog(order, dependent, root)
    assert catalog[0]["freshness"] == "current"
    assert catalog[0]["verification"] == "reported"
    scope = SimpleNamespace(
        store=store, work_order_id=order.work_order_id, task_id=dependent.task_id
    )
    page = read_workorder_evidence(scope, artifact.metadata["reference"], root)
    assert "current" in page.text and "Failure is in app.py" in page.text
    scope.task_id = investigator.task_id
    with pytest.raises(LookupError):
        read_workorder_evidence(scope, artifact.metadata["reference"], root)
    (root / "app.py").write_text("modified")
    assert dependency_catalog(order, dependent, root)[0]["freshness"] == "stale"


@pytest.mark.parametrize("mutation", ["new", "deleted", "config", "environment"])
def test_manifest_invalidates_changes(tmp_path, monkeypatch, mutation):
    root, _, _, _, _ = setup(tmp_path, monkeypatch)
    manifest = source_manifest(root, env_names=("TEST_EVIDENCE_ENV",))
    assert evidence_validity(manifest, root)["freshness"] == "current"
    if mutation == "new":
        (root / "new.py").write_text("new dependency")
    elif mutation == "deleted":
        (root / "app.py").unlink()
    elif mutation == "config":
        (root / ".superqode").mkdir()
        (root / ".superqode/policy.yaml").write_text("changed policy")
    else:
        monkeypatch.setenv("TEST_EVIDENCE_ENV", "changed")
    assert evidence_validity(manifest, root)["freshness"] == "stale"


def test_incomplete_manifests_do_not_establish_freshness(tmp_path, monkeypatch):
    root, _, _, _, _ = setup(tmp_path, monkeypatch)
    manifest = source_manifest(root, max_bytes=1)
    assert evidence_validity(manifest, root)["freshness"] == "unknown"
    assert evidence_validity({}, root)["freshness"] == "unknown"


def test_cli_catalog_and_read(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from superqode.commands.work import work
    import json

    root, store, order, investigator, _ = setup(tmp_path, monkeypatch)
    artifact = publish_evidence(store, order, investigator, "Finding", root)
    prefix = [
        "--store",
        str(store.path),
        "evidence",
        order.work_order_id,
        "--task",
        "implement",
        "--json",
    ]
    result = CliRunner().invoke(work, prefix)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["freshness"] == "current"
    result = CliRunner().invoke(
        work, prefix + ["--read", artifact.metadata["reference"], "--limit", "3"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["text"].endswith("Fin")


def test_supporting_tool_receipts_are_assigned_and_historical(tmp_path, monkeypatch):
    from superqode.harness.events import HarnessEvent
    from superqode.workorders.evidence import collect_supporting_evidence

    root, store, order, investigator, dependent = setup(tmp_path, monkeypatch)
    events = [
        HarnessEvent(
            "tool_call", {"tool_name": "read", "tool_call_id": "read-1", "args": {"path": "app.py"}}
        ),
        HarnessEvent(
            "tool_result",
            {"tool_name": "read", "tool_call_id": "read-1", "output": "original", "success": True},
        ),
    ]
    supporting = collect_supporting_evidence(order, investigator, events)
    publish_evidence(
        store, order, investigator, "Finding with source evidence", root, supporting=supporting
    )
    order = store.get(order.work_order_id)
    catalog = dependency_catalog(order, dependent, root)
    assert len(catalog) == 2
    assert catalog[1]["verification"] == "observed_output"
    assert catalog[1]["freshness"] == "unknown"
    scope = SimpleNamespace(
        store=store, work_order_id=order.work_order_id, task_id=dependent.task_id
    )
    assert read_workorder_evidence(scope, supporting[0]["reference"], root).text.endswith(
        "original"
    )


def test_derived_evidence_invalidated_by_replaced_predecessor(tmp_path, monkeypatch):
    root, store, order, investigator, dependent = setup(tmp_path, monkeypatch)
    publish_evidence(store, order, investigator, "First finding", root)
    publish_evidence(store, store.get(order.work_order_id), dependent, "Derived finding", root)
    order = store.get(order.work_order_id)
    third = WorkOrderTask(
        "review", "Review", "Review derived findings", dependencies=("implement",)
    )
    assert dependency_catalog(order, third, root)[0]["freshness"] == "current"
    publish_evidence(store, order, investigator, "Corrected finding", root)
    assert (
        dependency_catalog(store.get(order.work_order_id), third, root)[0]["reason"]
        == "changed_predecessor_evidence"
    )


def test_unchanged_sources_valid_across_worktrees(tmp_path, monkeypatch):
    root, _, _, _, _ = setup(tmp_path, monkeypatch)
    manifest = source_manifest(root)
    worktree = tmp_path / "worker"
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "--detach", str(worktree)],
        check=True,
        capture_output=True,
    )
    assert evidence_validity(manifest, worktree)["freshness"] == "current"


def test_receipts_cannot_be_assigned_to_another_producer(tmp_path, monkeypatch):
    from superqode.harness.events import HarnessEvent
    from superqode.workorders.evidence import collect_supporting_evidence

    root, store, order, investigator, dependent = setup(tmp_path, monkeypatch)
    receipts = collect_supporting_evidence(
        order,
        investigator,
        [
            HarnessEvent("tool_call", {"tool_call_id": "c", "args": {"path": "app.py"}}),
            HarnessEvent(
                "tool_result",
                {"tool_call_id": "c", "tool_name": "read", "output": "original", "success": True},
            ),
        ],
    )
    assert receipts
    artifact = publish_evidence(
        store, order, dependent, "Derived finding", root, supporting=receipts
    )
    assert artifact.metadata["supporting"] == []


def test_workflow_receipts_keep_step_authority_separate(tmp_path, monkeypatch):
    from superqode.harness.events import HarnessEvent
    from superqode.workorders.evidence import collect_supporting_evidence
    from superqode.harness.context_artifacts import ContextArtifactStore

    _, _, order, task, _ = setup(tmp_path, monkeypatch)
    references = []
    for step, path in (("first", "old.py"), ("second", "new.py")):
        events = [
            HarnessEvent("tool_call", {"tool_call_id": "same", "args": {"path": path}}),
            HarnessEvent(
                "tool_result",
                {
                    "tool_call_id": "same",
                    "tool_name": "read",
                    "output": "same bytes",
                    "success": True,
                },
            ),
        ]
        references.extend(
            collect_supporting_evidence(order, task, events, invocation_namespace=step)
        )
    assert len(references) == 2 and references[0]["reference"] != references[1]["reference"]
    artifacts = ContextArtifactStore()
    assert [
        artifacts.describe(order.work_order_id, ref["reference"]).metadata["arguments"]["path"]
        for ref in references
    ] == ["old.py", "new.py"]


def test_core_worker_checks_revoked_origin_permission_for_assigned_receipts(tmp_path, monkeypatch):
    from superqode.agent.loop import AgentLoop
    from superqode.harness.events import HarnessEvent
    from superqode.workorders.evidence import collect_supporting_evidence
    from superqode.execution_recovery import RecoveryScope, recovery_scope
    from superqode.tools.permissions import Permission

    root, store, order, producer, dependent = setup(tmp_path, monkeypatch)
    receipts = collect_supporting_evidence(
        order,
        producer,
        [
            HarnessEvent("tool_call", {"tool_call_id": "read", "args": {"path": "app.py"}}),
            HarnessEvent(
                "tool_result",
                {
                    "tool_call_id": "read",
                    "tool_name": "read",
                    "output": "original",
                    "success": True,
                },
            ),
        ],
    )
    publish_evidence(store, order, producer, "Finding", root, supporting=receipts)
    core = AgentLoop.__new__(AgentLoop)
    core.session_id = "different-session"
    core.config = SimpleNamespace(working_directory=root, harness_spec=None)
    core.permission_manager = SimpleNamespace(
        check_permission=lambda name, args: (
            Permission.DENY if name == "read_file" else Permission.ALLOW
        )
    )
    with recovery_scope(RecoveryScope(store, order.work_order_id, dependent.task_id, "worker", 1)):
        with pytest.raises(PermissionError):
            core._context_page(receipts[0]["reference"])


@pytest.mark.asyncio
async def test_runner_publishes_evidence_and_passes_addressable_dependencies(tmp_path, monkeypatch):
    from superqode.workorders import runner
    from superqode.workspace.worktree import GitWorktreeManager

    monkeypatch.setattr(GitWorktreeManager, "WORKTREE_ROOT", tmp_path / "working")
    monkeypatch.setattr(GitWorktreeManager, "SESSION_REGISTRY", tmp_path / "working" / "_sessions")

    root, store, order, _, _ = setup(tmp_path, monkeypatch)
    store.queue(order.work_order_id)
    prompts = []

    async def execute(order, task, **kwargs):
        prompts.append(
            runner._task_prompt(order, task, working_directory=kwargs["working_directory"])
        )
        return {
            "content": "Observed failure",
            "session_id": "fixture",
            "run_id": task.task_id,
            "stopped_reason": "complete",
            "harness": "coding",
            "provider": "fixture",
            "model": "fixed",
            "runtime": "builtin",
        }

    monkeypatch.setattr(runner, "_execute_harness_task", execute)
    for _ in range(2):
        result = await runner.run_next_task(
            store, work_order_id=order.work_order_id, worker_id="fixture-worker"
        )
        assert result.status == "succeeded"
    finished = store.get(order.work_order_id)
    receipts = [a for a in finished.artifacts if a.kind == "evidence"]
    assert len(receipts) == 2
    assert receipts[0].metadata["reference"] in prompts[1]
    assert "reported" in prompts[1] and "read_context_chunk" in prompts[1]
