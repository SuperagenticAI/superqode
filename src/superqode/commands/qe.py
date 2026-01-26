"""
SuperQE (Super Quality Engineering) CLI commands.

Main entry point for running QE automation with ephemeral workspace guarantees.

Features:
- Git worktree-based isolation
- Session coordination with locking
- JSONL event streaming for CI
- Structured QR with priorities
- Constitution system for guardrails
- Patch harness for validation
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.markdown import Markdown

from superqode.safety import get_safety_warnings, show_safety_warnings, get_warning_acknowledgment
from superqode.enterprise import require_enterprise

console = Console()


def _enterprise_only(feature_name: str) -> bool:
    return require_enterprise(feature_name)


@click.group()
def qe():
    """Quality Engineering automation commands.

    Run QE sessions with full ephemeral workspace guarantee:
    - Agents can freely modify code for testing
    - All changes are automatically reverted
    - Artifacts (patches, tests, QRs) are preserved
    - Git operations are blocked
    """
    pass


@qe.command("run")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option(
    "--mode",
    "-m",
    type=click.Choice(["quick", "deep"]),
    default="quick",
    help="QE mode: quick (fast scan) or deep (full investigation)",
)
@click.option("--role", "-r", multiple=True, help="QE role(s) to run (e.g., qe.security_tester)")
@click.option("--timeout", "-t", type=int, default=None, help="Timeout in seconds")
@click.option("--no-revert", is_flag=True, help="Don't revert changes (for debugging)")
@click.option("--output", "-o", type=click.Path(), help="Output directory for artifacts")
@click.option("--json", "json_output", is_flag=True, help="Output results as JSON")
@click.option("--jsonl", "jsonl_stream", is_flag=True, help="Stream events as JSONL (for CI)")
@click.option("--junit", type=click.Path(), help="Export JUnit XML to file for CI")
@click.option(
    "--worktree",
    "use_worktree",
    is_flag=True,
    help="Use git worktree isolation (writes .git/worktrees; opt-in only)",
)
@click.option("--generate", "-g", is_flag=True, help="Generate tests for detected issues")
@click.option(
    "--allow-suggestions",
    is_flag=True,
    help="Enable suggestion mode: agents can fix bugs, verify fixes, then revert. "
    "Patches preserved for user approval.",
)
@click.option(
    "--verbose", "-v", is_flag=True, help="Show detailed progress and agent work logs in real-time"
)
def qe_run(
    path: str,
    mode: str,
    role: tuple,
    timeout: int,
    no_revert: bool,
    output: str,
    json_output: bool,
    jsonl_stream: bool,
    junit: str,
    use_worktree: bool,
    generate: bool,
    allow_suggestions: bool,
    verbose: bool,
):
    """Run a QE session on the specified path.

    Examples:

        superqe run .                  # Quick scan current directory

        superqe run ./src --mode deep  # Deep QE on src/ (verbose by default)

        superqe run . --verbose        # Show detailed agent work logs

        superqe run . -r security_tester -r api_tester

        superqe run . --junit results.xml  # Export for CI

        superqe run . --jsonl             # Stream JSONL events for CI

        superqe run . --worktree          # Use git worktree isolation

        superqe run . --generate          # Generate tests for issues

        superqe run . --allow-suggestions # Let agents suggest and verify fixes
    """
    if jsonl_stream or junit or generate or allow_suggestions:
        if not _enterprise_only("Advanced QE automation"):
            return 1

    from superqode.superqe import QEOrchestrator, QEEventEmitter, set_event_emitter
    from superqode.workspace import QECoordinator
    from superqode.utils.error_handling import check_dependencies, validate_project_structure
    from superqode.config.loader import find_config_file

    project_root = Path(path).resolve()

    if not find_config_file() and not (project_root / "superqode.yaml").exists():
        console.print(
            "[yellow]⚠️  No superqode.yaml found. Run `superqe init` to create one.[/yellow]"
        )
        return 1

    # Check for basic dependencies first
    if not check_dependencies():
        console.print("[red]❌ Dependency check failed. Please fix issues above.[/red]")
        return 1

    # Validate project structure
    issues = validate_project_structure(project_root)
    if issues["errors"]:
        console.print("[red]❌ Project validation errors:[/red]")
        for error in issues["errors"]:
            console.print(f"   • {error}")
        console.print("[yellow]💡 Fix these issues and try again.[/yellow]")
        return 1

    if issues["warnings"] and not jsonl_stream:
        console.print("[yellow]⚠️  Project warnings:[/yellow]")
        for warning in issues["warnings"]:
            console.print(f"   • {warning}")

    # Setup JSONL streaming if requested
    if jsonl_stream:
        emitter = QEEventEmitter(output=sys.stdout, enabled=True)
        set_event_emitter(emitter)
        # Suppress rich console output when streaming JSONL
        console_output = Console(quiet=True)
    else:
        console_output = console

    # Show safety warnings for QE sessions
    if not jsonl_stream:
        safety_warnings = get_safety_warnings()
        show_safety_warnings(safety_warnings, console=console_output)

        # Get acknowledgment for critical warnings
        if not get_warning_acknowledgment(safety_warnings, console=console_output):
            console_output.print("[yellow]Operation cancelled by user.[/yellow]")
            return 1

    # Check for conflicting sessions using coordinator
    coordinator = QECoordinator(project_root)
    with coordinator.session(
        f"qe-cli-{datetime.now().strftime('%Y%m%d%H%M%S')}", mode, "CLI QE session"
    ) as lock:
        if lock is None:
            if jsonl_stream:
                print(
                    json.dumps(
                        {
                            "type": "qe.blocked",
                            "reason": "Another QE session is already running",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                )
            else:
                console_output.print("[yellow]Another QE session is already running[/yellow]")
                console_output.print("[dim]Use 'superqe status' to check session status[/dim]")
            return 1

        # Warn about worktree isolation touching git metadata
        if use_worktree and not jsonl_stream:
            console_output.print(
                "[yellow]Worktree isolation writes to .git/worktrees. "
                "Use only if you are comfortable with git metadata changes.[/yellow]"
            )
            console_output.print()

        # Show allow_suggestions mode notice
        if allow_suggestions and not jsonl_stream:
            console_output.print()
            console_output.print("[yellow]SUGGESTION MODE ENABLED[/yellow]")
            console_output.print(
                "Agents will fix bugs in an isolated workspace, verify fixes, then revert."
            )
            console_output.print("Patches preserved in .superqode/qe-artifacts/patches/")
            console_output.print()

        # Verbose output only when explicitly requested
        enable_verbose = verbose

        # Create orchestrator
        orchestrator = QEOrchestrator(
            project_root,
            verbose=enable_verbose,
            output_format="jsonl" if jsonl_stream else ("json" if json_output else "rich"),
            use_worktree=use_worktree,
            allow_suggestions=allow_suggestions,
        )

        # Run the appropriate mode or roles
        try:
            # If specific roles are requested, run them
            if role:
                role_list = list(role)
                if not jsonl_stream:
                    console_output.print(f"[cyan]Running QE roles: {', '.join(role_list)}[/cyan]")
                    console_output.print()

                result = _run_async(orchestrator.run_roles(role_list))
            elif mode == "quick":
                result = _run_async(orchestrator.quick_scan())
            else:
                result = _run_async(orchestrator.deep_qe())

            # Handle output options
            if json_output and not jsonl_stream:
                console_output.print(orchestrator.export_json(result))

            if junit:
                junit_path = Path(junit)
                junit_content = orchestrator.export_junit(result)
                junit_path.write_text(junit_content)
                if not jsonl_stream:
                    console_output.print(f"[green]✓[/green] JUnit report saved to {junit_path}")

            # Return exit code based on result
            return 0 if result.success else 1

        except KeyboardInterrupt:
            if not jsonl_stream:
                console_output.print("\n[yellow]Session cancelled by user[/yellow]")
            orchestrator.cancel()
            return 130
        except Exception as e:
            if jsonl_stream:
                print(
                    json.dumps(
                        {
                            "type": "qe.error",
                            "error": str(e),
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                )
            else:
                console_output.print(f"[red]Error:[/red] {e}")
            return 1


@qe.command("roles")
def qe_roles():
    """List all available QE roles."""
    from superqode.superqe import list_roles

    console.print()
    console.print(Panel("[bold]Available QE Roles[/bold]", border_style="cyan"))
    console.print()

    roles = list_roles()

    # Group by type
    execution_roles = [r for r in roles if r["type"] == "execution"]
    detection_roles = [r for r in roles if r["type"] == "detection"]
    heuristic_roles = [r for r in roles if r["type"] == "heuristic"]

    console.print("[bold]Execution Roles[/bold] (run existing tests)")
    for role in execution_roles:
        console.print(f"  [cyan]{role['name']}[/cyan]: {role['description']}")
    console.print()

    console.print("[bold]Detection Roles[/bold] (AI-powered issue detection)")
    for role in detection_roles:
        console.print(f"  [magenta]{role['name']}[/magenta]: {role['description']}")
        if role.get("focus_areas"):
            console.print(f"    [dim]Focus: {', '.join(role['focus_areas'])}[/dim]")
    console.print()

    console.print("[bold]Heuristic Roles[/bold] (senior QE review)")
    for role in heuristic_roles:
        console.print(f"  [green]{role['name']}[/green]: {role['description']}")
    console.print()

    console.print("[dim]Usage: superqe run . -r <role_name> -r <role_name>[/dim]")


@qe.command("behaviors")
def qe_behaviors():
    """List available basic QE behaviors."""
    console.print()
    console.print(Panel("[bold]Basic QE Behaviors[/bold]", border_style="cyan"))
    console.print()

    # Basic behaviors (always available)
    basic_behaviors = {
        "syntax-errors": "Basic syntax validation and linting",
        "code-style": "PEP8 and style checking",
        "imports": "Import organization and dependencies",
        "documentation": "Documentation completeness",
    }

    for name, desc in basic_behaviors.items():
        console.print(f"  [green]✓[/green] [cyan]{name}[/cyan]: {desc}")

    console.print()
    console.print("[yellow]🔬 For advanced CodeOptiX behaviors, use:[/yellow]")
    console.print("  [cyan]superqe advanced behaviors[/cyan]")


@qe.command("quick")
@click.argument("path", type=click.Path(exists=True), default=".")
def qe_quick(path: str):
    """Run a quick scan QE session (alias for 'qe run --mode quick').

    Fast, time-boxed QE for pre-commit and developer feedback.
    """
    from superqode.superqe import QEOrchestrator

    project_root = Path(path).resolve()
    orchestrator = QEOrchestrator(project_root, verbose=False)

    try:
        result = asyncio.get_event_loop().run_until_complete(orchestrator.quick_scan())
        return 0 if result.success else 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Session cancelled[/yellow]")
        return 130
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1


@qe.command("deep")
@click.argument("path", type=click.Path(exists=True), default=".")
def qe_deep(path: str):
    """Run a deep QE session (alias for 'qe run --mode deep').

    Full investigation for pre-release and nightly CI.
    """
    from superqode.superqe import QEOrchestrator

    project_root = Path(path).resolve()
    orchestrator = QEOrchestrator(project_root, verbose=True)

    try:
        result = asyncio.get_event_loop().run_until_complete(orchestrator.deep_qe())
        return 0 if result.success else 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Session cancelled[/yellow]")
        return 130
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1


@qe.command("status")
@click.argument("path", type=click.Path(exists=True), default=".")
def qe_status(path: str):
    """Show current QE workspace status."""
    if not _enterprise_only("QE workspace status"):
        return 1
    from superqode.workspace import WorkspaceManager

    project_root = Path(path).resolve()
    workspace = WorkspaceManager(project_root)

    console.print()
    console.print(Panel("[bold]QE Workspace Status[/bold]", border_style="cyan"))
    console.print()

    # Check if .superqode exists
    superqode_dir = project_root / ".superqode"
    if not superqode_dir.exists():
        console.print("[dim]No .superqode directory found.[/dim]")
        console.print("[dim]Run 'superqe run .' to start a QE session.[/dim]")
        return

    # Show state
    state_file = superqode_dir / "workspace-state.json"
    if state_file.exists():
        import json

        state = json.loads(state_file.read_text())

        table = Table(show_header=False, box=None)
        table.add_column("Key", style="dim")
        table.add_column("Value")

        table.add_row("State", state.get("state", "unknown"))
        table.add_row("Session ID", state.get("session_id") or "-")
        table.add_row("Started", state.get("session_start") or "-")
        table.add_row("Updated", state.get("updated_at") or "-")

        console.print(table)

    # Show artifacts
    artifacts_dir = superqode_dir / "qe-artifacts"
    if artifacts_dir.exists():
        console.print()
        console.print("[bold]Artifacts:[/bold]")

        manifest_file = artifacts_dir / "manifest.json"
        if manifest_file.exists():
            import json

            manifest = json.loads(manifest_file.read_text())

            by_type = {}
            for artifact in manifest.get("artifacts", []):
                t = artifact.get("type", "unknown")
                by_type[t] = by_type.get(t, 0) + 1

            for t, count in sorted(by_type.items()):
                console.print(f"  {t}: {count}")

    # Show recent history
    history_file = superqode_dir / "history" / "sessions.jsonl"
    if history_file.exists():
        console.print()
        console.print("[bold]Recent Sessions:[/bold]")

        sessions = []
        with open(history_file) as f:
            for line in f:
                try:
                    sessions.append(__import__("json").loads(line))
                except Exception:
                    pass

        for session in sessions[-5:]:
            verdict = (
                "✓"
                if session.get("findings_count", 0) == 0
                else f"⚠ {session.get('findings_count')} findings"
            )
            console.print(f"  {session.get('session_id', 'unknown')}: {verdict}")


@qe.command("artifacts")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--type", "-t", "artifact_type", help="Filter by type (patch, test_unit, qr, etc.)")
def qe_artifacts(path: str, artifact_type: str):
    """List QE artifacts from previous sessions."""
    if not _enterprise_only("QE artifacts"):
        return 1
    from superqode.workspace.artifacts import ArtifactManager

    project_root = Path(path).resolve()
    manager = ArtifactManager(project_root)
    manager.initialize("view")

    artifacts = manager.get_all_artifacts()

    if artifact_type:
        artifacts = [a for a in artifacts if a.type.value == artifact_type]

    if not artifacts:
        console.print("[dim]No artifacts found.[/dim]")
        return

    console.print()
    console.print(Panel("[bold]QE Artifacts[/bold]", border_style="cyan"))
    console.print()

    table = Table()
    table.add_column("ID", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Name")
    table.add_column("Description", style="dim")

    for artifact in artifacts:
        table.add_row(
            artifact.id,
            artifact.type.value,
            artifact.name,
            artifact.description[:40] + "..."
            if len(artifact.description) > 40
            else artifact.description,
        )

    console.print(table)


@qe.command("show")
@click.argument("artifact_id")
@click.argument("path", type=click.Path(exists=True), default=".")
def qe_show(artifact_id: str, path: str):
    """Show content of a specific artifact."""
    if not _enterprise_only("QE artifact viewer"):
        return 1
    from superqode.workspace.artifacts import ArtifactManager

    project_root = Path(path).resolve()
    manager = ArtifactManager(project_root)
    manager.initialize("view")

    artifact = manager.get_artifact(artifact_id)
    if not artifact:
        console.print(f"[red]Artifact not found:[/red] {artifact_id}")
        return 1

    content = manager.get_artifact_content(artifact_id)
    if not content:
        console.print(f"[red]Could not read artifact content[/red]")
        return 1

    console.print()
    console.print(
        Panel(
            f"[bold]{artifact.name}[/bold]\n"
            f"[dim]Type: {artifact.type.value}[/dim]\n"
            f"[dim]{artifact.description}[/dim]",
            border_style="cyan",
        )
    )
    console.print()

    # Render based on type
    if artifact.name.endswith(".md"):
        console.print(Markdown(content))
    elif artifact.name.endswith(".patch"):
        console.print(content, highlight=True)
    else:
        console.print(content)


@qe.command("clean")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--keep-qrs", is_flag=True, default=True, help="Keep QR files")
@click.option("--all", "clean_all", is_flag=True, help="Remove all including QRs")
@click.confirmation_option(prompt="Are you sure you want to clean artifacts?")
def qe_clean(path: str, keep_qrs: bool, clean_all: bool):
    """Clean up QE artifacts."""
    if not _enterprise_only("QE artifact cleanup"):
        return 1
    from superqode.workspace.artifacts import ArtifactManager

    project_root = Path(path).resolve()
    manager = ArtifactManager(project_root)
    manager.initialize("cleanup")

    removed = manager.cleanup(keep_qrs=keep_qrs and not clean_all)

    console.print(f"[green]✓[/green] Removed {removed} artifact(s)")


@qe.command("report")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option(
    "--format", "-f", type=click.Choice(["md", "json", "html"]), default="md", help="Output format"
)
@click.option("--output", "-o", type=click.Path(), help="Output file path")
def qe_report(path: str, format: str, output: str):
    """View or export the latest QR."""
    if not _enterprise_only("QE reports"):
        return 1
    from superqode.workspace.artifacts import ArtifactManager, ArtifactType

    project_root = Path(path).resolve()
    manager = ArtifactManager(project_root)
    manager.initialize("view")

    qrs = manager.list_qrs()
    if not qrs:
        console.print("[dim]No QR reports found.[/dim]")
        console.print("[dim]Run 'superqe run .' to generate a report.[/dim]")
        return

    # Get latest QR
    latest = qrs[-1]
    content = manager.get_artifact_content(latest.id)

    if output:
        output_path = Path(output)
        output_path.write_text(content)
        console.print(f"[green]✓[/green] Report saved to {output_path}")
    else:
        console.print()
        if format == "md":
            console.print(Markdown(content))
        else:
            console.print(content)


def _display_session_summary(result):
    """Display a summary of the completed QE session."""
    from superqode.workspace.manager import QESessionResult

    console.print()
    console.print(Panel("[bold]QE Session Complete[/bold]", border_style="green"))
    console.print()

    # Verdict
    if result.critical_count > 0:
        verdict = "[red]🔴 FAIL - Critical issues found[/red]"
    elif result.warning_count > 0:
        verdict = "[yellow]🟡 CONDITIONAL PASS - Warnings found[/yellow]"
    else:
        verdict = "[green]🟢 PASS - No significant issues[/green]"

    console.print(f"Verdict: {verdict}")
    console.print()

    # Summary table
    table = Table(show_header=False, box=None)
    table.add_column("Metric", style="dim")
    table.add_column("Value")

    table.add_row("Session ID", result.session_id)
    table.add_row("Duration", f"{result.duration_seconds:.1f}s")
    table.add_row("Mode", result.mode.value)
    table.add_row("Findings", str(result.findings_count))
    table.add_row("  Critical", str(result.critical_count))
    table.add_row("  Warnings", str(result.warning_count))
    table.add_row("Patches Generated", str(result.patches_generated))
    table.add_row("Tests Generated", str(result.tests_generated))
    table.add_row("Files Modified", str(len(result.files_modified)))
    table.add_row("Files Created", str(len(result.files_created)))
    table.add_row("Reverted", "✓" if result.reverted else "✗")

    console.print(table)
    console.print()

    # Show artifact location
    if result.qir_generated or result.patches_generated or result.tests_generated:
        console.print("[dim]Artifacts saved to:[/dim] .superqode/qe-artifacts/")
        console.print("[dim]View report with:[/dim] superqe report")

    # Errors
    if result.errors:
        console.print()
        console.print("[yellow]Errors:[/yellow]")
        for error in result.errors:
            console.print(f"  • {error}")


@qe.command("logs")
@click.argument("session_id", required=False)
@click.argument("path", type=click.Path(exists=True), default=".")
def qe_logs(session_id: Optional[str], path: str):
    """Show detailed agent work logs for QE sessions.

    Shows the actual agent interaction logs, including connection attempts,
    prompts sent, responses received, and analysis steps. This provides
    complete transparency into the AI analysis process.

    If SESSION_ID is not provided, shows logs for the most recent session.
    """
    if not _enterprise_only("QE logs"):
        return 1
    from superqode.workspace.artifacts import ArtifactManager

    project_root = Path(path).resolve()
    manager = ArtifactManager(project_root)
    manager.initialize("qe_logs")

    console.print()
    console.print(Panel("[bold]AI Agent Work Logs[/bold]", border_style="blue"))
    console.print()

    # Find the session
    superqode_dir = project_root / ".superqode"
    if not superqode_dir.exists():
        console.print("[red]No QE sessions found. Run 'superqe run .' first.[/red]")
        return 1

    # Get session ID if not provided
    if not session_id:
        # Find most recent QE agent log
        qe_logs = manager.list_logs_by_type("qe_agent")
        if qe_logs:
            latest_log = max(qe_logs, key=lambda a: a.created_at)
            console.print(f"[dim]Showing logs for latest QE agent session[/dim]")
            console.print()
        else:
            # Fallback to finding most recent QR
            qr_dir = superqode_dir / "qe-artifacts" / "qr"
            if qr_dir.exists():
                qr_files = list(qr_dir.glob("*.md"))
                if qr_files:
                    latest_qr = max(qr_files, key=lambda f: f.stat().st_mtime)
                    console.print(
                        "[dim]No QE agent logs found, showing QR analysis for latest session[/dim]"
                    )
                    console.print()
                    _show_qr_work_logs(latest_qr)
                    return 0

            console.print("[red]No QE sessions found with work logs.[/red]")
            return 1

    # Try to find QE agent logs for the session
    qe_logs = manager.list_logs_by_type("qe_agent")
    if qe_logs:
        # Filter by session if provided
        if session_id:
            session_logs = [log for log in qe_logs if session_id in log.name]
        else:
            session_logs = qe_logs

        if session_logs:
            # Show the most recent log
            latest_log = max(session_logs, key=lambda a: a.created_at)

            console.print(f"[bold green]📋 QE Agent Session Log[/bold green]")
            console.print(f"[dim]File: {latest_log.path}[/dim]")
            console.print(
                f"[dim]Created: {latest_log.created_at.strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
            )
            console.print()

            log_content = manager.get_artifact_content(latest_log.id)
            if log_content:
                # Display the log with syntax highlighting
                console.print(log_content)
                console.print()
                console.print(
                    "[dim]💡 This log shows the complete agent interaction, including:[/dim]"
                )
                console.print("[dim]   • Connection attempts and responses[/dim]")
                console.print("[dim]   • Prompts sent to the AI agent[/dim]")
                console.print("[dim]   • Analysis steps and reasoning[/dim]")
                console.print("[dim]   • Tool calls and their results[/dim]")
                console.print("[dim]   • Final findings extraction[/dim]")
            else:
                console.print("[red]Could not read log content[/red]")
                return 1
        else:
            console.print(f"[yellow]No QE agent logs found for session {session_id}[/yellow]")
            # Try to show QR work logs as fallback
            _show_qr_work_logs_for_session(session_id, project_root)
    else:
        console.print("[yellow]No QE agent logs found[/yellow]")
        console.print("[dim]QE agent logs are saved automatically during analysis.[/dim]")
        # Try to show QR work logs as fallback
        if session_id:
            _show_qr_work_logs_for_session(session_id, project_root)
        else:
            # Find most recent QR
            qr_dir = superqode_dir / "qe-artifacts" / "qr"
            if qr_dir.exists():
                qr_files = list(qr_dir.glob("*.md"))
                if qr_files:
                    latest_qr = max(qr_files, key=lambda f: f.stat().st_mtime)
                    _show_qr_work_logs(latest_qr)


def _show_qr_work_logs_for_session(session_id: str, project_root: Path):
    """Show work logs extracted from a QR for a specific session."""
    superqode_dir = project_root / ".superqode"
    qr_path = superqode_dir / "qe-artifacts" / "qr" / f"qr-*-qe-{session_id}.md"
    qr_files = list(qr_path.parent.glob(qr_path.name.replace("*", "*")))

    if qr_files:
        _show_qr_work_logs(qr_files[0])
    else:
        console.print(f"[red]QR not found for session: {session_id}[/red]")


@qe.command("dashboard")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--port", "-p", default=8765, help="Port for web server (default: 8765)")
@click.option("--no-open", is_flag=True, help="Don't open browser automatically")
@click.option("--export", "-e", type=click.Path(), help="Export as standalone HTML file")
def qe_dashboard(path: str, port: int, no_open: bool, export: str):
    """Open QR dashboard in web browser.

    Provides an interactive web interface for viewing Quality Reports
    with severity filtering, findings details, and verified fixes visualization.

    Examples:

        superqe dashboard              # Open latest QR in browser

        superqe dashboard --port 9000  # Use custom port

        superqe dashboard --export report.html  # Export as HTML file
    """
    if not _enterprise_only("QE dashboard"):
        return 1
    from superqode.qr.dashboard import start_dashboard, find_latest_qr, export_html

    project_root = Path(path).resolve()

    # Find latest QR
    qr_path = find_latest_qr(project_root)
    if qr_path is None:
        console.print("[red]No QR reports found.[/red]")
        console.print("[dim]Run 'superqe run .' to generate a report first.[/dim]")
        return 1

    console.print(f"[dim]Using QR: {qr_path.name}[/dim]")

    if export:
        # Export mode
        output_path = Path(export)
        result_path = export_html(qr_path, output_path)
        console.print(f"[green]✓[/green] Dashboard exported to {result_path}")
        return 0

    # Start web server
    try:
        start_dashboard(
            qr_path=qr_path,
            project_root=project_root,
            port=port,
            open_browser=not no_open,
        )
    except OSError as e:
        if "Address already in use" in str(e):
            console.print(f"[red]Port {port} is already in use.[/red]")
            console.print(f"[dim]Try: superqe dashboard --port {port + 1}[/dim]")
        else:
            console.print(f"[red]Error starting dashboard: {e}[/red]")
        return 1


def _show_qr_work_logs(qir_file: Path):
    """Show work logs extracted from a QR file."""
    console.print("[bold yellow]📄 Analysis Summary from QR[/bold yellow]")
    console.print(f"[dim]File: {qir_file}[/dim]")
    console.print()

    qir_content = qir_file.read_text()

    # Extract work logs from QR
    work_logs_found = False
    current_section = None
    in_analysis_process = False
    in_evidence = False

    for line in qir_content.split("\n"):
        # Find finding sections
        if line.startswith("### ") and ("🤖" in line or "🔍" in line or "✨" in line):
            if current_section and work_logs_found:
                console.print()  # Add spacing between sections
            current_section = line.replace("### ", "").replace("**", "")
            console.print(f"[bold cyan]{current_section}[/bold cyan]")
            work_logs_found = True
            in_analysis_process = False
            in_evidence = False

        elif current_section:
            if line.startswith("**Agent Analysis Process**:"):
                in_analysis_process = True
                in_evidence = False
                console.print("[yellow]Agent Work Process:[/yellow]")

            elif line.startswith("**Tools Used**:"):
                in_evidence = False
                in_analysis_process = False
                tools = line.replace("**Tools Used**: ", "")
                console.print(f"[green]🔧 Tools Used:[/green] {tools}")

            elif (
                in_analysis_process
                and line.strip()
                and not line.startswith("```")
                and not line.startswith("... and")
            ):
                console.print(f"  {line}")

            elif line.startswith("... and") and "more analysis steps" in line:
                steps_match = line.split("... and ")[1].split(" more")[0]
                console.print(f"  [dim]... and {steps_match} more detailed steps[/dim]")

    if not work_logs_found:
        console.print("[yellow]No detailed work logs found in QR[/yellow]")
        console.print(
            "[dim]Work logs are available in QR reports for sessions with AI agent analysis.[/dim]"
        )

    console.print()
    console.print("[dim]💡 These logs show the analysis steps performed by AI agents,[/dim]")
    console.print(
        "[dim]   demonstrating transparency and trustworthiness of the AI analysis.[/dim]"
    )


@qe.command("feedback")
@click.argument("finding_id")
@click.option(
    "--valid", "feedback_type", flag_value="valid", help="Mark finding as valid (true positive)"
)
@click.option(
    "--false-positive",
    "-fp",
    "feedback_type",
    flag_value="false_positive",
    help="Mark finding as false positive (suppress in future)",
)
@click.option("--fixed", "feedback_type", flag_value="fixed", help="Mark finding as fixed")
@click.option(
    "--wont-fix", "feedback_type", flag_value="wont_fix", help="Mark finding as won't fix"
)
@click.option("--reason", "-r", default="", help="Reason for the feedback")
@click.option(
    "--scope",
    "-s",
    type=click.Choice(["project", "team"]),
    default="project",
    help="Scope for suppression (for false positives)",
)
@click.option(
    "--expires",
    "-e",
    type=int,
    default=None,
    help="Suppression expires in N days (for false positives)",
)
@click.argument("path", type=click.Path(exists=True), default=".")
def qe_feedback(
    finding_id: str, feedback_type: str, reason: str, scope: str, expires: int, path: str
):
    """Provide feedback on a finding to improve future QE runs.

    Feedback types:
    - --valid: Confirm finding is a true positive
    - --false-positive: Suppress this finding in future runs
    - --fixed: Mark as fixed (can learn fix pattern)
    - --wont-fix: Acknowledge but don't fix

    Examples:

        superqe feedback sec-001 --valid

        superqe feedback sec-002 --false-positive -r "Intentional for testing"

        superqe feedback sec-003 --false-positive --scope team -r "Known limitation"

        superqe feedback perf-001 --fixed -r "Optimized query"
    """
    if not _enterprise_only("QE feedback"):
        return 1
    from superqode.memory import FeedbackCollector, MemoryStore

    if not feedback_type:
        console.print("[red]Error:[/red] Must specify feedback type")
        console.print("Options: --valid, --false-positive, --fixed, --wont-fix")
        return 1

    project_root = Path(path).resolve()
    collector = FeedbackCollector(project_root)

    # Find the finding in recent QRs
    finding_info = _find_finding_in_qrs(project_root, finding_id)
    if not finding_info:
        console.print(f"[yellow]Warning:[/yellow] Finding '{finding_id}' not found in recent QRs")
        console.print("[dim]Proceeding with limited information[/dim]")
        finding_info = {
            "id": finding_id,
            "title": finding_id,
            "fingerprint": None,
            "category": "unknown",
            "severity": "medium",
            "found_by": "unknown",
        }

    console.print()
    console.print(f"[bold]Finding:[/bold] {finding_info.get('title', finding_id)}")
    console.print(f"[dim]ID: {finding_id}[/dim]")
    console.print()

    try:
        if feedback_type == "valid":
            collector.mark_valid(
                finding_id=finding_id,
                finding_title=finding_info.get("title", finding_id),
                category=finding_info.get("category", "unknown"),
                severity=finding_info.get("severity", "medium"),
                role_name=finding_info.get("found_by", "unknown"),
                reason=reason,
            )
            console.print("[green]✓[/green] Marked as valid (true positive)")

        elif feedback_type == "false_positive":
            if not reason:
                console.print("[red]Error:[/red] Reason required for false positive")
                console.print("Use: --reason 'Your reason here'")
                return 1

            feedback, suppression = collector.mark_false_positive(
                finding_id=finding_id,
                finding_title=finding_info.get("title", finding_id),
                finding_fingerprint=finding_info.get("fingerprint"),
                role_name=finding_info.get("found_by", "unknown"),
                reason=reason,
                scope=scope,
                expires_in_days=expires,
            )
            console.print("[green]✓[/green] Marked as false positive")
            console.print(f"[dim]Suppression created: {suppression.id}[/dim]")
            if scope == "team":
                console.print("[dim]Saved to .superqode/memory.json (commit to share)[/dim]")
            if expires:
                console.print(f"[dim]Expires in {expires} days[/dim]")

        elif feedback_type == "fixed":
            collector.mark_fixed(
                finding_id=finding_id,
                finding_title=finding_info.get("title", finding_id),
                finding_fingerprint=finding_info.get("fingerprint"),
                fix_description=reason or "Fixed",
            )
            console.print("[green]✓[/green] Marked as fixed")

        elif feedback_type == "wont_fix":
            collector.mark_wont_fix(
                finding_id=finding_id,
                finding_title=finding_info.get("title", finding_id),
                reason=reason or "Won't fix",
            )
            console.print("[green]✓[/green] Marked as won't fix")

        console.print()
        console.print("[dim]Feedback recorded. Future QE runs will use this information.[/dim]")

    except Exception as e:
        console.print(f"[red]Error recording feedback:[/red] {e}")
        return 1

    return 0


def _find_finding_in_qrs(project_root: Path, finding_id: str) -> Optional[Dict]:
    """Search recent QRs for a finding by ID."""
    qr_dir = project_root / ".superqode" / "qe-artifacts" / "qr"
    if not qr_dir.exists():
        return None

    # Search JSON files
    for json_file in sorted(qr_dir.glob("*.json"), reverse=True)[:5]:
        try:
            data = json.loads(json_file.read_text())
            for finding in data.get("findings", []):
                if finding.get("id") == finding_id:
                    return finding
        except Exception:
            continue

    return None


@qe.command("suppressions")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--remove", "-r", help="Remove suppression by ID")
def qe_suppressions(path: str, remove: str):
    """List or manage finding suppressions.

    Suppressions prevent specific findings from appearing in future QE runs.
    They are created via 'superqe feedback --false-positive'.

    Examples:

        superqe suppressions           # List active suppressions

        superqe suppressions -r abc123  # Remove suppression by ID
    """
    if not _enterprise_only("QE suppressions"):
        return 1
    from superqode.memory import MemoryStore

    project_root = Path(path).resolve()
    store = MemoryStore(project_root)
    memory = store.load()

    if remove:
        if store.remove_suppression(remove):
            console.print(f"[green]✓[/green] Removed suppression {remove}")
        else:
            console.print(f"[red]Suppression not found:[/red] {remove}")
        return

    # List suppressions
    active = memory.get_active_suppressions()

    console.print()
    console.print(Panel("[bold]Active Suppressions[/bold]", border_style="cyan"))
    console.print()

    if not active:
        console.print("[dim]No active suppressions[/dim]")
        console.print()
        console.print("[dim]Create suppressions with:[/dim]")
        console.print("  superqe feedback <finding-id> --false-positive -r 'reason'")
        return

    table = Table()
    table.add_column("ID", style="cyan")
    table.add_column("Pattern")
    table.add_column("Type")
    table.add_column("Scope")
    table.add_column("Reason", style="dim")
    table.add_column("Expires")

    for supp in active:
        pattern_display = supp.pattern[:30] + "..." if len(supp.pattern) > 30 else supp.pattern
        expires = supp.expires_at[:10] if supp.expires_at else "-"
        table.add_row(
            supp.id,
            pattern_display,
            supp.pattern_type,
            supp.scope,
            supp.reason[:25] + "..." if len(supp.reason) > 25 else supp.reason,
            expires,
        )

    console.print(table)
    console.print()
    console.print(
        f"[dim]Total: {len(active)} active, {memory.total_suppressions_applied} applied[/dim]"
    )


def _run_async(coro):
    """Run a coroutine from sync CLI code with a compatible event loop."""
    return asyncio.run(coro)
