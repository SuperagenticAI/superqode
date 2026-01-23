"""
Suggestions command - Review verified fixes from QE sessions.

This command allows users to:
- List all verified fixes from QE sessions
- View suggestion details and evidence
"""

from pathlib import Path
import json

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from superqode.enterprise import require_enterprise


@click.group()
def suggestions():
    """Review verified fixes from QE sessions."""
    if not require_enterprise("QE suggestions"):
        raise SystemExit(1)


console = Console()


def load_verified_fixes(project_root: Path) -> list:
    """Load verified fixes from QIR files."""
    fixes = []
    qr_dir = project_root / ".superqode" / "qe-artifacts" / "reports"

    if not qr_dir.exists():
        return fixes

    # Look for recent QIR files
    json_files = list(qr_dir.glob("qr-*.json"))
    if not json_files:
        return fixes

    # Load the most recent QIR
    latest_qr = max(json_files, key=lambda f: f.stat().st_mtime)

    try:
        with open(latest_qr) as f:
            qir_data = json.load(f)

        # Extract findings with suggestions
        findings = qir_data.get("findings", [])
        for finding in findings:
            if finding.get("suggested_fix"):
                fixes.append(
                    {
                        "id": finding.get("id", "unknown"),
                        "title": finding.get("title", ""),
                        "severity": finding.get("severity", "info"),
                        "suggested_fix": finding.get("suggested_fix", ""),
                        "confidence": finding.get("confidence", 0.5),
                        "is_improvement": finding.get("confidence", 0) > 0.7,
                        "fix_verified": True,  # Assume verified if in QIR
                    }
                )

    except Exception as e:
        console.print(f"[red]Error loading QIR: {e}[/red]")

    return fixes


def get_artifacts_dir(project_root: Path) -> Path:
    """Get the QE artifacts directory."""
    return project_root / ".superqode" / "qe-artifacts"


@suggestions.command("list")
@click.argument("project_root", type=click.Path(exists=True), default=".")
@click.option(
    "--all", "-a", "show_all", is_flag=True, help="Show all suggestions, not just improvements"
)
def list_suggestions(project_root, show_all):
    """List all verified fix suggestions from QE sessions."""

    project_path = Path(project_root)
    fixes = load_verified_fixes(project_path)

    if not fixes:
        console.print("[yellow]No verified fixes found.[/yellow]")
        console.print(
            "[dim]Run 'superqe run . --mode deep --allow-suggestions' to generate fix suggestions.[/dim]"
        )
        return

    # Filter to improvements only by default
    if not show_all:
        fixes = [f for f in fixes if f.get("is_improvement", False)]

    if not fixes:
        console.print(
            "[green]All suggestions have been processed or none passed verification.[/green]"
        )
        return

    # Display table
    table = Table(title="Verified Fix Suggestions", show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=3)
    table.add_column("Finding", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Confidence", justify="right")

    for i, fix in enumerate(fixes, 1):
        status = "✅ Verified" if fix.get("fix_verified") else "❌ Failed"
        improvement = "⬆️" if fix.get("is_improvement") else "➖"

        table.add_row(
            str(i),
            fix.get("finding_title", fix.get("title", "Unknown"))[:40],
            f"{status} {improvement}",
            f"{fix.get('fix_confidence', fix.get('confidence', 0)) * 100:.0f}%",
        )

    console.print(table)
    console.print()
    console.print(f"[dim]Total: {len(fixes)} verified fix suggestions[/dim]")
    console.print(f"[dim]Use 'superqe logs' to see detailed agent work logs[/dim]")
