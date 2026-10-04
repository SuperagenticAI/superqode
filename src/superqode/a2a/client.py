"""
A2A Client - Client for communicating with A2A-compliant agents.

Implements JSON-RPC and HTTP+JSON bindings for Agent2Agent Protocol.
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .inspect import InspectLog, auth_summary
from .types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    Artifact,
    Message,
    MessageRole,
    FilePart,
    Part,
    StreamResponse,
    Task,
    TaskStatus,
    TaskStatusValue,
)


class A2AClientError(Exception):
    """Base exception for A2A client errors."""

    def __init__(self, message: str, inspect: InspectLog | None = None):
        super().__init__(message)
        self.inspect = inspect


class AgentNotFoundError(A2AClientError):
    """Agent not found or not responding."""


class TaskFailedError(A2AClientError):
    """Task failed on remote agent."""


class A2AClient:
    """Client for communicating with A2A-compliant agents.

    Usage:
        client = A2AClient("http://localhost:8000")
        card = await client.get_agent_card()
        result = await client.send_message("Hello agent!")
    """

    def __init__(
        self,
        agent_url: str,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 60.0,
        bearer_token: Optional[str] = None,
        extra_headers: Optional[dict[str, str]] = None,
        client_cert: Optional[str] = None,
        client_key: Optional[str] = None,
        strict_origin: bool = False,
        max_response_bytes: int = 4 * 1024 * 1024,
        subscription_method: str = "GET",
    ):
        """Initialize A2A client.

        Args:
            agent_url: URL of the A2A agent server
            http_client: Optional existing httpx client
            timeout: Request timeout in seconds
        """
        self.agent_url = agent_url.rstrip("/")
        self._interface_url: str | None = None
        self._binding: str | None = None
        self._protocol_version: str | None = None
        self._agent_card: AgentCard | None = None
        self._card_data: dict | None = None
        self.timeout = timeout
        self.strict_origin = strict_origin
        self.max_response_bytes = max_response_bytes
        if subscription_method not in {"GET", "POST"}:
            raise ValueError("REST subscription_method must be GET or POST")
        self.subscription_method = subscription_method
        self._owns_http = http_client is None
        self._tls_cert = (client_cert or "").strip()
        self._tls_key = (client_key or "").strip()
        cert = _httpx_cert(self._tls_cert, self._tls_key)
        self._http = http_client or httpx.AsyncClient(timeout=timeout, cert=cert)
        self._query_params: dict[str, str] = {}
        self.inspect = InspectLog()
        if extra_headers:
            self._http.headers.update(extra_headers)
        if bearer_token:
            self._http.headers["Authorization"] = f"Bearer {bearer_token}"
        if self._tls_cert:
            self.inspect.auth("Mutual TLS client certificate attached")

    def add_query_params(self, params: dict[str, str]) -> None:
        """Attach API-key query parameters to every subsequent request."""
        self._query_params.update({str(key): str(value) for key, value in params.items() if key})

    def _with_query(self, url: str) -> str:
        return _merge_query(url, self._query_params)

    async def close(self):
        """Close the HTTP client."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> "A2AClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def get_agent_card(self) -> AgentCard:
        """Discover capabilities from the A2A well-known Agent Card.

        Returns:
            AgentCard with agent metadata and skills

        Raises:
            AgentNotFoundError: If agent is not available
        """
        paths = ("/.well-known/agent-card.json", "/.well-known/agent.json")
        response = None
        url = f"{self.agent_url}{paths[0]}"
        for index, path in enumerate(paths):
            url = self._with_query(f"{self.agent_url}{path}")
            note = "agent-card" if index == 0 else "agent.json fallback"
            self.inspect.request(
                "GET",
                url,
                note=note,
                headers={str(key): str(value) for key, value in self._http.headers.items()},
            )
            try:
                response = await self._bounded_request(
                    "GET", url, follow_redirects=not self.strict_origin
                )
            except httpx.RequestError as e:
                summary = f"Cannot connect to agent: {e}"
                self.inspect.error(summary, url=url)
                raise AgentNotFoundError(summary, inspect=self.inspect) from e
            self.inspect.response(
                response.status_code, "GET", str(response.request.url), body=response.text
            )
            if response.status_code == 404 and index == 0:
                continue
            break
        assert response is not None
        if response.status_code == 404:
            raise AgentNotFoundError(
                f"No Agent Card at {self.agent_url}/.well-known/agent-card.json "
                "or /.well-known/agent.json (404).",
                inspect=self.inspect,
            )
        if response.status_code in {401, 403}:
            raise A2AClientError(
                f"Agent Card at {url} returned {response.status_code}. "
                "Discovery is protected; pass a Bearer if you have one.",
                inspect=self.inspect,
            )
        if response.status_code >= 300:
            raise A2AClientError(
                f"Failed to get agent card: {response.status_code} {url}",
                inspect=self.inspect,
            )
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise A2AClientError(
                f"Agent Card at {url} was not JSON: {e}",
                inspect=self.inspect,
            ) from e
        if not isinstance(data, dict):
            raise A2AClientError(
                f"Agent Card at {url} was {type(data).__name__}, not an object",
                inspect=self.inspect,
            )
        self._card_data = data
        card, binding, version = self._parse_agent_card(data)
        self._interface_url = card.url.strip().rstrip("/")
        self._binding = binding
        self._protocol_version = version
        self._agent_card = card
        return card

    def _parse_agent_card(self, data: dict) -> tuple[AgentCard, str, str]:
        """Parse a card and pick the first interface this client can speak.

        Cards list ``supportedInterfaces`` in preference order. JSON-RPC is
        the default A2A binding; HTTP+JSON is optional. Demanding one binding
        made JSON-RPC-only agents uncallable.
        """
        self._card_data = data
        capabilities_data = data.get("capabilities", {})
        capabilities = AgentCapabilities(
            streaming=capabilities_data.get("streaming", False),
            push_notifications=capabilities_data.get("pushNotifications", False),
            extended_agent_card=capabilities_data.get("extendedAgentCard", False),
        )

        skills = [
            AgentSkill(
                id=s.get("id", ""),
                name=s.get("name", ""),
                description=s.get("description", ""),
                tags=list(s.get("tags", [])),
                examples=list(s.get("examples", [])),
            )
            for s in data.get("skills", [])
        ]
        interfaces = data.get("supportedInterfaces", [])
        fallback = data.get("url", self.agent_url)
        if isinstance(fallback, str):
            fallback = fallback.strip() or self.agent_url
        else:
            fallback = self.agent_url

        self.inspect.auth(auth_summary(data))
        self._record_card_review(data)
        selected, skipped = _select_interface(interfaces, fallback)
        listed = interfaces if isinstance(interfaces, list) else []
        note = ""
        if selected is not None and not listed:
            note = "no supportedInterfaces; using card url as JSONRPC 0.3"
        self.inspect.choice(selected, skipped, note=note)
        if selected is None:
            raise A2AClientError(_reject_message(skipped), inspect=self.inspect)
        interface_url, binding, version = selected
        if self.strict_origin and _origin(interface_url) != _origin(self.agent_url):
            raise A2AClientError("Agent Card changed the configured peer origin")
        interface = urlsplit(interface_url)
        if self.strict_origin and (
            interface.username or interface.password or interface.query or interface.fragment
        ):
            raise A2AClientError(
                "Agent Card interface contains unsupported URL credentials/query/fragment"
            )

        card = AgentCard(
            name=data.get("name", "Unknown"),
            description=data.get("description", ""),
            url=interface_url,
            version=data.get("version", "1.0"),
            capabilities=capabilities,
            skills=skills,
            supported_interfaces=interfaces,
            default_input_modes=data.get("defaultInputModes", ["text"]),
            default_output_modes=data.get("defaultOutputModes", ["text"]),
        )
        return card, binding, version

    def _record_card_review(self, data: dict) -> None:
        """Record A2ABreak card-review findings. Never treat JWS as auth."""
        from superqode.a2a.trust import (
            origin_is_allowed,
            parse_origin_allowlist,
            record_card_review,
            resolve_jws_trust_root,
            review_agent_card,
        )

        allowed = getattr(self, "allowed_origins", None)
        if allowed is None:
            allowed = parse_origin_allowlist()
        trust_root = getattr(self, "jws_trust_root", None)
        if trust_root is None:
            trust_root = resolve_jws_trust_root()
        review = review_agent_card(
            data,
            origin=self.agent_url,
            allowed_origins=tuple(allowed or ()),
            jws_trust_root=str(trust_root or ""),
        )
        self._card_review = review
        record_card_review(self.inspect, review)
        if tuple(allowed or ()) and not origin_is_allowed(self.agent_url, tuple(allowed)):
            raise A2AClientError(
                f"Origin is not on the A2A allowlist: {self.agent_url}",
                inspect=self.inspect,
            )

    async def _ensure_interface(self) -> tuple[str, str, str]:
        if self._interface_url is None or self._binding is None or self._protocol_version is None:
            await self.get_agent_card()
        assert self._interface_url and self._binding and self._protocol_version
        return self._interface_url, self._binding, self._protocol_version

    def _version_headers(self, version: str) -> dict[str, str]:
        # A 1.0 method under a missing header is negotiated as 0.3 and rejected.
        # A 0.3 client sends no version header.
        return {
            **({"A2A-Version": "1.0"} if version == "1.0" else {}),
            **({"Accept-Encoding": "identity"} if self.strict_origin else {}),
        }

    async def _operation_url(self, path: str) -> str:
        """Resolve a REST path against the selected HTTP+JSON interface."""
        interface_url, _, _ = await self._ensure_interface()
        return f"{interface_url}/{path.lstrip('/')}"

    async def send_message(
        self,
        message: str,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        *,
        message_id: str | None = None,
        nonblocking: bool = False,
        metadata: dict | None = None,
    ) -> Task | Message:
        """Send a message on the binding advertised first on the card."""
        interface_url, binding, version = await self._ensure_interface()
        params = _message_params(
            message,
            version,
            session_id=session_id,
            task_id=task_id,
            message_id=message_id,
            nonblocking=nonblocking,
            metadata=metadata,
        )
        try:
            if binding == "JSONRPC":
                method = "SendMessage" if version == "1.0" else "message/send"
                data = await self._jsonrpc(interface_url, method, params, version)
            else:
                data = await self._rest(
                    "POST",
                    f"{interface_url}/message:send",
                    json_body=params,
                    headers=self._version_headers(version),
                    note=f"HTTP+JSON {version}",
                )
            return self._parse_response(data)
        except A2AClientError:
            raise
        except httpx.HTTPStatusError as e:
            raise TaskFailedError(f"Task failed: {e}", inspect=self.inspect) from e
        except httpx.RequestError as e:
            raise A2AClientError(f"Request failed: {e}", inspect=self.inspect) from e

    async def _bounded_request(self, method, url, **kwargs):
        # Enforce the allowance while consuming the body, before JSON parsing
        # or inspect logging can retain an unbounded peer response.
        if self.strict_origin:
            kwargs["headers"] = {**dict(kwargs.get("headers") or {}), "Accept-Encoding": "identity"}
        async with self._http.stream(method, url, **kwargs) as response:
            if (
                self.strict_origin
                and response.headers.get("content-encoding", "identity") != "identity"
            ):
                raise A2AClientError(
                    "Compressed A2A responses are unsupported under bounded peer policy"
                )
            chunks, size = [], 0
            async for chunk in response.aiter_bytes(65536):
                size += len(chunk)
                if size > self.max_response_bytes:
                    raise TaskFailedError("A2A response exceeds the configured size limit")
                chunks.append(chunk)
            return httpx.Response(
                response.status_code,
                headers={
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() not in {"content-encoding", "content-length"}
                },
                content=b"".join(chunks),
                request=response.request,
            )

    async def _rest(
        self,
        method: str,
        url: str,
        *,
        json_body: dict | None = None,
        headers: dict[str, str] | None = None,
        note: str = "",
        follow_redirects: bool = True,
        unwrap_jsonrpc: bool = False,
    ) -> dict:
        """One HTTP call, recorded on the inspect log."""
        url = self._with_query(url)
        encoded = json.dumps(json_body) if json_body is not None else ""
        merged_headers = {str(key): str(value) for key, value in self._http.headers.items()}
        if headers:
            merged_headers.update(headers)
        self.inspect.request(method, url, note=note, body=encoded, headers=merged_headers)
        try:
            request_kwargs: dict = {
                "headers": headers,
                "follow_redirects": follow_redirects and not self.strict_origin,
            }
            if json_body is not None:
                request_kwargs["json"] = json_body
            response = await self._bounded_request(method, url, **request_kwargs)
        except httpx.RequestError as e:
            self.inspect.error(f"Request failed: {e}", url=url)
            raise A2AClientError(f"Request failed: {e}", inspect=self.inspect) from e
        self.inspect.response(
            response.status_code, method, str(response.request.url), body=response.text
        )
        if len(response.content) > self.max_response_bytes:
            raise TaskFailedError("A2A response exceeds the configured size limit")
        if response.status_code >= 300:
            raise TaskFailedError(
                f"Task failed: {response.status_code} {url}",
                inspect=self.inspect,
            )
        try:
            parsed = response.json()
        except json.JSONDecodeError as e:
            raise TaskFailedError(
                f"Response was not JSON: {e}",
                inspect=self.inspect,
            ) from e
        if unwrap_jsonrpc and isinstance(parsed, dict) and parsed.get("error"):
            error = parsed["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise TaskFailedError(message or "JSON-RPC error", inspect=self.inspect)
        return _unwrap_body(parsed)

    async def _jsonrpc(self, url: str, method: str, params: dict, version: str) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        body = await self._rest(
            "POST",
            url,
            json_body=payload,
            headers=self._version_headers(version),
            note=f"{method} JSONRPC {version}",
            follow_redirects=True,
            unwrap_jsonrpc=True,
        )
        return body

    async def send_message_streaming(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[StreamResponse]:
        """POST /message:stream - Send message with streaming response.

        Args:
            message: Text message to send
            session_id: Optional session/context ID

        Yields:
            StreamResponse events

        Raises:
            TaskFailedError: If task fails
        """
        interface_url, binding, version = await self._ensure_interface()
        params = _message_params(message, version, session_id=session_id)
        if binding == "JSONRPC":
            method = "SendStreamingMessage" if version == "1.0" else "message/stream"
            url = self._with_query(interface_url)
            body: dict = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": method,
                "params": params,
            }
            self.inspect.request("POST", url, note=f"{method} stream JSONRPC {version}")
        else:
            url = self._with_query(f"{interface_url}/message:stream")
            body = params
            self.inspect.request("POST", url, note=f"stream HTTP+JSON {version}")
        try:
            async with self._http.stream(
                "POST",
                url,
                json=body,
                headers=self._version_headers(version),
                follow_redirects=not self.strict_origin,
            ) as response:
                response.raise_for_status()
                async for event in self._events(response):
                    yield event
        except httpx.HTTPStatusError as e:
            yield StreamResponse(type="error", data=str(e))
        except httpx.RequestError as e:
            yield StreamResponse(type="error", data=str(e))

    async def get_task(self, task_id: str) -> Task:
        """GET /tasks/{id} - Get task state.

        Args:
            task_id: ID of the task to retrieve

        Returns:
            Task with current state
        """
        interface_url, binding, version = await self._ensure_interface()
        if binding == "JSONRPC":
            method = "GetTask" if version == "1.0" else "tasks/get"
            data = await self._jsonrpc(interface_url, method, {"id": task_id}, version)
            return self._parse_task(data)
        url = f"{interface_url}/tasks/{task_id}"
        data = await self._rest(
            "GET",
            url,
            headers=self._version_headers(version),
            note=f"HTTP+JSON {version}",
        )
        return self._parse_task(data)

    async def cancel_task(self, task_id: str) -> Task:
        """POST /tasks/{id}:cancel - Cancel a running task.

        Args:
            task_id: ID of the task to cancel

        Returns:
            Task in canceled state
        """
        interface_url, binding, version = await self._ensure_interface()
        if binding == "JSONRPC":
            method = "CancelTask" if version == "1.0" else "tasks/cancel"
            data = await self._jsonrpc(interface_url, method, {"id": task_id}, version)
            return self._parse_task(data)
        url = f"{interface_url}/tasks/{task_id}:cancel"
        data = await self._rest(
            "POST",
            url,
            json_body={},
            headers=self._version_headers(version),
            note=f"HTTP+JSON {version}",
        )
        return self._parse_task(data)

    async def subscribe_task(self, task_id: str) -> AsyncIterator[StreamResponse]:
        """GET /tasks/{id}:subscribe - Subscribe to task updates.

        Args:
            task_id: ID of the task to subscribe to

        Yields:
            StreamResponse with task updates
        """
        interface_url, binding, version = await self._ensure_interface()
        if binding == "JSONRPC":
            url = interface_url
        else:
            url = f"{interface_url}/tasks/{task_id}:subscribe"

        try:
            stream_headers = self._version_headers(version)
            if binding == "JSONRPC":
                method = "SubscribeToTask" if version == "1.0" else "tasks/resubscribe"
                async with self._http.stream(
                    "POST",
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": str(uuid.uuid4()),
                        "method": method,
                        "params": {"id": task_id},
                    },
                    headers=stream_headers,
                    follow_redirects=not self.strict_origin,
                ) as response:
                    response.raise_for_status()
                    async for event in self._events(response):
                        yield event
                return
            async with self._http.stream(
                self.subscription_method,
                url,
                headers=stream_headers,
                follow_redirects=not self.strict_origin,
            ) as response:
                response.raise_for_status()
                async for event in self._events(response):
                    yield event
        except httpx.HTTPStatusError as e:
            yield StreamResponse(type="error", data=str(e))

    def _parse_response(self, data: dict) -> Task | Message:
        value = _unwrap_body(data)
        if "message" in value:
            return _parse_message(value["message"])
        if "role" in value and "parts" in value:
            return _parse_message(value)
        return self._parse_task(value)

    def _parse_task(self, data: dict) -> Task:
        data = _unwrap_body(data)
        if not isinstance(data, dict) or not (data.get("id") or data.get("taskId")):
            raise A2AClientError("A2A task response has no task ID")
        return Task(
            task_id=str(data.get("id") or data["taskId"]),
            status=_parse_status(data.get("status", {})),
            history=[_parse_message(m) for m in data.get("history", [])],
            artifacts=[_parse_artifact(a) for a in data.get("artifacts", [])],
            metadata=data.get("metadata", {}),
            context_id=data.get("contextId"),
        )

    def _parse_event(self, data: dict) -> StreamResponse:
        if data.get("error"):
            return StreamResponse("error", data["error"])
        value = _unwrap_body(data)
        if "statusUpdate" in value:
            value = value["statusUpdate"]
        if "artifactUpdate" in value:
            value = value["artifactUpdate"]
        if value.get("kind") == "status-update" or ("status" in value and "taskId" in value):
            return StreamResponse(
                "status_update", {**value, "status": _parse_status(value["status"])}
            )
        if "artifact" in value:
            return StreamResponse(
                "artifact_update", {**value, "artifact": _parse_artifact(value["artifact"])}
            )
        parsed = self._parse_response(value)
        return StreamResponse("task" if isinstance(parsed, Task) else "message", parsed)

    async def _events(self, response: httpx.Response) -> AsyncIterator[StreamResponse]:
        response.raise_for_status()
        fields: list[str] = []
        size = 0
        async for line in self._bounded_lines(response):
            if not line:
                if fields:
                    payload = "\n".join(fields)
                    fields, size = [], 0
                    if payload == "[DONE]":
                        yield StreamResponse("done", None)
                    else:
                        try:
                            yield self._parse_event(json.loads(payload))
                        except (ValueError, TypeError, KeyError, A2AClientError) as error:
                            raise A2AClientError(f"Invalid A2A stream event: {error}") from error
                continue
            if line.startswith("data:"):
                text = line[5:].removeprefix(" ")
                size += len(text.encode())
                if size > self.max_response_bytes:
                    raise A2AClientError("A2A stream event exceeds size limit")
                fields.append(text)
        if fields:
            yield self._parse_event(json.loads("\n".join(fields)))

    async def _bounded_lines(self, response):
        if (
            self.strict_origin
            and response.headers.get("content-encoding", "identity") != "identity"
        ):
            raise A2AClientError("Compressed A2A streams are unsupported under bounded peer policy")
        pending = bytearray()
        async for chunk in response.aiter_bytes(65536):
            pending.extend(chunk)
            while b"\n" in pending:
                raw, _, rest = pending.partition(b"\n")
                if len(raw) > self.max_response_bytes:
                    raise A2AClientError("A2A stream line exceeds size limit")
                pending = bytearray(rest)
                yield raw.rstrip(b"\r").decode("utf-8")
            if len(pending) > self.max_response_bytes:
                raise A2AClientError("A2A stream line exceeds size limit")
        if pending:
            yield pending.rstrip(b"\r").decode("utf-8")


