"""Explicit, retained inbox delivery within a recursive root's address space."""

from __future__ import annotations

import json
import time
from uuid import uuid4

from .delegation_store import DelegationStore


class AgentMailbox:
    def __init__(self, store: DelegationStore, root: str):
        self.store, self.root = store, root
        with store.transaction() as conn:
            conn.execute(
                "create table if not exists rlm_addresses(root text, agent text, parent text, primary key(root,agent))"
            )
            conn.execute(
                "create table if not exists rlm_address_aliases(root text, agent text, logical text, primary key(root,agent))"
            )
            conn.execute(
                "create table if not exists rlm_inbox(root text, id text, sender text, target text, body text, state text, observed real, primary key(root,id))"
            )

    def register(self, agent, parent="", logical=None):
        with self.store.transaction() as conn:
            conn.execute(
                "insert or ignore into rlm_addresses values (?,?,?)", (self.root, agent, parent)
            )
            if logical:
                conn.execute(
                    "insert into rlm_address_aliases values (?,?,?) on conflict(root,agent) do update set logical=excluded.logical",
                    (self.root, agent, logical),
                )
            else:
                conn.execute(
                    "insert or ignore into rlm_address_aliases values (?,?,?)",
                    (self.root, agent, agent),
                )

    def _canonical(self, conn, agent):
        row = conn.execute(
            "select logical from rlm_address_aliases where root=? and agent=?", (self.root, agent)
        ).fetchone()
        return row[0] if row else agent

    def send(self, sender, target, message, delivery_id=None):
        if not isinstance(message, str) or not message.strip() or len(message.encode()) > 20000:
            raise ValueError("Inbox messages require 1–20,000 bytes of text")
        identity = delivery_id or uuid4().hex
        if not isinstance(identity, str) or not identity or len(identity) > 512:
            raise ValueError("Invalid inbox delivery ID")
        with self.store.transaction() as conn:
            for agent in (sender, target):
                if not conn.execute(
                    "select 1 from rlm_addresses where root=? and agent=?", (self.root, agent)
                ).fetchone():
                    raise PermissionError("Inbox address does not belong to this recursive root")
            sender, target = self._canonical(conn, sender), self._canonical(conn, target)
            old = conn.execute(
                "select sender,target,body from rlm_inbox where root=? and id=?",
                (self.root, identity),
            ).fetchone()
            if old:
                if tuple(old) != (sender, target, message):
                    raise ValueError("Inbox delivery ID already identifies another message")
                return identity
            conn.execute(
                "insert into rlm_inbox values (?,?,?,?,?,'queued',?)",
                (self.root, identity, sender, target, message, time.time()),
            )
        return identity

    def read(self, target, limit=50):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("Inbox read limit must be between 1 and 100")
        with self.store.transaction() as conn:
            target = self._canonical(conn, target)
            rows = conn.execute(
                "select id,sender,body,observed from rlm_inbox where root=? and target=? and state='queued' order by observed limit ?",
                (self.root, target, limit),
            ).fetchall()
        return [{"id": r[0], "sender": r[1], "message": r[2], "observed_at": r[3]} for r in rows]

    def acknowledge(self, target, identity):
        with self.store.transaction() as conn:
            target = self._canonical(conn, target)
            changed = conn.execute(
                "update rlm_inbox set state='consumed' where root=? and target=? and id=?",
                (self.root, target, identity),
            ).rowcount
            if not changed:
                raise PermissionError("Inbox delivery belongs to another recipient")
        return identity

    def parent(self, agent):
        with self.store.transaction() as conn:
            agent = self._canonical(conn, agent)
            row = conn.execute(
                "select parent from rlm_addresses where root=? and agent=?", (self.root, agent)
            ).fetchone()
        return row[0] if row else ""
