"""Guarded GEPA Omni optimization for complete SuperQode HarnessSpecs."""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from superqode.skillopt import (
    SKILL_OPTIMIZER_ENGINES,
    _best_skill_text,
    _optimization_splits,
    _result_metadata,
    _run_modern_optimizer,
    _safe_name,
)

from .eval import load_eval_tasks, run_harness_eval
from .loader import harness_spec_to_dict, load_harness_spec
from .self_improve import audit_harness_candidate, record_candidate_audit


@dataclass(frozen=True)
class HarnessOmniOptimizationResult:
    engine: str
    output_dir: Path
    baseline_spec_path: Path
    staged_spec_path: Path
    report_json_path: Path
    report_md_path: Path
    baseline_score: float | None
    best_score: float | None
    total_evals: int | None
    candidate_audit: dict[str, Any]
    heldout_eval: dict[str, Any]
    accepted: bool
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "output_dir": str(self.output_dir),
            "baseline_spec_path": str(self.baseline_spec_path),
            "staged_spec_path": str(self.staged_spec_path),
            "report_json_path": str(self.report_json_path),
            "report_md_path": str(self.report_md_path),
            "baseline_score": self.baseline_score,
            "best_score": self.best_score,
            "total_evals": self.total_evals,
            "candidate_audit": self.candidate_audit,
            "heldout_eval": self.heldout_eval,
            "accepted": self.accepted,
            "metadata": self.metadata,
        }


