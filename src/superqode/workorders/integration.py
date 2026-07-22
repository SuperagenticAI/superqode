"""Safe review, delivery, rollback, and cleanup for WorkOrder worktrees."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import WorkArtifact, WorkOrder, WorkOrderStatus, WorkTaskRole
from .store import WorkOrderStore


@dataclass(frozen=True)
class IntegrationCandidate:
    """A reproducible patch from the captured repository baseline."""

    artifact_id: str
    patch: str
    digest: str
    files: tuple[str, ...]
    conflicts: tuple[str, ...]
    baseline_tree: str
    candidate_tree: str
    target_tree: str
    expected_tree: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "digest": self.digest,
            "files": list(self.files),
            "conflicts": list(self.conflicts),
            "baseline_tree": self.baseline_tree,
            "candidate_tree": self.candidate_tree,
            "target_tree": self.target_tree,
            "expected_tree": self.expected_tree,
        }


@dataclass(frozen=True)
class TaskIntegration:
    """Result of joining one isolated task patch into the integration worktree."""

    artifact_id: str
    task_id: str
    digest: str
    files: tuple[str, ...]
    conflicts: tuple[str, ...]
    baseline_tree: str
    pre_integration_tree: str
    post_integration_tree: str

    @property
    def integrated(self) -> bool:
        return not self.conflicts and bool(self.post_integration_tree)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "task_id": self.task_id,
            "digest": self.digest,
            "files": list(self.files),
            "conflicts": list(self.conflicts),
            "baseline_tree": self.baseline_tree,
            "pre_integration_tree": self.pre_integration_tree,
            "post_integration_tree": self.post_integration_tree,
            "integrated": self.integrated,
        }


@dataclass(frozen=True)
class TaskWorkspaceDelta:
    """Exact repository delta produced by one isolated task."""

    patch: str
    digest: str
    files: tuple[str, ...]
    baseline_tree: str
    candidate_tree: str


def capture_task_workspace_delta(
    task_workspace: Path,
    baseline_tree: str,
) -> TaskWorkspaceDelta:
    """Capture a binary-safe task patch without applying it anywhere."""
    if not baseline_tree:
        raise ValueError("Task workspace is missing its integration baseline")
    task_workspace = task_workspace.expanduser().resolve()
    candidate_tree = snapshot_worktree_tree(task_workspace)
    patch = _git(
        task_workspace,
        ["diff", "--binary", "--full-index", baseline_tree, candidate_tree, "--"],
    )
    return TaskWorkspaceDelta(
        patch=patch,
        digest=hashlib.sha256(patch.encode()).hexdigest(),
        files=_changed_paths(task_workspace, baseline_tree, candidate_tree),
        baseline_tree=baseline_tree,
        candidate_tree=candidate_tree,
    )


def capture_integration_baseline(repository: Path, workspace: Path) -> dict[str, str]:
    """Capture equal source/worktree trees before an agent can mutate the workspace."""
    repository = repository.resolve()
    workspace = workspace.resolve()
    base_commit = _git(repository, ["rev-parse", "HEAD"]).strip()
    source_tree = snapshot_worktree_tree(repository)
    workspace_tree = snapshot_worktree_tree(workspace)
    if source_tree != workspace_tree:
        raise ValueError(
            "WorkOrder worktree did not reproduce the source checkout; refusing an unsafe baseline"
        )
    return {
        "base_commit": base_commit,
        "baseline_tree": source_tree,
        "source_tree": source_tree,
    }


def snapshot_worktree_tree(repository: Path) -> str:
    """Write the visible, non-ignored checkout state to a temporary Git tree."""
    repository = repository.resolve()
    with tempfile.TemporaryDirectory(prefix="superqode-index-") as directory:
        index_path = Path(directory) / "index"
        env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
        _git(repository, ["read-tree", "HEAD"], env=env)
        _git(repository, ["add", "-A", "--", "."], env=env)
        return _git(repository, ["write-tree"], env=env).strip()


def create_tree_commit(
    repository: Path,
    tree: str,
    *,
    parent: str,
    message: str,
) -> str:
    """Create an unreferenced commit for an exact tree without changing user refs."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "SuperQode WorkOrder",
        "GIT_AUTHOR_EMAIL": "workorders@superqode.local",
        "GIT_COMMITTER_NAME": "SuperQode WorkOrder",
        "GIT_COMMITTER_EMAIL": "workorders@superqode.local",
    }
    args = ["commit-tree", tree]
    if parent:
        args.extend(["-p", parent])
    args.extend(["-m", message])
    return _git(repository.resolve(), args, env=env).strip()


