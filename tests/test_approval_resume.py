"""An approved tool call must resume the model turn, not end it.

Regression: approving a paused tool call (Ask mode in the Mac app, the TUI
/approve command, ACP, channels) ran the tool and returned its raw output as
the final answer. The model never saw the result, so an approved `ls` ended
the turn with a file listing and the question went unanswered. This affected
every model on the builtin runtime, not only Gemini.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from superqode.agent.loop import AgentConfig
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
    ToolDefinition,
)
from superqode.runtime import BuiltinRuntime, create_runtime
from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager

# Gemini 3+ thinking models return a thought signature that LiteLLM carries in
# the tool call id. It has to come back unchanged on the follow-up request.
GEMINI_CALL_ID = "call_abc__thought__c2lnbmF0dXJl"


class ListTool(Tool):
    def __init__(self, name: str = "list_files", output: str = "a.py\nb.py\nREADME.md"):
        self._name = name
        self._output = output
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "List files."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"path": {"type": "string"}}}

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, output=self._output)


def _call(call_id: str, name: str, args: dict, index: int = 0) -> dict:
    return {
        "index": index,
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


class RecordingGateway(GatewayInterface):
    """Replays turns for both the streaming and the non-streaming loop."""

    def __init__(self, turns: List[dict]):
        self.turns = list(turns)
        self.requests: List[List[Message]] = []

    def _next(self, messages) -> dict:
        self.requests.append(list(messages))
        return self.turns.pop(0) if self.turns else {"content": "fallback"}

    async def chat_completion(self, messages, model, provider=None, **kwargs) -> GatewayResponse:
        turn = self._next(messages)
        return GatewayResponse(
            content=turn.get("content", ""),
            tool_calls=turn.get("tool_calls"),
            thinking_content=turn.get("thinking"),
            finish_reason="tool_calls" if turn.get("tool_calls") else "stop",
        )

    async def stream_completion(
        self, messages, model, provider=None, **kwargs
    ) -> AsyncIterator[StreamChunk]:
        turn = self._next(messages)
        if turn.get("thinking"):
            yield StreamChunk(thinking_content=turn["thinking"])
        if turn.get("content"):
            yield StreamChunk(content=turn["content"])
        if turn.get("tool_calls"):
            yield StreamChunk(tool_calls=turn["tool_calls"], finish_reason="tool_calls")
        else:
            yield StreamChunk(finish_reason="stop")

    async def test_connection(self, provider: str, model: Optional[str] = None) -> Dict[str, Any]:
        return {"ok": True}

    def get_model_string(self, provider: str, model: str) -> str:
        return f"{provider}/{model}"


def _tool_messages(request: List[Message]) -> List[Message]:
    return [m for m in request if getattr(m, "role", None) == "tool"]


def _runtime(gateway, *tools: Tool, ask: set[str] | None = None) -> BuiltinRuntime:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    ask = ask if ask is not None else {t.name for t in tools}
    permissions = PermissionConfig(
        default=Permission.ALLOW,
        tools={name: Permission.ASK for name in ask},
    )
    runtime = create_runtime(
        "builtin",
        gateway=gateway,
        tools=registry,
        config=AgentConfig(provider="google", model="gemini-4-neon"),
        parallel_tools=False,
        permission_manager=PermissionManager(permissions),
    )
    assert isinstance(runtime, BuiltinRuntime)
    return runtime


async def _stream(runtime: BuiltinRuntime, prompt: str) -> str:
    return "".join([chunk async for chunk in runtime.run_streaming(prompt)])


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_approved_tool_result_goes_back_to_model_and_turn_finishes(streaming):
    tool = ListTool()
    gateway = RecordingGateway(
        [
            {"tool_calls": [_call(GEMINI_CALL_ID, "list_files", {"path": "."})]},
            {"content": "The project has two Python files and a README."},
        ]
    )
    runtime = _runtime(gateway, tool)

    if streaming:
        await _stream(runtime, "What is in this project?")
    else:
        paused = await runtime.run("What is in this project?")
        assert paused.stopped_reason == "needs_approval"
    assert runtime.get_pending_approvals()[0]["tool_call_id"] == GEMINI_CALL_ID
    assert tool.calls == 0

    resumed = await runtime.approve_and_resume()

    assert resumed.stopped_reason == "complete"
    assert resumed.content == "The project has two Python files and a README."
    assert "README.md" not in resumed.content
    assert tool.calls == 1
    assert runtime.get_pending_approvals() == []
    # The model was called again with the tool output, keyed by the same id
    # (which carries Gemini's thought signature).
    assert len(gateway.requests) == 2
    follow_up = gateway.requests[1]
    tools = _tool_messages(follow_up)
    assert [m.tool_call_id for m in tools] == [GEMINI_CALL_ID]
    assert "README.md" in tools[0].content
    assistant = [m for m in follow_up if m.role == "assistant" and m.tool_calls]
    assert assistant[-1].tool_calls[0]["id"] == GEMINI_CALL_ID


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_empty_or_thinking_only_follow_up_is_reported_not_silent(streaming):
    gateway = RecordingGateway(
        [
            {"tool_calls": [_call("call-1", "list_files", {})]},
            {"content": "", "thinking": "I have the listing."},
            # The streaming loop retries an empty stream once without streaming.
            {"content": ""},
        ]
    )
    runtime = _runtime(gateway, ListTool())
    if streaming:
        await _stream(runtime, "list")
    else:
        await runtime.run("list")

    resumed = await runtime.approve_and_resume()

    # The streaming loop may retry once without streaming before it reports.
    assert len(gateway.requests) >= 2
    assert "README.md" not in resumed.content
    assert resumed.content.strip()
    assert "empty response" in resumed.content


@pytest.mark.asyncio
async def test_batch_keeps_calls_that_ran_before_the_pause():
    reader = ListTool("read_tree", "src/\ntests/")
    shell = ListTool("run_listing", "a.py\nb.py")
    gateway = RecordingGateway(
        [
            {
                "tool_calls": [
                    _call("call-read", "read_tree", {}, 0),
                    _call("call-bash", "run_listing", {}, 1),
                ]
            },
            {"content": "Done."},
        ]
    )
    runtime = _runtime(gateway, reader, shell, ask={"run_listing"})

    paused = await runtime.run("look around")
    assert paused.stopped_reason == "needs_approval"
    assert reader.calls == 1 and shell.calls == 0

    resumed = await runtime.approve_and_resume()

    assert resumed.content == "Done."
    assert reader.calls == 1 and shell.calls == 1
    tools = _tool_messages(gateway.requests[1])
    assert [m.tool_call_id for m in tools] == ["call-read", "call-bash"]


@pytest.mark.asyncio
async def test_second_approval_in_the_same_turn_pauses_again_then_finishes():
    first = ListTool("run_listing", "one")
    second = ListTool("write_note", "two")
    gateway = RecordingGateway(
        [
            {"tool_calls": [_call("c1", "run_listing", {}, 0), _call("c2", "write_note", {}, 1)]},
            {"content": "Both done."},
        ]
    )
    runtime = _runtime(gateway, first, second)

    await runtime.run("do both")
    again = await runtime.approve_and_resume()
    assert again.stopped_reason == "needs_approval"
    assert runtime.get_pending_approvals()[0]["tool_call_id"] == "c2"

    final = await runtime.approve_and_resume()

    assert final.content == "Both done."
    assert [m.tool_call_id for m in _tool_messages(gateway.requests[1])] == ["c1", "c2"]
    assert first.calls == 1 and second.calls == 1


@pytest.mark.asyncio
async def test_rejection_still_ends_the_turn_and_clears_the_pause():
    gateway = RecordingGateway([{"tool_calls": [_call("c1", "list_files", {})]}])
    runtime = _runtime(gateway, ListTool())
    await runtime.run("list")

    rejected = await runtime.reject_and_resume(message="no")

    assert rejected.content == "no"
    assert runtime.loop._approval_continuation is None
    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_desktop_harness_path_answers_after_approval(tmp_path: Path, monkeypatch):
    """The same kernel calls the Mac app worker makes for an Ask-mode task."""
    from superqode.desktop_service.session_controls import apply_controls
    from superqode.harness import FileHarnessStore, init_harness
    from superqode.harness.catalog import resolve_harness
    from superqode.harness.backends import runtime as backend_runtime

    (tmp_path / "hello.py").write_text("print('hi')\n")
    gateway = RecordingGateway(
        [
            {"tool_calls": [_call(GEMINI_CALL_ID, "bash", {"command": "touch marker && ls"})]},
            {"content": "There is one file, hello.py."},
        ]
    )
    monkeypatch.setattr(backend_runtime, "_gateway_for_request", lambda provider, model: gateway)

    spec = resolve_harness("core", root=tmp_path).spec
    spec = apply_controls(spec, {"interaction_mode": "code", "permission_mode": "ask"})
    kernel = await init_harness(spec, store=FileHarnessStore(tmp_path / "store"))
    session = await kernel.session(None)
    async for _ in session.stream(
        "What files are here?",
        provider="google",
        model="gemini-4-neon",
        working_directory=tmp_path,
        sandbox_backend=spec.execution_policy.sandbox,
    ):
        pass
    pending = session.pending_approvals()
    assert pending and pending[0]["tool_name"] == "bash"

    response = await session.approve_pending(0, always=False)

    assert response.stopped_reason == "complete"
    assert response.content == "There is one file, hello.py."
    assert session.pending_approvals() == ()
    tools = _tool_messages(gateway.requests[1])
    assert [m.tool_call_id for m in tools] == [GEMINI_CALL_ID]
    assert "hello.py" in tools[0].content
