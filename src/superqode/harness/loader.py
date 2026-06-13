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
    raw = spec_path.read_text(encoding="utf-8")
    if spec_path.suffix.lower() == ".json":
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Harness spec must be a mapping: {spec_path}")
    return harness_spec_from_dict(data)


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
        version=int(raw.get("version", 1) or 1),
        description=str(raw.get("description", "") or ""),
        flavor=flavor,
        runtime=_runtime(raw.get("runtime")),
        model_policy=_model_policy(raw.get("model_policy")),
        execution_policy=_execution_policy(raw.get("execution_policy"), flavor),
        agents=_agents(raw.get("agents")),
        workflow=_workflow(raw.get("workflow")),
        context=_context(raw.get("context")),
        checks=_checks(raw.get("checks")),
        observability=_observability(raw.get("observability")),
        hooks=_hooks(raw.get("hooks")),
        metadata=dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {},
    )
    return apply_workflow_preset(spec)


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
            "run_store": spec.observability.run_store,
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
    return ObservabilitySpec(
        events=bool(data.get("events", True)),
        traces=bool(data.get("traces", False)),
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
