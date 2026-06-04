"""Tests for harness-level model policy resolution."""

import pytest

from superqode.agent.loop import AgentResponse
from superqode.agent.system_prompts import SystemPromptLevel
from superqode.harness import (
    HarnessBackendRequest,
    ModelPolicySpec,
    RuntimeHarnessBackend,
    get_harness_template,
    resolve_harness_model_policy,
)


class FakeRuntime:
    name = "fake-runtime"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def run(self, prompt: str) -> AgentResponse:
        return AgentResponse(
            content=prompt,
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
        )


def test_gemma4_template_resolves_compact_local_policy():
    spec = get_harness_template("gemma4-coding")

    policy = resolve_harness_model_policy(
        spec,
        provider="mlx",
        model="SuperagenticAI/gemma-4-31b-it-4bit-mlx",
    )

    assert policy.profile == "gemma4-coding"
    assert policy.family == "gemma4"
    assert policy.temperature == 0.2
    assert policy.system_level == SystemPromptLevel.MINIMAL
    assert policy.tool_profile == "ds4"
    assert policy.tool_call_format == "strict-json"
    assert policy.parallel_tools is False
    assert policy.max_iterations == 0
    assert policy.session_history_limit == 12


def test_ds4_provider_autodetects_ds4_coding_policy():
    spec = get_harness_template("coding")

    policy = resolve_harness_model_policy(
        spec,
        provider="ds4",
        model="deepseek-v4-flash",
    )

    assert policy.profile == "ds4-coding"
    assert policy.family == "ds4"
    assert policy.tool_profile == "ds4"
    assert policy.tool_call_format == "compact-json"
    assert policy.parallel_tools is False


def test_gemma3_autodetects_optimized_gemma_policy():
    # Gemma 3 (not just Gemma 4) is tool-capable and should get the
    # Gemma-optimized profile from the generic coding template.
    spec = get_harness_template("coding")

    policy = resolve_harness_model_policy(
        spec,
        provider="ollama",
        model="gemma3:27b-it",
    )

    assert policy.profile == "gemma4-coding"
    assert policy.family == "gemma4"
    assert policy.system_level == SystemPromptLevel.MINIMAL
    assert policy.tool_call_format == "strict-json"


def test_gemma2_stays_on_generic_coding_policy():
    # Gemma 1/2 don't reliably tool-call -> must NOT get the Gemma tool profile.
    spec = get_harness_template("coding")

    policy = resolve_harness_model_policy(
        spec,
        provider="ollama",
        model="gemma2:9b-it",
    )

    assert policy.profile == "coding"
    assert policy.family == "general"


def test_no_tool_gemma4_policy_keeps_model_only_contract():
    spec = get_harness_template("gemma4-no-tool")

    policy = resolve_harness_model_policy(spec, provider="mlx", model="gemma-4")

    assert policy.system_level == SystemPromptLevel.NO_TOOL
    assert policy.tool_profile == "none"
    assert policy.reasoning == "off"
    assert policy.parallel_tools is False
    assert policy.max_iterations == 0


def test_model_policy_config_overrides_profile_defaults():
    base = get_harness_template("gemma4-coding")
    spec = base.__class__(
        **{
            **base.__dict__,
            "model_policy": ModelPolicySpec(
                profile="gemma4-coding",
                config={
                    "temperature": 0.05,
                    "max_iterations": 9,
                    "session_history_limit": 3,
                    "parallel_tools": True,
                    "tool_profile": "coding",
                    "system_prompt_level": "standard",
                    "reasoning_effort": "high",
                },
            ),
        }
    )

    policy = resolve_harness_model_policy(spec, provider="mlx", model="gemma-4")

    assert policy.temperature == 0.05
    assert policy.max_iterations == 9
    assert policy.session_history_limit == 3
    assert policy.parallel_tools is True
    assert policy.tool_profile == "coding"
    assert policy.system_level == SystemPromptLevel.STANDARD
    assert policy.reasoning == "high"


@pytest.mark.asyncio
async def test_runtime_backend_applies_gemma4_policy(monkeypatch, tmp_path):
    created = {}

    def fake_create_runtime(name, **kwargs):
        created["name"] = name
        created["kwargs"] = kwargs
        return FakeRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    backend = RuntimeHarnessBackend("builtin")
    request = HarnessBackendRequest(
        spec=get_harness_template("gemma4-coding"),
        prompt="code",
        provider="mlx",
        model="SuperagenticAI/gemma-4-31b-it-4bit-mlx",
        working_directory=tmp_path,
        session_id="s",
    )

    await backend.run(request)

    config = created["kwargs"]["config"]
    tool_names = [tool.name for tool in created["kwargs"]["tools"].list()]
    assert config.system_prompt_level == SystemPromptLevel.MINIMAL
    assert config.temperature == 0.2
    assert config.reasoning_effort is None
    assert config.max_iterations == 0
    assert config.session_history_limit == 12
    assert created["kwargs"]["parallel_tools"] is False
    assert "read_file" in tool_names
    assert "patch" in tool_names
    assert "multi_edit" not in tool_names


@pytest.mark.asyncio
async def test_runtime_backend_applies_no_tool_reasoning_off(monkeypatch, tmp_path):
    created = {}

    def fake_create_runtime(name, **kwargs):
        created["name"] = name
        created["kwargs"] = kwargs
        return FakeRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    backend = RuntimeHarnessBackend("builtin")
    request = HarnessBackendRequest(
        spec=get_harness_template("no-tool"),
        prompt="think",
        provider="ds4",
        model="deepseek-v4-flash",
        working_directory=tmp_path,
        session_id="s",
    )

    await backend.run(request)

    config = created["kwargs"]["config"]
    assert config.tools_enabled is False
    assert config.reasoning_effort == "off"
    assert config.system_prompt_level == SystemPromptLevel.NO_TOOL
    assert created["kwargs"]["parallel_tools"] is False


@pytest.mark.asyncio
async def test_runtime_backend_applies_ds4_fast_local_template(monkeypatch, tmp_path):
    created = {}

    def fake_create_runtime(name, **kwargs):
        created["name"] = name
        created["kwargs"] = kwargs
        return FakeRuntime(**kwargs)

    monkeypatch.setattr("superqode.harness.backends.runtime.create_runtime", fake_create_runtime)
    backend = RuntimeHarnessBackend("builtin")
    request = HarnessBackendRequest(
        spec=get_harness_template("ds4-fast-local"),
        prompt="code",
        provider="ds4",
        model="deepseek-v4-flash",
        working_directory=tmp_path,
        session_id="s",
    )

    await backend.run(request)

    config = created["kwargs"]["config"]
    assert config.temperature == 0.1
    assert config.max_iterations == 0
    assert config.session_history_limit == 10
    assert created["kwargs"]["parallel_tools"] is False
