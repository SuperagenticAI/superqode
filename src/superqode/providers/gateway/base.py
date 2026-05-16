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


class TaskBudgetExceeded(GatewayError):
    """Raised when a session's cumulative token budget is exhausted.

    The agent loop is expected to catch this and stop the task with a
    user-visible message — silently halving the budget mid-run would
    confuse cost accounting downstream.
    """

    pass


class TaskTokenBudget:
    """Per-session token ceiling, shared across turns.

    Wire this into the gateway via ``task_budget=`` on the request kwarg.
    The gateway pre-checks before every call and credits the response
    usage when it lands. Callers reset between sessions.

    Concurrency note: a single budget is **not** safe to share across
    parallel sessions — the credit step is non-atomic. Use one budget
    per session (the typical agent-loop case).
    """

    def __init__(self, max_tokens: int) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.max_tokens = max_tokens
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.max_tokens

    def check(self) -> None:
        """Raise ``TaskBudgetExceeded`` if no budget remains.

        Called before each LLM request so the loop fails fast instead
        of paying for a final round-trip just to learn it's over.
        """
        if self.exhausted:
            raise TaskBudgetExceeded(
                f"Task token budget exhausted "
                f"({self.used}/{self.max_tokens} tokens used). "
                f"Reset the budget or start a new task.",
                error_type="task_budget_exceeded",
            )

    def credit(self, tokens: int) -> None:
        """Add ``tokens`` to the used count. No-op for non-positive values."""
        if tokens > 0:
            self.used += tokens

    def reset(self) -> None:
        """Zero the used counter; cap unchanged."""
        self.used = 0


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
