"""Google ADK runtime adapter.

Wraps ``google.adk.runners.Runner`` + ``google.adk.agents.LlmAgent`` behind the
AgentRuntime Protocol so SuperQode callers (TUI, headless, A2A server) can drive
ADK with the same constructor signature used by the builtin runtime.

ADK is a heavy optional dep — importing this module raises
RuntimeNotInstalledError when google-adk isn't available.

Phase 2 scope:
    * Tools bridged from the SuperQode ToolRegistry via tool_bridge.to_adk_tools
    * System prompt built with the same _cached_system_prompt as the builtin loop
    * LiteLlm wrapper for non-Gemini providers (matches superqode's provider list)
    * InMemorySessionService (SQLite/Vertex backends are a v2 task)
    * Streaming yields text deltas; tool execution is opaque (matches builtin)
    * Cancellation via a flag checked between events

Known gaps (deferred to v2 — listed in docs/runtimes.md):
    * MCP tools: ``mcp_tools`` / ``mcp_executor`` constructor args are accepted
      but ignored. ADK has native MCPToolset support; bridging it is a follow-up.
    * HITL: ADK's tool_confirmation pattern isn't wired through yet.
    * Resumability, persistent sessions, OTel exporters: not configured.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse, _cached_system_prompt
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
from .tool_bridge import to_adk_tools

logger = logging.getLogger(__name__)


def _require_adk():
    try:
        from google.adk.agents.llm_agent import LlmAgent  # noqa: F401
        from google.adk.runners import Runner  # noqa: F401
        from google.adk.sessions.in_memory_session_service import (  # noqa: F401
            InMemorySessionService,
        )
        from google.genai import types  # noqa: F401
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "ADK runtime requires the 'adk' extra. Install with: pip install superqode[adk]"
        ) from exc


def _build_model(provider: str, model: str):
    """Return an ADK model spec for the given (provider, model).

    For Gemini we pass the bare model id; for everything else we wrap in
    google.adk.models.lite_llm.LiteLlm so ADK routes via LiteLLM.
    """
    _require_adk()
    provider = normalize_provider_id(provider)
    model = normalize_model_for_provider(provider, model)
    if provider.lower() in {"gemini", "google", "google-gemini"}:
        return model
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(model=f"{provider}/{model}")


def _build_context_factory(
    config: AgentConfig,
    tool_registry: ToolRegistry,
    permission_manager: PermissionManager,
    session_id: str,
) -> Callable[[], ToolContext]:
    """Return a ctx_factory that mints a fresh ToolContext for each tool call."""

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


class ADKRuntime:
    """Google ADK-backed implementation of AgentRuntime."""

    name = "adk"

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
        **_unused: Any,
    ):
        _require_adk()
        if config is None or tools is None:
            raise ValueError("ADKRuntime requires both 'config' and 'tools'")

        from google.adk.agents.llm_agent import LlmAgent
        from google.adk.runners import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService

        # gateway is unused by ADK (it has its own model layer). Keep the param
        # in the signature for constructor parity with BuiltinRuntime.
        if gateway is not None:
            logger.debug("ADKRuntime: 'gateway' argument is unused (ADK manages its own models)")

        # MCP is a known gap in v1 — accept the args but log if the caller relied on them.
        if mcp_executor is not None or mcp_tools or include_mcp:
            logger.warning(
                "ADKRuntime: MCP tools are not bridged in v1. "
                "MCP-only tool calls will not be available in this session."
            )

        self.config = config
        self.tools = tools
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.on_thinking = on_thinking
        self.parallel_tools = parallel_tools

        # Permissions
        if permission_manager is not None:
            self.permission_manager = permission_manager
        elif config.require_confirmation:
            self.permission_manager = PermissionManager()
        else:
            self.permission_manager = PermissionManager(PermissionConfig(default=Permission.ALLOW))

        # Run provider/model pre-init once (e.g. OpenRouter attribution setup).
        run_pre_init_once(config.provider, config.model)

        self.session_id = config.session_id or f"adk-{uuid.uuid4().hex[:8]}"
        self._user_id = "superqode"
        self._app_name = "superqode"

        # System prompt — reuse the builtin cache so behavior matches.
        instructions = _cached_system_prompt(
            level=config.system_prompt_level,
            working_directory=str(config.working_directory),
            custom_prompt=config.custom_system_prompt,
            job_description=config.job_description,
            provider=config.provider,
            model=config.model,
        )

        # Excluded tools (model profile may drop tools incompatible with a model).
        profile = resolve_model_profile(config.provider, config.model)

        ctx_factory = _build_context_factory(
            config=config,
            tool_registry=tools,
            permission_manager=self.permission_manager,
            session_id=self.session_id,
        )
        self._ctx_factory = ctx_factory

        # Build the LlmAgent with bridged tools.
        bridged = to_adk_tools(
            tools,
            ctx_factory=ctx_factory,
            permission_manager=self.permission_manager,
            excluded=profile.excluded_tools,
        )
        self._agent = LlmAgent(
            name="superqode",
            description="SuperQode coding harness (ADK backend)",
            model=_build_model(config.provider, config.model),
            instruction=instructions,
            tools=bridged,
        )

        self._session_service = InMemorySessionService()
        runner_kwargs = {
            "app_name": self._app_name,
            "agent": self._agent,
            "session_service": self._session_service,
        }
        try:
            runner_params = inspect.signature(Runner).parameters
        except (TypeError, ValueError):
            runner_params = {}
        if "auto_create_session" in runner_params:
            runner_kwargs["auto_create_session"] = True
        self._runner = Runner(**runner_kwargs)
        self._cancelled = False

    # ------------------------------------------------------------------
    # AgentRuntime Protocol
    # ------------------------------------------------------------------

    async def run(self, prompt: str) -> AgentResponse:
        chunks: List[str] = []
        tool_calls_made = 0
        iterations = 0
        error: Optional[str] = None
        messages: List[AgentMessage] = [AgentMessage(role="user", content=prompt)]

        try:
            async for event in self._iter_events(prompt):
                iterations += 1
                # Count function-call events as tool invocations.
                fcalls = event.get_function_calls()
                if fcalls:
                    tool_calls_made += len(fcalls)
                    for fc in fcalls:
                        if self.on_tool_call:
                            try:
                                self.on_tool_call(fc.name, dict(fc.args or {}))
                            except Exception:  # noqa: BLE001 — callback is best-effort
                                logger.debug("on_tool_call callback raised", exc_info=True)
                # Collect text content from final (non-partial) assistant turns.
                if (
                    event.content
                    and event.content.parts
                    and not event.partial
                    and event.is_final_response()
                ):
                    for part in event.content.parts:
                        if getattr(part, "text", None):
                            chunks.append(part.text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as AgentResponse error
            error = f"{type(exc).__name__}: {exc}"

        content = "".join(chunks)
        if error:
            stopped = "error"
        elif self._cancelled:
            stopped = "cancelled"
        else:
            stopped = "complete"
        messages.append(AgentMessage(role="assistant", content=content))
        return AgentResponse(
            content=content,
            messages=messages,
            tool_calls_made=tool_calls_made,
            iterations=iterations,
            stopped_reason=stopped,
            error=error,
        )

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        try:
            async for event in self._iter_events(prompt):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        text = getattr(part, "text", None)
                        if text:
                            yield text
        except asyncio.CancelledError:
            raise

    def cancel(self) -> None:
        self._cancelled = True

    def reset_cancellation(self) -> None:
        self._cancelled = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _iter_events(self, prompt: str):
        """Yield ADK events for one user message, honoring cancellation."""
        from google.genai import types

        new_message = types.Content(role="user", parts=[types.Part(text=prompt)])
        async for event in self._runner.run_async(
            user_id=self._user_id,
            session_id=self.session_id,
            new_message=new_message,
        ):
            if self._cancelled:
                break
            yield event
