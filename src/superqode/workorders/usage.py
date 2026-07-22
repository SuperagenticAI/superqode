"""Normalized usage accounting and budget policy for WorkOrders."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable

from .models import WorkArtifact, WorkOrder, WorkOrderTask, WorkTaskRole


RISK_LEVELS = ("low", "medium", "high", "critical")
_RISK_RANK = {name: index for index, name in enumerate(RISK_LEVELS)}


@dataclass(frozen=True)
class WorkOrderUsage:
    """Usage observed for one WorkOrder task attempt."""

    task_id: str
    attempt: int
    observed_at: float
    tokens_in: int | None = None
    tokens_out: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    cost_currency: str | None = None
    tool_calls: int | None = None
    iterations: int | None = None
    latency_ms: int | None = None
    provider: str = ""
    model: str = ""
    runtime: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkOrderUsage":
        return cls(
            task_id=str(data.get("task_id") or ""),
            attempt=max(0, int(data.get("attempt") or 0)),
            observed_at=float(data.get("observed_at") or time.time()),
            tokens_in=_optional_int(data.get("tokens_in")),
            tokens_out=_optional_int(data.get("tokens_out")),
            total_tokens=_optional_int(data.get("total_tokens")),
            cost_usd=_optional_float(data.get("cost_usd")),
            cost_currency=(
                str(data.get("cost_currency")) if data.get("cost_currency") else None
            ),
            tool_calls=_optional_int(data.get("tool_calls")),
            iterations=_optional_int(data.get("iterations")),
            latency_ms=_optional_int(data.get("latency_ms")),
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            runtime=str(data.get("runtime") or ""),
        )


@dataclass(frozen=True)
class WorkOrderUsageSummary:
    """Cumulative observed WorkOrder usage, including reporting coverage."""

    run_count: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0
    iterations: int = 0
    latency_ms: int = 0
    token_reports: int = 0
    cost_reports: int = 0
    tool_call_reports: int = 0
    currencies: tuple[str, ...] = ()

    @property
    def unknown_token_runs(self) -> int:
        return max(0, self.run_count - self.token_reports)

    @property
    def unknown_cost_runs(self) -> int:
        return max(0, self.run_count - self.cost_reports)

    @property
    def unknown_tool_call_runs(self) -> int:
        return max(0, self.run_count - self.tool_call_reports)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "cost_usd": round(self.cost_usd, 12),
            "unknown_token_runs": self.unknown_token_runs,
            "unknown_cost_runs": self.unknown_cost_runs,
            "unknown_tool_call_runs": self.unknown_tool_call_runs,
        }


@dataclass(frozen=True)
class WorkOrderPolicyViolation:
    """One explainable WorkOrder policy denial."""

    code: str
    phase: str
    message: str
    limit: int | float | str | None = None
    observed: int | float | str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkOrderPolicyDecision:
    """Allow or deny result from a WorkOrder policy phase."""

    phase: str
    allowed: bool
    violations: tuple[WorkOrderPolicyViolation, ...] = ()

    @property
    def reason(self) -> str:
        return "; ".join(item.message for item in self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "allowed": self.allowed,
            "reason": self.reason,
            "violations": [item.to_dict() for item in self.violations],
        }


def usage_from_result(
    result: dict[str, Any],
    *,
    task: WorkOrderTask,
    latency_ms: int | None = None,
) -> WorkOrderUsage:
    """Normalize one harness result dictionary into WorkOrder accounting."""
    nested = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    tokens_in = _first_int(result, nested, "tokens_in", "input_tokens", "prompt_tokens")
    tokens_out = _first_int(
        result, nested, "tokens_out", "output_tokens", "completion_tokens"
    )
    total_tokens = _first_int(result, nested, "total_tokens")
    if total_tokens is None and (tokens_in is not None or tokens_out is not None):
        total_tokens = int(tokens_in or 0) + int(tokens_out or 0)
    cost_usd = _first_float(result, nested, "cost_usd", "total_cost_usd", "cost")
    return WorkOrderUsage(
        task_id=task.task_id,
        attempt=task.attempts,
        observed_at=time.time(),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        cost_currency=str(
            result.get("cost_currency") or nested.get("cost_currency") or "USD"
        )
        if cost_usd is not None
        else None,
        tool_calls=_first_int(result, nested, "tool_calls", "tool_calls_made"),
        iterations=_first_int(result, nested, "iterations"),
        latency_ms=latency_ms
        if latency_ms is not None
        else _first_int(result, nested, "latency_ms"),
        provider=str(result.get("provider") or ""),
        model=str(result.get("model") or ""),
        runtime=str(result.get("runtime") or ""),
    )


def aggregate_usage(values: Iterable[WorkOrderUsage]) -> WorkOrderUsageSummary:
    rows = list(values)
    currencies = tuple(sorted({item.cost_currency for item in rows if item.cost_currency}))
    return WorkOrderUsageSummary(
        run_count=len(rows),
        tokens_in=sum(int(item.tokens_in or 0) for item in rows),
        tokens_out=sum(int(item.tokens_out or 0) for item in rows),
        total_tokens=sum(int(item.total_tokens or 0) for item in rows),
        cost_usd=sum(float(item.cost_usd or 0) for item in rows),
        tool_calls=sum(int(item.tool_calls or 0) for item in rows),
        iterations=sum(int(item.iterations or 0) for item in rows),
        latency_ms=sum(int(item.latency_ms or 0) for item in rows),
        token_reports=sum(item.total_tokens is not None for item in rows),
        cost_reports=sum(item.cost_usd is not None for item in rows),
        tool_call_reports=sum(item.tool_calls is not None for item in rows),
        currencies=currencies,
    )


def usage_from_artifacts(artifacts: Iterable[WorkArtifact]) -> WorkOrderUsageSummary:
    rows: list[WorkOrderUsage] = []
    for artifact in artifacts:
        if artifact.kind != "usage":
            continue
        payload = artifact.metadata.get("usage") or artifact.metadata
        if isinstance(payload, dict):
            rows.append(WorkOrderUsage.from_dict(payload))
    return aggregate_usage(rows)


def evaluate_work_order_policy(
    order: WorkOrder,
    *,
    phase: str,
    task: WorkOrderTask | None = None,
    now: float | None = None,
    usage: WorkOrderUsageSummary | None = None,
) -> WorkOrderPolicyDecision:
    """Evaluate an explainable admission or completion budget decision."""
    current_time = time.time() if now is None else now
    observed_usage = usage if usage is not None else usage_from_artifacts(order.artifacts)
    violations: list[WorkOrderPolicyViolation] = []
    budget = order.budget

    if budget.max_seconds is not None:
        elapsed = max(0.0, current_time - order.created_at)
        if elapsed >= budget.max_seconds:
            violations.append(
                WorkOrderPolicyViolation(
                    "time_exhausted",
                    phase,
                    f"elapsed time {elapsed:.1f}s reached the {budget.max_seconds}s limit",
                    budget.max_seconds,
                    round(elapsed, 3),
                )
            )

    _evaluate_reported_limit(
        violations,
        phase=phase,
        label="token",
        value=observed_usage.total_tokens,
        limit=budget.max_tokens,
        unknown=observed_usage.unknown_token_runs,
        run_count=observed_usage.run_count,
        completion=phase == "completion",
    )
    _evaluate_reported_limit(
        violations,
        phase=phase,
        label="cost",
        value=observed_usage.cost_usd,
        limit=budget.max_cost_usd,
        unknown=observed_usage.unknown_cost_runs,
        run_count=observed_usage.run_count,
        completion=phase == "completion",
    )
    _evaluate_reported_limit(
        violations,
        phase=phase,
        label="tool_call",
        value=observed_usage.tool_calls,
        limit=budget.max_tool_calls,
        unknown=observed_usage.unknown_tool_call_runs,
        run_count=observed_usage.run_count,
        completion=phase == "completion",
    )

    if task is not None and budget.max_risk:
        actual_risk = effective_task_risk(task)
        allowed_risk = normalize_risk(budget.max_risk)
        if _RISK_RANK[actual_risk] > _RISK_RANK[allowed_risk]:
            violations.append(
                WorkOrderPolicyViolation(
                    "risk_denied",
                    phase,
                    f"task risk {actual_risk} exceeds the {allowed_risk} limit",
                    allowed_risk,
                    actual_risk,
                )
            )

    return WorkOrderPolicyDecision(
        phase=phase,
        allowed=not violations,
        violations=tuple(violations),
    )


def project_usage(
    usage: WorkOrderUsageSummary,
    *,
    add_cost_usd: float = 0.0,
    add_tokens: int = 0,
    add_tool_calls: int = 0,
) -> WorkOrderUsageSummary:
    """Project counters for a read-only policy simulation."""
    return replace(
        usage,
        cost_usd=usage.cost_usd + max(0.0, float(add_cost_usd)),
        total_tokens=usage.total_tokens + max(0, int(add_tokens)),
        tool_calls=usage.tool_calls + max(0, int(add_tool_calls)),
    )


def effective_task_risk(task: WorkOrderTask) -> str:
    """Return declared risk, or a conservative role-based default."""
    if task.risk:
        return normalize_risk(task.risk)
    if task.role in {
        WorkTaskRole.INVESTIGATOR,
        WorkTaskRole.REVIEWER,
        WorkTaskRole.TESTER,
    }:
        return "low"
    return "medium"


def normalize_risk(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _RISK_RANK:
        raise ValueError(f"risk must be one of: {', '.join(RISK_LEVELS)}")
    return normalized


def _evaluate_reported_limit(
    violations: list[WorkOrderPolicyViolation],
    *,
    phase: str,
    label: str,
    value: int | float,
    limit: int | float | None,
    unknown: int,
    run_count: int,
    completion: bool,
) -> None:
    if limit is None:
        return
    if run_count and unknown:
        violations.append(
            WorkOrderPolicyViolation(
                f"{label}_usage_unreported",
                phase,
                f"{unknown} completed run(s) did not report {label.replace('_', ' ')} usage",
                limit,
                "unknown",
            )
        )
        return
    exhausted = value > limit if completion else value >= limit
    if exhausted:
        comparison = "exceeded" if completion and value > limit else "reached"
        violations.append(
            WorkOrderPolicyViolation(
                f"{label}_budget_exhausted",
                phase,
                f"observed {label.replace('_', ' ')} usage {value} {comparison} limit {limit}",
                limit,
                value,
            )
        )


def _first_int(*sources_and_keys: Any) -> int | None:
    sources = sources_and_keys[:2]
    keys = sources_and_keys[2:]
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value is not None:
                return int(value)
    return None


def _first_float(*sources_and_keys: Any) -> float | None:
    sources = sources_and_keys[:2]
    keys = sources_and_keys[2:]
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value is not None:
                return float(value)
    return None


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
