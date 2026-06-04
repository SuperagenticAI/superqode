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
import os
import re
import uuid
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

from ..tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from ..tools.permissions import Permission, PermissionConfig, PermissionManager
from ..providers.gateway.base import GatewayInterface, Message, ToolDefinition
from .system_prompts import (
    SystemPromptLevel,
    get_system_prompt,
    get_job_description_prompt,
    get_provider_prompt,
)
from .session_manager import SessionManager, SessionMessage
from ..providers.profiles import resolve_model_profile, run_pre_init_once


# Module-level cache for system prompts
@lru_cache(maxsize=32)
def _cached_system_prompt(
    level: SystemPromptLevel,
    working_directory: str,
    custom_prompt: str | None,
    job_description: str | None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """Cached system prompt builder.

    At MINIMAL (the default) we substitute a provider/model-tuned prompt
    when one exists — e.g. DeepSeek V4 Flash gets a terse DS4-specific
    prompt instead of the generic one-liner. Higher levels keep the user's
    explicit choice intact.
    """
    tuned = get_provider_prompt(provider, model) if level == SystemPromptLevel.MINIMAL else ""
    if tuned:
        prompt = tuned
        if working_directory:
            prompt += f"\n\nWorking directory: {working_directory}"
    else:
        prompt = get_system_prompt(level=level, working_directory=Path(working_directory))
    try:
        from ..skills import load_project_instructions

        project_instructions = load_project_instructions(working_directory)
        if project_instructions:
            prompt += "\n\n# Project Instructions\n\n" + project_instructions
    except Exception:
        pass
    if custom_prompt:
        prompt += f"\n\n{custom_prompt}"
    if job_description:
        prompt += get_job_description_prompt(job_description)
    profile = resolve_model_profile(provider, model)
    if profile.system_prompt_suffix:
        prompt += "\n\n" + profile.system_prompt_suffix
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
            code_keywords = [
                "file",
                "code",
                "function",
                "class",
                "read",
                "write",
                "edit",
                "project",
                "repo",
                "repository",
                "readme",
                "codebase",
            ]
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


def _model_supports_tools(provider: str, model: str) -> bool:
    """Return whether a provider/model should receive tool definitions."""
    if provider == "ds4":
        return True

    try:
        from ..providers.models import MODEL_REGISTRY

        model_info = MODEL_REGISTRY.get(provider, {}).get(model)
        if model_info is not None:
            return bool(model_info.supports_tools)
    except Exception:
        pass

    # Local runtimes use arbitrary, user-chosen model names (e.g. a custom
    # Ollama tag like "gemma4-31b") that won't be in MODEL_REGISTRY. Fall back to
    # family-based detection so modern local models (Gemma 4, Qwen 3, Llama 4,
    # …) actually receive tools and can do agentic coding.
    try:
        from ..providers.local.base import likely_supports_tools

        return likely_supports_tools(model)
    except Exception:
        return False


def _ds4_should_send_tools() -> bool:
    """Return whether DS4 should receive tools for this session.

    DS4 reuses a KV-cache checkpoint based on the *rendered byte prefix* of
    every request. Adding or dropping tool definitions between turns changes
    the prefix and invalidates the cache, forcing an expensive re-prefill.
    The decision is therefore made once per session via env, not per turn.

    Set ``SUPERQODE_DS4_TOOL_MODE=never`` (or off/0/false) to disable tools
    for the whole session; default is to keep tools on so the rendered
    prefix is byte-stable.
    """
    mode = os.getenv("SUPERQODE_DS4_TOOL_MODE", "always").strip().lower()
    return mode not in {"never", "none", "off", "0", "false"}


def _should_send_tools(provider: str, model: str, user_message: str, tool_defs: List[Any]) -> bool:
    """Decide whether to pass tools to the model for this turn."""
    if not tool_defs:
        return False

    # For DS4, the decision is session-level (see _ds4_should_send_tools).
    # Do not inspect the user message — flipping tools mid-session
    # invalidates DS4's rendered-prefix KV cache.
    if provider == "ds4":
        return _ds4_should_send_tools()

    if _is_simple_conversational_query(user_message):
        return False

    from ..providers.registry import PROVIDERS, ProviderCategory

    provider_def = PROVIDERS.get(provider)
    is_local_provider = provider_def and provider_def.category == ProviderCategory.LOCAL
    if is_local_provider:
        return _model_supports_tools(provider, model)
    return True


def _looks_like_unexecuted_tool_intent(content: str) -> bool:
    """Detect narration where a model says it will inspect files but emits no tool call."""
    if not content:
        return False

    text = content.lower()
    intent_markers = [
        "let me start by",
        "let me list",
        "i'll list",
        "i will list",
        "i'll read",
        "i will read",
        "i'll inspect",
        "i will inspect",
        "i'll examine",
        "i will examine",
        "let me inspect",
        "let me examine",
        "start by listing",
        "start by reading",
    ]
    tool_targets = [
        "file",
        "files",
        "directory",
        "directories",
        "repo",
        "repository",
        "readme",
        "codebase",
        "project",
    ]
    return any(marker in text for marker in intent_markers) and any(
        target in text for target in tool_targets
    )


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
    # 0 or negative => unlimited (no cap). Positive => safety cap.
    # Aligned with fast-agent semantics where the loop runs until the model
    # stops emitting tool calls or the user cancels.
    max_iterations: int = 0  # 0 means unlimited
    require_confirmation: bool = False  # Ask before tool execution

    # Model parameters (passed through to gateway)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    reasoning_effort: Optional[str] = None

    # Plan mode - analyze without executing tools
    plan_mode: bool = False

    # Auto summarization settings
    enable_summarization: bool = False
    max_context_tokens: int = 8000

    # Session persistence (JSONL)
    enable_session_storage: bool = False
    session_storage_dir: str = ".superqode/sessions"
    session_id: Optional[str] = None
    session_history_limit: int = 20


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


class ToolApprovalRequired(RuntimeError):
    """Raised internally when a tool call must pause for HITL approval."""

    def __init__(self, tool_name: str, arguments: Dict[str, Any], tool_call_id: str | None):
        super().__init__(f"Approval required for tool: {tool_name}")
        self.tool_name = tool_name
        self.arguments = dict(arguments)
        self.tool_call_id = tool_call_id


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
        mcp_executor: Optional[
            Callable[[str, str, Dict], Awaitable[ToolResult]]
        ] = None,  # (server_id, tool_name, args) -> ToolResult
        mcp_tools: Optional[List[ToolDefinition]] = None,  # MCP tool definitions to include
        include_mcp: bool = False,  # Automatically inject MCP search/execute tools
        permission_manager: Optional[PermissionManager] = None,
        hooks: Optional["HookRegistry"] = None,  # Lifecycle hooks (before/after llm/tool/turn)
    ):
        self.gateway = gateway
        self.tools = tools
        self.config = config
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.on_thinking = on_thinking
        self.parallel_tools = parallel_tools
        self.mcp_executor = mcp_executor
        self._mcp_tools = mcp_tools or []
        self.include_mcp = include_mcp
        if self.include_mcp:
            try:
                from ..tools.mcp_tools import get_mcp_tools

                for tool in get_mcp_tools():
                    if self.tools.get(tool.name) is None:
                        self.tools.register(tool)
            except ImportError:
                pass
        if permission_manager:
            self.permission_manager = permission_manager
        elif config.require_confirmation:
            self.permission_manager = PermissionManager()
        else:
            # Still run dangerous-command checks, but allow normal tools by default.
            self.permission_manager = PermissionManager(PermissionConfig(default=Permission.ALLOW))

        # Initialize Context Manager
        from .context_manager import ContextManager

        self.context_manager = ContextManager(
            max_tokens=config.max_context_tokens,
            model_name=config.model,
        )

        # Build system prompt (cached via module-level function)
        self.system_prompt = self._build_system_prompt()

        # Session ID for tool context
        self.session_id = config.session_id or str(uuid.uuid4())

        # Session storage (JSONL) if enabled
        self._session_manager: Optional[SessionManager] = None
        if config.enable_session_storage:
            self._session_manager = SessionManager(storage_dir=config.session_storage_dir)
            self._session_manager.start_session(
                session_id=self.session_id,
                provider=config.provider,
                model=config.model,
            )

        # PERFORMANCE: Cache tool definitions at init (compute once)
        self._cached_tool_defs: List[ToolDefinition] = self._compute_tool_definitions()

        # PERFORMANCE: Cache for converted messages (avoid repeated conversions)
        self._message_cache: Dict[Tuple, Message] = {}

        # Cancellation support
        self._cancelled = False
        self.pause_on_approval = False
        self._pending_approval: Optional[Dict[str, Any]] = None
        self._approved_tool_call_ids: set[str] = set()

        # Per-model byte cap for tool output (computed once - same provider/model
        # for the lifetime of the loop). Passed into ToolContext so individual
        # tools (BashTool, web fetchers, ...) can size their truncation budget.
        from .terminal_output_limits import calculate_terminal_output_limit_for_model

        self._tool_output_byte_cap = calculate_terminal_output_limit_for_model(
            config.provider, config.model
        )

        # Lifecycle hook registry. Empty by default; plugins or test fixtures
        # register against it. See agent/hooks.py for the hook points.
        from .hooks import HookRegistry

        self.hooks: HookRegistry = hooks if hooks is not None else HookRegistry()
        self._current_iteration: int = 0
        # session_start fires once per AgentLoop instance, on the first run().
        self._session_started: bool = False

    def _build_system_prompt(self) -> str:
        """Build the system prompt based on config (uses cached function)."""
        return _cached_system_prompt(
            level=self.config.system_prompt_level,
            working_directory=str(self.config.working_directory),
            custom_prompt=self.config.custom_system_prompt,
            job_description=self.config.job_description,
            provider=self.config.provider,
            model=self.config.model,
        )

    def _profile_kwargs(self) -> Dict[str, Any]:
        """Resolve the active model profile's request kwargs.

        Runs ``pre_init`` once per spec, then returns the profile's
        ``init_kwargs`` merged with ``init_kwargs_factory()`` output.
        Caller-supplied kwargs at the gateway call site still override
        these — caller wins by passing them as explicit arguments.
        """
        run_pre_init_once(self.config.provider, self.config.model)
        profile = resolve_model_profile(self.config.provider, self.config.model)
        return profile.resolve_kwargs()

    def _compute_tool_definitions(self) -> List[ToolDefinition]:
        """Compute tool definitions once at init.

        Definitions are sorted by name so that the rendered request prefix is
        byte-stable across processes. This matters for providers that key a
        cached KV checkpoint on the rendered prefix (DS4, Anthropic prompt
        caching, OpenAI prompt caching); even a reordering of tool schemas
        forces a cold prefill.
        """
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

        # Inject MCP search/execute tools if requested
        if self.include_mcp:
            try:
                from ..tools.mcp_tools import get_mcp_tools

                mcp_tools = get_mcp_tools()
                for t in mcp_tools:
                    # Avoid duplicates
                    if not any(d.name == t.name for d in definitions):
                        definitions.append(
                            ToolDefinition(
                                name=t.name,
                                description=t.description,
                                parameters=t.parameters,
                            )
                        )
            except ImportError:
                pass

        # Add explicitly passed MCP tools if available
        definitions.extend(self._mcp_tools)

        # Hide tools the resolved model profile excludes.
        profile = resolve_model_profile(self.config.provider, self.config.model)
        if profile.excluded_tools:
            definitions = [d for d in definitions if d.name not in profile.excluded_tools]

        definitions.sort(key=lambda d: d.name)
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

    def _load_stored_messages(self) -> List[AgentMessage]:
        """Load stored conversation messages for resumed sessions."""
        if not self._session_manager:
            return []

        restored: List[AgentMessage] = []
        for message in self._session_manager.get_messages(limit=self.config.session_history_limit):
            restored.append(
                AgentMessage(
                    role=message.role,
                    content=message.content,
                    tool_calls=message.tool_calls,
                    name=message.tool_name,
                )
            )
        return restored

    def _create_tool_context(self) -> ToolContext:
        """Create context for tool execution."""
        return ToolContext(
            session_id=self.session_id,
            working_directory=self.config.working_directory,
            require_confirmation=self.config.require_confirmation,
            tool_registry=self.tools,
            sub_agent_runner=self._run_sub_agent,
            max_output_bytes=self._tool_output_byte_cap,
        )

    def _lifecycle_context(self) -> "LifecycleContext":
        """Build the lifecycle context passed to hooks."""
        from .hooks import LifecycleContext

        return LifecycleContext(
            session_id=self.session_id,
            provider=self.config.provider,
            model=self.config.model,
            working_directory=self.config.working_directory,
            iteration=self._current_iteration,
        )

    async def _run_sub_agent(self, task_description: str, metadata: Dict[str, Any]) -> str:
        """Run a delegated task in an isolated child AgentLoop."""
        child_depth = int(metadata.get("delegation_depth", 1))
        allowed_tools = metadata.get("allowed_tools")

        child_tools = self.tools
        if allowed_tools is not None:
            child_tools = self.tools.filtered(list(allowed_tools))

        child_config = replace(
            self.config,
            session_id=f"{self.session_id}:sub:{uuid.uuid4().hex[:8]}",
            enable_session_storage=False,
        )

        # Sub-agent shares the parent's runtime. For Phase 1 the parent always
        # *is* an AgentLoop (builtin runtime), so direct instantiation is correct.
        # Phase 2 TODO: propagate the parent's runtime name when ADK / other
        # backends can host sub-agents, and construct via create_runtime().
        child_loop = AgentLoop(
            gateway=self.gateway,
            tools=child_tools,
            config=child_config,
            on_tool_call=self.on_tool_call,
            on_tool_result=self.on_tool_result,
            on_thinking=self.on_thinking,
            parallel_tools=self.parallel_tools,
            mcp_executor=self.mcp_executor,
            mcp_tools=self._mcp_tools,
            include_mcp=self.include_mcp,
            permission_manager=self.permission_manager,
        )
        child_loop.session_id = child_config.session_id or child_loop.session_id

        original_create_context = child_loop._create_tool_context

        def create_child_context() -> ToolContext:
            ctx = original_create_context()
            ctx.delegation_depth = child_depth
            return ctx

        child_loop._create_tool_context = create_child_context  # type: ignore[method-assign]
        result = await child_loop.run(task_description)

        if result.stopped_reason == "complete":
            return result.content
        if result.error:
            raise RuntimeError(result.error)
        raise RuntimeError(f"Sub-agent stopped: {result.stopped_reason}")

    async def _check_tool_permission(
        self, name: str, arguments: Dict[str, Any], tool_call_id: Optional[str] = None
    ) -> Optional[ToolResult]:
        """Apply central permission checks before any local tool executes.

        Order of authority:

        1. ``permission_request`` hooks fire first and can **deny** any call -
           even one the manager would auto-allow - so a harness permission policy
           (or custom hook) can veto allowed tools. A hook **allow** pre-approves
           an otherwise-ASK call.
        2. The manager's own **deny** (e.g. dangerous-command guards) still wins
           over a permissive hook - hard safety rules are not overridable.
        3. Manager **allow** passes through; otherwise (ASK) we honour a hook
           allow or fall back to the pause/prompt flow.
        """
        from .hooks import PERMISSION_REQUEST

        verdict = await self.hooks.fire_decision(
            PERMISSION_REQUEST, self._lifecycle_context(), name, arguments
        )
        if verdict.denied:
            return ToolResult(
                success=False,
                output="",
                error=verdict.message or f"Permission denied for tool: {name}",
                metadata={
                    "permission": "hook_denied",
                    "tool": name,
                    **({"reason": verdict.reason} if verdict.reason else {}),
                },
            )

        permission = self.permission_manager.check_permission(name, arguments)
        if permission == Permission.DENY:
            return ToolResult(
                success=False,
                output="",
                error=f"Permission denied for tool: {name}",
                metadata={"permission": "deny", "tool": name},
            )
        if permission == Permission.ALLOW:
            return None
        if tool_call_id and tool_call_id in self._approved_tool_call_ids:
            return None
        if verdict.allowed:
            return None

        if self.pause_on_approval:
            self._pending_approval = {
                "index": 0,
                "tool_name": name,
                "arguments": dict(arguments),
                "tool_call_id": tool_call_id,
            }
            raise ToolApprovalRequired(name, arguments, tool_call_id)

        approved = await self.permission_manager.request_permission(
            name,
            arguments,
            description=f"Agent requested tool `{name}`",
        )
        if approved:
            return None
        return ToolResult(
            success=False,
            output="",
            error=f"Permission required for tool: {name}",
            metadata={"permission": "ask_denied", "tool": name},
        )

    async def _execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        tool_call_id: Optional[str] = None,
    ) -> ToolResult:
        """Execute a single tool call.

        ``tool_call_id`` is threaded through so any tool calls nested
        inside this one (e.g. tools invoked by a sub-agent spawned via
        SubAgentTool) inherit it as ``parentToolCallId`` in their ACP
        ``_meta`` payload. Optional for backwards compatibility — if a
        caller doesn't supply it, no parent linkage is recorded.

        Hook coverage: ``before_tool_call`` fires once before any work
        happens; ``after_tool_call`` fires once with the final ``ToolResult``,
        even for permission denials and unknown-tool errors, so audit/log
        hooks see every attempted call.
        """
        from ..acp.tool_call_context import acp_tool_call_context
        from .hooks import AFTER_TOOL_CALL, BEFORE_TOOL_CALL

        lifecycle_ctx = self._lifecycle_context()

        async def _finalize(result: ToolResult) -> ToolResult:
            await self.hooks.fire(AFTER_TOOL_CALL, lifecycle_ctx, name, arguments, result)
            return result

        # Handler hooks can deny a tool call outright or rewrite its arguments
        # before execution. Deny short-circuits; modify swaps in new arguments
        # that the rest of this call (and the after-hook) see.
        gate = await self.hooks.fire_decision(BEFORE_TOOL_CALL, lifecycle_ctx, name, arguments)
        if gate.denied:
            denied = (
                gate.result
                if isinstance(gate.result, ToolResult)
                else ToolResult(
                    success=False,
                    output="",
                    error=gate.message or f"Tool call blocked by hook: {name}",
                    metadata={
                        "permission": "hook_denied",
                        "tool": name,
                        **({"reason": gate.reason} if gate.reason else {}),
                    },
                )
            )
            return await _finalize(denied)
        if gate.modified:
            arguments = gate.arguments

        tool = self.tools.get(name)

        if not tool:
            # Check if it's an MCP tool (format: mcp_serverid_toolname)
            if self.mcp_executor and name.startswith("mcp_"):
                denied = await self._check_tool_permission(name, arguments, tool_call_id)
                if denied:
                    return await _finalize(denied)
                parts = name.split(
                    "_", 2
                )  # mcp_serverid_toolname -> ["mcp", serverid", "toolname"]
                if len(parts) == 3:
                    server_id = parts[1]
                    tool_name = parts[2]
                    try:
                        result = await self.mcp_executor(server_id, tool_name, arguments)
                        return await _finalize(result)
                    except Exception as e:
                        return await _finalize(
                            ToolResult(success=False, output="", error=f"MCP tool error: {str(e)}")
                        )
            return await _finalize(
                ToolResult(success=False, output="", error=f"Unknown tool: {name}")
            )

        denied = await self._check_tool_permission(name, arguments, tool_call_id)
        if denied:
            return await _finalize(denied)

        ctx = self._create_tool_context()

        try:
            # Set this call's id as the parent for anything it spawns.
            # ContextVar propagates through asyncio.create_task automatically,
            # so SubAgentTool's background _execute_subtask sees it too.
            with acp_tool_call_context(parent_tool_call_id=tool_call_id):
                result = await tool.execute(arguments, ctx)
            return await _finalize(result)
        except Exception as e:
            return await _finalize(
                ToolResult(success=False, output="", error=f"Tool execution error: {str(e)}")
            )

    async def _maybe_summarize(self, messages: List["AgentMessage"]) -> List["AgentMessage"]:
        """Compact or prune messages when context exceeds the limit.

        Strategy:
        1. Estimate tokens; bail if under the limit.
        2. Try LLM-backed structured compaction (9-section template). Replace
           the head of history with the summary; keep the system prompt and a
           short tail of recent turns intact so the next assistant turn has
           live context to work with.
        3. If compaction fails or returns nothing, fall back to mechanical
           prune-from-front so the loop can still make progress.
        """
        if not self.config.enable_summarization:
            return messages

        msg_dicts = [
            {
                "role": m.role,
                "content": m.content,
                "tool_calls": m.tool_calls,
                "tool_result": m.content if m.role == "tool" else None,
            }
            for m in messages
        ]
        token_count = self.context_manager.count_tokens(msg_dicts)
        if token_count <= self.config.max_context_tokens:
            return messages

        # before_compact handler hooks may skip this round (DENY) - e.g. to defer
        # compaction until a logical boundary - while observers can record it.
        from .hooks import AFTER_COMPACT, BEFORE_COMPACT

        lifecycle_ctx = self._lifecycle_context()
        pre = await self.hooks.fire_decision(
            BEFORE_COMPACT,
            lifecycle_ctx,
            token_count,
            self.config.max_context_tokens,
        )
        if pre.denied:
            return messages

        if self.on_thinking:
            await self.on_thinking(
                f"Context management active ({token_count} tokens). Compacting earlier turns..."
            )

        from .compaction import compact_history

        keep_tail = 4
        system_prefix = [m for m in messages if m.role == "system"][:1]
        body = (
            [m for m in messages if m.role != "system" or m is not system_prefix[0]]
            if system_prefix
            else list(messages)
        )

        strategy = "prune"
        result_messages: List["AgentMessage"]
        if len(body) > keep_tail:
            head = body[:-keep_tail]
            tail = body[-keep_tail:]
            summary = await compact_history(
                head,
                self.gateway,
                self.config.provider,
                self.config.model,
            )
            if summary:
                summary_msg = AgentMessage(
                    role="system",
                    content=f"[Earlier conversation summary]\n\n{summary}",
                )
                result_messages = system_prefix + [summary_msg] + tail
                strategy = "summary"

        if strategy != "summary":
            # Fallback: mechanical prune-from-front (existing path).
            pruned_dicts = self.context_manager.prune_history(msg_dicts)
            result_messages = [
                AgentMessage(role=d["role"], content=d["content"], tool_calls=d.get("tool_calls"))
                for d in pruned_dicts
            ]

        await self.hooks.fire(
            AFTER_COMPACT,
            lifecycle_ctx,
            token_count,
            result_messages,
            strategy,
        )
        return result_messages

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

            result = await self._execute_tool(tool_name, tool_args, tool_call_id=tool_call_id)

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
            if isinstance(r, ToolApprovalRequired):
                raise r
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
        from .hooks import SESSION_START, STOP, USER_PROMPT_SUBMIT

        lifecycle_ctx = self._lifecycle_context()

        async def _finish(response: AgentResponse) -> AgentResponse:
            await self.hooks.fire(STOP, self._lifecycle_context(), response)
            return response

        if not self._session_started:
            self._session_started = True
            await self.hooks.fire(SESSION_START, lifecycle_ctx, user_message)

        # user_prompt_submit handler hooks may block a prompt outright (DENY),
        # e.g. policy filters. Deny returns immediately without calling the model.
        submit = await self.hooks.fire_decision(USER_PROMPT_SUBMIT, lifecycle_ctx, user_message)
        if submit.denied:
            return await _finish(
                AgentResponse(
                    content=submit.message or "Prompt blocked by policy.",
                    messages=[],
                    tool_calls_made=0,
                    iterations=0,
                    stopped_reason="blocked",
                )
            )

        messages: List[AgentMessage] = []

        # Add system message if we have one
        if self.system_prompt:
            messages.append(AgentMessage(role="system", content=self.system_prompt))

        messages.extend(self._load_stored_messages())

        # Add user message
        messages.append(AgentMessage(role="user", content=user_message))

        # Save to session storage if enabled
        if self._session_manager:
            self._session_manager.add_user_message(user_message)

        tool_calls_made = 0
        iterations = 0
        unexecuted_tool_intent_retries = 0
        max_unexecuted_tool_intent_retries = 1

        # Emit initial processing log
        if self.on_thinking:
            await self.on_thinking("Processing request...")

        # Get cached tool definitions (computed once at init)
        tool_defs = self._get_tool_definitions()

        # Always send tools if available - let malformed tool call handling deal with issues
        # This ensures models always get the full context and we handle malformed responses gracefully
        # max_iterations <= 0 means unlimited (loop until the model stops)
        _cap = self.config.max_iterations
        while _cap <= 0 or iterations < _cap:
            iterations += 1
            self._current_iteration = iterations
            turn_tool_results: List[ToolResult] = []

            # Emit iteration log
            if self.on_thinking:
                await self.on_thinking(
                    f"Calling model {self.config.provider}/{self.config.model}... (iteration {iterations})"
                )

            # PERFORMANCE: Use cached message conversion
            gateway_messages = self._convert_messages(messages)

            # Plan mode: disable tools so model only analyzes/plans without executing
            tools_to_send = None
            if not self.config.plan_mode:
                tools_to_send = (
                    tool_defs
                    if _should_send_tools(
                        self.config.provider,
                        self.config.model,
                        user_message,
                        tool_defs,
                    )
                    else None
                )
            elif self.on_thinking:
                await self.on_thinking("Plan Mode: Analyzing without executing tools...")

            # Call the model
            from .hooks import (
                AFTER_LLM_CALL,
                BEFORE_LLM_CALL,
            )

            lifecycle_ctx = self._lifecycle_context()
            await self.hooks.fire(BEFORE_LLM_CALL, lifecycle_ctx, messages, tools_to_send)
            try:
                response = await self.gateway.chat_completion(
                    messages=gateway_messages,
                    model=self.config.model,
                    provider=self.config.provider,
                    tools=tools_to_send,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    reasoning_effort=self.config.reasoning_effort,
                    **self._profile_kwargs(),
                )
            except Exception as e:
                return await _finish(
                    AgentResponse(
                        content="",
                        messages=messages,
                        tool_calls_made=tool_calls_made,
                        iterations=iterations,
                        stopped_reason="error",
                        error=str(e),
                    )
                )
            await self.hooks.fire(AFTER_LLM_CALL, lifecycle_ctx, response)

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
                        return await _finish(
                            AgentResponse(
                                content=content,
                                messages=messages,
                                tool_calls_made=tool_calls_made,
                                iterations=iterations,
                                stopped_reason="complete",
                            )
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

                # Save to session storage
                if self._session_manager:
                    self._session_manager.add_assistant_message(
                        response_content, response.tool_calls
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
                    try:
                        results = await self._execute_tools_parallel(response.tool_calls)
                    except ToolApprovalRequired:
                        return await _finish(
                            AgentResponse(
                                content="",
                                messages=messages,
                                tool_calls_made=tool_calls_made,
                                iterations=iterations,
                                stopped_reason="needs_approval",
                            )
                        )
                    for tool_name, tool_call_id, tool_args, result in results:
                        tool_calls_made += 1
                        turn_tool_results.append(result)
                        messages.append(
                            AgentMessage(
                                role="tool",
                                content=result.to_message(),
                                tool_call_id=tool_call_id,
                                name=tool_name,
                            )
                        )
                        if self._session_manager:
                            self._session_manager.add_tool_result(tool_name, result.to_message())
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

                        try:
                            result = await self._execute_tool(
                                tool_name, tool_args, tool_call_id=tool_call_id
                            )
                        except ToolApprovalRequired:
                            return await _finish(
                                AgentResponse(
                                    content="",
                                    messages=messages,
                                    tool_calls_made=tool_calls_made,
                                    iterations=iterations,
                                    stopped_reason="needs_approval",
                                )
                            )
                        tool_calls_made += 1
                        turn_tool_results.append(result)

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

                from .hooks import AFTER_TURN_COMPLETE

                await self.hooks.fire(
                    AFTER_TURN_COMPLETE,
                    lifecycle_ctx,
                    response,
                    turn_tool_results,
                )

                # Auto-summarize if enabled and context is too large
                if self.config.enable_summarization:
                    messages = await self._maybe_summarize(messages)

            else:
                # No tool calls - return the response content
                if (
                    tools_to_send
                    and _looks_like_unexecuted_tool_intent(response_content)
                    and unexecuted_tool_intent_retries < max_unexecuted_tool_intent_retries
                ):
                    unexecuted_tool_intent_retries += 1
                    messages.append(AgentMessage(role="assistant", content=response_content))
                    messages.append(
                        AgentMessage(
                            role="user",
                            content=(
                                "You described using tools, but no tool call was emitted. "
                                "Call the appropriate tool now. Do not narrate the tool use."
                            ),
                        )
                    )
                    if self.on_thinking:
                        await self.on_thinking(
                            "Model described tool use without calling a tool; retrying."
                        )
                    continue
                if (
                    tools_to_send
                    and _looks_like_unexecuted_tool_intent(response_content)
                    and self.on_thinking
                ):
                    await self.on_thinking(
                        "Model still described tool use without calling a tool; returning response."
                    )
                if self.on_thinking:
                    await self.on_thinking("Response complete")
                from .hooks import AFTER_TURN_COMPLETE

                await self.hooks.fire(
                    AFTER_TURN_COMPLETE,
                    lifecycle_ctx,
                    response,
                    turn_tool_results,
                )
                final = AgentResponse(
                    content=response_content,
                    messages=messages,
                    tool_calls_made=tool_calls_made,
                    iterations=iterations,
                    stopped_reason="complete",
                )
                return await _finish(final)

        # Hit max iterations (only reachable when a positive cap is configured)
        if self.on_thinking:
            await self.on_thinking(f"Reached maximum iterations ({self.config.max_iterations})")
        return await _finish(
            AgentResponse(
                content="",
                messages=messages,
                tool_calls_made=tool_calls_made,
                iterations=iterations,
                stopped_reason="max_iterations",
                error=f"Reached maximum iterations ({self.config.max_iterations})",
            )
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

        messages.extend(self._load_stored_messages())

        messages.append(AgentMessage(role="user", content=user_message))
        if self._session_manager:
            self._session_manager.add_user_message(user_message)

        iterations = 0
        tool_calls_made = 0

        # Emit initial processing log
        if self.on_thinking:
            await self.on_thinking("Processing request...")

        # Get cached tool definitions
        tool_defs = self._get_tool_definitions()

        # max_iterations <= 0 means unlimited (loop until the model stops)
        _cap = self.config.max_iterations
        while _cap <= 0 or iterations < _cap:
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

            tools_to_send = None
            if not self.config.plan_mode:
                tools_to_send = (
                    tool_defs
                    if _should_send_tools(
                        self.config.provider,
                        self.config.model,
                        user_message,
                        tool_defs,
                    )
                    else None
                )
            elif self.on_thinking:
                await self.on_thinking("Plan Mode: Analyzing without executing tools...")

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
                    reasoning_effort=self.config.reasoning_effort,
                    **self._profile_kwargs(),
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
                # Streaming can fail for some provider/model combinations even when
                # a non-streaming request would succeed. Retry once before failing.
                try:
                    if self.on_thinking:
                        await self.on_thinking(
                            "Streaming failed; retrying once with non-streaming completion..."
                        )
                    fallback = await self.gateway.chat_completion(
                        messages=gateway_messages,
                        model=self.config.model,
                        provider=self.config.provider,
                        tools=tools_to_send,
                        temperature=self.config.temperature,
                        max_tokens=self.config.max_tokens,
                        reasoning_effort=self.config.reasoning_effort,
                        **self._profile_kwargs(),
                    )
                    if fallback.tool_calls:
                        tool_calls.extend(fallback.tool_calls)
                    if fallback.content and fallback.content.strip():
                        full_content = fallback.content
                        yield fallback.content
                        had_content = True
                    elif not fallback.tool_calls:
                        raise RuntimeError("Fallback completion returned no content")
                except Exception:
                    error_msg = str(e)
                    error_type = type(e).__name__
                    # Yield original streaming error for maximum transparency
                    yield f"\n\n[Error: {error_type}] {error_msg}"
                    full_content = f"[Error: {error_type}] {error_msg}"
                    return

            # Some providers may return an empty stream even when the request succeeded.
            # Retry once with non-streaming completion so users still get a response.
            if not full_content.strip() and not tool_calls:
                if self.on_thinking:
                    await self.on_thinking(
                        "No streamed text received; retrying once with non-streaming completion..."
                    )
                try:
                    fallback = await self.gateway.chat_completion(
                        messages=gateway_messages,
                        model=self.config.model,
                        provider=self.config.provider,
                        tools=tools_to_send,
                        temperature=self.config.temperature,
                        max_tokens=self.config.max_tokens,
                        **self._profile_kwargs(),
                    )
                    if fallback.tool_calls:
                        tool_calls.extend(fallback.tool_calls)
                    if fallback.content and fallback.content.strip():
                        full_content = fallback.content
                        yield fallback.content
                        had_content = True
                except Exception as e:
                    error_msg = str(e)
                    error_type = type(e).__name__
                    yield f"\n\n[Error: {error_type}] {error_msg}"
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
                if self._session_manager:
                    self._session_manager.add_assistant_message(full_content, tool_calls)

                # Emit tool execution log
                if self.on_thinking:
                    tool_count = len(tool_calls)
                    await self.on_thinking(
                        f"Executing {tool_count} tool call{'s' if tool_count != 1 else ''}..."
                    )

                # PERFORMANCE: Execute tools in parallel or sequential
                if self.parallel_tools and len(tool_calls) > 1:
                    try:
                        results = await self._execute_tools_parallel(tool_calls)
                    except ToolApprovalRequired:
                        return
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
                        if self._session_manager:
                            self._session_manager.add_tool_result(tool_name, result.to_message())
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

                        try:
                            result = await self._execute_tool(
                                tool_name, tool_args, tool_call_id=tool_call_id
                            )
                        except ToolApprovalRequired:
                            return
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
                        if self._session_manager:
                            self._session_manager.add_tool_result(tool_name, result.to_message())

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
                if self._session_manager and full_content.strip():
                    self._session_manager.add_assistant_message(full_content)
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
