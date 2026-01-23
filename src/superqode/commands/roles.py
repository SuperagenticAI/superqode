"""
Roles CLI commands for SuperQode.

Commands for listing and showing role execution details.
"""

import os
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from ..config import load_config, load_enabled_modes, resolve_role
from ..execution.resolver import ExecutionResolver
from ..execution.modes import ExecutionMode, GatewayType
from ..providers.registry import PROVIDERS
from ..agents.registry import AGENTS, AgentStatus


console = Console()


@click.group()
def roles():
    """Manage team roles and their execution configuration."""
    pass


@roles.command("list")
@click.option("--mode", "-m", help="Filter by mode (e.g., dev, qe, devops)")
@click.option("--enabled-only", is_flag=True, help="Show only enabled roles")
def list_roles(mode: Optional[str], enabled_only: bool):
    """List all configured roles with their execution mode."""

    config = load_config()
    enabled_modes = load_enabled_modes(config)

    if not enabled_modes:
        console.print(
            "[yellow]No roles configured. Run 'superqode init' to create default configuration.[/yellow]"
        )
        return

    # Build table
    table = Table(title="Team Roles", show_header=True, header_style="bold cyan")
    table.add_column("Role", style="white")
    table.add_column("Mode", style="dim")
    table.add_column("Exec Mode", style="cyan")
    table.add_column("Provider/Agent", style="green")
    table.add_column("Model", style="dim")
    table.add_column("Status", style="white")

    for mode_name, mode_config in enabled_modes.items():
        if mode and mode_name != mode:
            continue

        if mode_config.roles:
            for role_name, role_config in mode_config.roles.items():
                if enabled_only and not role_config.enabled:
                    continue

                # Determine execution mode display
                exec_mode = role_config.execution_mode
                if exec_mode == "acp":
                    exec_display = "[blue]ACP[/blue]"
                    # For ACP, show the agent (new field or legacy coding_agent)
                    provider_agent = role_config.agent_id or role_config.coding_agent
                    model = "(agent-managed)"
                else:
                    exec_display = "[green]BYOK[/green]"
                    provider_agent = role_config.provider or "-"
                    model = role_config.model or "-"

                status = (
                    "[green]✅ Enabled[/green]" if role_config.enabled else "[red]❌ Disabled[/red]"
                )

                table.add_row(
                    f"{mode_name}.{role_name}",
                    mode_name,
                    exec_display,
                    provider_agent,
                    model,
                    status,
                )
        elif mode_config.direct_role:
            role_config = mode_config.direct_role
            if enabled_only and not role_config.enabled:
                continue

            exec_mode = role_config.execution_mode
            if exec_mode == "acp":
                exec_display = "[blue]ACP[/blue]"
                provider_agent = role_config.agent_id or role_config.coding_agent
                model = "(agent-managed)"
            else:
                exec_display = "[green]BYOK[/green]"
                provider_agent = role_config.provider or "-"
                model = role_config.model or "-"

            status = (
                "[green]✅ Enabled[/green]" if role_config.enabled else "[red]❌ Disabled[/red]"
            )

            table.add_row(
                mode_name,
                mode_name,
                exec_display,
                provider_agent,
                model,
                status,
            )

    console.print(table)

    # Legend
    console.print()
    console.print("[dim]Execution Modes:[/dim]")
    console.print("  [green]BYOK[/green] = Bring Your Own Key (direct LLM API via gateway)")
    console.print("  [blue]ACP[/blue]  = Agent Client Protocol (full coding agent)")


