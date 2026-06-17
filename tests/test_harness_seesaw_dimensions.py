"""HarnessX-inspired cheap wins: 9-dimension failure tags + the seesaw gate."""

from __future__ import annotations

import asyncio

from click.testing import CliRunner


# --- Win 1: nine-dimension failure tagging -------------------------------------


def test_failure_digest_tags_dimension():
    from superqode.harness.testing import HarnessTestCheck, build_failure_digest

    digest = build_failure_digest(
        [HarnessTestCheck("before_model", "failed", error="provider endpoint unreachable")]
    )
    assert digest["failure_category"] == "model_endpoint_error"
    assert digest["dimension"]["id"] == "D1"  # model selection
    assert digest["dimension"]["field"] == "model_policy"


def test_passed_digest_has_empty_dimension():
    from superqode.harness.testing import HarnessTestCheck, build_failure_digest

    digest = build_failure_digest([HarnessTestCheck("load", "passed")])
    assert digest["outcome"] == "passed"
    assert digest["dimension"] == {"id": "", "label": "", "field": ""}


def test_dimension_for_category_mapping():
    from superqode.harness.testing import HARNESS_DIMENSIONS, dimension_for_category

    assert dimension_for_category("tool_or_permission_error")["id"] == "D7"
    assert dimension_for_category("runtime_error")["id"] == "D5"
    assert dimension_for_category("spec_load_error")["id"] == "D2"
    assert dimension_for_category("nope") == {"id": "", "label": "", "field": ""}
    # Every mapped dimension is a real D1-D9 entry with a canonical field.
    for category in ("model_endpoint_error", "tool_or_permission_error", "runtime_error"):
        dim = dimension_for_category(category)
        assert dim["id"] in HARNESS_DIMENSIONS
        assert dim["field"]


# --- Win 2: the seesaw gate ----------------------------------------------------


def test_harness_eval_regressions_helper():
    from superqode.harness import harness_eval_regressions

    baseline = {"tasks": [{"id": "t1", "status": "passed"}, {"id": "t2", "status": "passed"}]}
    candidate = {"tasks": [{"id": "t1", "status": "passed"}, {"id": "t2", "status": "failed"}]}
    assert harness_eval_regressions(baseline, candidate) == ["t2"]
    # A candidate that keeps everything passing has no regressions.
    assert harness_eval_regressions(baseline, baseline) == []


def test_run_harness_eval_marks_regressed(monkeypatch):
    import superqode.harness.eval as ev

    monkeypatch.setattr(
        ev, "load_eval_tasks", lambda p: {"tasks": [{"id": "t1"}, {"id": "t2"}], "variants": []}
    )

    async def _fake_variant(*, spec_path, **kwargs):
        name = str(spec_path)
        # baseline solves both; the candidate regresses t2.
        if "candidate" in name:
            tasks = [{"id": "t1", "status": "passed"}, {"id": "t2", "status": "failed"}]
        else:
            tasks = [{"id": "t1", "status": "passed"}, {"id": "t2", "status": "passed"}]
        passed = sum(1 for t in tasks if t["status"] == "passed")
        return {
            "harness": name,
            "spec": name,
            "status": "passed",
            "score": passed / len(tasks),
            "passed": passed,
            "failed": len(tasks) - passed,
            "skipped": 0,
            "duration_seconds": 0.1,
            "tasks": tasks,
        }

    monkeypatch.setattr(ev, "_run_variant_eval", _fake_variant)

    payload = asyncio.run(
        ev.run_harness_eval(
            spec_paths=["baseline.yaml", "candidate.yaml"],
            tasks_path="tasks.yaml",
            provider="x",
            model="y",
        )
    )
    assert payload["regressed"] is True
    assert payload["regressed_variants"] == ["candidate.yaml"]


def test_eval_cli_exits_nonzero_on_regression(monkeypatch):
    import superqode.harness.eval as ev
    from superqode.main import cli_main

    async def _fake_eval(**kwargs):
        return {
            "tasks_file": "tasks.yaml",
            "live": False,
            "status": "passed",
            "duration_seconds": 0.1,
            "baseline": "base",
            "best": "base",
            "regressed": True,
            "regressed_variants": ["candidate"],
            "variants": [],
        }

    # The CLI does `from superqode.harness import run_harness_eval`.
    monkeypatch.setattr(ev, "run_harness_eval", _fake_eval)
    monkeypatch.setattr("superqode.harness.run_harness_eval", _fake_eval, raising=False)
    monkeypatch.setattr("superqode.harness.render_harness_eval", lambda p: "ok", raising=False)

    runner = CliRunner()
    with runner.isolated_filesystem():
        import os

        os.write(os.open("s.yaml", os.O_CREAT | os.O_WRONLY), b"name: s\n")
        os.write(os.open("t.yaml", os.O_CREAT | os.O_WRONLY), b"tasks: []\n")
        blocked = runner.invoke(cli_main, ["harness", "eval", "--spec", "s.yaml", "--tasks", "t.yaml"])
        assert blocked.exit_code == 2  # seesaw gate blocks
        allowed = runner.invoke(
            cli_main,
            ["harness", "eval", "--spec", "s.yaml", "--tasks", "t.yaml", "--allow-regressions"],
        )
        assert allowed.exit_code == 0  # override
