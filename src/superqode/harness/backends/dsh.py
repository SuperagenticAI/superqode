"""Native Python bridge from HarnessSpec to the DeepSeek Harness SDK runtime.

DeepSeek ships its TypeScript harness as a compiled single-file executable
inside the ``deepseek-harness-runtime-bin`` platform wheel, driven from Python
over newline-delimited JSON-RPC by ``deepseek-harness-sdk``.  This backend hosts
that stream: DeepSeek owns the agent loop, tools, prompts, and compaction, and
SuperQode translates the wire vocabulary into normalized harness events.

The SDK is synchronous (reader threads feeding ``queue.Queue``), so every
blocking call is dispatched to a worker thread and awaited.
"""

from __future__ import annotations

import asyncio
import atexit
import importlib.util
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ...agent.loop import AgentResponse
from ...providers.env_introspect import install_command
from ..events import HarnessEvent
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult

DSH_BACKEND_NAME = "deepseek-harness"
# DeepSeek's own shorthand. Kept resolvable so `runtime.backend: dsh` in an
# existing harness file, and the short name in the TUI, both still work.
DSH_BACKEND_ALIASES = ("dsh",)
HarnessFactory = Callable[[HarnessBackendRequest, "DSHSettings"], Any]

# The kernel builds a fresh backend object per run, so runtime reuse has to live
# beside it. DeepSeek treats a session id as owning a persisted log: sending a
# second prompt from a new process under the same id is rejected as an id
# collision, which breaks every conversation after its first message. Keeping the
# subprocess alive per session is also what the SDK documents.
_RUNTIMES: dict[tuple[str, str], Any] = {}
_RUNTIMES_LOCK = threading.Lock()

# SuperQode session ids are durable across restarts, but DeepSeek rejects an id
# whose persisted log predates the live session. Namespacing per process keeps a
# resumed SuperQode session working; DeepSeek-side history does not survive a
# restart, which matches this backend's advertised fresh-session continuity.
_PROCESS_TOKEN = uuid.uuid4().hex[:8]


def _runtime_session_id(session_id: str) -> str:
    return f"{session_id}-{_PROCESS_TOKEN}"


def close_dsh_runtimes() -> None:
    """Shut down every cached DeepSeek runtime subprocess."""
    with _RUNTIMES_LOCK:
        harnesses = list(_RUNTIMES.values())
        _RUNTIMES.clear()
    for harness in harnesses:
        try:
            harness.close()
        except Exception:
            pass


atexit.register(close_dsh_runtimes)


