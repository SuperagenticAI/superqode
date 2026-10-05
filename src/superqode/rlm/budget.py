"""A durable family-wide inference allowance and provider usage ledger.

Call admission is atomic across detached workers. Token and USD thresholds stop
new admissions once reported usage reaches a threshold; they are not prepaid
provider billing caps. Missing usage remains explicit, including interrupted
requests. Remote service credits are accounted separately by A2A admission.
"""

import asyncio
from dataclasses import dataclass
import math
from pathlib import Path
import sqlite3
import time
import os
from uuid import uuid4
from .commands import fingerprint


class BudgetBusyError(RuntimeError):
    """A live request must settle before another capped request is admitted."""


@dataclass(frozen=True)
class BudgetPolicy:
    max_calls: int = 0
    max_tokens: int = 0
    max_cost_usd: float = 0

    def __post_init__(self):
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v < 0
            for v in (self.max_calls, self.max_tokens)
        ):
            raise ValueError("RLM call and token limits must be nonnegative integers")
        if (
            isinstance(self.max_cost_usd, bool)
            or not math.isfinite(self.max_cost_usd)
            or self.max_cost_usd < 0
        ):
            raise ValueError("RLM USD threshold must be finite and nonnegative")

    @classmethod
    def from_config(cls, data=None):
        data = dict(data or {})
        for key in ("max_calls", "max_tokens"):
            raw = data.get(key, 0)
            if isinstance(raw, bool) or str(int(raw)) != str(raw):
                raise ValueError("RLM call and token limits must be nonnegative integers")
        values = cls(
            int(data.get("max_calls", 0)),
            int(data.get("max_tokens", 0)),
            float(data.get("max_cost_usd", 0)),
        )
        if min(values.max_calls, values.max_tokens, values.max_cost_usd) < 0 or not math.isfinite(
            values.max_cost_usd
        ):
            raise ValueError("RLM budget limits must be finite and nonnegative")
        return values

    def to_dict(self):
        return {
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
        }


