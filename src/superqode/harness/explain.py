"""Plain-English explanation of what a HarnessSpec actually does.

``harness compile`` prints the resolved policy as JSON. ``explain`` answers the
question a developer actually asks: "in plain words, what will this harness let
the model do, and why?" It reads the same resolved policy the runtime uses, so
the explanation is the truth, not a restatement of the YAML.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .compiler import compile_to_headless_profile
from .model_policy import resolve_harness_model_policy
from .spec import HarnessFlavor, HarnessSpec, WorkflowMode


@dataclass
class HarnessExplanation:
    """Structured, human-readable account of a harness's behavior."""

    name: str
    summary: str
    sections: list[tuple[str, list[str]]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary,
            "sections": [{"title": title, "lines": lines} for title, lines in self.sections],
        }


def _tool_phrase(tools: list[str] | None) -> str:
    if tools is None:
        return "the full coding toolset"
    if not tools:
        return "no tools"
    if len(tools) <= 6:
        return ", ".join(tools)
    head = ", ".join(tools[:6])
    return f"{head}, and {len(tools) - 6} more"


def explain_harness(
    spec: HarnessSpec,
    *,
    provider: str = "",
    model: str = "",
) -> HarnessExplanation:
    """Build a plain-English explanation from the resolved harness policy."""
    resolved = resolve_harness_model_policy(
        spec,
        provider=provider or spec.model_policy.config.get("provider", ""),
        model=model or spec.model_policy.primary or "",
    )
    profile = compile_to_headless_profile(spec)
    exec_policy = spec.execution_policy
    no_tool = spec.flavor == HarnessFlavor.NO_TOOL

    # One-sentence summary.
    if no_tool:
        summary = (
            f"'{spec.name}' is a model-only harness: it answers with text and "
            "cannot read files, edit code, or run commands."
        )
    else:
        summary = (
            f"'{spec.name}' is a coding harness: it gives the model {_tool_phrase(profile.tools)} "
            "to work in your repository, under the permission rules below."
        )

    explanation = HarnessExplanation(name=spec.name, summary=summary)

    # Model section.
    model_lines: list[str] = []
    primary = spec.model_policy.primary or (f"{provider}/{model}".strip("/") if model else "")
    if primary:
        model_lines.append(f"Primary model: {primary}.")
    if spec.model_policy.fallbacks:
        model_lines.append(f"Falls back to: {', '.join(spec.model_policy.fallbacks)}.")
    if resolved.temperature is not None:
        model_lines.append(
            f"Temperature {resolved.temperature} (lower is more deterministic, better for code)."
        )
    if spec.model_policy.context_window:
        model_lines.append(f"Context window: {spec.model_policy.context_window:,} tokens.")
    fmt = resolved.tool_call_format
    if not no_tool:
        if fmt == "prompt":
            model_lines.append(
                "Tool calls use PROMPT format: tools are described in the prompt and parsed from "
                "text, because this model has weak or unreliable native tool support."
            )
        elif fmt in ("native", "json", "harmony", "xml") and fmt:
            model_lines.append(
                f"Tool calls use {fmt.upper()} format (the model's native tool API)."
            )
        else:
            model_lines.append("Tool calls use the runtime default for this model.")
        model_lines.append(
            "Parallel tool calls are "
            + (
                "ON."
                if resolved.parallel_tools
                else "OFF (one tool at a time, safer for local models)."
            )
        )
    iters = resolved.max_iterations
    model_lines.append(
        "Max agent steps per turn: "
        + ("unlimited (runs until the model stops)." if not iters else f"{iters}.")
    )
    explanation.sections.append(("Model", model_lines))

    if no_tool:
        explanation.sections.append(
            (
                "Tools and permissions",
                ["This harness runs no tools, so there is nothing to permission."],
            )
        )
        _append_context_section(explanation, spec)
        _append_usage_section(explanation, spec)
        return explanation

    # Tools section.
    tool_lines: list[str] = []
    if profile.tools is None:
        tool_lines.append(
            "The model gets the full coding toolset (read, search, edit, shell, todos)."
        )
    else:
        tool_lines.append(f"The model gets these tools: {', '.join(profile.tools)}.")
    explanation.sections.append(("Tools", tool_lines))

    # Permissions section: this is the part people most want explained.
    perm_lines: list[str] = []
    perm_lines.append(
        "Reading files and searching the repo: allowed."
        if exec_policy.allow_read
        else "Reading files: blocked."
    )
    perm_lines.append(
        "Writing/editing files: allowed."
        if exec_policy.allow_write
        else "Writing/editing files: BLOCKED (read-only harness)."
    )
    perm_lines.append(
        "Running shell commands: allowed."
        if exec_policy.allow_shell
        else "Running shell commands: BLOCKED."
    )
    perm_lines.append(
        "Network access: allowed."
        if exec_policy.allow_network
        else "Network access: blocked (offline by default)."
    )
    approval = exec_policy.approval_profile or "balanced"
    approval_text = {
        "yolo": "auto-approves every tool call (no prompts).",
        "balanced": "auto-approves safe reads/searches but asks before writes and shell commands.",
        "careful": "asks before most actions.",
        "deny": "denies tool calls unless an explicit rule allows them.",
    }.get(approval, f"uses the '{approval}' approval profile.")
    perm_lines.append(f"Approval profile '{approval}': {approval_text}")
    for rule in exec_policy.permission_rules:
        target = rule.tool if rule.tool != "*" else "any tool"
        pat = f" matching '{rule.pattern}'" if rule.pattern not in ("", "*") else ""
        verb = {"allow": "auto-allow", "deny": "block", "ask": "ask before"}.get(
            rule.action, rule.action
        )
        perm_lines.append(f"Rule: {verb} {target}{pat}.")
    if exec_policy.allowed_commands:
        perm_lines.append(f"Shell allow-list: {', '.join(exec_policy.allowed_commands)}.")
    if exec_policy.blocked_categories:
        perm_lines.append(
            f"Blocked command categories: {', '.join(exec_policy.blocked_categories)}."
        )
    perm_lines.append(f"Sandbox: {exec_policy.sandbox}.")
    explanation.sections.append(("Permissions", perm_lines))

    # Workflow section.
    wf = spec.workflow
    wf_lines: list[str] = []
    if wf.mode == WorkflowMode.SINGLE:
        wf_lines.append("Single agent handles the whole task.")
    else:
        label = wf.preset or wf.mode.value
        wf_lines.append(
            f"Multi-agent workflow ({label}): the task flows through more than one agent role "
            f"(for example planner, implementer, reviewer)."
        )
        if wf.parallelism > 1:
            wf_lines.append(f"Up to {wf.parallelism} agents run in parallel.")
    if spec.agents and len(spec.agents) > 1:
        roles = ", ".join(f"{a.id} ({a.role})" if a.role else a.id for a in spec.agents)
        wf_lines.append(f"Agents: {roles}.")
    explanation.sections.append(("Workflow", wf_lines))

    _append_context_section(explanation, spec)

    # Checks / hooks.
    extra: list[str] = []
    if spec.checks.enabled and spec.checks.custom_steps:
        names = ", ".join(step.name for step in spec.checks.custom_steps)
        extra.append(f"Runs verification steps after edits: {names}.")
    if spec.hooks.enabled and spec.hooks.rules:
        points = ", ".join(sorted({rule.point for rule in spec.hooks.rules}))
        extra.append(f"Custom hooks fire at: {points}.")
    if extra:
        explanation.sections.append(("Checks and hooks", extra))

    _append_usage_section(explanation, spec)
    return explanation


