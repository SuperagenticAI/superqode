"""Loop hook parity with pi (checklist L13, L14, L17 to L20)."""

from __future__ import annotations

from conftest import call, config, context, echo_tool

from superqode.pipy import (
    AfterToolCallResult,
    AgentContext,
    AgentLoopTurnUpdate,
    AgentToolResult,
    BeforeToolCallResult,
    Model,
    TextContent,
    ToolResultMessage,
    UserMessage,
    run_agent_loop,
)
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.messages import Usage


async def test_before_tool_call_blocks(model, recorder):
    executed: list[str] = []

    async def body(tool_call_id, args, signal=None, on_update=None):
        executed.append(tool_call_id)
        return AgentToolResult(content=[TextContent(text="ran")])

    async def before(hook_context, signal):
        return BeforeToolCallResult(block=True, reason="not on my watch")

    script = [tool_response(call("echo", value="x")), text_response("done")]

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool(body=body)]),
        config(model, before_tool_call=before),
        recorder,
        None,
        FakeStream(script),
    )

    assert executed == []
    end = recorder.of_type("tool_execution_end")[0]
    assert end.is_error is True
    assert end.result.text == "not on my watch"


async def test_before_tool_call_default_block_message(model, recorder):
    async def before(hook_context, signal):
        return BeforeToolCallResult(block=True)

    script = [tool_response(call("echo", value="x")), text_response("done")]

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(model, before_tool_call=before),
        recorder,
        None,
        FakeStream(script),
    )

    assert recorder.of_type("tool_execution_end")[0].result.text == "Tool execution was blocked"


async def test_before_tool_call_sees_validated_arguments(model, recorder):
    seen: list[object] = []

    async def before(hook_context, signal):
        seen.append((hook_context.tool_call.name, hook_context.args))
        assert hook_context.assistant_message.tool_calls
        assert isinstance(hook_context.context, AgentContext)
        return None

    script = [tool_response(call("echo", value="x")), text_response("done")]

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(model, before_tool_call=before),
        recorder,
        None,
        FakeStream(script),
    )

    assert seen == [("echo", {"value": "x"})]


async def test_after_tool_call_overrides_fields(model, recorder):
    async def after(hook_context, signal):
        return AfterToolCallResult(
            content=[TextContent(text="patched")],
            details={"patched": True},
            is_error=True,
            usage=Usage(input=5, output=6),
        )

    script = [tool_response(call("echo", value="x")), text_response("done")]

    messages = await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(model, after_tool_call=after),
        recorder,
        None,
        FakeStream(script),
    )

    result = next(m for m in messages if isinstance(m, ToolResultMessage))
    assert result.text == "patched"
    assert result.details == {"patched": True}
    assert result.is_error is True
    assert result.usage is not None and result.usage.input == 5


async def test_after_tool_call_keeps_unset_fields(model, recorder):
    async def after(hook_context, signal):
        return AfterToolCallResult(details={"added": True})

    script = [tool_response(call("echo", value="x")), text_response("done")]

    messages = await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(model, after_tool_call=after),
        recorder,
        None,
        FakeStream(script),
    )

    result = next(m for m in messages if isinstance(m, ToolResultMessage))
    assert result.text == "echo:x"
    assert result.details == {"added": True}
    assert result.is_error is False


async def test_after_tool_call_exception_becomes_an_error_result(model, recorder):
    async def after(hook_context, signal):
        raise RuntimeError("hook exploded")

    script = [tool_response(call("echo", value="x")), text_response("done")]

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(model, after_tool_call=after),
        recorder,
        None,
        FakeStream(script),
    )

    end = recorder.of_type("tool_execution_end")[0]
    assert end.is_error is True
    assert end.result.text == "hook exploded"


async def test_after_tool_call_can_terminate(model, recorder):
    async def after(hook_context, signal):
        return AfterToolCallResult(terminate=True)

    script = [tool_response(call("echo", value="x")), text_response("should not run")]
    stream = FakeStream(script)

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(model, after_tool_call=after),
        recorder,
        None,
        stream,
    )

    assert stream.index == 1


