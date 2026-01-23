"""
Base Gateway Interface for BYOK mode.

Defines the abstract interface that all gateways must implement.
This allows swapping between LiteLLM, direct API calls, or other
gateway implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional


@dataclass
class Message:
    """A chat message."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


@dataclass
class ToolDefinition:
    """A tool/function definition."""

    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass
class Usage:
    """Token usage information."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class Cost:
    """Cost information."""

    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"


@dataclass
class GatewayResponse:
    """Response from a gateway call."""

    content: str
    role: str = "assistant"
    finish_reason: Optional[str] = None
    usage: Optional[Usage] = None
    cost: Optional[Cost] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    raw_response: Optional[Any] = None
    thinking_content: Optional[str] = (
        None  # Extended thinking/reasoning from models that support it
    )
    thinking_tokens: Optional[int] = None  # Number of thinking tokens used


@dataclass
class StreamChunk:
    """A chunk from a streaming response."""

    content: str = ""
    role: Optional[str] = None
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage: Optional[Usage] = None
    cost: Optional[Cost] = None
    thinking_content: Optional[str] = None  # Extended thinking/reasoning chunk


class GatewayError(Exception):
    """Base error for gateway operations."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        error_type: Optional[str] = None,
        status_code: Optional[int] = None,
        retry_after: Optional[int] = None,
    ):
        self.provider = provider
        self.model = model
        self.error_type = error_type
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(message)


class AuthenticationError(GatewayError):
    """Authentication/API key error."""

    pass


class RateLimitError(GatewayError):
    """Rate limit exceeded."""

    pass


class ModelNotFoundError(GatewayError):
    """Model not found."""

    pass


class InvalidRequestError(GatewayError):
    """Invalid request parameters."""

    pass


class GatewayInterface(ABC):
    """Abstract interface for LLM gateways.

    All gateway implementations must implement this interface.
    This allows swapping between LiteLLM, direct API calls, etc.
    """

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        """Make a chat completion request.

        Args:
            messages: List of chat messages
            model: Model identifier (may include provider prefix)
            provider: Optional provider override
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            tools: Optional tool definitions
            tool_choice: Tool choice mode ("auto", "none", "required")
            **kwargs: Additional provider-specific parameters

        Returns:
            GatewayResponse with the completion

        Raises:
            GatewayError: On any error
        """
        pass

    @abstractmethod
    async def stream_completion(
        self,
        messages: List[Message],
        model: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Make a streaming chat completion request.

        Args:
            messages: List of chat messages
            model: Model identifier (may include provider prefix)
            provider: Optional provider override
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            tools: Optional tool definitions
            tool_choice: Tool choice mode
            **kwargs: Additional provider-specific parameters

        Yields:
            StreamChunk objects as they arrive

        Raises:
            GatewayError: On any error
        """
        pass

    @abstractmethod
    async def test_connection(
        self,
        provider: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Test connection to a provider.

        Args:
            provider: Provider ID
            model: Optional model to test with

        Returns:
            Dictionary with test results
        """
        pass

    @abstractmethod
    def get_model_string(self, provider: str, model: str) -> str:
        """Get the full model string for a provider/model combination.

        Args:
            provider: Provider ID
            model: Model ID

        Returns:
            Full model string for the gateway
        """
        pass
