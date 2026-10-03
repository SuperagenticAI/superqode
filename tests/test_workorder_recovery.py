"""Crash boundaries, stale owners, reconciliation and evaluation case reuse."""

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import replace

import pytest

from superqode.workorders import WorkOrder, WorkOrderStore, WorkOrderTask, WorkTaskStatus
from superqode.workorders.recovery import workspace_fingerprint
from superqode.evaluation.recovery import EvaluationRecovery


def make_store(tmp_path):
    store = WorkOrderStore(tmp_path / ".superqode" / "work.sqlite3")
    store.create(
        WorkOrder(
            work_order_id="work",
            goal="recover",
            repository=str(tmp_path),
            tasks=(WorkOrderTask(task_id="task", title="task", goal="recover", max_attempts=5),),
        )
    )
    store.queue("work")
    return store


def expire(store, monkeypatch):
    from superqode.workorders import store as module

    with monkeypatch.context() as patch:
        patch.setattr(module.time, "time", lambda: time.time_ns() / 1e9 + 1000)
        store.recover_stale("work")


def test_unsafe_intent_blocks_and_requires_explicit_reconciliation(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    _, task = store.claim_next_task(worker_id="old", reference="work", lease_seconds=1)
    store.begin_invocation(
        "work",
        "task",
        worker_id="old",
        attempt=task.attempts,
        invocation_id="remote-create",
        operation="issue.create",
        fingerprint="same-input",
        replay_safe=False,
    )
    expire(store, monkeypatch)
    assert store.get("work").tasks[0].status == WorkTaskStatus.BLOCKED
    assert store.claim_next_task(worker_id="new", reference="work") is None
    store.reconcile_invocation(
        "work",
        "task",
        "remote-create",
        actor="operator",
        reason="Remote lookup found issue 42",
        result={"issue_id": 42},
    )
    store.resume("work", actor="operator")
    _, task = store.claim_next_task(worker_id="new", reference="work")
    admission = store.begin_invocation(
        "work",
        "task",
        worker_id="new",
        attempt=task.attempts,
        invocation_id="remote-create",
        operation="issue.create",
        fingerprint="same-input",
    )
    assert admission == {"action": "reuse", "result": {"issue_id": 42}}


def test_attempt_fences_same_worker_identity_and_committed_result_reused(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    _, old = store.claim_next_task(worker_id="same", reference="work", lease_seconds=1)
    store.begin_invocation(
        "work",
        "task",
        worker_id="same",
        attempt=old.attempts,
        invocation_id="read",
        operation="read",
        fingerprint="same",
        replay_safe=True,
    )
    expire(store, monkeypatch)
    _, current = store.claim_next_task(worker_id="same", reference="work")
    with pytest.raises(ValueError, match="Stale"):
        store.finish_invocation(
            "work", "task", worker_id="same", attempt=old.attempts, invocation_id="read", result={}
        )
    with pytest.raises(ValueError, match="Stale"):
        store.heartbeat("work", "task", worker_id="same", attempt=old.attempts)
    assert (
        store.begin_invocation(
            "work",
            "task",
            worker_id="same",
            attempt=current.attempts,
            invocation_id="read",
            operation="read",
            fingerprint="same",
            replay_safe=True,
        )["action"]
        == "execute"
    )
    store.finish_invocation(
        "work",
        "task",
        worker_id="same",
        attempt=current.attempts,
        invocation_id="read",
        result={"answer": 42},
        workspace="unchanged",
    )
    with pytest.raises(ValueError, match="Workspace"):
        store.begin_invocation(
            "work",
            "task",
            worker_id="same",
            attempt=current.attempts,
            invocation_id="read",
            operation="read",
            fingerprint="same",
            replay_safe=True,
            workspace="drift",
        )
    assert store.begin_invocation(
        "work",
        "task",
        worker_id="same",
        attempt=current.attempts,
        invocation_id="read",
        operation="read",
        fingerprint="same",
        workspace="unchanged",
    )["result"] == {"answer": 42}
    with pytest.raises(ValueError, match="configuration"):
        store.begin_invocation(
            "work",
            "task",
            worker_id="same",
            attempt=current.attempts,
            invocation_id="read",
            operation="read",
            fingerprint="different",
            workspace="unchanged",
        )
    with pytest.raises(ValueError, match="configuration"):
        store.begin_invocation(
            "work",
            "task",
            worker_id="same",
            attempt=current.attempts,
            invocation_id="read",
            operation="write",
            fingerprint="same",
            workspace="unchanged",
        )


def test_real_process_exit_after_intent_never_replays_unknown_side_effect(tmp_path):
    store = make_store(tmp_path)
    code = """import os,sys
from superqode.workorders import WorkOrderStore
s=WorkOrderStore(sys.argv[1]); _,t=s.claim_next_task(worker_id="child",reference="work",lease_seconds=1)
s.begin_invocation("work","task",worker_id="child",attempt=t.attempts,invocation_id="write",operation="remote.write",fingerprint="input")
open(sys.argv[2],"w").write("remote effect happened")
os._exit(37)
"""
    marker = tmp_path / "effect"
    child = subprocess.run(
        [sys.executable, "-c", code, str(store.path), str(marker)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"),
        },
    )
    assert child.returncode == 37 and marker.read_text() == "remote effect happened"
    time.sleep(1.1)
    store.recover_stale("work")
    assert store.get("work").tasks[0].status == WorkTaskStatus.BLOCKED
    assert store.invocations("work")[0]["status"] == "intent"


@pytest.mark.asyncio
async def test_100_case_evaluation_recovers_after_70_commits(tmp_path):
    cases = [{"id": str(i), "prompt": f"case {i}"} for i in range(100)]
    store = WorkOrderStore(tmp_path / ".superqode" / "eval.sqlite3")
    script = """import asyncio,json,os,sys
from pathlib import Path
from superqode.workorders import WorkOrderStore
from superqode.evaluation.recovery import EvaluationRecovery
async def main():
 root=Path(sys.argv[1]); s=WorkOrderStore(root/".superqode"/"eval.sqlite3")
 cases=[{"id":str(i),"prompt":f"case {i}"} for i in range(100)]
 recovery=EvaluationRecovery(s,configuration={"model":"fixture-v1"},tasks=cases,working_directory=root)
 async def execute(i):
  with (root/".superqode"/"executed.txt").open("a") as f: f.write(str(i)+"\\n")
  return {"id":str(i),"status":"passed","duration_seconds":.001,"tokens_in":2,"tokens_out":1,"total_tokens":3,"cost_usd":None}
 for i in range(70): await recovery.run_case(str(i),lambda i=i:execute(i))
 os._exit(42)
asyncio.run(main())
"""
    from pathlib import Path

    child = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert child.returncode == 42
    calls = []

    async def execute(index):
        calls.append(index)
        return {
            "id": str(index),
            "status": "passed",
            "duration_seconds": 0.001,
            "tokens_in": 2,
            "tokens_out": 1,
            "total_tokens": 3,
            "cost_usd": None,
        }

    # A fresh owner reconstructs solely from the database.
    recovered = EvaluationRecovery(
        WorkOrderStore(store.path),
        configuration={"model": "fixture-v1"},
        tasks=cases,
        working_directory=tmp_path,
    )
    for i in range(100):
        result = await recovered.run_case(str(i), lambda i=i: execute(i))
        assert result["recovery"] == ("reused" if i < 70 else "committed")
    assert calls == list(range(70, 100))
    assert (tmp_path / ".superqode" / "executed.txt").read_text().splitlines() == [
        str(i) for i in range(70)
    ]
    assert len(store.invocations(recovered.order_id)) == 100
    assert store.usage_summary(recovered.order_id).unknown_cost_runs == 100
    changed = EvaluationRecovery(
        store, configuration={"model": "fixture-v2"}, tasks=cases, working_directory=tmp_path
    )
    assert changed.order_id != recovered.order_id


def test_workspace_guard_detects_same_size_uncommitted_edits(tmp_path):
    path = tmp_path / "code.py"
    path.write_text("old")
    before = workspace_fingerprint(tmp_path)
    path.write_text("new")
    assert workspace_fingerprint(tmp_path) != before


@pytest.mark.asyncio
async def test_hosted_pipy_policy_controls_reuse_and_suppression_before_commit(tmp_path):
    from superqode.execution_recovery import RecoveryScope, recovery_scope
    from superqode.governance import (
        ContextualPolicyEngine,
        ContextualPolicyRule,
        CredentialBroker,
        GovernanceBundle,
        PolicyLayer,
        governance_scope,
    )
    from superqode.harness.pipy_governance import guard_pipy_tools
    from superqode.pipy.messages import TextContent
    from superqode.pipy.tools.base import AgentTool, AgentToolResult

    calls = []

    async def execute(*args):
        calls.append("executed")
        return AgentToolResult(content=[TextContent("sensitive fixture result")])

    tool = guard_pipy_tools([AgentTool("read", "Read", "Read", {"type": "object"}, execute)])[0]
    store = make_store(tmp_path)
    _, task = store.claim_next_task(worker_id="owner", reference="work")
    scope = RecoveryScope(store, "work", "task", "owner", task.attempts)

    def policy(phase):
        return GovernanceBundle(
            ContextualPolicyEngine(
                (
                    PolicyLayer(
                        "test",
                        "fixture",
                        rules=(
                            ContextualPolicyRule(
                                "block", "deny", tools=("read_file",), phases=(phase,)
                            ),
                        ),
                    ),
                )
            ),
            CredentialBroker(),
        )

    with recovery_scope(scope):
        result = await tool.execute("completed", {})
        assert result.text == "sensitive fixture result"
        with governance_scope(policy("tool_call")):
            assert (await tool.execute("completed", {})).details["governance_denied"]
        with governance_scope(policy("tool_result")):
            assert (await tool.execute("completed", {})).details["governance_denied"]
            assert (await tool.execute("suppressed", {})).details["governance_denied"]
    assert calls == ["executed", "executed"]
    suppressed = next(
        r for r in store.invocations("work") if r["invocation_id"].endswith("/suppressed")
    )
    assert "sensitive fixture result" not in str(suppressed["result"])
    assert suppressed["status"] == "completed"


def test_recovery_cli_inspects_and_reconciles(tmp_path, monkeypatch):
    import json
    from click.testing import CliRunner
    from superqode.commands.work import work

    store = make_store(tmp_path)
    _, task = store.claim_next_task(worker_id="owner", reference="work", lease_seconds=1)
    store.begin_invocation(
        "work",
        "task",
        worker_id="owner",
        attempt=task.attempts,
        invocation_id="remote",
        operation="remote.create",
        fingerprint="input",
    )
    expire(store, monkeypatch)
    runner = CliRunner()
    args = ["--store", str(store.path)]
    inspected = runner.invoke(work, args + ["invocations", "work", "--json"])
    assert inspected.exit_code == 0, inspected.output
    assert json.loads(inspected.output)[0]["status"] == "intent"
    reconciled = runner.invoke(
        work,
        args
        + [
            "reconcile",
            "work",
            "task",
            "remote",
            "--actor",
            "operator",
            "--reason",
            "verified no external object exists",
            "--allow-retry",
        ],
    )
    assert reconciled.exit_code == 0, reconciled.output
    assert store.invocations("work")[0]["status"] == "retry"


@pytest.mark.asyncio
async def test_evaluation_reuses_case_outcome_not_nested_tool_outcome(tmp_path):
    from superqode.execution_recovery import recoverable_call

    store = WorkOrderStore(tmp_path / ".superqode" / "nested.sqlite3")
    cases = [{"id": "one", "prompt": "fixture"}]

    async def execute():
        async def child():
            return {"child": "result"}

        await recoverable_call(
            identity="call",
            operation="tool.fixture",
            inputs={},
            execute=child,
            encode=lambda value: value,
            decode=lambda value: value,
        )
        return {"id": "one", "status": "passed", "duration_seconds": 0.01}

    recovery = EvaluationRecovery(
        store, configuration={"model": "fixture"}, tasks=cases, working_directory=tmp_path
    )
    await recovery.run_case("one", execute)
    resumed = EvaluationRecovery(
        store, configuration={"model": "fixture"}, tasks=cases, working_directory=tmp_path
    )

    async def must_not_execute():
        pytest.fail("case should be reused")

    result = await resumed.run_case("one", must_not_execute)
    assert result["id"] == "one" and result["recovery"] == "reused"


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", [False, True])
async def test_coding_process_exit_after_outcome_reuses_or_blocks_drift(
    tmp_path, monkeypatch, drift
):
    from pathlib import Path
    from superqode.workorders import runner

    store = make_store(tmp_path)
    script = """import asyncio,os,sys
from pathlib import Path
from superqode.workorders import WorkOrderStore
from superqode.workorders import runner
async def execute(order,task,**kwargs):
 Path(kwargs["working_directory"],"result.txt").write_text("committed output")
 return {"content":"implemented","session_id":"fixture","run_id":"fixture","stopped_reason":"complete","harness":"coding"}
async def main():
 s=WorkOrderStore(sys.argv[1])
 runner._execute_harness_task=execute
 s.complete_task=lambda *args,**kwargs:os._exit(43)
 await runner.run_next_task(s,work_order_id="work",worker_id="child",lease_seconds=1)
asyncio.run(main())
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(store.path)],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert child.returncode == 43
    assert store.invocations("work")[0]["status"] == "completed"
    time.sleep(1.1)
    store.recover_stale("work")
    if drift:
        (tmp_path / "result.txt").write_text("concurrent user edit")

    async def must_not_execute(*args, **kwargs):
        pytest.fail("committed harness outcome must not run again")

    monkeypatch.setattr(runner, "_execute_harness_task", must_not_execute)
    result = await runner.run_next_task(store, work_order_id="work", worker_id="new")
    assert result.status == ("blocked" if drift else "succeeded")
    if drift:
        assert "Workspace changed" in result.error
        assert (tmp_path / "result.txt").read_text() == "concurrent user edit"
    else:
        assert result.content == "implemented"
        assert (tmp_path / "result.txt").read_text() == "committed output"
    assert store.usage_summary("work").run_count == 1
