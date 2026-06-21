"""OpenAI Agents SDK runtime adapter.

Wraps ``agents.Agent`` + ``agents.Runner`` behind SuperQode's AgentRuntime
Protocol. SuperQode callers (TUI, headless, A2A server) drive the OpenAI
Agents SDK with the same constructor signature used by the builtin runtime.

Phase 3 scope:
    * SuperQode tools bridged via ``tool_bridge_openai.to_openai_function_tools``
    * ``needs_approval`` wired to PermissionManager (real HITL for ASK)
    * JSONL Session persistence via ``openai_session.SuperQodeSession``
    * Streaming via ``Runner.run_streamed`` / ``stream_events``
    * Cancellation via ``RunResultStreaming.cancel`` (no flag-poll hack)
    * LiteLLM wrapper for non-OpenAI providers (transparent via [litellm] extra)

Phase 3 gaps (documented; deferred to later phases):
    * MCP servers are bridged at the tool-definition layer only — each
      ``mcp_tools`` entry becomes a FunctionTool that delegates to
      ``mcp_executor``. Native ``MCPServerStdio`` instances on Agent come
      in a later phase along with SandboxAgent.
    * HITL approval flow: ``run()`` reports ``stopped_reason="needs_approval"``
      and stashes ``RunState`` on ``self._pending_state``; TUI plumbing
      to surface the approval dialog + ``resume()`` is Phase 6.
    * SandboxAgent + Manifest + ``RunConfig(sandbox=...)`` is Phase 7.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse, _cached_system_prompt
from ..harness.events import HarnessEvent
from ..providers.gateway.base import GatewayInterface, ToolDefinition
from ..providers.model_specs import normalize_model_for_provider, normalize_provider_id
from ..providers.profiles import resolve_model_profile, run_pre_init_once
from ..tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from ..tools.permissions import (
    Permission,
    PermissionConfig,
    PermissionManager,
)
from .errors import RuntimeNotInstalledError
from .tool_bridge_openai import to_openai_function_tools

logger = logging.getLogger(__name__)

# OpenAI Agents SDK requires a positive max_turns. When SuperQode's
# AgentConfig is set to unlimited (max_iterations <= 0),
# pass a very high cap so the SDK won't artificially terminate the run.
_OPENAI_AGENTS_UNLIMITED_TURNS = 10_000


def _resolve_max_turns(max_iterations: int) -> int:
    return _OPENAI_AGENTS_UNLIMITED_TURNS if max_iterations <= 0 else max_iterations


def _require_sdk():
    try:
        from agents import Agent, Runner  # noqa: F401
        from agents.run import RunConfig  # noqa: F401
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "OpenAI Agents runtime requires the 'openai-agents' extra. "
            "Install with: pip install superqode[openai-agents]"
        ) from exc


def _build_model(provider: str, model: str):
    """Return the SDK model spec for the given (provider, model).

    For OpenAI's own provider we pass the bare model id (the SDK handles it
    via the default OpenAI client). For anything else we wrap in
    ``LitellmModel`` so the same model name works across providers.
    """
    _require_sdk()
    provider = normalize_provider_id(provider)
    model = normalize_model_for_provider(provider, model)
    if (provider or "").strip().lower() in {"openai", "openai-compatible"}:
        return model
    try:
        from agents.extensions.models.litellm_model import LitellmModel
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "Non-OpenAI providers require the litellm sub-extra. "
            "Install with: pip install 'openai-agents[litellm]' "
            "(included automatically in superqode[openai-agents])"
        ) from exc
    return LitellmModel(model=f"{provider}/{model}")


def _build_context_factory(
    config: AgentConfig,
    tool_registry: ToolRegistry,
    permission_manager: PermissionManager,
    session_id: str,
) -> Callable[[], ToolContext]:
    """Return a ctx_factory that mints a fresh ToolContext per tool call."""
    working_directory = Path(config.working_directory)

    def make_ctx() -> ToolContext:
        return ToolContext(
            session_id=session_id,
            working_directory=working_directory,
            require_confirmation=config.require_confirmation,
            tool_registry=tool_registry,
            sub_agent_runner=None,
        )

    return make_ctx


def _bridge_mcp_tools_as_function_tools(
    mcp_tools: List[ToolDefinition],
    mcp_executor: Callable[..., Awaitable[ToolResult]],
    permission_manager: PermissionManager,
) -> List[Any]:
    """Wrap each MCP ToolDefinition as a FunctionTool delegating to mcp_executor.

    SuperQode names MCP tools ``mcp_{server_id}_{tool_name}``; we parse the
    server_id off the prefix when invoking. This is a v1 bridge — native
    ``MCPServerStdio`` integration on Agent is a follow-up.
    """
    if not mcp_tools or mcp_executor is None:
        return []

    _require_sdk()
    from agents.tool import FunctionTool

    out: List[Any] = []
    for tool_def in mcp_tools:
        name = tool_def.name
        # Strip the "mcp_" prefix and split "{server_id}_{tool_name}".
        rest = name[len("mcp_") :] if name.startswith("mcp_") else name
        if "_" in rest:
            server_id, real_tool_name = rest.split("_", 1)
        else:
            server_id, real_tool_name = "", rest

        out.append(
            _make_mcp_function_tool(
                FunctionTool=FunctionTool,
                tool_name=name,
                description=tool_def.description,
                params_schema=tool_def.parameters or {"type": "object", "properties": {}},
                server_id=server_id,
                real_tool_name=real_tool_name,
                mcp_executor=mcp_executor,
                permission_manager=permission_manager,
            )
        )
    return out


def _make_mcp_function_tool(
    *,
    FunctionTool: Any,
    tool_name: str,
    description: str,
    params_schema: Dict[str, Any],
    server_id: str,
    real_tool_name: str,
    mcp_executor: Callable[..., Awaitable[ToolResult]],
    permission_manager: PermissionManager,
) -> Any:
    """Build one MCP FunctionTool wrapper bound to a specific server+tool."""

    async def _needs_approval(_ctx: Any, params: Dict[str, Any], _call_id: str) -> bool:
        return permission_manager.check_permission(tool_name, params) == Permission.ASK

    async def _on_invoke(_ctx: Any, args_json: str) -> str:
        try:
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            return "ERROR: invalid JSON arguments"
        perm = permission_manager.check_permission(tool_name, args)
        if perm == Permission.DENY:
            return f"ERROR: Permission denied for tool: {tool_name}"
        try:
            result: ToolResult = await mcp_executor(server_id, real_tool_name, args)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {type(exc).__name__}: {exc}"
        if not result.success:
            return f"ERROR: {result.error or 'mcp tool error'}"
        output = result.output
        if isinstance(output, (dict, list)):
            return json.dumps(output, default=str)
        return "" if output is None else str(output)

    from .tool_bridge_openai import construct_function_tool

    return construct_function_tool(
        FunctionTool,
        name=tool_name,
        description=description,
        params_json_schema=params_schema,
        on_invoke_tool=_on_invoke,
        needs_approval=_needs_approval,
        strict_json_schema=False,
    )


class OpenAIAgentsRuntime:
    """OpenAI Agents SDK-backed implementation of AgentRuntime."""

    name = "openai-agents"

    def __init__(
        self,
        gateway: Optional[GatewayInterface] = None,
        tools: Optional[ToolRegistry] = None,
        config: Optional[AgentConfig] = None,
        on_tool_call: Optional[Callable[[str, Dict], None]] = None,
        on_tool_result: Optional[Callable[[str, ToolResult], None]] = None,
        on_thinking: Optional[Callable[[str], Awaitable[None]]] = None,
        parallel_tools: bool = True,
        mcp_executor: Optional[Callable[..., Awaitable[ToolResult]]] = None,
        mcp_tools: Optional[List[ToolDefinition]] = None,
        include_mcp: bool = False,
        permission_manager: Optional[PermissionManager] = None,
        sandbox_backend: Optional[str] = None,
        **_unused: Any,
    ):
        _require_sdk()
        if config is None or tools is None:
            raise ValueError("OpenAIAgentsRuntime requires both 'config' and 'tools'")

        from agents import Agent, Runner  # noqa: F401
        from agents.run import RunConfig

        # gateway is unused by the OpenAI Agents SDK (it has its own model layer).
        if gateway is not None:
            logger.debug("OpenAIAgentsRuntime: 'gateway' is unused (SDK manages its own models)")

        self.config = config
        self.tools = tools
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.on_thinking = on_thinking
        self.parallel_tools = parallel_tools

        if permission_manager is not None:
            self.permission_manager = permission_manager
        elif config.require_confirmation:
            self.permission_manager = PermissionManager()
        else:
            self.permission_manager = PermissionManager(PermissionConfig(default=Permission.ALLOW))

        run_pre_init_once(config.provider, config.model)

        self.session_id = config.session_id or f"oai-{uuid.uuid4().hex[:8]}"

        # System prompt — reuse the builtin cache so behavior matches.
        instructions = _cached_system_prompt(
            level=config.system_prompt_level,
            working_directory=str(config.working_directory),
            custom_prompt=config.custom_system_prompt,
            job_description=config.job_description,
            provider=config.provider,
            model=config.model,
        )

        profile = resolve_model_profile(config.provider, config.model)

        ctx_factory = _build_context_factory(
            config=config,
            tool_registry=tools,
            permission_manager=self.permission_manager,
            session_id=self.session_id,
        )

        # Bridge SuperQode tools as FunctionTools.
        bridged_tools = to_openai_function_tools(
            tools,
            ctx_factory=ctx_factory,
            permission_manager=self.permission_manager,
            excluded=profile.excluded_tools,
        )
        # Bridge MCP tool definitions (if any) as additional FunctionTools.
        bridged_tools.extend(
            _bridge_mcp_tools_as_function_tools(
                mcp_tools or [],
                mcp_executor,
                self.permission_manager,
            )
        )

        # Optional JSONL session — only if the caller asked for persistence.
        self._session = None
        if config.enable_session_storage:
            from .openai_session import make_session_class

            SuperQodeSession = make_session_class()
            self._session = SuperQodeSession(
                session_id=self.session_id,
                storage_dir=config.session_storage_dir,
            )

        # Sandbox: when the caller asks for a backend, upgrade the Agent to a
        # SandboxAgent and wire RunConfig.sandbox. Backends we don't recognize
        # pass through to the regular Agent path (and log a debug note).
        self.sandbox_backend = (sandbox_backend or "").strip().lower() or None
        self._sandbox_client = None
        if self.sandbox_backend:
            from superqode.harness.sandbox import (
                build_manifest,
                build_sandbox_agent,
                build_sandbox_client,
                build_sandbox_run_config,
                supported_sandbox_backends,
            )

            if self.sandbox_backend in supported_sandbox_backends():
                self._sandbox_client = build_sandbox_client(self.sandbox_backend)
                manifest = build_manifest(config)
                self._agent = build_sandbox_agent(
                    name="superqode",
                    instructions=instructions,
                    tools=bridged_tools,
                    model=_build_model(config.provider, config.model),
                    manifest=manifest,
                )
                self._run_config = build_sandbox_run_config(
                    client=self._sandbox_client,
                    base_run_config=RunConfig(tracing_disabled=True),
                )
            else:
                logger.warning(
                    "OpenAIAgentsRuntime: sandbox_backend '%s' not recognized by the OpenAI "
                    "Agents bridge; falling back to non-sandbox Agent.",
                    self.sandbox_backend,
                )
                self.sandbox_backend = None

        if self._sandbox_client is None:
            # Build the Agent. Default tool_use_behavior is "run_llm_again",
            # matching the AgentLoop iteration model.
            self._agent = Agent(
                name="superqode",
                instructions=instructions,
                tools=bridged_tools,
                model=_build_model(config.provider, config.model),
            )
            # RunConfig: keep tracing disabled by default for privacy.
            self._run_config = RunConfig(tracing_disabled=True)

        # Cancellation: keep a flag *and* a handle to any active streaming
        # result so cancel() can call result.cancel() directly.
        self._cancelled = False
        self._active_stream = None

        # Phase 6 plumbing — when run() returns needs_approval, we stash the
        # RunResult here so the TUI can drive an approve/reject loop.
        self.pending_state: Any = None

    # ------------------------------------------------------------------
    # AgentRuntime Protocol
    # ------------------------------------------------------------------

    async def run(self, prompt: str) -> AgentResponse:
        from agents import Runner

        try:
            result = await Runner.run(
                self._agent,
                prompt,
                session=self._session,
                run_config=self._run_config,
                max_turns=_resolve_max_turns(self.config.max_iterations),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as AgentResponse error
            logger.exception("OpenAI Agents Runner.run failed")
            return AgentResponse(
                content="",
                messages=[AgentMessage(role="user", content=prompt)],
                tool_calls_made=0,
                iterations=0,
                stopped_reason="error",
                error=f"{type(exc).__name__}: {exc}",
            )

        return self._translate_result(prompt, result)

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        from agents import Runner
        from agents.stream_events import RawResponsesStreamEvent

        result = Runner.run_streamed(
            self._agent,
            prompt,
            session=self._session,
            run_config=self._run_config,
            max_turns=_resolve_max_turns(self.config.max_iterations),
        )
        self._active_stream = result
        try:
            async for event in result.stream_events():
                if self._cancelled:
                    break
                if isinstance(event, RawResponsesStreamEvent):
                    text = _extract_text_delta(event)
                    if text:
                        yield text
        finally:
            self._active_stream = None

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        """Stream OpenAI Agents SDK events as normalized SuperQode harness events."""
        from agents import Runner

        self.reset_cancellation()
        yield HarnessEvent(type="model_request", data={"runtime": self.name})
        if self.sandbox_backend:
            yield HarnessEvent(
                type="sandbox_start",
                data={"backend": self.sandbox_backend, "runtime": self.name},
            )

        result = Runner.run_streamed(
            self._agent,
            prompt,
            session=self._session,
            run_config=self._run_config,
            max_turns=_resolve_max_turns(self.config.max_iterations),
        )
        self._active_stream = result
        try:
            async for event in result.stream_events():
                if self._cancelled:
                    break
                for normalized in _events_from_openai_agents_event(event):
                    yield normalized
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("OpenAI Agents Runner.run_streamed failed")
            yield HarnessEvent(
                type="runtime_error",
                data={"error": str(exc), "error_type": type(exc).__name__},
            )
            return
        finally:
            self._active_stream = None

        response = self._translate_result(prompt, result)
        if response.stopped_reason == "needs_approval":
            yield HarnessEvent(
                type="approval_required",
                data={
                    "backend": self.name,
                    "runtime": self.name,
                    "pending_approvals": self.get_pending_approvals(),
                    "pending_runtime": self,
                },
            )
        else:
            yield HarnessEvent(
                type="model_result",
                data={
                    "output": response.content,
                    "tool_calls_made": response.tool_calls_made,
                    "iterations": response.iterations,
                    "stopped_reason": response.stopped_reason,
                },
            )

    def cancel(self) -> None:
        self._cancelled = True
        active = self._active_stream
        if active is not None:
            try:
                active.cancel()
            except Exception:  # noqa: BLE001 — best effort
                logger.debug("active_stream.cancel() raised", exc_info=True)

    def reset_cancellation(self) -> None:
        self._cancelled = False

    async def resume(self, state: Any) -> AgentResponse:
        """Resume a HITL-interrupted run after caller calls state.approve/reject.

        Phase 6 plumbs this into the TUI permission dialog. For now any caller
        that has a ``RunState`` (typically derived from ``self.pending_state``)
        can call this directly to continue the run.
        """
        from agents import Runner

        result = await Runner.run(
            self._agent,
            state,
            session=self._session,
            run_config=self._run_config,
            max_turns=_resolve_max_turns(self.config.max_iterations),
        )
        return self._translate_result(prompt="", result=result)

    # ------------------------------------------------------------------
    # Phase 6 — HITL approval surface
    # ------------------------------------------------------------------

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """Return a serialized snapshot of pending approval items.

        Each entry has ``{index, tool_name, arguments}`` so callers (TUI dialogs
        or :approve / :reject slash commands) can display the tool calls and
        pick one by index. Returns an empty list when no run is awaiting
        approval.
        """
        result = self.pending_state
        if result is None:
            return []
        interruptions = list(getattr(result, "interruptions", []) or [])
        out: List[Dict[str, Any]] = []
        for idx, item in enumerate(interruptions):
            tool_name = getattr(item, "tool_name", None) or _tool_name_from_item(item)
            args = _tool_args_from_item(item)
            out.append({"index": idx, "tool_name": tool_name, "arguments": args})
        return out

    async def approve_and_resume(self, index: int = 0, always: bool = False) -> AgentResponse:
        """Approve the pending approval at ``index`` and resume the run.

        Raises ``RuntimeError`` when there's nothing pending or the index is
        out of range. ``always=True`` records a permanent approval for the
        tool (the SDK persists this across resume cycles).
        """
        state, item = self._take_pending(index)
        state.approve(item, always_approve=always)
        return await self._consume_state(state)

    async def reject_and_resume(
        self,
        index: int = 0,
        message: Optional[str] = None,
        always: bool = False,
    ) -> AgentResponse:
        """Reject the pending approval at ``index`` and resume the run.

        ``message`` is sent verbatim to the model as the rejection reason;
        when omitted the SDK's default rejection text is used.
        """
        state, item = self._take_pending(index)
        if message is not None:
            state.reject(item, always_reject=always, rejection_message=message)
        else:
            state.reject(item, always_reject=always)
        return await self._consume_state(state)

    def clear_pending(self) -> None:
        """Drop any pending interruption without approving or rejecting."""
        self.pending_state = None

    def _take_pending(self, index: int) -> tuple[Any, Any]:
        result = self.pending_state
        if result is None:
            raise RuntimeError("No pending approval to act on")
        interruptions = list(getattr(result, "interruptions", []) or [])
        if not interruptions:
            raise RuntimeError("No pending approval to act on")
        if index < 0 or index >= len(interruptions):
            raise RuntimeError(f"Approval index {index} out of range (have {len(interruptions)})")
        state = result.to_state()
        return state, interruptions[index]

    async def _consume_state(self, state: Any) -> AgentResponse:
        # Clear pending before resuming so a cascading interrupt sets it fresh.
        self.pending_state = None
        return await self.resume(state)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _translate_result(self, prompt: str, result: Any) -> AgentResponse:
        messages: List[AgentMessage] = []
        if prompt:
            messages.append(AgentMessage(role="user", content=prompt))

        tool_calls_made = 0
        for item in getattr(result, "new_items", []) or []:
            type_name = getattr(item, "type", "")
            if type_name == "message_output_item":
                content = _text_from_message_item(item)
                if content:
                    messages.append(AgentMessage(role="assistant", content=content))
            elif type_name in {"tool_call_item", "handoff_call_item"}:
                tool_calls_made += 1
                if self.on_tool_call is not None:
                    try:
                        name = _tool_name_from_item(item)
                        args = _tool_args_from_item(item)
                        self.on_tool_call(name, args)
                    except Exception:  # noqa: BLE001
                        logger.debug("on_tool_call callback raised", exc_info=True)

        interruptions = list(getattr(result, "interruptions", []) or [])
        if interruptions:
            stopped = "needs_approval"
            self.pending_state = result
        elif self._cancelled:
            stopped = "cancelled"
        else:
            stopped = "complete"
            self.pending_state = None

        content = ""
        final = getattr(result, "final_output", None)
        if final is not None:
            content = final if isinstance(final, str) else str(final)
        if not content and messages and messages[-1].role == "assistant":
            content = messages[-1].content

        iterations = len(getattr(result, "raw_responses", []) or [])

        return AgentResponse(
            content=content,
            messages=messages,
            tool_calls_made=tool_calls_made,
            iterations=iterations,
            stopped_reason=stopped,
        )


def _extract_text_delta(event: Any) -> str:
    """Pull a text delta off a RawResponsesStreamEvent if present."""
    data = getattr(event, "data", None)
    if data is None:
        return ""
    # Responses API streaming: ResponseTextDeltaEvent has a `.delta` string.
    delta = getattr(data, "delta", None)
    if isinstance(delta, str):
        return delta
    # Some delta events nest text under `.delta.text`.
    if delta is not None:
        text = getattr(delta, "text", None)
        if isinstance(text, str):
            return text
    return ""


def _events_from_openai_agents_event(event: Any) -> list[HarnessEvent]:
    event_name = event.__class__.__name__
    events: list[HarnessEvent] = []

    text = _extract_text_delta(event)
    if text:
        events.append(
            HarnessEvent(
                type="model_delta",
                data={"text": text, "source_event": event_name},
            )
        )

    item = getattr(event, "item", None) or getattr(event, "data", None)
    tool_call = _tool_call_event_data(item)
    if tool_call is not None:
        events.append(
            HarnessEvent(
                type="tool_call",
                data={**tool_call, "source_event": event_name},
            )
        )

    tool_result = _tool_result_event_data(item)
    if tool_result is not None:
        events.append(
            HarnessEvent(
                type="tool_result",
                data={**tool_result, "source_event": event_name},
            )
        )

    mcp_event = _mcp_event_data(item)
    if mcp_event is not None:
        events.append(
            HarnessEvent(
                type="mcp_list_tools",
                data={**mcp_event, "source_event": event_name},
            )
        )

    if _is_sandbox_item(item):
        events.append(
            HarnessEvent(
                type=_sandbox_event_type(item),
                data={"source_event": event_name, "item_type": getattr(item, "type", "")},
            )
        )

    if not events and _should_keep_runtime_event(event):
        events.append(
            HarnessEvent(
                type="runtime_event",
                data={"source_event": event_name},
            )
        )
    return events


def _tool_call_event_data(item: Any) -> dict[str, Any] | None:
    if item is None:
        return None
    item_type = getattr(item, "type", "")
    if item_type == "tool_search_call_item":
        raw = _raw_item_payload(item)
        return {
            "tool_name": "tool_search",
            "tool_call_id": _raw_get(raw, "id") or _raw_get(raw, "call_id"),
            "arguments": raw,
        }
    if item_type not in {"tool_call_item", "handoff_call_item"}:
        return None
    return {
        "tool_name": _tool_name_from_item(item),
        "arguments": _tool_args_from_item(item),
    }


def _tool_result_event_data(item: Any) -> dict[str, Any] | None:
    if item is None:
        return None
    item_type = getattr(item, "type", "")
    if item_type == "tool_search_output_item":
        raw = _raw_item_payload(item)
        return {
            "tool_name": "tool_search",
            "tool_call_id": _raw_get(raw, "id") or _raw_get(raw, "call_id"),
            "content": _raw_get(raw, "output") or _raw_get(raw, "results") or raw,
        }
    if item_type not in {"tool_call_output_item", "handoff_output_item"}:
        return None
    raw = getattr(item, "raw_item", None)
    output = getattr(raw, "output", None) if raw is not None else getattr(item, "output", None)
    return {
        "tool_name": _tool_name_from_item(item),
        "content": output,
    }


def _mcp_event_data(item: Any) -> dict[str, Any] | None:
    if item is None or getattr(item, "type", "") != "mcp_list_tools_item":
        return None
    raw = _raw_item_payload(item)
    tools = _raw_get(raw, "tools") or []
    normalized_tools: list[dict[str, Any]] = []
    if isinstance(tools, list):
        for tool in tools:
            name = _raw_get(tool, "name")
            if not name:
                continue
            normalized_tools.append(
                {
                    "name": name,
                    **({"title": title} if (title := _raw_get(tool, "title")) else {}),
                    **(
                        {"description": description}
                        if (description := _raw_get(tool, "description"))
                        else {}
                    ),
                }
            )
    return {
        "server_label": _raw_get(raw, "server_label"),
        "tool_count": len(normalized_tools),
        "tools": normalized_tools,
    }


def _raw_item_payload(item: Any) -> dict[str, Any]:
    raw = getattr(item, "raw_item", item)
    if isinstance(raw, Mapping):
        return dict(raw)
    model_dump = getattr(raw, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(exclude_unset=True)
        except TypeError:
            dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dict(dumped)
    data: dict[str, Any] = {}
    for name in ("id", "call_id", "type", "server_label", "tools", "query", "output", "results"):
        value = getattr(raw, name, None)
        if value is not None:
            data[name] = value
    return data


def _raw_get(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _is_sandbox_item(item: Any) -> bool:
    item_type = str(getattr(item, "type", "")).lower()
    return "sandbox" in item_type or item_type in {
        "file_search_call",
        "computer_call",
        "code_interpreter_call",
    }


def _sandbox_event_type(item: Any) -> str:
    item_type = str(getattr(item, "type", "")).lower()
    if "command" in item_type or "code_interpreter" in item_type:
        return "sandbox_command"
    if "file" in item_type:
        return "sandbox_file"
    if "snapshot" in item_type:
        return "sandbox_snapshot"
    return "sandbox_event"


def _should_keep_runtime_event(event: Any) -> bool:
    name = event.__class__.__name__.lower()
    return any(token in name for token in ("handoff", "tool", "sandbox", "approval", "mcp"))


def _text_from_message_item(item: Any) -> str:
    raw = getattr(item, "raw_item", None)
    if raw is None:
        return ""
    content = getattr(raw, "content", None)
    if not content:
        return ""
    parts: List[str] = []
    for part in content:
        text = getattr(part, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _tool_name_from_item(item: Any) -> str:
    raw = getattr(item, "raw_item", None)
    if raw is None:
        return ""
    name = getattr(raw, "name", None)
    if isinstance(name, str):
        return name
    if isinstance(raw, dict):
        return str(raw.get("name", ""))
    return ""


def _tool_args_from_item(item: Any) -> Dict[str, Any]:
    raw = getattr(item, "raw_item", None)
    if raw is None:
        return {}
    args = getattr(raw, "arguments", None)
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {}
    if isinstance(args, dict):
        return args
    if isinstance(raw, dict):
        return dict(raw.get("arguments", {}) or {})
    return {}
