"""Real VM continuation, atomic journals and crash/authority boundaries."""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from superqode.execution_recovery import RecoveryScope, recovery_scope
from superqode.workorders import (
    WorkOrder,
    WorkOrderStore,
    WorkOrderTask,
    WorkOrderBudget,
    WorkTaskStatus,
    WorkTaskRole,
)
from superqode.workorders.programs import ProgramJournal, inspect_programs
from superqode.tools.monty_program import cancellable_program, run_program


def store_for(root, **budget):
    store = WorkOrderStore(root / ".superqode" / "work.sqlite3")
    store.create(
        WorkOrder(
            work_order_id="work",
            goal="inspect",
            repository=str(root),
            harness="pipy",
            budget=WorkOrderBudget(**budget),
            tasks=(
                WorkOrderTask(
                    task_id="task",
                    title="inspect",
                    goal="inspect",
                    max_attempts=8,
                    role=WorkTaskRole.INVESTIGATOR,
                ),
            ),
        )
    )
    store.queue("work")
    return store


def scope_for(store, worker="owner", lease=300):
    _, task = store.claim_next_task(worker_id=worker, reference="work", lease_seconds=lease)
    return RecoveryScope(store, "work", "task", worker, task.attempts)


def recover(store, monkeypatch):
    from superqode.workorders import store as module

    with monkeypatch.context() as patch:
        patch.setattr(module.time, "time", lambda: time.time_ns() / 1e9 + 1000)
        store.recover_stale("work")


def test_atomic_checkpoint_intent_and_revision_fencing(tmp_path):
    store = store_for(tmp_path)
    scope = scope_for(store)
    journal = ProgramJournal(scope, "program", "config", "tree")
    args = dict(
        revision=0,
        checkpoint=b"fixture",
        metadata={},
        invocation_id="child",
        inputs={},
        replay_safe=True,
    )
    journal.stage(**args)
    assert journal.load()["revision"] == 1
    assert store.invocations("work")[0]["status"] == "intent"
    with pytest.raises(ValueError, match="Stale program revision"):
        journal.stage(**args)
    assert len(store.invocations("work")) == 1


def test_atomic_publication_rolls_back_when_event_write_fails(tmp_path, monkeypatch):
    store = store_for(tmp_path)
    journal = ProgramJournal(scope_for(store), "program", "config", "tree")
    original = store._append_event_tx

    def fail(conn, order, kind, **kwargs):
        if kind == "program.pending":
            raise RuntimeError("disk fixture failure")
        return original(conn, order, kind, **kwargs)

    monkeypatch.setattr(store, "_append_event_tx", fail)
    with pytest.raises(RuntimeError):
        journal.stage(
            revision=0,
            checkpoint=b"fixture",
            metadata={},
            invocation_id="child",
            inputs={},
            replay_safe=True,
        )
    assert journal.load() is None
    assert store.invocations("work") == []


def test_checkpoint_integrity_size_and_identity(tmp_path):
    store = store_for(tmp_path)
    scope = scope_for(store)
    journal = ProgramJournal(scope, "program", "config", "tree")
    with pytest.raises(ValueError, match="8 MiB"):
        journal.stage(
            revision=0,
            checkpoint=b"x" * (8 * 1024 * 1024 + 1),
            metadata={},
            invocation_id="child",
            inputs={},
            replay_safe=True,
        )
    journal.stage(
        revision=0,
        checkpoint=b"fixture",
        metadata={},
        invocation_id="child",
        inputs={},
        replay_safe=True,
    )
    with pytest.raises(ValueError, match="runtime changed"):
        ProgramJournal(scope, "program", "different", "tree").load()
    with pytest.raises(ValueError, match="Workspace changed"):
        ProgramJournal(scope, "program", "config", "other").load()
    with store._transaction() as conn:
        conn.execute("update work_programs set checkpoint=?", (b"corrupt",))
    with pytest.raises(ValueError, match="integrity"):
        journal.load()


def test_stale_owner_cannot_read_or_complete(tmp_path, monkeypatch):
    store = store_for(tmp_path)
    old = ProgramJournal(scope_for(store, lease=1), "program", "config", "tree")
    old.stage(
        revision=0,
        checkpoint=b"fixture",
        metadata={},
        invocation_id="child",
        inputs={},
        replay_safe=True,
    )
    recover(store, monkeypatch)
    scope_for(store, worker="new")
    with pytest.raises(ValueError, match="leased"):
        old.load()
    with pytest.raises(ValueError, match="leased"):
        old.complete(1, {}, {})


