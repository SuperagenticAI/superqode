"""Acceptance tests for the Docker RLM kernel, run against a real container.

These are the tests that decide whether the boundary is real. Everything else
about the sandboxed kernel is verified without a daemon in
``test_rlm_sandboxed_kernel.py``; what cannot be faked is whether model-written
Python actually executes somewhere other than this process.

They skip when Docker is unavailable so the suite stays runnable everywhere.
"""

from __future__ import annotations

import asyncio
import json
import os
import pickle
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from superqode.rlm.kernel_docker import DockerKernelBackend
from superqode.rlm.sandbox import RLMSandboxConfig
from superqode.rlm.supervisor import AgentSupervisor

IMAGE = "python:3.12-slim"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(  # noqa: S603,S607 - fixed availability probe
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=15,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _docker_ready(), reason="Docker daemon is not available"),
]


def _config(**config) -> RLMSandboxConfig:
    return RLMSandboxConfig.from_config({"sandbox": "docker", "sandbox_image": IMAGE, **config})


@pytest.fixture
async def containers(tmp_path):
    """Hand out backends and guarantee their containers are removed."""
    created: list[DockerKernelBackend] = []

    def make(session_id: str, *, workspace: Path | None = None, **config) -> DockerKernelBackend:
        backend = DockerKernelBackend(
            workspace or tmp_path / "repo",
            config=_config(**config),
            session_id=session_id,
            state_dir=tmp_path / f"state-{session_id}",
        )
        created.append(backend)
        return backend

    (tmp_path / "repo").mkdir(exist_ok=True)
    yield make

    for backend in created:
        # Close kernels on the running loop so subprocess transports are not
        # finalized after it shuts down.
        await backend.close(remove_container=False)
        subprocess.run(  # noqa: S603,S607 - deterministic cleanup
            ["docker", "rm", "--force", backend.container_name],
            capture_output=True,
            check=False,
        )


async def test_python_executes_inside_the_container_and_not_on_this_host(
    containers, tmp_path, monkeypatch
):
    monkeypatch.setenv("RLM_TEST_SECRET", "leaked")
    repo = tmp_path / "repo"
    (repo / "existing.py").write_text("value = 1\n", encoding="utf-8")
    backend = containers("isolation")
    await backend.start()

    hostname = await backend.execute("root", "import socket; socket.gethostname()")
    identity = await backend.execute("root", "import os; os.getuid()")
    passwd = await backend.execute("root", "open('/etc/passwd').read()")
    secret = await backend.execute("root", "import os; os.environ.get('RLM_TEST_SECRET', 'absent')")
    written = await backend.execute("root", "workspace.write('made_inside.txt', 'hello\\n')")

    assert hostname.value_repr.strip("'\"") != socket.gethostname()
    assert identity.value_repr == "0" or identity.error is None
    assert "root:x:0:0" in passwd.value_repr
    assert secret.value_repr == "'absent'"
    assert written.error is None
    # The bind mount is the only thing that crosses, and it crosses on purpose.
    assert (repo / "made_inside.txt").read_text(encoding="utf-8") == "hello\n"


async def test_commands_and_completion_gates_run_inside_the_boundary(containers):
    """A gate on the host would defeat the boundary it is meant to verify."""
    backend = containers("gates")
    await backend.start()

    inside = await backend.execute("root", "import socket; socket.gethostname()")
    gate = await backend.shell("hostname && pwd")

    assert gate.returncode == 0
    assert inside.value_repr.strip("'\"")[:12] in gate.stdout
    assert "/workspace" in gate.stdout
    assert socket.gethostname() not in gate.stdout


async def test_root_and_children_get_separate_namespaces_in_one_container(containers, tmp_path):
    backend = containers("namespaces")
    await backend.start()
    await backend.create_kernel("root")
    await backend.create_kernel("agent-1")

    await backend.execute("root", "only_in_root = 'root value'")
    child_view = await backend.execute("agent-1", "only_in_root")
    await backend.execute("agent-1", "workspace.write('from_child.txt', 'child\\n')")
    root_view = await backend.execute("root", "workspace.read('from_child.txt')")

    assert "NameError" in (child_view.error or "")
    # Separate namespaces, one shared repository: children see each other's work.
    # `read` returns joined lines, as the host namespace does, so no trailing newline.
    assert root_view.value_repr == "'child'"


