import asyncio

import pytest

from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from superqode.tools.composition import ToolComposition
from superqode.tools.monty_tool import MontyPythonReplTool, is_monty_available


class Lookup(Tool):
    read_only = True
    name = "lookup"
    description = "Read deterministic fixture data"
    parameters = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
    }

    async def execute(self, args, ctx):
        return ToolResult(True, str(args["value"]))


def make_context(tmp_path, dispatcher):
    registry = ToolRegistry()
    registry.register(Lookup())
    return ToolContext(
        "composition",
        tmp_path,
        tool_registry=registry,
        execute_tool=dispatcher,
        invocation_id="parent",
    )


@pytest.mark.asyncio
async def test_bridge_uses_dispatcher_and_bounded_receipts(tmp_path):
    calls = []

    async def dispatch(name, args, call_id):
        calls.append(call_id)
        return ToolResult(False, "", error="blocked by policy", metadata={"permission": "denied"})

    bridge = ToolComposition(make_context(tmp_path, dispatch))
    result = await asyncio.to_thread(bridge.call, "lookup", {"value": 1, "token": "secret"})
    assert not result["success"] and result["error"] == "blocked by policy"
    assert calls == ["parent/call-1"]
    assert "secret" not in str(bridge.receipt())
    assert bridge.receipt()["calls"][0]["permission"] == "denied"
    await bridge.close()


