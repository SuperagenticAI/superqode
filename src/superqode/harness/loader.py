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
    HookRuleSpec,
    HooksSpec,
    ModelPolicySpec,
    PermissionRuleSpec,
    ObservabilitySpec,
    OptimizationSpec,
    RecursionSpec,
    RemoteHarnessSpec,
    RuntimeSpec,
    ChecksSpec,
    CheckStepSpec,
    WorkflowMode,
    WorkflowSpec,
)
from .workflow_presets import apply_workflow_preset


def load_harness_spec(path: str | Path) -> HarnessSpec:
    """Load a harness spec from a YAML or JSON file."""
    spec_path = Path(path).expanduser()
    data = _load_harness_data(spec_path)
    resolved = resolve_harness_inheritance(data, base_dir=spec_path.parent, seen=())
    return harness_spec_from_dict(resolved)


def _load_harness_data(spec_path: Path) -> dict[str, Any]:
    raw = spec_path.read_text(encoding="utf-8")
    if spec_path.suffix.lower() == ".json":
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Harness spec must be a mapping: {spec_path}")
    return data


def resolve_harness_inheritance(
    data: dict[str, Any],
    *,
    base_dir: str | Path | None = None,
    seen: tuple[str, ...] = (),
    max_depth: int = 16,
) -> dict[str, Any]:
    """Resolve ``inherits`` / ``extends`` on raw HarnessSpec dictionaries.

    Composition happens before dataclass construction so omitted child fields
    remain distinguishable from explicit default-looking values.
    """
    raw = dict(data.get("harness") if isinstance(data.get("harness"), dict) else data)
    inherited = raw.get("inherits", raw.get("extends"))
    if not inherited:
        return raw
    if not isinstance(inherited, str) or not inherited.strip():
        raise ValueError("Harness inherits/extends must be a non-empty string")
    if len(seen) >= max_depth:
        chain = " -> ".join((*seen, inherited))
        raise ValueError(f"Harness inheritance depth exceeded {max_depth}: {chain}")

    base_payload, base_token, child_base_dir = _load_inherited_harness(
        inherited.strip(), Path(base_dir or ".")
    )
    if base_token in seen:
        chain = " -> ".join((*seen, base_token))
        raise ValueError(f"Harness inheritance cycle detected: {chain}")
    resolved_base = resolve_harness_inheritance(
        base_payload,
        base_dir=child_base_dir,
        seen=(*seen, base_token),
        max_depth=max_depth,
    )
    return _deep_merge_dicts(resolved_base, raw)


def _load_inherited_harness(name: str, base_dir: Path) -> tuple[dict[str, Any], str, Path]:
    candidate = Path(name).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    if candidate.is_file():
        resolved = candidate.resolve()
        return _load_harness_data(resolved), str(resolved), resolved.parent

    from .templates import get_harness_template

    try:
        template = get_harness_template(name)
    except ValueError as exc:
        raise ValueError(
            f"Unable to resolve inherited harness {name!r} as a file or built-in template"
        ) from exc
    return harness_spec_to_dict(template), f"template:{name.strip().lower()}", base_dir


