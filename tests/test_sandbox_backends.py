"""Tests for sandbox backend capability policies."""

from superqode.sandbox import apply_backend_permissions, get_sandbox_capabilities
from superqode.tools.permissions import Permission, PermissionConfig, ToolGroup


def test_read_only_backend_denies_write_shell_and_network():
    config = PermissionConfig(default=Permission.ALLOW)
    restricted = apply_backend_permissions(config, "read-only")

    assert get_sandbox_capabilities("read-only").can_write is False
    assert restricted.get_permission("write_file") == Permission.DENY
    assert restricted.get_permission("bash") == Permission.DENY
    assert restricted.get_permission("fetch") == Permission.DENY


def test_no_shell_backend_only_denies_shell_group():
    config = PermissionConfig(default=Permission.ALLOW, groups={ToolGroup.WRITE: Permission.ALLOW})
    restricted = apply_backend_permissions(config, "no-shell")

    assert restricted.get_permission("bash") == Permission.DENY
    assert restricted.get_permission("write_file") == Permission.ALLOW


def test_remote_provider_backends_have_full_capabilities():
    for backend in (
        "docker",
        "e2b",
        "daytona",
        "modal",
        "vercel",
        "runloop",
        "agentcore",
        "langsmith",
    ):
        caps = get_sandbox_capabilities(backend)
        assert caps.can_read is True
        assert caps.can_write is True
        assert caps.can_shell is True
        assert caps.can_network is True
