import pytest

from superqode.providers.local import DS4Client
from superqode.providers.registry import get_local_providers


@pytest.mark.asyncio
async def test_ds4_lists_server_models_as_tool_capable(monkeypatch):
    client = DS4Client(host="http://127.0.0.1:8000/v1")

    async def fake_request(method, endpoint, data=None, timeout=10.0):
        assert method == "GET"
        assert endpoint == "/models"
        return {"data": [{"id": "deepseek-v4-flash"}]}

    monkeypatch.setattr(client, "_async_request", fake_request)

    models = await client.list_models()

    assert [model.id for model in models] == ["deepseek-v4-flash"]
    assert models[0].supports_tools is True
    assert models[0].running is True
    assert models[0].family == "deepseek"


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


def test_ds4_is_a_local_provider_for_tui_picker():
    assert "ds4" in get_local_providers()
