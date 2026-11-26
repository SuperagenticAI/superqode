"""Configuration preservation, reproducible probes and evidence-bound objectives."""

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import time
from types import SimpleNamespace

import pytest
import yaml

from test_factory_definition import project, git  # noqa: F401
from test_factory_trials import suite_project  # noqa: F401
from test_factory_improvement import prepared  # noqa: F401
from superqode.factory import compile_factory, load_factory, resolve_factory, materialize_snapshot
from superqode.factory import benchmarks, improvement, trials
from superqode.factory.rlm_architect import architect_factory
from superqode.factory.runtime import admit_factory, factory_store
from superqode.factory.search import objective_score
from superqode.factory.templates import factory_template


def test_rlm_preserves_existing_settings_even_with_a_different_drafter(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}')
    existing = factory_template("triage-spec-build")
    existing["metadata"]["name"] = "my-factory"
    existing["inference"]["harnesses"]["coder"]["model"] = "ollama/executor"
    existing["governance"]["budget"]["max_seconds"] = 61
    existing["governance"]["permissions"]["allow_write"] = False
    existing["data_context"]["requirements"] = {
        "original": {"description": "Keep behavior", "stages": ["verify"], "checks": ["regression"]}
    }
    original = deepcopy(existing)

    class Gateway:
        async def chat_completion(self, **kwargs):
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "workflow": "scrum",
                        "test_command": "npm test",
                        "stage_guidance": {"implement": "Inspect edge cases."},
                    }
                ),
                usage=None,
                cost=None,
            )

    result = asyncio.run(
        architect_factory(
            tmp_path,
            yaml_text=yaml.safe_dump(existing),
            provider="ollama",
            model="drafter",
            gateway=Gateway(),
            use_monty=False,
        )
    )
    data = yaml.safe_load(result["yaml"])
    for key in (
        "metadata",
        "inference",
        "governance",
        "data_context",
        "improvement",
        "compute",
        "access",
    ):
        assert data[key] == original[key]
    assert data["orchestration"]["stages"][2]["goal"].endswith("Inspect edge cases.")
    assert existing == original
    assert "Repo note:" in result["definition_diff"]
    assert result["existing_configuration_preserved"] is True


def test_fresh_rlm_does_not_bind_drafting_model_for_execution(tmp_path):
    class Gateway:
        async def chat_completion(self, **kwargs):
            return SimpleNamespace(content="{}", usage=None, cost=None)

    result = asyncio.run(
        architect_factory(
            tmp_path, provider="ollama", model="drafter", gateway=Gateway(), use_monty=False
        )
    )
    assert (
        yaml.safe_load(result["yaml"])["inference"]["harnesses"]["coder"]["model"]
        != "ollama/drafter"
    )


def efficiency_report(objective="cost", before=10, after=5, candidate_status="passed"):
    ids = ["one", "two", "three"]
    plan = {
        "objective": objective,
        "heldout_ids": ids,
        "tasks_digest": "tasks",
        "trial_fixture_digest": "a" * 64,
        "limits": {},
    }
    specs = {"before": "old", "after": "new"}
    variants = []
    for name, value, status in (("before", before, "passed"), ("after", after, candidate_status)):
        variants.append(
            {
                "spec": name,
                "usage": {"cost_usd": value},
                "duration_seconds": value,
                "tasks": [
                    {
                        "id": i,
                        "split": "held-out",
                        "status": status,
                        "evaluation": {"status": status, "evaluator": "contains"},
                        "workspace": {"mode": "isolated-copy", "snapshot_sha256": "a" * 64},
                    }
                    for i in ids
                ],
            }
        )
    report = {
        "live": True,
        "split": "held-out",
        "task_count": 3,
        "tasks_hash": "tasks",
        "spec_digests": specs,
        "workspace": {"mode": "isolated-copy", "snapshot_sha256": "a" * 64},
        "variants": variants,
    }
    return plan, report, specs


@pytest.mark.parametrize("objective", ["cost", "latency"])
def test_efficiency_can_improve_at_equal_quality_but_cannot_regress(objective):
    plan, report, specs = efficiency_report(objective)
    gate = improvement._gate(plan, report, specs)
    assert gate["accepted"]
    assert gate["objective_evidence"]["statistical_significance_established"] is False
    report["variants"][1]["tasks"][0]["status"] = "failed"
    report["variants"][1]["tasks"][0]["evaluation"]["status"] = "failed"
    assert not improvement._gate(plan, report, specs)["accepted"]


