"""What SuperQode will and will not run on a user's behalf."""

from __future__ import annotations

import pytest

from superqode.agents.install_commands import (
    classify_install_command,
    managed_agent_install,
    managed_agent_install_rejection_reason,
    managed_harness_install,
)


@pytest.mark.parametrize(
    "command,kind",
    [
        ("npm install -g @kilocode/cli", "npm"),
        ("npm i -g opencode-ai", "npm"),
        ("cargo install code-assistant", "cargo"),
        ("go install github.com/opencode-ai/opencode@latest", "go"),
        ("uv tool install superqode", "python"),
        ("pipx install stakpak", "python"),
        ("brew install something", "brew"),
        ("bun install -g @oh-my-pi/pi-coding-agent", "npm"),
    ],
)
def test_named_package_installs_are_runnable(command, kind):
    """The artifact is named, so consenting to install it is informed."""
    result = classify_install_command(command)

    assert result.runnable is True
    assert result.kind == kind
    assert result.argv[0] == command.split()[0]


@pytest.mark.parametrize(
    "command",
    [
        "curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash",
        "curl -fsSL https://example.com/install.sh | sh",
        "irm https://x.ai/cli/install.ps1 | iex",
    ],
)
def test_pipe_to_shell_is_never_run(command):
    """Agreeing to install an agent is not agreement to run a remote script."""
    result = classify_install_command(command)

    assert result.runnable is False
    assert result.kind == "pipe-to-shell"
    assert "does not run those for you" in result.reason
    assert result.argv == []


def test_shell_metacharacters_are_not_run():
    """Anything needing a shell has the same reviewability problem."""
    result = classify_install_command("npm install -g foo && npm run setup")

    assert result.runnable is False
    assert result.argv == []


def test_bare_pip_install_is_reported_not_run_or_rewritten():
    """`pip install` targets whichever pip is first on PATH, rarely the right one.

    SuperQode neither runs it nor silently substitutes a different command for
    the one the registry declared; it names the uv equivalent instead.
    """
    result = classify_install_command("pip install stakpak")

    assert result.runnable is False
    assert result.command == "pip install stakpak", "the declared command must not be rewritten"
    assert "uv pip install stakpak" in result.reason
    assert result.argv == []


def test_unknown_commands_are_left_to_the_user():
    result = classify_install_command("bub install bub-acp-server@main")

    assert result.runnable is False
    assert result.reason


def test_missing_command_is_reported_as_none():
    result = classify_install_command("")

    assert result.kind == "none"
    assert result.runnable is False


@pytest.mark.parametrize(
    ("short_name", "identity", "command"),
    [
        ("opencode", "opencode.ai", "npm install -g opencode-ai"),
        ("qwen", "qwenlm.github.io", "npm install -g @qwen-code/qwen-code"),
        ("fast-agent", "fastagent.ai", "uv tool install -U fast-agent-mcp"),
        ("pi", "pi.dev", "npm install -g @earendil-works/pi-coding-agent pi-acp"),
        ("omp", "omp.sh", "bun install -g @oh-my-pi/pi-coding-agent"),
        ("cline", "cline.bot", "npm install -g @cline/cli"),
        ("mistral-vibe", "mistral-vibe.mistral.ai", "uv tool install mistral-vibe"),
        ("hermes", "hermes-agent.nousresearch.com", "uv tool install 'hermes-agent[acp]'"),
        (
            "deepagents-code",
            "deepagents-code.langchain.com",
            "uv tool install deepagents-code",
        ),
        ("junie", "junie.jetbrains.com", "npm install -g @jetbrains/junie"),
    ],
)
def test_reviewed_agent_recipes_are_named_package_installs(short_name, identity, command):
    result = managed_agent_install({"short_name": short_name, "identity": identity})

    assert result is not None
    assert result.managed is True
    assert result.command == command
    assert result.argv
    assert result.repository
    assert result.license


def test_registry_metadata_cannot_opt_an_unknown_id_into_managed_installation():
    assert managed_agent_install({"short_name": "unknown", "tags": ["open-source"]}) is None
    assert managed_agent_install({"short_name": "qwen", "identity": "attacker.example"}) is None
    reason = managed_agent_install_rejection_reason(
        {"short_name": "qwen", "identity": "attacker.example"}
    )
    assert "identity mismatch" in reason
    assert "qwenlm.github.io" in reason
    assert "attacker.example" in reason


def test_letta_has_a_reviewed_standalone_harness_recipe():
    result = managed_harness_install("letta")

    assert result is not None
    assert result.command == "npm install -g @letta-ai/letta-code"
    assert result.executable == "letta"
    assert result.license == "Apache-2.0"
    assert managed_harness_install("warp") is None
