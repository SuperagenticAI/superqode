"""Client for the Unified Harness Protocol.

UHP is an HTTP contract for handing a task to a complete agent harness and
getting finished work back.  This module speaks that wire format directly:
protocol discovery, harness listing, response creation, Server-Sent Event
streaming, session files, and cancellation.

No SuperQode types appear in these signatures, so the client is usable on its
own.  ``uhp_adapter`` wraps it for Harness Protocol v1.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

UHP_PROTOCOL_VERSION = "2026-08-11"

#: Sent on every request so a server does not silently answer at another
#: version than the one this client was written against.
VERSION_HEADER = "UHP-Version"

#: Retrying a task without this header starts a second agent in the same
#: workspace, so every task submission carries one.
IDEMPOTENCY_HEADER = "Idempotency-Key"

_TERMINAL_STREAM_EVENTS = frozenset(
    {
        "response.completed",
        "response.incomplete",
        "response.failed",
    }
)


class UHPError(RuntimeError):
    """Base error for every failure reported by a UHP server."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "server_error",
        code: str = "",
        param: str | None = None,
        status_code: int | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.code = code
        self.param = param
        self.status_code = status_code
        self.detail = dict(detail or {})


class UHPInvalidRequestError(UHPError):
    """The server rejected the request as malformed."""


class UHPAuthenticationError(UHPError):
    """The API key was missing, invalid, or expired."""


class UHPPermissionError(UHPError):
    """The credential is valid but not allowed to perform the operation."""


class UHPRateLimitError(UHPError):
    """The caller exceeded a server-side rate or quota limit."""


class UHPHarnessError(UHPError):
    """The harness itself failed while running the task."""


class UHPServerError(UHPError):
    """The server failed for a reason unrelated to the request."""


_ERROR_TYPES: dict[str, type[UHPError]] = {
    "invalid_request_error": UHPInvalidRequestError,
    "authentication_error": UHPAuthenticationError,
    "permission_error": UHPPermissionError,
    "rate_limit_error": UHPRateLimitError,
    "harness_error": UHPHarnessError,
    "server_error": UHPServerError,
}


def _error_from_payload(payload: Any, status_code: int | None = None) -> UHPError:
    """Build a typed error from a UHP error envelope."""
    error: Mapping[str, Any] = {}
    if isinstance(payload, Mapping):
        candidate = payload.get("error")
        if isinstance(candidate, Mapping):
            error = candidate
        elif payload.get("type") in _ERROR_TYPES:
            error = payload
    error_type = str(error.get("type") or "server_error")
    message = str(error.get("message") or "UHP request failed")
    detail = error.get("detail")
    return _ERROR_TYPES.get(error_type, UHPServerError)(
        message,
        error_type=error_type,
        code=str(error.get("code") or ""),
        param=error.get("param"),
        status_code=status_code,
        detail=detail if isinstance(detail, Mapping) else None,
    )


def _error_from_stream_event(data: Mapping[str, Any]) -> UHPError:
    """Build an error from an ``error`` stream event.

    The event envelope reuses ``type`` for the event name, so the error class
    is only available when the payload nests a full error object.  Otherwise
    the stream carries just ``code``, ``message``, and ``param``.
    """
    nested = data.get("error")
    if isinstance(nested, Mapping):
        return _error_from_payload({"error": nested})
    return _error_from_payload(
        {
            "error": {
                "type": "server_error",
                "code": data.get("code"),
                "message": data.get("message"),
                "param": data.get("param"),
            }
        }
    )


