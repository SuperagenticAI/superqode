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


class DynamicTool(Tool):
    """Adapt a host executor to the same policy/storage boundary as local tools."""

    description = "Dynamic host tool"
    parameters = {"type": "object"}

    def __init__(self, name, executor):
        self._name = name
        self._executor = executor

    @property
    def name(self):
        return self._name

    async def execute(self, args, ctx):
        return await self._executor(args)


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
    from .approval_receipts import ApprovalReceipt

    receipt = ctx.approval_receipt
    approved_ask = (
        call_decision.action == "ask"
        and isinstance(receipt, ApprovalReceipt)
        and receipt.consume(ctx.invocation_id, tool.name, original)
    )
    if call_decision.action != "allow" and not approved_ask:
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
    from superqode.execution_recovery import recoverable_call

    def encode_outcome(result):
        storage_decision = evaluate_active_policy(
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
        if storage_decision.action != "allow":
            return {
                "success": False,
                "output": "",
                "error": "Contextual policy suppressed tool result",
                "metadata": {"governance": storage_decision.to_dict()},
            }
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "metadata": result.metadata,
        }

    result = await recoverable_call(
        identity=ctx.invocation_id,
        operation=f"tool.{tool.name}",
        inputs=original,
        execute=lambda: tool.execute(execution_args, ctx),
        encode=encode_outcome,
        decode=lambda result: ToolResult(**result),
        replay_safe=tool.replay_safe,
    )
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
        **(
            {"approval": {"invocation_id": ctx.invocation_id, "scope": "once"}}
            if approved_ask
            else {}
        ),
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