def optimize_harness_with_omni(
    *,
    spec_path: str | Path,
    tasks_path: str | Path,
    output_dir: str | Path,
    engine: str = "omni",
    continuation_engine: str = "gepa",
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    runtime: str | None = None,
    working_dir: str | Path = ".",
    sandbox_backend: str = "local",
    reflection_lm: str = "openai/gpt-5.1",
    optimizer_model: str = "claude-sonnet-4-6",
    optimizer_effort: str | None = None,
    max_evals: int = 20,
    explore_max_evals: int | None = None,
    max_token_cost: float | None = None,
    max_workers: int = 1,
    seed: int = 0,
    max_candidate_proposals: int | None = None,
    candidate_selection_strategy: str = "pareto",
    frontier_type: str = "hybrid",
    acceptance_criterion: str = "strict_improvement",
    cache_evaluation: bool = False,
    use_merge: bool = False,
    max_merge_invocations: int = 5,
    reflection_minibatch_size: int | None = None,
    agent_sandbox: bool = True,
    live: bool = False,
    force: bool = False,
) -> HarnessOmniOptimizationResult:
    """Optimize a complete HarnessSpec without changing the live source file."""
    if not live:
        raise ValueError("Harness Omni optimization requires --live")
    if engine not in SKILL_OPTIMIZER_ENGINES:
        raise ValueError(f"Unsupported harness optimizer engine: {engine}")

    source = Path(spec_path).expanduser().resolve()
    source_spec = load_harness_spec(source)
    # Optimize a self-contained, resolved spec so relative inheritance and
    # source-local fragments cannot break after the baseline is staged.
    source_data = harness_spec_to_dict(source_spec)
    source_data.pop("inherits", None)
    source_text = yaml.safe_dump(source_data, sort_keys=False)
    task_source = Path(tasks_path).expanduser().resolve()
    task_file = load_eval_tasks(task_source)
    tasks = list(task_file["tasks"])
    train_tasks, val_tasks, test_tasks = _optimization_splits(tasks)
    if not test_tasks:
        raise ValueError(
            "Harness Omni optimization requires at least one task with split: held-out"
        )

    out = Path(output_dir).expanduser().resolve()
    if out.exists() and any(out.iterdir()) and not force:
        raise FileExistsError(f"{out} already exists and is not empty; pass --force")
    if out.exists() and force:
        shutil.rmtree(out)
    baseline_dir = out / "baseline"
    staged_dir = out / "staged"
    eval_dir = out / "evals"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    staged_dir.mkdir(parents=True, exist_ok=True)
    eval_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = baseline_dir / "harness.yaml"
    baseline_path.write_text(source_text, encoding="utf-8")

    evaluator = _HarnessOmniEvaluator(
        baseline_spec_path=baseline_path,
        tasks_path=task_source,
        tasks=tasks,
        eval_dir=eval_dir,
        provider=provider,
        model=model,
        runtime=runtime,
        working_dir=Path(working_dir).expanduser().resolve(),
        sandbox_backend=sandbox_backend,
        live=live,
    )
    objective = (
        f"Optimize the complete SuperQode HarnessSpec `{source_spec.name}` while "
        "preserving its identity, safety boundaries, and previously passing behavior."
    )
    background = (
        "The candidate is a complete YAML HarnessSpec. Only edit surfaces permitted "
        "by the baseline optimization policy. Invalid, out-of-scope, protected, "
        "permission-widening, or check-weakening candidates receive score zero. "
        "Prefer narrow changes to context, workflow, model policy, and agent tools."
    )
    result = _run_modern_optimizer(
        engine=engine,
        continuation_engine=continuation_engine,
        seed_candidate=source_text,
        evaluator=evaluator.evaluate,
        dataset=train_tasks,
        valset=val_tasks,
        test_set=test_tasks,
        objective=objective,
        background=background,
        output_dir=out,
        max_evals=max_evals,
        explore_max_evals=explore_max_evals,
        max_token_cost=max_token_cost,
        reflection_lm=reflection_lm,
        optimizer_model=optimizer_model,
        optimizer_effort=optimizer_effort,
        agent_sandbox=agent_sandbox,
        max_workers=max_workers,
        seed=seed,
        max_candidate_proposals=max_candidate_proposals,
        candidate_selection_strategy=candidate_selection_strategy,
        frontier_type=frontier_type,
        acceptance_criterion=acceptance_criterion,
        cache_evaluation=cache_evaluation,
        use_merge=use_merge,
        max_merge_invocations=max_merge_invocations,
        reflection_minibatch_size=reflection_minibatch_size,
    )

    staged_path = staged_dir / "best_harness.yaml"
    staged_path.write_text(_best_skill_text(result), encoding="utf-8")
    load_harness_spec(staged_path)
    candidate_audit = audit_harness_candidate(
        base_spec_path=baseline_path,
        candidate_spec_path=staged_path,
        tasks_path=task_source,
        ledger_path=out / "candidate-ledger.jsonl",
        require_heldout=False,
        allow_ungated=True,
    )
    heldout_eval = asyncio.run(
        run_harness_eval(
            spec_paths=[baseline_path, staged_path],
            tasks_path=task_source,
            provider=provider,
            model=model,
            runtime=runtime,
            working_dir=Path(working_dir).expanduser().resolve(),
            sandbox_backend=sandbox_backend,
            live=True,
            eval_split="held-out",
        )
    )
    from .acceptance import heldout_acceptance

    heldout_gate = heldout_acceptance(heldout_eval)
    accepted = bool(candidate_audit.get("accepted") and heldout_gate["accepted"])
    heldout_gate["accepted"] = accepted
    candidate_audit = {
        **candidate_audit,
        "optimizer_policy_accepted": bool(candidate_audit.get("accepted")),
        "heldout_gate": heldout_gate,
        "accepted": accepted,
        "decision": "accepted" if accepted else "rejected",
    }
    record_candidate_audit(
        candidate_audit,
        ledger_path=out / "candidate-ledger.jsonl",
        notes="GEPA Omni final candidate after sealed held-out gate",
    )
    baseline_score = heldout_gate["baseline_score"]
    best_score = heldout_gate["candidate_score"]
    result_metadata = _result_metadata(result)
    total_evals = result_metadata.get(
        "omni_total_evals",
        getattr(result, "total_evals", None),
    )
    report_json = out / "report.json"
    report_md = out / "report.md"
    payload = HarnessOmniOptimizationResult(
        engine=engine,
        output_dir=out,
        baseline_spec_path=baseline_path,
        staged_spec_path=staged_path,
        report_json_path=report_json,
        report_md_path=report_md,
        baseline_score=baseline_score,
        best_score=best_score,
        total_evals=int(total_evals) if total_evals is not None else None,
        candidate_audit=candidate_audit,
        heldout_eval=heldout_eval,
        accepted=accepted,
        metadata={**result_metadata, "heldout_gate": heldout_gate},
    )
    report_json.write_text(json.dumps(payload.to_dict(), indent=2) + "\n", encoding="utf-8")
    report_md.write_text(render_harness_omni_result(payload) + "\n", encoding="utf-8")
    return payload


