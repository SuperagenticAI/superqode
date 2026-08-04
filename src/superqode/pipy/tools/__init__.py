"""PiPy tool contract and the pi coding tools."""

from .base import AgentTool, AgentToolResult, ToolExecutor, ToolUpdateCallback
from .edit_diff import EditError
from .files import create_edit_tool, create_read_tool, create_write_tool
from .registry import (
    ALL_TOOL_NAMES,
    CODING_TOOL_NAMES,
    READ_ONLY_TOOL_NAMES,
    create_all_tools,
    create_coding_tools,
    create_read_only_tools,
    create_tool,
    create_tools,
)
from .search import create_find_tool, create_grep_tool, create_ls_tool
from .shell import create_bash_tool
from .truncate import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    GREP_MAX_LINE_LENGTH,
    TruncationResult,
    format_size,
    truncate_head,
    truncate_line,
    truncate_tail,
)

__all__ = [
    "ALL_TOOL_NAMES",
    "CODING_TOOL_NAMES",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_LINES",
    "GREP_MAX_LINE_LENGTH",
    "READ_ONLY_TOOL_NAMES",
    "AgentTool",
    "AgentToolResult",
    "EditError",
    "ToolExecutor",
    "ToolUpdateCallback",
    "TruncationResult",
    "create_all_tools",
    "create_bash_tool",
    "create_coding_tools",
    "create_edit_tool",
    "create_find_tool",
    "create_grep_tool",
    "create_ls_tool",
    "create_read_only_tools",
    "create_read_tool",
    "create_tool",
    "create_tools",
    "create_write_tool",
    "format_size",
    "truncate_head",
    "truncate_line",
    "truncate_tail",
]
