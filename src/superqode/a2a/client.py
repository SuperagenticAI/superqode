"""
A2A Client - Client for communicating with A2A-compliant agents.

Implements HTTP/gRPC client for Agent2Agent Protocol.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator, Optional

import httpx

from .types import (
    AgentCard,
    AgentCapabilities,
    Message,
    MessageRole,
    Part,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskStatus,
    TaskStatusValue,
    TextPart,
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
    ):
        """Initialize A2A client.

        Args:
            agent_url: URL of the A2A agent server
            http_client: Optional existing httpx client
            timeout: Request timeout in seconds
        """
        self.agent_url = agent_url.rstrip("/")
        self.timeout = timeout
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    async def close(self):
        """Close the HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> "A2AClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def get_agent_card(self) -> AgentCard:
        """GET /agentCard - Discover agent capabilities.

        Returns:
            AgentCard with agent metadata and skills

        Raises:
            AgentNotFoundError: If agent is not available
        """
        url = f"{self.agent_url}/agentCard"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
            return self._parse_agent_card(data)
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

        skills = []
        for s in data.get("skills", []):
            skills.append(
                {
                    "id": s.get("id", ""),
                    "name": s.get("name", ""),
                    "description": s.get("description", ""),
                }
            )

        return AgentCard(
            name=data.get("name", "Unknown"),
            description=data.get("description", ""),
            url=data.get("url", self.agent_url),
            version=data.get("version", "1.0"),
            capabilities=capabilities,
            skills=skills,
            supported_interfaces=data.get("supportedInterfaces", []),
            default_input_modes=data.get("defaultInputModes", ["text"]),
            default_output_modes=data.get("defaultOutputModes", ["text"]),
        )

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
        url = f"{self.agent_url}/message:send"

        message_obj = {
            "role": "user",
            "parts": [{"text": {"text": message}}],
        }
        if session_id:
            message_obj["sessionId"] = session_id

        body = {"message": message_obj}
        if task_id:
            body["taskId"] = task_id

        try:
            response = await self._http.post(url, json=body)
            response.raise_for_status()
            data = response.json()

            return self._parse_task(data)
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
        url = f"{self.agent_url}/message:stream"

        message_obj = {
            "role": "user",
            "parts": [{"text": {"text": message}}],
            "messageId": str(uuid.uuid4()),
        }
        if session_id:
            message_obj["sessionId"] = session_id

        body = {"message": message_obj}

        try:
            async with self._http.stream("POST", url, json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        data = line.strip()
                        # Handle SSE format: "data: {...}"
                        if data.startswith("data: "):
                            data = data[6:]
                        yield StreamResponse(type="message", data=data)
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
        url = f"{self.agent_url}/tasks/{task_id}"

        response = await self._http.get(url)
        response.raise_for_status()
        data = response.json()

        return self._parse_task(data)

    async def cancel_task(self, task_id: str) -> Task:
        """POST /tasks/{id}:cancel - Cancel a running task.

        Args:
            task_id: ID of the task to cancel

        Returns:
            Task in canceled state
        """
        url = f"{self.agent_url}/tasks/{task_id}:cancel"

        response = await self._http.post(url, json={})
        response.raise_for_status()
        data = response.json()

        return self._parse_task(data)

    async def subscribe_task(self, task_id: str) -> AsyncIterator[StreamResponse]:
        """GET /tasks/{id}:subscribe - Subscribe to task updates.

        Args:
            task_id: ID of the task to subscribe to

        Yields:
            StreamResponse with task updates
        """
        url = f"{self.agent_url}/tasks/{task_id}:subscribe"

        try:
            async with self._http.stream("GET", url) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        data = line.strip()
                        if data.startswith("data: "):
                            data = data[6:]
                        yield StreamResponse(type="task_update", data=data)
        except httpx.HTTPStatusError as e:
            yield StreamResponse(type="error", data=str(e))

    def _parse_task(self, data: dict) -> Task:
        """Parse JSON response into Task."""
        status_data = data.get("status", {})
        state_str = status_data.get("state", "submitted")

        try:
            state = TaskStatusValue(state_str)
        except ValueError:
            state = TaskStatusValue.SUBMITTED

        status = TaskStatus(
            state=state,
            message=status_data.get("message"),
            agent_name=status_data.get("agentName"),
        )

        # Parse history
        history = []
        for msg in data.get("history", []):
            role = MessageRole(msg.get("role", "user"))
            parts = []
            for p in msg.get("parts", []):
                if "text" in p:
                    parts.append(Part(text=p["text"].get("text", "")))
                elif "data" in p:
                    parts.append(Part(data=p["data"]))
            history.append(Message(role=role, parts=parts))

        return Task(
            task_id=data.get("taskId", ""),
            status=status,
            history=history,
            artifacts=data.get("artifacts", []),
            metadata=data.get("metadata", {}),
            context_id=data.get("contextId"),
        )


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
