"""Compile HarnessSpec objects into today's runtime-facing profiles."""

from __future__ import annotations

from .spec import HarnessFlavor, HarnessSpec
from ..agent.system_prompts import SystemPromptLevel
from ..headless import HarnessProfile, get_harness_profiles
from ..tools.permissions import Permission, PermissionConfig, ToolGroup


def spec_from_headless_profile(name: str) -> HarnessSpec:
    """Return a HarnessSpec equivalent for an existing headless profile."""
    from .spec import AgentSpec, ExecutionPolicySpec, RuntimeSpec, ValidationSpec

    profiles = get_harness_profiles()
    if name not in profiles:
        valid = ", ".join(sorted(profiles))
        raise ValueError(f"Unknown profile {name!r}. Valid profiles: {valid}")
    profile = profiles[name]
    flavor = HarnessFlavor.NO_TOOL if profile.name == "no-tool" else HarnessFlavor.CODING
    tools = tuple(profile.tools or ("full",))
    allow_write = _profile_allows_write(profile)
    allow_shell = profile.permissions.get_permission("bash") != Permission.DENY

    return HarnessSpec(
        name=profile.name,
        description=profile.description,
        flavor=flavor,
        runtime=RuntimeSpec(backend="builtin"),
        execution_policy=ExecutionPolicySpec(
            sandbox="none" if flavor == HarnessFlavor.NO_TOOL else "local",
            approval_profile="deny" if flavor == HarnessFlavor.NO_TOOL else "balanced",
            allow_read=flavor != HarnessFlavor.NO_TOOL,
            allow_write=allow_write,
            allow_shell=allow_shell,
            allow_network=False,
        ),
        agents=(
            AgentSpec(
                id=_agent_id_for_profile(profile.name),
                role=profile.name,
                tools=() if flavor == HarnessFlavor.NO_TOOL else tools,
                skills=(),
                system_prompt=profile.job_description or None,
            ),
        ),
        validation=ValidationSpec(enabled=profile.name == "build"),
        metadata={
            "source": "headless_profile",
            "system_level": profile.system_level.value,
        },
    )


def compile_to_headless_profile(spec: HarnessSpec) -> HarnessProfile:
    """Compile a HarnessSpec to the current ``HarnessProfile`` shape.

    This is the compatibility bridge for P1: new specs can drive existing
    headless/runtime code before the full HarnessKernel exists.
    """
    if spec.flavor == HarnessFlavor.NO_TOOL:
        return HarnessProfile(
            name=spec.name,
            description=spec.description or "Model-only reasoning profile.",
            system_level=SystemPromptLevel.NO_TOOL,
            tools=[],
            permissions=PermissionConfig(default=Permission.DENY),
            job_description=_primary_agent_prompt(spec),
        )

    permissions = _permission_config_from_spec(spec)
    tools = _tool_names_from_spec(spec)
    return HarnessProfile(
        name=spec.name,
        description=spec.description or "Coding harness profile.",
        system_level=_system_level_from_spec(spec),
        tools=tools,
        permissions=permissions,
        job_description=_primary_agent_prompt(spec),
    )


def _permission_config_from_spec(spec: HarnessSpec) -> PermissionConfig:
    default = Permission.ALLOW
    groups: dict[ToolGroup, Permission] = {}
    if not spec.execution_policy.allow_write:
        groups[ToolGroup.WRITE] = Permission.DENY
    if not spec.execution_policy.allow_shell:
        groups[ToolGroup.SHELL] = Permission.DENY
    if not spec.execution_policy.allow_network:
        groups[ToolGroup.NETWORK] = Permission.DENY
    return PermissionConfig(default=default, groups=groups)


def _tool_names_from_spec(spec: HarnessSpec) -> list[str] | None:
    if spec.flavor == HarnessFlavor.NO_TOOL:
        return []
    if not spec.agents:
        return None
    tools = spec.agents[0].tools
    if not tools or tools == ("full",):
        return None
    return list(tools)


def _system_level_from_spec(spec: HarnessSpec) -> SystemPromptLevel:
    if spec.flavor == HarnessFlavor.NO_TOOL:
        return SystemPromptLevel.NO_TOOL
    profile = (spec.model_policy.profile or "").lower()
    if profile in {"ds4-coding", "gemma4-coding"}:
        return SystemPromptLevel.MINIMAL
    return SystemPromptLevel.FULL


def _primary_agent_prompt(spec: HarnessSpec) -> str:
    if not spec.agents:
        return ""
    agent = spec.agents[0]
    return agent.system_prompt or ""


def _profile_allows_write(profile: HarnessProfile) -> bool:
    return (
        profile.permissions.get_permission("write_file") != Permission.DENY
        or profile.permissions.get_permission("edit_file") != Permission.DENY
    )


def _agent_id_for_profile(name: str) -> str:
    if name == "no-tool":
        return "reasoner"
    if name == "review":
        return "reviewer"
    if name == "plan":
        return "planner"
    return "coder"
