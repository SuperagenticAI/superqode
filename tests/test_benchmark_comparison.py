"""Independent grading, repeated isolation and honest comparative accounting."""

import json
import sys

import pytest
from click.testing import CliRunner

from superqode.main import cli_main
from superqode.benchmarks import (
    BenchmarkTask,
    BenchmarkTarget,
    run_benchmark_task,
    run_benchmark_suite,
    benchmark_scorecard,
    load_comparison,
)


def target(name="fixture", *, reported_model="same"):
    script = (
        'from pathlib import Path; import json; Path("answer").write_text("correct"); print(json.dumps({"provider":"fixture","model":'
        + repr(reported_model)
        + ',"cost_usd":0.05,"total_tokens":10}))'
    )
    return BenchmarkTarget(name, [sys.executable, "-c", script], "fixture", "same", "fixture-v1")


def test_repeated_trials_are_fresh_and_charge_every_attempt(tmp_path):
    task = BenchmarkTask(
        "case",
        "do",
        tmp_path,
        checks=(
            (
                sys.executable,
                "-c",
                'from pathlib import Path; assert Path("answer").read_text()=="correct"',
            ),
        ),
    )
    rows = run_benchmark_suite([task], [target("a"), target("b")], repetitions=3)
    assert len(rows) == 6 and all(r["status"] == "passed" for r in rows)
    assert len({r["source_sha256"] for r in rows}) == 1
    assert [r["target"] for r in rows] == ["a", "b", "b", "a", "a", "b"]
    card = benchmark_scorecard(rows)
    assert card["comparison_ready"]
    assert card["targets"]["a"]["solved_trials"] == 3
    assert card["targets"]["a"]["cost_per_solved_task"] == pytest.approx(0.05)
    assert not (tmp_path / "answer").exists()


def test_wrong_model_cannot_support_comparison(tmp_path):
    result = run_benchmark_task(
        BenchmarkTask("case", "do", tmp_path, expected_text="cost_usd"),
        target(reported_model="different"),
    )
    assert result["status"] == "passed" and not result["configuration_verified"]
    assert not benchmark_scorecard([result])["comparison_ready"]


def test_grader_tampering_fails_even_if_modified_grader_passes(tmp_path):
    (tmp_path / "grader.py").write_text("raise SystemExit(1)")
    command = [
        sys.executable,
        "-c",
        'from pathlib import Path; Path("grader.py").write_text("pass")',
    ]
    task = BenchmarkTask(
        "case",
        "do",
        tmp_path,
        checks=((sys.executable, "grader.py"),),
        protected_paths=("grader.py",),
    )
    result = run_benchmark_task(task, BenchmarkTarget("tamper", command))
    assert result["status"] == "failed" and not result["grader_unchanged"]


def test_grader_timeout_is_a_failure(tmp_path):
    task = BenchmarkTask(
        "case",
        "do",
        tmp_path,
        timeout_seconds=1,
        checks=((sys.executable, "-c", "import time;time.sleep(3)"),),
    )
    result = run_benchmark_task(task, target())
    assert result["status"] == "failed" and result["checks"][0]["timed_out"]


def test_cost_from_failed_attempt_stays_in_denominator():
    rows = [
        {
            "target": "one",
            "task_id": "case",
            "status": "failed",
            "cost_usd": 0.10,
            "usage_complete": True,
        },
        {
            "target": "one",
            "task_id": "case",
            "status": "passed",
            "cost_usd": 0.20,
            "usage_complete": True,
        },
    ]
    assert benchmark_scorecard(rows)["targets"]["one"]["cost_per_solved_task"] == pytest.approx(
        0.30
    )
    rows[0]["usage_complete"] = False
    card = benchmark_scorecard(rows)["targets"]["one"]
    assert card["observed_cost_usd"] == pytest.approx(0.30) and card["total_cost_usd"] is None


def test_manifest_rejects_mismatched_models_and_ungraded_tasks(tmp_path):
    manifest = tmp_path / "suite.json"
    data = {
        "targets": [
            {
                "name": n,
                "provider": "fixture",
                "model": n,
                "revision": "v1",
                "command": [sys.executable],
            }
            for n in ("a", "b")
        ],
        "tasks": [],
    }
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="same provider"):
        load_comparison(manifest)
    for t in data["targets"]:
        t["model"] = "same"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="graders"):
        load_comparison(manifest)


def test_cli_comparison_executes_manifest_and_writes_evidence(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    manifest = tmp_path / "suite.json"
    data = {
        "targets": [
            {
                "name": n,
                "provider": "fixture",
                "model": "same",
                "revision": "fixture-v1",
                "command": target(n).command,
            }
            for n in ("a", "b")
        ],
        "tasks": [
            {
                "id": "case",
                "prompt": "do",
                "cwd": "source",
                "checks": [
                    [
                        sys.executable,
                        "-c",
                        'from pathlib import Path; assert Path("answer").read_text()=="correct"',
                    ]
                ],
            }
        ],
    }
    manifest.write_text(json.dumps(data))
    output = tmp_path / "report.json"
    result = CliRunner().invoke(
        cli_main,
        ["benchmark", "compare", str(manifest), "--repetitions", "2", "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert len(json.loads(output.read_text())["results"]) == 4
