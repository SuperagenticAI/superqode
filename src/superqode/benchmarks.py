"""Isolated, graded comparisons of explicitly configured coding agent CLIs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import signal
import statistics
import subprocess
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkTarget:
    name: str
    command: list[str]
    provider: str | None = None
    model: str | None = None
    revision: str | None = None


@dataclass(frozen=True)
class BenchmarkTask:
    id: str
    prompt: str
    cwd: Path
    timeout_seconds: int = 300
    expected_text: str | None = None
    checks: tuple[tuple[str, ...], ...] = ()
    protected_paths: tuple[str, ...] = ()


DEFAULT_TARGETS = {
    "superqode": BenchmarkTarget("superqode", ["superqode", "-p"]),
    "opencode": BenchmarkTarget("opencode", ["opencode", "run"]),
    "pi": BenchmarkTarget("pi", ["pi", "-p"]),
    "deepagents": BenchmarkTarget("deepagents", ["deepagents"]),
}


def is_target_available(target: BenchmarkTarget) -> bool:
    return bool(target.command) and shutil.which(target.command[0]) is not None


def _run(argv, cwd, timeout):
    """Terminate the owned process group on deadline, including its children."""
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        start_new_session=os.name == "posix",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        stdout, stderr = process.communicate()
        return process.returncode, stdout, stderr, True


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _protected(root, paths):
    hashes = {}
    for name in paths:
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("Protected grader paths must be files inside the task workspace")
        hashes[name] = _digest(path)
    return hashes


def _metrics(stdout, target, *, completed):
    """Read reported usage from SQ JSON or Pi JSON message-end events.

    Reported prices are estimates from the harness, not verified billing. A
    timed-out/failed run can have additional unreported spend.
    """
    try:
        values = [json.loads(stdout)]
    except ValueError:
        values = []
        for line in stdout.splitlines():
            try:
                values.append(json.loads(line))
            except ValueError:
                continue
    measurements = []
    for value in values:
        if not isinstance(value, dict):
            continue
        if value.get("type") == "message_end":
            message = value.get("message", {})
            if message.get("role") != "assistant":
                continue
            usage = message.get("usage", {})
            measurements.append(
                {
                    "cost": usage.get("cost", {}).get("total"),
                    "tokens": usage.get("totalTokens"),
                    "provider": message.get("provider"),
                    "model": message.get("model"),
                    "complete": message.get("stopReason") not in {"error", "aborted"},
                }
            )
        elif "cost_usd" in value:
            measurements.append(
                {
                    "cost": value.get("cost_usd"),
                    "tokens": value.get("total_tokens"),
                    "provider": value.get("provider"),
                    "model": value.get("model"),
                    "complete": value.get("stopped_reason")
                    not in {"error", "failed", "recovery_required", "needs_approval"},
                }
            )
    valid = [
        m
        for m in measurements
        if isinstance(m["cost"], (float, int))
        and not isinstance(m["cost"], bool)
        and math.isfinite(m["cost"])
        and m["cost"] >= 0
    ]
    complete = (
        bool(measurements)
        and len(valid) == len(measurements)
        and completed
        and all(m.get("complete", True) for m in measurements)
    )
    verified = (
        bool(measurements)
        and all(
            m["provider"] == target.provider and m["model"] == target.model for m in measurements
        )
        and bool(target.provider and target.model)
    )
    return {
        "cost_usd": sum(m["cost"] for m in valid) if valid else None,
        "usage_complete": complete,
        "configuration_verified": verified,
        "cost_provenance": "harness-reported estimate" if valid else "unreported",
    }


def run_benchmark_task(task: BenchmarkTask, target: BenchmarkTarget) -> dict[str, Any]:
    started = time.monotonic()
    identity = {
        "target": target.name,
        "task_id": task.id,
        "provider": target.provider,
        "model": target.model,
        "revision": target.revision,
        "configuration_verified": False,
        "cost_usd": None,
        "usage_complete": False,
    }
    if not is_target_available(target):
        return {
            **identity,
            "status": "skipped",
            "reason": f"executable not found: {target.command[0]}",
        }
    try:
        protected = _protected(task.cwd, task.protected_paths)
        code, stdout, stderr, timed_out = _run(
            [*target.command, task.prompt], task.cwd, task.timeout_seconds
        )
        duration = time.monotonic() - started
        checks = []
        unchanged = _protected(task.cwd, task.protected_paths) == protected
        if code == 0 and unchanged:
            for argv in task.checks:
                check_code, _, _, timeout = _run(list(argv), task.cwd, task.timeout_seconds)
                checks.append(
                    {
                        "command": list(argv),
                        "passed": check_code == 0 and not timeout,
                        "returncode": check_code,
                        "timed_out": timeout,
                    }
                )
        graded = task.expected_text is not None or bool(task.checks)
        correct = (
            unchanged
            and (task.expected_text is None or task.expected_text in stdout)
            and all(c["passed"] for c in checks)
        )
        status = (
            "timeout"
            if timed_out
            else (
                "failed"
                if code != 0 or (graded and not correct)
                else ("passed" if graded else "completed")
            )
        )
        return {
            **identity,
            "status": status,
            "quality_status": "graded" if graded else "ungraded",
            "checks": checks,
            "grader_unchanged": unchanged,
            "returncode": code,
            "duration_seconds": round(duration, 3),
            "grading_seconds": round(time.monotonic() - started - duration, 3),
            "stdout_chars": len(stdout),
            "stderr_chars": len(stderr),
            "output_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            **_metrics(stdout, target, completed=code == 0 and not timed_out),
        }
    except (OSError, ValueError) as error:
        return {
            **identity,
            "status": "failed",
            "reason": type(error).__name__,
            "duration_seconds": round(time.monotonic() - started, 3),
        }


def run_benchmark_suite(
    tasks: list[BenchmarkTask],
    targets: list[BenchmarkTarget] | None = None,
    *,
    repetitions: int = 1,
) -> list[dict[str, Any]]:
    if not isinstance(repetitions, int) or not 1 <= repetitions <= 20:
        raise ValueError("repetitions requires an integer from 1 to 20")
    selected = list(DEFAULT_TARGETS.values()) if targets is None else targets
    results = []
    ignored = shutil.ignore_patterns(
        ".git", ".venv", "node_modules", "__pycache__", ".superqode", ".env", ".env.*"
    )
    for task in tasks:
        with tempfile.TemporaryDirectory(prefix="superqode-benchmark-seed-") as directory:
            seed = Path(directory) / "seed"
            shutil.copytree(task.cwd, seed, ignore=ignored, ignore_dangling_symlinks=True)
            source_sha = hashlib.sha256()
            for path in sorted(seed.rglob("*")):
                if path.is_file():
                    source_sha.update(
                        str(path.relative_to(seed)).encode() + b"\0" + _digest(path).encode()
                    )
            for repeat in range(repetitions):
                for target in selected if repeat % 2 == 0 else list(reversed(selected)):
                    with tempfile.TemporaryDirectory(prefix="superqode-benchmark-") as attempt:
                        workspace = Path(attempt) / "workspace"
                        shutil.copytree(seed, workspace)
                        row = run_benchmark_task(replace(task, cwd=workspace), target)
                        row.update(
                            workspace_isolated=True,
                            source_workspace=str(task.cwd),
                            source_sha256=source_sha.hexdigest(),
                            repetition=repeat + 1,
                        )
                        results.append(row)
    return results


def load_tasks(path: str | Path) -> list[BenchmarkTask]:
    source = Path(path).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    tasks = []
    for item in data.get("tasks", []):
        cwd = Path(item.get("cwd", ".")).expanduser()
        tasks.append(
            BenchmarkTask(
                id=item["id"],
                prompt=item["prompt"],
                cwd=(cwd if cwd.is_absolute() else source.parent / cwd).resolve(),
                timeout_seconds=int(item.get("timeout_seconds", 300)),
                expected_text=item.get("expected_text"),
                checks=tuple(tuple(str(arg) for arg in check) for check in item.get("checks", [])),
                protected_paths=tuple(item.get("protected_paths", [])),
            )
        )
    return tasks


def load_comparison(path: str | Path):
    data = json.loads(Path(path).read_text())
    targets = []
    for item in data.get("targets", []):
        if not all(
            isinstance(item.get(key), str) and item[key]
            for key in ("name", "provider", "model", "revision")
        ):
            raise ValueError(
                "Every comparison target requires name, provider, model and pinned revision"
            )
        command = item.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(arg, str) for arg in command)
        ):
            raise ValueError("Target command requires a nonempty argument list")
        targets.append(
            BenchmarkTarget(
                item["name"], command, item["provider"], item["model"], item["revision"]
            )
        )
    if len(targets) < 2 or len({t.name for t in targets}) != len(targets):
        raise ValueError("A comparison requires at least two distinct targets")
    if len({(t.provider, t.model) for t in targets}) != 1:
        raise ValueError("Comparison targets must declare the same provider and model")
    tasks = load_tasks(path)
    if not tasks or any(not t.checks for t in tasks) or len({t.id for t in tasks}) != len(tasks):
        raise ValueError("Comparison tasks require unique IDs and executable graders")
    return tasks, targets


def benchmark_scorecard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    targets = {}
    for name in sorted({str(row["target"]) for row in rows}):
        attempts = [row for row in rows if row["target"] == name]
        solved = {row["task_id"] for row in attempts if row.get("status") == "passed"}
        solved_trials = {
            (row["task_id"], row.get("repetition", 1))
            for row in attempts
            if row.get("status") == "passed"
        }
        executed = [row for row in attempts if row.get("status") != "skipped"]
        complete = bool(executed) and all(
            row.get("cost_usd") is not None and row.get("usage_complete", True) for row in executed
        )
        measured = sum(float(row.get("cost_usd") or 0) for row in executed)
        durations = sorted(row["duration_seconds"] for row in executed if "duration_seconds" in row)
        targets[name] = {
            "attempts": len(attempts),
            "solved": len(solved),
            "solved_trials": len(solved_trials),
            "passed_attempts": sum(row.get("status") == "passed" for row in attempts),
            "success_rate": sum(row.get("status") == "passed" for row in executed) / len(executed)
            if executed
            else None,
            "skipped": len(attempts) - len(executed),
            "unknown_cost_attempts": sum(
                not row.get("usage_complete", row.get("cost_usd") is not None) for row in executed
            ),
            "observed_cost_usd": measured,
            "total_cost_usd": measured if complete else None,
            "cost_per_solved_task": measured / len(solved_trials)
            if complete and solved_trials
            else None,
            "median_seconds": statistics.median(durations) if durations else None,
            "p95_seconds": durations[math.ceil(len(durations) * 0.95) - 1] if durations else None,
            "ungraded": sum(row.get("quality_status") == "ungraded" for row in attempts),
        }
    ready = (
        len(targets) >= 2
        and bool(rows)
        and all(
            row.get("quality_status") == "graded"
            and row.get("configuration_verified")
            and row.get("revision")
            and row.get("workspace_isolated")
            and row.get("usage_complete")
            for row in rows
        )
    )
    return {
        "targets": targets,
        "comparison_ready": ready,
        "comparison_claim": "Matched graded evidence is required; harness-reported costs are estimates, not billing verification",
    }
