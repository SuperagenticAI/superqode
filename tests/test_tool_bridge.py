"""Tests for the SuperQode → ADK tool bridge.

Skipped when google-adk is not installed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from superqode.runtime.errors import RuntimeNotInstalledError
from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager

pytest.importorskip("google.adk", reason="google-adk not installed; skipping bridge tests")

# Imports below only execute when google-adk is available.
from superqode.runtime.tool_bridge import (  # noqa: E402
    make_bridged_tool_class,
    to_adk_tools,
)


class _EchoTool(Tool):
    """A trivial tool we can run end-to-end through the bridge."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes the provided text back."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to echo"},
            },
            "required": ["text"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(success=True, output=args.get("text", ""))


def _ctx_factory():
    from pathlib import Path

    def make() -> ToolContext:
        return ToolContext(
            session_id="test",
            working_directory=Path.cwd(),
            require_confirmation=False,
            tool_registry=ToolRegistry(),
            sub_agent_runner=None,
        )

    return make


def _allow_all() -> PermissionManager:
    return PermissionManager(PermissionConfig(default=Permission.ALLOW))


def _deny_all() -> PermissionManager:
    return PermissionManager(PermissionConfig(default=Permission.DENY))


def test_bridge_produces_one_adk_tool_per_registered_tool():
    registry = ToolRegistry()
    registry.register(_EchoTool())

    bridged = to_adk_tools(registry, _ctx_factory(), _allow_all())

    assert len(bridged) == 1
    assert bridged[0].name == "echo"
    assert "Echoes" in bridged[0].description


def test_excluded_tools_are_skipped():
    registry = ToolRegistry()
    registry.register(_EchoTool())

    bridged = to_adk_tools(registry, _ctx_factory(), _allow_all(), excluded={"echo"})

    assert bridged == []


def test_declaration_preserves_json_schema_parameters():
    registry = ToolRegistry()
    registry.register(_EchoTool())

    bridged = to_adk_tools(registry, _ctx_factory(), _allow_all())
    decl = bridged[0]._get_declaration()

    assert decl.name == "echo"
    # ADK Schema is a pydantic model; .properties should mirror our JSON Schema
    assert decl.parameters is not None
    props = decl.parameters.properties or {}
    assert "text" in props


@pytest.mark.asyncio
async def test_bridged_tool_executes_through_run_async():
    from google.adk.tools.tool_context import ToolContext as ADKToolContext  # noqa: F401

    registry = ToolRegistry()
    registry.register(_EchoTool())
    bridged = to_adk_tools(registry, _ctx_factory(), _allow_all())

    result = await bridged[0].run_async(args={"text": "hi"}, tool_context=None)  # type: ignore[arg-type]
    assert result == {"success": True, "output": "hi"}


@pytest.mark.asyncio
async def test_permission_deny_short_circuits_execution():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    bridged = to_adk_tools(registry, _ctx_factory(), _deny_all())

    result = await bridged[0].run_async(args={"text": "should not run"}, tool_context=None)  # type: ignore[arg-type]
    assert result["success"] is False
    assert "denied" in result["error"].lower()


def test_make_bridged_tool_class_returns_a_basetool_subclass():
    from google.adk.tools.base_tool import BaseTool

    cls = make_bridged_tool_class()
    assert issubclass(cls, BaseTool)


def test_bridge_raises_install_hint_when_adk_missing(monkeypatch):
    # This test only runs when google.adk IS installed — but we can simulate
    # the failure path by hiding the module from importlib briefly.
    import sys

    saved = {k: v for k, v in sys.modules.items() if k.startswith("google.adk")}
    for k in list(saved):
        sys.modules.pop(k, None)
    sys.modules["google.adk.tools.base_tool"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeNotInstalledError):
            make_bridged_tool_class()
    finally:
        sys.modules.pop("google.adk.tools.base_tool", None)
        sys.modules.update(saved)
