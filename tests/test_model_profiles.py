"""Tests for the model profile registry."""

from __future__ import annotations

import os

import pytest

from superqode.providers.profiles import (
    ModelProfile,
    clear_registry,
    register_model_profile,
    resolve_model_profile,
    run_pre_init_once,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test starts with a fresh registry (builtins reload on first access)."""
    clear_registry()
    yield
    clear_registry()


def test_empty_default_when_no_match():
    profile = resolve_model_profile("nonexistent_provider", "nonexistent_model")
    assert profile.system_prompt_suffix is None
    assert profile.excluded_tools == frozenset()
    assert dict(profile.init_kwargs) == {}


def test_provider_level_match():
    register_model_profile("my_provider", ModelProfile(system_prompt_suffix="hi"))
    profile = resolve_model_profile("my_provider", "any_model")
    assert profile.system_prompt_suffix == "hi"


def test_exact_model_match_wins_over_provider():
    register_model_profile("p", ModelProfile(system_prompt_suffix="provider"))
    register_model_profile("p:m", ModelProfile(system_prompt_suffix="model"))
    profile = resolve_model_profile("p", "m")
    assert profile.system_prompt_suffix == "model"


def test_merge_unions_excluded_tools():
    register_model_profile("p", ModelProfile(excluded_tools=frozenset({"bash"})))
    register_model_profile("p:m", ModelProfile(excluded_tools=frozenset({"shell"})))
    profile = resolve_model_profile("p", "m")
    assert profile.excluded_tools == frozenset({"bash", "shell"})


def test_init_kwargs_merge_with_override_winning():
    register_model_profile("p", ModelProfile(init_kwargs={"temperature": 0.5, "max_tokens": 1024}))
    register_model_profile("p:m", ModelProfile(init_kwargs={"temperature": 0.0}))
    profile = resolve_model_profile("p", "m")
    kwargs = profile.resolve_kwargs()
    assert kwargs == {"temperature": 0.0, "max_tokens": 1024}


def test_caller_kwargs_override_profile_kwargs():
    register_model_profile("p", ModelProfile(init_kwargs={"temperature": 0.5}))
    profile = resolve_model_profile("p", "m")
    kwargs = profile.resolve_kwargs({"temperature": 1.0})
    assert kwargs == {"temperature": 1.0}


def test_init_kwargs_factory_runs_at_resolve_time():
    counter = {"calls": 0}

    def factory():
        counter["calls"] += 1
        return {"dynamic": counter["calls"]}

    register_model_profile("p", ModelProfile(init_kwargs_factory=factory))
    profile = resolve_model_profile("p", "m")
    assert profile.resolve_kwargs() == {"dynamic": 1}
    assert profile.resolve_kwargs() == {"dynamic": 2}


def test_factory_overrides_static_init_kwargs():
    register_model_profile(
        "p",
        ModelProfile(
            init_kwargs={"a": 1, "b": 2},
            init_kwargs_factory=lambda: {"b": 99, "c": 3},
        ),
    )
    profile = resolve_model_profile("p", "m")
    assert profile.resolve_kwargs() == {"a": 1, "b": 99, "c": 3}


def test_pre_init_runs_once_per_spec():
    calls: list[str] = []
    register_model_profile("p", ModelProfile(pre_init=lambda spec: calls.append(spec)))
    run_pre_init_once("p", "m")
    run_pre_init_once("p", "m")
    run_pre_init_once("p", "other")
    assert calls == ["p:m", "p:other"]


def test_additive_registration_merges():
    register_model_profile("p", ModelProfile(system_prompt_suffix="first"))
    register_model_profile("p", ModelProfile(excluded_tools=frozenset({"x"})))
    profile = resolve_model_profile("p", "m")
    assert profile.system_prompt_suffix == "first"
    assert profile.excluded_tools == frozenset({"x"})


def test_malformed_key_raises():
    with pytest.raises(ValueError):
        register_model_profile("", ModelProfile())
    with pytest.raises(ValueError):
        register_model_profile("a:b:c", ModelProfile())
    with pytest.raises(ValueError):
        register_model_profile(":m", ModelProfile())
    with pytest.raises(ValueError):
        register_model_profile("p:", ModelProfile())


def test_profile_is_frozen():
    profile = ModelProfile(init_kwargs={"a": 1})
    with pytest.raises(TypeError):
        profile.init_kwargs["a"] = 2  # type: ignore[index]


def test_builtin_anthropic_sonnet_loaded_lazily():
    profile = resolve_model_profile("anthropic", "claude-sonnet-4-6")
    assert profile.system_prompt_suffix is not None
    assert "parallel_tool_calls" in profile.system_prompt_suffix


def test_builtin_openrouter_injects_attribution_when_env_unset(monkeypatch):
    monkeypatch.delenv("OPENROUTER_APP_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_APP_TITLE", raising=False)
    profile = resolve_model_profile("openrouter", "some-model")
    kwargs = profile.resolve_kwargs()
    assert kwargs.get("app_title") == "SuperQode"
    assert "github.com" in kwargs.get("app_url", "")


def test_builtin_openrouter_respects_env_overrides(monkeypatch):
    monkeypatch.setenv("OPENROUTER_APP_URL", "https://example.com")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "Custom")
    profile = resolve_model_profile("openrouter", "some-model")
    kwargs = profile.resolve_kwargs()
    assert "app_url" not in kwargs
    assert "app_title" not in kwargs
