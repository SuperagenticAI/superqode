"""Portable progressive discovery: configuration, retrieval, and activation."""

from __future__ import annotations

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.harness.loader import harness_spec_from_dict, harness_spec_to_dict
from superqode.providers.gateway.base import GatewayResponse
from superqode.tools.base import ToolContext, ToolRegistry
from superqode.tools.discovery import (
    BM25Searcher,
    DiscoverySettings,
    ToolDescriptor,
    evaluate_retrieval,
    resolve_discovery_settings,
    retrieve,
)
from superqode.tools.tool_search import ToolSearchTool
from test_deferred_tools import _NamedTool, _registry


class _Gateway:
    async def chat_completion(self, *args, **kwargs):
        return GatewayResponse(content="done")

    async def stream_completion(self, *args, **kwargs):
        if False:
            yield None


def reverse_rank(_query, candidates, *, limit):
    return [candidate.descriptor.id for candidate in reversed(candidates)][:limit]


def test_tool_discovery_spec_round_trips_and_resolves():
    spec = harness_spec_from_dict(
        {
            "name": "portable-discovery",
            "tool_discovery": {
                "enabled": True,
                "mode": "unified",
                "search": {
                    "backend": "custom",
                    "handler": "company.search:tools",
                    "limit": 17,
                    "on_error": "empty",
                },
                "rank": {"candidate_limit": 6, "exact_name_boost": 9},
                "judge": {"backend": "jev", "mode": "shadow"},
                "activation": {"limit": 2},
                "mcp": {"mode": "deferred_tools"},
            },
        }
    )
    settings = resolve_discovery_settings(spec, environ={})
    assert settings == DiscoverySettings(
        enabled=True,
        mode="unified",
        search_backend="custom",
        search_handler="company.search:tools",
        search_limit=17,
        candidate_limit=6,
        activation_limit=2,
        on_error="empty",
        fallback_backends=("bm25", "lexical"),
        exact_name_boost=9.0,
        judge_backend="jev",
        judge_mode="shadow",
        mcp_mode="deferred_tools",
    )
    restored = harness_spec_from_dict(harness_spec_to_dict(spec))
    assert restored.tool_discovery == spec.tool_discovery


@pytest.mark.asyncio
async def test_bm25_exact_identifier_is_deterministic_top_one():
    catalogue = [
        ToolDescriptor(
            id="native:notification_send_channel",
            exposed_name="notification_send_channel",
            original_name="notification_send_channel",
            source="native",
            description="Send a notification to a channel",
        ),
        ToolDescriptor(
            id="native:notification_send_user",
            exposed_name="notification_send_user",
            original_name="notification_send_user",
            source="native",
            description="Send a notification to a user",
        ),
    ]
    found = await BM25Searcher().search(
        "notification_send_user", catalogue, limit=2
    )
    assert [item.descriptor.original_name for item in found] == [
        "notification_send_user",
        "notification_send_channel",
    ]
    assert found[0].signals["exact_name"] > 0


@pytest.mark.asyncio
async def test_unknown_backend_falls_back_with_provenance():
    catalogue = [
        ToolDescriptor(
            id="native:web_fetch",
            exposed_name="web_fetch",
            original_name="web_fetch",
            source="native",
            description="Fetch a web page",
        )
    ]
    candidates, trace = await retrieve(
        "fetch web page",
        catalogue,
        DiscoverySettings(
            enabled=True,
            mode="unified",
            search_backend="semantic",
            fallback_backends=("bm25",),
        ),
    )
    assert candidates[0].descriptor.id == "native:web_fetch"
    assert trace["backend"] == "bm25"
    assert trace["errors"] == [{"backend": "semantic", "error": "ValueError"}]


@pytest.mark.asyncio
async def test_user_owned_ranker_runs_after_search():
    catalogue = [
        ToolDescriptor(
            id=f"native:search_{name}",
            exposed_name=f"search_{name}",
            original_name=f"search_{name}",
            source="native",
            description=f"Search {name}",
        )
        for name in ("alpha", "beta")
    ]
    candidates, trace = await retrieve(
        "search alpha beta",
        catalogue,
        DiscoverySettings(
            enabled=True,
            mode="unified",
            rank_backend="custom",
            rank_handler="test_tool_discovery_pipeline:reverse_rank",
        ),
    )
    assert [item.descriptor.id for item in candidates] == [
        "native:search_beta",
        "native:search_alpha",
    ]
    assert trace["ranker"] == "custom"


@pytest.mark.asyncio
async def test_retrieval_eval_separates_recall_and_none_cases():
    catalogue = [
        ToolDescriptor(
            id="native:web_fetch",
            exposed_name="web_fetch",
            original_name="web_fetch",
            source="native",
            description="Fetch a web page",
        )
    ]
    report = await evaluate_retrieval(
        [
            {"id": "hit", "query": "fetch web page", "expected": "native:web_fetch"},
            {"id": "none", "query": "play a violin", "expected": "none"},
        ],
        catalogue,
        DiscoverySettings(enabled=True, mode="unified"),
    )
    assert report["recallAt1"] == report["mrr"] == 1.0
    assert report["noneAccuracy"] == 1.0
    assert report["positive"] == report["none"] == 1


