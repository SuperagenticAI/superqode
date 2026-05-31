"""
Tests for SuperQode CLI Commands.

Tests the command-line interface functionality.
"""

import json
import pytest
from click.testing import CliRunner
from pathlib import Path
from unittest.mock import patch, MagicMock
from contextlib import contextmanager

from superqode.agent.loop import AgentResponse
from superqode.main import cli_main


@pytest.fixture
def runner():
    """Create a CLI test runner."""
    return CliRunner()


class TestCLIVersion:
    """Tests for version command."""

    def test_version_flag(self, runner):
        """Test --version flag."""
        result = runner.invoke(cli_main, ["--version"])

        assert result.exit_code == 0
        assert "0.1.0" in result.output or "version" in result.output.lower()


class TestCLIHelp:
    """Tests for help command."""

    def test_help_flag(self, runner):
        """Test --help flag."""
        result = runner.invoke(cli_main, ["--help"])

        assert result.exit_code == 0
        assert "Usage:" in result.output or "SuperQode" in result.output

    def test_agents_help(self, runner):
        """Test agents command help."""
        result = runner.invoke(cli_main, ["agents", "--help"])

        assert result.exit_code == 0
        assert "agents" in result.output.lower() or "acp" in result.output.lower()

    def test_providers_help(self, runner):
        """Test providers command help."""
        result = runner.invoke(cli_main, ["providers", "--help"])

        assert result.exit_code == 0
        assert "providers" in result.output.lower()

    def test_doctor_json(self, runner):
        """Doctor should show basic developer setup state."""
        result = runner.invoke(cli_main, ["doctor", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["version"]
        assert "providers" in payload
        assert "recommended_models" in payload
        assert "superqode" in payload["next_steps"][0]


class TestHarnessCommand:
    """Tests for HarnessSpec CLI commands."""

    def test_harness_help(self, runner):
        result = runner.invoke(cli_main, ["harness", "--help"])

        assert result.exit_code == 0
        assert "list-backends" in result.output
        assert "list-templates" in result.output
        assert "validate" in result.output
        assert "inspect" in result.output
        assert "compile" in result.output
        assert "diff" in result.output
        assert "doctor" in result.output
        assert "run" in result.output
        assert "replay" in result.output
        assert "fork" in result.output

    def test_harness_list_backends_json(self, runner):
        result = runner.invoke(cli_main, ["harness", "list-backends", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        by_backend = {item["backend"]: item for item in payload}
        assert by_backend["builtin"]["availability"] == "available"
        assert by_backend["openai-agents"]["supports_approvals"] is True
        assert "install_hint" in by_backend["deepagents"]

    def test_harness_list_templates_json(self, runner):
        result = runner.invoke(cli_main, ["harness", "list-templates", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        names = {item["name"] for item in payload}
        assert {"coding", "no-tool", "gemma4-coding"} <= names
        descriptions = {item["name"]: item["description"] for item in payload}
        assert descriptions["coding"] != descriptions["gemma4-coding"]
        assert descriptions["coding"] != descriptions["ds4-coding"]

    def test_harness_init_and_validate(self, runner):
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli_main,
                ["harness", "init", "demo", "--template", "no-tool", "--output", "harness.yaml"],
            )

            assert result.exit_code == 0
            assert Path("harness.yaml").exists()
            assert Path(".agents/skills").is_dir()

            validate = runner.invoke(cli_main, ["harness", "validate", "harness.yaml", "--json"])
            assert validate.exit_code == 0
            payload = json.loads(validate.output)
            assert payload["valid"] is True
            assert payload["name"] == "demo"
            assert payload["flavor"] == "no_tool"

            validate_option = runner.invoke(
                cli_main,
                ["harness", "validate", "--spec", "harness.yaml", "--json"],
            )
            assert validate_option.exit_code == 0
            option_payload = json.loads(validate_option.output)
            assert option_payload["valid"] is True
            assert option_payload["name"] == "demo"

            schema = runner.invoke(cli_main, ["harness", "validate", "harness.yaml", "--schema"])
            assert schema.exit_code == 0
            schema_payload = json.loads(schema.output)
            assert schema_payload["title"] == "SuperQode HarnessSpec"
            assert "flavor" in schema_payload["properties"]

    def test_harness_inspect_json_reports_backend_capabilities(self, runner):
        with runner.isolated_filesystem():
            init = runner.invoke(
                cli_main,
                ["harness", "init", "demo", "--template", "no-tool", "--output", "harness.yaml"],
            )
            assert init.exit_code == 0

            result = runner.invoke(
                cli_main,
                [
                    "harness",
                    "inspect",
                    "--spec",
                    "harness.yaml",
                    "--runtime",
                    "deepagents",
                    "--json",
                ],
            )

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["name"] == "demo"
            assert payload["backend"]["ok"] is False
            assert payload["backend"]["issues"][0]["code"] == "no_tool_unsupported"
            assert payload["backend"]["capabilities"]["supports_no_tool"] is False
            assert payload["runtime_details"]["backend"] == "deepagents"
            assert payload["workflow_details"]["mode"] == "single"

    def test_harness_doctor_json_reports_readiness(self, runner):
        with runner.isolated_filesystem():
            init = runner.invoke(
                cli_main,
                ["harness", "init", "demo", "--template", "no-tool", "--output", "harness.yaml"],
            )
            assert init.exit_code == 0

            result = runner.invoke(
                cli_main,
                [
                    "harness",
                    "doctor",
                    "--spec",
                    "harness.yaml",
                    "--runtime",
                    "builtin",
                    "--json",
                ],
            )

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["name"] == "demo"
            assert payload["runtime"] == "builtin"
            by_check = {check["name"]: check for check in payload["checks"]}
            assert by_check["spec"]["status"] == "ok"
            assert by_check["backend"]["status"] == "ok"
            assert by_check["event_store"]["graph"] is True
            assert by_check["event_graph"]["rich_events"] is True
            assert by_check["model_registry"]["status"] == "ok"
            assert by_check["model_registry"]["unknown_models"] == []
            assert payload["ready"] is True
            assert payload["summary"]["checks"] == len(payload["checks"])
            assert by_check["spec"]["severity"] == "info"

    def test_harness_doctor_json_blocks_unknown_provider(self, runner):
        with runner.isolated_filesystem():
            Path("harness.yaml").write_text(
                """
name: demo
model_policy:
  primary: demo-model
  config:
    provider: missing-provider
""".strip()
                + "\n",
                encoding="utf-8",
            )

            result = runner.invoke(
                cli_main,
                ["harness", "doctor", "--spec", "harness.yaml", "--json"],
            )

            assert result.exit_code == 1
            payload = json.loads(result.output)
            assert payload["ready"] is False
            assert payload["summary"]["blockers"] >= 1
            model_check = next(check for check in payload["checks"] if check["name"] == "model_registry")
            assert model_check["status"] == "error"
            assert model_check["severity"] == "blocker"
            assert "missing-provider" in model_check["errors"][0]
            assert "fix" in model_check

    def test_harness_doctor_json_blocks_invalid_mcp_config(self, runner):
        with runner.isolated_filesystem():
            Path(".superqode").mkdir()
            Path(".superqode/mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "missing": {
                                "command": "definitely-missing-superqode-mcp-server",
                                "args": [],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            Path("harness.yaml").write_text(
                """
name: demo
runtime:
  backend: builtin
  config:
    mcp_config_path: .superqode/mcp.json
""".strip()
                + "\n",
                encoding="utf-8",
            )

            result = runner.invoke(
                cli_main,
                ["harness", "doctor", "--spec", "harness.yaml", "--json"],
            )

            assert result.exit_code == 1
            payload = json.loads(result.output)
            mcp_check = next(check for check in payload["checks"] if check["name"] == "mcp")
            assert mcp_check["status"] == "error"
            assert mcp_check["severity"] == "blocker"
            assert "missing" in mcp_check["servers"]
            assert mcp_check["errors"]

    def test_harness_doctor_json_blocks_missing_validation_command(self, runner):
        with runner.isolated_filesystem():
            Path("harness.yaml").write_text(
                """
name: demo
validation:
  enabled: true
  custom_steps:
    - name: missing-validator
      command: definitely-missing-superqode-validator --check
""".strip()
                + "\n",
                encoding="utf-8",
            )

            result = runner.invoke(
                cli_main,
                ["harness", "doctor", "--spec", "harness.yaml", "--json"],
            )

            assert result.exit_code == 1
            payload = json.loads(result.output)
            validation_check = next(check for check in payload["checks"] if check["name"] == "validation")
            assert validation_check["status"] == "error"
            assert validation_check["missing"] == ["missing-validator"]
            assert "fix" in validation_check

    def test_harness_graph_spec_json_reports_planned_workflow(self, runner):
        with runner.isolated_filesystem():
            init = runner.invoke(
                cli_main,
                ["harness", "init", "demo", "--template", "coding", "--output", "harness.yaml"],
            )
            assert init.exit_code == 0

            result = runner.invoke(
                cli_main,
                ["harness", "graph", "--spec", "harness.yaml", "--json"],
            )

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["run_id"] == "planned"
            labels = [node["label"] for node in payload["nodes"]]
            assert labels == ["coder"]

    def test_harness_runs_json_lists_file_store_runs(self, runner):
        from superqode.harness import FileHarnessStore, HarnessEvent, get_harness_template

        with runner.isolated_filesystem():
            store = FileHarnessStore(".superqode/sessions")
            spec = get_harness_template("no-tool")
            store.open_session("session-1", spec)
            run = store.start_run(
                session_id="session-1",
                spec=spec,
                provider="test",
                model="model",
                runtime="builtin",
                prompt="parent workflow",
                metadata={"workflow": True},
            )
            store.append_event(run.run_id, HarnessEvent(type="workflow.run.started", run_id=run.run_id))

            result = runner.invoke(cli_main, ["harness", "runs", "--json"])

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload[0]["run_id"] == run.run_id
            assert payload[0]["metadata"]["workflow"] is True

    def test_harness_evidence_json_reports_run_receipt(self, runner):
        from superqode.harness import FileHarnessStore, HarnessEvent, get_harness_template

        with runner.isolated_filesystem():
            store = FileHarnessStore(".superqode/sessions")
            spec = get_harness_template("no-tool")
            store.open_session("session-1", spec)
            run = store.start_run(
                session_id="session-1",
                spec=spec,
                provider="test",
                model="model",
                runtime="builtin",
                prompt="parent workflow",
                metadata={
                    "workflow": True,
                    "workflow_mode": "single",
                    "changed_files": {"file_count": 0, "additions": 0, "deletions": 0, "files": []},
                    "validation": {"enabled": True, "status": "passed", "steps": []},
                },
            )
            store.append_event(
                run.run_id,
                HarnessEvent(type="workflow.run.started", run_id=run.run_id, data={"mode": "single"}),
            )
            store.append_event(
                run.run_id,
                HarnessEvent(type="workflow.step.completed", run_id=run.run_id, data={"step_id": "coder", "child_run_id": "run_child"}),
            )
            store.append_event(
                run.run_id,
                HarnessEvent(type="workspace.changes.captured", run_id=run.run_id, data={"file_count": 0, "additions": 0, "deletions": 0, "files": []}),
            )
            store.append_event(
                run.run_id,
                HarnessEvent(type="workflow.result", run_id=run.run_id, data={"status": "succeeded", "content_preview": "done", "result_count": 1}),
            )
            store.end_run(run.run_id, status="succeeded", metadata={"workflow": True})

            result = runner.invoke(cli_main, ["harness", "evidence", run.run_id, "--json"])

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["run"]["run_id"] == run.run_id
            assert payload["workflow"]["child_run_ids"] == ["run_child"]
            assert payload["changes"]["file_count"] == 0
            assert payload["result"]["content_preview"] == "done"
            assert payload["commands"]["graph"].endswith(run.run_id)

    def test_harness_replay_json_reports_replay_plan(self, runner):
        from superqode.harness import FileHarnessStore, HarnessEvent, get_harness_template

        with runner.isolated_filesystem():
            store = FileHarnessStore(".superqode/sessions")
            spec = get_harness_template("no-tool")
            store.open_session("session-1", spec)
            run = store.start_run(
                session_id="session-1",
                spec=spec,
                provider="test",
                model="model",
                runtime="builtin",
                prompt="replay workflow",
            )
            store.append_event(run.run_id, HarnessEvent(type="run_start", run_id=run.run_id))
            store.append_event(
                run.run_id,
                HarnessEvent(type="run_end", run_id=run.run_id, data={"status": "succeeded"}),
            )
            store.end_run(run.run_id, status="succeeded")

            result = runner.invoke(cli_main, ["harness", "replay", run.run_id, "--json"])

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["run"]["run_id"] == run.run_id
            assert payload["events"]["count"] == 2
            assert payload["terminal"]["type"] == "run_end"
            assert payload["replayable"] is False
            assert payload["commands"]["fork"].endswith(run.run_id)

    def test_harness_replay_json_reports_full_prompt_replayable(self, runner):
        from superqode.harness import ContextSpec, FileHarnessStore, HarnessSpec

        with runner.isolated_filesystem():
            spec = HarnessSpec(
                name="prompt-full",
                context=ContextSpec(session_storage=".superqode/sessions", prompt_persistence="full"),
            )
            store = FileHarnessStore(".superqode/sessions")
            store.open_session("session-1", spec)
            run = store.start_run(
                session_id="session-1",
                spec=spec,
                provider="test",
                model="model",
                runtime="builtin",
                prompt="exact replay prompt",
            )

            result = runner.invoke(cli_main, ["harness", "replay", run.run_id, "--json"])

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["replayable"] is True
            assert payload["prompt"] == "exact replay prompt"
            assert payload["run"]["has_full_prompt"] is True

    def test_harness_replay_execute_requires_prompt_or_full_persistence(self, runner):
        from superqode.harness import FileHarnessStore, get_harness_template

        with runner.isolated_filesystem():
            init = runner.invoke(
                cli_main,
                ["harness", "init", "demo", "--template", "no-tool", "--output", "harness.yaml"],
            )
            assert init.exit_code == 0
            store = FileHarnessStore(".superqode/sessions")
            spec = get_harness_template("no-tool")
            store.open_session("session-1", spec)
            run = store.start_run(
                session_id="session-1",
                spec=spec,
                provider="test",
                model="model",
                runtime="builtin",
                prompt="preview only",
            )

            result = runner.invoke(
                cli_main,
                ["harness", "replay", run.run_id, "--execute", "--spec", "harness.yaml"],
            )

            assert result.exit_code != 0
            assert "No full prompt is stored" in result.output

    def test_harness_fork_json_creates_lineage_run(self, runner):
        from superqode.harness import FileHarnessStore, HarnessEvent, get_harness_template

        with runner.isolated_filesystem():
            store = FileHarnessStore(".superqode/sessions")
            spec = get_harness_template("no-tool")
            store.open_session("session-1", spec)
            run = store.start_run(
                session_id="session-1",
                spec=spec,
                provider="test",
                model="model",
                runtime="builtin",
                prompt="fork workflow",
            )
            store.append_event(run.run_id, HarnessEvent(type="run_start", run_id=run.run_id))
            store.append_event(run.run_id, HarnessEvent(type="tool_call", run_id=run.run_id))

            result = runner.invoke(
                cli_main,
                ["harness", "fork", run.run_id, "--after", "0", "--session", "fork-s", "--json"],
            )

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["fork_of"] == run.run_id
            assert payload["fork_after"] == 0
            assert payload["session_id"] == "fork-s"
            assert payload["events"] == 1
            forked = store.get_run(payload["run_id"])
            assert forked is not None
            assert forked.events[0].type == "run_start"

    def test_harness_compile_json_reports_effective_policy(self, runner):
        with runner.isolated_filesystem():
            init = runner.invoke(
                cli_main,
                ["harness", "init", "demo", "--template", "no-tool", "--output", "harness.yaml"],
            )
            assert init.exit_code == 0

            result = runner.invoke(
                cli_main,
                ["harness", "compile", "--spec", "harness.yaml", "--json"],
            )

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["spec"]["name"] == "demo"
            assert payload["effective_model_policy"]["system_level"] == "no_tool"
            assert payload["headless_profile"]["permissions"]["default"] == "deny"

    def test_harness_diff_json_reports_changes(self, runner):
        with runner.isolated_filesystem():
            left = runner.invoke(
                cli_main,
                ["harness", "init", "left", "--template", "no-tool", "--output", "left.yaml"],
            )
            assert left.exit_code == 0
            right = runner.invoke(
                cli_main,
                ["harness", "init", "right", "--template", "coding", "--output", "right.yaml"],
            )
            assert right.exit_code == 0

            result = runner.invoke(
                cli_main,
                ["harness", "diff", "left.yaml", "right.yaml", "--json"],
            )

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["changed"] is True
            paths = {change["path"] for change in payload["changes"]}
            assert "flavor" in paths
            assert any(path.startswith("agents.") for path in paths)

    def test_harness_init_help_lists_templates_and_accepts_ds4_fast_local(self, runner):
        help_result = runner.invoke(cli_main, ["harness", "init", "--help"])
        assert help_result.exit_code == 0
        assert "ds4-fast-local" in help_result.output
        assert "gemma4-coding" in help_result.output
        assert "--preset" in help_result.output
        assert "fix-and-verify" in help_result.output

        with runner.isolated_filesystem():
            result = runner.invoke(
                cli_main,
                [
                    "harness",
                    "init",
                    "demo",
                    "--template",
                    "ds4-fast-local",
                    "--output",
                    "harness.yaml",
                ],
            )

            assert result.exit_code == 0
            validate = runner.invoke(
                cli_main,
                ["harness", "validate", "--spec", "harness.yaml", "--json"],
            )
            assert validate.exit_code == 0
            payload = json.loads(validate.output)
            assert payload["valid"] is True
            assert payload["spec"]["model_policy"]["primary"].endswith("-local")

    def test_harness_init_applies_workflow_preset(self, runner):
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli_main,
                [
                    "harness",
                    "init",
                    "team-agent",
                    "--preset",
                    "fix-and-verify",
                    "--output",
                    "harness.yaml",
                ],
            )

            assert result.exit_code == 0
            assert "Applied workflow preset: fix-and-verify" in result.output

            validate = runner.invoke(
                cli_main,
                ["harness", "validate", "--spec", "harness.yaml", "--json"],
            )
            assert validate.exit_code == 0
            payload = json.loads(validate.output)
            spec = payload["spec"]
            assert spec["name"] == "team-agent"
            assert spec["workflow"]["preset"] == "fix-and-verify"
            assert spec["workflow"]["mode"] == "chain"
            assert [agent["id"] for agent in spec["agents"]] == [
                "planner",
                "implementer",
                "verifier",
            ]
            assert "read_file" in spec["agents"][0]["tools"]
            assert spec["validation"]["enabled"] is True

            graph = runner.invoke(
                cli_main,
                ["harness", "graph", "--spec", "harness.yaml", "--json"],
            )
            assert graph.exit_code == 0
            graph_payload = json.loads(graph.output)
            assert [node["label"] for node in graph_payload["nodes"]] == [
                "planner",
                "implementer",
                "verifier",
            ]

    def test_harness_init_applies_security_review_preset(self, runner):
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli_main,
                [
                    "harness",
                    "init",
                    "security-agent",
                    "--preset",
                    "security-review",
                    "--output",
                    "harness.yaml",
                ],
            )

            assert result.exit_code == 0
            validate = runner.invoke(
                cli_main,
                ["harness", "validate", "--spec", "harness.yaml", "--json"],
            )
            assert validate.exit_code == 0
            spec = json.loads(validate.output)["spec"]
            assert spec["workflow"]["mode"] == "orchestrator"
            assert spec["workflow"]["parallelism"] == 3
            assert [agent["id"] for agent in spec["agents"]] == [
                "appsec",
                "data-flow",
                "dependency-risk",
            ]

    def test_harness_doctor_json_blocks_incompatible_backend(self, runner):
        with runner.isolated_filesystem():
            init = runner.invoke(
                cli_main,
                ["harness", "init", "demo", "--template", "no-tool", "--output", "harness.yaml"],
            )
            assert init.exit_code == 0

            result = runner.invoke(
                cli_main,
                [
                    "harness",
                    "doctor",
                    "--spec",
                    "harness.yaml",
                    "--runtime",
                    "deepagents",
                    "--json",
                ],
            )

            assert result.exit_code != 0
            payload = json.loads(result.output)
            assert payload["status"] == "error"
            compatibility = next(
                check for check in payload["checks"] if check["name"] == "compatibility"
            )
            assert compatibility["issues"][0]["code"] == "no_tool_unsupported"

    def test_harness_run_json_uses_kernel(self, runner, monkeypatch):
        class FakeRuntime:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def run(self, prompt):
                return AgentResponse(
                    content=f"ran:{prompt}",
                    messages=[],
                    tool_calls_made=0,
                    iterations=1,
                    stopped_reason="complete",
                )

            async def run_streaming(self, prompt):
                yield prompt

            def cancel(self):
                pass

            def reset_cancellation(self):
                pass

        monkeypatch.setattr(
            "superqode.harness.backends.runtime.create_runtime",
            lambda name, **kwargs: FakeRuntime(**kwargs),
        )
        with runner.isolated_filesystem():
            init = runner.invoke(
                cli_main,
                ["harness", "init", "demo", "--template", "no-tool", "--output", "harness.yaml"],
            )
            assert init.exit_code == 0

            result = runner.invoke(
                cli_main,
                [
                    "harness",
                    "run",
                    "--spec",
                    "harness.yaml",
                    "--prompt",
                    "hello",
                    "--provider",
                    "test",
                    "--model",
                    "model",
                    "--json",
                ],
            )

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["content"] == "ran:hello"
            assert payload["harness"] == "demo"

    def test_harness_run_store_sqlite_override(self, runner, monkeypatch):
        class FakeRuntime:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def run(self, prompt):
                return AgentResponse(
                    content=f"ran:{prompt}",
                    messages=[],
                    tool_calls_made=0,
                    iterations=1,
                    stopped_reason="complete",
                )

            def cancel(self):
                pass

            def reset_cancellation(self):
                pass

        monkeypatch.setattr(
            "superqode.harness.backends.runtime.create_runtime",
            lambda name, **kwargs: FakeRuntime(**kwargs),
        )
        with runner.isolated_filesystem():
            init = runner.invoke(
                cli_main,
                ["harness", "init", "demo", "--template", "no-tool", "--output", "harness.yaml"],
            )
            assert init.exit_code == 0

            result = runner.invoke(
                cli_main,
                [
                    "harness",
                    "run",
                    "--spec",
                    "harness.yaml",
                    "--prompt",
                    "hello",
                    "--provider",
                    "test",
                    "--model",
                    "model",
                    "--store",
                    "sqlite",
                    "--json",
                ],
            )

            assert result.exit_code == 0
            assert Path(".superqode/sessions/store.sqlite3").exists()


class TestAgentsCommand:
    """Tests for agents commands."""

    def test_agents_list(self, runner):
        """Test agents list command."""
        result = runner.invoke(cli_main, ["agents", "list"])

        # Should not error
        assert result.exit_code == 0 or "Error" not in result.output

    def test_agents_show_nonexistent(self, runner):
        """Test agents show with nonexistent agent."""
        result = runner.invoke(cli_main, ["agents", "show", "nonexistent"])

        # Should handle gracefully
        assert "not found" in result.output.lower() or result.exit_code != 0

    def test_agents_doctor_json(self, runner, monkeypatch):
        """ACP doctor should report install and setup state."""
        import superqode.agents.registry as registry

        async def fake_get_all_acp_agents():
            return {
                "test.agent": {
                    "identity": "test.agent",
                    "name": "Test Agent",
                    "short_name": "testagent",
                    "protocol": "acp",
                    "type": "coding",
                    "run_command": {"*": "testagent acp"},
                    "actions": {
                        "*": {
                            "install": {
                                "command": "npm install -g testagent",
                            }
                        }
                    },
                }
            }

        monkeypatch.setattr(registry, "get_all_acp_agents", fake_get_all_acp_agents)
        monkeypatch.setattr("superqode.acp.doctor.shutil.which", lambda name: "/bin/testagent")

        result = runner.invoke(cli_main, ["agents", "doctor", "testagent", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload[0]["short_name"] == "testagent"
        assert payload[0]["installed"] is True
        assert payload[0]["command"] == "testagent acp"

    def test_agents_doctor_live_missing_command_json(self, runner, monkeypatch):
        """ACP live doctor should fail clearly before protocol startup when missing."""
        import superqode.agents.registry as registry

        async def fake_get_all_acp_agents():
            return {
                "missing.agent": {
                    "identity": "missing.agent",
                    "name": "Missing Agent",
                    "short_name": "missingagent",
                    "protocol": "acp",
                    "type": "coding",
                    "run_command": {"*": "missingagent acp"},
                    "actions": {},
                }
            }

        monkeypatch.setattr(registry, "get_all_acp_agents", fake_get_all_acp_agents)
        monkeypatch.setattr("superqode.acp.doctor.shutil.which", lambda name: None)

        result = runner.invoke(cli_main, ["agents", "doctor", "missingagent", "--live", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload[0]["installed"] is False
        assert payload[0]["live"]["started"] is False
        assert "Command not found" in payload[0]["live"]["error"]


class TestProvidersCommand:
    """Tests for providers commands."""

    def test_providers_list(self, runner):
        """Test providers list command."""
        result = runner.invoke(cli_main, ["providers", "list"])

        # Should show provider list or handle gracefully
        assert result.exit_code == 0 or "Error" not in result.output

    def test_providers_ds4_server_prints_start_command(self, runner):
        """`providers ds4 server` must surface the kv-disk-dir flag — that's
        the single biggest perf knob and it's easy to forget."""
        result = runner.invoke(cli_main, ["providers", "ds4", "server"])
        assert result.exit_code == 0
        assert "ds4-server" in result.output
        assert "--kv-disk-dir" in result.output

    def test_providers_ds4_doctor_reports_unreachable_when_no_server(self, runner):
        """The doctor must exit non-zero and tell the user how to recover
        rather than hanging or printing a misleading 'ok'."""
        result = runner.invoke(
            cli_main,
            ["providers", "ds4", "doctor", "--host", "http://127.0.0.1:1/v1"],
        )
        assert result.exit_code != 0
        assert "Not reachable" in result.output

    def test_profiles_list_json(self, runner):
        """Test harness profile listing."""
        result = runner.invoke(cli_main, ["profiles", "list", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert {item["name"] for item in payload} >= {"build", "plan", "review", "qe"}

    def test_tools_list_json(self, runner):
        """Test harness tool listing."""
        result = runner.invoke(cli_main, ["tools", "list", "--profile", "plan", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        names = {item["name"] for item in payload}
        assert "read_file" in names
        assert "edit_file" not in names
        bash = next(item for item in payload if item["name"] == "bash")
        assert bash["permission"] == "ask"

    def test_provider_models_json(self, runner):
        """Test provider model listing."""
        result = runner.invoke(cli_main, ["providers", "models", "openai", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["provider"] == "openai"
        assert payload["models"]

    def test_provider_doctor_json(self, runner, monkeypatch):
        """Test provider setup diagnostics."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        result = runner.invoke(cli_main, ["providers", "doctor", "openai", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload[0]["provider"] == "openai"
        assert payload[0]["configured"] is False
        assert "OPENAI_API_KEY" in payload[0]["required_env_vars"]

    def test_provider_doctor_live_local_json(self, runner, monkeypatch):
        """Live provider doctor should reuse the local smoke health payload."""
        from superqode.providers.local.base import LocalProviderType, ProviderStatus
        from superqode.providers.local.ollama import OllamaClient

        async def fake_is_available(self):
            return False

        async def fake_get_status(self):
            return ProviderStatus(
                available=False,
                provider_type=LocalProviderType.OLLAMA,
                host=self.host,
                error="offline",
            )

        async def fake_list_models(self):
            return []

        monkeypatch.setattr(OllamaClient, "is_available", fake_is_available)
        monkeypatch.setattr(OllamaClient, "get_status", fake_get_status)
        monkeypatch.setattr(OllamaClient, "list_models", fake_list_models)

        result = runner.invoke(cli_main, ["providers", "doctor", "ollama", "--live", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload[0]["provider"] == "ollama"
        assert payload[0]["live"]["provider"] == "ollama"
        assert payload[0]["live"]["available"] is False

    def test_provider_recommend_json(self, runner):
        """Provider recommendations should include model quality labels."""
        result = runner.invoke(cli_main, ["providers", "recommend", "coding", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload
        assert payload[0]["provider"]
        assert payload[0]["price"]
        assert payload[0]["context"]
        assert payload[0]["tool_support"] in {"yes", "no"}
        assert payload[0]["setup"]["setup_hint"]

    def test_provider_recommend_local_json_prefers_ds4(self, runner):
        """Local recommendations should make DS4 easy to discover."""
        result = runner.invoke(cli_main, ["providers", "recommend", "local", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload
        assert payload[0]["provider"] == "ds4"
        assert payload[0]["model"] == "deepseek-v4-flash"

    def test_provider_guide_json(self, runner):
        """Provider guide should expose setup and representative model cards."""
        result = runner.invoke(cli_main, ["providers", "guide", "openai", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload[0]["provider"] == "openai"
        assert payload[0]["models"]
        assert "setup_hint" in payload[0]

    def test_ds4_models_json(self, runner):
        """DS4 should be a first-class local provider."""
        result = runner.invoke(cli_main, ["providers", "models", "ds4", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["provider"] == "ds4"
        assert "deepseek-v4-flash" in payload["models"]

    def test_ds4_smoke_json_without_running_completion(self, runner, monkeypatch):
        """DS4 smoke should be available without requiring a local server in CI."""
        from superqode.providers.local.base import LocalProviderType, ProviderStatus
        from superqode.providers.local.base import ToolTestResult
        from superqode.providers.local.ds4 import DS4Client

        async def fake_is_available(self):
            return False

        async def fake_get_status(self):
            return ProviderStatus(
                available=False,
                provider_type=LocalProviderType.OPENAI_COMPAT,
                host=self.host,
                error="offline",
            )

        async def fake_list_models(self):
            return self._fallback_models()

        async def fake_test_tool_calling(self, model_id):
            return ToolTestResult(
                model_id=model_id,
                supports_tools=True,
                parallel_tools=False,
                tool_choice=["auto"],
                notes="test",
            )

        monkeypatch.setattr(DS4Client, "is_available", fake_is_available)
        monkeypatch.setattr(DS4Client, "get_status", fake_get_status)
        monkeypatch.setattr(DS4Client, "list_models", fake_list_models)
        monkeypatch.setattr(DS4Client, "test_tool_calling", fake_test_tool_calling)

        result = runner.invoke(cli_main, ["providers", "smoke", "ds4", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["provider"] == "ds4"
        assert payload["registered"] is True
        assert payload["available"] is False
        assert payload["tool_support"] is True
        assert payload["completion_ran"] is False

    def test_ollama_smoke_json_without_running_completion(self, runner, monkeypatch):
        """Local smoke should work for non-DS4 providers too."""
        from superqode.providers.local.base import (
            LocalModel,
            LocalProviderType,
            ProviderStatus,
            ToolTestResult,
        )
        from superqode.providers.local.ollama import OllamaClient

        async def fake_is_available(self):
            return True

        async def fake_get_status(self):
            return ProviderStatus(
                available=True,
                provider_type=LocalProviderType.OLLAMA,
                host=self.host,
                models_count=1,
                running_models=1,
            )

        async def fake_list_models(self):
            return [
                LocalModel(
                    id="qwen2.5-coder:7b",
                    name="qwen2.5-coder:7b",
                    supports_tools=True,
                    running=True,
                    family="qwen",
                )
            ]

        async def fake_test_tool_calling(self, model_id):
            return ToolTestResult(
                model_id=model_id,
                supports_tools=True,
                parallel_tools=True,
                tool_choice=["auto"],
                notes="verified",
            )

        monkeypatch.setattr(OllamaClient, "is_available", fake_is_available)
        monkeypatch.setattr(OllamaClient, "get_status", fake_get_status)
        monkeypatch.setattr(OllamaClient, "list_models", fake_list_models)
        monkeypatch.setattr(OllamaClient, "test_tool_calling", fake_test_tool_calling)

        result = runner.invoke(cli_main, ["providers", "smoke", "ollama", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["provider"] == "ollama"
        assert payload["supported"] is True
        assert payload["available"] is True
        assert payload["model"] == "qwen2.5-coder:7b"
        assert payload["running_models"] == ["qwen2.5-coder:7b"]
        assert payload["tool_support"] is True

    def test_local_smoke_reports_registered_unsupported_provider(self, runner):
        """Local registry providers without a client should fail gracefully."""
        result = runner.invoke(cli_main, ["providers", "smoke", "llamacpp", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["provider"] == "llamacpp"
        assert payload["registered"] is True
        assert payload["supported"] is False
        assert "No local smoke client" in payload["error"]


class TestSandboxCommand:
    """Tests for sandbox provider commands."""

    def test_sandbox_doctor_json(self, runner, monkeypatch):
        """Sandbox diagnostics should expose provider readiness."""
        monkeypatch.setattr("superqode.sandbox.execution.shutil.which", lambda name: None)

        result = runner.invoke(cli_main, ["sandbox", "doctor", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert {item["backend"] for item in payload} >= {
            "docker",
            "e2b",
            "daytona",
            "modal",
            "vercel",
            "runloop",
            "agentcore",
            "langsmith",
        }
        docker = next(item for item in payload if item["backend"] == "docker")
        assert docker["available"] is False
        assert docker["capabilities"]["can_shell"] is True

    def test_sandbox_run_json(self, runner, monkeypatch, tmp_path):
        """Sandbox run should return structured command results."""
        import superqode.sandbox as sandbox

        def fake_run_in_sandbox(backend, command, cwd, timeout=300, image="python:3.12-slim"):
            assert backend == "docker"
            assert command == "echo hi"
            assert cwd == tmp_path
            assert timeout == 9
            assert image == "python:3.12"
            return sandbox.SandboxRunResult(backend, command, 0, stdout="hi\n")

        monkeypatch.setattr(sandbox, "run_in_sandbox", fake_run_in_sandbox)

        result = runner.invoke(
            cli_main,
            [
                "sandbox",
                "run",
                "docker",
                "--cwd",
                str(tmp_path),
                "--timeout",
                "9",
                "--image",
                "python:3.12",
                "--json",
                "echo",
                "hi",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["backend"] == "docker"
        assert payload["stdout"] == "hi\n"


class TestHeadlessCommand:
    """Tests for headless one-shot CLI mode."""

    def test_print_mode_runs_once(self, runner, monkeypatch):
        """`superqode -p` should run headlessly and print content."""
        import superqode.headless as headless

        async def fake_run_headless(**kwargs):
            assert kwargs["prompt"] == "summarize repo"
            assert kwargs["profile_name"] == "review"
            return AgentResponse(
                content="summary",
                messages=[],
                tool_calls_made=0,
                iterations=1,
                stopped_reason="complete",
            )

        monkeypatch.setattr(headless, "run_headless", fake_run_headless)

        result = runner.invoke(cli_main, ["-p", "--profile", "review", "summarize", "repo"])

        assert result.exit_code == 0
        assert result.output.strip() == "summary"

    def test_json_mode_outputs_structured_result(self, runner, monkeypatch):
        """`superqode --mode json` should emit a stable JSON object."""
        import json
        import superqode.headless as headless

        async def fake_run_headless(**kwargs):
            return AgentResponse(
                content="planned",
                messages=[],
                tool_calls_made=1,
                iterations=2,
                stopped_reason="complete",
            )

        monkeypatch.setattr(headless, "run_headless", fake_run_headless)

        result = runner.invoke(
            cli_main,
            ["--mode", "json", "--profile", "plan", "--provider", "test", "--model", "m", "plan"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["type"] == "superqode.result"
        assert payload["profile"] == "plan"
        assert payload["content"] == "planned"
        assert payload["success"] is True
        assert "changes" in payload

    def test_sessions_list_json(self, runner, tmp_path, monkeypatch):
        """Stored sessions should be listable from the CLI."""
        from superqode.agent.session_manager import SessionManager

        with runner.isolated_filesystem(temp_dir=tmp_path):
            manager = SessionManager(".superqode/sessions")
            manager.start_session("abc123", provider="test", model="m")
            manager.add_user_message("hello")

            result = runner.invoke(cli_main, ["sessions", "list", "--json"])

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload[0]["session_id"] == "abc123"
            assert payload[0]["message_count"] == 1

    def test_sessions_export_file(self, runner, tmp_path):
        """Stored sessions should export to files."""
        from superqode.agent.session_manager import SessionManager

        with runner.isolated_filesystem(temp_dir=tmp_path):
            manager = SessionManager(".superqode/sessions")
            manager.start_session("abc123", provider="test", model="m")
            manager.add_user_message("hello")

            result = runner.invoke(
                cli_main,
                ["sessions", "export", "abc", "--output", "session.md"],
            )

            assert result.exit_code == 0
            assert "# SuperQode Session abc123" in Path("session.md").read_text()

    def test_sessions_tree_json(self, runner, tmp_path):
        """Stored session forks should be visible as a tree."""
        from superqode.agent.session_manager import SessionManager

        with runner.isolated_filesystem(temp_dir=tmp_path):
            manager = SessionManager(".superqode/sessions")
            manager.start_session("root", provider="test", model="m")
            manager.add_user_message("hello")
            manager.fork_current_session("child")

            result = runner.invoke(cli_main, ["sessions", "tree", "--json"])

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload[0]["session_id"] == "root"
            assert payload[0]["children"][0]["session_id"] == "child"


class TestPluginsCommand:
    """Tests for plugin manifest CLI commands."""

    def test_plugins_list_json(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            plugin_dir = Path(".superqode/plugins/demo")
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps({"id": "demo", "name": "Demo", "version": "1.0.0"}),
                encoding="utf-8",
            )

            result = runner.invoke(cli_main, ["plugins", "list", "--json"])

            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload[0]["id"] == "demo"

    def test_plugins_validate(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("plugin.json").write_text(
                json.dumps({"id": "demo", "name": "Demo"}),
                encoding="utf-8",
            )

            result = runner.invoke(cli_main, ["plugins", "validate", "plugin.json"])

            assert result.exit_code == 0
            assert "valid" in result.output


class TestQECommand:
    """Tests for QE commands (superqe CLI)."""

    def test_qe_help(self, runner):
        """Test qe command help."""
        from superqode.superqe_cli import superqe

        result = runner.invoke(superqe, ["--help"])

        assert result.exit_code == 0
        assert "qe" in result.output.lower() or "quality" in result.output.lower()

    def test_jsonl_and_junit_do_not_require_enterprise(self, runner, tmp_path, monkeypatch):
        """CI output formats should be available in OSS."""
        from superqode.superqe_cli import superqe
        import superqode.commands.qe as qe_commands
        import superqode.superqe as superqe_module
        import superqode.utils.error_handling as error_handling
        import superqode.workspace as workspace_module

        def fail_enterprise_check(feature_name):
            raise AssertionError(f"Unexpected enterprise gate: {feature_name}")

        class FakeResult:
            success = True
            total_tests = 0
            tests_failed = 0
            duration_seconds = 0.0
            smoke_result = None
            sanity_result = None
            regression_result = None

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs):
                pass

            async def quick_scan(self):
                return FakeResult()

            def export_junit(self, result):
                return "<testsuites />"

            def cancel(self):
                pass

        class FakeCoordinator:
            def __init__(self, *args, **kwargs):
                pass

            @contextmanager
            def session(self, *args, **kwargs):
                yield object()

        monkeypatch.setattr(qe_commands, "_enterprise_only", fail_enterprise_check)
        monkeypatch.setattr(superqe_module, "QEOrchestrator", FakeOrchestrator)
        monkeypatch.setattr(workspace_module, "QECoordinator", FakeCoordinator)
        monkeypatch.setattr(error_handling, "check_dependencies", lambda: True)
        monkeypatch.setattr(
            error_handling,
            "validate_project_structure",
            lambda path: {"errors": [], "warnings": []},
        )
        monkeypatch.setattr(qe_commands, "get_warning_acknowledgment", lambda *args, **kwargs: True)

        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("superqode.yaml").write_text("team: {}\n", encoding="utf-8")

            jsonl_result = runner.invoke(superqe, ["run", ".", "--jsonl"])
            assert jsonl_result.exit_code == 0

            junit_result = runner.invoke(superqe, ["run", ".", "--junit", "results.xml"])
            assert junit_result.exit_code == 0
            assert Path("results.xml").read_text(encoding="utf-8") == "<testsuites />"


class TestRolesCommand:
    """Tests for roles commands."""

    def test_roles_help(self, runner):
        """Test roles command help."""
        result = runner.invoke(cli_main, ["roles", "--help"])

        assert result.exit_code == 0
        assert "roles" in result.output.lower()

    def test_roles_list(self, runner):
        """Test roles list command."""
        result = runner.invoke(cli_main, ["roles", "list"])

        # Should show role list or handle gracefully
        assert result.exit_code == 0 or "Error" not in result.output


class TestAuthCommand:
    """Tests for auth commands."""

    def test_auth_help(self, runner):
        """Test auth command help."""
        result = runner.invoke(cli_main, ["auth", "--help"])

        assert result.exit_code == 0
        assert "auth" in result.output.lower()

    def test_auth_info(self, runner):
        """Test auth info command."""
        result = runner.invoke(cli_main, ["auth", "info"])

        # Should handle gracefully even without credentials
        assert result.exit_code in [0, 1]


class TestInitCommand:
    """Tests for init command."""

    def test_init_creates_config(self, runner, tmp_path):
        """Test init command creates config file."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli_main, ["init"])

            # Check for config creation message or file
            config_path = Path("superqode.yaml")
            assert (
                config_path.exists()
                or "Created" in result.output
                or "already exists" in result.output.lower()
            )

    def test_init_force(self, runner, tmp_path):
        """Test init --force overwrites existing config."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Create existing config
            Path("superqode.yaml").write_text("# existing config")

            result = runner.invoke(cli_main, ["init", "--force"])

            # Should succeed with force flag
            assert result.exit_code == 0 or "Created" in result.output


class TestSuggestionsCommand:
    """Tests for suggestions commands."""

    def test_suggestions_help(self, runner):
        """Test suggestions command help."""
        result = runner.invoke(cli_main, ["suggestions", "--help"])

        assert result.exit_code == 0
        assert "suggestions" in result.output.lower()


# Integration tests
@pytest.mark.integration
class TestCLIIntegration:
    """Integration tests for CLI commands.

    These tests may interact with external services.
    Run with: pytest -m integration
    """

    @pytest.mark.skip(reason="Requires agent to be installed")
    def test_agents_connect(self, runner, tmp_path):
        """Test connecting to an agent."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli_main, ["agents", "connect", "opencode"])

            # Should attempt connection
            assert "connect" in result.output.lower() or "agent" in result.output.lower()