@roles.command("info")
@click.argument("role_path", metavar="MODE.ROLE")
def role_info(role_path: str):
    """Show detailed execution information for a role.

    Examples:
        superqode roles info dev.fullstack
        superqode roles info qe.api_tester
    """

    # Parse role path
    parts = role_path.split(".", 1)
    mode_name = parts[0]
    role_name = parts[1] if len(parts) > 1 else None

    config = load_config()
    resolved = resolve_role(mode_name, role_name, config)

    if not resolved:
        console.print(f"[red]Error: Role '{role_path}' not found or disabled[/red]")
        console.print("\nUse 'superqode roles list' to see available roles.")
        return

    # Build info panel
    info_lines = []

    # Basic info
    info_lines.append(f"[bold]Role:[/bold] {role_path}")
    info_lines.append(f"[bold]Description:[/bold] {resolved.description}")
    info_lines.append(f"[bold]Enabled:[/bold] {'Yes' if resolved.enabled else 'No'}")
    info_lines.append("")

    # Execution mode section
    exec_mode = resolved.execution_mode

    if exec_mode == "byok":
        info_lines.append("[bold cyan]═══ BYOK MODE (Direct LLM) ═══[/bold cyan]")
        info_lines.append("")
        info_lines.append(f"[bold]Provider:[/bold] {resolved.provider or '(not set)'}")
        info_lines.append(f"[bold]Model:[/bold] {resolved.model or '(not set)'}")
        info_lines.append(f"[bold]Gateway:[/bold] LiteLLM")
        info_lines.append("")

        # Check provider status
        if resolved.provider:
            provider_def = PROVIDERS.get(resolved.provider)
            if provider_def:
                # Check env vars
                configured = False
                for env_var in provider_def.env_vars:
                    if os.environ.get(env_var):
                        configured = True
                        break

                if not provider_def.env_vars:
                    configured = True  # Local provider

                status = (
                    "[green]✅ Configured[/green]" if configured else "[red]❌ Not configured[/red]"
                )
                info_lines.append(f"[bold]Provider Status:[/bold] {status}")

                if provider_def.env_vars:
                    info_lines.append(f"[bold]Required Env:[/bold] {provider_def.env_vars[0]}")

                if not configured:
                    info_lines.append("")
                    info_lines.append(
                        f'[yellow]To configure: export {provider_def.env_vars[0]}="your-key"[/yellow]'
                    )
                    info_lines.append(f"[yellow]Get key at: {provider_def.docs_url}[/yellow]")
            else:
                info_lines.append(
                    f"[yellow]⚠️ Provider '{resolved.provider}' not in registry[/yellow]"
                )

        info_lines.append("")
        info_lines.append("[bold]Capabilities:[/bold]")
        info_lines.append("  • Chat completion")
        info_lines.append("  • Streaming responses")
        info_lines.append("  • Tool calling (if model supports)")
        info_lines.append("")
        info_lines.append("[bold]Limitations:[/bold]")
        info_lines.append("  • No file editing")
        info_lines.append("  • No shell commands")
        info_lines.append("  • No MCP tools")

    else:  # ACP mode
        info_lines.append("[bold blue]═══ ACP MODE (Coding Agent) ═══[/bold blue]")
        info_lines.append("")

        agent_id = resolved.agent_id or resolved.coding_agent
        info_lines.append(f"[bold]Agent:[/bold] {agent_id}")

        # Check agent status
        agent_def = AGENTS.get(agent_id)
        if agent_def:
            status_str = {
                AgentStatus.SUPPORTED: "[green]✅ Supported[/green]",
                AgentStatus.COMING_SOON: "[yellow]⏳ Coming Soon[/yellow]",
                AgentStatus.EXPERIMENTAL: "[blue]🧪 Experimental[/blue]",
            }.get(agent_def.status, "[dim]Unknown[/dim]")

            info_lines.append(f"[bold]Agent Status:[/bold] {status_str}")
            info_lines.append(f"[bold]Protocol:[/bold] {agent_def.protocol.value.upper()}")
            info_lines.append(f"[bold]Auth:[/bold] {agent_def.auth_info}")
            info_lines.append("")

            # Show agent's LLM config (new style or legacy)
            if resolved.agent_config:
                info_lines.append("[bold]Agent LLM Config:[/bold]")
                if resolved.agent_config.provider:
                    info_lines.append(f"  Provider: {resolved.agent_config.provider}")
                if resolved.agent_config.model:
                    info_lines.append(f"  Model: {resolved.agent_config.model}")
                info_lines.append("")
            elif resolved.provider or resolved.model:
                # Legacy: provider/model specified at role level for ACP agent
                info_lines.append("[bold]Agent LLM Config (legacy):[/bold]")
                if resolved.provider:
                    info_lines.append(f"  Provider: {resolved.provider}")
                if resolved.model:
                    info_lines.append(f"  Model: {resolved.model}")
                info_lines.append("")

            info_lines.append("[bold]Capabilities:[/bold]")
            for cap in agent_def.capabilities:
                info_lines.append(f"  • {cap}")

            if agent_def.status != AgentStatus.SUPPORTED:
                info_lines.append("")
                info_lines.append(f"[yellow]Setup: {agent_def.setup_command}[/yellow]")
        else:
            info_lines.append(f"[yellow]⚠️ Agent '{agent_id}' not in registry[/yellow]")

    # MCP servers
    if resolved.mcp_servers:
        info_lines.append("")
        info_lines.append("[bold]MCP Servers:[/bold]")
        for server in resolved.mcp_servers:
            info_lines.append(f"  • {server}")

    # Job description
    if resolved.job_description:
        info_lines.append("")
        info_lines.append("[bold]Job Description:[/bold]")
        # Truncate long descriptions
        desc = resolved.job_description.strip()
        if len(desc) > 200:
            desc = desc[:200] + "..."
        info_lines.append(f"  {desc}")

    # Auth info
    info_lines.append("")
    info_lines.append("[bold cyan]═══ SECURITY ═══[/bold cyan]")
    info_lines.append("")
    if exec_mode == "byok":
        info_lines.append("🔒 API key read from YOUR environment variables")
        info_lines.append("🔒 SuperQode NEVER stores your keys")
        info_lines.append("🔒 Data flows: You → SuperQode → LiteLLM → Provider")
    else:
        info_lines.append("🔒 Auth managed by the agent (not SuperQode)")
        info_lines.append("🔒 Agent stores its own credentials")
        info_lines.append("🔒 Data flows: You → SuperQode → Agent → Provider")

    panel = Panel(
        "\n".join(info_lines),
        title=f"Role: {role_path}",
        border_style="cyan",
    )
    console.print(panel)


