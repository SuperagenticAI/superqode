"""Load SuperQode harness specs from dictionaries, YAML, or JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .spec import (
    AgentSpec,
    ContextSpec,
    ExecutionPolicySpec,
    HarnessFlavor,
    HarnessSpec,
    ModelPolicySpec,
    ObservabilitySpec,
    RuntimeSpec,
    ValidationSpec,
    ValidationStepSpec,
    WorkflowMode,
    WorkflowSpec,
)


def load_harness_spec(path: str | Path) -> HarnessSpec:
    """Load a harness spec from a YAML or JSON file."""
    spec_path = Path(path).expanduser()
    raw = spec_path.read_text(encoding="utf-8")
    if spec_path.suffix.lower() == ".json":
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Harness spec must be a mapping: {spec_path}")
    return harness_spec_from_dict(data)


def harness_spec_from_dict(data: dict[str, Any]) -> HarnessSpec:
    """Build a ``HarnessSpec`` from a Python mapping.

    Accepts either a bare spec mapping or ``{"harness": {...}}`` so it can be
    embedded in future ``superqode.yaml`` layouts.
    """
    raw = dict(data.get("harness") if isinstance(data.get("harness"), dict) else data)
    flavor = _flavor(raw.get("flavor", HarnessFlavor.CODING.value))
    name = str(raw.get("name") or f"superqode-{flavor.value}").strip()
    if not name:
        raise ValueError("Harness spec requires a non-empty name")

    return HarnessSpec(
        name=name,
        version=int(raw.get("version", 1) or 1),
        description=str(raw.get("description", "") or ""),
        flavor=flavor,
        runtime=_runtime(raw.get("runtime")),
        model_policy=_model_policy(raw.get("model_policy")),
        execution_policy=_execution_policy(raw.get("execution_policy"), flavor),
        agents=_agents(raw.get("agents")),
        workflow=_workflow(raw.get("workflow")),
        context=_context(raw.get("context")),
        validation=_validation(raw.get("validation")),
        observability=_observability(raw.get("observability")),
        metadata=dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {},
    )


def harness_spec_to_dict(spec: HarnessSpec) -> dict[str, Any]:
    """Serialize a harness spec to a YAML/JSON-friendly dictionary."""
    return {
        "version": spec.version,
        "name": spec.name,
        "description": spec.description,
        "flavor": spec.flavor.value,
        "runtime": {
            "backend": spec.runtime.backend,
            "fallback_backends": list(spec.runtime.fallback_backends),
            **({"config": spec.runtime.config} if spec.runtime.config else {}),
        },
        "model_policy": {
            key: value
            for key, value in {
                "primary": spec.model_policy.primary,
                "fallbacks": list(spec.model_policy.fallbacks),
                "profile": spec.model_policy.profile,
                "temperature": spec.model_policy.temperature,
                "context_window": spec.model_policy.context_window,
                "reasoning": spec.model_policy.reasoning,
                "local_hardware": spec.model_policy.local_hardware,
                "tool_call_format": spec.model_policy.tool_call_format,
                "config": spec.model_policy.config or None,
            }.items()
            if value not in (None, [], {})
        },
        "execution_policy": {
            "sandbox": spec.execution_policy.sandbox,
            "approval_profile": spec.execution_policy.approval_profile,
            "allow_read": spec.execution_policy.allow_read,
            "allow_write": spec.execution_policy.allow_write,
            "allow_shell": spec.execution_policy.allow_shell,
            "allow_network": spec.execution_policy.allow_network,
            "allowed_commands": list(spec.execution_policy.allowed_commands),
            "blocked_categories": list(spec.execution_policy.blocked_categories),
        },
        "agents": [
            {
                key: value
                for key, value in {
                    "id": agent.id,
                    "role": agent.role,
                    "model": agent.model,
                    "system_prompt": agent.system_prompt,
                    "tools": list(agent.tools),
                    "skills": list(agent.skills),
                    "delegates_to": list(agent.delegates_to),
                    "max_iterations": agent.max_iterations,
                    "output_schema": agent.output_schema,
                    "config": agent.config or None,
                }.items()
                if value not in (None, "", [], {})
            }
            for agent in spec.agents
        ],
        "workflow": {
            "mode": spec.workflow.mode.value,
            "max_task_depth": spec.workflow.max_task_depth,
            "parallelism": spec.workflow.parallelism,
            "merge_strategy": spec.workflow.merge_strategy,
        },
        "context": {
            "instruction_files": list(spec.context.instruction_files),
            "skills_dir": spec.context.skills_dir,
            "roles_dir": spec.context.roles_dir,
            "session_storage": spec.context.session_storage,
            "compaction": spec.context.compaction,
            "memory": spec.context.memory,
        },
        "validation": {
            "enabled": spec.validation.enabled,
            "fail_on_error": spec.validation.fail_on_error,
            "timeout_seconds": spec.validation.timeout_seconds,
            "custom_steps": [
                {
                    "name": step.name,
                    "command": step.command,
                    "enabled": step.enabled,
                    "timeout": step.timeout,
                }
                for step in spec.validation.custom_steps
            ],
        },
        "observability": {
            "events": spec.observability.events,
            "traces": spec.observability.traces,
            "run_store": spec.observability.run_store,
        },
        "metadata": spec.metadata,
    }


def _runtime(value: Any) -> RuntimeSpec:
    data = value if isinstance(value, dict) else {}
    return RuntimeSpec(
        backend=str(data.get("backend") or "builtin"),
        fallback_backends=_str_tuple(data.get("fallback_backends") or data.get("fallbacks")),
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _model_policy(value: Any) -> ModelPolicySpec:
    data = value if isinstance(value, dict) else {}
    return ModelPolicySpec(
        primary=str(data["primary"]) if data.get("primary") else None,
        fallbacks=_str_tuple(data.get("fallbacks") or data.get("fallback")),
        profile=str(data["profile"]) if data.get("profile") else None,
        temperature=float(data["temperature"]) if data.get("temperature") is not None else None,
        context_window=int(data["context_window"]) if data.get("context_window") else None,
        reasoning=str(data["reasoning"]) if data.get("reasoning") else None,
        local_hardware=str(data["local_hardware"]) if data.get("local_hardware") else None,
        tool_call_format=str(data["tool_call_format"]) if data.get("tool_call_format") else None,
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _execution_policy(value: Any, flavor: HarnessFlavor) -> ExecutionPolicySpec:
    data = value if isinstance(value, dict) else {}
    no_tool = flavor == HarnessFlavor.NO_TOOL
    return ExecutionPolicySpec(
        sandbox=str(data.get("sandbox") or "local"),
        approval_profile=str(data.get("approval_profile") or "balanced"),
        allow_read=False if no_tool else bool(data.get("allow_read", True)),
        allow_write=False if no_tool else bool(data.get("allow_write", False)),
        allow_shell=False if no_tool else bool(data.get("allow_shell", False)),
        allow_network=False if no_tool else bool(data.get("allow_network", False)),
        allowed_commands=() if no_tool else _str_tuple(data.get("allowed_commands")),
        blocked_categories=_str_tuple(data.get("blocked_categories")),
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _agents(value: Any) -> tuple[AgentSpec, ...]:
    if not isinstance(value, list):
        return ()
    out: list[AgentSpec] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"Agent spec at index {index} must be a mapping")
        agent_id = str(item.get("id") or "").strip()
        if not agent_id:
            raise ValueError(f"Agent spec at index {index} requires id")
        out.append(
            AgentSpec(
                id=agent_id,
                role=str(item.get("role") or ""),
                model=str(item["model"]) if item.get("model") else None,
                system_prompt=str(item["system_prompt"]) if item.get("system_prompt") else None,
                tools=_str_tuple(item.get("tools")),
                skills=_str_tuple(item.get("skills")),
                delegates_to=_str_tuple(item.get("delegates_to")),
                max_iterations=int(item["max_iterations"]) if item.get("max_iterations") else None,
                output_schema=dict(item["output_schema"])
                if isinstance(item.get("output_schema"), dict)
                else None,
                config=dict(item.get("config") or {}) if isinstance(item.get("config"), dict) else {},
            )
        )
    return tuple(out)


def _workflow(value: Any) -> WorkflowSpec:
    data = value if isinstance(value, dict) else {}
    return WorkflowSpec(
        mode=_workflow_mode(data.get("mode", WorkflowMode.SINGLE.value)),
        max_task_depth=int(data.get("max_task_depth", 4) or 0),
        parallelism=int(data.get("parallelism", 1) or 1),
        merge_strategy=str(data.get("merge_strategy") or "summary"),
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _context(value: Any) -> ContextSpec:
    data = value if isinstance(value, dict) else {}
    return ContextSpec(
        instruction_files=_str_tuple(
            data.get("instruction_files") or ("AGENTS.md", "CLAUDE.md", "SUPERQODE.md")
        ),
        skills_dir=str(data.get("skills_dir") or ".agents/skills"),
        roles_dir=str(data.get("roles_dir") or ".agents/roles"),
        session_storage=str(data.get("session_storage") or ".superqode/sessions"),
        compaction=dict(data.get("compaction") or {})
        if isinstance(data.get("compaction"), dict)
        else {},
        memory=dict(data.get("memory") or {}) if isinstance(data.get("memory"), dict) else {},
    )


def _validation(value: Any) -> ValidationSpec:
    data = value if isinstance(value, dict) else {}
    steps: list[ValidationStepSpec] = []
    for index, item in enumerate(data.get("custom_steps") or ()):
        if not isinstance(item, dict):
            raise ValueError(f"Validation step at index {index} must be a mapping")
        steps.append(
            ValidationStepSpec(
                name=str(item.get("name") or f"step-{index + 1}"),
                command=str(item.get("command") or ""),
                enabled=bool(item.get("enabled", True)),
                timeout=int(item.get("timeout", data.get("timeout_seconds", 300)) or 0),
            )
        )
    return ValidationSpec(
        enabled=bool(data.get("enabled", False)),
        fail_on_error=bool(data.get("fail_on_error", False)),
        timeout_seconds=int(data.get("timeout_seconds", 300) or 0),
        custom_steps=tuple(steps),
        config={k: v for k, v in data.items() if k not in {"enabled", "fail_on_error", "timeout_seconds", "custom_steps"}},
    )


def _observability(value: Any) -> ObservabilitySpec:
    data = value if isinstance(value, dict) else {}
    return ObservabilitySpec(
        events=bool(data.get("events", True)),
        traces=bool(data.get("traces", False)),
        run_store=str(data.get("run_store") or "memory"),
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _flavor(value: Any) -> HarnessFlavor:
    normalized = str(value or HarnessFlavor.CODING.value).strip().lower().replace("-", "_")
    if normalized in {"none", "notool", "model_only"}:
        normalized = HarnessFlavor.NO_TOOL.value
    try:
        return HarnessFlavor(normalized)
    except ValueError as exc:
        valid = ", ".join(item.value for item in HarnessFlavor)
        raise ValueError(f"Unknown harness flavor {value!r}. Valid flavors: {valid}") from exc


def _workflow_mode(value: Any) -> WorkflowMode:
    normalized = str(value or WorkflowMode.SINGLE.value).strip().lower().replace("-", "_")
    try:
        return WorkflowMode(normalized)
    except ValueError as exc:
        valid = ", ".join(item.value for item in WorkflowMode)
        raise ValueError(f"Unknown workflow mode {value!r}. Valid modes: {valid}") from exc


def _str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value)
    return (str(value),)