@pytest.mark.parametrize("value", [None, float("nan"), -1, 9.9, 10, True])
def test_missing_invalid_or_insufficient_cost_savings_hold(value):
    plan, report, specs = efficiency_report(after=value)
    assert not improvement._gate(plan, report, specs)["accepted"]


def test_quality_tie_stays_held_and_search_rewards_only_successful_efficiency():
    plan, report, specs = efficiency_report("quality")
    assert not improvement._gate(plan, report, specs)["accepted"]
    good = {"status": "passed", "score": 1, "usage": {"cost_usd": 2}}
    cheaper = {**good, "usage": {"cost_usd": 1}}
    assert objective_score({"objective": "cost"}, cheaper) > objective_score(
        {"objective": "cost"}, good
    )
    assert objective_score({"objective": "cost"}, {**cheaper, "status": "failed"}) == 0
    with pytest.raises(ValueError, match="complete measured"):
        objective_score({"objective": "cost"}, {**good, "usage": {}})


def test_cost_comparison_issues_receipt_only_for_pinned_equal_quality_savings(
    prepared, monkeypatch
):
    from test_factory_improvement import graded_report, proposed
    from superqode.providers.gateway.base import GatewayResponse, Usage, Cost

    root, _ = prepared
    factory_before = (root / ".superqode/factory.yaml").read_bytes()
    tasks = root / ".superqode/evals/output.yaml"
    data = yaml.safe_load(tasks.read_text())
    data["tasks"] += [{**data["tasks"][1], "id": "gate-2"}, {**data["tasks"][1], "id": "gate-3"}]
    tasks.write_text(yaml.safe_dump(data))
    plan = improvement.prepare(
        root,
        binding="coder",
        tasks=".superqode/evals/output.yaml",
        fixture="fixture",
        objective="cost",
        max_seconds=60,
    )
    assert plan["objective"] == "cost"
    candidate = proposed(root, plan)

    async def evaluate(**kwargs):
        unobserved = {k: v for k, v in kwargs.items() if k != "evaluation_observer"}
        report = graded_report(unobserved, before="passed", after="passed")
        report["task_count"] = 3
        source_tasks = yaml.safe_load(Path(kwargs["tasks_path"]).read_text())["tasks"]
        heldout = [t for t in source_tasks if t["split"] == "held-out"]
        observer = kwargs["evaluation_observer"]
        for index, variant in enumerate(report["variants"]):
            price = 0.002 if index == 0 else 0.001
            variant["usage"] = {
                "tokens_in": 6,
                "tokens_out": 6,
                "total_tokens": 12,
                "tool_calls": 3,
                "cost_usd": price * 3,
            }
            for row, task in zip(variant["tasks"], heldout):
                row["usage"] = {
                    "tokens_in": 2,
                    "tokens_out": 2,
                    "total_tokens": 4,
                    "tool_calls": 1,
                    "cost_usd": price,
                }
                with observer.operation(
                    spec=variant["spec"],
                    task=task,
                    provider=kwargs["provider"],
                    model=kwargs["model"],
                ) as scope:
                    request = scope.ledger.begin_request(
                        scope.identity, kwargs["provider"], kwargs["model"]
                    )
                    scope.ledger.finish_request(
                        request,
                        GatewayResponse(
                            content="Simulated graded response",
                            usage=Usage(prompt_tokens=2, completion_tokens=2, total_tokens=4),
                            cost=Cost(total_cost=price),
                        ),
                    )
                    observer.complete(scope, row)
        return report

    monkeypatch.setattr(improvement, "run_harness_eval", evaluate)
    result = asyncio.run(
        improvement.compare(root, plan["id"], candidate["candidate"], plan["digest"])
    )
    assert result["eligible"] is True, result
    assert (root / ".superqode/factory.yaml").read_bytes() == factory_before
    _, _, receipt = improvement.evidence(
        root, plan["id"], candidate["candidate"], result["receipt_digest"]
    )
    assert receipt["gate"]["objective_evidence"]["objective"] == "cost"
    loaded, _ = improvement.load(root, plan["id"])
    assert loaded["objective"] == "cost"