@roles.command("check")
@click.argument("role_path", metavar="MODE.ROLE")
def role_check(role_path: str):
    """Check if a role is ready to run (auth configured, etc.)."""

    # Parse role path
    parts = role_path.split(".", 1)
    mode_name = parts[0]
    role_name = parts[1] if len(parts) > 1 else None

    config = load_config()
    resolved = resolve_role(mode_name, role_name, config)

    if not resolved:
        console.print(f"[red]❌ Role '{role_path}' not found or disabled[/red]")
        return

    console.print(f"Checking role: {role_path}")
    console.print()

    issues = []
    warnings = []

    exec_mode = resolved.execution_mode

    if exec_mode == "byok":
        # Check provider
        if not resolved.provider:
            issues.append("No provider specified")
        else:
            provider_def = PROVIDERS.get(resolved.provider)
            if not provider_def:
                warnings.append(f"Provider '{resolved.provider}' not in registry (may still work)")
            elif provider_def.env_vars:
                configured = False
                for env_var in provider_def.env_vars:
                    if os.environ.get(env_var):
                        configured = True
                        break
                if not configured:
                    issues.append(f"API key not set. Set {provider_def.env_vars[0]}")

        # Check model
        if not resolved.model:
            issues.append("No model specified")

    else:  # ACP
        agent_id = resolved.agent_id or resolved.coding_agent
        agent_def = AGENTS.get(agent_id)

        if not agent_def:
            warnings.append(f"Agent '{agent_id}' not in registry")
        elif agent_def.status != AgentStatus.SUPPORTED:
            issues.append(
                f"Agent '{agent_id}' is not yet supported (status: {agent_def.status.value})"
            )

    # Display results
    if issues:
        console.print("[red]❌ Issues found:[/red]")
        for issue in issues:
            console.print(f"  • {issue}")
        console.print()

    if warnings:
        console.print("[yellow]⚠️ Warnings:[/yellow]")
        for warning in warnings:
            console.print(f"  • {warning}")
        console.print()

    if not issues and not warnings:
        console.print("[green]✅ Role is ready to run![/green]")
    elif not issues:
        console.print("[green]✅ Role should work (with warnings)[/green]")
    else:
        console.print("[red]❌ Role has issues that need to be fixed[/red]")


# Register with main CLI
def register_commands(cli):
    """Register roles commands with the main CLI."""
    cli.add_command(roles)
