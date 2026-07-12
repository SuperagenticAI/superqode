"""Tests for the interactive harness wizard builder."""

from __future__ import annotations

import pytest

from superqode.harness import (
    WizardAnswers,
    build_wizard_spec,
    harness_spec_to_dict,
    load_harness_spec,
    save_harness_spec,
)
from superqode.harness.spec import WorkflowMode


def test_wizard_qwen_starter_carries_pack():
    spec = build_wizard_spec(WizardAnswers(name="q", starter="qwen-coding"))
    assert spec.model_policy.pack == "qwen-coder"
    assert spec.model_policy.primary == "ollama/qwen3-coder"
    assert spec.metadata["built_with"] == "harness wizard"


def test_wizard_glm_starter():
    spec = build_wizard_spec(WizardAnswers(name="g", starter="glm-coding"))
    assert spec.model_policy.pack == "glm"


def test_wizard_glm52_zai_starter():
    spec = build_wizard_spec(WizardAnswers(name="g52", starter="glm52-coding"))

    assert spec.model_policy.primary == "zai/glm-5.2"
    assert spec.model_policy.fallbacks == ("zai/glm-5.1", "zai/glm-5")
    assert spec.model_policy.pack == "glm"
    assert spec.model_policy.reasoning == "max"
    assert spec.model_policy.context_window == 1_000_000
    assert spec.model_policy.config["parallel_tools"] is True
    assert spec.metadata["api_endpoint"] == "general"


def test_wizard_minimax_starter():
    spec = build_wizard_spec(WizardAnswers(name="mm", starter="minimax-coding"))
    assert spec.model_policy.pack == "minimax"
    assert spec.model_policy.reasoning == "medium"


def test_wizard_permission_choices_apply():
    spec = build_wizard_spec(
        WizardAnswers(
            name="ro",
            starter="qwen-coding",
            allow_write=False,
            allow_shell=False,
        )
    )
    assert spec.execution_policy.allow_read is True
    assert spec.execution_policy.allow_write is False
    assert spec.execution_policy.allow_shell is False


def test_wizard_model_override():
    spec = build_wizard_spec(
        WizardAnswers(name="m", starter="coding", provider="lmstudio", model="qwen3-coder-30b")
    )
    assert spec.model_policy.primary == "lmstudio/qwen3-coder-30b"


def test_wizard_prompt_format_override():
    spec = build_wizard_spec(
        WizardAnswers(name="p", starter="qwen-coding", tool_call_format="prompt")
    )
    assert spec.model_policy.tool_call_format == "prompt"


def test_wizard_workflow_preset_builds_chain():
    spec = build_wizard_spec(
        WizardAnswers(name="team", starter="coding", workflow_preset="plan-implement-review")
    )
    assert spec.workflow.mode == WorkflowMode.CHAIN
    assert len(spec.agents) == 3
    assert {a.id for a in spec.agents} == {"planner", "implementer", "reviewer"}


def test_wizard_no_tool_stays_locked():
    spec = build_wizard_spec(
        WizardAnswers(name="think", starter="no-tool", allow_write=True, allow_shell=True)
    )
    assert spec.is_no_tool
    assert spec.execution_policy.allow_write is False
    assert spec.execution_policy.allow_shell is False


def test_wizard_unknown_starter_rejected():
    with pytest.raises(ValueError):
        build_wizard_spec(WizardAnswers(name="x", starter="does-not-exist"))


def test_wizard_spec_round_trips_to_yaml(tmp_path):
    spec = build_wizard_spec(
        WizardAnswers(name="rt", starter="qwen-coding", workflow_preset="plan-implement-review")
    )
    path = save_harness_spec(spec, tmp_path / "wizard.yaml")
    reloaded = load_harness_spec(path)
    assert harness_spec_to_dict(reloaded)["name"] == "rt"
    assert reloaded.workflow.preset == "plan-implement-review"