def _origin(url: str) -> tuple[str, str, int | None]:
    value = urlsplit(url)
    return (
        value.scheme.lower(),
        (value.hostname or "").lower(),
        value.port or (443 if value.scheme == "https" else 80),
    )


def _parse_status(value: dict) -> TaskStatus:
    state = str(value.get("state", "submitted"))
    normalized = state.removeprefix("TASK_STATE_").lower().replace("-", "_")
    try:
        parsed = TaskStatusValue(normalized)
    except ValueError as error:
        raise A2AClientError(f"Unknown A2A task state: {state}") from error
    return TaskStatus(
        parsed,
        _message_text(value.get("message")),
        value.get("agentName"),
        _parse_message(value["message"]) if isinstance(value.get("message"), dict) else None,
        value.get("timestamp"),
    )


def _parse_part(value: dict) -> Part:
    file = value.get("file")
    if not file and ("url" in value or "raw" in value):
        file = {
            "uri": value.get("url"),
            "bytes": value.get("raw"),
            "mimeType": value.get("mediaType"),
            "name": value.get("filename"),
        }
    text = value.get("text")
    return Part(
        text=text
        if isinstance(text, str)
        else text.get("text")
        if isinstance(text, dict)
        else None,
        data=value.get("data"),
        file=FilePart(
            url=file.get("uri") or file.get("url"),
            raw=file.get("bytes") or file.get("raw"),
            mime_type=file.get("mimeType") or file.get("mediaType"),
            filename=file.get("name") or file.get("filename"),
        )
        if file
        else None,
        mime_type=value.get("mediaType") or value.get("mimeType"),
        filename=value.get("filename"),
        metadata=value.get("metadata", {}),
    )


