"""
SuperQode Server Commands.

Start various SuperQode servers:
- Web server for browser-based TUI
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from superqode.enterprise import require_enterprise

console = Console()


@click.group()
def serve():
    """Server commands for IDE and web integration."""
    if not require_enterprise("Server integrations"):
        raise SystemExit(1)


@serve.command("web")
@click.option("--port", "-p", default=8080, help="Port for web server (default: 8080)")
@click.option("--host", "-h", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
@click.option("--project", type=click.Path(exists=True), default=".", help="Project root directory")
@click.option("--no-open", is_flag=True, help="Don't open browser automatically")
@click.option(
    "--allow-remote",
    is_flag=True,
    help="Allow binding to non-loopback hosts such as 0.0.0.0",
)
@click.option("--token", default=None, help="Use a specific web access token")
def serve_web(
    port: int,
    host: str,
    project: str,
    no_open: bool,
    allow_remote: bool,
    token: Optional[str],
):
    """Start the web server for browser-based TUI.

    Run SuperQode's TUI interface in your web browser.

    Examples:

        superqode serve web                  # Start on localhost:8080

        superqode serve web -p 3000          # Use custom port

        superqode serve web -h 0.0.0.0 --allow-remote
    """
    from superqode.server import start_server

    project_root = Path(project).resolve()

    console.print(f"[cyan]Starting SuperQode web server on http://{host}:{port}[/cyan]")
    if allow_remote:
        console.print("[yellow]Remote web serving enabled. Use only on trusted networks.[/yellow]")

    try:
        start_server(
            host=host,
            port=port,
            project_path=project_root,
            require_auth=True,
            auth_token=token,
            allow_remote=allow_remote,
            open_browser=not no_open,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@serve.command("status")
@click.option("--project", type=click.Path(exists=True), default=".", help="Project root directory")
def serve_status(project: str):
    """Show status of running servers."""
    import socket

    project_root = Path(project).resolve()

    console.print()
    console.print("[bold]SuperQode Server Status[/bold]")
    console.print()

    # Check LSP TCP port
    lsp_port = 9000
    lsp_running = False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", lsp_port))
        lsp_running = result == 0
        sock.close()
    except Exception:
        pass

    if lsp_running:
        console.print(f"[green]LSP Server:[/green] Running on port {lsp_port}")
    else:
        console.print(f"[dim]LSP Server:[/dim] Not running (stdio mode doesn't show here)")

    # Check web server port
    web_port = 8080
    web_running = False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", web_port))
        web_running = result == 0
        sock.close()
    except Exception:
        pass

    if web_running:
        console.print(f"[green]Web Server:[/green] Running on port {web_port}")
    else:
        console.print(f"[dim]Web Server:[/dim] Not running")

    console.print()
