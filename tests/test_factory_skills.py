"""Explicit skill bindings share deployed compilation and guarded improvement."""
# ruff: noqa: F811

import asyncio
from copy import deepcopy

import pytest
import yaml

from test_factory_definition import project, rewrite  # noqa: F401
from test_factory_improvement import prepared, fake_eval, proposed  # noqa: F401
from superqode.desktop_service.service import DesktopService
from superqode.factory import compile_factory, load_factory, resolve_factory
from superqode.factory.definition import FactoryDefinition
from superqode.factory.skills import bound_harness, check_candidate
from superqode.factory import improvement

BASE = "---\nname: review\ndescription: Output review\n---\nCheck the response format.\n"
BETTER = BASE.replace("Check the response format.", "Check the response format and say ready.")


def bind(root, name="review", text=BASE):
    path = root / f".superqode/skills/{name}/SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)

    def change(data):
        data["data_context"].setdefault("files", {})[name] = {
            "path": path.relative_to(root).as_posix(),
            "purpose": "skill",
        }
        data["inference"]["harnesses"]["coder"].setdefault("skills", []).append(name)

    rewrite(root, change)


@pytest.fixture
def skill_plan(prepared):
    root, old = prepared
    bind(root)
    bind(root, "fixed", BASE.replace("review", "fixed").replace("response format", "spelling"))
    return root, improvement.prepare(
        root,
        binding="coder",
        tasks=old["tasks"],
        fixture="fixture",
        target_kind="skill",
        skill="review",
        max_evals=2,
        max_seconds=60,
    )


def test_declared_skills_are_opt_in_and_pinned_in_deployed_compilation(project):
    bind(project)
    snapshot = resolve_factory(load_factory(root=project))
    raw = deepcopy(snapshot.payload["harnesses"])
    effective = bound_harness(snapshot.payload, "coder")
    assert "## Skill: review" in effective["agents"][0]["system_prompt"]
    assert snapshot.payload["harnesses"] == raw
    plan = compile_factory(snapshot, root=project, goal="Fixture")
    assert any(
        "Check the response format." in h["agents"][0]["system_prompt"]
        for h in plan.harnesses.values()
    )
    rewrite(project, lambda d: d["inference"]["harnesses"]["coder"].pop("skills"))
    unbound = resolve_factory(load_factory(root=project))
    assert bound_harness(unbound.payload, "coder") == unbound.payload["harnesses"]["coder"]


def test_evaluator_alias_cannot_be_bound_using_equivalent_path(project):
    bind(project)
    rewrite(
        project,
        lambda d: d["data_context"]["files"].update(
            evaluator={"path": ".superqode/skills/review/./SKILL.md", "purpose": "evaluator"}
        ),
    )
    with pytest.raises(ValueError, match="never evaluator"):
        resolve_factory(load_factory(root=project))


def test_equivalent_skill_source_paths_still_pin_and_compare(prepared, fake_eval):
    root, old = prepared
    bind(root)
    rewrite(
        root,
        lambda d: d["data_context"]["files"]["review"].update(
            path="./.superqode/skills/review/SKILL.md"
        ),
    )
    plan = improvement.prepare(
        root,
        binding="coder",
        tasks=old["tasks"],
        fixture="fixture",
        target_kind="skill",
        skill="review",
    )
    candidate = improvement.stage(root, plan["id"], BETTER)
    result = asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    assert result["eligible"]


@pytest.mark.parametrize("kind", ["missing", "evaluator", "disabled", "empty", "metadata"])
def test_invalid_binding_or_proposal_fails_closed(project, kind):
    bind(project)
    if kind == "missing":
        rewrite(project, lambda d: d["inference"]["harnesses"]["coder"].update(skills=["absent"]))
    elif kind == "evaluator":
        rewrite(project, lambda d: d["data_context"]["files"]["review"].update(purpose="evaluator"))
    elif kind == "disabled":
        (project / ".superqode/skills/review/SKILL.md").write_text(
            BASE.replace("name: review", "name: review\nenabled: false")
        )
    elif kind == "empty":
        (project / ".superqode/skills/review/SKILL.md").write_text("---\nname: review\n---\n")
    else:
        with pytest.raises(ValueError, match="frontmatter"):
            check_candidate(BASE, BETTER.replace("Output review", "New description"))
        return
    with pytest.raises(ValueError):
        resolve_factory(load_factory(root=project))


