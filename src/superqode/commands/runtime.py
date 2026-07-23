"""CLI commands for managing the agent runtime backend.

superqode runtime list           # show all known runtimes + status
superqode runtime doctor [name]  # probe installs + show install hints
"""

from __future__ import annotations

import importlib
import sys
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from ..providers.env_introspect import install_command
from ..runtime import list_runtimes, resolve_runtime_name

console = Console()


@click.group()
def runtime_cmd() -> None:
    """Manage the agent runtime backend."""


@runtime_cmd.command("list")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def list_runtimes_cmd(json_output: bool) -> None:
    """Show installed and available runtimes."""
    runtimes = list_runtimes()
    active = resolve_runtime_name()

    if json_output:
        import json as _json

        payload = [
            {
                "name": r.name,
                "description": r.description,
                "installed": r.installed,
                "implemented": r.implemented,
                "ready": r.ready,
                "status_detail": r.status_detail,
                "install_hint": r.install_hint,
                "active": r.name == active,
            }
            for r in runtimes
        ]
        click.echo(_json.dumps(payload, indent=2))
        return

    table = Table(title="SuperQode runtimes", show_lines=False)
    table.add_column("", width=2)
    table.add_column("Runtime", style="bold")
    table.add_column("Status")
    table.add_column("Description")

    for r in runtimes:
        marker = "▸" if r.name == active else " "
        if not r.installed:
            status = f"[yellow]missing[/yellow]  {r.install_hint or ''}".strip()
        elif not r.implemented:
            status = "[red]stub[/red]"
        elif not r.ready:
            status = f"[yellow]unavailable[/yellow]  {r.status_detail or ''}".strip()
        else:
            status = "[green]ready[/green]"
        table.add_row(marker, r.name, status, r.description)

    console.print(table)
    console.print(f"\nActive runtime (current resolution): [bold]{active}[/bold]")


@runtime_cmd.command("setup")
def setup() -> None:
    """Show optional vendor runtime installation and authentication steps."""
    click.echo("Optional vendor SDK runtimes")
    click.echo(f"  Codex SDK:        {install_command('codex-sdk')}")
    click.echo(f"  GitHub Copilot:   {install_command('copilot-sdk')}")
    click.echo(f"  Claude Agent SDK: {install_command('claude-agent-sdk')}")
    click.echo(f"  Antigravity SDK:  {install_command('antigravity-sdk')}")
    click.echo("\nInstall all vendor SDK runtimes:")
    click.echo(f"  {install_command('vendor-sdks')}")
    click.echo("\nAuthentication:")
    click.echo("  Codex:            codex login")
    click.echo("  Codex CLI:        npm i -g @openai/codex")
    click.echo("  GitHub Copilot:   copilot login (or COPILOT_GITHUB_TOKEN)")
    click.echo("  Claude:           export ANTHROPIC_API_KEY=...")
    click.echo("  Antigravity SDK:  export GEMINI_API_KEY=...")
    click.echo("\nExternal subscription CLIs are not included in the bundle:")
    click.echo("  Antigravity: https://antigravity.google/docs/cli-install, then run agy")
    click.echo("  Grok:        https://x.ai/cli, then run grok login")
    click.echo("\nRestart SuperQode after changing installed extras.")


@runtime_cmd.command("doctor")
@click.argument("name", required=False)
def doctor(name: Optional[str]) -> None:
    """Probe a runtime's optional dependencies and report what loads.

    With no argument, probes every known runtime. Pass ``agents-md`` to
    inspect AGENTS.md / CLAUDE.md resolution from the current directory.
    """
    # Special target: print the resolved AGENTS.md / CLAUDE.md prompt chain.
    if name == "agents-md":
        from pathlib import Path

        from ..skills import load_project_instructions

        resolved = load_project_instructions(Path.cwd())
        if not resolved:
            console.print(
                "[yellow]No AGENTS.md or CLAUDE.md found from this directory upward.[/yellow]"
            )
            return
        console.rule("[bold]Resolved project instructions[/bold]")
        console.print(resolved)
        return

    target_names: list[str] = []
    info_by_name = {r.name: r for r in list_runtimes()}

    if name is None:
        target_names = list(info_by_name.keys())
    elif name in info_by_name:
        target_names = [name]
    else:
        console.print(f"[red]Unknown runtime '{name}'[/red]")
        console.print(f"Known: {', '.join(sorted(info_by_name))} (or 'agents-md')")
        sys.exit(2)

    any_problems = False
    for target in target_names:
        info = info_by_name[target]
        console.rule(f"[bold]{target}[/bold]")
        console.print(f"  description: {info.description}")
        console.print(f"  installed:   {'yes' if info.installed else 'no'}")
        console.print(f"  implemented: {'yes' if info.implemented else 'no'}")
        console.print(f"  ready:       {'yes' if info.ready else 'no'}")
        if info.status_detail:
            console.print(f"  status:      {info.status_detail}")
        if info.install_hint:
            console.print(f"  install:     [yellow]{info.install_hint}[/yellow]")

        if target == "adk":
            _probe_modules(["google.adk", "google.adk.agents.llm_agent", "google.adk.runners"])
        elif target == "openai-agents":
            _probe_modules(
                [
                    "agents",
                    "agents.tool",
                    "agents.run",
                    "agents.memory.session",
                    "agents.extensions.models.litellm_model",
                ]
            )
        elif target == "pydanticai":
            _probe_modules(
                [
                    "pydantic_ai",
                    "pydantic_ai.agent",
                    "pydantic_ai.toolsets",
                ]
            )
        elif target == "builtin":
            _probe_modules(["superqode.agent.loop", "superqode.tools.base"])

        if not info.usable:
            any_problems = True

    if any_problems:
        sys.exit(1)


def _probe_modules(names: list[str]) -> None:
    """Try to import each module; report success/failure with one indented line each."""
    for mod in names:
        try:
            importlib.import_module(mod)
            console.print(f"    [green]✓[/green] {mod}")
        except Exception as exc:  # noqa: BLE001
            console.print(f"    [red]✗[/red] {mod} — {type(exc).__name__}: {exc}")
