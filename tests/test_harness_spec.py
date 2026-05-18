"""Tests for v2 harness specs and compatibility compiler."""

from pathlib import Path

import pytest

from superqode.agent.system_prompts import SystemPromptLevel
from superqode.harness import (
    HarnessFlavor,
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


def test_harness_spec_round_trip_preserves_core_fields():
    spec = harness_spec_from_dict(
        {
            "name": "team-coder",
            "flavor": "coding",
            "runtime": {"backend": "adk", "fallback_backends": ["builtin"]},
            "execution_policy": {"allow_write": True, "allow_shell": True},
            "agents": [{"id": "coder", "tools": ["read_file", "bash"]}],
            "validation": {
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
    assert restored.execution_policy.allow_write is True
    assert restored.execution_policy.allow_shell is True
    assert restored.agents[0].tools == ("read_file", "bash")
    assert restored.validation.enabled is True
    assert restored.validation.custom_steps[0].command == "pytest -q"


@pytest.mark.parametrize("profile_name", ["build", "plan", "review", "no-tool"])
def test_existing_headless_profiles_have_spec_equivalents(profile_name: str):
    spec = spec_from_headless_profile(profile_name)

    assert spec.name == profile_name
    if profile_name == "no-tool":
        assert spec.flavor == HarnessFlavor.NO_TOOL
        assert spec.agents[0].tools == ()
    else:
        assert spec.flavor == HarnessFlavor.CODING