@pytest.mark.asyncio
async def test_parallel_and_cancellation_keep_child_status(tmp_path):
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def dispatch(name, args, call_id):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    bridge = ToolComposition(make_context(tmp_path, dispatch), deadline_seconds=10)
    task = asyncio.create_task(asyncio.to_thread(bridge.call, "lookup", {"value": 1}))
    await entered.wait()
    await bridge.close()
    await asyncio.gather(task, return_exceptions=True)
    assert stopped.is_set()
    assert bridge.receipt()["calls"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_bridge_rejects_recursive_and_untrusted_parallel_calls(tmp_path):
    async def dispatch(*args):
        pytest.fail("must not execute")

    bridge = ToolComposition(make_context(tmp_path, dispatch))
    with pytest.raises(ValueError, match="Nested"):
        await asyncio.to_thread(bridge.call, "python_repl", {})
    with pytest.raises(ValueError, match="trusted"):
        await asyncio.to_thread(bridge.parallel, [{"name": "mcp_remote_lookup", "arguments": {}}])
    await bridge.close()


@pytest.mark.skipif(not is_monty_available(), reason="Monty extra unavailable")
@pytest.mark.asyncio
async def test_real_monty_composition_filters_results(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_RLM_TOOLS", "1")

    async def dispatch(name, args, call_id):
        return ToolResult(True, str(args["value"]))

    ctx = make_context(tmp_path, dispatch)
    result = await MontyPythonReplTool().execute(
        {
            "code": 'results = tool_parallel([{"name": "lookup", "arguments": {"value": 2}}, {"name": "lookup", "arguments": {"value": 5}}])\nsum([int(r["output"]) for r in results])'
        },
        ctx,
    )
    assert result.success, result.error
    assert result.output == "7"
    assert len(result.metadata["composition"]["calls"]) == 2


def test_disabled_composition_adds_no_prompt_payload(monkeypatch):
    monkeypatch.delenv("SUPERQODE_RLM_TOOLS", raising=False)
    base = MontyPythonReplTool().description
    assert "tool_call" not in base
    monkeypatch.setenv("SUPERQODE_RLM_TOOLS", "1")
    assert MontyPythonReplTool().description.startswith(base)


@pytest.mark.asyncio
async def test_composition_uses_real_agent_loop_hook_gate(tmp_path):
    from superqode.agent.loop import AgentLoop, AgentConfig
    from superqode.agent.hooks import BEFORE_TOOL_CALL, DENY, HookDecision

    registry = ToolRegistry()
    registry.register(Lookup())
    loop = AgentLoop(
        gateway=object(),
        tools=registry,
        config=AgentConfig(provider="fixture", model="fixture", working_directory=tmp_path),
    )
    loop.hooks.register(
        BEFORE_TOOL_CALL,
        lambda *args, **kwargs: HookDecision(action=DENY, message="fixture policy blocked"),
    )
    ctx = loop._create_tool_context()
    ctx.invocation_id = "outer"
    bridge = ToolComposition(ctx)
    result = await asyncio.to_thread(bridge.call, "lookup", {"value": 1})
    assert not result["success"] and "fixture policy blocked" in result["error"]
    assert bridge.receipt()["calls"][0]["status"] == "blocked"
    await bridge.close()


def test_retained_evidence_is_redacted_bounded_and_expires(tmp_path, monkeypatch):
    import json
    import time
    from superqode.tools.composition_evidence import CompositionEvidence

    monkeypatch.setenv("FIXTURE_API_KEY", "super-secret-token")
    evidence = CompositionEvidence(tmp_path)
    receipt = evidence.retain(
        "call", "Authorization: Bearer abcdef\napi_key=super-secret-token\n" + "x" * 100_000
    )
    assert receipt["evidence_redacted"] and receipt["evidence_truncated"]
    payload = evidence.read("call")
    assert "super-secret-token" not in payload["output"] and "abcdef" not in payload["output"]
    assert payload["retained_bytes"] <= evidence.MAX_RESULT_BYTES
    path = evidence._refs["call"]
    assert path.stat().st_mode & 0o777 == 0o600
    payload["expires_at"] = time.time() - 1
    path.write_text(json.dumps(payload))
    assert evidence.read("call") == {"available": False, "reason": "evidence expired"}
    assert not path.exists()


@pytest.mark.skipif(not is_monty_available(), reason="Monty extra unavailable")
@pytest.mark.asyncio
async def test_real_monty_combines_native_calls_with_real_mcp(tmp_path, monkeypatch):
    import sys
    from superqode.agent.loop import AgentLoop, AgentConfig
    from superqode.harness.pipy_mcp import PiPyMCPTools
    from superqode.tools.mcp_tools import MCPSearchTool, MCPExecuteTool

    server = tmp_path / "datasets.py"
    server.write_text("""from mcp.server.fastmcp import FastMCP
m = FastMCP("datasets")
@m.tool()
def dataset() -> dict[str, list[int]]:
    return {"items": [3,4]}
m.run(transport="stdio")
""")
    monkeypatch.setenv("SUPERQODE_RLM_TOOLS", "1")
    bridge = await PiPyMCPTools.create(
        {"mcp_servers": {"data_account": {"command": sys.executable, "args": [str(server)]}}}
    )
    try:
        await bridge.manager.connect("data_account")
        registry = ToolRegistry()
        registry.register(Lookup())
        registry.register(MCPSearchTool(lambda: bridge.manager))
        registry.register(MCPExecuteTool(lambda: bridge.manager))
        loop = AgentLoop(
            gateway=object(),
            tools=registry,
            config=AgentConfig(provider="fixture", model="fixture", working_directory=tmp_path),
        )
        ctx = loop._create_tool_context()
        ctx.invocation_id = "combine"
        program = """native = tool_search("deterministic fixture")
remote = tool_call("mcp_search", {"query": "dataset", "server": "data_account"})
local = tool_parallel([{"name": native[0]["name"], "arguments": {"value": 2}}, {"name": native[0]["name"], "arguments": {"value": 5}}])
data = tool_call("mcp_execute", {"server": "data_account", "tool": "dataset", "arguments": {}})
sum([int(r["output"]) for r in local]) + sum([x for x in data["structured_content"]["items"] if x > 0])"""
        result = await MontyPythonReplTool().execute({"code": program}, ctx)
        assert result.success, result.error
        assert result.output == "14"
        calls = result.metadata["composition"]["calls"]
        assert len(calls) == 4 and all(c["status"] == "succeeded" for c in calls)
        assert all(c["effective_arguments_sha256"] for c in calls)
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_composition_cannot_enable_mcp_disabled_by_execution_profile(tmp_path):
    from dataclasses import replace
    from superqode.agent.loop import AgentLoop, AgentConfig

    registry = ToolRegistry()

    class Remote(Lookup):
        name = "mcp_fixture"

        async def execute(self, args, ctx):
            pytest.fail("disabled MCP must not run")

    registry.register(Remote())
    config = AgentConfig(provider="fixture", model="fixture", working_directory=tmp_path)
    config.loop_policy = replace(config.loop_policy, mcp=False)
    loop = AgentLoop(gateway=object(), tools=registry, config=config)
    bridge = ToolComposition(loop._create_tool_context())
    try:
        result = await asyncio.to_thread(bridge.call, "mcp_fixture", {"value": 1})
        assert not result["success"] and "disables MCP" in result["error"]
        assert bridge.receipt()["calls"][0]["status"] == "blocked"
    finally:
        await bridge.close()