def integrate_task_workspace(
    store: WorkOrderStore,
    reference: str,
    *,
    task_id: str,
    task_workspace: Path,
    baseline_tree: str,
    actor: str,
) -> TaskIntegration:
    """Join one isolated task into the integration worktree under a process lock."""
    task_workspace = task_workspace.expanduser().resolve()
    delta = capture_task_workspace_delta(task_workspace, baseline_tree)
    candidate_tree = delta.candidate_tree
    patch = delta.patch
    files = delta.files
    digest = delta.digest

    with work_order_integration_lock(store, reference):
        order = store.get(reference)
        integration_workspace = _latest_workspace(order)
        integration_path = Path(integration_workspace.path).expanduser().resolve()
        if not integration_path.is_dir():
            raise ValueError("WorkOrder integration worktree is missing")
        pre_tree = snapshot_worktree_tree(integration_path)
        concurrent_paths = _changed_paths(integration_path, baseline_tree, pre_tree)
        conflicts = tuple(sorted(set(files) & set(concurrent_paths)))
        expected_tree = pre_tree
        apply_error = ""
        if not conflicts and patch.strip():
            try:
                expected_tree = _tree_after_patch(integration_path, pre_tree, patch)
            except ValueError as exc:
                apply_error = str(exc)
        if apply_error:
            conflicts = tuple(sorted(set(conflicts) | set(files)))

        metadata: dict[str, Any] = {
            "digest": digest,
            "files": list(files),
            "conflicts": list(conflicts),
            "concurrent_paths": list(concurrent_paths),
            "baseline_tree": baseline_tree,
            "candidate_tree": candidate_tree,
            "pre_integration_tree": pre_tree,
            "post_integration_tree": "" if conflicts else expected_tree,
            "task_workspace": str(task_workspace),
            "integration_workspace": str(integration_path),
            "apply_error": apply_error,
        }
        artifact = store.add_artifact(
            order.work_order_id,
            kind="task_integration",
            task_id=task_id,
            path=str(task_workspace),
            content=patch,
            digest=digest,
            metadata=metadata,
            actor=actor,
        )
        if not conflicts and patch.strip():
            _apply_patch(integration_path, patch)
            actual_tree = snapshot_worktree_tree(integration_path)
            if actual_tree != expected_tree:
                raise ValueError("Task integration tree failed post-apply verification")
        else:
            actual_tree = "" if conflicts else pre_tree
        return TaskIntegration(
            artifact_id=artifact.artifact_id,
            task_id=task_id,
            digest=digest,
            files=files,
            conflicts=conflicts,
            baseline_tree=baseline_tree,
            pre_integration_tree=pre_tree,
            post_integration_tree=actual_tree,
        )


