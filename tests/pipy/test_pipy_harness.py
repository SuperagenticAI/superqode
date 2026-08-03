"""AgentHarness parity with pi (checklist H1 to H7, H10)."""

from __future__ import annotations

import asyncio

import pytest
from conftest import MODEL, call, echo_tool

from superqode.pipy import AgentToolResult, Model, TextContent, ToolResultMessage, UserMessage
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.harness import AgentHarness, HarnessResources
from superqode.pipy.harness_events import (
    AgentHarnessError,
    BeforeAgentStartResult,
    ContextResult,
    ToolCallResult,
    ToolResultPatch,
)
from superqode.pipy.session import MemorySessionStorage, create_session


async def build(script=(), tools=(), **kwargs) -> AgentHarness:
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    return AgentHarness(
        session=session,
        model=MODEL,
        stream_fn=FakeStream(list(script)),
        tools=list(tools),
        system_prompt="You are a test agent.",
        **kwargs,
    )


# -- H2: session-backed turn state ------------------------------------------ #


async def test_prompt_writes_the_whole_turn_to_the_session():
    harness = await build([text_response("hello")])

    message = await harness.prompt("hi")

    assert message.text == "hello"
    context = await harness.session.build_context()
    assert [m.text for m in context.messages] == ["hi", "hello"]


async def test_second_prompt_sees_the_first_from_the_session():
    harness = await build([text_response("one"), text_response("two")])

    await harness.prompt("first")
    await harness.prompt("second")

    context = await harness.session.build_context()
    assert [m.text for m in context.messages] == ["first", "one", "second", "two"]


async def test_tool_results_are_persisted():
    harness = await build(
        [tool_response(call("echo", value="x")), text_response("done")], [echo_tool()]
    )

    await harness.prompt("go")

    context = await harness.session.build_context()
    assert any(isinstance(m, ToolResultMessage) and m.text == "echo:x" for m in context.messages)


async def test_turn_state_is_rebuilt_between_turns():
    """H2: a session write made mid-run reaches the next provider call."""
    stream = FakeStream([tool_response(call("echo", value="x")), text_response("done")])
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    harness = AgentHarness(
        session=session,
        model=MODEL,
        stream_fn=stream,
        tools=[echo_tool()],
        system_prompt="You are a test agent.",
    )

    async def inject(event):
        if getattr(event, "type", "") == "tool_execution_end":
            await session.append_message(UserMessage(content="injected mid-run"))

    harness.subscribe(inject)
    await harness.prompt("go")

    second_call_texts = [m.text for m in stream.calls[1].messages]
    assert "injected mid-run" in second_call_texts


# -- H1, H7: lifecycle ------------------------------------------------------ #


async def test_phase_returns_to_idle():
    harness = await build([text_response("ok")])
    assert harness.phase == "idle"

    await harness.prompt("hi")

    assert harness.phase == "idle"
    assert harness.is_running is False


async def test_busy_guard():
    started = asyncio.Event()
    release = asyncio.Event()

    async def body(tool_call_id, args, signal=None, on_update=None):
        started.set()
        await release.wait()
        return AgentToolResult(content=[TextContent(text="ok")])

    harness = await build(
        [tool_response(call("echo", value="x")), text_response("done")], [echo_tool(body=body)]
    )
    task = asyncio.ensure_future(harness.prompt("go"))
    await started.wait()

    with pytest.raises(AgentHarnessError) as error:
        await harness.prompt("again")
    assert error.value.code == "busy"

    release.set()
    await task


async def test_wait_for_idle():
    release = asyncio.Event()

    async def body(tool_call_id, args, signal=None, on_update=None):
        await release.wait()
        return AgentToolResult(content=[TextContent(text="ok")])

    harness = await build(
        [tool_response(call("echo", value="x")), text_response("done")], [echo_tool(body=body)]
    )
    task = asyncio.ensure_future(harness.prompt("go"))
    await asyncio.sleep(0)
    release.set()

    await harness.wait_for_idle()
    assert harness.phase == "idle"
    await task


