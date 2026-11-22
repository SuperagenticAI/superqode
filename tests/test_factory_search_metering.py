"""Both Factory engines use one request ledger and never see held-out labels."""
# ruff: noqa: F811

import asyncio
import json

import pytest
import yaml

from test_factory_definition import project, git, rewrite  # noqa: F401
from test_factory_improvement import prepared, graded_report, record_fixture_usage  # noqa: F401
from superqode.factory import improvement
from superqode.factory.metering import BudgetHalt
from superqode.providers.gateway.base import GatewayResponse, Usage, Cost
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


@pytest.fixture
def native_plan(prepared):
    root, old = prepared
    path = root / old["tasks"]
    tasks = yaml.safe_load(path.read_text())
    tasks["tasks"][1]["prompt"] = "PRIVATE_HELDOUT_PROMPT must never enter reflection"
    path.write_text(yaml.safe_dump(tasks))
    rewrite(root, lambda d: d["governance"]["budget"].update(max_tokens=100, max_cost_usd=1))
    plan = improvement.prepare(
        root,
        binding="coder",
        tasks=old["tasks"],
        fixture="fixture",
        max_evals=2,
        max_seconds=60,
        target_kind="workflow",
        stage="investigate",
        reflection_model="ollama/qwen3-coder",
        optimizer_engine="evaluator-optimizer",
    )
    return root, plan


@pytest.fixture
def model(monkeypatch):
    gateway = object.__new__(LiteLLMGateway)
    calls = []

    async def generate(messages, *args, **kwargs):
        calls.append(messages)
        return GatewayResponse(
            content="stage: investigate\ngoal: Follow the overall task and return its requested output exactly.\n",
            usage=Usage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            cost=Cost(total_cost=0),
        )

    monkeypatch.setattr(gateway, "_local_chat_completion", generate)
    monkeypatch.setattr("superqode.factory.search.GatewayFactory.create", lambda **kwargs: gateway)
    return calls, gateway


def evaluator(monkeypatch, *, heldin_score=1):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        if kwargs["eval_split"] == "held-out":
            return graded_report(kwargs)
        report = {
            "variants": [
                {
                    "tasks": [
                        {
                            "score": heldin_score,
                            "status": "passed" if heldin_score else "failed",
                            "reason": "not approved by deterministic criteria",
                        }
                    ]
                }
            ]
        }
        record_fixture_usage(kwargs, report)
        return report

    monkeypatch.setattr(improvement, "run_harness_eval", evaluate)
    return calls


def test_native_search_and_final_comparison_share_usage(native_plan, model, monkeypatch):
    root, plan = native_plan
    calls = evaluator(monkeypatch)
    staged = improvement.optimize(root, plan["id"], plan["digest"])
    assert staged["optimizer"] == "evaluator-optimizer" and staged["budget"]["request_count"] == 2
    assert len(model[0]) == 1 and "PRIVATE_HELDOUT_PROMPT" not in str(model[0])
    result = asyncio.run(improvement.compare(root, plan["id"], staged["candidate"]))
    assert result["eligible"]
    summary = result["budget"]
    assert summary["request_count"] == 4 and summary["observed"]["tokens"] == 17
    phases = [o["phase"] for o in improvement.budget(root, plan).detail()["operations"]]
    assert phases == ["reflection", "held-in", "held-out", "held-out"]
    assert len(calls) == 2 and calls[-1]["eval_split"] == "held-out"
    improvement.evidence(root, plan["id"], staged["candidate"], result["receipt_digest"])


def test_native_refines_when_feedback_contains_not_approved(native_plan, model, monkeypatch):
    root, plan = native_plan
    evaluator(monkeypatch, heldin_score=0)
    staged = improvement.optimize(root, plan["id"], plan["digest"])
    assert len(model[0]) == 2 and staged["metric_calls"] == 1
    assert staged["deduplicated_proposals"] == 1
    assert staged["budget"]["request_count"] == 3


def test_missing_observer_is_unknown_not_free_usage(native_plan, model, monkeypatch):
    root, plan = native_plan

    async def unobserved(**kwargs):
        return {"variants": [{"tasks": [{"score": 1, "status": "passed"}]}]}

    monkeypatch.setattr(improvement, "run_harness_eval", unobserved)
    result = improvement.optimize(root, plan["id"], plan["digest"])
    assert result["held"] and result["budget"]["unknown_operations"] == 1
    with pytest.raises(BudgetHalt):
        improvement.budget(root, plan).check_admission()


def test_ledger_tampering_cannot_reuse_completed_comparison(native_plan, model, monkeypatch):
    root, plan = native_plan
    evaluator(monkeypatch)
    staged = improvement.optimize(root, plan["id"], plan["digest"])
    result = asyncio.run(improvement.compare(root, plan["id"], staged["candidate"]))
    path = improvement.folder(root, plan["id"]) / "usage.json"
    data = json.loads(path.read_text())
    data["requests"][0]["tokens"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="usage evidence changed"):
        improvement.evidence(root, plan["id"], staged["candidate"], result["receipt_digest"])


def test_search_usage_can_exhaust_budget_before_candidate_heldout(native_plan, model, monkeypatch):
    root, old = native_plan
    rewrite(root, lambda d: d["governance"]["budget"].update(max_tokens=12))
    plan = improvement.prepare(
        root,
        binding="coder",
        tasks=old["tasks"],
        fixture="fixture",
        max_evals=2,
        max_seconds=60,
        target_kind="workflow",
        stage="investigate",
        reflection_model="ollama/qwen3-coder",
        optimizer_engine="evaluator-optimizer",
    )
    evaluator(monkeypatch)
    staged = improvement.optimize(root, plan["id"], plan["digest"])
    result = asyncio.run(improvement.compare(root, plan["id"], staged["candidate"]))
    assert not result["eligible"] and result["budget"]["observed"]["tokens"] == 13
    assert result["budget"]["request_count"] == 3
