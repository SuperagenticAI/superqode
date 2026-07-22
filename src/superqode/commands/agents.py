"""SuperQode 'agents' CLI: list/store/show/doctor/connect/install ACP agents."""

import json
import click


# ACP Agent commands
@click.group()
def agents():
    """Manage ACP (Agent-Client Protocol) coding agents."""
    pass


@agents.command("list")
@click.option("--store", is_flag=True, help="Show agent store interface")
@click.option(
    "--protocol",
    type=click.Choice(["acp", "external"]),
    help="Filter by protocol. The active agents command currently lists ACP agents.",
)
@click.option("--supported", is_flag=True, help="Accepted for compatibility; ACP agents are shown.")
@click.option(
    "--tier",
    type=click.Choice(["featured", "enterprise", "all"]),
    default="all",
    show_default=True,
    help="Filter the missing-agent catalog. Installed agents are always shown.",
)
@click.option("--refresh", is_flag=True, help="Refresh the official ACP Registry cache first.")
def agents_list(store, protocol, supported, tier, refresh):
    """List all available ACP coding agents."""
    from superqode.commands.acp import show_agents_list, show_agents_store

    if protocol == "external":
        click.echo(
            "No external agents are listed by this command. Use `superqode agents list` for ACP agents."
        )
        return

    if store:
        show_agents_store()
    else:
        show_agents_list(catalog_tier=tier, refresh=refresh)


@agents.command("refresh")
def agents_refresh():
    """Refresh the cached official ACP Registry."""
    import asyncio

    from superqode.providers.acp_registry import CACHE_FILE, get_acp_registry_agents

    records = asyncio.run(get_acp_registry_agents(force_refresh=True))
    click.echo(f"ACP Registry refreshed: {len(records)} agents")
    click.echo(f"Cache: {CACHE_FILE}")


@agents.command("store")
def agents_store():
    """Show the beautiful agent store interface."""
    from superqode.commands.acp import show_agents_store

    show_agents_store()


@agents.command("show")
@click.argument("agent", metavar="AGENT")
def agents_show(agent):
    """Show detailed information about a specific agent."""
    from superqode.commands.acp import show_agent

    show_agent(agent)


@agents.command("doctor")
@click.argument("agent", metavar="AGENT", required=False)
@click.option("--live", is_flag=True, help="Start the ACP agent and check protocol support")
@click.option("--timeout", default=10.0, type=float, help="Live protocol check timeout")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def agents_doctor(agent, live, timeout, json_output):
    """Check ACP agent install, setup, and optional protocol health."""
    import asyncio

    from superqode.acp.doctor import acp_doctor

    results = asyncio.run(acp_doctor(agent, live=live, timeout=timeout))
    if agent and not results:
        raise click.ClickException(f"ACP agent not found: {agent}")

    if json_output:
        click.echo(json.dumps(results, indent=2))
        return

    for result in results:
        status = "installed" if result["installed"] else "missing"
        click.echo(f"{result['short_name']} ({result['name']}): {status}")
        if result.get("command"):
            click.echo(f"  command: {result['command']}")
        if result.get("missing_env_vars"):
            click.echo(f"  env: set one of {', '.join(result['missing_env_vars'])}")
        if not result["installed"] and result.get("install_command"):
            click.echo(f"  install: {result['install_command']}")
        live_result = result.get("live")
        if live_result:
            started = "yes" if live_result.get("started") else "no"
            click.echo(f"  protocol started: {started}")
            if live_result.get("session"):
                click.echo("  session: yes")
            if live_result.get("models"):
                click.echo(f"  models: {len(live_result['models'])}")
            if live_result.get("modes"):
                click.echo(f"  modes: {len(live_result['modes'])}")
            if live_result.get("error"):
                click.echo(f"  error: {live_result['error']}")


@agents.command("connect")
@click.argument("agent", metavar="AGENT")
@click.option("--project-dir", "-d", metavar="DIR", help="Project directory to work in")
def agents_connect(agent, project_dir):
    """Connect to an ACP coding agent. (Deprecated: use 'superqode connect acp' instead)"""
    import warnings

    warnings.warn(
        "'superqode agents connect' is deprecated. Use 'superqode connect acp' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from superqode.commands.acp import connect_agent

    exit(connect_agent(agent, project_dir))


@agents.command("install")
@click.argument("agent", metavar="AGENT")
def agents_install(agent):
    """Install an ACP coding agent."""
    from superqode.commands.acp import install_agent_cmd

    exit(install_agent_cmd(agent))


@agents.command("free-models")
@click.option(
    "--agent",
    "agent_filter",
    default=None,
    help="Only show free models from this agent (identity or short_name)",
)
@click.option("--refresh", is_flag=True, help="Skip the discovery cache and re-probe live")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a table")
def agents_free_models(agent_filter, refresh, as_json):
    """List free-tier models discovered across all installed ACP agents.

    Each agent declares its catalog via the optional [free_models] section
    in its TOML descriptor; SuperQode probes them in parallel and falls
    back to a curated list when the live probe is unavailable.
    """
    from superqode.commands.acp import show_free_models

    exit(show_free_models(agent_filter=agent_filter, refresh=refresh, as_json=as_json))
