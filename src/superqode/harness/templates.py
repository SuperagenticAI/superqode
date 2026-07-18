"""Built-in SuperQode harness templates."""

from __future__ import annotations

from .spec import (
    AgentSpec,
    ExecutionPolicySpec,
    HarnessFlavor,
    HarnessSpec,
    ModelPolicySpec,
    RuntimeSpec,
    ChecksSpec,
)
from .model_routes import model_policy_for_route


def core_template(*, name: str = "core", backend: str = "builtin") -> HarnessSpec:
    """Lean four-tool native coding harness."""
    return HarnessSpec(
        name=name,
        description="Lean native coding harness with read, write, edit, and bash.",
        flavor=HarnessFlavor.CODING,
        runtime=RuntimeSpec(backend=backend),
        model_policy=ModelPolicySpec(
            profile="core",
            config={
                "system_level": "core",
                "tool_profile": "core",
                "max_iterations": 0,
                "session_history_limit": 20,
                "parallel_tools": True,
            },
        ),
        execution_policy=ExecutionPolicySpec(
            sandbox="local",
            approval_profile="balanced",
            allow_read=True,
            allow_write=True,
            allow_shell=True,
            allow_network=False,
        ),
        agents=(
            AgentSpec(
                id="coder",
                role="implementation",
                tools=("read", "write", "edit", "bash"),
            ),
        ),
        checks=ChecksSpec(enabled=False),
        metadata={"template": "core", "builtin_harness": True},
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
                    "local_code_search",
                    "repo_search",
                    "code_search",
                    "bash",
                    "todo_write",
                    "todo_read",
                ),
                skills=("repo-navigation", "implementation"),
            ),
        ),
        checks=ChecksSpec(enabled=True),
        metadata={"template": "coding"},
    )


def workbench_template(*, name: str = "workbench", backend: str = "builtin") -> HarnessSpec:
    """Feature-rich native harness preserving the former default behavior."""
    base = coding_template(name=name, backend=backend)
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": "Feature-rich native coding harness with the full workbench toolset.",
            "model_policy": ModelPolicySpec(
                profile="workbench",
                config={
                    "system_level": "full",
                    "tool_profile": "coding",
                    "max_iterations": 0,
                    "session_history_limit": 20,
                    "parallel_tools": True,
                },
            ),
            "metadata": {"template": "workbench", "builtin_harness": True},
        }
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
                    "max_iterations": 0,
                    "session_history_limit": 10,
                    "parallel_tools": False,
                    "tool_profile": "ds4",
                },
            ),
            "metadata": {"template": "ds4-fast-local"},
        }
    )


def qwen_coding_template() -> HarnessSpec:
    """Qwen-Coder optimized local coding harness starting point."""
    base = coding_template(name="qwen-coding")
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": "Qwen-Coder local coding harness: low temperature, native tools.",
            "model_policy": ModelPolicySpec(
                primary="ollama/qwen3-coder",
                fallbacks=("ollama/qwen3.5", "glm-4.6"),
                profile="qwen-coding",
                pack="qwen-coder",
                temperature=0.1,
            ),
            "metadata": {"template": "qwen-coding"},
        }
    )


def glm_coding_template() -> HarnessSpec:
    """GLM optimized coding harness starting point."""
    base = coding_template(name="glm-coding")
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": "GLM local/endpoint coding harness: strong agentic coder, native tools.",
            "model_policy": ModelPolicySpec(
                primary="glm-4.6",
                fallbacks=("ollama/qwen3-coder",),
                profile="glm-coding",
                pack="glm",
                temperature=0.2,
            ),
            "metadata": {"template": "glm-coding"},
        }
    )


def glm52_coding_template() -> HarnessSpec:
    """GLM-5.2 harness for Z.AI's first-party general API."""
    base = coding_template(name="glm52-coding")
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": (
                "GLM-5.2 long-horizon coding harness via the first-party Z.AI general API."
            ),
            "model_policy": ModelPolicySpec(
                primary="zai/glm-5.2",
                fallbacks=("zai/glm-5.1", "zai/glm-5"),
                profile="glm52-coding",
                pack="glm",
                temperature=0.2,
                context_window=1_000_000,
                reasoning="max",
                config={
                    "parallel_tools": True,
                    "session_history_limit": 30,
                },
            ),
            "metadata": {
                "template": "glm52-coding",
                "provider": "zai",
                "api_endpoint": "general",
            },
        }
    )


def minimax_coding_template() -> HarnessSpec:
    """MiniMax optimized coding harness starting point."""
    base = coding_template(name="minimax-coding")
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": "MiniMax local/endpoint coding harness: long-context reasoning with measured tool behavior.",
            "model_policy": ModelPolicySpec(
                primary="minimax/minimax-m1",
                fallbacks=("ollama/qwen3-coder",),
                profile="minimax-coding",
                pack="minimax",
                temperature=0.2,
                reasoning="medium",
            ),
            "metadata": {"template": "minimax-coding"},
        }
    )


