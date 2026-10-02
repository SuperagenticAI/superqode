"""PiPy program integration, capability checks and hooks on recovery."""

import asyncio
from pathlib import Path

import pytest

from superqode.harness.pipy_governance import guard_pipy_tools
from superqode.harness.pipy_program import PiPyProgramHost
from superqode.pipy import AgentHarness, AgentTool, AgentToolResult, TextContent, ToolCall
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.session import MemorySessionStorage, create_session
from superqode.pipy.stream import Model
from superqode.pipy.harness_events import ToolCallResult, ToolResultPatch


async def make_host(root, *, config=None, tools=None, script=None):
    from superqode.pipy.tools.registry import create_read_only_tools

    host = PiPyProgramHost(root, config or {"monty": {"enabled": True}})
    harness = AgentHarness(
        session=await create_session(MemorySessionStorage(cwd=str(root))),
        model=Model(id="fixture", provider="fixture"),
        tools=guard_pipy_tools((tools or create_read_only_tools(root)) + [host.tool()]),
        stream_fn=FakeStream(script or [text_response("done")]),
    )
    host.harness = harness
    return host, harness


async def test_program_hooks_revalidate_effective_arguments(tmp_path):
    host, harness = await make_host(tmp_path)
    harness.on("tool_call", lambda event: ToolCallResult(arguments={"path": "rewritten"}))
    prepared = await host.prepare("tool_call", ["read", {"path": "original"}], {}, "call")
    assert prepared["arguments"]["path"] == "rewritten"
    assert prepared["replay_safe"] is True
    harness.on("tool_call", lambda event: ToolCallResult(block=True, reason="denied"))
    with pytest.raises(ValueError, match="denied"):
        await host.prepare("tool_call", ["read", {"path": "original"}], {}, "call")


async def test_invalid_extension_rewrite_and_nested_orchestration_block(tmp_path):
    host, harness = await make_host(tmp_path)
    harness.on("tool_call", lambda event: ToolCallResult(arguments={"path": {"bad": "type"}}))
    with pytest.raises(ValueError, match="Validation failed"):
        await host.prepare("tool_call", ["read", {"path": "original"}], {}, "call")
    for name in ("write", "edit", "bash", "python_program", "spawn_agent"):
        with pytest.raises(ValueError, match="unavailable"):
            await host.prepare("tool_call", [name, {}], {}, "call")


def mcp_tool():
    async def execute(call_id, args, signal=None, on_update=None):
        return AgentToolResult(
            content="remote fixture", details={"structured_content": {"value": 42}}
        )

    return AgentTool(
        name="mcp_call",
        label="MCP",
        description="MCP",
        parameters={"type": "object"},
        execute_fn=execute,
    )


async def test_mcp_capabilities_are_host_owned_and_rechecked_after_rewrite(tmp_path):
    config = {"monty": {"mcp_tools": [{"server": "docs", "tool": "lookup", "read_only": True}]}}
    host, harness = await make_host(tmp_path, config=config, tools=[mcp_tool()])
    args = {"server": "docs", "tool": "lookup", "arguments": {}}
    prepared = await host.prepare("tool_call", ["mcp_call", args], {}, "call")
    assert prepared["replay_safe"] is False
    result = await host.execute(prepared, "call", None)
    assert result["details"]["structured_content"]["value"] == 42
    harness.on("tool_call", lambda event: ToolCallResult(arguments={**args, "tool": "create"}))
    with pytest.raises(ValueError, match="explicit host"):
        await host.prepare("tool_call", ["mcp_call", args], {}, "call")


async def test_result_hook_changes_require_reconciliation_on_reuse(tmp_path):
    host, harness = await make_host(
        tmp_path,
        config={"monty": {"mcp_tools": [{"server": "docs", "tool": "lookup", "read_only": True}]}},
        tools=[mcp_tool()],
    )
    prepared = await host.prepare(
        "tool_call", ["mcp_call", {"server": "docs", "tool": "lookup"}], {}, "call"
    )
    result = await host.execute(prepared, "call", None)
    harness.on("tool_result", lambda event: ToolResultPatch(content=[TextContent("suppressed")]))
    with pytest.raises(ValueError, match="projection changed"):
        await host.check_result(prepared, result)


