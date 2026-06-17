"""First-class HarnessSpec evaluation scorecards."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml

from .loader import load_harness_spec
from .store import create_harness_store
from .kernel import init_harness
from .spec import WorkflowMode
from .testing import build_failure_digest
from .workflow import run_workflow, workflow_steps_from_spec


def load_eval_tasks(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Eval task file must be a mapping")
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Eval task file requires a non-empty tasks list")
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"Eval task at index {index} must be a mapping")
        if not str(task.get("id") or "").strip():
            raise ValueError(f"Eval task at index {index} requires id")
        if not str(task.get("prompt") or "").strip():
            raise ValueError(f"Eval task {task.get('id') or index} requires prompt")
    variants = data.get("variants", [])
    if variants is not None and not isinstance(variants, list):
        raise ValueError("Eval variants must be a list")
    return {"tasks": tasks, "variants": variants or [], "metadata": data.get("metadata") or {}}


async def run_harness_eval(
    *,
    spec_paths: list[str | Path],
    tasks_path: str | Path,
    provider: str,
    model: str,
    runtime: str | None = None,
    working_dir: str | Path = ".",
    sandbox_backend: str = "local",
    live: bool = False,
) -> dict[str, Any]:
    task_file = load_eval_tasks(tasks_path)
    specs = list(spec_paths)
    for variant in task_file["variants"]:
        if isinstance(variant, dict) and variant.get("spec"):
            specs.append(variant["spec"])
    if not specs:
        raise ValueError("At least one harness spec is required")

    started = time.monotonic()
    variant_results = []
    for spec_path in specs:
        variant_results.append(
            await _run_variant_eval(
                spec_path=spec_path,
                tasks=task_file["tasks"],
                provider=provider,
                model=model,
                runtime=runtime,
                working_dir=working_dir,
                sandbox_backend=sandbox_backend,
                live=live,
            )
        )
    baseline = variant_results[0]
    for item in variant_results:
        item["delta_vs_baseline"] = round(item["score"] - baseline["score"], 3)
        item["regressions_vs_baseline"] = _regressions(baseline, item)
        item["regressed"] = bool(item["regressions_vs_baseline"])
    best = max(variant_results, key=lambda item: (item["score"], -item["duration_seconds"]))
    # Seesaw verdict: a candidate variant regresses if it breaks any task the
    # baseline solved. The baseline itself cannot regress against itself.
    regressed_variants = [item["harness"] for item in variant_results[1:] if item["regressed"]]
    return {
        "tasks_file": str(tasks_path),
        "live": live,
        "status": "passed"
        if all(item["status"] != "error" for item in variant_results)
        else "failed",
        "duration_seconds": round(time.monotonic() - started, 3),
        "baseline": baseline["harness"],
        "best": best["harness"],
        "regressed": bool(regressed_variants),
        "regressed_variants": regressed_variants,
        "variants": variant_results,
    }


def harness_eval_regressions(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Task ids the baseline solved that the candidate no longer solves.

    The seesaw constraint: an improved harness must not regress previously
    passing tasks. Operates on `harness eval` variant dicts, no model needed.
    """
    return _regressions(baseline, candidate)


