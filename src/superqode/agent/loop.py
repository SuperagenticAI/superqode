"""
Agent Loop - Minimal, Transparent Execution.

The simplest possible agent loop:
1. Send messages + tools to model
2. If model calls tools, execute them
3. Add results to messages
4. Repeat until model responds with text only

NO:
- Complex state management
- Hidden context injection
- Automatic retries with modified prompts
- "Smart" error recovery

YES:
- Transparent execution
- Raw model behavior
- Fair comparison between models

Performance optimizations:
- Tool definitions cached at init (not rebuilt each iteration)
- Message conversion cached with hash-based lookup
- Parallel tool execution support
"""

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

from ..tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from ..providers.gateway.base import GatewayInterface, Message, ToolDefinition
from .system_prompts import SystemPromptLevel, get_system_prompt, get_job_description_prompt


# Module-level cache for system prompts
@lru_cache(maxsize=32)
def _cached_system_prompt(
    level: SystemPromptLevel,
    working_directory: str,
    custom_prompt: str | None,
    job_description: str | None,
) -> str:
    """Cached system prompt builder."""
    prompt = get_system_prompt(level=level, working_directory=Path(working_directory))
    if custom_prompt:
        prompt += f"\n\n{custom_prompt}"
    if job_description:
        prompt += get_job_description_prompt(job_description)
    return prompt


def _make_hashable(value: Any) -> Any:
    """Convert a value to a hashable type for use in tuples/dict keys.

    Converts dicts to tuples, lists to tuples, and handles nested structures.
    """
    if isinstance(value, dict):
        # Convert dict to sorted tuple of (key, hashable_value) pairs
        return tuple(sorted((k, _make_hashable(v)) for k, v in value.items()))
    elif isinstance(value, list):
        # Convert list to tuple
        return tuple(_make_hashable(item) for item in value)
    elif isinstance(value, (str, int, float, bool, type(None))):
        # Already hashable
        return value
    else:
        # For other types (objects, etc.), convert to string representation
        # This is safe because we only need unique identification, not exact equality
        return str(value)


def _message_to_tuple(m: "AgentMessage") -> Tuple:
    """Convert message to hashable tuple for caching."""
    if m.tool_calls:
        # Handle tool calls that might be dicts or objects (from LiteLLM)
        tool_calls_list = []
        for tc in m.tool_calls:
            if isinstance(tc, dict):
                # Already a dict - convert to hashable representation
                # Use _make_hashable to handle nested dicts (like function field)
                tool_calls_list.append(_make_hashable(tc))
            else:
                # Object (e.g., ChatCompletionDeltaToolCall) - convert to dict representation
                # Extract key fields that make tool calls unique
                tc_dict = {}
                if hasattr(tc, "id"):
                    tc_dict["id"] = getattr(tc, "id", None)
                if hasattr(tc, "function"):
                    func = getattr(tc, "function", None)
                    if func:
                        if isinstance(func, dict):
                            func_dict = func
                        else:
                            func_dict = {}
                            if hasattr(func, "name"):
                                func_dict["name"] = getattr(func, "name", None)
                            if hasattr(func, "arguments"):
                                func_dict["arguments"] = getattr(func, "arguments", None)
                        tc_dict["function"] = func_dict
                elif hasattr(tc, "get"):
                    # Might be a dict-like object
                    tc_dict = dict(tc) if hasattr(tc, "__iter__") and hasattr(tc, "keys") else {}
                # Convert to hashable representation
                tool_calls_list.append(_make_hashable(tc_dict))
        tool_calls_tuple = tuple(tool_calls_list)
    else:
        tool_calls_tuple = None
    return (m.role, m.content, tool_calls_tuple, m.tool_call_id, m.name)


def _is_simple_conversational_query(message: str) -> bool:
    """Detect if a query is simple/conversational and doesn't need tools.

    Simple queries are general knowledge questions, greetings, or basic
    questions that don't require code/file operations.

    This is conservative - only returns True for very obvious cases.
    """
    message_lower = message.lower().strip()

    # Very short greetings only
    if message_lower in ["hi", "hello", "hey"]:
        return True

    # Simple question patterns - detect basic general knowledge questions
    # These should not require tools and some models handle them poorly with tools
    simple_patterns = [
        r"^(what|what\'s|whats) .+\??$",  # "What is the capital?", "What's the weather?"
        r"^where .+\??$",  # "Where is the capital?"
        r"^who .+\??$",  # "Who is the president?"
        r"^when .+\??$",  # "When was the war?"
        r"^how (many|much|long|old) .+\??$",  # "How many people?", "How old is it?"
    ]

    for pattern in simple_patterns:
        if re.match(pattern, message_lower):
            # Double-check: no code keywords
            code_keywords = ["file", "code", "function", "class", "read", "write", "edit"]
            if not any(keyword in message_lower for keyword in code_keywords):
                return True

    # Don't auto-detect other cases - be conservative
    return False


