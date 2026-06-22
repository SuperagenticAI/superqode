"""SkillOpt-style optimization workspaces for SuperQode skills."""

from __future__ import annotations

import asyncio
import difflib
import json
import shlex
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from superqode.harness.eval import load_eval_tasks
from superqode.harness.loader import harness_spec_to_dict, load_harness_spec
from superqode.skills import Skill, SkillsLoader


@dataclass(frozen=True)
class SkillOptExport:
    """Files created for a SkillOpt-style skill optimization workspace."""

    project_dir: Path
    baseline_dir: Path
    skill_path: Path
    baseline_skill_path: Path
    tasks_path: Path
    instructions_path: Path
    harness_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "baseline_dir": str(self.baseline_dir),
            "skill_path": str(self.skill_path),
            "baseline_skill_path": str(self.baseline_skill_path),
            "tasks_path": str(self.tasks_path),
            "instructions_path": str(self.instructions_path),
            "harness_path": str(self.harness_path) if self.harness_path else None,
        }


@dataclass(frozen=True)
class SkillOptimizationResult:
    """Result of a staged skill optimization run."""

    engine: str
    skill_name: str
    output_dir: Path
    baseline_skill_path: Path
    staged_skill_path: Path
    report_json_path: Path
    report_md_path: Path
    baseline_score: float | None
    best_score: float | None
    total_metric_calls: int | None
    check: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "skill_name": self.skill_name,
            "output_dir": str(self.output_dir),
            "baseline_skill_path": str(self.baseline_skill_path),
            "staged_skill_path": str(self.staged_skill_path),
            "report_json_path": str(self.report_json_path),
            "report_md_path": str(self.report_md_path),
            "baseline_score": self.baseline_score,
            "best_score": self.best_score,
            "total_metric_calls": self.total_metric_calls,
            "check": self.check,
        }


