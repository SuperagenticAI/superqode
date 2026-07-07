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

EVAL_SPLITS = ("all", "held-in", "held-out")


def bundled_eval_packs_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "eval_packs"


def list_eval_packs() -> list[dict[str, Any]]:
    """Return bundled HarnessSpec eval packs."""
    rows: list[dict[str, Any]] = []
    root = bundled_eval_packs_dir()
    for path in sorted(root.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        metadata = data.get("metadata") if isinstance(data, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        rows.append(
            {
                "id": str(metadata.get("id") or path.stem),
                "name": str(metadata.get("name") or path.stem),
                "description": str(metadata.get("description") or ""),
                "best_for": str(metadata.get("best_for") or ""),
                "path": str(path),
                "tasks": len(data.get("tasks") or []) if isinstance(data, dict) else 0,
            }
        )
    return rows


def eval_pack_path(pack_id: str) -> Path:
    """Resolve a bundled eval pack id or path."""
    candidate = Path(pack_id).expanduser()
    if candidate.exists():
        return candidate
    normalized = pack_id.strip().removesuffix(".yaml")
    for row in list_eval_packs():
        if row["id"] == normalized or Path(row["path"]).stem == normalized:
            return Path(row["path"])
    raise ValueError(f"Unknown eval pack: {pack_id}")


def load_eval_tasks(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Eval task file must be a mapping")
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Eval task file requires a non-empty tasks list")
    normalized_tasks: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"Eval task at index {index} must be a mapping")
        if not str(task.get("id") or "").strip():
            raise ValueError(f"Eval task at index {index} requires id")
        if not str(task.get("prompt") or "").strip():
            raise ValueError(f"Eval task {task.get('id') or index} requires prompt")
        normalized = dict(task)
        normalized["split"] = _normalize_eval_split(task.get("split"))
        normalized_tasks.append(normalized)
    variants = data.get("variants", [])
    if variants is not None and not isinstance(variants, list):
        raise ValueError("Eval variants must be a list")
    return {
        "tasks": normalized_tasks,
        "variants": variants or [],
        "metadata": data.get("metadata") or {},
        "split_counts": eval_task_split_counts(normalized_tasks),
    }


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
    eval_split: str = "all",
) -> dict[str, Any]:
    task_file = load_eval_tasks(tasks_path)
    split = _normalize_eval_filter(eval_split)
    tasks = filter_eval_tasks(task_file["tasks"], split)
    if not tasks:
        raise ValueError(f"No eval tasks match split: {split}")
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
                tasks=tasks,
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
        "split": split,
        "task_count": len(tasks),
        "split_counts": task_file.get("split_counts") or eval_task_split_counts(task_file["tasks"]),
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


def filter_eval_tasks(tasks: list[dict[str, Any]], split: str = "all") -> list[dict[str, Any]]:
    """Return tasks for an eval split."""
    normalized = _normalize_eval_filter(split)
    if normalized == "all":
        return list(tasks)
    return [task for task in tasks if _normalize_eval_split(task.get("split")) == normalized]


def eval_task_split_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"held-in": 0, "held-out": 0, "all": len(tasks)}
    for task in tasks:
        split = _normalize_eval_split(task.get("split"))
        if split in {"held-in", "held-out"}:
            counts[split] += 1
    return counts


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
    duration_seconds = round(time.monotonic() - started, 3)
    usage = _aggregate_task_usage(task_results)
    return {
        "harness": spec.name,
        "spec": str(spec_path),
        "inherits": spec.inherits or "",
        "status": status,
        "score": round(score, 3),
        "passed": passed,
        "failed": failed,
        "skipped": sum(1 for item in task_results if item["status"] == "skipped"),
        "duration_seconds": duration_seconds,
        "usage": usage,
        "tokens_in": usage["tokens_in"],
        "tokens_out": usage["tokens_out"],
        "total_tokens": usage["total_tokens"],
        "cost_usd": usage["cost_usd"],
        "tokens_per_success": _per_success(usage["total_tokens"], passed),
        "cost_per_success": _per_success(usage["cost_usd"], passed, digits=8),
        "latency_ms_per_success": _per_success(duration_seconds * 1000, passed),
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
            "split": task.get("split") or "held-in",
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
        usage = _usage_from_result(result)
        passed, reason = _score_content(content, task)
        return {
            "id": task["id"],
            "split": task.get("split") or "held-in",
            "status": "passed" if passed else "failed",
            "score": 1.0 if passed else 0.0,
            "duration_seconds": round(time.monotonic() - started, 3),
            "run_id": run_id,
            "content_chars": len(content),
            "usage": usage,
            "tokens_in": usage["tokens_in"],
            "tokens_out": usage["tokens_out"],
            "total_tokens": usage["total_tokens"],
            "cost_usd": usage["cost_usd"],
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
            "split": task.get("split") or "held-in",
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


def _normalize_eval_filter(value: Any) -> str:
    normalized = str(value or "all").strip().lower().replace("_", "-")
    if normalized in {"*", "any"}:
        return "all"
    if normalized in {"heldin", "held-in", "in", "train", "training"}:
        return "held-in"
    if normalized in {"heldout", "held-out", "holdout", "out", "validation", "test"}:
        return "held-out"
    if normalized == "all":
        return "all"
    raise ValueError("eval split must be one of: all, held-in, held-out")


def _normalize_eval_split(value: Any) -> str:
    normalized = str(value or "held-in").strip().lower().replace("_", "-")
    if normalized in {"heldin", "held-in", "in", "train", "training", "all"}:
        return "held-in"
    if normalized in {"heldout", "held-out", "holdout", "out", "validation", "test"}:
        return "held-out"
    raise ValueError("eval task split must be one of: held-in, held-out")


def _usage_from_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "results"):
        return _aggregate_run_usage(result.results)
    return _aggregate_run_usage([result])


def _aggregate_run_usage(results: list[Any] | tuple[Any, ...]) -> dict[str, Any]:
    tokens_in = 0
    tokens_out = 0
    total_tokens = 0
    cost_usd = 0.0
    currency = ""
    usage_seen = False
    cost_seen = False
    for result in results:
        in_value = getattr(result, "tokens_in", None)
        out_value = getattr(result, "tokens_out", None)
        total_value = getattr(result, "total_tokens", None)
        cost_value = getattr(result, "cost_usd", None)
        response = getattr(result, "response", None)
        if in_value is None and response is not None:
            in_value = getattr(response, "input_tokens", None)
        if out_value is None and response is not None:
            out_value = getattr(response, "output_tokens", None)
        if total_value is None and response is not None:
            total_value = getattr(response, "total_tokens", None)
        if cost_value is None and response is not None:
            cost_value = getattr(response, "cost_usd", None)
        if in_value is not None or out_value is not None or total_value is not None:
            in_tokens = int(in_value or 0)
            out_tokens = int(out_value or 0)
            total = int(total_value or (in_tokens + out_tokens))
            tokens_in += in_tokens
            tokens_out += out_tokens
            total_tokens += total
            usage_seen = True
        if cost_value is not None:
            cost_usd += float(cost_value)
            cost_seen = True
            if response is not None:
                currency = getattr(response, "cost_currency", None) or currency
    return {
        "tokens_in": tokens_in if usage_seen else None,
        "tokens_out": tokens_out if usage_seen else None,
        "total_tokens": total_tokens if usage_seen else None,
        "cost_usd": round(cost_usd, 12) if cost_seen else None,
        "cost_currency": currency or ("USD" if cost_seen else None),
    }


def _aggregate_task_usage(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return _aggregate_usage_dicts([task.get("usage") or {} for task in tasks])


def _aggregate_usage_dicts(usages: list[dict[str, Any]]) -> dict[str, Any]:
    tokens_in = 0
    tokens_out = 0
    total_tokens = 0
    cost_usd = 0.0
    currency = ""
    usage_seen = False
    cost_seen = False
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        in_value = usage.get("tokens_in")
        out_value = usage.get("tokens_out")
        total_value = usage.get("total_tokens")
        cost_value = usage.get("cost_usd")
        if in_value is not None or out_value is not None or total_value is not None:
            in_tokens = int(in_value or 0)
            out_tokens = int(out_value or 0)
            total = int(total_value or (in_tokens + out_tokens))
            tokens_in += in_tokens
            tokens_out += out_tokens
            total_tokens += total
            usage_seen = True
        if cost_value is not None:
            cost_usd += float(cost_value)
            currency = str(usage.get("cost_currency") or currency or "USD")
            cost_seen = True
    return {
        "tokens_in": tokens_in if usage_seen else None,
        "tokens_out": tokens_out if usage_seen else None,
        "total_tokens": total_tokens if usage_seen else None,
        "cost_usd": round(cost_usd, 12) if cost_seen else None,
        "cost_currency": currency or ("USD" if cost_seen else None),
    }


def _per_success(value: int | float | None, passed: int, *, digits: int = 3) -> float | None:
    if value is None or passed <= 0:
        return None
    return round(float(value) / passed, digits)


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
        f"Split: {payload.get('split') or 'all'} ({payload.get('task_count') or 0} task(s))",
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
        usage = variant.get("usage") or {}
        if usage.get("total_tokens") is not None or usage.get("cost_usd") is not None:
            lines.append(
                "    usage: "
                f"tokens={usage.get('total_tokens') if usage.get('total_tokens') is not None else '-'} "
                f"in={usage.get('tokens_in') if usage.get('tokens_in') is not None else '-'} "
                f"out={usage.get('tokens_out') if usage.get('tokens_out') is not None else '-'} "
                f"cost_usd={usage.get('cost_usd') if usage.get('cost_usd') is not None else '-'}"
            )
        if variant["regressions_vs_baseline"]:
            lines.append(f"    regressions: {', '.join(variant['regressions_vs_baseline'])}")
    return "\n".join(lines)
