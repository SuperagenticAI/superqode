from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from superqode.harness import HarnessFlavor, WorkflowMode, load_harness_spec
from superqode.harness.omnigent_importer import (
    import_omnigent_agent,
    omnigent_agent_to_harness_spec,
)
from superqode.main import cli_main


def test_omnigent_agent_to_harness_spec_maps_core_fields():
    spec = omnigent_agent_to_harness_spec(
        {
            "name": "coding_agent",
            "prompt": "You are careful.",
            "executor": {
                "harness": "claude-sdk",
                "model": "databricks-claude-sonnet-4-6",
                "auth": {"type": "databricks", "profile": "oss"},
            },
            "os_env": {
                "type": "caller_process",
                "cwd": ".",
                "sandbox": {
                    "type": "linux_bwrap",
                    "write_paths": ["."],
                    "allow_network": True,
                },
            },
            "tools": {
                "repo_search": {
                    "type": "function",
                    "callable": "my_package.tools.repo_search",
                },
                "reviewer": {
                    "type": "agent",
                    "description": "Review code.",
                    "prompt": "Review proposed code changes.",
                    "executor": {
                        "harness": "codex",
                        "model": "gpt-5.1-codex",
                    },
                    "pass_history": True,
                    "max_sessions": 2,
                },
            },
            "policies": {
                "approve_shell": {
                    "type": "function",
                    "handler": "my.policies.ask_on_shell",
                }
            },
        }
    )

    assert spec.name == "coding_agent"
    assert spec.flavor == HarnessFlavor.CODING
    assert spec.runtime.backend == "claude-agent-sdk"
    assert spec.model_policy.primary == "databricks-claude-sonnet-4-6"
    assert spec.model_policy.config["auth"]["profile"] == "oss"
    assert spec.execution_policy.allow_read is True
    assert spec.execution_policy.allow_write is True
    assert spec.execution_policy.allow_shell is True
    assert spec.execution_policy.allow_network is True
    assert spec.agents[0].system_prompt == "You are careful."
    assert spec.agents[0].tools == ("repo_search",)
    assert spec.agents[0].delegates_to == ("reviewer",)
    assert spec.agents[1].id == "reviewer"
    assert spec.agents[1].model == "gpt-5.1-codex"
    assert spec.agents[1].max_iterations == 2
    assert spec.workflow.mode == WorkflowMode.ORCHESTRATOR
    assert spec.metadata["omnigent"]["policies"]["approve_shell"]["handler"] == (
        "my.policies.ask_on_shell"
    )


def test_omnigent_importer_preserves_instruction_file_reference(tmp_path: Path):
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "AGENTS.md").write_text("Imported instructions", encoding="utf-8")
    agent_yaml.write_text(
        """
name: docs_agent
instructions: AGENTS.md
executor:
  harness: openai-agents
  model: gpt-5.1
""",
        encoding="utf-8",
    )

    spec = import_omnigent_agent(agent_yaml)

    assert not isinstance(spec, Path)
    assert spec.runtime.backend == "openai-agents"
    assert spec.context.instruction_files == ("AGENTS.md",)
    assert spec.agents[0].system_prompt is None


def test_import_omnigent_agent_writes_loadable_harness(tmp_path: Path):
    source = tmp_path / "agent.yaml"
    output = tmp_path / "harness.yaml"
    source.write_text(
        """
name: hello_agent
prompt: Hello.
executor:
  harness: codex
  model: gpt-5.1-codex
tools:
  summarize_file:
    type: function
    callable: my.tools.summarize
""",
        encoding="utf-8",
    )

    written = import_omnigent_agent(source, output=output, name="hello-superqode")
    restored = load_harness_spec(written)

    assert written == output
    assert restored.name == "hello-superqode"
    assert restored.runtime.backend == "codex-sdk"
    assert restored.agents[0].tools == ("summarize_file",)
    assert restored.metadata["omnigent"]["source_path"] == str(source)


def test_harness_import_omnigent_cli_refuses_overwrite(tmp_path: Path):
    source = tmp_path / "agent.yaml"
    output = tmp_path / "harness.yaml"
    source.write_text("name: cli_agent\nprompt: Hello.\n", encoding="utf-8")
    output.write_text("existing", encoding="utf-8")

    result = CliRunner().invoke(
        cli_main,
        ["harness", "import-omnigent", str(source), "--output", str(output)],
    )

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_harness_import_omnigent_cli_writes_with_force(tmp_path: Path):
    source = tmp_path / "agent.yaml"
    output = tmp_path / "harness.yaml"
    source.write_text(
        """
name: cli_agent
prompt: Hello.
executor:
  harness: claude-sdk
  model: claude-sonnet
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli_main,
        [
            "harness",
            "import-omnigent",
            str(source),
            "--output",
            str(output),
            "--force",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Imported Omnigent agent" in result.output
    assert load_harness_spec(output).runtime.backend == "claude-agent-sdk"
