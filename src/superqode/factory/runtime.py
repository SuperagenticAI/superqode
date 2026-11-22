"""Factory admission and integrity checks over durable WorkOrder execution."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re

from superqode.workorders.models import WorkOrder, WorkOrderStatus
from superqode.workorders.store import WorkOrderStore

from .compiler import (
    CompiledFactory,
    _compile_factory,
    materialize_snapshot,
    repository_revision,
)
from .definition import project_path
from .snapshot import FactorySnapshot, MAX_SNAPSHOT_BYTES


def is_factory_order(order: WorkOrder) -> bool:
    return "factory" in order.metadata or any(
        "factory_snapshot" in task.metadata for task in order.tasks
    )


def factory_store(root=".", *, read_only=False) -> WorkOrderStore:
    root = Path(root).resolve()
    path = project_path(root, ".superqode/workorders/store.sqlite3")
    return WorkOrderStore.read_only(path) if read_only else WorkOrderStore(path)


def factory_worktree_manager(order: WorkOrder):
    """Own factory execution resources inside the declared customer repository."""
    from superqode.workspace.worktree import GitWorktreeManager

    root = Path(order.repository)
    manager = GitWorktreeManager(root)
    manager.worktree_root = project_path(root, ".superqode/factory/worktrees")
    manager.session_registry = project_path(root, ".superqode/factory/worktrees/_sessions")
    return manager


def _contract(order: WorkOrder) -> dict:
    """Compare declared work without timestamps, leases, outputs or gate decisions."""
    data = order.to_dict()
    result = {
        key: data[key]
        for key in (
            "goal",
            "repository",
            "harness",
            "harness_version",
            "policy_lineage",
            "budget",
            "acceptance_tests",
        )
    }
    result["factory"] = order.metadata.get("factory")
    result["tasks"] = []
    for task in data["tasks"]:
        entry = {
            key: task[key]
            for key in (
                "task_id",
                "title",
                "goal",
                "role",
                "risk",
                "dependencies",
                "harness",
                "provider",
                "model",
                "runtime",
                "acceptance_tests",
                "max_attempts",
            )
        }
        entry["binding"] = {
            key: task["metadata"].get(key, False if key == "human_gate" else None)
            for key in (
                "factory_snapshot",
                "factory_stage",
                "human_gate",
                "factory_contract",
            )
        }
        result["tasks"].append(entry)
    return result


def _pinned_plan(order: WorkOrder) -> CompiledFactory:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", order.work_order_id):
        raise ValueError("Factory WorkOrder id must be a safe resource identifier")
    root = Path(order.repository)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError("Factory repository must be an absolute canonical project path")
    metadata = order.metadata.get("factory")
    if not isinstance(metadata, dict):
        raise ValueError("Factory WorkOrder is missing its pinned factory contract")
    token = metadata.get("snapshot_digest", "")
    if not isinstance(token, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", token):
        raise ValueError("Factory WorkOrder has an invalid snapshot digest")
    directory = project_path(root, f".superqode/factory/snapshots/{token[7:]}")
    if metadata.get("snapshot_directory") != str(directory):
        raise ValueError("Factory snapshot path does not match its pinned digest")
    path = project_path(root, (directory.relative_to(root) / "snapshot.json").as_posix())
    if path.stat().st_size > MAX_SNAPSHOT_BYTES * 2:
        raise ValueError("Factory snapshot file exceeds its size limit")
    snapshot = FactorySnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if snapshot.digest != token:
        raise ValueError("Stored factory snapshot does not match the WorkOrder")
    revision = metadata.get("repository_commit")
    if not isinstance(revision, str):
        raise ValueError("Factory WorkOrder requires its repository starting commit")
    trusted = _compile_factory(snapshot, root=root, goal=order.goal, revision=revision)
    if _contract(order) != _contract(trusted.work_order):
        raise ValueError("Factory WorkOrder differs from its pinned compiled contract")
    return replace(trusted, work_order=order)


def load_compiled_plan(data: dict, *, root=".") -> CompiledFactory:
    """Reopen a compiler JSON plan using the project's materialized snapshot."""
    root = Path(root).resolve()
    if (
        not isinstance(data, dict)
        or data.get("format") != "superqode.factory-plan/1"
        or not isinstance(data.get("work_order"), dict)
    ):
        raise ValueError("Expected a superqode.factory-plan/1 compiler plan")
    order = WorkOrder.from_dict(data["work_order"])
    if order.repository != str(root):
        raise ValueError("Factory plan belongs to a different project")
    plan = _pinned_plan(order)
    if (
        data.get("snapshot_digest") != plan.snapshot.digest
        or data.get("snapshot_directory") != str(plan.snapshot_directory)
        or data.get("harnesses") != plan.harnesses
    ):
        raise ValueError("Factory plan differs from its pinned compiled components")
    return plan