def _deep_merge_dicts(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    merged = dict(parent)
    for key, child_value in child.items():
        if key == "extends":
            continue
        parent_value = merged.get(key)
        if isinstance(parent_value, dict) and isinstance(child_value, dict):
            merged[key] = _deep_merge_dicts(parent_value, child_value)
        else:
            merged[key] = child_value
    return merged


def save_harness_spec(spec: HarnessSpec, path: str | Path) -> Path:
    """Write a harness spec to YAML or JSON and return the resolved path."""
    spec_path = Path(path).expanduser()
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    data = harness_spec_to_dict(spec)
    if spec_path.suffix.lower() == ".json":
        spec_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        spec_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return spec_path


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

    spec = HarnessSpec(
        name=name,
        inherits=str(raw["inherits"]) if raw.get("inherits") else None,
        version=int(raw.get("version", 1) or 1),
        description=str(raw.get("description", "") or ""),
        flavor=flavor,
        runtime=_runtime(raw.get("runtime")),
        model_policy=_model_policy(raw.get("model_policy")),
        execution_policy=_execution_policy(raw.get("execution_policy"), flavor),
        agents=_agents(raw.get("agents")),
        workflow=_workflow(raw.get("workflow")),
        recursion=_recursion(raw.get("recursion")),
        remote_harness=_remote_harness(raw.get("remote_harness")),
        context=_context(raw.get("context")),
        checks=_checks(raw.get("checks")),
        observability=_observability(raw.get("observability")),
        hooks=_hooks(raw.get("hooks")),
        optimization=_optimization(raw.get("optimization")),
        metadata=dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {},
    )
    return apply_workflow_preset(spec)


def harness_spec_to_dict(spec: HarnessSpec) -> dict[str, Any]:
    """Serialize a harness spec to a YAML/JSON-friendly dictionary."""
    return {
        "version": spec.version,
        "name": spec.name,
        **({"inherits": spec.inherits} if spec.inherits else {}),
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
                "pack": spec.model_policy.pack,
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
            **(
                {
                    "permission_rules": [
                        {
                            key: value
                            for key, value in {
                                "tool": rule.tool,
                                "pattern": rule.pattern,
                                "action": rule.action,
                                "argument": rule.argument,
                            }.items()
                            if value not in ("", None)
                        }
                        for rule in spec.execution_policy.permission_rules
                    ]
                }
                if spec.execution_policy.permission_rules
                else {}
            ),
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
            **({"preset": spec.workflow.preset} if spec.workflow.preset else {}),
            "max_task_depth": spec.workflow.max_task_depth,
            "parallelism": spec.workflow.parallelism,
            "merge_strategy": spec.workflow.merge_strategy,
            **({"config": spec.workflow.config} if spec.workflow.config else {}),
        },
        **(
            {
                "recursion": {
                    "enabled": spec.recursion.enabled,
                    "max_depth": spec.recursion.max_depth,
                    "max_children": spec.recursion.max_children,
                    "max_parallel": spec.recursion.max_parallel,
                    "max_wall_seconds": spec.recursion.max_wall_seconds,
                    **(
                        {"max_budget": spec.recursion.max_budget}
                        if spec.recursion.max_budget is not None
                        else {}
                    ),
                    **(
                        {"child_model": spec.recursion.child_model}
                        if spec.recursion.child_model
                        else {}
                    ),
                    "child_sandbox": spec.recursion.child_sandbox,
                    "write_policy": spec.recursion.write_policy,
                    **({"config": spec.recursion.config} if spec.recursion.config else {}),
                }
            }
            if spec.recursion.enabled or spec.recursion.config
            else {}
        ),
        **(
            {
                "remote_harness": {
                    "enabled": spec.remote_harness.enabled,
                    "provider": spec.remote_harness.provider,
                    **(
                        {"agent_id": spec.remote_harness.agent_id}
                        if spec.remote_harness.agent_id
                        else {}
                    ),
                    **(
                        {"region": spec.remote_harness.region} if spec.remote_harness.region else {}
                    ),
                    "context_policy": spec.remote_harness.context_policy,
                    **(
                        {"config": spec.remote_harness.config} if spec.remote_harness.config else {}
                    ),
                }
            }
            if spec.remote_harness.enabled
            or spec.remote_harness.provider
            or spec.remote_harness.config
            else {}
        ),
        "context": {
            "instruction_files": list(spec.context.instruction_files),
            "skills_dir": spec.context.skills_dir,
            "roles_dir": spec.context.roles_dir,
            "session_storage": spec.context.session_storage,
            "prompt_persistence": spec.context.prompt_persistence,
            "compaction": spec.context.compaction,
            "memory": spec.context.memory,
        },
        "checks": {
            "enabled": spec.checks.enabled,
            "fail_on_error": spec.checks.fail_on_error,
            "timeout_seconds": spec.checks.timeout_seconds,
            "custom_steps": [
                {
                    "name": step.name,
                    "command": step.command,
                    "enabled": step.enabled,
                    "timeout": step.timeout,
                }
                for step in spec.checks.custom_steps
            ],
        },
        "observability": {
            "events": spec.observability.events,
            "traces": spec.observability.traces,
            "local": spec.observability.local,
            "exporters": list(spec.observability.exporters),
            "run_store": spec.observability.run_store,
            **({"config": spec.observability.config} if spec.observability.config else {}),
        },
        **(
            {
                "hooks": {
                    "enabled": spec.hooks.enabled,
                    "rules": [
                        {
                            key: value
                            for key, value in {
                                "point": rule.point,
                                "handler": rule.handler,
                                "matcher": rule.matcher,
                                "name": rule.name,
                                "config": rule.config or None,
                            }.items()
                            if value not in (None, "", {})
                        }
                        for rule in spec.hooks.rules
                    ],
                }
            }
            if spec.hooks.rules or not spec.hooks.enabled
            else {}
        ),
        **(
            {
                "optimization": {
                    "enabled": spec.optimization.enabled,
                    "require_human_apply": spec.optimization.require_human_apply,
                    "editable_surfaces": list(spec.optimization.editable_surfaces),
                    "protected_surfaces": list(spec.optimization.protected_surfaces),
                    "heldout_fraction": spec.optimization.heldout_fraction,
                    **(
                        {"max_candidate_edits": spec.optimization.max_candidate_edits}
                        if spec.optimization.max_candidate_edits is not None
                        else {}
                    ),
                    **(
                        {"config": spec.optimization.config}
                        if spec.optimization.config
                        else {}
                    ),
                }
            }
            if _include_optimization(spec.optimization)
            else {}
        ),
        "metadata": spec.metadata,
    }


