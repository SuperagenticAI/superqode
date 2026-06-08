"""Tests for exposing SuperQode harnesses over MCP."""

from pathlib import Path

import pytest

from superqode.mcp.harness_server import (
    _resolve_provider_model,
    build_harness_mcp_server,
    build_steps_from_spec,
    discover_harness_specs,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "harnesses"


def test_discover_harness_specs_finds_examples():
    specs = discover_harness_specs(str(EXAMPLES))
    assert "coding" in specs
    assert specs["coding"].suffix in (".yaml", ".yml")


def test_discover_unknown_dir_is_empty():
    assert discover_harness_specs("/no/such/harness/dir") == {}


def test_server_registers_three_tools():
    server = build_harness_mcp_server(str(EXAMPLES))
    import asyncio

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"list_harnesses", "describe_harness", "run_harness"} <= names


@pytest.mark.parametrize("spec_name", ["coding", "ds4"])
def test_build_steps_from_spec_produces_steps(spec_name):
    from superqode.harness import load_harness_spec

    spec = load_harness_spec(str(EXAMPLES / f"{spec_name}.yaml"))
    steps = build_steps_from_spec(spec, "add a healthcheck endpoint")
    assert len(steps) >= 1
    assert all(getattr(s, "id", None) for s in steps)


def test_resolve_provider_model_from_spec_primary():
    spec = type(
        "S",
        (),
        {"model_policy": type("MP", (), {"primary": "openai/gpt-4o"})()},
    )()
    provider, model = _resolve_provider_model(spec, "", "")
    assert provider == "openai"
    assert model == "gpt-4o"


def test_resolve_provider_model_explicit_overrides(monkeypatch):
    monkeypatch.delenv("SUPERQODE_MCP_PROVIDER", raising=False)
    monkeypatch.delenv("SUPERQODE_MCP_MODEL", raising=False)
    spec = type("S", (), {"model_policy": type("MP", (), {"primary": "openai/gpt-4o"})()})()
    provider, model = _resolve_provider_model(spec, "anthropic", "claude-haiku-4-5")
    assert provider == "anthropic"
    assert model == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_describe_harness_tool_returns_details():
    server = build_harness_mcp_server(str(EXAMPLES))
    result = await server.call_tool("describe_harness", {"harness": "coding"})
    content = result[0] if isinstance(result, tuple) else result.content
    text = content[0].text
    assert "Harness: coding" in text
    assert "Workflow mode:" in text


@pytest.mark.asyncio
async def test_describe_unknown_harness_is_graceful():
    server = build_harness_mcp_server(str(EXAMPLES))
    result = await server.call_tool("describe_harness", {"harness": "does-not-exist"})
    content = result[0] if isinstance(result, tuple) else result.content
    assert "Unknown harness" in content[0].text
