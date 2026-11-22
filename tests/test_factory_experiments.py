"""Route and entry-stage experiments keep deployment and evidence bound together."""
# ruff: noqa: F811

import asyncio
from types import SimpleNamespace

import pytest
import yaml

from test_factory_definition import project, rewrite  # noqa: F401
from test_factory_improvement import prepared, fake_eval, graded_report  # noqa: F401
from superqode.factory import improvement
from superqode.desktop_service.service import DesktopService


def prepare(root, original, kind, **extra):
    return improvement.prepare(
        root,
        binding="coder",
        tasks=original["tasks"],
        fixture="fixture",
        target_kind=kind,
        stage="investigate" if kind == "workflow" else "",
        route_models=["ollama/qwen3-coder", "lmstudio/candidate"] if kind == "route" else None,
        max_evals=2,
        max_seconds=60,
        **extra,
    )


def proposal(kind):
    return (
        {"model": "lmstudio/candidate"}
        if kind == "route"
        else {"stage": "investigate", "goal": "Check the requested output and respond ready."}
    )


@pytest.mark.parametrize("kind", ["route", "workflow"])
def test_comparison_and_draft_change_only_selected_surface(prepared, fake_eval, kind):
    root, original = prepared
    before = (root / ".superqode/factory.yaml").read_text()
    plan = prepare(root, original, kind)
    candidate = improvement.stage(root, plan["id"], yaml.safe_dump(proposal(kind)))
    result = asyncio.run(improvement.compare(str(root), plan["id"], candidate["candidate"]))
    assert result["eligible"]
    call = fake_eval[0]
    specs = [yaml.safe_load(path.read_text()) for path in call["spec_paths"]]
    if kind == "route":
        assert list(call["model_routes"].values()) == ["ollama/qwen3-coder", "lmstudio/candidate"]
        specs[0]["model_policy"]["primary"] = "lmstudio/candidate"
        assert specs[0] == specs[1]
    else:
        assert call["readonly_workspace"] is True
        prompts = [values["gate"] for values in call["task_prompts"].values()]
        assert "Overall goal:\nSay ready" in prompts[1]
        assert "Assigned role: investigator" in prompts[1]
        assert "Check the requested output" not in prompts[0]
        assert "Check the requested output" in prompts[1]
        assert "Completed dependencies" not in prompts[1]
        assert specs[0]["execution_policy"]["allow_write"] is False
    draft = improvement.adoption(root, plan["id"], candidate["candidate"], result["receipt_digest"])
    assert draft["proposal_only"] and not draft["component"]
    expected = yaml.safe_load(before)
    if kind == "route":
        expected["inference"]["harnesses"]["coder"]["model"] = proposal(kind)["model"]
    else:
        expected["orchestration"]["stages"][0]["goal"] = proposal(kind)["goal"]
    assert yaml.safe_load(draft["yaml"]) == expected
    assert (root / ".superqode/factory.yaml").read_text() == before
    assert not (root / ".superqode/components").exists()


@pytest.mark.parametrize(
    "kind,field",
    [
        ("route", "inference_routes"),
        ("workflow", "prompt_digests"),
        ("workflow", "readonly_workspace"),
        ("workflow", "workspace_integrity"),
    ],
)
def test_missing_or_forged_execution_evidence_holds_adoption(prepared, monkeypatch, kind, field):
    root, original = prepared
    plan = prepare(root, original, kind)
    candidate = improvement.stage(root, plan["id"], yaml.safe_dump(proposal(kind)))

    async def evaluate(**kwargs):
        report = graded_report(kwargs)
        if field == "workspace_integrity":
            report["variants"][1]["tasks"][0].pop(field)
        else:
            report.pop(field)
        return report

    monkeypatch.setattr(improvement, "run_harness_eval", evaluate)
    result = asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    assert not result["eligible"]
    expected_error = (
        "usage evidence changed or is incomplete"
        if field == "inference_routes"
        else "does not authorize"
    )
    with pytest.raises(ValueError, match=expected_error):
        improvement.adoption(root, plan["id"], candidate["candidate"], result["receipt_digest"])


@pytest.mark.parametrize(
    "kind,surface",
    [
        ("route", "routes"),
        ("route", "inference.harnesses.coder.model"),
        ("route", "harnesses.coder.model_policy"),
        ("workflow", "workflow"),
        ("workflow", "orchestration.stages.investigate.goal"),
        ("workflow", "orchestration.stages.0.goal"),
    ],
)
def test_factory_protections_prevent_experiment(prepared, kind, surface):
    root, original = prepared
    rewrite(root, lambda d: d["improvement"]["optimization"]["protected"].append(surface))
    with pytest.raises(ValueError, match="protects"):
        prepare(root, original, kind)


