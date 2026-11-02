"""SDK client construction binds local endpoints explicitly; no SDK/model calls."""

import sys
import types

import pytest

from superqode.runtime.local_endpoint import local_endpoint, local_litellm_options


@pytest.mark.parametrize(
    "provider,variable,port",
    [
        ("ollama", "OLLAMA_HOST", 11434),
        ("lmstudio", "LMSTUDIO_HOST", 1234),
        ("mlx", "MLX_HOST", 8080),
        ("llamacpp", "LLAMACPP_HOST", 8081),
    ],
)
def test_local_endpoint_ignores_inherited_openai_credentials(monkeypatch, provider, variable, port):
    monkeypatch.setenv(variable, f"http://127.0.0.1:{port}")
    monkeypatch.setenv("OPENAI_API_BASE", "https://unrelated.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "private-remote-key")
    endpoint = f"http://127.0.0.1:{port}/v1"
    assert local_endpoint(provider) == endpoint
    assert local_litellm_options(provider, "model:4b") == {
        "model": "openai/model:4b",
        "api_base": endpoint,
        "api_key": "superqode-local",
    }
    assert local_endpoint("openai") is None


def test_local_endpoint_rejects_inline_auth_and_invalid_transport(monkeypatch):
    for value in [
        "file:///tmp/models",
        "http://user:secret@127.0.0.1:8080/v1",
        "http://127.0.0.1:8080/v1?token=secret",
    ]:
        monkeypatch.setenv("MLX_HOST", value)
        with pytest.raises(ValueError):
            local_endpoint("mlx")


def test_openai_agents_local_client_options(monkeypatch):
    from superqode.runtime import openai_agents

    monkeypatch.setattr(openai_agents, "_require_sdk", lambda: None)
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: kwargs)
    module = types.ModuleType("agents.models.openai_chatcompletions")
    module.OpenAIChatCompletionsModel = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:4567/v1")
    client = openai_agents._build_model("lmstudio", "fixture-model")
    assert client == {
        "model": "fixture-model",
        "openai_client": {"base_url": "http://127.0.0.1:4567/v1", "api_key": "superqode-local"},
    }


def test_adk_local_client_options(monkeypatch):
    from superqode.runtime import adk

    monkeypatch.setattr(adk, "_require_adk", lambda: None)
    module = types.ModuleType("google.adk.models.lite_llm")
    module.LiteLlm = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("MLX_HOST", "http://127.0.0.1:4567/v1")
    assert adk._build_model("mlx", "fixture-model") == {
        "model": "openai/fixture-model",
        "api_base": "http://127.0.0.1:4567/v1",
        "api_key": "superqode-local",
    }


def test_pydanticai_local_client_options(monkeypatch):
    from superqode.runtime import pydanticai

    model = types.ModuleType("pydantic_ai.models.openai")
    provider = types.ModuleType("pydantic_ai.providers.openai")
    model.OpenAIChatModel = lambda name, **kwargs: {"name": name, **kwargs}
    provider.OpenAIProvider = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, model.__name__, model)
    monkeypatch.setitem(sys.modules, provider.__name__, provider)
    monkeypatch.setenv("LLAMACPP_HOST", "http://127.0.0.1:4567/v1")
    result = pydanticai._pydanticai_model("llamacpp", "fixture-model", ())
    assert result == {
        "name": "fixture-model",
        "provider": {"base_url": "http://127.0.0.1:4567/v1", "api_key": "superqode-local"},
    }


@pytest.mark.asyncio
async def test_adk_forwards_model_call_budget(monkeypatch):
    from superqode.runtime.adk import ADKRuntime

    genai = types.ModuleType("google.genai")
    genai.types = types.SimpleNamespace(
        Content=lambda **kwargs: kwargs, Part=lambda **kwargs: kwargs
    )
    limits = types.ModuleType("google.adk.agents.run_config")
    limits.RunConfig = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, limits.__name__, limits)
    captured = {}

    class Runner:
        async def run_async(self, **kwargs):
            captured.update(kwargs)
            yield "fixture-event"

    runtime = ADKRuntime.__new__(ADKRuntime)
    runtime.config = types.SimpleNamespace(max_iterations=6)
    runtime._runner = Runner()
    runtime._user_id, runtime.session_id, runtime._cancelled = "fixture", "fixture", False
    assert [event async for event in runtime._iter_events("hello")] == ["fixture-event"]
    assert captured["run_config"] == {"max_llm_calls": 6}