def test_efficiency_preparation_rejects_insufficient_held_out_cases(prepared):
    root, _ = prepared
    with pytest.raises(ValueError, match="three held-out"):
        improvement.prepare(
            root,
            binding="coder",
            tasks=".superqode/evals/output.yaml",
            fixture="fixture",
            objective="cost",
        )


def historical_runs(root, *, first_goal="Make app.py print 43"):
    first = compile_factory(resolve_factory(load_factory(root=root)), root=root, goal=first_goal)
    materialize_snapshot(first)
    before = admit_factory(first, actor="test", request_id="history-before")
    (root / "app.py").write_text("answer = 41\n")
    git(root, "add", "app.py")
    git(root, "commit", "-qm", "A different application seed")
    second = compile_factory(
        resolve_factory(load_factory(root=root)),
        root=root,
        goal="Repair the next application revision",
    )
    materialize_snapshot(second)
    after = admit_factory(second, actor="test", request_id="history-after")
    return before, after


def test_historical_replay_uses_original_commits_and_never_adopts_or_executes(suite_project):
    root, _ = suite_project
    before, after = historical_runs(root)
    definition_before = (root / ".superqode/factory.yaml").read_bytes()
    proposal = benchmarks.draft(
        root,
        held_in=[before.work_order_id],
        held_out=[after.work_order_id],
        candidate=".superqode/trials/candidate.yaml",
    )
    assert not (root / ".superqode/trials/history").exists()
    with pytest.raises(ValueError, match="Confirm"):
        benchmarks.install(root, proposal, expected=proposal["digest"])
    saved = benchmarks.install(root, proposal, expected=proposal["digest"], confirmed=True)
    suite = trials._read(root / saved["path"])
    plan = trials.prepare(root, suite_text=suite)
    assert {e["source_revision"] for e in plan["entries"]} == {
        before.metadata["factory"]["repository_commit"],
        after.metadata["factory"]["repository_commit"],
    }
    for entry in plan["entries"]:
        app = (root / entry["project"] / "app.py").read_text()
        assert ("42" if entry["split"] == "held-in" else "41") in app
        assert factory_store(root / entry["project"]).get(entry["run"]).status.value == "queued"
    board = trials.scorecard(root, plan["id"])
    assert board["summary"]["baseline"]["by_split"]["held-out"]["total"] == 1
    assert not board["promotion_authority"]
    assert (root / ".superqode/factory.yaml").read_bytes() == definition_before
    older = next(iter(plan["case_fixtures"]))
    (trials.folder(root, plan["id"]) / ("fixture-" + older) / "app.py").write_text("tampered")
    with pytest.raises(ValueError, match="historical application fixture"):
        trials.load(root, plan["id"])


def test_historical_review_rejects_duplicate_splits_and_candidate_drift(suite_project):
    root, _ = suite_project
    before, after = historical_runs(root)
    with pytest.raises(ValueError, match="distinct"):
        benchmarks.draft(
            root,
            held_in=[before.work_order_id],
            held_out=[before.work_order_id],
            candidate=".superqode/factory.yaml",
        )
    proposal = benchmarks.draft(
        root,
        held_in=[before.work_order_id],
        held_out=[after.work_order_id],
        candidate=".superqode/trials/candidate.yaml",
    )
    candidate = root / ".superqode/trials/candidate.yaml"
    data = yaml.safe_load(candidate.read_text())
    data["orchestration"]["stages"][0]["goal"] = "Changed after review"
    candidate.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="changed"):
        benchmarks.install(root, proposal, expected=proposal["digest"], confirmed=True)


