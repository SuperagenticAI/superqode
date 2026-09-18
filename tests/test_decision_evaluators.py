"""Decision labels, abstention, and rubric errors must remain distinct."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from superqode.harness.evaluators import evaluate_content, validate_evaluator
from superqode.agent.rubric import evaluate_jev_rubric, grade_against_rubric
from superqode.systemone.client import SystemOneError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,status",
    [
        ({"status": "decided", "outputs": {"route": "review"}}, "passed"),
        ({"status": "decided", "outputs": {"route": "cheap"}}, "failed"),
        ({"status": "abstain", "outputs": {"route": None}}, "abstained"),
        ({"status": "error", "outputs": {"route": "review"}}, "error"),
        ([], "error"),
    ],
)
async def test_labelled_decisions(payload, status):
    result = await evaluate_content(
        json.dumps(payload), {"evaluator": {"type": "decision", "expected": {"route": "review"}}}
    )
    assert result.status == status


@pytest.mark.asyncio
async def test_labels_are_typed():
    result = await evaluate_content(
        '{"outputs": {"urgent": 1}}',
        {"evaluator": {"type": "decision", "expected": {"urgent": True}}},
    )
    assert result.status == "failed"


@pytest.mark.parametrize(
    "config", [{"type": "unknown"}, {"type": "decision", "expected": {}}, {"type": "jev_rubric"}]
)
def test_bad_evaluator_fails_before_execution(config):
    with pytest.raises(ValueError):
        validate_evaluator({"evaluator": config})


@pytest.mark.asyncio
async def test_jev_failure_is_ungraded():
    client = SimpleNamespace(
        name="test", evaluate=AsyncMock(side_effect=SystemOneError("private body"))
    )
    result = await evaluate_jev_rubric("Tests pass", "work", client=client)
    assert result["verdict"] == "ungraded"
    assert "private body" not in json.dumps(result)


@pytest.mark.asyncio
async def test_offline_rubric_never_calls_client(monkeypatch):
    from superqode.harness.spec import HarnessSpec
    from superqode.systemone import live

    constructor = AsyncMock()
    monkeypatch.setattr(live, "LiveSystemOneClient", constructor)
    spec = HarnessSpec(name="offline", metadata={"airplane_mode": True})
    result = await evaluate_jev_rubric("r", "work", spec=spec)
    assert result["verdict"] == "ungraded"
    constructor.assert_not_called()


@pytest.mark.asyncio
async def test_rubric_opt_in_avoids_utility_model(monkeypatch):
    from superqode.agent import rubric

    monkeypatch.setenv("SUPERQODE_RUBRIC_GRADER", "systemone")
    mocked = AsyncMock(
        return_value={
            "verdict": "needs_revision",
            "reason": "gap",
            "decision": {"status": "decided"},
        }
    )
    monkeypatch.setattr(rubric, "evaluate_jev_rubric", mocked)
    evidence = {}
    verdict, feedback = await grade_against_rubric(
        [], "draft", "include tests", None, "unused", "unused", on_result=evidence.update
    )
    assert verdict == "needs_revision"
    assert "include tests" in feedback
    assert evidence["decision"]["status"] == "decided"


@pytest.mark.asyncio
async def test_utility_failure_no_longer_passes(monkeypatch):
    from superqode.agent import utility_model

    monkeypatch.delenv("SUPERQODE_RUBRIC_GRADER", raising=False)
    monkeypatch.setattr(
        utility_model, "utility_completion", AsyncMock(side_effect=RuntimeError("secret"))
    )
    verdict, feedback = await grade_against_rubric([], "draft", "r", None, "p", "m")
    assert verdict == "ungraded"
    assert "secret" not in feedback


@pytest.mark.asyncio
async def test_eval_cli_with_recorded_decisions(tmp_path, monkeypatch):
    from superqode.harness.eval import run_harness_eval

    monkeypatch.delenv("SUPERQODE_SYSTEMONE", raising=False)
    (tmp_path / "answer.json").write_text(
        json.dumps({"answers": {"route": {"choice": "review", "confidence": 0.99}}})
    )
    (tmp_path / "harness.yaml").write_text(
        "name: recorded-route\nflavor: decision\nruntime:\n  backend: systemone\nsystemone:\n  enabled: true\n  client: replay\n  pack: factory_route\n  replay_path: answer.json\n"
    )
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text(
        "tasks:\n  - id: review\n    prompt: Review the patch\n    evaluator:\n      type: decision\n      expected: {route: review}\n"
    )
    result = await run_harness_eval(
        spec_paths=[tmp_path / "harness.yaml"],
        tasks_path=tasks,
        provider="systemone",
        model="jev-1.13.0",
        working_dir=tmp_path,
        live=True,
    )
    variant = result["variants"][0]
    assert variant["passed"] == 1
    assert variant["coverage"] == 1
    assert variant["tasks"][0]["evaluation"]["evidence"]["decision"]["metadata"][
        "pack_hash"
    ].startswith("sha256:")
    assert result["tasks_hash"].startswith("sha256:")


@pytest.mark.asyncio
async def test_jev_rubric_real_loop_revision(monkeypatch):
    from superqode.agent.loop import AgentConfig, AgentLoop
    from superqode.tools.base import ToolRegistry
    from test_final_parity_wave import RubricScriptedGateway
    from superqode.agent import rubric

    monkeypatch.setenv("SUPERQODE_RUBRIC_GRADER", "systemone")
    mocked = AsyncMock(
        side_effect=[
            {"verdict": "needs_revision", "reason": "missing evidence"},
            {
                "verdict": "satisfied",
                "reason": "requirements met",
                "decision": {"status": "decided"},
            },
        ]
    )
    monkeypatch.setattr(rubric, "evaluate_jev_rubric", mocked)
    gateway = RubricScriptedGateway(["draft", "revised"], [])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.empty(),
        config=AgentConfig(provider="t", model="m", rubric="include evidence"),
    )
    response = await loop.run("work")
    assert response.content == "revised"
    assert response.rubric_result["verdict"] == "satisfied"
    assert gateway.grader_calls == 0
    assert mocked.await_count == 2
