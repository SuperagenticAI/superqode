"""
Agent CLI commands for SuperQode.

Commands for listing and showing ACP/External agents.
"""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..agents.registry import (
    AGENTS,
    AgentProtocol,
    AgentStatus,
    get_supported_agents,
    get_acp_agents,
    get_external_agents,
)


console = Console()


@click.group()
def agents():
    """Manage coding agents (ACP mode)."""
    pass


@agents.command("list")
@click.option(
    "--protocol",
    type=click.Choice(["acp", "external"]),
    help="Filter by protocol",
)
@click.option(
    "--supported",
    is_flag=True,
    help="Show only supported agents",
)
def list_agents(protocol: str, supported: bool):
    """List available coding agents."""

    # Filter agents
    filtered = dict(AGENTS)

    if protocol:
        proto = AgentProtocol.ACP if protocol == "acp" else AgentProtocol.EXTERNAL
        filtered = {k: v for k, v in filtered.items() if v.protocol == proto}

    if supported:
        filtered = {k: v for k, v in filtered.items() if v.status == AgentStatus.SUPPORTED}

    # Build table
    table = Table(title="Coding Agents", show_header=True, header_style="bold cyan")
    table.add_column("Agent", style="white")
    table.add_column("Name", style="white")
    table.add_column("Protocol", style="dim")
    table.add_column("Status", style="white")
    table.add_column("Description", style="dim", max_width=40)

    # Sort by status (supported first) then name
    sorted_agents = sorted(filtered.items(), key=lambda x: (x[1].status.value, x[0]))

    for agent_id, agent_def in sorted_agents:
        status_map = {
            AgentStatus.SUPPORTED: "[green]✅ Supported[/green]",
            AgentStatus.COMING_SOON: "[yellow]🔜 Coming Soon[/yellow]",
            AgentStatus.EXPERIMENTAL: "[blue]🧪 Experimental[/blue]",
        }
        status = status_map.get(agent_def.status, agent_def.status.value)

        protocol_str = agent_def.protocol.value.upper()

        table.add_row(
            agent_id,
            agent_def.name,
            protocol_str,
            status,
            agent_def.description[:40] + "..."
            if len(agent_def.description) > 40
            else agent_def.description,
        )

    console.print(table)

    # Summary
    supported_count = sum(1 for v in filtered.values() if v.status == AgentStatus.SUPPORTED)
    console.print(f"\n[dim]Total: {len(filtered)} agents, {supported_count} supported[/dim]")


@agents.command("show")
@click.argument("agent_id")
def show_agent(agent_id: str):
    """Show details for a specific agent."""

    agent_def = AGENTS.get(agent_id)

    if not agent_def:
        console.print(f"[red]Error: Agent '{agent_id}' not found[/red]")
        console.print("\nAvailable agents:")
        for aid in sorted(AGENTS.keys()):
            console.print(f"  • {aid}")
        return

    # Build info panel
    status_map = {
        AgentStatus.SUPPORTED: "[green]✅ Supported[/green]",
        AgentStatus.COMING_SOON: "[yellow]🔜 Coming Soon[/yellow]",
        AgentStatus.EXPERIMENTAL: "[blue]🧪 Experimental[/blue]",
    }
    status = status_map.get(agent_def.status, agent_def.status.value)

    info_lines = [
        f"[bold]Agent:[/bold] {agent_def.name}",
        f"[bold]ID:[/bold] {agent_id}",
        f"[bold]Protocol:[/bold] {agent_def.protocol.value.upper()}",
        f"[bold]Status:[/bold] {status}",
        f"[bold]Connection:[/bold] {agent_def.connection_type}",
        "",
        f"[bold]Description:[/bold]",
        f"  {agent_def.description}",
        "",
    ]

    # Capabilities
    if agent_def.capabilities:
        info_lines.append("[bold]Capabilities:[/bold]")
        for cap in agent_def.capabilities:
            info_lines.append(f"  • {cap}")
        info_lines.append("")

    # Auth info
    info_lines.append("[bold]Authentication:[/bold]")
    info_lines.append(f"  {agent_def.auth_info}")
    info_lines.append("")

    # Setup
    info_lines.append("[bold]Setup:[/bold]")
    info_lines.append(f"  {agent_def.setup_command}")
    info_lines.append("")

    # Command
    if agent_def.command:
        info_lines.append(f"[bold]Command:[/bold] {agent_def.command}")
        info_lines.append("")

    # Docs
    info_lines.append(f"[bold]Documentation:[/bold] {agent_def.docs_url}")

    panel = Panel(
        "\n".join(info_lines),
        title=f"Agent: {agent_def.name}",
        border_style="cyan",
    )
    console.print(panel)

    # Usage example
    if agent_def.status == AgentStatus.SUPPORTED:
        console.print("\n[bold]Usage in superqode.yaml:[/bold]")
        console.print(f"""
[dim]team:
  dev:
    roles:
      my-role:
        mode: "acp"
        agent: "{agent_id}"
        agent_config:
          provider: "anthropic"
          model: "claude-sonnet-4-20250514"
        job_description: |
          Your job description here...[/dim]
""")


# Register with main CLI
def register_commands(cli):
    """Register agent commands with the main CLI."""
    cli.add_command(agents)