def _parse_message(value: dict) -> Message:
    role = str(value.get("role", "agent")).removeprefix("ROLE_").lower()
    if role not in {"user", "agent"}:
        raise A2AClientError(f"Unknown A2A message role: {role}")
    return Message(
        MessageRole(role),
        [_parse_part(p) for p in value.get("parts", [])],
        value.get("messageId"),
        value.get("contextId"),
        value.get("taskId"),
        value.get("metadata", {}),
    )


def _parse_artifact(value: dict) -> Artifact:
    return Artifact(
        parts=[_parse_part(p) for p in value.get("parts", [])],
        artifact_id=value.get("artifactId"),
        name=value.get("name"),
        mime_type=value.get("mediaType"),
        metadata=value.get("metadata", {}),
    )


def _httpx_cert(cert: str, key: str) -> str | tuple[str, str] | None:
    if cert and key:
        return (cert, key)
    if cert:
        return cert
    return None


def _merge_query(url: str, params: dict[str, str]) -> str:
    """Append extra query parameters without dropping those already on ``url``."""
    if not params:
        return url
    parts = urlsplit(url)
    existing = dict(parse_qsl(parts.query, keep_blank_values=True))
    existing.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(existing), parts.fragment))


_SPEAKABLE = frozenset(
    {
        ("JSONRPC", "1.0"),
        ("JSONRPC", "0.3"),
        ("HTTP+JSON", "1.0"),
    }
)


