"""Tests for live /v1/models discovery and models.dev auto-freshness."""

from __future__ import annotations

import pytest

from superqode.providers import live_models
from superqode.providers.models import ModelCapability, ModelInfo
from superqode.providers.models_dev import ProviderInfo, get_models_dev
from superqode.providers.registry import PROVIDERS


# --- payload parsing / endpoint candidates -----------------------------------


def test_models_endpoints_with_and_without_v1():
    assert live_models._models_endpoints("http://x/v1") == ["http://x/v1/models"]
    got = live_models._models_endpoints("http://x")
    assert got == ["http://x/v1/models", "http://x/models"]


def test_xai_live_discovery_uses_official_api_endpoint():
    xai = PROVIDERS["xai"]

    assert xai.base_url_env == "XAI_API_BASE"
    assert xai.default_base_url == "https://api.x.ai/v1"
    assert xai.example_models[0] == "grok-4.5"


def test_parse_openai_style():
    payload = {"data": [{"id": "a"}, {"id": "b"}, {"nope": 1}]}
    assert live_models._parse_models_payload(payload) == ["a", "b"]


def test_parse_ollama_style():
    payload = {"models": [{"name": "llama3"}, {"name": "qwen"}]}
    assert live_models._parse_models_payload(payload) == ["llama3", "qwen"]


def test_parse_bare_list():
    assert live_models._parse_models_payload([{"id": "x"}]) == ["x"]


def test_parse_garbage():
    assert live_models._parse_models_payload(None) == []
    assert live_models._parse_models_payload(42) == []


@pytest.mark.asyncio
async def test_discover_openai_compatible_models(monkeypatch):
    async def fake_fetch(url, headers, timeout):
        assert url.endswith("/models")
        return {"data": [{"id": "m2"}, {"id": "m1"}]}

    monkeypatch.setattr(live_models, "_fetch_json", fake_fetch)
    ids = await live_models.discover_openai_compatible_models("http://host/v1", "key")
    assert ids == ["m1", "m2"]  # sorted+deduped


@pytest.mark.asyncio
async def test_discover_openai_compatible_empty_on_failure(monkeypatch):
    async def fake_fetch(url, headers, timeout):
        return None

    monkeypatch.setattr(live_models, "_fetch_json", fake_fetch)
    assert await live_models.discover_openai_compatible_models("http://host") == []


# --- provider-level discovery ------------------------------------------------


@pytest.fixture
def fake_catalog(monkeypatch):
    client = get_models_dev()
    saved_p, saved_m = dict(client._providers), dict(client._models)
    client._providers = {
        "baseten": ProviderInfo(
            id="baseten",
            name="Baseten",
            env_vars=["BASETEN_API_KEY"],
            api_url="https://inference.baseten.co/v1",
        ),
    }
    client._models = {
        "baseten": {
            "known-model": ModelInfo(
                id="known-model",
                name="Known",
                provider="baseten",
                input_price=1.0,
                capabilities=[ModelCapability.TOOLS],
            )
        }
    }
    monkeypatch.setattr(client, "ensure_cache_loaded", lambda: True)
    try:
        yield client
    finally:
        client._providers, client._models = saved_p, saved_m


@pytest.mark.asyncio
async def test_discover_provider_live_enriches_and_includes_new(fake_catalog, monkeypatch):
    # Live endpoint returns a catalogued model AND a brand-new one.
    async def fake_disc(base_url, api_key=None, timeout=8.0):
        return ["known-model", "brand-new-model"]

    monkeypatch.setattr(live_models, "discover_openai_compatible_models", fake_disc)
    result = await live_models.discover_provider_models("baseten")
    assert result.source == "live"
    ids = {m.id for m in result.models}
    assert ids == {"known-model", "brand-new-model"}
    # Catalogued one keeps metadata; new one gets safe defaults but is selectable.
    known = next(m for m in result.models if m.id == "known-model")
    new = next(m for m in result.models if m.id == "brand-new-model")
    assert known.input_price == 1.0
    assert new.provider == "baseten"


@pytest.mark.asyncio
async def test_discover_provider_falls_back_to_catalog(fake_catalog, monkeypatch):
    async def fake_disc(base_url, api_key=None, timeout=8.0):
        return []  # live endpoint unreachable

    monkeypatch.setattr(live_models, "discover_openai_compatible_models", fake_disc)
    result = await live_models.discover_provider_models("baseten")
    assert result.source == "models.dev"
    assert [m.id for m in result.models] == ["known-model"]


