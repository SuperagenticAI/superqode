"""Tool execution parity with pi's agent loop (checklist L6 to L12, L15, L16, L22, L23)."""

from __future__ import annotations

import asyncio

from conftest import call, config, context, echo_tool, slow_tool

from superqode.pipy import (
    AbortController,
    AgentTool,
    AgentToolResult,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    run_agent_loop,
)
from superqode.pipy.ai import FakeStream, text_response, tool_response


async def run(model, recorder, script, tools, **config_kwargs):
    signal = config_kwargs.pop("signal", None)
    return await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=tools),
        config(model, **config_kwargs),
        recorder,
        signal,
        FakeStream(script),
    )


async def test_single_tool_call_round_trip(model, recorder):
    script = [tool_response(call("echo", value="x")), text_response("done")]

    messages = await run(model, recorder, script, [echo_tool()])

    assert recorder.types == [
        "agent_start",
        "turn_start",
        "message_start",
        "message_end",
        "message_start",
        "message_update",
        "message_update",
        "message_end",
        "tool_execution_start",
        "tool_execution_end",
        "message_start",
        "message_end",
        "turn_end",
        "turn_start",
        "message_start",
        "message_update",
        "message_update",
        "message_update",
        "message_end",
        "turn_end",
        "agent_end",
    ]
    result = next(m for m in messages if isinstance(m, ToolResultMessage))
    assert result.text == "echo:x"
    assert result.is_error is False


async def test_truncated_message_refuses_tool_calls(model, recorder):
    """L6: a length stop fails every call without executing any of them."""
    executed: list[str] = []

    async def body(tool_call_id, args, signal=None, on_update=None):
        executed.append(tool_call_id)
        return AgentToolResult(content=[TextContent(text="ran")])

    script = [
        tool_response(
            call("echo", "c1", value="a"),
            call("echo", "c2", value="b"),
            stop_reason="length",
        ),
        text_response("recovered"),
    ]

    await run(model, recorder, script, [echo_tool(body=body)])

    assert executed == []
    ends = recorder.of_type("tool_execution_end")
    assert len(ends) == 2
    assert all(event.is_error for event in ends)
    assert "output token limit" in ends[0].result.text
    # terminate is False for a truncated batch, so the loop takes another turn.
    assert recorder.types.count("turn_start") == 2


async def test_parallel_tools_run_concurrently(model, recorder):
    """L7: the batch finishes in about the slowest tool's time, not the sum."""
    order: list[str] = []
    tools = [slow_tool("slow", 0.06, order), slow_tool("quick", 0.01, order)]
    script = [
        tool_response(call("slow", "c1"), call("quick", "c2")),
        text_response("done"),
    ]

    started = asyncio.get_running_loop().time()
    await run(model, recorder, script, tools)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.06 + 0.01
    assert order == ["quick", "slow"]


async def test_parallel_emission_ordering(model, recorder):
    """L8: ends in completion order, result messages in assistant source order."""
    order: list[str] = []
    tools = [slow_tool("slow", 0.06, order), slow_tool("quick", 0.01, order)]
    script = [
        tool_response(call("slow", "c1"), call("quick", "c2")),
        text_response("done"),
    ]

    await run(model, recorder, script, tools)

    assert recorder.tool_names("tool_execution_start") == ["slow", "quick"]
    assert recorder.tool_names("tool_execution_end") == ["quick", "slow"]
    results = [
        event.message.tool_name
        for event in recorder.of_type("message_end")
        if isinstance(event.message, ToolResultMessage)
    ]
    assert results == ["slow", "quick"]


async def test_sequential_mode_by_config(model, recorder):
    order: list[str] = []
    tools = [slow_tool("slow", 0.04, order), slow_tool("quick", 0.01, order)]
    script = [
        tool_response(call("slow", "c1"), call("quick", "c2")),
        text_response("done"),
    ]

    await run(model, recorder, script, tools, tool_execution="sequential")

    assert order == ["slow", "quick"]
    assert recorder.tool_names("tool_execution_end") == ["slow", "quick"]