def test_program_inspection_contains_no_snapshot_or_results(tmp_path):
    store = store_for(tmp_path)
    journal = ProgramJournal(scope_for(store), "program", "config", "tree")
    journal.stage(
        revision=0,
        checkpoint=b"private",
        metadata={"secret": "private"},
        invocation_id="child",
        inputs={},
        replay_safe=True,
    )
    rows = inspect_programs(store, "work")
    assert rows[0]["checkpoint_bytes"] == 7
    assert "private" not in str(rows)


class FixtureHost:
    def __init__(self, root, *, safe=True):
        self.root = root
        self.safe = safe
        self.calls = []
        self.denied = False
        self.result_denied = False

    def identity(self):
        return {"capabilities": "fixture", "safe": self.safe}

    async def prepare(self, function, args, kwargs, call_id):
        if self.denied:
            raise ValueError("current policy denied")
        return {"name": args[0], "arguments": args[1], "replay_safe": self.safe}

    async def execute(self, prepared, call_id, signal):
        value = prepared["arguments"]["value"]
        self.calls.append(value)
        with (self.root / ".superqode" / "calls").open("a") as stream:
            stream.write(str(value) + "\n")
        return {"output": str(value * 10)}

    async def check_result(self, prepared, value):
        if self.result_denied:
            raise ValueError("current result policy denied")


@pytest.fixture
def monty():
    return pytest.importorskip("pydantic_monty")


PROGRAM = 'a = tool_call("read", {"value": 1})\nb = tool_call("read", {"value": 2})\nint(a["output"]) + int(b["output"])'


@pytest.mark.asyncio
async def test_real_program_completed_reuse_and_current_policy(tmp_path, monty):
    store = store_for(tmp_path)
    scope = scope_for(store)
    host = FixtureHost(tmp_path)
    with recovery_scope(scope):
        first = await run_program("p", PROGRAM, host, cwd=tmp_path)
        reused = await run_program("p", PROGRAM, host, cwd=tmp_path)
        assert first["output"] == "30" and reused["recovery"] == "reused"
        assert host.calls == [1, 2]
        host.denied = True
        with pytest.raises(ValueError, match="current policy"):
            await run_program("p", PROGRAM, host, cwd=tmp_path)
        host.denied = False
        host.result_denied = True
        with pytest.raises(ValueError, match="result policy"):
            await run_program("p", PROGRAM, host, cwd=tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["code", "workspace", "runtime"])
async def test_changed_inputs_block_restore(tmp_path, monty, monkeypatch, change):
    store = store_for(tmp_path)
    scope = scope_for(store)
    host = FixtureHost(tmp_path)
    with recovery_scope(scope):
        await run_program("p", PROGRAM, host, cwd=tmp_path)
        code = PROGRAM
        if change == "code":
            code += "\n42"
        elif change == "workspace":
            (tmp_path / "concurrent-edit").write_text("changed")
        else:
            from superqode.tools import monty_program

            original = monty_program.runtime_identity
            monkeypatch.setattr(
                monty_program, "runtime_identity", lambda m: ({"api": "different"}, original(m)[1])
            )
        with pytest.raises(ValueError, match="changed"):
            await run_program("p", code, host, cwd=tmp_path)
        assert host.calls == [1, 2]


# Abruptly exit a real host process at journal boundaries. Child writes are
# deterministic fixtures, not claims about remote exactly-once execution.
CHILD = """import asyncio,os,sys
from pathlib import Path
from superqode.workorders import WorkOrderStore
from superqode.execution_recovery import recovery_scope
from superqode.workorders.programs import ProgramJournal
from test_monty_program_recovery import FixtureHost,scope_for,PROGRAM
from superqode.tools.monty_program import run_program
root=Path(sys.argv[1]); boundary=sys.argv[2]
store=WorkOrderStore(root/".superqode"/"work.sqlite3")
scope=scope_for(store,"child",1)
host=FixtureHost(root,safe=boundary!="unsafe-effect")
original_stage=ProgramJournal.stage
def stage(self,**kwargs):
 result=original_stage(self,**kwargs)
 if boundary=="before-dispatch" or (boundary=="second-checkpoint" and kwargs["revision"]==1): os._exit(61)
 return result
ProgramJournal.stage=stage
original_finish=ProgramJournal.finish_call
def finish(self,*args):
 original_finish(self,*args)
 if boundary=="after-result": os._exit(61)
ProgramJournal.finish_call=finish
original_complete=ProgramJournal.complete
def complete(self,*args):
 if boundary=="before-complete": os._exit(61)
 original_complete(self,*args)
 if boundary=="after-complete": os._exit(61)
ProgramJournal.complete=complete
original_execute=host.execute
async def execute(*args):
 value=await original_execute(*args)
 if boundary=="unsafe-effect": os._exit(61)
 return value
host.execute=execute
async def main():
 with recovery_scope(scope): await run_program("p",PROGRAM,host,cwd=root)
asyncio.run(main())
"""


