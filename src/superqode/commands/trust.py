"""SuperQode 'trust' CLI: project trust status/doctor/yes/no."""

import json
from pathlib import Path
import click
import click

import click


@click.group()
def trust():
    """Manage local project trust."""
    pass


def _print_trust_status(json_output: bool = False, doctor: bool = False) -> None:
    from superqode.project_trust import get_project_trust, project_risk_signals, trust_store_path

    record = get_project_trust(Path.cwd())
    signals = project_risk_signals(Path.cwd())
    if json_output:
        click.echo(
            json.dumps(
                {
                    "path": record.path,
                    "trusted": record.trusted,
                    "trusted_at": record.trusted_at,
                    "store": str(trust_store_path()),
                    "signals": signals,
                },
                indent=2,
            )
        )
        return
    click.echo(f"Project: {record.path}")
    click.echo(f"Status: {'trusted' if record.trusted else 'untrusted'}")
    if record.trusted_at:
        click.echo(f"Since: {record.trusted_at}")
    click.echo(f"Store: {trust_store_path()}")
    if signals:
        click.echo("Trust-sensitive files:")
        for signal_name in signals:
            click.echo(f"  - {signal_name}")
    elif doctor:
        click.echo("No project-local plugins, MCP config, or hooks detected.")


@trust.command("status")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def trust_status(json_output):
    """Show trust status for the current project."""
    _print_trust_status(json_output=json_output)


@trust.command("doctor")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def trust_doctor(json_output):
    """Show trust-sensitive project-local files."""
    _print_trust_status(json_output=json_output, doctor=True)


@trust.command("yes")
def trust_yes():
    """Trust the current project on this machine."""
    from superqode.project_trust import set_project_trust

    record = set_project_trust(Path.cwd(), True, note="trusted from CLI")
    click.echo(f"Trusted project: {record.path}")


@trust.command("no")
def trust_no():
    """Mark the current project untrusted on this machine."""
    from superqode.project_trust import set_project_trust

    record = set_project_trust(Path.cwd(), False, note="untrusted from CLI")
    click.echo(f"Marked project untrusted: {record.path}")
