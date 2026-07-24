from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from superqode.agent.loop import AgentConfig
from superqode.runtime.antigravity_cli import AntigravityCLIRuntime, _version_tuple
from superqode.runtime.antigravity_status import probe_antigravity_cli


@pytest.fixture(autouse=True)
def _clear_antigravity_overrides(monkeypatch):
    monkeypatch.delenv("SUPERQODE_ANTIGRAVITY_CLI_AGENT", raising=False)
    monkeypatch.delenv("SUPERQODE_ANTIGRAVITY_CLI_EFFORT", raising=False)


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


def test_version_check_has_a_timeout(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(provider="google", model="", working_directory=Path.cwd())
    )

    class Process:
        killed = False

        async def communicate(self):
            await asyncio.sleep(60)

        def kill(self):
            self.killed = True

        async def wait(self):
            return -9

    process = Process()

    async def create(*_args, **_kwargs):
        return process

    async def immediate_timeout(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(asyncio, "wait_for", immediate_timeout)

    with pytest.raises(RuntimeError, match="Timed out"):
        asyncio.run(runtime._check_version())
    assert process.killed is True


def test_readiness_probe_rejects_old_cli(monkeypatch):
    class Process:
        returncode = 0
        stdout = "1.0.3\n"
        stderr = ""

    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: Process())

    status = probe_antigravity_cli()

    assert status.installed is True
    assert status.compatible is False
    assert "agy update" in status.issue


def test_stderr_is_drained_concurrently_and_bounded():
    class Stream:
        def __init__(self):
            self.chunks = [b"a" * 40000, b"b" * 40000, b""]

        async def read(self, _size):
            return self.chunks.pop(0)

    output = asyncio.run(AntigravityCLIRuntime._read_bounded_stderr(Stream(), limit=65536))

    assert len(output) == 65536
    assert output.endswith(b"b" * 40000)


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


def test_command_supports_custom_agent_and_effort(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    monkeypatch.setenv("SUPERQODE_ANTIGRAVITY_CLI_AGENT", "reviewer")
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(
            provider="google",
            model="gemini-test",
            working_directory=tmp_path,
            reasoning_effort="high",
        )
    )

    command = runtime._command("review this")

    assert command[command.index("--agent") : command.index("--agent") + 2] == [
        "--agent",
        "reviewer",
    ]
    assert command[command.index("--effort") : command.index("--effort") + 2] == [
        "--effort",
        "high",
    ]
    runtime.set_agent("auto")
    runtime.set_model("gemini-next")
    runtime.set_reasoning_effort("medium")
    assert runtime.agent_name is None
    assert runtime.config.model == "gemini-next"
    assert runtime.reasoning_effort == "medium"

    with pytest.raises(ValueError, match="low, medium, or high"):
        runtime.set_reasoning_effort("extra-high")


def test_effort_requires_cli_1_1_5_after_version_probe(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(provider="google", model="", working_directory=tmp_path)
    )
    runtime._cli_version = (1, 1, 1)

    with pytest.raises(RuntimeError, match="1.1.5"):
        runtime.set_reasoning_effort("high")

    assert runtime.reasoning_effort is None


def test_metadata_identifies_antigravity_harness(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(provider="google", model="", working_directory=Path.cwd())
    )
    assert runtime.metadata["runtime"] == "antigravity-cli"
    assert runtime.metadata["harness_owner"] == "antigravity"
    assert runtime.metadata["authentication"] == "google-sign-in"
    assert runtime.metadata["structured_events"] is False
    assert runtime.metadata["agent"] is None
    assert runtime.metadata["reasoning_effort"] is None
