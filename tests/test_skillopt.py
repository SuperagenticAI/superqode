"""Tests for SkillOpt-style skill optimization helpers."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from superqode.main import cli_main
from superqode.skillopt import check_skill_candidate, export_skillopt_project, optimize_skill_with_gepa


def _write_skill(path: Path, body: str = "Follow the existing project style.") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "name: review\n"
        "description: Review code\n"
        "enabled: true\n"
        "---\n\n"
        "# Review\n\n"
        f"{body}\n",
        encoding="utf-8",
    )


def _write_tasks(path: Path) -> None:
    path.write_text(
        "tasks:\n"
        "  - id: smoke\n"
        "    prompt: Say ready\n"
        "    expect_contains: ready\n",
        encoding="utf-8",
    )


def _write_harness(path: Path) -> None:
    path.write_text(
        "version: 1\n"
        "name: skill-test\n"
        "flavor: no_tool\n"
        "agents:\n"
        "  - id: reasoner\n"
        "    role: reasoner\n"
        "    system_prompt: Answer directly.\n",
        encoding="utf-8",
    )


def test_export_skillopt_project_stages_baseline_workspace(tmp_path):
    skill_path = tmp_path / ".agents" / "skills" / "review" / "SKILL.md"
    tasks_path = tmp_path / "eval-tasks.yaml"
    _write_skill(skill_path)
    _write_tasks(tasks_path)

    export = export_skillopt_project(
        skill="review",
        tasks_path=tasks_path,
        project_dir=tmp_path / "opt",
        root=tmp_path,
        max_edits=3,
    )

    assert export.skill_path.exists()
    assert export.baseline_skill_path.exists()
    assert export.tasks_path.exists()
    assert "bounded-skill-edit" in export.tasks_path.read_text(encoding="utf-8")
    assert "max-edits 3" in export.tasks_path.read_text(encoding="utf-8")
    assert "review" in export.instructions_path.read_text(encoding="utf-8")


def test_check_skill_candidate_accepts_small_bounded_edit(tmp_path):
    baseline = tmp_path / "baseline.md"
    candidate = tmp_path / "candidate.md"
    _write_skill(baseline)
    _write_skill(candidate, "Follow the existing project style.\nPrefer focused findings.")

    payload = check_skill_candidate(baseline_path=baseline, candidate_path=candidate, max_edits=2)

    assert payload["ok"] is True
    assert payload["edit_hunks"] == 1


def test_check_skill_candidate_rejects_name_change(tmp_path):
    baseline = tmp_path / "baseline.md"
    candidate = tmp_path / "candidate.md"
    _write_skill(baseline)
    _write_skill(candidate)
    candidate.write_text(
        candidate.read_text(encoding="utf-8").replace("name: review", "name: other"),
        encoding="utf-8",
    )

    payload = check_skill_candidate(baseline_path=baseline, candidate_path=candidate)

    assert payload["ok"] is False
    assert "frontmatter name" in payload["errors"][0]


def test_skillopt_cli_export_and_check(tmp_path):
    skill_path = tmp_path / ".agents" / "skills" / "review" / "SKILL.md"
    tasks_path = tmp_path / "eval-tasks.yaml"
    _write_skill(skill_path)
    _write_tasks(tasks_path)

    runner = CliRunner()
    export_result = runner.invoke(
        cli_main,
        [
            "skillopt",
            "export",
            "review",
            "--tasks",
            str(tasks_path),
            "--project",
            str(tmp_path / "opt"),
            "--root",
            str(tmp_path),
            "--json",
        ],
    )

    assert export_result.exit_code == 0, export_result.output
    payload = json.loads(export_result.output)
    check_result = runner.invoke(
        cli_main,
        [
            "skillopt",
            "check",
            "--baseline",
            payload["baseline_skill_path"],
            "--candidate",
            payload["skill_path"],
            "--json",
        ],
    )

    assert check_result.exit_code == 0, check_result.output
    assert json.loads(check_result.output)["ok"] is True


def test_optimize_skill_with_gepa_stages_fake_result(tmp_path):
    skill_path = tmp_path / ".agents" / "skills" / "review" / "SKILL.md"
    tasks_path = tmp_path / "eval-tasks.yaml"
    harness_path = tmp_path / "harness.yaml"
    _write_skill(skill_path)
    _write_tasks(tasks_path)
    _write_harness(harness_path)

    class FakeResult:
        best_candidate = {
            "skill": skill_path.read_text(encoding="utf-8")
            + "\nPrefer precise regression evidence.\n"
        }
        best_idx = 1
        val_aggregate_scores = [0.25, 0.75]
        total_metric_calls = 2

    def fake_optimizer(**kwargs):
        assert kwargs["seed_candidate"]["skill"].startswith("---")
        assert kwargs["dataset"][0]["id"] == "smoke"
        assert kwargs["valset"][0]["id"] == "smoke"
        return FakeResult()

    result = optimize_skill_with_gepa(
        skill="review",
        harness_path=harness_path,
        tasks_path=tasks_path,
        output_dir=tmp_path / "opt-gepa",
        root=tmp_path,
        optimizer=fake_optimizer,
        allow_dry_run=True,
        max_edits=2,
    )

    assert result.engine == "gepa"
    assert result.baseline_score == 0.25
    assert result.best_score == 0.75
    assert result.check["ok"] is True
    assert "Prefer precise regression evidence" in result.staged_skill_path.read_text(
        encoding="utf-8"
    )
    assert result.report_json_path.exists()
    assert result.report_md_path.exists()


def test_optimize_skill_with_gepa_passes_gepa_search_controls(tmp_path, monkeypatch):
    skill_path = tmp_path / ".agents" / "skills" / "review" / "SKILL.md"
    tasks_path = tmp_path / "eval-tasks.yaml"
    harness_path = tmp_path / "harness.yaml"
    _write_skill(skill_path)
    _write_tasks(tasks_path)
    _write_harness(harness_path)

    captured = {}

    class FakeEngineConfig:
        def __init__(self, **kwargs):
            captured["engine"] = kwargs

    class FakeReflectionConfig:
        def __init__(self, **kwargs):
            captured["reflection"] = kwargs

    class FakeMergeConfig:
        def __init__(self, **kwargs):
            captured["merge"] = kwargs

    class FakeGEPAConfig:
        def __init__(self, **kwargs):
            captured["config"] = kwargs

    class FakeResult:
        best_candidate = {"skill": skill_path.read_text(encoding="utf-8")}
        best_idx = 0
        val_aggregate_scores = [1.0]
        total_metric_calls = 1

    def fake_optimize_anything(**kwargs):
        captured["optimize"] = kwargs
        return FakeResult()

    import sys
    import types

    fake_module = types.ModuleType("gepa.optimize_anything")
    fake_module.EngineConfig = FakeEngineConfig
    fake_module.GEPAConfig = FakeGEPAConfig
    fake_module.MergeConfig = FakeMergeConfig
    fake_module.ReflectionConfig = FakeReflectionConfig
    fake_module.optimize_anything = fake_optimize_anything
    monkeypatch.setitem(sys.modules, "gepa.optimize_anything", fake_module)

    optimize_skill_with_gepa(
        skill="review",
        harness_path=harness_path,
        tasks_path=tasks_path,
        output_dir=tmp_path / "opt-gepa-controls",
        root=tmp_path,
        allow_dry_run=True,
        max_candidate_proposals=7,
        max_reflection_cost=1.25,
        candidate_selection_strategy="top_k_pareto",
        frontier_type="cartesian",
        acceptance_criterion="improvement_or_equal",
        cache_evaluation=True,
        use_merge=True,
        max_merge_invocations=3,
    )

    assert captured["engine"]["max_candidate_proposals"] == 7
    assert captured["engine"]["max_reflection_cost"] == 1.25
    assert captured["engine"]["candidate_selection_strategy"] == "top_k_pareto"
    assert captured["engine"]["frontier_type"] == "cartesian"
    assert captured["engine"]["acceptance_criterion"] == "improvement_or_equal"
    assert captured["engine"]["cache_evaluation"] is True
    assert captured["merge"]["max_merge_invocations"] == 3
    assert captured["config"]["merge"] is not None


def test_skills_optimize_requires_live_for_gepa(tmp_path):
    skill_path = tmp_path / ".agents" / "skills" / "review" / "SKILL.md"
    tasks_path = tmp_path / "eval-tasks.yaml"
    harness_path = tmp_path / "harness.yaml"
    _write_skill(skill_path)
    _write_tasks(tasks_path)
    _write_harness(harness_path)

    result = CliRunner().invoke(
        cli_main,
        [
            "skills",
            "optimize",
            "review",
            "--harness",
            str(harness_path),
            "--tasks",
            str(tasks_path),
            "--root",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert "requires --live" in result.output
