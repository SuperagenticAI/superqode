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
async def test_ds4_falls_back_to_known_models_when_server_unreachable(monkeypatch):
    client = DS4Client(host="http://127.0.0.1:8000/v1")

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        raise OSError("offline")

    monkeypatch.setattr(client, "_async_request", fake_request)

    models = await client.list_models()

    assert [model.id for model in models] == ["deepseek-v4-flash", "deepseek-chat"]
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
