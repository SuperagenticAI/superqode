"""Tests for the unified tool-batch executor: mutation-safe parallelism,
argument-repair feedback, and doom-loop integration."""

import asyncio
import json
from typing import Any, Dict

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.agent.loop_guard import DoomLoopAbort, DoomLoopDetector
from superqode.tools.base import Tool, ToolRegistry, ToolResult


class _StubTool(Tool):
    """Records execution overlap so tests can assert (non-)parallelism."""

    def __init__(self, name: str, read_only: bool, tracker: Dict[str, Any], delay: float = 0.02):
        self._name = name
        self.read_only = read_only
        self._tracker = tracker
        self._delay = delay

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"stub {self._name}"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args, ctx) -> ToolResult:
        self._tracker["active"] += 1
        self._tracker["max_active"] = max(self._tracker["max_active"], self._tracker["active"])
        self._tracker["order"].append(self._name)
        await asyncio.sleep(self._delay)
        self._tracker["active"] -= 1
        return ToolResult(success=True, output=f"{self._name} ran with {json.dumps(args)}")


def _make_loop(tools: ToolRegistry, threshold: int = 3) -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop.config = AgentConfig(provider="x", model="y", doom_loop_threshold=threshold)
    loop.tools = tools
    loop.parallel_tools = True
    loop.on_tool_call = None
    loop.on_tool_result = None
    loop.on_thinking = None
    loop._doom_guard = DoomLoopDetector(threshold)

    async def _fake_execute_tool(name, arguments, tool_call_id=None):
        tool = tools.get(name)
        if tool is None:
            return ToolResult(success=False, output="", error=f"Unknown tool: {name}")
        return await tool.execute(arguments, None)

    loop._execute_tool = _fake_execute_tool
    return loop


def _call(name: str, args: Any = None, call_id: str = "") -> Dict[str, Any]:
    raw = args if isinstance(args, str) else json.dumps(args or {})
    return {"id": call_id or f"id-{name}", "function": {"name": name, "arguments": raw}}


def _tracker() -> Dict[str, Any]:
    return {"active": 0, "max_active": 0, "order": []}


@pytest.mark.asyncio
async def test_all_read_only_batch_runs_in_parallel():
    tracker = _tracker()
    registry = ToolRegistry()
    for n in ("r1", "r2", "r3"):
        registry.register(_StubTool(n, read_only=True, tracker=tracker))
    loop = _make_loop(registry)

    results = await loop._execute_tool_batch(
        [_call("r1", {"i": 1}), _call("r2", {"i": 2}), _call("r3", {"i": 3})]
    )

    assert tracker["max_active"] >= 2  # genuinely concurrent
    assert [r[0] for r in results] == ["r1", "r2", "r3"]  # results in call order
    assert all(r[3].success for r in results)


@pytest.mark.asyncio
async def test_batch_with_mutation_runs_sequentially_in_order():
    tracker = _tracker()
    registry = ToolRegistry()
    registry.register(_StubTool("read", read_only=True, tracker=tracker))
    registry.register(_StubTool("edit", read_only=False, tracker=tracker))
    loop = _make_loop(registry)

    results = await loop._execute_tool_batch(
        [_call("read", {"a": 1}, "c1"), _call("edit", {"b": 2}, "c2"), _call("read", {"c": 3}, "c3")]
    )

    assert tracker["max_active"] == 1  # never concurrent
    assert tracker["order"] == ["read", "edit", "read"]  # strict call order
    assert [r[1] for r in results] == ["c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_unknown_tool_treated_as_mutating():
    tracker = _tracker()
    registry = ToolRegistry()
    registry.register(_StubTool("read", read_only=True, tracker=tracker))
    loop = _make_loop(registry)

    results = await loop._execute_tool_batch(
        [_call("read", {}), _call("mcp_server_thing", {}), _call("read", {"x": 1})]
    )
    assert tracker["max_active"] == 1
    assert results[1][3].success is False  # unknown tool errors, in order


@pytest.mark.asyncio
async def test_unparseable_arguments_not_executed_and_reported():
    tracker = _tracker()
    registry = ToolRegistry()
    registry.register(_StubTool("edit", read_only=False, tracker=tracker))
    loop = _make_loop(registry)

    results = await loop._execute_tool_batch([_call("edit", "definitely {{{ not json")])

    assert tracker["order"] == []  # never executed
    name, _, args, result = results[0]
    assert name == "edit"
    assert args == {}
    assert result.success is False
    assert "not executed" in (result.error or "")
    assert result.metadata.get("invalid_arguments") is True


@pytest.mark.asyncio
async def test_python_style_arguments_repaired_and_executed():
    tracker = _tracker()
    registry = ToolRegistry()
    registry.register(_StubTool("edit", read_only=False, tracker=tracker))
    loop = _make_loop(registry)

    results = await loop._execute_tool_batch([_call("edit", "{'path': 'x.py', 'flag': True}")])

    assert tracker["order"] == ["edit"]
    assert results[0][2] == {"path": "x.py", "flag": True}
    assert results[0][3].success is True


@pytest.mark.asyncio
async def test_doom_loop_blocks_third_identical_call():
    tracker = _tracker()
    registry = ToolRegistry()
    registry.register(_StubTool("grep", read_only=True, tracker=tracker))
    loop = _make_loop(registry)

    same = {"q": "needle"}
    results = await loop._execute_tool_batch(
        [_call("grep", same, "a"), _call("grep", same, "b"), _call("grep", same, "c")]
    )

    assert tracker["order"] == ["grep", "grep"]  # third call intercepted
    assert results[2][3].success is False
    assert results[2][3].metadata.get("doom_loop") is True
    assert "Loop detected" in (results[2][3].error or "")


@pytest.mark.asyncio
async def test_doom_loop_aborts_when_model_repeats_after_warning():
    tracker = _tracker()
    registry = ToolRegistry()
    registry.register(_StubTool("grep", read_only=True, tracker=tracker))
    loop = _make_loop(registry)

    same = {"q": "needle"}
    await loop._execute_tool_batch(
        [_call("grep", same), _call("grep", same), _call("grep", same)]
    )
    with pytest.raises(DoomLoopAbort):
        await loop._execute_tool_batch([_call("grep", same)])


@pytest.mark.asyncio
async def test_doom_loop_disabled_via_threshold_zero():
    tracker = _tracker()
    registry = ToolRegistry()
    registry.register(_StubTool("grep", read_only=True, tracker=tracker))
    loop = _make_loop(registry, threshold=0)

    same = {"q": "needle"}
    results = await loop._execute_tool_batch([_call("grep", same) for _ in range(5)])
    assert all(r[3].success for r in results)
    assert tracker["order"] == ["grep"] * 5
