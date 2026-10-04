"""Integer task credits and skill entitlements, independent of signed keys.

Use one authoritative database shared by workers. Disconnects and ambiguous
execution keep their reservation until an operator reconciles it.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time


class CreditLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            conn.executescript("""
              create table if not exists a2a_accounts (
                customer text primary key, balance integer not null, reserved integer not null,
                skills text not null, expires real not null, max_parallel integer not null);
              create table if not exists a2a_credit_jobs (
                id text primary key, customer text not null, fingerprint text not null,
                credits integer not null, state text not null, charged integer, updated real not null);
              create table if not exists a2a_credit_audit (
                seq integer primary key autoincrement, customer text not null,
                job text not null, action text not null, data text not null, observed real not null);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def transaction(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma journal_mode=wal")
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

    def grant(self, customer, credits, *, skills, expires_at, max_parallel=1):
        if (
            not customer
            or isinstance(credits, bool)
            or not isinstance(credits, int)
            or credits < 0
            or not skills
            or expires_at <= time.time()
            or not 1 <= max_parallel <= 64
        ):
            raise ValueError(
                "Credits require a customer, integer allowance, skills, future expiry and bounded concurrency"
            )
        with self.transaction() as conn:
            conn.execute(
                "insert into a2a_accounts values (?,?,0,?,?,?) on conflict(customer) do update set balance=balance+excluded.balance,skills=excluded.skills,expires=excluded.expires,max_parallel=excluded.max_parallel",
                (customer, credits, json.dumps(list(skills)), expires_at, max_parallel),
            )
            conn.execute(
                "insert into a2a_credit_audit(customer,job,action,data,observed) values (?,?,'grant',?,?)",
                (
                    customer,
                    "",
                    json.dumps({"credits": credits, "skills": list(skills), "expires": expires_at}),
                    time.time(),
                ),
            )
        return self.account(customer)

    def account(self, customer):
        with self.transaction() as conn:
            row = conn.execute(
                "select * from a2a_accounts where customer=?", (customer,)
            ).fetchone()
            if row is None:
                raise PermissionError("No hosted service account")
            return {
                **dict(row),
                "skills": json.loads(row["skills"]),
                "available": row["balance"] - row["reserved"],
            }

    def reserve(self, customer, job, fingerprint, *, skill, credits):
        if isinstance(credits, bool) or not isinstance(credits, int) or credits <= 0:
            raise ValueError("A hosted task requires a positive integer credit tariff")
        with self.transaction() as conn:
            existing = conn.execute("select * from a2a_credit_jobs where id=?", (job,)).fetchone()
            if existing:
                if existing["customer"] != customer or existing["fingerprint"] != fingerprint:
                    raise PermissionError("Computational work ID belongs to another request")
                return dict(existing), False
            account = conn.execute(
                "select * from a2a_accounts where customer=?", (customer,)
            ).fetchone()
            if (
                account is None
                or account["expires"] <= time.time()
                or skill not in json.loads(account["skills"])
            ):
                raise PermissionError("Hosted skill entitlement is missing or expired")
            active = conn.execute(
                "select count(*) from a2a_credit_jobs where customer=? and state='reserved'",
                (customer,),
            ).fetchone()[0]
            if (
                active >= account["max_parallel"]
                or account["balance"] - account["reserved"] < credits
            ):
                raise PermissionError("Hosted credit or concurrency allowance exhausted")
            conn.execute(
                "update a2a_accounts set reserved=reserved+? where customer=?", (credits, customer)
            )
            conn.execute(
                "insert into a2a_credit_jobs values (?,?,?,?, 'reserved',NULL,?)",
                (job, customer, fingerprint, credits, time.time()),
            )
            return {"id": job, "customer": customer, "credits": credits, "state": "reserved"}, True

    def settle(self, customer, job, charged, *, reason="execution finished"):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Credit settlement requires an audit reason")
        with self.transaction() as conn:
            row = conn.execute(
                "select * from a2a_credit_jobs where id=? and customer=?", (job, customer)
            ).fetchone()
            if row is None:
                raise PermissionError("Unknown hosted reservation")
            if (
                isinstance(charged, bool)
                or not isinstance(charged, int)
                or not 0 <= charged <= row["credits"]
            ):
                raise ValueError("Settlement must fit the admitted integer tariff")
            if row["state"] == "settled":
                if row["charged"] != charged:
                    raise ValueError("Reservation already settled for a different amount")
                return False
            conn.execute(
                "update a2a_accounts set balance=balance-?,reserved=reserved-? where customer=?",
                (charged, row["credits"], customer),
            )
            conn.execute(
                "update a2a_credit_jobs set state='settled',charged=?,updated=? where id=?",
                (charged, time.time(), job),
            )
            conn.execute(
                "insert into a2a_credit_audit(customer,job,action,data,observed) values (?,?,'settle',?,?)",
                (customer, job, json.dumps({"charged": charged, "reason": reason}), time.time()),
            )
            return True
