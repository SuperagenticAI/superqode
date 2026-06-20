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


def test_omnigent_importer_maps_current_mcp_skills_and_legacy_profile():
    spec = omnigent_agent_to_harness_spec(
        {
            "name": "current_agent",
            "prompt": "Use the declared tools.",
            "skills": ["claude-api", "mlflow-onboarding"],
            "executor": {
                "harness": "open-responses",
                "model": "databricks-gpt-5-5",
                "profile": "legacy-profile",
            },
            "tools": {
                "docs": {
                    "type": "mcp",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer ${TOKEN}"},
                    "tools": ["search_docs"],
                },
                "open_in_editor": {
                    "type": "function",
                    "runtime": "client",
                    "description": "Open a file in the user's editor.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            },
        }
    )

    assert spec.runtime.backend == "openai-agents"
    assert spec.runtime.config["mcp_servers"]["docs"]["url"] == "https://example.com/mcp"
    assert spec.model_policy.profile == "legacy-profile"
    assert spec.model_policy.config["legacy_executor_profile"] == "legacy-profile"
    assert spec.agents[0].tools == ("docs", "open_in_editor")
    assert spec.agents[0].skills == ("claude-api", "mlflow-onboarding")
    assert spec.agents[0].config["skills_filter"] == ["claude-api", "mlflow-onboarding"]
    assert spec.agents[0].config["mcp_servers"]["docs"]["tools"] == ["search_docs"]
    assert spec.metadata["omnigent"]["skills"] == ["claude-api", "mlflow-onboarding"]


def test_omnigent_importer_preserves_newer_sandbox_controls():
    spec = omnigent_agent_to_harness_spec(
        {
            "name": "sandbox_agent",
            "prompt": "Inspect files safely.",
            "executor": {"model": "databricks-gpt-5-4-mini"},
            "os_env": {
                "type": "caller_process",
                "cwd": ".",
                "sandbox": {
                    "type": "darwin_seatbelt",
                    "read_paths": ["/opt/reference"],
                    "env_passthrough": ["AWS_PROFILE"],
                    "egress_rules": ["GET httpbin.org/get"],
                },
            },
        }
    )

    assert spec.execution_policy.allow_read is True
    assert spec.execution_policy.allow_write is False
    assert spec.execution_policy.allow_shell is True
    assert spec.execution_policy.allow_network is True
    assert spec.execution_policy.config["omnigent_sandbox"]["egress_rules"] == [
        "GET httpbin.org/get"
    ]


def test_omnigent_importer_preserves_richer_agent_tool_config(tmp_path: Path):
    (tmp_path / "WORKER.md").write_text("Worker instructions", encoding="utf-8")

    spec = omnigent_agent_to_harness_spec(
        {
            "name": "supervisor",
            "prompt": "Coordinate specialists.",
            "executor": {"model": "parent-model"},
            "tools": {
                "search_web": {
                    "type": "function",
                    "callable": "tools.search_web",
                },
                "worker": {
                    "type": "agent",
                    "description": "Investigate and implement.",
                    "instructions": "WORKER.md",
                    "executor": {
                        "harness": "open-responses",
                        "model": "child-model",
                        "auth": {"type": "databricks", "profile": "child-profile"},
                        "base_url": "https://example.cloud.databricks.com",
                        "reasoning": "high",
                        "temperature": 0.2,
                        "context_window": 200000,
                    },
                    "skills": "none",
                    "max_iterations": 7,
                    "pass_history": True,
                    "os_env": {
                        "type": "caller_process",
                        "fork": True,
                        "sandbox": {"type": "none"},
                    },
                    "tools": {
                        "search_web": "inherit",
                        "docs": {
                            "type": "mcp",
                            "url": "https://example.com/mcp",
                            "tools": ["lookup"],
                        },
                    },
                    "output_schema": {
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                    "policies": {
                        "gate_shell": {
                            "type": "function",
                            "handler": "policies.gate_shell",
                        }
                    },
                },
            },
        },
        source_path=tmp_path / "agent.yaml",
    )

    worker = spec.agents[1]
    assert worker.id == "worker"
    assert worker.model == "child-model"
    assert worker.system_prompt is None
    assert worker.tools == ("search_web", "docs")
    assert worker.skills == ()
    assert worker.max_iterations == 7
    assert worker.output_schema == {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    }
    assert worker.config["executor_harness"] == "open-responses"
    assert worker.config["runtime_backend"] == "openai-agents"
    assert worker.config["model_profile"] == "child-profile"
    assert worker.config["model_config"]["auth"]["profile"] == "child-profile"
    assert worker.config["model_config"]["base_url"] == "https://example.cloud.databricks.com"
    assert worker.config["model_config"]["reasoning"] == "high"
    assert worker.config["model_config"]["temperature"] == 0.2
    assert worker.config["model_config"]["context_window"] == 200000
    assert worker.config["pass_history"] is True
    assert worker.config["os_env"]["fork"] is True
    assert worker.config["instruction_files"] == ("WORKER.md",)
    assert worker.config["omnigent_tools"]["search_web"] == "inherit"
    assert worker.config["mcp_servers"]["docs"]["url"] == "https://example.com/mcp"
    assert worker.config["skills_filter"] == "none"
    assert worker.config["omnigent"]["policies"]["gate_shell"]["handler"] == "policies.gate_shell"


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
