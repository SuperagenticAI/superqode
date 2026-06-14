"""Tests for plain-English harness explanations."""

from __future__ import annotations

from superqode.harness import explain_harness, harness_spec_from_dict, render_explanation


def _spec(**overrides):
    base = {
        "name": "my-coder",
        "flavor": "coding",
        "model_policy": {"primary": "ollama/qwen3-coder", "temperature": 0.1},
        "execution_policy": {"allow_write": True, "allow_shell": True},
        "agents": [{"id": "coder", "tools": ["read_file", "edit_file", "bash"]}],
    }
    base.update(overrides)
    return harness_spec_from_dict(base)


def test_explain_full_coding_harness():
    explanation = explain_harness(_spec(), provider="ollama", model="qwen3-coder")
    text = render_explanation(explanation)

    assert "coding harness" in explanation.summary
    sections = {title for title, _ in explanation.sections}
    assert {"Model", "Tools", "Permissions", "Context", "How to use it"} <= sections
    assert "Writing/editing files: allowed." in text
    assert "Running shell commands: allowed." in text


def test_explain_read_only_harness_reports_blocked():
    spec = _spec(execution_policy={"allow_write": False, "allow_shell": False})
    text = render_explanation(explain_harness(spec))

    assert "Writing/editing files: BLOCKED" in text
    assert "Running shell commands: BLOCKED" in text


def test_explain_prompt_tool_format_states_reason():
    spec = _spec(
        model_policy={"primary": "ollama/gemma4", "tool_call_format": "prompt"},
    )
    text = render_explanation(explain_harness(spec))

    assert "PROMPT format" in text
    assert "weak or unreliable native tool support" in text


def test_explain_no_tool_harness():
    spec = harness_spec_from_dict({"name": "thinker", "flavor": "no_tool"})
    explanation = explain_harness(spec)
    text = render_explanation(explanation)

    assert "model-only harness" in explanation.summary
    assert "nothing to permission" in text
    assert "PROMPT format" not in text


def test_explain_permission_rule_is_described():
    spec = _spec(
        execution_policy={
            "allow_write": True,
            "allow_shell": True,
            "permission_rules": [{"tool": "bash", "pattern": "rm *", "action": "deny"}],
        }
    )
    text = render_explanation(explain_harness(spec))

    assert "Rule: block bash matching 'rm *'." in text


def test_explanation_to_dict_round_trips():
    payload = explain_harness(_spec()).to_dict()
    assert payload["name"] == "my-coder"
    assert isinstance(payload["sections"], list)
    assert all({"title", "lines"} <= set(section) for section in payload["sections"])
