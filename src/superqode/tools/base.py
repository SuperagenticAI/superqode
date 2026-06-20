"""
Base Tool System - Minimal, Standard Interface.

Design:
- OpenAI-compatible tool format (works with any provider via LiteLLM)
- No opinionated prompts - just tool name, description, parameters
- Transparent execution - what you call is what runs

Performance features:
- Streaming output support for long-running tools
- Progress callbacks for UI updates
- Async-first design for non-blocking execution
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Dict, List, Optional, Callable, Union
from pathlib import Path
import json


# Type aliases for callbacks
OutputCallback = Callable[[str], Union[None, Awaitable[None]]]
ProgressCallback = Callable[[float, str], Union[None, Awaitable[None]]]


@dataclass
class ToolContext:
    """Context passed to tool execution.

    Minimal context - just what's needed for execution.
    No hidden state, no magic.

    Streaming support:
        on_output: Called with output chunks as they're produced
        on_progress: Called with (progress_fraction, status_message)

    tool_registry: Set by the agent loop so tools like BatchTool can execute other tools.
    """

    session_id: str
    working_directory: Path
    # Optional: extra read-only roots that search/read tools may access (e.g. a
    # downloaded repo outside the project). None => fall back to the
    # SUPERQODE_SEARCH_ROOTS env var. Writers ignore this and stay in the cwd.
    search_roots: Optional[List[Path]] = None
    # Optional: for permission checks (user can enable/disable)
    require_confirmation: bool = False
    # Callback for streaming output (optional) - can be sync or async
    on_output: Optional[OutputCallback] = None
    # Callback for progress updates (0.0 to 1.0, plus status message)
    on_progress: Optional[ProgressCallback] = None
    # Optional: registry for BatchTool to resolve and run other tools
    tool_registry: Optional["ToolRegistry"] = None
    # Delegation depth for SubAgentTool (0=top, incremented for child sessions; max 3)
    delegation_depth: int = 0
    # Optional runner provided by AgentLoop for real child-agent execution.
    sub_agent_runner: Optional[Callable[[str, Dict[str, Any]], Awaitable[str]]] = None
    # Per-model byte cap for tool output (shell, web, etc.). When None, tools
    # use their built-in defaults. Populated by AgentLoop via
    # agent.terminal_output_limits.calculate_terminal_output_limit_for_model.
    max_output_bytes: Optional[int] = None
    # Peer-agent manager (spawn_agent/send_input/wait_agent/...). Set only for
    # the top-level loop; None inside sub-agents so peers cannot spawn peers.
    peer_manager: Optional[Any] = None
    # Permission manager, for tools that interact with the approval flow
    # (request_permissions). Set by the agent loop.
    permission_manager: Optional[Any] = None
    # Live context-budget reporter for get_context_remaining. Returns a dict
    # with window/used/compaction_threshold. Set by the agent loop.
    context_status: Optional[Callable[[], Dict[str, Any]]] = None
    # Harness run context, populated when tools execute inside HarnessKernel.
    harness_store: Optional[Any] = None
    harness_spec: Optional[Any] = None
    harness_run_id: str = ""
    harness_root_run_id: str = ""
    harness_runtime: str = ""
    harness_provider: str = ""
    harness_model: str = ""
    harness_sandbox_backend: str = "local"

    async def emit_output(self, text: str) -> None:
        """Emit output to the callback if set."""
        if self.on_output:
            result = self.on_output(text)
            if hasattr(result, "__await__"):
                await result

    async def emit_progress(self, fraction: float, status: str = "") -> None:
        """Emit progress update to the callback if set.

        Args:
            fraction: Progress from 0.0 to 1.0
            status: Optional status message
        """
        if self.on_progress:
            result = self.on_progress(fraction, status)
            if hasattr(result, "__await__"):
                await result


@dataclass
class ToolResult:
    """Result from tool execution.

    Simple, transparent result format.
    """

    success: bool
    output: str
    error: Optional[str] = None
    # Metadata for debugging/logging (not sent to model)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_message(self) -> str:
        """Convert to message content for the model."""
        if self.success:
            return self.output
        else:
            return f"Error: {self.error}\n{self.output}" if self.output else f"Error: {self.error}"


class Tool(ABC):
    """Base class for all tools.

    Minimal interface:
    - name: Tool identifier
    - description: What it does (sent to model)
    - parameters: JSON Schema (sent to model)
    - execute(): Run the tool

    NO:
    - Complex initialization
    - Hidden system prompts
    - Opinionated formatting
    """

    # True for tools that cannot mutate files, project state, or the
    # environment. The agent loop only parallelizes batches in which every
    # call is read-only; anything else runs sequentially in call order so
    # concurrent mutations can never race. Unknown tools default to False.
    read_only: bool = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name (e.g., 'read_file')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for the model. Keep it simple and factual."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON Schema for parameters."""
        pass

    @abstractmethod
    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute the tool with given arguments."""
        pass

    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling format.

        This is the standard format that works with:
        - OpenAI (GPT-4, GPT-5)
        - Anthropic (Claude)
        - Google (Gemini)
        - All LiteLLM-supported providers
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry of available tools.

    Simple dict-based registry. No magic, no auto-discovery.

    Deferred tools: ``defer()`` keeps a tool registered and executable but
    excludes its schema from what is advertised to the model until
    ``activate()`` is called (normally by the tool_search tool). ``version``
    increments on every visibility change so callers can cache derived
    schema lists cheaply.
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._deferred: set[str] = set()
        self.version: int = 0

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        self.version += 1

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list(self) -> List[Tool]:
        """List all registered tools (active and deferred)."""
        return list(self._tools.values())

    def defer(self, *names: str) -> int:
        """Hide the named tools' schemas until activated. Returns count hidden."""
        count = 0
        for name in names:
            if name in self._tools and name not in self._deferred:
                self._deferred.add(name)
                count += 1
        if count:
            self.version += 1
        return count

    def activate(self, name: str) -> bool:
        """Expose a deferred tool's schema to the model again."""
        if name in self._deferred:
            self._deferred.discard(name)
            self.version += 1
            return True
        return False

    def deferred_names(self) -> List[str]:
        return sorted(self._deferred)

    def deferred_tools(self) -> List[Tool]:
        return [self._tools[n] for n in sorted(self._deferred) if n in self._tools]

    def active_tools(self) -> List[Tool]:
        """Tools whose schemas are advertised to the model."""
        return [t for n, t in self._tools.items() if n not in self._deferred]

    def filtered(self, allowed_tools: List[str]) -> "ToolRegistry":
        """Create a registry containing only the named tools that exist."""
        registry = ToolRegistry()
        allowed = set(allowed_tools)
        for name, tool in self._tools.items():
            if name in allowed:
                registry.register(tool)
                if name in self._deferred:
                    registry.defer(name)
        return registry

    def to_openai_format(self) -> List[Dict[str, Any]]:
        """Get active (non-deferred) tools in OpenAI format."""
        return [tool.to_openai_format() for tool in self.active_tools()]

    @classmethod
    def empty(cls) -> "ToolRegistry":
        """Create an empty registry for no-tool harness runs."""
        return cls()

    @classmethod
    def default(cls) -> "ToolRegistry":
        """Create registry with default minimal tools."""
        from .file_tools import ReadFileTool, WriteFileTool, CreateFileTool, ListDirectoryTool
        from .edit_tools import EditFileTool, InsertTextTool
        from .shell_tools import BashTool
        from .search_tools import GrepTool, GlobTool, RepoSearchTool

        registry = cls()

        # Core file operations
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(CreateFileTool())
        registry.register(ListDirectoryTool())

        # Editing
        registry.register(EditFileTool())
        registry.register(InsertTextTool())

        # Shell
        registry.register(BashTool())

        # Search
        registry.register(GrepTool())
        registry.register(GlobTool())
        registry.register(RepoSearchTool())

        return registry

    @classmethod
    def coding(cls) -> "ToolRegistry":
        """Create a lean registry for normal interactive coding sessions.

        This keeps the model focused on local code work and avoids sending
        web, network, sub-agent, A2A, skill, and LSP tools on every turn.
        """
        from .file_tools import ReadFileTool, WriteFileTool, CreateFileTool, ListDirectoryTool
        from .edit_tools import EditFileTool, InsertTextTool, PatchTool, MultiEditTool
        from .apply_patch import ApplyPatchTool
        from .shell_tools import BashTool
        from .shell_session import ShellSessionTool
        from .image_tools import ViewImageTool
        from .search_tools import GrepTool, GlobTool, CodeSearchTool, RepoSearchTool
        from .question_tool import QuestionTool, ConfirmTool
        from .todo_tools import TodoWriteTool, TodoReadTool
        from .batch_tool import BatchTool
        from .compact_tool import CompactTool
        from .dynamic_workflow import DynamicWorkflowScriptTool, DynamicWorkflowTool
        from .monty_tool import MontyPythonReplTool, is_monty_available
        from .web_tools import WebSearchTool, WebFetchTool

        registry = cls()

        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(CreateFileTool())
        registry.register(ListDirectoryTool())

        registry.register(EditFileTool())
        registry.register(InsertTextTool())
        registry.register(PatchTool())
        registry.register(MultiEditTool())
        registry.register(ApplyPatchTool())

        registry.register(TodoWriteTool())
        registry.register(TodoReadTool())
        registry.register(BatchTool())

        registry.register(BashTool())
        registry.register(ShellSessionTool())
        registry.register(GrepTool())
        registry.register(GlobTool())
        registry.register(RepoSearchTool())
        registry.register(CodeSearchTool())

        # Semantic (embedding) search — only when the optional cocoindex-code
        # integration is installed; otherwise silently skipped.
        from .semantic_search import SemanticSearchTool, is_semantic_search_available

        if is_semantic_search_available():
            registry.register(SemanticSearchTool())

        if is_monty_available():
            registry.register(MontyPythonReplTool())

        registry.register(WebSearchTool())
        registry.register(WebFetchTool())
        registry.register(ViewImageTool())

        registry.register(QuestionTool())
        registry.register(ConfirmTool())
        registry.register(CompactTool())
        registry.register(DynamicWorkflowTool())
        registry.register(DynamicWorkflowScriptTool())

        # Context-budget visibility for the model
        from .context_tools import GetContextRemainingTool

        registry.register(GetContextRemainingTool())

        return registry

    @classmethod
    def ds4(cls) -> "ToolRegistry":
        """Create a compact registry tuned for DS4/local tool calling.

        DS4 benefits from a smaller schema surface. Keep the core coding loop
        intact while avoiding parallel/meta tools that tend to add latency or
        extra planning turns on local models.
        """
        from .file_tools import ReadFileTool, WriteFileTool, CreateFileTool, ListDirectoryTool
        from .edit_tools import EditFileTool, PatchTool
        from .apply_patch import ApplyPatchTool
        from .shell_tools import BashTool
        from .search_tools import GrepTool, GlobTool, RepoSearchTool, CodeSearchTool
        from .question_tool import QuestionTool, ConfirmTool
        from .todo_tools import TodoWriteTool, TodoReadTool

        registry = cls()

        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(CreateFileTool())
        registry.register(ListDirectoryTool())

        registry.register(EditFileTool())
        registry.register(PatchTool())
        registry.register(ApplyPatchTool())

        registry.register(TodoWriteTool())
        registry.register(TodoReadTool())

        registry.register(BashTool())
        registry.register(GrepTool())
        registry.register(GlobTool())
        registry.register(RepoSearchTool())
        # Semantic symbol/definition/reference search. Local models lean on
        # local search in place of web access, so give them the richer tool.
        registry.register(CodeSearchTool())

        # Semantic (embedding) search — only when the optional cocoindex-code
        # integration is installed; otherwise silently skipped.
        from .semantic_search import SemanticSearchTool, is_semantic_search_available

        if is_semantic_search_available():
            registry.register(SemanticSearchTool())

        registry.register(QuestionTool())
        registry.register(ConfirmTool())

        # Context-budget visibility for the model
        from .context_tools import GetContextRemainingTool

        registry.register(GetContextRemainingTool())

        return registry

    @classmethod
    def for_profile(cls, profile: str = "coding") -> "ToolRegistry":
        """Create a registry for a named tool profile."""
        normalized = (profile or "coding").strip().lower()
        if normalized in ("full", "all"):
            return cls.full()
        if normalized in ("standard", "safe"):
            return cls.standard()
        if normalized in ("ds4", "local-fast", "local_fast"):
            return cls.ds4()
        if normalized in ("none", "no-tool", "no_tool", "notool", "model-only", "model_only"):
            return cls.empty()
        if normalized in ("default", "minimal", "small"):
            return cls.default()
        return cls.coding()

    @classmethod
    def full(cls) -> "ToolRegistry":
        """Create registry with all available tools."""
        from .file_tools import ReadFileTool, WriteFileTool, CreateFileTool, ListDirectoryTool
        from .edit_tools import EditFileTool, InsertTextTool, PatchTool, MultiEditTool
        from .apply_patch import ApplyPatchTool
        from .shell_tools import BashTool
        from .shell_session import ShellSessionTool
        from .image_tools import ViewImageTool
        from .search_tools import GrepTool, GlobTool, CodeSearchTool, RepoSearchTool
        from .diagnostics import DiagnosticsTool
        from .network_tools import FetchTool, DownloadTool
        from .agent_tools import SubAgentTool, TaskCoordinatorTool
        from .dynamic_workflow import DynamicWorkflowScriptTool, DynamicWorkflowTool
        from .lsp_tools import LSPTool
        from .web_tools import WebSearchTool, WebFetchTool
        from .question_tool import QuestionTool, ConfirmTool
        from .todo_tools import TodoWriteTool, TodoReadTool
        from .batch_tool import BatchTool
        from .monty_tool import MontyPythonReplTool, is_monty_available

        registry = cls()

        # Core file operations
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(CreateFileTool())
        registry.register(ListDirectoryTool())

        # Editing (basic + advanced)
        registry.register(EditFileTool())
        registry.register(InsertTextTool())
        registry.register(PatchTool())
        registry.register(MultiEditTool())
        registry.register(ApplyPatchTool())

        # TODO management
        registry.register(TodoWriteTool())
        registry.register(TodoReadTool())

        # Batch (parallel tool execution)
        registry.register(BatchTool())

        # Shell
        registry.register(BashTool())
        registry.register(ShellSessionTool())

        # Search (basic + semantic)
        registry.register(GrepTool())
        registry.register(GlobTool())
        registry.register(RepoSearchTool())
        registry.register(CodeSearchTool())

        # Semantic (embedding) search — only when the optional cocoindex-code
        # integration is installed; otherwise silently skipped.
        from .semantic_search import SemanticSearchTool, is_semantic_search_available

        if is_semantic_search_available():
            registry.register(SemanticSearchTool())

        # Diagnostics
        registry.register(DiagnosticsTool())
        from .context_handle import ContextHandleTool

        registry.register(ContextHandleTool())

        # Sandboxed Python interpreter (optional pydantic-monty extra)
        if is_monty_available():
            registry.register(MontyPythonReplTool())

        # Network
        registry.register(FetchTool())
        registry.register(DownloadTool())

        # Web tools (search + enhanced fetch)
        registry.register(WebSearchTool())
        registry.register(WebFetchTool())

        # Visual inspection for vision-capable models
        registry.register(ViewImageTool())

        # Agent tools
        registry.register(SubAgentTool())
        registry.register(TaskCoordinatorTool())
        from .spawn_harness import SpawnHarnessTool

        registry.register(SpawnHarnessTool())
        registry.register(DynamicWorkflowTool())
        registry.register(DynamicWorkflowScriptTool())

        # Peer agents (long-lived, addressable child agents)
        from .peer_agent_tools import (
            CloseAgentTool,
            ListAgentsTool,
            SendInputTool,
            SpawnAgentTool,
            WaitAgentTool,
        )

        registry.register(SpawnAgentTool())
        registry.register(SendInputTool())
        registry.register(WaitAgentTool())
        registry.register(ListAgentsTool())
        registry.register(CloseAgentTool())
        from .harness_agent_session import AgentSessionTool

        registry.register(AgentSessionTool())

        # Permission escalation (model asks, user decides)
        from .request_permissions_tool import RequestPermissionsTool

        registry.register(RequestPermissionsTool())

        # LSP tools
        registry.register(LSPTool())

        # Interactive tools
        registry.register(QuestionTool())
        registry.register(ConfirmTool())

        # MCP tools (opt-in via SUPERQODE_MCP_SEARCH env var)
        import os

        if os.environ.get("SUPERQODE_MCP_SEARCH", "").lower() in ("1", "true", "yes"):
            from .mcp_tools import MCPSearchTool, MCPExecuteTool

            registry.register(MCPSearchTool())
            registry.register(MCPExecuteTool())

        # Skill tools (always available, loads from .agents/skills/)
        from .skill_tools import SkillTool, ReadSkillTool, CreateSkillTool

        registry.register(SkillTool())
        registry.register(ReadSkillTool())
        registry.register(CreateSkillTool())

        # Compact tool (manual context compression)
        from .compact_tool import CompactTool

        registry.register(CompactTool())

        # Context-budget visibility for the model
        from .context_tools import GetContextRemainingTool

        registry.register(GetContextRemainingTool())

        # A2A tools (call external A2A agents)
        try:
            from ..a2a.tools import A2ACallTool, A2ADiscoverTool

            registry.register(A2ACallTool())
            registry.register(A2ADiscoverTool())
        except ImportError:
            pass  # A2A extras not installed

        return registry

    @classmethod
    def standard(cls) -> "ToolRegistry":
        """Create registry with standard tools (no network/agent)."""
        from .file_tools import ReadFileTool, WriteFileTool, CreateFileTool, ListDirectoryTool
        from .edit_tools import EditFileTool, InsertTextTool, PatchTool, MultiEditTool
        from .apply_patch import ApplyPatchTool
        from .shell_tools import BashTool
        from .shell_session import ShellSessionTool
        from .image_tools import ViewImageTool
        from .search_tools import GrepTool, GlobTool, CodeSearchTool, RepoSearchTool
        from .diagnostics import DiagnosticsTool
        from .lsp_tools import LSPTool
        from .question_tool import QuestionTool, ConfirmTool
        from .todo_tools import TodoWriteTool, TodoReadTool
        from .batch_tool import BatchTool
        from .monty_tool import MontyPythonReplTool, is_monty_available

        registry = cls()

        # Core file operations
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(CreateFileTool())
        registry.register(ListDirectoryTool())

        # Editing
        registry.register(EditFileTool())
        registry.register(InsertTextTool())
        registry.register(PatchTool())
        registry.register(MultiEditTool())
        registry.register(ApplyPatchTool())

        # TODO management
        registry.register(TodoWriteTool())
        registry.register(TodoReadTool())

        # Batch (parallel tool execution)
        registry.register(BatchTool())

        # Shell
        registry.register(BashTool())

        # Search
        registry.register(GrepTool())
        registry.register(GlobTool())
        registry.register(RepoSearchTool())
        registry.register(CodeSearchTool())

        # Semantic (embedding) search — only when the optional cocoindex-code
        # integration is installed; otherwise silently skipped.
        from .semantic_search import SemanticSearchTool, is_semantic_search_available

        if is_semantic_search_available():
            registry.register(SemanticSearchTool())

        # Diagnostics
        registry.register(DiagnosticsTool())

        # Sandboxed Python interpreter (optional pydantic-monty extra)
        if is_monty_available():
            registry.register(MontyPythonReplTool())

        # LSP tools
        registry.register(LSPTool())

        # Interactive tools
        registry.register(QuestionTool())
        registry.register(ConfirmTool())

        return registry
