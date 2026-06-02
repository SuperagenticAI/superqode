"""Tests for the local OS sandbox command builder.

Enforcement is platform-specific (Seatbelt/bwrap), so these tests pin the
deterministic planning logic: which backend, which argv, write/network policy.
"""

from pathlib import Path

import pytest

from superqode.sandbox import local_sandbox as ls
from superqode.sandbox.local_sandbox import (
    MODE_DANGER,
    MODE_OFF,
    MODE_READ_ONLY,
    MODE_WORKSPACE_WRITE,
    build_sandboxed_command,
    current_mode,
)


def test_off_mode_does_not_wrap(monkeypatch):
    monkeypatch.setenv("SUPERQODE_SANDBOX", "off")
    plan = build_sandboxed_command("ls", Path("/tmp"))
    assert plan.applied is False
    assert plan.argv == ["/bin/sh", "-c", "ls"]


def test_danger_mode_does_not_wrap(monkeypatch):
    monkeypatch.setenv("SUPERQODE_SANDBOX", "danger-full-access")
    plan = build_sandboxed_command("ls", Path("/tmp"))
    assert plan.applied is False


def test_invalid_mode_falls_back_to_off(monkeypatch):
    monkeypatch.setenv("SUPERQODE_SANDBOX", "nonsense")
    assert current_mode() == MODE_OFF


def test_no_backend_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(ls, "_backend_for_platform", lambda: "none")
    plan = build_sandboxed_command("ls", Path("/tmp"), mode=MODE_WORKSPACE_WRITE)
    assert plan.applied is False
    assert plan.backend == "none"
    assert plan.argv == ["/bin/sh", "-c", "ls"]


def test_seatbelt_workspace_write_profile(monkeypatch):
    monkeypatch.setattr(ls, "_backend_for_platform", lambda: "seatbelt")
    plan = build_sandboxed_command("echo hi", Path("/work/proj"), mode=MODE_WORKSPACE_WRITE)
    assert plan.applied and plan.backend == "seatbelt"
    assert plan.argv[0] == "sandbox-exec"
    profile = plan.argv[2]
    assert "(deny file-write*)" in profile
    assert "/work/proj" in profile  # workspace is writable
    assert "(deny network*)" not in profile  # network allowed in workspace-write


def test_seatbelt_read_only_denies_network_and_workspace_write(monkeypatch):
    monkeypatch.setattr(ls, "_backend_for_platform", lambda: "seatbelt")
    plan = build_sandboxed_command("echo hi", Path("/work/proj"), mode=MODE_READ_ONLY)
    profile = plan.argv[2]
    assert "(deny network*)" in profile
    # read-only must NOT make the workspace writable (only temp dirs).
    assert "/work/proj" not in profile
    assert '(subpath "/tmp")' in profile


def test_bwrap_workspace_write(monkeypatch):
    monkeypatch.setattr(ls, "_backend_for_platform", lambda: "bwrap")
    plan = build_sandboxed_command("echo hi", Path("/work/proj"), mode=MODE_WORKSPACE_WRITE)
    assert plan.applied and plan.backend == "bwrap"
    assert plan.argv[0] == "bwrap"
    assert "--ro-bind" in plan.argv
    assert "--bind" in plan.argv  # workspace bound rw
    assert "--unshare-net" not in plan.argv  # network allowed


def test_bwrap_read_only_unshares_network(monkeypatch):
    monkeypatch.setattr(ls, "_backend_for_platform", lambda: "bwrap")
    plan = build_sandboxed_command("echo hi", Path("/work/proj"), mode=MODE_READ_ONLY)
    assert "--unshare-net" in plan.argv
    assert plan.argv[-3:] == ["/bin/sh", "-c", "echo hi"]
