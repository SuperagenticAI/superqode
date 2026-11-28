"""Client-owned submission recovery. Keys never appear in agent history or logs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3


class SubmissionOutbox:
    def __init__(self, path: Path | None = None, *, scope: str = ""):
        self.path, self.scope = path, scope
        self.entries: dict[str, dict] = {}
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            os.chmod(path, 0o600)
            with sqlite3.connect(path) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS acp_outbox (scope TEXT, key TEXT, payload TEXT NOT NULL, PRIMARY KEY(scope,key))"
                )
                self.entries = {
                    key: json.loads(raw)
                    for key, raw in db.execute(
                        "SELECT key,payload FROM acp_outbox WHERE scope=?", (scope,)
                    )
                }

    def put(self, key: str, entry: dict) -> None:
        self.entries[key] = entry
        if self.path is not None:
            with sqlite3.connect(self.path) as db:
                db.execute(
                    "INSERT OR REPLACE INTO acp_outbox VALUES (?,?,?)",
                    (self.scope, key, json.dumps(entry)),
                )

    def pending(self) -> dict[str, dict]:
        return {
            key: dict(value)
            for key, value in self.entries.items()
            if value.get("status") != "completed"
        }
