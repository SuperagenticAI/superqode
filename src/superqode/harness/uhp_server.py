"""Native Unified Harness Protocol server for SuperQode.

Exposes one configured SuperQode HarnessSpec as a UHP-speaking harness. This is
a *native* UHP server (Path A), complementary to HarnessRouter: SuperQode's own
harness bind speaks the wire format directly, rather than wrapping Codex/Claude
as a multi-backend runner.

Serves UHP ``2026-09-12`` and ``2026-08-11``. Passes the conformance suite at
class ``core``. Session listing is served where the bind is not shared; file
artifacts are not implemented, so the class stays ``core``.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from fastapi import Request as FastAPIRequest
except Exception:  # pragma: no cover - optional at import time
    FastAPIRequest = Any  # type: ignore[misc,assignment]

from superqode.harness.uhp_client import (
    PROVIDER_KEY_HEADER,
    UHP_PROTOCOL_VERSION,
    UHP_SUPPORTED_VERSIONS,
    VERSION_HEADER,
)

#: Default protocol version: what a caller gets when it names none.
SUPPORTED_VERSION = UHP_PROTOCOL_VERSION

#: Every version served, newest first. 2026-09-12 is additive to 2026-08-11,
#: so both answer from one code path and only the echoed header differs.
SUPPORTED_VERSIONS: tuple[str, ...] = UHP_SUPPORTED_VERSIONS

#: Discovery document object type.
DISCOVERY_OBJECT = "uhp.discovery"

IDEMPOTENCY_HEADER = "Idempotency-Key"

#: Runtime controls, not caller context. A request body may not set these.
RESERVED_METADATA_KEYS = frozenset(
    {
        "agent_max_iterations",
        "delegation_depth",
        "harness_digest",
        "harness_source",
        "provider_api_key",
    }
)

#: Guards the caller key in os.environ, which the whole process shares.
_PROVIDER_ENV_LOCK = asyncio.Lock()

HarnessRunner = Callable[["UHPRunRequest"], Awaitable["UHPRunResult"]]


class MissingUHPServerDependency(RuntimeError):
    """Serving UHP needs the `uhp` extra; the client does not."""


@dataclass(frozen=True)
class UHPRunRequest:
    """Inputs handed to the bound harness runner."""

    prompt: str
    model: str
    provider: str
    working_directory: Path
    session_id: str
    response_id: str
    previous_response_id: str | None = None
    instructions: str | None = None
    max_output_tokens: int | None = None
    max_step: int | None = None
    timeout_seconds: int | None = None
    cancel_event: asyncio.Event | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UHPRunResult:
    """Normalized outcome from one harness turn."""

    text: str = ""
    model: str = ""
    status: str = "completed"  # completed | failed | cancelled | incomplete
    error_type: str = "harness_error"
    error_code: str = "harness_error"
    error_message: str | None = None
    usage: dict[str, int] | None = None
    output_items: tuple[dict[str, Any], ...] = ()


# AgentLoop (and most harness backends) return these on AgentResponse.stopped_reason
# instead of raising. Empty content with stopped_reason="error" is a failed turn.
_FAILED_STOPS = frozenset({"error", "blocked", "loop_detected"})
_CANCELLED_STOPS = frozenset({"cancelled"})
_INCOMPLETE_STOPS = frozenset({"needs_approval", "max_iterations"})


def _usage_from_harness_result(result: Any) -> dict[str, int] | None:
    tokens_in = getattr(result, "tokens_in", None)
    tokens_out = getattr(result, "tokens_out", None)
    if tokens_in is None and tokens_out is None:
        return None
    return {
        "input_tokens": int(tokens_in or 0),
        "output_tokens": int(tokens_out or 0),
        "total_tokens": int(getattr(result, "total_tokens", None) or 0),
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def uhp_result_from_harness_run(result: Any, *, model: str = "") -> UHPRunResult:
    """Map a HarnessRunResult onto the UHP response status.

    Provider failures are often returned as ``stopped_reason="error"`` with
    empty content rather than an exception. Those must be UHP ``failed``, not
    an empty ``completed`` response.
    """
    response = getattr(result, "response", None)
    stopped = str(getattr(response, "stopped_reason", "") or "")
    error = getattr(response, "error", None)
    text = str(getattr(result, "content", None) or "")
    resolved_model = model or str(getattr(response, "model", "") or "")
    usage = _usage_from_harness_result(result)

    if stopped in _CANCELLED_STOPS:
        return UHPRunResult(status="cancelled", model=resolved_model, usage=usage)
    if stopped in _INCOMPLETE_STOPS:
        reason = (
            str(error).strip()
            if error
            else ("Approval required." if stopped == "needs_approval" else stopped)
        )
        return UHPRunResult(
            text=text,
            model=resolved_model,
            status="incomplete",
            error_message=reason,
            usage=usage,
        )
    if stopped in _FAILED_STOPS or error:
        message = str(error).strip() if error else (text.strip() or "Harness run failed.")
        return UHPRunResult(
            text=text,
            model=resolved_model,
            status="failed",
            error_code="harness_error",
            error_message=message,
            usage=usage,
        )
    return UHPRunResult(
        text=text,
        model=resolved_model,
        status="completed",
        usage=usage,
    )


@dataclass
class UHPServerConfig:
    """Runtime settings for the native UHP server."""

    harness_id: str = "chrn_superqode"
    harness_name: str = "SuperQode"
    harness_base: str = "superqode"
    harness_base_label: str = "SuperQode"
    default_model: str = ""
    provider: str = "openai"
    model: str = ""
    working_directory: Path = field(default_factory=Path.cwd)
    api_key: str | None = None
    implementation_name: str = "superqode"
    implementation_version: str = ""
    #: Backed by a suite run, which is the only claim the spec recognises.
    conformance_class: str = "core"
    #: GET catalog without a bearer (remote public host). POST still requires api_key.
    public_catalog: bool = False
    #: Refuse a harness turn unless the caller sent PROVIDER_KEY_HEADER.
    require_caller_provider_key: bool = False
    #: Per-session directory under working_directory, so callers on a shared
    #: bind cannot read each other's files. Off locally: work in the project.
    isolate_session_workspaces: bool = False
    #: Serve session listing. Off on a shared bind: one bearer for every
    #: caller would make a list everyone's prompts.
    expose_session_listing: bool = True


def _package_version() -> str:
    try:
        from superqode import __version__

        return __version__
    except Exception:
        return "0.0.0"


def _provider_key_envs(provider: str) -> tuple[str, ...]:
    """Every env var LiteLLM may read for this provider (caller BYOK).

    All of them, not just the first: which one LiteLLM reads is its choice,
    and Google alone has two.
    """
    try:
        from superqode.providers.registry import PROVIDERS

        pdef = PROVIDERS.get(provider)
        names = tuple(str(name) for name in (getattr(pdef, "env_vars", None) or ()) if name)
        if names:
            return names
    except Exception:
        pass
    return (f"{(provider or 'OPENAI').upper()}_API_KEY",)


@asynccontextmanager
async def _caller_provider_key(token: str, env_names: Sequence[str]) -> AsyncIterator[None]:
    """Hold one caller's model key in ``os.environ`` for the length of a turn.

    Serialises BYOK turns: the environment is process-global, so overlapping
    turns would otherwise send each other's key.
    """
    if not token:
        yield
        return
    async with _PROVIDER_ENV_LOCK:
        previous = {name: os.environ.get(name) for name in env_names}
        for name in env_names:
            os.environ[name] = token
        try:
            yield
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _caller_metadata(body: Mapping[str, Any]) -> dict[str, Any]:
    """Caller-supplied metadata with the runtime's own control keys removed."""
    raw = body.get("metadata")
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(key): value
        for key, value in raw.items()
        if str(key) not in RESERVED_METADATA_KEYS and not str(key).startswith("_")
    }


