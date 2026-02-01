"""SuperClaw integration for agent security testing.

This module provides SuperQode integration with SuperClaw for running
security tests against AI coding agents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


@dataclass
class SecurityScanResult:
    """Result from a SuperClaw security scan."""

    agent_type: str
    target: str
    timestamp: str
    overall_score: float
    behaviors: dict[str, dict[str, Any]] = field(default_factory=dict)
    attacks: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Check if security scan passed (all behaviors passed)."""
        if not self.behaviors:
            return True
        return all(b.get("passed", False) for b in self.behaviors.values())

    @property
    def critical_findings(self) -> int:
        """Count critical security findings."""
        return self.summary.get("critical", 0)

    @property
    def high_findings(self) -> int:
        """Count high severity findings."""
        return self.summary.get("high", 0)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "agent_type": self.agent_type,
            "target": self.target,
            "timestamp": self.timestamp,
            "overall_score": self.overall_score,
            "behaviors": self.behaviors,
            "attacks": self.attacks,
            "summary": self.summary,
            "passed": self.passed,
            "errors": self.errors,
        }

    def save(self, path: Path) -> None:
        """Save results to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))


def _check_superclaw_installed() -> bool:
    """Check if SuperClaw is installed."""
    try:
        import superclaw

        return True
    except ImportError:
        return False


def run_security_scan(
    agent_type: str = "openclaw",
    target: str = "ws://127.0.0.1:18789",
    behaviors: list[str] | None = None,
    techniques: list[str] | None = None,
    mode: str = "standard",
) -> SecurityScanResult:
    """
    Run a SuperClaw security scan against an agent.

    Args:
        agent_type: Type of agent to test (openclaw, acp, etc.)
        target: Target URL or command
        behaviors: Specific behaviors to test (None = based on mode)
        techniques: Specific attack techniques (None = based on mode)
        mode: Scan mode (quick, standard, comprehensive)

    Returns:
        SecurityScanResult with findings
    """
    if not _check_superclaw_installed():
        return SecurityScanResult(
            agent_type=agent_type,
            target=target,
            timestamp=datetime.now().isoformat(),
            overall_score=0.0,
            errors=["SuperClaw not installed. Run: pip install superclaw"],
        )

    try:
        from superclaw.attacks import run_audit

        results = run_audit(
            agent_type=agent_type,
            target=target,
            mode=mode,
        )

        return SecurityScanResult(
            agent_type=agent_type,
            target=target,
            timestamp=datetime.now().isoformat(),
            overall_score=results.get("overall_score", 0.0),
            behaviors=results.get("behaviors", {}),
            attacks=results.get("attacks", []),
            summary=results.get("summary", {}),
        )

    except Exception as e:
        return SecurityScanResult(
            agent_type=agent_type,
            target=target,
            timestamp=datetime.now().isoformat(),
            overall_score=0.0,
            errors=[str(e)],
        )


def run_quick_scan(
    agent_type: str = "openclaw",
    target: str = "ws://127.0.0.1:18789",
) -> SecurityScanResult:
    """Run a quick security scan (injection + tool policy only)."""
    return run_security_scan(
        agent_type=agent_type,
        target=target,
        mode="quick",
    )


def run_comprehensive_scan(
    agent_type: str = "openclaw",
    target: str = "ws://127.0.0.1:18789",
) -> SecurityScanResult:
    """Run a comprehensive security scan (all behaviors and techniques)."""
    return run_security_scan(
        agent_type=agent_type,
        target=target,
        mode="comprehensive",
    )


def generate_attack_scenarios(
    behavior: str,
    num_scenarios: int = 10,
    variations: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate attack scenarios using SuperClaw's Bloom integration.

    Args:
        behavior: Target behavior (e.g., 'prompt-injection')
        num_scenarios: Number of scenarios to generate
        variations: Variation dimensions (e.g., ['noise', 'emotional_pressure'])

    Returns:
        List of generated scenarios
    """
    if not _check_superclaw_installed():
        raise RuntimeError("SuperClaw not installed. Run: pip install superclaw")

    from superclaw.bloom import generate_scenarios

    return generate_scenarios(
        behavior=behavior,
        num_scenarios=num_scenarios,
        variation_dimensions=variations or ["noise", "emotional_pressure"],
    )


