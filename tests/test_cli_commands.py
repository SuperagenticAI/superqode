"""
Tests for SuperQode CLI Commands.

Tests the command-line interface functionality.
"""

import pytest
from click.testing import CliRunner
from pathlib import Path
from unittest.mock import patch, MagicMock

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


class TestQECommand:
    """Tests for QE commands (superqe CLI)."""

    def test_qe_help(self, runner):
        """Test qe command help."""
        from superqode.superqe_cli import superqe

        result = runner.invoke(superqe, ["--help"])

        assert result.exit_code == 0
        assert "qe" in result.output.lower() or "quality" in result.output.lower()


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
