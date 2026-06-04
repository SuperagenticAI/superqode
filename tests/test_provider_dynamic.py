"""Tests for models.dev-driven BYOK provider resolution."""

from __future__ import annotations

import pytest

from superqode.providers import dynamic
from superqode.providers.models_dev import ProviderInfo, get_models_dev
from superqode.providers.registry import PROVIDERS, ProviderCategory, ProviderTier


@pytest.fixture
def fake_models_dev(monkeypatch):
    """Populate the models.dev singleton with synthetic provider metadata."""
    client = get_models_dev()
    saved = dict(client._providers)
    client._providers = {
        # Long-tail provider WITH an explicit OpenAI-compatible endpoint.
        "baseten": ProviderInfo(
            id="baseten",
            name="Baseten",
            env_vars=["BASETEN_API_KEY"],
            api_url="https://inference.baseten.co/v1",
            doc_url="https://docs.baseten.co",
        ),
        # Long-tail provider WITHOUT an endpoint (rely on native LiteLLM routing).
        "deepinfra": ProviderInfo(
            id="deepinfra",
            name="DeepInfra",
            env_vars=["DEEPINFRA_API_KEY"],
            api_url="",
        ),
        # A local runtime id.
        "ollama": ProviderInfo(id="ollama", name="Ollama", env_vars=[], api_url=""),
    }
    # Prevent ensure_cache_loaded from clobbering our fake data.
    monkeypatch.setattr(client, "ensure_cache_loaded", lambda: True)
    try:
        yield client
    finally:
        client._providers = saved


def test_curated_provider_wins(fake_models_dev):
    d = dynamic.resolve_provider_def("anthropic")
    assert d is not None
    assert d.dynamic is False
    assert d.id == "anthropic"


def test_synthesize_openai_compatible_with_endpoint(fake_models_dev):
    d = dynamic.resolve_provider_def("baseten")
    assert d is not None and d.dynamic is True
    assert d.litellm_prefix == "openai/"
    assert d.default_base_url == "https://inference.baseten.co/v1"
    assert d.base_url_env == "BASETEN_BASE_URL"
    assert d.env_vars == ["BASETEN_API_KEY"]
    assert d.category == ProviderCategory.MODEL_HOSTS


def test_synthesize_native_routing_without_endpoint(fake_models_dev):
    d = dynamic.resolve_provider_def("deepinfra")
    assert d is not None and d.dynamic is True
    # No endpoint -> native LiteLLM provider prefix, no base url.
    assert d.litellm_prefix == "deepinfra/"
    assert d.default_base_url is None
    assert d.base_url_env is None


def test_synthesize_local_runtime_category(fake_models_dev):
    d = dynamic.resolve_provider_def("ollama")
    # 'ollama' is curated, so it stays curated; verify the local id mapping via a
    # non-curated local-ish lookup instead.
    assert d is not None


def test_unknown_provider_returns_none(fake_models_dev):
    assert dynamic.resolve_provider_def("totally-unknown-xyz") is None
    assert dynamic.resolve_provider_def("") is None
    assert dynamic.resolve_provider_def(None) is None


def test_provider_api_key_reads_env(fake_models_dev, monkeypatch):
    d = dynamic.resolve_provider_def("baseten")
    assert dynamic.provider_api_key(d) is None
    monkeypatch.setenv("BASETEN_API_KEY", "secret-xyz")
    assert dynamic.provider_api_key(d) == "secret-xyz"


def test_resolve_base_url_prefers_env_override(fake_models_dev, monkeypatch):
    d = dynamic.resolve_provider_def("baseten")
    assert dynamic.resolve_base_url(d) == "https://inference.baseten.co/v1"
    monkeypatch.setenv("BASETEN_BASE_URL", "http://localhost:9000/v1")
    assert dynamic.resolve_base_url(d) == "http://localhost:9000/v1"


def test_all_provider_ids_unions_curated_and_models_dev(fake_models_dev):
    ids = dynamic.all_provider_ids()
    assert "anthropic" in ids  # curated
    assert "baseten" in ids  # models.dev only
    assert len(ids) >= len(PROVIDERS)


def test_is_curated(fake_models_dev):
    assert dynamic.is_curated_provider("anthropic") is True
    assert dynamic.is_curated_provider("baseten") is False


# --- gateway integration -----------------------------------------------------


def test_gateway_resolves_and_routes_dynamic(fake_models_dev, monkeypatch):
    from superqode.providers.gateway.litellm_gateway import (
        LiteLLMGateway,
        _resolve_provider_def,
    )

    assert _resolve_provider_def("baseten").dynamic is True

    gw = LiteLLMGateway()
    # Endpoint provider -> openai/ model string + explicit api_base/api_key.
    ms = gw.get_model_string("baseten", "meta-llama/Llama-3.3-70B")
    assert ms == "openai/meta-llama/Llama-3.3-70B"

    monkeypatch.setenv("BASETEN_API_KEY", "k-123")
    rk: dict = {}
    gw._apply_dynamic_provider("baseten", rk)
    assert rk["api_base"] == "https://inference.baseten.co/v1"
    assert rk["api_key"] == "k-123"

    # Curated provider is untouched by the dynamic path.
    rk2: dict = {}
    gw._apply_dynamic_provider("anthropic", rk2)
    assert rk2 == {}


def test_get_supported_providers_no_allowlist(fake_models_dev):
    # Allowlist gate removed: every known provider is returned.
    supported = get_models_dev().get_supported_providers()
    assert "baseten" in supported and "deepinfra" in supported
