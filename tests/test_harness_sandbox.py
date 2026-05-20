"""Tests for harness sandbox connector contract."""

import pytest

from superqode.harness import (
    HarnessSandboxBackend,
    LocalSandboxBackend,
    SandboxCapabilityBackend,
    SandboxPolicy,
    apply_backend_permissions,
    get_sandbox_capabilities,
    get_harness_template,
    sandbox_policy_from_execution_policy,
    supported_openai_sandbox_backends,
)
from superqode.tools.permissions import Permission, PermissionConfig, ToolGroup


def test_local_sandbox_read_list_stat_grep_and_glob(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    sandbox = LocalSandboxBackend(tmp_path, policy=SandboxPolicy(allow_read=True))

    assert sandbox.read_file("src/app.py") == "print('hello')"
    assert sandbox.list_files("src")[0].path == "/src/app.py"
    assert sandbox.stat("src/app.py").is_file is True
    assert sandbox.exists("src/app.py") is True
    assert sandbox.grep("hello", path="src") == "src/app.py:1:print('hello')"
    assert sandbox.glob("src/*.py") == "src/app.py"


def test_harness_sandbox_backend_protocol_is_exported():
    assert HarnessSandboxBackend is not None


def test_local_sandbox_blocks_path_escape(tmp_path):
    sandbox = LocalSandboxBackend(tmp_path, policy=SandboxPolicy(allow_read=True))

    with pytest.raises(ValueError, match="Path escapes sandbox root"):
        sandbox.read_file("../outside.txt")


def test_local_sandbox_write_policy(tmp_path):
    readonly = LocalSandboxBackend(tmp_path, policy=SandboxPolicy(allow_read=True))

    with pytest.raises(PermissionError, match="Write access is disabled"):
        readonly.write_file("a.txt", "nope")

    writable = LocalSandboxBackend(
        tmp_path, policy=SandboxPolicy(allow_read=True, allow_write=True)
    )
    writable.write_file("a.txt", "one")
    writable.edit_file("a.txt", "one", "two")

    assert writable.read_file("a.txt") == "two"


def test_local_sandbox_shell_policy_and_allowlist(tmp_path):
    sandbox = LocalSandboxBackend(
        tmp_path,
        policy=SandboxPolicy(
            allow_read=True,
            allow_shell=True,
            allowed_commands=("python",),
        ),
    )

    result = sandbox.shell("python -c 'print(123)'")
    assert result.success is True
    assert result.stdout.strip() == "123"

    with pytest.raises(PermissionError, match="Command is not allowed"):
        sandbox.shell("echo hi")


def test_local_sandbox_blocks_compound_commands_by_default(tmp_path):
    sandbox = LocalSandboxBackend(
        tmp_path,
        policy=SandboxPolicy(allow_read=True, allow_shell=True, allowed_commands=("python",)),
    )

    with pytest.raises(PermissionError, match="Compound shell syntax is disabled"):
        sandbox.shell("python -V && python -V")


def test_sandbox_policy_from_execution_policy_clamps_no_tool_template():
    spec = get_harness_template("no-tool")
    policy = sandbox_policy_from_execution_policy(spec.execution_policy)

    assert policy.allow_read is False
    assert policy.allow_write is False
    assert policy.allow_shell is False


def test_harness_sandbox_capabilities_are_single_source():
    caps = get_sandbox_capabilities(SandboxCapabilityBackend.READ_ONLY)

    assert caps.can_read is True
    assert caps.can_write is False
    assert caps.can_shell is False
    assert caps.can_network is False


def test_harness_apply_backend_permissions_clamps_tools():
    config = PermissionConfig(
        groups={ToolGroup.WRITE: Permission.ALLOW, ToolGroup.SHELL: Permission.ALLOW},
        tools={"bash": Permission.ALLOW},
    )

    restricted = apply_backend_permissions(config, "no-shell")

    assert restricted.groups[ToolGroup.WRITE] is Permission.ALLOW
    assert restricted.groups[ToolGroup.SHELL] is Permission.DENY
    assert restricted.tools["bash"] is Permission.DENY


def test_harness_lists_openai_sandbox_backends():
    assert set(supported_openai_sandbox_backends()) == {
        "local",
        "docker",
        "e2b",
        "daytona",
        "modal",
        "vercel",
        "runloop",
        "blaxel",
        "cloudflare",
    }