async def test_abort_clears_queues_and_reports_them():
    release = asyncio.Event()

    async def body(tool_call_id, args, signal=None, on_update=None):
        await release.wait()
        return AgentToolResult(content=[TextContent(text="ok")])

    harness = await build(
        [tool_response(call("echo", value="x")), text_response("done")], [echo_tool(body=body)]
    )
    task = asyncio.ensure_future(harness.prompt("go"))
    await asyncio.sleep(0)
    await harness.steer("steer me")
    await harness.follow_up("later")
    release.set()

    result = await harness.abort()

    assert [m.text for m in result.cleared_steer] == ["steer me"]
    assert [m.text for m in result.cleared_follow_up] == ["later"]
    assert harness.queued_messages().steer == []
    await task


async def test_shutdown_rejects_further_work():
    harness = await build([text_response("ok")])
    harness.request_shutdown()

    with pytest.raises(AgentHarnessError) as error:
        await harness.prompt("hi")
    assert error.value.code == "invalid_state"

    await harness.wait_for_shutdown()


async def test_wait_for_shutdown_without_request_raises():
    harness = await build()
    with pytest.raises(AgentHarnessError):
        await harness.wait_for_shutdown()


# -- H10: run failure ------------------------------------------------------- #


async def test_provider_crash_becomes_a_failed_turn():
    """H10: a raising stream function still yields a full event tail."""

    def exploding(model, context, options):
        raise RuntimeError("provider down")

    session = await create_session(MemorySessionStorage(cwd="/repo"))
    harness = AgentHarness(session=session, model=MODEL, stream_fn=exploding)
    seen: list[str] = []
    harness.subscribe(lambda event: seen.append(getattr(event, "type", "")))

    message = await harness.prompt("hi")

    assert message.stop_reason == "error"
    assert message.error_message == "provider down"
    # The prompt was already emitted and persisted before the provider failed,
    # so the run reports a complete turn: prompt, synthetic failure message,
    # turn_end, then agent_end. save_point lands between turn_end and agent_end,
    # as in pi's handleAgentEvent: emit the turn, flush writes, announce it.
    assert seen == [
        "agent_start",
        "turn_start",
        "message_start",  # the prompt
        "message_end",
        "message_start",  # the synthetic failure
        "message_end",
        "turn_end",
        "save_point",
        "agent_end",
        "settled",
    ]
    assert harness.phase == "idle"


async def test_failure_is_recorded_in_the_session():
    def exploding(model, context, options):
        raise RuntimeError("provider down")

    session = await create_session(MemorySessionStorage(cwd="/repo"))
    harness = AgentHarness(session=session, model=MODEL, stream_fn=exploding)

    await harness.prompt("hi")

    context = await session.build_context()
    assert context.messages[-1].stop_reason == "error"


# -- H4: queues ------------------------------------------------------------- #


async def test_steer_is_injected_between_turns():
    stream = FakeStream([tool_response(call("echo", value="x")), text_response("done")])
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    harness = AgentHarness(
        session=session,
        model=MODEL,
        stream_fn=stream,
        tools=[echo_tool()],
        system_prompt="p",
    )

    async def steer_once(event):
        if getattr(event, "type", "") == "tool_execution_end":
            await harness.steer("change of plan")

    harness.subscribe(steer_once)
    await harness.prompt("go")

    assert "change of plan" in [m.text for m in stream.calls[1].messages]


async def test_queue_mode_all_drains_everything():
    """Both queued messages land at the same drain point, so one turn answers both."""
    harness = await build([text_response("one"), text_response("two")], steering_mode="all")
    await harness.steer("a")
    await harness.steer("b")

    await harness.prompt("go")

    context = await harness.session.build_context()
    assert [m.text for m in context.messages] == ["go", "a", "b", "one"]


