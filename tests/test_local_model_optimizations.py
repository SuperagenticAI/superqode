"""Tests for Ollama/MLX/local-model harness optimizations.

These cover three optimization layers that close the gap between local-
model behavior and our cloud-provider experience:

1. Provider/model-tuned system prompts (Ollama/MLX/Qwen).
2. Request shaping (num_ctx, keep_alive, tool-temp clamp).
3. In-band tool-call extraction for models that emit tool calls as text.

The tests exercise the gateway helpers directly — no live local server
needed — so they run portably in CI.
"""

from __future__ import annotations

import json

import pytest

from superqode.agent.system_prompts import (
    LOCAL_PROMPT,
    QWEN_PROMPT,
    get_provider_prompt,
)
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------


def test_local_prompt_used_for_ollama_generic():
    """Generic Ollama model should get the plain LOCAL_PROMPT, not Qwen-tuned."""
    assert get_provider_prompt("ollama", "llama3.2:latest") == LOCAL_PROMPT


def test_qwen_prompt_used_for_ollama_qwen():
    """Qwen on Ollama should get the tag-aware variant — the model is
    sensitive to the explicit <tool_call> wording in its instruct tuning."""
    assert get_provider_prompt("ollama", "qwen2.5-coder:7b") == QWEN_PROMPT


def test_local_prompt_used_for_mlx():
    assert get_provider_prompt("mlx", "meta-llama/Llama-3.2-3B-Instruct").startswith(
        "You are a precise coding assistant running on a local model"
    )


def test_qwen_prompt_used_for_mlx_qwen():
    out = get_provider_prompt("mlx", "mlx-community/Qwen2.5-Coder-7B")
    assert out == QWEN_PROMPT


@pytest.mark.parametrize(
    "provider",
    ["ollama", "mlx", "lmstudio", "vllm", "sglang", "tgi", "llama-cpp"],
)
def test_all_local_providers_get_a_local_prompt(provider):
    """Every local provider routes through the local-prompt path —
    regressions where a provider falls through to "" silently make the
    model lose its tool-use instructions."""
    out = get_provider_prompt(provider, "any-model")
    assert "tools" in out.lower() and out != ""


def test_cloud_provider_still_returns_empty():
    """Cloud providers must not get the local prompt — they rely on
    their own provider-tuned prompt or the user's chosen SystemPromptLevel."""
    assert get_provider_prompt("anthropic", "claude-sonnet-4") == ""
    assert get_provider_prompt("openai", "gpt-5") == ""


# ---------------------------------------------------------------------------
# Request shaping — num_ctx, keep_alive, temperature clamp
# ---------------------------------------------------------------------------


def test_ollama_num_ctx_picks_family_hint():
    """Family-matched models should get their tuned context, not the 8192 floor."""
    gw = LiteLLMGateway()
    assert gw._ollama_num_ctx_for("qwen2.5-coder:7b") == 32768
    assert gw._ollama_num_ctx_for("llama3.2:3b") == 32768
    assert gw._ollama_num_ctx_for("gemma:7b") == 8192


def test_ollama_num_ctx_longest_prefix_wins():
    """``qwen2.5-coder`` must beat the shorter ``qwen`` key — otherwise
    coder-tuned models inherit the wrong context window."""
    gw = LiteLLMGateway()
    # Both keys would match this name; only the longest-key value is correct.
    assert gw._ollama_num_ctx_for("qwen2.5-coder-instruct") == 32768


def test_ollama_num_ctx_env_override_wins(monkeypatch):
    monkeypatch.setenv("SUPERQODE_OLLAMA_NUM_CTX", "65536")
    gw = LiteLLMGateway()
    assert gw._ollama_num_ctx_for("qwen2.5") == 65536


def test_ollama_num_ctx_unknown_model_falls_back_to_safe_default():
    gw = LiteLLMGateway()
    assert gw._ollama_num_ctx_for("some-exotic-model:latest") == 8192


def test_shaping_sets_keep_alive_and_num_ctx_for_ollama():
    gw = LiteLLMGateway()
    kwargs: dict = {}
    gw._apply_local_request_shaping("ollama", "qwen2.5-coder:7b", kwargs, has_tools=True)
    assert kwargs["keep_alive"] == "30m"
    assert kwargs["options"]["num_ctx"] == 32768