def kimi_k3_coding_template() -> HarnessSpec:
    """Frozen Kimi K3 harness retained for reproducible configurations."""
    base = coding_template(name="kimi-k3-coding")
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": (
                "Kimi K3 long-horizon coding harness with 1M context, max reasoning, "
                "native tools, and cache-friendly extended history."
            ),
            "model_policy": ModelPolicySpec(
                primary="moonshot/kimi-k3",
                fallbacks=("moonshot/kimi-k2.7-code-highspeed", "moonshot/kimi-k2.7-code"),
                profile="kimi-k3-coding",
                context_window=1_048_576,
                reasoning="max",
                config={
                    "parallel_tools": True,
                    "session_history_limit": 40,
                },
            ),
            "metadata": {
                "template": "kimi-k3-coding",
                "provider": "moonshot",
                "api_endpoint": "global",
                "automatic_context_caching": True,
                "deprecated": True,
                "replaced_by": "kimi-coding",
            },
        }
    )


def kimi_coding_template() -> HarnessSpec:
    """Stable Kimi-family coding harness maintained by SuperQode."""
    base = coding_template(name="kimi-coding")
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": (
                "Stable Kimi-family coding harness with long context, max reasoning, "
                "native tools, and cache-friendly extended history."
            ),
            "model_policy": model_policy_for_route("kimi", profile="kimi-coding"),
            "metadata": {
                "template": "kimi-coding",
                "category": "model-family",
                "provider": "moonshot",
                "route": "kimi",
                "channel": "stable",
                "api_endpoint": "global",
                "automatic_context_caching": True,
            },
        }
    )


_BENCHMARK_STANCE = """You are running unattended in a headless benchmark environment.

- There is NO user available. Never ask questions, never request confirmation, and
  never end your turn waiting for input. A response that asks a question scores zero.
- Investigate exhaustively with your tools before concluding anything is missing or
  impossible: inspect history, logs, hidden files, and recoverable state (for example
  `git reflog`, `git fsck --lost-found`, `git stash list`, backup and temp files).
- Always attempt a concrete solution and apply it with your tools. A reasonable
  attempt scores better than a perfect explanation with no changes.
- Before finishing, verify your work by running the relevant commands or tests and
  fix what fails. Finish with a short summary of what you changed."""


def benchmark_coding_template() -> HarnessSpec:
    """Coding harness tuned for unattended benchmark runs (Harbor, Terminal-Bench)."""
    base = coding_template(name="benchmark-coding")
    agents = tuple(
        AgentSpec(**{**agent.__dict__, "system_prompt": _BENCHMARK_STANCE}) for agent in base.agents
    )
    return HarnessSpec(
        **{
            **base.__dict__,
            "description": (
                "Autonomous coding harness for headless benchmark runs: never asks the "
                "user, investigates exhaustively, always attempts and verifies a fix."
            ),
            "agents": agents,
            "execution_policy": ExecutionPolicySpec(
                sandbox="local",
                approval_profile="yolo",
                allow_read=True,
                allow_write=True,
                allow_shell=True,
            ),
            "metadata": {"template": "benchmark-coding"},
        }
    )


BUILTIN_TEMPLATES = {
    "core": core_template,
    "workbench": workbench_template,
    "coding": coding_template,
    "benchmark-coding": benchmark_coding_template,
    "benchmark_coding": benchmark_coding_template,
    "no-tool": no_tool_template,
    "no_tool": no_tool_template,
    "gemma4-coding": gemma4_coding_template,
    "gemma4-no-tool": gemma4_no_tool_template,
    "gemma4-no_tool": gemma4_no_tool_template,
    "ds4-coding": ds4_coding_template,
    "ds4-fast-local": ds4_fast_local_template,
    "ds4-fast_local": ds4_fast_local_template,
    "qwen-coding": qwen_coding_template,
    "glm-coding": glm_coding_template,
    "glm52-coding": glm52_coding_template,
    "glm52_coding": glm52_coding_template,
    "minimax-coding": minimax_coding_template,
    "kimi-coding": kimi_coding_template,
    "kimi_coding": kimi_coding_template,
    "kimi-k3-coding": kimi_k3_coding_template,
    "kimi_k3_coding": kimi_k3_coding_template,
}


def get_harness_template(name: str) -> HarnessSpec:
    """Return a built-in harness template by name."""
    normalized = (name or "coding").strip().lower()
    factory = BUILTIN_TEMPLATES.get(normalized)
    if factory is None:
        valid = ", ".join(sorted(BUILTIN_TEMPLATES))
        raise ValueError(f"Unknown harness template {name!r}. Valid templates: {valid}")
    return factory()
