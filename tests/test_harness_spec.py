"""Tests for v2 harness specs and compatibility compiler."""

from pathlib import Path

import pytest

from superqode.agent.system_prompts import SystemPromptLevel
from superqode.harness import (
    HarnessFlavor,
    WorkflowMode,
    backend_capabilities,
    compile_to_headless_profile,
    get_harness_template,
    harness_spec_from_dict,
    harness_spec_to_dict,
    load_harness_spec,
    spec_from_headless_profile,
)
from superqode.tools.permissions import Permission


def test_no_tool_template_compiles_to_empty_headless_profile():
    spec = get_harness_template("no-tool")
    profile = compile_to_headless_profile(spec)

    assert spec.flavor == HarnessFlavor.NO_TOOL
    assert spec.execution_policy.allow_read is False
    assert spec.execution_policy.allow_write is False
    assert spec.execution_policy.allow_shell is False
    assert profile.system_level == SystemPromptLevel.NO_TOOL
    assert profile.tools == []
    assert profile.permissions.get_permission("read_file") == Permission.DENY
    assert profile.permissions.get_permission("bash") == Permission.DENY


def test_coding_template_compiles_to_tool_capable_profile():
    spec = get_harness_template("coding")
    profile = compile_to_headless_profile(spec)

    assert spec.flavor == HarnessFlavor.CODING
    assert spec.execution_policy.allow_read is True
    assert spec.execution_policy.allow_write is True
    assert spec.execution_policy.allow_shell is True
    assert "read_file" in profile.tools
    assert "patch" in profile.tools
    assert "bash" in profile.tools
    assert profile.permissions.get_permission("bash") == Permission.ALLOW


def test_load_embedded_harness_spec_from_yaml(tmp_path: Path):
    path = tmp_path / "superqode.yaml"
    path.write_text(
        """
superqode:
  ignored: true
harness:
  name: local-reasoner
  flavor: no-tool
  runtime:
    backend: builtin
  model_policy:
    primary: gemma4-local
    fallbacks: [ds4-local]
    temperature: 0.2
  execution_policy:
    allow_read: true
    allow_write: true
    allow_shell: true
  agents:
    - id: reasoner
      role: reasoning
      tools: [read_file]
""",
        encoding="utf-8",
    )

    spec = load_harness_spec(path)

    assert spec.name == "local-reasoner"
    assert spec.flavor == HarnessFlavor.NO_TOOL
    assert spec.model_policy.primary == "gemma4-local"
    assert spec.model_policy.fallbacks == ("ds4-local",)
    # No-tool flavor clamps execution access even if YAML asks for it.
    assert spec.execution_policy.allow_read is False
    assert spec.execution_policy.allow_write is False
    assert spec.execution_policy.allow_shell is False


def test_harness_spec_inherits_builtin_template(tmp_path: Path):
    path = tmp_path / "team.yaml"
    path.write_text(
        """
name: team-coder
inherits: coding
model_policy:
  primary: ollama/qwen3-coder
  config:
    local:
      num_ctx: 32768
execution_policy:
  config:
    local_guardrails:
      battery_mode: false
agents:
  - id: team-coder
    tools: [read_file]
metadata:
  owner: platform
""",
        encoding="utf-8",
    )

    spec = load_harness_spec(path)

    assert spec.name == "team-coder"
    assert spec.inherits == "coding"
    assert spec.execution_policy.allow_write is True
    assert spec.execution_policy.allow_shell is True
    assert spec.model_policy.primary == "ollama/qwen3-coder"
    assert spec.model_policy.config["local"]["num_ctx"] == 32768
    assert spec.execution_policy.config["local_guardrails"]["battery_mode"] is False
    assert spec.agents[0].id == "team-coder"
    assert spec.agents[0].tools == ("read_file",)
    assert spec.metadata["template"] == "coding"
    assert spec.metadata["owner"] == "platform"


def test_harness_spec_inherits_relative_file_and_detects_cycles(tmp_path: Path):
    base = tmp_path / "base.yaml"
    child = tmp_path / "child.yaml"
    base.write_text(
        """
name: base
runtime:
  backend: builtin
model_policy:
  config:
    a: 1
    nested:
      keep: true
agents:
  - id: base-agent
""",
        encoding="utf-8",
    )
    child.write_text(
        """
name: child
inherits: base.yaml
model_policy:
  config:
    nested:
      add: true
""",
        encoding="utf-8",
    )

    spec = load_harness_spec(child)

    assert spec.name == "child"
    assert spec.model_policy.config == {"a": 1, "nested": {"keep": True, "add": True}}
    assert spec.agents[0].id == "base-agent"

    base.write_text("name: base\ninherits: child.yaml\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cycle"):
        load_harness_spec(child)


def test_harness_spec_round_trip_preserves_core_fields():
    spec = harness_spec_from_dict(
        {
            "name": "team-coder",
            "flavor": "coding",
            "runtime": {"backend": "adk", "fallback_backends": ["builtin"]},
            "context": {"prompt_persistence": "full"},
            "execution_policy": {"allow_write": True, "allow_shell": True},
            "agents": [{"id": "coder", "tools": ["read_file", "bash"]}],
            "checks": {
                "enabled": True,
                "custom_steps": [{"name": "tests", "command": "pytest -q", "timeout": 120}],
            },
        }
    )

    payload = harness_spec_to_dict(spec)
    restored = harness_spec_from_dict(payload)

    assert restored.name == "team-coder"
    assert restored.runtime.backend == "adk"
    assert restored.runtime.fallback_backends == ("builtin",)
    assert restored.context.prompt_persistence == "full"
    assert restored.execution_policy.allow_write is True
    assert restored.execution_policy.allow_shell is True
    assert restored.agents[0].tools == ("read_file", "bash")
    assert restored.checks.enabled is True
    assert restored.checks.custom_steps[0].command == "pytest -q"


