"""Tests for the `superqode runtime` CLI subcommand group."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from superqode.commands.runtime import runtime_cmd


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_list_shows_current_runtimes(runner):
    result = runner.invoke(runtime_cmd, ["list"])
    assert result.exit_code == 0, result.output
    assert "builtin" in result.output
    assert "adk" in result.output
    assert "openai-agents" in result.output
    assert "codex-sdk" in result.output
    assert "pydanticai" in result.output


def test_list_marks_active_runtime(runner, monkeypatch):
    monkeypatch.delenv("SUPERQODE_RUNTIME", raising=False)
    result = runner.invoke(runtime_cmd, ["list"])
    # Active runtime is announced in plain text under the table.
    assert "builtin" in result.output


def test_list_json_emits_array(runner, monkeypatch):
    monkeypatch.delenv("SUPERQODE_RUNTIME", raising=False)
    result = runner.invoke(runtime_cmd, ["list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    names = {entry["name"] for entry in payload}
    assert names == {
        "builtin",
        "adk",
        "openai-agents",
        "codex-sdk",
        "claude-agent-sdk",
        "antigravity-sdk",
        "antigravity-cli",
        "pydanticai",
    }
    # Exactly one entry is marked active.
    active = [e for e in payload if e["active"]]
    assert len(active) == 1


def test_doctor_with_known_runtime(runner):
    result = runner.invoke(runtime_cmd, ["doctor", "builtin"])
    assert result.exit_code == 0
    assert "builtin" in result.output
    assert "superqode.agent.loop" in result.output


def test_doctor_with_unknown_name_exits_nonzero(runner):
    result = runner.invoke(runtime_cmd, ["doctor", "nonexistent"])
    assert result.exit_code == 2
    assert "Unknown runtime" in result.output


def test_doctor_no_arg_probes_all(runner):
    result = runner.invoke(runtime_cmd, ["doctor"])
    # exit code may be 0 (all healthy) or 1 (something missing); both acceptable.
    assert result.exit_code in (0, 1)
    assert "builtin" in result.output
    assert "adk" in result.output
    assert "openai-agents" in result.output
    assert "codex-sdk" in result.output
    assert "pydanticai" in result.output