def admit_factory(plan: CompiledFactory, *, request_id: str, actor: str) -> WorkOrder:
    """Queue exactly one contract per request id; never start a model call."""
    from .maintenance import assert_enabled

    assert_enabled(plan.work_order.repository)
    if not request_id.strip() or not actor.strip():
        raise ValueError("Factory submission requires a request id and actor")
    if plan.work_order.status != WorkOrderStatus.DRAFT:
        raise ValueError("Factory submission requires a fresh draft plan")
    trusted = _pinned_plan(plan.work_order)
    if trusted.harnesses != plan.harnesses or trusted.snapshot != plan.snapshot:
        raise ValueError("Factory submission differs from the pinned plan")
    store = factory_store(plan.work_order.repository)
    if store.find_submission(request_id) is not None:
        # Retry the persisted receipt, even after progress or application drift.
        return store.create(plan.work_order, request_id=request_id, queue=True, actor=actor)
    if (
        repository_revision(Path(plan.work_order.repository))
        != plan.work_order.metadata["factory"]["repository_commit"]
    ):
        raise ValueError("Factory application baseline changed; compile a new plan")
    materialize_snapshot(plan, verify_only=True)
    return store.create(plan.work_order, request_id=request_id, queue=True, actor=actor)


def validate_factory_order(
    order: WorkOrder,
    *,
    check_baseline=True,
    integration_locked=False,
    store: WorkOrderStore | None = None,
) -> CompiledFactory:
    """Fail closed before execution, including through ordinary WorkOrder workers."""
    if check_baseline:
        from .maintenance import assert_enabled

        assert_enabled(order.repository)
    plan = _pinned_plan(order)
    materialize_snapshot(plan, verify_only=True)
    from .contracts import validate_completed

    from superqode.workorders.models import COMPLETED_TASK_STATUSES

    validate_completed(
        order,
        final=bool(order.tasks) and all(t.status in COMPLETED_TASK_STATUSES for t in order.tasks),
    )
    if (
        check_baseline
        and repository_revision(Path(order.repository))
        != order.metadata["factory"]["repository_commit"]
    ):
        raise ValueError("Factory application baseline changed; reconcile before continuing")
    from superqode.workorders.integration import work_order_integration_lock, snapshot_worktree_tree

    store = store or factory_store(order.repository, read_only=True)
    root = Path(order.repository)
    store_path = store.path.absolute()
    if not store_path.is_relative_to(root):
        raise ValueError("Factory WorkOrder storage must stay inside the project")
    project_path(
        root,
        (store_path.parent / "locks" / f"{order.work_order_id}.lock").relative_to(root).as_posix(),
    )
    from contextlib import nullcontext

    with (
        nullcontext()
        if integration_locked
        else work_order_integration_lock(store, order.work_order_id)
    ):
        current = store.get(order.work_order_id)
        workspace = next(
            (
                artifact
                for artifact in reversed(current.artifacts)
                if artifact.kind == "workspace" and artifact.metadata.get("scope") == "work-order"
            ),
            None,
        )
        if workspace is not None:
            root = Path(order.repository)
            path = Path(workspace.path)
            if not path.is_relative_to(root):
                raise ValueError("Factory integration workspace is outside the project")
            path = project_path(root, path.relative_to(root).as_posix())
            expected = workspace.metadata.get("baseline_tree")
            integration = next(
                (
                    artifact
                    for artifact in reversed(current.artifacts)
                    if artifact.kind == "task_integration"
                    and artifact.metadata.get("post_integration_tree")
                ),
                None,
            )
            if integration is not None:
                expected = integration.metadata["post_integration_tree"]
            if not expected or not path.is_dir() or snapshot_worktree_tree(path) != expected:
                raise ValueError(
                    "Factory integration workspace changed outside recorded task integration"
                )
    return plan
