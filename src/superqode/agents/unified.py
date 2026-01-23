"""Unified agent interface for both ACP agents and SuperQode models."""

import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from .client import ACPAgentManager
from .schema import ResolvedRole


@dataclass
class AgentResponse:
    """Response from an agent."""

    content: str
    agent_type: str
    agent_name: str
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class UnifiedAgent(ABC):
    """Abstract base class for unified agent interface."""

    def __init__(self, role_config: ResolvedRole):
        self.role_config = role_config
        self.agent_type = role_config.agent_type
        self.agent_name = role_config.coding_agent

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the agent."""
        pass

    @abstractmethod
    async def send_message(self, message: str, **kwargs) -> AgentResponse:
        """Send a message to the agent and get response."""
        pass

    @abstractmethod
    async def get_capabilities(self) -> List[str]:
        """Get agent capabilities."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up agent resources."""
        pass

    @property
    def description(self) -> str:
        """Get agent description."""
        return self.role_config.description

    @property
    def job_description(self) -> str:
        """Get agent job description."""
        return self.role_config.job_description


class SuperQodeAgent(UnifiedAgent):
    """Agent implementation for SuperQode models (via LLM providers) with full tool access."""

    def __init__(self, role_config: ResolvedRole):
        super().__init__(role_config)
        self.provider = role_config.provider
        self.model = role_config.model
        self._initialized = False
        self._agent_loop = None
        self._working_directory = Path.cwd()

    async def initialize(self) -> bool:
        """Initialize the SuperQode agent with AgentLoop and tools."""
        if not self.provider or not self.model:
            return False

        # Import here to avoid circular imports
        from ..agent.loop import AgentLoop, AgentConfig
        from ..agent.system_prompts import SystemPromptLevel, get_job_description_prompt
        from ..tools.base import ToolRegistry
        from ..providers.gateway.litellm_gateway import LiteLLMGateway

        # Initialize gateway
        gateway = LiteLLMGateway()

        # Initialize tools
        tools = ToolRegistry.default()

        # Build job description prompt (OSS does not merge expert prompts)
        # Get base job description from role config
        base_job_description = self.role_config.job_description or ""
        merged_job_description = get_job_description_prompt(
            base_job_description, role_config=self.role_config
        )

        # Determine system prompt level (OSS uses standard guidance)
        system_level = SystemPromptLevel.STANDARD

        # Create agent config with merged job description
        config = AgentConfig(
            provider=self.provider,
            model=self.model,
            system_prompt_level=system_level,
            custom_system_prompt=None,  # Job description is added via config
            job_description=merged_job_description,
            working_directory=self._working_directory,
            tools_enabled=True,
            temperature=0.7,
            max_tokens=4000,
        )

        # Create agent loop (on_thinking will be set via send_message if provided)
        self._agent_loop = AgentLoop(
            gateway=gateway,
            tools=tools,
            config=config,
            parallel_tools=True,
        )

        self._initialized = True
        return True

    async def send_message(self, message: str, **kwargs) -> AgentResponse:
        """Send message to SuperQode model using AgentLoop with tools."""
        if not self._initialized or not self._agent_loop:
            raise RuntimeError("Agent not initialized")

        # Set up thinking callback if provided
        on_thinking = kwargs.get("on_thinking")
        if on_thinking:
            self._agent_loop.on_thinking = on_thinking

        try:
            # Use AgentLoop to run with tools
            response = await self._agent_loop.run(message)

            return AgentResponse(
                content=response.content,
                agent_type="superqode",
                agent_name=f"{self.provider}/{self.model}",
                metadata={
                    "provider": self.provider,
                    "model": self.model,
                    "tool_calls_made": response.tool_calls_made,
                    "iterations": response.iterations,
                    "stopped_reason": response.stopped_reason,
                    "error": response.error,
                },
            )
        except Exception as e:
            return AgentResponse(
                content=f"Error communicating with {self.provider}/{self.model}: {str(e)}",
                agent_type="superqode",
                agent_name=f"{self.provider}/{self.model}",
                metadata={"error": str(e)},
            )

    async def send_message_streaming(self, message: str, **kwargs) -> AsyncIterator[str]:
        """Send message with streaming output."""
        if not self._initialized or not self._agent_loop:
            raise RuntimeError("Agent not initialized")

        async for chunk in self._agent_loop.run_streaming(message):
            yield chunk

    async def get_capabilities(self) -> List[str]:
        """Get SuperQode agent capabilities."""
        capabilities = ["text_generation", "code_generation", "analysis"]

        # Add provider-specific capabilities
        if self.provider == "anthropic":
            capabilities.extend(["reasoning", "code_review", "architecture"])
        elif self.provider == "openai":
            capabilities.extend(["creativity", "problem_solving", "research"])
        elif self.provider == "google":
            capabilities.extend(["multimodal", "analysis", "synthesis"])
        elif self.provider == "deepseek":
            capabilities.extend(["deep_reasoning", "mathematical", "logical"])
        elif self.provider == "zhipuai":
            capabilities.extend(["multilingual", "vision", "reasoning"])

        return capabilities

    async def cleanup(self) -> None:
        """Clean up SuperQode agent resources."""
        self._agent_loop = None
        self._initialized = False


