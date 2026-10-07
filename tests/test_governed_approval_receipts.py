"""Consent and MCP mediation regressions; no provider or network calls."""

from types import SimpleNamespace

import pytest

from superqode.agent.loop import AgentConfig, ToolApprovalRequired
from superqode.agent.hooks import BEFORE_TOOL_CALL, HookDecision
from superqode.governance import (
    ContextualPolicyEngine,
    ContextualPolicyRule,
    CredentialBroker,
    GovernanceBundle,
    PolicyLayer,
    governance_scope,
)
from superqode.runtime.builtin import BuiltinRuntime
from superqode.tools.base import Tool, ToolRegistry, ToolResult
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager


class RecordingTool(Tool):
    name = "probe"
    description = "Record an invocation"
    parameters = {"type": "object"}

    def __init__(self):
        self.calls = []

    async def execute(self, args, ctx):
        self.calls.append(dict(args))
        return ToolResult(True, "PRIVATE_RESULT_MARKER")


def bundle(action="ask", phase="tool_call", tool="probe", revision="rule"):
    return GovernanceBundle(
        ContextualPolicyEngine(
            (
                PolicyLayer(
                    "project",
                    "test",
                    rules=(ContextualPolicyRule(revision, action, phases=(phase,), tools=(tool,)),),
                ),
            )
        ),
        CredentialBroker(),
    )


def runtime(tmp_path, *, mcp_executor=None):
    tool = RecordingTool()
    registry = ToolRegistry.empty()
    registry.register(tool)
    return BuiltinRuntime(
        gateway=SimpleNamespace(),
        tools=registry,
        config=AgentConfig("test", "test", working_directory=tmp_path),
        permission_manager=PermissionManager(PermissionConfig(default=Permission.ALLOW)),
        mcp_executor=mcp_executor,
    ), tool


async def park(rt, name="probe"):
    with pytest.raises(ToolApprovalRequired):
        await rt.loop._execute_tool(name, {"value": "original"}, "call-1")


async def test_contextual_ask_approved_executes_once_and_next_call_asks(tmp_path):
    rt, tool = runtime(tmp_path)
    with governance_scope(bundle()):
        await park(rt)
        response = await rt.approve_and_resume()
        assert not response.error
        assert tool.calls == [{"value": "original"}]
        assert not rt.loop._approval_receipts
        with pytest.raises(RuntimeError, match="No pending"):
            await rt.approve_and_resume()
        await park(rt)
        assert len(tool.calls) == 1


async def test_policy_revision_change_requires_fresh_consent(tmp_path):
    rt, tool = runtime(tmp_path)
    with governance_scope(bundle(revision="old")):
        await park(rt)
    with governance_scope(bundle(revision="new")):
        response = await rt.approve_and_resume()
        assert response.stopped_reason == "needs_approval"
        assert not tool.calls
        response = await rt.approve_and_resume()
        assert not response.error
        assert len(tool.calls) == 1


async def test_new_deny_cannot_be_overridden_by_approval(tmp_path):
    rt, tool = runtime(tmp_path)
    with governance_scope(bundle()):
        await park(rt)
    with governance_scope(bundle("deny")):
        response = await rt.approve_and_resume()
    assert response.error
    assert not tool.calls
    assert not rt.loop._approval_receipts


async def test_hook_rewrite_invalidates_consent(tmp_path):
    rt, tool = runtime(tmp_path)
    with governance_scope(bundle()):
        await park(rt)
        rt.loop.hooks.register(
            BEFORE_TOOL_CALL,
            lambda *args: HookDecision(action="modify", arguments={"value": "rewritten"}),
        )
        response = await rt.approve_and_resume()
        assert response.stopped_reason == "needs_approval"
        assert rt.get_pending_approvals()[0]["arguments"] == {"value": "rewritten"}
        assert not tool.calls


async def test_dynamic_mcp_result_is_suppressed(tmp_path):
    calls = []

    async def executor(server, tool, args):
        calls.append((server, tool))
        return ToolResult(True, "PRIVATE_RESULT_MARKER")

    rt, _ = runtime(tmp_path, mcp_executor=executor)
    with governance_scope(bundle("deny", "tool_result", "mcp_probe_echo")):
        result = await rt.loop._execute_tool("mcp_probe_echo", {}, "mcp-1")
    assert calls == [("probe", "echo")]
    assert not result.success
    assert "PRIVATE_RESULT_MARKER" not in result.to_message()


async def test_dynamic_mcp_ask_and_approve_use_same_boundary(tmp_path):
    calls = []

    async def executor(server, tool, args):
        calls.append(args)
        return ToolResult(True, "ok")

    rt, _ = runtime(tmp_path, mcp_executor=executor)
    with governance_scope(bundle(tool="mcp_probe_echo")):
        await park(rt, "mcp_probe_echo")
        assert not calls
        response = await rt.approve_and_resume()
    assert not response.error
    assert calls == [{"value": "original"}]


async def test_receipt_cannot_be_reused_through_same_context(tmp_path):
    from superqode.tools.approval_receipts import issue_receipt
    from superqode.tools.base import ToolContext
    from superqode.tools.governed import execute_governed_tool

    tool = RecordingTool()
    with governance_scope(bundle()):
        receipt = issue_receipt(
            SimpleNamespace(),
            {
                "tool_name": "probe",
                "arguments": {},
                "tool_call_id": "once",
            },
        )
        context = ToolContext("session", tmp_path, invocation_id="once", approval_receipt=receipt)
        first = await execute_governed_tool(tool, {}, context)
        second = await execute_governed_tool(tool, {}, context)
    assert first.success
    assert not second.success
    assert tool.calls == [{}]


async def test_lost_governance_scope_fails_closed_on_resume(tmp_path):
    rt, tool = runtime(tmp_path)
    with governance_scope(bundle()):
        await park(rt)
    with pytest.raises(RuntimeError, match="Original approval policy scope"):
        await rt.approve_and_resume()
    assert not tool.calls
    assert rt.get_pending_approvals()


async def test_current_project_policy_is_reloaded_before_resume(tmp_path):
    import yaml

    path = tmp_path / ".superqode" / "policy.yaml"
    path.parent.mkdir()
    policy = {"rules": [{"id": "probe", "tool": "probe", "action": "ask"}]}
    path.write_text(yaml.safe_dump(policy))
    rt, tool = runtime(tmp_path)
    await park(rt)
    policy["rules"][0]["action"] = "deny"
    path.write_text(yaml.safe_dump(policy))
    response = await rt.approve_and_resume()
    assert response.error
    assert not tool.calls