def harness_spec_json_schema() -> dict[str, Any]:
    """Return a JSON Schema for HarnessSpec YAML/JSON files."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "SuperQode HarnessSpec",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "version": {"type": "integer", "minimum": 1},
            "name": {"type": "string", "minLength": 1},
            "inherits": {"type": "string", "minLength": 1},
            "extends": {"type": "string", "minLength": 1},
            "description": {"type": "string"},
            "flavor": {"type": "string", "enum": [item.value for item in HarnessFlavor]},
            "runtime": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "backend": {"type": "string"},
                    "fallback_backends": {"type": "array", "items": {"type": "string"}},
                    "fallbacks": {"type": "array", "items": {"type": "string"}},
                    "config": {"type": "object"},
                },
            },
            "model_policy": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "primary": {"type": "string"},
                    "fallbacks": {"type": "array", "items": {"type": "string"}},
                    "fallback": {"type": "array", "items": {"type": "string"}},
                    "profile": {"type": "string"},
                    "temperature": {"type": "number"},
                    "context_window": {"type": "integer"},
                    "reasoning": {"type": "string"},
                    "local_hardware": {"type": "string"},
                    "tool_call_format": {"type": "string"},
                    "pack": {"type": "string"},
                    "config": {"type": "object"},
                },
            },
            "execution_policy": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "sandbox": {"type": "string"},
                    "approval_profile": {"type": "string"},
                    "allow_read": {"type": "boolean"},
                    "allow_write": {"type": "boolean"},
                    "allow_shell": {"type": "boolean"},
                    "allow_network": {"type": "boolean"},
                    "allowed_commands": {"type": "array", "items": {"type": "string"}},
                    "blocked_categories": {"type": "array", "items": {"type": "string"}},
                    "permission_rules": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "tool": {"type": "string"},
                                "pattern": {"type": "string"},
                                "action": {"type": "string", "enum": ["allow", "deny", "ask"]},
                                "argument": {"type": "string"},
                            },
                        },
                    },
                    "config": {"type": "object"},
                },
            },
            "agents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id"],
                    "additionalProperties": True,
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "role": {"type": "string"},
                        "model": {"type": "string"},
                        "system_prompt": {"type": "string"},
                        "tools": {"type": "array", "items": {"type": "string"}},
                        "skills": {"type": "array", "items": {"type": "string"}},
                        "delegates_to": {"type": "array", "items": {"type": "string"}},
                        "max_iterations": {"type": "integer"},
                        "output_schema": {"type": "object"},
                        "config": {"type": "object"},
                    },
                },
            },
            "workflow": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "mode": {"type": "string", "enum": [item.value for item in WorkflowMode]},
                    "preset": {"type": "string"},
                    "max_task_depth": {"type": "integer"},
                    "parallelism": {"type": "integer"},
                    "merge_strategy": {"type": "string"},
                    "config": {"type": "object"},
                },
            },
            "recursion": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "enabled": {"type": "boolean"},
                    "max_depth": {"type": "integer", "minimum": 0},
                    "max_children": {"type": "integer", "minimum": 0},
                    "max_parallel": {"type": "integer", "minimum": 1},
                    "max_wall_seconds": {"type": "integer", "minimum": 0},
                    "max_budget": {"type": "number", "minimum": 0},
                    "child_model": {"type": "string"},
                    "child_sandbox": {"type": "string"},
                    "write_policy": {"type": "string", "enum": ["approval", "deny", "allow"]},
                    "config": {"type": "object"},
                },
            },
            "remote_harness": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "enabled": {"type": "boolean"},
                    "provider": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "region": {"type": "string"},
                    "context_policy": {"type": "string"},
                    "config": {"type": "object"},
                },
            },
            "context": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "instruction_files": {"type": "array", "items": {"type": "string"}},
                    "skills_dir": {"type": "string"},
                    "roles_dir": {"type": "string"},
                    "session_storage": {"type": "string"},
                    "prompt_persistence": {"type": "string", "enum": ["off", "preview", "full"]},
                    "compaction": {"type": "object"},
                    "memory": {"type": "object"},
                },
            },
            "checks": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "enabled": {"type": "boolean"},
                    "fail_on_error": {"type": "boolean"},
                    "timeout_seconds": {"type": "integer"},
                    "custom_steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "command"],
                            "properties": {
                                "name": {"type": "string"},
                                "command": {"type": "string"},
                                "enabled": {"type": "boolean"},
                                "timeout": {"type": "integer"},
                            },
                        },
                    },
                },
            },
            "observability": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "events": {"type": "boolean"},
                    "traces": {"type": "boolean"},
                    "local": {"type": "boolean"},
                    "exporters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "type": {"type": "string"},
                                "enabled": {"type": "boolean"},
                            },
                        },
                    },
                    "run_store": {"type": "string"},
                    "config": {"type": "object"},
                },
            },
            "hooks": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "enabled": {"type": "boolean"},
                    "rules": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["point", "handler"],
                            "additionalProperties": True,
                            "properties": {
                                "point": {"type": "string"},
                                "handler": {"type": "string"},
                                "matcher": {"type": "string"},
                                "name": {"type": "string"},
                                "config": {"type": "object"},
                            },
                        },
                    },
                },
            },
            "optimization": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "enabled": {"type": "boolean"},
                    "require_human_apply": {"type": "boolean"},
                    "editable_surfaces": {"type": "array", "items": {"type": "string"}},
                    "protected_surfaces": {"type": "array", "items": {"type": "string"}},
                    "heldout_fraction": {"type": "number", "minimum": 0, "maximum": 1},
                    "max_candidate_edits": {"type": "integer", "minimum": 1},
                    "config": {"type": "object"},
                },
            },
            "metadata": {"type": "object"},
        },
        "required": ["name"],
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
        pack=str(data["pack"]) if data.get("pack") else None,
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
        permission_rules=_permission_rules(data.get("permission_rules")),
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _permission_rules(value: Any) -> tuple[PermissionRuleSpec, ...]:
    if not isinstance(value, list):
        return ()
    out: list[PermissionRuleSpec] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"Permission rule at index {index} must be a mapping")
        action = str(item.get("action") or "ask").strip().lower()
        if action not in {"allow", "deny", "ask"}:
            raise ValueError(
                f"Permission rule at index {index} has invalid action {action!r}; "
                "valid: allow, deny, ask"
            )
        out.append(
            PermissionRuleSpec(
                tool=str(item.get("tool") or "*"),
                pattern=str(item.get("pattern") or "*"),
                action=action,
                argument=str(item.get("argument") or ""),
            )
        )
    return tuple(out)


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
                config=dict(item.get("config") or {})
                if isinstance(item.get("config"), dict)
                else {},
            )
        )
    return tuple(out)


def _workflow(value: Any) -> WorkflowSpec:
    data = value if isinstance(value, dict) else {}
    return WorkflowSpec(
        mode=_workflow_mode(data.get("mode", WorkflowMode.SINGLE.value)),
        preset=str(data.get("preset") or "").strip().lower().replace("_", "-"),
        max_task_depth=int(data.get("max_task_depth", 4) or 0),
        parallelism=int(data.get("parallelism", 1) or 1),
        merge_strategy=str(data.get("merge_strategy") or "summary"),
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _recursion(value: Any) -> RecursionSpec:
    data = value if isinstance(value, dict) else {}
    write_policy = str(data.get("write_policy") or "approval").strip().lower()
    if write_policy not in {"approval", "deny", "allow"}:
        raise ValueError("recursion.write_policy must be one of: approval, deny, allow")
    max_budget = data.get("max_budget")
    return RecursionSpec(
        enabled=bool(data.get("enabled", False)),
        max_depth=max(0, int(data.get("max_depth", 1) or 0)),
        max_children=max(0, int(data.get("max_children", 6) or 0)),
        max_parallel=max(1, int(data.get("max_parallel", 2) or 1)),
        max_wall_seconds=max(0, int(data.get("max_wall_seconds", 600) or 0)),
        max_budget=float(max_budget) if max_budget is not None else None,
        child_model=str(data["child_model"]) if data.get("child_model") else None,
        child_sandbox=str(data.get("child_sandbox") or "docker"),
        write_policy=write_policy,
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _remote_harness(value: Any) -> RemoteHarnessSpec:
    data = value if isinstance(value, dict) else {}
    return RemoteHarnessSpec(
        enabled=bool(data.get("enabled", False)),
        provider=str(data.get("provider") or ""),
        agent_id=str(data["agent_id"]) if data.get("agent_id") else None,
        region=str(data["region"]) if data.get("region") else None,
        context_policy=str(data.get("context_policy") or "selected-files"),
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _context(value: Any) -> ContextSpec:
    data = value if isinstance(value, dict) else {}
    prompt_persistence = str(data.get("prompt_persistence") or "preview").strip().lower()
    if prompt_persistence not in {"off", "preview", "full"}:
        raise ValueError("context.prompt_persistence must be one of: off, preview, full")
    return ContextSpec(
        instruction_files=_str_tuple(
            data.get("instruction_files") or ("AGENTS.md", "CLAUDE.md", "SUPERQODE.md")
        ),
        skills_dir=str(data.get("skills_dir") or ".agents/skills"),
        roles_dir=str(data.get("roles_dir") or ".agents/roles"),
        session_storage=str(data.get("session_storage") or ".superqode/sessions"),
        prompt_persistence=prompt_persistence,
        compaction=dict(data.get("compaction") or {})
        if isinstance(data.get("compaction"), dict)
        else {},
        memory=dict(data.get("memory") or {}) if isinstance(data.get("memory"), dict) else {},
    )


def _checks(value: Any) -> ChecksSpec:
    data = value if isinstance(value, dict) else {}
    steps: list[CheckStepSpec] = []
    for index, item in enumerate(data.get("custom_steps") or ()):
        if not isinstance(item, dict):
            raise ValueError(f"Checks step at index {index} must be a mapping")
        steps.append(
            CheckStepSpec(
                name=str(item.get("name") or f"step-{index + 1}"),
                command=str(item.get("command") or ""),
                enabled=bool(item.get("enabled", True)),
                timeout=int(item.get("timeout", data.get("timeout_seconds", 300)) or 0),
            )
        )
    return ChecksSpec(
        enabled=bool(data.get("enabled", False)),
        fail_on_error=bool(data.get("fail_on_error", False)),
        timeout_seconds=int(data.get("timeout_seconds", 300) or 0),
        custom_steps=tuple(steps),
        config={
            k: v
            for k, v in data.items()
            if k not in {"enabled", "fail_on_error", "timeout_seconds", "custom_steps"}
        },
    )


def _observability(value: Any) -> ObservabilitySpec:
    data = value if isinstance(value, dict) else {}
    exporters: list[dict[str, Any]] = []
    for index, item in enumerate(data.get("exporters") or ()):
        if not isinstance(item, dict):
            raise ValueError(f"observability.exporters[{index}] must be a mapping")
        exporters.append(dict(item))
    return ObservabilitySpec(
        events=bool(data.get("events", True)),
        traces=bool(data.get("traces", False)),
        local=bool(data.get("local", True)),
        exporters=tuple(exporters),
        run_store=str(data.get("run_store") or "memory"),
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _hooks(value: Any) -> HooksSpec:
    data = value if isinstance(value, dict) else {}
    rules: list[HookRuleSpec] = []
    for index, item in enumerate(data.get("rules") or ()):
        if not isinstance(item, dict):
            raise ValueError(f"Hook rule at index {index} must be a mapping")
        point = str(item.get("point") or "").strip()
        handler = str(item.get("handler") or item.get("target") or "").strip()
        if not point:
            raise ValueError(f"Hook rule at index {index} requires a point")
        if not handler:
            raise ValueError(f"Hook rule at index {index} requires a handler")
        rules.append(
            HookRuleSpec(
                point=point,
                handler=handler,
                matcher=str(item.get("matcher") or "*"),
                name=str(item.get("name") or ""),
                config=dict(item.get("config") or {})
                if isinstance(item.get("config"), dict)
                else {},
            )
        )
    return HooksSpec(
        enabled=bool(data.get("enabled", True)),
        rules=tuple(rules),
    )


def _optimization(value: Any) -> OptimizationSpec:
    data = value if isinstance(value, dict) else {}
    default = OptimizationSpec()
    editable = _str_tuple(data.get("editable_surfaces")) or default.editable_surfaces
    protected = _str_tuple(data.get("protected_surfaces")) or default.protected_surfaces
    heldout_fraction = float(data.get("heldout_fraction", default.heldout_fraction))
    if heldout_fraction < 0 or heldout_fraction > 1:
        raise ValueError("optimization.heldout_fraction must be between 0 and 1")
    max_candidate_edits = data.get("max_candidate_edits")
    return OptimizationSpec(
        enabled=bool(data.get("enabled", default.enabled)),
        require_human_apply=bool(data.get("require_human_apply", default.require_human_apply)),
        editable_surfaces=editable,
        protected_surfaces=protected,
        heldout_fraction=heldout_fraction,
        max_candidate_edits=int(max_candidate_edits) if max_candidate_edits is not None else None,
        config=dict(data.get("config") or {}) if isinstance(data.get("config"), dict) else {},
    )


def _include_optimization(spec: OptimizationSpec) -> bool:
    default = OptimizationSpec()
    return (
        spec.enabled != default.enabled
        or spec.require_human_apply != default.require_human_apply
        or spec.editable_surfaces != default.editable_surfaces
        or spec.protected_surfaces != default.protected_surfaces
        or spec.heldout_fraction != default.heldout_fraction
        or spec.max_candidate_edits is not None
        or bool(spec.config)
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