@pytest.mark.asyncio
async def test_discover_unknown_provider_none(fake_catalog, monkeypatch):
    result = await live_models.discover_provider_models("nonexistent-xyz")
    assert result.source == "none"
    assert result.models == []


@pytest.mark.asyncio
async def test_model_studio_workspace_discovers_all_chat_pages(monkeypatch):
    base = "https://ws-demo.ap-southeast-1.maas.aliyuncs.com"
    calls = []

    async def fetch(url, headers, timeout):
        calls.append(url)
        assert headers["Authorization"] == "Bearer sk-metered-test"
        ids = ["qwen3.8-flash", "qwen4-max-preview"] if len(calls) == 1 else ["new-chat-model"]
        return {
            "success": True,
            "output": {
                "page_size": 2,
                "total": 3,
                "models": [
                    {
                        "model": m,
                        "features": ["function-calling"],
                        "model_info": {"context_window": 256000},
                    }
                    for m in ids
                ],
            },
        }

    monkeypatch.setattr(live_models, "_fetch_json", fetch)
    result = await live_models.discover_provider_models(
        "qwen-intl", base_url=f"{base}/compatible-mode/v1", api_key="sk-metered-test"
    )
    assert calls == [
        f"{base}/api/v1/models?capabilities=TG&page_no={page}&page_size=20" for page in (1, 2)
    ]
    assert result.source == "live"
    assert [m.id for m in result.models] == ["new-chat-model", "qwen3.8-flash"]
    assert all(m.supports_tools and m.context_window == 256000 for m in result.models)
    assert all(not m.pricing_known for m in result.models)


@pytest.mark.asyncio
async def test_model_studio_catalog_fallback_stays_on_workspace_host(monkeypatch):
    host = "https://ws-demo.ap-southeast-1.maas.aliyuncs.com"
    calls = []

    async def fetch(url, headers, timeout):
        calls.append(url)
        return {"data": [{"id": "glm-5.3"}]} if "/compatible-mode/" in url else None

    monkeypatch.setattr(live_models, "_fetch_json", fetch)
    result = await live_models.discover_provider_models(
        "qwen-intl", base_url=f"{host}/compatible-mode/v1", api_key="sk-metered-test"
    )
    assert len(calls) == 2 and all(url.startswith(f"{host}/") for url in calls)
    assert [m.id for m in result.models] == ["glm-5.3"]
    assert result.source == "live"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base,key",
    [
        ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "sk-sp-plan-test"),
        (
            "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
            "sk-metered-test",
        ),
    ],
)
async def test_model_studio_plan_route_never_sends_catalog_request(monkeypatch, base, key):
    async def unexpected(*args):
        pytest.fail("Token Plan credential or endpoint reached discovery")

    monkeypatch.setattr(live_models, "_fetch_json", unexpected)
    result = await live_models.discover_provider_models("qwen-intl", base_url=base, api_key=key)
    assert result.source == "examples"
    assert "metered" in result.error
    assert "qwen4-max-preview" not in [model.id for model in result.models]


# --- auto-freshness ----------------------------------------------------------


def test_get_effective_models_autoloads_from_cache(monkeypatch):
    import superqode.providers.models as models_mod

    # Simulate a fresh process: no live data yet.
    monkeypatch.setattr(models_mod, "_use_live_data", False)
    monkeypatch.setattr(models_mod, "_live_models", None)
    monkeypatch.setattr(models_mod, "_live_autoload_attempted", False)

    client = get_models_dev()
    saved_p, saved_m = dict(client._providers), dict(client._models)
    client._providers = {"acme": ProviderInfo(id="acme", name="Acme")}
    client._models = {"acme": {"acme-1": ModelInfo(id="acme-1", name="Acme 1", provider="acme")}}
    monkeypatch.setattr(client, "ensure_cache_loaded", lambda: True)
    try:
        effective = models_mod.get_effective_models()
        # The provider from the models.dev cache is now present without any
        # explicit set_live_models() call.
        assert "acme" in effective
        assert "acme-1" in effective["acme"]
        assert models_mod._use_live_data is True
    finally:
        client._providers, client._models = saved_p, saved_m
