"""Failure evidence, reviewed hypotheses and paired measurements stay separate."""
# ruff: noqa: F811

import asyncio
import json

import pytest
import yaml

from test_factory_definition import project, git, rewrite  # noqa: F401
from test_factory_trials import suite_project, execution  # noqa: F401
from test_factory_verification import simulated_probes  # noqa: F401
from superqode.factory import feedback, trials
from superqode.factory.runtime import factory_store
from superqode.factory.snapshot import FactorySnapshot


def finish(root, plan):
    for _ in range(4):
        board = asyncio.run(trials.advance(root, plan["id"], plan["digest"]))
        waiting = next((r for r in board["entries"] if r["gates"]), None)
        if not waiting:
            return board
        gate = waiting["gates"][0]
        trials.gate(
            root,
            plan["id"],
            waiting["id"],
            gate["stage"],
            gate["digest"],
            "approve",
            "Test-only operator",
        )
    raise AssertionError("Unexpected number of gates")


@pytest.fixture
def failure(suite_project, simulated_probes, monkeypatch):
    root, suite = suite_project

    async def execute(order, task, *, working_directory, **kwargs):
        if task.task_id == "implement":
            (working_directory / "app.py").write_text("print(43)\n")
        failed = (
            task.task_id == "verify"
            and "candidate" in str(working_directory)
            and task.attempts == 1
        )
        return {
            "content": "Test-only execution",
            "stopped_reason": "error" if failed else "complete",
            "error": "APIConnectionError: XML syntax error element <function> closed by </parameter>"
            if failed
            else "",
            "tokens_in": 4,
            "tokens_out": 2,
            "cost_usd": 0,
            "tool_calls": 1,
        }

    monkeypatch.setattr("superqode.workorders.runner._execute_harness_task", execute)
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    board = finish(root, plan)
    assert board["verdict"] == "hold"
    result = feedback.scan(root, plan["id"], plan["digest"])
    assert result["added_observations"] == 1 and not result["scan_issues"]
    issue = feedback.detail(root, result["issues"][0]["id"])
    return root, plan, issue


def reviewed(root, issue, category="model_protocol"):
    return feedback.review(
        root,
        issue["id"],
        issue["review_digest"],
        category,
        "reviewed",
        "Test operator: tentative protocol hypothesis; assess with paired trials.",
    )


def proposal(root, issue, value="Verify the requested behavior. Use well-formed tool calls."):
    return feedback.propose(
        root,
        issue["id"],
        issue["observations"][0]["id"],
        issue["review_digest"],
        "stage_goal",
        value,
    )


def test_dedup_retains_historical_failure_after_explicit_retry(failure):
    root, plan, issue = failure
    assert issue["suggested_category"] == "model_protocol"
    assert feedback.scan(root, plan["id"])["added_observations"] == 0
    observation = issue["observations"][0]
    trials.retry(
        root, plan["id"], observation["entry"], observation["stage"], 1, "Test explicit retry"
    )
    assert finish(root, plan)["verdict"] == "tie"
    assert feedback.scan(root, plan["id"])["added_observations"] == 0
    result = feedback.detail(root, issue["id"])
    assert len(result["observations"]) == 1
    assert result["observations"][0]["source_valid"]
    assert result["observations"][0]["current_stage_status"] == "succeeded"
    assert not result["promotion_authority"]


