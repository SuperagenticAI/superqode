"""Tests for default configuration model recommendations and aliases."""

from superqode.config import create_default_config


def test_default_openai_recommendations_and_aliases():
    """OpenAI defaults should point at the current flagship model."""
    config = create_default_config()

    openai = config.providers["openai"]

    assert openai.recommended_models[:3] == ["gpt-5.4", "gpt-5.4-pro", "gpt-5.3-codex"]
    assert config.model_aliases["latest-gpt"] == "gpt-5.4"
