"""Tests for the model catalog browser (CLI + TUI shared logic)."""

from __future__ import annotations

import pytest

from superqode.providers import catalog
from superqode.providers.models import ModelCapability, ModelInfo
from superqode.providers.models_dev import ProviderInfo, get_models_dev


def _model(provider, mid, **kw):
    return ModelInfo(
        id=mid,
        name=kw.get("name", mid),
        provider=provider,
        **{k: v for k, v in kw.items() if k != "name"},
    )


@pytest.fixture
def sample_models():
    return [
        _model(
            "anthropic",
            "claude-sonnet",
            input_price=3.0,
            output_price=15.0,
            context_window=200000,
            capabilities=[ModelCapability.TOOLS, ModelCapability.VISION],
        ),
        _model(
            "deepinfra",
            "Qwen2.5-Coder-32B",
            input_price=0.1,
            output_price=0.3,
            context_window=128000,
            capabilities=[ModelCapability.TOOLS, ModelCapability.CODE],
        ),
        _model(
            "cohere",
            "aya-free",
            input_price=0.0,
            output_price=0.0,
            context_window=8000,
            capabilities=[],
        ),
        _model(
            "baseten",
            "llama-70b",
            input_price=0.5,
            output_price=0.5,
            context_window=128000,
            capabilities=[ModelCapability.TOOLS],
        ),
    ]


@pytest.fixture
def fake_catalog(monkeypatch, sample_models):
    """Point the models.dev singleton at synthetic data (no network)."""
    client = get_models_dev()
    saved_p = dict(client._providers)
    saved_m = dict(client._models)
    client._providers = {
        "anthropic": ProviderInfo(id="anthropic", name="Anthropic", env_vars=["ANTHROPIC_API_KEY"]),
        "deepinfra": ProviderInfo(id="deepinfra", name="DeepInfra", env_vars=["DEEPINFRA_API_KEY"]),
        "cohere": ProviderInfo(id="cohere", name="Cohere", env_vars=["COHERE_API_KEY"]),
        "baseten": ProviderInfo(
            id="baseten",
            name="Baseten",
            env_vars=["BASETEN_API_KEY"],
            api_url="https://inference.baseten.co/v1",
        ),
    }
    client._models = {}
    for m in sample_models:
        client._models.setdefault(m.provider, {})[m.id] = m
    monkeypatch.setattr(client, "ensure_cache_loaded", lambda: True)
    try:
        yield client
    finally:
        client._providers = saved_p
        client._models = saved_m


def test_load_cached_returns_all(fake_catalog):
    models = catalog.load_models_catalog_cached()
    assert len(models) == 4


def test_filter_by_search(fake_catalog, sample_models):
    out = catalog.filter_models(sample_models, search="coder")
    assert [m.id for m in out] == ["Qwen2.5-Coder-32B"]


def test_filter_by_capability(fake_catalog, sample_models):
    out = catalog.filter_models(sample_models, capability=ModelCapability.CODE)
    assert all(ModelCapability.CODE in m.capabilities for m in out)
    assert len(out) == 1


def test_filter_free(fake_catalog, sample_models):
    out = catalog.filter_models(sample_models, free=True)
    assert [m.id for m in out] == ["aya-free"]


def test_filter_max_price(fake_catalog, sample_models):
    out = catalog.filter_models(sample_models, max_input_price=0.4)
    ids = {m.id for m in out}
    assert "Qwen2.5-Coder-32B" in ids and "aya-free" in ids
    assert "claude-sonnet" not in ids


def test_filter_curated_only(fake_catalog, sample_models):
    # anthropic + cohere are curated; deepinfra/baseten are not.
    out = catalog.filter_models(sample_models, curated_only=True)
    providers = {m.provider for m in out}
    assert "anthropic" in providers
    assert "deepinfra" not in providers


def test_sort_price(fake_catalog, sample_models):
    out = catalog.filter_models(sample_models, sort="price")
    prices = [m.input_price for m in out]
    assert prices == sorted(prices)


def test_sort_provider_curated_first(fake_catalog, sample_models):
    out = catalog.filter_models(sample_models, sort="provider")
    # First entries should be curated providers.
    from superqode.providers.dynamic import is_curated_provider

    assert is_curated_provider(out[0].provider)


def test_parse_capability_aliases():
    assert catalog.parse_capability("coder") == ModelCapability.CODE
    assert catalog.parse_capability("image") == ModelCapability.VISION
    assert catalog.parse_capability("bogus") is None
    assert catalog.parse_capability(None) is None


def test_render_models_table_marks_curated(fake_catalog, sample_models):
    text = catalog.render_models_table(sample_models, total=len(sample_models))
    assert "PROVIDER" in text and "CTX" in text
    assert "*anthropic" in text  # curated marker
    assert "deepinfra" in text
    assert "200k" in text  # context formatting
    assert "free/free" in text  # free pricing


def test_render_providers_table(fake_catalog):
    text = catalog.render_providers_table()
    assert "PROVIDER" in text and "API KEY ENV" in text
    assert "*anthropic" in text
    assert "DEEPINFRA_API_KEY" in text


def test_caps_str_drops_streaming(fake_catalog):
    m = _model("x", "y", capabilities=[ModelCapability.STREAMING, ModelCapability.TOOLS])
    assert catalog.caps_str(m) == "tools"
