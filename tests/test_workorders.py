import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from superqode.main import cli_main
from superqode.workorders import runner as work_runner
from superqode.workorders import worker as work_worker
from superqode.workorders import (
    WorkOrder,
    WorkOrderBudget,
    WorkOrderStatus,
    WorkOrderStore,
    WorkOrderTask,
    WorkOrderUsage,
    WorkTaskStatus,
    WorkTaskRole,
    WorkTaskExecution,
    WorkOrderWorker,
    WorkOrderWorkerConfig,
    build_cockpit_snapshot,
    cleanup_integration_workspace,
    generate_work_order_id,
    integrate_task_workspace,
    merge_integration,
    prepare_integration,
    render_cockpit,
    rollback_integration,
)


def _order(tmp_path, *, acceptance_tests=()) -> WorkOrder:
    return WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Implement and review the change",
        repository=str(tmp_path),
        acceptance_tests=tuple(acceptance_tests),
        harness="coding",
        tasks=(
            WorkOrderTask(
                task_id="implement",
                title="Implement",
                goal="Implement the smallest safe change",
            ),
            WorkOrderTask(
                task_id="review",
                title="Review",
                goal="Review the implementation",
                dependencies=("implement",),
                harness="review",
            ),
        ),
    )


def _git_repository(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repository, check=True)
    (repository / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repository, check=True)
    return repository


def _record_task_workspace(store, order, task, workspace):
    store.add_artifact(
        order.work_order_id,
        kind="workspace",
        task_id=task.task_id,
        path=str(workspace.path),
        metadata={
            "isolation": workspace.isolation,
            "scope": "task",
            "base_commit": workspace.base_commit,
            "baseline_tree": workspace.baseline_tree,
            "source_tree": workspace.source_tree,
            "workspace_id": workspace.workspace_id,
            "integration_workspace": str(workspace.integration_path or ""),
        },
    )