def _append_context_section(explanation: HarnessExplanation, spec: HarnessSpec) -> None:
    ctx = spec.context
    lines: list[str] = []
    if ctx.instruction_files:
        lines.append(
            f"Auto-loads instructions from: {', '.join(ctx.instruction_files)} (if present)."
        )
    compaction = ctx.compaction or {}
    if compaction:
        threshold = compaction.get("threshold")
        if threshold:
            lines.append(
                f"Compacts the conversation at {int(float(threshold) * 100)}% of the model's context window."
            )
        else:
            lines.append("Conversation compaction is configured for long sessions.")
    else:
        lines.append("Compaction auto-scales to the loaded model's context window.")
    lines.append(f"Sessions are stored in {ctx.session_storage} (resumable).")
    explanation.sections.append(("Context", lines))


def _append_usage_section(explanation: HarnessExplanation, spec: HarnessSpec) -> None:
    explanation.sections.append(
        (
            "How to use it",
            [
                "Interactive:  superqode --harness <file>.yaml",
                'Headless:     superqode harness run --spec <file>.yaml -p "<task>"',
                "Verify policy: superqode harness compile --spec <file>.yaml",
            ],
        )
    )


def render_explanation(explanation: HarnessExplanation) -> str:
    lines = [f"Harness: {explanation.name}", "", explanation.summary, ""]
    for title, body in explanation.sections:
        lines.append(f"{title}")
        for item in body:
            lines.append(f"  - {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["HarnessExplanation", "explain_harness", "render_explanation"]
