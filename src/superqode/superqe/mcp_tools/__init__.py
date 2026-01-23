"""
MCP Tools Module - Model Context Protocol tools with lazy loading.

Provides 100+ MCP tools organized by domain with 87% context reduction
through lazy loading (only load domain tools when needed).

Tool Categories:
- core: Always loaded (14 tools)
- testing: Test generation, execution, reporting
- security: Vulnerability scanning, OWASP analysis
- performance: Benchmarking, bottleneck analysis
- coverage: Gap detection, coverage analysis
- quality: Quality gates, deployment readiness
- flaky: Detection and stabilization
- accessibility: WCAG compliance, visual regression
- learning: Pattern management, training
"""

from .registry import (
    MCPToolRegistry,
    MCPTool,
    ToolDomain,
    get_registry,
    register_tool,
    get_tool,
    list_tools,
    list_domains,
    load_domain,
    get_loaded_domains,
)
from .core_tools import register_core_tools
from .testing_tools import register_testing_tools

__all__ = [
    "MCPToolRegistry",
    "MCPTool",
    "ToolDomain",
    "get_registry",
    "register_tool",
    "get_tool",
    "list_tools",
    "list_domains",
    "load_domain",
    "get_loaded_domains",
    "register_core_tools",
    "register_testing_tools",
]
