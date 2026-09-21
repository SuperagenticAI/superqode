from __future__ import annotations

import json

import httpx
import pytest
from click.testing import CliRunner

from superqode.commands.serve import serve
from superqode.systemone.tool_router import ToolRouter, ToolRoutingSettings
from superqode.tool_gateway import (
    GatewayConfig,
    ToolRequestRouter,
    create_tool_gateway_app,
)
from superqode.tool_gateway.app import _upstream_url


class _Decisions:
    def __init__(self, values: dict[str, float]) -> None:
        self.values = values
        self.calls = 0

    async def probabilities(self, request, tools):
        self.calls += 1
        return {tool.name: self.values.get(tool.name, 0.0) for tool in tools}


class _SSEStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"event: message_start\n"
        yield b'data: {"type":"message_start"}\n\n'
        yield b"event: message_stop\n"
        yield b'data: {"type":"message_stop"}\n\n'


def test_gemini_openai_compatibility_url_does_not_duplicate_v1() -> None:
    assert (
        _upstream_url(
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "/v1/chat/completions",
            "",
        )
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )


def _gemini_payload() -> dict:
    return {
        "contents": [{"role": "user", "parts": [{"text": "Read release notes online"}]}],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "web_fetch",
                        "description": "Read a web page",
                        "parameters": {"type": "object"},
                    },
                    {
                        "name": "image_gen",
                        "description": "Generate an image",
                        "parameters": {"type": "object"},
                    },
                ]
            }
        ],
    }


@pytest.mark.asyncio
async def test_native_gemini_catalogue_routes_nested_function_declarations() -> None:
    decisions = _Decisions({"web_fetch": 0.9, "image_gen": 0.1})
    router = ToolRouter(
        decisions,
        ToolRoutingSettings(mode="enforce", threshold=0.30, always_keep=frozenset()),
    )
    routed = ToolRequestRouter(router)

    first, event = await routed.route(_gemini_payload(), turn_id="gemini-turn")
    second, second_event = await routed.route(_gemini_payload(), turn_id="gemini-turn")

    assert [tool["name"] for tool in first["tools"][0]["functionDeclarations"]] == ["web_fetch"]
    assert event is not None and event.original_count == 2 and event.selected_count == 1
    assert second_event is not None and second_event.cached
    assert second == first
    assert decisions.calls == 1


@pytest.mark.asyncio
async def test_native_gemini_gateway_routes_path_and_google_key_header() -> None:
    decisions = _Decisions({"web_fetch": 0.9, "image_gen": 0.1})
    router = ToolRouter(
        decisions,
        ToolRoutingSettings(mode="shadow", threshold=0.30, always_keep=frozenset()),
    )
    received: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"ok": True})

    app = create_tool_gateway_app(
        GatewayConfig(
            "https://generativelanguage.googleapis.com",
            upstream_api_key="google-secret",
        ),
        ToolRequestRouter(router),
        http=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway"
    ) as client:
        response = await client.post(
            "/v1beta/models/gemini-3.8-flash:streamGenerateContent?alt=sse",
            json=_gemini_payload(),
        )

    assert response.status_code == 200
    assert str(received[0].url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.8-flash:streamGenerateContent?alt=sse"
    )
    assert received[0].headers["x-goog-api-key"] == "google-secret"
    assert "authorization" not in received[0].headers


def _chat_payload() -> dict:
    return {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Search the web"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object"},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search online",
                    "parameters": {"type": "object"},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "image_gen",
                    "description": "Generate images",
                    "parameters": {"type": "object"},
                },
            },
        ],
    }


def _anthropic_payload(*, with_result: bool = False) -> dict:
    messages = [{"role": "user", "content": "Inspect and edit the repository"}]
    if with_result:
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "read_file",
                            "input": {"path": "README.md"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "README contents that must not become the turn key",
                        }
                    ],
                },
            ]
        )
    return {
        "model": "claude-test",
        "max_tokens": 1024,
        "messages": messages,
        "tools": [
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
            {
                "name": "edit_file",
                "description": "Edit a file",
                "input_schema": {"type": "object"},
            },
            {
                "name": "web_search",
                "description": "Search online",
                "input_schema": {"type": "object"},
            },
        ],
    }