def _normalize_binding(value: str) -> str:
    binding = value.upper().replace(" ", "")
    if binding in {"HTTPJSON", "HTTP+JSON"}:
        return "HTTP+JSON"
    return binding


def _select_interface(
    interfaces: object, fallback_url: str
) -> tuple[tuple[str, str, str] | None, list[dict[str, str]]]:
    """First advertised interface this client can speak, else a 0.3 url fallback."""
    skipped: list[dict[str, str]] = []
    listed = interfaces if isinstance(interfaces, list) else []
    selected: tuple[str, str, str] | None = None
    for item in listed:
        if not isinstance(item, dict):
            skipped.append({"url": "", "binding": "", "version": "", "reason": "not an object"})
            continue
        url = str(item.get("url") or "").strip()
        binding = _normalize_binding(str(item.get("protocolBinding") or ""))
        version = str(item.get("protocolVersion") or "").strip()
        row = {"url": url, "binding": binding, "version": version}
        if not url:
            skipped.append({**row, "reason": "no url"})
            continue
        if (binding, version) in _SPEAKABLE:
            if selected is None:
                selected = (url, binding, version)
            else:
                skipped.append({**row, "reason": "later in preference"})
            continue
        skipped.append({**row, "reason": _unspeakable_reason(binding, version)})
    if selected is not None:
        return selected, skipped
    if listed:
        return None, skipped
    if fallback_url:
        return (fallback_url, "JSONRPC", "0.3"), skipped
    return None, skipped


