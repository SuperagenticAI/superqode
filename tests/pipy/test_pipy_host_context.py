import pytest

from conftest import MODEL
from superqode.pipy.ai import FakeStream, text_response
from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession
from superqode.pipy.messages import (
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    TextContent,
)
from superqode.harness.pipy_context import PiPyContextHost
from superqode.pipy.harness_events import ContextEvent


async def open_session(tmp_path, host, stream):
    session = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path,
            model=MODEL,
            stream_fn=stream,
            session_root=tmp_path / "sessions",
            context_file_transform=host.transform_files if host.conditional else None,
            extra_tools=(host.reader_tool(),) if host.policy else (),
        )
    )
    host.attach(session)
    return session


async def test_conditional_instructions_at_each_request_and_reload(tmp_path):
    rules = tmp_path / "AGENTS.md"
    rules.write_text(
        'Always preserve safety\n<!-- sq:when paths="src/**" -->\nUse source conventions\n<!-- /sq:when -->'
    )
    host = PiPyContextHost({"conditional_instructions": True})
    stream = FakeStream([text_response("one"), text_response("two"), text_response("three")])
    session = await open_session(tmp_path, host, stream)
    await session.prompt("Hello")
    assert "Always preserve safety" in stream.calls[0].system_prompt
    assert "Use source conventions" not in stream.calls[0].system_prompt
    await session.prompt("Edit src/app.py")
    assert "Use source conventions" in stream.calls[1].system_prompt
    rules.write_text(
        'Always preserve safety\n<!-- sq:when paths="src/**" -->\nReloaded conventions\n<!-- /sq:when -->'
    )
    session.reload_resources()
    await session.prompt("Continue src/app.py")
    assert "Reloaded conventions" in stream.calls[2].system_prompt
    assert "Use source conventions" not in stream.calls[2].system_prompt


async def test_host_projection_archive_reader_and_restart(tmp_path):
    config = {
        "mode": "enforce",
        "store_path": str(tmp_path / "evidence.sqlite"),
        "recent_messages": 1,
    }
    host = PiPyContextHost(config)
    stream = FakeStream([text_response("done")])
    session = await open_session(tmp_path, host, stream)
    original = "evidence " * 3000
    for message in [
        UserMessage("Inspect app.py"),
        AssistantMessage([ToolCall("call", "read", {"path": "app.py"})]),
        ToolResultMessage("call", "read", [TextContent(original)]),
        AssistantMessage([TextContent("Continue")]),
    ]:
        await session.session.append_message(message)
    before = session.session_path.read_bytes()
    context = await session.session.build_context()
    projection = await host.context(ContextEvent(context.messages + [UserMessage("Fix app.py")]))
    tool = next(m for m in projection.messages if m.role == "toolResult")
    assert len(tool.text) < len(original)
    reference = host.diagnostics[-1]["decisions"][0]["reference"]
    assert session.session_path.read_bytes() == before
    result = await host.reader_tool().execute(
        "retrieve", {"chunk_id": reference, "offset": 20, "limit": 100}
    )
    assert result.text == original[20:120]
    restarted = PiPyContextHost(config)
    resumed = await PiPyCodingSession.resume(
        CodingSessionOptions(
            cwd=tmp_path,
            model=MODEL,
            stream_fn=stream,
            session_root=tmp_path / "sessions",
            extra_tools=(restarted.reader_tool(),),
        ),
        session_path=session.session_path,
    )
    restarted.attach(resumed)
    result = await restarted.reader_tool().execute(
        "retrieve", {"chunk_id": reference, "offset": 20, "limit": 100}
    )
    assert result.text == original[20:120]
    await resumed.prompt("Fix app.py")
    sent = next(m for m in stream.calls[-1].messages if m.role == "toolResult")
    assert len(sent.text) < len(original)
    archived = (await resumed.session.build_context()).messages
    assert next(m for m in archived if m.role == "toolResult").text == original


async def test_mixed_images_and_errors_remain_intact(tmp_path):
    from superqode.pipy.messages import ImageContent
    from superqode.harness.pipy_context import pipy_items

    result = ToolResultMessage(
        "id", "read", [TextContent("body" * 5000), ImageContent("AA==", "image/png")]
    )
    assert pipy_items([result])[0].text == ""


async def test_core_and_pipy_share_selection_and_preserve_repeated_call_authority(tmp_path):
    from superqode.agent.loop import AgentMessage
    from superqode.harness.core_context import core_items
    from superqode.harness.pipy_context import pipy_items
    from superqode.harness.context_artifacts import ContextArtifactStore
    from superqode.harness.context_policy import ContextPolicy, ContextPolicyEngine

    body = "evidence\n" * 3000
    core = [
        AgentMessage("user", "Inspect"),
        AgentMessage(
            "assistant",
            "",
            tool_calls=[
                {
                    "id": "reused",
                    "function": {"name": "read_file", "arguments": '{"path":"old.py"}'},
                }
            ],
        ),
        AgentMessage("tool", body, tool_call_id="reused", name="read_file"),
        AgentMessage(
            "assistant",
            "",
            tool_calls=[
                {
                    "id": "reused",
                    "function": {"name": "read_file", "arguments": '{"path":"new.py"}'},
                }
            ],
        ),
        AgentMessage("tool", body, tool_call_id="reused", name="read_file"),
        AgentMessage("assistant", "Continue"),
        AgentMessage("user", "Implement"),
    ]
    pipy = [
        UserMessage("Inspect"),
        AssistantMessage([ToolCall("reused", "read", {"path": "old.py"})]),
        ToolResultMessage("reused", "read", [TextContent(body)], timestamp=1),
        AssistantMessage([ToolCall("reused", "read", {"path": "new.py"})]),
        ToolResultMessage("reused", "read", [TextContent(body)], timestamp=2),
        AssistantMessage([TextContent("Continue")]),
        UserMessage("Implement"),
    ]
    a, b = core_items(core), pipy_items(pipy)
    assert a[2].arguments == b[2].arguments == {"path": "old.py"}
    assert a[4].arguments == b[4].arguments == {"path": "new.py"}
    store = ContextArtifactStore(tmp_path / "evidence.sqlite")
    policy = ContextPolicy(mode="enforce", recent_messages=1)
    first = await ContextPolicyEngine(store, "core", policy).prepare(a)
    second = await ContextPolicyEngine(store, "pipy", policy).prepare(b)
    assert set(first.replacements) == set(second.replacements) == {2, 4}