def _is_malformed_tool_call_response(response_content: str, tool_calls: List[Dict]) -> bool:
    """Detect if tool calls look malformed (model trying to return JSON instead of proper tool calls).

    Some local models return JSON in content when they should return proper tool calls,
    or return tool calls for simple queries that don't need tools.
    """
    if not tool_calls:
        return False

    # Check if content looks like JSON (common with local models)
    content = (response_content or "").strip()
    if content.startswith("{") and content.endswith("}"):
        try:
            parsed = json.loads(content)
            # If it's a dict with keys like "function", "arguments", "input", "tool" - likely malformed
            if isinstance(parsed, dict) and any(
                key in parsed for key in ["function", "arguments", "input", "tool"]
            ):
                return True
            # Also check if content has answer-like fields (message, content, text, response)
            # This suggests the model returned JSON with the answer instead of tool calls
            if isinstance(parsed, dict) and any(
                key in parsed for key in ["message", "content", "text", "response"]
            ):
                # If we have tool calls but content has answer fields, it's likely malformed
                # (model should either return tool calls OR text, not both in JSON)
                return True
        except json.JSONDecodeError:
            pass

    # Check if tool calls have suspicious structure
    for tool_call in tool_calls:
        func = tool_call.get("function", {})
        if not isinstance(func, dict):
            return True
        if "name" not in func:
            return True
        # If arguments is a string that's not valid JSON, might be malformed
        args = func.get("arguments", "{}")
        if isinstance(args, str):
            try:
                json.loads(args)
            except json.JSONDecodeError:
                # Arguments should be valid JSON
                return True

    return False


@dataclass
class AgentConfig:
    """Configuration for the agent loop.

    Designed for transparency - every setting is explicit.
    """

    # Model settings
    provider: str
    model: str

    # System prompt level (default: minimal for fair testing)
    system_prompt_level: SystemPromptLevel = SystemPromptLevel.MINIMAL

    # Optional custom system prompt (appended to level prompt)
    custom_system_prompt: Optional[str] = None

    # Optional job description (role context)
    job_description: Optional[str] = None

    # Working directory
    working_directory: Path = field(default_factory=Path.cwd)

    # Tool settings
    tools_enabled: bool = True

    # Execution settings
    max_iterations: int = 50  # Prevent infinite loops
    require_confirmation: bool = False  # Ask before tool execution

    # Model parameters (passed through to gateway)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@dataclass
class AgentMessage:
    """A message in the agent conversation."""

    role: str  # "user", "assistant", "tool"
    content: str
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None  # Tool name for tool messages


@dataclass
class AgentResponse:
    """Response from the agent loop."""

    content: str
    messages: List[AgentMessage]
    tool_calls_made: int
    iterations: int
    stopped_reason: str  # "complete", "max_iterations", "error"
    error: Optional[str] = None


