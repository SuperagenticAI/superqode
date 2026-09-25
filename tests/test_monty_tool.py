"""Tests for the Monty Python-sandbox tool.

These run against the *real* ``pydantic-monty`` package (skipped when it is not
installed) so an API mismatch is actually caught — an earlier version of these
tests mocked a fake Monty API and masked a broken integration.
"""

import pytest

from superqode.tools.base import ToolContext, ToolRegistry
from superqode.tools.monty_tool import MontyPythonReplTool, is_monty_available

requires_monty = pytest.mark.skipif(not is_monty_available(), reason="pydantic-monty not installed")


@pytest.fixture
def tool_context(tmp_path):
    return ToolContext(session_id="test-monty", working_directory=tmp_path)


def test_full_registry_includes_python_repl_when_monty_available(monkeypatch):
    monkeypatch.setattr("superqode.tools.monty_tool.is_monty_available", lambda: True)
    registry = ToolRegistry.full()
    assert registry.get("python_repl") is not None


@pytest.mark.asyncio
async def test_python_repl_reports_missing_dependency(monkeypatch, tool_context):
    monkeypatch.setattr("superqode.tools.monty_tool._load_monty", lambda: None)
    result = await MontyPythonReplTool().execute({"code": "1 + 1"}, tool_context)
    assert not result.success
    assert result.metadata["missing_dependency"] == "pydantic-monty"
    assert "superqode[monty]" in result.error


@requires_monty
@pytest.mark.asyncio
async def test_python_repl_executes_and_captures_output(tool_context):
    tool = MontyPythonReplTool()
    result = await tool.execute({"code": "print(2 + 3)\nsum([1, 2, 3, 4])"}, tool_context)
    assert result.success, result.error
    # stdout (5) plus the final expression value (10).
    assert "5" in result.output
    assert "10" in result.output
    assert result.metadata["runtime"] == "monty"


@requires_monty
@pytest.mark.asyncio
async def test_python_repl_returns_final_expression_value(tool_context):
    result = await MontyPythonReplTool().execute({"code": "x = 40\nx + 2"}, tool_context)
    assert result.success, result.error
    assert result.output.strip() == "42"


@requires_monty
@pytest.mark.asyncio
async def test_python_repl_has_no_filesystem_access(tool_context):
    # Monty denies host access: open() is not even defined in the sandbox.
    result = await MontyPythonReplTool().execute(
        {"code": "open('/etc/passwd').read()"}, tool_context
    )
    assert not result.success
    assert result.metadata.get("runtime") == "monty"


@requires_monty
@pytest.mark.asyncio
async def test_python_repl_has_no_network_or_third_party_imports(tool_context):
    result = await MontyPythonReplTool().execute({"code": "import socket"}, tool_context)
    assert not result.success


@requires_monty
@pytest.mark.asyncio
async def test_python_repl_each_call_is_isolated(tool_context):
    tool = MontyPythonReplTool()
    await tool.execute({"code": "x = 99"}, tool_context)
    # Fresh sandbox each call: the prior binding must not leak.
    result = await tool.execute({"code": "x"}, tool_context)
    assert not result.success  # NameError: x is not defined


@requires_monty
@pytest.mark.asyncio
async def test_python_repl_empty_code_rejected(tool_context):
    result = await MontyPythonReplTool().execute({"code": "   "}, tool_context)
    assert not result.success
    assert "required" in result.error.lower()


@requires_monty
@pytest.mark.asyncio
async def test_python_repl_maps_max_duration_secs_to_feed_limit(tool_context):
    """User-facing max_duration_secs must map to Monty v1 max_feed_duration_secs."""
    from superqode.tools import monty_tool as mt

    captured = {}
    real_limits = mt._load_monty().ResourceLimits

    def capture_limits(**kwargs):
        captured.update(kwargs)
        return real_limits(**kwargs)

    class FakeModule:
        ResourceLimits = staticmethod(capture_limits)
        Monty = mt._load_monty().Monty
        __version__ = mt.monty_version()

    # Drive the helper directly so we assert the ResourceLimits kwargs.
    output = mt.run_monty_snippet(
        FakeModule,
        "1 + 1",
        max_duration_secs=1.5,
        max_memory=16 * 1024 * 1024,
    )
    assert "2" in output
    assert "max_feed_duration_secs" in captured
    assert captured["max_feed_duration_secs"] == 1.5
    assert "max_duration_secs" not in captured
    assert captured["max_memory"] == 16 * 1024 * 1024


@requires_monty
@pytest.mark.asyncio
async def test_python_repl_accepts_max_duration_secs_parameter(tool_context):
    result = await MontyPythonReplTool().execute(
        {"code": "2 * 21", "max_duration_secs": 1.0},
        tool_context,
    )
    assert result.success, result.error
    assert "42" in result.output