def _unspeakable_reason(binding: str, version: str) -> str:
    speakable_bindings = {pair[0] for pair in _SPEAKABLE}
    if not binding:
        return "no protocolBinding"
    if not version:
        return "no protocolVersion"
    if binding not in speakable_bindings:
        return f"unsupported binding {binding}"
    return f"unsupported version {version} for {binding}"


def _reject_message(skipped: list[dict[str, str]]) -> str:
    header = "Agent Card has no interface this client can speak"
    speakable = "This client speaks JSON-RPC 1.0, JSON-RPC 0.3, and HTTP+JSON 1.0."
    if not skipped:
        return f"{header}, and no url to fall back to. {speakable}"
    lines = [f"{header}:"]
    for item in skipped:
        loc = item.get("url") or "(no url)"
        binding = item.get("binding") or "?"
        version = item.get("version") or "?"
        reason = item.get("reason") or "unusable"
        lines.append(f"  {binding} {version} at {loc}: {reason}")
    lines.append(speakable)
    return "\n".join(lines)


def _message_params(
    message: str,
    version: str,
    *,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    message_id: str | None = None,
    nonblocking: bool = False,
    metadata: dict | None = None,
) -> dict:
    if version == "0.3":
        message_obj: dict = {
            "messageId": message_id or str(uuid.uuid4()),
            "role": "user",
            "parts": [{"kind": "text", "text": message}],
        }
    else:
        message_obj = {
            "messageId": message_id or str(uuid.uuid4()),
            "role": "ROLE_USER",
            "parts": [{"text": message}],
        }
    if session_id:
        message_obj["contextId"] = session_id
    if task_id:
        message_obj["taskId"] = task_id
    if metadata:
        message_obj["metadata"] = metadata
    configuration = {"acceptedOutputModes": ["text/plain"]}
    if nonblocking:
        configuration.update(
            {"blocking": False} if version == "0.3" else {"returnImmediately": True}
        )
    return {
        "message": message_obj,
        "configuration": configuration,
    }