@dataclass(frozen=True, slots=True)
class DSHSettings:
    """Resolved runtime settings for one DeepSeek Harness run."""

    provider: str = "deepseek-official"
    model: str = "deepseek-v4-flash"
    max_tokens: int | None = None
    cordis: str | None = None
    session_root: str | None = None
    runtime_bin: str | None = None
    env: Mapping[str, str] | None = None
    base_url: str | None = None
    api_key: str | None = None
    request_timeout_seconds: float | None = None
    shutdown_timeout_seconds: float = 1.0
    prompt_timeout_seconds: float = 600.0
    bridged_from: str | None = None

    @classmethod
    def from_request(cls, request: HarnessBackendRequest) -> "DSHSettings":
        # 'deepseek_harness' matches the backend name the way prime-agent uses
        # 'prime_agent'; 'dsh' stays readable for files written against the
        # shorthand.
        nested = request.spec.runtime.config.get("deepseek_harness")
        if not isinstance(nested, dict):
            nested = request.spec.runtime.config.get("dsh")
        raw = dict(nested) if isinstance(nested, dict) else dict(request.spec.runtime.config)
        environment = raw.get("env")
        env = (
            {str(key): str(value) for key, value in environment.items()}
            if isinstance(environment, Mapping)
            else None
        )
        cordis = _text(raw.get("cordis"))
        session_root = _text(raw.get("session_root"))
        # DeepSeek resolves provider route *names* from its own Cordis
        # composition, so forwarding 'ollama' as a provider would fail the
        # handshake. The endpoint behind the route is configurable though, so a
        # connected OpenAI-compatible route is bridged onto base_url/model while
        # the route name stays the one the composition registers.
        route = request if bool(raw.get("use_superqode_route", False)) else None
        bridge = (
            None
            if route or _text(raw.get("base_url")) or _text(raw.get("model"))
            else _bridged_route(request.provider, request.model)
        )
        return cls(
            provider=(
                (_text(route.provider) if route else None)
                or _text(raw.get("provider"))
                or "deepseek-official"
            ),
            model=(
                (_text(route.model) if route else None)
                or _text(raw.get("model"))
                or (bridge.model if bridge else None)
                or "deepseek-v4-flash"
            ),
            max_tokens=_optional_int(raw.get("max_tokens")),
            cordis=_resolve_optional_path(request.working_directory, cordis),
            session_root=_resolve_optional_path(
                request.working_directory,
                session_root or str(Path(".superqode") / DSH_BACKEND_NAME / "sessions"),
            ),
            runtime_bin=_text(raw.get("runtime_bin")),
            env=env,
            base_url=_text(raw.get("base_url")) or (bridge.base_url if bridge else None),
            api_key=_text(raw.get("api_key")) or (bridge.api_key if bridge else None),
            bridged_from=bridge.source if bridge else None,
            request_timeout_seconds=_optional_positive_float(raw.get("request_timeout")),
            shutdown_timeout_seconds=_positive_float(raw.get("shutdown_timeout"), 1.0),
            prompt_timeout_seconds=_positive_float(raw.get("prompt_timeout"), 600.0),
        )