def test_review_cas_policy_and_proposal_preserve_frozen_contract(failure):
    root, plan, issue = failure
    with pytest.raises(ValueError, match="Review the failure first"):
        proposal(root, issue)
    current = reviewed(root, issue)
    with pytest.raises(ValueError, match="changed"):
        reviewed(root, issue)
    draft = proposal(root, current)
    assert draft["status"] == "unmeasured" and draft["model_calls"] == 0
    assert draft["runnable"] and not draft["promotion_authority"]
    directory = root / draft["suite_path"]
    baseline = FactorySnapshot.from_dict(
        json.loads((directory.parent / "baseline.json").read_text())
    )
    candidate = FactorySnapshot.from_dict(
        json.loads((directory.parent / "candidate.json").read_text())
    )
    assert baseline.digest != candidate.digest
    original = baseline.payload
    changed = candidate.payload
    assert original["definition"]["orchestration"]["stages"][2]["human_gate"]
    changed["definition"]["orchestration"]["stages"][2]["goal"] = original["definition"][
        "orchestration"
    ]["stages"][2]["goal"]
    assert original["definition"] == changed["definition"]
    assert original["harnesses"] == changed["harnesses"]
    assert (root / "app.py").read_text() == "answer = 42\n"
    assert proposal(root, current)["id"] == draft["id"]
    for i in range(2):
        proposal(root, current, "Alternate bounded verification instruction " + str(i))
    with pytest.raises(ValueError, match="three-proposal"):
        proposal(root, current, "A fourth idea")
    assert proposal(root, current)["id"] == draft["id"]
    feedback.review(
        root,
        current["id"],
        current["review_digest"],
        "model_protocol",
        "dismissed",
        "Dismiss hypothesis after inspection",
    )
    assert not feedback.get_proposal(root, current["id"], draft["id"])["runnable"]
    with pytest.raises(ValueError, match="dismissed"):
        feedback.get_proposal(root, current["id"], draft["id"], for_execution=True)


@pytest.mark.parametrize(
    "category",
    [
        "provider_infrastructure",
        "evaluation_fault",
        "evidence_or_recovery",
        "policy_budget",
        "unknown",
    ],
)
def test_non_agent_findings_require_repair(failure, category):
    root, _, issue = failure
    current = reviewed(root, issue, category)
    with pytest.raises(ValueError, match="source repair"):
        proposal(root, current)


def test_exact_pair_only_links_measurements_without_adoption(failure, execution):
    root, original, issue = failure
    current = reviewed(root, issue)
    draft = proposal(root, current)
    with pytest.raises(ValueError, match="exact proposed suite"):
        feedback.attach_evaluation(root, issue["id"], draft["id"], original["id"])
    plan = trials.prepare(root, suite_text=draft["suite_yaml"])
    result = finish(root, plan)
    assert result["verdict"] == "tie"
    linked = feedback.attach_evaluation(root, issue["id"], draft["id"], plan["id"])
    assert linked["evaluations"][0]["verdict"] == "tie"
    assert linked["status"] == "measured"
    assert not linked["promotion_authority"]
    assert (
        not factory_store(root / plan["entries"][0]["project"])
        .get(plan["entries"][0]["run"])
        .decision
    )
    assert (root / "app.py").read_text() == "answer = 42\n"


def test_changed_sources_reject_proposals_and_report_scan_issue(failure):
    root, plan, issue = failure
    current = reviewed(root, issue)
    draft = proposal(root, current)
    path = root / draft["suite_path"]
    path.write_text(path.read_text() + "# tampered\n")
    with pytest.raises(ValueError, match="source changed"):
        feedback.get_proposal(root, issue["id"], draft["id"])
    entry = plan["entries"][1]
    order = factory_store(root / entry["project"]).get(entry["run"])
    from pathlib import Path

    (Path(order.metadata["factory"]["snapshot_directory"]) / "snapshot.json").write_text("{}")
    assert feedback.scan(root, plan["id"])["scan_issues"]
    assert not feedback.detail(root, issue["id"])["observations"][0]["source_valid"]


