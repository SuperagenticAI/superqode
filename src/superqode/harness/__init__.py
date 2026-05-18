"""SuperQode harness primitives.

The v2 harness layer is being introduced alongside the existing validation
harness. ``HarnessSpec`` describes user-owned agent harnesses; ``PatchHarness``
continues to provide project validation for generated changes.
"""

from .validator import PatchHarness, HarnessFinding, HarnessResult
from .config import HarnessConfig, ValidationCategory, load_harness_config
from .compiler import compile_to_headless_profile, spec_from_headless_profile
from .backends import (
    HarnessBackend,
    HarnessBackendRequest,
    HarnessBackendResult,
    RuntimeHarnessBackend,
    create_harness_backend,
    known_harness_backend_names,
)
from .events import HarnessEvent
from .kernel import HarnessKernel, HarnessRunRequest, HarnessRunResult, HarnessSession, init_harness
from .loader import harness_spec_from_dict, harness_spec_to_dict, load_harness_spec
from .model_policy import EffectiveModelPolicy, resolve_harness_model_policy
from .output import (
    RESULT_END,
    RESULT_START,
    TypedOutputError,
    build_typed_output_prompt,
    parse_typed_output,
)
from .sandbox import (
    LocalSandboxBackend,
    SandboxBackend,
    SandboxFileInfo,
    SandboxPolicy,
    SandboxShellResult,
    require_shell,
    require_write,
    sandbox_policy_from_execution_policy,
)
from .store import (
    FileHarnessStore,
    HarnessRunRecord,
    HarnessSessionRecord,
    generate_run_id,
)
from .spec import (
    AgentSpec,
    ContextSpec,
    ExecutionPolicySpec,
    HarnessFlavor,
    HarnessSpec,
    ModelPolicySpec,
    ObservabilitySpec,
    RuntimeSpec,
    ValidationSpec,
    ValidationStepSpec,
    WorkflowMode,
    WorkflowSpec,
)
from .templates import BUILTIN_TEMPLATES, get_harness_template
from .workflow import WorkflowResult, WorkflowStep, run_workflow
from .accelerator import (
    Accelerator,
    AcceleratorConfig,
    get_accelerator,
    prewarm,
    cached_system_prompt,
)

__all__ = [
    # Validation
    "PatchHarness",
    "HarnessFinding",
    "HarnessResult",
    "ValidationCategory",
    "HarnessConfig",
    "load_harness_config",
    # Agent harness specs
    "AgentSpec",
    "ContextSpec",
    "ExecutionPolicySpec",
    "HarnessFlavor",
    "HarnessSpec",
    "ModelPolicySpec",
    "ObservabilitySpec",
    "RuntimeSpec",
    "ValidationSpec",
    "ValidationStepSpec",
    "WorkflowMode",
    "WorkflowResult",
    "WorkflowSpec",
    "WorkflowStep",
    "BUILTIN_TEMPLATES",
    "EffectiveModelPolicy",
    "RESULT_END",
    "RESULT_START",
    "HarnessBackend",
    "HarnessBackendRequest",
    "HarnessBackendResult",
    "HarnessEvent",
    "HarnessKernel",
    "HarnessRunRequest",
    "HarnessRunResult",
    "HarnessSession",
    "HarnessRunRecord",
    "HarnessSessionRecord",
    "FileHarnessStore",
    "RuntimeHarnessBackend",
    "LocalSandboxBackend",
    "SandboxBackend",
    "SandboxFileInfo",
    "SandboxPolicy",
    "SandboxShellResult",
    "TypedOutputError",
    "build_typed_output_prompt",
    "compile_to_headless_profile",
    "create_harness_backend",
    "get_harness_template",
    "generate_run_id",
    "harness_spec_from_dict",
    "harness_spec_to_dict",
    "init_harness",
    "known_harness_backend_names",
    "parse_typed_output",
    "require_shell",
    "require_write",
    "sandbox_policy_from_execution_policy",
    "load_harness_spec",
    "run_workflow",
    "resolve_harness_model_policy",
    "spec_from_headless_profile",
    # Performance
    "Accelerator",
    "AcceleratorConfig",
    "get_accelerator",
    "prewarm",
    "cached_system_prompt",
]
