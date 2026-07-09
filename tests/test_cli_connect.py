"""Tests for CLI connection argument normalization."""

from superqode.commands.acp import validate_agent_environment
from superqode.commands.providers import connect_provider


def test_connect_provider_accepts_hf_shorthand(monkeypatch):
    captured = {}

    class FakeProviderManager:
        def test_connection(self, provider):
            captured["provider"] = provider
            return True, ""

    monkeypatch.setattr("superqode.providers.manager.ProviderManager", FakeProviderManager)

    assert connect_provider("hf.zai-org/GLM-5.2:fireworks-ai") == 0
    assert captured["provider"] == "huggingface"


def test_grok_subscription_agent_does_not_require_byok_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    assert validate_agent_environment({"short_name": "grok"}) == []