@dataclass(frozen=True)
class UHPDiscovery:
    """What ``GET /v1/uhp`` says the server implements."""

    protocol: str = ""
    default_version: str = ""
    versions: tuple[str, ...] = ()
    conformance_class: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)
    implementation: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> UHPDiscovery:
        payload = payload or {}
        versions = payload.get("versions")
        capabilities = payload.get("capabilities")
        implementation = payload.get("implementation")
        return cls(
            protocol=str(payload.get("protocol") or ""),
            default_version=str(payload.get("default_version") or ""),
            versions=tuple(str(version) for version in versions or ()),
            conformance_class=str(payload.get("conformance_class") or ""),
            capabilities=dict(capabilities) if isinstance(capabilities, Mapping) else {},
            implementation=dict(implementation) if isinstance(implementation, Mapping) else {},
            raw=dict(payload),
        )

    @property
    def version(self) -> str:
        """The version this server answers with when none is requested."""
        return self.default_version

    @property
    def speaks_target_version(self) -> bool:
        """Whether the server offers the version this client was built for."""
        return UHP_PROTOCOL_VERSION in self.versions or (
            self.default_version == UHP_PROTOCOL_VERSION
        )

    def supports(self, capability: str) -> bool:
        """Whether the server declared one named capability."""
        return bool(self.capabilities.get(capability))


@dataclass(frozen=True)
class UHPHarness:
    """One configured harness advertised by a UHP server."""

    id: str
    name: str = ""
    base: str = ""
    base_label: str = ""
    default_model: str = ""
    disabled_tools: tuple[str, ...] = ()
    max_step: int | None = None
    timeout_seconds: int | None = None
    created_at: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> UHPHarness:
        disabled = payload.get("disabledTools") or payload.get("disabled_tools") or ()
        max_step = payload.get("maxStep")
        if max_step is None:
            max_step = payload.get("max_step")
        timeout = payload.get("timeoutSeconds")
        if timeout is None:
            timeout = payload.get("timeout_seconds")
        return cls(
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            base=str(payload.get("base") or ""),
            base_label=str(payload.get("baseLabel") or payload.get("base_label") or ""),
            default_model=str(payload.get("defaultModel") or payload.get("default_model") or ""),
            disabled_tools=tuple(str(tool) for tool in disabled),
            max_step=max_step,
            timeout_seconds=timeout,
            created_at=payload.get("createdAt") or payload.get("created_at"),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class UHPUsage:
    """Token accounting for one response."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> UHPUsage | None:
        """Return usage, or ``None`` when the server reported none.

        A fabricated zero is worse than an honest absence, so a missing or
        null ``usage`` object stays missing rather than becoming a count.
        """
        if not isinstance(payload, Mapping):
            return None
        return cls(
            input_tokens=int(payload.get("input_tokens") or 0),
            output_tokens=int(payload.get("output_tokens") or 0),
            total_tokens=int(payload.get("total_tokens") or 0),
            cache_read_tokens=int(payload.get("cache_read_tokens") or 0),
            cache_write_tokens=int(payload.get("cache_write_tokens") or 0),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }


@dataclass(frozen=True)
class UHPFileCitation:
    """A file produced by a harness run and referenced from its output."""

    container_id: str
    file_id: str
    filename: str = ""
    download_url: str = ""

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> UHPFileCitation:
        return cls(
            container_id=str(payload.get("container_id") or ""),
            file_id=str(payload.get("file_id") or ""),
            filename=str(payload.get("filename") or ""),
            download_url=str(payload.get("download_url") or ""),
        )


@dataclass(frozen=True)
class UHPFunctionCall:
    """One tool call recorded in a response's output."""

    call_id: str
    name: str
    arguments: str = ""
    output: str | None = None

    def parsed_arguments(self) -> dict[str, Any]:
        """Return the decoded arguments, or an empty mapping when unparseable."""
        try:
            decoded = json.loads(self.arguments or "{}")
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}


