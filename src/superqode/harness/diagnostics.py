"""Harness inspection, readiness checks, and planned graph rendering."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from superqode.mcp.config import MCPHttpConfig, MCPSSEConfig, MCPStdioConfig, load_mcp_config
from superqode.providers.registry import PROVIDERS, ProviderCategory
from superqode.tools.base import ToolRegistry

from .backends.registry import (
    backend_capabilities,
    inspect_harness_backend,
    known_harness_backend_names,
)
from .model_policy import resolve_harness_model_policy
from .sandbox import get_sandbox_capabilities
from .spec import HarnessSpec, WorkflowMode
from .store import (
    FileHarnessStore,
    HarnessEventGraph,
    HarnessGraphEdge,
    HarnessGraphNode,
    create_harness_store,
)
from .workflow_presets import apply_workflow_preset

LOCAL_PROVIDER_ALIASES = {"local"}


@dataclass(frozen=True)
class HarnessCheck:
    """One doctor check for a harness."""

    name: str
    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {"name": self.name, "status": self.status, "message": self.message}
        payload.update(self.data)
        return payload


@dataclass(frozen=True)
class HarnessDoctorReport:
    """Structured readiness report."""

    status: str
    name: str
    runtime: str
    flavor: str
    workflow: str
    sandbox: str
    checks: tuple[HarnessCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        blockers = sum(1 for check in self.checks if check.status == "error")
        warnings = sum(1 for check in self.checks if check.status == "warning")
        return {
            "status": self.status,
            "ready": self.status != "error",
            "name": self.name,
            "runtime": self.runtime,
            "flavor": self.flavor,
            "workflow": self.workflow,
            "sandbox": self.sandbox,
            "summary": {
                "blockers": blockers,
                "warnings": warnings,
                "checks": len(self.checks),
            },
            "checks": [check.to_dict() for check in self.checks],
        }


def inspect_harness(
    spec: HarnessSpec,
    *,
    runtime: str | None = None,
    sandbox: str | None = None,
    cwd: str | Path = ".",
) -> dict[str, Any]:
    """Return a readable structured summary for a HarnessSpec."""
    spec = apply_workflow_preset(spec)
    backend_name = runtime or spec.runtime.backend
    sandbox_name = sandbox or spec.execution_policy.sandbox
    model_policy = resolve_harness_model_policy(
        spec,
        provider=str(spec.model_policy.config.get("provider") or ""),
        model=spec.model_policy.primary or "",
    )
    inspection = inspect_harness_backend(backend_name, spec, sandbox_backend=sandbox_name)
    graph = plan_harness_graph(spec)
    tools = sorted({tool for agent in spec.agents for tool in agent.tools})
    skills = sorted(
        {skill for agent in spec.agents for skill in agent.skills}
        | set(spec.metadata.get("skills", ()))
    )
    return {
        "name": spec.name,
        "version": spec.version,
        "description": spec.description,
        "flavor": spec.flavor.value,
        "runtime": {
            "backend": backend_name,
            "fallback_backends": list(spec.runtime.fallback_backends),
            "config_keys": sorted(spec.runtime.config),
        },
        "workflow": {
            "mode": spec.workflow.mode.value,
            "preset": spec.workflow.preset,
            "parallelism": spec.workflow.parallelism,
            "max_task_depth": spec.workflow.max_task_depth,
            "merge_strategy": spec.workflow.merge_strategy,
            "steps": [node.label for node in graph.nodes],
        },
        "agents": [
            {
                "id": agent.id,
                "role": agent.role,
                "model": agent.model,
                "tools": list(agent.tools),
                "skills": list(agent.skills),
                "delegates_to": list(agent.delegates_to),
                "max_iterations": agent.max_iterations,
            }
            for agent in spec.agents
        ],
        "model_policy": {
            "primary": spec.model_policy.primary,
            "fallbacks": list(spec.model_policy.fallbacks),
            "profile": model_policy.profile,
            "system_level": model_policy.system_level.value,
            "tool_profile": model_policy.tool_profile,
            "reasoning": model_policy.reasoning,
            "temperature": model_policy.temperature,
            "max_iterations": model_policy.max_iterations,
            "parallel_tools": model_policy.parallel_tools,
        },
        "permissions": {
            "sandbox": sandbox_name,
            "approval_profile": spec.execution_policy.approval_profile,
            "allow_read": spec.execution_policy.allow_read,
            "allow_write": spec.execution_policy.allow_write,
            "allow_shell": spec.execution_policy.allow_shell,
            "allow_network": spec.execution_policy.allow_network,
            "allowed_commands": list(spec.execution_policy.allowed_commands),
            "blocked_categories": list(spec.execution_policy.blocked_categories),
            "rules": _permission_rules_summary(spec),
            "remembered_rules": _remembered_permission_rules_summary(spec),
        },
        "hooks": _hooks_summary(spec),
        "tools": tools,
        "skills": skills,
        "mcp": _mcp_summary(spec),
        "checks": {
            "enabled": spec.checks.enabled,
            "fail_on_error": spec.checks.fail_on_error,
            "timeout_seconds": spec.checks.timeout_seconds,
            "steps": [
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
        "backend": inspection.to_dict(),
        "cwd": str(Path(cwd).expanduser().resolve()),
    }


def doctor_harness(
    spec: HarnessSpec,
    *,
    runtime: str | None = None,
    sandbox: str | None = None,
    store_root: str | Path | None = None,
    cwd: str | Path = ".",
) -> HarnessDoctorReport:
    """Run readiness checks for a HarnessSpec."""
    spec = apply_workflow_preset(spec)
    backend_name = runtime or spec.runtime.backend
    sandbox_name = sandbox or spec.execution_policy.sandbox
    root = Path(cwd).expanduser().resolve()
    checks: list[HarnessCheck] = []

    def add(name: str, status: str, message: str, **data: Any) -> None:
        checks.append(
            HarnessCheck(
                name=name,
                status=status,
                message=message,
                data={
                    "severity": _severity(status),
                    **data,
                },
            )
        )

    add(
        "spec",
        "ok",
        f"Loaded HarnessSpec '{spec.name}'.",
        version=spec.version,
        fix="No action needed.",
    )

    if backend_name not in known_harness_backend_names():
        add(
            "backend",
            "error",
            f"Unknown runtime backend '{backend_name}'.",
            known_backends=known_harness_backend_names(),
            fix=f"Use one of: {_join(known_harness_backend_names())}.",
        )
    else:
        capabilities = backend_capabilities(backend_name)
        add(
            "backend",
            "ok" if capabilities.availability == "available" else "error",
            (
                f"Backend '{backend_name}' is available."
                if capabilities.availability == "available"
                else f"Backend '{backend_name}' is missing."
            ),
            install_hint=capabilities.install_hint,
            fix=capabilities.install_hint or "No action needed.",
        )
        inspection = inspect_harness_backend(backend_name, spec, sandbox_backend=sandbox_name)
        add(
            "compatibility",
            "ok" if inspection.ok else "error",
            "Backend can run this spec."
            if inspection.ok
            else "Backend/spec compatibility is blocked.",
            issues=[issue.to_dict() for issue in inspection.issues],
            fix="Select a compatible runtime or adjust the harness flavor/tools.",
        )
        if spec.execution_policy.approval_profile != "deny":
            add(
                "approvals",
                "ok" if capabilities.supports_approvals else "warning",
                (
                    f"Backend '{backend_name}' supports approval pauses."
                    if capabilities.supports_approvals
                    else f"Backend '{backend_name}' may not pause for approvals."
                ),
                fix=(
                    "No action needed."
                    if capabilities.supports_approvals
                    else "Use an approval-aware runtime or set approval_profile: deny."
                ),
            )

    model_check = _model_policy_check(spec)
    add("model_registry", model_check["status"], model_check["message"], **model_check["data"])

    tool_check = _tool_check(spec)
    add("tools", tool_check["status"], tool_check["message"], **tool_check["data"])

    skill_check = _skill_check(spec, root)
    add("skills", skill_check["status"], skill_check["message"], **skill_check["data"])

    mcp_check = _mcp_check(spec, root)
    add("mcp", mcp_check["status"], mcp_check["message"], **mcp_check["data"])

    permission_status, permission_message, permission_data = _permission_check(spec)
    add("permissions", permission_status, permission_message, **permission_data)

    hooks_check = _hooks_check(spec)
    add("hooks", hooks_check["status"], hooks_check["message"], **hooks_check["data"])

    sandbox_check = _sandbox_check(sandbox_name)
    add("sandbox", sandbox_check["status"], sandbox_check["message"], **sandbox_check["data"])

    checks_check = _checks_check(spec, root)
    add(
        "checks",
        checks_check["status"],
        checks_check["message"],
        **checks_check["data"],
    )

    store_kind = spec.observability.run_store
    target_root = _resolve(
        root, store_root if store_root is not None else spec.context.session_storage
    )
    try:
        create_harness_store(store_kind, target_root)
        _assert_store_writable(store_kind, target_root)
    except Exception as exc:  # noqa: BLE001
        add(
            "event_store",
            "error",
            f"Cannot initialize harness run store '{store_kind}' at {target_root}: {exc}",
            store=store_kind,
            path=str(target_root),
            fix="Choose a writable observability.run_store path or fix directory permissions.",
        )
    else:
        add(
            "event_store",
            "ok",
            (
                "Harness run store 'memory' initialized."
                if store_kind == "memory"
                else f"Harness run store '{store_kind}' is writable at {target_root}."
            ),
            store=store_kind,
            path=str(target_root),
            graph=True,
            fix="No action needed.",
        )

    add(
        "event_graph",
        "ok"
        if backend_name in {"builtin", "pydanticai", "openai-agents", "deepagents"}
        else "warning",
        (
            f"Backend '{backend_name}' emits rich graph events."
            if backend_name in {"builtin", "pydanticai", "openai-agents", "deepagents"}
            else f"Backend '{backend_name}' emits coarse graph events."
        ),
        rich_events=backend_name in {"builtin", "pydanticai", "openai-agents", "deepagents"},
        fix=(
            "No action needed."
            if backend_name in {"builtin", "pydanticai", "openai-agents", "deepagents"}
            else "Use a richer runtime backend when you need detailed evidence graphs."
        ),
    )

    status = "ok"
    if any(check.status == "error" for check in checks):
        status = "error"
    elif any(check.status == "warning" for check in checks):
        status = "warning"
    return HarnessDoctorReport(
        status=status,
        name=spec.name,
        runtime=backend_name,
        flavor=spec.flavor.value,
        workflow=spec.workflow.mode.value,
        sandbox=sandbox_name,
        checks=tuple(checks),
    )


def plan_harness_graph(spec: HarnessSpec) -> HarnessEventGraph:
    """Build a planned workflow graph from a HarnessSpec."""
    spec = apply_workflow_preset(spec)
    labels = _planned_labels(spec)
    nodes = tuple(
        HarnessGraphNode(
            node_id=f"plan:{index + 1}:{_safe_node_id(label)}",
            run_id="planned",
            type="workflow.step",
            label=label,
            timestamp=0.0,
            event_index=index,
            data={"mode": spec.workflow.mode.value, "preset": spec.workflow.preset},
        )
        for index, label in enumerate(labels)
    )
    edges = _planned_edges(spec.workflow.mode, nodes)
    return HarnessEventGraph(run_id="planned", nodes=nodes, edges=edges)


def build_harness_evidence(store: FileHarnessStore, run_id: str) -> dict[str, Any]:
    """Build a human-readable evidence report from a persisted harness run."""
    run = store.get_run(run_id)
    if run is None:
        raise KeyError(f"Unknown harness run: {run_id}")
    graph = store.get_event_graph(run_id)
    events = list(run.events)
    step_events = [event for event in events if event.type.startswith("workflow.step.")]
    completed_steps = [event for event in events if event.type == "workflow.step.completed"]
    failed_steps = [event for event in events if event.type == "workflow.step.failed"]
    approval_events = [
        event
        for event in events
        if event.type.startswith("approval_")
        or event.type.startswith("approval.")
        or event.type == "approval_required"
    ]
    checks_events = [event for event in events if event.type.startswith("checks.")]
    final_event = next(
        (event for event in reversed(events) if event.type == "workflow.result"), None
    )
    completed_event = next(
        (event for event in reversed(events) if event.type == "workflow.run.completed"),
        None,
    )
    changes_event = next(
        (event for event in reversed(events) if event.type == "workspace.changes.captured"),
        None,
    )
    child_run_ids = []
    for event in completed_steps:
        child_run_id = event.data.get("child_run_id")
        if child_run_id and child_run_id not in child_run_ids:
            child_run_ids.append(str(child_run_id))
    metadata = dict(run.metadata)
    checks = metadata.get("checks")
    if not isinstance(checks, dict):
        checks = _checks_summary_from_events(checks_events)
    changed_files = metadata.get("changed_files")
    if not isinstance(changed_files, dict):
        changed_files = dict(changes_event.data) if changes_event is not None else {}
    return {
        "run": {
            "run_id": run.run_id,
            "session_id": run.session_id,
            "harness": run.harness,
            "flavor": run.flavor,
            "provider": run.provider,
            "model": run.model,
            "runtime": run.runtime,
            "status": run.status,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "prompt_preview": run.prompt_preview,
            "workflow": bool(metadata.get("workflow")),
        },
        "workflow": {
            "mode": metadata.get("workflow_mode")
            or (completed_event.data.get("mode") if completed_event else ""),
            "step_events": len(step_events),
            "completed_steps": [_workflow_step_summary(event) for event in completed_steps],
            "failed_steps": [_workflow_step_summary(event) for event in failed_steps],
            "child_run_ids": child_run_ids,
        },
        "changes": changed_files,
        "checks": checks,
        "approvals": [event.to_dict() for event in approval_events],
        "result": {
            "status": final_event.data.get("status") if final_event else run.status,
            "content_preview": final_event.data.get("content_preview", "") if final_event else "",
            "result_count": final_event.data.get("result_count") if final_event else None,
        },
        "graph": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "node_types": sorted({node.type for node in graph.nodes}),
        },
        "commands": {
            "graph": f"superqode harness graph {run.run_id}",
            "events": f"superqode harness events {run.run_id}",
            "runs": "superqode harness runs",
        },
    }


def build_harness_replay_plan(store: FileHarnessStore, run_id: str) -> dict[str, Any]:
    """Build a deterministic replay/fork plan from a persisted run."""
    run = store.get_run(run_id)
    if run is None:
        raise KeyError(f"Unknown harness run: {run_id}")
    events = store.get_events(run_id)
    pending = [
        event
        for event in events
        if event.type in {"approval_required", "harness.permission.check"}
        or event.type.startswith("approval")
    ]
    terminal = next(
        (
            event
            for event in reversed(events)
            if event.type in {"run_end", "harness.stop", "workflow.result"}
        ),
        None,
    )
    stored_prompt = (
        run.metadata.get("prompt") if isinstance(run.metadata.get("prompt"), str) else ""
    )
    replayable = bool(stored_prompt)
    return {
        "run": {
            "run_id": run.run_id,
            "session_id": run.session_id,
            "harness": run.harness,
            "provider": run.provider,
            "model": run.model,
            "runtime": run.runtime,
            "status": run.status,
            "prompt_preview": run.prompt_preview,
            "prompt_persistence": run.metadata.get("prompt_persistence") or "unknown",
            "has_full_prompt": bool(stored_prompt),
        },
        "events": {
            "count": len(events),
            "first": events[0].type if events else "",
            "last": events[-1].type if events else "",
            "approval_related": len(pending),
        },
        "terminal": terminal.to_dict() if terminal is not None else None,
        "lineage": {
            "fork_of": run.metadata.get("fork_of"),
            "fork_after": run.metadata.get("fork_after"),
        },
        "replayable": replayable,
        "prompt": stored_prompt,
        "limitations": []
        if replayable
        else [
            "No full prompt is stored for this run; pass --prompt or set context.prompt_persistence: full."
        ],
        "commands": {
            "fork": f"superqode harness fork {run.run_id}",
            "events": f"superqode harness events {run.run_id}",
            "evidence": f"superqode harness evidence {run.run_id}",
        },
    }


def render_harness_replay_plan(plan: dict[str, Any]) -> str:
    """Render a replay/fork plan for humans."""
    run = plan["run"]
    events = plan["events"]
    lines = [
        "Harness replay plan",
        f"Run: {run['run_id']}",
        f"Harness: {run['harness']}  runtime={run['runtime']}",
        f"Model: {run['provider']}/{run['model']}",
        f"Status: {run['status']}",
        f"Prompt: {run['prompt_preview'] or '-'}",
        f"Prompt persistence: {run.get('prompt_persistence')}  full={run.get('has_full_prompt')}",
        f"Events: {events['count']} ({events['first']} -> {events['last']})",
        f"Approval-related: {events['approval_related']}",
    ]
    lineage = plan.get("lineage") or {}
    if lineage.get("fork_of"):
        lines.append(f"Forked from: {lineage['fork_of']} after={lineage.get('fork_after')}")
    terminal = plan.get("terminal")
    if terminal:
        lines.append(f"Terminal event: {terminal.get('type')}")
    limitations = plan.get("limitations") or []
    if limitations:
        lines.append("")
        lines.append("Limitations:")
        lines.extend(f"  - {item}" for item in limitations)
    commands = plan.get("commands") or {}
    lines.append("")
    lines.append("Next:")
    lines.append(f"  {commands.get('fork')}")
    lines.append(f"  {commands.get('events')}")
    return "\n".join(lines)


def fork_harness_run(
    store: FileHarnessStore,
    run_id: str,
    *,
    after: int | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Fork a persisted run by copying its event prefix into a new run."""
    fork = store.fork_run(run_id, after=after, session_id=session_id)
    return {
        "run_id": fork.run_id,
        "status": fork.status,
        "session_id": fork.session_id,
        "fork_of": fork.metadata.get("fork_of"),
        "fork_after": fork.metadata.get("fork_after"),
        "events": len(fork.events),
        "prompt_preview": fork.prompt_preview,
    }


