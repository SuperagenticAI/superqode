"""Explicit stage outputs are validated before integration and consumed by receipt."""
# ruff: noqa: F811

from dataclasses import replace

import pytest
import yaml

from test_factory_definition import project, git, rewrite  # noqa: F401
from test_factory_trials import suite_project  # noqa: F401
from test_factory_feedback import finish  # noqa: F401
from test_factory_verification import simulated_probes  # noqa: F401
from superqode.factory import trials, contracts, load_factory
from superqode.factory.runtime import factory_store


def declarations(root):
    def change(data):
        stages = data["orchestration"]["stages"]
        stages[0]["outputs"] = {
            "findings": {
                "type": "json",
                "fields": {"needs-fix": {"type": "boolean"}, "summary": {"type": "string"}},
            }
        }
        stages[1]["inputs"] = {"analysis": {"stage": "investigate", "output": "findings"}}
        stages[1]["outputs"] = {"patch": {"type": "text"}}
        stages[2]["inputs"] = {
            "candidate": {"stage": "implement", "output": "patch", "candidate_bound": True}
        }

    rewrite(root, change)


@pytest.fixture
def contract_execution(monkeypatch):
    calls = []

    async def execute(order, task, *, working_directory, **kwargs):
        calls.append((task.task_id, contracts.prompt(order, task)))
        outputs = {}
        if task.task_id == "investigate":
            outputs = {"findings": {"needs-fix": True, "summary": "Implement accumulation"}}
        if task.task_id == "implement":
            (working_directory / "app.py").write_text("print(43)\n")
            outputs = {"patch": "Changed app.py to satisfy the requested output"}
        return {
            "content": "Test-only execution",
            "outputs": outputs,
            "stopped_reason": "complete",
            "tokens_in": 4,
            "tokens_out": 2,
            "cost_usd": 0,
            "tool_calls": 1,
        }

    monkeypatch.setattr("superqode.workorders.runner._execute_harness_task", execute)
    return calls, execute


def test_explicit_handoffs_bind_values_provenance_and_candidate(
    suite_project, simulated_probes, contract_execution
):
    root, suite = suite_project
    declarations(root)
    suite["candidate"] = suite["baseline"]
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    assert finish(root, plan)["verdict"] == "tie"
    calls, _ = contract_execution
    assert "Implement accumulation" in next(
        prompt for stage, prompt in calls if stage == "implement"
    )
    assert "candidate_tree" in next(prompt for stage, prompt in calls if stage == "verify")
    for entry in plan["entries"]:
        order = factory_store(root / entry["project"]).get(entry["run"])
        assert len([a for a in order.artifacts if a.kind == "factory_stage_output"]) == 2
        values, references = contracts.resolve_inputs(order, order.tasks[-1])
        assert values["candidate"] and references["candidate"]["artifact"]
    assert (root / "app.py").read_text() == "answer = 42\n"


@pytest.mark.parametrize("bad", ["type", "missing"])
def test_bad_output_does_not_integrate_model_patch(
    suite_project, simulated_probes, contract_execution, monkeypatch, bad
):
    root, suite = suite_project
    declarations(root)
    suite["candidate"] = suite["baseline"]
    _, execute = contract_execution

    async def invalid(order, task, **kwargs):
        result = await execute(order, task, **kwargs)
        if task.task_id == "implement":
            result["outputs"] = {"patch": False} if bad == "type" else {}
        return result

    monkeypatch.setattr("superqode.workorders.runner._execute_harness_task", invalid)
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    board = finish(root, plan)
    assert board["verdict"] == "hold"
    for entry in plan["entries"]:
        order = factory_store(root / entry["project"]).get(entry["run"])
        assert not [a for a in order.artifacts if a.kind == "task_integration"]


@pytest.mark.parametrize(
    "change", ["unknown-output", "non-predecessor", "review-role", "enum-type"]
)
def test_definition_rejects_unresolvable_or_invalid_contracts(project, change):
    declarations(project)

    def invalid(data):
        stages = data["orchestration"]["stages"]
        if change == "unknown-output":
            stages[1]["inputs"]["analysis"]["output"] = "missing"
        elif change == "non-predecessor":
            stages[0]["inputs"] = {"bad": {"stage": "implement", "output": "patch"}}
        elif change == "review-role":
            stages[0]["outputs"] = {"decision": {"type": "review"}}
        else:
            stages[0]["outputs"]["findings"]["fields"]["needs-fix"]["enum"] = ["true"]

    rewrite(project, invalid)
    with pytest.raises(ValueError):
        load_factory(root=project)


def test_changed_output_receipt_is_refused(suite_project, simulated_probes, contract_execution):
    root, suite = suite_project
    declarations(root)
    suite["candidate"] = suite["baseline"]
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    finish(root, plan)
    entry = plan["entries"][0]
    store = factory_store(root / entry["project"])
    order = store.get(entry["run"])
    artifacts = tuple(
        replace(a, content="{}") if a.kind == "factory_stage_output" else a for a in order.artifacts
    )
    damaged = replace(order, artifacts=artifacts)
    with pytest.raises(ValueError, match="digest changed"):
        contracts.resolve_inputs(damaged, damaged.tasks[-1])


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_output_json_has_no_duplicate_or_non_finite_values(text):
    with pytest.raises(ValueError):
        contracts.parse_json(text)
