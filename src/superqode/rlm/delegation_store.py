"""Durable outbound intents, results and root-wide reservations in SQLite."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

TERMINAL = frozenset({"completed", "failed", "rejected", "canceled"})


class DelegationStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            conn.executescript("""
                create table if not exists rlm_delegations (
                    id text primary key, root text not null, owner text not null,
                    request_id text not null, fingerprint text not null,
                    state text not null, credits integer not null, payload text not null,
                    unique(root, owner, request_id));
                create table if not exists rlm_delegation_events (
                    seq integer primary key autoincrement, root text not null,
                    id text not null, type text not null, observed real not null, data text not null);
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

    def admit(self, root, owner, request_id, fingerprint, policy, peer, record):
        with self.transaction() as conn:
            old = conn.execute(
                "select * from rlm_delegations where root=? and owner=? and request_id=?",
                (root, owner, request_id),
            ).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("Delegation request ID already identifies different work")
                return json.loads(old["payload"]), False
            count, active, credits = conn.execute(
                "select count(*), coalesce(sum(state not in ('completed','failed','rejected','canceled')),0), coalesce(sum(credits),0) from rlm_delegations where root=?",
                (root,),
            ).fetchone()
            if count >= policy.max_tasks or active >= policy.max_parallel:
                raise PermissionError("Root A2A task/concurrency allowance exhausted")
            if credits + peer.credits > policy.max_hosted_credits and peer.hosted:
                raise PermissionError("Root hosted credit allowance exhausted")
            identifier = f"delegation-{uuid4().hex}"
            value = {
                **record,
                "id": identifier,
                "root": root,
                "owner": owner,
                "state": "admitting",
                "message_id": uuid4().hex,
                "observed_at": time.time(),
                "revision": 0,
                "request_id": request_id,
                "credits": peer.credits if peer.hosted else 0,
                "usage": None,
                "usage_source": "unknown",
                "result": None,
            }
            conn.execute(
                "insert into rlm_delegations values (?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    root,
                    owner,
                    request_id,
                    fingerprint,
                    "admitting",
                    value["credits"],
                    json.dumps(value),
                ),
            )
            self._event(conn, value, "admitted")
            return value, True

    def get(self, root, owner, identifier):
        with self.transaction() as conn:
            row = conn.execute(
                "select payload from rlm_delegations where root=? and owner=? and id=?",
                (root, owner, identifier),
            ).fetchone()
            if row is None:
                raise PermissionError("Delegation handle does not belong to this session")
            return json.loads(row[0])

    def update(self, record, kind, **changes):
        with self.transaction() as conn:
            row = conn.execute(
                "select payload from rlm_delegations where id=? and root=? and owner=?",
                (record["id"], record["root"], record["owner"]),
            ).fetchone()
            current = json.loads(row[0]) if row else None
            if current is None or current["revision"] != record["revision"]:
                raise ValueError("Stale delegation revision cannot commit")
            value = {
                **current,
                **changes,
                "revision": current["revision"] + 1,
                "observed_at": time.time(),
            }
            conn.execute(
                "update rlm_delegations set state=?,payload=? where id=?",
                (value["state"], json.dumps(value), value["id"]),
            )
            self._event(conn, value, kind)
            return value

    def records(self, root, owner=None):
        with self.transaction() as conn:
            rows = conn.execute(
                "select payload from rlm_delegations where root=?"
                + (" and owner=?" if owner is not None else "")
                + " order by rowid",
                (root, owner) if owner is not None else (root,),
            ).fetchall()
            return [json.loads(r[0]) for r in rows]

    def events(self, root, after=0):
        with self.transaction() as conn:
            rows = conn.execute(
                "select seq,id,type,observed,data from rlm_delegation_events where root=? and seq>? order by seq",
                (root, after),
            ).fetchall()
            return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    @staticmethod
    def _event(conn, value, kind):
        # Progress is published only after this transaction. No input, private
        # results, credentials or endpoint authentication appears in events.
        conn.execute(
            "insert into rlm_delegation_events(root,id,type,observed,data) values (?,?,?,?,?)",
            (
                value["root"],
                value["id"],
                kind,
                time.time(),
                json.dumps(
                    {
                        "state": value["state"],
                        "peer": value.get("peer"),
                        "owner": value["owner"],
                        "required": value.get("required", True),
                        "credits": value["credits"],
                    }
                ),
            ),
        )
