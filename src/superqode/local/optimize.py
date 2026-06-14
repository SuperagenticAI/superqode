"""Role-aware local model optimization for agentic coding workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .bench import BenchResult, list_endpoint_models, run_agentic_bench
from .repo import RepoProfile

DEFAULT_ROLES = ("planner", "implementer", "reviewer", "utility")


@dataclass(frozen=True)
class RoleRecommendation:
    role: str
    model: str
    endpoint: str
    score: float
    reason: str


@dataclass(frozen=True)
class OptimizationReport:
    results: tuple[BenchResult, ...]
    recommendations: tuple[RoleRecommendation, ...]
    notes: tuple[str, ...] = ()
    repo_profile: RepoProfile | None = None


def discover_targets(
    endpoint: str | None,
    models: Iterable[str],
) -> list[tuple[str, str]]:
    """Build endpoint/model targets for an optimization run."""
    requested = list(models)
    if endpoint:
        ids = requested or list_endpoint_models(endpoint)[:1]
        return [(endpoint, model) for model in ids]

    from .engines import detect_engines

    targets: list[tuple[str, str]] = []
    for status in detect_engines().values():
        if not status.running or not status.endpoint:
            continue
        wanted = requested or list_endpoint_models(status.endpoint)[:1]
        targets.extend((status.endpoint, model) for model in wanted)
    return targets


def run_optimization(
    targets: Iterable[tuple[str, str]],
    *,
    roles: Iterable[str] = DEFAULT_ROLES,
    max_tokens: int = 384,
    api_key: str = "",
    repo_profile: RepoProfile | None = None,
) -> OptimizationReport:
    """Run agentic probes and recommend the best model for each workflow role."""
    results = tuple(
        run_agentic_bench(endpoint, model, max_tokens=max_tokens, api_key=api_key)
        for endpoint, model in targets
    )
    return recommend_roles(results, roles=roles, repo_profile=repo_profile)


def recommend_roles(
    results: Iterable[BenchResult],
    *,
    roles: Iterable[str] = DEFAULT_ROLES,
    repo_profile: RepoProfile | None = None,
) -> OptimizationReport:
    """Score completed bench results for workflow roles."""
    bench_results = tuple(results)
    usable = [item for item in bench_results if item.ok]
    notes: list[str] = []
    if not usable:
        return OptimizationReport(
            results=bench_results,
            recommendations=(),
            notes=("No usable local model results; start an engine or pass --endpoint/--model.",),
            repo_profile=repo_profile,
        )

    recommendations: list[RoleRecommendation] = []
    for role in roles:
        normalized = role.strip().lower()
        if not normalized:
            continue
        ranked = sorted(
            usable,
            key=lambda result: _role_score(result, normalized, repo_profile),
            reverse=True,
        )
        best = ranked[0]
        score = round(_role_score(best, normalized, repo_profile), 1)
        recommendations.append(
            RoleRecommendation(
                role=normalized,
                model=best.model,
                endpoint=best.endpoint,
                score=score,
                reason=_role_reason(best, normalized, repo_profile),
            )
        )
        if best.agentic_score is not None and best.agentic_score < 75:
            notes.append(
                f"{normalized}: best model scored {best.agentic_score:.0f}% on agentic probes; "
                "keep strict tool-call repair enabled."
            )
    if repo_profile is not None:
        notes.append(
            "Repo-aware scoring used "
            f"{repo_profile.recommended_model_size} model guidance, "
            f"{repo_profile.recommended_context_tokens} token context, "
            f"and {repo_profile.workflow_shape} workflow shape."
        )

    return OptimizationReport(
        results=bench_results,
        recommendations=tuple(recommendations),
        notes=tuple(dict.fromkeys(notes)),
        repo_profile=repo_profile,
    )


def render_optimization(report: OptimizationReport) -> str:
    lines = ["SuperQode local optimizer (role routing)", ""]
    if report.recommendations:
        lines.append(f"{'role':<14} {'model':<36} {'score':>7}  reason")
        for rec in report.recommendations:
            lines.append(f"{rec.role:<14} {rec.model:<36} {rec.score:>6.1f}  {rec.reason}")
    else:
        lines.append("No recommendations available.")
    if report.notes:
        lines.append("")
        for note in report.notes:
            lines.append(f"- {note}")
    lines.append("")
    lines.append("Scores combine agentic control probes, TTFT, decode speed, and role fit.")
    if report.repo_profile is not None:
        lines.append("Repo-aware scoring biases context-heavy roles toward stronger candidates.")
    return "\n".join(lines)


def optimization_harness_yaml(report: OptimizationReport, *, name: str = "local-optimized") -> str:
    """Generate a chain harness with per-agent model routing from recommendations."""
    recs = list(report.recommendations)
    if not recs:
        raise ValueError("cannot generate a harness without recommendations")
    lines = [
        f"name: {name}",
        "flavor: coding",
        "workflow:",
        "  mode: chain",
        "  config:",
        "    max_retries: 1",
        "    continue_on_error: false",
    ]
    if report.repo_profile is not None:
        lines.extend(
            [
                "model_policy:",
                f"  context_window: {report.repo_profile.recommended_context_tokens}",
                "metadata:",
                f"  repo_model_size: {report.repo_profile.recommended_model_size}",
                f"  repo_context_tokens: {report.repo_profile.recommended_context_tokens}",
                f"  repo_workflow_shape: {report.repo_profile.workflow_shape}",
            ]
        )
    lines.append("agents:")
    role_text = {
        "planner": "Plan the implementation with the cheapest fast model that preserves context.",
        "implementer": "Implement the requested code change and use tools precisely.",
        "reviewer": "Review the diff, call out risks, and verify tests.",
        "utility": "Handle summaries, grading, memory extraction, and small support tasks.",
    }
    for rec in recs:
        lines.extend(
            [
                f"  - id: {rec.role}",
                f"    role: {role_text.get(rec.role, rec.role)}",
                f"    model: {rec.model}",
                "    config:",
                "      runtime: builtin",
                f"      endpoint: {rec.endpoint}",
            ]
        )
    return "\n".join(lines) + "\n"


def _role_score(result: BenchResult, role: str, repo_profile: RepoProfile | None = None) -> float:
    agentic = float(result.agentic_score or 0.0)
    speed = _speed_score(result)
    tool = _bool_score(result.tool_call_success)
    edit = _bool_score(result.edit_format_success)
    shell = _bool_score(result.shell_call_success)
    context = _bool_score(result.context_recall_success)

    if role in {"utility", "summarizer", "grader"}:
        score = (speed * 0.85) + (agentic * 0.05) + (context * 0.10)
        return _apply_repo_bias(score, result, role, repo_profile)
    if role in {"planner", "architect"}:
        score = (agentic * 0.45) + (context * 0.25) + (tool * 0.15) + (speed * 0.15)
        return _apply_repo_bias(score, result, role, repo_profile)
    if role in {"reviewer", "critic", "tester"}:
        score = (
            (agentic * 0.40) + (context * 0.25) + (edit * 0.15) + (shell * 0.10) + (speed * 0.10)
        )
        return _apply_repo_bias(score, result, role, repo_profile)
    score = (agentic * 0.50) + (tool * 0.15) + (edit * 0.15) + (shell * 0.10) + (speed * 0.10)
    return _apply_repo_bias(score, result, role, repo_profile)


def _apply_repo_bias(
    score: float,
    result: BenchResult,
    role: str,
    repo_profile: RepoProfile | None,
) -> float:
    if repo_profile is None:
        return score
    adjusted = score
    context_heavy = repo_profile.recommended_context_tokens >= 32768
    large_repo = repo_profile.recommended_model_size in {"medium-large", "large"}
    coder_named = _model_looks_coder(result.model)
    if context_heavy and role not in {"utility", "summarizer", "grader"}:
        adjusted += 8.0 if result.context_recall_success else -12.0
    if large_repo and role in {"planner", "architect", "reviewer", "critic", "tester"}:
        adjusted += 5.0 if coder_named else -4.0
    if role in {"implementer", "coder"} and coder_named:
        adjusted += 4.0
    if repo_profile.workflow_shape != "single" and role == "utility":
        adjusted -= 3.0
    return max(0.0, min(100.0, adjusted))


def _speed_score(result: BenchResult) -> float:
    ttft = result.ttft_s if result.ttft_s is not None else 30.0
    decode = result.decode_tps if result.decode_tps is not None else 0.0
    ttft_score = max(0.0, min(100.0, 100.0 - (ttft * 12.5)))
    decode_score = max(0.0, min(100.0, decode * 2.0))
    return (ttft_score * 0.7) + (decode_score * 0.3)


def _bool_score(value: bool | None) -> float:
    return 100.0 if value is True else 0.0


def _model_looks_coder(model: str) -> bool:
    lowered = model.lower()
    return any(token in lowered for token in ("coder", "code", "devstral", "ds4", "deepseek"))


def _role_reason(
    result: BenchResult,
    role: str,
    repo_profile: RepoProfile | None = None,
) -> str:
    speed = _speed_score(result)
    agentic = result.agentic_score
    repo = ""
    if repo_profile is not None:
        repo = f", repo {repo_profile.recommended_model_size}/{repo_profile.workflow_shape}"
    if role == "utility":
        return (
            "fastest useful route: "
            f"speed {speed:.0f}, agentic {agentic if agentic is not None else 'n/a'}{repo}"
        )
    return (
        "best role fit: "
        f"agentic {agentic if agentic is not None else 'n/a'}, speed {speed:.0f}{repo}"
    )


__all__ = [
    "DEFAULT_ROLES",
    "OptimizationReport",
    "RoleRecommendation",
    "discover_targets",
    "optimization_harness_yaml",
    "recommend_roles",
    "render_optimization",
    "run_optimization",
]
