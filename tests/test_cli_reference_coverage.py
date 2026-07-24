"""Documentation coverage checks for the public CLI surface."""

import tomllib
from pathlib import Path

from superqode.main import cli_main
from superqode.providers.connection_profiles import connection_profile_ids
from superqode.providers.registry import PROVIDERS


def test_top_level_cli_groups_have_reference_docs():
    """Every public top-level command group should be discoverable from the docs."""

    root = Path(__file__).resolve().parents[1]
    cli_reference = root / "docs" / "cli-reference"
    docs_index = (cli_reference / "index.md").read_text(encoding="utf-8")
    mkdocs = (root / "mkdocs.yml").read_text(encoding="utf-8")

    documented_files = {path.name for path in cli_reference.glob("*.md")}
    filename_aliases = {
        "provider-commands.md": {"providers"},
        "doctor-command.md": {"doctor"},
        "daemon-command.md": {"daemon"},
        "mcp-command.md": {"mcp"},
        "init-commands.md": {"init"},
    }
    intentionally_inline = {
        "help",  # help is built into the CLI and surfaced by Click.
        "tui",  # documented in advanced/tui.md rather than the CLI section.
    }

    documented_groups = set()
    for filename in documented_files:
        if filename == "index.md":
            continue
        if filename.endswith("-commands.md"):
            documented_groups.add(filename[: -len("-commands.md")])
        elif filename.endswith("-command.md"):
            documented_groups.add(filename[: -len("-command.md")])
        documented_groups.update(filename_aliases.get(filename, set()))

    missing = []
    for name in sorted(cli_main.commands):
        if name in intentionally_inline:
            continue
        if name not in documented_groups:
            missing.append(name)
            continue
        expected_refs = [
            f"{name}-commands.md",
            f"{name}-command.md",
            "provider-commands.md" if name == "providers" else "",
        ]
        if not any(ref and ref in docs_index and ref in mkdocs for ref in expected_refs):
            missing.append(name)

    assert missing == []


def test_product_capability_reference_covers_public_surfaces():
    """The product index should retain the main implementation and protocol surfaces."""

    root = Path(__file__).resolve().parents[1]
    capability_path = root / "docs" / "product-capabilities.md"
    capability_text = capability_path.read_text(encoding="utf-8")
    mkdocs = (root / "mkdocs.yml").read_text(encoding="utf-8")

    required_surfaces = {
        "Harness authoring",
        "Harness Protocol",
        "Poolside Laguna S 2.1",
        "Runtime adapters",
        "Safety and governance",
        "Context and memory",
        "Evaluation",
        "Optimization",
        "Recursive workflows",
        "Offline operation",
        "Durable repository delivery",
        "Code Factory operation",
        "Extensions",
        "Protocol integration",
        "Automation",
        "Omnigent interoperability",
    }

    missing = sorted(surface for surface in required_surfaces if surface not in capability_text)
    assert missing == []
    assert "product-capabilities.md" in mkdocs


def test_connection_reference_covers_methods_profiles_providers_and_agents():
    """The connection page should not hide implemented routes in separate guides."""

    root = Path(__file__).resolve().parents[1]
    connection_path = root / "docs" / "concepts" / "modes.md"
    connection_text = connection_path.read_text(encoding="utf-8")
    mkdocs = (root / "mkdocs.yml").read_text(encoding="utf-8")

    required_methods = {
        "## Local Providers",
        "## ACP Coding Agents",
        "## BYOK Providers",
        "## SDK Runtimes",
        "## MCP Tool Connections",
        "## A2A Agent Connections",
    }
    required_named_products = {
        "OpenAI Codex",
        "Anthropic Claude",
        "Google Antigravity",
        "Google Gemini",
        "GitHub Copilot",
        "xAI Grok",
        "OpenCode",
        "Z.AI GLM",
        "Poolside",
        "Moonshot AI Kimi",
        "Alibaba Qwen",
        "DeepSeek",
        "Mistral AI",
        "MiniMax",
    }

    missing_methods = sorted(method for method in required_methods if method not in connection_text)
    missing_products = sorted(
        product for product in required_named_products if product not in connection_text
    )
    missing_profiles = sorted(
        profile_id
        for profile_id in connection_profile_ids()
        if f"`{profile_id}`" not in connection_text
        and f":connect {profile_id}" not in connection_text
    )
    missing_providers = sorted(
        provider_id
        for provider_id in PROVIDERS
        if f"`{provider_id}`" not in connection_text
    )

    agent_data_dir = root / "src" / "superqode" / "agents" / "data"
    bundled_agent_ids = {
        tomllib.loads(path.read_text(encoding="utf-8"))["short_name"]
        for path in agent_data_dir.glob("*.toml")
    }
    missing_agents = sorted(
        agent_id for agent_id in bundled_agent_ids if f"`{agent_id}`" not in connection_text
    )

    assert missing_methods == []
    assert missing_products == []
    assert missing_profiles == []
    assert missing_providers == []
    assert missing_agents == []
    assert "Connection Methods and Vendors: concepts/modes.md" in mkdocs
