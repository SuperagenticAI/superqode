"""Tests for the ACP agent registry compatibility API."""

from superqode.agents.acp_registry import (
    get_all_registry_agents,
    get_registry_agent,
    get_registry_agent_by_short_name,
)


def test_registry_prefers_toml_agent_data_for_legacy_api():
    agent = get_registry_agent("codex.openai.com")

    assert agent is not None
    assert agent["short_name"] == "codex"
    assert agent["run_command"] == "codex-acp"
    assert agent["installation_command"] == "npm i @zed-industries/codex-acp"


def test_registry_includes_toml_only_agents():
    agents = get_all_registry_agents()

    assert "ampcode.com" in agents
    assert agents["ampcode.com"]["short_name"] == "amp"
    assert agents["ampcode.com"]["run_command"] == "acp-amp"


def test_registry_short_name_lookup_uses_toml_data():
    agent = get_registry_agent_by_short_name("opencode")

    assert agent is not None
    assert agent["identity"] == "opencode.ai"
    assert agent["run_command"] == "opencode acp"
