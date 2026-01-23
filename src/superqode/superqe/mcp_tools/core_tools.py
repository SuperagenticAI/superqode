"""
Core MCP Tools - Always loaded tools for essential operations.

14 core tools:
- fleet_init, agent_spawn, fleet_status
- test_generate, test_execute, test_report
- memory_store, memory_retrieve, memory_query
- quality_analyze, task_orchestrate, task_status
- tools_discover, tools_load_domain
"""

from typing import Any, Dict, List, Optional
from .registry import MCPToolRegistry, MCPTool, ToolDomain


async def fleet_init(
    topology: str = "hierarchical", max_agents: int = 10, **kwargs
) -> Dict[str, Any]:
    """Initialize the QE fleet with specified topology."""
    return {
        "status": "initialized",
        "topology": topology,
        "max_agents": max_agents,
        "available_agents": [
            "flaky-test-hunter",
            "visual-tester",
            "accessibility-ally",
            "deployment-readiness",
            "code-complexity",
            "requirements-validator",
            "contract-tester",
            "mutation-tester",
        ],
    }


async def agent_spawn(
    agent_type: str, config: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """Spawn a QE agent of the specified type."""
    from ..agents import get_agent, AgentConfig

    agent_config = AgentConfig(**(config or {}))
    agent = get_agent(agent_type, agent_config)

    return {
        "agent_id": agent.agent_id,
        "type": agent_type,
        "status": "spawned",
        "info": agent.get_info(),
    }


async def fleet_status(**kwargs) -> Dict[str, Any]:
    """Get the status of the QE fleet."""
    return {
        "status": "active",
        "agents_available": 8,
        "agents_running": 0,
        "domains_loaded": ["core"],
        "memory_usage": "low",
    }


async def test_generate(
    target: str, framework: str = "pytest", coverage_goal: float = 80.0, **kwargs
) -> Dict[str, Any]:
    """Generate tests for the specified target."""
    return {
        "status": "generated",
        "target": target,
        "framework": framework,
        "tests_generated": 0,
        "coverage_goal": coverage_goal,
        "message": "Use testing domain tools for actual generation",
    }


async def test_execute(
    pattern: str = "**/test_*.py", parallel: bool = True, workers: int = 4, **kwargs
) -> Dict[str, Any]:
    """Execute tests matching the pattern."""
    return {
        "status": "executed",
        "pattern": pattern,
        "parallel": parallel,
        "workers": workers,
        "results": {"passed": 0, "failed": 0, "skipped": 0},
    }


async def test_report(
    format: str = "html", output_path: Optional[str] = None, **kwargs
) -> Dict[str, Any]:
    """Generate a test report."""
    return {
        "status": "generated",
        "format": format,
        "output_path": output_path or f"./reports/test_report.{format}",
    }


async def memory_store(
    key: str,
    value: Any,
    namespace: str = "default",
    ttl: Optional[int] = None,
    persist: bool = False,
    **kwargs,
) -> Dict[str, Any]:
    """Store a value in agent memory."""
    return {"status": "stored", "key": key, "namespace": namespace, "persist": persist, "ttl": ttl}


async def memory_retrieve(key: str, namespace: str = "default", **kwargs) -> Dict[str, Any]:
    """Retrieve a value from agent memory."""
    return {
        "status": "retrieved",
        "key": key,
        "namespace": namespace,
        "value": None,
        "found": False,
    }


async def memory_query(
    pattern: str, namespace: str = "default", limit: int = 100, **kwargs
) -> Dict[str, Any]:
    """Query memory with a pattern."""
    return {
        "status": "queried",
        "pattern": pattern,
        "namespace": namespace,
        "results": [],
        "total": 0,
    }


async def quality_analyze(
    target: str, checks: Optional[List[str]] = None, **kwargs
) -> Dict[str, Any]:
    """Analyze code quality."""
    return {
        "status": "analyzed",
        "target": target,
        "checks": checks or ["complexity", "security", "coverage"],
        "score": 0,
        "findings": [],
    }


async def task_orchestrate(
    task: str, agents: Optional[List[str]] = None, priority: str = "medium", **kwargs
) -> Dict[str, Any]:
    """Orchestrate a task across agents."""
    return {
        "status": "orchestrating",
        "task": task,
        "agents": agents or [],
        "priority": priority,
        "task_id": "task-001",
    }


async def task_status(task_id: str, **kwargs) -> Dict[str, Any]:
    """Get the status of a task."""
    return {"task_id": task_id, "status": "pending", "progress": 0, "agents": [], "results": None}


async def tools_discover(
    domain: Optional[str] = None, keyword: Optional[str] = None, **kwargs
) -> Dict[str, Any]:
    """Discover available tools."""
    from .registry import get_registry, ToolDomain

    registry = get_registry()

    if domain:
        try:
            d = ToolDomain(domain)
            tools = registry.list_tools(d)
        except ValueError:
            return {"error": f"Unknown domain: {domain}"}
    else:
        tools = registry.list_tools()

    if keyword:
        tools = [
            t
            for t in tools
            if keyword.lower() in t.name.lower() or keyword.lower() in t.description.lower()
        ]

    return {
        "tools": [t.to_mcp_format() for t in tools],
        "count": len(tools),
        "domains": registry.list_domains(),
    }


async def tools_load_domain(domain: str, **kwargs) -> Dict[str, Any]:
    """Load tools for a specific domain."""
    from .registry import get_registry, ToolDomain

    registry = get_registry()

    try:
        d = ToolDomain(domain)
    except ValueError:
        return {"error": f"Unknown domain: {domain}"}

    # Register domain tools if not already
    if d == ToolDomain.TESTING:
        from .testing_tools import register_testing_tools

        register_testing_tools(registry)
    tools = registry.load_domain(d)

    return {"domain": domain, "tools_loaded": len(tools), "tools": [t.name for t in tools]}


def register_core_tools(registry: MCPToolRegistry) -> None:
    """Register all core tools."""
    tools = [
        MCPTool(
            name="fleet_init",
            description="Initialize the QE fleet with specified topology",
            handler=fleet_init,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {
                    "topology": {"type": "string", "enum": ["hierarchical", "mesh", "ring"]},
                    "max_agents": {"type": "integer", "default": 10},
                },
            },
            keywords=["init", "start", "fleet", "setup"],
        ),
        MCPTool(
            name="agent_spawn",
            description="Spawn a QE agent of the specified type",
            handler=agent_spawn,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {"agent_type": {"type": "string"}, "config": {"type": "object"}},
                "required": ["agent_type"],
            },
            keywords=["spawn", "agent", "create"],
        ),
        MCPTool(
            name="fleet_status",
            description="Get the status of the QE fleet",
            handler=fleet_status,
            domain=ToolDomain.CORE,
            keywords=["status", "health", "fleet"],
        ),
        MCPTool(
            name="test_generate",
            description="Generate tests for a target",
            handler=test_generate,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "framework": {"type": "string"},
                    "coverage_goal": {"type": "number"},
                },
                "required": ["target"],
            },
            keywords=["generate", "test", "create"],
        ),
        MCPTool(
            name="test_execute",
            description="Execute tests",
            handler=test_execute,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "parallel": {"type": "boolean"},
                    "workers": {"type": "integer"},
                },
            },
            keywords=["run", "execute", "test"],
        ),
        MCPTool(
            name="test_report",
            description="Generate test report",
            handler=test_report,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {
                    "format": {"type": "string", "enum": ["html", "json", "junit", "markdown"]},
                    "output_path": {"type": "string"},
                },
            },
            keywords=["report", "test", "results"],
        ),
        MCPTool(
            name="memory_store",
            description="Store a value in agent memory",
            handler=memory_store,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {},
                    "namespace": {"type": "string"},
                    "ttl": {"type": "integer"},
                    "persist": {"type": "boolean"},
                },
                "required": ["key", "value"],
            },
            keywords=["store", "memory", "save"],
        ),
        MCPTool(
            name="memory_retrieve",
            description="Retrieve a value from agent memory",
            handler=memory_retrieve,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {"key": {"type": "string"}, "namespace": {"type": "string"}},
                "required": ["key"],
            },
            keywords=["get", "retrieve", "memory"],
        ),
        MCPTool(
            name="memory_query",
            description="Query memory with a pattern",
            handler=memory_query,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "namespace": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["pattern"],
            },
            keywords=["query", "search", "memory"],
        ),
        MCPTool(
            name="quality_analyze",
            description="Analyze code quality",
            handler=quality_analyze,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "checks": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["target"],
            },
            keywords=["analyze", "quality", "check"],
        ),
        MCPTool(
            name="task_orchestrate",
            description="Orchestrate a task across agents",
            handler=task_orchestrate,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "agents": {"type": "array", "items": {"type": "string"}},
                    "priority": {"type": "string"},
                },
                "required": ["task"],
            },
            keywords=["orchestrate", "task", "coordinate"],
        ),
        MCPTool(
            name="task_status",
            description="Get task status",
            handler=task_status,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
            keywords=["status", "task"],
        ),
        MCPTool(
            name="tools_discover",
            description="Discover available tools",
            handler=tools_discover,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {"domain": {"type": "string"}, "keyword": {"type": "string"}},
            },
            keywords=["discover", "tools", "list"],
        ),
        MCPTool(
            name="tools_load_domain",
            description="Load tools for a specific domain",
            handler=tools_load_domain,
            domain=ToolDomain.CORE,
            schema={
                "type": "object",
                "properties": {"domain": {"type": "string"}},
                "required": ["domain"],
            },
            keywords=["load", "domain", "tools"],
        ),
    ]

    for tool in tools:
        registry.register(tool)
