from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from superqode.harness import (
    WorkflowMode,
    agent_yaml_to_harness_spec,
    import_agent_yaml,
    load_harness_spec,
)
from superqode.main import cli_main


def test_agent_yaml_to_harness_spec_compiles_concise_authoring_shape():
    spec = agent_yaml_to_harness_spec(
        {
            "name": "coding_supervisor",
            "prompt": "Coordinate the work.",
            "skills": ["code-review"],
            "executor": {
                "harness": "codex",
                "model": "databricks-gpt-5-5",
                "auth": {"type": "databricks", "profile": "oss"},
            },
            "tools": {
                "github": {
                    "type": "mcp",
                    "command": "uvx",
                    "args": ["github-mcp-server"],
                    "tools": ["search_issues"],
                },
                "reviewer": {
                    "type": "agent",
                    "description": "Review proposed changes.",
                    "prompt": "Focus on correctness and tests.",
                    "executor": {"harness": "claude-sdk", "model": "claude-sonnet"},
                    "max_sessions": 2,
                },
            },
        }
    )

    assert spec.name == "coding_supervisor"
    assert spec.runtime.backend == "codex-sdk"
    assert spec.runtime.config["agent_harness"] == "codex"
    assert spec.runtime.config["mcp_servers"]["github"]["command"] == "uvx"
    assert spec.model_policy.profile == "oss"
    assert spec.agents[0].tools == ("github",)
    assert spec.agents[0].skills == ("code-review",)
    assert spec.agents[0].delegates_to == ("reviewer",)
    assert spec.agents[0].config["source"] == "superqode-agent"
    assert spec.agents[0].config["agent_tools"]["github"]["tools"] == ["search_issues"]
    assert spec.agents[1].id == "reviewer"
    assert spec.agents[1].config["source"] == "superqode-agent"
    assert spec.workflow.mode == WorkflowMode.ORCHESTRATOR
    assert spec.metadata["source"] == "superqode-agent"
    assert spec.metadata["agent"]["name"] == "coding_supervisor"


def test_import_agent_yaml_writes_loadable_harness(tmp_path: Path):
    source = tmp_path / "agent.yaml"
    output = tmp_path / "harness.yaml"
    source.write_text(
        """
name: hello_agent
prompt: Hello.
executor:
  harness: open-responses
  model: databricks-gpt-5-5
""",
        encoding="utf-8",
    )

    written = import_agent_yaml(source, output=output, name="hello-harness")
    restored = load_harness_spec(written)

    assert written == output
    assert restored.name == "hello-harness"
    assert restored.runtime.backend == "openai-agents"
    assert restored.metadata["agent"]["source_path"] == str(source)


def test_harness_import_agent_cli_writes_with_force(tmp_path: Path):
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
            "import-agent",
            str(source),
            "--output",
            str(output),
            "--force",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Imported SuperQode agent" in result.output
    assert load_harness_spec(output).runtime.backend == "claude-agent-sdk"
