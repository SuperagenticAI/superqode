"""Common contextual-policy wrapper for SuperQode tool execution."""

from __future__ import annotations

from typing import Any, Mapping

from superqode.governance import (
    active_governance,
    evaluate_active_policy,
    model_supplied_secret_headers,
)

from .base import Tool, ToolContext, ToolResult
from .permissions import TOOL_GROUPS, PermissionManager


async def execute_governed_tool(
    tool: Tool,
    arguments: Mapping[str, Any],
    ctx: ToolContext,
) -> ToolResult:
    """Evaluate call/result policy and inject host-bound credentials behind the model."""
    original = dict(arguments)
    group = TOOL_GROUPS.get(tool.name)
    group_name = group.value if group is not None else ""
    risk = PermissionManager().get_risk_level(tool.name, original)
    bundle = active_governance()
    secret_headers = model_supplied_secret_headers(original)
    if bundle is not None and bundle.block_model_credentials and secret_headers:
        return ToolResult(
            success=False,
            output="",
            error=(
                "Credential-bearing headers must use a named SuperQode credential binding: "
                + ", ".join(secret_headers)
            ),
            metadata={"governance": {"phase": "tool_call", "action": "deny"}},
        )
    call_decision = evaluate_active_policy(
        "tool_call",
        tool=tool.name,
        tool_group=group_name,
        risk=risk,
        arguments=original,
    )
    if call_decision.action != "allow":
        verb = "requires approval" if call_decision.action == "ask" else "was denied"
        return ToolResult(
            success=False,
            output="",
            error=f"Contextual policy {verb} for tool {tool.name}: {call_decision.reason}",
            metadata={"governance": call_decision.to_dict()},
        )
    execution_args = original
    credential_evidence: dict[str, Any] = {}
    if bundle is not None and "credential" in original:
        if tool.name not in {"fetch", "web_fetch"}:
            return ToolResult(
                success=False,
                output="",
                error=f"Credential bindings are not supported by tool {tool.name}",
                metadata={"governance": call_decision.to_dict()},
            )
        try:
            execution_args, credential_evidence = bundle.broker.inject(original)
        except ValueError as exc:
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                metadata={"governance": call_decision.to_dict()},
            )
    result = await tool.execute(execution_args, ctx)
    result_decision = evaluate_active_policy(
        "tool_result",
        tool=tool.name,
        tool_group=group_name,
        arguments={
            "success": result.success,
            "error": result.error or "",
            "output": result.output,
            "output_length": len(str(result.output or "")),
        },
    )
    evidence = {
        "tool_call": call_decision.to_dict(),
        "tool_result": result_decision.to_dict(),
        **({"credential": credential_evidence} if credential_evidence else {}),
    }
    if result_decision.action != "allow":
        return ToolResult(
            success=False,
            output="",
            error=f"Contextual policy suppressed tool result: {result_decision.reason}",
            metadata={**result.metadata, "governance": evidence},
        )
    return ToolResult(
        success=result.success,
        output=result.output,
        error=result.error,
        metadata={**result.metadata, "governance": evidence},
    )


__all__ = ["execute_governed_tool"]
