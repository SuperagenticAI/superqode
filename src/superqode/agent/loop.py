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


def _content_for_counting(content: Any) -> str:
    """Token-estimation text for message content.

    Multimodal list content (text + image parts) must not be str()'d for
    counting - a 4MB image data URL would register as ~1M tokens and stampede
    compaction. Text parts count normally; each image part is charged a flat
    ~1000-token equivalent.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: List[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                pieces.append(str(part.get("text", "")))
            else:
                pieces.append("x" * 4000)  # ~1000-token flat charge per image part
        return "\n".join(pieces)
    return str(content)


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
    # content may be a multimodal list (text + image parts) - make it hashable.
    content = m.content if isinstance(m.content, str) else _make_hashable(m.content)
    return (m.role, content, tool_calls_tuple, m.tool_call_id, m.name)


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

    # Doom-loop guard: block the Nth consecutive identical tool call and feed
    # corrective guidance back to the model; abort the run if it immediately
    # repeats the same call anyway. 0 disables. Local models are the main
    # beneficiaries - they get stuck re-issuing the same failing call.
    doom_loop_threshold: int = 3

    # When the model's output is cut at the max-token limit
    # (finish_reason == "length"), automatically ask it to continue from where
    # it stopped, up to this many times per run. 0 disables.
    max_auto_continues: int = 2

    # Rubric self-grading: when set, a separate grader call judges the final
    # answer against this rubric; "needs_revision" feedback re-enters the loop
    # (at most max_rubric_rounds times). None disables.
    rubric: Optional[str] = None
    max_rubric_rounds: int = 2

    # How tool calls reach the model. None/"native" uses the provider's tool
    # channel (today's behavior; "compact-json"/"strict-json" are argument
    # style hints for native calls). "prompt" renders tool schemas into the
    # system prompt and parses <tool_call>{...}</tool_call> blocks from the
    # response text - for local models with no native tool-calling head.
    tool_call_format: Optional[str] = None

    # Auto summarization / context compaction.
    # Compaction is now ADAPTIVE and on by default (opt out with
    # SUPERQODE_AUTO_COMPACT=0). The threshold and kept-recent window are derived
    # from the model's real context window so small local models don't overflow
    # and large models aren't compacted prematurely.
    enable_summarization: bool = False  # legacy explicit opt-in (still honored)
    max_context_tokens: int = 8000  # fallback only when the model window is unknown
    context_window: int = 0  # the model's real window; 0 => auto-detect from model info
    compaction_reserve_tokens: int = 0  # 0 => auto (~15% of window, capped at 16k)
    keep_recent_tokens: int = 0  # 0 => auto (~40% of window, capped at 24k)

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


def repair_dangling_tool_calls(messages: List["AgentMessage"]) -> List["AgentMessage"]:
    """Ensure every assistant tool_call is followed by a tool result.

    A *dangling* tool_call is one an assistant requested that never got a result
    — caused by an interrupted/cancelled run, an approval pause, a malformed or
    truncated tool call (common with small local models), or a resumed session
    that ended mid-call. Providers reject such a history ("tool_calls must be
    followed by tool results"), so we synthesize a short result for each
    unanswered call, keeping the conversation valid and letting the agent
    recover gracefully.

    Matching prefers ``tool_call_id`` but falls back to positional order, since
    resumed tool messages may not carry ids. Returns a new list; the input is
    not mutated. Idempotent — re-running it adds nothing new.
    """
    if not messages:
        return messages

    out: List["AgentMessage"] = []
    i, n = 0, len(messages)
    while i < n:
        msg = messages[i]
        out.append(msg)
        tool_calls = msg.tool_calls if msg.role == "assistant" else None
        if not tool_calls:
            i += 1
            continue

        # Collect the consecutive tool-result messages that follow this call.
        j = i + 1
        following: List["AgentMessage"] = []
        while j < n and messages[j].role == "tool":
            following.append(messages[j])
            j += 1
        out.extend(following)

        answered_ids = {m.tool_call_id for m in following if m.tool_call_id}
        # Calls not satisfied by a matching id.
        remaining = [tc for tc in tool_calls if not (tc.get("id") and tc.get("id") in answered_ids)]
        # Tool results without an id answer the remaining calls positionally.
        idless = sum(1 for m in following if not m.tool_call_id)
        unanswered = remaining[idless:]

        for tc in unanswered:
            tc_id = tc.get("id") or str(uuid.uuid4())
            name = (tc.get("function") or {}).get("name") or tc.get("name") or "unknown"
            out.append(
                AgentMessage(
                    role="tool",
                    content=(
                        f"[Tool call '{name}' did not complete - it was interrupted, "
                        "cancelled, or its arguments were malformed/truncated. "
                        "Continue without its result.]"
                    ),
                    tool_call_id=tc_id,
                    name=name,
                )
            )
        i = j
    return out


@dataclass
class AgentResponse:
    """Response from the agent loop."""

    content: str
    messages: List[AgentMessage]
    tool_calls_made: int
    iterations: int
    stopped_reason: str  # "complete", "max_iterations", "error"
    error: Optional[str] = None
    # Populated by headless --output-schema runs: the extracted JSON payload
    # and any schema-validation errors (empty list means valid).
    structured_output: Optional[Any] = None
    schema_errors: Optional[List[str]] = None


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
        allow_peer_agents: bool = True,  # False inside sub/peer agents (no nesting)
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

        # Apply the deferred-tool policy (env-gated) before the first compute
        # so heavy schemas stay out of the prompt until tool_search loads them.
        try:
            from ..tools.tool_search import apply_deferred_tool_policy

            apply_deferred_tool_policy(self.tools, provider=config.provider, model=config.model)
        except ImportError:
            pass

        # PERFORMANCE: Cache tool definitions, recomputed when the registry
        # version changes (deferred-tool activation).
        self._cached_tool_defs: List[ToolDefinition] = self._compute_tool_definitions()
        self._cached_tool_defs_version: int = getattr(self.tools, "version", 0)

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

        # Doom-loop guard; re-armed at the start of each run.
        from .loop_guard import DoomLoopDetector

        self._doom_guard: Optional[DoomLoopDetector] = None

        # In-run steering: user messages queued while the agent works are
        # injected at the next iteration boundary instead of waiting for the
        # whole run to finish. Thread-safe - the TUI enqueues from its own
        # thread.
        import collections
        import threading

        self._steering_queue: "collections.deque[str]" = collections.deque()
        self._steering_lock = threading.Lock()
        self.run_active: bool = False

        # Per-call system reminders (changed files, stale todos).
        self._reminder_state: Dict[str, Any] = {}

        # Aggregate diff of the most recent turn's file changes.
        self.last_turn_diff: str = ""

        # Peer agents (spawn_agent/...). Lazily created; None inside
        # sub/peer agents so the hierarchy stays one level deep.
        self._allow_peer_agents = allow_peer_agents
        self._peer_manager: Optional[Any] = None

    def _exec_policy(self):
        """User exec-policy rules, loaded once per loop instance."""
        if not hasattr(self, "_exec_policy_cache"):
            from .exec_policy import ExecPolicy

            self._exec_policy_cache = ExecPolicy.load(self.config.working_directory)
        return self._exec_policy_cache

    def _prompt_tool_mode(self) -> bool:
        """True when tools go through the prompt instead of the native channel."""
        from .text_tool_calls import is_prompt_format

        return self.config.tools_enabled and is_prompt_format(self.config.tool_call_format)

    def _system_prompt_for_run(self) -> str:
        """System prompt, plus the rendered tool catalog in prompt-tool mode."""
        if not self._prompt_tool_mode():
            return self.system_prompt
        from .text_tool_calls import render_tool_catalog

        catalog = render_tool_catalog(self._get_tool_definitions())
        return f"{self.system_prompt}\n{catalog}" if catalog else self.system_prompt

    def _extract_prompt_tool_calls(
        self, content: str, native_tool_calls: Optional[List[Dict]]
    ) -> Tuple[str, Optional[List[Dict]]]:
        """In prompt-tool mode, lift <tool_call> blocks out of response text."""
        if not self._prompt_tool_mode() or native_tool_calls:
            return content, native_tool_calls
        from .text_tool_calls import extract_text_tool_calls

        cleaned, extracted = extract_text_tool_calls(content or "")
        if extracted:
            return cleaned, extracted
        return content, native_tool_calls

    def _get_peer_manager(self):
        if not self._allow_peer_agents:
            return None
        if self._peer_manager is None:
            from .peer_agents import PeerAgentManager

            self._peer_manager = PeerAgentManager(self._create_peer_loop)
        return self._peer_manager

    def _create_peer_loop(self, task_name: str) -> "AgentLoop":
        """Build an isolated loop for one peer agent (no nesting, no storage)."""
        peer_config = replace(
            self.config,
            session_id=f"{self.session_id}:peer:{task_name}",
            enable_session_storage=False,
        )
        return AgentLoop(
            gateway=self.gateway,
            tools=self.tools,
            config=peer_config,
            on_tool_call=self.on_tool_call,
            on_tool_result=self.on_tool_result,
            on_thinking=self.on_thinking,
            parallel_tools=self.parallel_tools,
            mcp_executor=self.mcp_executor,
            mcp_tools=self._mcp_tools,
            include_mcp=self.include_mcp,
            permission_manager=self.permission_manager,
            allow_peer_agents=False,
        )

    def _doom_threshold(self) -> int:
        """Doom-loop threshold; SUPERQODE_DOOM_LOOP_THRESHOLD overrides config."""
        raw = os.environ.get("SUPERQODE_DOOM_LOOP_THRESHOLD", "").strip()
        if raw:
            try:
                return max(0, int(raw))
            except ValueError:
                pass
        return self.config.doom_loop_threshold

    def _arm_doom_guard(self) -> None:
        from .loop_guard import DoomLoopDetector

        self._doom_guard = DoomLoopDetector(self._doom_threshold())

    # ------------------------------------------------------------------
    # In-run steering: messages typed while the agent works
    # are injected between iterations, not after the run.
    # ------------------------------------------------------------------

    def steer(self, message: str) -> bool:
        """Queue a user message for injection at the next iteration boundary.

        Safe to call from any thread. Returns True when a run is active (the
        message will be picked up mid-run); False when idle (the caller
        should submit it as a normal prompt instead).
        """
        text = (message or "").strip()
        if not text:
            return self.run_active
        with self._steering_lock:
            self._steering_queue.append(text)
        return self.run_active

    def steering_pending(self) -> bool:
        with self._steering_lock:
            return bool(self._steering_queue)

    def _drain_steering(self, messages: List["AgentMessage"]) -> List[str]:
        """Move queued steering messages into the conversation. Returns them."""
        with self._steering_lock:
            drained = list(self._steering_queue)
            self._steering_queue.clear()
        for text in drained:
            messages.append(AgentMessage(role="user", content=text))
            if self._session_manager:
                self._session_manager.add_user_message(text)
        return drained

    def _collect_reminder_messages(
        self, iteration: int, user_message: str = ""
    ) -> List["AgentMessage"]:
        """Per-call synthetic reminders; attached to the request, never to history."""
        try:
            from .reminders import collect_reminders, format_reminder_message

            texts = collect_reminders(
                session_id=self.session_id,
                working_directory=self.config.working_directory,
                iteration=iteration,
                state=self._reminder_state,
                user_message=user_message,
            )
        except Exception:
            return []
        if not texts:
            return []
        return [AgentMessage(role="user", content=format_reminder_message(texts))]

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
        """Compute tool definitions for the current registry state.

        Definitions are sorted by name so that the rendered request prefix is
        byte-stable across processes. This matters for providers that key a
        cached KV checkpoint on the rendered prefix (DS4, Anthropic prompt
        caching, OpenAI prompt caching); even a reordering of tool schemas
        forces a cold prefill.

        Deferred tools (see ``ToolRegistry.defer`` / the tool_search tool) are
        excluded until activated; recomputation happens whenever the registry
        version changes.
        """
        if not self.config.tools_enabled:
            return []

        definitions = []
        active = (
            self.tools.active_tools() if hasattr(self.tools, "active_tools") else self.tools.list()
        )
        for tool in active:
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
        """Get tool definitions, recomputing when the registry changed.

        The cache is keyed by the registry version so activating a deferred
        tool (tool_search) is visible on the very next model call, while the
        common case stays a single attribute read.
        """
        version = getattr(self.tools, "version", 0)
        if version != self._cached_tool_defs_version:
            self._cached_tool_defs = self._compute_tool_definitions()
            self._cached_tool_defs_version = version
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
        """Convert messages to gateway format, repairing any dangling tool calls.

        Every model send goes through here, so this is where we guarantee the
        history is valid (each assistant tool_call has a tool result).
        """
        return [self._convert_message(m) for m in repair_dangling_tool_calls(messages)]

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
        # A session may have been saved mid-tool-call; repair so the resumed
        # history is valid before the first model send.
        return repair_dangling_tool_calls(restored)

    def _create_tool_context(self) -> ToolContext:
        """Create context for tool execution."""
        return ToolContext(
            session_id=self.session_id,
            working_directory=self.config.working_directory,
            require_confirmation=self.config.require_confirmation,
            tool_registry=self.tools,
            sub_agent_runner=self._run_sub_agent,
            max_output_bytes=self._tool_output_byte_cap,
            peer_manager=self._get_peer_manager(),
            permission_manager=self.permission_manager,
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
            allow_peer_agents=False,
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
        2. User exec-policy rules (.superqode/execpolicy.yaml) apply to shell
           commands: ``deny`` blocks outright, ``ask`` forces the approval
           prompt even for auto-allowed commands, ``allow`` pre-approves an
           otherwise-ASK command.
        3. The manager's own **deny** (e.g. dangerous-command guards) still wins
           over a permissive hook or rule - hard safety rules are not overridable.
        4. Manager **allow** passes through; otherwise (ASK) we honour a hook or
           rule allow, or fall back to the pause/prompt flow.
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

        # User exec-policy rules for shell commands.
        rule_allow = False
        rule_ask = False
        if name in ("bash", "shell_session"):
            command = str(arguments.get("command") or "")
            rule = self._exec_policy().evaluate(command) if command else None
            if rule is not None:
                if rule.action == "deny":
                    return ToolResult(
                        success=False,
                        output="",
                        error=(
                            "Command blocked by exec policy"
                            + (f": {rule.reason}" if rule.reason else f" (rule: {rule.pattern})")
                        ),
                        metadata={"permission": "exec_policy_deny", "tool": name},
                    )
                rule_allow = rule.action == "allow"
                rule_ask = rule.action == "ask"

        permission = self.permission_manager.check_permission(name, arguments)
        if permission == Permission.DENY:
            return ToolResult(
                success=False,
                output="",
                error=f"Permission denied for tool: {name}",
                metadata={"permission": "deny", "tool": name},
            )
        if permission == Permission.ALLOW and not rule_ask:
            return None
        if tool_call_id and tool_call_id in self._approved_tool_call_ids:
            return None
        if (verdict.allowed or rule_allow) and not rule_ask:
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
            result = self._bound_tool_result(name, result)
            await self.hooks.fire(AFTER_TOOL_CALL, lifecycle_ctx, name, arguments, result)
            return result

        if self.config.plan_mode:
            return await _finalize(
                ToolResult(
                    success=False,
                    output="",
                    error=f"Plan mode blocked tool execution: {name}",
                    metadata={"permission": "plan_mode_denied", "tool": name},
                )
            )

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

    def _compaction_active(self) -> bool:
        """Auto-compaction is on by default; SUPERQODE_AUTO_COMPACT=0 opts out.

        The legacy ``enable_summarization`` flag, if explicitly set, also turns it
        on, but it no longer needs to be set for compaction to run.
        """
        env = os.environ.get("SUPERQODE_AUTO_COMPACT", "").strip().lower()
        if env in ("0", "false", "no", "off"):
            return False
        if env in ("1", "true", "yes", "on"):
            return True
        return True

    # Provider names that denote a self-hosted local server. For these we never
    # trust the static model catalog's window (that's the model-card maximum,
    # not the loaded one) - we probe the live server instead.
    _LOCAL_PROVIDERS = frozenset(
        {
            "ollama",
            "lmstudio",
            "lm-studio",
            "lm_studio",
            "vllm",
            "sglang",
            "mlx",
            "tgi",
            "llamacpp",
            "llama.cpp",
            "ds4",
            "dwarfstar",
            "local",
            "openai_compatible",
        }
    )

    def _provider_is_local(self) -> bool:
        p = (self.config.provider or "").lower()
        return any(token in p for token in self._LOCAL_PROVIDERS)

    async def _ensure_context_window(self) -> int:
        """Resolve and cache the real context window once per session.

        For local providers this probes the live server for the *loaded* window
        (Ollama num_ctx, llama.cpp n_ctx, vLLM max_model_len, etc.). An explicit
        ``config.context_window`` always wins. Safe + best-effort.
        """
        if getattr(self, "_cached_context_window", 0):
            return self._cached_context_window
        if self.config.context_window and self.config.context_window > 0:
            self._cached_context_window = int(self.config.context_window)
            self._context_window_source = "configured"
            return self._cached_context_window
        if self._provider_is_local():
            try:
                from superqode.providers.local.context_probe import (
                    resolve_local_context_window,
                )

                probed = await resolve_local_context_window(self.config.provider, self.config.model)
                if probed:
                    window, endpoint = probed
                    self._cached_context_window = window
                    self._context_window_source = f"loaded ({endpoint})"
                    return window
            except Exception:
                pass
            # Unknown local window: stay conservative rather than risk overflow.
            self._cached_context_window = max(self.config.max_context_tokens, 8192)
            self._context_window_source = "local-fallback"
            return self._cached_context_window
        # Cloud/BYOK: the static catalog window is reliable.
        self._cached_context_window = self._effective_context_window()
        self._context_window_source = "model-info"
        return self._cached_context_window

    def _effective_context_window(self) -> int:
        """Best-guess context window (sync). Prefers the cached/probed value."""
        cached = getattr(self, "_cached_context_window", 0)
        if cached:
            return cached
        if self.config.context_window and self.config.context_window > 0:
            return int(self.config.context_window)
        # Local windows can't be trusted from the static catalog (model-card max);
        # stay conservative until the async probe fills the cache.
        if self._provider_is_local():
            return max(self.config.max_context_tokens, 8192)
        try:
            from superqode.providers.models import get_model_info

            info = get_model_info(self.config.provider, self.config.model)
            if info and getattr(info, "context_window", 0):
                return int(info.context_window)
        except Exception:
            pass
        return max(self.config.max_context_tokens, 8192)

    def _compaction_budgets(self) -> tuple[int, int, int]:
        """Return (trigger_threshold, keep_recent_tokens, window) for this model.

        Threshold = window - reserve (room for the response). Keep-recent is a
        token budget so we keep *meaningful* recent context regardless of how
        many messages that is. Both auto-scale to the model's window. The reserve
        floor (1024) and 20% fraction protect small local windows, where the
        system prompt + tool schemas alone can eat a couple thousand tokens.
        """
        window = self._effective_context_window()
        reserve = self.config.compaction_reserve_tokens or max(1024, min(16384, int(window * 0.20)))
        keep_recent = self.config.keep_recent_tokens or max(1024, min(24576, int(window * 0.40)))
        # Never let the kept tail + reserve swallow the whole window.
        if keep_recent + reserve >= window:
            keep_recent = max(512, int(window * 0.5) - reserve)
        threshold = max(1024, window - reserve)
        return threshold, keep_recent, window

    def _token_budgeted_split(
        self, messages: List["AgentMessage"], msg_dicts: List[Dict], keep_recent: int
    ) -> int:
        """Index splitting head (to compact) from the recent tail (to keep).

        Walks backward from the newest message, accumulating token estimates
        until ``keep_recent`` is reached. Returns the head/tail boundary index.
        """
        accumulated = 0
        boundary = len(messages)
        for idx in range(len(messages) - 1, -1, -1):
            try:
                accumulated += self.context_manager.count_tokens([msg_dicts[idx]])
            except Exception:
                accumulated += max(1, len(_content_for_counting(messages[idx].content)) // 4)
            boundary = idx
            if accumulated >= keep_recent:
                break
        return boundary

    # Tool outputs smaller than this aren't worth stubbing.
    _PRUNE_MIN_CHARS = 240
    # Skip the prune pass entirely when it would save less than this.
    _PRUNE_MIN_TOTAL_SAVINGS = 2000

    def _prune_stale_tool_outputs(
        self, messages: List["AgentMessage"], msg_dicts: List[Dict], keep_recent: int
    ) -> Tuple[List["AgentMessage"], int]:
        """Replace old tool outputs with short stubs, keeping the recent tail.

        Walks backwards accumulating token estimates; once the accumulated
        total exceeds ``keep_recent``, older tool outputs become prunable
        (the protected window is a token budget, and a single huge stale
        output that crosses it is exactly what should go). The current turn's tool results - anything after the last
        assistant message - are always protected regardless of size, since
        the model is about to reason over them.

        Returns ``(new_messages, saved_chars)``; ``saved_chars`` is 0 when
        nothing was pruned (savings below the floor). Original message objects
        are never mutated - pruned entries are fresh copies - so persisted
        session history is unaffected.
        """
        last_assistant = max(
            (i for i, m in enumerate(messages) if m.role == "assistant"),
            default=len(messages),
        )
        replacements: List[Tuple[int, str]] = []
        saved = 0
        accumulated = 0
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            try:
                accumulated += self.context_manager.count_tokens([msg_dicts[idx]])
            except Exception:
                accumulated += max(1, len(_content_for_counting(msg.content)) // 4)
            if accumulated <= keep_recent:
                continue  # inside the protected recent budget
            if idx >= last_assistant:
                continue  # current turn's results: always protected
            if msg.role == "user" and isinstance(msg.content, list):
                # Stale image attachment: the data URL dominates a local
                # model's window. Keep the textual note, drop the pixels.
                saved += 4000  # matches the flat per-image counting charge
                replacements.append(
                    (
                        idx,
                        "[Old image attachment removed to save context. Re-run view_image if needed.]",
                    )
                )
                continue
            if msg.role != "tool":
                continue
            content = msg.content or ""
            if len(content) <= self._PRUNE_MIN_CHARS:
                continue
            stub = (
                f"[Old output of '{msg.name or 'tool'}' removed to save context "
                f"({len(content):,} chars). Re-run the tool if you need it again.]"
            )
            if len(stub) >= len(content):
                continue
            saved += len(content) - len(stub)
            replacements.append((idx, stub))
        if saved < self._PRUNE_MIN_TOTAL_SAVINGS:
            return messages, 0
        new_messages = list(messages)
        for idx, stub in replacements:
            old = messages[idx]
            new_messages[idx] = AgentMessage(
                role=old.role,
                content=stub,
                tool_calls=old.tool_calls,
                tool_call_id=old.tool_call_id,
                name=old.name,
            )
        return new_messages, saved

    async def _maybe_summarize(self, messages: List["AgentMessage"]) -> List["AgentMessage"]:
        """Compact or prune messages when context approaches the model's window.

        Strategy:
        1. Derive an adaptive threshold (window - reserve) and kept-recent token
           budget from the model's real context window; bail if under threshold.
        2. Try LLM-backed structured compaction (9-section template). Replace the
           head of history with the summary; keep the system prompt and a
           token-budgeted tail of recent turns intact.
        3. If compaction fails, fall back to mechanical prune-from-front.
        """
        if not self._compaction_active():
            return messages

        msg_dicts = [
            {
                "role": m.role,
                "content": _content_for_counting(m.content),
                "tool_calls": m.tool_calls,
                "tool_result": m.content if m.role == "tool" else None,
            }
            for m in messages
        ]
        token_count = self.context_manager.count_tokens(msg_dicts)
        threshold, keep_recent, window = self._compaction_budgets()
        if token_count <= threshold:
            return messages

        # before_compact handler hooks may skip this round (DENY) - e.g. to defer
        # compaction until a logical boundary - while observers can record it.
        from .hooks import AFTER_COMPACT, BEFORE_COMPACT

        lifecycle_ctx = self._lifecycle_context()
        pre = await self.hooks.fire_decision(
            BEFORE_COMPACT,
            lifecycle_ctx,
            token_count,
            threshold,
        )
        if pre.denied:
            return messages

        # Stage 1 (free): stub out stale tool outputs older than the protected
        # recent tail. The conversation skeleton (who did what, in what order)
        # survives; only old tool payloads are dropped. No LLM call needed, and
        # when this alone gets us back under threshold we skip summarization -
        # the cheaper outcome for local models.
        pruned_messages, pruned_chars = self._prune_stale_tool_outputs(
            messages, msg_dicts, keep_recent
        )
        if pruned_chars > 0:
            messages = pruned_messages
            msg_dicts = [
                {
                    "role": m.role,
                    "content": _content_for_counting(m.content),
                    "tool_calls": m.tool_calls,
                    "tool_result": m.content if m.role == "tool" else None,
                }
                for m in messages
            ]
            token_count = self.context_manager.count_tokens(msg_dicts)
            if token_count <= threshold:
                if self.on_thinking:
                    await self.on_thinking(
                        f"Context pruned: removed {pruned_chars:,} chars of stale tool "
                        f"output ({token_count}/{window} tokens now). No summary needed."
                    )
                await self.hooks.fire(
                    AFTER_COMPACT,
                    lifecycle_ctx,
                    token_count,
                    messages,
                    "tool_prune",
                )
                return messages

        if self.on_thinking:
            await self.on_thinking(
                f"Context management active ({token_count}/{window} tokens). "
                "Compacting earlier turns..."
            )

        from .compaction import compact_history

        # Keep the system prompt, plus a token-budgeted tail of recent turns, and
        # compact everything before that. The tail is sized to the model's window
        # (keep_recent), not a fixed message count, so small local models keep a
        # sensible amount of live context.
        system_prefix = [m for m in messages if m.role == "system"][:1]
        body = (
            [m for m in messages if m.role != "system" or m is not system_prefix[0]]
            if system_prefix
            else list(messages)
        )
        body_dicts = [
            {
                "role": m.role,
                "content": _content_for_counting(m.content),
                "tool_calls": m.tool_calls,
                "tool_result": m.content if m.role == "tool" else None,
            }
            for m in body
        ]
        split = self._token_budgeted_split(body, body_dicts, keep_recent)
        # Always compact at least something and keep at least one recent message.
        split = max(1, min(split, len(body) - 1)) if len(body) > 1 else len(body)

        strategy = "prune"
        result_messages: List["AgentMessage"]
        if len(body) > 1 and split >= 1:
            # Image parts must not reach the summarizer as raw data URLs.
            head = [self._strip_image_parts(m) for m in body[:split]]
            tail = body[split:]
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

    def _bound_tool_result(self, name: str, result: ToolResult) -> ToolResult:
        """Last-resort output bound for tools that don't self-limit.

        Bash and read_file already size themselves to the model; this guard
        catches everything else (MCP tools, web fetchers, plugins) so a single
        oversized result can never blow out a local model's context. The full
        output is spilled to disk and the model gets a preview plus the path.
        The cap carries some slack so self-limited tools that add a short
        notice after their own truncation aren't truncated twice.
        """
        output = result.output or ""
        cap = self._tool_output_byte_cap or 100_000
        limit = int(cap * 1.25) + 512
        if len(output) <= limit:  # cheap pre-check; chars <= bytes
            return result
        from ..tools.output_spill import truncate_with_spill

        bounded, truncated, spill_path = truncate_with_spill(
            output,
            max_bytes=limit,
            label=f"{name} output",
            prefix=(name or "tool")[:24],
            direction="head_tail",
        )
        if not truncated:
            return result
        metadata = dict(result.metadata or {})
        metadata["loop_truncated"] = True
        if spill_path is not None:
            metadata["spilled_to"] = str(spill_path)
        return ToolResult(
            success=result.success,
            output=bounded,
            error=result.error,
            metadata=metadata,
        )

    def _prepare_tool_call(self, tc: Dict) -> Tuple[str, str, Dict[str, Any], Optional[str]]:
        """Extract (name, call_id, args, parse_error) from a raw tool call.

        Arguments go through lenient repair (code fences, Python-dict syntax,
        trailing commas, double-encoded JSON - the usual local-model shapes).
        When they are still unparseable, ``parse_error`` is set and the call
        must NOT be executed - the error is returned to the model instead of
        silently running the tool with empty arguments.
        """
        from .tool_args import parse_tool_arguments

        function = tc.get("function", {}) or {}
        tool_name = function.get("name", "") or tc.get("name", "")
        raw_args = function.get("arguments", "{}")
        tool_call_id = tc.get("id", str(uuid.uuid4()))
        tool_args, parse_error = parse_tool_arguments(raw_args)
        return tool_name, tool_call_id, tool_args, parse_error

    def _tool_is_read_only(self, name: str) -> bool:
        tool = self.tools.get(name)
        return bool(tool is not None and getattr(tool, "read_only", False))

    @staticmethod
    def _strip_image_parts(msg: "AgentMessage") -> "AgentMessage":
        """Return a text-only copy of a multimodal message (for summarization)."""
        if not isinstance(msg.content, list):
            return msg
        texts = [
            str(part.get("text", ""))
            for part in msg.content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        texts.append("[image attachment omitted]")
        return AgentMessage(
            role=msg.role,
            content="\n".join(t for t in texts if t),
            tool_calls=msg.tool_calls,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        )

    @staticmethod
    def _image_followup_message(result: ToolResult) -> Optional["AgentMessage"]:
        """Build the multimodal user message carrying a view_image attachment.

        Tool-role messages cannot carry image parts on most providers, so the
        image is delivered as a user message immediately after the tool
        result (codex does the same). Not persisted to session storage -
        data URLs are large and reproducible from the file path.
        """
        data_url = (result.metadata or {}).get("image_data_url")
        if not data_url or not result.success:
            return None
        path = (result.metadata or {}).get("image_path", "image")
        return AgentMessage(
            role="user",
            content=[
                {"type": "text", "text": f"[Attached image: {path}]"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        )

    async def _execute_tool_batch(
        self,
        tool_calls: List[Dict],
    ) -> List[Tuple[str, str, Dict, ToolResult]]:
        """Parse, guard, and execute one assistant turn's tool calls.

        Returns (tool_name, tool_call_id, tool_args, result) tuples in call
        order. Three guards run before any execution:

        - unparseable arguments are answered with corrective feedback instead
          of executing the tool with ``{}``;
        - the doom-loop detector blocks the Nth consecutive identical call and
          raises :class:`DoomLoopAbort` if the model repeats it anyway;
        - the batch only runs concurrently when *every* runnable call is
          read-only - any batch containing a mutating call (edit, write,
          bash, MCP, unknown) runs sequentially in call order so concurrent
          mutations can never race.
        """
        from .loop_guard import DoomLoopAbort
        from .tool_args import invalid_arguments_message

        n = len(tool_calls)
        prepared: List[Tuple[str, str, Dict[str, Any]]] = []
        results: Dict[int, Tuple[str, str, Dict, ToolResult]] = {}

        for i, tc in enumerate(tool_calls):
            tool_name, tool_call_id, tool_args, parse_error = self._prepare_tool_call(tc)
            prepared.append((tool_name, tool_call_id, tool_args))
            if parse_error is not None:
                result = ToolResult(
                    success=False,
                    output="",
                    error=invalid_arguments_message(tool_name or "unknown", parse_error),
                    metadata={"invalid_arguments": True, "tool": tool_name},
                )
                if self.on_tool_call:
                    self.on_tool_call(tool_name, {})
                if self.on_tool_result:
                    self.on_tool_result(tool_name, result)
                results[i] = (tool_name, tool_call_id, {}, result)
                continue

            guard = self._doom_guard
            if guard is not None and guard.threshold > 0:
                if guard.should_abort(tool_name, tool_args):
                    raise DoomLoopAbort(guard.abort_message(tool_name))
                if guard.observe(tool_name, tool_args):
                    result = ToolResult(
                        success=False,
                        output="",
                        error=guard.guidance(tool_name),
                        metadata={"doom_loop": True, "tool": tool_name},
                    )
                    if self.on_thinking:
                        await self.on_thinking(
                            f"Loop guard: blocked repeated identical call to '{tool_name}'."
                        )
                    if self.on_tool_call:
                        self.on_tool_call(tool_name, tool_args)
                    if self.on_tool_result:
                        self.on_tool_result(tool_name, result)
                    results[i] = (tool_name, tool_call_id, tool_args, result)

        runnable = [i for i in range(n) if i not in results]

        async def dispatch(i: int) -> None:
            tool_name, tool_call_id, tool_args = prepared[i]
            if self.on_tool_call:
                self.on_tool_call(tool_name, tool_args)
            result = await self._execute_tool(tool_name, tool_args, tool_call_id=tool_call_id)
            if self.on_tool_result:
                self.on_tool_result(tool_name, result)
            results[i] = (tool_name, tool_call_id, tool_args, result)

        run_parallel = (
            self.parallel_tools
            and len(runnable) > 1
            and all(self._tool_is_read_only(prepared[i][0]) for i in runnable)
        )
        if run_parallel:
            outcomes = await asyncio.gather(
                *(dispatch(i) for i in runnable), return_exceptions=True
            )
            for i, outcome in zip(runnable, outcomes):
                if isinstance(outcome, ToolApprovalRequired) or isinstance(outcome, DoomLoopAbort):
                    raise outcome
                if isinstance(outcome, BaseException):
                    tool_name, tool_call_id, tool_args = prepared[i]
                    results[i] = (
                        tool_name,
                        tool_call_id,
                        tool_args,
                        ToolResult(success=False, output="", error=str(outcome)),
                    )
        else:
            for i in runnable:
                await dispatch(i)

        return [results[i] for i in range(n)]

    async def _execute_tools_parallel(
        self,
        tool_calls: List[Dict],
    ) -> List[Tuple[str, str, Dict, ToolResult]]:
        """Back-compat alias for :meth:`_execute_tool_batch`."""
        return await self._execute_tool_batch(tool_calls)

    async def run(self, user_message: str) -> AgentResponse:
        """Run the agent loop until completion.

        Args:
            user_message: The user's request

        Returns:
            AgentResponse with the final result

        Performance: Uses cached message conversion and parallel tool execution.
        """
        # Resolve the real (loaded, for local) context window once so adaptive
        # compaction is sized correctly from the first turn.
        await self._ensure_context_window()
        self._arm_doom_guard()

        from .hooks import SESSION_START, STOP, USER_PROMPT_SUBMIT

        lifecycle_ctx = self._lifecycle_context()

        async def _finish(response: AgentResponse) -> AgentResponse:
            self.run_active = False
            await self.hooks.fire(STOP, self._lifecycle_context(), response)
            # Opt-in automatic memory extraction, off the hot path.
            try:
                from .auto_memory import auto_memory_enabled, extract_session_memories

                if auto_memory_enabled() and response.stopped_reason == "complete":
                    self._auto_memory_task = asyncio.create_task(
                        extract_session_memories(
                            list(response.messages),
                            self.gateway,
                            self.config.provider,
                            self.config.model,
                            self.config.working_directory,
                        )
                    )
            except Exception:
                pass
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
            messages.append(AgentMessage(role="system", content=self._system_prompt_for_run()))

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
        auto_continues = 0
        length_parts: List[str] = []
        rubric_rounds = 0

        # Emit initial processing log
        if self.on_thinking:
            await self.on_thinking("Processing request...")

        self.run_active = True

        # Always send tools if available - let malformed tool call handling deal with issues
        # This ensures models always get the full context and we handle malformed responses gracefully
        # max_iterations <= 0 means unlimited (loop until the model stops)
        _cap = self.config.max_iterations
        while _cap <= 0 or iterations < _cap:
            if self._cancelled:
                return await _finish(
                    AgentResponse(
                        content="",
                        messages=messages,
                        tool_calls_made=tool_calls_made,
                        iterations=iterations,
                        stopped_reason="cancelled",
                    )
                )

            iterations += 1
            self._current_iteration = iterations
            turn_tool_results: List[ToolResult] = []

            # Inject any steering messages queued while the agent was working.
            drained = self._drain_steering(messages)
            if drained and self.on_thinking:
                await self.on_thinking(
                    f"Steering: picked up {len(drained)} queued user message(s)."
                )

            # Tool definitions are per-iteration: tool_search may have
            # activated deferred tools since the last call.
            tool_defs = self._get_tool_definitions()

            # Emit iteration log
            if self.on_thinking:
                await self.on_thinking(
                    f"Calling model {self.config.provider}/{self.config.model}... (iteration {iterations})"
                )

            # PERFORMANCE: Use cached message conversion. Reminders ride along
            # on the request only - they are not part of stored history.
            gateway_messages = self._convert_messages(
                messages + self._collect_reminder_messages(iterations, user_message)
            )

            # Plan mode: disable tools so model only analyzes/plans without executing
            tools_to_send = None
            if not self.config.plan_mode and not self._prompt_tool_mode():
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

            # Prompt-tool mode: lift <tool_call> blocks out of the text into
            # standard tool calls (no-op when native calls are present).
            response_content, response.tool_calls = self._extract_prompt_tool_calls(
                response_content, response.tool_calls
            )

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

                # Execute the turn's tool calls. The batch executor handles
                # argument repair, doom-loop guarding, and only parallelizes
                # when every call is read-only (mutations run in call order).
                from .loop_guard import DoomLoopAbort

                try:
                    results = await self._execute_tool_batch(response.tool_calls)
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
                except DoomLoopAbort as abort:
                    if self.on_thinking:
                        await self.on_thinking(
                            "Loop guard: aborting run (model kept repeating the same call)."
                        )
                    return await _finish(
                        AgentResponse(
                            content=str(abort),
                            messages=messages,
                            tool_calls_made=tool_calls_made,
                            iterations=iterations,
                            stopped_reason="loop_detected",
                            error=str(abort),
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
                    image_msg = self._image_followup_message(result)
                    if image_msg is not None:
                        messages.append(image_msg)

                # Per-turn aggregate diff: one summary line per turn, full
                # diff retained for consumers.
                from ..tools.diff_utils import summarize_turn_changes

                turn_summary, turn_diff = summarize_turn_changes(turn_tool_results)
                self.last_turn_diff = turn_diff
                if turn_summary and self.on_thinking:
                    await self.on_thinking(turn_summary)

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

                # Adaptive context compaction (on by default; the helper checks
                # the model window and decides whether to act).
                messages = await self._maybe_summarize(messages)

            else:
                # No tool calls. If the output was cut at the max-token limit,
                # ask the model to continue from where it stopped (bounded).
                if response.finish_reason == "length" and auto_continues < max(
                    0, self.config.max_auto_continues
                ):
                    auto_continues += 1
                    length_parts.append(response_content)
                    messages.append(AgentMessage(role="assistant", content=response_content))
                    messages.append(
                        AgentMessage(
                            role="user",
                            content=(
                                "Your previous message was cut off at the output-token "
                                "limit. Continue from exactly where it stopped. Do not "
                                "repeat any text you already produced."
                            ),
                        )
                    )
                    if self.on_thinking:
                        await self.on_thinking(
                            f"Output hit the token limit; auto-continuing ({auto_continues}/{self.config.max_auto_continues})..."
                        )
                    continue

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
                # User steered while the model was finishing: keep the turn
                # going with the queued message(s) instead of returning.
                if self.steering_pending():
                    messages.append(AgentMessage(role="assistant", content=response_content))
                    if self._session_manager and response_content.strip():
                        self._session_manager.add_assistant_message(response_content)
                    continue

                # Rubric self-grading: a separate grader judges the final
                # answer; needs_revision feedback re-enters the loop.
                if self.config.rubric and rubric_rounds < max(0, self.config.max_rubric_rounds):
                    from .rubric import grade_against_rubric

                    verdict, feedback = await grade_against_rubric(
                        messages,
                        response_content,
                        self.config.rubric,
                        self.gateway,
                        self.config.provider,
                        self.config.model,
                    )
                    if verdict == "needs_revision" and feedback:
                        rubric_rounds += 1
                        if self.on_thinking:
                            await self.on_thinking(
                                f"Rubric review: needs revision (round {rubric_rounds}/{self.config.max_rubric_rounds}) - {feedback[:120]}"
                            )
                        messages.append(AgentMessage(role="assistant", content=response_content))
                        messages.append(
                            AgentMessage(
                                role="user",
                                content=(
                                    "[rubric review] Your work does not yet satisfy the "
                                    f"rubric. Reviewer feedback:\n{feedback}\n"
                                    "Revise your work to address this, then give your final answer."
                                ),
                            )
                        )
                        continue
                    if verdict == "failed" and self.on_thinking:
                        await self.on_thinking(f"Rubric review: failed - {feedback[:120]}")

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
                    content=(
                        "".join(length_parts + [response_content])
                        if length_parts
                        else response_content
                    ),
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
        # Resolve the real (loaded, for local) context window once so adaptive
        # compaction in this streaming run is sized correctly.
        await self._ensure_context_window()
        self._arm_doom_guard()

        messages: List[AgentMessage] = []

        if self.system_prompt:
            messages.append(AgentMessage(role="system", content=self._system_prompt_for_run()))

        messages.extend(self._load_stored_messages())

        messages.append(AgentMessage(role="user", content=user_message))
        if self._session_manager:
            self._session_manager.add_user_message(user_message)

        iterations = 0
        tool_calls_made = 0
        auto_continues = 0

        # Emit initial processing log
        if self.on_thinking:
            await self.on_thinking("Processing request...")

        self.run_active = True

        try:
            async for chunk in self._run_streaming_loop(
                messages, user_message, iterations, tool_calls_made, auto_continues
            ):
                yield chunk
        finally:
            self.run_active = False

    async def _run_streaming_loop(
        self,
        messages: List["AgentMessage"],
        user_message: str,
        iterations: int,
        tool_calls_made: int,
        auto_continues: int,
    ) -> AsyncIterator[str]:
        _cap = self.config.max_iterations
        while _cap <= 0 or iterations < _cap:
            # Check for cancellation
            if self._cancelled:
                if self.on_thinking:
                    await self.on_thinking("Operation cancelled by user")
                return

            iterations += 1

            # Inject any steering messages queued while the agent was working.
            drained = self._drain_steering(messages)
            if drained and self.on_thinking:
                await self.on_thinking(
                    f"Steering: picked up {len(drained)} queued user message(s)."
                )

            # Tool definitions are per-iteration: tool_search may have
            # activated deferred tools since the last call.
            tool_defs = self._get_tool_definitions()

            # Emit iteration log
            if self.on_thinking:
                await self.on_thinking(
                    f"Calling model {self.config.provider}/{self.config.model}... (iteration {iterations})"
                )

            # PERFORMANCE: Use cached message conversion. Reminders ride along
            # on the request only - they are not part of stored history.
            gateway_messages = self._convert_messages(
                messages + self._collect_reminder_messages(iterations, user_message)
            )

            tools_to_send = None
            if not self.config.plan_mode and not self._prompt_tool_mode():
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
            stream_finish_reason: Optional[str] = None

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

                    if chunk.finish_reason:
                        stream_finish_reason = chunk.finish_reason

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

            # Prompt-tool mode: lift <tool_call> blocks out of the streamed
            # text into standard tool calls (no-op when native calls arrived).
            full_content, extracted_calls = self._extract_prompt_tool_calls(
                full_content, tool_calls or None
            )
            tool_calls = extracted_calls or []

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

                # Execute the turn's tool calls. The batch executor handles
                # argument repair, doom-loop guarding, and only parallelizes
                # when every call is read-only (mutations run in call order).
                from .loop_guard import DoomLoopAbort

                try:
                    results = await self._execute_tool_batch(tool_calls)
                except ToolApprovalRequired:
                    return
                except DoomLoopAbort as abort:
                    if self.on_thinking:
                        await self.on_thinking(
                            "Loop guard: aborting run (model kept repeating the same call)."
                        )
                    yield f"\n\n[{abort}]"
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
                    image_msg = self._image_followup_message(result)
                    if image_msg is not None:
                        messages.append(image_msg)

                # Per-turn aggregate diff.
                from ..tools.diff_utils import summarize_turn_changes

                turn_summary, turn_diff = summarize_turn_changes([r[3] for r in results])
                self.last_turn_diff = turn_diff
                if turn_summary and self.on_thinking:
                    await self.on_thinking(turn_summary)

                # Emit iteration complete log
                if self.on_thinking:
                    await self.on_thinking(f"Iteration {iterations} complete")

                # Adaptive context compaction. The streaming loop (used by local
                # and BYOK models) previously NEVER compacted, so long sessions
                # overflowed the window. Compact here at the turn boundary so the
                # next iteration starts within budget.
                messages = await self._maybe_summarize(messages)

                # Continue loop to get final response after tool execution
                # The next iteration will stream the final response with tool results
                # Important: The model should provide a summary after seeing tool results
            else:
                # No tool calls. If the output was cut at the max-token limit,
                # ask the model to continue from where it stopped; the
                # continuation streams seamlessly after the partial text.
                if stream_finish_reason == "length" and auto_continues < max(
                    0, self.config.max_auto_continues
                ):
                    auto_continues += 1
                    messages.append(AgentMessage(role="assistant", content=full_content))
                    messages.append(
                        AgentMessage(
                            role="user",
                            content=(
                                "Your previous message was cut off at the output-token "
                                "limit. Continue from exactly where it stopped. Do not "
                                "repeat any text you already produced."
                            ),
                        )
                    )
                    if self.on_thinking:
                        await self.on_thinking(
                            f"Output hit the token limit; auto-continuing ({auto_continues}/{self.config.max_auto_continues})..."
                        )
                    continue

                # User steered while the model was finishing: keep going with
                # the queued message(s) instead of ending the run.
                if self.steering_pending():
                    messages.append(AgentMessage(role="assistant", content=full_content))
                    if self._session_manager and full_content.strip():
                        self._session_manager.add_assistant_message(full_content)
                    continue

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