async def test_queue_mode_one_at_a_time():
    """One message per drain point, so each gets its own turn.

    pi polls steering once before the first turn, which is why a message queued
    while the harness was idle is injected ahead of the first assistant reply
    rather than after it.
    """
    harness = await build([text_response("one"), text_response("two"), text_response("three")])
    await harness.steer("a")
    await harness.steer("b")

    await harness.prompt("go")

    context = await harness.session.build_context()
    assert [m.text for m in context.messages] == ["go", "a", "one", "b", "two"]


async def test_next_turn_leads_the_prompt():
    harness = await build([text_response("ok")])
    await harness.next_turn("read this first")

    await harness.prompt("my question")

    context = await harness.session.build_context()
    assert [m.text for m in context.messages][:2] == ["read this first", "my question"]


async def test_queue_update_events():
    harness = await build([text_response("ok")])
    updates: list[int] = []
    harness.subscribe(
        lambda event: updates.append(len(event.steer))
        if getattr(event, "type", "") == "queue_update"
        else None
    )

    await harness.steer("a")
    await harness.steer("b")

    assert updates == [1, 2]


# -- H5: hooks -------------------------------------------------------------- #


async def test_before_agent_start_can_replace_the_system_prompt():
    stream = FakeStream([text_response("ok")])
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    harness = AgentHarness(session=session, model=MODEL, stream_fn=stream, system_prompt="original")
    harness.on(
        "before_agent_start",
        lambda event: BeforeAgentStartResult(system_prompt="replaced"),
    )

    await harness.prompt("hi")

    assert stream.calls[0].system_prompt == "replaced"


async def test_before_agent_start_can_append_messages():
    harness = await build([text_response("ok")])
    harness.on(
        "before_agent_start",
        lambda event: BeforeAgentStartResult(messages=[UserMessage(content="extra")]),
    )

    await harness.prompt("hi")

    context = await harness.session.build_context()
    assert [m.text for m in context.messages][:2] == ["hi", "extra"]


async def test_context_hook_rewrites_provider_messages():
    stream = FakeStream([text_response("ok")])
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    harness = AgentHarness(session=session, model=MODEL, stream_fn=stream, system_prompt="p")
    harness.on("context", lambda event: ContextResult(messages=[UserMessage(content="rewritten")]))

    await harness.prompt("hi")

    assert [m.text for m in stream.calls[0].messages] == ["rewritten"]


async def test_tool_call_hook_blocks():
    harness = await build(
        [tool_response(call("echo", value="x")), text_response("done")], [echo_tool()]
    )
    harness.on("tool_call", lambda event: ToolCallResult(block=True, reason="denied"))

    await harness.prompt("go")

    context = await harness.session.build_context()
    result = next(m for m in context.messages if isinstance(m, ToolResultMessage))
    assert result.is_error is True
    assert result.text == "denied"


async def test_tool_result_hook_patches():
    harness = await build(
        [tool_response(call("echo", value="x")), text_response("done")], [echo_tool()]
    )
    harness.on(
        "tool_result",
        lambda event: ToolResultPatch(content=[TextContent(text="redacted")]),
    )

    await harness.prompt("go")

    context = await harness.session.build_context()
    result = next(m for m in context.messages if isinstance(m, ToolResultMessage))
    assert result.text == "redacted"


async def test_hook_exception_is_normalised():
    harness = await build([text_response("ok")])

    def boom(event):
        raise ValueError("hook failed")

    harness.on("before_agent_start", boom)

    with pytest.raises(AgentHarnessError) as error:
        await harness.prompt("hi")
    assert error.value.code == "hook"
    assert harness.phase == "idle"


# -- H3, H6: save points and deferred writes -------------------------------- #