@pytest.mark.asyncio
async def test_enforce_filters_and_reuses_plan_across_model_steps() -> None:
    decisions = _Decisions({"read_file": 0.01, "web_search": 0.90, "image_gen": 0.01})
    router = ToolRouter(
        decisions,
        ToolRoutingSettings(mode="enforce", threshold=0.30),
    )
    routed = ToolRequestRouter(router)
    received: list[dict] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True}, headers={"x-upstream": "yes"})

    app = create_tool_gateway_app(
        GatewayConfig(upstream="https://provider.example/v1"),
        routed,
        http=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway"
    ) as client:
        first = await client.post(
            "/v1/chat/completions",
            json=_chat_payload(),
            headers={"x-superqode-turn-id": "turn-1"},
        )
        second = await client.post(
            "/v1/chat/completions",
            json=_chat_payload(),
            headers={"x-superqode-turn-id": "turn-1"},
        )

    expected = ["read_file", "web_search"]
    assert [item["function"]["name"] for item in received[0]["tools"]] == expected
    assert [item["function"]["name"] for item in received[1]["tools"]] == expected
    assert decisions.calls == 1
    assert first.headers["x-superqode-tools"] == "3->2"
    assert first.headers["x-superqode-schema-bytes"] == "341->226"
    assert first.headers["x-superqode-routing-cache"] == "miss"
    assert second.headers["x-superqode-routing-cache"] == "hit"
    assert first.headers["x-upstream"] == "yes"


@pytest.mark.asyncio
async def test_status_reports_only_aggregate_routing_metrics() -> None:
    decisions = _Decisions({"read_file": 0.01, "web_search": 0.90, "image_gen": 0.01})
    router = ToolRouter(decisions, ToolRoutingSettings(mode="shadow", threshold=0.30))

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    app = create_tool_gateway_app(
        GatewayConfig("https://provider.example"),
        ToolRequestRouter(router),
        http=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway"
    ) as client:
        await client.post("/v1/chat/completions", json=_chat_payload())
        response = await client.get("/superqode/status")

    assert response.json() == {
        "model_requests": 1,
        "catalogue_requests": 1,
        "tool_entries_received": 3,
        "unroutable_catalogues": 0,
        "routed_requests": 1,
        "original_tools": 3,
        "selected_tools": 2,
        "tool_entries_avoided": 1,
        "tool_entry_reduction_percent": 33.3,
        "original_schema_bytes": 341,
        "selected_schema_bytes": 226,
        "schema_bytes_avoided": 115,
        "schema_byte_reduction_percent": 33.7,
        "cache_hits": 0,
        "fail_open_errors": 0,
        "decision_latency_ms": 0,
        "last_request_shape": {
            "path": "/v1/chat/completions",
            "top_level_keys": ["messages", "model", "tools"],
            "tools_container": "list",
            "tool_count": 3,
        },
    }


@pytest.mark.asyncio
async def test_shadow_and_responses_shape_preserve_complete_catalogue() -> None:
    decisions = _Decisions({"function_a": 0.90, "web_search_preview": 0.01})
    router = ToolRouter(
        decisions,
        ToolRoutingSettings(mode="shadow", threshold=0.30, always_keep=frozenset()),
    )
    routed = ToolRequestRouter(router)
    body = {
        "model": "test-model",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "code"}]}],
        "tools": [
            {
                "type": "function",
                "name": "function_a",
                "description": "Do A",
                "parameters": {"type": "object"},
            },
            {"type": "web_search_preview"},
        ],
    }

    output, event = await routed.route(body)

    assert output["tools"] == body["tools"]
    assert event is not None
    assert event.original_count == 2
    assert event.selected_count == 1
    assert event.dropped == ("web_search_preview",)


@pytest.mark.asyncio
async def test_anthropic_messages_routes_input_schema_and_ignores_tool_results_for_turn_id() -> (
    None
):
    decisions = _Decisions({"read_file": 0.95, "edit_file": 0.80, "web_search": 0.01})
    router = ToolRouter(
        decisions,
        ToolRoutingSettings(mode="enforce", threshold=0.30),
    )
    routed = ToolRequestRouter(router)

    first, first_event = await routed.route(_anthropic_payload())
    second, second_event = await routed.route(_anthropic_payload(with_result=True))

    assert [tool["name"] for tool in first["tools"]] == ["read_file", "edit_file"]
    assert [tool["name"] for tool in second["tools"]] == ["read_file", "edit_file"]
    assert decisions.calls == 1
    assert first_event is not None and not first_event.cached
    assert second_event is not None and second_event.cached
    assert first_event.turn_id == second_event.turn_id


