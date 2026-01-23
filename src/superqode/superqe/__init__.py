"""
SuperQE (Super Quality Engineering) Module.

This is the main entry point for SuperQode's quality engineering functionality.

Key components:
- QESession: Orchestrates a QE session
- QEOrchestrator: High-level interface for CLI/CI
- QEEventEmitter: JSONL event streaming for CI
- NoiseFilter: Filters and deduplicates findings
- QERole: Execution and detection roles
- FixVerifier: Verify suggested fixes work

Features:
- Git worktree-based isolation
- Session coordination with locking
- Diff tracking for patch generation
- Structured QIR with priorities and confidence
- JSONL event streaming
- Noise controls (confidence, deduplication, severity filtering)
- Allow Suggestions mode (prove fixes, then revert)
- Constitution system with guardrails
- MCP tools with lazy loading
- Multi-framework test execution
- QE Skills bank (46+ skills)
- 8 specialized QE agents
"""

from .session import QESession, QESessionConfig
from .orchestrator import QEOrchestrator, SuggestionMode
from .events import (
    QEEventEmitter,
    QEEventCollector,
    QEEvent,
    EventType,
    get_event_emitter,
    set_event_emitter,
    emit_event,
)
from .noise import (
    NoiseFilter,
    NoiseConfig,
    load_noise_config,
    Finding as NoiseFinding,
)
from .roles import (
    QERole,
    RoleType,
    RoleConfig,
    RoleResult,
    get_role,
    list_roles,
    ROLE_REGISTRY,
)
from .acp_runner import (
    ACPQERunner,
    ACPRunnerConfig,
    ACPRunnerResult,
    ACPFinding,
    get_qe_prompt,
)
from .verifier import (
    FixVerifier,
    FixVerifierConfig,
    VerificationResult,
    VerificationStatus,
)

# Constitution System
from .constitution import (
    Constitution,
    Principle,
    Rule,
    ConstitutionLoader,
    ConstitutionEvaluator,
    EvaluationResult,
)

# MCP Tools with Lazy Loading
from .mcp_tools import (
    MCPToolRegistry,
    MCPTool,
    get_tool,
    list_tools,
    load_domain,
)

# Multi-Framework Test Execution
from .frameworks import (
    TestFramework,
    FrameworkConfig,
    ExecutionResult,
    FrameworkRegistry,
    detect_framework,
    get_framework,
    MultiFrameworkExecutor,
    execute_tests,
)

# QE Skills Bank
from .skills import (
    Skill,
    SkillConfig,
    SkillResult,
    SkillRegistry,
    get_skill,
    list_skills,
)


__all__ = [
    # Session management
    "QESession",
    "QESessionConfig",
    "QEOrchestrator",
    "SuggestionMode",
    # Event streaming
    "QEEventEmitter",
    "QEEventCollector",
    "QEEvent",
    "EventType",
    "get_event_emitter",
    "set_event_emitter",
    "emit_event",
    # Noise controls
    "NoiseFilter",
    "NoiseConfig",
    "load_noise_config",
    "NoiseFinding",
    # Roles
    "QERole",
    "RoleType",
    "RoleConfig",
    "RoleResult",
    "get_role",
    "list_roles",
    "ROLE_REGISTRY",
    # ACP Runner
    "ACPQERunner",
    "ACPRunnerConfig",
    "ACPRunnerResult",
    "ACPFinding",
    "get_qe_prompt",
    # Fix Verifier (allow_suggestions mode)
    "FixVerifier",
    "FixVerifierConfig",
    "VerificationResult",
    "VerificationStatus",
    # Specialized QE Agents
    "BaseQEAgent",
    "AgentConfig",
    "AgentResult",
    "get_agent",
    "list_agents",
    # Constitution System
    "Constitution",
    "Principle",
    "Rule",
    "ConstitutionLoader",
    "ConstitutionEvaluator",
    "EvaluationResult",
    # MCP Tools
    "MCPToolRegistry",
    "MCPTool",
    "get_tool",
    "list_tools",
    "load_domain",
    # Multi-Framework Test Execution
    "TestFramework",
    "FrameworkConfig",
    "ExecutionResult",
    "FrameworkRegistry",
    "detect_framework",
    "get_framework",
    "MultiFrameworkExecutor",
    "execute_tests",
    # QE Skills Bank
    "Skill",
    "SkillConfig",
    "SkillResult",
    "SkillRegistry",
    "get_skill",
    "list_skills",
]