async def test_transform_context(model, recorder):
    """L17: transform_context runs before convert_to_llm."""
    order: list[str] = []

    async def transform(messages, signal):
        order.append("transform")
        return [*messages, UserMessage(content="injected")]

    def convert(messages):
        order.append("convert")
        return list(messages)

    stream = FakeStream([text_response("ok")])

    await run_agent_loop(
        [UserMessage(content="go")],
        context(),
        config(model, transform_context=transform, convert_to_llm=convert),
        recorder,
        None,
        stream,
    )

    assert order == ["transform", "convert"]
    assert stream.calls[0].messages[-1].text == "injected"


async def test_get_api_key(model, recorder):
    seen: list[str] = []

    async def get_api_key(provider):
        seen.append(provider)
        return "resolved-key"

    class Capturing(FakeStream):
        keys: list[str | None] = []

        def __call__(self, model_arg, context_arg, options):
            Capturing.keys.append(options.api_key)
            return super().__call__(model_arg, context_arg, options)

    stream = Capturing([text_response("ok")])

    await run_agent_loop(
        [UserMessage(content="go")],
        context(),
        config(model, get_api_key=get_api_key, api_key="fallback"),
        recorder,
        None,
        stream,
    )

    assert seen == ["fake"]
    assert Capturing.keys == ["resolved-key"]
    Capturing.keys.clear()


async def test_get_api_key_falls_back(model, recorder):
    async def get_api_key(provider):
        return None

    class Capturing(FakeStream):
        keys: list[str | None] = []

        def __call__(self, model_arg, context_arg, options):
            Capturing.keys.append(options.api_key)
            return super().__call__(model_arg, context_arg, options)

    stream = Capturing([text_response("ok")])

    await run_agent_loop(
        [UserMessage(content="go")],
        context(),
        config(model, get_api_key=get_api_key, api_key="fallback"),
        recorder,
        None,
        stream,
    )

    assert Capturing.keys == ["fallback"]
    Capturing.keys.clear()


async def test_prepare_next_turn_replaces_model_and_context(model, recorder):
    """L19: the next provider request uses the returned state."""
    replacement = Model(id="fake-2", provider="fake", api="fake-api")
    replacement_context = AgentContext(
        system_prompt="replaced prompt",
        messages=[UserMessage(content="replaced")],
        tools=[echo_tool()],
    )

    async def prepare_next_turn(turn_context):
        return AgentLoopTurnUpdate(
            context=replacement_context,
            model=replacement,
            thinking_level="high",
        )

    script = [tool_response(call("echo", value="x")), text_response("second turn")]
    stream = FakeStream(script)

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(model, prepare_next_turn=prepare_next_turn),
        recorder,
        None,
        stream,
    )

    assert len(stream.calls) == 2
    assert stream.calls[1].system_prompt == "replaced prompt"


async def test_prepare_next_turn_off_clears_reasoning(model, recorder):
    captured: list[str | None] = []

    class Capturing(FakeStream):
        def __call__(self, model_arg, context_arg, options):
            captured.append(options.reasoning)
            return super().__call__(model_arg, context_arg, options)

    async def prepare_next_turn(turn_context):
        return AgentLoopTurnUpdate(thinking_level="off")

    script = [tool_response(call("echo", value="x")), text_response("done")]

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(model, prepare_next_turn=prepare_next_turn, reasoning="high"),
        recorder,
        None,
        Capturing(script),
    )

    assert captured == ["high", None]


async def test_should_stop_after_turn(model, recorder):
    """L20: stopping happens before the queues are polled."""
    steered: list[int] = []

    async def should_stop(turn_context):
        return True

    def get_steering():
        steered.append(1)
        return []

    script = [tool_response(call("echo", value="x")), text_response("never")]
    stream = FakeStream(script)

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(model, should_stop_after_turn=should_stop, get_steering_messages=get_steering),
        recorder,
        None,
        stream,
    )

    assert stream.index == 1
    assert recorder.types[-1] == "agent_end"
    # Polled once before the first turn, never after the stop decision.
    assert len(steered) == 1


async def test_should_stop_after_turn_sees_turn_results(model, recorder):
    seen: list[tuple[str, int]] = []

    async def should_stop(turn_context):
        seen.append((turn_context.message.text, len(turn_context.tool_results)))
        return False

    script = [tool_response(call("echo", value="x")), text_response("final")]

    await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(model, should_stop_after_turn=should_stop),
        recorder,
        None,
        FakeStream(script),
    )

    assert seen == [("", 1), ("final", 0)]
