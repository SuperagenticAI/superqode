"""Role-aware local model optimization for agentic coding workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .bench import BenchResult, list_endpoint_models, run_agentic_bench

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
) -> OptimizationReport:
    """Run agentic probes and recommend the best model for each workflow role."""
    results = tuple(
        run_agentic_bench(endpoint, model, max_tokens=max_tokens, api_key=api_key)
        for endpoint, model in targets
    )
    return recommend_roles(results, roles=roles)


def recommend_roles(
    results: Iterable[BenchResult],
    *,
    roles: Iterable[str] = DEFAULT_ROLES,
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
        )

    recommendations: list[RoleRecommendation] = []
    for role in roles:
        normalized = role.strip().lower()
        if not normalized:
            continue
        ranked = sorted(
            usable,
            key=lambda result: _role_score(result, normalized),
            reverse=True,
        )
        best = ranked[0]
        score = round(_role_score(best, normalized), 1)
        recommendations.append(
            RoleRecommendation(
                role=normalized,
                model=best.model,
                endpoint=best.endpoint,
                score=score,
                reason=_role_reason(best, normalized),
            )
        )
        if best.agentic_score is not None and best.agentic_score < 75:
            notes.append(
                f"{normalized}: best model scored {best.agentic_score:.0f}% on agentic probes; "
                "keep strict tool-call repair enabled."
            )

    return OptimizationReport(
        results=bench_results,
        recommendations=tuple(recommendations),
        notes=tuple(dict.fromkeys(notes)),
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
        "agents:",
    ]
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


def _role_score(result: BenchResult, role: str) -> float:
    agentic = float(result.agentic_score or 0.0)
    speed = _speed_score(result)
    tool = _bool_score(result.tool_call_success)
    edit = _bool_score(result.edit_format_success)
    shell = _bool_score(result.shell_call_success)
    context = _bool_score(result.context_recall_success)

    if role in {"utility", "summarizer", "grader"}:
        return (speed * 0.85) + (agentic * 0.05) + (context * 0.10)
    if role in {"planner", "architect"}:
        return (agentic * 0.45) + (context * 0.25) + (tool * 0.15) + (speed * 0.15)
    if role in {"reviewer", "critic", "tester"}:
        return (agentic * 0.40) + (context * 0.25) + (edit * 0.15) + (shell * 0.10) + (speed * 0.10)
    return (agentic * 0.50) + (tool * 0.15) + (edit * 0.15) + (shell * 0.10) + (speed * 0.10)


def _speed_score(result: BenchResult) -> float:
    ttft = result.ttft_s if result.ttft_s is not None else 30.0
    decode = result.decode_tps if result.decode_tps is not None else 0.0
    ttft_score = max(0.0, min(100.0, 100.0 - (ttft * 12.5)))
    decode_score = max(0.0, min(100.0, decode * 2.0))
    return (ttft_score * 0.7) + (decode_score * 0.3)


def _bool_score(value: bool | None) -> float:
    return 100.0 if value is True else 0.0


def _role_reason(result: BenchResult, role: str) -> str:
    speed = _speed_score(result)
    agentic = result.agentic_score
    if role == "utility":
        return f"fastest useful route: speed {speed:.0f}, agentic {agentic if agentic is not None else 'n/a'}"
    return f"best role fit: agentic {agentic if agentic is not None else 'n/a'}, speed {speed:.0f}"


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
