"""Tests for the ACP agent registry compatibility API."""

from superqode.agents.acp_registry import (
    get_all_registry_agents,
    get_registry_agent,
    get_registry_agent_by_short_name,
)
from superqode.agents.official_acp import OFFICIAL_ACP_AGENTS


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


def test_fast_agent_registry_uses_documented_acp_entrypoint():
    agent = get_registry_agent_by_short_name("fast-agent")

    assert agent is not None
    assert agent["identity"] == "fastagent.ai"
    assert agent["run_command"] == "uvx --from fast-agent-mcp@latest fast-agent-acp"
    assert agent["installation_command"] == "uv tool install -U fast-agent-mcp"


def test_registry_includes_official_acp_agents_page_entries():
    agents = get_all_registry_agents()

    for official in OFFICIAL_ACP_AGENTS:
        assert official["identity"] in agents


def test_registry_removed_stale_moltbot_alias():
    agents = get_all_registry_agents()

    assert "molt.bot" not in agents
    assert get_registry_agent_by_short_name("moltbot") is None
    openclaw = get_registry_agent_by_short_name("openclaw")
    assert openclaw is not None
    assert openclaw["identity"] == "openclaw.ai"
