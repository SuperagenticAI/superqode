"""Documentation coverage checks for the public CLI surface."""

import re
import tomllib
from pathlib import Path

import click

from superqode.app.constants import COMMANDS
from superqode.harness.templates import BUILTIN_TEMPLATES
from superqode.headless import get_harness_profiles
from superqode.main import cli_main
from superqode.providers.connection_profiles import connection_profile_ids
from superqode.providers.registry import PROVIDERS
from superqode.runtime.registry import known_runtime_names
from superqode.tools.base import ToolRegistry


def _all_documentation_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((root / "docs").rglob("*.md"))
    )


def _click_command_paths(command: click.Command, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if not isinstance(command, click.Group):
        return paths
    for name, child in sorted(command.commands.items()):
        path = f"{prefix} {name}".strip()
        paths.append(path)
        paths.extend(_click_command_paths(child, path))
    return paths


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


def test_every_public_cli_path_is_present_in_documentation():
    """Every public Click command path should appear in runnable or reference form."""

    root = Path(__file__).resolve().parents[1]
    documentation = _all_documentation_text(root)
    missing = []

    for path in _click_command_paths(cli_main):
        if path in {"help", "tui"}:
            continue
        escaped = re.escape(path)
        documented = re.search(
            rf"(?:superqode|sq)\s+{escaped}(?:\s|`|$)|`{escaped}(?:\s|`)",
            documentation,
        )
        if documented is None:
            missing.append(path)

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
        provider_id for provider_id in PROVIDERS if f"`{provider_id}`" not in connection_text
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


def test_runtime_tool_template_pack_and_tui_inventories_are_documented():
    """Source-derived runtime, tool, template, pack, and TUI roots stay discoverable."""

    root = Path(__file__).resolve().parents[1]
    documentation = _all_documentation_text(root)
    runtime_text = (root / "docs" / "runtimes.md").read_text(encoding="utf-8")
    tool_text = (root / "docs" / "advanced" / "tools-catalog.md").read_text(encoding="utf-8")
    harness_text = (root / "docs" / "getting-started" / "bring-your-own-harness.md").read_text(
        encoding="utf-8"
    )
    tui_text = (root / "docs" / "advanced" / "tui.md").read_text(encoding="utf-8")

    missing_runtimes = sorted(
        name for name in known_runtime_names() if f"`{name}`" not in runtime_text
    )
    missing_tools = sorted(
        tool.name for tool in ToolRegistry.full().list() if f"`{tool.name}`" not in tool_text
    )
    missing_profiles = sorted(
        name for name in get_harness_profiles() if f"`{name}`" not in tool_text
    )
    canonical_templates = sorted(name for name in BUILTIN_TEMPLATES if "_" not in name)
    missing_templates = [name for name in canonical_templates if f"`{name}`" not in harness_text]

    model_pack_dir = root / "src" / "superqode" / "local" / "data" / "model-packs"
    missing_model_packs = sorted(
        path.stem
        for path in model_pack_dir.glob("*.yaml")
        if f"`{path.stem}`" not in documentation and f" {path.stem} " not in documentation
    )

    tui_roots = sorted({command.split()[0] for command in COMMANDS if command.startswith(":")})
    missing_tui_roots = [root for root in tui_roots if f"`{root}`" not in tui_text]

    assert missing_runtimes == []
    assert missing_tools == []
    assert missing_profiles == []
    assert missing_templates == []
    assert missing_model_packs == []
    assert missing_tui_roots == []


def test_superqode_environment_variables_are_in_the_environment_reference():
    """Every source-level SUPERQODE environment variable stays in one reference."""

    root = Path(__file__).resolve().parents[1]
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "src" / "superqode").rglob("*.py"))
    )
    environment_text = (root / "docs" / "configuration" / "environment-variables.md").read_text(
        encoding="utf-8"
    )
    internal_constants = {
        "SUPERQODE_CSS",
        "SUPERQODE_DIR",
        "SUPERQODE_ICONS",
        "SUPERQODE_REF",
        "SUPERQODE_REVIEW",
        "SUPERQODE_SENTINEL_4",
    }

    source_names = set(re.findall(r"SUPERQODE_[A-Z0-9_]+", source_text))
    public_names = {
        name
        for name in source_names
        if name not in internal_constants and not name.startswith("SUPERQODE_CODE_BLOCK_")
    }
    missing = sorted(name for name in public_names if f"`{name}`" not in environment_text)

    assert missing == []


def test_optional_dependency_extras_are_in_the_installation_reference():
    """Every published package extra should be discoverable before installation."""

    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    installation_text = (root / "docs" / "getting-started" / "installation.md").read_text(
        encoding="utf-8"
    )
    extras = project["project"]["optional-dependencies"]

    missing = sorted(name for name in extras if f"`{name}`" not in installation_text)

    assert missing == []
