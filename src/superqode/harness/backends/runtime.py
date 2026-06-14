"""Harness backend that delegates to SuperQode's existing runtime registry."""

from __future__ import annotations

from collections.abc import AsyncIterator

from ...agent.loop import AgentConfig
from ...providers.gateway.litellm_gateway import LiteLLMGateway
from ...runtime import create_runtime
from ...tools.base import ToolResult
from ...tools.base import ToolRegistry
from ...tools.permissions import PermissionManager
from ..compiler import compile_to_headless_profile
from ..events import HarnessEvent
from ..model_policy import EffectiveModelPolicy, resolve_harness_model_policy
from ..sandbox import apply_backend_permissions
from ..spec import HarnessFlavor, HarnessSpec
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult


class RuntimeHarnessBackend:
    """Adapter from HarnessBackend to the current AgentRuntime protocol."""

    def __init__(self, runtime_name: str) -> None:
        self.runtime_name = runtime_name
        self.name = runtime_name
        self.capabilities = _runtime_capabilities(runtime_name)

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        runtime_events: list[HarnessEvent] = []
        runtime_name, runtime_obj = _create_runtime_for_request(
            request,
            self.runtime_name,
            event_sink=runtime_events,
        )
        runtime_events.insert(
            0,
            HarnessEvent(type="model_request", data={"runtime": runtime_name}),
        )
        response = await runtime_obj.run(request.prompt)
        runtime_events.append(
            HarnessEvent(
                type="model_result",
                data={
                    "stopped_reason": response.stopped_reason,
                    "tool_calls_made": response.tool_calls_made,
                    "iterations": response.iterations,
                },
            )
        )
        pending_approvals = _pending_approvals(runtime_obj)
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime=runtime_name,
            metadata={
                **({"events": runtime_events} if runtime_events else {}),
                **({"pending_approvals": pending_approvals} if pending_approvals else {}),
                **({"pending_runtime": runtime_obj} if pending_approvals else {}),
            },
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        """Stream normalized harness delta events from the wrapped runtime."""
        _runtime_name, runtime_obj = _create_runtime_for_request(request, self.runtime_name)
        if hasattr(runtime_obj, "run_harness_events"):
            async for event in runtime_obj.run_harness_events(request.prompt):
                yield HarnessEvent(
                    type=event.type,
                    data=event.data,
                    timestamp=event.timestamp,
                    session_id=request.session_id,
                    run_id=event.run_id,
                )
        else:
            async for chunk in runtime_obj.run_streaming(request.prompt):
                if chunk:
                    yield HarnessEvent(
                        type="delta",
                        data={"text": chunk},
                        session_id=request.session_id,
                    )
        pending_approvals = _pending_approvals(runtime_obj)
        if pending_approvals:
            yield HarnessEvent(
                type="approval_required",
                data={
                    "backend": self.name,
                    "runtime": request.runtime or self.runtime_name,
                    "pending_approvals": pending_approvals,
                    "pending_runtime": runtime_obj,
                },
                session_id=request.session_id,
            )
        yield HarnessEvent(
            type="end",
            data={"backend": self.name, "runtime": request.runtime or self.runtime_name},
            session_id=request.session_id,
        )


class ADKHarnessBackend(RuntimeHarnessBackend):
    """First-class harness adapter name for Google ADK."""

    def __init__(self) -> None:
        super().__init__("adk")


class OpenAIAgentsHarnessBackend(RuntimeHarnessBackend):
    """First-class harness adapter name for OpenAI Agents SDK."""

    def __init__(self) -> None:
        super().__init__("openai-agents")


class CodexSDKHarnessBackend(RuntimeHarnessBackend):
    """First-class harness adapter name for OpenAI Codex Python SDK."""

    def __init__(self) -> None:
        super().__init__("codex-sdk")


class ClaudeAgentSDKHarnessBackend(RuntimeHarnessBackend):
    """First-class harness adapter name for the Anthropic Claude Agent SDK."""

    def __init__(self) -> None:
        super().__init__("claude-agent-sdk")


