"""
Open Responses Gateway Implementation.

Gateway for the Open Responses specification, providing a unified API
across multiple AI providers with support for:
- Streaming with 45+ event types
- Reasoning/thinking content
- Built-in tools (apply_patch, code_interpreter, file_search)
- Message ↔ Item conversion

This gateway can be used with:
- Local providers (Ollama, vLLM, etc.) that implement Open Responses
- Cloud providers with Open Responses-compatible endpoints
- Custom Open Responses servers

Usage:
    gateway = OpenResponsesGateway(base_url="http://localhost:11434")
    response = await gateway.chat_completion(messages, model="qwen3:8b")
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import aiohttp

from .base import (
    Cost,
    GatewayError,
    GatewayInterface,
    GatewayResponse,
    InvalidRequestError,
    Message,
    ModelNotFoundError,
    RateLimitError,
    StreamChunk,
    ToolDefinition,
    Usage,
)
from ..openresponses.converters.messages import (
    messages_to_items,
    convert_output_to_message,
    extract_reasoning_from_output,
)
from ..openresponses.converters.tools import convert_tools_to_openresponses
from ..openresponses.streaming.parser import StreamingEventParser


class OpenResponsesGateway(GatewayInterface):
    """
    Open Responses-based gateway.

    Implements GatewayInterface using the Open Responses specification
    for unified API access to various AI providers.

    Features:
    - Automatic message ↔ item conversion
    - Full streaming support with 45+ event types
    - Reasoning/thinking content extraction
    - Built-in tool support (apply_patch, code_interpreter, etc.)
    - Configurable reasoning effort and truncation

    Args:
        base_url: Base URL for the Open Responses API
        api_key: Optional API key for authentication
        reasoning_effort: Reasoning effort level ("low", "medium", "high")
        truncation: Truncation strategy ("auto", "disabled")
        timeout: Request timeout in seconds
        track_costs: Whether to track costs
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        api_key: Optional[str] = None,
        reasoning_effort: str = "medium",
        truncation: str = "auto",
        timeout: float = 300.0,
        track_costs: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self.truncation = truncation
        self.timeout = timeout
        self.track_costs = track_costs

    def get_model_string(self, provider: str, model: str) -> str:
        """Get the model string for Open Responses.

        Open Responses typically uses plain model names without provider prefix.
        """
        # Remove provider prefix if present
        if "/" in model:
            return model.split("/", 1)[1]
        return model

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
        """Make a chat completion request via Open Responses.

        Converts messages to items, sends request, and converts response back.
        """
        # Convert messages to Open Responses items
        items = messages_to_items(messages)

        # Build request
        request: Dict[str, Any] = {
            "model": self.get_model_string(provider or "", model),
            "input": items,
            "stream": False,
        }

        # Add reasoning config
        if self.reasoning_effort:
            request["reasoning"] = {"effort": self.reasoning_effort}

        # Add truncation
        if self.truncation:
            request["truncation"] = self.truncation

        # Optional parameters
        if temperature is not None:
            request["temperature"] = temperature
        if max_tokens is not None:
            request["max_output_tokens"] = max_tokens
        if tools:
            request["tools"] = convert_tools_to_openresponses(tools)
        if tool_choice:
            request["tool_choice"] = tool_choice

        # Add any extra kwargs
        for key, value in kwargs.items():
            if key not in request and value is not None:
                request[key] = value

        # Make request
        try:
            response_data = await self._post("/v1/responses", request)
        except Exception as e:
            self._handle_error(e, provider or "openresponses", model)
            raise  # Re-raise if _handle_error doesn't raise

        # Parse response
        return self._parse_response(response_data, provider, model)

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
        """Make a streaming chat completion request via Open Responses.

        Handles 45+ streaming event types and yields StreamChunk objects.
        """
        # Convert messages to Open Responses items
        items = messages_to_items(messages)

        # Build request
        request: Dict[str, Any] = {
            "model": self.get_model_string(provider or "", model),
            "input": items,
            "stream": True,
        }

        # Add reasoning config
        if self.reasoning_effort:
            request["reasoning"] = {"effort": self.reasoning_effort}

        # Add truncation
        if self.truncation:
            request["truncation"] = self.truncation

        # Optional parameters
        if temperature is not None:
            request["temperature"] = temperature
        if max_tokens is not None:
            request["max_output_tokens"] = max_tokens
        if tools:
            request["tools"] = convert_tools_to_openresponses(tools)
        if tool_choice:
            request["tool_choice"] = tool_choice

        # Add any extra kwargs
        for key, value in kwargs.items():
            if key not in request and value is not None:
                request[key] = value

        # Stream response
        parser = StreamingEventParser()

        try:
            async for chunk in self._stream_sse("/v1/responses", request):
                parsed_chunk = parser.parse_line(chunk)
                if parsed_chunk:
                    yield parsed_chunk
        except Exception as e:
            self._handle_error(e, provider or "openresponses", model)
            raise

    async def test_connection(
        self,
        provider: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Test connection to the Open Responses API."""
        try:
            # Make a minimal test request
            response = await self.chat_completion(
                messages=[Message(role="user", content="Hi")],
                model=model or "default",
                provider=provider,
                max_tokens=5,
            )

            return {
                "success": True,
                "provider": provider,
                "model": model,
                "response_model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                },
            }

        except GatewayError as e:
            return {
                "success": False,
                "provider": provider,
                "model": model,
                "error": str(e),
                "error_type": e.error_type,
            }
        except Exception as e:
            return {
                "success": False,
                "provider": provider,
                "model": model,
                "error": str(e),
            }

    async def _post(
        self,
        path: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Make a POST request to the Open Responses API."""
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        timeout = aiohttp.ClientTimeout(total=self.timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=data, headers=headers) as response:
                if response.status >= 400:
                    error_text = await response.text()
                    self._handle_http_error(response.status, error_text)

                return await response.json()

    async def _stream_sse(
        self,
        path: str,
        data: Dict[str, Any],
    ) -> AsyncIterator[str]:
        """Stream SSE events from the Open Responses API."""
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        timeout = aiohttp.ClientTimeout(total=self.timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=data, headers=headers) as response:
                if response.status >= 400:
                    error_text = await response.text()
                    self._handle_http_error(response.status, error_text)

                async for line in response.content:
                    line_str = line.decode("utf-8").strip()
                    if line_str:
                        yield line_str

    def _parse_response(
        self,
        data: Dict[str, Any],
        provider: Optional[str],
        model: str,
    ) -> GatewayResponse:
        """Parse an Open Responses response to GatewayResponse."""
        # Extract output items
        output = data.get("output", [])

        # Convert output to message
        message = convert_output_to_message(output)

        # Extract reasoning/thinking
        thinking_content = extract_reasoning_from_output(output)

        # Extract usage
        usage_data = data.get("usage", {})
        usage = None
        if usage_data:
            usage = Usage(
                prompt_tokens=usage_data.get("input_tokens", 0),
                completion_tokens=usage_data.get("output_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )

        # Extract thinking tokens if available
        thinking_tokens = None
        output_details = usage_data.get("output_tokens_details", {})
        if output_details:
            thinking_tokens = output_details.get("reasoning_tokens")

        # Determine finish reason
        status = data.get("status", "completed")
        finish_reason = "stop" if status == "completed" else status

        # Check for incomplete
        incomplete_details = data.get("incomplete_details")
        if incomplete_details:
            finish_reason = f"incomplete:{incomplete_details.get('reason', 'unknown')}"

        return GatewayResponse(
            content=message.content,
            role="assistant",
            finish_reason=finish_reason,
            usage=usage,
            model=data.get("model", model),
            provider=provider or "openresponses",
            tool_calls=message.tool_calls,
            raw_response=data,
            thinking_content=thinking_content,
            thinking_tokens=thinking_tokens,
        )

    def _handle_http_error(self, status: int, error_text: str) -> None:
        """Handle HTTP error responses."""
        try:
            error_data = json.loads(error_text)
            error = error_data.get("error", {})
            message = error.get("message", error_text)
            code = error.get("code", "")
        except json.JSONDecodeError:
            message = error_text
            code = ""

        if status == 401:
            raise GatewayError(
                f"Authentication failed: {message}",
                error_type="authentication",
                status_code=status,
            )
        elif status == 429:
            raise RateLimitError(
                f"Rate limit exceeded: {message}",
                error_type="rate_limit",
                status_code=status,
            )
        elif status == 404:
            raise ModelNotFoundError(
                f"Not found: {message}",
                error_type="model_not_found",
                status_code=status,
            )
        elif status == 400:
            raise InvalidRequestError(
                f"Invalid request: {message}",
                error_type="invalid_request",
                status_code=status,
            )
        else:
            raise GatewayError(
                f"HTTP {status}: {message}",
                error_type="http_error",
                status_code=status,
            )

    def _handle_error(
        self,
        error: Exception,
        provider: str,
        model: str,
    ) -> None:
        """Handle and convert errors to GatewayError."""
        if isinstance(error, GatewayError):
            raise error

        error_msg = str(error)

        if "Connection refused" in error_msg:
            raise GatewayError(
                f"Cannot connect to Open Responses server at {self.base_url}.\n\n"
                f"Please ensure the server is running.",
                provider=provider,
                model=model,
            )
        elif "timeout" in error_msg.lower():
            raise GatewayError(
                f"Request timed out. The server may be busy or the model may need more time.",
                provider=provider,
                model=model,
            )
        else:
            raise GatewayError(
                f"Error calling Open Responses API: {error_msg}",
                provider=provider,
                model=model,
            )