class DSHHarnessBackend:
    """Run the DeepSeek Harness runtime through its Python SDK."""

    name = DSH_BACKEND_NAME
    capabilities = HarnessBackendCapabilities(
        backend=DSH_BACKEND_NAME,
        supports_coding=True,
        supports_no_tool=False,
        supports_streaming=True,
        # DeepSeek owns tool execution and its own permission mode, so SuperQode
        # approval profiles cannot gate a call before it runs.
        supports_approvals=False,
        supports_sandbox=False,
        supports_shell=True,
        supports_mcp=False,
        supports_typed_output=False,
        supports_workflow_children=False,
        event_detail="rich",
        notes=(
            "DeepSeek Harness owns tools and permissions; SuperQode hosts its JSON-RPC stream.",
            "Set DSH_PERMISSION_MODE in runtime config env to choose workspace-write "
            "or danger-full-access.",
            "Composition is owned by the runtime's cordis.yml, not by the HarnessSpec.",
            "Unknown notifications are preserved as dsh_event for forward compatibility.",
        ),
    )

    def __init__(self, *, harness_factory: HarnessFactory | None = None) -> None:
        self._harness_factory = harness_factory or _default_harness_factory
        self._active: dict[str, Any] = {}

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        events = [event async for event in self._events(request)]
        usage = _accumulate_usage(events)
        stopped_reason, error = _outcome(events)
        response = AgentResponse(
            content=_final_response(events),
            messages=[],
            tool_calls_made=sum(event.type == "tool_call" for event in events),
            iterations=max(1, sum(event.type == "turn_complete" for event in events)),
            stopped_reason=stopped_reason,
            error=error,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime="dsh_jsonrpc",
            metadata={
                "events": events,
                "dsh_usage": usage,
                "dsh_session_id": next(
                    (event.session_id for event in events if event.session_id), None
                ),
            },
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        async for event in self._events(request):
            yield event

    async def cancel(self, session_id: str) -> None:
        await asyncio.to_thread(self._close_session, session_id)

    def _close_session(self, session_id: str) -> None:
        with _RUNTIMES_LOCK:
            keys = [key for key in _RUNTIMES if key[0] == session_id]
            harnesses = [_RUNTIMES.pop(key) for key in keys]
        for harness in harnesses:
            try:
                harness.close()
            except Exception:
                pass

    async def _events(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        settings = DSHSettings.from_request(request)
        session_id = request.session_id or f"session-{uuid.uuid4().hex}"
        key = (session_id, str(request.working_directory))
        try:
            harness = await asyncio.to_thread(self._runtime_for, key, request, settings)
            stream = _stream_session(
                harness,
                _runtime_session_id(session_id),
                request.prompt,
                settings,
            )
            async for event in stream:
                # Emit SuperQode's session id, not the process-scoped wire id.
                yield replace(event, session_id=session_id)
        except Exception as exc:
            # A broken runtime must not be reused by the next turn.
            await asyncio.to_thread(self._close_session, session_id)
            yield HarnessEvent(
                type="error",
                # Some transport exceptions carry no message; the type is then
                # the only thing that tells the user what broke.
                data={"error": str(exc) or type(exc).__name__, "exception": type(exc).__name__},
                session_id=session_id,
            )

    def _runtime_for(
        self,
        key: tuple[str, str],
        request: HarnessBackendRequest,
        settings: DSHSettings,
    ) -> Any:
        """Return the live runtime for this session, starting one when needed."""
        with _RUNTIMES_LOCK:
            existing = _RUNTIMES.get(key)
            if existing is not None:
                return existing
        harness = self._harness_factory(request, settings)
        try:
            harness.start()
        except BaseException:
            # start() spawns before it handshakes, so a failure here can leave a
            # live subprocess that nothing else holds a reference to.
            try:
                harness.close()
            except Exception:
                pass
            raise
        with _RUNTIMES_LOCK:
            racing = _RUNTIMES.get(key)
            if racing is not None:
                harness.close()
                return racing
            _RUNTIMES[key] = harness
        return harness


async def _stream_session(
    harness: Any,
    session_id: str,
    prompt: str,
    settings: DSHSettings,
) -> AsyncIterator[HarnessEvent]:
    """Yield normalized events for one owned prompt-to-idle interval."""
    client = harness.client
    subscription = client.subscribe_session_notifications(session_id)
    try:
        message_id = await asyncio.to_thread(
            client.session_prompt,
            session_id,
            [{"type": "text", "text": prompt}],
            notification_subscription=subscription,
        )
        deadline = asyncio.get_running_loop().time() + settings.prompt_timeout_seconds
        received = False
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                yield HarnessEvent(
                    type="error",
                    data={
                        "error": (
                            f"DeepSeek Harness run exceeded "
                            f"{settings.prompt_timeout_seconds}s without reaching idle"
                        ),
                        "exception": "TimeoutError",
                    },
                    session_id=session_id,
                )
                return
            try:
                notification = await asyncio.wait_for(
                    asyncio.to_thread(subscription.next),
                    timeout=remaining,
                )
            except TimeoutError:
                continue
            # The SDK owns the run interval from this prompt's durable inbox
            # receipt, so earlier queued traffic is not attributed to it.
            if not received:
                if not _is_inbox_receipt(notification, session_id, message_id):
                    continue
                received = True
            yield from_dsh_notification(notification.method, notification.payload)
            if _is_session_idle(notification, session_id):
                return
    finally:
        subscription.close()


def from_dsh_notification(method: str, payload: Mapping[str, Any]) -> HarnessEvent:
    """Normalize one DeepSeek Harness notification, retaining the full payload."""
    session_id = payload.get("sessionId")
    session_id = session_id if isinstance(session_id, str) else None
    base: dict[str, Any] = {
        "dsh_notification": {"method": method, "params": dict(payload)},
        "source_method": method,
    }
    if method == "session.status":
        status = payload.get("status")
        event_type = {"running": "start", "idle": "end"}.get(str(status), "status")
        return HarnessEvent(
            type=event_type,
            data={**base, "status": status},
            session_id=session_id,
        )
    if method == "session.event":
        event = payload.get("event")
        if isinstance(event, Mapping):
            return _from_session_event(event, base, session_id)
    if method in {"subagent.started", "subagent.finished"}:
        return HarnessEvent(
            type="subagent",
            data={
                **base,
                "phase": "started" if method.endswith("started") else "finished",
                "parent_session_id": payload.get("parentSessionId"),
                "child_session_id": payload.get("childSessionId"),
            },
            session_id=session_id,
        )
    return HarnessEvent(type="dsh_event", data=base, session_id=session_id)


def _from_session_event(
    event: Mapping[str, Any],
    base: dict[str, Any],
    session_id: str | None,
) -> HarnessEvent:
    event_type = str(event.get("type") or "")
    data = event.get("data")
    data = dict(data) if isinstance(data, Mapping) else {}
    base = {**base, "dsh_event_type": event_type, "seq": event.get("seq")}

    if event_type == "assistant/chunk":
        return _from_assistant_chunk(data, base, session_id)
    if event_type == "tool/call":
        return HarnessEvent(
            type="tool_call",
            data={
                **base,
                "tool_call_id": data.get("callId"),
                "name": data.get("name"),
                "arguments": data.get("arguments"),
            },
            session_id=session_id,
        )
    if event_type == "tool/result":
        text, is_error, call_id = _tool_result(data)
        return HarnessEvent(
            type="tool_result",
            data={
                **base,
                "tool_call_id": call_id,
                "result": text,
                "is_error": is_error,
            },
            session_id=session_id,
        )
    if event_type == "turn/start":
        return HarnessEvent(
            type="turn_start",
            data={**base, "turn": data.get("turn")},
            session_id=session_id,
        )
    if event_type == "turn/end":
        reason = data.get("reason")
        reason = reason if isinstance(reason, Mapping) else {}
        message, code = _failure(reason.get("error"))
        return HarnessEvent(
            type="turn_complete",
            data={
                **base,
                "turn": data.get("turn"),
                "reason": reason.get("kind"),
                # A failed turn carries its cause here rather than in a separate
                # error notification, so dropping it loses the only explanation.
                "error": message,
                "error_code": code,
            },
            session_id=session_id,
        )
    if event_type == "assistant/message":
        message = data.get("message")
        message = message if isinstance(message, Mapping) else {}
        return HarnessEvent(
            type="message",
            data={
                **base,
                "role": message.get("role"),
                "text": _message_text(message),
                "usage": _usage(data.get("usage")),
            },
            session_id=session_id,
        )
    if event_type in {"request/header", "request/context"}:
        return HarnessEvent(
            type="model_request",
            data={**base, "provider": data.get("provider"), "model": data.get("model")},
            session_id=session_id,
        )
    return HarnessEvent(type="dsh_event", data=base, session_id=session_id)


def _from_assistant_chunk(
    data: Mapping[str, Any],
    base: dict[str, Any],
    session_id: str | None,
) -> HarnessEvent:
    chunk = data.get("chunk")
    chunk = chunk if isinstance(chunk, Mapping) else {}
    kind = str(chunk.get("type") or "")
    base = {**base, "chunk_type": kind}
    if kind == "text-delta":
        return HarnessEvent(
            type="model_delta",
            data={**base, "text": str(chunk.get("text") or "")},
            session_id=session_id,
        )
    if kind == "reasoning-delta":
        return HarnessEvent(
            type="thinking_delta",
            data={**base, "text": str(chunk.get("text") or "")},
            session_id=session_id,
        )
    if kind == "tool-call-delta":
        return HarnessEvent(
            type="tool_delta",
            data={
                **base,
                "tool_call_id": chunk.get("id"),
                "name": chunk.get("name"),
                "arguments_delta": chunk.get("argumentsDelta"),
            },
            session_id=session_id,
        )
    if kind == "usage":
        return HarnessEvent(
            type="usage",
            data={**base, "usage": _usage(chunk.get("usage"))},
            session_id=session_id,
        )
    if kind == "finish":
        reason = chunk.get("reason")
        reason = reason if isinstance(reason, Mapping) else {}
        if reason.get("kind") == "error":
            # The closing turn/end repeats this failure and is the authoritative
            # record, so this stays a detail event: emitting a second 'error'
            # made the TUI print the same message twice.
            message, code = _failure(reason.get("failure"))
            return HarnessEvent(
                type="model_failure",
                data={**base, "error": message, "error_code": code},
                session_id=session_id,
            )
    return HarnessEvent(type="dsh_event", data=base, session_id=session_id)


def dsh_installation_status() -> tuple[bool, str]:
    """Return whether the DeepSeek Harness SDK is importable and why not."""
    if importlib.util.find_spec("deepseek_harness") is None:
        return (
            False,
            f"DeepSeek Harness SDK is not installed; run {install_command(DSH_BACKEND_NAME)}",
        )
    if importlib.util.find_spec("deepseek_harness_runtime") is None:
        return (
            False,
            "deepseek-harness-runtime-bin is missing; the platform wheel ships only "
            "macOS arm64 and Linux x86_64/aarch64",
        )
    return True, ""


def _default_harness_factory(request: HarnessBackendRequest, settings: DSHSettings) -> Any:
    available, issue = dsh_installation_status()
    if not available:
        raise RuntimeError(issue)

    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig

    return DeepSeekHarness(
        DeepSeekHarnessConfig(
            provider=settings.provider,
            model=settings.model,
            max_tokens=settings.max_tokens,
            cwd=str(request.working_directory),
            session_root=settings.session_root,
            cordis=settings.cordis,
            env=dict(settings.env or {}),
            runtime_bin=settings.runtime_bin,
            request_timeout_seconds=settings.request_timeout_seconds,
            shutdown_timeout_seconds=settings.shutdown_timeout_seconds,
            base_url=settings.base_url,
            api_key=settings.api_key,
        )
    )


def _is_inbox_receipt(notification: Any, session_id: str, message_id: str) -> bool:
    """Return whether this notification is the durable receipt for our prompt."""
    if notification.method != "session.event":
        return False
    payload = notification.payload
    if payload.get("sessionId") != session_id:
        return False
    event = payload.get("event")
    if not isinstance(event, Mapping) or event.get("type") != "agent/inbox/spliced":
        return False
    data = event.get("data")
    inserted = data.get("inserted") if isinstance(data, Mapping) else None
    return isinstance(inserted, list) and any(
        isinstance(message, Mapping) and message.get("id") == message_id for message in inserted
    )


def _is_session_idle(notification: Any, session_id: str) -> bool:
    return (
        notification.method == "session.status"
        and notification.payload.get("sessionId") == session_id
        and notification.payload.get("status") == "idle"
    )


@dataclass(frozen=True, slots=True)
class _BridgedRoute:
    """A SuperQode route expressed as DeepSeek endpoint configuration."""

    model: str
    base_url: str
    api_key: str
    source: str


def _bridged_route(provider: str, model: str) -> _BridgedRoute | None:
    """Map a connected OpenAI-compatible SuperQode route onto DeepSeek config.

    DeepSeek's adapter speaks the OpenAI wire format, so a local or dynamic
    provider can be driven by repointing base_url rather than by renaming the
    route. Providers with their own wire format (Anthropic, Google) are left
    alone: bridging them would swap one confusing failure for another.
    """
    provider_id = (provider or "").strip().lower()
    model_id = (model or "").strip()
    if not provider_id or not model_id or provider_id == "deepseek-official":
        return None
    try:
        from ...providers.dynamic import provider_api_key, resolve_base_url, resolve_provider_def

        definition = resolve_provider_def(provider_id)
        if definition is None:
            return None
        local = (definition.deployment_mode or "") == "local"
        if not local and not definition.dynamic:
            return None
        base_url = resolve_base_url(definition)
        if not base_url:
            return None
        key = provider_api_key(definition)
    except Exception:
        # Route bridging is a convenience; provider lookup must never break a run.
        return None
    return _BridgedRoute(
        model=model_id,
        base_url=_openai_compatible_url(base_url),
        # DeepSeek requires a non-empty credential; keyless local servers ignore it.
        api_key=key or "superqode-local-placeholder",
        source=f"{provider_id}/{model_id}",
    )


def _openai_compatible_url(base: str) -> str:
    trimmed = base.rstrip("/")
    return trimmed if trimmed.endswith("/v1") else f"{trimmed}/v1"


def _failure(raw: Any) -> tuple[str, str]:
    """Extract a DeepSeek failure message and code."""
    if not isinstance(raw, Mapping):
        return "", ""
    return str(raw.get("message") or ""), str(raw.get("code") or "")


def _tool_result(data: Mapping[str, Any]) -> tuple[str, bool, Any]:
    message = data.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, list):
        return "", False, None
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "tool-result":
            continue
        parts = block.get("content")
        text = ""
        if isinstance(parts, list):
            text = "".join(
                str(part.get("text") or "")
                for part in parts
                if isinstance(part, Mapping) and part.get("type") == "text"
            )
        return text, bool(block.get("isError")), block.get("toolCallId")
    return "", False, None


def _message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, Mapping) and block.get("type") == "text"
    )


