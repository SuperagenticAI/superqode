"""
Auth CLI commands for SuperQode.

Commands for showing authentication information and security details.

SuperQode supports three auth modes:
1. BYOK (env vars) - Primary, never stored
2. Local storage (~/.superqode/auth.json) - Optional, secure file storage
3. ACP - Delegated to agents
"""

import os
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from ..providers.registry import PROVIDERS, ProviderCategory
from ..agents.registry import AGENTS, AgentStatus
from ..auth import (
    get_storage,
    get,
    set as auth_set,
    remove,
    all as auth_all,
    ApiAuth,
    OAuthAuth,
)


console = Console()


@click.group()
def auth():
    """Manage API keys and view authentication status.

    SuperQode supports three auth modes:

    \b
    1. BYOK (env vars)  - Primary, set ANTHROPIC_API_KEY etc.
    2. Local storage    - Optional, stored in ~/.superqode/auth.json
    3. ACP (agents)     - Delegated to coding agents

    Environment variables always take precedence over local storage.
    """
    pass


@auth.command("info")
def auth_info():
    """Show comprehensive auth information."""

    # Header
    console.print(
        Panel(
            "[bold]🔒 Auth Modes:[/bold]\n"
            "1. [cyan]BYOK[/cyan] - Environment variables (primary)\n"
            "2. [cyan]Local[/cyan] - ~/.superqode/auth.json (optional)\n"
            "3. [cyan]ACP[/cyan] - Delegated to agents",
            title="SuperQode Auth Information",
            border_style="cyan",
        )
    )

    console.print()

    # Get local storage
    local_creds = auth_all()

    # BYOK Section
    console.print("[bold cyan]═══ PROVIDER AUTH STATUS ═══[/bold cyan]")
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

        # Check local storage too
        has_local = provider_id in local_creds

        if not provider_def.env_vars:
            # Local provider (ollama, etc)
            status = "[blue]🏠 Local[/blue]"
            source = provider_def.default_base_url or "localhost"
        elif configured:
            status = "[green]✅ Set[/green]"
            source = _detect_env_source(configured_var)
        elif has_local:
            status = "[green]✅ Set[/green]"
            source = "~/.superqode/auth.json"
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
    console.print("[bold cyan]═══ DATA FLOW & TRANSPARENCY ═══[/bold cyan]")
    console.print()
    console.print("[bold]BYOK:[/bold]  You → SuperQode → LiteLLM → Provider API")
    console.print("[bold]ACP:[/bold]   You → SuperQode → Agent (e.g., opencode) → Provider API")
    console.print()
    console.print("[dim]SuperQode is a pass-through orchestrator. Your data goes directly[/dim]")
    console.print("[dim]to the LLM provider or agent.[/dim]")
    console.print()
    console.print("[bold cyan]What SuperQode does:[/bold cyan]")
    console.print("  ✅ Reads keys from env vars or ~/.superqode/auth.json")
    console.print("  ✅ Passes keys directly to LLM providers")
    console.print("  ✅ Sets 0600 permissions on local auth file")
    console.print()
    console.print("[bold cyan]What SuperQode does NOT do:[/bold cyan]")
    console.print("  ❌ Send keys to any external server")
    console.print("  ❌ Log or display full key values")
    console.print("  ❌ Store keys without explicit 'auth login' command")


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


@auth.command("login")
@click.argument("provider")
def auth_login(provider: str):
    """
    Store API key for a provider in local storage.

    Example: superqode auth login anthropic
    """
    provider_def = PROVIDERS.get(provider)
    if not provider_def:
        console.print(f"[red]Unknown provider: {provider}[/red]")
        console.print("Use 'superqode providers list' to see available providers.")
        return

    if not provider_def.env_vars:
        console.print(f"[yellow]{provider} is a local provider - no API key needed[/yellow]")
        return

    # Check if already configured
    existing = get(provider)
    if existing:
        if not Confirm.ask(f"[yellow]{provider} already configured. Overwrite?[/yellow]"):
            return

    # Get the key
    console.print(f"\n[bold]Configure {provider_def.name}[/bold]")
    if provider_def.docs_url:
        console.print(f"[dim]Get your key at: {provider_def.docs_url}[/dim]")
    console.print()

    api_key = Prompt.ask(f"Enter API key for {provider}", password=True)
    if not api_key:
        console.print("[red]No key provided[/red]")
        return

    # Save it
    auth_set(provider, ApiAuth(key=api_key))
    console.print(f"[green]✅ Saved {provider} API key to ~/.superqode/auth.json[/green]")


@auth.command("logout")
@click.argument("provider")
def auth_logout(provider: str):
    """
    Remove stored API key for a provider.

    Example: superqode auth logout anthropic
    """
    if remove(provider):
        console.print(f"[green]✅ Removed {provider} from local storage[/green]")
    else:
        console.print(f"[yellow]{provider} not found in local storage[/yellow]")


@auth.command("list")
def auth_list():
    """List all locally stored credentials."""
    creds = auth_all()
    if not creds:
        console.print("[dim]No credentials in local storage[/dim]")
        console.print("Use 'superqode auth login <provider>' to add one.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Provider", style="white")
    table.add_column("Type", style="dim")
    table.add_column("Key Preview", style="dim")

    for provider_id, info in creds.items():
        if isinstance(info, ApiAuth):
            key_preview = info.key[:8] + "..." if len(info.key) > 8 else "***"
            table.add_row(provider_id, "api", key_preview)
        elif isinstance(info, OAuthAuth):
            table.add_row(provider_id, "oauth", f"expires: {info.expires}")
        else:
            table.add_row(provider_id, info.type, "-")

    console.print(table)
    console.print(f"\n[dim]Stored in: ~/.superqode/auth.json[/dim]")


# Register with main CLI
def register_commands(cli):
    """Register auth commands with the main CLI."""
    cli.add_command(auth)
