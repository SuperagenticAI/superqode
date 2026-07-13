"""Reference Harness Protocol v1 adapters for Core, Python, and ACP."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .events import HarnessEvent
from .kernel import HarnessKernel, HarnessSession
from .protocol import (
    HarnessCapabilities,
    HarnessCapabilityError,
    HarnessCheckpoint,
    HarnessCreateRequest,
    HarnessDescriptor,
    HarnessMessage,
    HarnessSessionRef,
    require_capability,
)
from .spec import HarnessSpec
from .store import MemoryHarnessStore


class BaseHarnessAdapter:
    """Safe defaults for optional adapter operations."""

    descriptor: HarnessDescriptor

    async def resume(self, session: HarnessSessionRef) -> HarnessSessionRef:
        require_capability(self.descriptor, "resume")
        return session

    async def steer(self, session: HarnessSessionRef, message: HarnessMessage) -> None:
        del session, message
        raise HarnessCapabilityError(self.descriptor.id, "steer")

    async def cancel(self, session: HarnessSessionRef) -> None:
        del session
        raise HarnessCapabilityError(self.descriptor.id, "cancel")

    async def checkpoint(self, session: HarnessSessionRef) -> HarnessCheckpoint:
        del session
        raise HarnessCapabilityError(self.descriptor.id, "checkpoint")


class CoreHarnessProtocolAdapter(BaseHarnessAdapter):
    """Expose SuperQode's native ``HarnessKernel`` through Protocol v1."""

    def __init__(self, spec: HarnessSpec, *, adapter_id: str = "core") -> None:
        self.spec = spec
        self.descriptor = HarnessDescriptor(
            id=adapter_id,
            name="SuperQode Core",
            description="SuperQode's native minimal coding harness",
            capabilities=HarnessCapabilities(
                streaming=False,
                resume=True,
                approvals=True,
                tools=not spec.is_no_tool,
                usage=True,
            ),
            metadata={"spec": spec.name, "runtime": spec.runtime.backend},
        )
        self._kernel = HarnessKernel(spec, store=MemoryHarnessStore())
        self._sessions: dict[str, HarnessSession] = {}

    async def create(self, request: HarnessCreateRequest) -> HarnessSessionRef:
        session = await self._kernel.session(request.session_id)
        self._sessions[session.session_id] = session
        return HarnessSessionRef(
            session_id=session.session_id,
            harness_id=self.descriptor.id,
            metadata={
                "provider": request.provider,
                "model": request.model,
                "working_directory": str(request.working_directory),
                **dict(request.metadata),
            },
        )

    async def resume(self, session: HarnessSessionRef) -> HarnessSessionRef:
        core_session = await self._kernel.session(session.session_id)
        self._sessions[session.session_id] = core_session
        return session

    async def send(
        self,
        session: HarnessSessionRef,
        message: HarnessMessage,
    ) -> AsyncIterator[HarnessEvent]:
        core_session = self._sessions.get(session.session_id)
        if core_session is None:
            core_session = await self._kernel.session(session.session_id)
            self._sessions[session.session_id] = core_session
        provider = str(session.metadata.get("provider") or "")
        model = str(session.metadata.get("model") or "")
        if not provider or not model:
            raise ValueError("Core harness sessions require both provider and model")
        yield HarnessEvent(
            type="model.requested",
            data={"provider": provider, "model": model, "runtime": self.spec.runtime.backend},
        )
        result = await core_session.prompt(
            message.content,
            provider=provider,
            model=model,
            working_directory=Path(str(session.metadata.get("working_directory") or Path.cwd())),
            metadata={"protocol_version": self.descriptor.protocol_version},
        )
        for event in result.events:
            if event.run_id != result.run_id:
                continue
            if event.type in {"run_start", "run_end", "model_request", "model_result"}:
                continue
            yield event
        yield HarnessEvent(
            type="model.completed",
            data={
                "provider": provider,
                "model": model,
                "stopped_reason": result.response.stopped_reason,
                "iterations": result.iterations,
                "tool_calls_made": result.tool_calls_made,
                "usage": {
                    "input_tokens": result.tokens_in,
                    "output_tokens": result.tokens_out,
                    "total_tokens": result.total_tokens,
                    "cost_usd": result.cost_usd,
                },
            },
        )
        yield HarnessEvent(
            type="message.created",
            data=HarnessMessage("assistant", result.content).to_dict(),
        )
        if result.response.error:
            yield HarnessEvent(
                type="run.failed",
                data={
                    "error": result.response.error,
                    "stopped_reason": result.response.stopped_reason,
                },
            )
        elif result.response.stopped_reason == "needs_approval":
            yield HarnessEvent(
                type="run.completed",
                data={"status": "needs_approval"},
            )


