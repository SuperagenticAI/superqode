"""MCP client controls using the same resolver and transports as hosted PiPy."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click


def register_mcp_client_commands(group):
    def options(fn):
        fn = click.option("--cwd", type=click.Path(file_okay=False, path_type=Path), default=".")(
            fn
        )
        return click.option("--config", type=click.Path(path_type=Path), default=None)(fn)

    async def control(action, server, config, cwd, connect=False):
        from superqode.harness.pipy_mcp import PiPyMCPTools
        from superqode.mcp.client import MCPClientManager
        from superqode.mcp.config import resolve_mcp_config

        resolved = resolve_mcp_config({"mcp_config": str(config)} if config else {}, cwd=cwd)
        async with MCPClientManager() as manager:
            for declaration in resolved.servers.values():
                manager.add_server(declaration)
            bridge = PiPyMCPTools(manager)
            bridge.sources, bridge.errors = resolved.sources, resolved.errors
            if connect:
                await manager.connect_all()
            return await bridge.control(action, server)

    @group.command("list")
    @options
    @click.option("--connect", is_flag=True, help="Connect enabled servers and inspect live state.")
    def list_servers(config, cwd, connect):
        """Inspect shared MCP configuration; credentials are omitted."""
        result = asyncio.run(control("status", None, config, cwd, connect))
        click.echo(json.dumps(result, indent=2))
        if result["errors"] or (
            connect
            and any(row["enabled"] and row["state"] != "connected" for row in result["servers"])
        ):
            raise click.exceptions.Exit(1)

    for action in ("login", "logout", "reconnect"):

        def make_command(action):
            @options
            @click.argument("server")
            def command(server, config, cwd):
                try:
                    result = asyncio.run(control(action, server, config, cwd))
                except ValueError as error:
                    raise click.ClickException(str(error)) from error
                click.echo(json.dumps(result, indent=2))
                if not result["success"]:
                    raise click.exceptions.Exit(1)

            command.__doc__ = f"{action.capitalize()} one configured MCP server."
            return command

        group.command(action)(make_command(action))
