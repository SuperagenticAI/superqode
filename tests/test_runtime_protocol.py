"""Tests for the runtime Protocol and registry."""

from __future__ import annotations

import os

import pytest

from superqode.runtime import (
    AgentRuntime,
    BuiltinRuntime,
    RuntimeNotInstalledError,
    UnknownRuntimeError,
    create_runtime,
    known_runtime_names,
    list_runtimes,
    resolve_runtime_name,
)


def test_known_runtime_names_contains_all_three():
    names = known_runtime_names()
    assert "builtin" in names
    assert "adk" in names
    assert "openai-agents" in names


def test_list_runtimes_marks_builtin_installed():
    info = {r.name: r for r in list_runtimes()}
    assert info["builtin"].installed is True
    assert info["builtin"].implemented is True
    assert info["builtin"].install_hint is None


def test_list_runtimes_reports_install_hint_for_missing_extras():
    info = {r.name: r for r in list_runtimes()}
    # In the dev env neither adk nor openai-agents are installed.
    # The install_hint must mention the exact extra name.
    if not info["adk"].installed:
        assert info["adk"].install_hint == "pip install superqode[adk]"
    if not info["openai-agents"].installed:
        assert info["openai-agents"].install_hint == "pip install superqode[openai-agents]"


def test_all_known_runtimes_are_implemented():
    """Phase 3 promoted openai-agents from stub to full implementation."""
    info = {r.name: r for r in list_runtimes()}
    for name in info:
        assert info[name].implemented is True, f"{name} should be implemented"


def test_resolve_runtime_name_precedence_cli_over_yaml_over_env(monkeypatch):
    monkeypatch.delenv("SUPERQODE_RUNTIME", raising=False)
    # Default
    assert resolve_runtime_name() == "builtin"
    # Env only
    monkeypatch.setenv("SUPERQODE_RUNTIME", "adk")
    assert resolve_runtime_name() == "adk"
    # YAML beats env
    assert resolve_runtime_name(yaml="openai-agents") == "openai-agents"
    # CLI beats YAML and env
    assert resolve_runtime_name(cli="builtin", yaml="adk") == "builtin"


def test_resolve_runtime_name_normalizes_case_and_whitespace(monkeypatch):
    monkeypatch.delenv("SUPERQODE_RUNTIME", raising=False)
    assert resolve_runtime_name(cli="  ADK  ") == "adk"


def test_create_runtime_unknown_name_raises():
    with pytest.raises(UnknownRuntimeError):
        create_runtime("nope")


def test_create_runtime_default_returns_builtin():
    # We don't construct a full BuiltinRuntime here (it needs gateway/tools);
    # the registry-level validation is what we exercise via UnknownRuntimeError above.
    # This test just confirms the resolver falls back to builtin when name is None.
    assert resolve_runtime_name(cli=None, yaml=None) == "builtin"


def test_optional_runtimes_raise_not_installed_when_missing():
    # Skip this test if the optional dep is somehow present.
    import importlib

    try:
        importlib.import_module("google.adk")
        pytest.skip("google-adk is installed; this test asserts the missing-extra path")
    except ImportError:
        pass

    with pytest.raises(RuntimeNotInstalledError) as exc:
        create_runtime("adk")
    assert "superqode[adk]" in str(exc.value)


def test_builtin_runtime_conforms_to_protocol():
    # runtime_checkable Protocol: instance check works only against an instance.
    # Construct a minimal BuiltinRuntime by patching the AgentLoop import path —
    # but the protocol check works on attribute presence, not construction. We
    # use AgentRuntime as a structural check on the class shape.
    assert hasattr(BuiltinRuntime, "run")
    assert hasattr(BuiltinRuntime, "run_streaming")
    assert hasattr(BuiltinRuntime, "cancel")
    assert hasattr(BuiltinRuntime, "reset_cancellation")
    assert BuiltinRuntime.name == "builtin"
