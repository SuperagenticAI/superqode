"""Harness backend that delegates to SuperQode's existing runtime registry."""

from __future__ import annotations

from ...agent.loop import AgentConfig
from ...providers.gateway.litellm_gateway import LiteLLMGateway
from ...runtime import create_runtime
from ...sandbox import apply_backend_permissions
from ...tools.base import ToolRegistry
from ...tools.permissions import PermissionManager
from ..compiler import compile_to_headless_profile
from ..model_policy import EffectiveModelPolicy, resolve_harness_model_policy
from ..spec import HarnessFlavor, HarnessSpec
from .base import HarnessBackendRequest, HarnessBackendResult


class RuntimeHarnessBackend:
    """Adapter from HarnessBackend to the current AgentRuntime protocol."""

    def __init__(self, runtime_name: str) -> None:
        self.runtime_name = runtime_name
        self.name = runtime_name

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        profile = compile_to_headless_profile(request.spec)
        model_policy = resolve_harness_model_policy(
            request.spec,
            provider=request.provider,
            model=request.model,
        )
        runtime_name = request.runtime or self.runtime_name
        config = AgentConfig(
            provider=request.provider,
            model=request.model,
            system_prompt_level=request.system_level or model_policy.system_level,
            working_directory=request.working_directory,
            job_description=profile.job_description,
            plan_mode=profile.name == "plan",
            tools_enabled=request.spec.flavor != HarnessFlavor.NO_TOOL,
            max_iterations=model_policy.max_iterations,
            temperature=model_policy.temperature,
            reasoning_effort=model_policy.reasoning,
            enable_session_storage=True,
            session_storage_dir=request.spec.context.session_storage,
            session_id=request.session_id,
            session_history_limit=model_policy.session_history_limit,
        )
        runtime_obj = create_runtime(
            runtime_name,
            gateway=LiteLLMGateway(),
            tools=_tool_registry_for_spec(request.spec, profile, model_policy),
            config=config,
            parallel_tools=model_policy.parallel_tools,
            permission_manager=PermissionManager(
                apply_backend_permissions(profile.permissions, request.sandbox_backend)
            ),
        )
        response = await runtime_obj.run(request.prompt)
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime=runtime_name,
        )


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
