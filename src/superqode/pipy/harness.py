"""The stateful agent brain: session-backed, steerable, abortable.

Port of ``packages/agent/src/harness/agent-harness.ts`` from earendil-works/pi
(MIT). See NOTICE.

The important structural point, and the one the first draft of PiPy missed: the
harness does not keep a message list. Every turn rebuilds its state from the
session tree, and every completed message is written back to it. That is what
makes branching, resuming and compaction possible without the loop knowing
anything about them.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from .compaction import (
    DEFAULT_COMPACTION_SETTINGS,
    CompactionSettings,
    CompactResult,
    calculate_context_tokens,
    generate_branch_summary,
    generate_summary,
    get_last_assistant_usage,
    prepare_compaction,
    should_compact,
)
from .event_stream import EventStream
from .events import (
    AgentEndEvent,
    AgentEvent,
    MessageEndEvent,
    MessageStartEvent,
    TurnEndEvent,
    event_type,
)
from .harness_events import (
    AbortEvent,
    AbortResult,
    AfterProviderResponseEvent,
    AgentHarnessError,
    BeforeAgentStartEvent,
    BeforeAgentStartResult,
    BeforeProviderRequestEvent,
    BeforeProviderRequestResult,
    ContextEvent,
    ContextResult,
    HarnessOwnEvent,
    ModelUpdateEvent,
    QueueUpdateEvent,
    SavePointEvent,
    SettledEvent,
    ThinkingLevelUpdateEvent,
    ToolCallEvent,
    ToolCallResult,
    ToolResultEvent,
    ToolResultPatch,
    ToolsUpdateEvent,
    to_error,
)
from .loop import (
    AfterToolCallResult,
    AgentContext,
    AgentLoopConfig,
    AgentLoopTurnUpdate,
    BeforeToolCallResult,
    run_agent_loop,
)
from .messages import (
    AgentMessage,
    AssistantMessage,
    ImageContent,
    TextContent,
    UserMessage,
    default_convert_to_llm,
)
from .session import Session, SessionError
from .signals import AbortController, AbortSignal
from .stream import Model, StreamFn, StreamOptions
from .tools.base import AgentTool
from .types import QueueMode, ThinkingLevel

HarnessPhase = Literal["idle", "turn", "compaction", "branch_summary"]

#: Subscribers receive every agent and harness event and return nothing.
Subscriber = Callable[[AgentEvent | HarnessOwnEvent], Awaitable[None] | None]
#: Hooks are registered per event type and may return a patch.
Hook = Callable[[Any], Any]

_SUBSCRIBER_KEY = "*"


@dataclass(slots=True)
class HarnessResources:
    """Skills and prompt templates available to a run. Filled in by phase 5."""

    skills: tuple[Any, ...] = ()
    prompt_templates: tuple[Any, ...] = ()


#: Builds the system prompt for a turn. Receives the harness so it can read the
#: model, thinking level, active tools and resources.
SystemPromptSource = str | Callable[["TurnState"], str | Awaitable[str]]


@dataclass(slots=True)
class TurnState:
    """Immutable snapshot of everything one turn runs against."""

    messages: list[AgentMessage]
    session_id: str
    system_prompt: str
    model: Model
    thinking_level: ThinkingLevel
    tools: list[AgentTool]
    active_tools: list[AgentTool]
    resources: HarnessResources
    stream_options: StreamOptions


@dataclass(slots=True)
class _PendingWrite:
    """A session write deferred until the current turn reaches a save point."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


def _create_user_message(text: str, images: Sequence[ImageContent] | None = None) -> UserMessage:
    content: list[Any] = [TextContent(text=text)]
    if images:
        content.extend(images)
    return UserMessage(content=content)


def _failure_message(model: Model, error: BaseException, aborted: bool) -> AssistantMessage:
    return AssistantMessage(
        content=[TextContent(text="")],
        api=model.api,
        provider=model.provider,
        model=model.id,
        stop_reason="aborted" if aborted else "error",
        error_message=str(error),
    )


