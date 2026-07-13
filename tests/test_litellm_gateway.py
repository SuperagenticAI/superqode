"""Tests for LiteLLM gateway model compatibility fallbacks."""

from types import SimpleNamespace

import pytest

from superqode.providers.gateway.base import GatewayResponse, Message
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


@pytest.mark.asyncio
async def test_litellm_completion_skips_optional_proxy_mcp_handler(monkeypatch):
    """Tool calls must not require FastAPI in a standard SuperQode install."""
    gateway = LiteLLMGateway()
    seen = {}

    async def fake_acompletion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(
        gateway,
        "_get_litellm",
        lambda: SimpleNamespace(acompletion=fake_acompletion),
    )

    await gateway._acompletion_with_retry(
        {
            "model": "ollama/gemma4:12b-mlx",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [{"type": "function", "function": {"name": "read_file"}}],
        }
    )

    assert seen["_skip_mcp_handler"] is True


def test_openai_gpt54_fallback_candidates():
    """GPT-5.4 should fall back to the prior flagship if rollout lags."""
    gateway = LiteLLMGateway()

    assert gateway._get_model_candidates("openai", "gpt-5.4") == [
        "openai/gpt-5.4",
        "openai/gpt-5.2",
    ]


def test_gemma_num_ctx_modern_vs_legacy():
    """Gemma 3/4 get a real context window; Gemma 1/2 stay at 8K."""
    gateway = LiteLLMGateway()

    # Modern Gemma must not be capped at the legacy 8K (cripples agentic loops).
    assert gateway._ollama_num_ctx_for("gemma4:31b-mlx-bf16") == 32768
    assert gateway._ollama_num_ctx_for("gemma3:27b-it") == 32768
    # Gemma 2 is genuinely an 8K model.
    assert gateway._ollama_num_ctx_for("gemma2:9b-it") == 8192


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


def test_huggingface_hf_prefix_routes_to_litellm_huggingface_provider():
    gateway = LiteLLMGateway()

    assert (
        gateway.get_model_string("huggingface", "hf.zai-org/GLM-5.2:fireworks-ai")
        == "huggingface/zai-org/GLM-5.2:fireworks-ai"
    )
    assert (
        gateway.get_model_string("hf", "zai-org/GLM-5.2:fireworks-ai")
        == "huggingface/zai-org/GLM-5.2:fireworks-ai"
    )


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
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
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


@pytest.mark.asyncio
async def test_ollama_stream_preserves_terminal_usage_chunk(monkeypatch):
    gateway = LiteLLMGateway()
    captured = {}

    async def stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="answer", role="assistant", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=1200,
                completion_tokens=340,
                total_tokens=1540,
            ),
        )

    async def fake_completion(kwargs):
        captured.update(kwargs)
        return stream()

    monkeypatch.setattr(gateway, "_get_litellm", lambda: object())
    monkeypatch.setattr(gateway, "_acompletion_with_retry", fake_completion)

    chunks = [
        chunk
        async for chunk in gateway.stream_completion(
            messages=[Message(role="user", content="hello")],
            model="qwen3:8b",
            provider="ollama",
        )
    ]

    assert captured["stream_options"] == {"include_usage": True}
    assert "".join(chunk.content for chunk in chunks) == "answer"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 1540


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


# ---------------------------------------------------------------------------
# Prompt caching
# ---------------------------------------------------------------------------


def _msgs(*roles_contents):
    """Helper to build LiteLLM-shaped dicts."""
    return [{"role": r, "content": c} for r, c in roles_contents]


def test_caching_marks_system_and_last_two_for_anthropic(monkeypatch):
    """The sliding-window caching pattern: system + last 2 non-system get marked.
    Intermediate user/assistant turns are left alone so the cache window
    sweeps forward with the conversation."""
    monkeypatch.delenv("SUPERQODE_DISABLE_PROMPT_CACHE", raising=False)
    gateway = LiteLLMGateway()

    msgs = _msgs(
        ("system", "you are helpful"),
        ("user", "first"),
        ("assistant", "first reply"),
        ("user", "second"),
        ("assistant", "second reply"),
    )
    out = gateway._apply_prompt_caching(msgs, provider="anthropic")

    # System message: content lifted to a list with cache_control on the last block.
    assert isinstance(out[0]["content"], list)
    assert out[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

    # Middle two messages untouched.
    assert out[1]["content"] == "first"
    assert out[2]["content"] == "first reply"

    # Last two non-system messages marked.
    assert isinstance(out[3]["content"], list)
    assert out[3]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(out[4]["content"], list)
    assert out[4]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_caching_uses_copilot_marker_for_github_copilot():
    """GitHub Copilot's API uses a distinct field name."""
    gateway = LiteLLMGateway()
    out = gateway._apply_prompt_caching(
        _msgs(("system", "S"), ("user", "U")), provider="github-copilot"
    )
    assert "copilot_cache_control" in out[0]["content"][0]
    assert "cache_control" not in out[0]["content"][0]


def test_caching_skipped_for_unsupported_provider():
    """OpenAI auto-caches without explicit markers; never add them."""
    gateway = LiteLLMGateway()
    msgs = _msgs(("system", "S"), ("user", "U"))
    out = gateway._apply_prompt_caching(msgs, provider="openai")
    assert out == msgs  # no mutation


def test_caching_disabled_via_env(monkeypatch):
    monkeypatch.setenv("SUPERQODE_DISABLE_PROMPT_CACHE", "1")
    gateway = LiteLLMGateway()
    msgs = _msgs(("system", "S"), ("user", "U"))
    out = gateway._apply_prompt_caching(msgs, provider="anthropic")
    assert out == msgs


def test_caching_is_idempotent():
    """Running through caching twice must not nest markers or duplicate."""
    gateway = LiteLLMGateway()
    msgs = _msgs(("system", "S"), ("user", "U"))
    once = gateway._apply_prompt_caching(msgs, provider="anthropic")
    twice = gateway._apply_prompt_caching(once, provider="anthropic")
    assert once == twice


def test_caching_preserves_existing_content_blocks():
    """If content is already a list of blocks (e.g. multi-part user msg with
    an image), tag only the last text block — don't clobber the structure."""
    gateway = LiteLLMGateway()
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "..."}},
                {"type": "text", "text": "describe this"},
            ],
        }
    ]
    out = gateway._apply_prompt_caching(msgs, provider="anthropic")
    assert out[0]["content"][0] == {"type": "image_url", "image_url": {"url": "..."}}
    assert out[0]["content"][1]["cache_control"] == {"type": "ephemeral"}


def test_caching_skips_empty_string_content():
    """Don't promote an empty string to a content block — would be a wire-
    format error on some providers."""
    gateway = LiteLLMGateway()
    msgs = [{"role": "user", "content": ""}]
    out = gateway._apply_prompt_caching(msgs, provider="anthropic")
    assert out[0]["content"] == ""


def test_caching_handles_empty_message_list():
    gateway = LiteLLMGateway()
    assert gateway._apply_prompt_caching([], provider="anthropic") == []


@pytest.mark.parametrize("provider", ["bedrock", "amazon-bedrock", "vertex", "openrouter"])
def test_caching_supported_provider_aliases_get_marked(provider):
    """Bedrock/Vertex host Anthropic models — same cache_control field.
    OpenRouter routes Anthropic models too."""
    gateway = LiteLLMGateway()
    msgs = _msgs(("system", "S"), ("user", "U"))
    out = gateway._apply_prompt_caching(msgs, provider=provider)
    assert "cache_control" in out[0]["content"][0]