async def test_actual_pipy_turn_uses_monty_tool(tmp_path):
    pytest.importorskip("pydantic_monty")
    (tmp_path / "a.txt").write_text("fixture body")
    code = 'r = tool_call("read", {"path": "a.txt"})\nlen(r["output"])'
    host, harness = await make_host(
        tmp_path,
        script=[
            tool_response(
                ToolCall(id="program-call", name="python_program", arguments={"code": code})
            ),
            text_response("done"),
        ],
    )
    await harness.prompt("inspect")
    # Use the public conversation projection on the storage object.
    branch = await harness._session.get_branch()
    results = [
        e.message
        for e in branch
        if hasattr(e, "message") and getattr(e.message, "role", None) == "toolResult"
    ]
    assert results and results[-1].text == "12"
    assert results[-1].details["checkpointed"] is False


async def test_adapter_opt_in_and_missing_dependency(tmp_path, monkeypatch):
    from superqode.harness.pipy_adapter import PiPyHarnessProtocolAdapter
    from superqode.harness.protocol import HarnessCreateRequest
    from superqode.pipy.coding_session import PiPyCodingSession
    from superqode.pipy.signals import AbortSignal
    from superqode.tools import monty_program

    captured = []

    async def fake_create(options):
        captured.append(options)

        class Session:
            session_path = tmp_path / "fixture.jsonl"
            harness = type("Harness", (), {"on": lambda *args: None})()

        return Session()

    monkeypatch.setattr(PiPyCodingSession, "create", fake_create)
    adapter = PiPyHarnessProtocolAdapter()
    for config in ({}, {"monty": {"enabled": True}}):
        await adapter._open(
            HarnessCreateRequest(
                harness_id="pipy",
                working_directory=tmp_path,
                model="openai/gpt-4o",
                metadata={"runtime_config": config},
            ),
            tmp_path,
        )
    assert captured[0].extra_tools == ()
    tool = captured[1].extra_tools[0]
    assert tool.name == "python_program"
    monkeypatch.setattr(monty_program, "_load_monty", lambda: None)
    with pytest.raises(RuntimeError, match="not installed"):
        await tool.execute("call", {"code": "42"}, AbortSignal())


async def test_hosted_completed_program_rechecks_nested_hooks(tmp_path):
    pytest.importorskip("pydantic_monty")
    from superqode.workorders import WorkOrder, WorkOrderTask, WorkOrderStore
    from superqode.execution_recovery import RecoveryScope, recovery_scope

    (tmp_path / "a.txt").write_text("body")
    store = WorkOrderStore(tmp_path / ".superqode" / "work.sqlite3")
    store.create(
        WorkOrder(
            work_order_id="work",
            goal="inspect",
            repository=str(tmp_path),
            tasks=(WorkOrderTask(task_id="task", title="inspect", goal="inspect"),),
        )
    )
    store.queue("work")
    _, task = store.claim_next_task(worker_id="owner", reference="work")
    host, harness = await make_host(tmp_path)
    tool = next(t for t in harness.get_tools() if t.name == "python_program")
    code = 'tool_call("read", {"path": "a.txt"})["output"]'
    with recovery_scope(RecoveryScope(store, "work", "task", "owner", task.attempts)):
        first = await tool.execute("same-call", {"code": code})
        assert first.text == "'body'"
        harness.on("tool_call", lambda event: ToolCallResult(block=True, reason="new nested deny"))
        with pytest.raises(ValueError, match="new nested deny"):
            await tool.execute("same-call", {"code": code})
    assert [r["operation"] for r in store.invocations("work")] == ["pipy.program.host"]


