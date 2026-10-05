"""Acceptance contracts for history, shared inference budgets and Bash jobs."""

import asyncio
from dataclasses import replace
import json
import os
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.messages import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from superqode.pipy.stream import Model
from superqode.rlm.budget import BudgetPolicy, RLMBudget
from superqode.rlm.commands import CommandBroker, clean_env, fingerprint
from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions
from superqode.rlm.history import RLMHistory
from superqode.rlm.profile import RLMProfile
from superqode.rlm.sandbox import RLMSandboxConfig


def broker(tmp_path, **kwargs):
    return CommandBroker(tmp_path, tmp_path / "jobs.sqlite3", **kwargs)


@pytest.mark.skipif(
    os.name != "posix" or not shutil.which("bash"),
    reason="Bash is required for this execution profile",
)
def test_bash_outputs_are_bounded_durable_and_idempotent(tmp_path):
    commands = broker(tmp_path, max_output_chars=256)
    job = commands.start("printf '%0400d' 1", request_id="once")
    receipt = job.wait(timeout=5)
    assert receipt["state"] == "complete"
    assert receipt["stdout_chars"] == 256
    assert receipt["stdout_omitted"] == 144
    assert len(repr(job)) < 200
    resumed = broker(tmp_path)
    assert resumed.read(job.id, start=250, size=20)["text"] == "000000"
    assert resumed.start("printf '%0400d' 1", request_id="once").id == job.id
    with pytest.raises(ValueError, match="different inputs"):
        resumed.start("echo changed", request_id="once")


def test_command_environment_does_not_receive_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private")
    monkeypatch.setenv("SUPERQODE_A2A_KEY", "private")
    monkeypatch.setenv("CUSTOM_ACCESS_TOKEN", "private")
    assert not any(
        k in clean_env() for k in ("OPENAI_API_KEY", "SUPERQODE_A2A_KEY", "CUSTOM_ACCESS_TOKEN")
    )
    with pytest.raises(ValueError, match="Credential"):
        clean_env(overrides={"OPENAI_API_KEY": "private"})


@pytest.mark.skipif(
    os.name != "posix" or os.name != "posix" or not shutil.which("bash"),
    reason="POSIX process group contract",
)
def test_cancellation_stops_descendant_and_serializes_mutations(tmp_path):
    commands = broker(tmp_path)
    job = commands.start("sleep 30 & echo $!; wait")
    deadline = asyncio.run(_wait_for_output(job))
    child = int(deadline.strip())
    with pytest.raises(RuntimeError, match="Workspace"):
        commands.start("echo competing edit")
    job.cancel()
    for _ in range(100):
        if not fingerprint(child):
            break
        import time

        time.sleep(0.01)
    assert not fingerprint(child)
    assert job.wait(timeout=5)["state"] == "cancelled"
    assert commands.start("echo next").wait(timeout=5)["state"] == "complete"


async def _wait_for_output(job):
    for _ in range(100):
        value = job.read()["text"]
        if value:
            return value
        await asyncio.sleep(0.01)
    raise AssertionError("Command produced no output")


@pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="Bash required")
def test_unknown_outcome_keeps_lease_until_verified(tmp_path):
    commands = broker(tmp_path)
    job = commands.start("true")
    job.wait(timeout=5)
    with sqlite3.connect(commands.path) as db:
        db.execute("UPDATE jobs SET state='unknown' WHERE id=?", (job.id,))
    with pytest.raises(RuntimeError, match="reconciliation"):
        commands.start("echo retry")
    result = commands.reconcile(job.id, returncode=0, reason="Verified workspace and output")
    assert result["state"] == "reconciled"
    assert commands.start("echo next").wait(timeout=5)["returncode"] == 0