def test_shaping_clamps_temperature_when_tools_present():
    """High temp wrecks tool discipline on small local models. Clamp it
    when the caller is using tools, regardless of what they asked for."""
    gw = LiteLLMGateway()
    kwargs: dict = {"temperature": 0.9}
    gw._apply_local_request_shaping("ollama", "qwen2.5", kwargs, has_tools=True)
    assert kwargs["temperature"] == 0.2


def test_shaping_does_not_clamp_temperature_without_tools():
    """Free-form chat without tools should keep the user's temperature."""
    gw = LiteLLMGateway()
    kwargs: dict = {"temperature": 0.8}
    gw._apply_local_request_shaping("ollama", "qwen2.5", kwargs, has_tools=False)
    assert kwargs["temperature"] == 0.8


def test_shaping_skips_cloud_providers():
    gw = LiteLLMGateway()
    kwargs: dict = {"temperature": 0.9}
    gw._apply_local_request_shaping("anthropic", "claude-sonnet-4", kwargs, has_tools=True)
    assert kwargs == {"temperature": 0.9}  # untouched


def test_shaping_respects_disable_env(monkeypatch):
    monkeypatch.setenv("SUPERQODE_DISABLE_LOCAL_SHAPING", "1")
    gw = LiteLLMGateway()
    kwargs: dict = {}
    gw._apply_local_request_shaping("ollama", "qwen2.5", kwargs, has_tools=True)
    assert kwargs == {}


def test_shaping_preserves_existing_options():
    """Caller-supplied Ollama options must not be obliterated — we only
    fill in defaults, never overwrite."""
    gw = LiteLLMGateway()
    kwargs: dict = {"options": {"num_ctx": 65536, "num_gpu": 1}}
    gw._apply_local_request_shaping("ollama", "qwen2.5", kwargs, has_tools=False)
    assert kwargs["options"]["num_ctx"] == 65536  # caller wins
    assert kwargs["options"]["num_gpu"] == 1


def test_shaping_keep_alive_env_override(monkeypatch):
    monkeypatch.setenv("SUPERQODE_OLLAMA_KEEP_ALIVE", "2h")
    gw = LiteLLMGateway()
    kwargs: dict = {}
    gw._apply_local_request_shaping("ollama", "qwen2.5", kwargs, has_tools=False)
    assert kwargs["keep_alive"] == "2h"


# ---------------------------------------------------------------------------
# In-band tool-call extraction
# ---------------------------------------------------------------------------


def test_extract_qwen_style_tool_call_tag():
    """Qwen 2.5 emits <tool_call>{...}</tool_call>. Must promote to
    proper tool_calls and strip from content."""
    gw = LiteLLMGateway()
    content = (
        "I will read the README.\n"
        '<tool_call>{"name": "read_file", "arguments": {"path": "README.md"}}</tool_call>'
    )
    stripped, calls = gw._extract_inline_tool_calls(content)
    assert calls is not None
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "read_file"
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "README.md"}
    assert "<tool_call>" not in stripped


def test_extract_code_fenced_tool_call():
    """Some Llama fine-tunes emit ```tool_call ... ``` fences."""
    gw = LiteLLMGateway()
    content = (
        'Let me check.\n```tool_call\n{"name": "list_directory", "arguments": {"path": "."}}\n```'
    )
    _, calls = gw._extract_inline_tool_calls(content)
    assert calls is not None
    assert calls[0]["function"]["name"] == "list_directory"


def test_extract_bare_llama3_function_call():
    """Llama 3 emits a bare JSON object with name + parameters on its
    own line. The parameters→arguments mapping is the part that's easy
    to miss."""
    gw = LiteLLMGateway()
    content = '{"name": "grep", "parameters": {"pattern": "TODO"}}'
    _, calls = gw._extract_inline_tool_calls(content)
    assert calls is not None
    assert calls[0]["function"]["name"] == "grep"
    assert json.loads(calls[0]["function"]["arguments"]) == {"pattern": "TODO"}