@pytest.mark.asyncio
async def test_unified_search_uses_one_shortlist_and_activates_mcp_proxy(monkeypatch, tmp_path):
    registry = _registry()
    registry.defer("web_fetch", "shell_session")
    mcp_proxy = _NamedTool("mcp__github__create_issue", "Create a GitHub issue")

    async def fake_mcp_descriptors(*_args, **_kwargs):
        return [
            ToolDescriptor(
                id="mcp:github:create_issue",
                exposed_name=mcp_proxy.name,
                original_name="create_issue",
                source="mcp",
                namespace="github",
                description=mcp_proxy.description,
                input_schema=mcp_proxy.parameters,
                payload=mcp_proxy,
            )
        ]

    monkeypatch.setattr(
        "superqode.tools.discovery.descriptors_from_mcp", fake_mcp_descriptors
    )
    spec = harness_spec_from_dict(
        {
            "name": "unified",
            "tool_discovery": {
                "enabled": True,
                "mode": "unified",
                "search": {"backend": "bm25"},
                "rank": {"candidate_limit": 8},
                "activation": {"limit": 1},
                "mcp": {"mode": "deferred_tools"},
            },
        }
    )
    ctx = ToolContext(
        session_id="t",
        working_directory=tmp_path,
        tool_registry=registry,
        harness_spec=spec,
    )
    result = await ToolSearchTool().execute({"query": "create github issue"}, ctx)

    assert result.success
    assert result.metadata["activated"] == ["mcp__github__create_issue"]
    assert registry.get("mcp__github__create_issue") is mcp_proxy
    assert result.metadata["discovery"]["candidates"][0]["source"] == "mcp"


@pytest.mark.asyncio
async def test_discovery_trace_links_activated_tool(tmp_path):
    registry = _registry()
    registry.defer("web_fetch")
    spec = harness_spec_from_dict(
        {
            "name": "traced",
            "tool_discovery": {
                "enabled": True,
                "mode": "unified",
                "trace_dir": str(tmp_path / "traces"),
                "search": {"backend": "bm25"},
            },
        }
    )
    result = await ToolSearchTool().execute(
        {"query": "fetch web page"},
        ToolContext(
            session_id="session-1",
            working_directory=tmp_path,
            tool_registry=registry,
            harness_spec=spec,
        ),
    )
    discovery_id = result.metadata["discovery"]["discoveryId"]
    assert registry.activation_origin("web_fetch")["discoveryId"] == discovery_id
    traces = list((tmp_path / "traces" / "tool-discovery").glob("*.json"))
    assert len(traces) == 1


def test_agent_loop_enables_unified_discovery_and_appends_activated_schema(tmp_path):
    registry = ToolRegistry()
    registry.register(_NamedTool("read_file", "Read a file"))
    registry.register(_NamedTool("web_fetch", "Fetch a web page"))
    spec = harness_spec_from_dict(
        {
            "name": "unified",
            "tool_discovery": {"enabled": True, "mode": "unified"},
        }
    )
    loop = AgentLoop(
        gateway=_Gateway(),
        tools=registry,
        config=AgentConfig(
            provider="test",
            model="test",
            working_directory=tmp_path,
            enable_session_storage=False,
            harness_spec=spec,
        ),
    )
    before = [item.name for item in loop._get_tool_definitions()]
    assert "tool_search" in before
    assert "web_fetch" not in before

    registry.activate("web_fetch")
    after = [item.name for item in loop._get_tool_definitions()]
    assert after[:-1] == before
    assert after[-1] == "web_fetch"


@pytest.mark.asyncio
async def test_agent_loop_records_discovery_and_execution_for_tui(tmp_path):
    registry = ToolRegistry()
    registry.register(_NamedTool("read_file", "Read a file"))
    registry.register(_NamedTool("web_fetch", "Fetch a web page"))
    spec = harness_spec_from_dict(
        {
            "name": "observable-discovery",
            "tool_discovery": {"enabled": True, "mode": "unified"},
        }
    )
    loop = AgentLoop(
        gateway=_Gateway(),
        tools=registry,
        config=AgentConfig(
            provider="test",
            model="test",
            working_directory=tmp_path,
            enable_session_storage=False,
            harness_spec=spec,
        ),
    )

    search = await ToolSearchTool().execute(
        {"query": "fetch a web page"}, loop._create_tool_context()
    )
    assert search.success
    assert loop.last_discovery_event["query"] == "fetch a web page"
    assert loop.last_discovery_event["activated"] == ["web_fetch"]
    assert "executions" not in loop.last_discovery_event

    executed = await loop._execute_tool("web_fetch", {})
    assert executed.success
    assert loop.last_discovery_event["executions"] == [
        {"tool": "web_fetch", "status": "success", "permission": "allowed"}
    ]
