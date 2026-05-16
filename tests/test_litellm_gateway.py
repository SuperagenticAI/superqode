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
    """DS4 must bypass LiteLLM and call the local /v1/messages endpoint directly."""
    gateway = LiteLLMGateway()
    seen = {}

    async def fake_ds4_messages_completion(
        messages, model, temperature=None, max_tokens=None, tools=None, **kwargs
    ):
        seen["messages"] = messages
        seen["model"] = model
        return GatewayResponse(content="ok", provider="ds4", model=model)

    def fail_litellm():
        raise AssertionError("DS4 should not load LiteLLM")

    monkeypatch.setattr(gateway, "_ds4_messages_completion", fake_ds4_messages_completion)
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
    """DS4 streaming must bypass LiteLLM and use the /v1/messages SSE endpoint."""
    gateway = LiteLLMGateway()

    async def fake_ds4_messages_stream(
        messages, model, temperature=None, max_tokens=None, tools=None, **kwargs
    ):
        from superqode.providers.gateway.base import StreamChunk

        yield StreamChunk(content="streamed ", role="assistant")
        yield StreamChunk(content="ok", role="assistant")
        yield StreamChunk(
            content="",
            role="assistant",
            finish_reason="tool_use",
            tool_calls=[
                {"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
            ],
        )

    def fail_litellm():
        raise AssertionError("DS4 streaming should not load LiteLLM")

    monkeypatch.setattr(gateway, "_ds4_messages_stream", fake_ds4_messages_stream)
    monkeypatch.setattr(gateway, "_get_litellm", fail_litellm)

    chunks = [
        chunk
        async for chunk in gateway.stream_completion(
            messages=[Message(role="user", content="what is in pyproject.toml")],
            model="deepseek-v4-flash",
            provider="ds4",
        )
    ]

    assert "".join(c.content for c in chunks) == "streamed ok"
    assert chunks[-1].tool_calls
    assert chunks[-1].finish_reason == "tool_use"


def test_ds4_thinking_default_omits_field(monkeypatch):
    """Unset env returns None so DS4's own default thinking regime applies."""
    monkeypatch.delenv("SUPERQODE_DS4_THINKING", raising=False)
    gateway = LiteLLMGateway()
    assert gateway._ds4_thinking_config() is None


def test_ds4_thinking_off_disables_reasoning(monkeypatch):
    monkeypatch.setenv("SUPERQODE_DS4_THINKING", "off")
    gateway = LiteLLMGateway()
    assert gateway._ds4_thinking_config() == {"type": "disabled"}


@pytest.mark.parametrize(
    "level,budget",
    [("low", 1024), ("medium", 4096), ("high", 16000), ("max", 31999)],
)
def test_ds4_thinking_levels_set_budget(monkeypatch, level, budget):
    monkeypatch.setenv("SUPERQODE_DS4_THINKING", level)
    gateway = LiteLLMGateway()
    assert gateway._ds4_thinking_config() == {
        "type": "enabled",
        "budget_tokens": budget,
    }


def test_ds4_thinking_unknown_value_falls_back_to_default(monkeypatch):
    """Garbage env values fall back to None rather than a guessed budget."""
    monkeypatch.setenv("SUPERQODE_DS4_THINKING", "ultraturbo")
    gateway = LiteLLMGateway()
    assert gateway._ds4_thinking_config() is None
