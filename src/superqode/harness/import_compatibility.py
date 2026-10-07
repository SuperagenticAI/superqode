"""Conservative field-mapping receipts; these do not certify execution behavior."""

from __future__ import annotations

from typing import Any, Mapping


def build_omnigent_compatibility_receipt(
    data: Mapping[str, Any], backend_map: Mapping[str, str]
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "version": 1,
        "scope": "field_mapping",
        "runtime_equivalence": "unverified",
        "translated": [],
        "preserved_only": [],
        "unsupported": [],
        "behavior_changes": [],
    }

    def record(category, field, reason, target=""):
        receipt[category].append(
            {"field": field, "reason": reason, **({"target": target} if target else {})}
        )

    def inspect(agent, prefix="", child=False):
        def field(name):
            return prefix + name

        targets = {
            "name": "HarnessSpec.name and primary AgentSpec.id",
            "description": "HarnessSpec.description / AgentSpec.role",
            "prompt": "AgentSpec.system_prompt",
            "instructions": "instruction_files or AgentSpec.system_prompt",
            "parallelism": "WorkflowSpec.parallelism",
            "skills": "AgentSpec.skills / skills_filter config",
        }
        if child:
            targets.pop("name")
            targets.pop("parallelism")
            targets.update(
                {
                    "max_iterations": "AgentSpec.max_iterations",
                    "output_schema": "AgentSpec.output_schema",
                }
            )
        instructions_active = isinstance(agent.get("instructions"), str) and bool(
            agent["instructions"].strip()
        )
        for name, target in targets.items():
            if name not in agent:
                continue
            if name == "prompt" and instructions_active:
                record(
                    "unsupported",
                    field(name),
                    "Ignored because instructions takes precedence; prompt is not preserved by conversion.",
                )
                record(
                    "behavior_changes",
                    field(name),
                    "Non-empty instructions replaces prompt during conversion.",
                )
            elif name in {"instructions", "prompt"} and not (
                isinstance(agent[name], str) and agent[name].strip()
            ):
                record(
                    "unsupported",
                    field(name),
                    "Empty or non-string instruction content is not translated.",
                )
            else:
                record(
                    "translated",
                    field(name),
                    "Mapped to the generated spec; runtime support remains adapter-dependent.",
                    target,
                )
        for name in ("policies", "params", "terminals", "async", "cancellable", "timers"):
            if name in agent:
                reason = (
                    "Stored as source metadata; Omnigent execution semantics are not translated."
                )
                if name == "policies":
                    reason = "Preserved in metadata only; does not become SuperQode governance or permission enforcement."
                record("preserved_only", field(name), reason)
        if child and "pass_history" in agent:
            record(
                "preserved_only",
                field("pass_history"),
                "Carried into child config; native fork or reattach semantics are not established.",
            )
        if child and "max_sessions" in agent:
            record(
                "behavior_changes",
                field("max_sessions"),
                "Used as a fallback max_iterations value, not a concurrent session limit.",
                "AgentSpec.max_iterations",
            )
        executor = agent.get("executor")
        if isinstance(executor, dict):
            for name in executor:
                path = field(f"executor.{name}")
                if name == "harness":
                    record(
                        "translated",
                        path,
                        "Mapped backend name; validate availability before execution.",
                        "runtime.backend" if not child else "AgentSpec.config.runtime_backend",
                    )
                    value = str(executor[name] or "").strip()
                    if value in {"codex-native", "claude-native", "open-responses"}:
                        record(
                            "behavior_changes",
                            path,
                            f"Uses {backend_map[value]} instead of the source integration. Native UI, authentication, hooks, approvals and continuity do not automatically transfer.",
                        )
                    elif value == "pi":
                        record(
                            "unsupported",
                            path,
                            "Maps to the legacy runtime backend name; no registered Pi execution adapter is established by conversion.",
                        )
                elif name == "model":
                    record(
                        "translated",
                        path,
                        "Mapped model selection; effective model is not verified.",
                        "model_policy.primary" if not child else "AgentSpec.model",
                    )
                else:
                    record(
                        "preserved_only",
                        path,
                        "Carried in executor/model config; credential readiness and adapter enforcement are not verified.",
                    )
        if "executor" in agent and not isinstance(executor, dict):
            record(
                "unsupported",
                field("executor"),
                "Non-mapping executor is ignored during conversion.",
            )
        environment_preserved = child or (
            isinstance(agent.get("os_env"), dict) and bool(agent["os_env"])
        )
        if "os_env" in agent and not environment_preserved:
            record(
                "unsupported",
                field("os_env"),
                "Empty or non-mapping environment does not produce imported environment config.",
            )
        if "os_env" in agent and environment_preserved:
            record(
                "preserved_only",
                field("os_env"),
                "Source environment controls remain in config; their complete semantics are not enforced by conversion.",
            )
            if not child:
                record(
                    "translated",
                    field("os_env.sandbox"),
                    "Maps coarse read/write/shell/network settings only.",
                    "execution_policy",
                )
                record(
                    "behavior_changes",
                    field("os_env.sandbox"),
                    "Sandbox types map to local or none; path lists, egress rules and host lifecycle are not equivalent isolation guarantees.",
                )
        tools = agent.get("tools")
        if isinstance(tools, dict):
            for name, tool in tools.items():
                path = field(f"tools.{name}")
                if isinstance(tool, dict) and tool.get("type") == "agent":
                    if child:
                        record(
                            "unsupported",
                            path,
                            "Nested agent definition is preserved in tool config but is not compiled into another AgentSpec.",
                        )
                    else:
                        record(
                            "translated",
                            path,
                            "Compiled child agent and orchestrator workflow; not a shared native session.",
                            "agents / workflow",
                        )
                        inspect(tool, path + ".", child=True)
                elif isinstance(tool, dict) and tool.get("type") == "mcp":
                    record(
                        "translated",
                        path,
                        "Copies supported server connection fields into mcp_servers; server availability and content behavior remain unverified.",
                        "runtime / agent config.mcp_servers",
                    )
                elif str(tool).strip().lower() in {"inherit", "self"}:
                    record(
                        "translated" if child else "unsupported",
                        path,
                        "Child tool reference is retained."
                        if child
                        else "Top-level inherited/self tool references are omitted.",
                    )
                else:
                    record(
                        "preserved_only",
                        path,
                        "Tool name and definition are retained; external Python callables and client implementations are not installed or imported by conversion.",
                    )
        if "tools" in agent and not isinstance(tools, dict):
            record(
                "unsupported", field("tools"), "Non-mapping tools are ignored during conversion."
            )
        known = set(targets) | {
            "executor",
            "tools",
            "os_env",
            "policies",
            "params",
            "terminals",
            "async",
            "cancellable",
            "timers",
        }
        if child:
            known |= {"type", "pass_history", "max_sessions"}
        for name in agent:
            if name not in known:
                record(
                    "unsupported",
                    field(str(name)),
                    "Field has no importer translation or preservation contract.",
                )

    inspect(data)
    return receipt


def render_import_compatibility(receipt: Mapping[str, Any]) -> str:
    """Render field paths/reasons only; never echo source credentials or policies."""
    lines = ["Compatibility receipt (field mapping; runtime equivalence unverified):"]
    lines.append(f"  Translated: {len(receipt.get('translated', []))} field(s)")
    for category, label in (
        ("preserved_only", "Preserved only"),
        ("unsupported", "Unsupported"),
        ("behavior_changes", "Behavior change"),
    ):
        for entry in receipt.get(category, []):
            lines.append(f"  {label}: {entry['field']} — {entry['reason']}")
    return "\n".join(lines)