class RLMBudget:
    def __init__(self, path: Path, policy: BudgetPolicy):
        self.path, self.policy = Path(path), policy
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, lane TEXT, owner TEXT, model TEXT, started REAL,
                state TEXT, input INTEGER DEFAULT 0, output INTEGER DEFAULT 0,
                cache_read INTEGER DEFAULT 0, cache_write INTEGER DEFAULT 0,
                tokens INTEGER DEFAULT 0, cost REAL DEFAULT 0,
                tokens_known INTEGER DEFAULT 0, cost_known INTEGER DEFAULT 0)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(calls)")}
            if "owner_pid" not in columns:
                db.execute("ALTER TABLE calls ADD COLUMN owner_pid INTEGER DEFAULT 0")
                db.execute("ALTER TABLE calls ADD COLUMN owner_identity TEXT DEFAULT ''")
            db.execute(
                "CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT)"
            )
            import json

            encoded = json.dumps(policy.to_dict(), sort_keys=True)
            db.execute("INSERT OR IGNORE INTO policy VALUES (1, ?)", (encoded,))
            if db.execute("SELECT value FROM policy WHERE id=1").fetchone()[0] != encoded:
                raise ValueError("Changing a shared RLM budget requires a new session")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def admit(self, lane, owner, model):
        identity = "call-" + uuid4().hex
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT COUNT(*) calls, COALESCE(SUM(tokens),0) tokens,
                COALESCE(SUM(cost),0) cost,
                COALESCE(SUM(state != 'active' AND tokens_known=0),0) unknown_tokens,
                COALESCE(SUM(state != 'active' AND cost_known=0),0) unknown_cost FROM calls""").fetchone()
            policy = self.policy
            if policy.max_calls and row["calls"] >= policy.max_calls:
                raise RuntimeError("Shared RLM model-call allowance exhausted")
            if policy.max_tokens and (row["tokens"] >= policy.max_tokens or row["unknown_tokens"]):
                raise RuntimeError("Shared RLM token threshold reached or usage unavailable")
            if policy.max_cost_usd and (row["cost"] >= policy.max_cost_usd or row["unknown_cost"]):
                raise RuntimeError("Shared RLM USD threshold reached or pricing unavailable")
            # With spend thresholds, admit one unsettled request at a time to
            # avoid unbounded concurrent overshoot; wrapped live calls wait. A crashed request remains
            # active and requires explicit accounting reconciliation.
            if policy.max_tokens or policy.max_cost_usd:
                active = db.execute(
                    "SELECT owner_pid,owner_identity FROM calls WHERE state='active' LIMIT 1"
                ).fetchone()
                if active:
                    if active[0] == os.getpid() or (
                        active[1] and fingerprint(active[0]) == active[1]
                    ):
                        raise BudgetBusyError("Another RLM inference request has unsettled usage")
                    raise RuntimeError(
                        "Interrupted RLM inference has unsettled usage; reconcile before continuing"
                    )
            db.execute(
                "INSERT INTO calls (id,lane,owner,model,started,state) VALUES (?,?,?,?,?,'active')",
                (identity, lane, owner, model, time.time()),
            )
            db.execute(
                "UPDATE calls SET owner_pid=?,owner_identity=? WHERE id=?",
                (os.getpid(), fingerprint(os.getpid()), identity),
            )
        return identity

    def finish(self, identity, message=None, *, failed=False):
        usage = getattr(message, "usage", None)

        def count(key):
            return max(0, int(getattr(usage, key, 0) or 0))

        tokens = count("total_tokens") or count("input") + count("output") + count(
            "cache_read"
        ) + count("cache_write")
        cost = max(0, float(getattr(getattr(usage, "cost", None), "total", 0) or 0))
        if not math.isfinite(cost):
            cost = 0
        # PiPy currently represents missing price and free usage with the same
        # zero. Do not turn that ambiguity into a claim of free inference.
        with self._db() as db:
            db.execute(
                """UPDATE calls SET state=?,input=?,output=?,cache_read=?,cache_write=?,
                tokens=?,cost=?,tokens_known=?,cost_known=? WHERE id=? AND state='active'""",
                (
                    "failed" if failed else "complete",
                    count("input"),
                    count("output"),
                    count("cache_read"),
                    count("cache_write"),
                    tokens,
                    cost,
                    int(tokens > 0),
                    int(cost > 0),
                    identity,
                ),
            )

    def snapshot(self, *, unsettled_offset=0, unsettled_limit=50):
        with self._db() as db:
            rows = db.execute("""SELECT lane, COUNT(*) calls, SUM(tokens) tokens, SUM(cost) cost_usd,
                SUM(input) input_tokens, SUM(output) output_tokens,
                SUM(cache_read) cache_read_tokens, SUM(cache_write) cache_write_tokens,
                SUM(tokens_known=0) unknown_token_calls, SUM(cost_known=0) unknown_cost_calls,
                SUM(state='active') active_calls, SUM(state='failed') failures
                FROM calls GROUP BY lane ORDER BY lane""").fetchall()
            unresolved_count = db.execute(
                "SELECT COUNT(*) FROM calls WHERE state='active' OR tokens_known=0 OR cost_known=0"
            ).fetchone()[0]
            unsettled = [
                dict(r)
                for r in db.execute(
                    "SELECT id,lane,owner,model,started,state,tokens_known,cost_known FROM calls WHERE state='active' OR tokens_known=0 OR cost_known=0 ORDER BY state='active' DESC,started DESC LIMIT ? OFFSET ?",
                    (max(1, min(200, int(unsettled_limit))), max(0, int(unsettled_offset))),
                )
            ]
        lanes = {row["lane"]: {k: row[k] for k in row.keys() if k != "lane"} for row in rows}
        keys = (
            next(iter(lanes.values())).keys()
            if lanes
            else (
                "calls",
                "tokens",
                "cost_usd",
                "unknown_token_calls",
                "unknown_cost_calls",
                "active_calls",
            )
        )
        return {
            "policy": self.policy.to_dict(),
            "lanes": lanes,
            "total": {k: sum(lane[k] for lane in lanes.values()) for k in keys},
            "unsettled": unsettled,
            "unsettled_count": unresolved_count,
        }

    def wrap(self, source_fn, *, lane, owner):
        async def stream(model, context, options):
            try:
                while True:
                    try:
                        identity = self.admit(lane, owner, f"{model.provider}/{model.id}")
                        break
                    except BudgetBusyError:
                        # Cancellation before admission spends no allowance.
                        await asyncio.sleep(0.05)
            except RuntimeError as error:
                from superqode.pipy.messages import AssistantMessage
                from superqode.pipy.provider_events import AssistantErrorEvent

                yield AssistantErrorEvent(
                    reason="error",
                    error=AssistantMessage(
                        model=model.id,
                        provider=model.provider,
                        api=model.api,
                        stop_reason="error",
                        error_message=str(error),
                    ),
                )
                return
            terminal = False
            try:
                source = source_fn(model, context, options)
                if asyncio.iscoroutine(source):
                    source = await source
                async for event in source:
                    kind = getattr(event, "type", "")
                    if kind in {"done", "error"}:
                        self.finish(
                            identity,
                            getattr(event, "message" if kind == "done" else "error", None),
                            failed=kind == "error",
                        )
                        terminal = True
                    yield event
            finally:
                if not terminal:
                    self.finish(identity, failed=True)

        return stream

    def reconcile(self, identity, *, tokens, cost_usd, reason):
        tokens, cost_usd = int(tokens), float(cost_usd)
        if tokens < 0 or cost_usd < 0 or not math.isfinite(cost_usd) or not str(reason).strip():
            raise ValueError(
                "Accounting reconciliation needs nonnegative usage and a verification reason"
            )
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,tokens_known,cost_known,owner_pid,owner_identity FROM calls WHERE id=?",
                (identity,),
            ).fetchone()
            if row is None or (row[0] != "active" and row[1] and row[2]):
                raise ValueError("Only unsettled or unknown usage can be reconciled")
            if row[0] == "active" and (
                row[3] == os.getpid() or (row[4] and fingerprint(row[3]) == row[4])
            ):
                raise ValueError(
                    "A live request must finish or be stopped before usage reconciliation"
                )
            db.execute(
                "UPDATE calls SET state='reconciled',tokens=?,cost=?,tokens_known=1,cost_known=1 WHERE id=?",
                (tokens, cost_usd, identity),
            )
            db.execute("CREATE TABLE IF NOT EXISTS reconciliation (id TEXT, reason TEXT, at REAL)")
            db.execute(
                "INSERT INTO reconciliation VALUES (?,?,?)", (identity, str(reason), time.time())
            )


def usage_delta(before, after):
    lanes = {}
    for name, values in after["lanes"].items():
        previous = before["lanes"].get(name, {})
        lanes[name] = {key: value - previous.get(key, 0) for key, value in values.items()}
    keys = next(iter(lanes.values())).keys() if lanes else after["total"].keys()
    return {"lanes": lanes, "total": {key: sum(v[key] for v in lanes.values()) for key in keys}}


def budget_lines(snapshot):
    total = snapshot["total"]
    lines = [
        f"family     {total['calls']} calls, {total['tokens']} reported tokens, ${total['cost_usd']:.4f} known cost"
    ]
    for lane, usage in snapshot["lanes"].items():
        lines.append(
            f"{lane:<10} {usage['calls']} calls, {usage['tokens']} reported tokens, ${usage['cost_usd']:.4f} known cost"
        )
    lines.append(
        f"unknown    {total['unknown_token_calls']} token reports, {total['unknown_cost_calls']} cost reports; {total['active_calls']} unsettled calls"
    )
    policy = snapshot["policy"]
    lines.append(
        f"limits     calls={policy['max_calls'] or 'unlimited'}, reported tokens={policy['max_tokens'] or 'unlimited'}, reported USD={policy['max_cost_usd'] or 'unlimited'}"
    )
    lines.append(
        "Token/USD thresholds stop new calls after reported spend; the current request can cross a threshold. A2A credits are separate."
    )
    return lines
