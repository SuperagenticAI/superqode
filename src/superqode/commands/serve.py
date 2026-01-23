"""
SuperQode Server Commands.

Start various SuperQode servers:
- LSP server for IDE integration
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


@serve.command("lsp")
@click.option(
    "--transport",
    "-t",
    type=click.Choice(["stdio", "tcp"]),
    default="stdio",
    help="Transport mode: stdio (default) for editors, tcp for debugging",
)
@click.option("--port", "-p", default=9000, help="Port for TCP transport (default: 9000)")
@click.option("--project", type=click.Path(exists=True), default=".", help="Project root directory")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def serve_lsp(transport: str, port: int, project: str, verbose: bool):
    """Start the LSP server for IDE integration.

    The LSP server exposes QE findings as diagnostics in your IDE.
    Supports VSCode, Neovim, and other LSP-compatible editors.

    Examples:

        superqode serve lsp                    # Start in stdio mode (for editors)

        superqode serve lsp -t tcp -p 9000    # Start in TCP mode (for debugging)

    VSCode Setup:
        1. Install the SuperQode VSCode extension
        2. The extension will automatically connect to the LSP server

    Neovim Setup (with nvim-lspconfig):
        require('lspconfig.configs').superqode = {
            default_config = {
                cmd = { 'superqode', 'serve', 'lsp' },
                filetypes = { '*' },
                root_dir = function(fname)
                    return vim.fn.getcwd()
                end,
            },
        }
        require('lspconfig').superqode.setup{}
    """
    import logging

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    from superqode.server import start_lsp_server

    project_root = Path(project).resolve()

    if transport == "tcp":
        console.print(f"[cyan]Starting SuperQode LSP server on port {port}[/cyan]")
        console.print("[dim]Connect your editor to localhost:{port}[/dim]")
    else:
        # stdio mode - don't print to stdout as it interferes with LSP
        import sys

        sys.stderr.write("SuperQode LSP server starting (stdio mode)\n")

    start_lsp_server(
        project_root=project_root,
        transport=transport,
        port=port,
    )


@serve.command("web")
@click.option("--port", "-p", default=8080, help="Port for web server (default: 8080)")
@click.option("--host", "-h", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
@click.option("--project", type=click.Path(exists=True), default=".", help="Project root directory")
@click.option("--no-open", is_flag=True, help="Don't open browser automatically")
def serve_web(port: int, host: str, project: str, no_open: bool):
    """Start the web server for browser-based TUI.

    Run SuperQode's TUI interface in your web browser.

    Examples:

        superqode serve web                  # Start on localhost:8080

        superqode serve web -p 3000          # Use custom port

        superqode serve web -h 0.0.0.0       # Allow external connections
    """
    from superqode.server import start_server, WebServerConfig

    project_root = Path(project).resolve()

    console.print(f"[cyan]Starting SuperQode web server on http://{host}:{port}[/cyan]")

    config = WebServerConfig(
        host=host,
        port=port,
        project_root=project_root,
    )

    start_server(config, open_browser=not no_open)


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
