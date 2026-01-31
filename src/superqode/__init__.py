"""
SuperQode CLI package.

This package provides the terminal user interface (TUI), interactive chat,
and voice entrypoints for SuperQode, a multi-agent coding orchestration platform.

Features:
- Multi-agent coding team support
- Approval system for file changes
- Diff viewer with syntax highlighting
- Plan tracking for agent tasks
- Command history management
- File viewer with search
- Danger detection for shell commands
- Atomic file operations with undo
"""

__all__ = [
    "__version__",
    # Core modules
    "danger",
    "diff_view",
    "approval",
    "plan",
    "tool_call",
    "flash",
    "atomic",
    "file_viewer",
    "history",
    "sidebar",
]

__version__ = "0.1.8"
