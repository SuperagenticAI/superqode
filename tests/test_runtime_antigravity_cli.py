from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from superqode.agent.loop import AgentConfig
from superqode.runtime.antigravity_cli import AntigravityCLIRuntime, _version_tuple


def test_version_tuple():
    assert _version_tuple("agy version 1.1.1") == (1, 1, 1)
    assert _version_tuple("1.2.0") == (1, 2, 0)
    assert _version_tuple("unknown") is None


def test_rejects_cli_before_subprocess_fix(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(provider="google", model="", working_directory=Path.cwd())
    )

    class Process:
        returncode = 0

        async def communicate(self):
            return b"1.0.2\n", b""

    async def create(*_args, **_kwargs):
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    with pytest.raises(RuntimeError, match="1.1.1 or newer"):
        asyncio.run(runtime._check_version())


def test_command_uses_workspace_project_then_exact_conversation(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    project_dir = tmp_path / ".antigravitycli"
    project_dir.mkdir()
    (project_dir / "project-1.json").write_text(
        '{"id":"project-1","projectResources":{"resources":[{"gitFolder":{"folderUri":"file://'
        + str(tmp_path)
        + '"}}]}}'
    )
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(provider="google", model="gemini-test", working_directory=tmp_path)
    )
    first = runtime._command("hello")
    assert "--continue" not in first
    assert first[first.index("--project") : first.index("--project") + 2] == [
        "--project",
        "project-1",
    ]
    assert first[-2:] == ["--print", "hello"]
    assert ["--model", "gemini-test"] == first[first.index("--model") : first.index("--model") + 2]
    runtime._conversation_id = "conversation-1"
    resumed = runtime._command("again")
    assert resumed[resumed.index("--conversation") : resumed.index("--conversation") + 2] == [
        "--conversation",
        "conversation-1",
    ]
    assert "--continue" not in resumed


def test_command_creates_project_when_workspace_has_no_mapping(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(provider="google", model="", working_directory=tmp_path)
    )
    assert "--new-project" in runtime._command("hello")


def test_metadata_identifies_antigravity_harness(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(provider="google", model="", working_directory=Path.cwd())
    )
    assert runtime.metadata == {
        "runtime": "antigravity-cli",
        "harness_owner": "antigravity",
        "authentication": "google-sign-in",
        "structured_events": False,
    }
