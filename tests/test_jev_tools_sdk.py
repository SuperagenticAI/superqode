from __future__ import annotations

import httpx
import pytest
from fastmcp import Client

from superqode.jev_tools import CodexDynamicToolsAdapter, JevToolRouting, JevToolRoutingClient
from superqode.jev_tools.sdk import RoutingResult
from superqode.jev_tools.service import create_jev_service_app
from superqode.mcp.jev_router_server import build_jev_mcp_server
from superqode.systemone.tool_router import ToolRouter, ToolRoutingSettings


class _Decisions:
    def __init__(self) -> None:
        self.calls = 0

    async def probabilities(self, request, tools):
        self.calls += 1
        return {tool.name: (0.9 if tool.name == "web_search" else 0.1) for tool in tools}


def _tools():
    return [
        {
            "type": "function",
            "name": "web_search",
            "description": "Search the web",
            "parameters": {"type": "object"},
        },
        {
            "type": "function",
            "name": "image_gen",
            "description": "Generate an image",
            "parameters": {"type": "object"},
        },
    ]


@pytest.mark.asyncio
async def test_local_sdk_routes_once_per_turn_and_preserves_schema() -> None:
    decisions = _Decisions()
    core = ToolRouter(
        decisions,
        ToolRoutingSettings(mode="enforce", threshold=0.30, always_keep=frozenset()),
    )
    sdk = JevToolRouting(router=core)

    first = await sdk.route("Find current documentation", _tools(), turn_id="turn-1")
    second = await sdk.route("Find current documentation", _tools(), turn_id="turn-1")

    assert first.tools == (dict(_tools()[0]),)
    assert first.dropped == ("image_gen",)
    assert first.reduction_percent == 50.0
    assert not first.cached and second.cached
    assert decisions.calls == 1


@pytest.mark.asyncio
async def test_codex_adapter_routes_experimental_dynamic_tools() -> None:
    decisions = _Decisions()
    sdk = JevToolRouting(
        router=ToolRouter(
            decisions,
            ToolRoutingSettings(mode="enforce", threshold=0.30, always_keep=frozenset()),
        )
    )
    adapter = CodexDynamicToolsAdapter(sdk)

    params, result = await adapter.thread_start_params(
        "Search docs", _tools(), base={"cwd": "/repo"}
    )

    assert params == {"cwd": "/repo", "dynamicTools": [_tools()[0]]}
    assert result.selected_count == 1
    assert adapter.initialize_capabilities({"another": True}) == {
        "another": True,
        "experimentalApi": True,
    }


class _Coordinator:
    async def route(self, request, tools, **kwargs):
        return RoutingResult(
            tools=(dict(tools[0]),),
            original_count=len(tools),
            selected_count=1,
            dropped=("image_gen",),
            status="ok",
            mode=kwargs.get("mode", "enforce"),
            latency_ms=12,
        )


@pytest.mark.asyncio
async def test_http_service_auth_health_and_remote_client() -> None:
    app = create_jev_service_app(coordinator=_Coordinator(), token="service-secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        health = await http.get("/healthz")
        denied = await http.post(
            "/v1/route-tools", json={"request": "Search docs", "tools": _tools()}
        )
        client = JevToolRoutingClient("http://test", token="service-secret", http=http)
        result = await client.route("Search docs", _tools(), turn_id="turn-2")

    assert health.json()["status"] == "ok"
    assert denied.status_code == 401
    assert result.selected_count == 1
    assert result.tools == (dict(_tools()[0]),)


@pytest.mark.asyncio
async def test_http_service_rejects_invalid_route_input() -> None:
    app = create_jev_service_app(coordinator=_Coordinator(), token="")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post(
            "/v1/route-tools",
            json={"request": "", "tools": _tools()},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_mcp_server_exposes_same_routing_contract() -> None:
    async with Client(build_jev_mcp_server(_Coordinator())) as client:
        listed = await client.list_tools()
        result = await client.call_tool(
            "route_tools",
            {"request": "Search docs", "tools": _tools(), "turn_id": "turn-mcp"},
        )

    assert [tool.name for tool in listed] == ["route_tools"]
    assert result.data["selected_count"] == 1
    assert result.data["tools"] == [_tools()[0]]