def test_extract_multiple_tool_calls_in_one_response():
    gw = LiteLLMGateway()
    content = (
        '<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>\n'
        '<tool_call>{"name": "read_file", "arguments": {"path": "b.py"}}</tool_call>'
    )
    _, calls = gw._extract_inline_tool_calls(content)
    assert calls is not None
    assert len(calls) == 2
    assert [c["function"]["name"] for c in calls] == ["read_file", "read_file"]
    assert {c["id"] for c in calls} == {"extracted_0", "extracted_1"}


def test_extract_returns_none_on_plain_text():
    """Plain prose with no tool patterns must not produce phantom calls."""
    gw = LiteLLMGateway()
    content = "Here is some explanation with no tools at all."
    stripped, calls = gw._extract_inline_tool_calls(content)
    assert calls is None
    assert stripped == content


def test_extract_returns_none_on_malformed_json():
    """A <tool_call> tag with non-JSON body should not crash and must
    not produce a tool call — better to skip than to fabricate args."""
    gw = LiteLLMGateway()
    content = "<tool_call>not valid json</tool_call>"
    _, calls = gw._extract_inline_tool_calls(content)
    assert calls is None


def test_extract_skips_objects_without_name():
    """A JSON blob missing the ``name`` field isn't a tool call —
    ignore it instead of emitting a call with empty name."""
    gw = LiteLLMGateway()
    content = '<tool_call>{"arguments": {"x": 1}}</tool_call>'
    _, calls = gw._extract_inline_tool_calls(content)
    assert calls is None


def test_extract_handles_empty_content():
    gw = LiteLLMGateway()
    stripped, calls = gw._extract_inline_tool_calls("")
    assert calls is None
    assert stripped == ""


def test_extract_function_name_field_variant():
    """Real-world: qwen3:8b emits ``function_name`` instead of ``name``.
    Caught by the live smoke probe — keep the regression here."""
    gw = LiteLLMGateway()
    content = '{"function_name": "read_file", "arguments": {"path": "pyproject.toml"}}'
    _, calls = gw._extract_inline_tool_calls(content)
    assert calls is not None
    assert calls[0]["function"]["name"] == "read_file"


# ---------------------------------------------------------------------------
# LiteLLM model routing — Ollama tool support requires ollama_chat/
# ---------------------------------------------------------------------------


def test_ollama_routes_to_chat_endpoint():
    """LiteLLM's ``ollama/`` prefix hits /api/generate which silently
    drops tool calls. Tool-using agents only work on /api/chat, which
    LiteLLM exposes as ``ollama_chat/``. Caught by a live probe against
    gpt-oss:20b that returned empty content + zero tool_calls until we
    swapped the prefix."""
    gw = LiteLLMGateway()
    assert gw.get_model_string("ollama", "qwen3:8b") == "ollama_chat/qwen3:8b"
    assert gw.get_model_string("ollama", "gpt-oss:20b") == "ollama_chat/gpt-oss:20b"


def test_ollama_strips_existing_ollama_prefix():
    """If a caller pre-qualified with the legacy prefix, rewrite it
    rather than producing ``ollama_chat/ollama/...``."""
    gw = LiteLLMGateway()
    assert gw.get_model_string("ollama", "ollama/qwen3:8b") == "ollama_chat/qwen3:8b"


def test_ollama_chat_prefix_passes_through():
    gw = LiteLLMGateway()
    assert gw.get_model_string("ollama", "ollama_chat/qwen3:8b") == "ollama_chat/qwen3:8b"