@contextmanager
def work_order_integration_lock(store: WorkOrderStore, reference: str):
    """Serialize filesystem joins across local scheduler processes."""
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - native Windows is not supported yet
        raise RuntimeError("Parallel WorkOrder integration requires POSIX file locking") from exc
    lock_root = store.path.parent / "locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / f"{reference}.lock"
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def prepare_integration(
    store: WorkOrderStore,
    reference: str,
    *,
    actor: str = "integration",
) -> IntegrationCandidate:
    """Create and validate the exact patch a human may approve for delivery."""
    order = store.get(reference)
    if order.status not in {
        WorkOrderStatus.REVIEWING,
        WorkOrderStatus.CHECKING,
        WorkOrderStatus.READY_TO_MERGE,
    }:
        raise ValueError(f"Cannot prepare merge from {order.status.value}")
    if order.acceptance_tests and not order.metadata.get("acceptance_checks_passed"):
        raise ValueError("Cannot prepare merge until WorkOrder acceptance checks pass")
    for task in order.tasks:
        if task.role != WorkTaskRole.REVIEWER:
            continue
        review = next(
            (
                artifact
                for artifact in reversed(order.artifacts)
                if artifact.kind == "review" and artifact.task_id == task.task_id
            ),
            None,
        )
        if review is None or review.metadata.get("review_verdict") != "approved":
            raise ValueError(f"Reviewer task {task.task_id} has no approved review verdict")

    workspace_artifact = _latest_workspace(order)
    if workspace_artifact.metadata.get("isolation") != "worktree":
        raise ValueError("Safe integration requires WorkOrder worktree isolation")
    baseline_tree = str(workspace_artifact.metadata.get("baseline_tree") or "")
    if not baseline_tree:
        raise ValueError(
            "WorkOrder predates integration baselines; create a new isolated WorkOrder"
        )

    repository = Path(order.repository).expanduser().resolve()
    workspace = Path(workspace_artifact.path).expanduser().resolve()
    if not repository.is_dir() or not workspace.is_dir():
        raise ValueError("WorkOrder source checkout or integration worktree is missing")

    candidate_tree = snapshot_worktree_tree(workspace)
    patch = _git(
        workspace,
        ["diff", "--binary", "--full-index", baseline_tree, candidate_tree, "--"],
    )
    files = _changed_paths(workspace, baseline_tree, candidate_tree)
    if not files or not patch.strip():
        raise ValueError("WorkOrder produced no repository changes to integrate")

    target_tree = snapshot_worktree_tree(repository)
    source_drift = _changed_paths(repository, baseline_tree, target_tree)
    conflicts = tuple(sorted(set(files) & set(source_drift)))
    expected_tree = ""
    apply_error = ""
    if not conflicts:
        try:
            expected_tree = _tree_after_patch(repository, target_tree, patch)
        except ValueError as exc:
            apply_error = str(exc)

    digest = hashlib.sha256(patch.encode()).hexdigest()
    metadata: dict[str, Any] = {
        "digest": digest,
        "files": list(files),
        "conflicts": list(conflicts),
        "source_drift": list(source_drift),
        "baseline_tree": baseline_tree,
        "candidate_tree": candidate_tree,
        "target_tree": target_tree,
        "expected_tree": expected_tree,
        "workspace": str(workspace),
        "apply_error": apply_error,
    }
    artifact = store.add_artifact(
        order.work_order_id,
        kind="integration_candidate",
        path=str(workspace),
        content=patch,
        digest=digest,
        metadata=metadata,
        actor=actor,
    )
    candidate = IntegrationCandidate(
        artifact_id=artifact.artifact_id,
        patch=patch,
        digest=digest,
        files=files,
        conflicts=conflicts,
        baseline_tree=baseline_tree,
        candidate_tree=candidate_tree,
        target_tree=target_tree,
        expected_tree=expected_tree,
    )
    if conflicts or apply_error:
        reasons = []
        if conflicts:
            reasons.append("conflicting source changes: " + ", ".join(conflicts))
        if apply_error:
            reasons.append("patch does not apply cleanly")
        store.block_integration(
            order.work_order_id,
            reason="; ".join(reasons),
            metadata={"artifact_id": artifact.artifact_id, **metadata},
            actor=actor,
        )
        return candidate

    store.mark_ready_to_merge(
        order.work_order_id,
        candidate_artifact_id=artifact.artifact_id,
        metadata=metadata,
        actor=actor,
    )
    return candidate


