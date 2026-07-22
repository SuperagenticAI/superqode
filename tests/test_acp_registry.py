"""Tests for the ACP agent registry compatibility API."""

from superqode.agents.acp_registry import (
    get_all_registry_agents,
    get_registry_agent,
    get_registry_agent_by_short_name,
)
from superqode.acp_discovery import KNOWN_AGENTS
from superqode.agents.official_acp import OFFICIAL_ACP_AGENTS
from superqode.providers.acp_registry import (
    convert_registry_agent,
    registry_catalog_tier,
)


def test_registry_prefers_toml_agent_data_for_legacy_api():
    agent = get_registry_agent("codex.openai.com")

    assert agent is not None
    assert agent["short_name"] == "codex"
    assert agent["run_command"] == "codex-acp"
    assert agent["installation_command"] == "npm install -g @agentclientprotocol/codex-acp"


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


def test_registry_includes_official_grok_cli_agent():
    agent = get_registry_agent_by_short_name("grok")

    assert agent is not None
    assert agent["identity"] == "x.ai"
    assert agent["run_command"] == "grok agent stdio"


def test_acp_discovery_uses_grok_native_stdio_server():
    grok = next(agent for agent in KNOWN_AGENTS if agent["short_name"] == "grok")

    assert grok["command"] == ["grok", "agent", "stdio"]
    assert grok["requires_api_key"] is False
    # Both the generic xAI key and the CLI's own key env are accepted.
    assert grok["api_key_env_vars"] == ["XAI_API_KEY", "GROK_CODE_XAI_API_KEY"]


def test_acp_discovery_grok_models_lead_with_account_default():
    import asyncio

    from superqode.acp_discovery import ACPDiscovery, DiscoveredAgent

    agent = DiscoveredAgent(
        name="Grok Build", short_name="grok", command=["grok", "agent", "stdio"]
    )
    models = asyncio.run(ACPDiscovery()._get_models(agent))

    ids = [m.id for m in models]
    # The CLI's default alias must come first; explicit ids follow.
    assert ids[0] == "grok-build"
    assert "grok-4.5" in ids
    assert "grok-build-0.1" in ids


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


def test_bundled_catalog_uses_current_acp_commands():
    expected = {
        "gemini": "gemini --acp",
        "claude": "claude-agent-acp",
        "goose": "goose acp",
        "kimi": "kimi acp",
        "copilot": "copilot --acp",
        "qwen": "qwen --acp --experimental-skills",
        "droid": "droid exec --output-format acp-daemon",
        "cortex": "cortex acp serve",
        "devin": "devin acp",
        "harn": "harn serve acp",
        "kilo": "kilo acp",
    }

    for short_name, command in expected.items():
        agent = get_registry_agent_by_short_name(short_name)
        assert agent is not None
        assert agent["run_command"] == command


def test_auto_discovery_covers_the_bundled_catalog():
    names = {agent["short_name"] for agent in KNOWN_AGENTS}

    assert {"devin", "harn", "kilo", "qwen", "copilot", "cortex"} <= names
    assert len(names) >= 30


def test_registry_converter_preserves_stable_alias_and_tier():
    converted = convert_registry_agent(
        {
            "id": "qwen-code",
            "name": "Qwen Code",
            "version": "0.20.1",
            "description": "Alibaba's coding assistant",
            "authors": ["Alibaba Qwen Team"],
            "distribution": {
                "npx": {
                    "package": "@qwen-code/qwen-code@0.20.1",
                    "args": ["--acp", "--experimental-skills"],
                }
            },
        }
    )

    assert converted["identity"] == "qwenlm.github.io"
    assert converted["short_name"] == "qwen"
    assert converted["catalog_tier"] == "featured"
    assert converted["run_command"]["*"] == "qwen --acp --experimental-skills"
    assert converted["actions"]["*"]["install"]["command"] == (
        "npm install -g @qwen-code/qwen-code"
    )


def test_registry_tiers_are_stable_for_public_aliases():
    assert registry_catalog_tier("codex-acp", "codex") == "featured"
    assert registry_catalog_tier("devin", "devin") == "enterprise"
    assert registry_catalog_tier("glm-acp-agent", "glm") == "all"
