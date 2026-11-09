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
    (ACP usage updates, run end), then the sum of per-model-call reports.
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
            self.latest = normalize_usage(data) or self.latest
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
        if name in {"run_end", "run.completed"}:
            self.latest = found
        elif name in {"model_result", "model.completed"}:
            self.summed = _add(self.summed, found)

    def result(self, result: Any) -> dict | None:
        if isinstance(result, dict):
            reported = normalize_usage(result.get("usage"))
            if reported:
                return reported
        return self.latest or self.summed


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
