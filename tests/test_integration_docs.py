"""Coverage checks for the public integrations catalog."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml


CONTRIBUTOR_EXTRAS = {
    "dev",
    "docs",
    "linters",
    "performance",
    "testing",
    "ui-testing",
}


def _integration_documentation(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "docs" / "integrations").glob("*.md"))
    )


def test_integration_catalog_covers_every_runtime_extra():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    catalog = _integration_documentation(root)

    optional_extras = set(project["project"]["optional-dependencies"])
    runtime_extras = optional_extras - CONTRIBUTOR_EXTRAS
    missing = sorted(extra for extra in runtime_extras if f"superqode[{extra}]" not in catalog)

    assert missing == []


def test_documentation_does_not_reference_unknown_superqode_extras():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    known_extras = set(project["project"]["optional-dependencies"])
    documentation = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((root / "docs").rglob("*.md"))
    )

    documented_extras = set(re.findall(r"superqode\[([a-z0-9-]+)\]", documentation))
    assert sorted(documented_extras - known_extras) == []


def test_integration_catalog_covers_the_public_integration_families():
    root = Path(__file__).resolve().parents[1]
    catalog = _integration_documentation(root)

    required_sections = {
        "# Coding agents",
        "# Models and inference",
        "# Runtimes and harnesses",
        "# Protocols and tools",
        "# Optimization",
        "# Memory",
        "# Sandboxes",
        "# Observability",
        "# Remote interfaces",
        "# Dependency compatibility",
        "## Diagnose an integration",
    }
    required_integrations = {
        "OpenAI Codex",
        "Anthropic Claude",
        "GitHub Copilot",
        "Google Antigravity",
        "xAI Grok",
        "Kimi Code",
        "Qwen Code",
        "LiteLLM",
        "OpenResponses",
        "Ollama",
        "LM Studio",
        "vLLM",
        "SGLang",
        "Hugging Face TGI",
        "MLX",
        "Google Agent Development Kit",
        "OpenAI Agents SDK",
        "PydanticAI",
        "DeepAgents",
        "RLM Code",
        "Hugging Face Tau",
        "Omnigent",
        "Agent Client Protocol",
        "Model Context Protocol",
        "Agent2Agent",
        "CocoIndex Code",
        "Monty Python REPL",
        "GEPA Omni",
        "AutoResearch",
        "MetaHarness",
        "Mem0",
        "Cognee",
        "Supermemory",
        "E2B",
        "Daytona",
        "Modal",
        "Vercel Sandbox",
        "OpenTelemetry",
        "MLflow",
        "LangSmith",
        "Logfire",
        "Arize Phoenix",
        "Telegram",
        "Slack",
        "Discord",
    }

    assert sorted(section for section in required_sections if section not in catalog) == []
    assert (
        sorted(integration for integration in required_integrations if integration not in catalog)
        == []
    )


def test_integrations_is_a_top_level_tab_without_expanding_desktop_navigation():
    root = Path(__file__).resolve().parents[1]
    mkdocs = (root / "mkdocs.yml").read_text(encoding="utf-8")
    nav_yaml = "nav:\n" + mkdocs.split("\nnav:\n", maxsplit=1)[1]
    config = yaml.safe_load(nav_yaml)
    navigation = config["nav"]
    labels = [next(iter(entry)) for entry in navigation]

    assert labels == [
        "🚀 Quick Start",
        "🔌 Connect",
        "⚓ Build Harness",
        "🔁 A2A",
        "📈 Evaluate & Optimise",
        "🛠️ Operate",
        "🔗 Integrations",
        "📚 Reference",
    ]
    quick_start_navigation = navigation[0]["🚀 Quick Start"]
    assert quick_start_navigation[0] == {"⚡ Quick Start": "getting-started/quickstart.md"}
    assert {
        "📘 Complete Getting Started Guide": "getting-started/complete-guide.md"
    } in quick_start_navigation
    integration_navigation = navigation[6]["🔗 Integrations"]
    assert integration_navigation == [
        {"🧭 Integration Overview": "integrations/index.md"},
        {"📋 All Integrations": "integrations/all.md"},
        {"🤖 Coding Agents": "integrations/coding-agents.md"},
        {"🧠 Models & Inference": "integrations/models-inference.md"},
        {"⚙️ Runtimes & Harnesses": "integrations/runtimes-harnesses.md"},
        {"🔌 Protocols & Tools": "integrations/protocols-tools.md"},
        {"📈 Optimization": "integrations/optimization.md"},
        {"🧠 Memory": "integrations/memory.md"},
        {"🏖️ Sandboxes": "integrations/sandboxes.md"},
        {"📊 Observability": "integrations/observability.md"},
        {"📱 Remote Interfaces": "integrations/remote-interfaces.md"},
        {"🧩 Dependency Compatibility": "integrations/dependency-compatibility.md"},
    ]


def test_quick_start_covers_the_first_session_and_first_harness():
    root = Path(__file__).resolve().parents[1]
    quick_start = (root / "docs" / "getting-started" / "quickstart.md").read_text(encoding="utf-8")

    required_commands = {
        "superqode --version",
        ":connect local ollama qwen3:8b",
        ":connect acp",
        ":connect byok",
        ":connect codex",
        ":connect antigravity",
        ":connect grok",
        "superqode harness list",
        ":harness",
        "superqode harness init",
        "superqode harness validate",
        "superqode harness doctor",
    }

    assert sorted(command for command in required_commands if command not in quick_start) == []
    assert (root / "docs" / "getting-started" / "complete-guide.md").is_file()
