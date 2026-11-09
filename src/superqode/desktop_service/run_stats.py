"""Per-run statistics for the desktop app: timing and reported token usage.

Only values that a runtime actually reported are kept. Missing fields stay
absent so the app never shows invented numbers.
"""

from __future__ import annotations

import math
import time
from typing import Any

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted", "regressed"})

_IN = ("tokens_in", "input_tokens", "prompt_tokens", "inputTokens", "promptTokens")
# Cumulative usage events: ACP usage_update / prompt usage (the ACP worker
# forwards the client's merged running totals) and run end summaries.
_CUMULATIVE = {"usage", "usage_update", "run_end", "run.completed"}
# One model call each; these add up.
_PER_CALL = {"model_result", "model.completed"}
_OUT = (
    "tokens_out",
    "output_tokens",
    "completion_tokens",
    "outputTokens",
    "completionTokens",
)
_TOTAL = ("total_tokens", "totalTokens")
_COST = ("cost_usd", "total_cost", "totalCost", "cost")


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _first(raw: dict, keys: tuple[str, ...]) -> float | int | None:
    for key in keys:
        value = _number(raw.get(key))
        if value is not None:
            return value
    return None


def normalize_usage(raw: Any) -> dict | None:
    """Map provider, harness and ACP usage shapes to one small dictionary."""
    if not isinstance(raw, dict):
        return None
    tokens_in = _first(raw, _IN)
    tokens_out = _first(raw, _OUT)
    total = _first(raw, _TOTAL)
    cost = _first(raw, _COST)
    currency = raw.get("cost_currency") or raw.get("currency")
    nested = raw.get("cost")
    if isinstance(nested, dict):
        amount = _number(nested.get("amount"))
        if amount is not None:
            cost = amount
            currency = nested.get("currency") or currency
    if total is None and tokens_in is not None and tokens_out is not None:
        total = tokens_in + tokens_out
    usage = {
        "tokens_in": int(tokens_in) if tokens_in is not None else None,
        "tokens_out": int(tokens_out) if tokens_out is not None else None,
        "total_tokens": int(total) if total is not None else None,
        "cost": float(cost) if cost is not None else None,
        "cost_currency": str(currency) if isinstance(currency, str) and currency else None,
    }
    usage = {key: value for key, value in usage.items() if value is not None}
    if usage.keys() <= {"cost_currency"}:
        return None
    return usage


class UsageCollector:
    """Collect usage from a run's event stream.

    Priority: usage in the terminal result, then the latest cumulative report
    (ACP usage updates, run end) completed by the ACP result stats, then the
    sum of per-model-call reports. Cumulative reports replace each other and
    are never added, so running totals are not double counted.
    """

    def __init__(self) -> None:
        self.latest: dict | None = None
        self.summed: dict | None = None

    def observe(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        data = event.get("data")
        if not isinstance(data, dict):
            return
        if kind == "usage":
            self._cumulative(normalize_usage(data))
            return
        if kind != "harness_event":
            return
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return
        name = data.get("event")
        found = normalize_usage(payload.get("usage")) or normalize_usage(payload)
        if not found:
            return
        if name in _CUMULATIVE:
            self._cumulative(found)
        elif name in _PER_CALL:
            self.summed = _add(self.summed, found)

    def _cumulative(self, found: dict | None) -> None:
        if not found:
            return
        # A later running total wins per field. Fields it omits (for example a
        # context-only update without tokens) keep the earlier value.
        self.latest = {**(self.latest or {}), **found}

    def result(self, result: Any) -> dict | None:
        stats = None
        if isinstance(result, dict):
            reported = normalize_usage(result.get("usage"))
            if reported:
                return reported
            stats = acp_stats_usage(result.get("stats"))
        if self.latest or stats:
            # Same running totals from two places: fill gaps, never add.
            merged = {**(stats or {}), **(self.latest or {})}
            if (
                "total_tokens" not in (self.latest or {})
                and {"tokens_in", "tokens_out"} <= merged.keys()
            ):
                merged["total_tokens"] = merged["tokens_in"] + merged["tokens_out"]
            return merged
        return self.summed


def acp_stats_usage(stats: Any) -> dict | None:
    """Usage from an ACP result's stats. Zero means not reported there."""
    if not isinstance(stats, dict):
        return None
    tokens_in = _number(stats.get("prompt_tokens"))
    tokens_out = _number(stats.get("completion_tokens"))
    cost = _number(stats.get("cost"))
    raw = {
        "tokens_in": tokens_in or None,
        "tokens_out": tokens_out or None,
        "cost": cost or None,
    }
    return normalize_usage({key: value for key, value in raw.items() if value is not None})


def _add(left: dict | None, right: dict) -> dict:
    if not left:
        return dict(right)
    merged = dict(left)
    for key in ("tokens_in", "tokens_out", "total_tokens", "cost"):
        if key in right:
            merged[key] = merged.get(key, 0) + right[key]
    if right.get("cost_currency"):
        merged["cost_currency"] = right["cost_currency"]
    return merged


def ensure_timing_table(db) -> None:
    # A separate table keeps the jobs schema unchanged, so older app versions
    # can still open this state folder.
    db.execute(
        "CREATE TABLE IF NOT EXISTS job_timing(job TEXT PRIMARY KEY, started REAL, finished REAL)"
    )


def timing(service, row: dict) -> dict:
    """started_at and finished_at for a job row, falling back for older runs."""
    stored = service._all("SELECT started,finished FROM job_timing WHERE job=?", (row["id"],))
    started = stored[0]["started"] if stored else None
    finished = stored[0]["finished"] if stored else None
    if started is None:
        started = row.get("created")
    if finished is None and row.get("status") in TERMINAL_STATUSES:
        finished = row.get("updated")
    return {"started_at": started, "finished_at": finished}


def now() -> float:
    return time.time()
