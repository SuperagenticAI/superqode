"""
A2A Client - Client for communicating with A2A-compliant agents.

Implements HTTP/gRPC client for Agent2Agent Protocol.
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator, Optional

import httpx

from .inspect import InspectLog
from .types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    Artifact,
    Message,
    MessageRole,
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
        self.timeout = timeout
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self.inspect = InspectLog()
        if bearer_token:
            self._http.headers.setdefault("Authorization", f"Bearer {bearer_token}")

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
        url = f"{self.agent_url}/.well-known/agent-card.json"
        self.inspect.request(
            "GET",
            url,
            note="agent-card",
            headers={str(key): str(value) for key, value in self._http.headers.items()},
        )
        try:
            response = await self._http.get(url, follow_redirects=True)
        except httpx.RequestError as e:
            summary = f"Cannot connect to agent: {e}"
            self.inspect.error(summary, url=url)
            raise AgentNotFoundError(summary, inspect=self.inspect) from e

        body = response.text
        self.inspect.response(response.status_code, "GET", str(response.request.url), body=body)
        if response.status_code == 404:
            raise AgentNotFoundError(
                f"No Agent Card at {url} (404). SuperQode fetches "
                "/.well-known/agent-card.json from the origin.",
                inspect=self.inspect,
            )
        if response.status_code in {401, 403}:
            raise A2AClientError(
                f"Agent Card at {url} returned {response.status_code}. "
                "Discovery is protected; pass a Bearer if you have one.",
                inspect=self.inspect,
            )
        if response.status_code >= 400:
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

        selected, skipped = _select_interface(interfaces, fallback)
        listed = interfaces if isinstance(interfaces, list) else []
        note = ""
        if selected is not None and not listed:
            note = "no supportedInterfaces; using card url as JSONRPC 0.3"
        self.inspect.choice(selected, skipped, note=note)
        if selected is None:
            raise A2AClientError(_reject_message(skipped), inspect=self.inspect)
        interface_url, binding, version = selected

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

    async def _ensure_interface(self) -> tuple[str, str, str]:
        if self._interface_url is None or self._binding is None or self._protocol_version is None:
            await self.get_agent_card()
        assert self._interface_url and self._binding and self._protocol_version
        return self._interface_url, self._binding, self._protocol_version

    def _version_headers(self, version: str) -> dict[str, str]:
        # A 1.0 method under a missing header is negotiated as 0.3 and rejected.
        # A 0.3 client sends no version header.
        if version == "1.0":
            return {"A2A-Version": "1.0"}
        return {}

    async def _operation_url(self, path: str) -> str:
        """Resolve a REST path against the selected HTTP+JSON interface."""
        interface_url, _, _ = await self._ensure_interface()
        return f"{interface_url}/{path.lstrip('/')}"

    async def send_message(
        self,
        message: str,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Task:
        """Send a message on the binding advertised first on the card."""
        interface_url, binding, version = await self._ensure_interface()
        params = _message_params(message, version, session_id=session_id, task_id=task_id)
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
            return self._parse_task(data)
        except A2AClientError:
            raise
        except httpx.HTTPStatusError as e:
            raise TaskFailedError(f"Task failed: {e}", inspect=self.inspect) from e
        except httpx.RequestError as e:
            raise A2AClientError(f"Request failed: {e}", inspect=self.inspect) from e

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
        encoded = json.dumps(json_body) if json_body is not None else ""
        merged_headers = {str(key): str(value) for key, value in self._http.headers.items()}
        if headers:
            merged_headers.update(headers)
        self.inspect.request(method, url, note=note, body=encoded, headers=merged_headers)
        try:
            request_kwargs: dict = {
                "headers": headers,
                "follow_redirects": follow_redirects,
            }
            if json_body is not None:
                request_kwargs["json"] = json_body
            response = await self._http.request(method, url, **request_kwargs)
        except httpx.RequestError as e:
            self.inspect.error(f"Request failed: {e}", url=url)
            raise A2AClientError(f"Request failed: {e}", inspect=self.inspect) from e
        self.inspect.response(
            response.status_code, method, str(response.request.url), body=response.text
        )
        if response.status_code >= 400:
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

    async def _jsonrpc(
        self, url: str, method: str, params: dict, version: str
    ) -> dict:
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
            url = interface_url
            body: dict = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": method,
                "params": params,
            }
            self.inspect.request("POST", url, note=f"{method} stream JSONRPC {version}")
        else:
            url = f"{interface_url}/message:stream"
            body = params
            self.inspect.request("POST", url, note=f"stream HTTP+JSON {version}")

        try:
            async with self._http.stream(
                "POST",
                url,
                json=body,
                headers=self._version_headers(version),
                follow_redirects=True,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    data = line.strip()
                    if not data.startswith("data:"):
                        continue
                    data = data[5:].lstrip()
                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        parsed = data
                    yield StreamResponse(type="message", data=parsed)
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
                method = "TaskResubscription" if version == "1.0" else "tasks/resubscribe"
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
                    follow_redirects=True,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        data = line.strip()
                        if not data.startswith("data:"):
                            continue
                        data = data[5:].lstrip()
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            parsed = data
                        yield StreamResponse(type="task_update", data=parsed)
                return
            async with self._http.stream("GET", url, headers=stream_headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    data = line.strip()
                    if not data.startswith("data:"):
                        continue
                    data = data[5:].lstrip()
                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        parsed = data
                    yield StreamResponse(type="task_update", data=parsed)
        except httpx.HTTPStatusError as e:
            yield StreamResponse(type="error", data=str(e))

    def _parse_task(self, data: dict) -> Task:
        """Parse JSON response into Task."""
        if not isinstance(data, dict):
            data = {}
        status_data = data.get("status", {})
        state_str = status_data.get("state", "submitted")
        normalized_state = {
            "TASK_STATE_SUBMITTED": "submitted",
            "TASK_STATE_WORKING": "working",
            "TASK_STATE_INPUT_REQUIRED": "input_required",
            "TASK_STATE_COMPLETED": "completed",
            "TASK_STATE_FAILED": "failed",
            "TASK_STATE_CANCELED": "canceled",
            "TASK_STATE_REJECTED": "rejected",
            "TASK_STATE_AUTH_REQUIRED": "input_required",
        }.get(str(state_str), str(state_str).lower())

        try:
            state = TaskStatusValue(normalized_state)
        except ValueError:
            state = TaskStatusValue.SUBMITTED

        status = TaskStatus(
            state=state,
            message=_message_text(status_data.get("message")),
            agent_name=status_data.get("agentName"),
        )

        # Parse history
        history = []
        for msg in data.get("history", []):
            role_value = str(msg.get("role", "user"))
            role = MessageRole.AGENT if role_value in {"agent", "ROLE_AGENT"} else MessageRole.USER
            parts = []
            for p in msg.get("parts", []):
                if "text" in p:
                    text = p["text"]
                    parts.append(Part(text=text if isinstance(text, str) else text.get("text", "")))
                elif "data" in p:
                    parts.append(Part(data=p["data"]))
            history.append(Message(role=role, parts=parts))

        artifacts = []
        for item in data.get("artifacts", []):
            parts = [
                Part(
                    text=p.get("text") if isinstance(p.get("text"), str) else None,
                    data=p.get("data"),
                    mime_type=p.get("mediaType"),
                    filename=p.get("filename"),
                )
                for p in item.get("parts", [])
            ]
            artifacts.append(
                Artifact(
                    artifact_id=item.get("artifactId"),
                    name=item.get("name"),
                    parts=parts,
                    metadata=item.get("metadata", {}),
                )
            )

        return Task(
            task_id=data.get("id", data.get("taskId", "")),
            status=status,
            history=history,
            artifacts=artifacts,
            metadata=data.get("metadata", {}),
            context_id=data.get("contextId"),
        )


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
            skipped.append(
                {"url": "", "binding": "", "version": "", "reason": "not an object"}
            )
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
) -> dict:
    if version == "0.3":
        message_obj: dict = {
            "messageId": str(uuid.uuid4()),
            "role": "user",
            "parts": [{"kind": "text", "text": message}],
        }
    else:
        message_obj = {
            "messageId": str(uuid.uuid4()),
            "role": "ROLE_USER",
            "parts": [{"text": message}],
        }
    if session_id:
        message_obj["contextId"] = session_id
    if task_id:
        message_obj["taskId"] = task_id
    return {
        "message": message_obj,
        "configuration": {"acceptedOutputModes": ["text/plain"]},
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
