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


def test_known_runtime_names_contains_current_runtimes():
    names = known_runtime_names()
    assert "builtin" in names
    assert "adk" in names
    assert "openai-agents" in names
    assert "pydanticai" in names


def test_list_runtimes_marks_builtin_installed():
    info = {r.name: r for r in list_runtimes()}
    assert info["builtin"].installed is True
    assert info["builtin"].implemented is True
    assert info["builtin"].install_hint is None


def test_list_runtimes_reports_install_hint_for_missing_extras():
    info = {r.name: r for r in list_runtimes()}
    # In the dev env neither adk nor openai-agents are installed. The hint is an
    # env-aware uv command (uv tool install / uv add) naming the exact extra.
    for name in ("adk", "openai-agents", "pydanticai"):
        if not info[name].installed:
            hint = info[name].install_hint
            assert hint.startswith("uv ")
            assert f"[{name}]" in hint


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
    assert "[adk]" in str(exc.value)


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


def test_listing_runtimes_never_shells_out_to_a_vendor_cli(monkeypatch):
    """The default listing runs on a UI frame, so it must not fork a process.

    Selecting one runtime used to run `agy --version`, `devin version` and
    `devin auth status`, which froze the terminal for seconds before the
    picker redrew.
    """
    import subprocess

    from superqode.runtime import list_runtimes
    from superqode.runtime import antigravity_status, devin_status

    antigravity_status.clear_antigravity_cli_cache()
    devin_status.clear_devin_cli_cache()

    def forbidden(*args, **kwargs):
        raise AssertionError(f"list_runtimes() shelled out: {args!r}")

    monkeypatch.setattr(subprocess, "run", forbidden)

    runtimes = list_runtimes()
    assert {"devin-cli", "antigravity-cli"} <= {item.name for item in runtimes}


def test_listing_runtimes_never_imports_an_optional_sdk(monkeypatch):
    """Deciding whether to draw a row must not execute the package.

    SuperQode's own small modules are still imported; what must not happen is
    pulling in google.adk or openai_codex to decide whether a row is drawn.
    """
    import importlib

    from superqode.runtime import list_runtimes
    from superqode.runtime.registry import _OPTIONAL_PACKAGES

    guarded = {pkg for pkg, _extra in _OPTIONAL_PACKAGES.values()}
    real_import = importlib.import_module

    def guard(name, *args, **kwargs):
        if name in guarded:
            raise AssertionError(f"list_runtimes() imported the {name!r} SDK")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", guard)

    names = {item.name for item in list_runtimes()}
    assert "codex-sdk" in names


def test_the_deep_probe_is_still_available_for_reports(monkeypatch):
    """`superqode runtime list` and drift still pay for the real status."""
    import subprocess

    from superqode.runtime import list_runtimes
    from superqode.runtime import antigravity_status, devin_status

    antigravity_status.clear_antigravity_cli_cache()
    devin_status.clear_devin_cli_cache()

    calls: list[tuple] = []
    real_run = subprocess.run

    def counted(args, **kwargs):
        calls.append(tuple(args))
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", counted)
    monkeypatch.setattr(
        "shutil.which", lambda binary: f"/usr/local/bin/{binary}" if binary == "devin" else None
    )

    list_runtimes(probe=True)
    assert any("devin" in call[0] for call in calls), "the deep probe stopped probing"
