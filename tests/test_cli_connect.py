"""Tests for CLI connection argument normalization."""

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