def test_command_policy_refuses_shell_and_cross_agent_access(tmp_path):
    commands = broker(tmp_path, policy={"allow_shell": False})
    with pytest.raises(PermissionError):
        commands.start("true")
    with sqlite3.connect(commands.path) as db:
        db.execute(
            "INSERT INTO jobs (id,request_id,command,state,agent) VALUES ('a','a','x','complete','child-a')"
        )
    child = broker(tmp_path, agent="child-b")
    with pytest.raises(PermissionError):
        child.status("a")
    assert child.list() == []


def usage_message(tokens=10, cost=0.01):
    return SimpleNamespace(
        usage=SimpleNamespace(
            input=tokens,
            output=0,
            total_tokens=tokens,
            cache_read=0,
            cache_write=0,
            cost=SimpleNamespace(total=cost),
        )
    )


def test_family_allowance_survives_restart_and_counts_all_lanes(tmp_path):
    path = tmp_path / "budget.sqlite3"
    ledger = RLMBudget(path, BudgetPolicy(max_calls=3))
    for lane in ("root", "child", "semantic"):
        identity = ledger.admit(lane, "agent", "model")
        ledger.finish(identity, usage_message())
    resumed = RLMBudget(path, ledger.policy)
    assert resumed.snapshot()["total"]["tokens"] == 30
    assert resumed.snapshot()["total"]["cost_usd"] == pytest.approx(0.03)
    with pytest.raises(RuntimeError, match="allowance"):
        resumed.admit("child", "agent", "model")
    with pytest.raises(ValueError, match="new session"):
        RLMBudget(path, BudgetPolicy(max_calls=4))


def test_budget_admission_is_atomic_across_workers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    ledger = RLMBudget(tmp_path / "budget.sqlite3", BudgetPolicy(max_calls=2))

    def admit(_):
        try:
            return ledger.admit("child", "agent", "model")
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(x is not None for x in pool.map(admit, range(12))) == 2


@pytest.mark.parametrize("policy", [BudgetPolicy(max_tokens=100), BudgetPolicy(max_cost_usd=1)])
def test_unknown_usage_blocks_capped_admission(tmp_path, policy):
    ledger = RLMBudget(tmp_path / "budget.sqlite3", policy)
    identity = ledger.admit("root", "root", "model")
    ledger.finish(identity, failed=True)
    assert ledger.snapshot()["total"]["unknown_cost_calls"] == 1
    with pytest.raises(RuntimeError, match="unavailable"):
        ledger.admit("semantic", "root", "model")


@pytest.mark.asyncio
async def test_history_is_branch_scoped_and_reads_before_compaction(tmp_path):
    session = await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=tmp_path,
            model=Model("fake", "fake"),
            stream_fn=FakeStream([]),
            session_root=tmp_path / "sessions",
        )
    )
    first = await session.session.append_message(UserMessage("old verified result"))
    branch = await session.session.append_message(UserMessage("branch-a-only"))
    await session.session.append_compaction(
        summary="summary", first_kept_entry_id=branch, tokens_before=100
    )
    assert (await session.history.dispatch("history.read", {"id": first}))[
        "text"
    ] == "old verified result"
    await session.session.move_to(first)
    await session.session.append_message(UserMessage("branch-b-only"))
    assert not await session.history.dispatch("history.search", {"query": "branch-a-only"})
    with pytest.raises(ValueError, match="current branch"):
        await session.history.dispatch("history.read", {"id": branch})


@pytest.mark.asyncio
async def test_live_tool_history_cannot_cross_a_branch_change(tmp_path):
    session = await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=tmp_path,
            model=Model("fake", "fake"),
            stream_fn=FakeStream([]),
            session_root=tmp_path / "sessions",
        )
    )
    first = await session.session.append_message(UserMessage("shared root"))
    await session.session.append_message(UserMessage("branch a"))
    result = ToolResultMessage(
        tool_call_id="private-tool", tool_name="python", content=[TextContent("branch a evidence")]
    )
    handle = session.history.store(result)
    session.history.project([result], RLMProfile())
    assert await session.history.dispatch("history.read", {"id": handle})
    await session.session.move_to(first)
    await session.session.append_message(UserMessage("branch b"))
    with pytest.raises(ValueError, match="current branch"):
        await session.history.dispatch("history.read", {"id": handle})


