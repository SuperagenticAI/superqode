"""Tests for deferred tool loading and the tool_search tool."""

from typing import Any, Dict

import pytest

from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from superqode.tools.tool_search import (
    DEFERRED_TOOLS_ENV,
    ToolSearchTool,
    apply_deferred_tool_policy,
    search_deferred,
)


class _NamedTool(Tool):
    def __init__(self, name: str, description: str):
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args, ctx) -> ToolResult:
        return ToolResult(success=True, output=self._name)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(_NamedTool("read_file", "Read the contents of a text file."))
    registry.register(
        _NamedTool("web_fetch", "Fetch a web page over HTTP and convert to markdown.")
    )
    registry.register(
        _NamedTool("shell_session", "Run and interact with persistent shell processes (REPLs).")
    )
    return registry


def test_defer_hides_schema_but_keeps_tool_executable():
    registry = _registry()
    v0 = registry.version
    assert registry.defer("web_fetch") == 1
    assert registry.version > v0
    active = [t.name for t in registry.active_tools()]
    assert "web_fetch" not in active and "read_file" in active
    assert [d["function"]["name"] for d in registry.to_openai_format()] == active
    # Still resolvable for execution.
    assert registry.get("web_fetch") is not None


def test_activate_restores_schema_and_bumps_version():
    registry = _registry()
    registry.defer("web_fetch")
    v = registry.version
    assert registry.activate("web_fetch") is True
    assert registry.version > v
    assert "web_fetch" in [t.name for t in registry.active_tools()]
    assert registry.activate("web_fetch") is False  # already active


def test_filtered_preserves_deferred_state():
    registry = _registry()
    registry.defer("web_fetch")
    sub = registry.filtered(["read_file", "web_fetch"])
    assert sub.deferred_names() == ["web_fetch"]


def test_search_deferred_ranks_relevant_tool_first():
    registry = _registry()
    registry.defer("web_fetch", "shell_session")
    matches = search_deferred(registry, "fetch a web page")
    assert matches and matches[0][1].name == "web_fetch"


@pytest.mark.asyncio
async def test_tool_search_activates_matches(tmp_path):
    registry = _registry()
    registry.defer("web_fetch", "shell_session")
    ctx = ToolContext(session_id="t", working_directory=tmp_path, tool_registry=registry)
    result = await ToolSearchTool().execute({"query": "interactive shell repl"}, ctx)
    assert result.success
    assert "shell_session" in result.metadata.get("activated", [])
    assert "shell_session" in [t.name for t in registry.active_tools()]


@pytest.mark.asyncio
async def test_tool_search_no_match_lists_deferred(tmp_path):
    registry = _registry()
    registry.defer("web_fetch")
    ctx = ToolContext(session_id="t", working_directory=tmp_path, tool_registry=registry)
    result = await ToolSearchTool().execute({"query": "qqqqzzzz"}, ctx)
    assert result.success
    assert "web_fetch" in result.output


def test_policy_disabled_by_default(monkeypatch):
    monkeypatch.delenv(DEFERRED_TOOLS_ENV, raising=False)
    registry = _registry()
    assert apply_deferred_tool_policy(registry) == 0
    assert registry.deferred_names() == []


def test_policy_all_defers_heavy_set_and_registers_search(monkeypatch):
    monkeypatch.setenv(DEFERRED_TOOLS_ENV, "all")
    registry = _registry()
    count = apply_deferred_tool_policy(registry)
    assert count >= 2  # web_fetch + shell_session exist here
    assert registry.get("tool_search") is not None
    assert "read_file" in [t.name for t in registry.active_tools()]


def test_policy_explicit_names(monkeypatch):
    monkeypatch.setenv(DEFERRED_TOOLS_ENV, "web_fetch")
    registry = _registry()
    assert apply_deferred_tool_policy(registry) == 1
    assert registry.deferred_names() == ["web_fetch"]
