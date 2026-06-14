"""Optional DeepAgents runtime backend for HarnessSpec runs."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import Any

from ...agent.loop import AgentMessage, AgentResponse
from ..compiler import compile_to_headless_profile
from ..events import HarnessEvent
from ..model_policy import resolve_harness_model_policy
from ..spec import AgentSpec, HarnessFlavor
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult


class DeepAgentsHarnessBackend:
    """Adapter from SuperQode HarnessSpec to ``deepagents.create_deep_agent``.

    DeepAgents is kept optional and peer-level with other runtimes. It is most
    useful for graph/middleware/subagent-heavy coding harnesses; model-only
    harnesses should use the native runtime path because DeepAgents' public
    API is tool-oriented.
    """

    name = "deepagents"
    capabilities = HarnessBackendCapabilities(
        backend=name,
        supports_coding=True,
        supports_no_tool=False,
        supports_streaming=True,
        supports_approvals=False,
        supports_sandbox=True,
        supports_shell=True,
        supports_mcp=False,
        supports_typed_output=True,
        supports_workflow_children=True,
        event_detail="rich",
        notes=(
            "DeepAgents requires a tool-capable harness.",
            "DeepAgents currently requires allow_shell=True with its filesystem backend.",
        ),
    )

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        agent, metadata = _create_agent_for_request(request)
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
            metadata=metadata,
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        agent, metadata = _create_agent_for_request(request)
        async for event in _stream_agent_events(agent, request.prompt):
            yield HarnessEvent(
                type=event.type,
                data={
                    **event.data,
                    **({"model": metadata["model"]} if event.type == "model_request" else {}),
                },
                timestamp=event.timestamp,
                session_id=request.session_id,
            )
        yield HarnessEvent(
            type="end",
            data={"backend": self.name, "runtime": self.name},
            session_id=request.session_id,
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


def _validate_deepagents_request(request: HarnessBackendRequest) -> None:
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


def _create_agent_for_request(request: HarnessBackendRequest) -> tuple[Any, dict[str, Any]]:
    _validate_deepagents_request(request)
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
        subagents=_subagent_specs(
            request.spec.agents, provider=request.provider, default_model=model
        ),
        skills=_skill_sources(request.spec),
        memory=_memory_sources(request.spec),
        permissions=_filesystem_permissions(request, filesystem_permission_cls),
        backend=backend,
        response_format=request.metadata.get("response_format"),
        name=request.spec.name,
    )
    return agent, {"model_policy": model_policy.profile, "model": model}


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
        if not agent.delegates_to and agent.role not in {
            "subagent",
            "worker",
            "research",
            "review",
        }:
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


async def _stream_agent_events(agent: Any, prompt: str) -> AsyncIterator[HarnessEvent]:
    payload = {"messages": [{"role": "user", "content": prompt}]}
    yield HarnessEvent(type="model_request", data={"runtime": "deepagents"})
    if hasattr(agent, "astream_events"):
        async for raw in agent.astream_events(payload):
            for event in _events_from_deepagents_event(raw):
                yield event
        return
    if hasattr(agent, "astream"):
        async for raw in agent.astream(payload):
            for event in _events_from_deepagents_event(raw):
                yield event
        return
    result = await _invoke_agent(agent, prompt)
    content = _extract_final_content(result)
    if content:
        yield HarnessEvent(type="model_result", data={"output": content})


def _events_from_deepagents_event(event: Any) -> list[HarnessEvent]:
    payload = event if isinstance(event, dict) else _event_object_to_dict(event)
    event_name = str(payload.get("event") or payload.get("type") or event.__class__.__name__)
    name = str(payload.get("name") or payload.get("node") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    events: list[HarnessEvent] = []

    text = _deepagents_text_delta(payload, data)
    if text:
        events.append(
            HarnessEvent(
                type="model_delta",
                data={"text": text, "source_event": event_name, "node": name},
            )
        )

    tool_call = _deepagents_tool_call(payload, data)
    if tool_call is not None:
        events.append(
            HarnessEvent(type="tool_call", data={**tool_call, "source_event": event_name})
        )

    tool_result = _deepagents_tool_result(payload, data)
    if tool_result is not None:
        events.append(
            HarnessEvent(type="tool_result", data={**tool_result, "source_event": event_name})
        )

    subagent = _deepagents_subagent_event(event_name, payload, data)
    if subagent is not None:
        events.append(subagent)

    memory = _deepagents_memory_event(event_name, payload, data)
    if memory is not None:
        events.append(memory)

    sandbox = _deepagents_sandbox_event(event_name, payload, data)
    if sandbox is not None:
        events.append(sandbox)

    final = _deepagents_final_output(payload, data)
    if final:
        events.append(
            HarnessEvent(
                type="model_result",
                data={"output": final, "source_event": event_name, "node": name},
            )
        )

    if not events and _keep_deepagents_runtime_event(event_name):
        events.append(
            HarnessEvent(
                type="runtime_event",
                data={"source_event": event_name, "node": name},
            )
        )
    return events


def _event_object_to_dict(event: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("event", "type", "name", "node", "data", "metadata"):
        if hasattr(event, key):
            out[key] = getattr(event, key)
    return out


def _deepagents_text_delta(payload: dict[str, Any], data: dict[str, Any]) -> str:
    for source in (payload, data):
        for key in ("chunk", "delta", "text", "content"):
            value = source.get(key)
            if isinstance(value, str):
                return value
    chunk = data.get("chunk") or payload.get("chunk")
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    return ""


def _deepagents_tool_call(
    payload: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any] | None:
    event_name = str(payload.get("event") or payload.get("type") or "")
    if "tool" not in event_name or not event_name.endswith(("_start", "start")):
        return None
    tool_name = str(payload.get("name") or data.get("name") or "")
    return {"tool_name": tool_name, "arguments": data.get("input") or data.get("args") or {}}


def _deepagents_tool_result(
    payload: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any] | None:
    event_name = str(payload.get("event") or payload.get("type") or "")
    if "tool" not in event_name or not event_name.endswith(("_end", "end")):
        return None
    tool_name = str(payload.get("name") or data.get("name") or "")
    return {"tool_name": tool_name, "content": data.get("output") or data.get("result")}


def _deepagents_subagent_event(
    event_name: str,
    payload: dict[str, Any],
    data: dict[str, Any],
) -> HarnessEvent | None:
    marker = f"{event_name} {payload.get('name', '')} {payload.get('node', '')}".lower()
    if "subagent" not in marker and "task" not in marker:
        return None
    event_type = "subagent_result" if event_name.endswith(("_end", "end")) else "subagent_start"
    return HarnessEvent(
        type=event_type,
        data={
            "name": payload.get("name") or payload.get("node") or data.get("name"),
            "input": data.get("input"),
            "output": data.get("output") or data.get("result"),
            "source_event": event_name,
        },
    )


def _deepagents_memory_event(
    event_name: str,
    payload: dict[str, Any],
    data: dict[str, Any],
) -> HarnessEvent | None:
    marker = f"{event_name} {payload.get('name', '')}".lower()
    if "memory" not in marker and "/memories/" not in str(data).lower():
        return None
    event_type = (
        "memory_write" if any(token in marker for token in ("write", "edit")) else "memory_read"
    )
    return HarnessEvent(
        type=event_type,
        data={"path": data.get("path"), "source_event": event_name},
    )


def _deepagents_sandbox_event(
    event_name: str,
    payload: dict[str, Any],
    data: dict[str, Any],
) -> HarnessEvent | None:
    marker = f"{event_name} {payload.get('name', '')}".lower()
    if not any(
        token in marker for token in ("sandbox", "execute", "filesystem", "write_file", "edit_file")
    ):
        return None
    if "execute" in marker or "command" in marker:
        event_type = "sandbox_command"
    elif "write" in marker or "edit" in marker or "file" in marker:
        event_type = "sandbox_file"
    else:
        event_type = "sandbox_event"
    return HarnessEvent(
        type=event_type,
        data={
            "name": payload.get("name"),
            "input": data.get("input") or data.get("args"),
            "output": data.get("output") or data.get("result"),
            "source_event": event_name,
        },
    )


def _deepagents_final_output(payload: dict[str, Any], data: dict[str, Any]) -> str:
    for source in (data, payload):
        output = source.get("output") or source.get("result")
        if isinstance(output, str):
            return output
    return ""


def _keep_deepagents_runtime_event(event_name: str) -> bool:
    lowered = event_name.lower()
    return any(token in lowered for token in ("chain", "graph", "node", "agent"))


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
    content = (
        message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    )
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
        tool_calls = (
            message.get("tool_calls")
            if isinstance(message, dict)
            else getattr(message, "tool_calls", None)
        )
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