def _usage(raw: Any) -> dict[str, int]:
    """Map DeepSeek token counters onto SuperQode's snake_case names."""
    if not isinstance(raw, Mapping):
        return {}
    fields = {
        "inputTokens": "input_tokens",
        "outputTokens": "output_tokens",
        "cacheReadTokens": "cache_read_tokens",
        "cacheWriteTokens": "cache_write_tokens",
        "reasoningTokens": "reasoning_tokens",
    }
    usage = {
        name: int(raw[key])
        for key, name in fields.items()
        if isinstance(raw.get(key), (int, float))
    }
    if "input_tokens" in usage or "output_tokens" in usage:
        usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return usage


def _accumulate_usage(events: Sequence[HarnessEvent]) -> dict[str, int]:
    """Sum the committed per-step usage records.

    Only ``message`` events are counted: the streamed ``usage`` chunk repeats
    the same step totals, so counting both would double every run.
    """
    totals: dict[str, int] = {}
    for event in events:
        if event.type != "message":
            continue
        usage = event.data.get("usage")
        if not isinstance(usage, Mapping):
            continue
        for key, value in usage.items():
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value
    return totals


def _final_response(events: Sequence[HarnessEvent]) -> str:
    """Return the last committed assistant text, as the SDK defines it."""
    for event in reversed(events):
        if event.type == "message":
            text = str(event.data.get("text") or "")
            if text:
                return text
    return "".join(
        str(event.data.get("text") or "") for event in events if event.type == "model_delta"
    )