# ---------------------------------------------------------------------------
# MLX path — mocked, no live server required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mlx_chat_clamps_temperature_and_extracts_inline_tool_calls(monkeypatch):
    """Live coverage for the MLX direct path: temperature clamp fires
    when tools are present, and a Gemma-style ``<tool_call>`` block in
    content is rescued into proper ``tool_calls`` so the agent loop
    can act on it.

    Mocked at the MLXClient boundary so this is fast and portable —
    we don't need a live 8081 server to verify the gateway behavior."""
    import superqode.providers.local.mlx as mlx_mod
    from superqode.providers.gateway.base import Message, ToolDefinition

    captured: dict = {}

    async def fake_async_request(self, method, endpoint, data, timeout=120.0):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["data"] = data
        # Simulate Gemma 4 on MLX: emits the tool call as text rather
        # than via the native tool_calls channel.
        return {
            "model": "SuperagenticAI/gemma-4-31b-it-4bit-mlx",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": (
                            "Let me read it.\n"
                            '<tool_call>{"name": "read_file", "arguments": {"path": "pyproject.toml"}}</tool_call>'
                        ),
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

    monkeypatch.setattr(mlx_mod.MLXClient, "_async_request", fake_async_request)

    gw = LiteLLMGateway()
    resp = await gw.chat_completion(
        messages=[Message(role="user", content="What does pyproject.toml contain?")],
        model="SuperagenticAI/gemma-4-31b-it-4bit-mlx",
        provider="mlx",
        tools=[
            ToolDefinition(
                name="read_file",
                description="Read a file",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            )
        ],
        temperature=0.9,
    )

    # Temperature was clamped down from 0.9 to ≤0.2 before the request hit MLX.
    assert captured["data"]["temperature"] == 0.2
    # The inline <tool_call> tag was lifted into proper tool_calls.
    assert resp.tool_calls is not None
    assert resp.tool_calls[0]["function"]["name"] == "read_file"
    args = json.loads(resp.tool_calls[0]["function"]["arguments"])
    assert args == {"path": "pyproject.toml"}
    # Tag was stripped from the visible content so the user doesn't see it twice.
    assert "<tool_call>" not in (resp.content or "")


@pytest.mark.asyncio
async def test_mlx_chat_native_tool_calls_are_normalized(monkeypatch):
    """When MLX *does* return native OpenAI-shaped tool_calls (some
    models do, e.g. Qwen with the right chat template), they should
    pass through normalization rather than being replaced by the
    inline-extractor's empty result."""
    import superqode.providers.local.mlx as mlx_mod
    from superqode.providers.gateway.base import Message

    async def fake_async_request(self, method, endpoint, data, timeout=120.0):
        return {
            "model": "qwen-mlx",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": '{"path": "x"}'},
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(mlx_mod.MLXClient, "_async_request", fake_async_request)

    gw = LiteLLMGateway()
    resp = await gw.chat_completion(
        messages=[Message(role="user", content="hi")],
        model="qwen-mlx",
        provider="mlx",
    )
    assert resp.tool_calls is not None and len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["function"]["name"] == "read_file"


@pytest.mark.asyncio
async def test_mlx_stream_extracts_inline_tool_calls(monkeypatch):
    """MLX streaming path (which actually does a non-streaming call
    under the hood for KV-cache safety) must apply the same tool-call
    rescue as the non-streaming path."""
    import superqode.providers.local.mlx as mlx_mod
    from superqode.providers.gateway.base import Message

    async def fake_async_request(self, method, endpoint, data, timeout=120.0):
        return {
            "model": "gemma-mlx",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": '<tool_call>{"name": "list_directory", "arguments": {"path": "."}}</tool_call>',
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(mlx_mod.MLXClient, "_async_request", fake_async_request)

    gw = LiteLLMGateway()
    chunks = [
        c
        async for c in gw.stream_completion(
            messages=[Message(role="user", content="list files")],
            model="gemma-mlx",
            provider="mlx",
        )
    ]
    assert chunks
    final = chunks[-1]
    # Stream terminator flipped to tool_calls so the loop dispatches.
    assert final.finish_reason == "tool_calls"
    assert final.tool_calls is not None
    assert final.tool_calls[0]["function"]["name"] == "list_directory"


def test_extract_arguments_string_form_preserved():
    """If a model emits ``arguments`` as a JSON string (not an object),
    we should still surface it through — agent loops json.loads() it
    back so a string is fine."""
    gw = LiteLLMGateway()
    content = '<tool_call>{"name": "read_file", "arguments": "{\\"path\\": \\"x\\"}"}</tool_call>'
    _, calls = gw._extract_inline_tool_calls(content)
    assert calls is not None
    # We forward whatever the model produced; loop's parser handles it.
    assert calls[0]["function"]["name"] == "read_file"