def _unwrap_body(data: object) -> dict:
    if not isinstance(data, dict):
        return {}
    if "jsonrpc" in data:
        result = data.get("result")
        if isinstance(result, dict) and "task" in result:
            return result["task"] if isinstance(result["task"], dict) else {}
        return result if isinstance(result, dict) else {}
    nested = data.get("task")
    return nested if isinstance(nested, dict) else data


def _message_text(message: object) -> str | None:
    if not isinstance(message, dict):
        return str(message) if message else None
    chunks = []
    for part in message.get("parts", []):
        if not isinstance(part, dict) or "text" not in part:
            continue
        text = part["text"]
        chunks.append(text if isinstance(text, str) else str(text.get("text", "")))
    return "".join(chunks) or None


class A2AClientPool:
    """Manage multiple A2A clients for orchestration.

    Usage:
        pool = A2AClientPool()
        await pool.add("gemini", "http://localhost:8001")
        await pool.add("claude", "http://localhost:8002")

        # Call specific agent
        result = await pool.call("gemini", "Write code")

        # Broadcast to all
        results = await pool.broadcast("Run tests")
    """

    def __init__(self):
        self._clients: dict[str, A2AClient] = {}

    async def add(self, name: str, url: str):
        """Add an A2A agent to the pool."""
        self._clients[name] = A2AClient(url)

    async def remove(self, name: str):
        """Remove an agent from the pool."""
        if name in self._clients:
            await self._clients[name].close()
            del self._clients[name]

    async def get_card(self, name: str) -> Optional[AgentCard]:
        """Get agent card for a specific agent."""
        if name not in self._clients:
            return None
        try:
            return await self._clients[name].get_agent_card()
        except AgentNotFoundError:
            return None

    async def call(self, name: str, message: str, **kwargs) -> Optional[Task]:
        """Call a specific agent by name."""
        if name not in self._clients:
            return None
        return await self._clients[name].send_message(message, **kwargs)

    async def broadcast(self, message: str, **kwargs) -> dict[str, Task]:
        """Send message to all agents in pool."""
        results = {}
        for name, client in self._clients.items():
            try:
                results[name] = await client.send_message(message, **kwargs)
            except Exception as e:
                results[name] = None
        return results

    async def get_skills(self, name: str) -> list[dict]:
        """Get skills/capabilities of an agent."""
        card = await self.get_card(name)
        if card:
            return [{"id": s.id, "name": s.name, "description": s.description} for s in card.skills]
        return []

    async def close_all(self):
        """Close all clients in pool."""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
