"""
SuperQode A2A Integration - Agent-to-Agent Protocol Support.

A2A (Agent2Agent) Protocol enables multi-agent communication and orchestration.

Quick Start:
    # As A2A Client - call external A2A agents
    from superqode.a2a import A2AClient
    
    client = A2AClient("http://gemini-cli:8000")
    card = await client.get_agent_card()
    result = await client.send_message("Write a function")

    # As A2A Server - expose SuperQode
    from superqode.a2a import create_a2a_server
    
    server = await create_a2a_server(config)
    await server.start()

    # Workflow orchestration
    from superqode.a2a import A2AWorkflowEngine
    
    engine = A2AWorkflowEngine()
    result = await engine.parallel([
        {"url": "http://test-agent:8000", "prompt": "Run tests"},
        {"url": "http://lint-agent:8000", "prompt": "Lint code"},
    ])

    # Registry
    from superqode.a2a import A2ARegistry
    
    registry = A2ARegistry()
    await registry.add("gemini", "http://localhost:8000")
    agents = registry.get_by_skill("testing")
"""

from .client import A2AClient, A2AClientPool, A2AClientError
from .server import A2AServer, A2AServerConfig, create_a2a_server
from .types import (
    AgentCard,
    AgentCapabilities,
    AgentProvider,
    AgentSkill,
    Message,
    MessageRole,
    Part,
    StreamResponse,
    Task,
    TaskStatus,
    TaskStatusValue,
)
from .workflows import (
    A2AWorkflowEngine,
    A2ATool,
    WorkflowPattern,
    WorkflowResult,
    WorkflowStep,
)
from .registry import A2ARegistry, A2AAgentEntry, discover_known_agents
from .presets import A2APresets, WorkflowPreset, get_presets
from .skills import SkillMapper, get_skill_mapper, RoleMapping

__all__ = [
    # Client
    "A2AClient",
    "A2AClientPool", 
    "A2AClientError",
    
    # Server
    "A2AServer",
    "A2AServerConfig", 
    "create_a2a_server",
    
    # Types
    "AgentCard",
    "AgentCapabilities",
    "AgentProvider", 
    "AgentSkill",
    "Message",
    "MessageRole",
    "Part",
    "StreamResponse",
    "Task",
    "TaskStatus",
    "TaskStatusValue",
    
    # Workflows
    "A2AWorkflowEngine",
    "A2ATool",
    "WorkflowPattern",
    "WorkflowResult", 
    "WorkflowStep",
    
    # Registry
    "A2ARegistry",
    "A2AAgentEntry",
    "discover_known_agents",
    
    # Presets
    "A2APresets",
    "WorkflowPreset",
    "get_presets",
    
    # Skills
    "SkillMapper",
    "get_skill_mapper",
    "RoleMapping",
]