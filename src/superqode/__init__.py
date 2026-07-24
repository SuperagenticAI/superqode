"""
SuperQode CLI package.

This package provides the terminal user interface, command-line interface,
interactive chat, and voice entrypoints for SuperQode, the terminal-first
Agent Engineering framework for your code factory.

Features:
- Repository-owned coding-agent harnesses
- Native, ACP, SDK, BYOK, and local-model connections
- Multi-agent coding team support
- Harness evaluation, governance, and optimization
- Durable WorkOrders with evidence and delivery gates
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
    "Extension",
    "ExtensionCompatibility",
    "ExtensionContext",
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

__version__ = "0.2.35"

# Stable, lightweight public extension surface.  Importing this package does
# not discover or execute third-party extensions; discovery happens only when
# a native harness runtime is constructed.
from .extensions import Extension, ExtensionCompatibility, ExtensionContext