async def test_final_policy_rejection_precedes_program_completion_commit(tmp_path, monkeypatch):
    pytest.importorskip("pydantic_monty")
    from superqode.workorders import WorkOrder, WorkOrderTask, WorkOrderStore
    from superqode.execution_recovery import RecoveryScope, recovery_scope
    from superqode.workorders.programs import inspect_programs
    from superqode.harness import pipy_program

    (tmp_path / "a.txt").write_text("body")
    store = WorkOrderStore(tmp_path / ".superqode" / "work.sqlite3")
    store.create(
        WorkOrder(
            work_order_id="work",
            goal="inspect",
            repository=str(tmp_path),
            tasks=(WorkOrderTask(task_id="task", title="inspect", goal="inspect"),),
        )
    )
    store.queue("work")
    _, task = store.claim_next_task(worker_id="owner", reference="work")
    host, harness = await make_host(tmp_path)
    original = pipy_program._result_policy

    def policy(tool, result):
        if tool.name == "python_program":
            return AgentToolResult(
                content="final output denied", details={"governance_denied": True}
            )
        return original(tool, result)

    monkeypatch.setattr(pipy_program, "_result_policy", policy)
    tool = next(t for t in harness.get_tools() if t.name == "python_program")
    with recovery_scope(RecoveryScope(store, "work", "task", "owner", task.attempts)):
        with pytest.raises(ValueError, match="final output denied"):
            await tool.execute(
                "same-call", {"code": 'tool_call("read", {"path": "a.txt"})["output"]'}
            )
    assert inspect_programs(store, "work")[0]["state"] == "pending"


async def test_parallel_native_reads_and_replay_policy(tmp_path):
    (tmp_path / "a").write_text("one")
    (tmp_path / "b").write_text("two")
    host, harness = await make_host(tmp_path)
    prepared = await host.prepare(
        "tool_parallel",
        [
            [
                {"name": "read", "arguments": {"path": "a"}},
                {"name": "read", "arguments": {"path": "b"}},
            ]
        ],
        {},
        "batch",
    )
    result = await host.execute(prepared, "batch", None)
    assert [r["output"] for r in result] == ["one", "two"]
    await host.check_result(prepared, result)
    for name in ("write", "bash", "mcp_call", "python_program"):
        with pytest.raises(ValueError, match="trusted native"):
            await host.prepare("tool_parallel", [[{"name": name}]], {}, "batch")
    harness.on("tool_call", lambda e: ToolCallResult(block=True, reason="current deny"))
    with pytest.raises(ValueError, match="current deny"):
        await host.prepare(
            "tool_parallel", [[{"name": "read", "arguments": {"path": "a"}}]], {}, "batch"
        )


async def test_actual_parallel_program_and_branch_store(tmp_path):
    pytest.importorskip("pydantic_monty")
    from superqode.tools.monty_program import run_program

    host, harness = await make_host(tmp_path)
    (tmp_path / "a").write_text("one")
    code = 'r = tool_parallel([{"name":"read", "arguments":{"path":"a"}}])\nstore("answer", len(r[0]["output"]))\nload("answer")'
    result = await run_program("first", code, host, cwd=tmp_path)
    assert result["output"] == "3"
    leaf = await harness._session.get_leaf_id()
    result = await run_program("second", 'store("answer", 4)\nload("answer")', host, cwd=tmp_path)
    assert result["output"] == "4"
    await harness._session.move_to(leaf)
    result = await run_program("branch", 'load("answer")', host, cwd=tmp_path)
    assert result["output"] == "3"
    with pytest.raises(Exception):
        await run_program("failed", 'store("answer", 99)\n1/0', host, cwd=tmp_path)
    result = await run_program("after-failure", 'load("answer")', host, cwd=tmp_path)
    assert result["output"] == "3"


async def test_parallel_program_budget_counts_children(tmp_path):
    pytest.importorskip("pydantic_monty")
    from superqode.execution_recovery import recovery_scope
    from test_monty_program_recovery import store_for, scope_for
    from superqode.tools.monty_program import run_program

    store = store_for(tmp_path, max_tool_calls=1)
    host, _ = await make_host(tmp_path)
    (tmp_path / "a").write_text("one")
    with recovery_scope(scope_for(store)):
        with pytest.raises(ValueError, match="tool-call budget"):
            await run_program(
                "too-many",
                'tool_parallel([{"name":"read","arguments":{"path":"a"}}, {"name":"read","arguments":{"path":"a"}}])',
                host,
                cwd=tmp_path,
            )
    assert store.invocations("work") == []


async def test_store_limits_do_not_publish(tmp_path):
    host, _ = await make_host(tmp_path)
    await host.begin_program("limits")
    with pytest.raises(ValueError, match="16,000"):
        await host.prepare("store", ["key", "x" * 16_001], {}, "call")
    assert host.program_state() == {"writes": {}}
