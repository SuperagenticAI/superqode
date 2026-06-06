"""Tests for project trust state."""

from pathlib import Path

from superqode.project_trust import (
    get_project_trust,
    is_project_trusted,
    project_risk_signals,
    set_project_trust,
)


def test_project_trust_round_trip(tmp_path, monkeypatch):
    store = tmp_path / "trust.json"
    project = tmp_path / "repo"
    project.mkdir()
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(store))

    assert is_project_trusted(project) is False

    trusted = set_project_trust(project, True, note="test")
    assert trusted.trusted is True
    assert trusted.path == str(project.resolve())
    assert is_project_trusted(project) is True

    untrusted = set_project_trust(project, False)
    assert untrusted.trusted is False
    assert get_project_trust(project).trusted is False


def test_project_risk_signals_detect_local_plugins_mcp_and_hooks(tmp_path):
    (tmp_path / ".superqode" / "plugins").mkdir(parents=True)
    (tmp_path / ".superqode" / "mcp.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".superqode" / "hooks.json").write_text("{}", encoding="utf-8")

    signals = project_risk_signals(tmp_path)

    assert ".superqode/plugins" in signals
    assert ".superqode/mcp.json" in signals
    assert ".superqode/hooks.json" in signals
