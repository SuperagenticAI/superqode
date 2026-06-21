"""Tests for provider/model reference parsing helpers."""

from superqode.providers.model_specs import (
    normalize_model_for_provider,
    normalize_provider_id,
    split_hf_provider_suffix,
    split_provider_model_ref,
)


def test_split_provider_model_ref_handles_hf_shorthand_forms():
    expected = ("huggingface", "zai-org/GLM-5.2:fireworks-ai")

    for raw in (
        "hf.zai-org/GLM-5.2:fireworks-ai",
        "hf/zai-org/GLM-5.2:fireworks-ai",
        "huggingface/zai-org/GLM-5.2:fireworks-ai",
        "HF.zai-org/GLM-5.2:fireworks-ai",
    ):
        parsed = split_provider_model_ref(raw)
        assert (parsed.provider, parsed.model) == expected


def test_split_provider_model_ref_preserves_regular_provider_model_refs():
    parsed = split_provider_model_ref("openai/gpt-5.4")

    assert parsed.provider == "openai"
    assert parsed.model == "gpt-5.4"


def test_split_provider_model_ref_uses_default_provider_for_bare_models():
    parsed = split_provider_model_ref("claude-sonnet-4-6", default_provider="anthropic")

    assert parsed.provider == "anthropic"
    assert parsed.model == "claude-sonnet-4-6"


def test_normalize_huggingface_provider_and_model():
    assert normalize_provider_id("hf") == "huggingface"
    assert (
        normalize_model_for_provider("hf", "hf.zai-org/GLM-5.2:fireworks-ai")
        == "zai-org/GLM-5.2:fireworks-ai"
    )


def test_split_hf_provider_suffix_strips_hf_prefix():
    assert split_hf_provider_suffix("hf.zai-org/GLM-5.2:deepinfra") == (
        "zai-org/GLM-5.2",
        "deepinfra",
    )
