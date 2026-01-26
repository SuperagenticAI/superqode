"""ACP agents package for SuperQode."""

from typing import TYPE_CHECKING

from .discovery import AgentReadError, get_agent_by_identity, get_agent_by_short_name, read_agents
from .schema import Agent, AgentProtocol, AgentType, Command, OS, Tag
from .registry import (
    AGENTS,
    AgentDef,
    AgentProtocol as AgentProtocolNew,
    AgentStatus,
    get_agent,
    get_supported_agents,
    get_acp_agents,
    get_external_agents,
    get_all_agent_ids,
    is_agent_available,
)

if TYPE_CHECKING:
    from .client import ACPAgentManager, SuperQodeACPClient


def __getattr__(name):
    if name in ("ACPAgentManager", "SuperQodeACPClient"):
        from .client import ACPAgentManager, SuperQodeACPClient

        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Client
    "ACPAgentManager",
    "SuperQodeACPClient",
    # Discovery
    "AgentReadError",
    "get_agent_by_identity",
    "get_agent_by_short_name",
    "read_agents",
    # Schema (legacy)
    "Agent",
    "AgentProtocol",
    "AgentType",
    "Command",
    "OS",
    "Tag",
    # New Registry
    "AGENTS",
    "AgentDef",
    "AgentProtocolNew",
    "AgentStatus",
    "get_agent",
    "get_supported_agents",
    "get_acp_agents",
    "get_external_agents",
    "get_all_agent_ids",
    "is_agent_available",
]
