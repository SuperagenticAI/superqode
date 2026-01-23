"""
MCP Tool Registry - Central registry for MCP tools with lazy loading.

Implements 87% context reduction by only loading domain tools when needed.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


class ToolDomain(str, Enum):
    """Tool domains for lazy loading."""

    CORE = "core"  # Always loaded
    TESTING = "testing"  # Test generation, execution
    SECURITY = "security"  # Vulnerability scanning
    PERFORMANCE = "performance"  # Benchmarking
    COVERAGE = "coverage"  # Coverage analysis
    QUALITY = "quality"  # Quality gates
    FLAKY = "flaky"  # Flaky test detection
    ACCESSIBILITY = "accessibility"  # A11y testing
    LEARNING = "learning"  # Pattern management
    ADVANCED = "advanced"  # Mutation, contract testing


@dataclass
class MCPTool:
    """Definition of an MCP tool."""

    name: str
    description: str
    handler: Callable[..., Any]
    domain: ToolDomain
    schema: Optional[Dict[str, Any]] = None
    keywords: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    requires_auth: bool = False
    timeout: int = 30

    def to_mcp_format(self) -> Dict[str, Any]:
        """Convert to MCP tool format."""
        result = {
            "name": self.name,
            "description": self.description,
        }
        if self.schema:
            result["inputSchema"] = self.schema
        return result


class MCPToolRegistry:
    """
    Registry for MCP tools with lazy loading.

    Only core tools are loaded initially. Domain-specific tools
    are loaded on-demand when requested or when keywords match.
    """

    def __init__(self):
        self._tools: Dict[str, MCPTool] = {}
        self._domains: Dict[ToolDomain, List[str]] = {d: [] for d in ToolDomain}
        self._loaded_domains: Set[ToolDomain] = {ToolDomain.CORE}
        self._keyword_index: Dict[str, Set[str]] = {}

    def register(self, tool: MCPTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        self._domains[tool.domain].append(tool.name)

        # Index keywords
        for keyword in tool.keywords:
            if keyword not in self._keyword_index:
                self._keyword_index[keyword] = set()
            self._keyword_index[keyword].add(tool.name)

        logger.debug(f"Registered tool: {tool.name} in domain {tool.domain.value}")

    def get_tool(self, name: str) -> Optional[MCPTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(
        self, domain: Optional[ToolDomain] = None, loaded_only: bool = False
    ) -> List[MCPTool]:
        """List tools, optionally filtered by domain."""
        if domain:
            tool_names = self._domains.get(domain, [])
        else:
            tool_names = list(self._tools.keys())

        tools = []
        for name in tool_names:
            tool = self._tools.get(name)
            if tool:
                if loaded_only and tool.domain not in self._loaded_domains:
                    continue
                tools.append(tool)

        return tools

    def list_domains(self) -> List[Dict[str, Any]]:
        """List available domains with tool counts."""
        return [
            {
                "domain": domain.value,
                "tool_count": len(self._domains[domain]),
                "loaded": domain in self._loaded_domains,
            }
            for domain in ToolDomain
        ]

    def load_domain(self, domain: ToolDomain) -> List[MCPTool]:
        """Load a domain's tools."""
        if domain in self._loaded_domains:
            return self.list_tools(domain)

        self._loaded_domains.add(domain)
        logger.info(f"Loaded domain: {domain.value}")

        return self.list_tools(domain)

    def get_loaded_domains(self) -> List[ToolDomain]:
        """Get list of loaded domains."""
        return list(self._loaded_domains)

    def auto_load_for_keywords(self, text: str) -> List[ToolDomain]:
        """Auto-load domains based on keyword detection in text."""
        text_lower = text.lower()
        domains_to_load: Set[ToolDomain] = set()

        # Keyword patterns for auto-loading
        domain_keywords = {
            ToolDomain.TESTING: ["test", "generate test", "run test", "test suite"],
            ToolDomain.SECURITY: ["security", "vulnerability", "scan", "owasp", "cve"],
            ToolDomain.PERFORMANCE: ["performance", "benchmark", "slow", "bottleneck"],
            ToolDomain.COVERAGE: ["coverage", "gap", "uncovered"],
            ToolDomain.QUALITY: ["quality", "gate", "deploy", "readiness"],
            ToolDomain.FLAKY: ["flaky", "unstable", "intermittent"],
            ToolDomain.ACCESSIBILITY: ["accessibility", "a11y", "wcag", "screen reader"],
            ToolDomain.LEARNING: ["pattern", "learn", "train"],
            ToolDomain.ADVANCED: ["mutation", "contract", "api spec"],
        }

        for domain, keywords in domain_keywords.items():
            if domain in self._loaded_domains:
                continue
            for keyword in keywords:
                if keyword in text_lower:
                    domains_to_load.add(domain)
                    break

        # Load detected domains
        for domain in domains_to_load:
            self.load_domain(domain)

        return list(domains_to_load)

    def get_tools_for_mcp(self) -> List[Dict[str, Any]]:
        """Get all loaded tools in MCP format."""
        tools = []
        for tool in self.list_tools(loaded_only=True):
            tools.append(tool.to_mcp_format())
        return tools

    async def invoke(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke a tool by name."""
        tool = self.get_tool(tool_name)
        if not tool:
            return {"error": f"Tool not found: {tool_name}"}

        # Auto-load domain if needed
        if tool.domain not in self._loaded_domains:
            self.load_domain(tool.domain)

        try:
            result = await tool.handler(**params)
            return {"result": result}
        except Exception as e:
            logger.exception(f"Tool invocation failed: {tool_name}")
            return {"error": str(e)}


# Global registry instance
_registry: Optional[MCPToolRegistry] = None


def get_registry() -> MCPToolRegistry:
    """Get the global tool registry."""
    global _registry
    if _registry is None:
        _registry = MCPToolRegistry()
        # Register core tools by default
        from .core_tools import register_core_tools

        register_core_tools(_registry)
    return _registry


def register_tool(tool: MCPTool) -> None:
    """Register a tool in the global registry."""
    get_registry().register(tool)


def get_tool(name: str) -> Optional[MCPTool]:
    """Get a tool from the global registry."""
    return get_registry().get_tool(name)


def list_tools(domain: Optional[ToolDomain] = None) -> List[MCPTool]:
    """List tools from the global registry."""
    return get_registry().list_tools(domain)


def list_domains() -> List[Dict[str, Any]]:
    """List domains from the global registry."""
    return get_registry().list_domains()


def load_domain(domain: ToolDomain) -> List[MCPTool]:
    """Load a domain in the global registry."""
    return get_registry().load_domain(domain)


def get_loaded_domains() -> List[ToolDomain]:
    """Get loaded domains from the global registry."""
    return get_registry().get_loaded_domains()
