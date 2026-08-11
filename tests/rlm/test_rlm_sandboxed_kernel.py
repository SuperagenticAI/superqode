"""Contract tests for the sandboxed RLM kernel.

The kernel server is transport-agnostic on purpose, so almost all of its
behaviour is verified here by running it as a local subprocess. Only container
lifecycle needs Docker; the protocol, the persistence, the host-call bridge and
the checkpoint boundary do not.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from superqode.rlm import kernel_server
from superqode.rlm.kernel import Shell as HostShell
from superqode.rlm.kernel import Workspace as HostWorkspace
from superqode.rlm.kernel_docker import (
    KernelChannel,
    STATE_MOUNT,
    container_run_command,
    kernel_exec_command,
    safe_name,
    shell_exec_command,
)
from superqode.rlm.sandbox import RLMSandboxConfig

SERVER = Path(kernel_server.__file__)
TIMEOUT = 30


def _command(workspace: Path, kernel_id: str = "root") -> list[str]:
    return [sys.executable, str(SERVER), kernel_id, str(workspace)]


async def _channel(workspace: Path, *, host_call: Any = None, kernel_id: str = "root"):
    channel = KernelChannel(_command(workspace, kernel_id), host_call=host_call)
    await channel.start()
    return channel


async def _execute(channel: KernelChannel, code: str, **extra) -> dict[str, Any]:
    return await channel.request({"op": "execute", "code": code, **extra}, timeout=TIMEOUT)


async def test_the_sandboxed_kernel_keeps_state_between_calls(tmp_path):
    channel = await _channel(tmp_path)
    try:
        await _execute(channel, "value = 40")
        result = await _execute(channel, "value + 2")
    finally:
        await channel.close()

    assert result["value_repr"] == "42"
    assert result["error"] is None


async def test_a_failed_call_returns_a_traceback_and_keeps_the_kernel(tmp_path):
    channel = await _channel(tmp_path)
    try:
        await _execute(channel, "kept = 7")
        failed = await _execute(channel, "raise RuntimeError('boom')")
        after = await _execute(channel, "kept")
    finally:
        await channel.close()

    assert "boom" in failed["error"]
    assert after["value_repr"] == "7"


async def test_stray_output_from_model_code_cannot_corrupt_the_protocol(tmp_path):
    """A subprocess inheriting stdout would otherwise inject into the stream."""
    channel = await _channel(tmp_path)
    try:
        noisy = await _execute(
            channel, "import os\nos.system('echo not-protocol-traffic')\nvalue = 1"
        )
        following = await _execute(channel, "value + 1")
    finally:
        await channel.close()

    assert noisy["error"] is None
    assert following["value_repr"] == "2"


async def test_workspace_and_shell_run_inside_the_kernel(tmp_path):
    (tmp_path / "a.txt").write_text("before\n", encoding="utf-8")
    channel = await _channel(tmp_path)
    try:
        read = await _execute(channel, "workspace.read('a.txt')")
        await _execute(channel, "workspace.edit('a.txt', 'before', 'after')")
        command = await _execute(channel, "shell.run(['pwd']).ok")
    finally:
        await channel.close()

    assert read["value_repr"] == "'before'"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "after\n"
    assert command["value_repr"] == "True"


async def test_recursive_calls_are_forwarded_to_the_host(tmp_path):
    """The supervisor and the credentials stay outside the boundary."""
    seen: list[tuple[str, dict]] = []

    async def host_call(name: str, payload: dict) -> Any:
        seen.append((name, payload))
        if name == "rlm.run":
            return {"__rlm__": "agent", "id": "agent-1", "status": {"status": "running"}}
        if name == "rlm.wait":
            return "child finished"
        return None

    channel = await _channel(tmp_path, host_call=host_call)
    try:
        spawned = await _execute(channel, "child = rlm.run('inspect the tests')\nchild.id")
        waited = await _execute(channel, "child.wait()")
    finally:
        await channel.close()

    assert spawned["value_repr"] == "'agent-1'"
    assert waited["value_repr"] == "'child finished'"
    assert [name for name, _payload in seen] == ["rlm.run", "rlm.wait"]
    assert seen[0][1]["prompt"] == "inspect the tests"


async def test_subcalls_from_inside_the_sandbox_run_on_the_host(tmp_path):
    """Provider credentials never enter the boundary, so the query leaves it."""
    seen: list[tuple[str, dict]] = []

    async def host_call(name: str, payload: dict) -> Any:
        seen.append((name, payload))
        if name == "llm.query":
            return {
                "__rlm__": "response",
                "id": "query-1",
                "text": "the answer" * 20,
                "usage": {"total_tokens": 15},
            }
        if name == "llm.query_batch":
            return [
                {"__rlm__": "response", "id": f"query-{index}", "text": prompt.upper()}
                for index, prompt in enumerate(payload["prompts"], start=2)
            ]
        return None

    channel = await _channel(tmp_path, host_call=host_call)
    try:
        single = await _execute(
            channel, "answer = llm_query('what is this', context='some text')\nrepr(answer)"
        )
        length = await _execute(channel, "len(answer)")
        batch = await _execute(
            channel, "answers = llm_query_batched(['a', 'b'])\n[a.text for a in answers]"
        )
    finally:
        await channel.close()

    # A handle, not the text: the repr is what reaches the conversation.
    assert "RLMResponse(id='query-1'" in single["value_repr"]
    assert "the answer" * 20 not in single["value_repr"]
    assert length["value_repr"] == "200"
    assert batch["value_repr"] == "['A', 'B']"
    assert [name for name, _payload in seen] == ["llm.query", "llm.query_batch"]
    assert seen[0][1]["context"] == "some text"


async def test_context_inside_the_sandbox_is_served_by_the_host(tmp_path):
    """One implementation of discovery and chunking, not a second that drifts."""
    seen: list[tuple[str, dict]] = []

    async def host_call(name: str, payload: dict) -> Any:
        seen.append((name, payload))
        if name == "ctx.files":
            # The real bridge builds a narrowed view from the carried paths.
            return payload.get("paths") or ["a.py", "b.py"]
        if name == "ctx.len":
            return 4096
        if name == "ctx.select":
            return ["a.py"]
        if name == "ctx.chunk":
            return [
                {
                    "__rlm__": "chunk",
                    "text": "slice",
                    "path": "a.py",
                    "index": 0,
                    "start": 0,
                    "end": 5,
                }
            ]
        return None

    channel = await _channel(tmp_path, host_call=host_call)
    try:
        listed = await _execute(channel, "context.files()")
        size = await _execute(channel, "len(context)")
        narrowed = await _execute(channel, "view = context.select('*.py')\nview.files()")
        chunked = await _execute(channel, "chunk = context.chunk(size=5)[0]\nchunk.path")
    finally:
        await channel.close()

    assert listed["value_repr"] == "['a.py', 'b.py']"
    assert size["value_repr"] == "4096"
    assert narrowed["value_repr"] == "['a.py']"
    assert chunked["value_repr"] == "'a.py'"
    # A narrowed view carries its own paths, so neither side keeps a handle.
    operations = [name for name, _payload in seen]
    assert operations == ["ctx.files", "ctx.len", "ctx.select", "ctx.files", "ctx.chunk"]
    assert seen[3][1]["paths"] == ["a.py"]


async def test_a_host_call_failure_surfaces_inside_the_kernel(tmp_path):
    async def host_call(name: str, payload: dict) -> Any:
        raise RuntimeError("depth limit reached")

    channel = await _channel(tmp_path, host_call=host_call)
    try:
        result = await _execute(channel, "rlm.run('too deep')")
    finally:
        await channel.close()

    assert "depth limit reached" in result["error"]


async def test_a_kernel_without_a_host_channel_says_so(tmp_path):
    channel = await _channel(tmp_path)
    try:
        result = await _execute(channel, "rlm.run('no host')")
    finally:
        await channel.close()

    assert "not available" in result["error"]


async def test_checkpoints_are_written_and_restored_inside_the_boundary(tmp_path):
    state = tmp_path / "state.pkl"
    first = await _channel(tmp_path)
    try:
        await _execute(first, "answer = {'value': 42}\nimport threading\nlock = threading.Lock()")
        checkpoint = await first.request({"op": "checkpoint", "path": str(state)}, timeout=TIMEOUT)
    finally:
        await first.close()

    second = await _channel(tmp_path)
    try:
        restored = await second.request({"op": "restore", "path": str(state)}, timeout=TIMEOUT)
        value = await _execute(second, "answer['value']")
    finally:
        await second.close()

    assert "answer" in checkpoint["saved"]
    assert "lock" in checkpoint["skipped"]
    assert checkpoint["digest"] and checkpoint["size"] > 0
    assert restored["restored"] == ["answer"]
    assert value["value_repr"] == "42"


async def test_the_execute_call_checkpoints_state_as_the_host_kernel_does(tmp_path):
    state = tmp_path / "auto.pkl"
    channel = await _channel(tmp_path)
    try:
        result = await _execute(channel, "kept = 5", checkpoint_path=str(state))
    finally:
        await channel.close()

    assert result["checkpoint"]["saved"] == ["kept"]
    assert state.is_file()


def test_the_two_namespaces_expose_the_same_api():
    """Host and sandbox namespaces are separate code, so drift is the risk."""

    def surface(target: type) -> set[str]:
        return {
            name
            for name, member in inspect.getmembers(target)
            if not name.startswith("_")
            and (inspect.isfunction(member) or isinstance(member, property))
        }

    assert surface(kernel_server.Workspace) == surface(HostWorkspace) - {"sandbox"}
    assert surface(kernel_server.Shell) == surface(HostShell) - {"sandbox"}


def test_the_container_never_mounts_the_docker_socket(tmp_path):
    command = container_run_command(
        image="python:3.12-slim",
        name="superqode-rlm-test",
        session_id="test",
        workspace=tmp_path,
        server_dir=tmp_path / "server",
        state_dir=tmp_path / "state",
        config=RLMSandboxConfig.from_config({"sandbox": "docker"}),
        uid=501,
        gid=20,
    )

    joined = " ".join(command)
    assert "docker.sock" not in joined
    assert "--privileged" not in command
    assert "--user" in command and "501:20" in command
    assert "--cap-drop" in command and "ALL" in command
    assert "no-new-privileges" in command
    assert "--read-only" in command
    assert command[command.index("--volume") + 1] == f"{tmp_path}:/workspace"
    assert command[-2:] == ["sleep", "infinity"]


def test_the_host_environment_is_never_forwarded_into_the_container(tmp_path, monkeypatch):
    monkeypatch.setenv("RLM_TEST_SECRET", "leaked")
    monkeypatch.setenv("ALLOWED_ONE", "fine")

    without = container_run_command(
        image="python:3.12-slim",
        name="c",
        session_id="s",
        workspace=tmp_path,
        server_dir=tmp_path,
        state_dir=tmp_path / "state",
        config=RLMSandboxConfig.from_config({"sandbox": "docker"}),
        uid=1,
        gid=1,
    )
    with_allowlist = container_run_command(
        image="python:3.12-slim",
        name="c",
        session_id="s",
        workspace=tmp_path,
        server_dir=tmp_path,
        state_dir=tmp_path / "state",
        config=RLMSandboxConfig.from_config(
            {"sandbox": "docker", "env_allowlist": ["ALLOWED_ONE"]}
        ),
        uid=1,
        gid=1,
    )

    assert not any("RLM_TEST_SECRET" in item for item in without)
    assert not any("RLM_TEST_SECRET" in item for item in with_allowlist)
    assert "ALLOWED_ONE=fine" in with_allowlist


def test_network_is_off_unless_the_profile_asks_for_it(tmp_path):
    def network_of(**config) -> str:
        command = container_run_command(
            image="i",
            name="c",
            session_id="s",
            workspace=tmp_path,
            server_dir=tmp_path,
            state_dir=tmp_path / "state",
            config=RLMSandboxConfig.from_config({"sandbox": "docker", **config}),
            uid=1,
            gid=1,
        )
        return command[command.index("--network") + 1]

    assert network_of() == "none"
    assert network_of(allow_network=False) == "none"
    assert network_of(allow_network=True) == "bridge"


def test_exec_commands_target_the_workspace_and_the_mounted_server():
    kernel = kernel_exec_command("abc123", "agent-1")
    shell = shell_exec_command("abc123", "pytest -q")

    assert kernel[:5] == ["docker", "exec", "--interactive", "--workdir", "/workspace"]
    assert kernel[-4:-1] == ["/opt/superqode-rlm/kernel_server.py", "agent-1", "/workspace"]
    assert json.loads(kernel[-1])["allow_shell"] is True
    assert shell[-3:] == ["sh", "-lc", "pytest -q"]


def test_session_names_are_docker_legal():
    assert safe_name("2026-08-10T00:00:00Z_abc") == "2026-08-10T00-00-00Z_abc"
    assert safe_name("///") == "session"
    assert len(safe_name("x" * 200)) <= 48


async def test_restore_refuses_state_from_outside_the_boundary(tmp_path):
    """A path outside the state mount would mean state the sandbox did not own."""
    from superqode.rlm.kernel_backend import CheckpointReference
    from superqode.rlm.kernel_docker import DockerKernelBackend

    backend = DockerKernelBackend(
        tmp_path,
        config=RLMSandboxConfig.from_config({"sandbox": "docker"}),
        session_id="s",
        state_dir=tmp_path / "state",
    )

    with pytest.raises(ValueError, match=STATE_MOUNT):
        await backend.restore("root", CheckpointReference(path="/etc/passwd"))


def test_a_denied_write_uses_a_read_only_workspace_mount(tmp_path):
    command = container_run_command(
        image="i",
        name="c",
        session_id="s",
        workspace=tmp_path,
        server_dir=tmp_path,
        state_dir=tmp_path / "state",
        config=RLMSandboxConfig.from_config({"sandbox": "docker", "allow_write": False}),
        uid=1,
        gid=1,
    )

    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--volume"]
    assert f"{tmp_path}:/workspace:ro" in mounts


async def test_sandboxed_namespace_enforces_declared_guardrails(tmp_path):
    policy = RLMSandboxConfig.from_config(
        {"sandbox": "docker", "allow_shell": False, "allow_read": False}
    )
    channel = KernelChannel(kernel_exec_command("unused", "root", policy))
    # Replace the Docker command with the same server command plus its policy.
    channel.command = _command(tmp_path) + [channel.command[-1]]
    await channel.start()
    try:
        denied_read = await _execute(channel, "workspace.read('anything')")
        denied_shell = await _execute(channel, "shell.run('echo nope')")
    finally:
        await channel.close()

    assert "Reading is disabled" in denied_read["error"]
    assert "Shell execution is disabled" in denied_shell["error"]