@dataclass(frozen=True)
class UHPResponse:
    """A completed or in-flight UHP response."""

    id: str
    status: str = ""
    model: str = ""
    previous_response_id: str | None = None
    session_id: str | None = None
    usage: UHPUsage | None = None
    error: UHPError | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> UHPResponse:
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        error_payload = payload.get("error")
        return cls(
            id=str(payload.get("id") or ""),
            status=str(payload.get("status") or ""),
            model=str(payload.get("model") or ""),
            previous_response_id=payload.get("previous_response_id"),
            # Published examples carry it in metadata; a server may equally
            # put it on the response object, and resume needs either.
            session_id=(
                str(metadata.get("session_id") or payload.get("session_id"))
                if (metadata.get("session_id") or payload.get("session_id"))
                else None
            ),
            usage=UHPUsage.from_payload(payload.get("usage")),
            error=_error_from_payload(payload) if isinstance(error_payload, Mapping) else None,
            raw=dict(payload),
        )

    @property
    def is_terminal(self) -> bool:
        """Whether the server considers this task finished."""
        return self.status in {"completed", "failed", "incomplete", "cancelled"}

    @property
    def output_items(self) -> tuple[dict[str, Any], ...]:
        items = self.raw.get("output")
        if not isinstance(items, Sequence):
            return ()
        return tuple(dict(item) for item in items if isinstance(item, Mapping))

    @property
    def output_text(self) -> str:
        """Concatenate every assistant text part in output order."""
        parts: list[str] = []
        for item in self.output_items:
            if item.get("type") not in {None, "message", "output_text"}:
                continue
            content = item.get("content")
            if not isinstance(content, Sequence):
                continue
            for part in content:
                if isinstance(part, Mapping) and part.get("type") == "output_text":
                    parts.append(str(part.get("text") or ""))
        return "".join(parts)

    @property
    def file_citations(self) -> tuple[UHPFileCitation, ...]:
        """Return every file the response annotated, de-duplicated by file id."""
        seen: dict[str, UHPFileCitation] = {}
        for item in self.output_items:
            content = item.get("content")
            if not isinstance(content, Sequence):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                for annotation in part.get("annotations") or ():
                    if (
                        isinstance(annotation, Mapping)
                        and annotation.get("type") == "container_file_citation"
                    ):
                        citation = UHPFileCitation.from_payload(annotation)
                        seen.setdefault(citation.file_id, citation)
        return tuple(seen.values())

    @property
    def function_calls(self) -> tuple[UHPFunctionCall, ...]:
        """Return the tool calls and their outputs recorded in the response."""
        outputs: dict[str, str] = {}
        for item in self.output_items:
            if item.get("type") == "function_call_output":
                outputs[str(item.get("call_id") or "")] = str(item.get("output") or "")
        calls: list[UHPFunctionCall] = []
        for item in self.output_items:
            if item.get("type") != "function_call":
                continue
            call_id = str(item.get("call_id") or "")
            calls.append(
                UHPFunctionCall(
                    call_id=call_id,
                    name=str(item.get("name") or ""),
                    arguments=str(item.get("arguments") or ""),
                    output=outputs.get(call_id),
                )
            )
        return tuple(calls)

    def raise_for_error(self) -> None:
        """Raise when the server reported a failed or errored response."""
        if self.error is not None:
            raise self.error
        if self.status == "failed":
            raise UHPHarnessError(
                f"UHP response {self.id or '<unknown>'} failed",
                error_type="harness_error",
            )


@dataclass(frozen=True)
class UHPStreamEvent:
    """One Server-Sent Event emitted while a response is running."""

    type: str
    sequence_number: int = 0
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.type in _TERMINAL_STREAM_EVENTS

    @property
    def is_error(self) -> bool:
        """An ``error`` event reports a failure but does not end the task."""
        return self.type == "error"

    @property
    def error(self) -> UHPError | None:
        return _error_from_stream_event(self.data) if self.is_error else None

    @property
    def response(self) -> UHPResponse | None:
        """Return the embedded response object when the event carries one."""
        payload = self.data.get("response")
        if isinstance(payload, Mapping):
            return UHPResponse.from_payload(payload)
        return None


