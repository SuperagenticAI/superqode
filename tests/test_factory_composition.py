"""Finite revision DAGs, conditional skips, exact reviewer evidence and fixed budgets."""
# ruff: noqa: F811

from dataclasses import replace

import pytest
import yaml

from test_factory_definition import project, rewrite  # noqa: F401
from test_factory_trials import suite_project  # noqa: F401
from test_factory_feedback import finish  # noqa: F401
from test_factory_verification import simulated_probes  # noqa: F401
from superqode.factory import trials, contracts, load_factory
from superqode.factory.runtime import factory_store, validate_factory_order


def composition(root, *, loop=True, gated=False):
    def change(data):
        stages = data["orchestration"]["stages"]
        stages[0]["outputs"] = {
            "analysis": {"type": "json", "fields": {"needs-fix": {"type": "boolean"}}}
        }
        stages[1]["outputs"] = {"patch": {"type": "text"}}
        review = {
            "id": "review",
            "role": "reviewer",
            "harness": "coder",
            "goal": "Review the exact candidate; return structured findings.",
            "depends_on": ["implement"],
            "inputs": {
                "candidate": {"stage": "implement", "output": "patch", "candidate_bound": True}
            },
            "outputs": {"decision": {"type": "review"}},
        }
        stages.insert(2, review)
        stages[3]["depends_on"] = ["review"]
        stages[3]["inputs"] = {
            "decision": {"stage": "review", "output": "decision", "candidate_bound": True}
        }
        if loop:
            data["orchestration"]["revision_loop"] = {
                "implement": "implement",
                "review": "review",
                "max_iterations": 3,
            }
        else:
            stages[1]["inputs"] = {"analysis": {"stage": "investigate", "output": "analysis"}}
            stages[1]["when"] = {"input": "analysis", "field": "needs-fix", "equals": True}
            stages[1]["human_gate"] = gated
            review["inputs"]["candidate"]["optional"] = True
            # A non-selected writer is optional; the review still evaluates the exact candidate.
            review["inputs"]["candidate"]["candidate_bound"] = False

    rewrite(root, change)


@pytest.fixture
def run_model(monkeypatch):
    calls = []
    config = {"requests": 0, "needs_fix": True}

    async def execute(order, task, *, working_directory, **kwargs):
        calls.append(task.task_id)
        origin = task.metadata["factory_stage"]
        outputs = {}
        review = None
        if origin == "investigate":
            outputs = {"analysis": {"needs-fix": config["needs_fix"]}}
        if origin in {"implement", "seed"}:
            (working_directory / "app.py").write_text("print(43)\n")
            outputs = (
                {"patch": "Candidate implements requested behavior"}
                if origin == "implement"
                else {}
            )
        if origin == "review":
            iteration = (
                task.metadata.get("factory_contract", {}).get("loop", {}).get("iteration", 1)
            )
            verdict = "changes_requested" if iteration <= config["requests"] else "approved"
            review = {
                "verdict": verdict,
                "summary": "Test-only review",
                "issues": ["Use a clearer implementation"]
                if verdict == "changes_requested"
                else [],
            }
            outputs = {"decision": review}
        return {
            "content": "Test-only execution",
            "outputs": outputs,
            **({"review": review} if review else {}),
            "stopped_reason": "complete",
            "tokens_in": 4,
            "tokens_out": 2,
            "cost_usd": 0,
            "tool_calls": 1,
        }

    monkeypatch.setattr("superqode.workorders.runner._execute_harness_task", execute)
    return calls, config