async def _run_variant_eval(
    *,
    spec_path: str | Path,
    tasks: list[dict[str, Any]],
    provider: str,
    model: str,
    runtime: str | None,
    working_dir: str | Path,
    sandbox_backend: str,
    live: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    spec = load_harness_spec(spec_path)
    task_results = []
    kernel = None
    if live:
        store = create_harness_store("memory")
        kernel = await init_harness(spec, store=store)
    for task in tasks:
        task_results.append(
            await _run_eval_task(
                spec=spec,
                kernel=kernel,
                task=task,
                provider=provider,
                model=model,
                runtime=runtime,
                working_dir=working_dir,
                sandbox_backend=sandbox_backend,
                live=live,
            )
        )
    passed = sum(1 for item in task_results if item["status"] == "passed")
    failed = sum(1 for item in task_results if item["status"] == "failed")
    score = passed / len(task_results) if task_results else 0.0
    status = "error" if failed and passed == 0 else "passed"
    return {
        "harness": spec.name,
        "spec": str(spec_path),
        "inherits": spec.inherits or "",
        "status": status,
        "score": round(score, 3),
        "passed": passed,
        "failed": failed,
        "skipped": sum(1 for item in task_results if item["status"] == "skipped"),
        "duration_seconds": round(time.monotonic() - started, 3),
        "tasks": task_results,
    }


async def _run_eval_task(
    *,
    spec,
    kernel,
    task: dict[str, Any],
    provider: str,
    model: str,
    runtime: str | None,
    working_dir: str | Path,
    sandbox_backend: str,
    live: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    if not live:
        return {
            "id": task["id"],
            "status": "skipped",
            "score": 0.0,
            "duration_seconds": 0.0,
            "reason": "pass --live to execute eval tasks",
        }
    try:
        if spec.workflow.mode != WorkflowMode.SINGLE:
            result = await run_workflow(
                kernel,
                workflow_steps_from_spec(spec, task["prompt"]),
                provider=provider,
                model=model,
                runtime=runtime,
                working_directory=Path(working_dir),
                sandbox_backend=sandbox_backend,
            )
            content = result.content or ""
            run_id = result.run_id
        else:
            session = await kernel.session()
            result = await session.prompt(
                task["prompt"],
                provider=provider,
                model=model,
                runtime=runtime,
                working_directory=Path(working_dir),
                sandbox_backend=sandbox_backend,
            )
            content = result.content or ""
            run_id = result.run_id
        passed, reason = _score_content(content, task)
        return {
            "id": task["id"],
            "status": "passed" if passed else "failed",
            "score": 1.0 if passed else 0.0,
            "duration_seconds": round(time.monotonic() - started, 3),
            "run_id": run_id,
            "content_chars": len(content),
            "reason": reason,
            "failure_digest": {}
            if passed
            else build_failure_digest(
                [
                    type(
                        "EvalCheck",
                        (),
                        {
                            "name": "eval_task",
                            "status": "failed",
                            "error": reason,
                            "details": {"task_id": task["id"]},
                        },
                    )()
                ]
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "id": task["id"],
            "status": "failed",
            "score": 0.0,
            "duration_seconds": round(time.monotonic() - started, 3),
            "reason": str(exc),
            "failure_digest": build_failure_digest(
                [
                    type(
                        "EvalCheck",
                        (),
                        {
                            "name": "eval_task",
                            "status": "failed",
                            "error": str(exc),
                            "details": {"task_id": task["id"]},
                        },
                    )()
                ]
            ),
        }


def _score_content(content: str, task: dict[str, Any]) -> tuple[bool, str]:
    expected = task.get("expect_contains")
    if expected:
        values = expected if isinstance(expected, list) else [expected]
        missing = [str(value) for value in values if str(value) not in content]
        if missing:
            return False, f"missing expected text: {', '.join(missing)}"
        return True, "matched expect_contains"
    return (bool(content.strip()), "non-empty response" if content.strip() else "empty response")


def _regressions(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    base_by_id = {item["id"]: item for item in baseline["tasks"]}
    regressions = []
    for item in candidate["tasks"]:
        base = base_by_id.get(item["id"])
        if base and base["status"] == "passed" and item["status"] != "passed":
            regressions.append(item["id"])
    return regressions


def render_harness_eval(payload: dict[str, Any]) -> str:
    lines = [
        f"Harness eval: {payload['status']}",
        f"Tasks: {payload['tasks_file']}",
        f"Live: {payload['live']}",
        f"Baseline: {payload['baseline']}",
        f"Best: {payload['best']}",
        "",
        "Scorecard",
    ]
    for variant in payload["variants"]:
        lines.append(
            f"  {variant['harness']:<24} score={variant['score']:.3f} "
            f"passed={variant['passed']} failed={variant['failed']} "
            f"skipped={variant['skipped']} delta={variant['delta_vs_baseline']:+.3f}"
        )
        if variant["regressions_vs_baseline"]:
            lines.append(f"    regressions: {', '.join(variant['regressions_vs_baseline'])}")
    return "\n".join(lines)
