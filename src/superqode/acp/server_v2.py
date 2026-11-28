"""ACP v2 agent lifecycle over a pinned schema, sharing the harness with v1."""

from __future__ import annotations

import asyncio
import base64
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import uuid

from .ledger import SessionLedger
from .protocol import ProtocolError, capability, validate_v2
from .state import SessionRegistry
from .server import (
    SuperQodeAcpAgent,
    _AcpSessionState,
    _ToolCallTracker,
    _clip,
    _tool_kind,
    _tool_title,
)


@dataclass
class PendingPrompt:
    prompt: list
    key: str | None
    future: asyncio.Future


@dataclass
class LiveSession:
    harness: _AcpSessionState
    active: bool = True
    queue: deque = field(default_factory=deque)
    pending: dict = field(default_factory=dict)
    runner: asyncio.Task | None = None
    work: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    admission_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    background: dict = field(default_factory=dict)
    thoughts: bool = True
    cancel_epoch: int = 0


class SuperQodeAcpV2Agent:
    def __init__(self, *, ledger_path: Path | None = None, **harness_options):
        self.core = SuperQodeAcpAgent(**harness_options)
        self.connection = None
        self.registry = SessionRegistry()
        self.live: dict[str, LiveSession] = {}
        self.child_ids: dict[tuple[str, str], str] = {}
        self.client_capabilities = {}
        root = Path(os.environ.get("SUPERQODE_HOME", str(Path.home() / ".superqode")))
        self.ledger = SessionLedger(ledger_path or root / "acp-v2" / "sessions.sqlite3")

    async def initialize(self, params):
        params = dict(params)
        if params.get("_meta") is not None and not isinstance(params["_meta"], dict):
            params.pop("_meta")
        if params.get("protocolVersion", 0) > 2:
            if not isinstance(params.get("capabilities", {}), dict):
                params.pop("capabilities", None)
            if not isinstance(params.get("info"), dict):
                params["info"] = {"name": "unknown", "version": "unknown"}
        validate_v2("InitializeRequest", params)
        self.client_capabilities = params.get("capabilities", {})

    def initialization(self):
        from superqode import __version__

        result = {
            "protocolVersion": 2,
            "info": {"name": "superqode", "title": "SuperQode", "version": __version__},
            "capabilities": {"session": {"prompt": {"embeddedContext": {}}}},
            "authMethods": [
                {
                    "type": "terminal",
                    "methodId": "superqode-setup",
                    "name": "Set up SuperQode",
                    "args": ["local", "init", "--repo", "."],
                }
            ],
        }
        if not capability(self.client_capabilities, "auth", "terminal"):
            result["authMethods"] = []
        validate_v2("InitializeResponse", result)
        return result

    def _session(self, identity):
        session = self.live.get(identity)
        if session is None or not session.active:
            raise ProtocolError(-32002, "Unknown or inactive session", {"sessionId": identity})
        return session

    async def handle(self, method, params):
        params = dict(params)
        if params.get("_meta") is not None and not isinstance(params["_meta"], dict):
            params.pop("_meta")
        definitions = {
            "session/new": "NewSessionRequest",
            "session/list": "ListSessionsRequest",
            "session/resume": "ResumeSessionRequest",
            "session/close": "CloseSessionRequest",
            "session/prompt": "PromptRequest",
            "session/cancel": "CancelSessionNotification",
            "session/set_config_option": "SetSessionConfigOptionRequest",
            "tool_call/cancel": "CancelToolCallRequest",
            "terminal/cancel": "CancelTerminalRequest",
            "auth/login": "LoginAuthRequest",
            "auth/logout": "LogoutAuthRequest",
        }
        if method not in definitions:
            raise ProtocolError(-32601, "Method not supported")
        validate_v2(definitions[method], params)
        if method.startswith("auth/") and not self.initialization()["authMethods"]:
            raise ProtocolError(-32601, "No authentication methods advertised")
        if method == "auth/login":
            raise ProtocolError(-32602, "Use the advertised terminal setup flow")
        if method == "auth/logout":
            return {}
        if method == "session/new":
            return await self.new_session(params)
        if method == "session/list":
            if params.get("cursor") is not None:
                raise ProtocolError(-32602, "Unknown session-list cursor")
            if params.get("cwd") is not None and not Path(params["cwd"]).is_absolute():
                raise ProtocolError(-32602, "cwd filter must be absolute")
            rows = self.ledger.list(params.get("cwd"))
            rows = [
                row
                for row in rows
                if not self.ledger.get(row["sessionId"])["metadata"].get("parent")
            ]
            return {"sessions": rows}
        if method == "session/resume":
            return await self.resume(params)
        identity = params["sessionId"]
        if identity in self.registry.sessions and self.registry.get(identity).parent_id:
            try:
                self.registry.check_child_method(
                    identity, method, params.get("toolCallId") or params.get("terminalId")
                )
            except ProtocolError as exc:
                raise ProtocolError(
                    -32602, "Operation is not permitted for a child session"
                ) from exc
        if method in {"tool_call/cancel", "terminal/cancel"}:
            return await self.cancel_item(identity, params, terminal=method == "terminal/cancel")
        if method == "session/close" and (
            identity not in self.live or not self.live[identity].active
        ):
            return {}
        session = self._session(identity)
        if method == "session/prompt":
            return await self.prompt(identity, params)
        if method == "session/cancel":
            await self.cancel(identity)
            return {}
        if method == "session/close":
            await self.close_session(identity)
            return {}
        if method == "session/set_config_option":
            return await self.configure(identity, session, params)

    @staticmethod
    def _check_setup(params):
        if params.get("mcpServers"):
            raise ProtocolError(-32602, "This harness does not advertise MCP transports")
        if params.get("systemPrompt"):
            raise ProtocolError(-32602, "This harness does not advertise system prompts")
        cwd = Path(params["cwd"])
        if not cwd.is_absolute() or not cwd.is_dir():
            raise ProtocolError(-32602, "cwd must name an existing absolute directory")
        return cwd.resolve()

    async def new_session(self, params):
        from superqode.harness.loader import harness_spec_to_dict

        cwd = self._check_setup(params)
        try:
            response = await self.core.new_session(cwd=str(cwd))
        except Exception as exc:
            raise ProtocolError(
                -32602, "Unable to create harness session; configure its provider and model"
            ) from exc
        identity = response.session_id
        state = self.core._sessions[identity]
        self.live[identity] = LiveSession(state)
        self.registry.get(identity).background = []
        self.ledger.create(
            identity,
            str(cwd),
            {
                "spec": harness_spec_to_dict(state.spec),
                "provider": state.provider,
                "model": state.model,
            },
        )
        return {"sessionId": identity, "configOptions": self.config_options(identity)}

    def config_options(self, identity):
        session = self.live[identity]
        state = session.harness
        return [
            {
                "configId": "model",
                "type": "select",
                "category": "model",
                "name": "Model",
                "currentValue": state.model,
                "options": [{"value": state.model, "name": state.model}],
            },
            {
                "configId": "thoughts",
                "type": "boolean",
                "name": "Show reasoning",
                "currentValue": session.thoughts,
            },
        ]

    async def configure(self, identity, session, params):
        if params["configId"] == "thoughts" and params["type"] == "boolean":
            session.thoughts = params["value"]
            record = self.ledger.get(identity)["metadata"]
            self.ledger.configure(identity, {**record, "thoughts": session.thoughts})
        elif not (
            params["configId"] == "model"
            and params["type"] == "id"
            and params["value"] == session.harness.model
        ):
            raise ProtocolError(-32602, "Unknown config option or value")
        result = {"configOptions": self.config_options(identity)}
        await self.emit(identity, {"sessionUpdate": "config_option_update", **result})
        return result

    async def resume(self, params):
        from superqode.harness import FileHarnessStore, init_harness
        from superqode.harness.loader import harness_spec_from_dict

        identity = params["sessionId"]
        cwd = self._check_setup(params)
        record = self.ledger.get(identity)
        if record["metadata"].get("parent"):
            raise ProtocolError(-32602, "A child cannot be resumed directly")
        if record["cwd"] != str(cwd) or record["metadata"].get("parent"):
            raise ProtocolError(
                -32002, "Session is not available in this workspace", {"sessionId": identity}
            )
        if identity not in self.live:
            meta = record["metadata"]
            spec = harness_spec_from_dict(meta["spec"])
            storage = Path(spec.context.session_storage)
            kernel = await init_harness(
                spec, store=FileHarnessStore(storage if storage.is_absolute() else cwd / storage)
            )
            harness_session = await kernel.session(identity)
            self.live[identity] = LiveSession(
                _AcpSessionState(harness_session, spec, meta["provider"], meta["model"], cwd),
                thoughts=meta.get("thoughts", True),
            )
        session = self.live[identity]
        session.active = True
        if params.get("replayFrom") not in (None, {"type": "start"}):
            raise ProtocolError(-32602, "Unsupported replay cursor")
        async with session.lock:
            announced = set()
            if params.get("replayFrom"):
                announced = await self._replay(identity)
                await self.connection.notify(
                    "session/update",
                    sessionId=identity,
                    update={"sessionUpdate": "replay_complete"},
                )
            for child in announced - {identity}:
                parent = self.registry.get(child).parent_id
                await self.connection.notify(
                    "session/update",
                    sessionId=parent,
                    update={
                        "sessionUpdate": "subagent_update",
                        "sessionId": child,
                        "capabilities": {},
                        "state": {
                            k: v
                            for k, v in self.state_update(child).items()
                            if k != "sessionUpdate"
                        },
                    },
                )
                await self.connection.notify(
                    "session/update", sessionId=child, update=self.state_update(child)
                )
            await self.connection.notify(
                "session/update", sessionId=identity, update=self.state_update(identity)
            )
            await self.connection.notify(
                "session/update",
                sessionId=identity,
                update={
                    "sessionUpdate": "session_info_update",
                    "updatedAt": self.ledger.get(identity)["updatedAt"],
                },
            )
        return {"configOptions": self.config_options(identity)}

    async def _replay(self, identity, seen=None):
        seen = set() if seen is None else seen
        seen.add(identity)
        reduced = SessionRegistry()
        order = {}
        for update in self.ledger.history(identity):
            state, entity = reduced.apply(identity, update)
            kind = update["sessionUpdate"]
            if (
                kind.endswith("message")
                or kind.endswith("message_chunk")
                or kind.startswith("agent_thought")
            ):
                order["message", update["messageId"]] = None
            elif kind.startswith("tool_call"):
                order["tool", update["toolCallId"]] = None
            elif kind.startswith("terminal"):
                order["terminal", update["terminalId"]] = None
            elif kind == "subagent_update":
                order["child", update["sessionId"]] = None
            elif kind == "plan_update":
                order["plan", update["plan"]["planId"]] = None
            elif kind == "plan_removed":
                order.pop(("plan", update["planId"]), None)
        state = reduced.get(identity)
        for kind, key in order:
            if kind == "message":
                message = deepcopy(state.messages[key])
                role = message.pop("role")
                update = {"sessionUpdate": role, **message}
            elif kind == "tool":
                update = {**state.tools[key], "sessionUpdate": "tool_call_update"}
                if (
                    update.get("status") in {"pending", "paused", "in_progress"}
                    and not (
                        identity in self.live
                        and self.live[identity].work
                        and not self.live[identity].work.done()
                    )
                    and key not in getattr(self.live.get(identity), "background", {})
                ):
                    update["status"] = "cancelled"
            elif kind == "terminal":
                update = {k: v for k, v in state.terminals[key].items() if k != "bytes"}
                update.update(
                    {
                        "sessionUpdate": "terminal_update",
                        "output": {
                            "data": base64.b64encode(
                                state.terminals[key].get("bytes", b"")
                            ).decode()
                        },
                    }
                )
            elif kind == "plan":
                update = {"sessionUpdate": "plan_update", "plan": state.plans[key]}
            else:
                update = {
                    k: v
                    for k, v in state.children[key].items()
                    if k not in {"state", "capabilities"}
                }
                self.registry.apply(identity, update)
            await self.connection.notify("session/update", sessionId=identity, update=update)
            if kind == "child":
                child = key
                if child not in seen:
                    await self._replay(child, seen)
                    await self.connection.notify(
                        "session/update",
                        sessionId=child,
                        update={"sessionUpdate": "replay_complete"},
                    )
        return seen

    async def prompt(self, identity, params):
        session = self._session(identity)
        prompt = params["prompt"]
        if not prompt:
            raise ProtocolError(-32602, "A prompt requires content")
        if any(part.get("type") not in {"text", "resource_link", "resource"} for part in prompt):
            raise ProtocolError(-32602, "Prompt content type was not advertised")
        key = params.get("idempotencyKey")
        if key is not None:
            old = self.ledger.lookup(identity, key)
            if old:
                if old["prompt"] != prompt:
                    raise ProtocolError(-32602, "Submission key was used with different input")
                return {"messageId": old["messageId"]}
        pending = session.pending.get(key) if key is not None else None
        if pending and pending.prompt != prompt:
            raise ProtocolError(-32602, "Submission key was used with different input")
        if pending is None:
            pending = PendingPrompt(
                deepcopy(prompt), key, asyncio.get_running_loop().create_future()
            )
            session.queue.append(pending)
            if key is not None:
                session.pending[key] = pending
        if session.runner is None or session.runner.done():
            session.runner = asyncio.create_task(self._drain(identity))
        try:
            return await asyncio.shield(pending.future)
        except asyncio.CancelledError:
            # Once inserted, a cancelled RPC must still acknowledge insertion.
            if pending.future.done() and not pending.future.cancelled():
                return pending.future.result()
            if pending in session.queue:
                session.queue.remove(pending)
            session.pending.pop(key, None)
            if not pending.future.done():
                pending.future.set_exception(ProtocolError(-32800, "Uninserted prompt withdrawn"))
                pending.future.exception()
            raise ProtocolError(-32800, "Uninserted prompt withdrawn") from None

    async def _drain(self, identity):
        session = self.live[identity]
        while session.active and session.queue:
            pending = None
            try:
                async with session.admission_lock:
                    if not session.active or not session.queue:
                        return
                    pending = session.queue.popleft()
                    epoch = session.cancel_epoch
                    message_id, update = self.ledger.insert(identity, pending.prompt, pending.key)
                    # Commit is the acceptance boundary, including cancellation while
                    # a slow peer is receiving the user-message echo.
                    pending.future.set_result({"messageId": message_id})
                    if update is not None:
                        await self.emit(identity, update, retain=False)
                    if update is None:
                        continue
                    await self.emit(identity, self.state_update(identity, state="running"))
                    session.work = asyncio.create_task(
                        self._run_turn(identity, pending.prompt, epoch)
                    )
                await session.work
            except asyncio.CancelledError:
                if pending and not pending.future.done():
                    pending.future.set_exception(ProtocolError(-32800, "Prompt cancelled"))
                if self.registry.get(identity).state != "idle":
                    # A task cancelled before its coroutine starts cannot run
                    # its own finally block or publish foreground completion.
                    await self._finish_descendants(identity)
                    await self.emit(
                        identity,
                        {**self.state_update(identity, state="idle"), "stopReason": "cancelled"},
                    )
            except Exception:
                if pending and not pending.future.done():
                    pending.future.set_exception(ProtocolError(-32603, "Prompt insertion failed"))
            finally:
                if pending:
                    session.pending.pop(pending.key, None)
                session.work = None

    async def _run_turn(self, identity, prompt, epoch=None):
        session = self.live[identity]
        tracker = _ToolCallTracker()
        namespace = uuid.uuid4().hex
        message_ids = {"message": "msg-" + uuid.uuid4().hex, "thought": "msg-" + uuid.uuid4().hex}
        reason = "end_turn"
        error = None
        try:
            if not session.active or epoch is not None and epoch != session.cancel_epoch:
                raise asyncio.CancelledError
            parts = []
            for block in prompt:
                if block["type"] == "text":
                    parts.append(block["text"])
                elif block["type"] == "resource":
                    parts.append(str(block.get("resource", {}).get("text", "")))
                elif block["type"] == "resource_link":
                    parts.append(f"[resource: {block.get('uri', '')}]")
            stream = session.harness.session.stream(
                "\n\n".join(parts),
                provider=session.harness.provider,
                model=session.harness.model,
                working_directory=session.harness.cwd,
                sandbox_backend=session.harness.spec.execution_policy.sandbox,
            )
            async for event in stream:
                await self.dispatch_event(identity, event, tracker, namespace, message_ids)
            await self.resolve_approvals(identity, namespace)
        except asyncio.CancelledError:
            reason = "cancelled"
        except Exception:
            reason = "error"
            error = {"code": -32603, "message": "Harness execution failed"}
        finally:
            if reason == "cancelled":
                await self._finish_descendants(identity)
            # Finalize unfinished foreground calls before reporting idle.
            for tool in list(self.registry.get(identity).tools.values()):
                if (
                    tool.get("status") in {"pending", "in_progress", "paused"}
                    and tool["toolCallId"] not in session.background
                ):
                    await self.emit(
                        identity,
                        {
                            "sessionUpdate": "tool_call_update",
                            "toolCallId": tool["toolCallId"],
                            "status": "cancelled" if reason == "cancelled" else "failed",
                        },
                    )
            await self.emit(
                identity,
                {
                    **self.state_update(identity, state="idle"),
                    "stopReason": reason,
                    **({"error": error} if error else {}),
                },
            )

    async def dispatch_event(self, identity, event, tracker, namespace, messages):
        data, kind = dict(event.data or {}), event.type
        if kind in {"subagent_start", "subagent_result", "subagent_message"}:
            await self.subagent_event(identity, kind, data)
            return
        if kind in {"delta", "model_delta", "thinking"}:
            if kind == "thinking" and not self.live[identity].thoughts:
                return
            if data.get("text"):
                thought = kind == "thinking"
                await self.emit(
                    identity,
                    {
                        "sessionUpdate": "agent_thought_chunk"
                        if thought
                        else "agent_message_chunk",
                        "messageId": messages["thought" if thought else "message"],
                        "content": {"type": "text", "text": data["text"]},
                    },
                )
        elif kind == "tool_call":
            name = str(data.get("tool_name") or "tool")
            call_id = namespace + "-" + tracker.start(name)
            await self.emit(
                identity,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": call_id,
                    "name": name,
                    "title": _tool_title(name, data.get("arguments")),
                    "kind": _tool_kind(name),
                    "status": "in_progress",
                    "rawInput": data.get("arguments"),
                },
            )
        elif kind == "tool_result":
            name = str(data.get("tool_name") or "tool")
            previous = tracker.finish(name)
            call_id = namespace + "-" + (previous or tracker.start(name))
            output = (
                data.get("output")
                if data.get("success", True)
                else data.get("error") or data.get("output")
            )
            update = {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call_id,
                "name": name,
                "status": "completed" if data.get("success", True) else "failed",
                "rawOutput": output,
            }
            if output:
                update["content"] = [
                    {"type": "content", "content": {"type": "text", "text": _clip(output)}}
                ]
            await self.emit(identity, update)
        elif kind in {
            "plan_update",
            "plan_removed",
            "terminal_update",
            "terminal_output_chunk",
            "tool_call_content_chunk",
        }:
            await self.emit(identity, {"sessionUpdate": kind, **data})

    async def resolve_approvals(self, identity, namespace):
        session = self.live[identity].harness.session
        while pending := session.pending_approvals():
            item = pending[0]
            name = str(item.get("tool_name") or "tool")
            tool = {
                "toolCallId": namespace + "-approval-" + uuid.uuid4().hex,
                "name": name,
                "title": _tool_title(name, item.get("arguments")),
                "kind": _tool_kind(name),
                "status": "pending",
                "rawInput": item.get("arguments"),
            }
            await self.emit(identity, {"sessionUpdate": "tool_call_update", **tool})
            await self.emit(identity, self.state_update(identity, state="requires_action"))
            response = await self.connection.request(
                "session/request_permission",
                sessionId=identity,
                title="Allow " + tool["title"] + "?",
                subject={"type": "tool_call", "toolCall": tool},
                options=[
                    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
                    {"optionId": "allow_always", "name": "Always allow", "kind": "allow_always"},
                    {"optionId": "reject_once", "name": "Reject", "kind": "reject_once"},
                ],
            )
            validate_v2("RequestPermissionResponse", response)
            outcome = response["outcome"]
            selected = outcome.get("optionId") if outcome.get("outcome") == "selected" else None
            if selected in {"allow_once", "allow_always"}:
                result = await session.approve_pending(0, always=selected == "allow_always")
                status = "completed"
            else:
                result = await session.reject_pending(
                    0, message="Rejected or dismissed in ACP client"
                )
                status = "cancelled"
            await self.emit(
                identity,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": tool["toolCallId"],
                    "status": status,
                },
            )
            await self.emit(identity, self.state_update(identity, state="running"))
            text = getattr(result, "content", "")
            if text:
                await self.emit(
                    identity,
                    {
                        "sessionUpdate": "agent_message",
                        "messageId": "msg-" + uuid.uuid4().hex,
                        "content": [{"type": "text", "text": text}],
                    },
                )

    async def subagent_event(self, parent, kind, data):
        root_id = parent
        source_id = str(data.get("agent_id") or data.get("session_id") or "")
        if not source_id:
            return
        parent = self.child_ids.get((root_id, str(data.get("parent_id") or "")), root_id)
        identity = self.child_ids.get((root_id, source_id))
        if identity is None:
            identity = (
                "child-" + hashlib.sha256(f"{root_id}\0{source_id}".encode()).hexdigest()[:32]
            )
            self.child_ids[root_id, source_id] = identity
            root = self.live[root_id].harness.cwd
            try:
                self.ledger.get(identity)
            except ProtocolError:
                self.ledger.create(identity, str(root), {"parent": parent})
            await self.emit(
                parent,
                {
                    "sessionUpdate": "subagent_update",
                    "sessionId": identity,
                    "title": source_id,
                    "cwd": str(root),
                    "capabilities": {},
                },
            )
        if kind == "subagent_start":
            if data.get("prompt"):
                await self.emit(
                    identity,
                    {
                        "sessionUpdate": "session_message",
                        "messageId": "msg-" + uuid.uuid4().hex,
                        "senderSessionId": parent,
                        "recipientSessionId": identity,
                        "content": [{"type": "text", "text": str(data["prompt"])}],
                    },
                )
            child_state = self.state_update(identity, state="running")
            await self.emit(identity, child_state)
            await self.emit(
                parent,
                {
                    "sessionUpdate": "subagent_update",
                    "sessionId": identity,
                    "state": {k: v for k, v in child_state.items() if k != "sessionUpdate"},
                },
            )
        elif kind == "subagent_result":
            text = data.get("result") or data.get("error")
            if text:
                await self.emit(
                    identity,
                    {
                        "sessionUpdate": "agent_message",
                        "messageId": "msg-" + uuid.uuid4().hex,
                        "content": [{"type": "text", "text": str(text)}],
                    },
                )
            reason = "error" if data.get("error") else "end_turn"
            child_state = {**self.state_update(identity, state="idle"), "stopReason": reason}
            await self.emit(identity, child_state)
            await self.emit(
                parent,
                {
                    "sessionUpdate": "subagent_update",
                    "sessionId": identity,
                    "state": {k: v for k, v in child_state.items() if k != "sessionUpdate"},
                },
            )
        if kind in {"subagent_start", "subagent_result"}:
            ancestor = parent
            while ancestor:
                await self.emit(ancestor, self.state_update(ancestor))
                ancestor = self.registry.get(ancestor).parent_id
        else:
            await self.emit(
                identity,
                {
                    "sessionUpdate": "session_message",
                    "messageId": "msg-" + uuid.uuid4().hex,
                    "senderSessionId": parent,
                    "recipientSessionId": identity,
                    "content": [{"type": "text", "text": str(data.get("message") or "")}],
                },
            )

    def state_update(self, identity, *, state=None):
        session = self.registry.get(identity)
        live = self.live.get(identity)
        background = [entry["reference"] for entry in live.background.values()] if live else []
        for child_id in session.children:
            child_state = self.state_update(child_id)
            if child_state["state"] != "idle" or child_state["background"]:
                background.append({"type": "subagent", "sessionId": child_id})
        return {
            "sessionUpdate": "state_update",
            "state": state or session.state,
            "background": background,
        }

    async def emit(self, identity, update, *, retain=True):
        validate_v2("UpdateSessionNotification", {"sessionId": identity, "update": update})
        owner = identity
        while owner not in self.live:
            owner = self.ledger.get(owner)["metadata"]["parent"]
        lock = self.live[owner].lock
        async with lock:
            self.registry.apply(identity, update)
            if retain and update["sessionUpdate"] not in {
                "state_update",
                "notice",
                "usage_update",
                "session_info_update",
                "config_option_update",
                "available_commands_update",
                "replay_complete",
            }:
                self.ledger.append(identity, update)
            await self.connection.notify("session/update", sessionId=identity, update=update)

    async def register_background(
        self,
        identity: str,
        item_id: str,
        task: asyncio.Task,
        *,
        terminal=False,
        title="Background work",
    ):
        session = self._session(identity)
        field_name, kind = ("terminalId", "terminal") if terminal else ("toolCallId", "tool_call")
        update = {
            "sessionUpdate": "terminal_update" if terminal else "tool_call_update",
            field_name: item_id,
            "capabilities": {"cancel": {}},
        }
        update.update({"command": title} if terminal else {"title": title, "status": "in_progress"})
        await self.emit(identity, update)
        session.background[item_id] = {
            "task": task,
            "reference": {"type": kind, field_name: item_id},
        }
        await self.emit(identity, self.state_update(identity))

        async def finished():
            status = "completed"
            try:
                await task
            except asyncio.CancelledError:
                status = "cancelled"
            except Exception:
                status = "failed"
            try:
                await self.emit(
                    identity,
                    {
                        "sessionUpdate": "terminal_update" if terminal else "tool_call_update",
                        field_name: item_id,
                        **(
                            {
                                "exitStatus": {"exitCode": 0 if status == "completed" else None},
                                "capabilities": {},
                            }
                            if terminal
                            else {"status": status, "capabilities": {}}
                        ),
                    },
                )
                session.background.pop(item_id, None)
                await self.emit(identity, self.state_update(identity))
            except (ConnectionError, BrokenPipeError):
                session.background.pop(item_id, None)

        session.background[item_id]["monitor"] = asyncio.create_task(finished())

    async def cancel_item(self, identity, params, *, terminal=False):
        session = self._session(identity)
        item = session.background.get(params["terminalId" if terminal else "toolCallId"])
        if item is None or item["reference"]["type"] != ("terminal" if terminal else "tool_call"):
            raise ProtocolError(-32601, "Item does not support cancellation")
        item["task"].cancel()
        await item["monitor"]
        return {}

    async def cancel(self, identity):
        session = self._session(identity)
        await self._cancel_work(session)

    async def _cancel_work(self, session):
        async with session.admission_lock:
            session.cancel_epoch += 1
            for pending in list(session.queue):
                if not pending.future.done():
                    pending.future.set_exception(ProtocolError(-32800, "Held prompt cancelled"))
            session.queue.clear()
            session.pending.clear()
            work = session.work
            if work and not work.done():
                work.cancel()
                cancel = getattr(session.harness.session, "cancel", None)
                if cancel:
                    await cancel()
                await asyncio.gather(work, return_exceptions=True)

    async def close_session(self, identity):
        session = self._session(identity)
        # Reject new admissions immediately, including while backend cancellation waits.
        session.active = False
        await self._cancel_work(session)
        for item in list(session.background.values()):
            item["task"].cancel()
            await asyncio.gather(item["monitor"], return_exceptions=True)
        await self._finish_descendants(identity)
        if session.runner:
            await asyncio.gather(session.runner, return_exceptions=True)

    async def _finish_descendants(self, identity):
        for child in self.registry.get(identity).children:
            await self._finish_descendants(child)
            state = self.registry.get(child)
            if state.state != "idle":
                await self.emit(
                    child,
                    {
                        "sessionUpdate": "state_update",
                        "state": "idle",
                        "stopReason": "cancelled",
                        "background": [],
                    },
                )
                await self.emit(
                    identity,
                    {
                        "sessionUpdate": "subagent_update",
                        "sessionId": child,
                        "state": {"state": "idle", "stopReason": "cancelled", "background": []},
                    },
                )

    async def shutdown(self):
        for identity in list(self.live):
            if self.live[identity].active:
                try:
                    await self.close_session(identity)
                except (ConnectionError, BrokenPipeError):
                    pass
        self.ledger.close()
