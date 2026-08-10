"""Contract tests for RLM sandbox selection and host-mode guardrails.

These cover what host mode can honestly promise: a harness's declared execution
policy now reaches the Python namespace, and a boundary this build cannot
provide refuses to start instead of running on the host anyway.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.rlm import _session_ref
from superqode.harness.templates import rlm_template
from superqode.pipy.ai import FakeStream
from superqode.pipy.stream import Model
from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions
from superqode.rlm.kernel import PersistentPythonKernel, Shell, Workspace
from superqode.rlm.sandbox import (
    RLMSandboxConfig,
    SandboxPolicyError,
    SandboxUnavailableError,
    resolved_env,
)

MODEL = Model(id="fake-rlm", provider="fake", api="fake-api")


def _config(**config) -> RLMSandboxConfig:
    return RLMSandboxConfig.from_config(config)


def test_the_built_in_harness_keeps_the_permissions_it_shipped_with():
    """1A must not tighten anything for an existing RLM session."""
    spec = rlm_template()

    config = RLMSandboxConfig.from_config(
        spec.runtime.config, execution_policy=spec.execution_policy
    )

    assert config.backend == "host"
    assert config.isolated is False
    assert config.policy.allow_read is True
    assert config.policy.allow_write is True
    assert config.policy.allow_shell is True
    assert config.policy.allowed_commands == ()


def test_a_spec_that_denies_writes_now_reaches_the_python_namespace(tmp_path):
    """The kernel previously ignored its own harness execution policy."""
    source = tmp_path / "a.py"
    source.write_text("value = 1\n", encoding="utf-8")
    workspace = Workspace(tmp_path, sandbox=_config(allow_write=False))

    assert "value = 1" in workspace.read("a.py")
    with pytest.raises(SandboxPolicyError):
        workspace.write("a.py", "value = 2")
    with pytest.raises(SandboxPolicyError):
        workspace.edit("a.py", "1", "2")
    assert source.read_text(encoding="utf-8") == "value = 1\n"


def test_reading_can_be_denied_across_every_repository_call(tmp_path):
    (tmp_path / "a.py").write_text("value = 1\n", encoding="utf-8")
    workspace = Workspace(tmp_path, sandbox=_config(allow_read=False))

    for call in (
        lambda: workspace.read("a.py"),
        lambda: workspace.glob("*.py"),
        lambda: workspace.search("value"),
    ):
        with pytest.raises(SandboxPolicyError):
            call()


def test_the_command_allowlist_and_compound_rules_are_enforced(tmp_path):
    shell = Shell(
        tmp_path,
        sandbox=_config(allowed_commands=["echo"], allow_compound_commands=False),
    )

    assert shell.run(["echo", "ok"]).stdout.strip() == "ok"
    with pytest.raises(SandboxPolicyError):
        shell.run(["rm", "-rf", str(tmp_path)])
    with pytest.raises(SandboxPolicyError):
        shell.run("echo ok && rm -rf /")


def test_shell_execution_can_be_denied_outright(tmp_path):
    with pytest.raises(SandboxPolicyError):
        Shell(tmp_path, sandbox=_config(allow_shell=False)).run(["echo", "ok"])


def test_an_env_allowlist_keeps_host_variables_out_of_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("RLM_TEST_SECRET", "leaked")
    shell = Shell(tmp_path, sandbox=_config(env_allowlist=["PATH", "HOME"]))

    result = shell.run(
        [sys.executable, "-c", "import os; print(os.environ.get('RLM_TEST_SECRET', 'absent'))"]
    )

    assert result.stdout.strip() == "absent"


def test_without_an_allowlist_the_full_host_environment_is_inherited(monkeypatch):
    monkeypatch.setenv("RLM_TEST_SECRET", "present")

    assert resolved_env(_config())["RLM_TEST_SECRET"] == "present"
    assert "RLM_TEST_SECRET" not in resolved_env(_config(env_allowlist=["PATH"]))


def test_the_profile_round_trips_through_a_detached_worker_request():
    """A child rebuilds this from JSON, so the two directions must agree."""
    config = _config(
        allow_write=False,
        allow_network=False,
        allowed_commands=["pytest"],
        allow_compound_commands=False,
        env_allowlist=["PATH"],
    )

    restored = RLMSandboxConfig.from_config(json.loads(json.dumps(config.to_dict())))

    assert restored == config


def test_an_unimplemented_backend_refuses_instead_of_running_on_the_host(monkeypatch):
    """Pinned to the mechanism, so it keeps holding as backends are added."""
    monkeypatch.setattr("superqode.rlm.sandbox.IMPLEMENTED_BACKENDS", ("host",))
    config = _config(sandbox="docker")

    assert config.isolated is True
    with pytest.raises(SandboxUnavailableError):
        config.require_available()


def test_an_implemented_backend_is_accepted():
    assert _config(sandbox="docker").require_available().backend == "docker"


def test_an_unknown_backend_is_rejected_rather_than_ignored():
    with pytest.raises(ValueError):
        _config(sandbox="e2b")
    with pytest.raises(ValueError):
        _config(sandbox_granularity="thread")


def test_every_name_for_no_boundary_resolves_to_host():
    for name in ("", "none", "host", "local", "local-os"):
        assert _config(sandbox=name).backend == "host"


async def test_a_session_will_not_start_without_the_boundary_it_asked_for(tmp_path, monkeypatch):
    monkeypatch.setattr("superqode.rlm.sandbox.IMPLEMENTED_BACKENDS", ("host",))
    options = RLMCodingSessionOptions(
        cwd=tmp_path,
        model=MODEL,
        stream_fn=FakeStream([]),
        session_root=tmp_path / "sessions",
        sandbox=_config(sandbox="docker"),
    )

    with pytest.raises(SandboxUnavailableError):
        await RLMCodingSession.create(options)


async def test_the_session_kernel_receives_the_resolved_profile(tmp_path):
    options = RLMCodingSessionOptions(
        cwd=tmp_path,
        model=MODEL,
        stream_fn=FakeStream([]),
        session_root=tmp_path / "sessions",
        sandbox=_config(allow_write=False, allowed_commands=["pytest"]),
    )

    session = await RLMCodingSession.create(options)

    from superqode.rlm.kernel import kernel_for

    kernel = kernel_for(str(session.session_path.resolve()), tmp_path)
    assert kernel.sandbox.policy.allow_write is False
    assert kernel.workspace.sandbox.policy.allowed_commands == ("pytest",)
    assert kernel.shell.sandbox is kernel.sandbox


def test_the_backend_resolves_the_profile_where_the_spec_is_in_scope(tmp_path):
    """Only the backend holds both runtime config and the execution policy."""
    spec = rlm_template()
    request = HarnessBackendRequest(
        spec=spec,
        prompt="hi",
        provider="fake",
        model="fake-rlm",
        working_directory=tmp_path,
    )

    ref = _session_ref(request)

    assert ref.metadata["rlm_sandbox"]["sandbox"] == "host"
    assert ref.metadata["rlm_sandbox"]["allow_write"] is True
    assert ref.metadata["rlm_sandbox"]["isolated"] is False


async def test_a_detached_child_inherits_the_root_boundary(tmp_path, monkeypatch):
    """The worker is a separate process, so the profile must survive JSON."""
    import asyncio

    from superqode.rlm.supervisor import AgentRecord, AgentSupervisor
    from superqode.rlm.worker_process import run_durable_child

    supervisor = AgentSupervisor(
        asyncio.get_running_loop(), journal_path=tmp_path / "root.agents.jsonl"
    )
    record = AgentRecord(id="agent-child", prompt="work", parent_id="root", status="running")
    supervisor._records[record.id] = record

    class Process:
        pid = os.getpid()

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return None

    monkeypatch.setattr("superqode.rlm.worker_process.subprocess.Popen", lambda *a, **k: Process())
    monkeypatch.setattr(
        "superqode.rlm.worker_process._read_json",
        lambda path: {"status": "completed", "result": "done"},
    )
    options = RLMCodingSessionOptions(
        cwd=tmp_path,
        model=MODEL,
        sandbox=_config(allow_write=False, allowed_commands=["pytest"]),
    )

    assert await run_durable_child(record, options=options, supervisor=supervisor) == "done"

    request = json.loads(Path(record.worker_request_path).read_text(encoding="utf-8"))
    assert RLMSandboxConfig.from_config(request["sandbox"]) == options.sandbox


def test_a_default_kernel_keeps_host_permissions(tmp_path):
    """No configuration at all must behave exactly as the release does."""
    kernel = PersistentPythonKernel(tmp_path)

    assert kernel.sandbox.backend == "host"
    assert kernel.sandbox.policy.allow_write is True
    assert kernel.shell.run(["echo", "ok"]).stdout.strip() == "ok"
    assert os.environ.get("PATH") == resolved_env(kernel.sandbox).get("PATH")
    assert Path(kernel.cwd) == tmp_path.resolve()
