"""
Gateway module for BYOK mode.

Provides a pluggable gateway abstraction for LLM API calls.
Supports multiple gateway implementations:
- LiteLLM (default): Unified access to 100+ providers
- OpenResponses: Open Responses specification for local/custom providers

Usage:
    # Create gateway using factory (recommended)
    gateway = GatewayFactory.create("litellm")
    gateway = GatewayFactory.create("openresponses", base_url="http://localhost:11434")

    # Create gateway directly
    gateway = LiteLLMGateway()
    gateway = OpenResponsesGateway(base_url="http://localhost:11434")
"""

from typing import Any, Dict, Optional

from .base import (
    GatewayInterface,
    GatewayError,
    GatewayResponse,
    AuthenticationError,
    RateLimitError,
    ModelNotFoundError,
    InvalidRequestError,
    Message,
    ToolDefinition,
    StreamChunk,
    Usage,
    Cost,
)
from .litellm_gateway import LiteLLMGateway


class GatewayFactory:
    """
    Factory for creating gateway instances.

    Provides a unified interface for creating gateways of different types
    based on configuration. Supports:
    - litellm: LiteLLM-based gateway (default)
    - openresponses: Open Responses specification gateway

    Usage:
        # Default LiteLLM gateway
        gateway = GatewayFactory.create()

        # Open Responses gateway with custom base URL
        gateway = GatewayFactory.create(
            "openresponses",
            base_url="http://localhost:11434"
        )

        # With full configuration
        gateway = GatewayFactory.create_from_config({
            "type": "openresponses",
            "base_url": "http://localhost:11434",
            "reasoning_effort": "high",
        })
    """

    # Default gateway type
    DEFAULT_GATEWAY = "litellm"

    # Registered gateway types
    _registry: Dict[str, type] = {
        "litellm": LiteLLMGateway,
    }

    @classmethod
    def register(cls, name: str, gateway_class: type) -> None:
        """
        Register a gateway type.

        Args:
            name: Gateway type name
            gateway_class: Gateway class implementing GatewayInterface
        """
        cls._registry[name] = gateway_class

    @classmethod
    def create(
        cls,
        gateway_type: Optional[str] = None,
        **kwargs: Any,
    ) -> GatewayInterface:
        """
        Create a gateway instance.

        Args:
            gateway_type: Type of gateway ("litellm", "openresponses")
            **kwargs: Gateway-specific configuration

        Returns:
            Gateway instance

        Raises:
            ValueError: If gateway type is not registered
        """
        gateway_type = gateway_type or cls.DEFAULT_GATEWAY

        # Lazy import OpenResponsesGateway to avoid circular imports
        if gateway_type == "openresponses":
            if "openresponses" not in cls._registry:
                from .openresponses_gateway import OpenResponsesGateway

                cls._registry["openresponses"] = OpenResponsesGateway

        if gateway_type not in cls._registry:
            available = ", ".join(cls._registry.keys())
            raise ValueError(f"Unknown gateway type: {gateway_type}. Available: {available}")

        gateway_class = cls._registry[gateway_type]
        return gateway_class(**kwargs)

    @classmethod
    def create_from_config(
        cls,
        config: Dict[str, Any],
    ) -> GatewayInterface:
        """
        Create a gateway from a configuration dict.

        Args:
            config: Configuration dict with "type" and gateway-specific options

        Returns:
            Gateway instance
        """
        config = config.copy()
        gateway_type = config.pop("type", cls.DEFAULT_GATEWAY)
        return cls.create(gateway_type, **config)

    @classmethod
    def get_available_types(cls) -> list[str]:
        """Get list of available gateway types."""
        # Include openresponses even if not yet imported
        types = list(cls._registry.keys())
        if "openresponses" not in types:
            types.append("openresponses")
        return types


__all__ = [
    # Base classes
    "GatewayInterface",
    "GatewayError",
    "GatewayResponse",
    "AuthenticationError",
    "RateLimitError",
    "ModelNotFoundError",
    "InvalidRequestError",
    "Message",
    "ToolDefinition",
    "StreamChunk",
    "Usage",
    "Cost",
    # Gateway implementations
    "LiteLLMGateway",
    # Factory
    "GatewayFactory",
]