def test_skill_comparison_changes_only_selected_body_and_adoption_is_draft(skill_plan, fake_eval):
    root, plan = skill_plan
    original = (root / ".superqode/factory.yaml").read_text()
    candidate = improvement.stage(root, plan["id"], BETTER)
    assert (
        improvement.folder(root, plan["id"]) / "candidates" / (candidate["candidate"] + ".md")
    ).is_file()
    result = asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    assert result["eligible"]
    specs = [yaml.safe_load(p.read_text()) for p in fake_eval[0]["spec_paths"]]
    for spec in specs:
        assert "## Skill: fixed" in spec["agents"][0]["system_prompt"]
    assert "and say ready" not in specs[0]["agents"][0]["system_prompt"]
    assert "and say ready" in specs[1]["agents"][0]["system_prompt"]
    draft = improvement.adoption(root, plan["id"], candidate["candidate"], result["receipt_digest"])
    before = yaml.safe_load(original)
    after = yaml.safe_load(draft["yaml"])
    assert after["data_context"]["files"]["review"]["path"] == draft["component"]
    before["data_context"]["files"]["review"]["path"] = draft["component"]
    assert before == after
    assert (root / draft["component"]).read_text() == BETTER
    assert (root / ".superqode/skills/review/SKILL.md").read_text() == BASE
    assert (root / ".superqode/factory.yaml").read_text() == original
    deployed = resolve_factory(
        FactoryDefinition(root, root / ".superqode/factory.yaml", after), source_text=draft["yaml"]
    )
    assert "and say ready" in bound_harness(deployed.payload, "coder")["agents"][0]["system_prompt"]


@pytest.mark.parametrize(
    "surface",
    [
        "skills",
        "skills.review",
        "skills.review.instructions",
        "data_context.files.review",
        "data_context.files.review.path",
        "inference.harnesses.coder.skills",
        "inference.harnesses.coder.agents.*.system_prompt",
    ],
)
def test_skill_protected_surfaces_prevent_experiments(prepared, surface):
    root, old = prepared
    bind(root)
    rewrite(root, lambda d: d["improvement"]["optimization"]["protected"].append(surface))
    with pytest.raises(ValueError, match="protects"):
        improvement.prepare(
            root,
            binding="coder",
            tasks=old["tasks"],
            fixture="fixture",
            target_kind="skill",
            skill="review",
        )


def test_shared_skill_asset_needs_a_dedicated_binding_before_improvement(skill_plan):
    root, old = skill_plan
    rewrite(
        root,
        lambda d: d["inference"]["harnesses"].update(
            second=deepcopy(d["inference"]["harnesses"]["coder"])
        ),
    )
    with pytest.raises(ValueError, match="dedicated"):
        improvement.prepare(
            root,
            binding="coder",
            tasks=old["tasks"],
            fixture="fixture",
            target_kind="skill",
            skill="review",
        )


def test_harness_instruction_protection_applies_to_bound_skills(skill_plan):
    root, plan = skill_plan
    data = yaml.safe_load((improvement.folder(root, plan["id"]) / "baseline.yaml").read_text())
    data.setdefault("optimization", {}).setdefault("protected_surfaces", []).append(
        "agents.*.system_prompt"
    )
    path = root / ".superqode/components/protected.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(data))

    def change(definition):
        binding = definition["inference"]["harnesses"]["coder"]
        binding.pop("template")
        binding["path"] = path.relative_to(root).as_posix()

    rewrite(root, change)
    with pytest.raises(ValueError, match="Harness policy protects"):
        improvement.prepare(
            root,
            binding="coder",
            tasks=plan["tasks"],
            fixture="fixture",
            target_kind="skill",
            skill="review",
        )


def test_harness_adoption_preserves_fixed_skill_bindings(prepared, fake_eval):
    root, old = prepared
    bind(root)
    plan = improvement.prepare(root, binding="coder", tasks=old["tasks"], fixture="fixture")
    candidate = proposed(root, plan)
    result = asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    draft = improvement.adoption(root, plan["id"], candidate["candidate"], result["receipt_digest"])
    assert yaml.safe_load(draft["yaml"])["inference"]["harnesses"]["coder"]["skills"] == ["review"]


