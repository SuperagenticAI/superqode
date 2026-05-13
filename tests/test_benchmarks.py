"""Tests for benchmark harness primitives."""

import json

from superqode.benchmarks import (
    BenchmarkTarget,
    is_target_available,
    load_tasks,
    run_benchmark_task,
)


def test_load_tasks(tmp_path):
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(
        json.dumps({"tasks": [{"id": "t1", "prompt": "inspect", "cwd": str(tmp_path)}]}),
        encoding="utf-8",
    )

    tasks = load_tasks(tasks_file)

    assert tasks[0].id == "t1"
    assert tasks[0].prompt == "inspect"
    assert tasks[0].cwd == tmp_path


def test_unavailable_target_is_skipped(tmp_path):
    target = BenchmarkTarget("missing", ["definitely-not-superqode-command"])

    from superqode.benchmarks import BenchmarkTask

    result = run_benchmark_task(
        BenchmarkTask(id="t1", prompt="noop", cwd=tmp_path),
        target,
    )

    assert is_target_available(target) is False
    assert result["status"] == "skipped"