def merge_integration(
    store: WorkOrderStore,
    reference: str,
    *,
    actor: str = "human",
) -> WorkOrder:
    """Apply only the approved patch and verify the resulting target tree."""
    order = store.get(reference)
    if order.status not in {WorkOrderStatus.READY_TO_MERGE, WorkOrderStatus.MERGING}:
        raise ValueError(f"Cannot merge WorkOrder from {order.status.value}")
    candidate = _approved_candidate(order)
    patch = candidate.content
    digest = hashlib.sha256(patch.encode()).hexdigest()
    if digest != candidate.digest or digest != candidate.metadata.get("digest"):
        raise ValueError("Integration candidate digest does not match its reviewed patch")

    repository = Path(order.repository).expanduser().resolve()
    target_tree = str(candidate.metadata.get("target_tree") or "")
    expected_tree = str(candidate.metadata.get("expected_tree") or "")
    if not target_tree or not expected_tree:
        raise ValueError("Integration candidate is missing its target tree contract")

    current_tree = snapshot_worktree_tree(repository)
    if order.status == WorkOrderStatus.READY_TO_MERGE:
        if current_tree != target_tree:
            raise ValueError("Target checkout changed after review; run `sq work prepare` again")
        order = store.begin_merge(
            order.work_order_id,
            candidate_artifact_id=candidate.artifact_id,
            expected_tree=expected_tree,
            actor=actor,
        )

    if current_tree != expected_tree:
        if current_tree != target_tree:
            reason = "Target checkout does not match the pre-merge or expected merged tree"
            store.block_integration(
                order.work_order_id,
                reason=reason,
                metadata={"current_tree": current_tree, "expected_tree": expected_tree},
                actor=actor,
            )
            raise ValueError(reason)
        try:
            _apply_patch(repository, patch)
        except ValueError as exc:
            store.block_integration(
                order.work_order_id,
                reason=str(exc),
                metadata={"artifact_id": candidate.artifact_id},
                actor=actor,
            )
            raise
        current_tree = snapshot_worktree_tree(repository)
    if current_tree != expected_tree:
        reason = "Merged checkout tree failed post-apply verification"
        store.block_integration(
            order.work_order_id,
            reason=reason,
            metadata={"current_tree": current_tree, "expected_tree": expected_tree},
            actor=actor,
        )
        raise ValueError(reason)

    result = store.add_artifact(
        order.work_order_id,
        kind="merge_result",
        path=str(repository),
        digest=digest,
        metadata={
            "candidate_artifact_id": candidate.artifact_id,
            "pre_merge_tree": target_tree,
            "post_merge_tree": current_tree,
            "files": list(candidate.metadata.get("files") or ()),
        },
        actor=actor,
    )
    return store.mark_merged(
        order.work_order_id,
        result_artifact_id=result.artifact_id,
        metadata={
            "candidate_artifact_id": candidate.artifact_id,
            "pre_merge_tree": target_tree,
            "post_merge_tree": current_tree,
            "digest": digest,
        },
        actor=actor,
    )


def rollback_integration(
    store: WorkOrderStore,
    reference: str,
    *,
    actor: str = "human",
    reason: str = "",
) -> WorkOrder:
    """Reverse a merged patch only when the target has not changed afterward."""
    order = store.get(reference)
    if order.status != WorkOrderStatus.MERGED:
        raise ValueError(f"Cannot roll back WorkOrder from {order.status.value}")
    candidate = _candidate_for_merge(order)
    result = _latest_artifact(order, "merge_result")
    pre_merge_tree = str(result.metadata.get("pre_merge_tree") or "")
    post_merge_tree = str(result.metadata.get("post_merge_tree") or "")
    repository = Path(order.repository).expanduser().resolve()
    current_tree = snapshot_worktree_tree(repository)
    if current_tree != pre_merge_tree:
        if current_tree != post_merge_tree:
            raise ValueError(
                "Target checkout changed after merge; refusing to overwrite later work"
            )
        _apply_patch(repository, candidate.content, reverse=True)
        current_tree = snapshot_worktree_tree(repository)
    if current_tree != pre_merge_tree:
        raise ValueError("Rollback failed to restore the pre-merge checkout tree")
    rollback = store.add_artifact(
        order.work_order_id,
        kind="rollback_result",
        path=str(repository),
        digest=candidate.digest,
        metadata={
            "merge_result_id": result.artifact_id,
            "restored_tree": current_tree,
            "files": list(candidate.metadata.get("files") or ()),
        },
        actor=actor,
    )
    return store.mark_rolled_back(
        order.work_order_id,
        result_artifact_id=rollback.artifact_id,
        reason=reason,
        actor=actor,
    )