def render_harness_evidence(evidence: dict[str, Any]) -> str:
    """Render a persisted run evidence report as plain text."""
    run = evidence["run"]
    workflow = evidence["workflow"]
    changes = evidence["changes"] if isinstance(evidence["changes"], dict) else {}
    checks = evidence["checks"] if isinstance(evidence["checks"], dict) else {}
    result = evidence["result"]
    graph = evidence["graph"]
    lines = [
        f"Harness evidence: {run['run_id']}",
        f"Status: {run['status']}",
        f"Harness: {run['harness']} ({run['flavor']})",
        f"Runtime: {run['runtime']}  Model: {_provider_model(run)}",
        f"Session: {run['session_id']}",
    ]
    if workflow.get("mode"):
        lines.append(f"Workflow: {workflow['mode']}")
    lines.extend(
        [
            "",
            "Steps:",
        ]
    )
    completed_steps = workflow.get("completed_steps") or []
    failed_steps = workflow.get("failed_steps") or []
    if not completed_steps and not failed_steps:
        lines.append("  - no workflow step events")
    for step in completed_steps:
        lines.append(
            f"  - ok {step['step_id']}"
            + (f" -> {step['child_run_id']}" if step.get("child_run_id") else "")
            + (f" ({step['detail']})" if step.get("detail") else "")
        )
    for step in failed_steps:
        lines.append(
            f"  - failed {step['step_id']}" + (f" ({step['detail']})" if step.get("detail") else "")
        )
    lines.extend(["", _changes_line(changes), _checks_line(checks)])
    approvals = evidence.get("approvals") or []
    lines.append(f"Approvals: {len(approvals)} event(s)")
    lines.append(
        f"Graph: {graph['nodes']} node(s), {graph['edges']} edge(s)"
        + (f" [{_join(graph['node_types'])}]" if graph.get("node_types") else "")
    )
    lines.append(f"Result: {result.get('status') or run['status']}")
    if result.get("content_preview"):
        lines.extend(["", "Result preview:", str(result["content_preview"])])
    lines.extend(
        [
            "",
            "Next:",
            f"  {evidence['commands']['graph']}",
            f"  {evidence['commands']['events']}",
        ]
    )
    return "\n".join(lines).rstrip()