def test_harness_spec_round_trip_preserves_recursion_and_remote_harness():
    spec = harness_spec_from_dict(
        {
            "name": "recursive-local",
            "recursion": {
                "enabled": True,
                "max_depth": 2,
                "max_children": 4,
                "max_parallel": 2,
                "max_wall_seconds": 300,
                "max_budget": 1.25,
                "child_model": "utility-coder",
                "child_sandbox": "docker",
                "write_policy": "deny",
            },
            "remote_harness": {
                "enabled": True,
                "provider": "google-agent-engine",
                "agent_id": "agent-123",
                "region": "us-central1",
                "context_policy": "selected-files",
            },
        }
    )

    payload = harness_spec_to_dict(spec)
    restored = harness_spec_from_dict(payload)

    assert restored.recursion.enabled is True
    assert restored.recursion.max_depth == 2
    assert restored.recursion.max_children == 4
    assert restored.recursion.max_budget == 1.25
    assert restored.recursion.child_model == "utility-coder"
    assert restored.recursion.child_sandbox == "docker"
    assert restored.recursion.write_policy == "deny"
    assert restored.remote_harness.enabled is True
    assert restored.remote_harness.provider == "google-agent-engine"
    assert restored.remote_harness.agent_id == "agent-123"
    assert restored.remote_harness.region == "us-central1"


def test_harness_spec_round_trip_preserves_observability_exporters():
    spec = harness_spec_from_dict(
        {
            "name": "observable-local",
            "observability": {
                "events": True,
                "traces": True,
                "local": True,
                "run_store": "file",
                "exporters": [
                    {"type": "mlflow", "enabled": True, "experiment": "sq-test"},
                    {"type": "langsmith", "enabled": False},
                ],
                "config": {"mlflow_tracking_uri": "file:/tmp/mlruns"},
            },
        }
    )

    payload = harness_spec_to_dict(spec)
    restored = harness_spec_from_dict(payload)

    assert restored.observability.traces is True
    assert restored.observability.local is True
    assert restored.observability.run_store == "file"
    assert restored.observability.exporters[0]["type"] == "mlflow"
    assert restored.observability.exporters[0]["experiment"] == "sq-test"
    assert restored.observability.config["mlflow_tracking_uri"] == "file:/tmp/mlruns"


def test_harness_spec_round_trip_preserves_optimization_policy():
    spec = harness_spec_from_dict(
        {
            "name": "self-improving",
            "optimization": {
                "enabled": True,
                "require_human_apply": True,
                "editable_surfaces": ["context", "workflow"],
                "protected_surfaces": ["execution_policy", "checks"],
                "heldout_fraction": 0.25,
                "max_candidate_edits": 3,
                "config": {"novelty_gate": True},
            },
        }
    )

    payload = harness_spec_to_dict(spec)
    restored = harness_spec_from_dict(payload)

    assert payload["optimization"]["enabled"] is True
    assert restored.optimization.enabled is True
    assert restored.optimization.editable_surfaces == ("context", "workflow")
    assert restored.optimization.protected_surfaces == ("execution_policy", "checks")
    assert restored.optimization.heldout_fraction == 0.25
    assert restored.optimization.max_candidate_edits == 3
    assert restored.optimization.config["novelty_gate"] is True


def test_harness_spec_schema_includes_optimization_policy():
    from superqode.harness import harness_spec_json_schema

    schema = harness_spec_json_schema()

    assert "optimization" in schema["properties"]
    assert "editable_surfaces" in schema["properties"]["optimization"]["properties"]


def test_workflow_preset_expands_harness_agents_and_mode():
    spec = harness_spec_from_dict(
        {
            "name": "review-harness",
            "workflow": {"preset": "parallel-review"},
        }
    )

    assert spec.workflow.preset == "parallel-review"
    assert spec.workflow.mode == WorkflowMode.ORCHESTRATOR
    assert spec.workflow.parallelism == 3
    assert [agent.id for agent in spec.agents] == ["security", "tests", "architecture"]

    payload = harness_spec_to_dict(spec)
    assert payload["workflow"]["preset"] == "parallel-review"


def test_managed_agent_backend_capability_scaffolds_are_known():
    google = backend_capabilities("google-agent-engine")
    anthropic = backend_capabilities("anthropic-managed")

    assert google.backend == "google-agent-engine"
    assert google.availability in {"needs-config", "configured"}
    assert google.supports_sandbox is True
    assert anthropic.backend == "anthropic-managed"
    assert anthropic.availability in {"needs-config", "configured"}


@pytest.mark.parametrize("profile_name", ["build", "plan", "review", "no-tool"])
def test_existing_headless_profiles_have_spec_equivalents(profile_name: str):
    spec = spec_from_headless_profile(profile_name)

    assert spec.name == profile_name
    if profile_name == "no-tool":
        assert spec.flavor == HarnessFlavor.NO_TOOL
        assert spec.agents[0].tools == ()
    else:
        assert spec.flavor == HarnessFlavor.CODING
