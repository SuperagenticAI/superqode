"""SuperQode harness primitives.

The v2 harness layer is being introduced alongside the existing validation
harness. ``HarnessSpec`` describes user-owned agent harnesses; ``PatchHarness``
continues to provide project validation for generated changes.
"""

from superqode.patch_harness import (
    HarnessConfig,
    HarnessFinding,
    HarnessResult,
    PatchHarness,
    ValidationCategory,
    load_harness_config,
)
from .events import HarnessEvent
from .loader import (
    harness_spec_from_dict,
    harness_spec_json_schema,
    harness_spec_to_dict,
    load_harness_spec,
    save_harness_spec,
)
from .model_policy import EffectiveModelPolicy, resolve_harness_model_policy
from .output import (
    RESULT_END,
    RESULT_START,
    TypedOutputError,
    build_typed_output_prompt,
    parse_typed_output,
)
from .store import (
    FileHarnessStore,
    HarnessEventGraph,
    HarnessGraphEdge,
    HarnessGraphNode,
    HarnessRunRecord,
    HarnessSessionRecord,
    MemoryHarnessStore,
    SQLiteHarnessStore,
    create_harness_store,
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

_LAZY_IMPORTS = {
    # Compiler
    "compile_to_headless_profile": (".compiler", "compile_to_headless_profile"),
    "spec_from_headless_profile": (".compiler", "spec_from_headless_profile"),
    # Runtime backends
    "ADKHarnessBackend": (".backends", "ADKHarnessBackend"),
    "HarnessBackend": (".backends", "HarnessBackend"),
    "HarnessBackendCapabilities": (".backends", "HarnessBackendCapabilities"),
    "HarnessBackendInspection": (".backends", "HarnessBackendInspection"),
    "HarnessBackendIssue": (".backends", "HarnessBackendIssue"),
    "HarnessBackendRequest": (".backends", "HarnessBackendRequest"),
    "HarnessBackendResult": (".backends", "HarnessBackendResult"),
    "DeepAgentsHarnessBackend": (".backends", "DeepAgentsHarnessBackend"),
    "OpenAIAgentsHarnessBackend": (".backends", "OpenAIAgentsHarnessBackend"),
    "PydanticAIHarnessBackend": (".backends", "PydanticAIHarnessBackend"),
    "RuntimeHarnessBackend": (".backends", "RuntimeHarnessBackend"),
    "backend_capabilities": (".backends", "backend_capabilities"),
    "create_harness_backend": (".backends", "create_harness_backend"),
    "inspect_harness_backend": (".backends", "inspect_harness_backend"),
    "known_harness_backend_names": (".backends", "known_harness_backend_names"),
    # Kernel
    "HarnessKernel": (".kernel", "HarnessKernel"),
    "HarnessRunRequest": (".kernel", "HarnessRunRequest"),
    "HarnessRunResult": (".kernel", "HarnessRunResult"),
    "HarnessSession": (".kernel", "HarnessSession"),
    "init_harness": (".kernel", "init_harness"),
    # Sandbox
    "SandboxCapabilities": (".sandbox", "SandboxCapabilities"),
    "SandboxCapabilityBackend": (".sandbox", "SandboxCapabilityBackend"),
    "HarnessSandboxBackend": (".sandbox", "HarnessSandboxBackend"),
    "LocalSandboxBackend": (".sandbox", "LocalSandboxBackend"),
    "SandboxBackend": (".sandbox", "SandboxBackend"),
    "SandboxFileInfo": (".sandbox", "SandboxFileInfo"),
    "SandboxPolicy": (".sandbox", "SandboxPolicy"),
    "SandboxShellResult": (".sandbox", "SandboxShellResult"),
    "apply_backend_permissions": (".sandbox", "apply_backend_permissions"),
    "build_openai_sandbox_agent": (".sandbox", "build_openai_sandbox_agent"),
    "build_openai_sandbox_client": (".sandbox", "build_openai_sandbox_client"),
    "build_openai_sandbox_manifest": (".sandbox", "build_openai_sandbox_manifest"),
    "build_openai_sandbox_run_config": (".sandbox", "build_openai_sandbox_run_config"),
    "get_sandbox_capabilities": (".sandbox", "get_sandbox_capabilities"),
    "is_openai_sandbox_backend_available": (".sandbox", "is_openai_sandbox_backend_available"),
    "require_shell": (".sandbox", "require_shell"),
    "require_write": (".sandbox", "require_write"),
    "sandbox_policy_from_execution_policy": (".sandbox", "sandbox_policy_from_execution_policy"),
    "supported_openai_sandbox_backends": (".sandbox", "supported_openai_sandbox_backends"),
    # Workflow
    "WorkflowResult": (".workflow", "WorkflowResult"),
    "WorkflowProgress": (".workflow", "WorkflowProgress"),
    "WorkflowStep": (".workflow", "WorkflowStep"),
    "run_workflow": (".workflow", "run_workflow"),
    "WorkflowPreset": (".workflow_presets", "WorkflowPreset"),
    "WORKFLOW_PRESETS": (".workflow_presets", "WORKFLOW_PRESETS"),
    "apply_workflow_preset": (".workflow_presets", "apply_workflow_preset"),
    "get_workflow_preset": (".workflow_presets", "get_workflow_preset"),
    "list_workflow_presets": (".workflow_presets", "list_workflow_presets"),
    # Performance
    "Accelerator": (".accelerator", "Accelerator"),
    "AcceleratorConfig": (".accelerator", "AcceleratorConfig"),
    "get_accelerator": (".accelerator", "get_accelerator"),
    "prewarm": (".accelerator", "prewarm"),
    "cached_system_prompt": (".accelerator", "cached_system_prompt"),
}


def __getattr__(name: str):
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module_name, attr_name = _LAZY_IMPORTS[name]
    value = getattr(importlib.import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


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
    "WorkflowProgress",
    "WorkflowPreset",
    "WorkflowResult",
    "WorkflowSpec",
    "WorkflowStep",
    "WORKFLOW_PRESETS",
    "BUILTIN_TEMPLATES",
    "EffectiveModelPolicy",
    "RESULT_END",
    "RESULT_START",
    "ADKHarnessBackend",
    "HarnessBackend",
    "HarnessBackendCapabilities",
    "HarnessBackendInspection",
    "HarnessBackendIssue",
    "HarnessBackendRequest",
    "HarnessBackendResult",
    "HarnessEvent",
    "HarnessKernel",
    "HarnessEventGraph",
    "HarnessGraphEdge",
    "HarnessGraphNode",
    "HarnessRunRequest",
    "HarnessRunResult",
    "HarnessSession",
    "HarnessRunRecord",
    "HarnessSessionRecord",
    "FileHarnessStore",
    "MemoryHarnessStore",
    "SQLiteHarnessStore",
    "DeepAgentsHarnessBackend",
    "OpenAIAgentsHarnessBackend",
    "PydanticAIHarnessBackend",
    "RuntimeHarnessBackend",
    "HarnessSandboxBackend",
    "LocalSandboxBackend",
    "SandboxBackend",
    "SandboxCapabilities",
    "SandboxCapabilityBackend",
    "SandboxFileInfo",
    "SandboxPolicy",
    "SandboxShellResult",
    "TypedOutputError",
    "apply_backend_permissions",
    "apply_workflow_preset",
    "backend_capabilities",
    "build_openai_sandbox_agent",
    "build_openai_sandbox_client",
    "build_openai_sandbox_manifest",
    "build_openai_sandbox_run_config",
    "build_typed_output_prompt",
    "compile_to_headless_profile",
    "create_harness_store",
    "create_harness_backend",
    "get_harness_template",
    "get_workflow_preset",
    "get_sandbox_capabilities",
    "generate_run_id",
    "harness_spec_from_dict",
    "harness_spec_json_schema",
    "harness_spec_to_dict",
    "init_harness",
    "inspect_harness_backend",
    "is_openai_sandbox_backend_available",
    "known_harness_backend_names",
    "list_workflow_presets",
    "parse_typed_output",
    "require_shell",
    "require_write",
    "sandbox_policy_from_execution_policy",
    "supported_openai_sandbox_backends",
    "load_harness_spec",
    "save_harness_spec",
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
