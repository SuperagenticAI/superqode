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

    with pytest.raises(ValueError, match="agy effort must be"):
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
    assert runtime.metadata["structured_events"] is True
    assert runtime.metadata["agent"] is None
    assert runtime.metadata["reasoning_effort"] is None


def test_parse_agy_models_accepts_spaces_tabs_and_spinner_prefixes():
    from superqode.runtime.antigravity_status import parse_agy_models

    raw = (
        "\r⠋ Fetching available models...\r"
        "gemini-4-neon-high             Gemini 4 Neon (High)\n"
        "gemini-4-neon-medium\tGemini 4 Neon (Medium)\n"
        "gemini-4-neon-low\n"
    )
    assert parse_agy_models(raw) == [
        {"id": "gemini-4-neon-high", "name": "Gemini 4 Neon (High)"},
        {"id": "gemini-4-neon-medium", "name": "Gemini 4 Neon (Medium)"},
        {"id": "gemini-4-neon-low", "name": "gemini-4-neon-low"},
    ]


@pytest.mark.asyncio
async def test_stream_json_emits_structured_events_and_captures_conversation(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(
            provider="google", model="gemini-4-neon-medium", working_directory=tmp_path
        ),
        persistent=False,
    )
    runtime._checked_version = True
    runtime._cli_version = (1, 5, 16)

    lines = [
        '{"event":"init","conversation_id":"conv-42","init":{"model":"gemini-4-neon-medium"}}\n',
        '{"event":"step_update","step_update":{"conversation_id":"conv-42","step_index":1,"state":"ACTIVE","step_type":"agent_response","thinking_delta":"Inspecting repo"}}\n',
        '{"event":"step_update","step_update":{"conversation_id":"conv-42","step_index":2,"state":"ACTIVE","step_type":"tool","tool_name":"list_dir","tool_info":{"name":"list_dir","parameters":{"path":"."}}}}\n',
        '{"event":"step_update","step_update":{"conversation_id":"conv-42","step_index":2,"state":"DONE","step_type":"tool","tool_name":"list_dir","duration_seconds":0.1,"tool_info":{"name":"list_dir","parameters":{"path":"."},"output":"README.md"}}}\n',
        '{"event":"step_update","step_update":{"conversation_id":"conv-42","step_index":3,"state":"ACTIVE","step_type":"agent_response","text_delta":"Hello"}}\n',
        '{"event":"step_update","step_update":{"conversation_id":"conv-42","step_index":3,"state":"DONE","step_type":"agent_response","text_delta":" world"}}\n',
        '{"event":"result","result":{"conversation_id":"conv-42","status":"SUCCESS","response":"Hello world","duration_seconds":2.5,"usage":{"input_tokens":100,"output_tokens":10,"thinking_tokens":8,"cache_read_tokens":50,"total_tokens":110}}}\n',
    ]

    class FakeStdout:
        def __init__(self, items):
            self._items = [item.encode("utf-8") for item in items]

        async def readline(self):
            return self._items.pop(0) if self._items else b""

    class FakeStderr:
        async def read(self, _size):
            return b""

    class FakeProcess:
        def __init__(self):
            self.stdout = FakeStdout(lines)
            self.stderr = FakeStderr()
            self.returncode = 0

        async def wait(self):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    captured_argv = []

    async def create(*args, **_kwargs):
        captured_argv.append(list(args))
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    events = [event async for event in runtime.run_harness_events("check repo")]

    assert "--output-format" in captured_argv[0]
    assert captured_argv[0][captured_argv[0].index("--output-format") + 1] == "stream-json"
    assert [e.type for e in events] == [
        "model_request",
        "thinking",
        "tool_call",
        "tool_result",
        "model_delta",
        "model_delta",
        "turn_complete",
        "model_result",
    ]
    assert runtime.session_id == "conv-42"
    assert runtime.thread_id == "conv-42"
    assert events[2].data["tool_name"] == "list_dir"
    assert events[3].data["success"] is True
    assert events[3].data["output"] == "README.md"
    assert events[-2].data["usage"]["cache_read_tokens"] == 50


@pytest.mark.asyncio
async def test_persistent_stream_reuses_single_process_and_restarts_on_model_change(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(
            provider="google", model="gemini-4-neon-low", working_directory=tmp_path
        ),
        persistent=True,
    )
    runtime._checked_version = True
    runtime._cli_version = (1, 5, 16)

    spawned = []

    class FakeStdin:
        def __init__(self, out_queue):
            self.written = []
            self._queue = out_queue
            self._closed = False

        def write(self, data):
            msg = data.decode("utf-8").strip()
            self.written.append(msg)
            self._queue.append(
                '{"event":"init","conversation_id":"conv-warm","init":{"model":"gemini-4-neon-low"}}\n'.encode()
            )
            self._queue.append(
                '{"event":"step_update","step_update":{"step_index":1,"state":"DONE","step_type":"agent_response","text_delta":"ok"}}\n'.encode()
            )
            self._queue.append(
                '{"event":"result","result":{"conversation_id":"conv-warm","status":"SUCCESS","response":"ok","usage":{"total_tokens":5}}}\n'.encode()
            )

        async def drain(self):
            pass

        def is_closing(self):
            return self._closed

        def close(self):
            self._closed = True

    class FakeStdout:
        def __init__(self, queue):
            self._queue = queue

        async def readline(self):
            return self._queue.pop(0) if self._queue else b""

    class FakeStderr:
        async def read(self, _size):
            return b""

    class FakePersistentProcess:
        def __init__(self):
            self._queue = []
            self.stdin = FakeStdin(self._queue)
            self.stdout = FakeStdout(self._queue)
            self.stderr = FakeStderr()
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        async def wait(self):
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    async def create(*args, **_kwargs):
        proc = FakePersistentProcess()
        spawned.append((list(args), proc))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)

    r1 = await runtime.run("turn 1")
    r2 = await runtime.run("turn 2")
    assert r1.content == "ok" and r2.content == "ok"
    # Both turns share a single warm persistent agy process.
    assert len(spawned) == 1
    assert "--input-format" in spawned[0][0]
    assert len(spawned[0][1].stdin.written) == 2

    # Switching model cleanly restarts the persistent worker on the next turn.
    runtime.set_model("gemini-4-neon-medium")
    r3 = await runtime.run("turn 3")
    assert r3.content == "ok"
    assert len(spawned) == 2
    assert "--conversation" in spawned[1][0]
    assert spawned[1][0][spawned[1][0].index("--conversation") + 1] == "conv-warm"

    await runtime.aclose()


def test_resume_thread_updates_conversation_id(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/agy")
    runtime = AntigravityCLIRuntime(
        config=AgentConfig(provider="google", model="", working_directory=tmp_path)
    )
    runtime.resume_thread("conv-99")
    assert runtime.session_id == "conv-99"
    cmd = runtime._command("follow up")
    assert cmd[cmd.index("--conversation") : cmd.index("--conversation") + 2] == [
        "--conversation",
        "conv-99",
    ]
