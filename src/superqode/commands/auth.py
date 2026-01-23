"""
Auth CLI commands for SuperQode.

Commands for showing authentication information and security details.
SuperQode NEVER stores API keys - this shows where keys are stored
and who controls them.
"""

import os
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..providers.registry import PROVIDERS, ProviderCategory
from ..agents.registry import AGENTS, AgentStatus


console = Console()


@click.group()
def auth():
    """Show authentication and security information."""
    pass


@auth.command("info")
def auth_info():
    """Show comprehensive auth information."""

    # Header
    console.print(
        Panel(
            "[bold]🔒 SECURITY PRINCIPLE:[/bold] SuperQode [bold red]NEVER[/bold red] stores your API keys.\n\n"
            "All credentials are read from YOUR environment at runtime.\n"
            "You control where and how your keys are stored.",
            title="SuperQode Auth Information",
            border_style="cyan",
        )
    )

    console.print()

    # BYOK Section
    console.print("[bold cyan]═══ BYOK MODE (Direct LLM) ═══[/bold cyan]")
    console.print()
    console.print("Your API keys are read from YOUR environment variables:")
    console.print()

    # Build provider status table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Provider", style="white")
    table.add_column("Env Variable", style="dim")
    table.add_column("Status", style="white")
    table.add_column("Source", style="dim")

    # Check common providers
    priority_providers = [
        "anthropic",
        "openai",
        "google",
        "xai",
        "deepseek",
        "groq",
        "openrouter",
        "ollama",
        "zhipu",
        "alibaba",
    ]

    for provider_id in priority_providers:
        provider_def = PROVIDERS.get(provider_id)
        if not provider_def:
            continue

        # Check env vars
        configured = False
        configured_var = None

        for env_var in provider_def.env_vars:
            if os.environ.get(env_var):
                configured = True
                configured_var = env_var
                break

        if not provider_def.env_vars:
            # Local provider
            status = "[blue]🏠 Local[/blue]"
            source = provider_def.default_base_url or "localhost"
        elif configured:
            status = "[green]✅ Set[/green]"
            source = _detect_env_source(configured_var)
        else:
            status = "[red]❌ Not set[/red]"
            source = "-"

        env_var_display = provider_def.env_vars[0] if provider_def.env_vars else "(none)"

        table.add_row(
            provider_id,
            env_var_display,
            status,
            source,
        )

    console.print(table)
    console.print()
    console.print("[dim]💡 Keys are read at runtime, never stored by SuperQode[/dim]")
    console.print()

    # ACP Section
    console.print("[bold cyan]═══ ACP MODE (Coding Agents) ═══[/bold cyan]")
    console.print()
    console.print("Agent authentication is managed by each agent, not SuperQode:")
    console.print()

    # Build agent status table
    agent_table = Table(show_header=True, header_style="bold")
    agent_table.add_column("Agent", style="white")
    agent_table.add_column("Auth Location", style="dim")
    agent_table.add_column("Status", style="white")

    for agent_id, agent_def in AGENTS.items():
        if agent_def.status != AgentStatus.SUPPORTED:
            continue

        # Check if agent auth exists
        auth_exists = _check_agent_auth(agent_id)
        status = "[green]✅ Configured[/green]" if auth_exists else "[yellow]⚠️ Check agent[/yellow]"

        agent_table.add_row(
            agent_id,
            agent_def.auth_info,
            status,
        )

    console.print(agent_table)
    console.print()
    console.print("[dim]💡 Agent auth is managed by the agent itself, not SuperQode[/dim]")
    console.print("[dim]💡 Run the agent directly to configure: e.g., 'opencode' → /connect[/dim]")
    console.print()

    # Data Flow Section
    console.print("[bold cyan]═══ DATA FLOW ═══[/bold cyan]")
    console.print()
    console.print("[bold]BYOK:[/bold]  You → SuperQode → LiteLLM → Provider API")
    console.print("[bold]ACP:[/bold]   You → SuperQode → Agent (e.g., opencode) → Provider API")
    console.print()
    console.print("[dim]SuperQode is a pass-through orchestrator. Your data goes directly[/dim]")
    console.print("[dim]to the LLM provider or agent. We don't intercept or store anything.[/dim]")


