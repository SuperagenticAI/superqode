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


class TestProvidersCommand:
    """Tests for providers commands."""

    def test_providers_list(self, runner):
        """Test providers list command."""
        result = runner.invoke(cli_main, ["providers", "list"])

        # Should show provider list or handle gracefully
        assert result.exit_code == 0 or "Error" not in result.output

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
