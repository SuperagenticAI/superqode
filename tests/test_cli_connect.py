"""Tests for CLI connection argument normalization."""

from superqode.commands.acp import validate_agent_environment
from superqode.commands.providers import connect_provider
from superqode.providers.models_dev import ProviderInfo, get_models_dev


def test_connect_provider_accepts_hf_shorthand(monkeypatch):
    captured = {}

    class FakeProviderManager:
        def test_connection(self, provider, model=None):
            captured["provider"] = provider
            captured["model"] = model
            return True, ""

    monkeypatch.setattr("superqode.providers.manager.ProviderManager", FakeProviderManager)

    assert connect_provider("hf.zai-org/GLM-5.2:fireworks-ai") == 0
    assert captured["provider"] == "huggingface"
    assert captured["model"] == "zai-org/GLM-5.2:fireworks-ai"


def test_connect_provider_accepts_models_dev_provider(monkeypatch):
    captured = {}
    client = get_models_dev()
    saved_providers = dict(client._providers)

    class FakeProviderManager:
        def test_connection(self, provider, model=None):
            captured["provider"] = provider
            captured["model"] = model
            return True, ""

    try:
        client._providers = {
            "meta": ProviderInfo(
                id="meta",
                name="Meta",
                env_vars=["META_MODEL_API_KEY"],
                api_url="https://api.meta.ai/v1",
            )
        }
        monkeypatch.setattr(client, "ensure_cache_loaded", lambda: True)
        monkeypatch.setattr("superqode.providers.manager.ProviderManager", FakeProviderManager)

        assert connect_provider("meta", "muse-spark-1.1") == 0
        assert captured == {"provider": "meta", "model": "muse-spark-1.1"}
    finally:
        client._providers = saved_providers


def test_grok_subscription_agent_does_not_require_byok_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    assert validate_agent_environment({"short_name": "grok"}) == []