def crash(root, boundary):
    source = Path(__file__).resolve().parents[1] / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(source), str(Path(__file__).parent), os.environ.get("PYTHONPATH", "")]
        ),
    }
    child = subprocess.run(
        [sys.executable, "-c", CHILD, str(root), boundary], env=env, timeout=20, capture_output=True
    )
    assert child.returncode == 61, child.stderr.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary",
    ["before-dispatch", "after-result", "second-checkpoint", "before-complete", "after-complete"],
)
async def test_process_crash_restores_program_without_repeating_committed_calls(
    tmp_path, monty, monkeypatch, boundary
):
    store = store_for(tmp_path)
    crash(tmp_path, boundary)
    recover(store, monkeypatch)
    scope = scope_for(store, worker="new")
    with recovery_scope(scope):
        result = await run_program("p", PROGRAM, FixtureHost(tmp_path), cwd=tmp_path)
    assert result["output"] == "30"
    assert (tmp_path / ".superqode" / "calls").read_text().splitlines() == ["1", "2"]
    assert inspect_programs(store, "work")[0]["state"] == "completed"


@pytest.mark.asyncio
async def test_unknown_effect_blocks_until_verified_result(tmp_path, monty, monkeypatch):
    store = store_for(tmp_path)
    crash(tmp_path, "unsafe-effect")
    recover(store, monkeypatch)
    assert store.get("work").tasks[0].status == WorkTaskStatus.BLOCKED
    assert store.claim_next_task(worker_id="new", reference="work") is None
    assert (tmp_path / ".superqode" / "calls").read_text().splitlines() == ["1"]
    invocation = store.invocations("work")[0]
    store.reconcile_invocation(
        "work",
        "task",
        invocation["invocation_id"],
        actor="operator",
        reason="Verified fixture output",
        result={"value": {"output": "10"}},
        workspace=invocation["workspace"],
    )
    store.resume("work", actor="operator")
    with recovery_scope(scope_for(store, worker="new")):
        result = await run_program("p", PROGRAM, FixtureHost(tmp_path, safe=False), cwd=tmp_path)
    assert result["output"] == "30"
    assert (tmp_path / ".superqode" / "calls").read_text().splitlines() == ["1", "2"]


