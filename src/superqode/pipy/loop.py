"""Pi-compatible agent loop.

Port of ``packages/agent/src/agent-loop.ts`` from earendil-works/pi (MIT), which
works with transcript messages throughout and transforms to provider messages
only at the LLM call boundary. See NOTICE.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from .event_stream import EventStream
from .events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
    TurnEndEvent,
    TurnStartEvent,
)
from .messages import (
    AgentMessage,
    AssistantMessage,
    Message,
    TextContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    default_convert_to_llm,
)
from .provider_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantStartEvent,
)
from .signals import AbortSignal, is_aborted
from .stream import Context, Model, StreamFn, StreamOptions
from .tools.base import AgentTool, AgentToolResult
from .types import JSONObject, ThinkingLevel, ToolExecutionMode
from .validation import validate_tool_arguments

AgentEventSink = Callable[[AgentEvent], Awaitable[None] | None]


@dataclass(slots=True)
class AgentContext:
    """Context snapshot passed into the loop."""

    system_prompt: str
    messages: list[AgentMessage]
    tools: list[AgentTool] | None = None


@dataclass(slots=True)
class BeforeToolCallResult:
    """Returned from ``before_tool_call``. ``block`` prevents execution."""

    block: bool = False
    reason: str | None = None


@dataclass(slots=True)
class AfterToolCallResult:
    """Partial override returned from ``after_tool_call``.

    Merge is field by field with no deep merge: a field left as ``None`` keeps
    the executed value, and a field that is set replaces it in full.
    """

    content: list[Any] | None = None
    details: Any = None
    is_error: bool | None = None
    usage: Usage | None = None
    terminate: bool | None = None


@dataclass(slots=True)
class BeforeToolCallContext:
    assistant_message: AssistantMessage
    tool_call: ToolCall
    args: JSONObject
    context: AgentContext


@dataclass(slots=True)
class AfterToolCallContext:
    assistant_message: AssistantMessage
    tool_call: ToolCall
    args: JSONObject
    result: AgentToolResult
    is_error: bool
    context: AgentContext


@dataclass(slots=True)
class TurnContext:
    """Passed to ``should_stop_after_turn`` and ``prepare_next_turn``."""

    message: AssistantMessage
    tool_results: list[ToolResultMessage]
    context: AgentContext
    #: Messages this loop invocation returns if it exits here. Prompt runs
    #: include the initial prompts; continuation runs do not include
    #: pre-existing context messages.
    new_messages: list[AgentMessage]


@dataclass(slots=True)
class AgentLoopTurnUpdate:
    """Replacement runtime state applied before the next provider request."""

    context: AgentContext | None = None
    model: Model | None = None
    thinking_level: ThinkingLevel | None = None


@dataclass(slots=True)
class AgentLoopConfig:
    """Everything the loop needs beyond the context and the stream function.

    Every hook must not raise. Raising interrupts the loop without producing a
    normal event sequence; return a safe fallback instead.
    """

    model: Model

    #: Projects transcript messages onto provider messages before each call.
    #: Deviation D4: pi requires this, PiPy defaults it for bare-loop use.
    convert_to_llm: Callable[[list[AgentMessage]], list[Message] | Awaitable[list[Message]]] = (
        default_convert_to_llm
    )
    #: Applied to the transcript before ``convert_to_llm``. Use for context
    #: window management or injecting external context.
    transform_context: (
        Callable[[list[AgentMessage], AbortSignal | None], Awaitable[list[AgentMessage]]] | None
    ) = None
    #: Resolves an API key per request, for short-lived OAuth tokens that can
    #: expire during a long tool phase.
    get_api_key: Callable[[str], str | None | Awaitable[str | None]] | None = None
    #: Called after ``turn_end``. Returning true ends the run before the queues
    #: are polled and before another provider request starts.
    should_stop_after_turn: Callable[[TurnContext], bool | Awaitable[bool]] | None = None
    #: Called after ``turn_end`` and before the loop decides to continue.
    prepare_next_turn: (
        Callable[[TurnContext], AgentLoopTurnUpdate | None | Awaitable[AgentLoopTurnUpdate | None]]
        | None
    ) = None
    #: Messages injected mid-run, polled at the start and after each turn.
    get_steering_messages: (
        Callable[[], Sequence[AgentMessage] | Awaitable[Sequence[AgentMessage]]] | None
    ) = None
    #: Messages processed after the agent would otherwise stop.
    get_follow_up_messages: (
        Callable[[], Sequence[AgentMessage] | Awaitable[Sequence[AgentMessage]]] | None
    ) = None
    tool_execution: ToolExecutionMode = "parallel"
    before_tool_call: (
        Callable[
            [BeforeToolCallContext, AbortSignal | None],
            BeforeToolCallResult | None | Awaitable[BeforeToolCallResult | None],
        ]
        | None
    ) = None
    after_tool_call: (
        Callable[
            [AfterToolCallContext, AbortSignal | None],
            AfterToolCallResult | None | Awaitable[AfterToolCallResult | None],
        ]
        | None
    ) = None
    api_key: str | None = None
    reasoning: ThinkingLevel | None = None
    stream_options: StreamOptions = field(default_factory=StreamOptions)


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def agent_loop(
    prompts: Sequence[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    signal: AbortSignal | None,
    stream_fn: StreamFn,
) -> EventStream[AgentEvent, list[AgentMessage]]:
    """Start a run with new prompt messages, returning a consumable stream."""
    stream = _create_agent_stream()

    async def drive() -> None:
        try:
            messages = await run_agent_loop(
                prompts, context, config, stream.push, signal, stream_fn
            )
        except BaseException as error:  # noqa: BLE001 - surfaced to the consumer
            stream.fail(error)
            return
        stream.end(messages)

    asyncio.ensure_future(drive())
    return stream


def agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    signal: AbortSignal | None,
    stream_fn: StreamFn,
) -> EventStream[AgentEvent, list[AgentMessage]]:
    """Continue from the current context without adding a message."""
    _assert_continuable(context)
    stream = _create_agent_stream()

    async def drive() -> None:
        try:
            messages = await run_agent_loop_continue(
                context, config, stream.push, signal, stream_fn
            )
        except BaseException as error:  # noqa: BLE001 - surfaced to the consumer
            stream.fail(error)
            return
        stream.end(messages)

    asyncio.ensure_future(drive())
    return stream


async def run_agent_loop(
    prompts: Sequence[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    signal: AbortSignal | None,
    stream_fn: StreamFn,
) -> list[AgentMessage]:
    """Run a loop that begins with new prompt messages."""
    new_messages: list[AgentMessage] = list(prompts)
    current_context = AgentContext(
        system_prompt=context.system_prompt,
        messages=[*context.messages, *prompts],
        tools=context.tools,
    )

    await _emit(emit, AgentStartEvent())
    await _emit(emit, TurnStartEvent())
    for prompt in prompts:
        await _emit(emit, MessageStartEvent(message=prompt))
        await _emit(emit, MessageEndEvent(message=prompt))

    await _run_loop(current_context, new_messages, config, signal, emit, stream_fn)
    return new_messages


async def run_agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    signal: AbortSignal | None,
    stream_fn: StreamFn,
) -> list[AgentMessage]:
    """Run a loop that continues from an existing context.

    The last context message must convert to a user or tool-result message, or
    the provider will reject the request. That cannot be checked here because
    ``convert_to_llm`` runs once per turn, so only the raw role is rejected.
    """
    _assert_continuable(context)

    new_messages: list[AgentMessage] = []
    current_context = AgentContext(
        system_prompt=context.system_prompt,
        messages=context.messages,
        tools=context.tools,
    )

    await _emit(emit, AgentStartEvent())
    await _emit(emit, TurnStartEvent())

    await _run_loop(current_context, new_messages, config, signal, emit, stream_fn)
    return new_messages


def _assert_continuable(context: AgentContext) -> None:
    if not context.messages:
        raise ValueError("Cannot continue: no messages in context")
    if isinstance(context.messages[-1], AssistantMessage):
        raise ValueError("Cannot continue from message role: assistant")


def _create_agent_stream() -> EventStream[AgentEvent, list[AgentMessage]]:
    return EventStream(
        lambda event: getattr(event, "type", "") == "agent_end",
        lambda event: list(getattr(event, "messages", []) or []),
    )


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #


async def _run_loop(
    initial_context: AgentContext,
    new_messages: list[AgentMessage],
    initial_config: AgentLoopConfig,
    signal: AbortSignal | None,
    emit: AgentEventSink,
    stream_fn: StreamFn,
) -> None:
    current_context = initial_context
    config = initial_config
    first_turn = True
    # The user may have typed while the previous run was finishing.
    pending = await _poll_queue(config.get_steering_messages)

    while True:
        has_more_tool_calls = True

        # Inner loop: assistant turns, their tool calls, and steering messages.
        while has_more_tool_calls or pending:
            if not first_turn:
                await _emit(emit, TurnStartEvent())
            else:
                first_turn = False

            if pending:
                for message in pending:
                    await _emit(emit, MessageStartEvent(message=message))
                    await _emit(emit, MessageEndEvent(message=message))
                    current_context.messages.append(message)
                    new_messages.append(message)
                pending = []

            message = await _stream_assistant_response(
                current_context, config, signal, emit, stream_fn
            )
            new_messages.append(message)

            if message.stop_reason in ("error", "aborted"):
                await _emit(emit, TurnEndEvent(message=message, tool_results=[]))
                await _emit(emit, AgentEndEvent(messages=new_messages))
                return

            tool_calls = [block for block in message.content if isinstance(block, ToolCall)]
            tool_results: list[ToolResultMessage] = []
            has_more_tool_calls = False
            if tool_calls:
                # A "length" stop means the output was cut off by the token
                # limit, so every tool call in the message may carry truncated
                # arguments. Fail them all instead of executing borked calls.
                if message.stop_reason == "length":
                    batch = await _fail_tool_calls_from_truncated_message(tool_calls, emit)
                else:
                    batch = await _execute_tool_calls(
                        current_context, message, tool_calls, config, signal, emit
                    )
                tool_results.extend(batch.messages)
                has_more_tool_calls = not batch.terminate

                for result in tool_results:
                    current_context.messages.append(result)
                    new_messages.append(result)

            await _emit(emit, TurnEndEvent(message=message, tool_results=tool_results))

            if config.prepare_next_turn is not None:
                update = await _maybe_await(
                    config.prepare_next_turn(
                        TurnContext(message, tool_results, current_context, new_messages)
                    )
                )
                if update is not None:
                    current_context = update.context or current_context
                    config = replace(
                        config,
                        model=update.model or config.model,
                        reasoning=_next_reasoning(config.reasoning, update.thinking_level),
                    )

            if config.should_stop_after_turn is not None:
                stop = await _maybe_await(
                    config.should_stop_after_turn(
                        TurnContext(message, tool_results, current_context, new_messages)
                    )
                )
                if stop:
                    await _emit(emit, AgentEndEvent(messages=new_messages))
                    return

            pending = await _poll_queue(config.get_steering_messages)

        # The agent would stop here. Follow-ups get one more pass.
        follow_ups = await _poll_queue(config.get_follow_up_messages)
        if follow_ups:
            pending = follow_ups
            continue
        break

    await _emit(emit, AgentEndEvent(messages=new_messages))


def _next_reasoning(
    current: ThinkingLevel | None,
    requested: ThinkingLevel | None,
) -> ThinkingLevel | None:
    if requested is None:
        return current
    return None if requested == "off" else requested


async def _stream_assistant_response(
    context: AgentContext,
    config: AgentLoopConfig,
    signal: AbortSignal | None,
    emit: AgentEventSink,
    stream_fn: StreamFn,
) -> AssistantMessage:
    messages = context.messages
    if config.transform_context is not None:
        messages = await _maybe_await(config.transform_context(messages, signal))

    llm_messages = await _maybe_await(config.convert_to_llm(messages))

    llm_context = Context(
        system_prompt=context.system_prompt,
        messages=list(llm_messages),
        tools=context.tools,
    )

    resolved_api_key = config.api_key
    if config.get_api_key is not None:
        resolved = await _maybe_await(config.get_api_key(config.model.provider))
        resolved_api_key = resolved or config.api_key

    options = replace(
        config.stream_options,
        api_key=resolved_api_key,
        reasoning=config.reasoning,
        signal=signal,
    )
    response = await _maybe_await(stream_fn(config.model, llm_context, options))

    partial: AssistantMessage | None = None
    added_partial = False
    final: AssistantMessage | None = None

    async for event in response:
        if isinstance(event, AssistantStartEvent):
            partial = event.partial
            context.messages.append(partial)
            added_partial = True
            await _emit(emit, MessageStartEvent(message=partial))
        elif isinstance(event, (AssistantDoneEvent, AssistantErrorEvent)):
            final = event.message if isinstance(event, AssistantDoneEvent) else event.error
            break
        elif partial is not None:
            partial = event.partial
            context.messages[-1] = partial
            await _emit(emit, MessageUpdateEvent(message=partial, assistant_message_event=event))

    if final is None:
        final = _error_message(
            config.model,
            "Provider stream ended without a terminal done or error event",
        )

    if added_partial:
        context.messages[-1] = final
    else:
        context.messages.append(final)
        await _emit(emit, MessageStartEvent(message=final))
    await _emit(emit, MessageEndEvent(message=final))
    return final


# --------------------------------------------------------------------------- #
# Tool execution
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _ExecutedBatch:
    messages: list[ToolResultMessage]
    terminate: bool


@dataclass(slots=True)
class _Prepared:
    tool_call: ToolCall
    tool: AgentTool
    args: JSONObject


@dataclass(slots=True)
class _Finalized:
    tool_call: ToolCall
    result: AgentToolResult
    is_error: bool


async def _fail_tool_calls_from_truncated_message(
    tool_calls: list[ToolCall],
    emit: AgentEventSink,
) -> _ExecutedBatch:
    """Fail every tool call of a message that hit the output token limit.

    Streamed tool-call arguments are finalized with a best-effort salvage
    parser, so a truncated message can yield calls whose arguments parse and
    validate but are silently incomplete. None are safe to execute.
    """
    messages: list[ToolResultMessage] = []
    for tool_call in tool_calls:
        await _emit(emit, _start_event(tool_call))
        finalized = _Finalized(
            tool_call=tool_call,
            result=_error_result(
                f'Tool call "{tool_call.name}" was not executed: the response hit the '
                "output token limit, so its arguments may be truncated. Re-issue the "
                "tool call with complete arguments."
            ),
            is_error=True,
        )
        await _emit(emit, _end_event(finalized))
        message = _tool_result_message(finalized)
        await _emit_tool_result_message(message, emit)
        messages.append(message)
    return _ExecutedBatch(messages=messages, terminate=False)


async def _execute_tool_calls(
    context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[ToolCall],
    config: AgentLoopConfig,
    signal: AbortSignal | None,
    emit: AgentEventSink,
) -> _ExecutedBatch:
    tools_by_name = {tool.name: tool for tool in context.tools or []}
    has_sequential_call = any(
        (tools_by_name.get(call.name).execution_mode if call.name in tools_by_name else None)
        == "sequential"
        for call in tool_calls
    )
    if config.tool_execution == "sequential" or has_sequential_call:
        return await _execute_sequential(
            context, assistant_message, tool_calls, tools_by_name, config, signal, emit
        )
    return await _execute_parallel(
        context, assistant_message, tool_calls, tools_by_name, config, signal, emit
    )


async def _execute_sequential(
    context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[ToolCall],
    tools_by_name: dict[str, AgentTool],
    config: AgentLoopConfig,
    signal: AbortSignal | None,
    emit: AgentEventSink,
) -> _ExecutedBatch:
    finalized_calls: list[_Finalized] = []
    messages: list[ToolResultMessage] = []

    for tool_call in tool_calls:
        await _emit(emit, _start_event(tool_call))

        prepared = await _prepare_tool_call(
            context, assistant_message, tool_call, tools_by_name, config, signal
        )
        if isinstance(prepared, _Finalized):
            finalized = prepared
        else:
            executed, executed_is_error = await _execute_prepared(prepared, signal, emit)
            finalized = await _finalize(
                context, assistant_message, prepared, executed, executed_is_error, config, signal
            )

        await _emit(emit, _end_event(finalized))
        message = _tool_result_message(finalized)
        await _emit_tool_result_message(message, emit)
        finalized_calls.append(finalized)
        messages.append(message)

        if is_aborted(signal):
            break

    return _ExecutedBatch(messages=messages, terminate=_should_terminate(finalized_calls))


async def _execute_parallel(
    context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[ToolCall],
    tools_by_name: dict[str, AgentTool],
    config: AgentLoopConfig,
    signal: AbortSignal | None,
    emit: AgentEventSink,
) -> _ExecutedBatch:
    # Preparation stays sequential so hooks see calls in assistant order, then
    # the executable ones run concurrently. `tool_execution_end` therefore lands
    # in completion order, while the tool-result messages below stay in source
    # order so the transcript matches what the model emitted.
    entries: list[_Finalized | Callable[[], Awaitable[_Finalized]]] = []

    for tool_call in tool_calls:
        await _emit(emit, _start_event(tool_call))

        prepared = await _prepare_tool_call(
            context, assistant_message, tool_call, tools_by_name, config, signal
        )
        if isinstance(prepared, _Finalized):
            await _emit(emit, _end_event(prepared))
            entries.append(prepared)
            if is_aborted(signal):
                break
            continue

        def make_runner(prepared: _Prepared) -> Callable[[], Awaitable[_Finalized]]:
            async def run() -> _Finalized:
                executed, executed_is_error = await _execute_prepared(prepared, signal, emit)
                finalized = await _finalize(
                    context,
                    assistant_message,
                    prepared,
                    executed,
                    executed_is_error,
                    config,
                    signal,
                )
                await _emit(emit, _end_event(finalized))
                return finalized

            return run

        entries.append(make_runner(prepared))
        if is_aborted(signal):
            break

    ordered = await asyncio.gather(*(_resolve_entry(entry) for entry in entries))

    messages: list[ToolResultMessage] = []
    for finalized in ordered:
        message = _tool_result_message(finalized)
        await _emit_tool_result_message(message, emit)
        messages.append(message)

    return _ExecutedBatch(messages=messages, terminate=_should_terminate(list(ordered)))


async def _resolve_entry(entry: _Finalized | Callable[[], Awaitable[_Finalized]]) -> _Finalized:
    if isinstance(entry, _Finalized):
        return entry
    return await entry()


def _should_terminate(finalized_calls: list[_Finalized]) -> bool:
    return bool(finalized_calls) and all(
        finalized.result.terminate is True for finalized in finalized_calls
    )


async def _prepare_tool_call(
    context: AgentContext,
    assistant_message: AssistantMessage,
    tool_call: ToolCall,
    tools_by_name: dict[str, AgentTool],
    config: AgentLoopConfig,
    signal: AbortSignal | None,
) -> _Prepared | _Finalized:
    tool = tools_by_name.get(tool_call.name)
    if tool is None:
        return _immediate(tool_call, f"Tool {tool_call.name} not found")

    try:
        raw_args = dict(tool_call.arguments)
        if tool.prepare_arguments is not None:
            raw_args = dict(tool.prepare_arguments(raw_args))
        validated = validate_tool_arguments(tool.name, tool.parameters, raw_args)

        if config.before_tool_call is not None:
            before = await _maybe_await(
                config.before_tool_call(
                    BeforeToolCallContext(
                        assistant_message=assistant_message,
                        tool_call=tool_call,
                        args=validated,
                        context=context,
                    ),
                    signal,
                )
            )
            if is_aborted(signal):
                return _immediate(tool_call, "Operation aborted")
            if before is not None and before.block:
                return _immediate(tool_call, before.reason or "Tool execution was blocked")

        if is_aborted(signal):
            return _immediate(tool_call, "Operation aborted")

        return _Prepared(tool_call=tool_call, tool=tool, args=validated)
    except Exception as error:  # noqa: BLE001 - preparation failures become results
        return _immediate(tool_call, str(error))


async def _execute_prepared(
    prepared: _Prepared,
    signal: AbortSignal | None,
    emit: AgentEventSink,
) -> tuple[AgentToolResult, bool]:
    pending: list[asyncio.Future[Any]] = []
    accepting = True

    def on_update(partial: AgentToolResult) -> None:
        # Emitted live, exactly like pi: the sink is called from inside the
        # callback and only the awaiting of async sinks is deferred.
        if not accepting:
            return
        outcome = emit(
            ToolExecutionUpdateEvent(
                tool_call_id=prepared.tool_call.id,
                tool_name=prepared.tool_call.name,
                args=dict(prepared.tool_call.arguments),
                partial_result=partial.copy(),
            )
        )
        if inspect.isawaitable(outcome):
            pending.append(asyncio.ensure_future(outcome))

    try:
        result = await prepared.tool.execute(
            prepared.tool_call.id, prepared.args, signal, on_update
        )
        accepting = False
        if pending:
            await asyncio.gather(*pending)
        return result, False
    except asyncio.CancelledError:
        accepting = False
        raise
    except Exception as error:  # noqa: BLE001 - tools are an isolation boundary
        accepting = False
        if pending:
            await asyncio.gather(*pending)
        return _error_result(str(error)), True
    finally:
        accepting = False


async def _finalize(
    context: AgentContext,
    assistant_message: AssistantMessage,
    prepared: _Prepared,
    result: AgentToolResult,
    is_error: bool,
    config: AgentLoopConfig,
    signal: AbortSignal | None,
) -> _Finalized:
    if config.after_tool_call is not None:
        try:
            patch = await _maybe_await(
                config.after_tool_call(
                    AfterToolCallContext(
                        assistant_message=assistant_message,
                        tool_call=prepared.tool_call,
                        args=prepared.args,
                        result=result,
                        is_error=is_error,
                        context=context,
                    ),
                    signal,
                )
            )
            if patch is not None:
                result = replace(
                    result,
                    content=patch.content if patch.content is not None else result.content,
                    details=patch.details if patch.details is not None else result.details,
                    usage=patch.usage if patch.usage is not None else result.usage,
                    terminate=patch.terminate if patch.terminate is not None else result.terminate,
                )
                if patch.is_error is not None:
                    is_error = patch.is_error
        except Exception as error:  # noqa: BLE001 - hook failures become results
            result = _error_result(str(error))
            is_error = True

    return _Finalized(tool_call=prepared.tool_call, result=result, is_error=is_error)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _immediate(tool_call: ToolCall, message: str) -> _Finalized:
    return _Finalized(tool_call=tool_call, result=_error_result(message), is_error=True)


def _error_result(message: str) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=message)], details={})


def _error_message(model: Model, message: str) -> AssistantMessage:
    return AssistantMessage(
        content=[],
        api=model.api,
        provider=model.provider,
        model=model.id,
        stop_reason="error",
        error_message=message,
    )


def _start_event(tool_call: ToolCall) -> ToolExecutionStartEvent:
    return ToolExecutionStartEvent(
        tool_call_id=tool_call.id,
        tool_name=tool_call.name,
        args=dict(tool_call.arguments),
    )


def _end_event(finalized: _Finalized) -> ToolExecutionEndEvent:
    return ToolExecutionEndEvent(
        tool_call_id=finalized.tool_call.id,
        tool_name=finalized.tool_call.name,
        result=finalized.result,
        is_error=finalized.is_error,
    )


def _tool_result_message(finalized: _Finalized) -> ToolResultMessage:
    added = finalized.result.added_tool_names
    return ToolResultMessage(
        tool_call_id=finalized.tool_call.id,
        tool_name=finalized.tool_call.name,
        # Untyped tools can return results without content; normalize so that
        # never reaches session history or a provider payload.
        content=list(finalized.result.content or []),
        details=finalized.result.details,
        usage=finalized.result.usage,
        added_tool_names=list(added) if added else None,
        is_error=finalized.is_error,
    )


async def _emit_tool_result_message(message: ToolResultMessage, emit: AgentEventSink) -> None:
    await _emit(emit, MessageStartEvent(message=message))
    await _emit(emit, MessageEndEvent(message=message))


async def _emit(emit: AgentEventSink, event: AgentEvent) -> None:
    outcome = emit(event)
    if inspect.isawaitable(outcome):
        await outcome


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _poll_queue(
    getter: Callable[[], Sequence[AgentMessage] | Awaitable[Sequence[AgentMessage]]] | None,
) -> list[AgentMessage]:
    if getter is None:
        return []
    return list(await _maybe_await(getter()) or [])


__all__ = [
    "AfterToolCallContext",
    "AfterToolCallResult",
    "AgentContext",
    "AgentEventSink",
    "AgentLoopConfig",
    "AgentLoopTurnUpdate",
    "BeforeToolCallContext",
    "BeforeToolCallResult",
    "TurnContext",
    "agent_loop",
    "agent_loop_continue",
    "run_agent_loop",
    "run_agent_loop_continue",
]
