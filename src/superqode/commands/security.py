"""Security scanning commands using SuperClaw integration."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@click.group()
def security():
    """🦞 Agent security testing with SuperClaw."""
    pass


@security.command("scan")
@click.option(
    "--agent",
    "-a",
    default="openclaw",
    help="Agent type to test (openclaw, acp)",
)
@click.option(
    "--target",
    "-t",
    default="ws://127.0.0.1:18789",
    help="Target URL or command",
)
@click.option(
    "--mode",
    "-m",
    type=click.Choice(["quick", "standard", "comprehensive"]),
    default="standard",
    help="Scan mode",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output file for results (JSON)",
)
def scan(agent: str, target: str, mode: str, output: Optional[str]):
    """Run a security scan against an AI agent.

    Examples:

        superqode security scan --agent openclaw --mode quick

        superqode security scan --target ws://127.0.0.1:18789 --mode comprehensive

        superqode security scan -o results.json
    """
    from superqode.integrations.superclaw_runner import (
        print_scan_results,
        run_security_scan,
    )

    console.print(f"\n[bold cyan]🦞 SuperClaw Security Scan[/bold cyan]")
    console.print(f"   Agent: {agent}")
    console.print(f"   Target: {target}")
    console.print(f"   Mode: {mode}\n")

    with console.status("[bold green]Running security scan..."):
        result = run_security_scan(
            agent_type=agent,
            target=target,
            mode=mode,
        )

    print_scan_results(result)

    if output:
        output_path = Path(output)
        result.save(output_path)
        console.print(f"[green]Results saved to {output_path}[/green]")

    # Exit with non-zero if critical/high findings
    if result.critical_findings > 0 or result.high_findings > 0:
        raise SystemExit(1)


@security.command("quick")
@click.option(
    "--agent",
    "-a",
    default="openclaw",
    help="Agent type to test",
)
@click.option(
    "--target",
    "-t",
    default="ws://127.0.0.1:18789",
    help="Target URL",
)
def quick_scan(agent: str, target: str):
    """Run a quick security check (injection + tool policy only).

    Example:

        superqode security quick --agent openclaw
    """
    from superqode.integrations.superclaw_runner import (
        print_scan_results,
        run_quick_scan,
    )

    console.print(f"\n[bold cyan]🦞 Quick Security Check[/bold cyan]\n")

    with console.status("[bold green]Running quick scan..."):
        result = run_quick_scan(agent_type=agent, target=target)

    print_scan_results(result)


@security.command("audit")
@click.option(
    "--agent",
    "-a",
    default="openclaw",
    help="Agent type to test",
)
@click.option(
    "--target",
    "-t",
    default="ws://127.0.0.1:18789",
    help="Target URL",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["html", "json", "sarif"]),
    default="html",
    help="Report format",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="security-audit",
    help="Output file (without extension)",
)
def audit(agent: str, target: str, format: str, output: str):
    """Run a comprehensive security audit with report generation.

    Example:

        superqode security audit --format html --output audit-report
    """
    from superqode.integrations.superclaw_runner import (
        generate_security_report,
        print_scan_results,
        run_comprehensive_scan,
    )

    console.print(f"\n[bold cyan]🦞 Comprehensive Security Audit[/bold cyan]")
    console.print(f"   Agent: {agent}")
    console.print(f"   Target: {target}")
    console.print(f"   Format: {format}\n")

    with console.status("[bold green]Running comprehensive audit..."):
        result = run_comprehensive_scan(agent_type=agent, target=target)

    print_scan_results(result)

    if not result.errors:
        output_path = Path(output)
        try:
            report_path = generate_security_report(result, output_path, format)
            console.print(f"\n[green]Report saved to {report_path}[/green]")
        except Exception as e:
            console.print(f"\n[yellow]Could not generate report: {e}[/yellow]")


@security.command("behaviors")
def list_behaviors():
    """List available security behaviors.

    Example:

        superqode security behaviors
    """
    from superqode.integrations.superclaw_runner import list_available_behaviors

    behaviors = list_available_behaviors()

    if not behaviors:
        console.print("[yellow]SuperClaw not installed. Run: pip install superclaw[/yellow]")
        return

    console.print("\n[bold]Available Security Behaviors:[/bold]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Severity")
    table.add_column("Description")

    severity_colors = {
        "critical": "bold red",
        "high": "red",
        "medium": "yellow",
        "low": "green",
    }

    for b in behaviors:
        severity = b["severity"]
        color = severity_colors.get(severity, "white")
        table.add_row(b["name"], f"[{color}]{severity}[/{color}]", b["description"])

    console.print(table)
    console.print()


@security.command("attacks")
def list_attacks():
    """List available attack techniques.

    Example:

        superqode security attacks
    """
    from superqode.integrations.superclaw_runner import list_available_attacks

    attacks = list_available_attacks()

    if not attacks:
        console.print("[yellow]SuperClaw not installed. Run: pip install superclaw[/yellow]")
        return

    console.print("\n[bold]Available Attack Techniques:[/bold]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Description")

    for a in attacks:
        table.add_row(a["name"], a["type"], a["description"])

    console.print(table)
    console.print()


@security.command("generate")
@click.option(
    "--behavior",
    "-b",
    required=True,
    help="Target behavior for scenario generation",
)
@click.option(
    "--num-scenarios",
    "-n",
    default=10,
    help="Number of scenarios to generate",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="scenarios.json",
    help="Output file for scenarios",
)
def generate_scenarios(behavior: str, num_scenarios: int, output: str):
    """Generate attack scenarios using Bloom.

    Example:

        superqode security generate --behavior prompt-injection --num-scenarios 20
    """
    from superqode.integrations.superclaw_runner import generate_attack_scenarios
    import json

    console.print(f"\n[bold cyan]🌸 Generating Attack Scenarios[/bold cyan]")
    console.print(f"   Behavior: {behavior}")
    console.print(f"   Count: {num_scenarios}\n")

    try:
        with console.status("[bold green]Generating scenarios..."):
            scenarios = generate_attack_scenarios(
                behavior=behavior,
                num_scenarios=num_scenarios,
            )

        output_path = Path(output)
        output_path.write_text(json.dumps(scenarios, indent=2))
        console.print(f"[green]Generated {len(scenarios)} scenarios[/green]")
        console.print(f"[green]Saved to {output_path}[/green]")

    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@security.command("status")
def status():
    """Check SuperClaw installation status.

    Example:

        superqode security status
    """
    from superqode.integrations.superclaw_runner import _check_superclaw_installed

    console.print("\n[bold]🦞 SuperClaw Status[/bold]\n")

    if _check_superclaw_installed():
        try:
            from superclaw import __version__
            from superclaw.attacks import ATTACK_REGISTRY
            from superclaw.behaviors import BEHAVIOR_REGISTRY

            console.print(f"[green]✓ SuperClaw installed (v{__version__})[/green]")
            console.print(f"  • {len(BEHAVIOR_REGISTRY)} behaviors available")
            console.print(f"  • {len(ATTACK_REGISTRY)} attack techniques available")
        except Exception as e:
            console.print(f"[yellow]⚠ SuperClaw partially installed: {e}[/yellow]")
    else:
        console.print("[red]✗ SuperClaw not installed[/red]")
        console.print("\n  Install with:")
        console.print("    pip install superclaw")
        console.print("  or")
        console.print("    pip install -e /path/to/superclaw")

    console.print()
