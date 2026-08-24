"""Regression for the LangChain provider-name mapping."""

from __future__ import annotations

import pytest

from superqode.harness.backends.deepagents import _model_spec


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        # LangChain calls the Gemini API provider "google_genai". Passing
        # SuperQode's own id through unchanged made init_chat_model fail with
        # "Unable to infer model provider", which loses the whole run before a
        # token is spent.
        ("google", "gemini-3.5-flash-lite", "google_genai:gemini-3.5-flash-lite"),
        ("gemini", "gemini-3.5-flash-lite", "google_genai:gemini-3.5-flash-lite"),
        ("vertex", "gemini-3.5-flash", "google_vertexai:gemini-3.5-flash"),
        ("mistral", "mistral-large", "mistralai:mistral-large"),
        # Providers whose names already agree must pass through untouched.
        ("openai", "gpt-4o-mini", "openai:gpt-4o-mini"),
        ("anthropic", "claude-sonnet-4", "anthropic:claude-sonnet-4"),
        # A colon inside a model name is a version tag, not a provider prefix.
        ("ollama", "qwen3.5:2b", "ollama:qwen3.5:2b"),
    ],
)
def test_model_spec_uses_langchain_provider_names(provider, model, expected):
    assert _model_spec(provider, model) == expected
