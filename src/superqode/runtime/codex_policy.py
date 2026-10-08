"""Reject host policies that Codex's approval protocol cannot fully enforce."""

from superqode.governance import active_governance, load_governance
from superqode.tools.permissions import Permission, load_permission_config


def preflight(config, permission_manager):
    bundle = load_governance(config.working_directory)
    active = active_governance()
    for policy in (bundle, active):
        if policy is None:
            continue
        constrained = policy.network_strict or bool(policy.broker.bindings)
        constrained = (
            constrained
            or getattr(policy, "shell_env", "inherit") != "inherit"
            or bool(getattr(policy, "allowed_hosts", ()))
        )
        constrained = constrained or any(
            any(rule.action != "allow" for rule in layer.rules)
            or any(action != "allow" for action in layer.defaults.values())
            for layer in policy.engine.layers
        )
        if constrained:
            raise RuntimeError(
                "Codex CLI cannot guarantee this SuperQode organization/project policy for every tool call. Use a SuperQode-governed runtime or enforce the policy through Codex managed requirements. No Codex task was started."
            )
    # Re-read the project policy before every turn, including while connected.
    configurations = [load_permission_config(config.working_directory, strict=True)]
    if permission_manager is not None:
        configurations.append(permission_manager.config)
    for permissions in configurations:
        if (
            permissions.default == Permission.DENY
            or permissions.deny_patterns
            or Permission.DENY in permissions.tools.values()
            or Permission.DENY in permissions.groups.values()
        ):
            raise RuntimeError(
                "Codex CLI cannot guarantee SuperQode tool/path deny rules for actions that do not request approval. Use a SuperQode-governed runtime or Codex managed requirements. No Codex task was started."
            )