@pytest.mark.asyncio
async def test_cancellation_cancels_owned_host_call(tmp_path, monty):
    from superqode.pipy.signals import AbortController

    store = store_for(tmp_path)
    controller = AbortController()
    entered, stopped = asyncio.Event(), asyncio.Event()
    host = FixtureHost(tmp_path, safe=False)

    async def wait(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    host.execute = wait
    with recovery_scope(scope_for(store)):
        task = asyncio.create_task(
            cancellable_program("p", PROGRAM, host, cwd=tmp_path, signal=controller.signal)
        )
        await asyncio.wait_for(entered.wait(), 5)
        controller.abort()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stopped.is_set()
    assert store.invocations("work")[0]["status"] == "uncertain"


@pytest.mark.asyncio
async def test_call_budget_persists_across_attempts(tmp_path, monty, monkeypatch):
    store = store_for(tmp_path, max_tool_calls=1)
    crash(tmp_path, "after-result")
    recover(store, monkeypatch)
    with recovery_scope(scope_for(store, worker="new")):
        with pytest.raises(ValueError, match="tool-call budget"):
            await run_program("p", PROGRAM, FixtureHost(tmp_path), cwd=tmp_path)
    assert (tmp_path / ".superqode" / "calls").read_text().splitlines() == ["1"]


@pytest.mark.asyncio
async def test_standalone_workorder_process_exit_reuses_program_and_usage(
    tmp_path, monty, monkeypatch
):
    store = store_for(tmp_path)
    (tmp_path / "a.txt").write_text("fixture body")
    code = 'tool_call("read", {"path":"a.txt"})["output"]'
    child_code = """import asyncio,os,sys
from superqode.workorders import WorkOrderStore
from superqode.workorders.program_runner import run_next_program
s=WorkOrderStore(sys.argv[1])
s.complete_task=lambda *a,**k:os._exit(62)
asyncio.run(run_next_program(s,reference="work",code=sys.argv[2],worker_id="child",lease_seconds=1))
"""
    child = subprocess.run(
        [sys.executable, "-c", child_code, str(store.path), code], capture_output=True, timeout=20
    )
    assert child.returncode == 62, child.stderr.decode()
    assert store.usage_summary("work").run_count == 1
    recover(store, monkeypatch)
    from superqode.workorders.program_runner import run_next_program

    result = await run_next_program(store, reference="work", code=code, worker_id="new")
    assert result["status"] == "succeeded" and result["recovery"] == "reused"
    assert result["output"] == "'fixture body'"
    assert store.usage_summary("work").run_count == 1
    assert store.get("work").tasks[0].status == WorkTaskStatus.SUCCEEDED
    assert len([a for a in store.get("work").artifacts if a.kind == "agent_result"]) == 1


@pytest.mark.asyncio
async def test_workorder_cancellation_stops_inflight_program(tmp_path, monty, monkeypatch):
    from superqode.harness.pipy_program import PiPyProgramHost
    from superqode.workorders.program_runner import run_next_program

    store = store_for(tmp_path)
    entered, stopped = asyncio.Event(), asyncio.Event()

    async def wait(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(PiPyProgramHost, "execute", wait)
    task = asyncio.create_task(
        run_next_program(store, reference="work", code='tool_search("read")')
    )
    await asyncio.wait_for(entered.wait(), 5)
    store.cancel("work", actor="user")
    result = await asyncio.wait_for(task, 3)
    assert result["status"] == "cancelled" and stopped.is_set()


def test_program_cli_run_and_content_free_inspection(tmp_path, monty):
    from click.testing import CliRunner
    from superqode.commands.work import work

    store = store_for(tmp_path)
    code = tmp_path / "inspect.py"
    code.write_text('tool_search("read")[0]["name"]')
    runner = CliRunner()
    common = ["--store", str(store.path)]
    result = runner.invoke(work, common + ["program-run", "work", "--code", str(code), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "succeeded"
    inspected = runner.invoke(work, common + ["programs", "work", "--json"])
    assert inspected.exit_code == 0
    assert json.loads(inspected.output)[0]["state"] == "completed"
    assert "tool_search" not in inspected.output


@pytest.mark.asyncio
async def test_sandbox_os_access_is_not_dispatched(tmp_path, monty):
    host = FixtureHost(tmp_path)
    with pytest.raises((ValueError, monty.MontyRuntimeError)):
        await run_program("p", 'open("/etc/passwd").read()', host, cwd=tmp_path)
    assert host.calls == []


def test_remote_call_cannot_bypass_declared_spend_budget(tmp_path):
    store = store_for(tmp_path, max_cost_usd=1.0)
    journal = ProgramJournal(scope_for(store), "program", "config", "tree")
    with pytest.raises(ValueError, match="unknown spend"):
        journal.stage(
            revision=0,
            checkpoint=b"fixture",
            metadata={},
            invocation_id="remote",
            inputs={"prepared": {"name": "mcp_call"}},
            replay_safe=False,
        )
    assert journal.load() is None and store.invocations("work") == []


def test_new_program_id_cannot_bypass_old_uncertain_intent(tmp_path, monkeypatch):
    store = store_for(tmp_path)
    old = scope_for(store, lease=1)
    store.begin_invocation(
        "work",
        "task",
        worker_id=old.worker_id,
        attempt=old.attempt,
        invocation_id="remote",
        operation="remote.create",
        fingerprint="input",
        replay_safe=False,
    )
    recover(store, monkeypatch)
    store.resume("work", actor="operator")
    journal = ProgramJournal(scope_for(store, worker="new"), "different-program", "config", "tree")
    with pytest.raises(ValueError, match="earlier tool outcome"):
        journal.stage(
            revision=0,
            checkpoint=b"fixture",
            metadata={},
            invocation_id="different-call",
            inputs={},
            replay_safe=True,
        )
    assert journal.load() is None and len(store.invocations("work")) == 1
