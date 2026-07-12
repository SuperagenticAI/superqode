"""First-party Z.AI general-API provider coverage."""

from __future__ import annotations

import os

import pytest
from click.testing import CliRunner

from superqode.commands.connect import connect
from superqode.providers.catalog import filter_models, render_models_table
from superqode.providers.gateway.base import Message, ToolDefinition
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway
from superqode.providers.models import get_model_info
from superqode.providers.registry import PROVIDERS


def test_zai_registry_uses_general_api_only():
    provider = PROVIDERS["zai"]

    assert provider.dynamic is True
    assert provider.litellm_prefix == "openai/"
    assert provider.env_vars == ["ZAI_API_KEY"]
    assert provider.default_base_url == "https://api.z.ai/api/paas/v4"
    assert "/coding/" not in provider.default_base_url
    assert provider.example_models[0] == "glm-5.2"


def test_zai_glm52_model_metadata_does_not_claim_unknown_price_is_free():
    model = get_model_info("zai", "glm-5.2")

    assert model is not None
    assert model.context_window == 1_000_000
    assert model.max_output == 131_072
    assert model.pricing_known is False
    assert model.price_display == "Unknown"
    assert model.supports_tools is True
    assert model.supports_reasoning is True
    assert filter_models([model], free=True) == []
    assert "?/?" in render_models_table([model])


def test_zai_reasoning_mapping():
    gateway = LiteLLMGateway()

    assert gateway._resolve_reasoning_effort("zai", "glm-5.2", "max") == {
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "max",
    }
    assert gateway._resolve_reasoning_effort("zai", "glm-5.2", "off") == {
        "extra_body": {"thinking": {"type": "disabled"}},
        "reasoning_effort": "none",
    }
    assert gateway._resolve_reasoning_effort("zai", "glm-5.1", "high") == {
        "extra_body": {"thinking": {"type": "enabled"}}
    }


def test_zai_stream_tool_shaping_preserves_thinking_config():
    request = {"extra_body": {"thinking": {"type": "enabled"}}}

    LiteLLMGateway._apply_zai_stream_shaping("zai", request, has_tools=True)

    assert request["extra_body"] == {
        "thinking": {"type": "enabled"},
        "tool_stream": True,
    }


@pytest.mark.asyncio
async def test_zai_request_routes_to_general_openai_compatible_api(monkeypatch):
    gateway = LiteLLMGateway()
    captured: dict = {}

    class Choice:
        finish_reason = "stop"

        class message:
            role = "assistant"
            content = "ok"
            reasoning_content = "checked the repository"
            tool_calls = None

    class Response:
        choices = [Choice()]
        model = "glm-5.2"
        usage = type("Usage", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})()
        _hidden_params = {}

    class FakeLiteLLM:
        AuthenticationError = type("AuthenticationError", (Exception,), {})
        RateLimitError = type("RateLimitError", (Exception,), {})
        NotFoundError = type("NotFoundError", (Exception,), {})
        BadRequestError = type("BadRequestError", (Exception,), {})

        async def acompletion(self, **kwargs):
            captured.update(kwargs)
            return Response()

    monkeypatch.setenv("ZAI_API_KEY", "zai-test-key")
    monkeypatch.delenv("ZAI_API_BASE", raising=False)
    monkeypatch.setattr(gateway, "_get_litellm", lambda: FakeLiteLLM())

    response = await gateway.chat_completion(
        messages=[Message(role="user", content="inspect this project")],
        model="glm-5.2",
        provider="zai",
        reasoning_effort="max",
        tools=[
            ToolDefinition(
                name="read_file",
                description="Read a file",
                parameters={"type": "object", "properties": {}},
            )
        ],
    )

    assert captured["model"] == "openai/glm-5.2"
    assert captured["api_base"] == "https://api.z.ai/api/paas/v4"
    assert captured["api_key"] == "zai-test-key"
    assert captured["extra_body"] == {"thinking": {"type": "enabled"}}
    assert captured["reasoning_effort"] == "max"
    assert captured["tools"][0]["function"]["name"] == "read_file"
    assert response.thinking_content == "checked the repository"


def test_connect_zai_cli_routes_to_provider(monkeypatch):
    captured = {}

    def fake_connect_provider(provider, model=None):
        captured.update(provider=provider, model=model)
        return 0

    monkeypatch.setattr(
        "superqode.commands.providers.connect_provider",
        fake_connect_provider,
    )

    result = CliRunner().invoke(connect, ["zai", "glm-5.2"])

    assert result.exit_code == 0
    assert captured == {"provider": "zai", "model": "glm-5.2"}


_LIVE_ZAI = os.environ.get("SUPERQODE_LIVE_ZAI") == "1" and bool(os.environ.get("ZAI_API_KEY"))


@pytest.mark.skipif(
    not _LIVE_ZAI,
    reason="set SUPERQODE_LIVE_ZAI=1 and ZAI_API_KEY to run the paid live smoke test",
)
@pytest.mark.asyncio
async def test_zai_live_general_api_smoke():
    """Opt-in paid smoke test; never uses the restricted Coding Plan endpoint."""
    gateway = LiteLLMGateway(timeout=60)

    response = await gateway.chat_completion(
        messages=[Message(role="user", content="Reply with exactly: ok")],
        model=os.environ.get("SUPERQODE_LIVE_ZAI_MODEL", "glm-5.2"),
        provider="zai",
        max_tokens=16,
        reasoning_effort="off",
    )

    assert response.content.strip()
    assert response.provider == "zai"
