"""Root-wide semantic call allowances shared by recursive worker processes."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


class SubcallLedger:
    def __init__(self, path, root):
        self.path, self.root = Path(path), root
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            conn.execute(
                "create table if not exists rlm_subcalls(root text, number integer, state text, usage text, primary key(root,number))"
            )
        self.path.chmod(0o600)

    @contextmanager
    def transaction(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("pragma synchronous=full")
        conn.execute("begin immediate")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def reserve(self, count, policy):
        with self.transaction() as conn:
            rows = conn.execute(
                "select number,usage from rlm_subcalls where root=?", (self.root,)
            ).fetchall()
            used = max((r[0] for r in rows), default=0)
            tokens = sum(json.loads(r[1]).get("total_tokens", 0) for r in rows)
            if policy.max_calls and used + count > policy.max_calls:
                raise ValueError("Root semantic subcall allowance exhausted")
            if policy.token_budget and tokens >= policy.token_budget:
                raise ValueError("Root observed semantic token budget exhausted")
            for number in range(used + 1, used + count + 1):
                conn.execute(
                    "insert into rlm_subcalls values (?,?,'reserved','{}')", (self.root, number)
                )
            return used + 1

    def seed(self, usage):
        """Import released root accounting once, before the first admission."""
        calls = int(usage.get("calls") or 0)
        if not calls:
            return
        with self.transaction() as conn:
            if conn.execute(
                "select 1 from rlm_subcalls where root=? limit 1", (self.root,)
            ).fetchone():
                return
            for number in range(1, calls + 1):
                conn.execute(
                    "insert into rlm_subcalls values (?,?,'completed',?)",
                    (self.root, number, json.dumps(usage if number == calls else {})),
                )

    def claim(self, number, maximum):
        with self.transaction() as conn:
            count = conn.execute(
                "select count(*) from rlm_subcalls where root=? and state='running'", (self.root,)
            ).fetchone()[0]
            if count >= maximum:
                return False
            changed = conn.execute(
                "update rlm_subcalls set state='running' where root=? and number=? and state='reserved'",
                (self.root, number),
            ).rowcount
            if not changed:
                raise ValueError("Semantic call cannot be dispatched twice")
            return True

    def finish(self, number, usage, failed=False):
        with self.transaction() as conn:
            conn.execute(
                "update rlm_subcalls set state=?,usage=? where root=? and number=?",
                ("failed" if failed else "completed", json.dumps(usage), self.root, number),
            )

    def snapshot(self):
        with self.transaction() as conn:
            rows = conn.execute(
                "select state,usage from rlm_subcalls where root=?", (self.root,)
            ).fetchall()
        usage = {
            "calls": len(rows),
            "failures": sum(r[0] == "failed" for r in rows),
            "unresolved": sum(r[0] in {"reserved", "running"} for r in rows),
            "unknown_usage_calls": sum(not json.loads(r[1]) for r in rows),
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
        }
        for _, raw in rows:
            value = json.loads(raw)
            for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd"):
                usage[key] += value.get(key, 0)
        return usage
