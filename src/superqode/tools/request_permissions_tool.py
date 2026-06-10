"""request_permissions: the model asks the user for an escalation.

Instead of failing repeatedly against ASK/deny prompts, the model can make
one explicit, justified request for session-scoped permission on specific
tools. The user sees the justification and approves or declines through the
normal approval flow; approval upgrades those tools from ASK to ALLOW for
the rest of the session. Hard denies (dangerous-command guards, deny
patterns, explicit DENY config) are never overridable.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Tool, ToolContext, ToolResult

MAX_TOOLS_PER_REQUEST = 5


class RequestPermissionsTool(Tool):
    """Ask the user to pre-approve specific tools for this session."""

    @property
    def name(self) -> str:
        return "request_permissions"

    @property
    def description(self) -> str:
        return (
            "Ask the user to grant session-wide permission for specific tools "
            "when repeated approval prompts would interrupt the work. Provide "
            "a clear justification. Approval upgrades those tools from "
            "ask-each-time to allowed for this session; explicit denies are "
            "never overridden. Use sparingly and only for tools you actually "
            "need repeatedly."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": f"Tool names to pre-approve (max {MAX_TOOLS_PER_REQUEST}).",
                },
                "justification": {
                    "type": "string",
                    "description": "Why these permissions are needed for the current task.",
                },
            },
            "required": ["tools", "justification"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        manager = getattr(ctx, "permission_manager", None)
        if manager is None:
            return ToolResult(
                success=False,
                output="",
                error="No permission manager available in this context.",
            )
        tools = args.get("tools") or []
        if isinstance(tools, str):
            tools = [tools]
        tools = [str(t).strip() for t in tools if str(t).strip()][:MAX_TOOLS_PER_REQUEST]
        justification = str(args.get("justification") or "").strip()
        if not tools:
            return ToolResult(success=False, output="", error="Provide at least one tool name.")
        if len(justification) < 10:
            return ToolResult(
                success=False,
                output="",
                error="Provide a real justification (one sentence minimum).",
            )

        granted: List[str] = []
        declined: List[str] = []
        for tool_name in tools:
            approved = await manager.request_permission(
                tool_name,
                {"escalation": True},
                description=(
                    f"Agent requests session-wide permission for '{tool_name}'. "
                    f"Justification: {justification}"
                ),
            )
            if approved:
                manager.grant_session_permission(tool_name)
                granted.append(tool_name)
            else:
                declined.append(tool_name)

        parts = []
        if granted:
            parts.append(
                "Granted for this session: " + ", ".join(granted) + ". Proceed without re-asking."
            )
        if declined:
            parts.append(
                "Declined: "
                + ", ".join(declined)
                + ". Do not retry the request; work within current permissions or ask the user directly."
            )
        return ToolResult(
            success=bool(granted),
            output="\n".join(parts),
            error=None if granted else "All permission requests were declined.",
            metadata={"granted": granted, "declined": declined},
        )


__all__ = ["MAX_TOOLS_PER_REQUEST", "RequestPermissionsTool"]
