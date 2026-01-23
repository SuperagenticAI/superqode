"""
SuperQode Tools - Comprehensive Tool System for AI Coding Agents.

Design Philosophy:
- COMPREHENSIVE: Full-featured tooling for complex tasks
- TRANSPARENT: No hidden prompts or context injection
- STANDARD: Use OpenAI-compatible tool format
- EXTENSIBLE: Easy to add new tools

Tool Categories:
- File Operations: read, write, edit, patch, multi-edit
- Search: grep, glob, semantic code search
- Shell: bash with streaming and safety
- Diagnostics: LSP integration, linter errors
- Network: fetch URLs, download files, web search
- Agent: sub-agent spawning for parallel work
- LSP: Language Server Protocol operations
- Interactive: ask user questions during execution
"""

from .base import Tool, ToolResult, ToolContext, ToolRegistry
from .file_tools import ReadFileTool, WriteFileTool, ListDirectoryTool
from .edit_tools import EditFileTool, InsertTextTool, PatchTool, MultiEditTool
from .todo_tools import TodoWriteTool, TodoReadTool
from .batch_tool import BatchTool
from .shell_tools import BashTool
from .search_tools import GrepTool, GlobTool, CodeSearchTool
from .diagnostics import DiagnosticsTool
from .network_tools import FetchTool, DownloadTool
from .agent_tools import SubAgentTool, TaskCoordinatorTool
from .lsp_tools import LSPTool
from .web_tools import WebSearchTool, WebFetchTool
from .question_tool import QuestionTool, ConfirmTool, set_question_handler, get_question_handler
from .permissions import (
    Permission,
    PermissionConfig,
    PermissionManager,
    get_permission_manager,
    set_permission_manager,
    load_permission_config,
)

__all__ = [
    # Base
    "Tool",
    "ToolResult",
    "ToolContext",
    "ToolRegistry",
    # File tools
    "ReadFileTool",
    "WriteFileTool",
    "ListDirectoryTool",
    # Edit tools
    "EditFileTool",
    "InsertTextTool",
    "PatchTool",
    "MultiEditTool",
    # TODO tools
    "TodoWriteTool",
    "TodoReadTool",
    "BatchTool",
    # Shell tools
    "BashTool",
    # Search tools
    "GrepTool",
    "GlobTool",
    "CodeSearchTool",
    # Diagnostics
    "DiagnosticsTool",
    # Network tools
    "FetchTool",
    "DownloadTool",
    # Web tools
    "WebSearchTool",
    "WebFetchTool",
    # Agent tools
    "SubAgentTool",
    "TaskCoordinatorTool",
    # LSP tools
    "LSPTool",
    # Interactive tools
    "QuestionTool",
    "ConfirmTool",
    "set_question_handler",
    "get_question_handler",
    # Permissions
    "Permission",
    "PermissionConfig",
    "PermissionManager",
    "get_permission_manager",
    "set_permission_manager",
    "load_permission_config",
]
