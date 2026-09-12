"""Native Unified Harness Protocol server for SuperQode.

Exposes one configured SuperQode HarnessSpec as a UHP-speaking harness. This is
a *native* UHP server (Path A), complementary to HarnessRouter: SuperQode's own
harness bind speaks the wire format directly, rather than wrapping Codex/Claude
as a multi-backend runner.

Targets UHP version ``2026-08-11``. Claims conformance class ``core`` honestly —
the suite has not been run against this process, and Extended surfaces (files,
session listing) are deferred.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
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
    VERSION_HEADER,
)

#: Advertised and accepted protocol version.
SUPPORTED_VERSION = UHP_PROTOCOL_VERSION

#: Discovery document object type.
DISCOVERY_OBJECT = "uhp.discovery"

IDEMPOTENCY_HEADER = "Idempotency-Key"

HarnessRunner = Callable[["UHPRunRequest"], Awaitable["UHPRunResult"]]


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
    #: Honest claim: core endpoints only; suite not yet run.
    conformance_class: str = "core"
    #: GET catalog without a bearer (remote public host). POST still requires api_key.
    public_catalog: bool = False
    #: Refuse a harness turn unless the caller sent PROVIDER_KEY_HEADER.
    require_caller_provider_key: bool = False


def _package_version() -> str:
    try:
        from superqode import __version__

        return __version__
    except Exception:
        return "0.0.0"


def _provider_key_env(provider: str) -> str:
    """Env var LiteLLM reads for this provider (caller BYOK)."""
    try:
        from superqode.providers.registry import PROVIDERS

        pdef = PROVIDERS.get(provider)
        names = getattr(pdef, "env_vars", None) or ()
        if names:
            return str(names[0])
    except Exception:
        pass
    return f"{(provider or 'OPENAI').upper()}_API_KEY"


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
    store: bool = True,
    usage: Mapping[str, int] | None = None,
    error: Mapping[str, Any] | None = None,
    ignored_fields: Sequence[str] = (),
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"session_id": session_id}
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
            "versions": [SUPPORTED_VERSION],
            "default_version": SUPPORTED_VERSION,
            "conformance_class": self.config.conformance_class,
            "capabilities": {
                "streaming": True,
                "sessions": True,
                "cancellation": True,
                "files_input": False,
                "files_output": False,
                "session_listing": False,
                "harness_management": False,
                "session_sharing": False,
                "idempotency": True,
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
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, StreamingResponse

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
                        headers={VERSION_HEADER: SUPPORTED_VERSION},
                    )
            response = await call_next(request)
            response.headers[VERSION_HEADER] = SUPPORTED_VERSION
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
                    return existing

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
            await server._await_response(record["id"])
            return server._responses[record["id"]]

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
            event = server._cancel_events.get(response_id)
            if event is not None:
                event.set()
            if record.get("status") == "in_progress":
                record["status"] = "cancelled"
                record["error"] = None
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
            for response_id in session.get("response_ids", []):
                event = server._cancel_events.get(response_id)
                if event is not None:
                    event.set()
                record = server._responses.get(response_id)
                if record is not None and record.get("status") == "in_progress":
                    record["status"] = "cancelled"
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

    def _negotiate_version(self, requested: str | None) -> dict[str, Any] | None:
        if not requested or not requested.strip():
            return None
        version = requested.strip()
        if version == SUPPORTED_VERSION:
            return None
        return _error_envelope(
            error_type="invalid_request_error",
            code="unsupported_protocol_version",
            message=f"Unsupported UHP-Version '{version}'.",
            param="UHP-Version",
            detail={"supported": [SUPPORTED_VERSION]},
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
        if token != expected:
            return _error_envelope(
                error_type="authentication_error",
                code="invalid_credential",
                message="Invalid API key.",
            )
        return None

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
                # Soft-fail into a new session rather than 404 — some clients
                # resume after retention expiry; store a fresh session.
                session_id = None
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
            session_id = f"sess_{uuid.uuid4().hex[:16]}"

        response_id = f"resp_{uuid.uuid4().hex}"
        created_at = int(time.time())
        ignored: list[str] = []
        if body.get("tools") is not None:
            ignored.append("tools")
        if body.get("include") is not None:
            ignored.append("include")

        requested_model = body.get("model")
        model = str(
            requested_model or self.config.default_model or self.config.model or "server-default"
        )

        record = _response_payload(
            response_id=response_id,
            status="in_progress",
            model=model,
            output=[],
            created_at=created_at,
            previous_response_id=previous_response_id,
            session_id=session_id,
            store=bool(body.get("store", True)),
            ignored_fields=ignored,
        )
        self._responses[response_id] = record
        self._input_items[response_id] = self._normalize_input_items(body.get("input"))
        self._cancel_events[response_id] = asyncio.Event()
        session = self._sessions.setdefault(
            session_id,
            {"id": session_id, "harness_id": self.config.harness_id, "response_ids": []},
        )
        session["response_ids"].append(response_id)
        if idempotency_key:
            self._idempotency[idempotency_key] = response_id

        run_request = UHPRunRequest(
            prompt=prompt,
            model=model,
            provider=self.config.provider,
            working_directory=Path(self.config.working_directory),
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
                **(dict(body["metadata"]) if isinstance(body.get("metadata"), Mapping) else {}),
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
        task = self._tasks.get(response_id)
        if task is not None:
            await task

    async def _execute(self, response_id: str, request: UHPRunRequest) -> None:
        record = self._responses[response_id]
        try:
            if request.cancel_event and request.cancel_event.is_set():
                record["status"] = "cancelled"
                return
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
        token = str(request.metadata.get("provider_api_key") or "")
        env_name = _provider_key_env(provider)
        previous = os.environ.get(env_name)
        if token:
            os.environ[env_name] = token
        try:
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
        finally:
            if token:
                if previous is None:
                    os.environ.pop(env_name, None)
                else:
                    os.environ[env_name] = previous

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
) -> UHPServer:
    """Build a UHP server bound to one SuperQode HarnessSpec."""
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
    )
    return UHPServer(config, runner=runner, spec=loaded)
