"""Optional DeepAgents runtime backend for HarnessSpec runs."""

from __future__ import annotations

import inspect
from typing import Any

from ...agent.loop import AgentMessage, AgentResponse
from ..compiler import compile_to_headless_profile
from ..model_policy import resolve_harness_model_policy
from ..spec import AgentSpec, HarnessFlavor
from .base import HarnessBackendRequest, HarnessBackendResult


class DeepAgentsHarnessBackend:
    """Adapter from SuperQode HarnessSpec to ``deepagents.create_deep_agent``.

    DeepAgents is kept optional and peer-level with other runtimes. It is most
    useful for graph/middleware/subagent-heavy coding harnesses; model-only
    harnesses should use the native runtime path because DeepAgents' public
    API is tool-oriented.
    """

    name = "deepagents"

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        if request.spec.flavor == HarnessFlavor.NO_TOOL:
            raise ValueError(
                "The deepagents backend requires a tool-capable harness. "
                "Use the builtin runtime for no-tool/model-only runs."
            )
        if not request.spec.execution_policy.allow_shell:
            raise ValueError(
                "The deepagents backend currently requires allow_shell=True because "
                "DeepAgents exposes its execute tool when using a filesystem backend."
            )

        create_deep_agent, filesystem_backend_cls, filesystem_permission_cls = _load_deepagents()
        profile = compile_to_headless_profile(request.spec)
        model_policy = resolve_harness_model_policy(
            request.spec,
            provider=request.provider,
            model=request.model,
        )
        model = _model_spec(request.provider, request.model)
        backend = filesystem_backend_cls(root_dir=str(request.working_directory), virtual_mode=True)
        agent = create_deep_agent(
            model=model,
            tools=[],
            system_prompt=profile.job_description or None,
            subagents=_subagent_specs(request.spec.agents, provider=request.provider, default_model=model),
            skills=_skill_sources(request.spec),
            memory=_memory_sources(request.spec),
            permissions=_filesystem_permissions(request, filesystem_permission_cls),
            backend=backend,
            response_format=request.metadata.get("response_format"),
            name=request.spec.name,
        )
        result = await _invoke_agent(agent, request.prompt)
        content = _extract_final_content(result)
        response = AgentResponse(
            content=content,
            messages=[AgentMessage(role="assistant", content=content)],
            tool_calls_made=_count_tool_calls(result),
            iterations=_count_assistant_turns(result),
            stopped_reason="complete",
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime="deepagents",
            metadata={
                "model_policy": model_policy.profile,
                "model": model,
            },
        )


def _load_deepagents():
    try:
        from deepagents.backends import FilesystemBackend
        from deepagents.graph import create_deep_agent
        from deepagents.middleware.filesystem import FilesystemPermission
    except ImportError as exc:
        raise ImportError(
            "The deepagents backend requires the optional 'deepagents' package. "
            "Install SuperQode with the DeepAgents extra or install deepagents directly."
        ) from exc
    return create_deep_agent, FilesystemBackend, FilesystemPermission


def _model_spec(provider: str, model: str) -> str:
    if ":" in model:
        return model
    return f"{provider}:{model}" if provider else model


def _subagent_specs(
    agents: tuple[AgentSpec, ...],
    *,
    provider: str,
    default_model: str,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for agent in agents[1:]:
        if not agent.delegates_to and agent.role not in {"subagent", "worker", "research", "review"}:
            continue
        model = _model_spec(provider, agent.model) if agent.model else default_model
        specs.append(
            {
                "name": agent.id,
                "description": agent.role or agent.id,
                "system_prompt": agent.system_prompt or agent.role or agent.id,
                "model": model,
                "tools": [],
                **({"skills": list(agent.skills)} if agent.skills else {}),
            }
        )
    return specs


def _skill_sources(spec) -> list[str] | None:
    configured = spec.runtime.config.get("skills")
    if configured is None:
        return None
    if isinstance(configured, str):
        configured = [configured]
    sources = [f"/{str(source).strip('/')}" for source in configured if str(source).strip()]
    return sources or None


def _memory_sources(spec) -> list[str] | None:
    configured = spec.runtime.config.get("memory")
    if configured is None:
        return None
    if configured is True:
        configured = spec.context.instruction_files
    if isinstance(configured, str):
        configured = [configured]
    sources = [f"/{str(path).strip('/')}" for path in configured if str(path).strip()]
    return sources or None


def _filesystem_permissions(
    request: HarnessBackendRequest,
    filesystem_permission_cls: Any,
) -> list[Any]:
    policy = request.spec.execution_policy
    permissions: list[Any] = []
    if not policy.allow_read:
        permissions.append(
            filesystem_permission_cls(operations=["read"], paths=["/**"], mode="deny")
        )
    if not policy.allow_write:
        permissions.append(
            filesystem_permission_cls(operations=["write"], paths=["/**"], mode="deny")
        )
    return permissions


async def _invoke_agent(agent: Any, prompt: str) -> Any:
    payload = {"messages": [{"role": "user", "content": prompt}]}
    if hasattr(agent, "ainvoke"):
        return await agent.ainvoke(payload)
    result = agent.invoke(payload)
    if inspect.isawaitable(result):
        return await result
    return result


def _extract_final_content(result: Any) -> str:
    messages = _messages_from_result(result)
    for message in reversed(messages):
        content = _message_content(message)
        if content:
            return content
    if isinstance(result, str):
        return result
    return str(result)


def _messages_from_result(result: Any) -> list[Any]:
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list):
            return messages
    messages = getattr(result, "messages", None)
    if isinstance(messages, list):
        return messages
    return []


def _message_content(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _count_tool_calls(result: Any) -> int:
    count = 0
    for message in _messages_from_result(result):
        tool_calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
        if isinstance(tool_calls, list):
            count += len(tool_calls)
    return count


def _count_assistant_turns(result: Any) -> int:
    count = 0
    for message in _messages_from_result(result):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        msg_type = getattr(message, "type", None)
        if role == "assistant" or msg_type == "ai":
            count += 1
    return count or 1