async def test_a_timed_out_cell_is_replaced_from_the_last_checkpoint(containers):
    backend = containers("cell-timeout", python_timeout=1)
    await backend.start()
    await backend.execute("root", "stable = 42")

    timed_out = await backend.execute("root", "import time; time.sleep(30)")
    restored = await backend.execute("root", "stable")

    assert "timed out after 1s" in str(timed_out.error)
    assert restored.error is None
    assert restored.value_repr == "42"


async def test_read_only_policy_is_enforced_by_the_workspace_mount(containers, tmp_path):
    repo = tmp_path / "readonly-repo"
    repo.mkdir()
    source = repo / "kept.txt"
    source.write_text("original\n", encoding="utf-8")
    backend = containers("read-only", workspace=repo, allow_write=False)
    await backend.start()

    wrapped = await backend.execute("root", "workspace.write('kept.txt', 'changed')")
    direct = await backend.execute("root", "open('kept.txt', 'w').write('changed')")

    assert "Writing is disabled" in (wrapped.error or "")
    assert "Read-only file system" in (direct.error or "")
    assert source.read_text(encoding="utf-8") == "original\n"


async def test_state_and_the_container_survive_a_detached_reattach(containers):
    first = containers("reattach")
    started = await first.start()
    await first.execute("root", "carried = 'survives the restart'")
    # Leave the container running, as closing the TUI would.
    await first.close(remove_container=False)

    second = containers("reattach")
    reattached = await second.start()
    recovered = await second.execute("root", "carried")

    assert reattached.sandbox_id == started.sandbox_id
    # The kernel process is new, so continuity comes from the checkpoint. It is
    # restored before the first execution, because the checkpoint written after
    # that execution would otherwise overwrite the state being recovered.
    assert recovered.value_repr == "'survives the restart'"
    assert recovered.error is None


async def test_supervisor_recovery_verifies_the_live_docker_boundary(containers, tmp_path):
    backend = containers("supervisor-recovery")
    identity = await backend.start()
    runtime = tmp_path / "worker-runtime.json"
    runtime.write_text(
        json.dumps({"sandbox": identity.to_dict()}),
        encoding="utf-8",
    )
    request = tmp_path / "worker-request.json"
    request.write_text(
        json.dumps(
            {
                "agent_id": "agent-docker",
                "worker_pid": os.getpid(),
                "runtime_path": str(runtime),
            }
        ),
        encoding="utf-8",
    )
    agent = {
        "id": "agent-docker",
        "prompt": "work",
        "parent_id": "root",
        "status": "running",
        "created_at": time.time(),
        "worker_pid": os.getpid(),
        "worker_request_path": str(request),
        "sandbox": {"backend": "docker", "session_id": identity.session_id},
        "children": [],
    }
    journal = tmp_path / "docker.agents.jsonl"
    journal.write_text(
        json.dumps({"type": "agent.worker_started", "agent": agent}) + "\n",
        encoding="utf-8",
    )

    live = AgentSupervisor(asyncio.get_running_loop(), journal_path=journal)
    assert live.snapshot("agent-docker")["status"] == "running"
    assert live.snapshot("agent-docker")["sandbox"]["sandbox_id"] == identity.sandbox_id

    await backend.close()
    stopped = AgentSupervisor(asyncio.get_running_loop(), journal_path=journal)
    assert stopped.snapshot("agent-docker")["status"] == "interrupted"


async def test_the_host_never_unpickles_state_the_sandbox_produced(containers, monkeypatch):
    """Restoring model-influenced pickles on the host would be an escape."""
    backend = containers("pickles")
    await backend.start()
    await backend.execute("root", "payload = {'value': 42}")

    def refuse(*_args, **_kwargs):
        raise AssertionError("The host must never unpickle sandbox state")

    monkeypatch.setattr(pickle, "loads", refuse)

    reference = await backend.checkpoint("root")
    restored = await backend.restore("root", reference)

    assert reference.inside_boundary is True
    assert reference.ok is True
    assert reference.digest and reference.size > 0
    assert "payload" in restored