def test_model_hypothesis_preserves_tools_and_rejects_hosted_route(failure):
    root, _, issue = failure
    current = reviewed(root, issue)
    params = (
        root,
        issue["id"],
        issue["observations"][0]["id"],
        current["review_digest"],
        "model_route",
    )
    with pytest.raises(ValueError):
        feedback.propose(*params, "openai/test-hosted-model")
    draft = feedback.propose(*params, "lmstudio/test-local-model")
    path = (root / draft["suite_path"]).parent
    before = FactorySnapshot.from_dict(json.loads((path / "baseline.json").read_text())).payload
    after = FactorySnapshot.from_dict(json.loads((path / "candidate.json").read_text())).payload
    assert before["definition"]["governance"] == after["definition"]["governance"]
    for binding, harness in before["harnesses"].items():
        assert harness["agents"] == after["harnesses"][binding]["agents"]
    assert draft["model_calls"] == 0


def test_changed_event_is_not_counted_as_a_new_incident(failure):
    root, plan, issue = failure
    observation = issue["observations"][0]
    entry = next(e for e in plan["entries"] if e["id"] == observation["entry"])
    store = factory_store(root / entry["project"])
    with store._transaction() as conn:
        conn.execute(
            "UPDATE work_order_events SET data=? WHERE event_id=?",
            (json.dumps({"error": "Changed error", "attempt": 1}), observation["event"]),
        )
    assert not feedback.detail(root, issue["id"])["observations"][0]["source_valid"]
    with pytest.raises(ValueError, match="source changed"):
        feedback.scan(root, plan["id"])
    assert feedback.list_issues(root)["issues"][0]["observations"] == 1


def test_native_feedback_requires_registration_and_explicit_mutation(
    failure, tmp_path, monkeypatch
):
    from superqode.desktop_service.service import DesktopService

    root, plan, _ = failure
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "desktop-feedback")
    try:
        identity = service.open_project(str(root))["id"]
        params = {"project": identity, "suite": plan["id"]}
        assert service.dispatch("factory.suite.feedback.list", params)["issues"]
        with pytest.raises(ValueError, match="Explicitly"):
            service.dispatch("factory.suite.feedback.scan", params)
        with pytest.raises(ValueError, match="prepared for this project"):
            service.dispatch("factory.suite.feedback.scan", {**params, "confirmed": True})
        assert not service.processes
    finally:
        service.close()


def test_safe_text_and_error_classification_are_tentative(tmp_path):
    secret = "synthetic-secret-123"
    value = feedback._text(
        f"{tmp_path}/app.py {secret} Bearer token123 api_key=abc sk-example123456789",
        tmp_path,
        [secret],
    )
    assert secret not in value and "token123" not in value and "api_key=abc" not in value
    assert "<project>/app.py" in value and "sk-example" not in value
    assert feedback._classify("APIConnectionError XML syntax error") == "model_protocol"
    assert feedback._classify("Connection refused") == "provider_infrastructure"
    assert feedback._classify("Something unexpected") == "unknown"


def test_acceptance_mismatch_uses_verified_receipt_without_copying_answers(
    suite_project, simulated_probes, monkeypatch
):
    root, suite = suite_project

    async def execute(order, task, *, working_directory, **kwargs):
        if task.task_id == "implement":
            value = 0 if "candidate" in str(working_directory) else 43
            (working_directory / "app.py").write_text(f"print({value})\n")
        return {
            "content": "Test-only execution",
            "stopped_reason": "complete",
            "tokens_in": 4,
            "tokens_out": 2,
            "cost_usd": 0,
            "tool_calls": 1,
        }

    monkeypatch.setattr("superqode.workorders.runner._execute_harness_task", execute)
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    assert finish(root, plan)["verdict"] == "regression"
    scan = feedback.scan(root, plan["id"])
    assert scan["added_observations"] == 1
    issue = feedback.detail(root, scan["issues"][0]["id"])
    assert issue["suggested_category"] == "application_defect"
    observation = issue["observations"][0]
    assert observation["source_valid"] and observation["kind"] == "acceptance_failure"
    assert observation["stage"] == "implement"
    assert "stdout" not in json.dumps(issue) and "43\\n" not in json.dumps(issue)
    assert feedback.scan(root, plan["id"])["added_observations"] == 0
