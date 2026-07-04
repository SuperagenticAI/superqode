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
@click.pass_context
def serve(ctx: click.Context):
    """Server commands for IDE and web integration."""
    if ctx.invoked_subcommand in {"api", "harness", "acp"}:
        return
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


@serve.command("harness")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--dir", "harness_dir", type=click.Path(path_type=Path), default=None)
@click.option("--http", is_flag=True, help="Serve over streamable HTTP instead of stdio")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
def serve_harness(
    spec_path: Optional[Path], harness_dir: Optional[Path], http: bool, host: str, port: int
):
    """Expose HarnessSpec workflows as MCP tools.

    This is a friendly alias over `superqode mcp`; use --spec for one harness
    file or --dir for a directory of harness specs.
    """
    from superqode.mcp.harness_server import run_server

    if spec_path and harness_dir:
        raise click.ClickException("Pass either --spec or --dir, not both.")
    if spec_path:
        console.print(f"[cyan]Serving harness MCP tools from {spec_path.parent}[/cyan]")
        console.print(f"[dim]Use harness name: {spec_path.stem}[/dim]")
        run_server("http" if http else "stdio", host, port, str(spec_path.parent))
        return
    console.print(
        f"[cyan]Serving harness MCP tools from {harness_dir or 'default harness directories'}[/cyan]"
    )
    run_server("http" if http else "stdio", host, port, str(harness_dir) if harness_dir else None)


@serve.command("acp")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--dir", "harness_dir", type=click.Path(file_okay=False, path_type=Path), default=None
)
@click.option("--provider", default="", envvar="SUPERQODE_ACP_PROVIDER")
@click.option("--model", default="", envvar="SUPERQODE_ACP_MODEL")
def serve_acp(spec_path: Optional[Path], harness_dir: Optional[Path], provider: str, model: str):
    """Run SuperQode as an ACP agent on stdio (Zed, JetBrains, Neovim, ...).

    The agent loop is a HarnessSpec: --spec pins one file, otherwise each
    session resolves superqode.local.yaml / harness.yaml in its working
    directory, then the conventional harness dirs, then the coding template.
    """
    import asyncio

    from superqode.acp.server import run_acp_server

    if spec_path and harness_dir:
        raise click.ClickException("Pass either --spec or --dir, not both.")
    # stdout carries JSON-RPC, so any human-facing output must go to stderr.
    click.echo("SuperQode ACP agent listening on stdio", err=True)
    try:
        asyncio.run(
            run_acp_server(
                spec_path=spec_path,
                harness_dir=harness_dir,
                provider=provider,
                model=model,
            )
        )
    except KeyboardInterrupt:
        pass


@serve.command("api")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8766, show_default=True, type=int)
@click.option("--storage-dir", default=".superqode/sessions", show_default=True)
@click.option("--allow-remote", is_flag=True, help="Allow binding to non-loopback hosts")
@click.option("--token", default=None, help="Optional bearer token for browser/mobile clients")
def serve_api(host: str, port: int, storage_dir: str, allow_remote: bool, token: Optional[str]):
    """Serve the local session switchboard API."""
    from superqode.server.api import run_session_api

    if host not in {"127.0.0.1", "localhost", "::1"} and not allow_remote:
        raise click.ClickException("Use --allow-remote to bind outside localhost.")
    if allow_remote:
        console.print(
            "[yellow]Remote API serving enabled. Use --token on trusted networks.[/yellow]"
        )
    console.print(f"[cyan]Serving SuperQode session API on http://{host}:{port}[/cyan]")
    console.print(
        "[dim]Endpoints: /health, /sessions, /sessions/graph, /sessions/{id}/history[/dim]"
    )
    try:
        run_session_api(host=host, port=port, storage_dir=storage_dir, token=token)
    except KeyboardInterrupt:
        console.print("\n[dim]Session API stopped.[/dim]")


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