def harness_id_from_name(name: str) -> str:
    """Build a ``chrn_…`` id from a harness/spec name."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "superqode").lower()).strip("_")
    slug = slug or "superqode"
    if not slug.startswith("chrn_"):
        slug = f"chrn_{slug}"
    return slug[:64]


def _error_envelope(
    *,
    error_type: str,
    code: str,
    message: str,
    param: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "type": error_type,
            "code": code,
            "message": message,
            "param": param,
            "detail": dict(detail) if detail is not None else None,
        }
    }


def _extract_prompt(input_value: Any) -> str:
    """Collapse UHP ``input`` (string or message array) to a prompt string."""
    if isinstance(input_value, str):
        return input_value
    if not isinstance(input_value, Sequence):
        return ""
    parts: list[str] = []
    for item in input_value:
        if not isinstance(item, Mapping):
            continue
        # Bare text parts or message objects with content arrays.
        if item.get("type") == "input_text" and item.get("text"):
            parts.append(str(item["text"]))
            continue
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
            continue
        if isinstance(content, Sequence):
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                if part.get("type") in {"input_text", "text", "output_text"} and part.get("text"):
                    parts.append(str(part["text"]))
                elif part.get("text"):
                    parts.append(str(part["text"]))
        elif item.get("text"):
            parts.append(str(item["text"]))
    return "\n".join(parts).strip()


def _message_output(text: str, *, item_id: str | None = None) -> dict[str, Any]:
    return {
        "id": item_id or f"msg_{uuid.uuid4().hex[:12]}",
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _response_payload(
    *,
    response_id: str,
    status: str,
    model: str,
    output: Sequence[Mapping[str, Any]],
    created_at: int,
    previous_response_id: str | None,
    session_id: str,
    harness_id: str,
    store: bool = True,
    usage: Mapping[str, int] | None = None,
    error: Mapping[str, Any] | None = None,
    ignored_fields: Sequence[str] = (),
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # tasks §1.2: a request that names no harness MUST be told which one ran.
    metadata: dict[str, Any] = {"session_id": session_id, "harness_id": harness_id}
    if ignored_fields:
        metadata["ignored_fields"] = list(ignored_fields)
    if extra_metadata:
        metadata.update(dict(extra_metadata))
    payload: dict[str, Any] = {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": status,
        "error": dict(error) if error else None,
        "incomplete_details": None,
        "previous_response_id": previous_response_id,
        "model": model,
        "output": [dict(item) for item in output],
        "store": store,
        "usage": dict(usage) if usage is not None else None,
        "metadata": metadata,
    }
    return payload


class UHPServer:
    """FastAPI application that serves one SuperQode harness over UHP."""

    def __init__(
        self,
        config: UHPServerConfig,
        *,
        runner: HarnessRunner | None = None,
        spec: Any | None = None,
    ) -> None:
        self.config = config
        if not config.implementation_version:
            config.implementation_version = _package_version()
        self._runner = runner or self._default_runner
        self._spec = spec
        self._responses: dict[str, dict[str, Any]] = {}
        self._input_items: dict[str, list[dict[str, Any]]] = {}
        self._idempotency: dict[str, str] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._created_at_ms = int(time.time() * 1000)
        self.app = self._build_app()

    # -- public helpers ---------------------------------------------------------

    def harness_document(self) -> dict[str, Any]:
        model = self.config.default_model or self.config.model or "server-default"
        return {
            "id": self.config.harness_id,
            "object": "harness",
            "name": self.config.harness_name,
            "base": self.config.harness_base,
            "baseLabel": self.config.harness_base_label,
            "defaultModel": model,
            "disabledTools": [],
            "maxStep": None,
            "timeoutSeconds": None,
            "createdAt": self._created_at_ms,
        }

    def discovery_document(self) -> dict[str, Any]:
        return {
            "object": DISCOVERY_OBJECT,
            "protocol": "uhp",
            "versions": list(SUPPORTED_VERSIONS),
            "default_version": SUPPORTED_VERSION,
            "conformance_class": self.config.conformance_class,
            "capabilities": {
                "streaming": True,
                "sessions": True,
                "cancellation": True,
                "files_input": False,
                "files_output": False,
                "session_listing": self.config.expose_session_listing,
                "harness_management": False,
                "session_sharing": False,
                "idempotency": True,
                # 2026-09-12 adds plugins. Reported false, not omitted: a
                # client must be able to tell "not supported" from "older
                # than this field". `plugin_schemas` belongs to a server that
                # answers true, so it stays off the document.
                "plugins": False,
            },
            "implementation": {
                "name": self.config.implementation_name,
                "version": self.config.implementation_version or _package_version(),
                "harness": self.config.harness_id,
            },
        }

    def run(self, host: str = "127.0.0.1", port: int = 8787) -> None:
        import uvicorn

        uvicorn.run(self.app, host=host, port=port, log_level="info")

    # -- FastAPI app ------------------------------------------------------------

    def _build_app(self) -> Any:
        try:
            from fastapi import FastAPI
            from fastapi.responses import JSONResponse, StreamingResponse
        except ModuleNotFoundError as exc:  # pragma: no cover - install-shape error
            raise MissingUHPServerDependency(
                "Serving UHP needs FastAPI and uvicorn, which are not installed.\n"
                "  uv tool install 'superqode[uhp]'   (if you installed the CLI as a tool)\n"
                "  uv pip install 'superqode[uhp]'    (inside a virtual environment)\n"
                "The UHP client works without them."
            ) from exc

        app = FastAPI(
            title="SuperQode UHP Server",
            version=self.config.implementation_version or _package_version(),
            docs_url=None,
            redoc_url=None,
        )
        server = self

        @app.middleware("http")
        async def uhp_headers(request: FastAPIRequest, call_next):  # type: ignore[no-untyped-def]
            negotiated = server._negotiate_version(request.headers.get(VERSION_HEADER))
            if isinstance(negotiated, dict):
                return JSONResponse(
                    status_code=400,
                    content=negotiated,
                    headers={VERSION_HEADER: SUPPORTED_VERSION},
                )
            # Discovery (and optional catalog GETs) stay unauthenticated.
            if not server._is_public_request(request.method, request.url.path):
                auth_error = server._check_auth(request.headers.get("authorization"))
                if auth_error is not None:
                    return JSONResponse(
                        status_code=401,
                        content=auth_error,
                        headers={VERSION_HEADER: negotiated},
                    )
            response = await call_next(request)
            # The version actually served, which is the one the caller asked for.
            response.headers[VERSION_HEADER] = negotiated
            return response

        @app.get("/v1/uhp")
        async def get_discovery() -> dict[str, Any]:
            return server.discovery_document()

        @app.get("/v1/harnesses")
        async def list_harnesses() -> dict[str, Any]:
            return {"harnesses": [server.harness_document()]}

        @app.get("/v1/harnesses/{harness_id}")
        async def get_harness(harness_id: str) -> Any:
            if harness_id != server.config.harness_id:
                return JSONResponse(
                    status_code=404,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="harness_not_found",
                        message=f"No harness with id '{harness_id}'.",
                        param="harness_id",
                    ),
                )
            return server.harness_document()

        @app.get("/v1/models")
        async def list_models() -> dict[str, Any]:
            model_id = server.config.default_model or server.config.model or "server-default"
            return {
                "backends": {
                    server.config.harness_base: {
                        "default": model_id,
                        "models": [
                            {
                                "id": model_id,
                                "label": model_id,
                                "backend": server.config.harness_base,
                                "available": True,
                                "default": True,
                            }
                        ],
                    }
                }
            }

        @app.get("/v1/harnesses/{harness_id}/models")
        async def list_harness_models(harness_id: str) -> Any:
            if harness_id != server.config.harness_id:
                return JSONResponse(
                    status_code=404,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="harness_not_found",
                        message=f"No harness with id '{harness_id}'.",
                        param="harness_id",
                    ),
                )
            model_id = server.config.default_model or server.config.model or "server-default"
            return {
                "harness_id": harness_id,
                "backend": server.config.harness_base,
                "default": model_id,
                "fallback": "",
                "models": [
                    {
                        "id": model_id,
                        "label": model_id,
                        "backend": server.config.harness_base,
                        "available": True,
                        "default": True,
                    }
                ],
            }

        @app.post("/v1/responses")
        async def create_response(http_request: FastAPIRequest) -> Any:
            try:
                body = await http_request.json()
            except Exception:
                return JSONResponse(
                    status_code=400,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="invalid_input",
                        message="Request body must be JSON.",
                    ),
                )
            if not isinstance(body, dict):
                return JSONResponse(
                    status_code=400,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="invalid_input",
                        message="Request body must be a JSON object.",
                    ),
                )
            if "input" not in body:
                return JSONResponse(
                    status_code=400,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="invalid_input",
                        message="Field 'input' is required.",
                        param="input",
                    ),
                )

            idempotency_key = (http_request.headers.get(IDEMPOTENCY_HEADER) or "").strip()
            if idempotency_key and idempotency_key in server._idempotency:
                existing_id = server._idempotency[idempotency_key]
                existing = server._responses.get(existing_id)
                if existing is not None:
                    if body.get("stream"):
                        return StreamingResponse(
                            server._replay_stream(existing),
                            media_type="text/event-stream",
                            headers={VERSION_HEADER: SUPPORTED_VERSION},
                        )
                    # tasks §6: a repeated key waits for the first run and
                    # returns its result. Handing back an in-flight record
                    # would make a retry look like a finished, empty task.
                    if not body.get("background"):
                        await server._await_response(existing_id)
                    return server._responses.get(existing_id, existing)

            harness_error = server._validate_harness_selection(body)
            if harness_error is not None:
                status, envelope = harness_error
                return JSONResponse(status_code=status, content=envelope)

            provider_api_key = (http_request.headers.get(PROVIDER_KEY_HEADER) or "").strip()
            if server.config.require_caller_provider_key and not provider_api_key:
                return JSONResponse(
                    status_code=403,
                    content=_error_envelope(
                        error_type="permission_error",
                        code="missing_provider_key",
                        message=(
                            f"Harness turns on this host require header '{PROVIDER_KEY_HEADER}' "
                            "(your provider key). SuperQode does not attach a model key."
                        ),
                        param=PROVIDER_KEY_HEADER,
                    ),
                )

            stream = bool(body.get("stream"))
            started = await server._start_response(
                body,
                idempotency_key=idempotency_key or None,
                provider_api_key=provider_api_key or None,
            )
            if isinstance(started, tuple):
                status, envelope = started
                return JSONResponse(status_code=status, content=envelope)
            record = started
            if stream:
                return StreamingResponse(
                    server._stream_events(record["id"]),
                    media_type="text/event-stream",
                    headers={VERSION_HEADER: SUPPORTED_VERSION},
                )
            if body.get("background"):
                # Accepted and running; the caller follows it by id.
                return record
            await server._await_response(record["id"])
            return server._responses.get(record["id"], record)

        @app.get("/v1/responses/{response_id}")
        async def get_response(response_id: str) -> Any:
            record = server._responses.get(response_id)
            if record is None:
                return JSONResponse(
                    status_code=404,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="response_not_found",
                        message=f"No response with id '{response_id}'.",
                        param="response_id",
                    ),
                )
            return record

        @app.get("/v1/responses/{response_id}/input_items")
        async def get_input_items(response_id: str) -> Any:
            if response_id not in server._responses:
                return JSONResponse(
                    status_code=404,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="response_not_found",
                        message=f"No response with id '{response_id}'.",
                        param="response_id",
                    ),
                )
            return {
                "object": "list",
                "data": list(server._input_items.get(response_id, [])),
            }

        @app.post("/v1/responses/{response_id}/cancel")
        async def cancel_response(response_id: str) -> Any:
            record = server._responses.get(response_id)
            if record is None:
                return JSONResponse(
                    status_code=404,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="response_not_found",
                        message=f"No response with id '{response_id}'.",
                        param="response_id",
                    ),
                )
            # Terminal already: cancel changes nothing and says so.
            if record.get("status") != "in_progress":
                return record
            await server._stop(response_id)
            record = server._responses.get(response_id, record)
            # _execute owns the terminal status. It only stays in_progress if
            # the run was never started, so name it cancelled here.
            if record.get("status") == "in_progress":
                record["status"] = "cancelled"
                record["error"] = None
            if record.get("status") == "cancelled":
                record["incomplete_details"] = {"reason": "cancelled"}
            return record

        @app.delete("/v1/responses/{response_id}")
        async def delete_response(response_id: str) -> Any:
            if response_id not in server._responses:
                return JSONResponse(
                    status_code=404,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="response_not_found",
                        message=f"No response with id '{response_id}'.",
                        param="response_id",
                    ),
                )
            # Deletion must not cancel running work.
            del server._responses[response_id]
            server._input_items.pop(response_id, None)
            return {"id": response_id, "deleted": True}

        def _listing_disabled() -> Any:
            return JSONResponse(
                status_code=404,
                content=_error_envelope(
                    error_type="invalid_request_error",
                    code="session_not_found",
                    message="This bind does not serve session listing.",
                ),
            )

        @app.get("/v1/sessions")
        async def list_sessions(limit: str = "20", cursor: str = "", harness: str = "") -> Any:
            # A string, so a bad value answers in the UHP error envelope.
            if not server.config.expose_session_listing:
                return _listing_disabled()
            try:
                requested = int(limit)
            except (TypeError, ValueError):
                return JSONResponse(
                    status_code=400,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="invalid_input",
                        # Truncated: it is echoed back to the caller.
                        message=f"Query parameter 'limit' must be an integer, got '{limit[:32]}'.",
                        param="limit",
                    ),
                )
            ordered = sorted(
                server._sessions.values(),
                key=lambda item: (-int(item.get("updated_at") or 0), str(item.get("id") or "")),
            )
            if harness:
                ordered = [s for s in ordered if str(s.get("harness_id") or "") == harness]
            start = 0
            if cursor:
                ids = [str(s.get("id") or "") for s in ordered]
                start = ids.index(cursor) + 1 if cursor in ids else len(ordered)
            size = max(1, min(requested, 100))
            page = ordered[start : start + size]
            # Explicit end marker: a short page does not mean the last one.
            remaining = ordered[start + size :]
            return {
                "sessions": [server._session_document(item) for item in page],
                "next_cursor": (str(page[-1].get("id")) if page and remaining else None),
            }

        @app.get("/v1/sessions/{session_id}")
        async def get_session(session_id: str) -> Any:
            if not server.config.expose_session_listing:
                return _listing_disabled()
            session = server._sessions.get(session_id)
            if session is None:
                return JSONResponse(
                    status_code=404,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="session_not_found",
                        message=f"No session with id '{session_id}'.",
                        param="session_id",
                    ),
                )
            return server._session_document(session)

        @app.get("/v1/sessions/{session_id}/turns")
        async def get_session_turns(session_id: str) -> Any:
            if not server.config.expose_session_listing:
                return _listing_disabled()
            session = server._sessions.get(session_id)
            if session is None:
                return JSONResponse(
                    status_code=404,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="session_not_found",
                        message=f"No session with id '{session_id}'.",
                        param="session_id",
                    ),
                )
            return {"object": "list", "turns": server._session_turns(session)}

        @app.post("/v1/sessions/{session_id}/cancel")
        async def cancel_session(session_id: str) -> Any:
            session = server._sessions.get(session_id)
            if session is None:
                return JSONResponse(
                    status_code=404,
                    content=_error_envelope(
                        error_type="invalid_request_error",
                        code="session_not_found",
                        message=f"No session with id '{session_id}'.",
                        param="session_id",
                    ),
                )
            for response_id in list(session.get("response_ids", [])):
                record = server._responses.get(response_id)
                if record is None or record.get("status") != "in_progress":
                    continue
                await server._stop(response_id)
                record = server._responses.get(response_id, record)
                if record.get("status") == "in_progress":
                    record["status"] = "cancelled"
                if record.get("status") == "cancelled":
                    record["incomplete_details"] = {"reason": "cancelled"}
            return {"id": session_id, "status": "cancelled"}

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok", "protocol": "uhp", "version": SUPPORTED_VERSION}

        return app

    # -- auth / version ---------------------------------------------------------

    def _is_public_request(self, method: str, path: str) -> bool:
        path = path.rstrip("/") or "/"
        if path in {"/v1/uhp", "/health", "/docs", "/openapi.json", "/redoc"}:
            return True
        if not self.config.public_catalog or method.upper() != "GET":
            return False
        if path in {"/v1/harnesses", "/v1/models"}:
            return True
        if path.startswith("/v1/harnesses/"):
            rest = path[len("/v1/harnesses/") :]
            return "/" not in rest or rest.endswith("/models")
        return False

    def _negotiate_version(self, requested: str | None) -> str | dict[str, Any]:
        """The version to answer at, or the error envelope refusing to."""
        if not requested or not requested.strip():
            return SUPPORTED_VERSION
        version = requested.strip()
        if version in SUPPORTED_VERSIONS:
            return version
        return _error_envelope(
            error_type="invalid_request_error",
            code="unsupported_protocol_version",
            message=f"Unsupported UHP-Version '{version}'.",
            param="UHP-Version",
            detail={"supported": list(SUPPORTED_VERSIONS)},
        )

    def _check_auth(self, authorization: str | None) -> dict[str, Any] | None:
        expected = self.config.api_key
        if not expected:
            return None
        if not authorization:
            return _error_envelope(
                error_type="authentication_error",
                code="missing_credential",
                message="Bearer credential required.",
            )
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return _error_envelope(
                error_type="authentication_error",
                code="invalid_credential",
                message="Authorization must be a Bearer token.",
            )
        # Bytes, because compare_digest rejects a non-ASCII str.
        if not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
            return _error_envelope(
                error_type="authentication_error",
                code="invalid_credential",
                message="Invalid API key.",
            )
        return None

    def _output_text(self, record: Mapping[str, Any]) -> str:
        """The assistant text of one response, in output order."""
        parts: list[str] = []
        for item in record.get("output") or ():
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, Sequence):
                continue
            for part in content:
                if isinstance(part, Mapping) and part.get("type") == "output_text":
                    parts.append(str(part.get("text") or ""))
        return "".join(parts)

    def _session_document(self, session: Mapping[str, Any]) -> dict[str, Any]:
        response_ids = list(session.get("response_ids") or ())
        latest = self._responses.get(response_ids[-1]) if response_ids else None
        created_at = int(session.get("created_at") or 0)
        return {
            "id": str(session.get("id") or ""),
            "object": "session",
            "harness_id": str(session.get("harness_id") or self.config.harness_id),
            "title": str(session.get("title") or ""),
            "status": str((latest or {}).get("status") or "in_progress"),
            "created_at": created_at,
            "updated_at": int(session.get("updated_at") or created_at),
        }

    def _session_turns(self, session: Mapping[str, Any]) -> list[dict[str, Any]]:
        """The ordered task history, so a client can rebuild a transcript."""
        turns: list[dict[str, Any]] = []
        for response_id in session.get("response_ids") or ():
            record = self._responses.get(response_id)
            if record is None:
                continue
            turn: dict[str, Any] = {
                "id": response_id,
                "status": str(record.get("status") or ""),
            }
            user = _extract_prompt(self._input_items.get(response_id))
            if user:
                turn["user"] = user
            assistant = self._output_text(record)
            if assistant:
                turn["assistant"] = assistant
            turns.append(turn)
        return turns

    def _workspace_for(self, session_id: str) -> Path:
        """The directory a turn runs in."""
        root = Path(self.config.working_directory)
        if not self.config.isolate_session_workspaces:
            return root
        workspace = root / "sessions" / session_id
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _validate_harness_selection(
        self, body: Mapping[str, Any]
    ) -> tuple[int, dict[str, Any]] | None:
        metadata = body.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        harness_id = metadata.get("harness_id")
        if harness_id and harness_id != self.config.harness_id:
            return (
                404,
                _error_envelope(
                    error_type="invalid_request_error",
                    code="harness_not_found",
                    message=f"No harness with id '{harness_id}'.",
                    param="metadata.harness_id",
                ),
            )
        return None

    # -- response lifecycle -----------------------------------------------------

    async def _start_response(
        self,
        body: Mapping[str, Any],
        *,
        idempotency_key: str | None,
        provider_api_key: str | None = None,
    ) -> dict[str, Any]:
        prompt = _extract_prompt(body.get("input"))
        previous_response_id = body.get("previous_response_id")
        previous_response_id = (
            str(previous_response_id) if previous_response_id is not None else None
        )

        session_id: str | None = None
        if previous_response_id:
            prior = self._responses.get(previous_response_id)
            if prior is None:
                # lifecycle §4: an expired session is a 404 a client can act
                # on. Starting a fresh one quietly loses the conversation it
                # asked to continue, and says nothing.
                return (
                    404,
                    _error_envelope(
                        error_type="invalid_request_error",
                        code="session_expired",
                        message=(
                            f"No response '{previous_response_id}' is retained, so the session "
                            "it belongs to cannot be continued."
                        ),
                        param="previous_response_id",
                    ),
                )
            else:
                meta = prior.get("metadata") if isinstance(prior.get("metadata"), Mapping) else {}
                session_id = str(meta.get("session_id") or "") or None
                busy = any(
                    self._responses.get(rid, {}).get("status") == "in_progress"
                    for rid in (self._sessions.get(session_id or "", {}) or {}).get(
                        "response_ids", []
                    )
                )
                if busy:
                    return (
                        409,
                        _error_envelope(
                            error_type="invalid_request_error",
                            code="session_busy",
                            message="A task is already running in this session.",
                            param="previous_response_id",
                        ),
                    )

        if not session_id:
            # architecture §3 fixes the session prefix as `hsess`.
            session_id = f"hsess{uuid.uuid4().hex[:16]}"

        response_id = f"resp_{uuid.uuid4().hex}"
        created_at = int(time.time())
        ignored: list[str] = []
        if body.get("tools") is not None:
            ignored.append("tools")
        if body.get("include") is not None:
            ignored.append("include")

        served = self.config.default_model or self.config.model or "server-default"
        requested_model = body.get("model")
        if requested_model and str(requested_model) != served:
            # tasks §1.3: refuse, or substitute and say so. Never report a
            # model that did not run. This bind serves exactly what it lists.
            return (
                422,
                _error_envelope(
                    error_type="invalid_request_error",
                    code="model_unavailable",
                    message=f"This harness cannot serve model '{requested_model}'.",
                    param="model",
                    detail={"available": [served], "requested": str(requested_model)},
                ),
            )
        model = str(requested_model or served)

        record = _response_payload(
            response_id=response_id,
            status="in_progress",
            model=model,
            output=[],
            created_at=created_at,
            previous_response_id=previous_response_id,
            session_id=session_id,
            harness_id=self.config.harness_id,
            store=bool(body.get("store", True)),
            ignored_fields=ignored,
        )
        self._responses[response_id] = record
        self._input_items[response_id] = self._normalize_input_items(body.get("input"))
        self._cancel_events[response_id] = asyncio.Event()
        session = self._sessions.setdefault(
            session_id,
            {
                "id": session_id,
                "harness_id": self.config.harness_id,
                "response_ids": [],
                "created_at": created_at,
                "title": prompt.strip().splitlines()[0][:80] if prompt.strip() else "",
            },
        )
        session["response_ids"].append(response_id)
        session["updated_at"] = created_at
        if idempotency_key:
            self._idempotency[idempotency_key] = response_id

        run_request = UHPRunRequest(
            prompt=prompt,
            model=model,
            provider=self.config.provider,
            working_directory=self._workspace_for(session_id),
            session_id=session_id,
            response_id=response_id,
            previous_response_id=previous_response_id,
            instructions=str(body["instructions"]) if body.get("instructions") else None,
            max_output_tokens=body.get("max_output_tokens"),
            max_step=body.get("max_step"),
            timeout_seconds=body.get("timeout_seconds"),
            cancel_event=self._cancel_events[response_id],
            metadata={
                "harness_id": self.config.harness_id,
                **_caller_metadata(body),
                **({"provider_api_key": provider_api_key} if provider_api_key else {}),
            },
        )

        task = asyncio.create_task(self._execute(response_id, run_request))
        self._tasks[response_id] = task
        return record

    def _normalize_input_items(self, input_value: Any) -> list[dict[str, Any]]:
        if isinstance(input_value, str):
            return [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": input_value}],
                }
            ]
        if isinstance(input_value, Sequence):
            return [dict(item) for item in input_value if isinstance(item, Mapping)]
        return []

    async def _await_response(self, response_id: str) -> None:
        """Wait for one run to settle, cancellation included."""
        task = self._tasks.get(response_id)
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            # The run was cancelled, not this caller: the record is terminal
            # and the caller still wants it. Anything else is our own
            # cancellation and has to keep travelling.
            if not task.cancelled():
                raise

    async def _stop(self, response_id: str) -> None:
        """Stop one running task and wait for it to actually be over."""
        event = self._cancel_events.get(response_id)
        if event is not None:
            event.set()
        task = self._tasks.get(response_id)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            if not task.cancelled():
                raise
        except Exception:
            # The run raised on its way out. The record already says so.
            pass

    async def _execute(self, response_id: str, request: UHPRunRequest) -> None:
        record = self._responses[response_id]
        try:
            if request.cancel_event and request.cancel_event.is_set():
                record["status"] = "cancelled"
                return
            if request.timeout_seconds:
                # tasks §1.1: stop at the budget and report incomplete. Work
                # truncated by a budget is never `completed`.
                try:
                    result = await asyncio.wait_for(
                        self._runner(request), timeout=float(request.timeout_seconds)
                    )
                except TimeoutError:
                    if request.cancel_event is not None:
                        request.cancel_event.set()
                    record["status"] = "incomplete"
                    record["incomplete_details"] = {"reason": "timeout"}
                    record["error"] = None
                    return
            else:
                result = await self._runner(request)
            if request.cancel_event and request.cancel_event.is_set():
                record["status"] = "cancelled"
                record["error"] = None
                return
            output = list(result.output_items) if result.output_items else []
            if not output and result.text:
                output = [_message_output(result.text)]
            record["output"] = output
            record["model"] = result.model or request.model
            record["usage"] = dict(result.usage) if result.usage is not None else None
            status = result.status or "completed"
            if status == "failed":
                record["status"] = "failed"
                record["error"] = {
                    "type": result.error_type or "harness_error",
                    "code": result.error_code or "harness_error",
                    "message": result.error_message or "Harness run failed.",
                    "param": None,
                    "detail": None,
                }
            elif status == "cancelled":
                record["status"] = "cancelled"
                record["error"] = None
            elif status == "incomplete":
                record["status"] = "incomplete"
                record["incomplete_details"] = {"reason": result.error_message or "incomplete"}
                record["error"] = None
            else:
                record["status"] = "completed"
                record["error"] = None
        except asyncio.CancelledError:
            record["status"] = "cancelled"
            record["error"] = None
            raise
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = {
                "type": "harness_error",
                "code": "harness_error",
                "message": "Harness run failed.",
                "param": None,
                "detail": {"error_type": type(exc).__name__},
            }
        finally:
            self._tasks.pop(response_id, None)

    async def _stream_events(self, response_id: str) -> AsyncIterator[str]:
        """Emit a minimal but valid SSE sequence for one response."""
        seq = 0

        def emit(event_type: str, data: dict[str, Any]) -> str:
            nonlocal seq
            payload = {"type": event_type, "sequence_number": seq, **data}
            seq += 1
            return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"

        record = self._responses[response_id]
        yield emit("response.created", {"response": dict(record)})
        yield emit("response.in_progress", {"response": dict(record)})

        await self._await_response(response_id)
        record = self._responses[response_id]
        text = ""
        for item in record.get("output") or ():
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, Sequence):
                continue
            for part in content:
                if isinstance(part, Mapping) and part.get("type") == "output_text":
                    text += str(part.get("text") or "")

        if text and record.get("status") == "completed":
            item_id = f"msg_{uuid.uuid4().hex[:12]}"
            yield emit(
                "response.output_item.added",
                {
                    "item": {
                        "id": item_id,
                        "type": "message",
                        "status": "in_progress",
                        "role": "assistant",
                        "content": [],
                    }
                },
            )
            # Chunk coarsely so clients exercise delta handling without
            # pretending token-level streaming from a finished run.
            chunk_size = max(24, len(text) // 8 or 24)
            for index in range(0, len(text), chunk_size):
                delta = text[index : index + chunk_size]
                yield emit(
                    "response.output_text.delta",
                    {"item_id": item_id, "delta": delta},
                )
            yield emit(
                "response.output_text.done",
                {"item_id": item_id, "text": text},
            )
            yield emit(
                "response.output_item.done",
                {"item": _message_output(text, item_id=item_id)},
            )

        terminal = {
            "completed": "response.completed",
            "failed": "response.failed",
            "incomplete": "response.incomplete",
            "cancelled": "response.incomplete",
        }.get(str(record.get("status")), "response.completed")
        # Spec: cancelled is its own status on the Response object; stream uses
        # incomplete/failed/completed terminals. Prefer completed/failed/incomplete.
        if record.get("status") == "cancelled":
            # Emit incomplete with cancelled details rather than inventing a
            # non-standard terminal event name.
            terminal = "response.incomplete"
        yield emit(terminal, {"response": dict(record)})

    async def _replay_stream(self, record: Mapping[str, Any]) -> AsyncIterator[str]:
        """Replay a finished (or in-flight) response as SSE for idempotent retries."""
        response_id = str(record["id"])
        if record.get("status") == "in_progress":
            async for chunk in self._stream_events(response_id):
                yield chunk
            return
        # Finished: synthesize the same terminal event.
        seq = 0

        def emit(event_type: str, data: dict[str, Any]) -> str:
            nonlocal seq
            payload = {"type": event_type, "sequence_number": seq, **data}
            seq += 1
            return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"

        yield emit("response.created", {"response": dict(record)})
        terminal = {
            "completed": "response.completed",
            "failed": "response.failed",
            "incomplete": "response.incomplete",
            "cancelled": "response.incomplete",
        }.get(str(record.get("status")), "response.completed")
        yield emit(terminal, {"response": dict(record)})

    # -- default runner ---------------------------------------------------------

    async def _default_runner(self, request: UHPRunRequest) -> UHPRunResult:
        """Run the bound HarnessSpec through HarnessKernel."""
        from superqode.harness.kernel import init_harness
        from superqode.harness.store import MemoryHarnessStore

        spec = self._spec
        if spec is None:
            from superqode.harness import get_harness_template

            spec = get_harness_template("coding")

        provider = request.provider
        model = request.model
        # Prefer explicit request model; fall back to config / spec primary.
        if not model or model == "server-default":
            primary = getattr(getattr(spec, "model_policy", None), "primary", None)
            if primary:
                model = str(primary)

        kernel = await init_harness(spec, store=MemoryHarnessStore())
        session = await kernel.session(request.session_id)
        if request.cancel_event and request.cancel_event.is_set():
            return UHPRunResult(status="cancelled", model=model)

        prompt = request.prompt
        if request.instructions:
            prompt = f"{request.instructions.rstrip()}\n\n{prompt}"

        run_metadata = {
            key: value for key, value in dict(request.metadata).items() if key != "provider_api_key"
        }
        # The request's budgets, in the keys the harness runtime reads.
        if request.max_step:
            run_metadata["agent_max_iterations"] = int(request.max_step)
        if request.max_output_tokens:
            run_metadata["agent_max_tokens"] = int(request.max_output_tokens)
        token = str(request.metadata.get("provider_api_key") or "")
        try:
            async with _caller_provider_key(token, _provider_key_envs(provider)):
                result = await session.prompt(
                    prompt,
                    provider=provider,
                    model=model,
                    working_directory=request.working_directory,
                    metadata=run_metadata,
                )
        except Exception:
            return UHPRunResult(
                status="failed",
                model=model,
                error_message="Harness run failed.",
                error_code="harness_error",
                usage=None,
            )

        if request.cancel_event and request.cancel_event.is_set():
            return UHPRunResult(
                status="cancelled",
                model=model or getattr(result.response, "model", "") or "",
            )

        return uhp_result_from_harness_run(result, model=model)


def create_uhp_server(
    *,
    spec: Any | str | Path | None = None,
    provider: str = "openai",
    model: str = "",
    working_directory: str | Path | None = None,
    api_key: str | None = None,
    harness_id: str | None = None,
    harness_name: str | None = None,
    runner: HarnessRunner | None = None,
    public_catalog: bool = False,
    require_caller_provider_key: bool = False,
    isolate_session_workspaces: bool | None = None,
    expose_session_listing: bool | None = None,
) -> UHPServer:
    """Build a UHP server bound to one SuperQode HarnessSpec.

    ``isolate_session_workspaces`` defaults to whether the bind is BYOK, and
    ``expose_session_listing`` to the opposite: one bearer shared by every
    caller makes a session list everyone's prompts.
    """
    from superqode.harness import get_harness_template, load_harness_spec

    if spec is None:
        loaded = get_harness_template("coding")
    elif isinstance(spec, (str, Path)):
        path = Path(spec)
        if str(spec).startswith("template:"):
            loaded = get_harness_template(str(spec).split(":", 1)[1])
        else:
            loaded = load_harness_spec(path)
    else:
        loaded = spec

    name = harness_name or getattr(loaded, "name", None) or "SuperQode"
    resolved_id = harness_id or harness_id_from_name(str(name))
    primary = getattr(getattr(loaded, "model_policy", None), "primary", None)
    default_model = model or (str(primary) if primary else "") or "server-default"

    config = UHPServerConfig(
        harness_id=resolved_id,
        harness_name=str(name),
        harness_base="superqode",
        harness_base_label="SuperQode",
        default_model=default_model,
        provider=provider,
        model=default_model,
        working_directory=Path(working_directory or Path.cwd()).resolve(),
        api_key=api_key,
        implementation_version=_package_version(),
        conformance_class="core",
        public_catalog=public_catalog,
        require_caller_provider_key=require_caller_provider_key,
        isolate_session_workspaces=(
            require_caller_provider_key
            if isolate_session_workspaces is None
            else isolate_session_workspaces
        ),
        expose_session_listing=(
            not require_caller_provider_key
            if expose_session_listing is None
            else expose_session_listing
        ),
    )
    return UHPServer(config, runner=runner, spec=loaded)
