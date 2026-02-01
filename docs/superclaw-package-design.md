# SuperClaw: Agent Security Testing Framework

## Overview

**SuperClaw** is a dedicated package for testing and breaking AI coding agents. It uses CodeOptiX behaviors and Bloom scenario generation to systematically identify vulnerabilities in agents like OpenClaw, Claude Code, Codex, and others.

```
┌─────────────────────────────────────────────────────────────┐
│                  Superagentic AI Ecosystem                  │
├─────────────────────────────────────────────────────────────┤
│  SuperQode    │  TUI interface for SuperQE, CI/automation  │
│  SuperQE      │  Quality Engineering core engine            │
│  SuperClaw    │  Agent security testing framework (NEW)     │
│  CodeOptiX    │  Code optimization & evaluation engine      │
│  Bloom        │  Behavioral evaluation scenario generation  │
└─────────────────────────────────────────────────────────────┘
```

---

## Package Structure

```
superclaw/
├── src/
│   └── superclaw/
│       ├── __init__.py
│       ├── cli.py                    # CLI entry point
│       ├── main.py                   # Main application
│       │
│       ├── attacks/                  # Attack implementations
│       │   ├── __init__.py
│       │   ├── prompt_injection.py   # Prompt injection attacks
│       │   ├── tool_bypass.py        # Tool policy bypass
│       │   ├── sandbox_escape.py     # Sandbox escape attempts
│       │   ├── session_hijack.py     # Session boundary testing
│       │   ├── encoding.py           # Encoding obfuscation
│       │   └── jailbreaks.py         # Jailbreak techniques
│       │
│       ├── behaviors/                # Security behaviors
│       │   ├── __init__.py
│       │   ├── base.py               # Base behavior class
│       │   ├── injection_resistance.py
│       │   ├── tool_policy.py
│       │   ├── sandbox_isolation.py
│       │   ├── session_boundary.py
│       │   ├── config_drift.py
│       │   └── protocol_security.py
│       │
│       ├── adapters/                 # Agent adapters
│       │   ├── __init__.py
│       │   ├── base.py               # Base adapter
│       │   ├── openclaw.py           # OpenClaw adapter
│       │   ├── claude_code.py        # Claude Code adapter
│       │   ├── codex.py              # Codex adapter
│       │   └── gemini.py             # Gemini CLI adapter
│       │
│       ├── bloom/                    # Bloom integration
│       │   ├── __init__.py
│       │   ├── scenarios.py          # Scenario generation
│       │   ├── ideation.py           # Ideation stage
│       │   ├── rollout.py            # Rollout stage
│       │   └── judgment.py           # Judgment stage
│       │
│       ├── reporting/                # Report generation
│       │   ├── __init__.py
│       │   ├── html.py               # HTML reports
│       │   ├── json.py               # JSON reports
│       │   └── sarif.py              # SARIF format (for CI)
│       │
│       └── config/                   # Configuration
│           ├── __init__.py
│           ├── settings.py
│           └── schemas.py
│
├── tests/
│   └── ...
│
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## CLI Commands

```bash
# Install
pip install superclaw
# or
uv pip install superclaw

# ============================================================
# ATTACK COMMANDS
# ============================================================

# Attack OpenClaw agent
superclaw attack openclaw --target ws://127.0.0.1:18789 \
  --behaviors injection,tool-policy,sandbox

# Attack Claude Code
superclaw attack claude-code --workspace /path/to/project

# Attack any ACP-compatible agent
superclaw attack acp --command "opencode acp" --project /path

# ============================================================
# SCENARIO GENERATION (Bloom)
# ============================================================

# Generate attack scenarios
superclaw generate --behavior prompt-injection \
  --num-scenarios 20 \
  --output scenarios.json

# Generate with variations
superclaw generate --behavior tool-bypass \
  --variations noise,emotional_pressure

# ============================================================
# EVALUATION
# ============================================================

# Evaluate agent against behaviors
superclaw evaluate openclaw \
  --scenarios scenarios.json \
  --behaviors all

# Run specific attack techniques
superclaw evaluate openclaw \
  --techniques encoding,jailbreak,multi-turn

# ============================================================
# SECURITY AUDIT
# ============================================================

# Full security audit
superclaw audit openclaw --target ws://127.0.0.1:18789 \
  --comprehensive \
  --report-format html \
  --output audit-report.html

# Quick security check
superclaw audit openclaw --quick

# ============================================================
# REPORTING
# ============================================================

# Generate report from results
superclaw report --input results.json --format html

# SARIF output for CI/CD
superclaw report --input results.json --format sarif

# ============================================================
# CONFIGURATION
# ============================================================

# Initialize config
superclaw init

# Validate config
superclaw config validate

# Show available behaviors
superclaw behaviors list