async def test_a_whole_session_runs_its_python_inside_the_container(tmp_path):
    """The wiring test: selecting the profile has to actually move execution."""
    from superqode.pipy import ToolCall, ToolResultMessage
    from superqode.pipy.ai import FakeStream, text_response, tool_response
    from superqode.pipy.stream import Model
    from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions

    repo = tmp_path / "repo"
    repo.mkdir()
    session = await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=repo,
            model=Model(id="fake-rlm", provider="fake", api="fake-api"),
            stream_fn=FakeStream(
                [
                    tool_response(
                        ToolCall(
                            id="p1",
                            name="python",
                            arguments={"code": "import socket; socket.gethostname()"},
                        )
                    ),
                    text_response("done"),
                ]
            ),
            session_root=tmp_path / "sessions",
            sandbox=_config(),
        )
    )
    try:
        await session.prompt("where does this run")

        context = await session.session.build_context()
        results = [m for m in context.messages if isinstance(m, ToolResultMessage)]
        reported = results[-1].text.strip().strip("'\"")

        assert [tool.name for tool in session.tools] == ["python"]
        assert reported != socket.gethostname()
        assert session.sandbox_backend is not None
        assert session.sandbox_backend.identity.backend == "docker"
    finally:
        backend = session.sandbox_backend
        if backend is not None:
            await backend.close()


async def test_a_sessions_completion_gates_run_inside_the_container(tmp_path):
    """A gate on the host would report on the wrong machine."""
    from superqode.pipy.ai import FakeStream
    from superqode.pipy.stream import Model
    from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions
    from superqode.rlm.policy import run_completion_gates

    repo = tmp_path / "repo"
    repo.mkdir()
    session = await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=repo,
            model=Model(id="fake-rlm", provider="fake", api="fake-api"),
            stream_fn=FakeStream([]),
            session_root=tmp_path / "sessions",
            sandbox=_config(),
        )
    )
    try:
        results = await run_completion_gates(
            ["hostname", "test -d /workspace"],
            cwd=repo,
            timeout=60,
            runner=session.gate_runner,
        )

        assert session.gate_runner is not None
        assert [result.ok for result in results] == [True, True]
        assert results[0].stdout.strip() != socket.gethostname()
    finally:
        backend = session.sandbox_backend
        if backend is not None:
            await backend.close()


async def test_recursion_from_inside_the_container_spawns_on_the_host(tmp_path):
    """`rlm.run` cannot run in the sandbox: it needs the supervisor and keys."""
    from superqode.pipy import ToolCall, ToolResultMessage
    from superqode.pipy.ai import FakeStream, text_response, tool_response
    from superqode.pipy.stream import Model
    from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions

    repo = tmp_path / "repo"
    repo.mkdir()
    session = await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=repo,
            model=Model(id="fake-rlm", provider="fake", api="fake-api"),
            stream_fn=FakeStream(
                [
                    tool_response(
                        ToolCall(
                            id="p1",
                            name="python",
                            arguments={"code": "child = rlm.run('child work')\nchild.wait()"},
                        )
                    ),
                    text_response("child finished"),
                    text_response("root finished"),
                ]
            ),
            session_root=tmp_path / "sessions",
            sandbox=_config(),
        )
    )
    from superqode.rlm.coding_session import _BACKENDS

    try:
        await session.prompt("delegate")

        context = await session.session.build_context()
        results = [m for m in context.messages if isinstance(m, ToolResultMessage)]

        assert "child finished" in results[-1].text
        # One container for the session: the child joined it rather than
        # starting a second one.
        listed = subprocess.run(  # noqa: S603,S607 - verification
            ["docker", "ps", "--filter", "label=superqode.rlm.kind=kernel", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert len([line for line in listed.stdout.splitlines() if line.strip()]) == 1
    finally:
        # Root and child hold separate backend objects for one container.
        for backend in list(_BACKENDS.values()):
            await backend.close()
        _BACKENDS.clear()


async def test_the_profile_can_close_the_network(containers):
    backend = containers("no-network")
    await backend.start()

    result = await backend.execute(
        "root",
        "import socket; socket.create_connection(('1.1.1.1', 53), timeout=5)",
    )

    assert result.error is not None
    assert "Network is unreachable" in result.error or "Temporary failure" in result.error