async def test_sequential_mode_by_tool_declaration(model, recorder):
    """L9: one sequential tool forces the whole batch to run one at a time."""
    order: list[str] = []

    async def body(name):
        async def run_tool(tool_call_id, args, signal=None, on_update=None):
            await asyncio.sleep(0.04 if name == "slow" else 0.01)
            order.append(name)
            return AgentToolResult(content=[TextContent(text=name)])

        return run_tool

    slow = AgentTool(
        name="slow",
        label="slow",
        description="slow",
        parameters={"type": "object", "properties": {}},
        execute_fn=await body("slow"),
        execution_mode="sequential",
    )
    quick = AgentTool(
        name="quick",
        label="quick",
        description="quick",
        parameters={"type": "object", "properties": {}},
        execute_fn=await body("quick"),
    )
    script = [tool_response(call("slow", "c1"), call("quick", "c2")), text_response("done")]

    await run(model, recorder, script, [slow, quick])

    assert order == ["slow", "quick"]


async def test_updates_emit_during_execution(model, recorder):
    """L10: partial results reach the sink before the tool returns."""
    seen_before_return: list[int] = []
    gate = asyncio.Event()

    async def body(tool_call_id, args, signal=None, on_update=None):
        on_update(AgentToolResult(content=[TextContent(text="partial 1")]))
        on_update(AgentToolResult(content=[TextContent(text="partial 2")]))
        seen_before_return.append(len(recorder.of_type("tool_execution_update")))
        gate.set()
        return AgentToolResult(content=[TextContent(text="final")])

    script = [tool_response(call("echo", value="x")), text_response("done")]
    await run(model, recorder, script, [echo_tool(body=body)])

    assert seen_before_return == [2]
    updates = recorder.of_type("tool_execution_update")
    assert [event.partial_result.text for event in updates] == ["partial 1", "partial 2"]
    # The update snapshot is a copy, so a later mutation cannot rewrite history.
    assert updates[0].partial_result is not updates[1].partial_result


async def test_unknown_tool(model, recorder):
    script = [tool_response(call("nope", value="x")), text_response("done")]

    await run(model, recorder, script, [echo_tool()])

    end = recorder.of_type("tool_execution_end")[0]
    assert end.is_error is True
    assert end.result.text == "Tool nope not found"


async def test_invalid_arguments_produce_an_error_result(model, recorder):
    """L11: schema validation runs before execution."""
    executed: list[str] = []

    async def body(tool_call_id, args, signal=None, on_update=None):
        executed.append(tool_call_id)
        return AgentToolResult(content=[TextContent(text="ran")])

    script = [tool_response(ToolCall(id="c1", name="echo", arguments={})), text_response("done")]

    await run(model, recorder, script, [echo_tool(body=body)])

    assert executed == []
    end = recorder.of_type("tool_execution_end")[0]
    assert end.is_error is True
    assert 'Validation failed for tool "echo"' in end.result.text
    assert "Received arguments:" in end.result.text


async def test_arguments_are_coerced_before_execution(model, recorder):
    seen: list[object] = []

    async def body(tool_call_id, args, signal=None, on_update=None):
        seen.append(args["value"])
        return AgentToolResult(content=[TextContent(text="ok")])

    tool = AgentTool(
        name="count",
        label="count",
        description="count",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        },
        execute_fn=body,
    )
    script = [
        tool_response(ToolCall(id="c1", name="count", arguments={"value": "7"})),
        text_response("done"),
    ]

    await run(model, recorder, script, [tool])

    assert seen == [7]


async def test_prepare_arguments_shim_runs_first(model, recorder):
    seen: list[object] = []

    async def body(tool_call_id, args, signal=None, on_update=None):
        seen.append(args)
        return AgentToolResult(content=[TextContent(text="ok")])

    tool = AgentTool(
        name="legacy",
        label="legacy",
        description="legacy",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        execute_fn=body,
        prepare_arguments=lambda args: {"value": args.get("old_value", "")},
    )
    script = [
        tool_response(ToolCall(id="c1", name="legacy", arguments={"old_value": "x"})),
        text_response("done"),
    ]

    await run(model, recorder, script, [tool])

    assert seen == [{"value": "x"}]


async def test_tool_exception_becomes_an_error_result(model, recorder):
    async def body(tool_call_id, args, signal=None, on_update=None):
        raise RuntimeError("tool blew up")

    script = [tool_response(call("echo", value="x")), text_response("done")]

    await run(model, recorder, script, [echo_tool(body=body)])

    end = recorder.of_type("tool_execution_end")[0]
    assert end.is_error is True
    assert end.result.text == "tool blew up"


