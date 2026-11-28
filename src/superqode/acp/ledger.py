"""Server-owned ACP history and atomic insertion/deduplication records."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .protocol import ProtocolError


class SessionLedger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(path, 0o600)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, cwd TEXT NOT NULL,
                metadata TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS insertions (
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                key TEXT NOT NULL, message_id TEXT NOT NULL, prompt TEXT NOT NULL,
                PRIMARY KEY(session_id,key));
            CREATE TABLE IF NOT EXISTS history (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                payload TEXT NOT NULL);
        """)

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def create(self, session_id: str, cwd: str, metadata: dict):
        with self.db:
            self.db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
                (session_id, cwd, json.dumps(metadata), self.now()),
            )

    def get(self, session_id: str):
        row = self.db.execute(
            "SELECT cwd,metadata,updated_at FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            raise ProtocolError(-32002, "Unknown session", {"sessionId": session_id})
        return {
            "sessionId": session_id,
            "cwd": row[0],
            "metadata": json.loads(row[1]),
            "updatedAt": row[2],
        }

    def list(self, cwd: str | None = None):
        rows = self.db.execute(
            "SELECT session_id,cwd,updated_at FROM sessions ORDER BY updated_at DESC,session_id"
        ).fetchall()
        return [
            {"sessionId": sid, "cwd": root, "updatedAt": updated}
            for sid, root, updated in rows
            if cwd is None or cwd == root
        ]

    def lookup(self, session_id: str, key: str):
        row = self.db.execute(
            "SELECT message_id,prompt FROM insertions WHERE session_id=? AND key=?",
            (session_id, key),
        ).fetchone()
        return {"messageId": row[0], "prompt": json.loads(row[1])} if row else None

    def insert(self, session_id: str, prompt: list, key: str | None):
        # One SQLite commit owns both the retained message and its key. A
        # second process observes the committed insertion rather than rerunning it.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if key is not None:
                old = self.lookup(session_id, key)
                if old:
                    if old["prompt"] != prompt:
                        raise ProtocolError(-32602, "Submission key was used with different input")
                    return old["messageId"], None
            identity = "msg-" + uuid.uuid4().hex
            update = {"sessionUpdate": "user_message", "messageId": identity, "content": prompt}
            self.db.execute(
                "INSERT INTO history(session_id,payload) VALUES (?,?)",
                (session_id, json.dumps(update)),
            )
            if key is not None:
                self.db.execute(
                    "INSERT INTO insertions VALUES (?,?,?,?)",
                    (session_id, key, identity, json.dumps(prompt)),
                )
            self.db.execute(
                "UPDATE sessions SET updated_at=? WHERE session_id=?", (self.now(), session_id)
            )
        return identity, update

    def append(self, session_id: str, update: dict):
        with self.db:
            self.db.execute(
                "INSERT INTO history(session_id,payload) VALUES (?,?)",
                (session_id, json.dumps(update)),
            )
            self.db.execute(
                "UPDATE sessions SET updated_at=? WHERE session_id=?", (self.now(), session_id)
            )

    def history(self, session_id: str):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT payload FROM history WHERE session_id=? ORDER BY sequence", (session_id,)
            )
        ]

    def configure(self, session_id: str, metadata: dict):
        with self.db:
            self.db.execute(
                "UPDATE sessions SET metadata=?,updated_at=? WHERE session_id=?",
                (json.dumps(metadata), self.now(), session_id),
            )

    def close(self):
        self.db.close()