def _runtime_capabilities(runtime_name: str) -> HarnessBackendCapabilities:
    if runtime_name == "claude-agent-sdk":
        return HarnessBackendCapabilities(
            backend=runtime_name,
            supports_coding=True,
            supports_no_tool=True,
            supports_streaming=True,
            supports_approvals=False,
            supports_sandbox=True,
            supports_shell=True,
            supports_mcp=True,
            supports_typed_output=False,
            supports_workflow_children=True,
            event_detail="rich",
            notes=(
                "Anthropic Claude Agent SDK runtime (API key via ANTHROPIC_API_KEY). "
                "TUI approval callbacks are bridged via can_use_tool; MCP and slash "
                "commands resolve through the local Claude Code configuration.",
            ),
        )
    if runtime_name == "codex-sdk":
        return HarnessBackendCapabilities(
            backend=runtime_name,
            supports_coding=True,
            supports_no_tool=True,
            supports_streaming=True,
            supports_approvals=False,
            supports_sandbox=True,
            supports_shell=True,
            supports_mcp=True,
            supports_typed_output=False,
            supports_workflow_children=True,
            event_detail="rich",
            notes=(
                "Official Codex SDK runtime. TUI approval callbacks are bridged "
                "through SuperQode's inline prompt; harness pause/resume approvals "
                "are not exposed. MCP servers are resolved by the local Codex "
                "configuration.",
            ),
        )
    if runtime_name == "openai-agents":
        return HarnessBackendCapabilities(
            backend=runtime_name,
            supports_coding=True,
            supports_no_tool=True,
            supports_streaming=True,
            supports_approvals=True,
            supports_sandbox=True,
            supports_shell=True,
            supports_mcp=True,
            supports_typed_output=True,
            supports_workflow_children=True,
            event_detail="rich",
            notes=("OpenAI Agents approval pauses surface through HarnessKernel.",),
        )
    if runtime_name == "adk":
        return HarnessBackendCapabilities(
            backend=runtime_name,
            supports_coding=True,
            supports_no_tool=True,
            supports_streaming=True,
            supports_approvals=False,
            supports_sandbox=True,
            supports_shell=True,
            supports_mcp=False,
            supports_typed_output=True,
            supports_workflow_children=True,
            event_detail="rich",
            notes=("Google ADK uses SuperQode tool and permission bridging.",),
        )
    if runtime_name == "pydanticai":
        return HarnessBackendCapabilities(
            backend=runtime_name,
            supports_coding=True,
            supports_no_tool=True,
            supports_streaming=True,
            supports_approvals=True,
            supports_sandbox=False,
            supports_shell=True,
            supports_mcp=True,
            supports_typed_output=True,
            supports_workflow_children=True,
            event_detail="rich",
            notes=("PydanticAI uses SuperQode JSON-schema tool bridging.",),
        )
    if runtime_name == "builtin":
        return HarnessBackendCapabilities(
            backend=runtime_name,
            supports_coding=True,
            supports_no_tool=True,
            supports_streaming=True,
            supports_approvals=True,
            supports_sandbox=True,
            supports_shell=True,
            supports_mcp=True,
            supports_typed_output=True,
            supports_workflow_children=True,
            event_detail="rich",
            notes=("Builtin runtime pauses ASK-permission tool calls through HarnessKernel.",),
        )
    return HarnessBackendCapabilities(
        backend=runtime_name,
        supports_coding=True,
        supports_no_tool=True,
        supports_streaming=True,
        supports_approvals=False,
        supports_sandbox=True,
        supports_shell=True,
        supports_mcp=True,
        supports_typed_output=True,
        supports_workflow_children=True,
        event_detail="rich",
        notes=("Native runtime is the canonical SuperQode harness path.",),
    )


