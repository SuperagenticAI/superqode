"""Regression tests for the Ollama local provider client parsing."""

from superqode.providers.local import OllamaClient


def _tags_payload():
    # Mirrors a real /api/tags entry. Ollama returns "families": null for
    # many models — the parser must not crash on that.
    return {
        "name": "gemma4:31b-mlx-bf16",
        "model": "gemma4:31b-mlx-bf16",
        "modified_at": "2026-06-01T12:00:00.000000000Z",
        "size": 62_000_000_000,
        "digest": "abc123",
        "details": {
            "family": "gemma",
            "families": None,  # <-- the bug trigger
            "parameter_size": "31B",
            "quantization_level": "BF16",
        },
    }


def test_parse_model_handles_null_families():
    """A model whose details.families is null must still parse (not crash)."""
    client = OllamaClient()
    model = client._parse_model(_tags_payload())
    assert model.id == "gemma4:31b-mlx-bf16"
    assert model.supports_vision is False
    # Earlier this raised TypeError, making list_models() return [] silently.


def test_supports_vision_with_null_families():
    client = OllamaClient()
    assert client._supports_vision("gemma4:31b", {"families": None}) is False
    # Real vision signal still works.
    assert client._supports_vision("x", {"families": ["clip"]}) is True
    # And name-based detection is unaffected.
    assert client._supports_vision("llava:7b", {}) is True