@pytest.mark.parametrize(
    "kind,bad",
    [
        ("route", {"model": "openai/unselected"}),
        ("route", {"model": "lmstudio/candidate", "allow_network": True}),
        ("workflow", {"stage": "verify", "goal": "skip gate"}),
        ("workflow", {"stage": "investigate", "goal": "ready", "checks": []}),
        ("workflow", {"stage": "investigate", "goal": " "}),
    ],
)
def test_candidate_cannot_expand_scope(prepared, kind, bad):
    root, original = prepared
    plan = prepare(root, original, kind)
    with pytest.raises(ValueError):
        improvement.stage(root, plan["id"], yaml.safe_dump(bad))


@pytest.mark.parametrize("route", ["openai/hosted", "acp/codex", "synthetic/passthrough"])
def test_route_choices_obey_private_factory_and_direct_provider_policy(prepared, route):
    root, old = prepared
    with pytest.raises(ValueError):
        improvement.prepare(
            root,
            binding="coder",
            tasks=old["tasks"],
            fixture="fixture",
            target_kind="route",
            route_models=["ollama/qwen3-coder", route],
        )


@pytest.mark.parametrize("stage", ["implement", "verify", "missing"])
def test_dependencies_and_human_gates_cannot_be_implicitly_approved(prepared, stage):
    root, old = prepared
    with pytest.raises(ValueError):
        improvement.prepare(
            root,
            binding="coder",
            tasks=old["tasks"],
            fixture="fixture",
            target_kind="workflow",
            stage=stage,
        )


@pytest.mark.parametrize("kind", ["route", "workflow"])
def test_gepa_uses_selected_surface_and_heldin_only(prepared, monkeypatch, kind):
    root, old = prepared
    plan = prepare(root, old, kind, reflection_model="ollama/qwen3-coder")
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        assert kwargs["eval_split"] == "held-in"
        assert [t["id"] for t in yaml.safe_load(kwargs["tasks_path"].read_text())["tasks"]] == [
            "train"
        ]
        if kind == "route":
            assert list(kwargs["model_routes"].values()) == ["lmstudio/candidate"]
        else:
            assert all(list(v) == ["train"] for v in kwargs["task_prompts"].values())
        from test_factory_improvement import record_fixture_usage  # noqa: F401

        report = {"variants": [{"tasks": [{"score": 1, "status": "passed"}]}]}
        record_fixture_usage(kwargs, report)
        return report

    def optimizer(**kwargs):
        assert kwargs["test_set"] == []
        assert all(t["split"] == "held-in" for t in kwargs["dataset"] + kwargs["valset"])
        text = yaml.safe_dump(proposal(kind))
        assert kwargs["evaluator"](text + "permissions: {}\n", kwargs["dataset"][0])[0] == 0
        assert kwargs["evaluator"](text, kwargs["dataset"][0])[0] == 1
        return SimpleNamespace(best_candidate=text, metadata={})

    monkeypatch.setattr(improvement, "run_harness_eval", evaluate)
    monkeypatch.setattr("superqode.skillopt._run_modern_optimizer", optimizer)
    result = improvement.optimize(root, plan["id"], plan["digest"])
    assert result["proposal_only"] and not result["heldout_exposed"] and len(calls) == 1


@pytest.mark.parametrize("kind", ["route", "workflow"])
def test_native_plan_reopen_and_provider_credentials_are_scoped(
    prepared, tmp_path, monkeypatch, kind
):
    root, old = prepared
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(root))["id"]
        plan = service.dispatch(
            "factory.improvement.prepare",
            {
                "project": identity,
                "binding": "coder",
                "tasks": old["tasks"],
                "fixture": "fixture",
                "max_evals": 2,
                "max_seconds": 60,
                "reflection_model": "",
                "target_kind": kind,
                "stage": "investigate",
                "route_models": ["ollama/qwen3-coder", "lmstudio/candidate"],
            },
        )
        candidate = service.dispatch(
            "factory.improvement.propose",
            {"project": identity, "plan": plan["id"], "yaml": yaml.safe_dump(proposal(kind))},
        )
        opened = service.dispatch(
            "factory.improvement.open", {"project": identity, "plan": plan["id"]}
        )
        assert opened["target_kind"] == kind and opened["candidates"] == [candidate["candidate"]]
        from superqode.desktop_service.factory_studio import validate_request

        request = validate_request(
            root,
            {
                "project": identity,
                "factory_action": "improvement-compare",
                "confirmed": True,
                "plan": plan["id"],
                "candidate": candidate["candidate"],
                "factory_providers": ["unrelated"],
            },
            service=service,
        )
        assert request["factory_providers"] == (
            ["lmstudio", "ollama"] if kind == "route" else ["ollama"]
        )
        with pytest.raises(ValueError, match="completed native comparison"):
            service.dispatch(
                "factory.improvement.adopt",
                {
                    "project": identity,
                    "plan": plan["id"],
                    "candidate": candidate["candidate"],
                    "comparison_job": "invented",
                    "confirmed": True,
                },
            )
    finally:
        service.close()
