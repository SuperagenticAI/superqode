"""Benchmark harness for comparing coding agent CLIs."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class BenchmarkTarget:
    """A CLI target to benchmark."""

    name: str
    command: List[str]


@dataclass(frozen=True)
class BenchmarkTask:
    """A benchmark task definition."""

    id: str
    prompt: str
    cwd: Path
    timeout_seconds: int = 300


DEFAULT_TARGETS = {
    "superqode": BenchmarkTarget("superqode", ["superqode", "-p"]),
    "opencode": BenchmarkTarget("opencode", ["opencode", "run"]),
    "pi": BenchmarkTarget("pi", ["pi", "-p"]),
    "deepagents": BenchmarkTarget("deepagents", ["deepagents"]),
}


def is_target_available(target: BenchmarkTarget) -> bool:
    """Check whether a benchmark target executable is available."""
    return shutil.which(target.command[0]) is not None


def run_benchmark_task(task: BenchmarkTask, target: BenchmarkTarget) -> Dict[str, Any]:
    """Run one benchmark task against one target."""
    started = time.monotonic()
    if not is_target_available(target):
        return {
            "target": target.name,
            "task_id": task.id,
            "status": "skipped",
            "reason": f"executable not found: {target.command[0]}",
        }

    command = [*target.command, task.prompt]
    try:
        completed = subprocess.run(
            command,
            cwd=task.cwd,
            text=True,
            capture_output=True,
            timeout=task.timeout_seconds,
            check=False,
        )
        duration = time.monotonic() - started
        return {
            "target": target.name,
            "task_id": task.id,
            "status": "passed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "duration_seconds": round(duration, 3),
            "stdout_chars": len(completed.stdout),
            "stderr_chars": len(completed.stderr),
        }
    except subprocess.TimeoutExpired:
        return {
            "target": target.name,
            "task_id": task.id,
            "status": "timeout",
            "duration_seconds": task.timeout_seconds,
        }


def run_benchmark_suite(
    tasks: List[BenchmarkTask],
    targets: Optional[List[BenchmarkTarget]] = None,
) -> List[Dict[str, Any]]:
    """Run all tasks against all selected targets."""
    selected_targets = targets or list(DEFAULT_TARGETS.values())
    results: List[Dict[str, Any]] = []
    for task in tasks:
        for target in selected_targets:
            results.append(run_benchmark_task(task, target))
    return results


def load_tasks(path: str | Path) -> List[BenchmarkTask]:
    """Load benchmark tasks from JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks: List[BenchmarkTask] = []
    for item in data.get("tasks", []):
        tasks.append(
            BenchmarkTask(
                id=item["id"],
                prompt=item["prompt"],
                cwd=Path(item.get("cwd", ".")).expanduser().resolve(),
                timeout_seconds=int(item.get("timeout_seconds", 300)),
            )
        )
    return tasks