async def test_setters_are_deferred_during_a_run():
    """H3: a mid-run setter lands at the save point, not inside the turn."""
    stream = FakeStream([tool_response(call("echo", value="x")), text_response("done")])
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    harness = AgentHarness(
        session=session, model=MODEL, stream_fn=stream, tools=[echo_tool()], system_prompt="p"
    )

    async def switch(event):
        if getattr(event, "type", "") == "tool_execution_end":
            await harness.set_thinking_level("high")

    harness.subscribe(switch)
    await harness.prompt("go")

    context = await session.build_context()
    assert context.thinking_level == "high"


async def test_save_point_reports_pending_mutations():
    harness = await build([text_response("ok")])
    save_points: list[bool] = []
    harness.subscribe(
        lambda event: save_points.append(event.had_pending_mutations)
        if getattr(event, "type", "") == "save_point"
        else None
    )

    await harness.prompt("hi")

    assert save_points == [False]


async def test_settled_reports_work_queued_during_the_run():
    """A next-turn message queued mid-run is still waiting when the run settles."""
    harness = await build([text_response("ok")])
    settled: list[int] = []

    async def observe(event):
        kind = getattr(event, "type", "")
        if kind == "turn_end":
            await harness.next_turn("for the next one")
        elif kind == "settled":
            settled.append(event.next_turn_count)

    harness.subscribe(observe)
    await harness.prompt("hi")

    assert settled == [1]


async def test_next_turn_queued_while_idle_is_consumed_by_the_prompt():
    harness = await build([text_response("ok")])
    settled: list[int] = []
    harness.subscribe(
        lambda event: settled.append(event.next_turn_count)
        if getattr(event, "type", "") == "settled"
        else None
    )
    await harness.next_turn("queued")

    await harness.prompt("hi")

    # Drained into this prompt, so nothing is left over.
    assert settled == [0]


async def test_append_message_when_idle_writes_immediately():
    harness = await build()
    await harness.append_message(UserMessage(content="note"))

    context = await harness.session.build_context()
    assert [m.text for m in context.messages] == ["note"]


# -- setters and validation ------------------------------------------------- #


async def test_set_model_records_a_change_entry():
    harness = await build()
    await harness.set_model(Model(id="other", provider="anthropic", api="messages"))

    context = await harness.session.build_context()
    assert context.model is not None and context.model.model_id == "other"


async def test_duplicate_tool_names_are_rejected():
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    with pytest.raises(AgentHarnessError) as error:
        AgentHarness(
            session=session,
            model=MODEL,
            stream_fn=FakeStream(),
            tools=[echo_tool("dup"), echo_tool("dup")],
        )
    assert error.value.code == "invalid_argument"


async def test_unknown_active_tool_is_rejected():
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    with pytest.raises(AgentHarnessError):
        AgentHarness(
            session=session,
            model=MODEL,
            stream_fn=FakeStream(),
            tools=[echo_tool()],
            active_tool_names=["missing"],
        )


async def test_active_tools_narrow_what_the_model_sees():
    harness = await build([text_response("ok")], [echo_tool("a"), echo_tool("b")])
    await harness.set_active_tools(["a"])

    assert [tool.name for tool in harness.get_active_tools()] == ["a"]


async def test_callable_system_prompt_sees_turn_state():
    stream = FakeStream([text_response("ok")])
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    harness = AgentHarness(
        session=session,
        model=MODEL,
        stream_fn=stream,
        tools=[echo_tool()],
        system_prompt=lambda state: f"tools={len(state.active_tools)} model={state.model.id}",
        resources=HarnessResources(),
    )

    await harness.prompt("hi")

    assert stream.calls[0].system_prompt == "tools=1 model=fake-1"


async def test_prompt_events_streams_and_settles():
    harness = await build([text_response("streamed")])

    stream = harness.prompt_events("hi")
    types = [getattr(event, "type", "") async for event in stream]
    message = await stream.result()

    assert types[0] == "agent_start"
    assert "settled" in types
    assert message.text == "streamed"