@pytest.mark.asyncio
async def test_anthropic_forced_tool_is_kept_even_below_threshold() -> None:
    decisions = _Decisions({"read_file": 0.90, "edit_file": 0.01, "web_search": 0.01})
    router = ToolRouter(
        decisions,
        ToolRoutingSettings(mode="enforce", threshold=0.30, always_keep=frozenset()),
    )
    routed = ToolRequestRouter(router)
    body = _anthropic_payload()
    body["tool_choice"] = {"type": "tool", "name": "edit_file"}

    output, event = await routed.route(body)

    assert [tool["name"] for tool in output["tools"]] == ["read_file", "edit_file"]
    assert event is not None
    assert "edit_file" not in event.dropped


@pytest.mark.asyncio
async def test_proxy_preserves_upstream_error_and_overrides_authorization() -> None:
    seen = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(429, json={"error": "rate limited"})

    app = create_tool_gateway_app(
        GatewayConfig(upstream="https://provider.example", upstream_api_key="real-key"),
        None,
        http=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway"
    ) as client:
        response = await client.post(
            "/v1/responses?beta=1",
            json={"model": "m", "input": "hello"},
            headers={"authorization": "Bearer local-placeholder"},
        )

    assert response.status_code == 429
    assert response.json() == {"error": "rate limited"}
    assert seen == {
        "url": "https://provider.example/v1/responses?beta=1",
        "authorization": "Bearer real-key",
    }


@pytest.mark.asyncio
async def test_anthropic_upstream_uses_x_api_key_and_preserves_version_header() -> None:
    seen = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        seen["x-api-key"] = request.headers.get("x-api-key")
        seen["authorization"] = request.headers.get("authorization")
        seen["anthropic-version"] = request.headers.get("anthropic-version")
        return httpx.Response(200, json={"type": "message", "content": []})

    app = create_tool_gateway_app(
        GatewayConfig(
            upstream="https://api.anthropic.com",
            upstream_api_key="anthropic-real-key",
        ),
        None,
        http=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway"
    ) as client:
        response = await client.post(
            "/v1/messages",
            json=_anthropic_payload(),
            headers={
                "authorization": "Bearer local-placeholder",
                "anthropic-version": "2023-06-01",
            },
        )

    assert response.status_code == 200
    assert seen == {
        "x-api-key": "anthropic-real-key",
        "authorization": None,
        "anthropic-version": "2023-06-01",
    }


@pytest.mark.asyncio
async def test_anthropic_sse_stream_is_forwarded_without_buffer_rewriting() -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_SSEStream(),
        )

    app = create_tool_gateway_app(
        GatewayConfig(upstream="https://api.anthropic.com"),
        None,
        http=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway"
    ) as client:
        response = await client.post(
            "/v1/messages",
            json={"model": "claude-test", "stream": True, "messages": []},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.content == (
        b"event: message_start\n"
        b'data: {"type":"message_start"}\n\n'
        b"event: message_stop\n"
        b'data: {"type":"message_stop"}\n\n'
    )


def test_cli_refuses_remote_bind_without_explicit_permission() -> None:
    result = CliRunner().invoke(
        serve,
        ["optimize", "--upstream", "https://provider.example", "--host", "0.0.0.0"],
    )

    assert result.exit_code != 0
    assert "--allow-remote" in result.output


def test_cli_builds_local_gateway_without_contacting_upstream(monkeypatch) -> None:
    started = {}
    monkeypatch.setenv("TYPESAFE_API_KEY", "jev-test")

    def fake_run(app, **kwargs):
        started.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = CliRunner().invoke(
        serve,
        ["optimize", "--upstream", "https://provider.example", "--port", "9876"],
    )

    assert result.exit_code == 0, result.output
    assert started["host"] == "127.0.0.1"
    assert started["port"] == 9876


def test_chatgpt_codex_upstream_strips_public_v1_prefix() -> None:
    from superqode.tool_gateway.app import _upstream_url

    assert (
        _upstream_url("https://chatgpt.com/backend-api/codex", "/v1/responses", "")
        == "https://chatgpt.com/backend-api/codex/responses"
    )
