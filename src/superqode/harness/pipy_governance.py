"""Host policy boundary; PiPy keeps its independent tool API."""

from __future__ import annotations

from dataclasses import fields

from superqode.governance import (
    active_governance,
    evaluate_active_policy,
    model_supplied_secret_headers,
)
from superqode.pipy.messages import TextContent
from superqode.pipy.tools.base import AgentTool, AgentToolResult
from superqode.pipy.harness_events import ToolResultPatch
from superqode.tools.permissions import TOOL_GROUPS, PermissionManager


def _denied(reason):
    return AgentToolResult(content=[TextContent(reason)], details={"governance_denied": True})


def _call_policy(tool, args):
    bundle = active_governance()
    if bundle is None:
        return None
    if bundle.block_model_credentials and model_supplied_secret_headers(args):
        return _denied("Credential-bearing headers require a named host credential binding")
    aliases = {
        "read": "read_file",
        "write": "write_file",
        "edit": "edit_file",
        "mcp_call": "mcp_execute",
    }
    name = aliases.get(tool.name, tool.name)
    group = TOOL_GROUPS.get(name)
    decision = evaluate_active_policy(
        "tool_call",
        tool=name,
        tool_group=group.value if group else "",
        risk=PermissionManager().get_risk_level(name, args),
        arguments=args,
    )
    if decision.action != "allow":
        return _denied(f"Contextual policy {decision.action} for {tool.name}: {decision.reason}")
    return None


def _result_policy(tool, result):
    if active_governance() is not None:
        aliases = {
            "read": "read_file",
            "write": "write_file",
            "edit": "edit_file",
            "mcp_call": "mcp_execute",
        }
        name = aliases.get(tool.name, tool.name)
        group = TOOL_GROUPS.get(name)
        decision = evaluate_active_policy(
            "tool_result",
            tool=name,
            tool_group=group.value if group else "",
            arguments={
                "success": not bool(
                    isinstance(result.details, dict) and result.details.get("governance_denied")
                ),
                "output": result.text,
                "output_length": len(result.text),
            },
        )
        if decision.action != "allow":
            return _denied("Contextual policy suppressed tool result")
    return result


class _GovernedAgentTool(AgentTool):
    async def execute(self, tool_call_id, args, signal=None, on_update=None):
        # These checks surround recovery too: current authority controls reuse.
        denied = _call_policy(self, args)
        if denied is not None:
            return denied
        result = await super().execute(tool_call_id, args, signal, on_update)
        return _result_policy(self, result)


def guard_pipy_tools(tools):
    def guard(tool):
        async def execute(call_id, args, signal=None, on_update=None):
            # Suppress before recovery commits the output to its private ledger.
            return _result_policy(tool, await tool.execute_fn(call_id, args, signal, on_update))

        values = {field.name: getattr(tool, field.name) for field in fields(tool)}
        values["execute_fn"] = execute
        return _GovernedAgentTool(**values)

    return [guard(tool) for tool in tools]


def mark_policy_denial(event):
    if isinstance(event.details, dict) and event.details.get("governance_denied"):
        return ToolResultPatch(is_error=True)
    return None
