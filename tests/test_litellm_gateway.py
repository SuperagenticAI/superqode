"""Tests for LiteLLM gateway model compatibility fallbacks."""

from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


def test_openai_gpt54_fallback_candidates():
    """GPT-5.4 should fall back to the prior flagship if rollout lags."""
    gateway = LiteLLMGateway()

    assert gateway._get_model_candidates("openai", "gpt-5.4") == [
        "openai/gpt-5.4",
        "openai/gpt-5.2",
    ]


def test_openai_gpt54_pro_fallback_candidates():
    """GPT-5.4 Pro should fall back to the prior Pro tier if unavailable."""
    gateway = LiteLLMGateway()

    assert gateway._get_model_candidates("openai", "gpt-5.4-pro") == [
        "openai/gpt-5.4-pro",
        "openai/gpt-5.2-pro",
    ]


def test_openai_gpt53_codex_fallback_candidates():
    """GPT-5.3 Codex should keep the existing compatibility fallback."""
    gateway = LiteLLMGateway()

    assert gateway._get_model_candidates("openai", "gpt-5.3-codex") == [
        "openai/gpt-5.3-codex",
        "openai/gpt-5-codex",
    ]