@dataclass(frozen=True)
class PythonHarnessResult:
    """Convenient non-streaming result for a direct Python harness."""

    content: str
    events: tuple[HarnessEvent, ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


PythonHarnessHandler = Callable[[HarnessMessage, HarnessSessionRef], Any]


class DirectPythonHarnessAdapter(BaseHarnessAdapter):
    """Turn a Python callable or object into a package-friendly harness adapter."""

    def __init__(
        self,
        harness_id: str,
        handler: PythonHarnessHandler,
        *,
        name: str | None = None,
        description: str = "",
        supports_steer: bool | None = None,
    ) -> None:
        self.handler = handler
        steer = hasattr(handler, "steer") if supports_steer is None else supports_steer
        self.descriptor = HarnessDescriptor(
            id=harness_id,
            name=name or harness_id,
            description=description or "Direct Python harness",
            capabilities=HarnessCapabilities(
                streaming=True,
                resume=True,
                steer=steer,
                cancel=True,
                checkpoint=True,
                usage=True,
            ),
            metadata={"extension_surface": "python"},
        )
        self._session_state: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    async def create(self, request: HarnessCreateRequest) -> HarnessSessionRef:
        session_id = request.session_id or f"python-{uuid.uuid4().hex[:12]}"
        self._session_state.setdefault(session_id, {})
        return HarnessSessionRef(
            session_id=session_id,
            harness_id=self.descriptor.id,
            metadata={
                "provider": request.provider,
                "model": request.model,
                "working_directory": str(request.working_directory),
                **dict(request.metadata),
            },
        )

    async def resume(self, session: HarnessSessionRef) -> HarnessSessionRef:
        state = dict(session.metadata.get("checkpoint_state") or {})
        self._session_state.setdefault(session.session_id, {}).update(state)
        return session

    async def send(
        self,
        session: HarnessSessionRef,
        message: HarnessMessage,
    ) -> AsyncIterator[HarnessEvent]:
        yield HarnessEvent(
            type="model.requested",
            data={
                "provider": session.metadata.get("provider") or "",
                "model": session.metadata.get("model") or "",
            },
        )
        current_task = asyncio.current_task()
        if current_task is not None:
            self._tasks[session.session_id] = current_task
        try:
            result = self.handler(message, session)
            if inspect.isawaitable(result):
                result = await result
            if hasattr(result, "__aiter__"):
                content: list[str] = []
                assistant_created = False
                async for item in result:
                    if isinstance(item, HarnessEvent):
                        if item.type == "message.delta":
                            content.append(str(item.data.get("text") or ""))
                        if item.type == "message.created" and item.data.get("role") == "assistant":
                            assistant_created = True
                        yield item
                    else:
                        text = str(item)
                        content.append(text)
                        yield HarnessEvent(type="message.delta", data={"text": text})
                yield HarnessEvent(type="model.completed", data={"streamed": True})
                if not assistant_created:
                    yield HarnessEvent(
                        type="message.created",
                        data=HarnessMessage("assistant", "".join(content)).to_dict(),
                    )
                return
            normalized = _python_result(result)
            for event in normalized.events:
                yield event
            yield HarnessEvent(
                type="model.completed",
                data={"usage": dict(normalized.usage), **dict(normalized.metadata)},
            )
            yield HarnessEvent(
                type="message.created",
                data=HarnessMessage("assistant", normalized.content).to_dict(),
            )
        finally:
            self._tasks.pop(session.session_id, None)

    async def steer(self, session: HarnessSessionRef, message: HarnessMessage) -> None:
        require_capability(self.descriptor, "steer")
        method = getattr(self.handler, "steer")
        result = method(message, session)
        if inspect.isawaitable(result):
            await result

    async def cancel(self, session: HarnessSessionRef) -> None:
        task = self._tasks.get(session.session_id)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def checkpoint(self, session: HarnessSessionRef) -> HarnessCheckpoint:
        state = dict(self._session_state.setdefault(session.session_id, {}))
        method = getattr(self.handler, "checkpoint", None)
        if method is not None:
            result = method(session)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, dict):
                state.update(result)
        return HarnessCheckpoint(
            session_id=session.session_id,
            harness_id=self.descriptor.id,
            state=state,
        )


