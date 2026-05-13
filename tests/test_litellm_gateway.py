"""Tests for LiteLLM gateway model compatibility fallbacks."""

import pytest

from superqode.providers.gateway.base import GatewayResponse, Message
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


@pytest.mark.asyncio
async def test_ds4_uses_direct_local_gateway(monkeypatch):
    """DS4 should bypass LiteLLM and call the local OpenAI-compatible endpoint directly."""
    gateway = LiteLLMGateway()
    seen = {}

    async def fake_ds4_chat_completion(
        messages, model, temperature=None, max_tokens=None, tools=None, tool_choice=None, **kwargs
    ):
        seen["messages"] = messages
        seen["model"] = model
        return GatewayResponse(content="ok", provider="ds4", model=model)

    def fail_litellm():
        raise AssertionError("DS4 should not load LiteLLM")

    monkeypatch.setattr(gateway, "_ds4_chat_completion", fake_ds4_chat_completion)
    monkeypatch.setattr(gateway, "_get_litellm", fail_litellm)

    response = await gateway.chat_completion(
        messages=[Message(role="user", content="summarize README")],
        model="deepseek-v4-flash",
        provider="ds4",
    )

    assert response.content == "ok"
    assert seen["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_ds4_streaming_uses_direct_local_gateway(monkeypatch):
    """DS4 streaming should also bypass LiteLLM."""
    gateway = LiteLLMGateway()

    async def fake_ds4_chat_completion(
        messages, model, temperature=None, max_tokens=None, tools=None, tool_choice=None, **kwargs
    ):
        return GatewayResponse(
            content="streamed ok",
            role="assistant",
            provider="ds4",
            model=model,
            tool_calls=[{"id": "call-1", "function": {"name": "read_file", "arguments": "{}"}}],
        )

    def fail_litellm():
        raise AssertionError("DS4 streaming should not load LiteLLM")

    monkeypatch.setattr(gateway, "_ds4_chat_completion", fake_ds4_chat_completion)
    monkeypatch.setattr(gateway, "_get_litellm", fail_litellm)

    chunks = [
        chunk
        async for chunk in gateway.stream_completion(
            messages=[Message(role="user", content="what is in pyproject.toml")],
            model="deepseek-v4-flash",
            provider="ds4",
        )
    ]

    assert len(chunks) == 1
    assert chunks[0].content == "streamed ok"
    assert chunks[0].tool_calls
