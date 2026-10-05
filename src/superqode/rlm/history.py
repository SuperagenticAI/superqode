"""Branch-scoped history reads and durable selective observations.

The original append-only conversation stays authoritative. Projection only
changes the copy sent to a provider, preserving message roles and tool pairs.
"""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3

from superqode.pipy.messages import AssistantMessage, TextContent, ToolResultMessage, UserMessage


def message_text(message):
    text = str(getattr(message, "text", "") or "")
    if isinstance(message, AssistantMessage):
        thinking = str(getattr(message, "thinking_text", "") or "")
        if thinking:
            text += "\n<thinking>\n" + thinking + "\n</thinking>"
        for call in message.tool_calls:
            text += "\n" + json.dumps(
                {"tool_call_id": call.id, "tool": call.name, "arguments": call.arguments},
                ensure_ascii=False,
            )
    return text


class RLMHistory:
    def __init__(self, session, path: Path, *, allow_read=True):
        self.session = session
        self.path = path
        self.allow_read = allow_read
        self.live_messages = []
        self.live_leaf = None
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )

    def _db(self):
        return sqlite3.connect(self.path, timeout=30)

    def bind_profile(self, profile):
        encoded = json.dumps(profile.to_dict(), sort_keys=True)
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT)"
            )
            db.execute("INSERT OR IGNORE INTO profile VALUES (1, ?)", (encoded,))
            if db.execute("SELECT value FROM profile WHERE id=1").fetchone()[0] != encoded:
                raise ValueError("Changing an RLM profile requires a new session")

    def _check(self):
        if not self.allow_read:
            raise PermissionError("History reading is disabled by the RLM sandbox policy")

    def store(self, message):
        # Include the tool occurrence so identical outputs retain causal identity.
        body = message_text(message)
        identity = str(getattr(message, "tool_call_id", "")) + "\0" + body
        handle = "obs-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO observations VALUES (?, ?)", (handle, body))
        return handle

    async def _records(self):
        self._check()
        records = []
        for entry in await self.session.get_branch():
            message = getattr(entry, "message", None)
            if message is not None:
                records.append((entry.id, message))
            elif getattr(entry, "summary", None):
                records.append((entry.id, UserMessage(str(entry.summary))))
        seen = {
            getattr(m, "tool_call_id", None) for _, m in records if isinstance(m, ToolResultMessage)
        }
        live = self.live_messages if self.live_leaf == await self.session.get_leaf_id() else []
        for message in live:
            if isinstance(message, ToolResultMessage) and message.tool_call_id not in seen:
                records.append((self.store(message), message))
        return records

    async def dispatch(self, name, payload):
        records = await self._records()
        if name == "history.search":
            query = str(payload.get("query", "")).casefold()
            limit = max(1, min(50, int(payload.get("limit", 20))))
            matches = []
            for entry_id, message in reversed(records):
                body = message_text(message)
                pos = body.casefold().find(query)
                if pos >= 0:
                    matches.append(
                        {
                            "id": entry_id,
                            "role": message.role,
                            "tool": getattr(message, "tool_name", None),
                            "chars": len(body),
                            "preview": body[max(0, pos - 80) : pos + 240],
                        }
                    )
                    if len(matches) == limit:
                        break
            return matches
        if name == "history.read":
            identity = str(payload.get("id", ""))
            start = max(0, int(payload.get("start", 0)))
            size = max(1, min(20000, int(payload.get("size", 4000))))
            for entry_id, message in records:
                if identity in {entry_id, self.store(message)}:
                    body = message_text(message)
                    return {
                        "id": identity,
                        "entry_id": entry_id,
                        "role": message.role,
                        "start": start,
                        "chars": len(body),
                        "text": body[start : start + size],
                        "more": start + size < len(body),
                    }
            raise ValueError("History handle is unavailable on the current branch")
        if name == "history.stats":
            return {
                "entries": len(records),
                "chars": sum(len(message_text(m)) for _, m in records),
                "branch": await self.session.get_leaf_id(),
            }
        raise ValueError(f"Unsupported history operation: {name}")

    def project(self, messages, profile):
        self.live_messages = list(messages)
        self.live_leaf = getattr(self.session, "_leaf_id", None)
        if profile.observations != "selective":
            return messages
        recent = max(0, len(messages) - profile.recent_messages)
        projected = []
        for index, message in enumerate(messages):
            body = message_text(message)
            # Preserve all user instructions and assistant/tool-call identities.
            if isinstance(message, ToolResultMessage) and len(body) > profile.observation_chars:
                handle = self.store(message)
                receipt = json.dumps(
                    {
                        "history_handle": handle,
                        "tool": message.tool_name,
                        "error": message.is_error,
                        "chars": len(body),
                    }
                )
                preview = body[: profile.observation_chars] if index >= recent else ""
                projected.append(replace(message, content=[TextContent(receipt + "\n" + preview)]))
            elif (
                isinstance(message, AssistantMessage) and index < recent and not message.tool_calls
            ):
                handle = self.store(message)
                projected.append(
                    replace(
                        message,
                        content=[
                            TextContent(
                                f"Earlier assistant response stored as {handle}; {len(body)} characters."
                            )
                        ],
                    )
                )
            else:
                projected.append(message)
        return projected


class HistoryNamespace:
    """Synchronous Python facade backed by the session owner's event loop."""

    def __init__(self, call):
        self._call = call

    def search(self, query="", *, limit=20):
        return self._call("history.search", {"query": query, "limit": limit})

    def read(self, identity, *, start=0, size=4000):
        return self._call("history.read", {"id": identity, "start": start, "size": size})

    def stats(self):
        return self._call("history.stats", {})