class UHPClient:
    """Async client for a Unified Harness Protocol server.

    Args:
        base_url: Root URL of the UHP server, with or without a trailing
            ``/v1``.  A server that mounts the protocol under a prefix, such as
            HarnessRouter Community Edition's ``/api/harness``, takes that
            whole prefix as the base URL.
        api_key: Bearer credential sent on every request.
        timeout: Request timeout in seconds.  Streaming reads use no read
            timeout, because a harness can work for minutes between events.
        headers: Extra headers merged into every request.  A cookie header
            belongs here for a server that gates the API with a console
            session instead of a bearer token.
        client: An existing ``httpx.AsyncClient`` to borrow instead of creating
            one.  A borrowed client is never closed by ``aclose``.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 600.0,
        headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url)
        self.api_key = api_key
        self.timeout = timeout
        self._headers = {
            "Accept": "application/json",
            VERSION_HEADER: UHP_PROTOCOL_VERSION,
            **dict(headers or {}),
        }
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._client = client
        self._owns_client = client is None

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """Return the server root without a trailing slash or ``/v1`` suffix."""
        trimmed = base_url.rstrip("/")
        if trimmed.endswith("/v1"):
            trimmed = trimmed[: -len("/v1")]
        return trimmed

    def _url(self, path: str) -> str:
        return f"{self.base_url}/v1/{path.lstrip('/')}"

    async def __aenter__(self) -> UHPClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying transport when this client created it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_client = True
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        client = self._ensure_client()
        try:
            response = await client.request(
                method,
                self._url(path),
                json=dict(json_body) if json_body is not None else None,
                params=dict(params) if params else None,
                headers={**self._headers, **dict(headers or {})},
            )
        except httpx.HTTPError as exc:
            raise UHPServerError(f"UHP request to {path} failed: {exc}") from exc
        return self._decode(response)

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400:
            if payload is None:
                raise UHPServerError(
                    f"UHP server returned HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            raise _error_from_payload(payload, response.status_code)
        return payload

    async def discover(self) -> UHPDiscovery:
        """Return the server's version and capability declaration."""
        payload = await self._request("GET", "uhp")
        return UHPDiscovery.from_payload(payload if isinstance(payload, Mapping) else None)

    async def list_harnesses(self) -> tuple[UHPHarness, ...]:
        """Return every harness the server advertises."""
        payload = await self._request("GET", "harnesses")
        return tuple(
            UHPHarness.from_payload(item)
            for item in _items(payload, "harnesses")
            if isinstance(item, Mapping)
        )

    async def get_harness(self, harness_id: str) -> UHPHarness:
        """Return one harness by id."""
        payload = await self._request("GET", f"harnesses/{harness_id}")
        if not isinstance(payload, Mapping):
            raise UHPServerError(f"UHP server returned no harness for {harness_id!r}")
        return UHPHarness.from_payload(payload)

    async def create_harness(
        self,
        base: str,
        *,
        name: str | None = None,
        default_model: str | None = None,
        system_prompt: str | None = None,
        mcp_servers: Sequence[Mapping[str, Any]] | None = None,
        skills: Sequence[Mapping[str, Any]] | None = None,
        disabled_tools: Sequence[str] | None = None,
        max_step: int | None = None,
        timeout_seconds: int | None = None,
    ) -> UHPHarness:
        """Configure a new harness on the server and return it."""
        body: dict[str, Any] = {"base": base}
        optional = {
            "name": name,
            "default_model": default_model,
            "system_prompt": system_prompt,
            "mcp_servers": list(mcp_servers) if mcp_servers else None,
            "skills": list(skills) if skills else None,
            "disabled_tools": list(disabled_tools) if disabled_tools else None,
            "max_step": max_step,
            "timeout_seconds": timeout_seconds,
        }
        body.update({key: value for key, value in optional.items() if value is not None})
        payload = await self._request("POST", "harnesses", json_body=body)
        if not isinstance(payload, Mapping):
            raise UHPServerError(f"UHP server returned no harness for base {base!r}")
        return UHPHarness.from_payload(payload)

    async def delete_harness(self, harness_id: str) -> None:
        """Remove a configured harness from the server."""
        await self._request("DELETE", f"harnesses/{harness_id}")

    async def list_models(self, harness_id: str | None = None) -> tuple[str, ...]:
        """Return model ids, optionally narrowed to one harness.

        ``GET /v1/models`` groups models under ``backends``; the per-harness
        route returns a flat ``models`` list.
        """
        path = f"harnesses/{harness_id}/models" if harness_id else "models"
        payload = await self._request("GET", path)
        models: list[str] = []
        seen: set[str] = set()

        def add(entry: Any) -> None:
            model_id = entry.get("id") if isinstance(entry, Mapping) else entry
            if not model_id:
                return
            text = str(model_id)
            if text not in seen:
                seen.add(text)
                models.append(text)

        for item in _items(payload, "models"):
            add(item)
        if isinstance(payload, Mapping):
            backends = payload.get("backends")
            if isinstance(backends, Mapping):
                for backend in backends.values():
                    for item in _items(backend, "models"):
                        add(item)
        return tuple(models)

    def build_response_body(
        self,
        message: str,
        *,
        harness_id: str | None = None,
        model: str | None = None,
        previous_response_id: str | None = None,
        instructions: str | None = None,
        stream: bool = False,
        store: bool = True,
        background: bool = False,
        max_output_tokens: int | None = None,
        max_step: int | None = None,
        timeout_seconds: int | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        include: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble a ``POST /v1/responses`` body, omitting unset fields."""
        body: dict[str, Any] = {"input": message, "stream": stream, "store": store}
        merged_metadata: dict[str, Any] = dict(metadata or {})
        if harness_id:
            merged_metadata["harness_id"] = harness_id
        if merged_metadata:
            body["metadata"] = merged_metadata
        optional = {
            "model": model,
            "previous_response_id": previous_response_id,
            "instructions": instructions,
            "max_output_tokens": max_output_tokens,
            "max_step": max_step,
            "timeout_seconds": timeout_seconds,
            "tools": list(tools) if tools else None,
            "include": list(include) if include else None,
        }
        body.update({key: value for key, value in optional.items() if value is not None})
        if background:
            body["background"] = True
        return body

    @staticmethod
    def new_idempotency_key() -> str:
        """Return a fresh key for one task submission."""
        return f"sq-{uuid.uuid4().hex}"

    async def create_response(
        self,
        message: str,
        *,
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> UHPResponse:
        """Run one task to completion and return the finished response."""
        kwargs.pop("stream", None)
        body = self.build_response_body(message, stream=False, **kwargs)
        headers = {IDEMPOTENCY_HEADER: idempotency_key or self.new_idempotency_key()}
        payload = await self._request("POST", "responses", json_body=body, headers=headers)
        if not isinstance(payload, Mapping):
            raise UHPServerError("UHP server returned no response object")
        return UHPResponse.from_payload(payload)

    async def stream_response(
        self,
        message: str,
        *,
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[UHPStreamEvent]:
        """Run one task and yield each Server-Sent Event as it arrives.

        An ``error`` event does not end the task and must be followed by a
        terminal event, so it is yielded rather than raised.  The error is
        raised only when the stream ends without ever reaching a terminal
        event, which is a malformed stream.
        """
        from httpx_sse import aconnect_sse

        kwargs.pop("stream", None)
        body = self.build_response_body(message, stream=True, **kwargs)
        client = self._ensure_client()
        headers = {
            **self._headers,
            "Accept": "text/event-stream",
            IDEMPOTENCY_HEADER: idempotency_key or self.new_idempotency_key(),
        }
        pending_error: UHPError | None = None
        try:
            async with aconnect_sse(
                client,
                "POST",
                self._url("responses"),
                json=body,
                headers=headers,
                timeout=httpx.Timeout(self.timeout, read=None),
            ) as source:
                if source.response.status_code >= 400:
                    await source.response.aread()
                    self._decode(source.response)
                async for sse in source.aiter_sse():
                    event = _parse_stream_event(sse.event, sse.data)
                    if event is None:
                        continue
                    if event.is_error:
                        pending_error = event.error
                    yield event
                    if event.is_terminal:
                        return
        except httpx.HTTPError as exc:
            raise UHPServerError(f"UHP stream failed: {exc}") from exc
        if pending_error is not None:
            raise pending_error

    async def get_response(self, response_id: str) -> UHPResponse:
        """Fetch a stored response by id.

        This is the source of truth after a dropped stream, because a dropped
        connection does not stop the task.
        """
        payload = await self._request("GET", f"responses/{response_id}")
        if not isinstance(payload, Mapping):
            raise UHPServerError(f"UHP server returned no response for {response_id!r}")
        return UHPResponse.from_payload(payload)

    async def cancel_response(self, response_id: str) -> UHPResponse:
        """Cancel one in-flight response.  The call is idempotent."""
        payload = await self._request("POST", f"responses/{response_id}/cancel")
        if not isinstance(payload, Mapping):
            raise UHPServerError(f"UHP server returned no response for {response_id!r}")
        return UHPResponse.from_payload(payload)

    async def cancel_session(self, session_id: str) -> dict[str, Any]:
        """Cancel whatever is currently running in a session."""
        payload = await self._request("POST", f"sessions/{session_id}/cancel")
        return dict(payload) if isinstance(payload, Mapping) else {}

    async def list_session_turns(self, session_id: str) -> tuple[dict[str, Any], ...]:
        """Return the recorded turns for a session, oldest first."""
        payload = await self._request("GET", f"sessions/{session_id}/turns")
        return tuple(dict(item) for item in _items(payload, "turns") if isinstance(item, Mapping))

    async def latest_response_id(self, session_id: str) -> str | None:
        """Return the most recent response id recorded for a session."""
        turns = await self.list_session_turns(session_id)
        for turn in reversed(turns):
            for key in ("response_id", "id"):
                value = turn.get(key)
                if isinstance(value, str) and value.startswith("resp_"):
                    return value
        return None

    async def list_session_files(self, session_id: str) -> tuple[dict[str, Any], ...]:
        """Return the files a session has produced."""
        payload = await self._request("GET", f"sessions/{session_id}/files")
        return tuple(dict(item) for item in _items(payload, "files") if isinstance(item, Mapping))

    async def download_file(self, container_id: str, file_id: str) -> bytes:
        """Download one file produced by a harness run."""
        client = self._ensure_client()
        url = self._url(f"containers/{container_id}/files/{file_id}/content")
        try:
            response = await client.get(url, headers=self._headers)
        except httpx.HTTPError as exc:
            raise UHPServerError(f"UHP file download failed: {exc}") from exc
        if response.status_code >= 400:
            self._decode(response)
        return response.content


def _items(payload: Any, *keys: str) -> tuple[Any, ...]:
    """Return the element list from a UHP list envelope or a bare array.

    The spec names each collection (``harnesses``, ``turns``, ``files``,
    ``models``).  ``data`` is accepted afterwards so a Responses-style server
    still parses.
    """
    if isinstance(payload, Mapping):
        for key in (*keys, "data"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return tuple(value)
        return ()
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return tuple(payload)
    return ()


def _parse_stream_event(event_name: str | None, raw_data: str) -> UHPStreamEvent | None:
    """Decode one SSE frame, tolerating keep-alives and unparseable payloads."""
    if not raw_data or raw_data.strip() in {"", "[DONE]"}:
        return None
    try:
        payload = json.loads(raw_data)
    except ValueError:
        return None
    if not isinstance(payload, Mapping):
        return None
    event_type = str(payload.get("type") or event_name or "")
    if not event_type:
        return None
    return UHPStreamEvent(
        type=event_type,
        sequence_number=int(payload.get("sequence_number") or 0),
        data=dict(payload),
    )
