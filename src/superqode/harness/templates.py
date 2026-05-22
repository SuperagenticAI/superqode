"""Built-in SuperQode harness templates."""

from __future__ import annotations

from .spec import (
    AgentSpec,
    ExecutionPolicySpec,
    HarnessFlavor,
    HarnessSpec,
    ModelPolicySpec,
    RuntimeSpec,
    ValidationSpec,
)


def coding_template(*, name: str = "superqode-coding", backend: str = "builtin") -> HarnessSpec:
    """Default tool-rich coding harness."""
    return HarnessSpec(
        name=name,
        description="Tool-rich coding harness for repository work.",
        flavor=HarnessFlavor.CODING,
        runtime=RuntimeSpec(backend=backend),
        execution_policy=ExecutionPolicySpec(
            sandbox="local",
            approval_profile="balanced",
            allow_read=True,
            allow_write=True,
            allow_shell=True,
        ),
        agents=(
            AgentSpec(
                id="coder",
                role="implementation",
                tools=(
                    "read_file",
                    "write_file",
                    "list_directory",
                    "edit_file",
                    "insert_text",
                    "patch",
                    "multi_edit",
                    "grep",
                    "glob",
                    "repo_search",
                    "code_search",
                    "bash",
                    "todo_write",
                    "todo_read",
                ),
                skills=("repo-navigation", "implementation"),
            ),
        ),
        validation=ValidationSpec(enabled=True),
        metadata={"template": "coding"},
    )


def no_tool_template(*, name: str = "superqode-no-tool", backend: str = "builtin") -> HarnessSpec:
    """Model-only harness for tool-free reasoning and model evaluation."""
    return HarnessSpec(
        name=name,
        description="Model-only reasoning harness with no tools or repository access.",
        flavor=HarnessFlavor.NO_TOOL,
        runtime=RuntimeSpec(backend=backend),
        execution_policy=ExecutionPolicySpec(
            sandbox="none",
            approval_profile="deny",
            allow_read=False,
            allow_write=False,
            allow_shell=False,
            allow_network=False,
        ),
        agents=(
            AgentSpec(
                id="reasoner",
                role="reasoning",
                tools=(),
                skills=("architecture-review", "code-review-from-context"),
            ),
        ),
        metadata={"template": "no-tool"},
    )


def gemma4_coding_template() -> HarnessSpec:
    """Gemma4-optimized coding harness starting point."""
    base = coding_template(name="gemma4-coding")
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": "Gemma4 local coding harness tuned for strict JSON tool calls.",
            "model_policy": ModelPolicySpec(
                primary="gemma4-local",
                fallbacks=("ds4-local",),
                profile="gemma4-coding",
                temperature=0.2,
                local_hardware="mlx",
                tool_call_format="strict-json",
            ),
            "metadata": {"template": "gemma4-coding"},
        }
    )


def gemma4_no_tool_template() -> HarnessSpec:
    """Gemma4-optimized no-tool harness starting point."""
    base = no_tool_template(name="gemma4-no-tool")
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": "Gemma4 local reasoning harness with no repository tools.",
            "model_policy": ModelPolicySpec(
                primary="gemma4-local",
                fallbacks=("ds4-local",),
                profile="gemma4-no-tool",
                temperature=0.2,
                local_hardware="mlx",
            ),
            "metadata": {"template": "gemma4-no-tool"},
        }
    )


def ds4_coding_template() -> HarnessSpec:
    """DS4/local-fast coding harness starting point."""
    base = coding_template(name="ds4-coding")
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": "DS4 local coding harness tuned for compact JSON tool calls.",
            "model_policy": ModelPolicySpec(
                primary="ds4-local",
                profile="ds4-coding",
                temperature=0.2,
                tool_call_format="compact-json",
            ),
            "metadata": {"template": "ds4-coding"},
        }
    )


def ds4_fast_local_template() -> HarnessSpec:
    """DS4 template for latency-sensitive local coding runs."""
    base = ds4_coding_template()
    return HarnessSpec(
        **{
            **base.__dict__,
            "name": "ds4-fast-local",
            "description": "Compact DS4 coding harness for fast local iteration.",
            "model_policy": ModelPolicySpec(
                primary="ds4-local",
                profile="ds4-fast-local",
                temperature=0.1,
                tool_call_format="compact-json",
                config={
                    "max_iterations": 25,
                    "session_history_limit": 10,
                    "parallel_tools": False,
                    "tool_profile": "ds4",
                },
            ),
            "metadata": {"template": "ds4-fast-local"},
        }
    )


BUILTIN_TEMPLATES = {
    "coding": coding_template,
    "no-tool": no_tool_template,
    "no_tool": no_tool_template,
    "gemma4-coding": gemma4_coding_template,
    "gemma4-no-tool": gemma4_no_tool_template,
    "gemma4-no_tool": gemma4_no_tool_template,
    "ds4-coding": ds4_coding_template,
    "ds4-fast-local": ds4_fast_local_template,
    "ds4-fast_local": ds4_fast_local_template,
}


def get_harness_template(name: str) -> HarnessSpec:
    """Return a built-in harness template by name."""
    normalized = (name or "coding").strip().lower()
    factory = BUILTIN_TEMPLATES.get(normalized)
    if factory is None:
        valid = ", ".join(sorted(BUILTIN_TEMPLATES))
        raise ValueError(f"Unknown harness template {name!r}. Valid templates: {valid}")
    return factory()
