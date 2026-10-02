"""Current session semantics and the provider/extension boundaries."""

from dataclasses import replace

import pytest
from conftest import call, config, context, echo_tool

from superqode.agent.hooks import BEFORE_TOOL_CALL, MODIFY, HookDecision, HookRegistry
from superqode.harness.pipy_extensions import attach_extension_hooks
from superqode.pipy import AgentHarness, AgentToolResult, TextContent, UserMessage, run_agent_loop
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.ai.gateway import GatewayStream, _gateway_messages
from superqode.pipy.messages import ImageContent, SystemMessage, ToolResultMessage
from superqode.pipy.session import decode_entry, encode_entry
from superqode.pipy.session.session import build_session_context
from superqode.pipy.stream import Context, StreamOptions


def entry(entry_type, ident, **fields):
    return {
        "type": entry_type,
        "id": ident,
        "parentId": None,
        "timestamp": "2026-10-01T21:00:00Z",
        **fields,
    }


def test_context_edits_are_branch_local_and_preserve_history_and_accounting():
    original = decode_entry(
        entry(
            "message",
            "m",
            message={
                "role": "assistant",
                "content": [{"type": "text", "text": "original"}],
                "usage": {"input": 5},
            },
        )
    )
    usage = decode_entry(
        entry(
            "usage",
            "u",
            kind="cache_warm",
            provider="openai",
            model="fixture",
            usage={"input": 7},
            note="warm",
        )
    )
    edit = decode_entry(entry("context_edit", "e", targetId="m", replacement={"content": "edited"}))
    drop = decode_entry(entry("context_edit", "d", targetId="m", replacement=None))
    assert build_session_context([original, usage, edit]).messages[0].text == "edited"
    assert build_session_context([original, usage, edit, drop]).messages == []
    assert build_session_context([original]).messages[0].text == "original"
    assert original.message.text == "original"
    assert build_session_context([original, usage, edit, drop]).usage.input == 12
    assert encode_entry(edit)["replacement"] == {"content": "edited"}
    assert encode_entry(usage)["note"] == "warm"


def test_compaction_system_checkpoint_and_section_updates_round_trip():
    wire = entry(
        "compaction",
        "c",
        summary="summary",
        tokensBefore=99,
        systemMessage={
            "role": "system",
            "content": "base",
            "timestamp": 1,
            "sections": {"one": "first", "two": "second"},
            "toolsAdded": [{"name": "read", "description": "read", "parameters": {}}],
        },
    )
    checkpoint = decode_entry(wire)
    assert encode_entry(checkpoint)["systemMessage"] == wire["systemMessage"]
    messages = build_session_context([checkpoint]).messages
    assert isinstance(messages[0], SystemMessage)
    messages.append(SystemMessage(content="additional", sections={"one": None, "two": "updated"}))
    converted = _gateway_messages("", messages)
    assert converted[0].content == "base\n\nadditional\n\nupdated"


def test_images_survive_user_and_tool_messages():
    image = ImageContent(data="AA==", mime_type="image/png")
    converted = _gateway_messages(
        "",
        [
            UserMessage(content=[TextContent(text="inspect"), image]),
            ToolResultMessage(tool_call_id="call", tool_name="read", content=[image]),
        ],
    )
    assert converted[0].content[1]["image_url"]["url"] == "data:image/png;base64,AA=="
    assert converted[1].role == "tool" and isinstance(converted[1].content, str)
    assert converted[2].role == "user" and converted[2].content[1]["type"] == "image_url"


async def test_explicit_text_only_model_rejects_images_without_provider_call(model):
    class Gateway:
        def stream_completion(self, **kwargs):
            pytest.fail("text-only models must not receive image calls")

    events = [
        event
        async for event in GatewayStream(Gateway())(
            replace(model, supports_images=False),
            Context(
                system_prompt="",
                messages=[UserMessage(content=[ImageContent(data="AA==", mime_type="image/png")])],
            ),
            StreamOptions(),
        )
    ]
    assert events[-1].type == "error"
    assert "does not support image input" in events[-1].error.error_message


async def test_installed_extension_rewrite_reaches_executor(model, tmp_path):
    from superqode.pipy.session import MemorySessionStorage, create_session

    seen = []

    async def body(ident, args, signal=None, on_update=None):
        seen.append(args)
        return AgentToolResult(content="ok")

    harness = AgentHarness(
        session=await create_session(MemorySessionStorage(cwd=str(tmp_path))),
        model=model,
        tools=[echo_tool(body=body)],
        stream_fn=FakeStream([tool_response(call("echo", value="old")), text_response("done")]),
    )
    hooks = HookRegistry()
    hooks.register(
        BEFORE_TOOL_CALL, lambda **kwargs: HookDecision(action=MODIFY, arguments={"value": "new"})
    )
    attach_extension_hooks(harness, hooks)
    await harness.prompt("go")
    assert seen == [{"value": "new"}]


async def test_invalid_rewritten_arguments_never_execute(model, recorder):
    from superqode.pipy.loop import BeforeToolCallResult

    seen = []

    async def body(ident, args, signal=None, on_update=None):
        seen.append(args)
        return AgentToolResult(content="ok")

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool(body=body)]),
        config(model, before_tool_call=lambda *args: BeforeToolCallResult(arguments={})),
        recorder,
        None,
        FakeStream([tool_response(call("echo", value="old")), text_response("done")]),
    )
    assert seen == []
    assert recorder.of_type("tool_execution_end")[0].is_error


async def test_deny_cannot_be_overridden_by_later_argument_rewrite(model, tmp_path):
    from superqode.pipy.session import MemorySessionStorage, create_session
    from superqode.pipy.harness_events import ToolCallResult

    seen = []

    async def body(ident, args, signal=None, on_update=None):
        seen.append(args)
        return AgentToolResult(content="ok")

    harness = AgentHarness(
        session=await create_session(MemorySessionStorage(cwd=str(tmp_path))),
        model=model,
        tools=[echo_tool(body=body)],
        stream_fn=FakeStream([tool_response(call("echo", value="old")), text_response("done")]),
    )
    harness.on("tool_call", lambda event: ToolCallResult(block=True, reason="denied"))
    harness.on("tool_call", lambda event: ToolCallResult(arguments={"value": "new"}))
    await harness.prompt("go")
    assert seen == []