# Show available attacks
superclaw attacks list
```

---

## pyproject.toml

```toml
[project]
name = "superclaw"
version = "0.1.0"
description = "Agent Security Testing Framework - Break AI coding agents with CodeOptiX and Bloom"
authors = [
    { name = "Superagentic AI", email = "team@super-agentic.ai" }
]
readme = "README.md"
license = { text = "Apache-2.0" }
requires-python = ">=3.12"
keywords = [
    "ai",
    "agent",
    "security",
    "testing",
    "llm",
    "prompt-injection",
    "red-team",
    "openclaw",
    "codeoptix",
    "bloom"
]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3.12",
    "Topic :: Security",
    "Topic :: Software Development :: Testing",
]

dependencies = [
    "typer>=0.12.0",
    "rich>=13.0.0",
    "pydantic>=2.0.0",
    "httpx>=0.27.0",
    "websockets>=12.0",
    "codeoptix>=0.1.0",
    "litellm>=1.40.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=4.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
    "mypy>=1.10.0",
]
docs = [
    "mkdocs>=1.5.0",
    "mkdocs-material>=9.0.0",
]

[project.scripts]
superclaw = "superclaw.cli:app"

[project.urls]
Homepage = "https://github.com/SuperagenticAI/superclaw"
Documentation = "https://superagenticai.github.io/superclaw/"
Repository = "https://github.com/SuperagenticAI/superclaw"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/superclaw"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## Core Implementation

### cli.py

```python
"""SuperClaw CLI - Agent Security Testing Framework."""

import typer
from rich.console import Console
from typing import Optional, List

app = typer.Typer(
    name="superclaw",
    help="🦞 SuperClaw - Break AI coding agents with style",
    no_args_is_help=True,
)
console = Console()

# Sub-commands
attack_app = typer.Typer(help="Attack AI agents")
generate_app = typer.Typer(help="Generate attack scenarios")
evaluate_app = typer.Typer(help="Evaluate agent security")
audit_app = typer.Typer(help="Run security audits")
report_app = typer.Typer(help="Generate reports")

app.add_typer(attack_app, name="attack")
app.add_typer(generate_app, name="generate")
app.add_typer(evaluate_app, name="evaluate")
app.add_typer(audit_app, name="audit")
app.add_typer(report_app, name="report")


@attack_app.command("openclaw")
def attack_openclaw(
    target: str = typer.Option("ws://127.0.0.1:18789", help="OpenClaw gateway URL"),
    behaviors: str = typer.Option("all", help="Comma-separated behaviors to test"),
    techniques: str = typer.Option("all", help="Attack techniques to use"),
    output: Optional[str] = typer.Option(None, help="Output file for results"),
):
    """Attack an OpenClaw agent."""
    console.print(f"[bold red]🦞 SuperClaw attacking OpenClaw[/bold red]")
    console.print(f"   Target: {target}")
    console.print(f"   Behaviors: {behaviors}")
    console.print(f"   Techniques: {techniques}")

    from superclaw.attacks import run_attack
    results = run_attack(
        agent="openclaw",
        target=target,
        behaviors=behaviors.split(","),
        techniques=techniques.split(","),
    )

    if output:
        import json
        with open(output, "w") as f:
            json.dump(results, f, indent=2)
        console.print(f"[green]Results saved to {output}[/green]")


@attack_app.command("acp")
def attack_acp(
    command: str = typer.Option(..., help="ACP agent command"),
    project: str = typer.Option(".", help="Project directory"),
    behaviors: str = typer.Option("all", help="Comma-separated behaviors"),
):
    """Attack any ACP-compatible agent."""
    console.print(f"[bold red]🦞 SuperClaw attacking ACP agent[/bold red]")
    console.print(f"   Command: {command}")
    console.print(f"   Project: {project}")


@generate_app.command()
def generate(
    behavior: str = typer.Option(..., help="Target behavior"),
    num_scenarios: int = typer.Option(10, help="Number of scenarios"),
    variations: str = typer.Option("noise,emotional_pressure", help="Variation dimensions"),
    output: str = typer.Option("scenarios.json", help="Output file"),
):
    """Generate attack scenarios using Bloom."""
    console.print(f"[bold cyan]🌸 Generating scenarios with Bloom[/bold cyan]")
    console.print(f"   Behavior: {behavior}")
    console.print(f"   Scenarios: {num_scenarios}")
    console.print(f"   Variations: {variations}")

    from superclaw.bloom import generate_scenarios
    scenarios = generate_scenarios(
        behavior=behavior,
        num_scenarios=num_scenarios,
        variation_dimensions=variations.split(","),
    )

    import json
    with open(output, "w") as f:
        json.dump(scenarios, f, indent=2)
    console.print(f"[green]Scenarios saved to {output}[/green]")


@audit_app.command("openclaw")
def audit_openclaw(
    target: str = typer.Option("ws://127.0.0.1:18789", help="OpenClaw gateway URL"),
    comprehensive: bool = typer.Option(False, help="Run comprehensive audit"),
    quick: bool = typer.Option(False, help="Quick security check"),
    report_format: str = typer.Option("html", help="Report format: html, json, sarif"),
    output: str = typer.Option("audit-report", help="Output file (without extension)"),
):
    """Run security audit on OpenClaw agent."""
    console.print(f"[bold yellow]🔍 SuperClaw Security Audit[/bold yellow]")
    console.print(f"   Target: {target}")
    console.print(f"   Mode: {'Comprehensive' if comprehensive else 'Quick' if quick else 'Standard'}")

    from superclaw.audit import run_audit
    results = run_audit(
        agent="openclaw",
        target=target,
        mode="comprehensive" if comprehensive else "quick" if quick else "standard",
    )

    from superclaw.reporting import generate_report
    output_file = f"{output}.{report_format}"
    generate_report(results, format=report_format, output=output_file)
    console.print(f"[green]Report saved to {output_file}[/green]")


@app.command("behaviors")
def list_behaviors():
    """List available security behaviors."""
    from superclaw.behaviors import BEHAVIOR_REGISTRY

    console.print("[bold]Available Behaviors:[/bold]")
    for name, behavior_class in BEHAVIOR_REGISTRY.items():
        console.print(f"  • {name}")


@app.command("attacks")
def list_attacks():
    """List available attack techniques."""
    attacks = [
        ("prompt-injection", "Direct and indirect prompt injection"),
        ("encoding", "Base64, hex, unicode, typoglycemia obfuscation"),
        ("jailbreak", "DAN, grandmother, role-play techniques"),
        ("tool-bypass", "Tool policy bypass via aliases"),
        ("sandbox-escape", "Container escape attempts"),
        ("multi-turn", "Multi-turn persistent attacks"),
    ]

    console.print("[bold]Available Attack Techniques:[/bold]")
    for name, desc in attacks:
        console.print(f"  • {name}: {desc}")


@app.command("init")
def init_config():
    """Initialize SuperClaw configuration."""
    console.print("[bold]Initializing SuperClaw...[/bold]")
    # Create config files
    console.print("[green]✓ Configuration initialized[/green]")


@app.command("version")
def version():
    """Show SuperClaw version."""
    from superclaw import __version__
    console.print(f"SuperClaw v{__version__}")


def main():
    app()


if __name__ == "__main__":
    main()
```