def _create_runtime_for_request(
    request: HarnessBackendRequest,
    default_runtime_name: str,
    *,
    event_sink: list[HarnessEvent] | None = None,
):
    profile = compile_to_headless_profile(request.spec)
    model_policy = resolve_harness_model_policy(
        request.spec,
        provider=request.provider,
        model=request.model,
    )
    runtime_name = request.runtime or default_runtime_name
    config = AgentConfig(
        provider=request.provider,
        model=request.model,
        system_prompt_level=request.system_level or model_policy.system_level,
        working_directory=request.working_directory,
        job_description=profile.job_description,
        plan_mode=profile.name == "plan",
        tools_enabled=request.spec.flavor != HarnessFlavor.NO_TOOL,
        max_iterations=_max_iterations_for_request(request, model_policy),
        temperature=model_policy.temperature,
        reasoning_effort=model_policy.reasoning,
        enable_session_storage=True,
        session_storage_dir=request.spec.context.session_storage,
        session_id=request.session_id,
        session_history_limit=model_policy.session_history_limit,
        tool_call_format=model_policy.tool_call_format,
    )
    callbacks = {}
    hook_kwargs = {}
    if runtime_name == "builtin":
        if event_sink is not None:
            callbacks = _builtin_event_callbacks(event_sink)
        # Build the lifecycle hook registry from the HarnessSpec: declared
        # handler rules (deny/allow/modify) plus store forwarders that persist
        # new lifecycle events through the kernel's event_sink.
        from ..hooks import build_hook_registry

        registry, _hook_errors = build_hook_registry(
            request.spec,
            event_sink=event_sink,
            session_id=request.session_id,
        )
        hook_kwargs = {"hooks": registry}

    return runtime_name, create_runtime(
        runtime_name,
        gateway=LiteLLMGateway(),
        tools=_tool_registry_for_request(request, profile, model_policy),
        config=config,
        harness_spec=request.spec,
        parallel_tools=(
            model_policy.parallel_tools
            and not (
                runtime_name == "builtin"
                and request.spec.execution_policy.approval_profile != "deny"
            )
        ),
        **callbacks,
        **hook_kwargs,
        permission_manager=PermissionManager(
            apply_backend_permissions(profile.permissions, request.sandbox_backend)
        ),
    )


def _pending_approvals(runtime_obj) -> list[dict]:
    if not hasattr(runtime_obj, "get_pending_approvals"):
        return []
    pending = runtime_obj.get_pending_approvals()
    if not pending:
        return []
    return [dict(item) for item in pending]


def _builtin_event_callbacks(event_sink: list[HarnessEvent]) -> dict:
    def on_tool_call(name: str, args: dict) -> None:
        event_sink.append(
            HarnessEvent(
                type="tool_call",
                data={"tool_name": name, "arguments": args},
            )
        )

    def on_tool_result(name: str, result: ToolResult) -> None:
        event_sink.append(
            HarnessEvent(
                type="tool_result",
                data={
                    "tool_name": name,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                    "metadata": dict(result.metadata),
                },
            )
        )

    async def on_thinking(text: str) -> None:
        if text:
            event_sink.append(HarnessEvent(type="thinking", data={"text": text}))

    return {
        "on_tool_call": on_tool_call,
        "on_tool_result": on_tool_result,
        "on_thinking": on_thinking,
    }


def _tool_registry_for_spec(
    spec: HarnessSpec,
    profile,
    model_policy: EffectiveModelPolicy,
) -> ToolRegistry:
    if spec.flavor == HarnessFlavor.NO_TOOL:
        return ToolRegistry.empty()
    registry = ToolRegistry.for_profile(model_policy.tool_profile or "coding")
    if profile.tools is not None:
        return registry.filtered(profile.tools)
    return registry


def _tool_registry_for_request(
    request: HarnessBackendRequest,
    profile,
    model_policy: EffectiveModelPolicy,
) -> ToolRegistry:
    agent_tools = request.metadata.get("agent_tools")
    if agent_tools:
        return ToolRegistry.for_profile(model_policy.tool_profile or "coding").filtered(
            [str(tool) for tool in agent_tools]
        )
    return _tool_registry_for_spec(request.spec, profile, model_policy)


def _max_iterations_for_request(
    request: HarnessBackendRequest,
    model_policy: EffectiveModelPolicy,
) -> int:
    if request.metadata.get("agent_max_iterations") is not None:
        return int(request.metadata["agent_max_iterations"])
    return model_policy.max_iterations
