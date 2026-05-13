"""Sandbox backend capabilities for SuperQode harness profiles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict

from ..tools.permissions import Permission, PermissionConfig, ToolGroup


class SandboxBackend(str, Enum):
    """Supported sandbox backends."""

    LOCAL = "local"
    READ_ONLY = "read-only"
    NO_SHELL = "no-shell"
    GIT_WORKTREE = "git-worktree"
    DOCKER = "docker"
    E2B = "e2b"
    DAYTONA = "daytona"
    MODAL = "modal"
    VERCEL = "vercel"
    RUNLOOP = "runloop"
    AGENTCORE = "agentcore"
    LANGSMITH = "langsmith"
    REMOTE = "remote"


@dataclass(frozen=True)
class SandboxCapabilities:
    """Capabilities granted by a sandbox backend."""

    backend: SandboxBackend
    can_read: bool
    can_write: bool
    can_shell: bool
    can_network: bool
    description: str


def get_sandbox_capabilities(backend: str | SandboxBackend) -> SandboxCapabilities:
    """Return capabilities for a sandbox backend."""
    selected = SandboxBackend(backend)
    capabilities: Dict[SandboxBackend, SandboxCapabilities] = {
        SandboxBackend.LOCAL: SandboxCapabilities(
            selected, True, True, True, True, "Local workspace with full tool access."
        ),
        SandboxBackend.READ_ONLY: SandboxCapabilities(
            selected,
            True,
            False,
            False,
            False,
            "Read-only workspace; no writes, shell, or network.",
        ),
        SandboxBackend.NO_SHELL: SandboxCapabilities(
            selected, True, True, False, True, "Local workspace without shell execution."
        ),
        SandboxBackend.GIT_WORKTREE: SandboxCapabilities(
            selected, True, True, True, True, "Git worktree-isolated workspace."
        ),
        SandboxBackend.DOCKER: SandboxCapabilities(
            selected, True, True, True, True, "Container-isolated workspace."
        ),
        SandboxBackend.E2B: SandboxCapabilities(
            selected, True, True, True, True, "E2B remote sandbox workspace."
        ),
        SandboxBackend.DAYTONA: SandboxCapabilities(
            selected, True, True, True, True, "Daytona remote sandbox workspace."
        ),
        SandboxBackend.MODAL: SandboxCapabilities(
            selected, True, True, True, True, "Modal cloud sandbox workspace."
        ),
        SandboxBackend.VERCEL: SandboxCapabilities(
            selected, True, True, True, True, "Vercel Sandbox cloud workspace."
        ),
        SandboxBackend.RUNLOOP: SandboxCapabilities(
            selected, True, True, True, True, "Runloop remote devbox workspace."
        ),
        SandboxBackend.AGENTCORE: SandboxCapabilities(
            selected, True, True, True, True, "Amazon Bedrock AgentCore Code Interpreter sandbox."
        ),
        SandboxBackend.LANGSMITH: SandboxCapabilities(
            selected, True, True, True, True, "LangSmith remote sandbox workspace."
        ),
        SandboxBackend.REMOTE: SandboxCapabilities(
            selected, True, True, True, True, "Remote sandbox backend."
        ),
    }
    return capabilities[selected]


def apply_backend_permissions(
    config: PermissionConfig,
    backend: str | SandboxBackend,
) -> PermissionConfig:
    """Apply backend capability restrictions to an existing permission config."""
    caps = get_sandbox_capabilities(backend)
    groups = dict(config.groups)
    tools = dict(config.tools)

    if not caps.can_read:
        groups[ToolGroup.READ] = Permission.DENY
        groups[ToolGroup.SEARCH] = Permission.DENY
        groups[ToolGroup.DIAGNOSTICS] = Permission.DENY
    if not caps.can_write:
        groups[ToolGroup.WRITE] = Permission.DENY
    if not caps.can_shell:
        groups[ToolGroup.SHELL] = Permission.DENY
        tools["bash"] = Permission.DENY
    if not caps.can_network:
        groups[ToolGroup.NETWORK] = Permission.DENY
        tools["fetch"] = Permission.DENY
        tools["download"] = Permission.DENY
        tools["web_search"] = Permission.DENY
        tools["web_fetch"] = Permission.DENY

    return PermissionConfig(
        default=config.default,
        groups=groups,
        tools=tools,
        allow_patterns=list(config.allow_patterns),
        deny_patterns=list(config.deny_patterns),
    )