class ACPUnifiedAgent(UnifiedAgent):
    """Agent implementation for ACP coding agents."""

    def __init__(self, role_config: ResolvedRole):
        super().__init__(role_config)
        self.agent_manager: Optional[ACPAgentManager] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the ACP agent."""
        try:
            self.agent_manager = ACPAgentManager()

            # Get agent command from discovery
            from .discovery import get_agent_by_short_name

            agent_config = get_agent_by_short_name(self.agent_name)

            if not agent_config:
                return False

            # Get run command for the agent
            run_command = agent_config.get("run_command", {}).get("*")
            if not run_command:
                return False

            # Initialize the agent manager
            success = await self.agent_manager.connect_to_agent(run_command)
            if success:
                self._initialized = True
                return True

        except Exception:
            pass

        return False

    async def send_message(self, message: str, **kwargs) -> AgentResponse:
        """Send message to ACP agent."""
        if not self._initialized or not self.agent_manager:
            raise RuntimeError("ACP agent not initialized")

        try:
            # Send message to ACP agent
            await self.agent_manager.send_message(message)

            # Wait a bit for response
            await asyncio.sleep(0.1)

            # Get responses from the queue
            responses = await self.agent_manager.receive_messages()

            # Combine all responses
            content_parts = []
            for response in responses:
                if hasattr(response, "content"):
                    # Handle different response types
                    if hasattr(response, "text"):
                        content_parts.append(response.text)
                    elif hasattr(response, "content"):
                        content_parts.append(str(response.content))
                    else:
                        content_parts.append(str(response))

            content = "\n".join(content_parts) if content_parts else "No response from agent"

            return AgentResponse(
                content=content,
                agent_type="acp",
                agent_name=self.agent_name,
                metadata={"responses_count": len(responses), "agent_type": "acp"},
            )

        except Exception as e:
            return AgentResponse(
                content=f"Error communicating with ACP agent {self.agent_name}: {str(e)}",
                agent_type="acp",
                agent_name=self.agent_name,
                metadata={"error": str(e)},
            )

    async def get_capabilities(self) -> List[str]:
        """Get ACP agent capabilities."""
        capabilities = ["coding", "terminal_access", "file_operations"]

        # Add agent-specific capabilities
        if self.agent_name == "claude-code":
            capabilities.extend(["code_editing", "project_navigation", "refactoring"])
        elif self.agent_name == "openhands":
            capabilities.extend(["multi_file_editing", "testing", "deployment"])
        elif self.agent_name == "goose":
            capabilities.extend(["automation", "scripting", "productivity"])

        return capabilities

    async def cleanup(self) -> None:
        """Clean up ACP agent resources."""
        if self.agent_manager:
            await self.agent_manager.disconnect()
        self._initialized = False


def create_unified_agent(role_config: ResolvedRole) -> UnifiedAgent:
    """Factory function to create the appropriate agent type."""
    if role_config.agent_type == "acp":
        return ACPUnifiedAgent(role_config)
    elif role_config.agent_type == "superqode":
        return SuperQodeAgent(role_config)
    else:
        raise ValueError(f"Unknown agent type: {role_config.agent_type}")


class AgentManager:
    """Manager for unified agents with session handling."""

    def __init__(self):
        self.active_agents: Dict[str, UnifiedAgent] = {}
        self.current_agent: Optional[UnifiedAgent] = None

    async def switch_to_role(self, mode: str, role: Optional[str] = None) -> bool:
        """Switch to a specific role/mode."""
        from .config import load_config, resolve_role

        config = load_config()
        resolved_role = resolve_role(mode, role, config)

        if not resolved_role:
            return False

        # Create agent key
        agent_key = f"{mode}.{role}" if role else mode

        # Check if agent is already active
        if agent_key in self.active_agents:
            self.current_agent = self.active_agents[agent_key]
            return True

        # Create new agent
        agent = create_unified_agent(resolved_role)

        # Initialize agent
        if await agent.initialize():
            self.active_agents[agent_key] = agent
            self.current_agent = agent
            return True

        return False

    async def send_message(self, message: str, **kwargs) -> Optional[AgentResponse]:
        """Send message to current agent."""
        if not self.current_agent:
            return None

        return await self.current_agent.send_message(message, **kwargs)

    def get_current_agent_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the current agent."""
        if not self.current_agent:
            return None

        return {
            "name": self.current_agent.agent_name,
            "type": self.current_agent.agent_type,
            "description": self.current_agent.description,
            "capabilities": asyncio.run(self.current_agent.get_capabilities()),
        }

    async def cleanup(self) -> None:
        """Clean up all agents."""
        for agent in self.active_agents.values():
            await agent.cleanup()
        self.active_agents.clear()
        self.current_agent = None
