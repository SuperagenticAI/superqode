"""Tests for default configuration model recommendations and aliases."""

from superqode.config import create_default_config, resolve_model_spec


def test_default_openai_recommendations_and_aliases():
    """OpenAI defaults should point at the current flagship model."""
    config = create_default_config()

    openai = config.providers["openai"]

    assert openai.recommended_models[:3] == ["gpt-5.4", "gpt-5.4-pro", "gpt-5.3-codex"]
    assert config.model_aliases["latest-gpt"] == "gpt-5.4"


def test_default_google_recommendations_and_aliases():
    """Google BYOK defaults should track current models.dev Gemini IDs."""
    config = create_default_config()

    google = config.providers["google"]

    assert google.recommended_models[:2] == ["gemini-3.1-pro-preview", "gemini-flash-latest"]
    assert config.model_aliases["latest-gemini"] == "gemini-3.1-pro-preview"
    assert config.model_aliases["latest-gemini-flash"] == "gemini-flash-latest"


def test_default_huggingface_glm52_fireworks_route():
    """HF defaults should expose GLM-5.2 routes across available providers."""
    config = create_default_config()

    hf = config.providers["huggingface"]

    assert hf.recommended_models[:5] == [
        "zai-org/GLM-5.2:fireworks-ai",
        "zai-org/GLM-5.2:together",
        "zai-org/GLM-5.2:novita",
        "zai-org/GLM-5.2:zai-org",
        "zai-org/GLM-5.2:deepinfra",
    ]
    assert config.model_aliases["glm52"] == "hf.zai-org/GLM-5.2:fireworks-ai"
    assert resolve_model_spec("glm52", config) == (
        "huggingface",
        "zai-org/GLM-5.2:fireworks-ai",
    )
    assert resolve_model_spec("glm52-hf-together", config) == (
        "huggingface",
        "zai-org/GLM-5.2:together",
    )
    assert resolve_model_spec("glm52-hf-novita", config) == (
        "huggingface",
        "zai-org/GLM-5.2:novita",
    )


def test_huggingface_provider_suffix_specs_do_not_resolve_as_ollama():
    config = create_default_config()

    assert resolve_model_spec("hf.zai-org/GLM-5.2:fireworks-ai", config) == (
        "huggingface",
        "zai-org/GLM-5.2:fireworks-ai",
    )
    assert resolve_model_spec("huggingface/zai-org/GLM-5.2:fireworks-ai", config) == (
        "huggingface",
        "zai-org/GLM-5.2:fireworks-ai",
    )
    assert resolve_model_spec("hf/zai-org/GLM-5.2:fireworks-ai", config) == (
        "huggingface",
        "zai-org/GLM-5.2:fireworks-ai",
    )
