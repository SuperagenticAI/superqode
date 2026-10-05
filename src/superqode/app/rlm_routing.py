"""Persist new RLM routing profiles without changing an existing worker."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from superqode.harness.loader import save_harness_spec
from superqode.rlm.delegation_policy import DelegationPolicy


def save_routing_profile(spec, config: dict, root: Path) -> Path:
    if spec is None or spec.runtime.backend != "rlm":
        raise ValueError("Select a native RLM harness before configuring A2A.")
    DelegationPolicy.from_config(config)
    name = f"rlm-routing-{uuid4().hex[:12]}"
    profile = replace(
        spec,
        name=name,
        description="Native RLM with explicitly configured optional A2A routing.",
        runtime=replace(
            spec.runtime, config={**deepcopy(spec.runtime.config), "a2a": deepcopy(config)}
        ),
        metadata={**deepcopy(spec.metadata), "customized_from": spec.name},
    )
    return save_harness_spec(profile, root / ".superqode" / "harnesses" / f"{name}.yaml")


def save_runtime_profile(spec, config: dict, root: Path) -> Path:
    from superqode.rlm.budget import BudgetPolicy
    from superqode.rlm.profile import RLMProfile
    from superqode.rlm.sandbox import RLMSandboxConfig

    if spec is None or spec.runtime.backend != "rlm":
        raise ValueError("Select a native RLM harness before configuring its profile")
    selected = RLMProfile.from_config(config)
    sandbox = RLMSandboxConfig.from_config(config, execution_policy=spec.execution_policy)
    selected.validate_sandbox(sandbox)
    BudgetPolicy.from_config(config.get("budget"))
    DelegationPolicy.from_config(config.get("a2a"))
    name = f"rlm-profile-{uuid4().hex[:12]}"
    profile = replace(
        spec,
        name=name,
        description=f"Native RLM: {selected.tool_surface}, {selected.observations} observations.",
        runtime=replace(spec.runtime, config=deepcopy(config)),
        execution_policy=replace(
            spec.execution_policy,
            sandbox=sandbox.backend,
            allow_read=sandbox.policy.allow_read,
            allow_write=sandbox.policy.allow_write,
            allow_shell=sandbox.policy.allow_shell,
            allow_network=sandbox.allow_network,
        ),
        agents=tuple(replace(agent, tools=selected.tools) for agent in spec.agents),
        metadata={
            **deepcopy(spec.metadata),
            "customized_from": spec.name,
            "model_tool_count": len(selected.tools),
            "pure_permissions": not sandbox.isolated,
            "selection_warning": "Host execution uses process permissions."
            if not sandbox.isolated
            else f"{sandbox.backend} execution boundary; networking {'on' if sandbox.allow_network else 'off'}.",
            "experimental": selected.tool_surface != "python"
            or selected.observations != "transcript",
        },
    )
    return save_harness_spec(profile, root / ".superqode" / "harnesses" / f"{name}.yaml")
