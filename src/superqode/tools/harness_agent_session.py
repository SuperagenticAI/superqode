"""Persistent Omnigent-style sessions for HarnessSpec-declared agent tools."""

from __future__ import annotations

import re
from typing import Any

from .base import Tool, ToolContext, ToolResult


_NO_MANAGER_ERROR = "agent_session requires the builtin harness runtime with peer-agent support."


class AgentSessionTool(Tool):
    """Start, message, wait for, list, and close declared child agent sessions."""

    @property
    def name(self) -> str:
        return "agent_session"

    @property
    def description(self) -> str:
        return (
            "Manage persistent sessions for child agents declared in the active "
            "HarnessSpec, including Omnigent-style agent tools. Use action=start "
            "to launch a named child agent, resume to reattach a saved session, send "
            "for follow-up input, wait to collect its latest result, list to see "
            "sessions, approve/reject to decide pending child approvals, and "
            "close when finished."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "start",
                        "resume",
                        "send",
                        "wait",
                        "list",
                        "info",
                        "history",
                        "children",
                        "handoff",
                        "approve",
                        "reject",
                        "close",
                    ],
                    "description": "Session operation to perform.",
                },
                "agent": {
                    "type": "string",
                    "description": "Declared child agent id or active session/task name.",
                },
                "message": {
                    "type": "string",
                    "description": "Task brief or follow-up message for start/send.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Stable child session id for start/resume/info/history/handoff.",
                },
                "title": {
                    "type": "string",
                    "description": "Named child session title. start reuses the same agent+title child when available.",
                },
                "target_session_id": {
                    "type": "string",
                    "description": "For handoff: destination session id.",
                },
                "reason": {
                    "type": "string",
                    "description": "For handoff: why work is moving to the target session.",
                },
                "interrupt": {
                    "type": "boolean",
                    "description": "For send: cancel current work and redirect immediately.",
                },
                "timeout_s": {
                    "type": "integer",
                    "description": "For wait: maximum seconds to wait. For history: max messages. Default 60.",
                },
                "index": {
                    "type": "integer",
                    "description": "For approve/reject: pending approval index. Default 0.",
                },
                "always": {
                    "type": "boolean",
                    "description": "For approve/reject: remember the decision when supported.",
                },
            },
            "required": ["action"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        manager = getattr(ctx, "peer_manager", None)
        if manager is None:
            return ToolResult(success=False, output="", error=_NO_MANAGER_ERROR)

        action = str(args.get("action") or "").strip().lower()
        if action == "list":
            return _list_sessions(ctx, manager)
        if action == "children":
            return _children(ctx, args)

        target = str(args.get("agent") or "").strip()
        session_target = str(args.get("session_id") or target).strip()
        if action in {"info", "history", "handoff"}:
            if not session_target:
                return ToolResult(
                    success=False, output="", error="'session_id' or 'agent' is required"
                )
            if action == "info":
                return _info(session_target)
            if action == "history":
                return _history(session_target, args.get("timeout_s"))
            return _handoff(ctx, session_target, args)

        if not target:
            return ToolResult(success=False, output="", error="'agent' is required")

        if action == "start":
            return await _start_session(
                ctx,
                manager,
                target,
                str(args.get("message") or ""),
                session_id=str(args.get("session_id") or "").strip() or None,
                title=str(args.get("title") or "").strip() or None,
            )
        if action == "resume":
            return await _resume_session(
                ctx,
                manager,
                target,
                session_id=str(args.get("session_id") or "").strip() or None,
            )
        if action == "send":
            return await _send_session(
                ctx,
                manager,
                target,
                str(args.get("message") or ""),
                interrupt=bool(args.get("interrupt", False)),
            )
        if action == "wait":
            return await _wait_session(manager, target, args.get("timeout_s"))
        if action == "approve":
            return await _approve_session(
                manager,
                target,
                args.get("index"),
                always=bool(args.get("always", False)),
            )
        if action == "reject":
            return await _reject_session(
                manager,
                target,
                args.get("index"),
                message=str(args.get("message") or ""),
                always=bool(args.get("always", False)),
            )
        if action == "close":
            return await _close_session(manager, target)
        return ToolResult(
            success=False,
            output="",
            error=(
                "action must be one of: start, resume, send, wait, list, info, history, "
                "children, handoff, approve, reject, close"
            ),
        )


def _declared_child_agents(ctx: ToolContext) -> dict[str, Any]:
    spec = getattr(ctx, "harness_spec", None)
    agents = getattr(spec, "agents", ()) if spec is not None else ()
    if not agents:
        return {}
    primary = agents[0]
    delegated = set(getattr(primary, "delegates_to", ()) or ())
    by_id = {str(agent.id): agent for agent in agents}
    return {agent_id: by_id[agent_id] for agent_id in delegated if agent_id in by_id}


def _resolve_declared_agent(ctx: ToolContext, target: str) -> Any | None:
    declared = _declared_child_agents(ctx)
    if target in declared:
        return declared[target]
    normalized_target = _normalize_name(target)
    for agent_id, agent in declared.items():
        if _normalize_name(agent_id) == normalized_target:
            return agent
    return None


async def _start_session(
    ctx: ToolContext,
    manager: Any,
    agent_id: str,
    message: str,
    *,
    session_id: str | None,
    title: str | None,
) -> ToolResult:
    declared = _resolve_declared_agent(ctx, agent_id)
    if declared is None:
        available = ", ".join(sorted(_declared_child_agents(ctx))) or "none"
        return ToolResult(
            success=False,
            output="",
            error=f"Unknown declared child agent {agent_id!r}. Available: {available}",
        )
    message = message.strip()
    if not message:
        return ToolResult(success=False, output="", error="'message' is required for start")
    if session_id is None and title:
        from superqode.session.switchboard import SessionGraphStore

        existing = SessionGraphStore().find_named_child(
            str(ctx.session_id), str(declared.id), title
        )
        if existing is not None:
            session_id = existing.session_id
    try:
        session = await manager.spawn(str(declared.id), message, session_id=session_id)
    except RuntimeError as exc:
        return ToolResult(success=False, output="", error=str(exc))
    if title and hasattr(manager, "update_graph_metadata"):
        manager.update_graph_metadata(session.session_id, title=title, agent_id=str(declared.id))
    return ToolResult(
        success=True,
        output=(
            f"Started child agent session '{session.task_name}' for declared agent "
            f"{declared.id!r} (id {session.agent_id}, session {session.session_id}). "
            "Use agent_session wait/send/close."
        ),
        metadata={
            "agent_id": session.agent_id,
            "task_name": session.task_name,
            "session_id": session.session_id,
            "declared_agent": declared.id,
            "title": title or session.task_name,
            "status": session.status,
        },
    )


async def _resume_session(
    ctx: ToolContext,
    manager: Any,
    agent_id: str,
    *,
    session_id: str | None,
) -> ToolResult:
    declared = _resolve_declared_agent(ctx, agent_id)
    if declared is None:
        available = ", ".join(sorted(_declared_child_agents(ctx))) or "none"
        return ToolResult(
            success=False,
            output="",
            error=f"Unknown declared child agent {agent_id!r}. Available: {available}",
        )
    try:
        session = await manager.resume(str(declared.id), session_id=session_id)
    except RuntimeError as exc:
        return ToolResult(success=False, output="", error=str(exc))
    return ToolResult(
        success=True,
        output=(
            f"Resumed child agent session '{session.task_name}' for declared agent "
            f"{declared.id!r} (id {session.agent_id}, session {session.session_id})."
        ),
        metadata={
            "agent_id": session.agent_id,
            "task_name": session.task_name,
            "session_id": session.session_id,
            "declared_agent": declared.id,
            "status": session.status,
        },
    )


async def _send_session(
    ctx: ToolContext,
    manager: Any,
    target: str,
    message: str,
    *,
    interrupt: bool,
) -> ToolResult:
    if manager.resolve(target) is None and _resolve_declared_agent(ctx, target) is None:
        return ToolResult(
            success=False, output="", error=f"No child agent session matching {target!r}"
        )
    message = message.strip()
    if not message:
        return ToolResult(success=False, output="", error="'message' is required for send")
    try:
        mode = await manager.send_input(target, message, interrupt=interrupt)
    except (KeyError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=str(exc))
    return ToolResult(
        success=True,
        output=f"Message delivered to child agent session ({mode}).",
        metadata={"delivery": mode},
    )


async def _wait_session(manager: Any, target: str, timeout_value: Any) -> ToolResult:
    try:
        timeout = float(timeout_value or 60)
    except (TypeError, ValueError):
        timeout = 60.0
    try:
        outcome = await manager.wait(target, timeout_s=timeout)
    except KeyError as exc:
        return ToolResult(success=False, output="", error=str(exc))
    if not outcome["done"]:
        return ToolResult(
            success=True,
            output=f"Child agent '{outcome['task_name']}' is still {outcome['status']}.",
            metadata=outcome,
        )
    return ToolResult(
        success=True,
        output=f"Child agent '{outcome['task_name']}' ({outcome['status']}):\n{outcome['result']}",
        metadata=outcome,
    )


async def _approve_session(
    manager: Any,
    target: str,
    index_value: Any,
    *,
    always: bool,
) -> ToolResult:
    try:
        index = int(index_value or 0)
    except (TypeError, ValueError):
        index = 0
    try:
        outcome = await manager.approve(target, index=index, always=always)
    except (KeyError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=str(exc))
    return ToolResult(
        success=True,
        output=(
            f"Approved child agent '{outcome['task_name']}' approval {index} "
            f"({outcome['status']}):\n{outcome['result']}"
        ),
        metadata=outcome,
    )


async def _reject_session(
    manager: Any,
    target: str,
    index_value: Any,
    *,
    message: str,
    always: bool,
) -> ToolResult:
    try:
        index = int(index_value or 0)
    except (TypeError, ValueError):
        index = 0
    try:
        outcome = await manager.reject(
            target,
            index=index,
            message=message.strip() or None,
            always=always,
        )
    except (KeyError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=str(exc))
    return ToolResult(
        success=True,
        output=(
            f"Rejected child agent '{outcome['task_name']}' approval {index} "
            f"({outcome['status']}):\n{outcome['result']}"
        ),
        metadata=outcome,
    )


async def _close_session(manager: Any, target: str) -> ToolResult:
    closed = await manager.close(target)
    if not closed:
        return ToolResult(
            success=False, output="", error=f"No child agent session matching {target!r}"
        )
    return ToolResult(success=True, output=f"Closed child agent session {target}.")


def _list_sessions(ctx: ToolContext, manager: Any) -> ToolResult:
    declared = sorted(_declared_child_agents(ctx))
    sessions = manager.list_agents()
    from superqode.session.switchboard import SessionSwitchboard

    durable_children = []
    if getattr(ctx, "session_id", None):
        try:
            durable_children = SessionSwitchboard().children(str(ctx.session_id))
        except Exception:
            durable_children = []
    if not sessions:
        declared_text = ", ".join(declared) if declared else "none"
        return ToolResult(
            success=True,
            output=f"No active child agent sessions. Declared child agents: {declared_text}",
            metadata={
                "agents": [],
                "durable_children": durable_children,
                "declared_agents": declared,
            },
        )
    rows = [
        f"{item['agent_id']}  {item['task_name']:<20}  {item['session_id']:<28}  "
        f"{item['status']:<14}  {item['last_result_preview']}"
        for item in sessions
    ]
    return ToolResult(
        success=True,
        output="agent_id  task_name  session_id  status  last_result\n" + "\n".join(rows),
        metadata={
            "agents": sessions,
            "durable_children": durable_children,
            "declared_agents": declared,
        },
    )


def _info(session_id: str) -> ToolResult:
    from superqode.session.switchboard import SessionSwitchboard

    try:
        payload = SessionSwitchboard().info(session_id)
    except KeyError as exc:
        return ToolResult(success=False, output="", error=str(exc))
    return ToolResult(
        success=True,
        output=json_dumps(payload),
        metadata=payload,
    )


def _history(session_id: str, limit_value: Any) -> ToolResult:
    from superqode.session.switchboard import SessionSwitchboard

    try:
        limit = int(limit_value or 20)
    except (TypeError, ValueError):
        limit = 20
    try:
        payload = SessionSwitchboard().history(session_id, limit=limit)
    except KeyError as exc:
        return ToolResult(success=False, output="", error=str(exc))
    lines = [
        f"{item['timestamp']} {item['role']}: {str(item['content']).strip()[:240]}"
        for item in payload["messages"]
    ]
    return ToolResult(success=True, output="\n".join(lines), metadata=payload)


def _children(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    from superqode.session.switchboard import SessionSwitchboard

    session_id = str(args.get("session_id") or getattr(ctx, "session_id", "") or "").strip()
    if not session_id:
        return ToolResult(success=False, output="", error="'session_id' is required")
    try:
        payload = SessionSwitchboard().children(session_id)
    except KeyError as exc:
        return ToolResult(success=False, output="", error=str(exc))
    rows = [
        f"{item['session_id']}  {item['agent_id'] or '-'}  {item['status']}  {item['title']}"
        for item in payload
    ]
    return ToolResult(
        success=True, output="\n".join(rows) or "No child sessions.", metadata={"children": payload}
    )


def _handoff(ctx: ToolContext, source_session_id: str, args: dict[str, Any]) -> ToolResult:
    from superqode.session.switchboard import SessionSwitchboard

    try:
        packet = SessionSwitchboard().make_handoff(
            source_session_id,
            target_session_id=str(args.get("target_session_id") or ""),
            target_agent=str(args.get("agent") or ""),
            goal=str(args.get("message") or ""),
            reason=str(args.get("reason") or ""),
        )
    except KeyError as exc:
        return ToolResult(success=False, output="", error=str(exc))
    return ToolResult(success=True, output=packet.to_message(), metadata=packet.to_dict())


def json_dumps(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=False)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")


__all__ = ["AgentSessionTool"]
