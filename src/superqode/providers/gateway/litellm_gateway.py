"""
LiteLLM Gateway Implementation.

Default gateway for BYOK mode using LiteLLM for unified API access
to 100+ LLM providers.

Performance features:
- Background prewarming to avoid cold-start latency
- Shared module instance across gateway instances
"""

import asyncio
import concurrent.futures
import json
import os
import threading
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from .base import (
    AuthenticationError,
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
from ..registry import PROVIDERS, ProviderDef


# Module-level shared state for prewarming
_litellm_module = None
_litellm_lock = threading.Lock()
_prewarm_task: Optional[asyncio.Task] = None
_prewarm_complete = threading.Event()


def _load_litellm():
    """Load and configure litellm module (thread-safe)."""
    global _litellm_module
    with _litellm_lock:
        if _litellm_module is None:
            import litellm

            litellm.drop_params = True  # Drop unsupported params
            litellm.set_verbose = False
            _litellm_module = litellm
            _prewarm_complete.set()
    return _litellm_module


class LiteLLMGateway(GatewayInterface):
    """LiteLLM-based gateway for BYOK mode.

    Uses LiteLLM to provide unified access to 100+ LLM providers.

    Performance:
        Call prewarm() during app startup to load litellm in background,
        avoiding ~500-800ms cold-start on first LLM request.
    """

    # Class-level executor for background tasks
    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def __init__(
        self,
        track_costs: bool = True,
        timeout: float = 300.0,
    ):
        self.track_costs = track_costs
        self.timeout = timeout

    @classmethod
    def prewarm(cls) -> None:
        """Start prewarming litellm in background thread.

        Call this during app startup for faster first LLM request.
        Non-blocking - returns immediately while loading happens in background.

        Example:
            # In app startup
            LiteLLMGateway.prewarm()

            # Later, first request will be fast
            gateway = LiteLLMGateway()
            await gateway.chat_completion(...)
        """
        if _prewarm_complete.is_set():
            return  # Already loaded

        # Submit to thread pool (non-blocking)
        cls._executor.submit(_load_litellm)

    @classmethod
    async def prewarm_async(cls) -> None:
        """Async version of prewarm - await to ensure litellm is loaded.

        Use this if you want to wait for prewarming to complete.
        """
        if _prewarm_complete.is_set():
            return

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(cls._executor, _load_litellm)

    @classmethod
    def is_prewarmed(cls) -> bool:
        """Check if litellm has been loaded."""
        return _prewarm_complete.is_set()

    @classmethod
    def wait_for_prewarm(cls, timeout: float = 5.0) -> bool:
        """Wait for prewarming to complete.

        Args:
            timeout: Maximum seconds to wait

        Returns:
            True if prewarmed, False if timeout
        """
        return _prewarm_complete.wait(timeout=timeout)

    def _get_litellm(self):
        """Get litellm module (uses shared prewarmed instance if available)."""
        global _litellm_module
        if _litellm_module is not None:
            return _litellm_module

        # Not prewarmed - load synchronously (will be cached for next time)
        try:
            return _load_litellm()
        except ImportError as e:
            raise GatewayError("LiteLLM is not installed. Install with: pip install litellm") from e

    def get_model_string(self, provider: str, model: str) -> str:
        """Get the full model string for LiteLLM.

        Args:
            provider: Provider ID (e.g., "anthropic")
            model: Model ID (e.g., "claude-sonnet-4-20250514")

        Returns:
            Full model string for LiteLLM (e.g., "anthropic/claude-sonnet-4-20250514")
        """
        provider_def = PROVIDERS.get(provider)

        if provider_def and provider_def.litellm_prefix:
            # Don't double-prefix
            if model.startswith(provider_def.litellm_prefix):
                return model
            # Empty prefix means no prefix needed (e.g., OpenAI)
            if provider_def.litellm_prefix == "":
                return model
            return f"{provider_def.litellm_prefix}{model}"

        # Unknown provider - try as-is
        return model

    def _setup_provider_env(self, provider: str) -> None:
        """Set up environment for a provider if needed."""
        provider_def = PROVIDERS.get(provider)
        if not provider_def:
            return

        # Handle base URL for local/custom providers
        if provider_def.base_url_env:
            base_url = os.environ.get(provider_def.base_url_env)
            if not base_url and provider_def.default_base_url:
                # Set default base URL if not configured
                os.environ[provider_def.base_url_env] = provider_def.default_base_url
                base_url = provider_def.default_base_url

            # For Ollama, configure LiteLLM via OLLAMA_API_BASE environment variable
            # LiteLLM 1.80.11 uses OLLAMA_API_BASE env var (not ollama_base_url attribute)
            if provider == "ollama" and base_url:
                # Set both OLLAMA_HOST (our convention) and OLLAMA_API_BASE (LiteLLM convention)
                os.environ["OLLAMA_HOST"] = base_url
                os.environ["OLLAMA_API_BASE"] = base_url

            # For LM Studio - configure for local OpenAI-compatible API
            if provider == "lmstudio" and base_url:
                # LM Studio uses OpenAI-compatible API at /v1
                # Set OPENAI_API_BASE to the base URL (already includes /v1)
                clean_url = base_url.rstrip("/")
                os.environ["OPENAI_API_BASE"] = clean_url
                # Also set the provider-specific env var
                os.environ["LMSTUDIO_HOST"] = clean_url
                # For local LM Studio, set a dummy API key to avoid LiteLLM auth errors
                # Local servers typically don't require authentication
                os.environ["OPENAI_API_KEY"] = os.environ.get(
                    "OPENAI_API_KEY", "sk-local-lmstudio-dummy"
                )

            # For vLLM - configure for OpenAI-compatible API
            if provider == "vllm" and base_url:
                # vLLM uses OpenAI-compatible API at /v1
                # Set OPENAI_API_BASE to the base URL (already includes /v1)
                clean_url = base_url.rstrip("/")
                os.environ["OPENAI_API_BASE"] = clean_url
                # Also set the provider-specific env var
                os.environ["VLLM_HOST"] = clean_url
                # For local vLLM, set a dummy API key to avoid LiteLLM auth errors
                # Local servers typically don't require authentication
                os.environ["OPENAI_API_KEY"] = os.environ.get(
                    "OPENAI_API_KEY", "sk-local-vllm-dummy"
                )

            # For SGLang - configure for OpenAI-compatible API
            if provider == "sglang" and base_url:
                # SGLang uses OpenAI-compatible API at /v1
                # Set OPENAI_API_BASE to the base URL (already includes /v1)
                clean_url = base_url.rstrip("/")
                os.environ["OPENAI_API_BASE"] = clean_url
                # Also set the provider-specific env var
                os.environ["SGLANG_HOST"] = clean_url
                # For local SGLang, set a dummy API key to avoid LiteLLM auth errors
                # Local servers typically don't require authentication
                os.environ["OPENAI_API_KEY"] = os.environ.get(
                    "OPENAI_API_KEY", "sk-local-sglang-dummy"
                )

            # MLX is handled directly, not through LiteLLM, so no env setup needed

        # Ensure API keys are set for cloud providers (LiteLLM reads from environment)
        # Google - supports both GOOGLE_API_KEY and GEMINI_API_KEY
        if provider == "google":
            google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            if google_key:
                # Ensure both are set for maximum compatibility
                os.environ["GOOGLE_API_KEY"] = google_key
                if not os.environ.get("GEMINI_API_KEY"):
                    os.environ["GEMINI_API_KEY"] = google_key

    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert Message objects to LiteLLM format."""
        result = []
        for msg in messages:
            m = {"role": msg.role, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            if msg.tool_calls:
                m["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            result.append(m)
        return result

    def _convert_tools(
        self, tools: Optional[List[ToolDefinition]]
    ) -> Optional[List[Dict[str, Any]]]:
        """Convert ToolDefinition objects to LiteLLM format."""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    def _normalize_tool_calls(self, tool_calls: Any) -> Optional[List[Dict[str, Any]]]:
        """Normalize tool calls from LiteLLM to dictionaries.

        Handles both dict format and object format (ChatCompletionDeltaToolCall, etc.).
        This is necessary because different LiteLLM providers return tool calls in different formats.
        """
        if not tool_calls:
            return None

        if isinstance(tool_calls, list):
            normalized = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    # Already a dict - use as-is
                    normalized.append(tc)
                else:
                    # Object format (e.g., ChatCompletionDeltaToolCall) - convert to dict
                    tc_dict = {}

                    # Extract id if present
                    if hasattr(tc, "id"):
                        tc_dict["id"] = getattr(tc, "id", None)
                    elif hasattr(tc, "tool_call_id"):
                        tc_dict["id"] = getattr(tc, "tool_call_id", None)

                    # Extract function info
                    if hasattr(tc, "function"):
                        func = getattr(tc, "function")
                        if isinstance(func, dict):
                            tc_dict["function"] = func
                        else:
                            # Function object - extract fields
                            func_dict = {}
                            if hasattr(func, "name"):
                                func_dict["name"] = getattr(func, "name", "")
                            if hasattr(func, "arguments"):
                                func_dict["arguments"] = getattr(func, "arguments", "{}")
                            elif hasattr(func, "argument"):
                                func_dict["arguments"] = getattr(func, "argument", "{}")
                            tc_dict["function"] = func_dict
                    elif hasattr(tc, "name") or hasattr(tc, "function_name"):
                        # Tool call might have name directly
                        func_dict = {
                            "name": getattr(tc, "name", None) or getattr(tc, "function_name", ""),
                            "arguments": getattr(tc, "arguments", None)
                            or getattr(tc, "args", "{}")
                            or "{}",
                        }
                        tc_dict["function"] = func_dict

                    # If we couldn't extract anything useful, skip it
                    if not tc_dict or "function" not in tc_dict:
                        continue

                    normalized.append(tc_dict)
            return normalized if normalized else None

        # Single tool call (not a list) - wrap in list and process
        if isinstance(tool_calls, dict):
            return [tool_calls]
        else:
            # Object format - normalize it by wrapping in list
            result = self._normalize_tool_calls([tool_calls])
            return result

    def _handle_litellm_error(self, e: Exception, provider: str, model: str) -> None:
        """Convert LiteLLM exceptions to gateway errors."""
        litellm = self._get_litellm()
        error_msg = str(e)

        # Get provider info for helpful error messages
        provider_def = PROVIDERS.get(provider)
        docs_url = provider_def.docs_url if provider_def else ""
        env_vars = provider_def.env_vars if provider_def else []

        # Check for specific error types
        if isinstance(e, litellm.AuthenticationError):
            env_hint = f"Set {' or '.join(env_vars)}" if env_vars else ""
            raise AuthenticationError(
                f"Invalid API key for provider '{provider}'. {env_hint}. "
                f"Get your key at: {docs_url}",
                provider=provider,
                model=model,
                error_type="authentication",
            ) from e

        if isinstance(e, litellm.RateLimitError):
            raise RateLimitError(
                f"Rate limit exceeded for provider '{provider}'. "
                "Wait and retry, or upgrade your API plan.",
                provider=provider,
                model=model,
                error_type="rate_limit",
            ) from e

        if isinstance(e, litellm.NotFoundError):
            example_models = provider_def.example_models if provider_def else []
            models_hint = (
                f"Available models: {', '.join(example_models[:5])}" if example_models else ""
            )
            raise ModelNotFoundError(
                f"Model '{model}' not found for provider '{provider}'. {models_hint}",
                provider=provider,
                model=model,
                error_type="model_not_found",
            ) from e

        if isinstance(e, litellm.BadRequestError):
            raise InvalidRequestError(
                f"Invalid request to '{provider}': {error_msg}",
                provider=provider,
                model=model,
                error_type="invalid_request",
            ) from e

        # Generic error
        raise GatewayError(
            f"Error calling '{provider}/{model}': {error_msg}",
            provider=provider,
            model=model,
        ) from e

    async def _mlx_chat_completion(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        """Handle MLX chat completion directly (bypassing LiteLLM auth issues)."""
        from ..local.mlx import MLXClient

        client = MLXClient()

        # Convert messages to OpenAI format
        openai_messages = []
        for msg in messages:
            openai_msg = {"role": msg.role, "content": msg.content}
            if msg.name:
                openai_msg["name"] = msg.name
            if msg.tool_calls:
                openai_msg["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id
            openai_messages.append(openai_msg)

        # Build request
        request_data = {
            "model": model,
            "messages": openai_messages,
        }

        if temperature is not None:
            request_data["temperature"] = temperature
        if max_tokens is not None:
            request_data["max_tokens"] = max_tokens
        if tools:
            request_data["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_data["tool_choice"] = tool_choice

        try:
            # Make direct request to MLX server (MLX models can be slow)
            response_data = await client._async_request(
                "POST", "/v1/chat/completions", request_data, timeout=120.0
            )

            # Extract response
            choice = response_data["choices"][0]
            message = choice["message"]

            # Build usage info
            usage_data = response_data.get("usage", {})
            usage = None
            if usage_data:
                usage = Usage(
                    prompt_tokens=usage_data.get("prompt_tokens", 0),
                    completion_tokens=usage_data.get("completion_tokens", 0),
                    total_tokens=usage_data.get("total_tokens", 0),
                )

            # Clean up MLX response content - remove special tokens that might confuse users
            content = message.get("content", "")
            if content:
                # Some MLX models return content with special tokens like <|channel|>, <|message|>, etc.
                # Clean these up for better user experience
                content = (
                    content.replace("<|channel|>", "")
                    .replace("<|message|>", "")
                    .replace("<|end|>", "")
                    .replace("<|start|>", "")
                )
                content = content.replace(
                    "assistant", ""
                ).strip()  # Remove duplicate assistant markers

            return GatewayResponse(
                content=content,
                role=message.get("role", "assistant"),
                finish_reason=choice.get("finish_reason"),
                usage=usage,
                model=response_data.get("model", model),
                provider="mlx",
                tool_calls=message.get("tool_calls"),
                raw_response=response_data,
            )

        except Exception as e:
            # Provide more specific MLX error messages
            error_msg = str(e)
            if "broadcast_shapes" in error_msg or "cannot be broadcast" in error_msg:
                raise GatewayError(
                    f"MLX server encountered a KV cache conflict (concurrent request issue).\n\n"
                    f"This happens when multiple requests are sent to the MLX server simultaneously.\n"
                    f"MLX servers can only handle one request at a time to avoid memory conflicts.\n\n"
                    f"To fix:\n"
                    f"1. Wait for any running requests to complete\n"
                    f"2. superqode providers mlx list - Check server status\n"
                    f"3. If server crashed: superqode providers mlx server --model {model} - Restart server\n"
                    f"4. Try your request again with only one active session\n\n"
                    f"MLX Tip: Each model needs its own server instance for concurrent use",
                    provider="mlx",
                    model=model,
                ) from e
            elif "Expecting value" in error_msg or "Invalid JSON" in error_msg:
                raise GatewayError(
                    f"MLX server returned invalid response.\n\n"
                    f"This usually means the MLX server crashed or is in an error state.\n\n"
                    f"To fix:\n"
                    f"1. superqode providers mlx list - Check if server is running\n"
                    f"2. If not running: superqode providers mlx server --model {model} - Start server\n"
                    f"3. Wait 1-2 minutes for large models to load\n"
                    f"4. Try again",
                    provider="mlx",
                    model=model,
                ) from e
            elif "Connection refused" in error_msg:
                raise GatewayError(
                    f"Cannot connect to MLX server at http://localhost:8080.\n\n"
                    f"MLX server is not running. To fix:\n\n"
                    f"1. superqode providers mlx setup - Complete setup guide\n"
                    f"2. superqode providers mlx server --model {model} - Get server command\n"
                    f"3. Run the server command in a separate terminal\n"
                    f"4. Try connecting again",
                    provider="mlx",
                    model=model,
                ) from e
            elif "Connection timed out" in error_msg or "timeout" in error_msg.lower():
                raise GatewayError(
                    f"MLX server timed out. Large MLX models (like {model}) can take 1-2 minutes for first response.\n\n"
                    f"Please wait and try again. If this persists:\n"
                    f"1. Check server is still running: superqode providers mlx list\n"
                    f"2. Try a smaller model for testing\n"
                    f"3. Restart the server if needed",
                    provider="mlx",
                    model=model,
                ) from e
            else:
                # Convert to gateway error
                self._handle_litellm_error(e, "mlx", model)

    async def _lmstudio_chat_completion(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> GatewayResponse:
        """Handle LM Studio chat completion directly to control endpoint."""
        import aiohttp
        from ..registry import PROVIDERS

        # Get LM Studio base URL
        provider_def = PROVIDERS.get("lmstudio")
        base_url = provider_def.default_base_url if provider_def else "http://localhost:1234"
        if provider_def and provider_def.base_url_env:
            base_url = os.environ.get(provider_def.base_url_env, base_url)

        # LM Studio typically serves at /v1/chat/completions
        url = f"{base_url.rstrip('/')}/v1/chat/completions"

        # Convert messages to OpenAI format
        openai_messages = []
        for msg in messages:
            openai_msg = {"role": msg.role, "content": msg.content}
            if msg.name:
                openai_msg["name"] = msg.name
            if msg.tool_calls:
                openai_msg["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id
            openai_messages.append(openai_msg)

        # Build request
        request_data = {
            "model": model,
            "messages": openai_messages,
        }

        if temperature is not None:
            request_data["temperature"] = temperature
        if max_tokens is not None:
            request_data["max_tokens"] = max_tokens
        if tools:
            request_data["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_data["tool_choice"] = tool_choice

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', 'sk-local-lmstudio-dummy')}",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=request_data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120.0),
                ) as response:
                    response_data = await response.json()

                    # Extract response
                    choice = response_data["choices"][0]
                    message = choice["message"]

                    # Build usage info
                    usage_data = response_data.get("usage", {})
                    usage = None
                    if usage_data:
                        usage = Usage(
                            prompt_tokens=usage_data.get("prompt_tokens", 0),
                            completion_tokens=usage_data.get("completion_tokens", 0),
                            total_tokens=usage_data.get("total_tokens", 0),
                        )

                    return GatewayResponse(
                        content=message.get("content", ""),
                        role=message.get("role", "assistant"),
                        finish_reason=choice.get("finish_reason"),
                        usage=usage,
                        model=response_data.get("model", model),
                        provider="lmstudio",
                        tool_calls=message.get("tool_calls"),
                        raw_response=response_data,
                    )

        except aiohttp.ClientError as e:
            if "Connection refused" in str(e):
                raise GatewayError(
                    f"Cannot connect to LM Studio server at {base_url}.\n\n"
                    f"LM Studio server is not running. To fix:\n\n"
                    f"1. [cyan]Open LM Studio application[/cyan]\n"
                    f"2. [cyan]Load a model (like qwen/qwen3-30b)[/cyan]\n"
                    f"3. [cyan]Start the local server[/cyan]\n"
                    f"4. Try connecting again",
                    provider="lmstudio",
                    model=model,
                ) from e
            else:
                raise GatewayError(
                    f"LM Studio request failed: {str(e)}",
                    provider="lmstudio",
                    model=model,
                ) from e
        except Exception as e:
            raise GatewayError(
                f"LM Studio error: {str(e)}",
                provider="lmstudio",
                model=model,
            ) from e

    async def _mlx_stream_completion(
        self,
        messages: List[Message],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Handle MLX streaming completion directly."""
        from ..local.mlx import MLXClient

        client = MLXClient()

        # Convert messages to OpenAI format
        openai_messages = []
        for msg in messages:
            openai_msg = {"role": msg.role, "content": msg.content}
            if msg.name:
                openai_msg["name"] = msg.name
            if msg.tool_calls:
                openai_msg["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id
            openai_messages.append(openai_msg)

        # Build request - MLX server may not support streaming properly, so use non-streaming
        request_data = {
            "model": model,
            "messages": openai_messages,
            # Note: Not setting stream=True as MLX server streaming may cause KV cache issues
        }

        if temperature is not None:
            request_data["temperature"] = temperature
        if max_tokens is not None:
            request_data["max_tokens"] = max_tokens
        if tools:
            request_data["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_data["tool_choice"] = tool_choice

        try:
            # Make non-streaming request to MLX server (streaming causes KV cache issues)
            response_data = await client._async_request(
                "POST", "/v1/chat/completions", request_data, timeout=120.0
            )

            # Extract response and yield as single chunk
            choice = response_data["choices"][0]
            message = choice["message"]

            # Get content and clean it up
            content = message.get("content", "")

            # Clean up MLX response content - remove special tokens that might confuse users
            if content:
                # Some MLX models return content with special tokens like <|channel|>, <|message|>, etc.
                # Clean these up for better user experience
                content = (
                    content.replace("<|channel|>", "")
                    .replace("<|message|>", "")
                    .replace("<|end|>", "")
                    .replace("<|start|>", "")
                )
                content = content.replace(
                    "assistant", ""
                ).strip()  # Remove duplicate assistant markers

            yield StreamChunk(
                content=content,
                role=message.get("role"),
                finish_reason=choice.get("finish_reason"),
                tool_calls=message.get("tool_calls"),
            )

        except Exception as e:
            # Provide more specific MLX error messages
            error_msg = str(e)
            if "broadcast_shapes" in error_msg or "cannot be broadcast" in error_msg:
                raise GatewayError(
                    f"MLX server encountered a KV cache conflict (concurrent request issue).\n\n"
                    f"This happens when multiple requests are sent to the MLX server simultaneously.\n"
                    f"MLX servers can only handle one request at a time to avoid memory conflicts.\n\n"
                    f"To fix:\n"
                    f"1. [yellow]Wait for any running requests to complete[/yellow]\n"
                    f"2. [cyan]superqode providers mlx list[/cyan] - Check server status\n"
                    f"3. If server crashed: [cyan]superqode providers mlx server --model {model}[/cyan] - Restart server\n"
                    f"4. Try your request again with only one active session\n\n"
                    f"[dim]💡 MLX Tip: Each model needs its own server instance for concurrent use[/dim]",
                    provider="mlx",
                    model=model,
                ) from e
            elif "Connection refused" in error_msg:
                raise GatewayError(
                    f"Cannot connect to MLX server at http://localhost:8080.\n\n"
                    f"MLX server is not running. To fix:\n\n"
                    f"1. [cyan]superqode providers mlx setup[/cyan] - Complete setup guide\n"
                    f"2. [cyan]superqode providers mlx server --model {model}[/cyan] - Get server command\n"
                    f"3. Run the server command in a separate terminal\n"
                    f"4. Try connecting again",
                    provider="mlx",
                    model=model,
                ) from e
            elif "Connection timed out" in error_msg or "timeout" in error_msg.lower():
                raise GatewayError(
                    f"MLX server timed out. Large MLX models (like {model}) can take 1-2 minutes for first response.\n\n"
                    f"Please wait and try again. If this persists:\n"
                    f"1. Check server is still running: [cyan]superqode providers mlx list[/cyan]\n"
                    f"2. Try a smaller model for testing\n"
                    f"3. Restart the server if needed",
                    provider="mlx",
                    model=model,
                ) from e
            else:
                # Convert to gateway error
                self._handle_litellm_error(e, "mlx", model)

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
        """Make a chat completion request via LiteLLM."""

        # Determine provider from model string if not specified
        if not provider and "/" in model:
            provider = model.split("/")[0]
        provider = provider or "unknown"

        # Special handling for MLX - use direct client instead of LiteLLM
        if provider == "mlx":
            return await self._mlx_chat_completion(
                messages, model, temperature, max_tokens, tools, tool_choice, **kwargs
            )

        # Special handling for LM Studio - use direct client to avoid cloud API
        if provider == "lmstudio":
            return await self._lmstudio_chat_completion(
                messages, model, temperature, max_tokens, tools, tool_choice, **kwargs
            )

        litellm = self._get_litellm()

        # Set up provider environment
        self._setup_provider_env(provider)

        # Build model string
        model_string = self.get_model_string(provider, model) if provider != "unknown" else model

        # Build request
        request_kwargs = {
            "model": model_string,
            "messages": self._convert_messages(messages),
            "timeout": self.timeout,
        }

        # Explicitly pass API keys for providers that need them
        # Some LiteLLM versions require explicit api_key parameter
        if provider == "google":
            google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            if google_key:
                request_kwargs["api_key"] = google_key

        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
        if tools:
            request_kwargs["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_kwargs["tool_choice"] = tool_choice

        # Add any extra kwargs
        request_kwargs.update(kwargs)

        try:
            response = await litellm.acompletion(**request_kwargs)

            # Extract response data
            choice = response.choices[0]
            message = choice.message

            # Parse content - handle Ollama JSON responses and detect empty responses
            content = message.content or ""

            # Check if response is completely empty (no content, no tool calls)
            if not content.strip() and not (hasattr(message, "tool_calls") and message.tool_calls):
                # This model returned nothing - provide a helpful error
                content = f"⚠️ Model '{provider}/{model}' returned an empty response.\n\nThis usually means:\n• The model is not properly configured or available\n• The model may be overloaded or rate-limited\n• Check that the model exists and is accessible\n\nTry using a different model or check your provider configuration."

            elif isinstance(content, str) and content.strip().startswith("{"):
                try:
                    parsed = json.loads(content)
                    # Extract text from common Ollama JSON formats
                    if isinstance(parsed, dict):
                        # Try common fields in order of preference
                        content = (
                            parsed.get("response")
                            or parsed.get("message")
                            or parsed.get("content")
                            or parsed.get("text")
                            or parsed.get("answer")
                            or parsed.get("output")
                            or content
                        )
                        # If content is still a dict, try to extract from it
                        if isinstance(content, dict):
                            content = (
                                content.get("content")
                                or content.get("text")
                                or content.get("message")
                                or str(content)
                            )
                        elif not isinstance(content, str):
                            content = str(content)
                except (json.JSONDecodeError, AttributeError):
                    # Not valid JSON or can't parse, use as-is
                    pass

            # Build usage info
            usage = None
            if response.usage:
                usage = Usage(
                    prompt_tokens=response.usage.prompt_tokens or 0,
                    completion_tokens=response.usage.completion_tokens or 0,
                    total_tokens=response.usage.total_tokens or 0,
                )

            # Build cost info if tracking enabled
            cost = None
            if self.track_costs and hasattr(response, "_hidden_params"):
                hidden = response._hidden_params or {}
                if "response_cost" in hidden:
                    cost = Cost(total_cost=hidden["response_cost"])

            # Extract thinking/reasoning content from response
            thinking_content = None
            thinking_tokens = None

            # Check for extended thinking in various formats
            if hasattr(response, "_hidden_params"):
                hidden = response._hidden_params or {}
                # Claude extended thinking
                if "thinking" in hidden:
                    thinking_content = hidden["thinking"]
                elif "reasoning" in hidden:
                    thinking_content = hidden["reasoning"]
                # o1 reasoning tokens
                elif "reasoning_tokens" in hidden:
                    thinking_content = hidden.get("reasoning_content", "")
                    thinking_tokens = hidden.get("reasoning_tokens", 0)

            # Check raw response for thinking fields
            if not thinking_content and hasattr(response, "response_msgs"):
                # Some providers expose thinking in response_msgs
                for msg in response.response_msgs:
                    if hasattr(msg, "thinking") and msg.thinking:
                        thinking_content = msg.thinking
                        break

            # Check message for thinking fields (Claude format)
            if not thinking_content and hasattr(message, "thinking"):
                thinking_content = message.thinking

            # Check for stop_reason indicating thinking (Claude extended thinking)
            if not thinking_content and choice.finish_reason == "thinking":
                # Extended thinking mode - content might be in a different field
                if hasattr(choice, "thinking") and choice.thinking:
                    thinking_content = choice.thinking
                elif hasattr(message, "thinking") and message.thinking:
                    thinking_content = message.thinking

            # Extract thinking tokens from usage if available
            if thinking_content and usage and not thinking_tokens:
                # Some providers report thinking tokens separately
                if hasattr(response, "_hidden_params"):
                    hidden = response._hidden_params or {}
                    thinking_tokens = hidden.get("thinking_tokens") or hidden.get(
                        "reasoning_tokens"
                    )

            # Normalize tool calls from LiteLLM response (may be objects or dicts)
            tool_calls = None
            if hasattr(message, "tool_calls") and message.tool_calls:
                tool_calls = self._normalize_tool_calls(message.tool_calls)

            return GatewayResponse(
                content=content,
                role=message.role,
                finish_reason=choice.finish_reason,
                usage=usage,
                cost=cost,
                model=response.model,
                provider=provider,
                tool_calls=tool_calls,
                raw_response=response,
                thinking_content=thinking_content,
                thinking_tokens=thinking_tokens,
            )

        except Exception as e:
            self._handle_litellm_error(e, provider, model)

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
        """Make a streaming chat completion request via LiteLLM."""

        # Determine provider from model string if not specified
        if not provider and "/" in model:
            provider = model.split("/")[0]
        provider = provider or "unknown"

        # Special handling for MLX - use direct client instead of LiteLLM
        if provider == "mlx":
            async for chunk in self._mlx_stream_completion(
                messages, model, temperature, max_tokens, tools, tool_choice, **kwargs
            ):
                yield chunk
            return

        litellm = self._get_litellm()

        # Set up provider environment
        self._setup_provider_env(provider)

        # Build model string
        model_string = self.get_model_string(provider, model) if provider != "unknown" else model

        # Build request
        request_kwargs = {
            "model": model_string,
            "messages": self._convert_messages(messages),
            "stream": True,
            "timeout": self.timeout,
        }

        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
        if tools:
            request_kwargs["tools"] = self._convert_tools(tools)
        if tool_choice:
            request_kwargs["tool_choice"] = tool_choice

        # Explicitly pass API keys for providers that need them
        # Some LiteLLM versions require explicit api_key parameter
        if provider == "google":
            google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            if google_key:
                request_kwargs["api_key"] = google_key

        request_kwargs.update(kwargs)

        try:
            response = await litellm.acompletion(**request_kwargs)

            if not response:
                raise GatewayError(
                    f"No response from {provider}/{model}",
                    provider=provider,
                    model=model,
                )

            async for chunk in response:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # Extract thinking content if available (for extended thinking models)
                thinking_content = None
                if hasattr(delta, "thinking") and delta.thinking:
                    thinking_content = delta.thinking
                elif hasattr(choice, "thinking") and choice.thinking:
                    thinking_content = choice.thinking

                # Extract content - handle Ollama JSON responses
                content = ""
                if delta and delta.content:
                    content_str = delta.content
                    # Note: In streaming mode, JSON might come in chunks, so we only parse
                    # if we have a complete JSON object (starts with { and ends with })
                    # Otherwise, we pass through the content as-is
                    if (
                        isinstance(content_str, str)
                        and content_str.strip().startswith("{")
                        and content_str.strip().endswith("}")
                    ):
                        try:
                            parsed = json.loads(content_str)
                            # Extract text from common Ollama JSON formats
                            if isinstance(parsed, dict):
                                # Try common fields in order of preference
                                content = (
                                    parsed.get("response")
                                    or parsed.get("message")
                                    or parsed.get("content")
                                    or parsed.get("text")
                                    or parsed.get("answer")
                                    or parsed.get("output")
                                    or content_str
                                )
                                # If content is still a dict, try to extract from it
                                if isinstance(content, dict):
                                    content = (
                                        content.get("content")
                                        or content.get("text")
                                        or content.get("message")
                                        or content_str
                                    )
                            else:
                                content = content_str
                        except (json.JSONDecodeError, AttributeError):
                            # Not valid JSON or can't parse, use as-is
                            content = content_str
                    else:
                        content = content_str

                stream_chunk = StreamChunk(
                    content=content,
                    role=delta.role if delta and hasattr(delta, "role") else None,
                    finish_reason=choice.finish_reason,
                    thinking_content=thinking_content,
                )

                # Handle tool calls in stream
                # Normalize tool calls (may be objects or dicts from LiteLLM)
                if delta and hasattr(delta, "tool_calls") and delta.tool_calls:
                    stream_chunk.tool_calls = self._normalize_tool_calls(delta.tool_calls)

                yield stream_chunk

        except GatewayError:
            # Re-raise gateway errors (they're already formatted)
            raise
        except Exception as e:
            # Convert LiteLLM errors to gateway errors
            self._handle_litellm_error(e, provider, model)

    async def test_connection(
        self,
        provider: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Test connection to a provider."""
        provider_def = PROVIDERS.get(provider)

        if not provider_def:
            return {
                "success": False,
                "provider": provider,
                "error": f"Provider '{provider}' not found in registry",
            }

        # Use first example model if not specified
        test_model = model or (
            provider_def.example_models[0] if provider_def.example_models else None
        )

        if not test_model:
            return {
                "success": False,
                "provider": provider,
                "error": "No model specified and no example models available",
            }

        try:
            # Make a minimal test request
            response = await self.chat_completion(
                messages=[Message(role="user", content="Hi")],
                model=test_model,
                provider=provider,
                max_tokens=5,
            )

            return {
                "success": True,
                "provider": provider,
                "model": test_model,
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
                "model": test_model,
                "error": str(e),
                "error_type": e.error_type,
            }
        except Exception as e:
            return {
                "success": False,
                "provider": provider,
                "model": test_model,
                "error": str(e),
            }
