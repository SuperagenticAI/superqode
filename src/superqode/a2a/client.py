"""
A2A Client - Client for communicating with A2A-compliant agents.

Implements HTTP/gRPC client for Agent2Agent Protocol.
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator, Optional

import httpx

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

    pass


class AgentNotFoundError(A2AClientError):
    """Agent not found or not responding."""

    pass


class TaskFailedError(A2AClientError):
    """Task failed on remote agent."""

    pass


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
        self._agent_card: AgentCard | None = None
        self.timeout = timeout
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._http.headers.setdefault("A2A-Version", "1.0")
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
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
            card = self._parse_agent_card(data)
            self._interface_url = card.url.strip().rstrip("/")
            self._agent_card = card
            return card
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise AgentNotFoundError(f"Agent not found at {url}") from e
            raise A2AClientError(f"Failed to get agent card: {e}") from e
        except httpx.RequestError as e:
            raise AgentNotFoundError(f"Cannot connect to agent: {e}") from e

    def _parse_agent_card(self, data: dict) -> AgentCard:
        """Parse JSON response into AgentCard."""
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
        interface_url = next(
            (
                str(item.get("url") or "").strip()
                for item in interfaces
                if item.get("protocolBinding", "").upper() == "HTTP+JSON"
                and item.get("protocolVersion") == "1.0"
                and str(item.get("url") or "").strip()
            ),
            None,
        )
        if interfaces and interface_url is None:
            raise A2AClientError("Agent Card does not advertise A2A 1.0 HTTP+JSON")

        fallback = data.get("url", self.agent_url)
        if isinstance(fallback, str):
            fallback = fallback.strip() or self.agent_url

        return AgentCard(
            name=data.get("name", "Unknown"),
            description=data.get("description", ""),
            url=interface_url or fallback,
            version=data.get("version", "1.0"),
            capabilities=capabilities,
            skills=skills,
            supported_interfaces=interfaces,
            default_input_modes=data.get("defaultInputModes", ["text"]),
            default_output_modes=data.get("defaultOutputModes", ["text"]),
        )

    async def _operation_url(self, path: str) -> str:
        """Resolve an operation against the interface selected from discovery."""
        if self._interface_url is None:
            await self.get_agent_card()
        return f"{self._interface_url}/{path.lstrip('/')}"

    async def send_message(
        self,
        message: str,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Task:
        """POST /message:send - Send a message to the agent.

        Args:
            message: Text message to send
            session_id: Optional session/context ID
            task_id: Optional task ID to continue

        Returns:
            Task with status and results

        Raises:
            TaskFailedError: If task fails
        """
        url = await self._operation_url("message:send")

        message_obj = {
            "messageId": str(uuid.uuid4()),
            "role": "ROLE_USER",
            "parts": [{"text": message}],
        }
        if session_id:
            message_obj["contextId"] = session_id
        if task_id:
            message_obj["taskId"] = task_id

        body = {
            "message": message_obj,
            "configuration": {"acceptedOutputModes": ["text/plain"]},
        }

        try:
            response = await self._http.post(url, json=body)
            response.raise_for_status()
            data = response.json()

            return self._parse_task(data.get("task", data))
        except httpx.HTTPStatusError as e:
            raise TaskFailedError(f"Task failed: {e}") from e
        except httpx.RequestError as e:
            raise A2AClientError(f"Request failed: {e}") from e

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
        url = await self._operation_url("message:stream")

        message_obj = {
            "role": "ROLE_USER",
            "parts": [{"text": message}],
            "messageId": str(uuid.uuid4()),
        }
        if session_id:
            message_obj["contextId"] = session_id

        body = {
            "message": message_obj,
            "configuration": {"acceptedOutputModes": ["text/plain"]},
        }

        try:
            async with self._http.stream("POST", url, json=body) as response:
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
        url = await self._operation_url(f"tasks/{task_id}")

        response = await self._http.get(url)
        response.raise_for_status()
        data = response.json()

        return self._parse_task(data.get("task", data))

    async def cancel_task(self, task_id: str) -> Task:
        """POST /tasks/{id}:cancel - Cancel a running task.

        Args:
            task_id: ID of the task to cancel

        Returns:
            Task in canceled state
        """
        url = await self._operation_url(f"tasks/{task_id}:cancel")

        response = await self._http.post(url, json={})
        response.raise_for_status()
        data = response.json()

        return self._parse_task(data.get("task", data))

    async def subscribe_task(self, task_id: str) -> AsyncIterator[StreamResponse]:
        """GET /tasks/{id}:subscribe - Subscribe to task updates.

        Args:
            task_id: ID of the task to subscribe to

        Yields:
            StreamResponse with task updates
        """
        url = await self._operation_url(f"tasks/{task_id}:subscribe")

        try:
            async with self._http.stream("GET", url) as response:
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
