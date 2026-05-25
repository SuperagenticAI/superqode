"""Tests for the agent lifecycle hook system."""

from __future__ import annotations

from pathlib import Path

import pytest

from superqode.agent.hooks import (
    AFTER_LLM_CALL,
    AFTER_TOOL_CALL,
    AFTER_TURN_COMPLETE,
    ALL_HOOK_POINTS,
    BEFORE_LLM_CALL,
    BEFORE_TOOL_CALL,
    HookRegistry,
    LifecycleContext,
)
from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.providers.gateway import PassthroughGateway, PlaybackGateway
from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult


# ---------------------------------------------------------------------------
# Registry mechanics
# ---------------------------------------------------------------------------


def test_registry_rejects_unknown_point():
    reg = HookRegistry()
    with pytest.raises(ValueError):
        reg.register("nope", lambda: None)


def test_registry_lists_in_registration_order():
    reg = HookRegistry()
    reg.register(BEFORE_LLM_CALL, lambda *a: None, name="first")
    reg.register(BEFORE_LLM_CALL, lambda *a: None, name="second")
    assert reg.list_hooks(BEFORE_LLM_CALL) == ["first", "second"]
    assert reg.has_hooks(BEFORE_LLM_CALL) is True
    assert reg.has_hooks(AFTER_TOOL_CALL) is False


def test_registry_unregister_by_name():
    reg = HookRegistry()
    reg.register(BEFORE_LLM_CALL, lambda *a: None, name="x")
    assert reg.unregister(BEFORE_LLM_CALL, "x") is True
    assert reg.unregister(BEFORE_LLM_CALL, "x") is False
    assert reg.list_hooks(BEFORE_LLM_CALL) == []


@pytest.mark.asyncio
async def test_registry_fires_in_order_for_sync_and_async():
    reg = HookRegistry()
    fired: list[str] = []

    def sync_hook(*_args):
        fired.append("sync")

    async def async_hook(*_args):
        fired.append("async")

    reg.register(BEFORE_LLM_CALL, sync_hook)
    reg.register(BEFORE_LLM_CALL, async_hook)
    await reg.fire(BEFORE_LLM_CALL)
    assert fired == ["sync", "async"]


@pytest.mark.asyncio
async def test_failing_hook_does_not_break_chain(caplog):
    reg = HookRegistry()
    fired: list[str] = []

    def boom(*_args):
        raise RuntimeError("explode")

    def ok(*_args):
        fired.append("ok")

    reg.register(AFTER_LLM_CALL, boom)
    reg.register(AFTER_LLM_CALL, ok)
    with caplog.at_level("ERROR"):
        await reg.fire(AFTER_LLM_CALL)
    assert fired == ["ok"]
    assert any("explode" in r.message or "explode" in str(r.exc_info) for r in caplog.records)


def test_all_hook_points_constant_matches_registry_init():
    reg = HookRegistry()
    for point in ALL_HOOK_POINTS:
        assert reg.has_hooks(point) is False  # registry knows about it but it's empty


# ---------------------------------------------------------------------------
# AgentLoop integration
# ---------------------------------------------------------------------------


def _basic_config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(provider="synthetic", model="passthrough", working_directory=tmp_path)


@pytest.mark.asyncio
async def test_loop_fires_llm_call_hooks_each_iteration(tmp_path):
    reg = HookRegistry()
    fired: list[tuple[str, int]] = []

    async def record_before(ctx: LifecycleContext, *_):
        fired.append((BEFORE_LLM_CALL, ctx.iteration))

    async def record_after(ctx: LifecycleContext, *_):
        fired.append((AFTER_LLM_CALL, ctx.iteration))

    reg.register(BEFORE_LLM_CALL, record_before)
    reg.register(AFTER_LLM_CALL, record_after)

    loop = AgentLoop(
        gateway=PassthroughGateway(),
        tools=ToolRegistry(),
        config=_basic_config(tmp_path),
        hooks=reg,
    )
    response = await loop.run("hello")
    assert response.stopped_reason == "complete"
    # Single iteration, single before + after
    assert fired == [(BEFORE_LLM_CALL, 1), (AFTER_LLM_CALL, 1)]


@pytest.mark.asyncio
async def test_loop_fires_after_turn_complete_once_per_iteration(tmp_path):
    reg = HookRegistry()
    counts = []

    async def record(ctx: LifecycleContext, response, results):
        counts.append((ctx.iteration, len(results)))

    reg.register(AFTER_TURN_COMPLETE, record)

    loop = AgentLoop(
        gateway=PassthroughGateway(),
        tools=ToolRegistry(),
        config=_basic_config(tmp_path),
        hooks=reg,
    )
    await loop.run("hello")
    # One iteration, no tool calls -> single turn complete with empty results list.
    assert counts == [(1, 0)]


class _EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo back the message argument."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }

    async def execute(self, args, ctx: ToolContext) -> ToolResult:
        return ToolResult(success=True, output=args.get("message", ""))


@pytest.mark.asyncio
async def test_loop_fires_tool_hooks_around_execution(tmp_path):
    """PlaybackGateway → tool call → text. Two iterations total."""
    reg = HookRegistry()
    events: list[tuple[str, str]] = []

    async def before_tool(ctx, name, args):
        events.append(("before_tool", name))

    async def after_tool(ctx, name, args, result):
        events.append(("after_tool", f"{name}:{result.output}"))

    reg.register(BEFORE_TOOL_CALL, before_tool)
    reg.register(AFTER_TOOL_CALL, after_tool)

    gateway = PlaybackGateway()
    gateway.queue_tool_call("echo", {"message": "hi"})
    gateway.queue("done")

    tools = ToolRegistry()
    tools.register(_EchoTool())

    loop = AgentLoop(
        gateway=gateway,
        tools=tools,
        config=_basic_config(tmp_path),
        hooks=reg,
    )
    response = await loop.run("call echo")
    assert response.stopped_reason == "complete"
    assert response.tool_calls_made == 1
    assert events == [("before_tool", "echo"), ("after_tool", "echo:hi")]


@pytest.mark.asyncio
async def test_tool_hook_fires_for_unknown_tool(tmp_path):
    """Unknown tools should still get pre+post hook coverage for audit purposes."""
    reg = HookRegistry()
    seen: list[tuple[str, bool]] = []

    async def after_tool(ctx, name, args, result):
        seen.append((name, result.success))

    reg.register(AFTER_TOOL_CALL, after_tool)

    gateway = PlaybackGateway()
    gateway.queue_tool_call("ghost", {})
    gateway.queue("done")

    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry(),
        config=_basic_config(tmp_path),
        hooks=reg,
    )
    await loop.run("unknown tool")
    assert seen == [("ghost", False)]


@pytest.mark.asyncio
async def test_loop_runs_without_hooks_when_registry_omitted(tmp_path):
    """No registry passed → default empty registry → loop works unchanged."""
    loop = AgentLoop(
        gateway=PassthroughGateway(),
        tools=ToolRegistry(),
        config=_basic_config(tmp_path),
    )
    response = await loop.run("hello")
    assert response.stopped_reason == "complete"
    assert response.content == "hello"