def render_harness_inspect(summary: dict[str, Any]) -> str:
    """Render an inspect summary as plain text."""
    lines = [
        f"Harness: {summary['name']} v{summary['version']}",
        f"Description: {summary['description'] or '-'}",
        f"Flavor: {summary['flavor']}",
        f"Runtime: {summary['runtime']['backend']}",
        (
            "Workflow: "
            f"{summary['workflow']['mode']}"
            + (f" preset={summary['workflow']['preset']}" if summary["workflow"]["preset"] else "")
            + f" parallelism={summary['workflow']['parallelism']}"
        ),
        f"Model: {summary['model_policy']['primary'] or '-'}",
        f"Approval: {summary['permissions']['approval_profile']}",
        (
            "Permissions: "
            f"read={summary['permissions']['allow_read']} "
            f"write={summary['permissions']['allow_write']} "
            f"shell={summary['permissions']['allow_shell']} "
            f"network={summary['permissions']['allow_network']}"
        ),
        f"Tools: {_join(summary['tools'])}",
        f"Skills: {_join(summary['skills'])}",
        f"MCP: {_join(summary['mcp']['servers']) if summary['mcp']['servers'] else 'none declared'}",
        f"Checks: {'enabled' if summary['checks']['enabled'] else 'disabled'}",
        f"Run store: {summary['observability']['run_store']}",
    ]

    rules = summary["permissions"].get("rules") or []
    if rules:
        lines.append(f"Permission rules ({len(rules)}):")
        for rule in rules:
            target = rule["tool"]
            if rule.get("argument"):
                target += f" {rule['argument']}~'{rule.get('pattern', '*')}'"
            elif rule.get("pattern"):
                target += f" ~'{rule['pattern']}'"
            lines.append(f"  - {target} -> {rule['action']}")

    remembered_rules = summary["permissions"].get("remembered_rules") or []
    if remembered_rules:
        lines.append(f"Remembered approval rules ({len(remembered_rules)}):")
        for rule in remembered_rules:
            target = rule["tool"]
            if rule.get("argument"):
                target += f" {rule['argument']}~'{rule.get('pattern', '*')}'"
            elif rule.get("pattern"):
                target += f" ~'{rule['pattern']}'"
            lines.append(f"  - {target} -> {rule['action']}")

    hooks = summary.get("hooks") or {}
    hook_entries = list(hooks.get("declared", [])) if hooks.get("enabled", True) else []
    builtin_entries = list(hooks.get("builtin", []))
    if hook_entries or builtin_entries:
        suffix = "" if hooks.get("enabled", True) else " (disabled)"
        lines.append(f"Hooks ({hooks.get('count', 0)}){suffix}:")
        for entry in builtin_entries:
            lines.append(f"  - {entry['point']}  {entry['handler']} ({entry['rules']} rule(s))")
        for entry in hook_entries:
            extra = ""
            if entry.get("matcher"):
                extra += f"  matcher={entry['matcher']}"
            if entry.get("name"):
                extra += f"  name={entry['name']}"
            lines.append(f"  - {entry['point']}  {entry['handler']}{extra}")
    elif not hooks.get("enabled", True) and hooks.get("declared"):
        lines.append("Hooks: declared but disabled")

    lines.extend(["", "Agents:"])
    for agent in summary["agents"]:
        lines.append(
            f"  - {agent['id']}"
            + (f" ({agent['role']})" if agent["role"] else "")
            + (f" model={agent['model']}" if agent["model"] else "")
        )
    if not summary["agents"]:
        lines.append("  - prompt step generated at run time")
    lines.extend(
        ["", "Planned graph:", render_harness_graph(plan_harness_graph_from_summary(summary))]
    )
    return "\n".join(lines).rstrip()


