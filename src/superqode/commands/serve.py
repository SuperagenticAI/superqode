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
    if ctx.invoked_subcommand in {"api", "harness", "acp", "a2a"}:
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


@serve.command("a2a")
@click.option("--spec", "spec_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--provider", default="openai", envvar="SUPERQODE_PROVIDER", show_default=True)
@click.option(
    "--model", "model_name", default="gpt-5.4", envvar="SUPERQODE_MODEL", show_default=True
)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option(
    "--public-url", default=None, help="Public A2A interface URL advertised in the Agent Card"
)
@click.option(
    "--working-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
)
@click.option(
    "--harness-store",
    "--store",
    "store_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path(".superqode/a2a/store.sqlite3"),
    show_default=True,
    help="SQLite store for SuperQode sessions, runs, events, and evidence",
)
@click.option(
    "--task-store",
    "task_store_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path(".superqode/a2a/tasks.sqlite3"),
    show_default=True,
    help="SQLite store for A2A task lookup, listing, and restart recovery",
)
@click.option(
    "--no-task-store",
    is_flag=True,
    help=(
        "Keep A2A task records in memory. Suitable where responses are "
        "immediate and the filesystem does not survive a deploy."
    ),
)
@click.option("--token", envvar="SUPERQODE_A2A_TOKEN", help="Bearer token for A2A operations")
@click.option("--allow-remote", is_flag=True, help="Allow binding outside localhost")
@click.option(
    "--expose-harness",
    is_flag=True,
    help=(
        "Serve the harness skill on a remote bind. Requires --spec, because the "
        "bound spec decides what an accepted request may do."
    ),
)
@click.option(
    "--export-agent-card",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the runtime Agent Card to a JSON file and exit",
)
@click.option(
    "--anonymous-per-minute",
    type=int,
    default=None,
    help=(
        "Requests per minute allowed for a caller with no credential "
        "(default 10). Zero removes the ceiling. A conformance suite sends "
        "hundreds of requests and is throttled by the default."
    ),
)
@click.option(
    "--keyed-per-minute",
    type=int,
    default=None,
    help="Requests per minute allowed for a caller presenting a valid key (default 60).",
)
@click.option(
    "--global-per-day",
    type=int,
    default=None,
    help="Requests per day across every caller (default 5000). Zero removes the ceiling.",
)
def serve_a2a(
    spec_path: Optional[Path],
    provider: str,
    model_name: str,
    host: str,
    port: int,
    public_url: Optional[str],
    working_dir: Path,
    store_path: Path,
    task_store_path: Path,
    no_task_store: bool,
    token: Optional[str],
    allow_remote: bool,
    expose_harness: bool,
    export_agent_card: Optional[Path],
    anonymous_per_minute: Optional[int],
    keyed_per_minute: Optional[int],
    global_per_day: Optional[int],
):
    """Expose a HarnessSpec as an A2A 1.0 HTTP+JSON agent."""
    import asyncio

    from superqode.a2a import create_a2a_server
    from superqode.a2a.keys import SECRET_ENV as KEY_SECRET_ENV
    from superqode.a2a.keys import resolve_secret as resolve_key_secret

    is_loopback = host in {"127.0.0.1", "localhost", "::1"}
    if not is_loopback and not allow_remote:
        raise click.ClickException("Use --allow-remote to bind outside localhost.")
    key_secret = resolve_key_secret()

    # A remote endpoint shares one token among every caller, so the harness
    # skill would hand all of them the same working directory with whatever
    # the bound spec permits.  The default template allows shell and writes
    # with sandbox "local", which is no isolation at all.  Remote binds
    # therefore serve the shortlist skill only unless asked otherwise, and
    # asking requires naming the spec so the policy is a deliberate choice.
    harness_skill_enabled = True
    if not is_loopback:
        if expose_harness and spec_path is None:
            raise click.ClickException(
                "--expose-harness requires --spec. Serving the default coding "
                "harness remotely would allow shell access and writes with no "
                "sandbox isolation."
            )
        harness_skill_enabled = expose_harness
        if harness_skill_enabled and not token:
            # The harness runs work and spends money, so it is never anonymous.
            raise click.ClickException(
                "Serving the harness remotely requires --token or SUPERQODE_A2A_TOKEN."
            )
        if not harness_skill_enabled:
            console.print(
                "[yellow]Remote bind: serving the harness shortlist skill only. "
                "Pass --expose-harness with --spec to also run harnesses.[/yellow]"
            )
            if not token and not key_secret:
                console.print(
                    "[yellow]No credential configured: every caller is anonymous. "
                    f"Set {KEY_SECRET_ENV} to accept customer keys.[/yellow]"
                )
    elif expose_harness:
        console.print(
            "[yellow]--expose-harness only affects remote binds; loopback already "
            "serves the harness skill.[/yellow]"
        )
    advertised_url = public_url or f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    if not is_loopback and not public_url:
        console.print(
            "[yellow]No --public-url supplied; the Agent Card advertises a loopback URL.[/yellow]"
        )

    try:
        server = asyncio.run(
            create_a2a_server(
                spec=spec_path,
                server_url=advertised_url,
                provider=provider,
                model=model_name,
                working_directory=working_dir.resolve(),
                store_path=store_path,
                task_store_path=None if no_task_store else task_store_path,
                bearer_token=token,
                key_secret=key_secret,
                harness_skill_enabled=harness_skill_enabled,
                anonymous_per_minute=anonymous_per_minute,
                keyed_per_minute=keyed_per_minute,
                global_per_day=global_per_day,
            )
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    if export_agent_card is not None:
        export_agent_card.parent.mkdir(parents=True, exist_ok=True)
        export_agent_card.write_text(server.agent_card_json(), encoding="utf-8")
        console.print(f"[green]Wrote Agent Card to {export_agent_card}[/green]")
        return

    console.print(f"[cyan]Serving SuperQode A2A 1.0 on http://{host}:{port}[/cyan]")
    console.print("[dim]Agent Card: /.well-known/agent-card.json[/dim]")
    try:
        server.run(host=host, port=port)
    except KeyboardInterrupt:
        console.print("\n[dim]A2A server stopped.[/dim]")


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
