"""Native Python bridge from HarnessSpec to Prime Agent's RPC process."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prime_agent_client import PrimeEvent, PrimeSession

from ...agent.loop import AgentResponse
from ..events import HarnessEvent
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult

PRIME_AGENT_BACKEND_NAME = "prime-agent"
SessionFactory = Callable[[HarnessBackendRequest, "PrimeAgentSettings"], PrimeSession]


@dataclass(frozen=True, slots=True)
class PrimeAgentSettings:
    """Resolved process and persistence settings for a single harness run."""

    command: tuple[str, ...] = ("prime-agent",)
    args: tuple[str, ...] = ()
    env: Mapping[str, str] | None = None
    resume: str | None = None
    continue_session: bool = False
    session_dir: Path | None = None
    persist_session: bool = True
    request_timeout: float = 30.0
    startup_timeout: float = 30.0
    prompt_timeout: float = 600.0
    check_version: bool = True

    @classmethod
    def from_request(cls, request: HarnessBackendRequest) -> "PrimeAgentSettings":
        nested = request.spec.runtime.config.get("prime_agent")
        raw = dict(nested) if isinstance(nested, dict) else dict(request.spec.runtime.config)
        command = _strings(raw.get("command")) or ("prime-agent",)
        session_dir_value = _text(raw.get("session_dir"))
        session_dir = (
            _resolve_path(request.working_directory, session_dir_value)
            if session_dir_value
            else request.working_directory / ".superqode" / "prime-agent" / "sessions"
        )
        environment = raw.get("env")
        env = (
            {str(key): str(value) for key, value in environment.items()}
            if isinstance(environment, Mapping)
            else None
        )
        return cls(
            command=command,
            args=_strings(raw.get("args")),
            env=env,
            resume=_text(raw.get("resume")),
            continue_session=bool(raw.get("continue_session", False)),
            session_dir=session_dir,
            persist_session=bool(raw.get("persist_session", True)),
            request_timeout=_positive_float(raw.get("request_timeout"), 30.0),
            startup_timeout=_positive_float(raw.get("startup_timeout"), 30.0),
            prompt_timeout=_positive_float(raw.get("prompt_timeout"), 600.0),
            check_version=bool(raw.get("check_version", True)),
        )


class PrimeAgentHarnessBackend:
    """Run Prime Agent through the native Python RPC client."""

    name = PRIME_AGENT_BACKEND_NAME
    capabilities = HarnessBackendCapabilities(
        backend=PRIME_AGENT_BACKEND_NAME,
        supports_coding=True,
        supports_no_tool=False,
        supports_streaming=True,
        supports_approvals=False,
        supports_sandbox=False,
        supports_shell=True,
        supports_mcp=False,
        supports_typed_output=False,
        supports_workflow_children=False,
        event_detail="rich",
        notes=(
            "Prime Agent owns tools and process permissions; SuperQode hosts its RPC stream.",
            "RPC records and unknown event fields are preserved for forward compatibility.",
        ),
    )

    def __init__(self, *, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory or _default_session_factory
        self._active: dict[str, PrimeSession] = {}

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        events = [event async for event in self._events(request)]
        text = "".join(
            str(event.data.get("text") or "") for event in events if event.type == "model_delta"
        )
        stats_event = next((event for event in reversed(events) if event.type == "usage"), None)
        stats = stats_event.data if stats_event is not None else {}
        tokens = stats.get("tokens") if isinstance(stats.get("tokens"), Mapping) else {}
        errors = [event for event in events if event.type == "error"]
        response = AgentResponse(
            content=text,
            messages=[],
            tool_calls_made=sum(event.type == "tool_call" for event in events),
            iterations=max(1, sum(event.type == "turn_complete" for event in events)),
            stopped_reason="error" if errors else "complete",
            error=str(errors[-1].data.get("error")) if errors else None,
            input_tokens=_integer(tokens.get("input")),
            output_tokens=_integer(tokens.get("output")),
            total_tokens=_integer(tokens.get("total")),
            cost_usd=_number(stats.get("cost")),
            cost_currency="USD" if stats.get("cost") is not None else None,
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime="prime_rpc",
            metadata={
                "events": events,
                "prime_state": _event_data(events, "prime_state"),
                "prime_stats": dict(stats),
            },
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        async for event in self._events(request):
            yield event

    async def cancel(self, session_id: str) -> None:
        session = self._active.get(session_id)
        if session is not None and session.running:
            await session.abort()

    async def _events(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        settings = PrimeAgentSettings.from_request(request)
        session = self._session_factory(request, settings)
        key = request.session_id or "default"
        self._active[key] = session
        try:
            async with session:
                state = await session.state()
                yield HarnessEvent(type="prime_state", data=dict(state))
                async for event in session.prompt_stream(
                    request.prompt,
                    timeout=settings.prompt_timeout,
                ):
                    yield from_prime_event(event)
                stats = await session.stats()
                yield HarnessEvent(type="usage", data=dict(stats))
        except Exception as exc:
            yield HarnessEvent(
                type="error",
                data={"error": str(exc), "exception": type(exc).__name__},
            )
        finally:
            self._active.pop(key, None)


def from_prime_event(event: PrimeEvent) -> HarnessEvent:
    """Normalize known events while retaining the complete Prime payload."""
    raw = dict(event.raw)
    base = {"prime_event": raw, "source_event": event.type}
    if event.type == "agent_start":
        return HarnessEvent(type="start", data=base)
    if event.type == "agent_end":
        return HarnessEvent(type="end", data=base)
    if event.type == "turn_start":
        return HarnessEvent(type="turn_start", data=base)
    if event.type == "turn_end":
        return HarnessEvent(type="turn_complete", data=base)
    if event.type == "message_update":
        update = raw.get("assistantMessageEvent")
        if isinstance(update, Mapping) and update.get("type") == "text_delta":
            return HarnessEvent(
                type="model_delta",
                data={
                    **base,
                    "text": str(update.get("delta") or ""),
                    "content_index": update.get("contentIndex"),
                },
            )
        if isinstance(update, Mapping) and update.get("type") == "thinking_delta":
            return HarnessEvent(
                type="thinking_delta",
                data={**base, "text": str(update.get("delta") or "")},
            )
    if event.type == "tool_execution_start":
        return HarnessEvent(
            type="tool_call",
            data={
                **base,
                "tool_call_id": raw.get("toolCallId"),
                "name": raw.get("toolName"),
                "arguments": raw.get("args"),
            },
        )
    if event.type == "tool_execution_update":
        return HarnessEvent(
            type="tool_update",
            data={
                **base,
                "tool_call_id": raw.get("toolCallId"),
                "name": raw.get("toolName"),
                "partial_result": raw.get("partialResult"),
            },
        )
    if event.type == "tool_execution_end":
        return HarnessEvent(
            type="tool_result",
            data={
                **base,
                "tool_call_id": raw.get("toolCallId"),
                "name": raw.get("toolName"),
                "result": raw.get("result"),
                "is_error": bool(raw.get("isError")),
            },
        )
    if event.type in {"extension_error", "protocol_error"}:
        return HarnessEvent(
            type="error",
            data={**base, "error": raw.get("error") or raw.get("message") or event.type},
        )
    return HarnessEvent(type="prime_event", data=base)


def prime_agent_installation_status(command: Sequence[str] = ("prime-agent",)) -> tuple[bool, str]:
    executable = command[0] if command else "prime-agent"
    if shutil.which(executable) is None:
        return False, f"{executable!r} is not installed or is not on PATH"
    return True, ""


def _default_session_factory(
    request: HarnessBackendRequest,
    settings: PrimeAgentSettings,
) -> PrimeSession:
    return PrimeSession(
        cwd=request.working_directory,
        provider=request.provider or None,
        model=request.model or None,
        command=settings.command,
        args=settings.args,
        env=settings.env,
        resume=settings.resume,
        continue_session=settings.continue_session,
        session_dir=settings.session_dir,
        persist_session=settings.persist_session,
        request_timeout=settings.request_timeout,
        startup_timeout=settings.startup_timeout,
        prompt_timeout=settings.prompt_timeout,
        check_version=settings.check_version,
        ui_handler=lambda _event: {"cancelled": True},
    )


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    return ()


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _positive_float(value: Any, default: float) -> float:
    number = float(value) if value is not None else default
    if number <= 0:
        raise ValueError("Prime Agent timeouts must be positive")
    return number


def _integer(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _event_data(events: list[HarnessEvent], event_type: str) -> dict[str, Any]:
    event = next((item for item in events if item.type == event_type), None)
    return dict(event.data) if event is not None else {}


__all__ = [
    "PRIME_AGENT_BACKEND_NAME",
    "PrimeAgentHarnessBackend",
    "PrimeAgentSettings",
    "from_prime_event",
    "prime_agent_installation_status",
]