class AgentLoop:
    """Minimal agent loop for fair model testing.

    Usage:
        gateway = LiteLLMGateway()
        tools = ToolRegistry.default()
        config = AgentConfig(provider="anthropic", model="claude-sonnet-4-20250514")

        agent = AgentLoop(gateway, tools, config)
        response = await agent.run("Fix the bug in main.py")

    Performance features:
        - Tool definitions cached at initialization
        - Message conversion cached with hash lookup
        - Parallel tool execution via asyncio.gather
    """

    def __init__(
        self,
        gateway: GatewayInterface,
        tools: ToolRegistry,
        config: AgentConfig,
        on_tool_call: Optional[Callable[[str, Dict], None]] = None,
        on_tool_result: Optional[Callable[[str, ToolResult], None]] = None,
        on_thinking: Optional[Callable[[str], Awaitable[None]]] = None,
        parallel_tools: bool = True,  # Enable parallel tool execution
    ):
        self.gateway = gateway
        self.tools = tools
        self.config = config
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.on_thinking = on_thinking
        self.parallel_tools = parallel_tools

        # Build system prompt (cached via module-level function)
        self.system_prompt = self._build_system_prompt()

        # Session ID for tool context
        self.session_id = str(uuid.uuid4())

        # PERFORMANCE: Cache tool definitions at init (compute once)
        self._cached_tool_defs: List[ToolDefinition] = self._compute_tool_definitions()

        # PERFORMANCE: Cache for converted messages (avoid repeated conversions)
        self._message_cache: Dict[Tuple, Message] = {}

        # Cancellation support
        self._cancelled = False

    def _build_system_prompt(self) -> str:
        """Build the system prompt based on config (uses cached function)."""
        return _cached_system_prompt(
            level=self.config.system_prompt_level,
            working_directory=str(self.config.working_directory),
            custom_prompt=self.config.custom_system_prompt,
            job_description=self.config.job_description,
        )

    def _compute_tool_definitions(self) -> List[ToolDefinition]:
        """Compute tool definitions once at init."""
        if not self.config.tools_enabled:
            return []

        definitions = []
        for tool in self.tools.list():
            definitions.append(
                ToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                )
            )
        return definitions

    def _get_tool_definitions(self) -> List[ToolDefinition]:
        """Get cached tool definitions."""
        return self._cached_tool_defs

    def _convert_message(self, m: AgentMessage) -> Message:
        """Convert a single message with caching."""
        key = _message_to_tuple(m)
        if key not in self._message_cache:
            self._message_cache[key] = Message(
                role=m.role,
                content=m.content,
                tool_calls=m.tool_calls,
                tool_call_id=m.tool_call_id,
                name=m.name,
            )
        return self._message_cache[key]

    def _convert_messages(self, messages: List[AgentMessage]) -> List[Message]:
        """Convert messages to gateway format with caching."""
        return [self._convert_message(m) for m in messages]

    def _create_tool_context(self) -> ToolContext:
        """Create context for tool execution."""
        return ToolContext(
            session_id=self.session_id,
            working_directory=self.config.working_directory,
            require_confirmation=self.config.require_confirmation,
            tool_registry=self.tools,
        )

    async def _execute_tool(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        """Execute a single tool call."""
        tool = self.tools.get(name)

        if not tool:
            return ToolResult(success=False, output="", error=f"Unknown tool: {name}")

        ctx = self._create_tool_context()

        try:
            result = await tool.execute(arguments, ctx)
            return result
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Tool execution error: {str(e)}")

    async def _execute_tools_parallel(
        self,
        tool_calls: List[Dict],
    ) -> List[Tuple[str, str, Dict, ToolResult]]:
        """Execute multiple tool calls in parallel.

        Returns list of (tool_name, tool_call_id, tool_args, result) tuples.
        """

        async def execute_one(tc: Dict) -> Tuple[str, str, Dict, ToolResult]:
            tool_name = tc.get("function", {}).get("name", "")
            tool_args_str = tc.get("function", {}).get("arguments", "{}")
            tool_call_id = tc.get("id", str(uuid.uuid4()))

            try:
                tool_args = (
                    json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                )
            except json.JSONDecodeError:
                tool_args = {}

            # Callback for tool call
            if self.on_tool_call:
                self.on_tool_call(tool_name, tool_args)

            result = await self._execute_tool(tool_name, tool_args)

            # Callback for result
            if self.on_tool_result:
                self.on_tool_result(tool_name, result)

            return (tool_name, tool_call_id, tool_args, result)

        # Execute all tools in parallel
        tasks = [execute_one(tc) for tc in tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions
        processed = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                tc = tool_calls[i]
                tool_name = tc.get("function", {}).get("name", "unknown")
                tool_call_id = tc.get("id", str(uuid.uuid4()))
                processed.append(
                    (
                        tool_name,
                        tool_call_id,
                        {},
                        ToolResult(success=False, output="", error=str(r)),
                    )
                )
            else:
                processed.append(r)

        return processed

    async def run(self, user_message: str) -> AgentResponse:
        """Run the agent loop until completion.

        Args:
            user_message: The user's request

        Returns:
            AgentResponse with the final result

        Performance: Uses cached message conversion and parallel tool execution.
        """
        messages: List[AgentMessage] = []

        # Add system message if we have one
        if self.system_prompt:
            messages.append(AgentMessage(role="system", content=self.system_prompt))

        # Add user message
        messages.append(AgentMessage(role="user", content=user_message))

        tool_calls_made = 0
        iterations = 0

        # Emit initial processing log
        if self.on_thinking:
            await self.on_thinking("Processing request...")

        # Get cached tool definitions (computed once at init)
        tool_defs = self._get_tool_definitions()

        # Always send tools if available - let malformed tool call handling deal with issues
        # This ensures models always get the full context and we handle malformed responses gracefully
        while iterations < self.config.max_iterations:
            iterations += 1

            # Emit iteration log
            if self.on_thinking:
                await self.on_thinking(
                    f"Calling model {self.config.provider}/{self.config.model}... (iteration {iterations})"
                )

            # PERFORMANCE: Use cached message conversion
            gateway_messages = self._convert_messages(messages)

            # Check if this is a simple conversational query that doesn't need tools
            # Some models (especially local ones) don't handle tools well for simple questions
            # Local providers generally don't support tools well
            from ..providers.registry import PROVIDERS, ProviderCategory

            provider_def = PROVIDERS.get(self.config.provider)
            is_local_provider = provider_def and provider_def.category == ProviderCategory.LOCAL

            is_simple_query = _is_simple_conversational_query(user_message)
            tools_to_send = (
                tool_defs if (tool_defs and not is_simple_query and not is_local_provider) else None
            )

            # Call the model
            try:
                response = await self.gateway.chat_completion(
                    messages=gateway_messages,
                    model=self.config.model,
                    provider=self.config.provider,
                    tools=tools_to_send,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
            except Exception as e:
                return AgentResponse(
                    content="",
                    messages=messages,
                    tool_calls_made=tool_calls_made,
                    iterations=iterations,
                    stopped_reason="error",
                    error=str(e),
                )

            # Extract thinking content if available
            if response.thinking_content and self.on_thinking:
                await self.on_thinking(f"[Extended Thinking]\n{response.thinking_content}")

            # Emit response received log
            if self.on_thinking and response.usage:
                total_tokens = response.usage.total_tokens or 0
                await self.on_thinking(f"Received response ({total_tokens} tokens)")

            # Extract content - handle None/empty cases
            response_content = response.content if response.content is not None else ""

            # Check for empty responses from models that should respond
            if not response_content.strip() and not response.tool_calls:
                # Model returned empty content with no tool calls - this is likely a problem
                # Provide a helpful error message instead of empty content
                response_content = f"⚠️ The model '{self.config.provider}/{self.config.model}' returned an empty response. This could mean:\n\n• The model is not responding properly\n• The model may be overloaded or unavailable\n• The model format may not be compatible\n\nTry a different model or check your provider configuration."

            # Check for tool calls
            if response.tool_calls:
                # Check if tool calls look malformed (common with local models)
                if _is_malformed_tool_call_response(response_content, response.tool_calls):
                    # For malformed tool calls, try to extract text from content
                    # or if it's a simple query, just return the content as-is
                    content = response_content

                    # Try to extract text from JSON if content is JSON
                    if content.strip().startswith("{"):
                        try:
                            parsed = json.loads(content)
                            if isinstance(parsed, dict):
                                # Try common fields that might contain the answer
                                extracted = (
                                    parsed.get("message")
                                    or parsed.get("content")
                                    or parsed.get("text")
                                    or parsed.get("response")
                                    or str(parsed)
                                )
                                if isinstance(extracted, dict):
                                    extracted = extracted.get("content", str(extracted))
                                content = str(extracted) if extracted else content
                        except (json.JSONDecodeError, AttributeError):
                            pass

                    # If we have content, return it (ignore malformed tool calls)
                    if content.strip():
                        return AgentResponse(
                            content=content,
                            messages=messages,
                            tool_calls_made=tool_calls_made,
                            iterations=iterations,
                            stopped_reason="complete",
                        )

                    # No content extracted - continue to normal tool call handling
                    # (might be a false positive on malformed detection)

                # Add assistant message with tool calls
                messages.append(
                    AgentMessage(
                        role="assistant",
                        content=response_content,
                        tool_calls=response.tool_calls,
                    )
                )

                # Emit tool execution log
                if self.on_thinking:
                    tool_count = len(response.tool_calls)
                    await self.on_thinking(
                        f"Executing {tool_count} tool call{'s' if tool_count != 1 else ''}..."
                    )

                # PERFORMANCE: Execute tools in parallel or sequential
                if self.parallel_tools and len(response.tool_calls) > 1:
                    # Parallel execution for multiple tools
                    results = await self._execute_tools_parallel(response.tool_calls)
                    for tool_name, tool_call_id, tool_args, result in results:
                        tool_calls_made += 1
                        messages.append(
                            AgentMessage(
                                role="tool",
                                content=result.to_message(),
                                tool_call_id=tool_call_id,
                                name=tool_name,
                            )
                        )
                else:
                    # Sequential execution (single tool or parallel disabled)
                    for tool_call in response.tool_calls:
                        tool_name = tool_call.get("function", {}).get("name", "")
                        tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                        tool_call_id = tool_call.get("id", str(uuid.uuid4()))

                        try:
                            tool_args = (
                                json.loads(tool_args_str)
                                if isinstance(tool_args_str, str)
                                else tool_args_str
                            )
                        except json.JSONDecodeError:
                            tool_args = {}

                        if self.on_tool_call:
                            self.on_tool_call(tool_name, tool_args)

                        result = await self._execute_tool(tool_name, tool_args)
                        tool_calls_made += 1

                        if self.on_tool_result:
                            self.on_tool_result(tool_name, result)

                        messages.append(
                            AgentMessage(
                                role="tool",
                                content=result.to_message(),
                                tool_call_id=tool_call_id,
                                name=tool_name,
                            )
                        )

                # Emit iteration complete log
                if self.on_thinking:
                    await self.on_thinking(f"Iteration {iterations} complete")
            else:
                # No tool calls - return the response content
                if self.on_thinking:
                    await self.on_thinking("Response complete")
                return AgentResponse(
                    content=response_content,
                    messages=messages,
                    tool_calls_made=tool_calls_made,
                    iterations=iterations,
                    stopped_reason="complete",
                )

        # Hit max iterations
        if self.on_thinking:
            await self.on_thinking(f"Reached maximum iterations ({self.config.max_iterations})")
        return AgentResponse(
            content="",
            messages=messages,
            tool_calls_made=tool_calls_made,
            iterations=iterations,
            stopped_reason="max_iterations",
            error=f"Reached maximum iterations ({self.config.max_iterations})",
        )

    async def run_streaming(
        self,
        user_message: str,
    ) -> AsyncIterator[str]:
        """Run the agent loop with streaming output.

        Yields text chunks as they come from the model.
        Tool calls are executed between chunks.

        Performance: Uses cached message conversion and parallel tool execution.
        """
        messages: List[AgentMessage] = []

        if self.system_prompt:
            messages.append(AgentMessage(role="system", content=self.system_prompt))

        messages.append(AgentMessage(role="user", content=user_message))

        iterations = 0
        tool_calls_made = 0

        # Emit initial processing log
        if self.on_thinking:
            await self.on_thinking("Processing request...")

        # Get cached tool definitions
        tool_defs = self._get_tool_definitions()

        while iterations < self.config.max_iterations:
            # Check for cancellation
            if self._cancelled:
                if self.on_thinking:
                    await self.on_thinking("Operation cancelled by user")
                return

            iterations += 1

            # Emit iteration log
            if self.on_thinking:
                await self.on_thinking(
                    f"Calling model {self.config.provider}/{self.config.model}... (iteration {iterations})"
                )

            # PERFORMANCE: Use cached message conversion
            gateway_messages = self._convert_messages(messages)

            # Check if this is a simple conversational query that doesn't need tools
            # Some models (especially local ones) don't handle tools well for simple questions
            # Local providers generally don't support tools well
            from ..providers.registry import PROVIDERS, ProviderCategory

            provider_def = PROVIDERS.get(self.config.provider)
            is_local_provider = provider_def and provider_def.category == ProviderCategory.LOCAL

            is_simple_query = _is_simple_conversational_query(user_message)
            tools_to_send = (
                tool_defs if (tool_defs and not is_simple_query and not is_local_provider) else None
            )

            # Stream response
            full_content = ""
            tool_calls = []
            had_content = False

            # Buffer for accumulating thinking content chunks
            # Local models stream thinking in tiny pieces - accumulate for readable display
            thinking_buffer = ""
            import time as _time

            last_thinking_emit = _time.time()

            try:
                async for chunk in self.gateway.stream_completion(
                    messages=gateway_messages,
                    model=self.config.model,
                    provider=self.config.provider,
                    tools=tools_to_send,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                ):
                    # Check for cancellation during streaming
                    if self._cancelled:
                        if self.on_thinking:
                            await self.on_thinking("Operation cancelled by user")
                        return

                    # Handle thinking content if available - BUFFER for readable display
                    if chunk.thinking_content:
                        thinking_buffer += chunk.thinking_content
                        current_time = _time.time()

                        # Emit thinking content when:
                        # 1. Buffer has a complete sentence (ends with . ? ! or newline)
                        # 2. Buffer exceeds 200 chars (long enough to be readable)
                        # 3. 500ms has passed since last emit (prevent stale buffer)
                        should_emit = (
                            thinking_buffer.rstrip().endswith((".", "?", "!", "\n"))
                            or len(thinking_buffer) > 200
                            or (
                                current_time - last_thinking_emit > 0.5
                                and len(thinking_buffer) > 20
                            )
                        )

                        if should_emit and self.on_thinking and thinking_buffer.strip():
                            await self.on_thinking(thinking_buffer.strip())
                            thinking_buffer = ""
                            last_thinking_emit = current_time

                    if chunk.content:
                        full_content += chunk.content
                        had_content = True
                        yield chunk.content

                    if chunk.tool_calls:
                        tool_calls.extend(chunk.tool_calls)

                # Flush any remaining thinking content after streaming completes
                if thinking_buffer.strip() and self.on_thinking:
                    await self.on_thinking(thinking_buffer.strip())
                    thinking_buffer = ""

            except Exception as e:
                # Flush thinking buffer before handling error
                if thinking_buffer.strip() and self.on_thinking:
                    await self.on_thinking(thinking_buffer.strip())

                error_msg = str(e)
                error_type = type(e).__name__
                # Yield error message so it's displayed
                yield f"\n\n[Error: {error_type}] {error_msg}"
                # Don't return immediately - let the error be displayed
                # But mark that we had an error so we don't continue the loop
                full_content = f"[Error: {error_type}] {error_msg}"
                return

            # Handle tool calls
            if tool_calls:
                messages.append(
                    AgentMessage(
                        role="assistant",
                        content=full_content,
                        tool_calls=tool_calls,
                    )
                )

                # Emit tool execution log
                if self.on_thinking:
                    tool_count = len(tool_calls)
                    await self.on_thinking(
                        f"Executing {tool_count} tool call{'s' if tool_count != 1 else ''}..."
                    )

                # PERFORMANCE: Execute tools in parallel or sequential
                if self.parallel_tools and len(tool_calls) > 1:
                    results = await self._execute_tools_parallel(tool_calls)
                    for tool_name, tool_call_id, tool_args, result in results:
                        tool_calls_made += 1
                        messages.append(
                            AgentMessage(
                                role="tool",
                                content=result.to_message(),
                                tool_call_id=tool_call_id,
                                name=tool_name,
                            )
                        )
                else:
                    for tool_call in tool_calls:
                        tool_name = tool_call.get("function", {}).get("name", "")
                        tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                        tool_call_id = tool_call.get("id", str(uuid.uuid4()))

                        try:
                            tool_args = (
                                json.loads(tool_args_str)
                                if isinstance(tool_args_str, str)
                                else tool_args_str
                            )
                        except json.JSONDecodeError:
                            tool_args = {}

                        if self.on_tool_call:
                            self.on_tool_call(tool_name, tool_args)

                        result = await self._execute_tool(tool_name, tool_args)
                        tool_calls_made += 1

                        if self.on_tool_result:
                            self.on_tool_result(tool_name, result)

                        messages.append(
                            AgentMessage(
                                role="tool",
                                content=result.to_message(),
                                tool_call_id=tool_call_id,
                                name=tool_name,
                            )
                        )

                # Emit iteration complete log
                if self.on_thinking:
                    await self.on_thinking(f"Iteration {iterations} complete")

                # Continue loop to get final response after tool execution
                # The next iteration will stream the final response with tool results
                # Important: The model should provide a summary after seeing tool results
            else:
                # No tool calls - we have the final response
                # If we had tool calls in previous iterations but no content now,
                # the model should still provide a summary
                if self.on_thinking:
                    await self.on_thinking("Response complete")
                if full_content:
                    # Content was already yielded during streaming
                    pass
                # Done - return (final response was already streamed)
                return

        # Hit max iterations (unless cancelled)
        if not self._cancelled:
            if self.on_thinking:
                await self.on_thinking(f"Reached maximum iterations ({self.config.max_iterations})")
            yield f"\n\n[Reached maximum iterations ({self.config.max_iterations})]"

    def cancel(self):
        """Cancel the current agent operation."""
        self._cancelled = True

    def reset_cancellation(self):
        """Reset cancellation flag for a new operation."""
        self._cancelled = False