def _normalize_error(error: BaseException, fallback_code: str) -> AgentHarnessError:
    if isinstance(error, AgentHarnessError):
        return error
    if isinstance(error, SessionError):
        return AgentHarnessError("session", str(error), error)
    return AgentHarnessError(fallback_code, str(error), error)


class AgentHarness:
    """Reusable agent brain over a session tree.

    Not tied to coding, to a UI, or to SuperQode policy. The coding session in
    phase 7 supplies the tools, the prompt and the resources; this class owns
    lifecycle, queues, hooks and the session write-back.
    """

    def __init__(
        self,
        *,
        session: Session,
        model: Model,
        stream_fn: StreamFn,
        tools: Sequence[AgentTool] = (),
        active_tool_names: Sequence[str] | None = None,
        system_prompt: SystemPromptSource | None = None,
        thinking_level: ThinkingLevel = "off",
        steering_mode: QueueMode = "one-at-a-time",
        follow_up_mode: QueueMode = "one-at-a-time",
        resources: HarnessResources | None = None,
        stream_options: StreamOptions | None = None,
        compaction_settings: CompactionSettings | None = None,
        max_turns: int = 0,
    ) -> None:
        self._session = session
        self._model = model
        self._stream_fn = stream_fn
        self._compaction_settings = compaction_settings or DEFAULT_COMPACTION_SETTINGS
        # Zero means the loop runs until the model stops. A cap
        # is for unattended runs, where nobody is watching to interrupt one.
        self._max_turns = max(0, int(max_turns))
        self._system_prompt = system_prompt
        self._thinking_level: ThinkingLevel = thinking_level
        self._resources = resources or HarnessResources()
        self._stream_options = stream_options or StreamOptions()

        names = [tool.name for tool in tools]
        self._validate_unique(names, "Duplicate tool name(s)")
        self._tools: dict[str, AgentTool] = {tool.name: tool for tool in tools}

        self._active_tool_names = list(active_tool_names) if active_tool_names else list(names)
        self._validate_unique(self._active_tool_names, "Duplicate active tool name(s)")
        self._validate_known(self._active_tool_names)

        self._steering_mode: QueueMode = steering_mode
        self._follow_up_mode: QueueMode = follow_up_mode

        self._phase: HarnessPhase = "idle"
        self._steer_queue: list[AgentMessage] = []
        self._follow_up_queue: list[AgentMessage] = []
        self._next_turn_queue: list[AgentMessage] = []
        self._pending_writes: list[_PendingWrite] = []

        self._handlers: dict[str, list[Hook]] = {}
        self._active_controller: AbortController | None = None
        self._operations: set[asyncio.Future[None]] = set()
        self._is_shutdown = False
        self._shutdown_waiter: asyncio.Future[None] | None = None

    # -- introspection ---------------------------------------------------- #

    @property
    def session(self) -> Session:
        return self._session

    @property
    def phase(self) -> HarnessPhase:
        return self._phase

    @property
    def is_running(self) -> bool:
        return self._phase != "idle"

    @property
    def is_shutdown(self) -> bool:
        return self._is_shutdown

    def get_model(self) -> Model:
        return self._model

    def get_thinking_level(self) -> ThinkingLevel:
        return self._thinking_level

    def get_tools(self) -> list[AgentTool]:
        return list(self._tools.values())

    def get_active_tools(self) -> list[AgentTool]:
        return [self._tools[name] for name in self._active_tool_names if name in self._tools]

    def get_steering_mode(self) -> QueueMode:
        return self._steering_mode

    def get_follow_up_mode(self) -> QueueMode:
        return self._follow_up_mode

    def get_resources(self) -> HarnessResources:
        return self._resources

    def queued_messages(self) -> QueueUpdateEvent:
        return QueueUpdateEvent(
            steer=list(self._steer_queue),
            follow_up=list(self._follow_up_queue),
            next_turn=list(self._next_turn_queue),
        )

    # -- listeners -------------------------------------------------------- #

    def subscribe(self, listener: Subscriber) -> Callable[[], None]:
        """Receive every agent and harness event. Returns an unsubscribe."""
        self._assert_not_shut_down()
        return self._add_handler(_SUBSCRIBER_KEY, listener)

    def on(self, event_type_name: str, handler: Hook) -> Callable[[], None]:
        """Register a hook for one event type. Returns an unsubscribe."""
        self._assert_not_shut_down()
        return self._add_handler(event_type_name, handler)

    def _add_handler(self, key: str, handler: Hook) -> Callable[[], None]:
        handlers = self._handlers.setdefault(key, [])
        handlers.append(handler)

        def unsubscribe() -> None:
            if handler in handlers:
                handlers.remove(handler)

        return unsubscribe

    # -- mutations -------------------------------------------------------- #

    async def set_model(self, model: Model) -> None:
        self._assert_not_shut_down()
        self._model = model
        await self._write_or_defer(
            _PendingWrite("model_change", {"provider": model.provider, "model_id": model.id})
        )
        await self._emit_own(ModelUpdateEvent(model=model))

    async def set_thinking_level(self, level: ThinkingLevel) -> None:
        self._assert_not_shut_down()
        self._thinking_level = level
        await self._write_or_defer(_PendingWrite("thinking_level_change", {"level": level}))
        await self._emit_own(ThinkingLevelUpdateEvent(thinking_level=level))

    async def set_tools(
        self,
        tools: Sequence[AgentTool],
        active_tool_names: Sequence[str] | None = None,
    ) -> None:
        self._assert_not_shut_down()
        names = [tool.name for tool in tools]
        self._validate_unique(names, "Duplicate tool name(s)")
        registry = {tool.name: tool for tool in tools}
        next_active = list(active_tool_names) if active_tool_names is not None else names
        self._validate_unique(next_active, "Duplicate active tool name(s)")
        self._validate_known(next_active, registry)
        self._tools = registry
        self._active_tool_names = next_active
        await self._write_or_defer(_PendingWrite("active_tools_change", {"names": next_active}))
        await self._emit_own(
            ToolsUpdateEvent(tool_names=names, active_tool_names=list(next_active))
        )

    async def set_active_tools(self, tool_names: Sequence[str]) -> None:
        self._assert_not_shut_down()
        names = list(tool_names)
        self._validate_unique(names, "Duplicate active tool name(s)")
        self._validate_known(names)
        self._active_tool_names = names
        await self._write_or_defer(_PendingWrite("active_tools_change", {"names": names}))
        await self._emit_own(
            ToolsUpdateEvent(tool_names=list(self._tools), active_tool_names=names)
        )

    async def set_steering_mode(self, mode: QueueMode) -> None:
        self._steering_mode = mode

    async def set_follow_up_mode(self, mode: QueueMode) -> None:
        self._follow_up_mode = mode

    async def set_resources(self, resources: HarnessResources) -> None:
        self._resources = resources

    async def append_message(self, message: AgentMessage) -> None:
        """Add a message to the transcript without starting a run."""
        self._assert_not_shut_down()
        await self._write_or_defer(_PendingWrite("message", {"message": message}))

    # -- queues ----------------------------------------------------------- #

    async def steer(self, text: str, images: Sequence[ImageContent] | None = None) -> None:
        """Queue a message to be injected after the current turn's tools."""
        self._assert_not_shut_down()
        self._steer_queue.append(_create_user_message(text, images))
        await self._emit_queue_update()

    async def follow_up(self, text: str, images: Sequence[ImageContent] | None = None) -> None:
        """Queue a message for when the agent would otherwise stop."""
        self._assert_not_shut_down()
        self._follow_up_queue.append(_create_user_message(text, images))
        await self._emit_queue_update()

    async def next_turn(self, text: str, images: Sequence[ImageContent] | None = None) -> None:
        """Queue a message to lead the next prompt, before the user's own text."""
        self._assert_not_shut_down()
        self._next_turn_queue.append(_create_user_message(text, images))
        await self._emit_queue_update()

    # -- running ---------------------------------------------------------- #

    async def prompt(
        self,
        text: str,
        images: Sequence[ImageContent] | None = None,
    ) -> AssistantMessage:
        """Run a turn to completion and return the final assistant message."""
        self._assert_not_shut_down()
        if self._phase != "idle":
            raise AgentHarnessError("busy", "AgentHarness is busy")
        self._phase = "turn"
        signal, finish = self._start_operation()
        try:
            turn_state = await self._create_turn_state()
            return await self._execute_turn(turn_state, text, signal, images)
        except BaseException as error:
            self._phase = "idle"
            raise _normalize_error(to_error(error), "unknown") from error
        finally:
            finish()

    def prompt_events(
        self,
        text: str,
        images: Sequence[ImageContent] | None = None,
    ) -> EventStream[AgentEvent | HarnessOwnEvent, AssistantMessage]:
        """Run a turn, streaming events instead of awaiting the final message.

        The stream is settled explicitly once the run returns, not by a terminal
        event: ``settled`` is emitted before the final message is known.
        """
        stream: EventStream[Any, AssistantMessage] = EventStream(
            lambda event: False,
            lambda event: None,  # type: ignore[arg-type,return-value]
        )
        unsubscribe = self.subscribe(stream.push)

        async def drive() -> None:
            try:
                message = await self.prompt(text, images)
            except BaseException as error:  # noqa: BLE001 - surfaced to the consumer
                unsubscribe()
                stream.fail(error)
                return
            unsubscribe()
            stream.end(message)

        asyncio.ensure_future(drive())
        return stream

    async def compact(self, custom_instructions: str | None = None) -> CompactResult | None:
        """Summarize older context and append a compaction entry.

        Returns None when there is nothing old enough to be worth summarizing.
        Nothing is deleted: the entry records where the context builder should
        cut, and the full history stays in the tree.
        """
        self._assert_not_shut_down()
        if self._phase != "idle":
            raise AgentHarnessError("busy", "AgentHarness is busy")
        self._phase = "compaction"
        signal, finish = self._start_operation()
        try:
            branch = await self._session.get_branch()
            preparation = prepare_compaction(branch, self._compaction_settings)
            if preparation is None:
                return None
            summary, usage = await generate_summary(
                preparation,
                stream_fn=self._stream_fn,
                model=self._model,
                custom_instructions=custom_instructions,
                signal=signal,
            )
            await self._session.append_compaction(
                summary,
                tokens_before=preparation.tokens_before,
                first_kept_entry_id=preparation.first_kept_entry_id,
                usage=usage,
            )
            return CompactResult(
                summary=summary,
                first_kept_entry_id=preparation.first_kept_entry_id,
                tokens_before=preparation.tokens_before,
                usage=usage,
            )
        except BaseException as error:
            raise _normalize_error(to_error(error), "compaction") from error
        finally:
            self._phase = "idle"
            finish()

    async def navigate_tree(
        self,
        entry_id: str | None,
        *,
        summarize: bool = True,
    ) -> str | None:
        """Move the leaf to another entry, summarizing the branch left behind.

        Returns the summary when one was generated. The abandoned branch stays
        in the tree, so navigating back to it later is lossless.
        """
        self._assert_not_shut_down()
        if self._phase != "idle":
            raise AgentHarnessError("busy", "AgentHarness is busy")
        self._phase = "branch_summary"
        signal, finish = self._start_operation()
        try:
            summary: str | None = None
            usage = None
            if summarize:
                current = await self._session.get_branch()
                target = await self._session.get_branch_from(entry_id)
                target_ids = {entry.id for entry in target}
                abandoned = [entry for entry in current if entry.id not in target_ids]
                if abandoned:
                    try:
                        summary, usage = await generate_branch_summary(
                            abandoned,
                            stream_fn=self._stream_fn,
                            model=self._model,
                            signal=signal,
                        )
                    except Exception:
                        # A failed summary must not block navigation. The move
                        # is the user's intent; the summary is a convenience.
                        summary = None
            await self._session.move_to(
                entry_id,
                {"summary": summary, "usage": usage} if summary else None,
            )
            return summary
        except BaseException as error:
            raise _normalize_error(to_error(error), "branch_summary") from error
        finally:
            self._phase = "idle"
            finish()

    async def abort(self) -> AbortResult:
        """Cancel the active run and clear the steer and follow-up queues."""
        self._assert_not_shut_down()
        cleared_steer = list(self._steer_queue)
        cleared_follow_up = list(self._follow_up_queue)
        self._steer_queue.clear()
        self._follow_up_queue.clear()
        if self._active_controller is not None:
            self._active_controller.abort()

        errors: list[BaseException] = []
        for step in (
            self._emit_queue_update(),
            self.wait_for_idle(),
            self._emit_own(
                AbortEvent(cleared_steer=cleared_steer, cleared_follow_up=cleared_follow_up)
            ),
        ):
            try:
                await step
            except BaseException as error:  # noqa: BLE001 - reported together below
                errors.append(error)

        if errors:
            raise _normalize_error(errors[0], "hook")
        return AbortResult(cleared_steer=cleared_steer, cleared_follow_up=cleared_follow_up)

    async def wait_for_idle(self) -> None:
        """Wait until no run is in flight."""
        while self._operations:
            await asyncio.gather(*list(self._operations), return_exceptions=True)

    def request_shutdown(self) -> None:
        """Stop accepting work, cancel the active run and drop the queues."""
        if self._is_shutdown:
            return
        self._is_shutdown = True
        self._pending_writes.clear()
        self._steer_queue.clear()
        self._follow_up_queue.clear()
        self._next_turn_queue.clear()
        if self._active_controller is not None:
            self._active_controller.abort()
        self._shutdown_waiter = asyncio.ensure_future(self.wait_for_idle())

    async def wait_for_shutdown(self) -> None:
        """Wait for work that was active when shutdown was requested."""
        if self._shutdown_waiter is None:
            raise AgentHarnessError("invalid_state", "Shutdown has not been requested")
        await self._shutdown_waiter

    # -- turn machinery --------------------------------------------------- #

    async def _create_turn_state(self) -> TurnState:
        self._assert_not_shut_down()
        context = await self._session.build_context()
        metadata = await self._session.get_metadata()
        active_tools = self.get_active_tools()

        state = TurnState(
            messages=list(context.messages),
            session_id=metadata.id,
            system_prompt="You are a helpful assistant.",
            model=self._model,
            thinking_level=self._thinking_level,
            tools=self.get_tools(),
            active_tools=active_tools,
            resources=self._resources,
            stream_options=replace(self._stream_options),
        )
        if isinstance(self._system_prompt, str):
            state.system_prompt = self._system_prompt
        elif self._system_prompt is not None:
            state.system_prompt = await _maybe_await(self._system_prompt(state))
        return state

    def _create_context(
        self, turn_state: TurnState, system_prompt: str | None = None
    ) -> AgentContext:
        return AgentContext(
            system_prompt=system_prompt or turn_state.system_prompt,
            messages=list(turn_state.messages),
            tools=list(turn_state.active_tools),
        )

    async def _execute_turn(
        self,
        turn_state: TurnState,
        text: str,
        signal: AbortSignal,
        images: Sequence[ImageContent] | None,
    ) -> AssistantMessage:
        active_state = turn_state
        messages: list[AgentMessage] = [_create_user_message(text, images)]

        if self._next_turn_queue:
            queued = list(self._next_turn_queue)
            self._next_turn_queue.clear()
            try:
                await self._emit_queue_update()
            except BaseException as error:
                self._next_turn_queue[:0] = queued
                raise _normalize_error(to_error(error), "hook") from error
            messages = [*queued, *messages]

        before: BeforeAgentStartResult | None = await self._emit_hook(
            BeforeAgentStartEvent(
                prompt=text,
                system_prompt=turn_state.system_prompt,
                images=list(images or []),
            )
        )
        self._assert_not_shut_down()
        if before is not None and before.messages:
            messages = [*messages, *before.messages]

        def get_state() -> TurnState:
            return active_state

        def set_state(state: TurnState) -> None:
            nonlocal active_state
            active_state = state

        system_prompt = before.system_prompt if before is not None else None
        try:
            new_messages = await run_agent_loop(
                messages,
                self._create_context(turn_state, system_prompt),
                self._create_loop_config(get_state, set_state),
                lambda event: self._handle_agent_event(event, signal),
                signal,
                self._create_stream_fn(get_state),
            )
        except BaseException as error:  # noqa: BLE001 - reported as a failed turn
            new_messages = await self._emit_run_failure(
                active_state.model, to_error(error), signal.aborted, signal
            )
        finally:
            await self._flush_pending_writes()

        for message in reversed(new_messages):
            if isinstance(message, AssistantMessage):
                return message
        raise AgentHarnessError(
            "invalid_state", "AgentHarness prompt completed without an assistant message"
        )

    def _create_loop_config(
        self,
        get_state: Callable[[], TurnState],
        set_state: Callable[[TurnState], None],
    ) -> AgentLoopConfig:
        state = get_state()

        async def transform_context(messages: list[AgentMessage], signal: AbortSignal | None):
            result: ContextResult | None = await self._emit_hook(
                ContextEvent(messages=list(messages))
            )
            return (
                result.messages if result is not None and result.messages is not None else messages
            )

        async def before_tool_call(hook_context, signal):
            result: ToolCallResult | None = await self._emit_hook(
                ToolCallEvent(
                    tool_call_id=hook_context.tool_call.id,
                    tool_name=hook_context.tool_call.name,
                    input=dict(hook_context.args),
                )
            )
            if result is None:
                return None
            return BeforeToolCallResult(block=result.block, reason=result.reason)

        async def after_tool_call(hook_context, signal):
            patch: ToolResultPatch | None = await self._emit_hook(
                ToolResultEvent(
                    tool_call_id=hook_context.tool_call.id,
                    tool_name=hook_context.tool_call.name,
                    input=dict(hook_context.args),
                    content=list(hook_context.result.content),
                    details=hook_context.result.details,
                    is_error=hook_context.is_error,
                    usage=hook_context.result.usage,
                )
            )
            if patch is None:
                return None
            return AfterToolCallResult(
                content=patch.content,
                details=patch.details,
                is_error=patch.is_error,
                usage=patch.usage,
                terminate=patch.terminate,
            )

        async def prepare_next_turn(_turn_context) -> AgentLoopTurnUpdate:
            # Rebuilding from the session is what lets a compaction, a branch
            # move or a model change made mid-run take effect on the next turn.
            await self._flush_pending_writes()
            await self._auto_compact_if_needed()
            next_state = await self._create_turn_state()
            set_state(next_state)
            return AgentLoopTurnUpdate(
                context=self._create_context(next_state),
                model=next_state.model,
                thinking_level=next_state.thinking_level,
            )

        async def get_steering_messages() -> list[AgentMessage]:
            return await self._drain(self._steer_queue, self._steering_mode)

        async def get_follow_up_messages() -> list[AgentMessage]:
            return await self._drain(self._follow_up_queue, self._follow_up_mode)

        return AgentLoopConfig(
            model=state.model,
            convert_to_llm=default_convert_to_llm,
            reasoning=None if state.thinking_level == "off" else state.thinking_level,
            transform_context=transform_context,
            before_tool_call=before_tool_call,
            after_tool_call=after_tool_call,
            prepare_next_turn=prepare_next_turn,
            get_steering_messages=get_steering_messages,
            get_follow_up_messages=get_follow_up_messages,
            should_stop_after_turn=self._should_stop_after_turn if self._max_turns else None,
            stream_options=state.stream_options,
        )

    async def _should_stop_after_turn(self, turn_context) -> bool:
        """Stop once the configured turn cap is reached.

        pi has no cap because a person is watching the TUI and can interrupt.
        Unattended runs have nobody to do that, so callers there set one.
        """
        turns = sum(
            1 for message in turn_context.new_messages if isinstance(message, AssistantMessage)
        )
        return turns >= self._max_turns

    async def _auto_compact_if_needed(self) -> None:
        """Compact between turns when the next request would not fit.

        Uses the token counts the provider actually reported for the last turn,
        so this reflects real context use rather than an estimate. A model whose
        context window is unknown is left alone.
        """
        settings = self._compaction_settings
        window = self._model.context_window
        if not settings.enabled or window <= 0:
            return

        branch = await self._session.get_branch()
        usage = get_last_assistant_usage(branch)
        if usage is None:
            return
        if not should_compact(calculate_context_tokens(usage), window, settings):
            return

        preparation = prepare_compaction(branch, settings)
        if preparation is None:
            return
        try:
            summary, summary_usage = await generate_summary(
                preparation,
                stream_fn=self._stream_fn,
                model=self._model,
                signal=self._active_controller.signal if self._active_controller else None,
            )
        except Exception:  # noqa: BLE001 - a failed summary must not end the run
            return
        await self._session.append_compaction(
            summary,
            tokens_before=preparation.tokens_before,
            first_kept_entry_id=preparation.first_kept_entry_id,
            usage=summary_usage,
        )
        await self._emit_own(
            SavePointEvent(had_pending_mutations=True),
        )

    def _create_stream_fn(self, get_state: Callable[[], TurnState]) -> StreamFn:
        async def stream_fn(model: Model, context, options: StreamOptions):
            state = get_state()
            patched = options
            result: BeforeProviderRequestResult | None = await self._emit_hook(
                BeforeProviderRequestEvent(
                    model=model,
                    session_id=state.session_id,
                    stream_options=replace(options),
                )
            )
            if result is not None and result.stream_options is not None:
                patched = result.stream_options
            return await _maybe_await(self._stream_fn(model, context, patched))

        return stream_fn

    async def _handle_agent_event(self, event: AgentEvent, signal: AbortSignal) -> None:
        kind = event_type(event)
        if kind == "message_end":
            # The transcript is the session, so a completed message is written
            # before any subscriber sees it.
            assert isinstance(event, MessageEndEvent)
            await self._session.append_message(event.message)
            await self._emit_any(event)
            return
        if kind == "turn_end":
            assert isinstance(event, TurnEndEvent)
            hook_error: BaseException | None = None
            try:
                await self._emit_any(event)
            except BaseException as error:  # noqa: BLE001 - re-raised after the flush
                hook_error = error
            had_pending = bool(self._pending_writes)
            await self._flush_pending_writes()
            if hook_error is not None:
                raise hook_error
            await self._emit_own(SavePointEvent(had_pending_mutations=had_pending))
            return
        if kind == "agent_end":
            assert isinstance(event, AgentEndEvent)
            await self._flush_pending_writes()
            self._phase = "idle"
            await self._emit_any(event)
            await self._emit_own(SettledEvent(next_turn_count=len(self._next_turn_queue)))
            return
        await self._emit_any(event)

    async def _emit_run_failure(
        self,
        model: Model,
        error: BaseException,
        aborted: bool,
        signal: AbortSignal,
    ) -> list[AgentMessage]:
        """Report a crashed run as a normal failed turn, as pi does."""
        failure = _failure_message(model, error, aborted)
        await self._handle_agent_event(MessageStartEvent(message=failure), signal)
        await self._handle_agent_event(MessageEndEvent(message=failure), signal)
        await self._handle_agent_event(TurnEndEvent(message=failure, tool_results=[]), signal)
        await self._handle_agent_event(AgentEndEvent(messages=[failure]), signal)
        return [failure]

    # -- session writes --------------------------------------------------- #

    async def _write_or_defer(self, write: _PendingWrite) -> None:
        """Apply a session write now when idle, or defer it to the save point.

        Writing mid-turn would interleave with the loop's own message appends
        and corrupt the parent chain, so anything requested during a run waits
        for ``turn_end``.
        """
        if self._phase == "idle":
            await self._apply_write(write)
            return
        self._pending_writes.append(write)

    async def _flush_pending_writes(self) -> None:
        while self._pending_writes:
            await self._apply_write(self._pending_writes.pop(0))

    async def _apply_write(self, write: _PendingWrite) -> None:
        payload = write.payload
        if write.kind == "message":
            await self._session.append_message(payload["message"])
        elif write.kind == "model_change":
            await self._session.append_model_change(payload["provider"], payload["model_id"])
        elif write.kind == "thinking_level_change":
            await self._session.append_thinking_level_change(payload["level"])
        elif write.kind == "active_tools_change":
            await self._session.append_active_tools_change(payload["names"])
        elif write.kind == "custom":
            await self._session.append_custom_entry(payload["custom_type"], payload.get("data"))
        elif write.kind == "label":
            await self._session.append_label(payload["target_id"], payload.get("label"))
        elif write.kind == "session_info":
            await self._session.append_session_name(payload.get("name") or "")
        elif write.kind == "leaf":
            await self._session.move_to(payload.get("target_id"))

    # -- emit ------------------------------------------------------------- #

    async def _emit_any(self, event: AgentEvent | HarnessOwnEvent) -> None:
        for listener in list(self._handlers.get(_SUBSCRIBER_KEY, [])):
            try:
                await _maybe_await(listener(event))
            except BaseException as error:  # noqa: BLE001 - normalized for callers
                raise _normalize_error(to_error(error), "hook") from error

    async def _emit_own(self, event: HarnessOwnEvent) -> None:
        await self._emit_any(event)

    async def _emit_hook(self, event: Any) -> Any:
        handlers = self._handlers.get(event_type(event))
        if not handlers:
            return None
        last: Any = None
        for handler in list(handlers):
            try:
                result = await _maybe_await(handler(event))
            except BaseException as error:  # noqa: BLE001 - normalized for callers
                raise _normalize_error(to_error(error), "hook") from error
            if result is not None:
                last = result
        return last

    async def _emit_queue_update(self) -> None:
        await self._emit_own(self.queued_messages())

    # -- helpers ---------------------------------------------------------- #

    async def _drain(self, queue: list[AgentMessage], mode: QueueMode) -> list[AgentMessage]:
        if not queue:
            return []
        drained = list(queue) if mode == "all" else [queue[0]]
        del queue[: len(drained)]
        try:
            await self._emit_queue_update()
        except BaseException as error:  # noqa: BLE001 - restore before surfacing
            queue[:0] = drained
            raise _normalize_error(to_error(error), "hook") from error
        return drained

    def _start_operation(self) -> tuple[AbortSignal, Callable[[], None]]:
        controller = AbortController()
        self._active_controller = controller
        operation: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._operations.add(operation)

        def finish() -> None:
            self._active_controller = None
            self._operations.discard(operation)
            if not operation.done():
                operation.set_result(None)

        return controller.signal, finish

    def _assert_not_shut_down(self) -> None:
        if self._is_shutdown:
            raise AgentHarnessError("invalid_state", "AgentHarness has been shut down")

    @staticmethod
    def _validate_unique(names: Sequence[str], message: str) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for name in names:
            if name in seen:
                duplicates.add(name)
            seen.add(name)
        if duplicates:
            raise AgentHarnessError(
                "invalid_argument", f"{message}: {', '.join(sorted(duplicates))}"
            )

    def _validate_known(
        self,
        names: Sequence[str],
        registry: dict[str, AgentTool] | None = None,
    ) -> None:
        known = registry if registry is not None else self._tools
        missing = [name for name in names if name not in known]
        if missing:
            raise AgentHarnessError("invalid_argument", f"Unknown tool(s): {', '.join(missing)}")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "AgentHarness",
    "HarnessPhase",
    "HarnessResources",
    "SystemPromptSource",
    "TurnState",
]