def test_agent_review_withholds_probes_but_keeps_installation_explicit(suite_project):
    root, _ = suite_project
    before, after = historical_runs(root)
    with pytest.raises(ValueError, match="Confirm"):
        benchmarks.prepare_review(
            root,
            held_in=[before.work_order_id],
            held_out=[after.work_order_id],
            candidate=".superqode/trials/candidate.yaml",
        )
    review = benchmarks.prepare_review(
        root,
        held_in=[before.work_order_id],
        held_out=[after.work_order_id],
        candidate=".superqode/trials/candidate.yaml",
        confirmed=True,
    )
    assert not review["protected_artifact_contents_included"]
    assert "files" not in review
    assert "argv" not in json.dumps(review)
    saved = benchmarks.install_review(root, review["proposal_id"], confirmed=True)
    assert not saved["execution_started"]
    assert (root / saved["path"]).is_file()


DEMO = Path(__file__).resolve().parents[1] / "examples/factory/demo"


def test_shipped_demo_probes_match_the_public_case_definitions():
    from superqode.factory.probes import parse_probes

    for case in json.loads((DEMO / "suite.json").read_text())["cases"]:
        name = "cli-probes" if case["id"] == "totals" else case["id"]
        probes = parse_probes((DEMO / f"evals/{name}.json").read_text())["cases"]
        assert len(probes) == len(case["probes"]) == 4
        for probe, expected in zip(probes, case["probes"]):
            assert probe["argv"][:3] == ["python", "app.py", case["id"]]
            assert json.loads(probe["argv"][3]) == expected["input"]
            assert json.loads(probe["stdout"]) == expected["expected"]


@pytest.mark.skipif(
    os.environ.get("SUPERQODE_VERIFY_NATIVE") != "1",
    reason="requires explicit native isolation probes",
)
def test_real_demo_probes_fail_on_seed_and_pass_on_repaired_application(tmp_path):
    from superqode.factory.probes import parse_probes, run_python_probe

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    shutil.copy(DEMO / "app.py", candidate / "app.py")
    manifests = [parse_probes(p.read_text()) for p in sorted((DEMO / "evals").glob("*.json"))]

    def check(manifest):
        outcomes = []
        for case in manifest["cases"]:
            result = run_python_probe(
                case["argv"],
                candidate=candidate,
                scratch=scratch,
                stdin="",
                deadline=time.monotonic() + 10,
            )
            assert result["kind"] == "completed", result
            outcomes.append(result["returncode"] == 0 and result["stdout"] == case["stdout"])
        return outcomes

    assert all(not all(check(manifest)) for manifest in manifests)
    source = (
        (candidate / "app.py")
        .read_text()
        .replace(
            'result[row["category"]] = row["amount"]',
            'result[row["category"]] = result.get(row["category"], 0) + row["amount"]',
        )
        .replace('if item.get("active", True)', 'if item.get("active") is True')
        .replace("return sorted(names)", "return sorted(names, key=str.casefold)")
    )
    (candidate / "app.py").write_text(source)
    assert all(all(check(manifest)) for manifest in manifests)


@pytest.mark.parametrize(
    "secret",
    [
        "sk-proj-" + "SyntheticFixtureOnly123456789",
        "ghp_" + "SyntheticFixtureOnly123456789012345678",
        "api_key=synthetic-example-credential",
        "Authorization: Bearer synthetic-example-token-12345",
    ],
)
def test_historical_credentials_are_withheld_and_cannot_be_exported(suite_project, secret):
    root, _ = suite_project
    before, after = historical_runs(root, first_goal="Repair the API using " + secret)
    history = benchmarks.history(root)
    assert secret not in json.dumps(history)
    row = next(r for r in history["runs"] if r["run"] == before.work_order_id)
    assert row["task_text_withheld"]
    with pytest.raises(ValueError, match="may contain credentials"):
        benchmarks.prepare_review(
            root,
            held_in=[before.work_order_id],
            held_out=[after.work_order_id],
            candidate=".superqode/trials/candidate.yaml",
            confirmed=True,
        )
    assert not (root / ".superqode/factory-benchmark-drafts").exists()
    assert secret in factory_store(root, read_only=True).get(before.work_order_id).goal


def test_historical_configured_secret_values_are_rejected(monkeypatch):
    token = "synthetic-provider-value-92837465"
    monkeypatch.setenv("EXAMPLE_API_KEY", token)
    with pytest.raises(ValueError, match="may contain credentials"):
        benchmarks._safe_task("Use " + token + " to reproduce the issue")
    benchmarks._safe_task("Use ${EXAMPLE_API_KEY} from the environment")
