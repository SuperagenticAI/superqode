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
    config: dict[str, Any] = field(default_factory=dict)


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
class ContextSpec:
    """Context, instruction, memory, and compaction policy."""

    instruction_files: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md", "SUPERQODE.md")
    skills_dir: str = ".agents/skills"
    roles_dir: str = ".agents/roles"
    session_storage: str = ".superqode/sessions"
    compaction: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationStepSpec:
    """Project validation step."""

    name: str
    command: str
    enabled: bool = True
    timeout: int = 300


@dataclass(frozen=True)
class ValidationSpec:
    """Validation lifecycle policy."""

    enabled: bool = False
    fail_on_error: bool = False
    timeout_seconds: int = 300
    custom_steps: tuple[ValidationStepSpec, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ObservabilitySpec:
    """Run/session observability policy."""

    events: bool = True
    traces: bool = False
    run_store: str = "memory"
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessSpec:
    """Top-level SuperQode harness definition."""

    name: str
    version: int = 1
    description: str = ""
    flavor: HarnessFlavor = HarnessFlavor.CODING
    runtime: RuntimeSpec = field(default_factory=RuntimeSpec)
    model_policy: ModelPolicySpec = field(default_factory=ModelPolicySpec)
    execution_policy: ExecutionPolicySpec = field(default_factory=ExecutionPolicySpec)
    agents: tuple[AgentSpec, ...] = ()
    workflow: WorkflowSpec = field(default_factory=WorkflowSpec)
    context: ContextSpec = field(default_factory=ContextSpec)
    validation: ValidationSpec = field(default_factory=ValidationSpec)
    observability: ObservabilitySpec = field(default_factory=ObservabilitySpec)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_no_tool(self) -> bool:
        return self.flavor == HarnessFlavor.NO_TOOL

    @property
    def is_coding(self) -> bool:
        return self.flavor == HarnessFlavor.CODING


CompiledProfileName = Literal["build", "plan", "review", "no-tool"]
