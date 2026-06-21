"""Import Omnigent agent YAML into SuperQode HarnessSpec objects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .loader import save_harness_spec
from .spec import (
    AgentSpec,
    ContextSpec,
    ExecutionPolicySpec,
    HarnessFlavor,
    HarnessSpec,
    ModelPolicySpec,
    RuntimeSpec,
    WorkflowMode,
    WorkflowSpec,
)


_HARNESS_BACKEND_MAP = {
    "claude-sdk": "claude-agent-sdk",
    "openai-agents": "openai-agents",
    "open-responses": "openai-agents",
    "codex": "codex-sdk",
    "codex-native": "codex-sdk",
    "claude-native": "claude-agent-sdk",
    "pi": "runtime",
}

_OS_TOOL_NAMES = {
    "read_file",
    "write_file",
    "edit_file",
    "bash",
    "grep",
    "glob",
    "local_code_search",
    "repo_search",
}


def load_omnigent_agent(path: str | Path) -> dict[str, Any]:
    """Load an Omnigent agent YAML file as a mapping."""
    spec_path = Path(path).expanduser()
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Omnigent agent spec must be a mapping: {spec_path}")
    return data


def import_omnigent_agent(
    path: str | Path,
    *,
    output: str | Path | None = None,
    name: str | None = None,
) -> HarnessSpec | Path:
    """Convert an Omnigent agent YAML file and optionally write it to disk."""
    source_path = Path(path).expanduser()
    spec = omnigent_agent_to_harness_spec(
        load_omnigent_agent(source_path),
        source_path=source_path,
        name=name,
    )
    if output is None:
        return spec
    return save_harness_spec(spec, output)


def omnigent_agent_to_harness_spec(
    data: dict[str, Any],
    *,
    source_path: str | Path | None = None,
    name: str | None = None,
    source_label: str = "omnigent",
    metadata_key: str = "omnigent",
) -> HarnessSpec:
    """Convert an Omnigent agent mapping into a SuperQode HarnessSpec."""
    source = Path(source_path).expanduser() if source_path is not None else None
    base_dir = source.parent if source is not None else Path.cwd()
    omnigent_name = str(data.get("name") or "omnigent-agent").strip() or "omnigent-agent"
    spec_name = name or omnigent_name
    executor = _dict(data.get("executor"))
    harness_name = str(executor.get("harness") or "builtin").strip()
    runtime_backend = _HARNESS_BACKEND_MAP.get(harness_name, harness_name or "builtin")
    model = _string_or_none(executor.get("model"))
    model_profile = _executor_profile(executor)
    instruction_files, system_prompt = _resolve_instructions(data, base_dir)
    tool_entries = _dict(data.get("tools"))
    main_tools = _tool_names(tool_entries)
    subagents = _subagent_specs(
        tool_entries,
        base_dir=base_dir,
        source_label=source_label,
        metadata_key=metadata_key,
    )
    skills_filter = _skills_filter(data.get("skills"))
    mcp_servers = _mcp_servers(tool_entries)
    os_env = _dict(data.get("os_env"))
    execution_policy = _execution_policy(os_env, main_tools)
    agents = (
        AgentSpec(
            id=_safe_id(omnigent_name),
            role=str(data.get("description") or "Imported Omnigent agent"),
            model=model,
            system_prompt=system_prompt,
            tools=main_tools,
            skills=tuple(skills_filter) if isinstance(skills_filter, list) else (),
            delegates_to=tuple(agent.id for agent in subagents),
            config={
                "source": source_label,
                "executor": executor,
                **({"skills_filter": skills_filter} if skills_filter != "all" else {}),
                **({f"{metadata_key}_tools": tool_entries} if tool_entries else {}),
                **({"mcp_servers": mcp_servers} if mcp_servers else {}),
            },
        ),
        *subagents,
    )
    workflow = WorkflowSpec(
        mode=WorkflowMode.ORCHESTRATOR if subagents else WorkflowMode.SINGLE,
        parallelism=max(1, int(data.get("parallelism") or len(subagents) or 1)),
        config={"source": source_label} if subagents else {},
    )

    metadata: dict[str, Any] = {
        "source": source_label,
        metadata_key: {
            "name": omnigent_name,
            "executor_harness": harness_name,
            **({"source_path": str(source)} if source is not None else {}),
        },
    }
    for key in (
        "policies",
        "params",
        "terminals",
        "async",
        "cancellable",
        "timers",
        "skills",
    ):
        if key in data:
            metadata[metadata_key][key] = data[key]

    return HarnessSpec(
        name=spec_name,
        description=str(data.get("description") or f"Imported from Omnigent agent {omnigent_name}"),
        flavor=HarnessFlavor.CODING,
        runtime=RuntimeSpec(
            backend=runtime_backend,
            config={
                f"{metadata_key}_harness": harness_name,
                **({"mcp_servers": mcp_servers} if mcp_servers else {}),
            },
        ),
        model_policy=ModelPolicySpec(
            primary=model,
            profile=model_profile,
            config=_model_policy_config(executor),
        ),
        execution_policy=execution_policy,
        agents=agents,
        workflow=workflow,
        context=ContextSpec(
            instruction_files=instruction_files or ContextSpec().instruction_files,
        ),
        metadata=metadata,
    )


def _resolve_instructions(
    data: dict[str, Any], base_dir: Path
) -> tuple[tuple[str, ...], str | None]:
    instructions = data.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        value = instructions.strip()
        candidate = (base_dir / value).expanduser()
        if "\n" not in value and candidate.exists():
            return (value,), None
        return (), value
    prompt = data.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return (), prompt.strip()
    return (), None


def _execution_policy(os_env: dict[str, Any], tools: tuple[str, ...]) -> ExecutionPolicySpec:
    if not os_env:
        return ExecutionPolicySpec(
            sandbox="local",
            allow_read=bool(set(tools) & _OS_TOOL_NAMES),
            allow_write=False,
            allow_shell=False,
        )

    sandbox_spec = _dict(os_env.get("sandbox"))
    sandbox_type = str(sandbox_spec.get("type") or "local").strip() or "local"
    sandbox = "none" if sandbox_type == "none" else "local"
    has_os = True
    allow_shell = has_os
    allow_write = bool(sandbox_spec.get("write_paths") or sandbox_type == "none")
    allow_network = bool(
        sandbox_spec.get("allow_network", False) or sandbox_spec.get("egress_rules")
    )
    return ExecutionPolicySpec(
        sandbox=sandbox,
        allow_read=True,
        allow_write=allow_write,
        allow_shell=allow_shell,
        allow_network=allow_network,
        config={"omnigent_os_env": os_env, "omnigent_sandbox": sandbox_spec},
    )


def _tool_names(tools: dict[str, Any], *, include_inherit: bool = False) -> tuple[str, ...]:
    names: list[str] = []
    for name, spec in tools.items():
        if _is_subagent_tool(spec):
            continue
        if str(spec).strip().lower() in {"inherit", "self"}:
            if include_inherit:
                names.append(str(name))
            continue
        names.append(str(name))
    return tuple(names)


def _subagent_specs(
    tools: dict[str, Any],
    *,
    base_dir: Path | None = None,
    source_label: str = "omnigent",
    metadata_key: str = "omnigent",
) -> tuple[AgentSpec, ...]:
    agents: list[AgentSpec] = []
    resolved_base_dir = base_dir or Path.cwd()
    for name, raw in tools.items():
        spec = _dict(raw)
        if not _is_subagent_tool(spec):
            continue
        executor = _dict(spec.get("executor"))
        skills_filter = _skills_filter(spec.get("skills"))
        instruction_files, system_prompt = _resolve_instructions(spec, resolved_base_dir)
        child_tools = _dict(spec.get("tools"))
        child_mcp_servers = _mcp_servers(child_tools)
        preserved: dict[str, Any] = {}
        for key in (
            "policies",
            "params",
            "terminals",
            "async",
            "cancellable",
            "timers",
            "output_schema",
        ):
            if key in spec:
                preserved[key] = spec[key]
        agents.append(
            AgentSpec(
                id=_safe_id(str(name)),
                role=str(spec.get("description") or name),
                model=_string_or_none(executor.get("model")),
                system_prompt=system_prompt,
                tools=_tool_names(child_tools, include_inherit=True),
                skills=tuple(skills_filter) if isinstance(skills_filter, list) else (),
                max_iterations=_int_or_none(spec.get("max_iterations"))
                or _int_or_none(spec.get("max_sessions")),
                output_schema=_dict(spec.get("output_schema")) or None,
                config={
                    "source": source_label,
                    "executor": executor,
                    "executor_harness": _string_or_none(executor.get("harness")),
                    "runtime_backend": _HARNESS_BACKEND_MAP.get(
                        str(executor.get("harness") or "").strip(),
                        _string_or_none(executor.get("harness")),
                    ),
                    "model_profile": _executor_profile(executor),
                    "model_config": _model_policy_config(executor),
                    "pass_history": bool(spec.get("pass_history", False)),
                    "os_env": spec.get("os_env"),
                    **({"instruction_files": instruction_files} if instruction_files else {}),
                    **({f"{metadata_key}_tools": child_tools} if child_tools else {}),
                    **({"mcp_servers": child_mcp_servers} if child_mcp_servers else {}),
                    **({"skills_filter": skills_filter} if skills_filter != "all" else {}),
                    **({metadata_key: preserved} if preserved else {}),
                },
            )
        )
    return tuple(agents)


def _is_subagent_tool(value: Any) -> bool:
    return isinstance(value, dict) and value.get("type") == "agent"


def _mcp_servers(tools: dict[str, Any]) -> dict[str, Any]:
    servers: dict[str, Any] = {}
    for name, raw in tools.items():
        spec = _dict(raw)
        if spec.get("type") != "mcp":
            continue
        servers[str(name)] = {
            key: value
            for key, value in spec.items()
            if key in {"command", "args", "url", "headers", "env", "tools", "description"}
        }
    return servers


def _executor_profile(executor: dict[str, Any]) -> str | None:
    auth = executor.get("auth")
    if isinstance(auth, dict):
        profile = _string_or_none(auth.get("profile"))
        if profile:
            return profile
    return _string_or_none(executor.get("profile"))


def _model_policy_config(executor: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    auth = executor.get("auth")
    if isinstance(auth, dict):
        config["auth"] = auth
    legacy_profile = _string_or_none(executor.get("profile"))
    if legacy_profile:
        config["legacy_executor_profile"] = legacy_profile
    for key in ("base_url", "reasoning", "temperature", "context_window"):
        if key in executor:
            config[key] = executor[key]
    return config


def _skills_filter(value: Any) -> str | list[str]:
    if value is None:
        return "all"
    if isinstance(value, str):
        text = value.strip()
        if text in {"all", "none"}:
            return text
        return "all"
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return "all"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_id(value: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "agent"