async def cleanup_integration_workspace(
    store: WorkOrderStore,
    reference: str,
    *,
    actor: str = "human",
) -> WorkOrder:
    """Remove only the registered WorkOrder worktree after a terminal decision."""
    from superqode.workspace.worktree import GitWorktreeManager, WorktreeInfo

    order = store.get(reference)
    if order.status not in {
        WorkOrderStatus.ACCEPTED,
        WorkOrderStatus.MERGED,
        WorkOrderStatus.ROLLED_BACK,
        WorkOrderStatus.REJECTED,
        WorkOrderStatus.FAILED,
        WorkOrderStatus.CANCELLED,
    }:
        raise ValueError("WorkOrder workspace cleanup requires a terminal outcome")
    workspaces = [
        artifact
        for artifact in order.artifacts
        if artifact.kind == "workspace"
        and artifact.metadata.get("isolation") == "worktree"
        and artifact.path
    ]
    if not workspaces:
        raise ValueError("WorkOrder does not own a managed worktree")
    repository = Path(order.repository).expanduser().resolve()
    manager = GitWorktreeManager(repository)
    root = manager.worktree_base.resolve()
    removed: list[str] = []
    seen: set[Path] = set()
    for workspace in reversed(workspaces):
        path = Path(workspace.path).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        if not path.is_relative_to(root) or path == root:
            raise ValueError(f"Refusing to remove a path outside the WorkOrder root: {path}")
        info = WorktreeInfo(
            path=path,
            session_id=str(workspace.metadata.get("workspace_id") or path.name),
            base_ref=str(workspace.metadata.get("base_commit") or "HEAD"),
            base_commit=str(workspace.metadata.get("base_commit") or ""),
            created_at=datetime.fromtimestamp(workspace.created_at),
            repo_root=repository,
        )
        await manager.remove_worktree(info, force=True)
        removed.append(str(path))
    store.add_artifact(
        order.work_order_id,
        kind="cleanup_result",
        metadata={"removed": True, "paths": removed, "count": len(removed)},
        actor=actor,
    )
    return store.get(order.work_order_id)


def _approved_candidate(order: WorkOrder) -> WorkArtifact:
    if not order.decision or order.decision.verdict != "accepted":
        raise ValueError("Integration candidate has not been approved")
    return _candidate_for_merge(order)


def _candidate_for_merge(order: WorkOrder) -> WorkArtifact:
    artifact_id = str(order.metadata.get("integration_candidate_id") or "")
    for artifact in reversed(order.artifacts):
        if artifact.artifact_id == artifact_id and artifact.kind == "integration_candidate":
            return artifact
    raise ValueError("Current integration candidate artifact is missing")


def _latest_workspace(order: WorkOrder) -> WorkArtifact:
    for artifact in reversed(order.artifacts):
        if artifact.kind == "workspace" and artifact.metadata.get("scope") == "work-order":
            return artifact
    raise ValueError("WorkOrder has no integration workspace artifact")


def _latest_artifact(order: WorkOrder, kind: str) -> WorkArtifact:
    for artifact in reversed(order.artifacts):
        if artifact.kind == kind:
            return artifact
    raise ValueError(f"WorkOrder has no {kind} artifact")


def _changed_paths(repository: Path, before: str, after: str) -> tuple[str, ...]:
    output = _git(repository, ["diff", "--name-only", "-z", before, after, "--"])
    return tuple(sorted(path for path in output.split("\0") if path))


def _tree_after_patch(repository: Path, target_tree: str, patch: str) -> str:
    with tempfile.TemporaryDirectory(prefix="superqode-merge-index-") as directory:
        index_path = Path(directory) / "index"
        env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
        _git(repository, ["read-tree", target_tree], env=env)
        _git(
            repository,
            ["apply", "--cached", "--binary", "--whitespace=nowarn", "-"],
            input_text=patch,
            env=env,
        )
        return _git(repository, ["write-tree"], env=env).strip()


def _apply_patch(repository: Path, patch: str, *, reverse: bool = False) -> None:
    args = ["apply", "--check", "--binary", "--whitespace=nowarn"]
    if reverse:
        args.append("--reverse")
    args.append("-")
    _git(repository, args, input_text=patch)
    args.remove("--check")
    _git(repository, args, input_text=patch)


def _git(
    repository: Path,
    args: list[str],
    *,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    try:
        completed = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=repository,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Git integration command failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Git error"
        raise ValueError(f"Git integration command failed: {detail}")
    return completed.stdout
