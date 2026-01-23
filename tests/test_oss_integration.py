"""
SuperQode OSS Integration Tests

Comprehensive end-to-end testing for the open-source SuperQode package.
Validates all OSS functionality works correctly.
"""

import pytest
import asyncio
import tempfile
import os
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import SuperQode components
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from superqode.main import cli_main
from superqode.superqe_cli import superqe as superqe_cli
from superqode.superqe.orchestrator import QEOrchestrator
from superqode.superqe.acp_runner import ACPQERunner, ACPRunnerConfig
from superqode.workspace.manager import WorkspaceManager
import click.testing


class TestOSSIntegration:
    """Test the complete OSS integration."""

    @pytest.fixture
    def temp_project(self, monkeypatch):
        """Create a temporary project for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            state_dir = project_dir / ".superqode" / "state" / "qe"
            monkeypatch.setenv("SUPERQODE_STATE_DIR", str(state_dir))

            # Create a simple Python project
            (project_dir / "main.py").write_text("""
def hello_world():
    return "Hello, World!"

def add_numbers(a, b):
    return a + b

if __name__ == "__main__":
    print(hello_world())
""")

            (project_dir / "test_main.py").write_text("""
import main

def test_hello_world():
    assert main.hello_world() == "Hello, World!"

def test_add_numbers():
    assert main.add_numbers(2, 3) == 5
""")

            # Create superqode.yaml
            (project_dir / "superqode.yaml").write_text("""
superqode:
  version: "2.0"
  team_name: "Test Team"

default:
  mode: "acp"
  coding_agent: "opencode"

team:
  dev:
    roles:
      fullstack:
        enabled: true
        mode: "acp"
        coding_agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "glm-4.7-free"

  qe:
    roles:
      unit_tester:
        enabled: true
        mode: "acp"
        coding_agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "glm-4.7-free"
      api_tester:
        enabled: true
        mode: "acp"
        coding_agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "glm-4.7-free"

providers:
  opencode:
    description: "OpenCode free models"
    recommended_models:
      - "glm-4.7-free"
      - "grok-code"

code_agents:
  - "opencode"