def _outcome(events: Sequence[HarnessEvent]) -> tuple[str, str | None]:
    """Return the stop reason and the explanation for a failed run.

    A failed DeepSeek turn reports its cause on ``turn/end`` rather than as a
    separate error notification, so both sources are consulted before giving up
    and reporting a failure with no message.
    """
    errors = [event for event in events if event.type == "error"]
    message = str(errors[-1].data.get("error") or "") if errors else ""
    stopped = "complete"
    for event in reversed(events):
        if event.type != "turn_complete":
            continue
        kind = event.data.get("reason")
        if not isinstance(kind, str) or not kind:
            continue
        stopped = "complete" if kind == "completed" else ("error" if "error" in kind else kind)
        message = message or str(event.data.get("error") or "")
        break
    if errors:
        stopped = "error"
    if stopped == "error" and not message:
        message = "DeepSeek Harness ended the turn with an error and no message"
    return stopped, message or None


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _resolve_optional_path(base: Path, value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return str(path.resolve() if path.is_absolute() else (base / path).resolve())


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _positive_float(value: Any, default: float) -> float:
    number = float(value) if value is not None else default
    if number <= 0:
        raise ValueError("DeepSeek Harness timeouts must be positive")
    return number


def _optional_positive_float(value: Any) -> float | None:
    return None if value is None else _positive_float(value, 0.0)


__all__ = [
    "DSH_BACKEND_NAME",
    "DSHHarnessBackend",
    "DSHSettings",
    "dsh_installation_status",
    "from_dsh_notification",
]