def export_skillopt_project(
    *,
    skill: str,
    tasks_path: str | Path,
    project_dir: str | Path,
    root: str | Path = ".",
    harness_path: str | Path | None = None,
    max_edits: int = 4,
    live_eval: bool = False,
    force: bool = False,
) -> SkillOptExport:
    """Create a SkillOpt-style optimization workspace for one markdown skill."""

    root_path = Path(root).expanduser().resolve()
    source_skill = _resolve_skill(skill, root_path)
    source_tasks = Path(tasks_path).expanduser().resolve()
    load_eval_tasks(source_tasks)

    project = Path(project_dir).expanduser().resolve()
    if project.exists() and any(project.iterdir()) and not force:
        raise FileExistsError(f"{project} already exists and is not empty; pass --force")

    if project.exists() and force:
        shutil.rmtree(project)

    baseline = project / "baseline"
    skill_rel = _skill_relative_path(source_skill, root_path)
    skill_target = baseline / skill_rel
    skill_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_skill.path or source_skill.source_path, skill_target)

    tasks_target = baseline / "eval-tasks.yaml"
    shutil.copyfile(source_tasks, tasks_target)

    harness_target: Path | None = None
    if harness_path:
        source_harness = Path(harness_path).expanduser().resolve()
        harness_target = baseline / "harness.yaml"
        shutil.copyfile(source_harness, harness_target)

    snapshot = baseline / ".skillopt" / "baseline_skill.md"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(skill_target, snapshot)

    instructions = baseline / "AGENTS.md"
    instructions.write_text(
        _optimizer_instructions(
            skill_name=source_skill.name,
            skill_rel=skill_rel,
            max_edits=max_edits,
            has_harness=bool(harness_target),
        ),
        encoding="utf-8",
    )
    (baseline / "README.md").write_text(
        _readme(skill_name=source_skill.name, skill_rel=skill_rel, max_edits=max_edits),
        encoding="utf-8",
    )

    (project / "tasks.json").write_text(
        json.dumps(
            _optimization_tasks(
                skill_rel=skill_rel,
                max_edits=max_edits,
                has_harness=bool(harness_target),
                live_eval=live_eval,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (project / "skillopt.json").write_text(
        json.dumps(
            {
                "objective": (
                    f"Improve the SuperQode skill `{source_skill.name}` using "
                    "bounded text edits and accept only changes that preserve or "
                    "improve held-out eval performance."
                ),
                "baseline_dir": "baseline",
                "tasks_file": "tasks.json",
                "skill_path": str(skill_rel),
                "max_edits": int(max_edits),
                "gate": (
                    "Run live harness eval on eval-tasks.yaml before adopting the edited skill."
                    if live_eval
                    else "Dry eval checks the contract; run live harness eval before adoption."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return SkillOptExport(
        project_dir=project,
        baseline_dir=baseline,
        skill_path=skill_target,
        baseline_skill_path=snapshot,
        tasks_path=project / "tasks.json",
        instructions_path=instructions,
        harness_path=harness_target,
    )


def optimize_skill_with_gepa(
    *,
    skill: str,
    harness_path: str | Path,
    tasks_path: str | Path,
    output_dir: str | Path,
    root: str | Path = ".",
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    runtime: str | None = None,
    working_dir: str | Path = ".",
    sandbox_backend: str = "local",
    reflection_lm: str = "openai/gpt-5.1",
    max_metric_calls: int = 20,
    max_candidate_proposals: int | None = None,
    max_reflection_cost: float | None = None,
    reflection_minibatch_size: int | None = None,
    max_workers: int = 1,
    seed: int = 0,
    max_edits: int = 8,
    candidate_selection_strategy: str = "pareto",
    frontier_type: str = "hybrid",
    acceptance_criterion: str = "strict_improvement",
    cache_evaluation: bool = False,
    use_merge: bool = False,
    max_merge_invocations: int = 5,
    live: bool = False,
    force: bool = False,
    optimizer: Callable[..., Any] | None = None,
    allow_dry_run: bool = False,
) -> SkillOptimizationResult:
    """Optimize one SuperQode skill with GEPA and stage the best candidate."""

    if not live and not allow_dry_run:
        raise ValueError("GEPA skill optimization requires --live so eval tasks produce scores.")

    root_path = Path(root).expanduser().resolve()
    source_skill = _resolve_skill(skill, root_path)
    source_skill_path = source_skill.path or source_skill.source_path
    source_text = source_skill_path.read_text(encoding="utf-8")

    task_file = load_eval_tasks(tasks_path)
    tasks = list(task_file["tasks"])
    if not tasks:
        raise ValueError("GEPA optimization requires at least one eval task")

    harness_source = Path(harness_path).expanduser().resolve()
    # Validate early; candidate evals will write temporary derived specs.
    load_harness_spec(harness_source)

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

    baseline_skill_path = baseline_dir / "SKILL.md"
    baseline_skill_path.write_text(source_text, encoding="utf-8")

    evaluator = _GEPASkillEvaluator(
        source_harness_path=harness_source,
        tasks=tasks,
        eval_dir=eval_dir,
        provider=provider,
        model=model,
        runtime=runtime,
        working_dir=Path(working_dir).expanduser().resolve(),
        sandbox_backend=sandbox_backend,
        live=live,
        skill_name=source_skill.name,
    )

    if optimizer is None:
        try:
            from gepa.optimize_anything import (  # type: ignore[import-not-found]
                EngineConfig,
                GEPAConfig,
                MergeConfig,
                ReflectionConfig,
                optimize_anything,
            )
        except ImportError as exc:
            raise RuntimeError(
                "GEPA is not installed. Install it with `uv tool install 'superqode[optimization]'` "
                "or `pip install gepa`."
            ) from exc

        config = GEPAConfig(
            engine=EngineConfig(
                run_dir=str(out / "gepa-run"),
                max_metric_calls=int(max_metric_calls),
                max_candidate_proposals=max_candidate_proposals,
                max_reflection_cost=max_reflection_cost,
                max_workers=max(1, int(max_workers)),
                parallel=max_workers > 1,
                seed=int(seed),
                display_progress_bar=False,
                candidate_selection_strategy=candidate_selection_strategy,
                frontier_type=frontier_type,
                acceptance_criterion=acceptance_criterion,
                cache_evaluation=cache_evaluation,
            ),
            reflection=ReflectionConfig(
                reflection_lm=reflection_lm,
                reflection_minibatch_size=reflection_minibatch_size,
                module_selector="all",
            ),
            merge=MergeConfig(max_merge_invocations=max_merge_invocations) if use_merge else None,
            refiner=None,
        )
        optimizer = optimize_anything
    else:
        config = None

    objective = (
        f"Optimize the SuperQode skill `{source_skill.name}` so it improves held-out "
        "harness eval score without changing the skill identity or adding unsafe behavior."
    )
    background = (
        "The candidate is a complete markdown SKILL.md file. Preserve YAML frontmatter, "
        "keep instructions concise, and prefer concrete reusable developer workflow rules. "
        "The evaluator stages each candidate into a temporary SuperQode harness and returns "
        "task-level pass/fail feedback plus failure reasons as Actionable Side Information."
    )

    kwargs: dict[str, Any] = {
        "seed_candidate": {"skill": source_text},
        "evaluator": evaluator.evaluate,
        "dataset": tasks,
        "valset": tasks,
        "objective": objective,
        "background": background,
    }
    if config is not None:
        kwargs["config"] = config
    result = optimizer(**kwargs)

    best_candidate = _best_skill_text(result)
    staged_skill_path = staged_dir / "best_skill.md"
    staged_skill_path.write_text(best_candidate, encoding="utf-8")
    check = check_skill_candidate(
        baseline_path=baseline_skill_path,
        candidate_path=staged_skill_path,
        max_edits=max_edits,
    )

    baseline_score, best_score = _gepa_scores(result)
    total_metric_calls = getattr(result, "total_metric_calls", None)
    report_json_path = out / "report.json"
    report_md_path = out / "report.md"
    opt_result = SkillOptimizationResult(
        engine="gepa",
        skill_name=source_skill.name,
        output_dir=out,
        baseline_skill_path=baseline_skill_path,
        staged_skill_path=staged_skill_path,
        report_json_path=report_json_path,
        report_md_path=report_md_path,
        baseline_score=baseline_score,
        best_score=best_score,
        total_metric_calls=int(total_metric_calls) if total_metric_calls is not None else None,
        check=check,
    )
    report_json_path.write_text(json.dumps(opt_result.to_dict(), indent=2) + "\n", encoding="utf-8")
    report_md_path.write_text(render_skill_optimization_report(opt_result) + "\n", encoding="utf-8")
    return opt_result


class _GEPASkillEvaluator:
    def __init__(
        self,
        *,
        source_harness_path: Path,
        tasks: list[dict[str, Any]],
        eval_dir: Path,
        provider: str,
        model: str,
        runtime: str | None,
        working_dir: Path,
        sandbox_backend: str,
        live: bool,
        skill_name: str,
    ) -> None:
        self.source_harness_path = source_harness_path
        self.tasks = tasks
        self.eval_dir = eval_dir
        self.provider = provider
        self.model = model
        self.runtime = runtime
        self.working_dir = working_dir
        self.sandbox_backend = sandbox_backend
        self.live = live
        self.skill_name = skill_name
        self._lock = threading.Lock()
        self._counter = 0

    def evaluate(
        self, candidate: dict[str, str], example: dict[str, Any]
    ) -> tuple[float, dict[str, Any]]:
        skill_text = candidate.get("skill", "")
        with self._lock:
            self._counter += 1
            eval_id = self._counter
        task = self._task_by_id(str(example.get("id") or ""))
        run_dir = self.eval_dir / f"eval-{eval_id:04d}-{_safe_name(str(task.get('id') or 'task'))}"
        run_dir.mkdir(parents=True, exist_ok=True)
        spec_path = run_dir / "harness.yaml"
        task_path = run_dir / "eval-tasks.yaml"
        _write_candidate_harness(
            source_harness_path=self.source_harness_path,
            output_path=spec_path,
            skill_name=self.skill_name,
            skill_text=skill_text,
        )
        task_path.write_text(
            yaml.safe_dump(
                {"tasks": [task], "metadata": {"source": "gepa-skill-optimization"}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        try:
            from superqode.harness.eval import run_harness_eval

            payload = asyncio.run(
                run_harness_eval(
                    spec_paths=[spec_path],
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
            return 0.0, {
                "Input": {"Task": task},
                "Feedback": {"Status": "exception", "Error": str(exc)},
                "scores": {"harness_score": 0.0},
            }

        variant = payload.get("variants", [{}])[0]
        task_result = (variant.get("tasks") or [{}])[0]
        score = float(task_result.get("score") or 0.0)
        return score, {
            "Input": {
                "Task ID": task.get("id"),
                "Prompt": str(task.get("prompt") or "")[:1000],
                "Expect Contains": task.get("expect_contains"),
            },
            "Generated Outputs": {
                "Status": task_result.get("status"),
                "Reason": task_result.get("reason"),
                "Content chars": task_result.get("content_chars"),
            },
            "Feedback": {
                "Harness status": payload.get("status"),
                "Task status": task_result.get("status"),
                "Failure digest": task_result.get("failure_digest") or {},
                "Score": score,
            },
            "scores": {"harness_score": score},
        }

    def _task_by_id(self, task_id: str) -> dict[str, Any]:
        for task in self.tasks:
            if str(task.get("id") or "") == task_id:
                return task
        return dict(self.tasks[0])


def check_skill_candidate(
    *,
    baseline_path: str | Path,
    candidate_path: str | Path,
    max_edits: int = 4,
    max_bytes: int = 50_000,
) -> dict[str, Any]:
    """Validate a candidate skill for bounded SkillOpt-style edits."""

    baseline = Path(baseline_path).expanduser()
    candidate = Path(candidate_path).expanduser()
    errors: list[str] = []
    if not baseline.is_file():
        errors.append(f"baseline skill not found: {baseline}")
    if not candidate.is_file():
        errors.append(f"candidate skill not found: {candidate}")
    if errors:
        return {"ok": False, "errors": errors}

    baseline_text = baseline.read_text(encoding="utf-8")
    candidate_text = candidate.read_text(encoding="utf-8")
    if not candidate_text.strip():
        errors.append("candidate skill is empty")
    if len(candidate_text.encode("utf-8")) > max_bytes:
        errors.append(f"candidate skill exceeds {max_bytes} bytes")

    baseline_meta = _frontmatter(baseline_text)
    candidate_meta = _frontmatter(candidate_text)
    if baseline_meta.get("name") and candidate_meta.get("name") != baseline_meta.get("name"):
        errors.append("candidate changed the skill frontmatter name")

    edit_count = _diff_hunks(baseline_text, candidate_text)
    if edit_count > int(max_edits):
        errors.append(f"candidate uses {edit_count} diff hunks; max_edits is {max_edits}")

    return {
        "ok": not errors,
        "errors": errors,
        "edit_hunks": edit_count,
        "max_edits": int(max_edits),
        "candidate_bytes": len(candidate_text.encode("utf-8")),
        "candidate_name": candidate_meta.get("name") or "",
    }


def render_skillopt_export(payload: SkillOptExport | dict[str, Any]) -> str:
    data = payload.to_dict() if isinstance(payload, SkillOptExport) else payload
    lines = [
        f"SkillOpt workspace: {data['project_dir']}",
        f"Baseline: {data['baseline_dir']}",
        f"Skill: {data['skill_path']}",
        f"Tasks: {data['tasks_path']}",
        f"Instructions: {data['instructions_path']}",
    ]
    if data.get("harness_path"):
        lines.append(f"Harness: {data['harness_path']}")
    lines.append("")
    lines.append("Next: run an optimizer against this workspace, then gate with harness eval.")
    return "\n".join(lines)


def render_skillopt_check(payload: dict[str, Any]) -> str:
    status = "passed" if payload.get("ok") else "failed"
    lines = [
        f"SkillOpt check: {status}",
        f"Edit hunks: {payload.get('edit_hunks', 0)}/{payload.get('max_edits', 0)}",
    ]
    for error in payload.get("errors", []):
        lines.append(f"- {error}")
    return "\n".join(lines)


def render_skill_optimization_result(payload: SkillOptimizationResult | dict[str, Any]) -> str:
    data = payload.to_dict() if isinstance(payload, SkillOptimizationResult) else payload
    lines = [
        f"Skill optimization: {data['engine']}",
        f"Skill: {data['skill_name']}",
        f"Output: {data['output_dir']}",
        f"Staged skill: {data['staged_skill_path']}",
    ]
    if data.get("baseline_score") is not None or data.get("best_score") is not None:
        lines.append(f"Score: {data.get('baseline_score')} -> {data.get('best_score')}")
    if data.get("total_metric_calls") is not None:
        lines.append(f"Metric calls: {data['total_metric_calls']}")
    check = data.get("check") or {}
    lines.append(f"Bounded edit check: {'passed' if check.get('ok') else 'failed'}")
    if check.get("errors"):
        lines.extend(f"- {error}" for error in check["errors"])
    lines.append(f"Report: {data['report_md_path']}")
    return "\n".join(lines)


def render_skill_optimization_report(result: SkillOptimizationResult) -> str:
    data = result.to_dict()
    return "\n".join(
        [
            f"# SuperQode Skill Optimization: {result.skill_name}",
            "",
            f"- Engine: {result.engine}",
            f"- Baseline score: {result.baseline_score}",
            f"- Best score: {result.best_score}",
            f"- Metric calls: {result.total_metric_calls}",
            f"- Baseline skill: `{result.baseline_skill_path}`",
            f"- Staged skill: `{result.staged_skill_path}`",
            f"- Bounded edit check: {'passed' if result.check.get('ok') else 'failed'}",
            "",
            "The staged skill is a proposal. Review it and run held-out evals before copying it over the live skill.",
            "",
            "## Check",
            "",
            "```json",
            json.dumps(data["check"], indent=2),
            "```",
        ]
    )


def _resolve_skill(value: str, root: Path) -> Skill:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_file():
        loader = SkillsLoader(root)
        parsed = loader._parse_skill(candidate)  # noqa: SLF001 - central parser for skill files
        if not parsed:
            raise ValueError(f"Could not parse skill file: {candidate}")
        return _attach_source_path(parsed, candidate)

    loader = SkillsLoader(root)
    skill = loader.get(value)
    if not skill or not skill.path:
        raise ValueError(f"Skill not found by name or path: {value}")
    return _attach_source_path(skill, skill.path)


def _attach_source_path(skill: Skill, path: Path) -> Skill:
    object.__setattr__(skill, "source_path", path)
    return skill


def _skill_relative_path(skill: Skill, root: Path) -> Path:
    path = skill.path or skill.source_path
    try:
        return path.resolve().relative_to(root)
    except ValueError:
        return Path(".agents") / "skills" / _slug(skill.name) / "SKILL.md"


def _slug(value: str) -> str:
    chars = [ch.lower() if ch.isalnum() else "-" for ch in value.strip()]
    return "-".join(part for part in "".join(chars).split("-") if part) or "skill"


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[4:end]) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _diff_hunks(left: str, right: str) -> int:
    left_lines = left.splitlines()
    right_lines = right.splitlines()
    matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines)
    return sum(1 for tag, *_ in matcher.get_opcodes() if tag != "equal")


def _optimization_tasks(
    *,
    skill_rel: Path,
    max_edits: int,
    has_harness: bool,
    live_eval: bool,
) -> list[dict[str, Any]]:
    skill_arg = shlex.quote(str(skill_rel))
    tasks: list[dict[str, Any]] = [
        {
            "id": "skill-file-present",
            "type": "file_phrase",
            "path": str(skill_rel),
            "weight": 1.0,
            "required_phrases": ["---", "#"],
        },
        {
            "id": "bounded-skill-edit",
            "type": "command",
            "weight": 2.0,
            "command": (
                "superqode skillopt check "
                f"--baseline .skillopt/baseline_skill.md --candidate {skill_arg} "
                f"--max-edits {int(max_edits)} --json"
            ),
            "expect_exit_code": 0,
        },
    ]
    if has_harness:
        live_flag = " --live" if live_eval else ""
        tasks.append(
            {
                "id": "held-out-eval-contract",
                "type": "command",
                "weight": 3.0,
                "command": (
                    "superqode harness eval --spec harness.yaml "
                    f"--tasks eval-tasks.yaml --json{live_flag}"
                ),
                "expect_exit_code": 0,
            }
        )
    return tasks


def _optimizer_instructions(
    *,
    skill_name: str,
    skill_rel: Path,
    max_edits: int,
    has_harness: bool,
) -> str:
    eval_line = (
        "- Run `superqode harness eval --spec harness.yaml --tasks eval-tasks.yaml --json` "
        "and keep the candidate only when held-out score improves without regressions."
        if has_harness
        else "- No harness was exported; produce only a staged skill edit and require downstream eval before adoption."
    )
    return f"""# SkillOpt-Style Skill Optimization

You are optimizing the SuperQode skill `{skill_name}`.

Edit only `{skill_rel}`. Treat the markdown skill as trainable text state for a
frozen agent. Use the eval tasks as rollout evidence, propose bounded
add/delete/replace edits, and preserve behavior that already works.

Rules:
- Keep the frontmatter `name` unchanged.
- Use no more than {int(max_edits)} coherent diff hunks.
- Prefer concrete operating rules over broad rewrites.
- Do not edit `.skillopt/baseline_skill.md`.
{eval_line}
- Before finishing, run `superqode skillopt check --baseline .skillopt/baseline_skill.md --candidate {skill_rel} --max-edits {int(max_edits)}`.
"""


def _readme(*, skill_name: str, skill_rel: Path, max_edits: int) -> str:
    return f"""# SuperQode SkillOpt Workspace: {skill_name}

This workspace adapts the SkillOpt loop to a SuperQode markdown skill:

1. Roll out or inspect failures from `eval-tasks.yaml`.
2. Reflect on recurring failures and successes.
3. Edit `{skill_rel}` with a bounded text budget.
4. Gate the candidate with SuperQode evals before adoption.

The bounded edit check is:

```bash
superqode skillopt check --baseline .skillopt/baseline_skill.md --candidate {skill_rel} --max-edits {int(max_edits)}
```
"""


def _best_skill_text(result: Any) -> str:
    best = getattr(result, "best_candidate", result)
    if isinstance(best, dict):
        return str(best.get("skill") or next(iter(best.values()), ""))
    return str(best)


def _gepa_scores(result: Any) -> tuple[float | None, float | None]:
    scores = getattr(result, "val_aggregate_scores", None)
    if not scores:
        return None, None
    baseline = float(scores[0]) if scores else None
    best_idx = int(getattr(result, "best_idx", 0) or 0)
    best = float(scores[best_idx]) if 0 <= best_idx < len(scores) else None
    return baseline, best


def _write_candidate_harness(
    *,
    source_harness_path: Path,
    output_path: Path,
    skill_name: str,
    skill_text: str,
) -> None:
    from dataclasses import replace

    spec = load_harness_spec(source_harness_path)
    injection = (
        f"\n\n## Candidate Skill Under GEPA Optimization: {skill_name}\n\n{skill_text.strip()}\n"
    )
    if spec.agents:
        first = spec.agents[0]
        agents = (
            replace(
                first,
                system_prompt=((first.system_prompt or "").rstrip() + injection).strip(),
            ),
            *spec.agents[1:],
        )
        spec = replace(spec, agents=agents)
    else:
        from superqode.harness.spec import AgentSpec

        spec = replace(
            spec,
            agents=(
                AgentSpec(
                    id="candidate",
                    role="candidate",
                    system_prompt=injection.strip(),
                ),
            ),
        )
    output_path.write_text(
        yaml.safe_dump(harness_spec_to_dict(spec), sort_keys=False), encoding="utf-8"
    )


def _safe_name(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    return "-".join(part for part in cleaned.split("-") if part)[:80] or "task"