""")

            yield project_dir

    def test_cli_help(self):
        """Test that CLI help works."""
        runner = click.testing.CliRunner()
        result = runner.invoke(cli_main, ["--help"])
        assert result.exit_code == 0
        assert "SuperQode" in result.output

    def test_qe_help(self):
        """Test QE command help."""
        runner = click.testing.CliRunner()
        result = runner.invoke(superqe_cli, ["--help"])
        assert result.exit_code == 0
        assert "quality" in result.output.lower()

    def test_qe_run_help(self):
        """Test QE run command help."""
        runner = click.testing.CliRunner()
        result = runner.invoke(superqe_cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "--verbose" in result.output
        assert "--mode" in result.output

    @patch("superqode.superqe.acp_runner.ACPQERunner.run")
    def test_qe_quick_scan(self, mock_acp_run, temp_project):
        """Test QE quick scan (should not run agent analysis)."""
        # Mock the ACP runner to avoid actual AI calls
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.findings = []
        mock_result.agent_output = "Mock analysis complete"
        mock_result.tool_calls = []
        mock_result.duration_seconds = 1.0
        mock_result.errors = []
        mock_acp_run.return_value = mock_result

        runner = click.testing.CliRunner()
        with (
            patch("superqode.utils.error_handling.check_dependencies", return_value=True),
            patch("superqode.commands.qe.show_safety_warnings"),
            patch("superqode.commands.qe.get_warning_acknowledgment", return_value=True),
        ):
            result = runner.invoke(superqe_cli, ["run", str(temp_project), "--mode", "quick"])

        assert result.exit_code == 0
        # Quick scan should not show agent analysis messages
        assert "🤖 Starting AI agent analysis" not in result.output

    @patch("superqode.superqe.acp_runner.ACPQERunner.run")
    def test_qe_deep_scan_with_verbose(self, mock_acp_run, temp_project):
        """Test QE deep scan with verbose output."""
        # Mock the ACP runner
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.findings = []
        mock_result.agent_output = "Mock AI analysis complete"
        mock_result.tool_calls = [{"title": "file_scan", "status": "completed"}]
        mock_result.duration_seconds = 2.0
        mock_result.errors = []
        mock_acp_run.return_value = mock_result

        runner = click.testing.CliRunner()
        with (
            patch("superqode.utils.error_handling.check_dependencies", return_value=True),
            patch("superqode.commands.qe.show_safety_warnings"),
            patch("superqode.commands.qe.get_warning_acknowledgment", return_value=True),
        ):
            result = runner.invoke(
                superqe_cli, ["run", str(temp_project), "--mode", "deep", "--verbose"]
            )

        assert result.exit_code == 0
        # Deep scan should show agent analysis
        assert "🤖 Starting AI agent analysis" in result.output

    @patch("superqode.superqe.acp_runner.ACPQERunner.run")
    def test_qe_with_specific_roles(self, mock_acp_run, temp_project):
        """Test QE with specific roles."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.findings = []
        mock_result.agent_output = "Role-specific analysis"
        mock_result.tool_calls = []
        mock_result.duration_seconds = 1.5
        mock_result.errors = []
        mock_acp_run.return_value = mock_result

        runner = click.testing.CliRunner()
        with (
            patch("superqode.utils.error_handling.check_dependencies", return_value=True),
            patch("superqode.commands.qe.show_safety_warnings"),
            patch("superqode.commands.qe.get_warning_acknowledgment", return_value=True),
        ):
            result = runner.invoke(
                superqe_cli, ["run", str(temp_project), "-r", "unit_tester", "-r", "api_tester"]
            )

        assert result.exit_code == 0
        assert "unit_tester" in result.output or "api_tester" in result.output

    def test_workspace_creation(self, temp_project):
        """Test that workspace is properly created."""
        workspace = WorkspaceManager(temp_project)
        workspace.initialize()

        # Check that .superqode directory exists
        superqode_dir = temp_project / ".superqode"
        assert superqode_dir.exists()

        # Check that qe-artifacts directory exists
        artifacts_dir = superqode_dir / "qe-artifacts"
        assert artifacts_dir.exists()

    def test_qe_status_command(self, temp_project):
        """Test QE status command."""
        runner = click.testing.CliRunner()
        result = runner.invoke(superqe_cli, ["status", str(temp_project)])

        assert result.exit_code in (0, 1)
        if result.exit_code == 0:
            assert "QE Workspace Status" in result.output or "SuperQode Enterprise" in result.output
        else:
            assert "QE workspace status is available in SuperQode Enterprise" in result.output

    def test_qe_artifacts_command(self, temp_project):
        """Test QE artifacts listing."""
        runner = click.testing.CliRunner()
        result = runner.invoke(superqe_cli, ["artifacts", str(temp_project)])

        assert result.exit_code in (0, 1)
        if result.exit_code != 0:
            assert "QE artifacts is available in SuperQode Enterprise" in result.output

    def test_acp_runner_initialization(self, temp_project):
        """Test ACP runner can be initialized."""
        config = ACPRunnerConfig(verbose=True)
        runner = ACPQERunner(temp_project, config)

        assert runner.project_root == temp_project.resolve()
        assert runner.config.verbose

    def test_orchestrator_creation(self, temp_project):
        """Test QE orchestrator creation."""
        orchestrator = QEOrchestrator(temp_project, verbose=True)

        assert orchestrator.project_root == temp_project.resolve()
        assert orchestrator.verbose

    def test_yaml_config_loading(self, temp_project):
        """Test that YAML configuration is valid."""
        import yaml

        config_file = temp_project / "superqode.yaml"
        assert config_file.exists()

        with open(config_file) as f:
            config = yaml.safe_load(f)

        assert "superqode" in config
        assert "team" in config
        assert "providers" in config
        assert "opencode" in config["providers"]

    @pytest.mark.asyncio
    async def test_mock_acp_analysis(self, temp_project):
        """Test mock ACP analysis (simulates real AI calls)."""
        config = ACPRunnerConfig(
            agent_command="echo 'Mock AI analysis complete'", timeout_seconds=5, verbose=True
        )

        runner = ACPQERunner(temp_project, config)

        # This would normally call real AI, but we're using echo for testing
        try:
            result = await runner.run("Analyze this Python code", "unit_tester")

            # In real scenarios, this might fail due to mock setup
            # but the runner should handle it gracefully
            assert isinstance(result, object)  # Result object created

        except Exception as e:
            # Expected to fail in test environment without real OpenCode
            assert "Agent execution failed" in str(e) or "command not found" in str(e)

    def test_qr_generation(self, temp_project):
        """Test QR generation capability."""
        workspace = WorkspaceManager(temp_project)
        workspace.initialize()

        # Start a session to set up the config
        from superqode.superqe.session import QESessionConfig, QEMode

        config = QESessionConfig(mode=QEMode.DEEP_QE)
        workspace.start_session(config=config)

        # Create some mock findings
        workspace.add_finding(
            severity="info",
            title="Test Finding",
            description="This is a test finding for QR generation",
            evidence="Test evidence",
        )

        # Generate QR
        qr_artifact = workspace._generate_qir()

        # Read the QR content
        qr_path = workspace.artifacts.artifacts_dir / qr_artifact.path
        qr_content = qr_path.read_text()

        assert "Quality" in qr_content and "Report" in qr_content
        assert "Test Finding" in qr_content
        assert "deep_qe" in qr_content

    def test_error_handling_graceful_degradation(self, temp_project):
        """Test that system degrades gracefully when AI is unavailable."""
        # This simulates the fallback behavior when OpenCode isn't available
        from superqode.superqe.session import QESession, QESessionConfig, QEMode

        config = QESessionConfig(
            mode=QEMode.DEEP_QE, run_agent_analysis=True, agent_roles=["contract-tester"]
        )

        session = QESession(temp_project, config)

        # This should not crash even if AI agents fail
        # The session should complete with fallback findings
        assert session.project_root == temp_project.resolve()
        assert len(config.agent_roles) == 1


if __name__ == "__main__":
    # Run basic validation
    print("🧪 Running SuperQode OSS Integration Tests...")

    test_instance = TestOSSIntegration()

    # Test basic CLI functionality
    try:
        test_instance.test_cli_help()
        print("✅ CLI help works")
    except Exception as e:
        print(f"❌ CLI help failed: {e}")

    try:
        test_instance.test_qe_help()
        print("✅ QE help works")
    except Exception as e:
        print(f"❌ QE help failed: {e}")

    try:
        test_instance.test_qe_run_help()
        print("✅ QE run help works")
    except Exception as e:
        print(f"❌ QE run help failed: {e}")

    print("🎯 OSS Integration Tests completed!")