@pytest.mark.asyncio
async def test_root_and_semantic_usage_are_counted_once(tmp_path):
    stream = FakeStream(
        [
            tool_response(
                ToolCall(
                    id="query",
                    name="python",
                    arguments={"code": "answer = llm_query('focused', context='evidence')"},
                )
            ),
            text_response("focused answer"),
            text_response("finished"),
        ]
    )
    session = await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=tmp_path,
            model=Model("fake", "fake"),
            stream_fn=stream,
            session_root=tmp_path / "sessions",
        )
    )
    await session.prompt("work")
    snapshot = session.budget.snapshot()
    assert snapshot["total"]["calls"] == 3
    assert snapshot["lanes"]["root"]["calls"] == 2
    assert snapshot["lanes"]["semantic"]["calls"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("base_options", [False, True])
async def test_coding_children_inherit_family_budget_and_profile(tmp_path, base_options):
    def stream(model, context, options):
        if context.messages[0].text == "child task":
            return FakeStream([text_response("child complete")])(model, context, options)
        if len(context.messages) == 1:
            response = tool_response(
                ToolCall(
                    id="spawn",
                    name="python",
                    arguments={"code": "child = rlm.run('child task'); child.wait()"},
                )
            )
        else:
            response = text_response("root complete")
        return FakeStream([response])(model, context, options)

    from superqode.pipy.coding_session import CodingSessionOptions

    option_type = CodingSessionOptions if base_options else RLMCodingSessionOptions
    extra = (
        {}
        if base_options
        else {"durable_children": False, "profile": RLMProfile(observations="selective")}
    )
    session = await RLMCodingSession.create(
        option_type(
            cwd=tmp_path,
            model=Model("fake", "fake"),
            stream_fn=stream,
            session_root=tmp_path / "sessions",
            **extra,
        )
    )
    await session.prompt("root task")
    snapshot = session.budget.snapshot()
    assert snapshot["total"]["calls"] == 3
    assert snapshot["lanes"]["child"]["calls"] == 1


def test_projection_preserves_user_intent_tool_pairs_and_stored_data(tmp_path):
    history = RLMHistory(None, tmp_path / "history.sqlite3")
    assistant = AssistantMessage(
        content=[ToolCall(id="call", name="python", arguments={"code": "x"})]
    )
    result = ToolResultMessage(
        tool_call_id="call", tool_name="python", content=[TextContent("X" * 5000)]
    )
    messages = [UserMessage("keep this instruction"), assistant, result, UserMessage("latest goal")]
    projected = history.project(
        messages, RLMProfile(observations="selective", observation_chars=256)
    )
    assert projected[0] is messages[0] and projected[1] is assistant
    assert projected[2].tool_call_id == "call" and len(projected[2].text) < 600
    assert result.text == "X" * 5000
    with sqlite3.connect(history.path) as db:
        assert db.execute("SELECT LENGTH(body) FROM observations").fetchone()[0] == 5000


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="Bash required")
async def test_hybrid_uses_same_python_workspace_and_budget(tmp_path):
    session = await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=tmp_path,
            model=Model("fake", "fake"),
            stream_fn=FakeStream([text_response("done")]),
            session_root=tmp_path / "sessions",
            profile=RLMProfile(tool_surface="python-bash"),
        )
    )
    tools = {tool.name: tool for tool in session.tools}
    assert set(tools) == {"python", "bash"}
    receipt = await tools["bash"].execute(
        "bash-1", {"command": "printf evidence > result.txt", "wait": 5}
    )
    assert receipt.details["receipt"]["returncode"] == 0
    py = await tools["python"].execute("py-1", {"code": "workspace.read('result.txt')"})
    assert "evidence" in py.content[0].text
    assert not await session.command_completion_errors()
    await session.prompt("check")
    assert session.budget.snapshot()["lanes"]["root"]["calls"] == 1
    assert "two executable tools" in session._build_prompt(None)
    assert "a2a.start" not in session._build_prompt(None)


