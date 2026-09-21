from __future__ import annotations

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    ToolDefinition,
)
from superqode.systemone.client import StubSystemOneClient, SystemOneTimeout
from superqode.systemone.tool_router import (
    SystemOneToolDecisionProvider,
    ToolRouter,
    ToolRoutingSettings,
    resolve_tool_routing,
)
from superqode.tools.base import Tool, ToolRegistry, ToolResult


def _tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(name="read_file", description="Read a file", parameters={}),
        ToolDefinition(name="web_search", description="Search the web", parameters={}),
        ToolDefinition(name="image_gen", description="Generate an image", parameters={}),
    ]


def _answers(*probabilities: float) -> dict[str, dict[str, float]]:
    return {f"tool_{index}": {"noul": value} for index, value in enumerate(probabilities)}


@pytest.mark.asyncio
async def test_router_keeps_floor_and_tools_above_threshold() -> None:
    client = StubSystemOneClient(_answers(0.01, 0.72, 0.05), fill_missing=False)
    router = ToolRouter(
        SystemOneToolDecisionProvider(client),
        ToolRoutingSettings(mode="enforce", threshold=0.30),
    )

    plan = await router.plan("Research the latest API", _tools())

    assert plan.status == "ok"
    assert plan.selected == ("read_file", "web_search")
    assert [tool.name for tool in router.apply(_tools(), plan)] == ["read_file", "web_search"]
    assert len(client.calls) == 1
    assert len(client.calls[0][1]) == 3


@pytest.mark.asyncio
async def test_shadow_records_selection_but_sends_every_tool() -> None:
    client = StubSystemOneClient(_answers(0.01, 0.80, 0.01), fill_missing=False)
    router = ToolRouter(
        SystemOneToolDecisionProvider(client),
        ToolRoutingSettings(mode="shadow", threshold=0.30),
    )

    plan = await router.plan("Search online", _tools())

    assert plan.selected == ("read_file", "web_search")
    assert [tool.name for tool in router.apply(_tools(), plan)] == [
        "read_file",
        "web_search",
        "image_gen",
    ]


@pytest.mark.asyncio
async def test_timeout_fails_open_without_leaking_error_text() -> None:
    client = StubSystemOneClient(error=SystemOneTimeout("secret upstream body"))
    router = ToolRouter(
        SystemOneToolDecisionProvider(client),
        ToolRoutingSettings(mode="enforce"),
    )

    plan = await router.plan("Do work", _tools())

    assert plan.status == "fail_open"
    assert plan.selected == tuple(tool.name for tool in _tools())
    assert plan.error == "SystemOneTimeout"
    assert "secret" not in plan.error


def test_settings_default_off_and_validate_threshold() -> None:
    assert resolve_tool_routing({}).mode == "off"
    assert resolve_tool_routing({"SUPERQODE_TOOL_ROUTING": "jev"}).mode == "shadow"
    with pytest.raises(ValueError, match="between 0 and 1"):
        resolve_tool_routing({"SUPERQODE_TOOL_ROUTING_THRESHOLD": "2"})


class _NamedTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Run {self._name}"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, args, ctx) -> ToolResult:
        return ToolResult(success=True, output="ok")


class _TwoStepGateway(GatewayInterface):
    def __init__(self) -> None:
        self.tools_seen: list[list[str]] = []
        self.calls = 0

    async def chat_completion(self, messages, model, provider=None, tools=None, **kwargs):
        self.tools_seen.append([tool.name for tool in tools or []])
        self.calls += 1
        if self.calls == 1:
            return GatewayResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "function": {"name": "chosen", "arguments": "{}"},
                    }
                ],
            )
        return GatewayResponse(content="done")

    async def stream_completion(self, *args, **kwargs):
        if False:
            yield None

    async def test_connection(self, provider, model=None):
        return {"ok": True}

    def get_model_string(self, provider, model):
        return f"{provider}/{model}"


@pytest.mark.asyncio
async def test_agent_loop_routes_once_and_holds_catalogue_for_every_step() -> None:
    registry = ToolRegistry()
    registry.register(_NamedTool("chosen"))
    registry.register(_NamedTool("dropped"))
    client = StubSystemOneClient(_answers(0.90, 0.01), fill_missing=False)
    router = ToolRouter(
        SystemOneToolDecisionProvider(client),
        ToolRoutingSettings(mode="enforce", threshold=0.30, always_keep=frozenset()),
    )
    gateway = _TwoStepGateway()
    loop = AgentLoop(
        gateway=gateway,
        tools=registry,
        config=AgentConfig(provider="test", model="test-model"),
        tool_router=router,
    )

    result = await loop.run("Use the chosen tool")

    assert result.content == "done"
    assert gateway.tools_seen == [["chosen"], ["chosen"]]
    assert len(client.calls) == 1
