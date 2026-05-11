"""
A2A Tool - Call external A2A agents from SuperQode.

Integrates A2A client as a tool in SuperQode's tool registry.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..tools.base import Tool, ToolResult, ToolContext
from .client import A2AClient, A2AClientPool


class A2ACallTool(Tool):
    """Tool to call external A2A-compliant agents.
    
    Usage:
        a2a_call(agent_url="http://localhost:8000", message="Write tests")
    """

    def __init__(self):
        self._client_pool: Optional[A2AClientPool] = None

    @property
    def name(self) -> str:
        return "a2a_call"

    @property
    def description(self) -> str:
        return """Call an external A2A-compliant agent for specialized tasks.

Use this to delegate to external agents with specific capabilities:
- Security testing agents
- Code review agents  
- Specialized testing frameworks
- Other A2A-compliant coding agents

Arguments:
- agent_url: The A2A server URL (e.g., http://localhost:8000)
- message: The task to send to the agent
- agent_name: Optional name for caching the agent connection"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_url": {
                    "type": "string",
                    "description": "URL of the A2A agent server",
                },
                "message": {
                    "type": "string",
                    "description": "Task to send to the agent",
                },
                "agent_name": {
                    "type": "string",
                    "description": "Optional name to cache the agent (for repeated calls)",
                },
            },
            "required": ["agent_url", "message"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute A2A call to external agent."""
        agent_url = args.get("agent_url")
        message = args.get("message")
        agent_name = args.get("agent_name")

        if not agent_url:
            return ToolResult(success=False, output="", error="agent_url is required")

        if not message:
            return ToolResult(success=False, output="", error="message is required")

        # Use cached client if available
        if agent_name and self._client_pool:
            try:
                task = await self._client_pool.call(agent_name, message)
                if task:
                    return ToolResult(
                        success=True,
                        output=f"[A2A] {task.status.state.value}: {self._extract_result(task)}",
                        metadata={"task_id": task.task_id, "status": task.status.state.value},
                    )
            except Exception as e:
                return ToolResult(success=False, output="", error=str(e))

        # Direct call
        client = A2AClient(agent_url)

        try:
            # Get agent card for metadata
            try:
                card = await client.get_agent_card()
                agent_info = f"{card.name} (v{card.version})"
            except Exception:
                agent_info = agent_url

            # Send message
            task = await client.send_message(message)

            output = f"[A2A Agent: {agent_info}]\n"
            output += f"Status: {task.status.state.value}\n"
            output += f"Result: {self._extract_result(task)}"

            return ToolResult(
                success=task.status.state.value in ("completed", "working"),
                output=output,
                metadata={
                    "task_id": task.task_id,
                    "status": task.status.state.value,
                    "agent": agent_info,
                },
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=f"A2A call failed: {str(e)}")

        finally:
            await client.close()

    def _extract_result(self, task) -> str:
        """Extract text result from task."""
        if not hasattr(task, 'history') or not task.history:
            return "No response"
        
        for msg in reversed(task.history):
            if hasattr(msg, 'role') and msg.role.value == "agent":
                if hasattr(msg, 'parts') and msg.parts:
                    if hasattr(msg.parts[0], 'text') and msg.parts[0].text:
                        return msg.parts[0].text[:500]  # Truncate long results
        return "No result"


class A2ADiscoverTool(Tool):
    """Tool to discover and list available A2A agents.
    
    Usage:
        a2a_discover(registry_url="https://agents.example.com")
    """

    def __init__(self):
        self._discovered_agents: Dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "a2a_discover"

    @property
    def description(self) -> str:
        return """Discover A2A-compliant agents from a registry or URL.

Scans a registry or direct URL to find available A2A agents and their capabilities.
Use a2a_call to invoke discovered agents.

Arguments:
- registry_url: URL of agent registry or single agent endpoint
- scan_known: Also scan known A2A agent endpoints"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "registry_url": {
                    "type": "string",
                    "description": "URL of agent registry or single agent",
                },
                "scan_known": {
                    "type": "boolean",
                    "description": "Also scan known public A2A agents",
                    "default": False,
                },
            },
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Discover A2A agents."""
        registry_url = args.get("registry_url")
        scan_known = args.get("scan_known", False)

        discovered = []

        # Scan specific URL
        if registry_url:
            try:
                client = A2AClient(registry_url)
                card = await client.get_agent_card()
                await client.close()

                discovered.append({
                    "name": card.name,
                    "url": registry_url,
                    "description": card.description,
                    "version": card.version,
                    "skills": [{"id": s.id, "name": s.name} for s in card.skills],
                })
            except Exception as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Failed to discover agent: {str(e)}",
                )

        # Scan known public agents
        if scan_known:
            known_agents = [
                ("gemini", "http://localhost:8080"),
                ("claude", "http://localhost:8081"),
                ("codex", "http://localhost:8082"),
            ]

            for name, url in known_agents:
                try:
                    client = A2AClient(url)
                    card = await client.get_agent_card()
                    await client.close()

                    discovered.append({
                        "name": card.name,
                        "url": url,
                        "description": card.description,
                        "skills": [{"id": s.id, "name": s.name} for s in card.skills],
                    })
                except Exception:
                    pass  # Skip unavailable agents

        if not discovered:
            return ToolResult(
                success=True,
                output="No A2A agents discovered",
            )

        # Store for later use
        self._discovered_agents = {a["name"]: a for a in discovered}

        output = "Discovered A2A Agents:\n\n"
        for agent in discovered:
            output += f"• {agent['name']} ({agent['url']})\n"
            output += f"  {agent['description'][:80]}...\n"
            if agent.get('skills'):
                skills = ", ".join([s["name"] for s in agent['skills'][:3]])
                output += f"  Skills: {skills}\n"
            output += "\n"

        return ToolResult(
            success=True,
            output=output,
            metadata={"agents": discovered},
        )


def create_a2a_tools() -> list[Tool]:
    """Create A2A tools for the registry."""
    return [A2ACallTool(), A2ADiscoverTool()]