def render_harness_doctor(report: HarnessDoctorReport) -> str:
    """Render a doctor report as plain text."""
    summary = report.to_dict()["summary"]
    lines = [
        f"Harness doctor: {report.name}",
        f"Status: {report.status}",
        f"Ready: {'yes' if report.status != 'error' else 'no'}",
        f"Summary: {summary['blockers']} blocker(s), {summary['warnings']} warning(s), {summary['checks']} check(s)",
    ]
    for check in report.checks:
        lines.append(f"[{check.status}] {check.name}: {check.message}")
        if check.data.get("install_hint"):
            lines.append(f"  install: {check.data['install_hint']}")
        for issue in check.data.get("issues", []):
            lines.append(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")
        missing = check.data.get("missing")
        if missing:
            lines.append(f"  missing: {_join(missing)}")
        for err in check.data.get("errors", []):
            lines.append(f"  error: {err}")
        warnings = check.data.get("warnings")
        if warnings:
            lines.append(f"  warnings: {_join(warnings)}")
        fix = check.data.get("fix")
        if fix and fix != "No action needed.":
            lines.append(f"  fix: {fix}")
    return "\n".join(lines)


def render_harness_graph(graph: HarnessEventGraph) -> str:
    """Render a graph as readable plain text."""
    if not graph.nodes:
        return "(empty graph)"
    children: dict[str, list[str]] = {}
    incoming: set[str] = set()
    by_id = {node.node_id: node for node in graph.nodes}
    for edge in graph.edges:
        children.setdefault(edge.source, []).append(edge.target)
        incoming.add(edge.target)
    roots = [node.node_id for node in graph.nodes if node.node_id not in incoming] or [
        graph.nodes[0].node_id
    ]
    lines: list[str] = []
    seen: set[str] = set()

    def walk(node_id: str, prefix: str = "") -> None:
        node = by_id[node_id]
        connector = "-> " if prefix else ""
        lines.append(f"{prefix}{connector}{node.label}")
        seen.add(node_id)
        child_ids = children.get(node_id, [])
        for index, child_id in enumerate(child_ids):
            branch = "   " if index == len(child_ids) - 1 else "|  "
            walk(child_id, prefix + branch)

    for root in roots:
        walk(root)
    for node in graph.nodes:
        if node.node_id not in seen:
            lines.append(node.label)
    return "\n".join(lines)


def plan_harness_graph_from_summary(summary: dict[str, Any]) -> HarnessEventGraph:
    """Rebuild a minimal planned graph from an inspect summary."""
    labels = list(summary.get("workflow", {}).get("steps") or [])
    nodes = tuple(
        HarnessGraphNode(
            node_id=f"plan:{index + 1}:{_safe_node_id(label)}",
            run_id="planned",
            type="workflow.step",
            label=label,
            timestamp=0.0,
            event_index=index,
        )
        for index, label in enumerate(labels)
    )
    mode = WorkflowMode(summary.get("workflow", {}).get("mode") or WorkflowMode.SINGLE.value)
    return HarnessEventGraph(run_id="planned", nodes=nodes, edges=_planned_edges(mode, nodes))


def _planned_labels(spec: HarnessSpec) -> list[str]:
    agents = list(spec.agents)
    if agents:
        labels = [agent.id for agent in agents]
    elif spec.workflow.mode == WorkflowMode.EVALUATOR_OPTIMIZER:
        labels = ["candidate", "evaluator", "optimizer"]
    elif spec.workflow.mode == WorkflowMode.ROUTER:
        labels = ["router", "default"]
    else:
        labels = ["step-1"]
    if spec.workflow.mode == WorkflowMode.ROUTER and labels and labels[0] != "router":
        labels.insert(0, "router")
    if spec.workflow.mode == WorkflowMode.EVALUATOR_OPTIMIZER:
        defaults = ["candidate", "evaluator", "optimizer"]
        labels = (labels + defaults[len(labels) :])[:3]
    return labels


def _planned_edges(
    mode: WorkflowMode, nodes: tuple[HarnessGraphNode, ...]
) -> tuple[HarnessGraphEdge, ...]:
    if len(nodes) < 2:
        return ()
    edges: list[HarnessGraphEdge] = []
    if mode == WorkflowMode.PARALLEL:
        root = nodes[0]
        for node in nodes[1:]:
            edges.append(
                HarnessGraphEdge(source=root.node_id, target=node.node_id, type="parallel")
            )
        return tuple(edges)
    if mode == WorkflowMode.ROUTER:
        router = nodes[0]
        for node in nodes[1:]:
            edges.append(HarnessGraphEdge(source=router.node_id, target=node.node_id, type="route"))
        return tuple(edges)
    for left, right in zip(nodes, nodes[1:]):
        edges.append(HarnessGraphEdge(source=left.node_id, target=right.node_id, type="next"))
    return tuple(edges)


def _workflow_step_summary(event) -> dict[str, Any]:
    return {
        "step_id": str(event.data.get("step_id") or ""),
        "status": str(event.data.get("status") or ""),
        "detail": str(event.data.get("detail") or ""),
        "index": event.data.get("index"),
        "total": event.data.get("total"),
        "child_run_id": event.data.get("child_run_id"),
        "child_session_id": event.data.get("child_session_id"),
        "tool_calls_made": event.data.get("tool_calls_made"),
        "iterations": event.data.get("iterations"),
    }


def _checks_summary_from_events(events: list[Any]) -> dict[str, Any]:
    if not events:
        return {"enabled": False, "status": "unknown", "steps": []}
    steps = [
        {
            "name": event.data.get("name"),
            "status": "passed" if event.type.endswith(".completed") else "failed",
        }
        for event in events
        if event.type in {"checks.step.completed", "checks.step.failed"}
    ]
    status = "failed" if any(item["status"] == "failed" for item in steps) else "passed"
    return {"enabled": True, "status": status, "steps": steps}


def _provider_model(run: dict[str, Any]) -> str:
    provider = str(run.get("provider") or "").strip()
    model = str(run.get("model") or "").strip()
    if provider and model:
        return f"{provider}/{model}"
    return model or provider or "-"


def _changes_line(changes: dict[str, Any]) -> str:
    count = int(changes.get("file_count") or 0)
    additions = int(changes.get("additions") or 0)
    deletions = int(changes.get("deletions") or 0)
    files = changes.get("files") if isinstance(changes.get("files"), list) else []
    line = f"Changes: {count} file(s)"
    if additions or deletions:
        line += f" (+{additions} -{deletions})"
    if files:
        preview = ", ".join(
            str(item.get("path") or "") for item in files[:5] if isinstance(item, dict)
        )
        if preview:
            line += f" [{preview}]"
    return line


def _checks_line(checks: dict[str, Any]) -> str:
    enabled = bool(checks.get("enabled"))
    status = str(checks.get("status") or "unknown")
    steps = checks.get("steps") if isinstance(checks.get("steps"), list) else []
    if not enabled:
        return f"Checks: {status}"
    return f"Checks: {status} ({len(steps)} step(s))"


def _model_policy_check(spec: HarnessSpec) -> dict[str, Any]:
    models = [item for item in (spec.model_policy.primary, *spec.model_policy.fallbacks) if item]
    agent_models = sorted({agent.model for agent in spec.agents if agent.model})
    all_models = [*models, *agent_models]
    configured_provider = str(spec.model_policy.config.get("provider") or "").strip()
    inferred_providers = sorted(
        {_provider_from_model(model) for model in all_models if _provider_from_model(model)}
    )
    provider = configured_provider or (
        inferred_providers[0] if len(inferred_providers) == 1 else ""
    )
    warnings: list[str] = []
    errors: list[str] = []
    unknown_models: list[str] = []

    if (
        configured_provider
        and configured_provider not in PROVIDERS
        and configured_provider not in LOCAL_PROVIDER_ALIASES
    ):
        errors.append(f"unknown provider '{configured_provider}'")
    if len(inferred_providers) > 1 and not configured_provider:
        warnings.append(
            "multiple model providers inferred; set model_policy.config.provider explicitly"
        )
    if provider in PROVIDERS:
        provider_def = PROVIDERS[provider]
        expected_models = set(provider_def.example_models) | set(provider_def.free_models)
        for model in all_models:
            model_id = _model_without_provider(model)
            if expected_models and model_id not in expected_models and model not in expected_models:
                unknown_models.append(model)
        if unknown_models:
            warnings.append("some models are not in the built-in provider registry")
        if provider_def.category != ProviderCategory.LOCAL:
            present_keys = [env for env in provider_def.env_vars if os.environ.get(env)]
            optional_keys = [env for env in provider_def.optional_env if os.environ.get(env)]
            if not present_keys and not optional_keys:
                warnings.append(f"no API key environment variable found for provider '{provider}'")

    if all_models or spec.model_policy.profile:
        status = "error" if errors else "warning" if warnings else "ok"
        return {
            "status": status,
            "message": (
                "Model policy has blockers."
                if errors
                else "Model policy is configured with warnings."
                if warnings
                else "Model policy is configured."
            ),
            "data": {
                "primary": spec.model_policy.primary,
                "fallbacks": list(spec.model_policy.fallbacks),
                "agent_models": agent_models,
                "provider": provider,
                "models": all_models,
                "unknown_models": unknown_models,
                "warnings": warnings,
                "errors": errors,
                "fix": _model_policy_fix(provider, errors, warnings),
            },
        }
    return {
        "status": "ok",
        "message": "No model policy models are configured.",
        "data": {
            "primary": None,
            "fallbacks": [],
            "provider": "",
            "models": [],
            "unknown_models": [],
            "fix": "No action needed; CLI/provider defaults can still select the model at run time.",
        },
    }


def _tool_check(spec: HarnessSpec) -> dict[str, Any]:
    requested = sorted({tool for agent in spec.agents for tool in agent.tools})
    if not requested:
        return {
            "status": "ok",
            "message": "No tools are requested.",
            "data": {"requested": [], "fix": "No action needed."},
        }
    available = {tool.name for tool in ToolRegistry.full().list()}
    missing = [tool for tool in requested if tool not in available and not tool.startswith("mcp_")]
    mcp_tools = [tool for tool in requested if tool.startswith("mcp_")]
    warnings = []
    if mcp_tools and not _mcp_summary(spec)["servers"] and not _mcp_summary(spec)["config_path"]:
        warnings.append("MCP tools are requested but no MCP server or config path is declared")
    return {
        "status": "error" if missing else "warning" if warnings else "ok",
        "message": "All requested tools are available."
        if not missing
        else "Some requested tools are missing.",
        "data": {
            "requested": requested,
            "missing": missing,
            "mcp_tools": mcp_tools,
            "warnings": warnings,
            "fix": (
                "Remove or rename missing tools, or register them in the runtime tool registry."
                if missing
                else "Declare runtime.config.mcp_config_path when using mcp_* tools."
                if warnings
                else "No action needed."
            ),
        },
    }


def _skill_check(spec: HarnessSpec, root: Path) -> dict[str, Any]:
    requested = sorted({skill for agent in spec.agents for skill in agent.skills})
    if not requested:
        return {
            "status": "ok",
            "message": "No skills are requested.",
            "data": {"requested": [], "fix": "No action needed."},
        }
    skills_dir = _resolve(root, spec.context.skills_dir)
    found = _skill_names(skills_dir)
    missing = [name for name in requested if name not in found]
    status = "warning" if missing else "ok"
    return {
        "status": status,
        "message": "Requested skills are present."
        if not missing
        else "Some requested skills were not found.",
        "data": {
            "requested": requested,
            "missing": missing,
            "skills_dir": str(skills_dir),
            "found": sorted(found),
            "fix": (
                f"Create SKILL.md files under {skills_dir} or remove missing skill references."
                if missing
                else "No action needed."
            ),
        },
    }


def _mcp_check(spec: HarnessSpec, root: Path) -> dict[str, Any]:
    summary = _mcp_summary(spec)
    path = summary.get("config_path")
    if not path and not summary["servers"]:
        return {
            "status": "ok",
            "message": "No MCP servers are declared.",
            "data": {**summary, "fix": "No action needed."},
        }
    if path:
        config_path = _resolve(root, path)
        exists = config_path.exists()
        summary["config_path"] = str(config_path)
        if not exists:
            return {
                "status": "error",
                "message": f"MCP config path does not exist: {config_path}.",
                "data": {
                    **summary,
                    "fix": "Create the MCP config file or update runtime.config.mcp_config_path.",
                },
            }
        servers, errors, warnings = _inspect_mcp_config(config_path, root)
        summary["servers"] = sorted(set(summary["servers"]) | set(servers))
        summary["errors"] = errors
        summary["warnings"] = warnings
        return {
            "status": "error" if errors else "warning" if warnings else "ok",
            "message": (
                f"MCP config has blockers: {config_path}."
                if errors
                else f"MCP config has warnings: {config_path}."
                if warnings
                else f"MCP config is usable at {config_path}."
            ),
            "data": {
                **summary,
                "fix": (
                    "Fix MCP server commands/URLs in the config file."
                    if errors
                    else "Review disabled or incomplete MCP server entries."
                    if warnings
                    else "No action needed."
                ),
            },
        }
    return {
        "status": "warning",
        "message": "MCP servers are declared but no config file is linked for readiness checks.",
        "data": {
            **summary,
            "fix": "Set runtime.config.mcp_config_path so doctor can validate MCP server commands.",
        },
    }


def _permission_check(spec: HarnessSpec) -> tuple[str, str, dict[str, Any]]:
    policy = spec.execution_policy
    warnings: list[str] = []
    errors: list[str] = []
    requested_tools = {tool for agent in spec.agents for tool in agent.tools}
    if spec.is_coding and not policy.allow_write:
        warnings.append("coding harness is read-only")
    if (
        requested_tools
        & {"write_file", "create_file", "edit_file", "insert_text", "patch", "multi_edit"}
        and not policy.allow_write
    ):
        errors.append("write/edit tools are requested but allow_write is false")
    if "bash" in requested_tools and not policy.allow_shell:
        errors.append("bash tool is requested but allow_shell is false")
    if policy.allow_shell and not policy.allowed_commands:
        warnings.append("shell is enabled without an allowed_commands list")
    if policy.allow_network:
        warnings.append("network access is enabled")
    status = "error" if errors else "warning" if warnings else "ok"
    return (
        status,
        "Permission policy has blockers."
        if errors
        else "Permission policy is explicit."
        if not warnings
        else "Permission policy has warnings.",
        {
            "approval_profile": policy.approval_profile,
            "allow_read": policy.allow_read,
            "allow_write": policy.allow_write,
            "allow_shell": policy.allow_shell,
            "allow_network": policy.allow_network,
            "warnings": warnings,
            "errors": errors,
            "fix": (
                "Enable the matching execution permissions or remove the requested tools."
                if errors
                else "Consider allowed_commands for shell and disable network unless required."
                if warnings
                else "No action needed."
            ),
        },
    )


def _hooks_check(spec: HarnessSpec) -> dict[str, Any]:
    """Validate declared hook rules resolve and report the active hook surface."""
    from ..agent.hooks import ALL_HOOK_POINTS
    from .hooks import resolve_hook_handler

    warnings: list[str] = []
    errors: list[str] = []
    remembered_rules = _remembered_permission_rules_summary(spec)
    builtin = (
        ["harness_permission_policy"]
        if spec.execution_policy.permission_rules or remembered_rules
        else []
    )

    if spec.hooks.rules and not spec.hooks.enabled:
        warnings.append("hook rules are declared but hooks.enabled is false")

    resolved = 0
    if spec.hooks.enabled:
        for index, rule in enumerate(spec.hooks.rules):
            label = rule.name or rule.handler or f"rule[{index}]"
            if rule.point not in ALL_HOOK_POINTS:
                errors.append(
                    f"{label}: unknown hook point '{rule.point}' "
                    f"(valid: {_join(list(ALL_HOOK_POINTS))})"
                )
                continue
            try:
                resolve_hook_handler(rule.handler)
                resolved += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: handler '{rule.handler}' did not resolve ({exc})")

    total = resolved + len(builtin)
    status = "error" if errors else "warning" if warnings else "ok"
    if errors:
        message = "Hook rules have blockers."
    elif total == 0:
        message = "No hooks configured."
    else:
        message = f"{total} hook(s) active."
    return {
        "status": status,
        "message": message,
        "data": {
            "enabled": spec.hooks.enabled,
            "declared": len(spec.hooks.rules),
            "resolved": resolved,
            "builtin": builtin,
            "warnings": warnings,
            "errors": errors,
            "fix": (
                "Fix the handler import paths / hook points listed above."
                if errors
                else "Set hooks.enabled: true to activate declared rules."
                if warnings
                else "No action needed."
            ),
        },
    }


def _sandbox_check(name: str) -> dict[str, Any]:
    if name in {"", "none"}:
        return {
            "status": "ok",
            "message": "No sandbox is requested.",
            "data": {"backend": "none"},
        }
    try:
        caps = get_sandbox_capabilities(name)
    except ValueError as exc:
        return {
            "status": "error",
            "message": f"Unknown sandbox backend '{name}': {exc}",
            "data": {
                "backend": name,
                "fix": "Use a supported sandbox backend or set sandbox: none.",
            },
        }
    return {
        "status": "ok",
        "message": f"Sandbox policy '{name}' is recognized.",
        "data": {
            "backend": caps.backend.value,
            "can_read": caps.can_read,
            "can_write": caps.can_write,
            "can_shell": caps.can_shell,
            "can_network": caps.can_network,
            "description": caps.description,
            "fix": "No action needed.",
        },
    }


def _checks_check(spec: HarnessSpec, root: Path) -> dict[str, Any]:
    if not spec.checks.enabled:
        return {
            "status": "warning",
            "message": "Checks is disabled.",
            "data": {
                "enabled": False,
                "fix": "Add checks.custom_steps when this harness should prove changes before completion.",
            },
        }
    steps = [step for step in spec.checks.custom_steps if step.enabled]
    if not steps:
        return {
            "status": "warning",
            "message": "Checks is enabled but no custom checks steps are configured.",
            "data": {
                "enabled": True,
                "steps": [],
                "fix": "Add commands such as tests, lint, typecheck, or project smoke checks.",
            },
        }
    missing: list[str] = []
    malformed: list[str] = []
    for step in steps:
        command = step.command.strip()
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
            malformed.append(step.name)
        executable = parts[0] if parts else ""
        if executable and not shutil.which(executable) and not (root / executable).exists():
            missing.append(step.name)
        elif not executable:
            malformed.append(step.name)
    blockers = sorted(set(missing + malformed))
    return {
        "status": "error" if blockers else "ok",
        "message": (
            "Checks commands look executable."
            if not blockers
            else "Some checks commands are missing or malformed."
        ),
        "data": {
            "enabled": True,
            "steps": [step.name for step in steps],
            "missing": missing,
            "malformed": malformed,
            "fix": (
                "Install missing checks executables or update checks.custom_steps commands."
                if blockers
                else "No action needed."
            ),
        },
    }


def _permission_rules_summary(spec: HarnessSpec) -> list[dict[str, Any]]:
    """Readable list of declared rule-based approval rules."""
    rules: list[dict[str, Any]] = []
    for rule in spec.execution_policy.permission_rules:
        entry: dict[str, Any] = {"tool": rule.tool, "action": rule.action}
        if rule.argument:
            entry["argument"] = rule.argument
        if rule.pattern and rule.pattern != "*":
            entry["pattern"] = rule.pattern
        rules.append(entry)
    return rules


def _remembered_permission_rules_summary(spec: HarnessSpec) -> list[dict[str, Any]]:
    """Readable list of approval-memory rules."""
    try:
        from .approval_memory import load_approval_memory_rules

        remembered = load_approval_memory_rules(spec)
    except Exception:  # noqa: BLE001 - diagnostics must stay best-effort
        return []
    return [
        {
            key: value
            for key, value in {
                "tool": rule.tool,
                "action": rule.action,
                "argument": rule.argument,
                "pattern": rule.pattern if rule.pattern and rule.pattern != "*" else "",
            }.items()
            if value not in ("", None)
        }
        for rule in remembered
    ]


def _hooks_summary(spec: HarnessSpec) -> dict[str, Any]:
    """Readable summary of declared lifecycle hooks + the built-in policy hook."""
    declared = [
        {
            key: value
            for key, value in {
                "point": rule.point,
                "handler": rule.handler,
                "matcher": rule.matcher if rule.matcher and rule.matcher != "*" else None,
                "name": rule.name or None,
            }.items()
            if value is not None
        }
        for rule in spec.hooks.rules
    ]
    builtin = []
    remembered_count = len(_remembered_permission_rules_summary(spec))
    total_policy_rules = len(spec.execution_policy.permission_rules) + remembered_count
    if total_policy_rules:
        builtin.append(
            {
                "point": "permission_request",
                "handler": "harness_permission_policy",
                "rules": total_policy_rules,
            }
        )
    return {
        "enabled": spec.hooks.enabled,
        "declared": declared,
        "builtin": builtin,
        "count": (len(declared) if spec.hooks.enabled else 0) + len(builtin),
    }


def _mcp_summary(spec: HarnessSpec) -> dict[str, Any]:
    runtime_config = spec.runtime.config
    raw = runtime_config.get("mcp_servers") or runtime_config.get("mcp")
    servers: list[str] = []
    if isinstance(raw, dict):
        servers = sorted(str(key) for key in raw)
    elif isinstance(raw, list):
        servers = [str(item) for item in raw]
    pydanticai_config = runtime_config.get("pydanticai", {})
    config_path = None
    if isinstance(pydanticai_config, dict):
        config_path = pydanticai_config.get("mcp_config_path") or pydanticai_config.get(
            "mcp_config"
        )
    config_path = (
        config_path or runtime_config.get("mcp_config_path") or runtime_config.get("mcp_config")
    )
    return {"servers": servers, "config_path": str(config_path) if config_path else None}


def _inspect_mcp_config(config_path: Path, root: Path) -> tuple[list[str], list[str], list[str]]:
    servers = load_mcp_config(config_path)
    names: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    if not servers:
        warnings.append("config has no enabled or parseable servers")
        return names, errors, warnings
    for server_id, server in servers.items():
        names.append(server_id)
        if not server.enabled:
            warnings.append(f"{server_id} is disabled")
            continue
        config = server.config
        if isinstance(config, MCPStdioConfig):
            if not config.command:
                errors.append(f"{server_id} has no stdio command")
            elif not shutil.which(config.command) and not _resolve(root, config.command).exists():
                errors.append(f"{server_id} command not found: {config.command}")
            if config.cwd and not _resolve(root, config.cwd).exists():
                errors.append(f"{server_id} cwd does not exist: {config.cwd}")
        elif isinstance(config, (MCPHttpConfig, MCPSSEConfig)):
            if not config.url:
                errors.append(f"{server_id} has no URL")
            elif not str(config.url).startswith(("http://", "https://")):
                errors.append(f"{server_id} URL must start with http:// or https://")
        else:
            errors.append(f"{server_id} has unknown MCP transport")
    return names, errors, warnings


def _provider_from_model(model: str) -> str:
    if "/" not in model:
        return ""
    prefix = model.split("/", 1)[0].strip().lower()
    if prefix in PROVIDERS:
        return prefix
    litellm_prefixes = {
        provider.litellm_prefix.rstrip("/"): provider_id
        for provider_id, provider in PROVIDERS.items()
        if provider.litellm_prefix
    }
    return litellm_prefixes.get(prefix, "")


def _model_without_provider(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def _model_policy_fix(provider: str, errors: list[str], warnings: list[str]) -> str:
    if errors:
        return (
            "Set model_policy.config.provider to a known provider or remove the invalid provider."
        )
    if provider in PROVIDERS and any("API key" in warning for warning in warnings):
        envs = PROVIDERS[provider].env_vars
        return f"Export one of: {_join(envs)}."
    if warnings:
        return "Confirm the model/provider names or set an explicit provider in model_policy.config.provider."
    return "No action needed."


def _assert_store_writable(store_kind: str, target_root: Path) -> None:
    if store_kind == "memory":
        return
    if store_kind == "sqlite":
        path = target_root
        if path.exists() and path.is_dir():
            path = path / "store.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".superqode-doctor-write-test"
    else:
        target_root.mkdir(parents=True, exist_ok=True)
        probe = target_root / ".superqode-doctor-write-test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)


def _severity(status: str) -> str:
    if status == "error":
        return "blocker"
    if status == "warning":
        return "warning"
    return "info"


def _skill_names(skills_dir: Path) -> set[str]:
    names: set[str] = set()
    if not skills_dir.exists():
        return names
    frontmatter_available = importlib.util.find_spec("frontmatter") is not None
    for path in skills_dir.rglob("*.md"):
        names.add(path.parent.name if path.name.upper() == "SKILL.MD" else path.stem)
        if frontmatter_available:
            try:
                import frontmatter

                post = frontmatter.loads(path.read_text(encoding="utf-8"))
                name = str(post.metadata.get("name") or "").strip()
                if name:
                    names.add(name)
            except Exception:
                continue
    return names


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _safe_node_id(value: str) -> str:
    return (
        "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-")
        or "step"
    )


def _join(values: list[str] | tuple[str, ...]) -> str:
    return ", ".join(values) if values else "-"


def dumps_json(data: Any) -> str:
    """Return stable JSON for CLI outputs."""
    return json.dumps(data, indent=2, sort_keys=True)