def test_work_order_claims_dependency_ready_tasks_and_reaches_review(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = store.create(_order(tmp_path))
    queued = store.queue(order.work_order_id)
    assert queued.status == WorkOrderStatus.QUEUED

    first_order, first = store.claim_next_task(reference=order.work_order_id, worker_id="worker-a")
    assert first.task_id == "implement"
    assert first.attempts == 1
    assert first_order.status == WorkOrderStatus.RUNNING
    assert store.claim_next_task(reference=order.work_order_id, worker_id="worker-b") is None

    after_first = store.complete_task(
        order.work_order_id,
        "implement",
        worker_id="worker-a",
        run_id="run-1",
        session_id="session-1",
    )
    assert after_first.status == WorkOrderStatus.QUEUED

    _, second = store.claim_next_task(reference=order.work_order_id, worker_id="worker-b")
    assert second.task_id == "review"
    completed = store.complete_task(
        order.work_order_id,
        "review",
        worker_id="worker-b",
        run_id="run-2",
    )
    assert completed.status == WorkOrderStatus.REVIEWING
    assert [task.status for task in completed.tasks] == [
        WorkTaskStatus.SUCCEEDED,
        WorkTaskStatus.SUCCEEDED,
    ]
    assert [event.type for event in store.events(order.work_order_id)][-2:] == [
        "task.completed",
        "work.ready_for_review",
    ]


def test_work_order_lease_recovery_requeues_then_fails_at_attempt_limit(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Recover crashed work",
        repository=str(tmp_path),
        tasks=(
            WorkOrderTask(
                task_id="implementation",
                title="Implementation",
                goal="Do the work",
                max_attempts=2,
            ),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)
    store.claim_next_task(reference=order.work_order_id, worker_id="dead-worker")

    recovered = store.recover_stale(order.work_order_id, stale_after_seconds=0)
    assert recovered[0].tasks[0].status == WorkTaskStatus.PENDING
    assert recovered[0].tasks[0].metadata["recovered_from_worker"] == "dead-worker"

    store.claim_next_task(reference=order.work_order_id, worker_id="dead-again")
    terminal = store.recover_stale(order.work_order_id, stale_after_seconds=0)[0]
    assert terminal.tasks[0].status == WorkTaskStatus.FAILED
    assert terminal.status == WorkOrderStatus.FAILED


def test_recovery_can_exclude_a_live_worker_lease(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = store.create(_order(tmp_path))
    store.queue(order.work_order_id)
    store.claim_next_task(reference=order.work_order_id, worker_id="live-worker/1")

    recovered = store.recover_stale(
        order.work_order_id,
        stale_after_seconds=0,
        exclude_worker_ids=("live-worker/1",),
    )

    assert recovered == []
    assert store.get(order.work_order_id).tasks[0].status == WorkTaskStatus.RUNNING


def test_work_order_requires_checks_before_acceptance(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Ship tested work",
        repository=str(tmp_path),
        acceptance_tests=("python -V",),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)
    store.queue(order.work_order_id)
    store.claim_next_task(reference=order.work_order_id, worker_id="worker")
    store.complete_task(order.work_order_id, "work", worker_id="worker")

    with pytest.raises(ValueError, match="acceptance checks"):
        store.accept(order.work_order_id)

    checked = store.record_checks(
        order.work_order_id,
        [{"command": "python -V", "status": "passed", "returncode": 0}],
    )
    assert checked.status == WorkOrderStatus.CHECKING
    accepted = store.accept(order.work_order_id, actor="release-manager", reason="all green")
    assert accepted.status == WorkOrderStatus.ACCEPTED
    assert accepted.decision.actor == "release-manager"
    assert accepted.artifacts[-1].kind == "check_result"


def test_work_order_failed_checks_block_and_can_resume(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Fix until green",
        repository=str(tmp_path),
        acceptance_tests=("false",),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)
    store.queue(order.work_order_id)
    store.claim_next_task(reference=order.work_order_id, worker_id="worker")
    store.complete_task(order.work_order_id, "work", worker_id="worker")
    blocked = store.record_checks(
        order.work_order_id,
        [{"command": "false", "status": "failed", "returncode": 1}],
    )
    assert blocked.status == WorkOrderStatus.BLOCKED

    resumed = store.resume(order.work_order_id, actor="maintainer")
    assert resumed.status == WorkOrderStatus.REVIEWING
    assert resumed.tasks[0].status == WorkTaskStatus.SUCCEEDED


def test_work_order_rejects_dependency_cycles(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Invalid graph",
        repository=str(tmp_path),
        tasks=(
            WorkOrderTask(task_id="a", title="A", goal="A", dependencies=("b",)),
            WorkOrderTask(task_id="b", title="B", goal="B", dependencies=("a",)),
        ),
    )
    with pytest.raises(ValueError, match="dependency cycle"):
        store.create(order)


def test_work_order_cli_create_claim_complete_and_approve(tmp_path):
    runner = CliRunner()
    store_path = tmp_path / "work.sqlite3"
    create = runner.invoke(
        cli_main,
        [
            "work",
            "--store",
            str(store_path),
            "create",
            "Document the architecture",
            "--repo",
            str(tmp_path),
            "--queue",
            "--json",
        ],
    )
    assert create.exit_code == 0, create.output
    work_order_id = json.loads(create.output)["work_order_id"]

    claim = runner.invoke(
        cli_main,
        [
            "work",
            "--store",
            str(store_path),
            "claim",
            work_order_id,
            "--worker",
            "terminal-1",
            "--json",
        ],
    )
    assert claim.exit_code == 0, claim.output
    assert json.loads(claim.output)["task"]["task_id"] == "primary"

    complete = runner.invoke(
        cli_main,
        [
            "work",
            "--store",
            str(store_path),
            "complete",
            work_order_id,
            "primary",
            "--worker",
            "terminal-1",
            "--run-id",
            "run-cli",
            "--json",
        ],
    )
    assert complete.exit_code == 0, complete.output
    assert json.loads(complete.output)["status"] == "reviewing"

    approve = runner.invoke(
        cli_main,
        [
            "work",
            "--store",
            str(store_path),
            "approve",
            work_order_id,
            "--actor",
            "shashi",
            "--json",
        ],
    )
    assert approve.exit_code == 0, approve.output
    assert json.loads(approve.output)["status"] == "accepted"


@pytest.mark.asyncio
async def test_work_order_runner_executes_harness_and_records_evidence(tmp_path, monkeypatch):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Run a harness",
        repository=str(tmp_path),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)
    store.queue(order.work_order_id)

    async def fake_execute(order, task, **kwargs):
        assert order.goal == "Run a harness"
        assert task.task_id == "work"
        return {
            "content": "implemented",
            "session_id": "session-harness",
            "run_id": "run-harness",
            "stopped_reason": "complete",
            "harness": "coding",
            "provider": "test",
            "model": "model",
            "runtime": "builtin",
        }

    monkeypatch.setattr(work_runner, "_execute_harness_task", fake_execute)
    result = await work_runner.run_next_task(
        store,
        work_order_id=order.work_order_id,
        worker_id="runner-1",
    )

    assert result.status == "succeeded"
    assert result.run_id == "run-harness"
    finished = store.get(order.work_order_id)
    assert finished.status == WorkOrderStatus.REVIEWING
    assert finished.tasks[0].run_id == "run-harness"
    agent_result = next(item for item in finished.artifacts if item.kind == "agent_result")
    assert agent_result.content == "implemented"


def test_work_order_max_workers_is_a_hard_claim_gate(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Bound concurrency",
        repository=str(tmp_path),
        budget=WorkOrderBudget(max_workers=1),
        tasks=(
            WorkOrderTask(task_id="a", title="A", goal="A"),
            WorkOrderTask(task_id="b", title="B", goal="B"),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)
    assert store.claim_next_task(reference=order.work_order_id, worker_id="one") is not None
    assert store.claim_next_task(reference=order.work_order_id, worker_id="two") is None


@pytest.mark.asyncio
async def test_persistent_worker_drains_parallel_tasks_and_persists_heartbeat(
    tmp_path, monkeypatch
):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Drain the durable queue",
        repository=str(tmp_path),
        budget=WorkOrderBudget(max_workers=2),
        tasks=(
            WorkOrderTask(task_id="a", title="A", goal="A"),
            WorkOrderTask(task_id="b", title="B", goal="B"),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)

    async def fake_execute(store, *, order, task, worker_id, **kwargs):
        await asyncio.sleep(0)
        store.complete_task(order.work_order_id, task.task_id, worker_id=worker_id)
        return WorkTaskExecution(
            work_order_id=order.work_order_id,
            task_id=task.task_id,
            status="succeeded",
            worker_id=worker_id,
        )

    monkeypatch.setattr(work_worker, "execute_claimed_task", fake_execute)
    service = WorkOrderWorker(
        store,
        WorkOrderWorkerConfig(
            worker_id="builder-1",
            reference=order.work_order_id,
            concurrency=2,
            poll_interval=0.05,
            once=True,
        ),
    )
    stats = await service.run()

    assert stats.claimed == 2
    assert stats.succeeded == 2
    assert store.get(order.work_order_id).status == WorkOrderStatus.REVIEWING
    snapshot = json.loads((tmp_path / "workers" / "builder-1.json").read_text())
    assert snapshot["status"] == "stopped"
    assert snapshot["active"] == []
    assert snapshot["stats"]["succeeded"] == 2


@pytest.mark.asyncio
async def test_persistent_worker_recovers_a_stale_lease_before_claiming(tmp_path, monkeypatch):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Recover abandoned work",
        repository=str(tmp_path),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Work"),),
    )
    store.create(order)
    store.queue(order.work_order_id)
    store.claim_next_task(reference=order.work_order_id, worker_id="crashed")

    async def fake_execute(store, *, order, task, worker_id, **kwargs):
        store.complete_task(order.work_order_id, task.task_id, worker_id=worker_id)
        return WorkTaskExecution(
            work_order_id=order.work_order_id,
            task_id=task.task_id,
            status="succeeded",
            worker_id=worker_id,
        )

    monkeypatch.setattr(work_worker, "execute_claimed_task", fake_execute)
    service = WorkOrderWorker(
        store,
        WorkOrderWorkerConfig(
            worker_id="recovery-worker",
            reference=order.work_order_id,
            poll_interval=0.05,
            stale_after_seconds=0,
            once=True,
        ),
    )
    stats = await service.run()

    assert stats.recovered_orders == 1
    assert stats.succeeded == 1
    assert store.get(order.work_order_id).tasks[0].attempts == 2


@pytest.mark.asyncio
async def test_persistent_worker_rejects_a_duplicate_live_identity(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    stop = asyncio.Event()
    first = WorkOrderWorker(
        store,
        WorkOrderWorkerConfig(worker_id="unique-builder", poll_interval=0.05),
    )
    running = asyncio.create_task(first.run(stop=stop))
    state = tmp_path / "workers" / "unique-builder.json"
    for _ in range(20):
        if state.exists():
            break
        await asyncio.sleep(0.01)

    duplicate = WorkOrderWorker(
        store,
        WorkOrderWorkerConfig(worker_id="unique-builder", once=True),
    )
    with pytest.raises(RuntimeError, match="already running"):
        await duplicate.run()

    stop.set()
    await running


def test_cockpit_renders_tasks_gates_workers_and_latest_events(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = store.create(_order(tmp_path))
    store.queue(order.work_order_id)
    store.claim_next_task(reference=order.work_order_id, worker_id="builder/1")

    snapshot = build_cockpit_snapshot(store, order.work_order_id, event_limit=2)
    rendered = render_cockpit(snapshot)

    assert snapshot["status"] == "running"
    assert len(snapshot["events"]) == 2
    assert snapshot["events"][-1]["type"] == "task.claimed"
    assert "SuperQode WorkOrder Cockpit" in rendered
    assert "implement" in rendered
    assert "builder/1" in rendered
    assert "GATES & EVIDENCE" in rendered


def test_work_order_cli_watch_and_empty_worker_once(tmp_path):
    runner = CliRunner()
    store_path = tmp_path / "work.sqlite3"
    store = WorkOrderStore(store_path)
    order = store.create(_order(tmp_path))
    store.queue(order.work_order_id)

    watched = runner.invoke(
        cli_main,
        [
            "work",
            "--store",
            str(store_path),
            "watch",
            order.work_order_id,
            "--once",
            "--json",
        ],
    )
    assert watched.exit_code == 0, watched.output
    assert json.loads(watched.output)["work_order_id"] == order.work_order_id

    empty_store = tmp_path / "empty.sqlite3"
    worker = runner.invoke(
        cli_main,
        [
            "work",
            "--store",
            str(empty_store),
            "worker",
            "--id",
            "ci-worker",
            "--once",
            "--json",
        ],
    )
    assert worker.exit_code == 0, worker.output
    assert json.loads(worker.output)["stats"]["claimed"] == 0


def test_work_order_event_limit_returns_the_latest_events(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = store.create(_order(tmp_path))
    store.queue(order.work_order_id)
    store.claim_next_task(reference=order.work_order_id, worker_id="worker")

    assert [event.type for event in store.events(order.work_order_id, limit=2)] == [
        "work.queued",
        "task.claimed",
    ]
    assert store.events(order.work_order_id, limit=0) == []


@pytest.mark.asyncio
async def test_parallel_runner_joins_non_overlapping_task_worktrees(tmp_path, monkeypatch):
    from superqode.workspace.worktree import GitWorktreeManager

    repository = _git_repository(tmp_path)
    monkeypatch.setattr(GitWorktreeManager, "WORKTREE_ROOT", tmp_path / "working")
    monkeypatch.setattr(
        GitWorktreeManager,
        "SESSION_REGISTRY",
        tmp_path / "working" / "_sessions",
    )
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Run independent workers in parallel",
        repository=str(repository),
        budget=WorkOrderBudget(max_workers=2),
        tasks=(
            WorkOrderTask(task_id="alpha", title="Alpha", goal="Create alpha"),
            WorkOrderTask(task_id="beta", title="Beta", goal="Create beta"),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)
    active = 0
    peak = 0

    async def fake_execute(order, task, *, working_directory, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.1)
            (working_directory / f"{task.task_id}.txt").write_text(f"from {task.task_id}\n")
        finally:
            active -= 1
        return {
            "content": f"completed {task.task_id}",
            "session_id": f"session-{task.task_id}",
            "run_id": f"run-{task.task_id}",
            "stopped_reason": "complete",
        }

    monkeypatch.setattr(work_runner, "_execute_harness_task", fake_execute)
    results = await work_runner.run_until_idle(
        store,
        work_order_id=order.work_order_id,
        worker_id="parallel",
        isolation="worktree",
    )

    assert peak == 2
    assert {result.task_id for result in results} == {"alpha", "beta"}
    assert {result.status for result in results} == {"succeeded"}
    finished = store.get(order.work_order_id)
    assert finished.status == WorkOrderStatus.REVIEWING
    integration = next(
        artifact
        for artifact in finished.artifacts
        if artifact.kind == "workspace" and artifact.metadata.get("scope") == "work-order"
    )
    assert (tmp_path / "working").is_dir()
    integration_path = Path(integration.path)
    assert (integration_path / "alpha.txt").read_text() == "from alpha\n"
    assert (integration_path / "beta.txt").read_text() == "from beta\n"
    assert not (repository / "alpha.txt").exists()


@pytest.mark.asyncio
async def test_parallel_runner_blocks_overlapping_task_patches(tmp_path, monkeypatch):
    from superqode.workspace.worktree import GitWorktreeManager

    repository = _git_repository(tmp_path)
    monkeypatch.setattr(GitWorktreeManager, "WORKTREE_ROOT", tmp_path / "working")
    monkeypatch.setattr(
        GitWorktreeManager,
        "SESSION_REGISTRY",
        tmp_path / "working" / "_sessions",
    )
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Block conflicting workers",
        repository=str(repository),
        budget=WorkOrderBudget(max_workers=2),
        tasks=(
            WorkOrderTask(task_id="one", title="One", goal="Edit shared file"),
            WorkOrderTask(task_id="two", title="Two", goal="Edit shared file"),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)

    async def fake_execute(order, task, *, working_directory, **kwargs):
        await asyncio.sleep(0.05)
        (working_directory / "shared.txt").write_text(f"from {task.task_id}\n")
        return {
            "content": "done",
            "session_id": f"session-{task.task_id}",
            "run_id": f"run-{task.task_id}",
            "stopped_reason": "complete",
        }

    monkeypatch.setattr(work_runner, "_execute_harness_task", fake_execute)
    results = await work_runner.run_until_idle(
        store,
        work_order_id=order.work_order_id,
        worker_id="parallel",
        isolation="worktree",
    )

    assert {result.status for result in results} == {"succeeded", "blocked"}
    blocked = store.get(order.work_order_id)
    assert blocked.status == WorkOrderStatus.BLOCKED
    conflict = next(
        artifact
        for artifact in reversed(blocked.artifacts)
        if artifact.kind == "task_integration" and artifact.metadata.get("conflicts")
    )
    assert conflict.metadata["conflicts"] == ["shared.txt"]


@pytest.mark.asyncio
async def test_role_pipeline_passes_evidence_and_requires_structured_review(tmp_path, monkeypatch):
    from superqode.workspace.worktree import GitWorktreeManager

    repository = _git_repository(tmp_path)
    monkeypatch.setattr(GitWorktreeManager, "WORKTREE_ROOT", tmp_path / "working")
    monkeypatch.setattr(
        GitWorktreeManager,
        "SESSION_REGISTRY",
        tmp_path / "working" / "_sessions",
    )
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Investigate, implement, synthesize, and review",
        repository=str(repository),
        tasks=(
            WorkOrderTask(
                task_id="investigate",
                title="Investigate",
                goal="Find the relevant code",
                role=WorkTaskRole.INVESTIGATOR,
            ),
            WorkOrderTask(
                task_id="implement",
                title="Implement",
                goal="Implement the change",
                role=WorkTaskRole.IMPLEMENTER,
                dependencies=("investigate",),
            ),
            WorkOrderTask(
                task_id="synthesize",
                title="Synthesize",
                goal="Reconcile the implementation",
                role=WorkTaskRole.SYNTHESIZER,
                dependencies=("implement",),
            ),
            WorkOrderTask(
                task_id="review",
                title="Review",
                goal="Review the integrated result",
                role=WorkTaskRole.REVIEWER,
                dependencies=("synthesize",),
            ),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)

    async def fake_execute(order, task, *, working_directory, **kwargs):
        if task.role == WorkTaskRole.INVESTIGATOR:
            content = "Relevant code is in README.md; add role-output.txt."
        elif task.role == WorkTaskRole.IMPLEMENTER:
            assert any(
                artifact.task_id == "investigate" and "role-output" in artifact.content
                for artifact in order.artifacts
            )
            (working_directory / "role-output.txt").write_text("implemented\n")
            content = "Implemented role-output.txt."
        elif task.role == WorkTaskRole.SYNTHESIZER:
            assert (working_directory / "role-output.txt").read_text() == "implemented\n"
            (working_directory / "role-output.txt").write_text("synthesized\n")
            content = "Synthesized predecessor output."
        else:
            assert (working_directory / "role-output.txt").read_text() == "synthesized\n"
            content = (
                "Review passed.\n"
                'SUPERQODE_REVIEW: {"verdict":"approved","summary":"clean",'
                '"issues":[]}'
            )
        return {
            "content": content,
            "session_id": f"session-{task.task_id}",
            "run_id": f"run-{task.task_id}",
            "stopped_reason": "complete",
        }

    monkeypatch.setattr(work_runner, "_execute_harness_task", fake_execute)
    results = await work_runner.run_until_idle(
        store,
        work_order_id=order.work_order_id,
        isolation="worktree",
    )

    assert [result.task_id for result in results] == [
        "investigate",
        "implement",
        "synthesize",
        "review",
    ]
    assert {result.status for result in results} == {"succeeded"}
    finished = store.get(order.work_order_id)
    assert finished.status == WorkOrderStatus.REVIEWING
    review = next(artifact for artifact in finished.artifacts if artifact.kind == "review")
    assert review.metadata["review_verdict"] == "approved"
    assert WorkOrder.from_dict(finished.to_dict()).tasks[0].role == WorkTaskRole.INVESTIGATOR
    candidate = prepare_integration(store, order.work_order_id)
    assert candidate.files == ("role-output.txt",)


def test_prepare_cannot_bypass_reviewer_with_low_level_completion(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Require typed review evidence",
        repository=str(tmp_path),
        tasks=(
            WorkOrderTask(
                task_id="review",
                title="Review",
                goal="Review",
                role=WorkTaskRole.REVIEWER,
            ),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)
    store.claim_next_task(reference=order.work_order_id, worker_id="manual")
    store.complete_task(order.work_order_id, "review", worker_id="manual")

    with pytest.raises(ValueError, match="no approved review verdict"):
        prepare_integration(store, order.work_order_id)


@pytest.mark.asyncio
async def test_reviewer_changes_requested_blocks_work_order(tmp_path, monkeypatch):
    from superqode.workspace.worktree import GitWorktreeManager

    repository = _git_repository(tmp_path)
    monkeypatch.setattr(GitWorktreeManager, "WORKTREE_ROOT", tmp_path / "working")
    monkeypatch.setattr(
        GitWorktreeManager,
        "SESSION_REGISTRY",
        tmp_path / "working" / "_sessions",
    )
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Require cross-review",
        repository=str(repository),
        tasks=(
            WorkOrderTask(
                task_id="review",
                title="Review",
                goal="Reject unsafe work",
                role=WorkTaskRole.REVIEWER,
            ),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)

    async def fake_execute(*args, **kwargs):
        return {
            "content": (
                'SUPERQODE_REVIEW: {"verdict":"changes_requested",'
                '"summary":"unsafe","issues":["missing regression test"]}'
            ),
            "session_id": "session-review",
            "run_id": "run-review",
            "stopped_reason": "complete",
        }

    monkeypatch.setattr(work_runner, "_execute_harness_task", fake_execute)
    results = await work_runner.run_until_idle(
        store,
        work_order_id=order.work_order_id,
        isolation="worktree",
    )

    assert results[0].status == "blocked"
    blocked = store.get(order.work_order_id)
    assert blocked.status == WorkOrderStatus.BLOCKED
    assert "missing regression test" in blocked.error


@pytest.mark.asyncio
async def test_evidence_only_role_cannot_mutate_integration_tree(tmp_path, monkeypatch):
    from superqode.workspace.worktree import GitWorktreeManager

    repository = _git_repository(tmp_path)
    monkeypatch.setattr(GitWorktreeManager, "WORKTREE_ROOT", tmp_path / "working")
    monkeypatch.setattr(
        GitWorktreeManager,
        "SESSION_REGISTRY",
        tmp_path / "working" / "_sessions",
    )
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Keep investigation read-only",
        repository=str(repository),
        tasks=(
            WorkOrderTask(
                task_id="investigate",
                title="Investigate",
                goal="Inspect without edits",
                role=WorkTaskRole.INVESTIGATOR,
            ),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)

    async def fake_execute(order, task, *, working_directory, **kwargs):
        (working_directory / "forbidden.txt").write_text("should not integrate\n")
        return {
            "content": "Investigation complete.",
            "session_id": "session-investigate",
            "run_id": "run-investigate",
            "stopped_reason": "complete",
        }

    monkeypatch.setattr(work_runner, "_execute_harness_task", fake_execute)
    results = await work_runner.run_until_idle(
        store,
        work_order_id=order.work_order_id,
        isolation="worktree",
    )

    assert results[0].status == "blocked"
    blocked = store.get(order.work_order_id)
    violation = next(
        artifact for artifact in blocked.artifacts if artifact.kind == "workspace_violation"
    )
    assert violation.metadata["files"] == ["forbidden.txt"]
    integration = next(
        artifact
        for artifact in blocked.artifacts
        if artifact.kind == "workspace" and artifact.metadata.get("scope") == "work-order"
    )
    assert not (Path(integration.path) / "forbidden.txt").exists()


def test_work_order_draft_cannot_be_claimed(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = store.create(_order(tmp_path))
    assert store.claim_next_task(reference=order.work_order_id, worker_id="too-early") is None


@pytest.mark.asyncio
async def test_dependency_task_starts_from_integrated_predecessor_tree(tmp_path, monkeypatch):
    from superqode.workspace.worktree import GitWorktreeManager

    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repository, check=True)
    (repository / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repository, check=True)
    monkeypatch.setattr(GitWorktreeManager, "WORKTREE_ROOT", tmp_path / "working")
    monkeypatch.setattr(
        GitWorktreeManager,
        "SESSION_REGISTRY",
        tmp_path / "working" / "_sessions",
    )

    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Use an integration worktree",
        repository=str(repository),
        tasks=(
            WorkOrderTask(task_id="a", title="A", goal="A"),
            WorkOrderTask(task_id="b", title="B", goal="B", dependencies=("a",)),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)
    _, first_task = store.claim_next_task(reference=order.work_order_id, worker_id="worker-a")
    first = await work_runner._prepare_task_workspace(store, order, first_task, isolation="auto")
    assert first.isolation == "worktree"
    (first.path / "from-a.txt").write_text("kept\n")
    _record_task_workspace(store, order, first_task, first)
    joined = integrate_task_workspace(
        store,
        order.work_order_id,
        task_id=first_task.task_id,
        task_workspace=first.path,
        baseline_tree=first.baseline_tree,
        actor="worker-a",
    )
    assert joined.integrated
    store.complete_task(order.work_order_id, "a", worker_id="worker-a")

    updated = store.get(order.work_order_id)
    _, second_task = store.claim_next_task(reference=order.work_order_id, worker_id="worker-b")
    second = await work_runner._prepare_task_workspace(
        store, updated, second_task, isolation="auto"
    )
    assert second.path != first.path
    assert (second.path / "from-a.txt").read_text() == "kept\n"


@pytest.mark.asyncio
async def test_work_order_prepares_approved_patch_merges_and_rolls_back(tmp_path, monkeypatch):
    from superqode.workspace.worktree import GitWorktreeManager

    repository = _git_repository(tmp_path)
    (repository / "README.md").write_text("user work already in progress\n")
    monkeypatch.setattr(GitWorktreeManager, "WORKTREE_ROOT", tmp_path / "working")
    monkeypatch.setattr(
        GitWorktreeManager,
        "SESSION_REGISTRY",
        tmp_path / "working" / "_sessions",
    )
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Deliver a reviewed change",
        repository=str(repository),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)
    store.queue(order.work_order_id)
    _, task = store.claim_next_task(reference=order.work_order_id, worker_id="worker")
    workspace = await work_runner._prepare_task_workspace(store, order, task, isolation="auto")
    _record_task_workspace(store, order, task, workspace)
    (workspace.path / "feature.txt").write_text("agent change\n")
    joined = integrate_task_workspace(
        store,
        order.work_order_id,
        task_id=task.task_id,
        task_workspace=workspace.path,
        baseline_tree=workspace.baseline_tree,
        actor="worker",
    )
    assert joined.integrated
    store.complete_task(order.work_order_id, task.task_id, worker_id="worker")

    candidate = prepare_integration(store, order.work_order_id)
    assert candidate.files == ("feature.txt",)
    assert not candidate.conflicts
    assert store.get(order.work_order_id).status == WorkOrderStatus.READY_TO_MERGE
    approved = store.accept(order.work_order_id, actor="reviewer", reason="looks good")
    assert approved.status == WorkOrderStatus.READY_TO_MERGE
    assert approved.decision.verdict == "accepted"

    merged = merge_integration(store, order.work_order_id, actor="reviewer")
    assert merged.status == WorkOrderStatus.MERGED
    assert (repository / "feature.txt").read_text() == "agent change\n"
    assert (repository / "README.md").read_text() == "user work already in progress\n"
    assert not subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=repository, check=False
    ).returncode

    rolled_back = rollback_integration(
        store, order.work_order_id, actor="reviewer", reason="reconsidered"
    )
    assert rolled_back.status == WorkOrderStatus.ROLLED_BACK
    assert not (repository / "feature.txt").exists()
    assert (repository / "README.md").read_text() == "user work already in progress\n"

    cleaned = await cleanup_integration_workspace(store, order.work_order_id, actor="reviewer")
    assert not workspace.path.exists()
    assert cleaned.artifacts[-1].kind == "cleanup_result"


@pytest.mark.asyncio
async def test_work_order_prepare_blocks_overlapping_source_changes(tmp_path, monkeypatch):
    from superqode.workspace.worktree import GitWorktreeManager

    repository = _git_repository(tmp_path)
    monkeypatch.setattr(GitWorktreeManager, "WORKTREE_ROOT", tmp_path / "working")
    monkeypatch.setattr(
        GitWorktreeManager,
        "SESSION_REGISTRY",
        tmp_path / "working" / "_sessions",
    )
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Detect a conflict",
        repository=str(repository),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)
    store.queue(order.work_order_id)
    _, task = store.claim_next_task(reference=order.work_order_id, worker_id="worker")
    workspace = await work_runner._prepare_task_workspace(store, order, task, isolation="auto")
    _record_task_workspace(store, order, task, workspace)
    (workspace.path / "README.md").write_text("agent version\n")
    joined = integrate_task_workspace(
        store,
        order.work_order_id,
        task_id=task.task_id,
        task_workspace=workspace.path,
        baseline_tree=workspace.baseline_tree,
        actor="worker",
    )
    assert joined.integrated
    (repository / "README.md").write_text("human version\n")
    store.complete_task(order.work_order_id, task.task_id, worker_id="worker")

    candidate = prepare_integration(store, order.work_order_id)
    assert candidate.conflicts == ("README.md",)
    blocked = store.get(order.work_order_id)
    assert blocked.status == WorkOrderStatus.BLOCKED
    assert "README.md" in blocked.error


@pytest.mark.asyncio
async def test_work_order_merge_refuses_target_drift_after_review(tmp_path, monkeypatch):
    from superqode.workspace.worktree import GitWorktreeManager

    repository = _git_repository(tmp_path)
    monkeypatch.setattr(GitWorktreeManager, "WORKTREE_ROOT", tmp_path / "working")
    monkeypatch.setattr(
        GitWorktreeManager,
        "SESSION_REGISTRY",
        tmp_path / "working" / "_sessions",
    )
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Protect reviewed context",
        repository=str(repository),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)
    store.queue(order.work_order_id)
    _, task = store.claim_next_task(reference=order.work_order_id, worker_id="worker")
    workspace = await work_runner._prepare_task_workspace(store, order, task, isolation="auto")
    _record_task_workspace(store, order, task, workspace)
    (workspace.path / "agent.txt").write_text("ready\n")
    joined = integrate_task_workspace(
        store,
        order.work_order_id,
        task_id=task.task_id,
        task_workspace=workspace.path,
        baseline_tree=workspace.baseline_tree,
        actor="worker",
    )
    assert joined.integrated
    store.complete_task(order.work_order_id, task.task_id, worker_id="worker")
    prepare_integration(store, order.work_order_id)
    store.accept(order.work_order_id, actor="reviewer")
    (repository / "later.txt").write_text("changed after review\n")

    with pytest.raises(ValueError, match="changed after review"):
        merge_integration(store, order.work_order_id, actor="reviewer")
    assert not (repository / "agent.txt").exists()


@pytest.mark.asyncio
async def test_work_order_cancel_stops_live_harness_coroutine(tmp_path, monkeypatch):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Cancel live work",
        repository=str(tmp_path),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Wait"),),
    )
    store.create(order)
    store.queue(order.work_order_id)
    harness_cancelled = asyncio.Event()

    async def fake_execute(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            harness_cancelled.set()

    monkeypatch.setattr(work_runner, "_execute_harness_task", fake_execute)
    running = asyncio.create_task(
        work_runner.run_next_task(
            store,
            work_order_id=order.work_order_id,
            worker_id="runner",
            isolation="none",
        )
    )
    for _ in range(40):
        if store.get(order.work_order_id).status == WorkOrderStatus.RUNNING:
            break
        await asyncio.sleep(0.025)
    store.cancel(order.work_order_id, actor="operator", reason="stop now")
    result = await asyncio.wait_for(running, timeout=3)

    assert result.status == "cancelled"
    assert harness_cancelled.is_set()
    assert store.get(order.work_order_id).status == WorkOrderStatus.CANCELLED


def test_work_order_usage_is_normalized_and_accumulated(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Account for every run",
        repository=str(tmp_path),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)
    _, decision = store.record_usage(
        order.work_order_id,
        WorkOrderUsage(
            task_id="work",
            attempt=1,
            observed_at=1,
            tokens_in=80,
            tokens_out=20,
            total_tokens=100,
            cost_usd=0.0125,
            cost_currency="USD",
            tool_calls=3,
            iterations=2,
            latency_ms=450,
        ),
    )

    summary = store.usage_summary(order.work_order_id)
    assert decision.allowed
    assert summary.run_count == 1
    assert summary.total_tokens == 100
    assert summary.cost_usd == pytest.approx(0.0125)
    assert summary.tool_calls == 3
    assert summary.unknown_cost_runs == 0


@pytest.mark.parametrize(
    ("budget", "usage", "violation"),
    [
        (
            WorkOrderBudget(max_tokens=99),
            WorkOrderUsage("work", 1, 1, total_tokens=100),
            "token_budget_exhausted",
        ),
        (
            WorkOrderBudget(max_cost_usd=0.01),
            WorkOrderUsage("work", 1, 1, cost_usd=0.02),
            "cost_budget_exhausted",
        ),
        (
            WorkOrderBudget(max_tool_calls=2),
            WorkOrderUsage("work", 1, 1, tool_calls=3),
            "tool_call_budget_exhausted",
        ),
    ],
)
def test_work_order_usage_limits_block_at_task_completion(
    tmp_path, budget, usage, violation
):
    store = WorkOrderStore(tmp_path / f"{violation}.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Enforce a hard task boundary",
        repository=str(tmp_path),
        budget=budget,
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)

    _, decision = store.record_usage(order.work_order_id, usage)

    assert not decision.allowed
    assert decision.violations[0].code == violation
    assert store.get(order.work_order_id).status == WorkOrderStatus.BLOCKED


def test_work_order_configured_budget_fails_closed_when_usage_is_unreported(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Do not guess provider cost",
        repository=str(tmp_path),
        budget=WorkOrderBudget(max_cost_usd=1.0),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)

    _, decision = store.record_usage(
        order.work_order_id,
        WorkOrderUsage(task_id="work", attempt=1, observed_at=1),
    )

    assert not decision.allowed
    assert decision.violations[0].code == "cost_usage_unreported"


def test_work_order_risk_limit_denies_task_before_claim(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Only admit low-risk workers",
        repository=str(tmp_path),
        budget=WorkOrderBudget(max_risk="low"),
        tasks=(
            WorkOrderTask(
                task_id="work",
                title="Work",
                goal="Implement",
                role=WorkTaskRole.IMPLEMENTER,
            ),
        ),
    )
    store.create(order)
    store.queue(order.work_order_id)

    assert store.claim_next_task(reference=order.work_order_id, worker_id="builder") is None
    blocked = store.get(order.work_order_id)
    assert blocked.status == WorkOrderStatus.BLOCKED
    assert blocked.tasks[0].status == WorkTaskStatus.BLOCKED
    assert "risk medium exceeds the low limit" in blocked.tasks[0].error


@pytest.mark.asyncio
async def test_runner_blocks_over_budget_result_before_agent_result(tmp_path, monkeypatch):
    store = WorkOrderStore(tmp_path / "work.sqlite3")
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Stop an expensive run before integration",
        repository=str(tmp_path),
        budget=WorkOrderBudget(max_tokens=100),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)
    store.queue(order.work_order_id)

    async def fake_execute(*args, **kwargs):
        return {
            "content": "candidate output",
            "session_id": "session-budget",
            "run_id": "run-budget",
            "stopped_reason": "complete",
            "total_tokens": 101,
            "tool_calls_made": 2,
        }

    monkeypatch.setattr(work_runner, "_execute_harness_task", fake_execute)
    result = await work_runner.run_next_task(
        store,
        work_order_id=order.work_order_id,
        worker_id="budget-worker",
        isolation="none",
    )

    assert result.status == "blocked"
    assert result.policy["violations"][0]["code"] == "token_budget_exhausted"
    artifacts = store.get(order.work_order_id).artifacts
    assert any(item.kind == "usage" for item in artifacts)
    assert not any(item.kind == "agent_result" for item in artifacts)


def test_work_order_cli_usage_and_policy_simulation(tmp_path):
    store_path = tmp_path / "work.sqlite3"
    store = WorkOrderStore(store_path)
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal="Inspect projected limits",
        repository=str(tmp_path),
        budget=WorkOrderBudget(max_tokens=100),
        tasks=(WorkOrderTask(task_id="work", title="Work", goal="Implement"),),
    )
    store.create(order)
    store.record_usage(
        order.work_order_id,
        WorkOrderUsage(task_id="work", attempt=1, observed_at=1, total_tokens=60),
    )
    runner = CliRunner()

    usage = runner.invoke(
        cli_main,
        ["work", "--store", str(store_path), "usage", order.work_order_id, "--json"],
    )
    policy = runner.invoke(
        cli_main,
        [
            "work",
            "--store",
            str(store_path),
            "policy",
            order.work_order_id,
            "--phase",
            "completion",
            "--add-tokens",
            "41",
            "--json",
        ],
    )

    assert usage.exit_code == 0, usage.output
    assert json.loads(usage.output)["total_tokens"] == 60
    assert policy.exit_code == 0, policy.output
    assert not json.loads(policy.output)["decision"]["allowed"]
