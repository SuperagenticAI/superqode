"""Tests for env-aware uv install hints (superqode.providers.env_introspect)."""

import superqode.providers.env_introspect as ei


def test_uv_tool_context_recommends_uv_tool_install(monkeypatch):
    monkeypatch.setattr(ei, "_running_in_uv_tool", lambda: True)
    assert ei.running_context() == "uv-tool"
    assert ei.install_command("codex-sdk") == 'uv tool install "superqode[codex-sdk]"'


def test_project_venv_recommends_uv_add(monkeypatch):
    monkeypatch.setattr(ei, "_running_in_uv_tool", lambda: False)
    monkeypatch.setattr(ei, "_running_in_venv", lambda: True)
    monkeypatch.setattr(ei, "_running_from_superqode_checkout", lambda: False)
    monkeypatch.setattr(ei, "_has_pyproject", lambda: True)
    assert ei.running_context() == "project"
    assert ei.install_command("codex-sdk") == 'uv add "superqode[codex-sdk]"'


def test_dev_checkout_recommends_editable_extra_install(monkeypatch):
    monkeypatch.setattr(ei, "_running_in_uv_tool", lambda: False)
    monkeypatch.setattr(ei, "_running_in_venv", lambda: True)
    monkeypatch.setattr(ei, "_running_from_superqode_checkout", lambda: True)
    assert ei.running_context() == "dev-checkout"
    assert ei.install_command("mlx") == 'uv pip install -e ".[mlx]"'


def test_plain_venv_recommends_uv_pip_install(monkeypatch):
    monkeypatch.setattr(ei, "_running_in_uv_tool", lambda: False)
    monkeypatch.setattr(ei, "_running_in_venv", lambda: True)
    monkeypatch.setattr(ei, "_running_from_superqode_checkout", lambda: False)
    monkeypatch.setattr(ei, "_has_pyproject", lambda: False)
    assert ei.running_context() == "venv"
    assert ei.install_command("codex-sdk") == 'uv pip install "superqode[codex-sdk]"'


def test_system_context_falls_back_to_uv_tool(monkeypatch):
    monkeypatch.setattr(ei, "_running_in_uv_tool", lambda: False)
    monkeypatch.setattr(ei, "_running_in_venv", lambda: False)
    assert ei.running_context() == "system"
    assert ei.install_command("adk") == 'uv tool install "superqode[adk]"'


def test_missing_extra_hint_appends_suffix(monkeypatch):
    monkeypatch.setattr(ei, "_running_in_uv_tool", lambda: True)
    hint = ei.missing_extra_hint("codex-sdk", suffix="then run `codex login`")
    assert hint == 'uv tool install "superqode[codex-sdk]", then run `codex login`'


def test_install_command_never_recommends_pip():
    # Whatever the environment, the hint is always a uv command.
    assert ei.install_command("codex-sdk").startswith("uv ")


def test_python_package_install_command_targets_running_python(monkeypatch):
    monkeypatch.setattr(ei.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    cmd = ei.python_package_install_command("mlx-lm>=0.31.0,<0.32.0", python="/tmp/sq py")
    assert cmd == "uv pip install --python '/tmp/sq py' 'mlx-lm>=0.31.0,<0.32.0'"


def test_environment_info_explains_target(monkeypatch):
    monkeypatch.setattr(ei, "running_context", lambda: "project")
    monkeypatch.setattr(ei.sys, "executable", "/tmp/project/.venv/bin/python")
    monkeypatch.setattr(ei.sys, "prefix", "/tmp/project/.venv")
    info = ei.environment_info()
    assert info.label == "project virtual environment"
    assert "current project environment" in info.target