def test_monty_cannot_be_selected_with_bash():
    with pytest.raises(ValueError, match="host or Docker"):
        RLMProfile(tool_surface="python-bash").validate_sandbox(RLMSandboxConfig(backend="monty"))


def test_limits_validate_direct_and_config_construction():
    for kwargs in ({"max_calls": -1}, {"max_tokens": 1.5}, {"max_cost_usd": float("nan")}):
        with pytest.raises(ValueError):
            BudgetPolicy(**kwargs)
    for value in (True, 2.5, "1.5"):
        with pytest.raises(ValueError):
            BudgetPolicy.from_config({"max_calls": value})
    with pytest.raises(ValueError):
        RLMProfile(tool_surface="invalid")


def test_unknown_usage_is_visible_and_reconciliation_is_audited(tmp_path):
    ledger = RLMBudget(tmp_path / "budget.sqlite3", BudgetPolicy(max_cost_usd=1))
    identity = ledger.admit("root", "root", "fake")
    if os.name == "posix":
        with pytest.raises(ValueError, match="live request"):
            ledger.reconcile(identity, tokens=10, cost_usd=0.1, reason="premature")
    ledger.finish(identity)
    assert ledger.snapshot()["unsettled"][0]["id"] == identity
    ledger.reconcile(identity, tokens=10, cost_usd=0.1, reason="verified provider record")
    assert ledger.snapshot()["unsettled"] == []
    ledger.admit("semantic", "root", "fake")
    with sqlite3.connect(ledger.path) as db:
        assert (
            db.execute("SELECT reason FROM reconciliation").fetchone()[0]
            == "verified provider record"
        )


@pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="POSIX Bash required")
@pytest.mark.asyncio
async def test_command_request_signature_and_workspace_write_lease(tmp_path):
    from superqode.rlm.kernel import PersistentPythonKernel

    kernel = PersistentPythonKernel(tmp_path)
    commands = kernel.globals["commands"]
    job = commands.start("sleep 30", request_id="once", timeout=60)
    try:
        with pytest.raises(ValueError, match="different inputs"):
            commands.start("sleep 30", request_id="once", timeout=30)
        result = await kernel.execute("workspace.write('x.txt', 'racing')")
        assert "Workspace command is active" in result.error
        assert not (tmp_path / "x.txt").exists()
    finally:
        job.cancel()
    assert (await kernel.execute("workspace.write('x.txt', 'safe')")).error is None


@pytest.mark.asyncio
async def test_profile_is_immutable_across_session_resume(tmp_path):
    options = RLMCodingSessionOptions(
        cwd=tmp_path,
        model=Model("fake", "fake"),
        stream_fn=FakeStream([text_response("done")]),
        session_root=tmp_path / "sessions",
    )
    session = await RLMCodingSession.create(options)
    await session.prompt("hello")
    with pytest.raises(ValueError, match="new session"):
        await RLMCodingSession.resume(
            replace(options, profile=RLMProfile(observations="selective")),
            session_path=session.session_path,
        )


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="POSIX Bash required")
async def test_abort_cancels_command_before_waiting_for_busy_python(tmp_path):
    source = FakeStream(
        [
            tool_response(
                ToolCall(
                    id="blocking",
                    name="python",
                    arguments={"code": "job = commands.start('sleep 30'); job.wait(timeout=20)"},
                )
            ),
            text_response("done"),
        ]
    )
    session = await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=tmp_path,
            model=Model("fake", "fake"),
            stream_fn=source,
            session_root=tmp_path / "sessions",
        )
    )
    run = asyncio.create_task(session.prompt("work"))
    try:
        for _ in range(100):
            jobs = await session.command_request({"action": "list"}, admin=True)
            if jobs and jobs[0]["state"] == "running":
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("Command never started")
        await asyncio.wait_for(session.abort(), 3)
        await asyncio.wait_for(run, 3)
        assert (await session.command_request({"action": "list"}, admin=True))[0][
            "state"
        ] == "cancelled"
    finally:
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)