ACPClientFactory = Callable[..., Any]
PermissionHandler = Callable[[list[dict[str, Any]], dict[str, Any]], Awaitable[str]]


class ACPHarnessProtocolAdapter(BaseHarnessAdapter):
    """Expose any Agent Client Protocol process through Harness Protocol v1."""

    def __init__(
        self,
        command: str,
        *,
        adapter_id: str = "acp",
        name: str = "ACP agent",
        client_factory: ACPClientFactory | None = None,
        permission_handler: PermissionHandler | None = None,
    ) -> None:
        self.command = command
        self._client_factory = client_factory or _default_acp_client_factory
        self._permission_handler = permission_handler
        self.descriptor = HarnessDescriptor(
            id=adapter_id,
            name=name,
            description="Agent Client Protocol coding-agent adapter",
            capabilities=HarnessCapabilities(
                streaming=True,
                resume=True,
                cancel=True,
                approvals=True,
                tools=True,
                usage=True,
            ),
            metadata={"transport": "acp", "command": command},
        )
        self._clients: dict[str, Any] = {}
        self._queues: dict[str, asyncio.Queue[HarnessEvent]] = {}

    async def create(self, request: HarnessCreateRequest) -> HarnessSessionRef:
        session_id = request.session_id or f"acp-{uuid.uuid4().hex[:12]}"
        queue: asyncio.Queue[HarnessEvent] = asyncio.Queue()
        client = self._build_client(request, queue=queue)
        if not await client.start():
            await client.stop()
            raise RuntimeError(f"ACP agent failed to start: {self.command}")
        self._clients[session_id] = client
        self._queues[session_id] = queue
        return HarnessSessionRef(
            session_id=session_id,
            harness_id=self.descriptor.id,
            external_session_id=client.get_session_id(),
            metadata={
                "command": self.command,
                "provider": request.provider,
                "model": request.model,
                "working_directory": str(request.working_directory),
                "supports_resume": bool(client.supports_resume()),
                **dict(request.metadata),
            },
        )

    async def resume(self, session: HarnessSessionRef) -> HarnessSessionRef:
        if not session.external_session_id or not session.metadata.get("supports_resume"):
            raise HarnessCapabilityError(self.descriptor.id, "resume for this ACP agent")
        queue: asyncio.Queue[HarnessEvent] = asyncio.Queue()
        request = HarnessCreateRequest(
            harness_id=self.descriptor.id,
            provider=str(session.metadata.get("provider") or ""),
            model=str(session.metadata.get("model") or ""),
            working_directory=Path(str(session.metadata.get("working_directory") or Path.cwd())),
            session_id=session.session_id,
            metadata=dict(session.metadata),
        )
        client = self._build_client(
            request,
            queue=queue,
            resume_session_id=session.external_session_id,
        )
        if not await client.start():
            await client.stop()
            raise RuntimeError(f"ACP agent failed to resume: {self.command}")
        if not client.supports_resume() or client.get_session_id() != session.external_session_id:
            await client.stop()
            raise HarnessCapabilityError(self.descriptor.id, "resume for this ACP agent")
        old_client = self._clients.get(session.session_id)
        if old_client is not None:
            await old_client.stop()
        self._clients[session.session_id] = client
        self._queues[session.session_id] = queue
        return session

    async def send(
        self,
        session: HarnessSessionRef,
        message: HarnessMessage,
    ) -> AsyncIterator[HarnessEvent]:
        client = self._clients.get(session.session_id)
        queue = self._queues.get(session.session_id)
        if client is None or queue is None:
            session = await self.resume(session)
            client = self._clients[session.session_id]
            queue = self._queues[session.session_id]
        yield HarnessEvent(
            type="model.requested",
            data={
                "provider": session.metadata.get("provider") or "",
                "model": session.metadata.get("model") or "",
                "transport": "acp",
            },
        )
        task = asyncio.create_task(client.send_prompt(message.content))
        message_parts: list[str] = []
        try:
            while not task.done() or not queue.empty():
                if queue.empty():
                    queue_task = asyncio.create_task(queue.get())
                    done, _pending = await asyncio.wait(
                        {task, queue_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if queue_task in done:
                        event = queue_task.result()
                        if event.type == "message.delta":
                            message_parts.append(str(event.data.get("text") or ""))
                        yield event
                    else:
                        queue_task.cancel()
                else:
                    event = queue.get_nowait()
                    if event.type == "message.delta":
                        message_parts.append(str(event.data.get("text") or ""))
                    yield event
            stop_reason = await task
            while not queue.empty():
                event = queue.get_nowait()
                if event.type == "message.delta":
                    message_parts.append(str(event.data.get("text") or ""))
                yield event
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        stats = client.get_stats()
        yield HarnessEvent(
            type="model.completed",
            data={
                "stopped_reason": stop_reason,
                "usage": {
                    "input_tokens": stats.prompt_tokens,
                    "output_tokens": stats.completion_tokens,
                    "thinking_tokens": stats.thinking_tokens,
                    "cost_usd": stats.cost,
                },
                "tool_calls_made": stats.tool_count,
                "files_modified": list(stats.files_modified),
                "files_read": list(stats.files_read),
            },
        )
        yield HarnessEvent(
            type="message.created",
            data=HarnessMessage(
                "assistant", client.get_message_buffer() or "".join(message_parts)
            ).to_dict(),
        )

    async def cancel(self, session: HarnessSessionRef) -> None:
        client = self._clients.get(session.session_id)
        if client is not None and not await client.cancel():
            raise RuntimeError(f"ACP agent did not acknowledge cancellation: {session.session_id}")

    async def close(self, session: HarnessSessionRef) -> None:
        client = self._clients.pop(session.session_id, None)
        self._queues.pop(session.session_id, None)
        if client is not None:
            await client.stop()

    def _build_client(
        self,
        request: HarnessCreateRequest,
        *,
        queue: asyncio.Queue[HarnessEvent],
        resume_session_id: str | None = None,
    ) -> Any:
        async def on_message(text: str) -> None:
            await queue.put(HarnessEvent(type="message.delta", data={"text": text}))

        async def on_thinking(text: str) -> None:
            await queue.put(HarnessEvent(type="model.thinking", data={"text": text}))

        async def on_tool_call(tool: dict[str, Any]) -> None:
            await queue.put(HarnessEvent(type="tool.requested", data=dict(tool)))

        async def on_tool_update(tool: dict[str, Any]) -> None:
            await queue.put(HarnessEvent(type="tool.completed", data=dict(tool)))

        async def on_permission_request(options: list[dict[str, Any]], tool: dict[str, Any]) -> str:
            await queue.put(
                HarnessEvent(
                    type="approval.requested",
                    data={"options": list(options), "tool": dict(tool)},
                )
            )
            if self._permission_handler is None:
                decision = "reject_once"
            else:
                decision = await self._permission_handler(options, tool)
            await queue.put(HarnessEvent(type="approval.resolved", data={"decision": decision}))
            return decision

        return self._client_factory(
            project_root=request.working_directory,
            command=str(request.metadata.get("command") or self.command),
            model=request.model or None,
            resume_session_id=resume_session_id,
            on_message=on_message,
            on_thinking=on_thinking,
            on_tool_call=on_tool_call,
            on_tool_update=on_tool_update,
            on_permission_request=on_permission_request,
        )


def _python_result(result: Any) -> PythonHarnessResult:
    if isinstance(result, PythonHarnessResult):
        return result
    if isinstance(result, str):
        return PythonHarnessResult(content=result)
    if result is None:
        return PythonHarnessResult(content="")
    raise TypeError(
        "Python harness handler must return str, PythonHarnessResult, an awaitable, "
        "or an async iterator"
    )


def _default_acp_client_factory(**kwargs: Any) -> Any:
    from ..acp.client import ACPClient

    return ACPClient(**kwargs)