@auth.command("check")
@click.argument("provider_or_agent")
def auth_check(provider_or_agent: str):
    """Check auth status for a specific provider or agent."""

    # Check if it's a provider
    provider_def = PROVIDERS.get(provider_or_agent)
    if provider_def:
        _check_provider_auth(provider_or_agent, provider_def)
        return

    # Check if it's an agent
    agent_def = AGENTS.get(provider_or_agent)
    if agent_def:
        _check_agent_auth_detailed(provider_or_agent, agent_def)
        return

    console.print(f"[red]Error: '{provider_or_agent}' not found as provider or agent[/red]")
    console.print(
        "\nUse 'superqode providers list' or 'superqode agents list' to see available options."
    )


def _detect_env_source(env_var: str) -> str:
    """Try to detect where an env var is set."""
    # This is a best-effort detection
    home = Path.home()

    # Check common shell config files
    shell_files = [
        home / ".zshrc",
        home / ".bashrc",
        home / ".bash_profile",
        home / ".profile",
    ]

    for shell_file in shell_files:
        if shell_file.exists():
            try:
                content = shell_file.read_text()
                if env_var in content:
                    return f"~/{shell_file.name}"
            except Exception:
                pass

    # Check .env file in current directory
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        try:
            content = env_file.read_text()
            if env_var in content:
                return ".env"
        except Exception:
            pass

    return "environment"


def _check_agent_auth(agent_id: str) -> bool:
    """Check if agent auth exists."""
    if agent_id == "opencode":
        auth_file = Path.home() / ".local" / "share" / "opencode" / "auth.json"
        return auth_file.exists()
    return False


def _check_provider_auth(provider_id: str, provider_def):
    """Check and display provider auth status."""
    console.print(f"\n[bold]Provider: {provider_def.name}[/bold]")
    console.print()

    if not provider_def.env_vars:
        console.print("[blue]🏠 Local provider - no API key required[/blue]")
        if provider_def.default_base_url:
            console.print(f"Default URL: {provider_def.default_base_url}")
        return

    configured = False
    for env_var in provider_def.env_vars:
        value = os.environ.get(env_var)
        if value:
            configured = True
            # Mask the key
            masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
            source = _detect_env_source(env_var)
            console.print(f"[green]✅ {env_var}[/green] = {masked}")
            console.print(f"   Source: {source}")
        else:
            console.print(f"[red]❌ {env_var}[/red] = (not set)")

    if not configured:
        console.print()
        console.print("[yellow]To configure:[/yellow]")
        console.print(f'  export {provider_def.env_vars[0]}="your-api-key"')
        console.print(f"\n  Get your key at: {provider_def.docs_url}")


def _check_agent_auth_detailed(agent_id: str, agent_def):
    """Check and display agent auth status."""
    console.print(f"\n[bold]Agent: {agent_def.name}[/bold]")
    console.print()

    console.print(f"[bold]Auth managed by:[/bold] {agent_def.name} (not SuperQode)")
    console.print(f"[bold]Auth location:[/bold] {agent_def.auth_info}")
    console.print()

    if agent_id == "opencode":
        auth_file = Path.home() / ".local" / "share" / "opencode" / "auth.json"
        if auth_file.exists():
            console.print(f"[green]✅ Auth file exists:[/green] {auth_file}")
        else:
            console.print(f"[yellow]⚠️ Auth file not found:[/yellow] {auth_file}")
            console.print()
            console.print("[yellow]To configure:[/yellow]")
            console.print(f"  {agent_def.setup_command}")
    else:
        console.print(f"[dim]Setup: {agent_def.setup_command}[/dim]")


# Register with main CLI
def register_commands(cli):
    """Register auth commands with the main CLI."""
    cli.add_command(auth)
