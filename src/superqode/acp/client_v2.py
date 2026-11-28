"""Preview client adapter. The v1 client remains responsible for its own wire shapes."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import uuid

from .outbox import SubmissionOutbox
from .protocol import (
    ProtocolError,
    capability,
    mcp_servers_v2,
    protocol_policy,
    requested_version,
    validate_v2,
)
from .state import SessionRegistry, content_text


class V1FallbackRequired(Exception):
    pass


class ACPv2ClientMixin:
    def _setup_v2(self):
        self.protocol_policy, self.protocol_version = protocol_policy(
            self.protocol_policy, self.protocol_version
        )
        self._preferred_protocol_version = self.protocol_version
        if self.session_protocol_version is not None:
            self.session_protocol_version = requested_version(self.session_protocol_version)
            if (
                self.protocol_policy != "auto"
                and self.session_protocol_version != self.protocol_version
            ):
                raise ValueError("Changing ACP versions requires a new agent session")
        self.negotiated_version = 1
        self.sessions = SessionRegistry()
        self._v1_fallback = False
        self._fallback_attempt = False
        self._fallback_reason = ""
        self._v2_active_requests = {}
        self._v2_disconnected = False
        self._v2_send_lock = asyncio.Lock()
        self._foreground_lock = asyncio.Lock()
        self._v2_turn_baseline = set()
        self._v2_insertion_baselines = {}
        self._v2_replay_sessions = set()
        scope = f"{self.agent_identity or self.command}\0{self.project_root.resolve()}"
        self.outbox = SubmissionOutbox(self.pending_submission_path, scope=scope)

    async def _initialize_v2(self):
        from superqode import __version__

        self.negotiated_version = 2
        try:
            response = await self._call_method(
                "initialize",
                timeout=self.startup_timeout,
                protocolVersion=2,
                info={"name": "SuperQode", "title": "SuperQode", "version": __version__},
                capabilities={"auth": {"terminal": {}}} if self.terminal_auth_supported else {},
            )
        except Exception as exc:
            if getattr(exc, "acp_code", None) == -32022:
                self._request_v1_fallback(
                    "Agent rejected ACP v2 as an unsupported protocol version."
                )
            raise
        if type(response.get("protocolVersion")) is int and response["protocolVersion"] == 1:
            self._request_v1_fallback("Agent selected ACP v1 during initialization.")
        validate_v2("InitializeResponse", response)
        if response.get("protocolVersion") != 2:
            raise ValueError("Agent selected an unsupported ACP version")
        self.negotiated_version = 2
        self._agent_capabilities = response.get("capabilities", {})
        if not self.initialize_only and not capability(self._agent_capabilities, "session"):
            raise ValueError("ACP agent does not support sessions")
        self._auth_methods = response.get("authMethods", [])
        self._initialization_info = {
            "protocol_version": 2,
            "requested_protocol_version": self.protocol_version,
            "agent": {
                k: response["info"][k]
                for k in ("name", "title", "version")
                if k in response["info"]
            },
        }
        return response

    def _request_v1_fallback(self, reason):
        if self.protocol_policy != "auto":
            raise ProtocolError(-32022, "ACP v2 is required. Choose Auto or ACP v1 for this agent.")
        if self.resume_session_id and self.session_protocol_version == 2:
            raise ProtocolError(
                -32022,
                "The existing ACP v2 session cannot be resumed through v1. Start a new session.",
            )
        raise V1FallbackRequired(reason)

    def _v2_mcp_servers(self):
        from superqode.mcp.config import get_acp_mcp_servers

        return mcp_servers_v2(
            [*get_acp_mcp_servers(), *self.host_mcp_servers],
            self._agent_capabilities,
            cwd=self.project_root,
        )

    async def _new_session_v2(self):
        response = await self._call_method(
            "session/new",
            timeout=self.startup_timeout,
            cwd=str(self.project_root.resolve()),
            mcpServers=self._v2_mcp_servers(),
        )
        validate_v2("NewSessionResponse", response)
        self._session_id = response["sessionId"]
        session = self.sessions.get(self._session_id)
        session.config_options = deepcopy(response.get("configOptions", []))
        session.commands = deepcopy(response.get("availableCommands", []))
        self._apply_v2_configuration(session)
        await self._select_requested_model()
        await self._persist_current_session()
        return response

    async def _resume_session_v2(self, session_id: str, *, replay: bool = True):
        self.sessions.check_child_method(session_id, "session/resume")
        session = self.sessions.get(session_id)
        previous_id = self._session_id
        self._session_id = session_id
        session.replaying = replay
        session.replay_complete = False
        self._v2_replay_sessions = {session_id} if replay else set()
        session.synchronizing = True
        session.state_synchronized = False
        before = session.sequence
        params = {
            "sessionId": session_id,
            "cwd": str(self.project_root.resolve()),
            "mcpServers": self._v2_mcp_servers(),
        }
        if replay:
            params["replayFrom"] = {"type": "start"}
        try:
            response = await self._call_method(
                "session/resume", timeout=self.startup_timeout, **params
            )
            validate_v2("ResumeSessionResponse", response)
            if replay and not session.replay_complete:
                raise ProtocolError(
                    -32603, "Truncated ACP replay: replay_complete was not received"
                )
            if any(
                not self.sessions.get(child).replay_complete for child in self._v2_replay_sessions
            ):
                raise ProtocolError(-32603, "Truncated child-session replay")
            if session.sequence <= before or not getattr(session, "state_synchronized", False):
                raise ProtocolError(-32603, "ACP resume omitted the current state snapshot")
            session.config_options = deepcopy(response.get("configOptions", []))
            session.commands = deepcopy(response.get("availableCommands", []))
            self._apply_v2_configuration(session)
            await self._persist_current_session(touch_only=True)
            return response
        except BaseException:
            self._session_id = previous_id
            raise
        finally:
            session.replaying = False
            session.synchronizing = False
            for child in self._v2_replay_sessions:
                self.sessions.get(child).replaying = False
                self.sessions.get(child).synchronizing = False

    def _apply_v2_configuration(self, session):
        # `id` aliases belong to the product API, never to the v2 wire encoder.
        self._apply_session_state_from_response(
            {"configOptions": [{**o, "id": o.get("configId")} for o in session.config_options]}
        )
        self._available_commands = deepcopy(session.commands)
        mode = next((o for o in session.config_options if o.get("category") == "mode"), None)
        if mode:
            self._current_mode_id = mode.get("currentValue")
            self._available_modes = [
                {"id": x["value"], "name": x.get("name", x["value"])}
                for x in mode.get("options", [])
                if "value" in x
            ]

    async def submit_prompt(
        self, prompt: str, *, images=None, idempotency_key: str | None = None
    ) -> dict:
        if self.negotiated_version != 2:
            raise ValueError("submit_prompt requires an ACP v2 connection; use send_prompt for v1")
        blocks = [{"type": "text", "text": prompt}]
        if images:
            if not capability(self._agent_capabilities, "session", "prompt", "image"):
                raise ValueError("This ACP agent does not advertise image input")
            blocks.extend(image.acp_part() for image in images)
        return await self._submit_blocks(
            blocks, str(uuid.uuid4()) if idempotency_key is None else idempotency_key
        )

    async def _submit_blocks(self, blocks: list[dict], key: str):
        session_id = self._session_id
        self.sessions.check_child_method(session_id, "session/prompt")
        params = {"sessionId": session_id, "prompt": blocks, "idempotencyKey": key}
        validate_v2("PromptRequest", params)
        old = self.outbox.entries.get(key)
        if old and (old["session_id"] != session_id or old["prompt"] != blocks):
            raise ValueError("A submission key cannot be reused with different input or session")
        entry = old or {"session_id": session_id, "prompt": deepcopy(blocks), "status": "pending"}
        self.outbox.put(key, entry)
        response = await self._call_method("session/prompt", timeout=self.prompt_timeout, **params)
        validate_v2("PromptResponse", response)
        self.outbox.put(
            key,
            {
                **entry,
                "status": "completed" if entry.get("status") == "completed" else "accepted",
                "message_id": response["messageId"],
            },
        )
        return response

    async def retry_submission(self, key: str) -> dict:
        """Explicit retry only; recovery never automatically replays user work."""
        entry = self.outbox.entries[key]
        if self._session_id != entry["session_id"]:
            raise ValueError("Resume the original ACP session before retrying this submission")
        return await self._submit_blocks(entry["prompt"], key)

    async def reconnect(self) -> bool:
        session_id = self._session_id
        self.session_protocol_version = self.negotiated_version
        await self.stop()
        self.resume_session_id = session_id
        self.require_resume = True
        return await self.start()

    async def _send_prompt_v2(self, prompt, *, images=None, idempotency_key=None):
        async with self._foreground_lock:
            self.reset_stats()
            session = self.sessions.get(self._session_id)
            before = session.completed
            self._v2_turn_baseline = set(session.messages)
            key = str(uuid.uuid4()) if idempotency_key is None else idempotency_key
            previous_entry = deepcopy(self.outbox.entries.get(key))
            async with asyncio.timeout(self.prompt_timeout):
                accepted = await self.submit_prompt(prompt, images=images, idempotency_key=key)
                if accepted["messageId"] in self._v2_turn_baseline:
                    if previous_entry and previous_entry.get("status") == "completed":
                        self.outbox.put(key, previous_entry)
                        self._last_stop_reason = previous_entry["stop_reason"]
                        self._message_buffer = previous_entry.get("response", "")
                        if self.on_message_update:
                            await self.on_message_update(
                                {"sessionId": session.session_id, "text": self._message_buffer}
                            )
                        return self._last_stop_reason
                    if session.state == "idle":
                        raise RuntimeError(
                            "The earlier submission was inserted, but its execution outcome is uncertain; no duplicate work was started"
                        )

                def completed():
                    baseline = self._v2_insertion_baselines.get(
                        (session.session_id, accepted["messageId"]), before
                    )
                    return session.completed > baseline

                while not completed():
                    if session.state == "idle" and session.uncertain:
                        raise RuntimeError(
                            "ACP activity became unobservable; the execution outcome is uncertain"
                        )
                    if self._v2_disconnected:
                        raise ConnectionError(
                            "ACP disconnected after submission; outcome is uncertain. Resume before explicitly retrying."
                        )
                    session.changed.clear()
                    if not completed():
                        await session.changed.wait()
            self._last_stop_reason = session.stop_reason or "end_turn"
            entry = self.outbox.entries[key]
            self.outbox.put(
                key,
                {
                    **entry,
                    "status": "completed",
                    "stop_reason": self._last_stop_reason,
                    "response": self._message_buffer,
                },
            )
            if self.session_store and self.agent_identity:
                await self.session_store.touch(self.agent_identity, self._session_id)
            return self._last_stop_reason

    async def _handle_v2_update(self, params):
        validate_v2("UpdateSessionNotification", params)
        identity, update = params["sessionId"], params["update"]
        previous_session = self.sessions.get(identity)

        def turn_text():
            return "".join(
                content_text(m.get("content"))
                for key, m in previous_session.messages.items()
                if key not in self._v2_turn_baseline and m.get("role") == "agent_message"
            )

        previous = turn_text()
        if update["sessionUpdate"] in {"user_message", "user_message_chunk"}:
            self._v2_insertion_baselines.setdefault(
                (identity, update["messageId"]), previous_session.completed
            )
        kind = update["sessionUpdate"]
        if kind == "subagent_update" and previous_session.replaying:
            child_id = update["sessionId"]
            if child_id not in self._v2_replay_sessions:
                child = self.sessions.get(child_id)
                child.replaying = child.synchronizing = True
                child.replay_complete = False
                self._v2_replay_sessions.add(child_id)
        session, entity = self.sessions.apply(identity, update)
        if kind == "state_update":
            session.state_synchronized = True
        root = identity == self._session_id and not session.replaying and not session.synchronizing
        if root and kind in {"agent_message", "agent_message_chunk"}:
            current = turn_text()
            self._message_buffer = current
            if self.on_message_update:
                await self.on_message_update(
                    {
                        "sessionId": identity,
                        "messageId": update["messageId"],
                        "text": current,
                        "message": deepcopy(entity),
                    }
                )
            elif self.on_message and current.startswith(previous):
                await self.on_message(current[len(previous) :])
        elif root and kind in {"agent_thought", "agent_thought_chunk"} and self.on_thinking:
            await self.on_thinking(content_text(update.get("content")))
        elif root and kind in {"user_message", "user_message_chunk"} and self.on_user_message:
            await self.on_user_message(content_text(update.get("content")))
        elif root and kind in {"tool_call_update", "tool_call_content_chunk"}:
            tool_id = update["toolCallId"]
            new = tool_id not in self._tool_calls
            self._tool_calls[tool_id] = deepcopy(entity)
            if new:
                self._tool_actions.append(
                    {
                        "tool_call_id": tool_id,
                        "tool": entity.get("title", "Tool call"),
                        "kind": entity.get("kind", "other"),
                        "input": entity.get("rawInput"),
                    }
                )
            callback = self.on_tool_call if new else self.on_tool_update
            if callback:
                await callback(deepcopy(entity))
        elif root and kind in {"plan_update", "plan_removed"} and self.on_plan:
            await self.on_plan(
                [item for plan in session.plans.values() for item in plan.get("entries", [])]
            )
        elif root and kind in {"config_option_update", "available_commands_update"}:
            self._apply_v2_configuration(session)
            if kind == "available_commands_update" and self.on_available_commands:
                await self.on_available_commands(self._available_commands)
        elif root and kind == "usage_update":
            self._usage = deepcopy(session.usage)
            if self.on_usage_update:
                await self.on_usage_update(deepcopy(self._usage))
        if self.on_session_update:
            await self.on_session_update(deepcopy(params))

    async def _permission_v2(self, params):
        validate_v2("RequestPermissionRequest", params)
        session_id = params["sessionId"]
        if session_id not in self.sessions.sessions:
            raise ProtocolError(-32002, "Unknown session", {"sessionId": session_id})
        subject = params.get("subject") or {}
        tool = deepcopy(subject.get("toolCall") or {}) if subject.get("type") == "tool_call" else {}
        if tool:
            _, tool = self.sessions.apply(session_id, {"sessionUpdate": "tool_call_update", **tool})
            subject = {**subject, "toolCall": tool}
        display = {
            **tool,
            "title": params["title"],
            "description": params.get("description"),
            "subject": subject,
            "sessionId": session_id,
            "acp_permission": True,
        }
        if subject.get("type") == "command":
            display.update(
                {
                    "command": subject["command"],
                    "cwd": subject["cwd"],
                    "rawInput": {"command": subject["command"], "cwd": subject["cwd"]},
                }
            )
        options = params["options"]
        key = self._permission_key_v2(subject)
        stored = (
            await self.permission_store.get(self.permission_scope, key)
            if self.permission_store and self.permission_scope and key
            else None
        )
        if stored:
            option = next((o for o in options if o.get("kind") == stored.value), None)
            if option is None:
                option = next(
                    (
                        o
                        for o in options
                        if o.get("kind") == ("allow_once" if stored.allowed else "reject_once")
                    ),
                    None,
                )
            if option:
                return {"outcome": {"outcome": "selected", "optionId": option["optionId"]}}
        if not self.on_permission_request:
            return {"outcome": {"outcome": "cancelled"}}
        try:
            selected = await self.on_permission_request(options, display)
        except asyncio.CancelledError:
            return {"outcome": {"outcome": "cancelled"}}
        option = next((o for o in options if o["optionId"] == selected), None)
        if option is None:
            return {"outcome": {"outcome": "cancelled"}}
        if key and self.permission_store and self.permission_scope:
            from .permission_store import PermissionDecision

            decision = PermissionDecision.from_option_kind(option.get("kind"))
            if decision:
                await self.permission_store.set(self.permission_scope, key, decision)
        return {"outcome": {"outcome": "selected", "optionId": selected}}

    def _permission_key_v2(self, subject):
        kind = subject.get("type")
        if kind == "command":
            value = {k: subject[k] for k in ("type", "command", "cwd") if k in subject}
        elif kind == "tool_call":
            tool = subject.get("toolCall") or {}
            if not tool.get("name") or "rawInput" not in tool:
                return None
            value = {"type": kind, "name": tool["name"], "input": tool["rawInput"]}
        else:
            return None
        value["workspace"] = str(self.project_root.resolve())
        return "v2:" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    async def cancel_item(self, session_id: str, identity: str, *, terminal: bool = False):
        session = self.sessions.get(session_id)
        collection = session.terminals if terminal else session.tools
        if not capability(collection.get(identity), "capabilities", "cancel"):
            raise ValueError("This item does not advertise cancellation")
        method = "terminal/cancel" if terminal else "tool_call/cancel"
        self.sessions.check_child_method(session_id, method, identity)
        return await self._call_method(
            method, sessionId=session_id, **{"terminalId" if terminal else "toolCallId": identity}
        )

    async def close_session(self, session_id: str | None = None):
        session_id = session_id or self._session_id
        if self.negotiated_version == 2:
            self.sessions.check_child_method(session_id, "session/close")
        return await self._call_method("session/close", sessionId=session_id)

    async def list_sessions(self, **params):
        if self.negotiated_version != 2:
            raise ValueError("Use the v1 session store for this connection")
        return await self._call_method("session/list", **params)
