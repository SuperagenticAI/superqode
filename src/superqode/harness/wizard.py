"""Interactive builder for harness specs.

Nobody should hand-write ``harness.yaml``. The wizard asks a short series of
plain questions, starts from a model-family-optimized template, applies the
answers, and writes a ready-to-edit spec. The question-answering and the
spec-building are kept separate so the build step is easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .spec import ExecutionPolicySpec, HarnessSpec, ModelPolicySpec, WorkflowSpec
from .templates import BUILTIN_TEMPLATES, get_harness_template

# Model-family starters surfaced by the wizard, in the order shown.
WIZARD_STARTERS: tuple[tuple[str, str], ...] = (
    ("qwen-coding", "Qwen Coder (local, native tools, low temperature)"),
    ("glm-coding", "GLM 4.x/5.x (strong agentic coder, native tools)"),
    ("gemma4-coding", "Gemma 4 (local MLX, strict-JSON tool calls)"),
    ("ds4-coding", "DeepSeek/DS4 (compact-JSON tool calls)"),
    ("coding", "Generic coding (any model)"),
    ("no-tool", "Model-only (no tools, reasoning/review)"),
)

APPROVAL_PROFILES: tuple[tuple[str, str], ...] = (
    ("balanced", "Auto-approve safe reads/searches, ask before writes and shell"),
    ("careful", "Ask before most actions"),
    ("yolo", "Auto-approve everything (no prompts)"),
)

TOOL_CALL_FORMATS: tuple[tuple[str, str], ...] = (
    ("auto", "Use the template/model default"),
    ("native", "Model's native tool API (capable models)"),
    ("prompt", "Tools described in the prompt, parsed from text (weak models)"),
)


@dataclass
class WizardAnswers:
    """Everything the wizard needs to assemble a spec."""

    name: str = "my-harness"
    starter: str = "qwen-coding"
    provider: str = ""
    model: str = ""
    allow_write: bool = True
    allow_shell: bool = True
    allow_network: bool = False
    approval_profile: str = "balanced"
    tool_call_format: str = "auto"
    workflow_preset: str = "single"
    metadata_extra: dict = field(default_factory=dict)


def build_wizard_spec(answers: WizardAnswers) -> HarnessSpec:
    """Turn wizard answers into a HarnessSpec, ready to save and run."""
    if answers.starter not in BUILTIN_TEMPLATES:
        valid = ", ".join(sorted(BUILTIN_TEMPLATES))
        raise ValueError(f"Unknown starter {answers.starter!r}. Valid starters: {valid}")

    spec = replace(get_harness_template(answers.starter), name=answers.name)
    no_tool = spec.is_no_tool

    # Model policy: keep the template's tuning, override only what the user set.
    primary = spec.model_policy.primary
    if answers.model:
        primary = f"{answers.provider}/{answers.model}".strip("/") if answers.provider else answers.model
    elif answers.provider and primary and "/" not in primary:
        primary = f"{answers.provider}/{primary}"
    tool_format = spec.model_policy.tool_call_format
    if answers.tool_call_format and answers.tool_call_format != "auto":
        tool_format = answers.tool_call_format
    spec = replace(
        spec,
        model_policy=replace(
            spec.model_policy,
            primary=primary,
            tool_call_format=tool_format,
        ),
    )

    # Execution policy: a no-tool harness stays locked down.
    if not no_tool:
        spec = replace(
            spec,
            execution_policy=replace(
                spec.execution_policy,
                allow_read=True,
                allow_write=answers.allow_write,
                allow_shell=answers.allow_shell,
                allow_network=answers.allow_network,
                approval_profile=answers.approval_profile or "balanced",
            ),
        )

    # Workflow preset (multi-agent topology) if the user picked one.
    preset = (answers.workflow_preset or "single").strip().lower()
    if preset and preset != "single" and not no_tool:
        from .workflow_presets import apply_workflow_preset, get_workflow_preset

        wf_preset = get_workflow_preset(preset)
        base_agent = spec.agents[0] if spec.agents else None
        inherited_tools = base_agent.tools if base_agent else ()
        inherited_skills = base_agent.skills if base_agent else ()
        preset_agents = tuple(
            replace(
                agent,
                tools=agent.tools or inherited_tools,
                skills=agent.skills or inherited_skills,
            )
            for agent in wf_preset.agents
        )
        spec = replace(spec, workflow=WorkflowSpec(preset=wf_preset.name), agents=preset_agents)
        spec = apply_workflow_preset(spec)

    metadata = dict(spec.metadata)
    metadata["built_with"] = "harness wizard"
    if answers.metadata_extra:
        metadata.update(answers.metadata_extra)
    spec = replace(spec, metadata=metadata)
    return spec


__all__ = [
    "APPROVAL_PROFILES",
    "TOOL_CALL_FORMATS",
    "WIZARD_STARTERS",
    "WizardAnswers",
    "build_wizard_spec",
]
