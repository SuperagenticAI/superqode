"""Tests for harness sandbox connector contract."""

import pytest

from superqode.harness import (
    LocalSandboxBackend,
    SandboxPolicy,
    get_harness_template,
    sandbox_policy_from_execution_policy,
)


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