---

## README.md

```markdown
# 🦞 SuperClaw

**Agent Security Testing Framework** - Break AI coding agents with CodeOptiX and Bloom

[![PyPI version](https://badge.fury.io/py/superclaw.svg)](https://pypi.org/project/superclaw/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

SuperClaw is a comprehensive security testing framework for AI coding agents. It uses [CodeOptiX](https://github.com/SuperagenticAI/codeoptix) behaviors and [Bloom](https://github.com/safety-research/bloom) scenario generation to systematically identify vulnerabilities.

## Supported Agents

- 🦞 **OpenClaw** - Full support via ACP
- 🤖 **Claude Code** - Via ACP adapter
- 📝 **Codex** - Via API adapter
- 💎 **Gemini CLI** - Via CLI adapter
- 🔧 **Custom Agents** - Via ACP or custom adapters

## Quick Start

```bash
# Install
pip install superclaw

# Attack OpenClaw
superclaw attack openclaw --target ws://127.0.0.1:18789

# Generate attack scenarios
superclaw generate --behavior prompt-injection --num-scenarios 20

# Run security audit
superclaw audit openclaw --comprehensive --report-format html
```

## Attack Techniques

| Technique | Description |
|-----------|-------------|
| `prompt-injection` | Direct/indirect injection attacks |
| `encoding` | Base64, hex, unicode obfuscation |
| `jailbreak` | DAN, grandmother, role-play |
| `tool-bypass` | Tool policy bypass via aliases |
| `sandbox-escape` | Container escape attempts |
| `multi-turn` | Persistent multi-turn attacks |

## Security Behaviors

| Behavior | Description |
|----------|-------------|
| `prompt-injection-resistance` | Tests injection detection |
| `tool-policy-enforcement` | Tests allow/deny lists |
| `sandbox-isolation` | Tests container boundaries |
| `session-boundary-integrity` | Tests session isolation |
| `configuration-drift-detection` | Tests config stability |
| `acp-protocol-security` | Tests protocol handling |

## Part of Superagentic AI Ecosystem

- **SuperQode** - TUI interface for SuperQE
- **SuperQE** - Quality Engineering core
- **SuperClaw** - Agent security testing (this package)
- **CodeOptiX** - Code optimization engine

## License

Apache 2.0
```

---

## Relationship with SuperQode

SuperQode can optionally integrate SuperClaw for security testing:

```python
# superqode/integrations/superclaw.py

def run_superclaw_audit(target: str) -> dict:
    """Run SuperClaw security audit from SuperQode."""
    try:
        from superclaw.audit import run_audit
        return run_audit(agent="openclaw", target=target)
    except ImportError:
        raise RuntimeError("SuperClaw not installed. Run: pip install superclaw")
```

SuperQode command (optional):
```bash
# If user has superclaw installed, SuperQode can invoke it
superqode security --agent openclaw --target ws://127.0.0.1:18789
# This internally calls superclaw
```

---

## Next Steps

1. Create the superclaw package structure
2. Implement core attack engine
3. Port behaviors from the plan to superclaw/behaviors/
4. Implement Bloom integration
5. Create adapters for each agent type
6. Add reporting (HTML, JSON, SARIF)

Want me to start creating the actual package files?