@pytest.mark.parametrize("requests,executions,skipped", [(0, 4, 4), (1, 6, 2), (3, 7, 0)])
def test_revision_loop_early_exit_revision_and_ceiling(
    suite_project, simulated_probes, run_model, requests, executions, skipped
):
    root, suite = suite_project
    composition(root)
    suite["candidate"] = suite["baseline"]
    calls, config = run_model
    config["requests"] = requests
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    board = finish(root, plan)
    assert board["verdict"] == ("hold" if requests == 3 else "tie")
    assert len(calls) == executions * 2
    for entry in plan["entries"]:
        store = factory_store(root / entry["project"])
        order = store.get(entry["run"])
        assert sum(t.status.value == "skipped" for t in order.tasks) == skipped
        assert all(t.attempts == 0 for t in order.tasks if t.status.value == "skipped")
        assert len([e for e in store.events(entry["run"]) if e.type == "task.skipped"]) == skipped
        if requests < 3:
            validate_factory_order(order, store=store)
            if requests == 0:
                skipped_task = next(t for t in order.tasks if t.status.value == "skipped")
                changed = replace(
                    skipped_task,
                    metadata={**skipped_task.metadata, "factory_skip_receipt": "changed"},
                )
                damaged = replace(
                    order,
                    tasks=tuple(
                        changed if t.task_id == changed.task_id else t for t in order.tasks
                    ),
                )
                with pytest.raises(ValueError, match="Skipped stage"):
                    validate_factory_order(damaged, store=store)
            values, _ = contracts.resolve_inputs(order, order.tasks[-1])
            assert values["decision"]["verdict"] == "approved"
        else:
            assert any(
                t.status.value == "blocked" and "Reviewer requested changes" in t.error
                for t in order.tasks
            )
    assert (root / "app.py").read_text() == "answer = 42\n"


def test_false_branch_skips_before_its_human_gate(suite_project, simulated_probes, run_model):
    root, suite = suite_project
    composition(root, loop=False, gated=True)

    def seed(data):
        stages = data["orchestration"]["stages"]
        stages[1]["depends_on"] = ["seed"]
        stages.insert(
            1,
            {
                "id": "seed",
                "role": "implementer",
                "harness": "coder",
                "depends_on": ["investigate"],
                "goal": "Prepare the candidate; the optional follow-up writer may be skipped.",
            },
        )

    rewrite(root, seed)
    suite["candidate"] = suite["baseline"]
    _, config = run_model
    config["needs_fix"] = False
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    board = finish(root, plan)
    assert board["verdict"] == "tie"
    assert board["summary"]["baseline"]["passed"] == 1
    assert "implement" not in run_model[0]
    for entry in plan["entries"]:
        order = factory_store(root / entry["project"]).get(entry["run"])
        writer = next(t for t in order.tasks if t.task_id == "implement")
        assert writer.status.value == "skipped" and writer.attempts == 0


def test_post_review_change_cannot_reuse_candidate_bound_approval(
    suite_project, simulated_probes, run_model, monkeypatch
):
    root, suite = suite_project
    composition(root)
    suite["candidate"] = suite["baseline"]

    def change(data):
        stages = data["orchestration"]["stages"]
        stages[-1]["depends_on"] = ["after-review"]
        stages.insert(
            -1,
            {
                "id": "after-review",
                "role": "implementer",
                "harness": "coder",
                "depends_on": ["review"],
                "goal": "Change candidate after review",
            },
        )

    rewrite(root, change)
    from superqode.workorders import runner

    execute = runner._execute_harness_task

    async def modified(order, task, *, working_directory, **kwargs):
        result = await execute(order, task, working_directory=working_directory, **kwargs)
        if task.task_id == "after-review":
            (working_directory / "app.py").write_text(
                "print(43) # candidate changed after review\n"
            )
        return result

    monkeypatch.setattr(runner, "_execute_harness_task", modified)
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    assert finish(root, plan)["verdict"] == "hold"
    assert "verify" not in run_model[0]


@pytest.mark.parametrize(
    "change", ["loop-bound", "review-type", "candidate-bound", "collision", "predicate"]
)
def test_composition_schema_rejects_unsafe_or_ambiguous_graphs(project, change):
    composition(project)

    def invalid(data):
        stages = data["orchestration"]["stages"]
        if change == "loop-bound":
            data["orchestration"]["revision_loop"]["max_iterations"] = 100
        elif change == "review-type":
            stages[2]["outputs"]["decision"]["type"] = "text"
        elif change == "candidate-bound":
            stages[2]["inputs"]["candidate"]["candidate_bound"] = False
        elif change == "collision":
            stages.append(
                {"id": "implement-r1", "role": "tester", "harness": "coder", "goal": "Collision"}
            )
        else:
            stages[0]["when"] = {"input": "unknown", "equals": True}

    rewrite(project, invalid)
    with pytest.raises(ValueError):
        load_factory(root=project)
