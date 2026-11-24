"""Per-task Code, Plan, and permission overlays for a native desktop harness.

The saved HarnessSpec stays unchanged. Ask is the safe default when the
desktop sends a permission mode. A missing mode leaves the spec alone so
older clients and tests keep their current behavior.
"""

from __future__ import annotations

from dataclasses import replace

MODES = {"code", "chat", "plan"}
PERMISSIONS = {"ask", "auto-edit", "full"}
REASONING_EFFORTS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
READ_TOOLS = {
    "read",
    "read_file",
    "list_directory",
    "grep",
    "glob",
    "search",
    "code_search",
    "local_code_search",
    "repo_search",
    "diagnostics",
}
PLAN_NOTE = (
    "Plan mode is active. Inspect the repository and write a plan the person can review. "
    "Do not edit files, run shell commands, or use the network."
)


def enforces_session_controls(backend) -> bool:
    """True when this backend pauses for Ask and honors the compiled execution policy.

    PiPy, DeepSeek Harness, and other runtimes that keep their own tools do not.
    A missing or unknown backend does not count as builtin.
    """
    if not isinstance(backend, str) or not backend.strip():
        return False
    from superqode.harness.backends.registry import create_harness_backend

    try:
        return bool(create_harness_backend(backend).capabilities.supports_approvals)
    except ValueError:
        return False


def accept(params: dict) -> None:
    """Validate and canonicalize task controls. Raise before a job is stored."""
    mode = params.get("interaction_mode") or "code"
    if mode not in MODES:
        raise ValueError("Choose Code, Plan, or Chat")
    params["interaction_mode"] = mode
    raw_effort = params.get("reasoning_effort")
    if raw_effort in (None, "", "auto", "default"):
        params.pop("reasoning_effort", None)
    else:
        effort = str(raw_effort).strip().lower()
        if effort not in REASONING_EFFORTS:
            raise ValueError(
                "Choose a supported reasoning effort: off, minimal, low, medium, high, xhigh, or max"
            )
        params["reasoning_effort"] = effort
    raw = params.get("permission_mode")
    if raw in (None, ""):
        params.pop("permission_mode", None)
        return
    if raw not in PERMISSIONS:
        raise ValueError("Choose Ask, Auto-edit, or Full")
    params["permission_mode"] = "ask" if mode == "chat" else raw


def apply_controls(spec, request: dict):
    """Return a run-only spec. Plan mode closes write, shell, and network."""
    mode = request.get("interaction_mode") or "code"
    permission = request.get("permission_mode")
    reasoning = request.get("reasoning_effort")
    if mode not in MODES or (permission is not None and permission not in PERMISSIONS):
        raise ValueError("This task has an unsupported mode or permission")
    if reasoning:
        effort = str(reasoning).strip().lower()
        if effort not in REASONING_EFFORTS:
            raise ValueError("This task has an unsupported reasoning effort")
        spec = replace(spec, model_policy=replace(spec.model_policy, reasoning=effort))
    if mode != "plan" and not permission:
        return spec
    policy = spec.execution_policy
    groups = {
        "read": "allow",
        "search": "allow",
        "diagnostics": "allow",
        "write": "ask",
        "shell": "ask",
        "network": "deny",
        "agent": "ask",
    }
    if permission == "auto-edit" and policy.allow_write:
        groups["write"] = "allow"
    if permission == "full":
        if policy.allow_write:
            groups["write"] = "allow"
        if policy.allow_shell:
            groups["shell"] = "allow"
        groups["agent"] = "allow"
        groups["network"] = "ask" if policy.allow_network else "deny"
    agents = spec.agents
    runtime = spec.runtime
    if mode == "plan":
        if spec.model_policy.profile == "silicon":
            runtime = replace(
                runtime,
                config={
                    key: value for key, value in runtime.config.items() if key != "silicon_mcp"
                },
            )
        groups = {**groups, "write": "deny", "shell": "deny", "network": "deny", "agent": "deny"}
        policy = replace(policy, allow_write=False, allow_shell=False, allow_network=False)
        if agents:
            agent = agents[0]
            current = agent.tools
            if not current or current == ("full",):
                tools = ("read", "read_file", "list_directory", "grep", "glob")
            else:
                tools = tuple(tool for tool in current if tool in READ_TOOLS) or ("read",)
            prompt = ((agent.system_prompt or "").rstrip() + "\n\n" + PLAN_NOTE).strip()
            agents = (replace(agent, tools=tools, system_prompt=prompt),) + agents[1:]
    config = dict(policy.config)
    config["group_permissions"] = groups
    config["default_permission"] = "allow" if permission == "full" and mode != "plan" else "ask"
    approval = {"ask": "careful", "auto-edit": "balanced", "full": "yolo"}.get(
        permission or "ask", "careful"
    )
    if mode == "plan":
        approval = "careful"
    return replace(
        spec,
        agents=agents,
        runtime=runtime,
        checks=replace(spec.checks, enabled=False) if mode == "plan" else spec.checks,
        execution_policy=replace(policy, config=config, approval_profile=approval),
    )
