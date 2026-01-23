"""
Execution Resolver for SuperQode.

Resolves role configurations into execution configs, determining
whether to use BYOK or ACP mode based on the configuration.
"""

import os
from typing import Any, Dict, Optional, Tuple

from .modes import (
    ACPConfig,
    BYOKConfig,
    ExecutionConfig,
    ExecutionMode,
    GatewayType,
)
from ..providers.registry import PROVIDERS, ProviderDef
from ..agents.registry import AGENTS, AgentDef, AgentStatus


class ExecutionResolverError(Exception):
    """Base error for execution resolver."""

    pass


class ProviderNotFoundError(ExecutionResolverError):
    """Provider not found in registry."""

    def __init__(self, provider_id: str):
        self.provider_id = provider_id
        super().__init__(f"Provider '{provider_id}' not found in registry")


class AgentNotFoundError(ExecutionResolverError):
    """Agent not found in registry."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        super().__init__(f"Agent '{agent_id}' not found in registry")


class AgentNotSupportedError(ExecutionResolverError):
    """Agent is not yet supported."""

    def __init__(self, agent_id: str, status: AgentStatus):
        self.agent_id = agent_id
        self.status = status
        super().__init__(f"Agent '{agent_id}' is not yet supported (status: {status.value})")


class MissingEnvVarError(ExecutionResolverError):
    """Required environment variable is missing."""

    def __init__(self, provider_id: str, env_vars: list, docs_url: str):
        self.provider_id = provider_id
        self.env_vars = env_vars
        self.docs_url = docs_url
        env_list = " or ".join(env_vars)
        super().__init__(
            f"Missing API key for provider '{provider_id}'. "
            f"Set {env_list} environment variable. "
            f"Get your key at: {docs_url}"
        )


class ExecutionResolver:
    """Resolves role configurations into execution configs."""

    def __init__(self, gateway: GatewayType = GatewayType.LITELLM):
        self.gateway = gateway

    def resolve_role(
        self,
        role_config: Dict[str, Any],
        validate_env: bool = True,
    ) -> ExecutionConfig:
        """Resolve a role configuration into an execution config.

        Args:
            role_config: Role configuration dictionary from YAML
            validate_env: Whether to validate environment variables

        Returns:
            ExecutionConfig with the appropriate mode

        Raises:
            ExecutionResolverError: If configuration is invalid
        """
        mode = role_config.get("mode", "").lower()

        # Explicit mode declaration
        if mode == "byok":
            return self._resolve_byok(role_config, validate_env)
        elif mode == "acp":
            return self._resolve_acp(role_config, validate_env)

        # Implicit mode detection (backward compatibility)
        if "agent" in role_config:
            return self._resolve_acp(role_config, validate_env)
        elif "provider" in role_config:
            return self._resolve_byok(role_config, validate_env)

        # Default to BYOK if provider is specified
        if role_config.get("provider"):
            return self._resolve_byok(role_config, validate_env)

        raise ExecutionResolverError(
            "Role must specify either 'mode: byok' with 'provider' or 'mode: acp' with 'agent'"
        )

    def _resolve_byok(
        self,
        role_config: Dict[str, Any],
        validate_env: bool,
    ) -> ExecutionConfig:
        """Resolve BYOK mode configuration."""
        provider_id = role_config.get("provider")
        model = role_config.get("model")

        if not provider_id:
            raise ExecutionResolverError("BYOK mode requires 'provider'")
        if not model:
            raise ExecutionResolverError("BYOK mode requires 'model'")

        # Get provider definition
        provider_def = PROVIDERS.get(provider_id)

        # Validate environment variables if provider is known
        if provider_def and validate_env:
            self._validate_provider_env(provider_def)

        # Build BYOK config
        byok_config = BYOKConfig(
            provider=provider_id,
            model=model,
            gateway=self.gateway,
            base_url=role_config.get("base_url"),
            extra_headers=role_config.get("headers", {}),
            track_costs=role_config.get("track_costs", True),
        )

        return ExecutionConfig(
            mode=ExecutionMode.BYOK,
            byok=byok_config,
            job_description=role_config.get("job_description", ""),
            enabled=role_config.get("enabled", True),
        )

    def _resolve_acp(
        self,
        role_config: Dict[str, Any],
        validate_env: bool,
    ) -> ExecutionConfig:
        """Resolve ACP mode configuration."""
        agent_id = role_config.get("agent")

        if not agent_id:
            raise ExecutionResolverError("ACP mode requires 'agent'")

        # Get agent definition
        agent_def = AGENTS.get(agent_id)
        if not agent_def:
            raise AgentNotFoundError(agent_id)

        # Check agent status
        if agent_def.status != AgentStatus.SUPPORTED:
            raise AgentNotSupportedError(agent_id, agent_def.status)

        # Get agent config (provider/model for the agent to use)
        agent_config = role_config.get("agent_config", {})

        # Build ACP config
        acp_config = ACPConfig(
            agent=agent_id,
            agent_provider=agent_config.get("provider"),
            agent_model=agent_config.get("model"),
            connection_type=role_config.get("connection_type", "stdio"),
            command=role_config.get("command", agent_def.command),
            host=role_config.get("host"),
            port=role_config.get("port"),
        )

        return ExecutionConfig(
            mode=ExecutionMode.ACP,
            acp=acp_config,
            job_description=role_config.get("job_description", ""),
            enabled=role_config.get("enabled", True),
        )

    def _validate_provider_env(self, provider_def: ProviderDef) -> None:
        """Validate that required environment variables are set."""
        if not provider_def.env_vars:
            # No env vars required (e.g., local providers)
            return

        # Check if any of the env vars are set
        for env_var in provider_def.env_vars:
            if os.environ.get(env_var):
                return

        # None of the env vars are set
        raise MissingEnvVarError(
            provider_def.id,
            provider_def.env_vars,
            provider_def.docs_url,
        )

    def check_provider_status(self, provider_id: str) -> Dict[str, Any]:
        """Check the status of a provider (env vars, availability).

        Returns:
            Dictionary with status information
        """
        provider_def = PROVIDERS.get(provider_id)

        if not provider_def:
            return {
                "provider_id": provider_id,
                "found": False,
                "configured": False,
                "error": f"Provider '{provider_id}' not in registry",
            }

        # Check env vars
        configured = False
        env_var_status = {}

        for env_var in provider_def.env_vars:
            value = os.environ.get(env_var)
            env_var_status[env_var] = bool(value)
            if value:
                configured = True

        # For local providers with no env vars, check base URL
        if not provider_def.env_vars:
            base_url = os.environ.get(
                provider_def.base_url_env or "", provider_def.default_base_url
            )
            configured = bool(base_url)

        return {
            "provider_id": provider_id,
            "found": True,
            "name": provider_def.name,
            "tier": provider_def.tier.name,
            "category": provider_def.category.value,
            "configured": configured,
            "env_vars": env_var_status,
            "docs_url": provider_def.docs_url,
            "notes": provider_def.notes,
        }

    def check_agent_status(self, agent_id: str) -> Dict[str, Any]:
        """Check the status of an agent.

        Returns:
            Dictionary with status information
        """
        agent_def = AGENTS.get(agent_id)

        if not agent_def:
            return {
                "agent_id": agent_id,
                "found": False,
                "available": False,
                "error": f"Agent '{agent_id}' not in registry",
            }

        return {
            "agent_id": agent_id,
            "found": True,
            "name": agent_def.name,
            "protocol": agent_def.protocol.value,
            "status": agent_def.status.value,
            "available": agent_def.status == AgentStatus.SUPPORTED,
            "description": agent_def.description,
            "auth_info": agent_def.auth_info,
            "setup_command": agent_def.setup_command,
            "docs_url": agent_def.docs_url,
            "capabilities": agent_def.capabilities,
        }
