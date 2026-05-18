"""Tests for the SuperQode → openai-agents tool bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from superqode.runtime.errors import RuntimeNotInstalledError
from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from superqode.tools.permissions import (
    Permission,
    PermissionConfig,
    PermissionManager,
)

pytest.importorskip("agents", reason="openai-agents not installed")

from superqode.runtime.tool_bridge_openai import to_openai_function_tools  # noqa: E402


class _EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo back the input text."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(success=True, output=args.get("text", ""))


def _ctx_factory():
    def make() -> ToolContext:
        return ToolContext(
            session_id="t",
            working_directory=Path.cwd(),
            require_confirmation=False,
            tool_registry=ToolRegistry(),
            sub_agent_runner=None,
        )

    return make


def _allow() -> PermissionManager:
    return PermissionManager(PermissionConfig(default=Permission.ALLOW))


def _deny() -> PermissionManager:
    return PermissionManager(PermissionConfig(default=Permission.DENY))


def _ask() -> PermissionManager:
    return PermissionManager(PermissionConfig(default=Permission.ASK))


def test_bridges_one_function_tool_per_registered_tool():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    bridged = to_openai_function_tools(registry, _ctx_factory(), _allow())
    assert len(bridged) == 1
    assert bridged[0].name == "echo"
    assert "Echo" in bridged[0].description
    assert bridged[0].params_json_schema["properties"]["text"]["type"] == "string"


def test_excluded_tools_are_skipped():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    bridged = to_openai_function_tools(registry, _ctx_factory(), _allow(), excluded={"echo"})
    assert bridged == []


@pytest.mark.asyncio
async def test_on_invoke_runs_the_underlying_tool():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    bridged = to_openai_function_tools(registry, _ctx_factory(), _allow())

    out = await bridged[0].on_invoke_tool(None, '{"text": "hi"}')
    assert out == "hi"


@pytest.mark.asyncio
async def test_deny_returns_error_string_without_executing():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    bridged = to_openai_function_tools(registry, _ctx_factory(), _deny())

    out = await bridged[0].on_invoke_tool(None, '{"text": "should not run"}')
    assert isinstance(out, str)
    assert "denied" in out.lower()


@pytest.mark.asyncio
async def test_ask_triggers_needs_approval_callback():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    bridged = to_openai_function_tools(registry, _ctx_factory(), _ask())

    # needs_approval is the SDK's hook for HITL. We assert that when the
    # PermissionManager returns ASK, the callback returns True.
    needs = await bridged[0].needs_approval(None, {"text": "hi"}, "call-1")
    assert needs is True


@pytest.mark.asyncio
async def test_allow_does_not_require_approval():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    bridged = to_openai_function_tools(registry, _ctx_factory(), _allow())
    needs = await bridged[0].needs_approval(None, {"text": "hi"}, "call-1")
    assert needs is False


@pytest.mark.asyncio
async def test_invalid_json_returns_error_string():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    bridged = to_openai_function_tools(registry, _ctx_factory(), _allow())
    out = await bridged[0].on_invoke_tool(None, "not-json")
    assert "ERROR" in out