def list_available_behaviors() -> list[dict[str, str]]:
    """List available security behaviors from SuperClaw."""
    if not _check_superclaw_installed():
        return []

    from superclaw.behaviors import BEHAVIOR_REGISTRY

    behaviors = []
    for name, cls in BEHAVIOR_REGISTRY.items():
        instance = cls()
        behaviors.append(
            {
                "name": name,
                "description": instance.get_description()[:60] + "...",
                "severity": instance.severity.value,
            }
        )
    return behaviors


def list_available_attacks() -> list[dict[str, str]]:
    """List available attack techniques from SuperClaw."""
    if not _check_superclaw_installed():
        return []

    from superclaw.attacks import ATTACK_REGISTRY

    attacks = []
    for name, cls in ATTACK_REGISTRY.items():
        instance = cls()
        attacks.append(
            {
                "name": name,
                "description": instance.description[:60] + "..." if instance.description else "",
                "type": instance.attack_type,
            }
        )
    return attacks


def print_scan_results(result: SecurityScanResult) -> None:
    """Print security scan results in a formatted way."""
    # Header
    status_color = "green" if result.passed else "red"
    status_text = "PASSED" if result.passed else "FAILED"

    console.print()
    console.print(
        Panel(
            f"[bold {status_color}]Security Scan: {status_text}[/bold {status_color}]\n\n"
            f"Agent: {result.agent_type}\n"
            f"Target: {result.target}\n"
            f"Score: {result.overall_score:.1%}",
            title="🦞 SuperClaw Security Scan",
            border_style=status_color,
        )
    )

    # Errors
    if result.errors:
        console.print("\n[red]Errors:[/red]")
        for error in result.errors:
            console.print(f"  • {error}")
        return

    # Summary
    if result.summary:
        console.print("\n[bold]Summary:[/bold]")
        summary = result.summary
        console.print(f"  Total behaviors tested: {summary.get('total_behaviors', 0)}")
        console.print(f"  [green]Passed: {summary.get('passed', 0)}[/green]")
        console.print(f"  [red]Failed: {summary.get('failed', 0)}[/red]")
        if summary.get("critical", 0) > 0:
            console.print(f"  [bold red]Critical: {summary.get('critical', 0)}[/bold red]")
        if summary.get("high", 0) > 0:
            console.print(f"  [red]High: {summary.get('high', 0)}[/red]")

    # Behavior details
    if result.behaviors:
        console.print("\n[bold]Behavior Results:[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Behavior")
        table.add_column("Status")
        table.add_column("Score")
        table.add_column("Evidence")

        for name, data in result.behaviors.items():
            passed = data.get("passed", False)
            status = "[green]✓ PASS[/green]" if passed else "[red]✗ FAIL[/red]"
            score = f"{data.get('score', 0):.1%}"
            evidence = ", ".join(data.get("evidence", [])[:2]) or "-"
            if len(evidence) > 40:
                evidence = evidence[:40] + "..."
            table.add_row(name, status, score, evidence)

        console.print(table)

    console.print()


def generate_security_report(
    result: SecurityScanResult,
    output_path: Path,
    format: str = "html",
) -> Path:
    """
    Generate a security report from scan results.

    Args:
        result: Security scan result
        output_path: Output file path (without extension)
        format: Report format (html, json, sarif)

    Returns:
        Path to generated report
    """
    if not _check_superclaw_installed():
        raise RuntimeError("SuperClaw not installed. Run: pip install superclaw")

    from superclaw.reporting import generate_report

    output_file = output_path.with_suffix(f".{format}")
    generate_report(result.to_dict(), format=format, output=str(output_file))
    return output_file
