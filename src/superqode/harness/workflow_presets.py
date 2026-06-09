"""Built-in workflow presets for portable HarnessSpec authoring."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .spec import AgentSpec, HarnessSpec, WorkflowMode


@dataclass(frozen=True)
class WorkflowPreset:
    """Reusable workflow topology and default agent roles."""

    name: str
    mode: WorkflowMode
    description: str
    agents: tuple[AgentSpec, ...]
    parallelism: int = 1
    config: dict[str, str] | None = None


WORKFLOW_PRESETS: dict[str, WorkflowPreset] = {
    "single": WorkflowPreset(
        name="single",
        mode=WorkflowMode.SINGLE,
        description="One general coding agent handles the task.",
        agents=(AgentSpec(id="coder", role="General coding agent"),),
    ),
    "plan-implement-review": WorkflowPreset(
        name="plan-implement-review",
        mode=WorkflowMode.CHAIN,
        description="Planner creates direction, implementer changes code, reviewer checks the result.",
        agents=(
            AgentSpec(id="planner", role="Plan the implementation and risks."),
            AgentSpec(id="implementer", role="Implement the requested change."),
            AgentSpec(id="reviewer", role="Review correctness, tests, and edge cases."),
        ),
    ),
    "parallel-review": WorkflowPreset(
        name="parallel-review",
        mode=WorkflowMode.ORCHESTRATOR,
        description="Run focused reviewers in parallel, then synthesize one final answer.",
        agents=(
            AgentSpec(id="security", role="Review security and data-safety risks."),
            AgentSpec(id="tests", role="Review missing or weak tests."),
            AgentSpec(
                id="architecture", role="Review design, maintainability, and integration risk."
            ),
        ),
        parallelism=3,
        config={
            "synthesis_prompt": "Merge the reviewer findings into one prioritized engineering report."
        },
    ),
    "fix-and-verify": WorkflowPreset(
        name="fix-and-verify",
        mode=WorkflowMode.CHAIN,
        description="Plan the fix, implement it, then verify behavior and tests.",
        agents=(
            AgentSpec(id="planner", role="Identify the likely fix path and risks."),
            AgentSpec(id="implementer", role="Apply the code change with repository tools."),
            AgentSpec(
                id="verifier", role="Run checks, inspect changed files, and summarize evidence."
            ),
        ),
    ),
    "security-review": WorkflowPreset(
        name="security-review",
        mode=WorkflowMode.ORCHESTRATOR,
        description="Review code through security, data-flow, and dependency-risk lenses.",
        agents=(
            AgentSpec(id="appsec", role="Find application security risks and unsafe patterns."),
            AgentSpec(
                id="data-flow",
                role="Review sensitive data handling, auth boundaries, and leakage risk.",
            ),
            AgentSpec(
                id="dependency-risk", role="Review dependency, supply-chain, and runtime risk."
            ),
        ),
        parallelism=3,
        config={
            "synthesis_prompt": "Merge the security findings into one prioritized risk report."
        },
    ),
    "release-check": WorkflowPreset(
        name="release-check",
        mode=WorkflowMode.CHAIN,
        description="Check release readiness across changes, test results, docs, and operational risk.",
        agents=(
            AgentSpec(id="change-reviewer", role="Summarize the release changes and risky files."),
            AgentSpec(id="validator", role="Review test results and missing coverage."),
            AgentSpec(id="release-notes", role="Draft release notes and rollout caveats."),
        ),
    ),
    "router": WorkflowPreset(
        name="router",
        mode=WorkflowMode.ROUTER,
        description="Route each task to the most relevant specialist.",
        agents=(
            AgentSpec(id="frontend", role="Handle UI, interaction, and client-side code."),
            AgentSpec(id="backend", role="Handle APIs, data flow, and server-side code."),
            AgentSpec(id="devops", role="Handle CI, deployment, infra, and environment issues."),
        ),
    ),
    "evaluator-optimizer": WorkflowPreset(
        name="evaluator-optimizer",
        mode=WorkflowMode.EVALUATOR_OPTIMIZER,
        description="Generate a candidate, evaluate it, and improve it when needed.",
        agents=(
            AgentSpec(id="candidate", role="Produce the first candidate result."),
            AgentSpec(id="evaluator", role="Judge the candidate and identify improvements."),
            AgentSpec(id="optimizer", role="Improve the candidate based on evaluator feedback."),
        ),
    ),
}


def list_workflow_presets() -> tuple[WorkflowPreset, ...]:
    """Return built-in workflow presets sorted by name."""
    return tuple(WORKFLOW_PRESETS[name] for name in sorted(WORKFLOW_PRESETS))


def get_workflow_preset(name: str) -> WorkflowPreset:
    """Return a workflow preset by name."""
    normalized = name.strip().lower().replace("_", "-")
    if normalized not in WORKFLOW_PRESETS:
        valid = ", ".join(sorted(WORKFLOW_PRESETS))
        raise ValueError(f"Unknown workflow preset {name!r}. Valid presets: {valid}")
    return WORKFLOW_PRESETS[normalized]


def apply_workflow_preset(spec: HarnessSpec) -> HarnessSpec:
    """Apply a workflow preset to a HarnessSpec.

    User-defined agents are preserved. If no agents are defined, the preset's
    default roles become the harness agents.
    """
    preset_name = spec.workflow.preset.strip()
    if not preset_name:
        return spec
    preset = get_workflow_preset(preset_name)
    workflow = replace(
        spec.workflow,
        mode=preset.mode,
        parallelism=max(spec.workflow.parallelism, preset.parallelism),
        config={**(preset.config or {}), **spec.workflow.config},
    )
    agents = spec.agents or preset.agents
    return replace(spec, workflow=workflow, agents=agents)
