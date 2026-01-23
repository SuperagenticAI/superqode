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
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list(self) -> List[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def to_openai_format(self) -> List[Dict[str, Any]]:
        """Get all tools in OpenAI format."""
        return [tool.to_openai_format() for tool in self._tools.values()]

    @classmethod
    def default(cls) -> "ToolRegistry":
        """Create registry with default minimal tools."""
        from .file_tools import ReadFileTool, WriteFileTool, ListDirectoryTool
        from .edit_tools import EditFileTool, InsertTextTool
        from .shell_tools import BashTool
        from .search_tools import GrepTool, GlobTool

        registry = cls()

        # Core file operations
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(ListDirectoryTool())

        # Editing
        registry.register(EditFileTool())
        registry.register(InsertTextTool())

        # Shell
        registry.register(BashTool())

        # Search
        registry.register(GrepTool())
        registry.register(GlobTool())

        return registry

    @classmethod
    def full(cls) -> "ToolRegistry":
        """Create registry with all available tools."""
        from .file_tools import ReadFileTool, WriteFileTool, ListDirectoryTool
        from .edit_tools import EditFileTool, InsertTextTool, PatchTool, MultiEditTool
        from .shell_tools import BashTool
        from .search_tools import GrepTool, GlobTool, CodeSearchTool
        from .diagnostics import DiagnosticsTool
        from .network_tools import FetchTool, DownloadTool
        from .agent_tools import SubAgentTool, TaskCoordinatorTool
        from .lsp_tools import LSPTool
        from .web_tools import WebSearchTool, WebFetchTool
        from .question_tool import QuestionTool, ConfirmTool
        from .todo_tools import TodoWriteTool, TodoReadTool
        from .batch_tool import BatchTool

        registry = cls()

        # Core file operations
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(ListDirectoryTool())

        # Editing (basic + advanced)
        registry.register(EditFileTool())
        registry.register(InsertTextTool())
        registry.register(PatchTool())
        registry.register(MultiEditTool())

        # TODO management
        registry.register(TodoWriteTool())
        registry.register(TodoReadTool())

        # Batch (parallel tool execution)
        registry.register(BatchTool())

        # Shell
        registry.register(BashTool())

        # Search (basic + semantic)
        registry.register(GrepTool())
        registry.register(GlobTool())
        registry.register(CodeSearchTool())

        # Diagnostics
        registry.register(DiagnosticsTool())

        # Network
        registry.register(FetchTool())
        registry.register(DownloadTool())

        # Web tools (search + enhanced fetch)
        registry.register(WebSearchTool())
        registry.register(WebFetchTool())

        # Agent tools
        registry.register(SubAgentTool())
        registry.register(TaskCoordinatorTool())

        # LSP tools
        registry.register(LSPTool())

        # Interactive tools
        registry.register(QuestionTool())
        registry.register(ConfirmTool())

        return registry

    @classmethod
    def standard(cls) -> "ToolRegistry":
        """Create registry with standard tools (no network/agent)."""
        from .file_tools import ReadFileTool, WriteFileTool, ListDirectoryTool
        from .edit_tools import EditFileTool, InsertTextTool, PatchTool, MultiEditTool
        from .shell_tools import BashTool
        from .search_tools import GrepTool, GlobTool, CodeSearchTool
        from .diagnostics import DiagnosticsTool
        from .lsp_tools import LSPTool
        from .question_tool import QuestionTool, ConfirmTool
        from .todo_tools import TodoWriteTool, TodoReadTool
        from .batch_tool import BatchTool

        registry = cls()

        # Core file operations
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(ListDirectoryTool())

        # Editing
        registry.register(EditFileTool())
        registry.register(InsertTextTool())
        registry.register(PatchTool())
        registry.register(MultiEditTool())

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
        registry.register(CodeSearchTool())

        # Diagnostics
        registry.register(DiagnosticsTool())

        # LSP tools
        registry.register(LSPTool())

        # Interactive tools
        registry.register(QuestionTool())
        registry.register(ConfirmTool())

        return registry
