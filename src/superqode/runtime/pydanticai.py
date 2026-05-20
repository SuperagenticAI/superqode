"""PydanticAI runtime adapter."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from ..agent.loop import AgentConfig, AgentResponse, _cached_system_prompt
from ..harness.events import HarnessEvent
from ..harness.spec import HarnessSpec
from ..providers.gateway.base import GatewayInterface, ToolDefinition
from ..providers.profiles import resolve_model_profile, run_pre_init_once
from ..tools.base import ToolContext, ToolRegistry, ToolResult
from ..tools.permissions import Permission, PermissionConfig, PermissionManager
from .errors import RuntimeNotInstalledError
from .tool_bridge_pydanticai import to_pydanticai_toolsets

logger = logging.getLogger(__name__)
_LOGFIRE_CONFIGURED = False


def _require_pydanticai():
    try:
        from pydantic_ai import Agent  # noqa: F401
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "PydanticAI runtime requires the 'pydanticai' extra. "
            "Install with: pip install superqode[pydanticai]"
        ) from exc


def _model_name(provider: str, model: str) -> str:
    if ":" in model:
        return model
    provider = provider.strip().lower()
    if provider in {
        "openai",
        "anthropic",
        "google",
        "gemini",
        "groq",
        "mistral",
        "cohere",
        "bedrock",
        "ollama",
    }:
        normalized = "google" if provider == "gemini" else provider
        return f"{normalized}:{model}"
    return model


def _build_context_factory(
    config: AgentConfig,
    tool_registry: ToolRegistry,
    session_id: str,
) -> Callable[[], ToolContext]:
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


def _result_text(result: Any) -> str:
    for attr in ("output", "data"):
        value = getattr(result, attr, None)
        if value is not None:
            return str(value)
    return str(result)


def _pydanticai_model(provider: str, model: str, fallbacks: tuple[str, ...]):
    model_name = _model_name(provider, model)
    if not fallbacks:
        return model_name
    from pydantic_ai.models.fallback import FallbackModel

    return FallbackModel(model_name, *fallbacks)


def _configure_logfire_if_requested(spec: HarnessSpec | None) -> None:
    global _LOGFIRE_CONFIGURED
    if spec is None:
        return
    config = spec.runtime.config.get("pydanticai", {})
    if not isinstance(config, dict):
        config = {}
    logfire_config = config.get("logfire", {})
    if logfire_config is True:
        logfire_config = {}
    if not spec.observability.traces and not logfire_config:
        return
    if _LOGFIRE_CONFIGURED:
        return
    try:
        import logfire
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "PydanticAI Logfire tracing requires logfire. Install with: pip install logfire"
        ) from exc
    configure_kwargs = {}
    if isinstance(logfire_config, dict):
        for key in ("send_to_logfire", "service_name", "environment"):
            if key in logfire_config:
                configure_kwargs[key] = logfire_config[key]
    logfire.configure(**configure_kwargs)
    logfire.instrument_pydantic_ai()
    _LOGFIRE_CONFIGURED = True


def _native_mcp_toolsets(spec: HarnessSpec | None) -> list[Any]:
    if spec is None:
        return []
    config = spec.runtime.config.get("pydanticai", {})
    if not isinstance(config, dict):
        config = {}
    config_path = config.get("mcp_config_path") or config.get("mcp_config")
    if not config_path:
        return []
    try:
        from pydantic_ai.mcp import load_mcp_toolsets
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "PydanticAI native MCP requires pydantic_ai.mcp. "
            "Install with: pip install superqode[pydanticai]"
        ) from exc
    return list(load_mcp_toolsets(config_path))


def _pydanticai_config(spec: HarnessSpec | None) -> dict[str, Any]:
    if spec is None:
        return {}
    config = spec.runtime.config.get("pydanticai", {})
    return config if isinstance(config, dict) else {}


def _apply_durable_wrapper(agent: Any, spec: HarnessSpec | None) -> Any:
    config = _pydanticai_config(spec)
    durable = config.get("durable") or config.get("durable_execution")
    if not durable:
        return agent
    durable_name = str(durable).strip().lower()
    if durable_name == "prefect":
        try:
            from pydantic_ai.durable_exec.prefect import PrefectAgent
        except ImportError as exc:
            raise RuntimeNotInstalledError(
                "PydanticAI Prefect durable execution requires pydantic-ai[prefect]."
            ) from exc
        return PrefectAgent(agent)
    if durable_name == "dbos":
        try:
            from pydantic_ai.durable_exec.dbos import DBOSAgent
        except ImportError as exc:
            raise RuntimeNotInstalledError(
                "PydanticAI DBOS durable execution requires pydantic-ai[dbos]."
            ) from exc
        return DBOSAgent(agent)
    if durable_name == "temporal":
        raise RuntimeNotInstalledError(
            "PydanticAI Temporal durable execution requires a Temporal workflow and worker. "
            "Use runtime.config.pydanticai.durable='prefect' or 'dbos' for in-process wrappers."
        )
    raise ValueError(
        "Unsupported PydanticAI durable execution backend "
        f"{durable_name!r}. Expected 'prefect', 'dbos', or 'temporal'."
    )


def _is_deferred_tool_requests(value: Any) -> bool:
    return value.__class__.__name__ == "DeferredToolRequests" and hasattr(value, "approvals")


class PydanticAIRuntime:
    """PydanticAI-backed implementation of AgentRuntime."""

    name = "pydanticai"

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
        harness_spec: HarnessSpec | None = None,
        **_unused: Any,
    ) -> None:
        _require_pydanticai()
        if config is None or tools is None:
            raise ValueError("PydanticAIRuntime requires both 'config' and 'tools'")

        from pydantic_ai import Agent, DeferredToolRequests

        if gateway is not None:
            logger.debug("PydanticAIRuntime: 'gateway' is unused (PydanticAI manages models)")
        if mcp_executor is not None or mcp_tools or include_mcp:
            logger.warning(
                "PydanticAIRuntime: SuperQode MCP bridge is not wired yet. "
                "Use PydanticAI native MCP through a harness spec follow-up."
            )

        self.config = config
        self.tools = tools
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.on_thinking = on_thinking
        self.parallel_tools = parallel_tools
        self._cancelled = False
        self._pending_requests: Any | None = None
        self._pending_messages: list[Any] = []
        self._last_prompt: str | None = None

        if permission_manager is not None:
            self.permission_manager = permission_manager
        elif config.require_confirmation:
            self.permission_manager = PermissionManager()
        else:
            self.permission_manager = PermissionManager(PermissionConfig(default=Permission.ALLOW))

        run_pre_init_once(config.provider, config.model)
        _configure_logfire_if_requested(harness_spec)
        self.session_id = config.session_id or f"pai-{uuid.uuid4().hex[:8]}"

        instructions = _cached_system_prompt(
            level=config.system_prompt_level,
            working_directory=str(config.working_directory),
            custom_prompt=config.custom_system_prompt,
            job_description=config.job_description,
            provider=config.provider,
            model=config.model,
        )
        profile = resolve_model_profile(config.provider, config.model)
        ctx_factory = _build_context_factory(config, tools, self.session_id)
        toolsets = (
            to_pydanticai_toolsets(
                tools,
                ctx_factory=ctx_factory,
                permission_manager=self.permission_manager,
                excluded=profile.excluded_tools,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
            )
            if config.tools_enabled
            else []
        )
        toolsets.extend(_native_mcp_toolsets(harness_spec))

        model_settings: dict[str, Any] = {}
        if config.temperature is not None:
            model_settings["temperature"] = config.temperature
        if config.reasoning_effort:
            model_settings["thinking"] = config.reasoning_effort

        base_agent = Agent(
            _pydanticai_model(
                config.provider,
                config.model,
                tuple(
                    _model_name(config.provider, fallback) if ":" not in fallback else fallback
                    for fallback in (harness_spec.model_policy.fallbacks if harness_spec else ())
                ),
            ),
            output_type=[str, DeferredToolRequests],
            system_prompt=instructions,
            name="superqode",
            toolsets=toolsets,
            model_settings=model_settings or None,
            defer_model_check=True,
        )
        self._agent = _apply_durable_wrapper(base_agent, harness_spec)

    async def run(self, prompt: str) -> AgentResponse:
        self._last_prompt = prompt
        try:
            result = await self._agent.run(prompt)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return AgentResponse(
                content=f"Runtime error: {exc}",
                messages=[],
                tool_calls_made=0,
                iterations=1,
                stopped_reason="error",
            )
        return self._translate_result(result)

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        self.reset_cancellation()
        self._last_prompt = prompt
        try:
            if not hasattr(self._agent, "run_stream"):
                response = await self.run(prompt)
                if response.content:
                    yield response.content
                return
            async with self._agent.run_stream(prompt) as response:
                async for chunk in response.stream_text(delta=True, debounce_by=None):
                    if self._cancelled:
                        break
                    if chunk:
                        yield chunk
                output = await response.get_output()
                if _is_deferred_tool_requests(output):
                    self._pending_requests = output
                    self._pending_messages = list(response.all_messages())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            yield f"Runtime error: {exc}"

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        """Stream PydanticAI events as normalized SuperQode harness events."""
        self.reset_cancellation()
        self._last_prompt = prompt
        yield HarnessEvent(type="model_request", data={"runtime": self.name})
        try:
            if not hasattr(self._agent, "run_stream_events"):
                async for chunk in self.run_streaming(prompt):
                    if chunk:
                        yield HarnessEvent(type="model_delta", data={"text": chunk})
                return

            async with self._agent.run_stream_events(prompt) as stream:
                async for event in stream:
                    if self._cancelled:
                        break
                    for normalized in _events_from_pydanticai_event(event):
                        yield normalized
                    result = _result_from_pydanticai_event(event)
                    if result is not None:
                        output = getattr(result, "output", None)
                        if _is_deferred_tool_requests(output):
                            self._pending_requests = output
                            self._pending_messages = _messages_from_result(result)
            if self._pending_requests is not None:
                yield HarnessEvent(
                    type="approval_required",
                    data={
                        "backend": self.name,
                        "runtime": self.name,
                        "pending_approvals": self.get_pending_approvals(),
                        "pending_runtime": self,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            yield HarnessEvent(
                type="runtime_error",
                data={"error": str(exc), "error_type": type(exc).__name__},
            )

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        if self._pending_requests is None:
            return []
        approvals = getattr(self._pending_requests, "approvals", []) or []
        pending: list[dict[str, Any]] = []
        for index, call in enumerate(approvals):
            pending.append(
                {
                    "index": index,
                    "tool_name": getattr(call, "tool_name", ""),
                    "arguments": getattr(call, "args", {}),
                    "tool_call_id": getattr(call, "tool_call_id", None),
                }
            )
        return pending

    async def approve_and_resume(self, index: int = 0, always: bool = False) -> AgentResponse:
        del always
        return await self._resume_with_decision(index=index, approved=True, message=None)

    async def reject_and_resume(
        self,
        index: int = 0,
        *,
        message: str | None = None,
        always: bool = False,
    ) -> AgentResponse:
        del always
        return await self._resume_with_decision(index=index, approved=False, message=message)

    async def _resume_with_decision(
        self,
        *,
        index: int,
        approved: bool,
        message: str | None,
    ) -> AgentResponse:
        if self._pending_requests is None:
            raise RuntimeError("No pending approval to act on")
        approvals = list(getattr(self._pending_requests, "approvals", []) or [])
        if index < 0 or index >= len(approvals):
            raise RuntimeError("No pending approval to act on")

        from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied

        call = approvals[index]
        tool_call_id = getattr(call, "tool_call_id", None)
        if not tool_call_id:
            raise RuntimeError("Pending approval is missing tool_call_id")
        decision = True if approved else ToolDenied(message or "Tool call rejected")
        results = DeferredToolResults(approvals={tool_call_id: decision})
        try:
            result = await self._agent.run(
                None,
                output_type=[str, DeferredToolRequests],
                message_history=self._pending_messages,
                deferred_tool_results=results,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return AgentResponse(
                content=f"Runtime error: {exc}",
                messages=[],
                tool_calls_made=0,
                iterations=1,
                stopped_reason="error",
            )
        return self._translate_result(result)

    def _translate_result(self, result: Any) -> AgentResponse:
        output = getattr(result, "output", None)
        if _is_deferred_tool_requests(output):
            self._pending_requests = output
            self._pending_messages = list(result.all_messages())
            return AgentResponse(
                content="",
                messages=[],
                tool_calls_made=0,
                iterations=1,
                stopped_reason="needs_approval",
            )
        self._pending_requests = None
        self._pending_messages = []
        return AgentResponse(
            content=_result_text(result),
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
        )

    def cancel(self) -> None:
        self._cancelled = True

    def reset_cancellation(self) -> None:
        self._cancelled = False


def _events_from_pydanticai_event(event: Any) -> list[HarnessEvent]:
    event_name = event.__class__.__name__
    events: list[HarnessEvent] = []

    text = _text_delta_from_event(event)
    if text:
        events.append(
            HarnessEvent(
                type="model_delta",
                data={"text": text, "source_event": event_name},
            )
        )

    tool_call = _tool_call_from_event(event)
    if tool_call is not None:
        events.append(
            HarnessEvent(
                type="tool_call",
                data={**tool_call, "source_event": event_name},
            )
        )

    tool_result = _tool_result_from_event(event)
    if tool_result is not None:
        events.append(
            HarnessEvent(
                type="tool_result",
                data={**tool_result, "source_event": event_name},
            )
        )

    result = _result_from_pydanticai_event(event)
    if result is not None:
        output = getattr(result, "output", None)
        if not _is_deferred_tool_requests(output):
            events.append(
                HarnessEvent(
                    type="model_result",
                    data={"output": _result_text(result), "source_event": event_name},
                )
            )

    if not events:
        events.append(
            HarnessEvent(
                type="runtime_event",
                data={"source_event": event_name},
            )
        )
    return events


def _text_delta_from_event(event: Any) -> str:
    for attr in ("text", "content", "delta", "content_delta", "text_delta"):
        value = getattr(event, attr, None)
        if isinstance(value, str):
            return value
    for owner_attr in ("delta", "part_delta"):
        owner = getattr(event, owner_attr, None)
        if owner is None or isinstance(owner, str):
            continue
        for attr in ("content_delta", "text_delta", "text", "content"):
            value = getattr(owner, attr, None)
            if isinstance(value, str):
                return value
    return ""


def _tool_call_from_event(event: Any) -> dict[str, Any] | None:
    part = getattr(event, "part", None) or getattr(event, "tool_call", None)
    if part is None:
        return None
    tool_name = getattr(part, "tool_name", None) or getattr(part, "name", None)
    if not tool_name:
        return None
    if getattr(part, "content", None) is not None or getattr(part, "result", None) is not None:
        return None
    args = getattr(part, "args", None) or getattr(part, "arguments", None) or {}
    return {
        "tool_name": tool_name,
        "tool_call_id": getattr(part, "tool_call_id", None),
        "arguments": args,
    }


def _tool_result_from_event(event: Any) -> dict[str, Any] | None:
    part = getattr(event, "part", None) or getattr(event, "tool_result", None)
    if part is None:
        return None
    tool_name = getattr(part, "tool_name", None) or getattr(event, "tool_name", None)
    content = getattr(part, "content", None) or getattr(part, "result", None)
    if content is None:
        return None
    return {
        "tool_name": tool_name,
        "tool_call_id": getattr(part, "tool_call_id", None) or getattr(event, "tool_call_id", None),
        "content": content,
    }


def _result_from_pydanticai_event(event: Any) -> Any | None:
    for attr in ("result", "run_result", "agent_run_result"):
        value = getattr(event, attr, None)
        if value is not None:
            return value
    return None


def _messages_from_result(result: Any) -> list[Any]:
    if hasattr(result, "all_messages"):
        return list(result.all_messages())
    messages = getattr(result, "messages", None)
    if isinstance(messages, list):
        return messages
    return []
