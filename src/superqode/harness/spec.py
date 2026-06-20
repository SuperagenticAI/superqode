"""Declarative harness specification for SuperQode v2.

The spec is intentionally conservative: it captures the public shape we want
without replacing the existing runtime path. Existing headless profiles can be
compiled from this schema first, then the kernel can grow behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class HarnessFlavor(str, Enum):
    """Built-in harness flavors."""

    CODING = "coding"
    NO_TOOL = "no_tool"


class WorkflowMode(str, Enum):
    """Workflow topology requested by a harness."""

    SINGLE = "single"
    CHAIN = "chain"
    PARALLEL = "parallel"
    ROUTER = "router"
    ORCHESTRATOR = "orchestrator"
    EVALUATOR_OPTIMIZER = "evaluator_optimizer"


@dataclass(frozen=True)
class RuntimeSpec:
    """Runtime backend selection."""

    backend: str = "builtin"
    fallback_backends: tuple[str, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelPolicySpec:
    """Model routing and model-behavior policy."""

    primary: str | None = None
    fallbacks: tuple[str, ...] = ()
    profile: str | None = None
    temperature: float | None = None
    context_window: int | None = None
    reasoning: str | None = None
    local_hardware: str | None = None
    tool_call_format: str | None = None
    pack: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PermissionRuleSpec:
    """One rule-based approval rule, evaluated when a tool needs approval.

    ``tool`` is a glob over the tool name. ``pattern`` is a glob matched against
    an argument value (the ``argument`` key if given, otherwise any argument
    value); ``"*"`` matches any call to the tool. ``action`` is one of
    ``allow`` / ``deny`` / ``ask``. Rules are evaluated in order and the first
    match wins, so order them most-specific first.
    """

    tool: str = "*"
    pattern: str = "*"
    action: str = "ask"
    argument: str = ""


@dataclass(frozen=True)
class ExecutionPolicySpec:
    """Tool, sandbox, command, and approval policy."""

    sandbox: str = "local"
    approval_profile: str = "balanced"
    allow_read: bool = True
    allow_write: bool = False
    allow_shell: bool = False
    allow_network: bool = False
    allowed_commands: tuple[str, ...] = ()
    blocked_categories: tuple[str, ...] = ()
    permission_rules: tuple[PermissionRuleSpec, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentSpec:
    """One agent role inside a harness."""

    id: str
    role: str = ""
    model: str | None = None
    system_prompt: str | None = None
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    delegates_to: tuple[str, ...] = ()
    max_iterations: int | None = None
    output_schema: dict[str, Any] | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowSpec:
    """Multi-agent workflow policy."""

    mode: WorkflowMode = WorkflowMode.SINGLE
    preset: str = ""
    max_task_depth: int = 4
    parallelism: int = 1
    merge_strategy: str = "summary"
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecursionSpec:
    """Bounded recursive harness delegation policy."""

    enabled: bool = False
    max_depth: int = 1
    max_children: int = 6
    max_parallel: int = 2
    max_wall_seconds: int = 600
    max_budget: float | None = None
    child_model: str | None = None
    child_sandbox: str = "docker"
    write_policy: str = "approval"  # approval | deny | allow
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RemoteHarnessSpec:
    """Optional managed-agent execution backend policy."""

    enabled: bool = False
    provider: str = ""
    agent_id: str | None = None
    region: str | None = None
    context_policy: str = "selected-files"
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextSpec:
    """Context, instruction, memory, and compaction policy."""

    instruction_files: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md", "SUPERQODE.md")
    skills_dir: str = ".agents/skills"
    roles_dir: str = ".agents/roles"
    session_storage: str = ".superqode/sessions"
    prompt_persistence: str = "preview"  # off | preview | full
    compaction: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckStepSpec:
    """Project checks step."""

    name: str
    command: str
    enabled: bool = True
    timeout: int = 300


@dataclass(frozen=True)
class ChecksSpec:
    """Checks lifecycle policy."""

    enabled: bool = False
    fail_on_error: bool = False
    timeout_seconds: int = 300
    custom_steps: tuple[CheckStepSpec, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookRuleSpec:
    """One declarative lifecycle hook bound to a handler.

    ``point`` is an agent lifecycle hook name (see ``agent.hooks``), e.g.
    ``permission_request``, ``before_tool_call``, ``before_compact``.
    ``handler`` is a dotted import path to a callable: ``module:function`` or
    ``module.function``. For tool/permission points, ``matcher`` is a glob
    matched against the tool name so a rule can target specific tools.
    """

    point: str
    handler: str
    matcher: str = "*"
    name: str = ""
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HooksSpec:
    """Declarative hook policy attached to a harness."""

    enabled: bool = True
    rules: tuple[HookRuleSpec, ...] = ()


@dataclass(frozen=True)
class ObservabilitySpec:
    """Run/session observability policy."""

    events: bool = True
    traces: bool = False
    local: bool = True
    exporters: tuple[dict[str, Any], ...] = ()
    run_store: str = "memory"
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessSpec:
    """Top-level SuperQode harness definition."""

    name: str
    inherits: str | None = None
    version: int = 1
    description: str = ""
    flavor: HarnessFlavor = HarnessFlavor.CODING
    runtime: RuntimeSpec = field(default_factory=RuntimeSpec)
    model_policy: ModelPolicySpec = field(default_factory=ModelPolicySpec)
    execution_policy: ExecutionPolicySpec = field(default_factory=ExecutionPolicySpec)
    agents: tuple[AgentSpec, ...] = ()
    workflow: WorkflowSpec = field(default_factory=WorkflowSpec)
    recursion: RecursionSpec = field(default_factory=RecursionSpec)
    remote_harness: RemoteHarnessSpec = field(default_factory=RemoteHarnessSpec)
    context: ContextSpec = field(default_factory=ContextSpec)
    checks: ChecksSpec = field(default_factory=ChecksSpec)
    observability: ObservabilitySpec = field(default_factory=ObservabilitySpec)
    hooks: HooksSpec = field(default_factory=HooksSpec)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_no_tool(self) -> bool:
        return self.flavor == HarnessFlavor.NO_TOOL

    @property
    def is_coding(self) -> bool:
        return self.flavor == HarnessFlavor.CODING


CompiledProfileName = Literal["build", "plan", "review", "no-tool"]