def test_native_skill_creation_and_reopen_need_no_models(project, tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(project))["id"]
        original = (project / ".superqode/factory.yaml").read_text()
        params = {
            "project": identity,
            "yaml": original,
            "binding": "coder",
            "skill": "review",
            "markdown": BASE,
            "confirmed": True,
        }
        created = service.dispatch("factory.improvement.skill.create", params)
        assert (project / created["component"]).read_text() == BASE
        assert (project / ".superqode/factory.yaml").read_text() == original
        with pytest.raises(ValueError, match="already exists"):
            service.dispatch("factory.improvement.skill.create", params)
        # Explicit fixture save; production UI requires review and save separately.
        (project / ".superqode/factory.yaml").write_text(created["yaml"])
        cap = service.dispatch("factory.improvement.capabilities", {"project": identity})
        assert cap["bound_skills"]["coder"] == ["review"]
        suite = ".superqode/evals/skill.yaml"
        starter = service.dispatch(
            "factory.improvement.suite.open", {"project": identity, "path": suite}
        )
        service.dispatch(
            "factory.improvement.suite.save", {"project": identity, "path": suite, **starter}
        )
        plan = service.dispatch(
            "factory.improvement.prepare",
            {
                "project": identity,
                "binding": "coder",
                "target_kind": "skill",
                "skill": "review",
                "tasks": suite,
                "fixture": "@empty",
                "max_evals": 1,
                "max_seconds": 30,
                "reflection_model": "",
            },
        )
        assert plan["baseline_yaml"] == BASE
        candidate = service.dispatch(
            "factory.improvement.propose", {"project": identity, "plan": plan["id"], "yaml": BETTER}
        )
        opened = service.dispatch(
            "factory.improvement.open", {"project": identity, "plan": plan["id"]}
        )
        assert opened["candidates"] == [candidate["candidate"]]
        assert opened["baseline_yaml"] == BASE
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
        assert not service._all("SELECT * FROM jobs")
    finally:
        service.close()


def test_invalid_creation_writes_no_component(project, tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(project))["id"]
        params = {
            "project": identity,
            "yaml": (project / ".superqode/factory.yaml").read_text(),
            "binding": "missing",
            "skill": "review",
            "markdown": BASE,
            "confirmed": True,
        }
        with pytest.raises(ValueError, match="declared harness"):
            service.dispatch("factory.improvement.skill.create", params)
        assert not (project / ".superqode/skills").exists()
    finally:
        service.close()


def test_skill_gepa_uses_only_heldin_and_checks_metadata_before_rollout(skill_plan, monkeypatch):
    from types import SimpleNamespace

    root, original = skill_plan
    plan = improvement.prepare(
        root,
        binding="coder",
        tasks=original["tasks"],
        fixture="fixture",
        target_kind="skill",
        skill="review",
        max_evals=2,
        max_seconds=60,
        reflection_model="ollama/qwen3-coder",
    )
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        assert kwargs["eval_split"] == "held-in"
        tasks = yaml.safe_load(kwargs["tasks_path"].read_text())["tasks"]
        assert [t["id"] for t in tasks] == ["train"]
        spec = yaml.safe_load(kwargs["spec_paths"][0].read_text())
        assert "and say ready" in spec["agents"][0]["system_prompt"]
        from test_factory_improvement import record_fixture_usage  # noqa: F401

        report = {"variants": [{"tasks": [{"score": 1, "status": "passed"}]}]}
        record_fixture_usage(kwargs, report)
        return report

    def optimizer(**kwargs):
        assert kwargs["seed_candidate"] == BASE
        assert kwargs["test_set"] == []
        assert all(t["split"] == "held-in" for t in kwargs["dataset"] + kwargs["valset"])
        assert (
            kwargs["evaluator"](
                BETTER.replace("name: review", "name: changed"), kwargs["dataset"][0]
            )[0]
            == 0
        )
        assert kwargs["evaluator"](BETTER, kwargs["dataset"][0])[0] == 1
        return SimpleNamespace(best_candidate=BETTER, metadata={})

    monkeypatch.setattr(improvement, "run_harness_eval", evaluate)
    monkeypatch.setattr("superqode.skillopt._run_modern_optimizer", optimizer)
    result = improvement.optimize(root, plan["id"], plan["digest"])
    assert result["proposal_only"] and not result["heldout_exposed"]
    assert len(calls) == 1 and result["metric_calls"] == 2


@pytest.mark.parametrize("changed", ["source", "candidate", "baseline"])
def test_skill_drift_holds_adoption(skill_plan, fake_eval, changed):
    root, plan = skill_plan
    candidate = improvement.stage(root, plan["id"], BETTER)
    result = asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    directory = improvement.folder(root, plan["id"])
    path = {
        "source": root / ".superqode/skills/review/SKILL.md",
        "candidate": directory / "candidates" / (candidate["candidate"] + ".md"),
        "baseline": directory / "baseline.skill.md",
    }[changed]
    path.write_text(BASE + "Tampered instructions.\n")
    with pytest.raises(ValueError):
        improvement.adoption(root, plan["id"], candidate["candidate"], result["receipt_digest"])