async def test_terminate_stops_the_loop_when_every_result_sets_it(model, recorder):
    """L15: unanimous terminate ends the run without another provider call."""

    async def body(tool_call_id, args, signal=None, on_update=None):
        return AgentToolResult(content=[TextContent(text="bye")], terminate=True)

    script = [
        tool_response(call("echo", "c1", value="a"), call("echo", "c2", value="b")),
        text_response("should not run"),
    ]
    stream = FakeStream(script)

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool(body=body)]),
        config(model),
        recorder,
        None,
        stream,
    )

    assert stream.index == 1
    assert recorder.types.count("turn_start") == 1
    assert recorder.types[-1] == "agent_end"


async def test_terminate_ignored_when_only_some_results_set_it(model, recorder):
    calls: list[str] = []

    async def body(tool_call_id, args, signal=None, on_update=None):
        calls.append(tool_call_id)
        return AgentToolResult(
            content=[TextContent(text="x")],
            terminate=tool_call_id == "c1",
        )

    script = [
        tool_response(call("echo", "c1", value="a"), call("echo", "c2", value="b")),
        text_response("continues"),
    ]
    stream = FakeStream(script)

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool(body=body)]),
        config(model),
        recorder,
        None,
        stream,
    )

    assert stream.index == 2
    assert recorder.types.count("turn_start") == 2


async def test_abort_during_preparation_produces_an_error_result(model, recorder):
    """L16: an abort raised while preparing short-circuits before execution."""
    controller = AbortController()
    executed: list[str] = []

    async def body(tool_call_id, args, signal=None, on_update=None):
        executed.append(tool_call_id)
        return AgentToolResult(content=[TextContent(text="ran")])

    async def before(hook_context, signal):
        controller.abort()
        return None

    script = [tool_response(call("echo", value="x")), text_response("done")]

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool(body=body)]),
        config(model, before_tool_call=before),
        recorder,
        controller.signal,
        FakeStream(script),
    )

    assert executed == []
    end = recorder.of_type("tool_execution_end")[0]
    assert end.is_error is True
    assert end.result.text == "Operation aborted"


async def test_abort_stops_a_sequential_batch(model, recorder):
    """L16: sequential execution stops after the call that observed the abort."""
    controller = AbortController()
    executed: list[str] = []

    async def body(tool_call_id, args, signal=None, on_update=None):
        executed.append(tool_call_id)
        controller.abort()
        return AgentToolResult(content=[TextContent(text="ran")])

    script = [
        tool_response(call("echo", "c1", value="a"), call("echo", "c2", value="b")),
        text_response("done"),
    ]

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool(body=body)]),
        config(model, tool_execution="sequential"),
        recorder,
        controller.signal,
        FakeStream(script),
    )

    assert executed == ["c1"]
    assert len(recorder.of_type("tool_execution_end")) == 1


async def test_missing_content_normalised(model, recorder):
    """L22: a result without content still produces a valid tool result message."""

    async def body(tool_call_id, args, signal=None, on_update=None):
        return AgentToolResult(details={"only": "details"})

    script = [tool_response(call("echo", value="x")), text_response("done")]

    messages = await run(model, recorder, script, [echo_tool(body=body)])

    result = next(m for m in messages if isinstance(m, ToolResultMessage))
    assert result.content == []
    assert result.details == {"only": "details"}


async def test_added_tool_names(model, recorder):
    """L23: added_tool_names is carried only when non-empty."""

    async def with_names(tool_call_id, args, signal=None, on_update=None):
        return AgentToolResult(
            content=[TextContent(text="ok")],
            added_tool_names=["extra"],
        )

    script = [tool_response(call("echo", value="x")), text_response("done")]
    messages = await run(model, recorder, script, [echo_tool(body=with_names)])
    result = next(m for m in messages if isinstance(m, ToolResultMessage))
    assert result.added_tool_names == ["extra"]

    async def without_names(tool_call_id, args, signal=None, on_update=None):
        return AgentToolResult(content=[TextContent(text="ok")], added_tool_names=[])

    recorder.events.clear()
    script = [tool_response(call("echo", value="x")), text_response("done")]
    messages = await run(model, recorder, script, [echo_tool(body=without_names)])
    result = next(m for m in messages if isinstance(m, ToolResultMessage))
    assert result.added_tool_names is None