@pytest.mark.asyncio
async def test_backend_family_usage_is_per_run_and_unknown_cost_remains_none(tmp_path):
    from superqode.harness.backends.rlm import RLMHarnessBackend
    from superqode.harness.backends.base import HarnessBackendRequest
    from superqode.harness.rlm_adapter import RLMHarnessProtocolAdapter
    from superqode.harness.templates import get_harness_template
    from superqode.pipy.messages import Usage, UsageCost

    first, second = text_response("first"), text_response("second")
    first.usage = Usage(input=10, output=5, total_tokens=15, cost=UsageCost(total=0.02))
    source = FakeStream([first, second])

    async def factory(request, cwd, session_path):
        return await RLMCodingSession.create(
            RLMCodingSessionOptions(
                cwd=cwd,
                model=Model("fake", "fake"),
                stream_fn=source,
                session_root=tmp_path / "sessions",
            )
        )

    adapter = RLMHarnessProtocolAdapter(session_factory=factory)
    backend = RLMHarnessBackend(adapter=adapter)
    request = HarnessBackendRequest(
        spec=get_harness_template("rlm"),
        prompt="first",
        provider="fake",
        model="fake",
        working_directory=tmp_path,
        session_id="usage-pilot",
    )
    try:
        a = await backend.run(request)
        assert a.response.total_tokens == 15
        assert a.response.cost_usd == 0.02
        b = await backend.run(replace(request, prompt="second"))
        assert b.metadata["rlm_usage"]["total"]["calls"] == 1
        assert b.response.total_tokens is None and b.response.cost_usd is None
        assert a.metadata["rlm_usage"]["total"]["calls"] == 1
    finally:
        await adapter.close(adapter._refs["usage-pilot"])


@pytest.mark.asyncio
async def test_capped_concurrent_inference_waits_for_reported_usage(tmp_path):
    from superqode.pipy.messages import Usage, UsageCost
    from superqode.pipy.provider_events import AssistantDoneEvent

    ledger = RLMBudget(tmp_path / "budget.sqlite3", BudgetPolicy(max_calls=3, max_cost_usd=1))
    active = 0
    peak = 0

    async def source(model, context, options):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.03)
            message = text_response("done")
            message.usage = Usage(input=10, total_tokens=10, cost=UsageCost(total=0.01))
            yield AssistantDoneEvent(reason="stop", message=message)
        finally:
            active -= 1

    wrapped = ledger.wrap(source, lane="semantic", owner="root")

    async def consume():
        return [event async for event in wrapped(Model("fake", "fake"), None, None)]

    results = await asyncio.gather(consume(), consume(), consume())
    assert peak == 1 and all(events[0].type == "done" for events in results)
    assert ledger.snapshot()["total"]["cost_usd"] == pytest.approx(0.03)
    assert ledger.snapshot()["total"]["calls"] == 3


def test_interrupted_capped_inference_requires_reconciliation(tmp_path):
    ledger = RLMBudget(tmp_path / "budget.sqlite3", BudgetPolicy(max_cost_usd=1))
    identity = ledger.admit("root", "root", "fake")
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE calls SET owner_pid=0,owner_identity='' WHERE id=?", (identity,))
    with pytest.raises(RuntimeError, match="Interrupted"):
        ledger.admit("semantic", "root", "fake")
    ledger.reconcile(identity, tokens=10, cost_usd=0.01, reason="verified after worker crash")
    ledger.admit("semantic", "root", "fake")