class _HarnessOmniEvaluator:
    def __init__(
        self,
        *,
        baseline_spec_path: Path,
        tasks_path: Path,
        tasks: list[dict[str, Any]],
        eval_dir: Path,
        provider: str,
        model: str,
        runtime: str | None,
        working_dir: Path,
        sandbox_backend: str,
        live: bool,
    ) -> None:
        self.baseline_spec_path = baseline_spec_path
        self.tasks_path = tasks_path
        self.tasks = tasks
        self.eval_dir = eval_dir
        self.provider = provider
        self.model = model
        self.runtime = runtime
        self.working_dir = working_dir
        self.sandbox_backend = sandbox_backend
        self.live = live
        self._lock = threading.Lock()
        self._counter = 0
        self._baseline_scores: dict[str, float] = {}
        self._baseline_text = baseline_spec_path.read_text(encoding="utf-8")

    def evaluate(
        self, candidate: str | dict[str, str], example: dict[str, Any]
    ) -> tuple[float, dict[str, Any]]:
        candidate_text = (
            str(next(iter(candidate.values()), ""))
            if isinstance(candidate, dict)
            else str(candidate)
        )
        with self._lock:
            self._counter += 1
            eval_id = self._counter
        task = self._task_by_id(str(example.get("id") or ""))
        task_id = str(task.get("id") or "")
        run_dir = self.eval_dir / f"eval-{eval_id:04d}-{_safe_name(task_id)}"
        run_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = run_dir / "harness.yaml"
        task_path = run_dir / "eval-tasks.yaml"
        candidate_path.write_text(candidate_text, encoding="utf-8")
        task_path.write_text(
            yaml.safe_dump(
                {"tasks": [task], "metadata": {"source": "gepa-harness-optimization"}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        try:
            load_harness_spec(candidate_path)
            audit = audit_harness_candidate(
                base_spec_path=self.baseline_spec_path,
                candidate_spec_path=candidate_path,
                tasks_path=self.tasks_path,
                ledger_path=self.eval_dir / "candidate-ledger.jsonl",
                require_heldout=False,
                allow_ungated=True,
            )
        except Exception as exc:  # noqa: BLE001
            return self._rejection(task, "invalid_candidate", [str(exc)])
        if not audit.get("accepted"):
            return self._rejection(
                task,
                "policy_rejected",
                [str(item.get("message") or item.get("code")) for item in audit["violations"]],
                audit=audit,
            )
        try:
            payload = asyncio.run(
                run_harness_eval(
                    spec_paths=[candidate_path],
                    tasks_path=task_path,
                    provider=self.provider,
                    model=self.model,
                    runtime=self.runtime,
                    working_dir=self.working_dir,
                    sandbox_backend=self.sandbox_backend,
                    live=self.live,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return self._rejection(task, "evaluation_exception", [str(exc)], audit=audit)

        variant = payload.get("variants", [{}])[0]
        task_result = (variant.get("tasks") or [{}])[0]
        score = float(task_result.get("score") or 0.0)
        if candidate_text == self._baseline_text:
            with self._lock:
                self._baseline_scores[task_id] = score
        baseline_score = self._baseline_scores.get(task_id)
        non_regression = 0.0 if baseline_score == 1.0 and score < baseline_score else 1.0
        usage = task_result.get("usage") or {}
        cost = float(usage.get("cost_usd") or 0.0)
        duration = float(task_result.get("duration_seconds") or 0.0)
        return score, {
            "Input": {"Task": task},
            "Generated Outputs": {
                "Status": task_result.get("status"),
                "Reason": task_result.get("reason"),
                "Content chars": task_result.get("content_chars"),
            },
            "Feedback": {
                "Score": score,
                "Baseline score": baseline_score,
                "Failure digest": task_result.get("failure_digest") or {},
                "Candidate audit": {
                    "changed_surfaces": audit.get("changed_surfaces"),
                    "warnings": audit.get("warnings"),
                },
                "Usage": usage,
                "Duration seconds": duration,
            },
            "scores": {
                "harness_score": score,
                "policy_compliance": 1.0,
                "non_regression": non_regression,
                "cost_efficiency": 1.0 / (1.0 + max(0.0, cost)),
                "latency_efficiency": 1.0 / (1.0 + max(0.0, duration)),
            },
        }

    def _rejection(
        self,
        task: dict[str, Any],
        status: str,
        errors: list[str],
        *,
        audit: dict[str, Any] | None = None,
    ) -> tuple[float, dict[str, Any]]:
        return 0.0, {
            "Input": {"Task": task},
            "Feedback": {"Status": status, "Errors": errors, "Candidate audit": audit or {}},
            "scores": {
                "harness_score": 0.0,
                "policy_compliance": 0.0,
                "non_regression": 0.0,
            },
        }

    def _task_by_id(self, task_id: str) -> dict[str, Any]:
        for task in self.tasks:
            if str(task.get("id") or "") == task_id:
                return task
        return dict(self.tasks[0])


def render_harness_omni_result(
    result: HarnessOmniOptimizationResult | dict[str, Any],
) -> str:
    data = result.to_dict() if isinstance(result, HarnessOmniOptimizationResult) else result
    metadata = data.get("metadata") or {}
    lines = [
        f"Harness Omni optimization: {data['engine']}",
        f"Output: {data['output_dir']}",
        f"Staged spec: {data['staged_spec_path']}",
        f"Score: {data.get('baseline_score')} -> {data.get('best_score')}",
        f"Optimizer evaluations: {data.get('total_evals')}",
        f"Optimizer cost: ${float(metadata.get('omni_total_cost') or metadata.get('total_cost') or 0.0):.6f}",
        f"Held-out gate: {'passed' if data.get('accepted') else 'failed'}",
        "The live HarnessSpec was not modified.",
        f"Report: {data['report_md_path']}",
    ]
    return "\n".join(lines)
