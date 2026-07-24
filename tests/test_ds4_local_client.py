import pytest

from superqode.providers.local import DS4Client
from superqode.providers.registry import get_local_providers


@pytest.mark.asyncio
async def test_ds4_lists_server_models_as_tool_capable(monkeypatch):
    client = DS4Client(host="http://127.0.0.1:8000/v1")
    seen_timeouts = []

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        assert method == "GET"
        assert endpoint == "/models"
        seen_timeouts.append(timeout)
        return {"data": [{"id": "deepseek-v4-flash"}]}

    monkeypatch.setattr(client, "_async_request", fake_request)

    models = await client.list_models()

    assert [model.id for model in models] == ["deepseek-v4-flash"]
    assert seen_timeouts == [1.5]
    assert models[0].supports_tools is True
    assert models[0].running is True
    assert models[0].family == "deepseek"


@pytest.mark.asyncio
async def test_ds4_warmup_sends_one_token_completion():
    """warmup() pokes the model with a 1-token completion to trigger the
    cold load, and reports timing instead of raising."""
    client = DS4Client(host="http://127.0.0.1:8000/v1")
    calls = []

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        calls.append((method, endpoint, data, timeout))
        return {"choices": [{"message": {"content": "hi"}}]}

    client._async_request = fake_request

    result = await client.warmup("deepseek-v4-flash")

    assert result["ok"] is True
    assert result["elapsed"] >= 0
    method, endpoint, data, timeout = calls[0]
    assert method == "POST"
    assert endpoint == "/chat/completions"
    assert data["model"] == "deepseek-v4-flash"
    assert data["max_tokens"] == 1
    assert timeout >= 60  # generous, cold load can take a while


@pytest.mark.asyncio
async def test_ds4_warmup_reports_failure_without_raising():
    client = DS4Client(host="http://127.0.0.1:8000/v1")

    async def boom(method, endpoint, data=None, timeout=10.0):
        raise OSError("connection refused")

    client._async_request = boom

    result = await client.warmup()

    assert result["ok"] is False
    assert "refused" in result["error"]


@pytest.mark.asyncio
async def test_ds4_honors_server_reported_context_length(monkeypatch):
    """ds4-server --ctx N is surfaced via /v1/models; the harness budgets
    against the live window rather than the 1M default."""
    client = DS4Client(host="http://127.0.0.1:8000/v1")

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        return {
            "data": [
                {
                    "id": "deepseek-v4-flash",
                    "name": "DeepSeek V4 Flash",
                    "context_length": 100000,
                    "top_provider": {"context_length": 100000},
                },
                # Falls back to top_provider when the top-level field is absent.
                {"id": "deepseek-v4-pro", "top_provider": {"context_length": 100000}},
            ]
        }

    monkeypatch.setattr(client, "_async_request", fake_request)

    models = await client.list_models()

    assert {m.id: m.context_window for m in models} == {
        "deepseek-v4-flash": 100000,
        "deepseek-v4-pro": 100000,
    }


@pytest.mark.asyncio
async def test_ds4_context_window_defaults_to_1m_when_unreported(monkeypatch):
    client = DS4Client(host="http://127.0.0.1:8000/v1")

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        return {"data": [{"id": "deepseek-v4-flash"}]}

    monkeypatch.setattr(client, "_async_request", fake_request)

    models = await client.list_models()

    assert models[0].context_window == 1_000_000


@pytest.mark.asyncio
async def test_ds4_identifies_laguna_family_and_native_context(monkeypatch):
    client = DS4Client(host="http://127.0.0.1:8000/v1")

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        return {"data": [{"id": "laguna-s-2.1"}]}

    monkeypatch.setattr(client, "_async_request", fake_request)

    model = (await client.list_models())[0]

    assert model.family == "laguna"
    assert model.context_window == 262_144
    assert model.quantization == "Q4_K_M"
    assert model.parameter_count == "118B-A8B"
    assert model.details["reasoning_preservation"] is True


@pytest.mark.asyncio
async def test_ds4_gives_laguna_aliases_distinct_behavior_names(monkeypatch):
    client = DS4Client(host="http://127.0.0.1:8000/v1")

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        return {
            "data": [
                {"id": "laguna-s-2.1", "name": "Laguna S 2.1"},
                {"id": "laguna-s-2.1-chat", "name": "Laguna S 2.1"},
                {"id": "laguna-s-2.1-reasoner", "name": "Laguna S 2.1"},
            ]
        }

    monkeypatch.setattr(client, "_async_request", fake_request)

    models = await client.list_models()

    assert [model.name for model in models] == [
        "Poolside Laguna S 2.1 (default)",
        "Poolside Laguna S 2.1 Chat (thinking off)",
        "Poolside Laguna S 2.1 Reasoner (thinking on)",
    ]
    assert [model.details["thinking_mode"] for model in models] == [
        "request-controlled",
        "off",
        "on",
    ]


@pytest.mark.asyncio
async def test_ds4_falls_back_to_known_models_when_server_unreachable(monkeypatch):
    client = DS4Client(host="http://127.0.0.1:8000/v1")

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        raise OSError("offline")

    monkeypatch.setattr(client, "_async_request", fake_request)

    models = await client.list_models()

    assert [model.id for model in models] == [
        "deepseek-v4-flash",
        "deepseek-chat",
        "laguna-s-2.1",
        "laguna-s-2.1-chat",
        "laguna-s-2.1-reasoner",
    ]
    assert all(model.supports_tools for model in models)
    assert all(model.running is False for model in models)


@pytest.mark.asyncio
async def test_ds4_health_probe_uses_short_timeout(monkeypatch):
    client = DS4Client(host="http://127.0.0.1:8000/v1")
    seen_timeouts = []

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        seen_timeouts.append(timeout)
        return {"data": []}

    monkeypatch.setattr(client, "_async_request", fake_request)

    assert await client.is_available() is True
    assert seen_timeouts == [1.0]


@pytest.mark.asyncio
async def test_ds4_timeout_env_overrides(monkeypatch):
    client = DS4Client(host="http://127.0.0.1:8000/v1")
    seen_timeouts = []

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        seen_timeouts.append(timeout)
        return {"data": []}

    monkeypatch.setenv("DS4_MODELS_TIMEOUT", "0.25")
    monkeypatch.setattr(client, "_async_request", fake_request)

    await client.list_models()

    assert seen_timeouts == [0.25]


def test_ds4_is_a_local_provider_for_tui_picker():
    assert "ds4" in get_local_providers()
