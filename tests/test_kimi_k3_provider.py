"""First-party Moonshot Kimi K3 provider and harness coverage."""

from __future__ import annotations

import pytest

from superqode.harness import get_harness_template, resolve_harness_model_policy
from superqode.providers.gateway.base import Message, ToolDefinition
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway
from superqode.providers.manager import ProviderManager
from superqode.providers.models import get_model_info
from superqode.providers.registry import PROVIDERS


def test_moonshot_registry_uses_first_party_global_api():
    provider = PROVIDERS["moonshot"]

    assert provider.dynamic is True
    assert provider.litellm_prefix == "openai/"
    assert provider.default_base_url == "https://api.moonshot.ai/v1"
    assert provider.base_url_env == "MOONSHOT_API_BASE"
    assert provider.example_models[0] == "kimi-k3"


def test_kimi_k3_catalog_metadata_and_manager_picker():
    model = get_model_info("moonshot", "kimi-k3")

    assert model is not None
    assert model.context_window == 1_048_576
    assert model.max_output == 1_048_576
    assert model.input_price == 3.0
    assert model.output_price == 15.0
    assert model.supports_tools is True
    assert model.supports_reasoning is True
    assert model.supports_vision is True

    manager_ids = {
        item.id
        for provider in ProviderManager().list_providers()
        if provider.id == "moonshot"
        for item in provider.models
    }
    assert "kimi-k3" in manager_ids


def test_kimi_api_key_alias_counts_as_configured(monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.setenv("KIMI_API_KEY", "kimi-test-key")

    assert ProviderManager()._is_provider_configured("moonshot") is True


def test_kimi_k3_harness_template():
    spec = get_harness_template("kimi-k3-coding")
    policy = resolve_harness_model_policy(spec, provider="moonshot", model="kimi-k3")

    assert spec.model_policy.primary == "moonshot/kimi-k3"
    assert spec.model_policy.context_window == 1_048_576
    assert policy.reasoning == "max"
    assert policy.temperature is None
    assert policy.parallel_tools is True
    assert policy.session_history_limit == 40


def test_kimi_k3_reasoning_and_fixed_sampling_shaping():
    gateway = LiteLLMGateway()
    assert gateway._resolve_reasoning_effort("moonshot", "kimi-k3", "low") == {
        "reasoning_effort": "max"
    }

    request = {
        "temperature": 0.2,
        "top_p": 0.7,
        "presence_penalty": 0.1,
        "max_tokens": 4096,
    }
    gateway._apply_kimi_k3_request_shaping("moonshot", "kimi-k3", request)

    assert request == {"max_completion_tokens": 4096}


@pytest.mark.asyncio
async def test_kimi_k3_request_routes_and_preserves_reasoning_history(monkeypatch):
    gateway = LiteLLMGateway()
    captured: dict = {}

    class Choice:
        finish_reason = "stop"

        class message:
            role = "assistant"
            content = "done"
            reasoning_content = "checked the tool result"
            tool_calls = None

    class Response:
        choices = [Choice()]
        model = "kimi-k3"
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

    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-test-key")
    monkeypatch.delenv("MOONSHOT_API_BASE", raising=False)
    monkeypatch.setattr(gateway, "_get_litellm", lambda: FakeLiteLLM())

    response = await gateway.chat_completion(
        messages=[
            Message(role="user", content="inspect the repository"),
            Message(
                role="assistant",
                content="",
                reasoning_content="I should read the file",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            ),
            Message(role="tool", content="readme", tool_call_id="call_1"),
        ],
        model="kimi-k3",
        provider="moonshot",
        temperature=0.2,
        max_tokens=8192,
        reasoning_effort="max",
        tools=[
            ToolDefinition(
                name="read_file",
                description="Read a file",
                parameters={"type": "object", "properties": {}},
            )
        ],
    )

    assert captured["model"] == "openai/kimi-k3"
    assert captured["api_base"] == "https://api.moonshot.ai/v1"
    assert captured["api_key"] == "moonshot-test-key"
    assert captured["reasoning_effort"] == "max"
    assert captured["max_completion_tokens"] == 8192
    assert "temperature" not in captured
    assert captured["messages"][1]["reasoning_content"] == "I should read the file"
    assert response.thinking_content == "checked the tool result"
