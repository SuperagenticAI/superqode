"""
A2A Server - Expose SuperQode as an A2A-compliant agent.

Implements A2A protocol endpoints for agent communication.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent.loop import AgentLoop, AgentConfig, AgentMessage, AgentResponse
from .types import (
    AgentCard,
    AgentCapabilities,
    AgentProvider,
    AgentSkill,
    Message,
    MessageRole,
    Part,
    SendMessageRequest,
    Task,
    TaskStatus,
    TaskStatusValue,
    create_agent_card,
)


class A2AServerConfig(BaseModel):
    """Configuration for A2A server."""

    name: str = "SuperQode"
    description: str = "Coding agent with development and operations modes"
    version: str = "1.0"
    url: str = "http://localhost:8000"
    streaming: bool = True
    push_notifications: bool = False


class A2ATaskStore(BaseModel):
    """In-memory task storage."""

    tasks: Dict[str, Task] = {}


class A2AServer:
    """Expose SuperQode as an A2A-compliant agent.

    Usage:
        config = A2AServerConfig(url="http://localhost:8080")
        server = A2AServer(agent_loop, config)
        await server.start()
    """

    def __init__(
        self,
        agent_loop: Optional[AgentLoop] = None,
        config: Optional[A2AServerConfig] = None,
    ):
        self.agent_loop = agent_loop
        self.config = config or A2AServerConfig()
        self.app = FastAPI(title="SuperQode A2A Server")
        self._task_store = A2ATaskStore()
        self._setup_routes()

    def _setup_routes(self):
        """Set up A2A protocol routes."""

        @self.app.get("/agentCard")
        async def get_agent_card() -> Dict[str, Any]:
            """GET /agentCard - Return agent metadata."""
            skills = self._get_superqode_skills()

            return {
                "name": self.config.name,
                "description": self.config.description,
                "url": self.config.url,
                "version": self.config.version,
                "capabilities": {
                    "streaming": self.config.streaming,
                    "pushNotifications": self.config.push_notifications,
                    "extendedAgentCard": False,
                },
                "provider": {
                    "organization": "Superagentic AI",
                    "url": "https://super-agentic.ai",
                },
                "skills": skills,
                "defaultInputModes": ["text"],
                "defaultOutputModes": ["text", "code"],
                "supportedInterfaces": [{"protocolBinding": "http", "protocolVersion": "1.0"}],
            }

        @self.app.post("/message:send")
        async def send_message(request: SendMessageRequest) -> Dict[str, Any]:
            """POST /message:send - Send message and get response."""
            if not self.agent_loop:
                raise HTTPException(status_code=503, detail="Agent not initialized")

            # Extract message content
            content = ""
            if request.message and request.message.parts:
                for part in request.message.parts:
                    if part.text:
                        content = part.text
                        break

            if not content:
                raise HTTPException(status_code=400, detail="No message content")

            # Create task
            task_id = str(uuid.uuid4())

            try:
                # Run agent
                response: AgentResponse = await self.agent_loop.run(content)

                # Build response
                result = {
                    "taskId": task_id,
                    "status": {
                        "state": "completed" if response.content else "failed",
                        "message": None,
                    },
                    "history": [
                        {
                            "role": "user",
                            "parts": [{"text": {"text": content}}],
                        },
                        {
                            "role": "agent",
                            "parts": [{"text": {"text": response.content or "No response"}}],
                        },
                    ],
                    "metadata": {
                        "iterations": response.iterations,
                        "tool_calls": response.tool_calls_made,
                    },
                }

                return result

            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/message:stream")
        async def stream_message(request: SendMessageRequest) -> StreamingResponse:
            """POST /message:stream - Send message with streaming response."""
            if not self.agent_loop:
                raise HTTPException(status_code=503, detail="Agent not initialized")

            content = ""
            if request.message and request.message.parts:
                for part in request.message.parts:
                    if part.text:
                        content = part.text
                        break

            async def event_generator():
                yield 'data: {"type": "message", "content": "Processing..."}\n\n'

                try:
                    response: AgentResponse = await self.agent_loop.run(content)

                    # Stream the response
                    for chunk in self._chunk_response(response.content):
                        yield f"data: {{'type': 'message', 'content': '{chunk}'}}\n\n"

                    yield "data: {'type': 'done'}\n\n"

                except Exception as e:
                    yield f"data: {{'type': 'error', 'message': '{str(e)}'}}\n\n"

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )

        @self.app.get("/tasks/{task_id}")
        async def get_task(task_id: str) -> Dict[str, Any]:
            """GET /tasks/{id} - Get task state."""
            # For now, tasks are not persisted
            raise HTTPException(status_code=404, detail="Task not found")

        @self.app.post("/tasks/{task_id}:cancel")
        async def cancel_task(task_id: str) -> Dict[str, Any]:
            """POST /tasks/{id}:cancel - Cancel a running task."""
            if self.agent_loop:
                self.agent_loop.cancel()

            return {
                "taskId": task_id,
                "status": {"state": "canceled"},
            }

        @self.app.get("/tasks/{task_id}:subscribe")
        async def subscribe_task(task_id: str) -> StreamingResponse:
            """GET /tasks/{id}:subscribe - Subscribe to task updates."""

            async def event_generator():
                yield "data: {'type': 'task_update', 'state': 'working'}\n\n"
                await asyncio.sleep(1)
                yield "data: {'type': 'task_update', 'state': 'completed'}\n\n"

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
            )

    def _get_superqode_skills(self) -> list[Dict[str, str]]:
        """Get SuperQode skills as A2A skills."""
        return [
            {
                "id": "qe_unit",
                "name": "Unit Testing",
                "description": "Run unit tests and analyze coverage",
            },
            {
                "id": "qe_integration",
                "name": "Integration Testing",
                "description": "Run integration and API tests",
            },
            {
                "id": "qe_security",
                "name": "Security Testing",
                "description": "Run security scans and vulnerability detection",
            },
            {
                "id": "qe_accessibility",
                "name": "Accessibility Testing",
                "description": "Test for accessibility compliance (WCAG)",
            },
            {
                "id": "dev",
                "name": "Development",
                "description": "Code development and refactoring",
            },
            {
                "id": "devops",
                "name": "DevOps",
                "description": "Deployment and infrastructure automation",
            },
            {
                "id": "code_review",
                "name": "Code Review",
                "description": "Review code for quality and best practices",
            },
            {
                "id": "debug",
                "name": "Debugging",
                "description": "Debug and fix issues in code",
            },
        ]

    def _chunk_response(self, content: str, chunk_size: int = 50) -> list[str]:
        """Chunk response content for streaming."""
        if not content:
            return []
        words = content.split()
        chunks = []
        for i in range(0, len(words), chunk_size):
            chunks.append(" ".join(words[i : i + chunk_size]))
        return chunks


import asyncio


async def create_a2a_server(
    agent_config: AgentConfig,
    server_url: str = "http://localhost:8000",
    runtime: Optional[str] = None,
) -> A2AServer:
    """Create and configure an A2A server.

    Args:
        agent_config: Agent configuration
        server_url: URL where server will be accessible
        runtime: Agent runtime backend name (builtin/adk/openai-agents); defaults to builtin

    Returns:
        Configured A2AServer instance
    """
    from ..providers.gateway.litellm_gateway import LiteLLMGateway
    from ..tools.base import ToolRegistry
    from ..runtime import create_runtime, resolve_runtime_name

    gateway = LiteLLMGateway()
    tools = ToolRegistry.full()

    runtime_obj = create_runtime(
        resolve_runtime_name(cli=runtime),
        gateway=gateway,
        tools=tools,
        config=agent_config,
    )
    # A2AServer currently expects an AgentLoop. The builtin runtime exposes it
    # via .loop; non-builtin runtimes will need a follow-up adapter in Phase 2.
    agent_loop = getattr(runtime_obj, "loop", runtime_obj)

    config = A2AServerConfig(
        name="SuperQode",
        description="Quality-oriented coding agent",
        version="1.0",
        url=server_url,
    )

    return A2AServer(agent_loop=agent_loop, config=config)
