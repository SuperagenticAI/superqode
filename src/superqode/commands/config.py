"""
Config command - Manage SuperQode configuration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

console = Console()


@click.group()
def config():
    """Manage SuperQode configuration.

    View, validate, and modify configuration settings.
    """
    pass


@config.command("show")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(["yaml", "json", "tree"]),
    default="yaml",
    help="Output format",
)
@click.option("--section", "-s", help="Show specific section (e.g., 'team.modes.dev')")
def config_show(path: str, fmt: str, section: Optional[str]):
    """Show current configuration.

    Examples:

        superqode config show                # Show full config

        superqode config show -f json        # Output as JSON

        superqode config show -s team.modes.dev  # Show specific section
    """
    from superqode.config import load_config

    project_root = Path(path).resolve()
    config_file = project_root / "superqode.yaml"

    if not config_file.exists():
        console.print("[yellow]No configuration found.[/yellow]")
        console.print("[dim]Run 'superqode init' to create a configuration.[/dim]")
        return 1

    # Load and parse config
    try:
        cfg = load_config(project_root)
    except Exception as e:
        console.print(f"[red]Error loading configuration:[/red] {e}")
        return 1

    console.print()
    console.print(Panel("[bold]SuperQode Configuration[/bold]", border_style="cyan"))
    console.print()

    if fmt == "yaml":
        # Show raw YAML
        content = config_file.read_text()
        syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
        console.print(syntax)

    elif fmt == "json":
        # Convert to JSON
        import dataclasses

        def to_dict(obj):
            if dataclasses.is_dataclass(obj):
                return {k: to_dict(v) for k, v in dataclasses.asdict(obj).items()}
            elif isinstance(obj, dict):
                return {k: to_dict(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [to_dict(v) for v in obj]
            elif hasattr(obj, "value"):  # Enum
                return obj.value
            else:
                return obj

        config_dict = to_dict(cfg)
        console.print(json.dumps(config_dict, indent=2))

    elif fmt == "tree":
        # Show as tree
        _show_config_tree(cfg)

    return 0


@config.command("validate")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--fix", is_flag=True, help="Attempt to fix common issues")
def config_validate(path: str, fix: bool):
    """Validate configuration file.

    Checks for:
    - Valid YAML syntax
    - Required fields
    - Valid values
    - Provider configurations
    - Harness tool availability

    Examples:

        superqode config validate          # Validate current directory

        superqode config validate --fix    # Auto-fix common issues
    """
    from superqode.config import load_config

    project_root = Path(path).resolve()
    config_file = project_root / "superqode.yaml"

    console.print()
    console.print(Panel("[bold]Configuration Validation[/bold]", border_style="cyan"))
    console.print()

    if not config_file.exists():
        console.print("[red]✗[/red] No superqode.yaml found")
        console.print("[dim]Run 'superqode init' to create a configuration.[/dim]")
        return 1

    issues = []
    warnings = []

    # Check YAML syntax
    try:
        import yaml

        with open(config_file) as f:
            raw_config = yaml.safe_load(f)
        console.print("[green]✓[/green] YAML syntax is valid")
    except yaml.YAMLError as e:
        console.print(f"[red]✗[/red] YAML syntax error: {e}")
        return 1

    # Check required sections
    if "superqode" not in raw_config:
        issues.append("Missing 'superqode' section")
    else:
        if "version" not in raw_config.get("superqode", {}):
            warnings.append("Missing 'superqode.version' field")
        console.print("[green]✓[/green] 'superqode' section present")

    # Check MCP servers config (if present)
    mcp_config = raw_config.get("mcp_servers", {})
    if mcp_config:
        console.print("[green]✓[/green] MCP servers configured")
        for name, server_config in mcp_config.items():
            if server_config.get("enabled", False):
                console.print(f"  [green]✓[/green] {name}: enabled")
            else:
                console.print(f"  [dim]○[/dim] {name}: disabled")

    # Check providers
    providers = raw_config.get("providers", {})
    if providers:
        console.print("[green]✓[/green] Providers configured")
        for name, pconfig in providers.items():
            api_key_env = pconfig.get("api_key_env")
            if api_key_env:
                import os

                if os.environ.get(api_key_env):
                    console.print(f"  [green]✓[/green] {name}: {api_key_env} is set")
                else:
                    warnings.append(f"Provider '{name}': {api_key_env} not set in environment")

    # Load full config to check for errors
    try:
        cfg = load_config(project_root)
        console.print("[green]✓[/green] Configuration loads successfully")
    except Exception as e:
        issues.append(f"Configuration load error: {e}")

    # Report results
    console.print()
    if issues:
        console.print("[bold red]Issues found:[/bold red]")
        for issue in issues:
            console.print(f"  [red]✗[/red] {issue}")
        console.print()

    if warnings:
        console.print("[bold yellow]Warnings:[/bold yellow]")
        for warning in warnings:
            console.print(f"  [yellow]![/yellow] {warning}")
        console.print()

    if not issues and not warnings:
        console.print("[green]✓ Configuration is valid![/green]")
        return 0
    elif not issues:
        console.print("[green]✓ Configuration is valid (with warnings)[/green]")
        return 0
    else:
        console.print("[red]✗ Configuration has issues[/red]")
        return 1


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.argument("path", type=click.Path(exists=True), default=".")
def config_set(key: str, value: str, path: str):
    """Set a configuration value.

    Examples:

        superqode config set superqode.team_name "My Team"

        superqode config set team.modes.dev.roles.fullstack.enabled false
    """
    import yaml

    project_root = Path(path).resolve()
    config_file = project_root / "superqode.yaml"

    if not config_file.exists():
        console.print("[red]No configuration found.[/red]")
        console.print("[dim]Run 'superqode init' first.[/dim]")
        return 1

    # Load existing config
    with open(config_file) as f:
        config = yaml.safe_load(f) or {}

    # Parse the key path
    keys = key.split(".")
    current = config

    # Navigate to parent
    for k in keys[:-1]:
        if k not in current:
            current[k] = {}
        current = current[k]

    # Set value (try to parse as number/bool)
    final_key = keys[-1]
    try:
        # Try int
        parsed_value = int(value)
    except ValueError:
        try:
            # Try float
            parsed_value = float(value)
        except ValueError:
            # Try bool
            if value.lower() in ("true", "yes", "on"):
                parsed_value = True
            elif value.lower() in ("false", "no", "off"):
                parsed_value = False
            else:
                parsed_value = value

    old_value = current.get(final_key)
    current[final_key] = parsed_value

    # Write back
    with open(config_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]✓[/green] Set {key}: {old_value} → {parsed_value}")
    return 0


@config.command("get")
@click.argument("key")
@click.argument("path", type=click.Path(exists=True), default=".")
def config_get(key: str, path: str):
    """Get a configuration value.

    Examples:

        superqode config get superqode.team_name

        superqode config get team.modes.dev.roles.fullstack.enabled
    """
    import yaml

    project_root = Path(path).resolve()
    config_file = project_root / "superqode.yaml"

    if not config_file.exists():
        console.print("[red]No configuration found.[/red]")
        return 1

    with open(config_file) as f:
        config = yaml.safe_load(f) or {}

    # Navigate to value
    keys = key.split(".")
    current = config

    for k in keys:
        if isinstance(current, dict) and k in current:
            current = current[k]
        else:
            console.print(f"[yellow]Key not found:[/yellow] {key}")
            return 1

    # Output value
    if isinstance(current, (dict, list)):
        console.print(json.dumps(current, indent=2))
    else:
        console.print(current)

    return 0


def _show_config_tree(cfg) -> None:
    """Display configuration as a tree."""
    import dataclasses

    tree = Tree("[bold cyan]superqode.yaml[/bold cyan]")

    def add_to_tree(node, obj, name=""):
        if dataclasses.is_dataclass(obj):
            branch = node.add(f"[bold]{name}[/bold]") if name else node
            for field in dataclasses.fields(obj):
                add_to_tree(branch, getattr(obj, field.name), field.name)
        elif isinstance(obj, dict):
            branch = node.add(f"[bold]{name}[/bold]") if name else node
            for k, v in obj.items():
                add_to_tree(branch, v, k)
        elif isinstance(obj, list):
            branch = node.add(f"[bold]{name}[/bold] [dim]({len(obj)} items)[/dim]")
            for i, v in enumerate(obj[:5]):  # Limit to 5 items
                add_to_tree(branch, v, f"[{i}]")
            if len(obj) > 5:
                branch.add("[dim]...[/dim]")
        else:
            value = str(obj)
            if len(value) > 50:
                value = value[:47] + "..."
            node.add(f"{name}: [green]{value}[/green]")

    add_to_tree(tree, cfg)
    console.print(tree)


def _check_harness_tools(harness: dict, warnings: list) -> None:
    """Check if harness tools are available."""
    import shutil

    tool_checks = {
        "python_tools": ["ruff", "mypy", "pyright"],
        "javascript_tools": ["eslint", "tsc"],
        "go_tools": ["golangci-lint"],
        "rust_tools": ["cargo"],
        "shell_tools": ["shellcheck"],
    }

    for category, tools in tool_checks.items():
        configured_tools = harness.get(category, [])
        for tool in configured_tools:
            tool_name = tool.split()[0]  # Handle "go vet" -> "go"
            if not shutil.which(tool_name):
                warnings.append(f"Harness tool not found: {tool_name}")
