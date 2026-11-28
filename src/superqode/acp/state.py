"""ACP v2 session/entity reducer. Wire patches never use v1 truthiness rules."""

from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .protocol import ProtocolError, capability


def patch(target: dict, update: dict) -> dict:
    for key, value in update.items():
        if key == "_meta" and isinstance(value, dict):
            metadata = dict(target.get(key) or {})
            for name, item in value.items():
                if item is None:
                    metadata.pop(name, None)
                else:
                    metadata[name] = deepcopy(item)
            target[key] = metadata
        else:
            target[key] = deepcopy(value)
    return target


def content_text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(content_text(item) for item in content)
    if isinstance(content, dict):
        return str(content.get("text") or "") if content.get("type") == "text" else ""
    return ""


@dataclass
class SessionState:
    session_id: str
    parent_id: str | None = None
    messages: dict[str, dict] = field(default_factory=dict)
    tools: dict[str, dict] = field(default_factory=dict)
    terminals: dict[str, dict] = field(default_factory=dict)
    plans: dict[str, dict] = field(default_factory=dict)
    children: dict[str, dict] = field(default_factory=dict)
    info: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    config_options: list[dict] = field(default_factory=list)
    commands: list[dict] = field(default_factory=list)
    state: str = "idle"
    background: list[dict] | None = None
    stop_reason: str | None = None
    error: dict | None = None
    uncertain: bool = False
    sequence: int = 0
    activity: int = 0
    completed: int = 0
    replaying: bool = False
    replay_complete: bool = False
    synchronizing: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def text(self, role: str = "agent_message") -> str:
        return "".join(
            content_text(m.get("content")) for m in self.messages.values() if m.get("role") == role
        )

    @property
    def quiet(self) -> bool:
        return self.state == "idle" and self.background == []


class SessionRegistry:
    def __init__(self):
        self.sessions: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        if not isinstance(session_id, str) or not session_id:
            raise ProtocolError(-32602, "Missing sessionId")
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(session_id)
        return self.sessions[session_id]

    def check_child_method(self, session_id: str, method: str, item: str | None = None) -> None:
        session = self.get(session_id)
        if session.parent_id is None:
            return
        parent = self.get(session.parent_id)
        if method == "session/cancel" and capability(
            parent.children.get(session_id), "capabilities", "cancel"
        ):
            return
        collection = session.tools if method == "tool_call/cancel" else session.terminals
        if method in {"tool_call/cancel", "terminal/cancel"} and capability(
            collection.get(item), "capabilities", "cancel"
        ):
            return
        raise ProtocolError(-32601, "This child session does not allow that operation")

    def apply(self, session_id: str, update: dict) -> tuple[SessionState, dict | None]:
        session = self.get(session_id)
        session.sequence += 1
        kind = update.get("sessionUpdate", "")
        entity = None
        if kind in {
            "agent_message",
            "user_message",
            "agent_thought",
            "session_message",
            "agent_message_chunk",
            "user_message_chunk",
            "agent_thought_chunk",
            "session_message_chunk",
        }:
            identity = update.get("messageId")
            if not isinstance(identity, str):
                raise ProtocolError(-32602, "Message update requires messageId")
            role = kind.removesuffix("_chunk")
            entity = session.messages.setdefault(
                identity, {"messageId": identity, "role": role, "content": []}
            )
            excluded = {"sessionUpdate", "content"}
            if kind.endswith("_chunk"):
                # Chunk metadata describes this delivery, not the retained message.
                excluded.add("_meta")
            fields = {k: v for k, v in update.items() if k not in excluded}
            patch(entity, fields)
            if kind.endswith("_chunk"):
                content = update.get("content")
                entity["content"] = list(entity.get("content") or []) + (
                    content if isinstance(content, list) else [content]
                )
            elif "content" in update:
                entity["content"] = deepcopy(update["content"] or [])
        elif kind == "tool_call_update":
            identity = update["toolCallId"]
            entity = patch(session.tools.setdefault(identity, {"toolCallId": identity}), update)
        elif kind == "tool_call_content_chunk":
            entity = session.tools.setdefault(
                update["toolCallId"], {"toolCallId": update["toolCallId"]}
            )
            entity["content"] = list(entity.get("content") or []) + [deepcopy(update["content"])]
        elif kind in {"terminal_update", "terminal_output_chunk"}:
            identity = update["terminalId"]
            entity = session.terminals.setdefault(identity, {"terminalId": identity, "bytes": b""})
            if kind == "terminal_update":
                patch(entity, update)
                if "output" in update:
                    entity["bytes"] = self._bytes((update.get("output") or {}).get("data", ""))
            else:
                entity["bytes"] = entity.get("bytes", b"") + self._bytes(update.get("data", ""))
        elif kind == "plan_update":
            entity = deepcopy(update["plan"])
            session.plans[entity["planId"]] = entity
        elif kind == "plan_removed":
            session.plans.pop(update["planId"], None)
        elif kind == "subagent_update":
            child_id = update["sessionId"]
            child = self.get(child_id)
            if child_id == session_id or child.parent_id not in (None, session_id):
                raise ProtocolError(-32602, "Invalid child session association")
            ancestor = session
            while ancestor.parent_id:
                if ancestor.parent_id == child_id:
                    raise ProtocolError(-32602, "Cyclic child session association")
                ancestor = self.get(ancestor.parent_id)
            child.parent_id = session_id
            entity = patch(session.children.setdefault(child_id, {"sessionId": child_id}), update)
            if "state" in update:
                self.apply(
                    child_id,
                    {**(update["state"] or {"state": "unknown"}), "sessionUpdate": "state_update"},
                )
        elif kind == "state_update":
            state = update.get("state", "unknown")
            was_active = session.state in {"running", "requires_action"}
            session.state = (
                state if state in {"idle", "running", "requires_action", "unknown"} else "unknown"
            )
            if "background" in update:
                session.background = deepcopy(update["background"])
            if session.state in {"running", "requires_action"}:
                session.uncertain = False
                session.activity += 1
            elif session.state == "unknown":
                session.uncertain = True
            if session.state == "idle":
                if was_active and not session.replaying and not session.synchronizing:
                    session.completed += 1
                session.stop_reason = update.get("stopReason")
                session.error = update.get("error")
        elif kind == "replay_complete":
            if session.replay_complete or not session.replaying:
                raise ProtocolError(-32602, "Unexpected replay_complete")
            session.replay_complete = True
            session.replaying = False
        elif kind == "config_option_update":
            session.config_options = deepcopy(update.get("configOptions", []))
        elif kind == "available_commands_update":
            session.commands = deepcopy(update.get("availableCommands", []))
        elif kind == "session_info_update":
            patch(session.info, update)
        elif kind == "usage_update":
            patch(session.usage, update)
        elif kind.startswith("compaction"):
            entity = session.info.setdefault("compactions", {}).setdefault(
                update["compactionId"], {"status": "in_progress", "summary": []}
            )
            if kind == "compaction_summary_chunk":
                entity["summary"] = list(entity.get("summary") or []) + [
                    deepcopy(update["content"])
                ]
            else:
                patch(entity, update)
        else:
            # Keep forward-compatible events available to generic consumers.
            entity = deepcopy(update)
        session.changed.set()
        return session, entity

    @staticmethod
    def _bytes(value: str) -> bytes:
        try:
            return base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise ProtocolError(-32602, "Invalid terminal base64 output") from exc
