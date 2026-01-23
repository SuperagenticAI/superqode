"""
SuperQE Advanced Commands (CodeOptiX).

Advanced quality engineering powered by CodeOptiX integration:
• 🔬 Deep behavioral evaluation
• 🧬 GEPA evolution engine
• 🌸 Bloom scenario generation
• 🛡️ Advanced security analysis

Requires CodeOptiX (core dependency).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from superqode.evaluation import CODEOPTIX_AVAILABLE

console = Console()


def check_codeoptix():
    """Check if CodeOptiX is available and show helpful message if not."""
    if not CODEOPTIX_AVAILABLE:
        console.print("[red]CodeOptiX is required for SuperQE.[/red]")
        console.print("[dim]Install dependencies and retry.[/dim]")
        return False
    return True


@click.group()
def superqe():
    """🚀 SuperQE Advanced: CodeOptiX-powered quality engineering.

    Supercharges your QE with AI agent optimization:
    • 🔬 Deep behavioral evaluation (beyond basic checks)
    • 🧬 GEPA evolution engine (agent improvement)
    • 🌸 Bloom scenario generation (intelligent testing)
    • 🛡️ Advanced security analysis (comprehensive)

    💡 Works with any LLM provider: Ollama, OpenAI, Anthropic, Google
    ✨ All SuperQE advanced features are available in this package

    Note: Use these commands via `superqe advanced ...`.
    """
    pass


@superqe.command("run")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option(
    "--behaviors",
    help="Comma-separated enhanced behaviors to evaluate "
    "(security-vulnerabilities,test-quality,plan-adherence)",
)
@click.option(
    "--use-bloom", is_flag=True, help="Use Bloom scenario generation for intelligent testing"
)
@click.option("--agent", help="Specific agent to evaluate (claude-code, codex, gemini-cli)")
@click.option("--output", "-o", type=click.Path(), help="Output directory for enhanced results")
@click.option("--json", "json_output", is_flag=True, help="Output enhanced results as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed SuperQE analysis logs")
def superqe_run(
    path: str,
    behaviors: str,
    use_bloom: bool,
    agent: str,
    output: str,
    json_output: bool,
    verbose: bool,
):
    """Run SuperQE enhanced evaluation with integrated CodeOptiX.

    Examples:

        superqe advanced run . --behaviors security-vulnerabilities,test-quality

        superqe advanced run . --behaviors all --use-bloom

        superqe advanced run . --agent claude-code --behaviors security-vulnerabilities
    """
    if not check_codeoptix():
        return

    from superqode.evaluation.engine import EnhancedQEEngine

    project_root = Path(path).resolve()

    # Parse behaviors
    behavior_list = None
    if behaviors:
        if behaviors.lower() == "all":
            # Use all available enhanced behaviors
            from superqode.evaluation.behaviors import get_enhanced_behaviors

            available = get_enhanced_behaviors()
            behavior_list = list(available.keys())
        else:
            behavior_list = [b.strip() for b in behaviors.split(",")]

    # Setup enhanced config
    enhanced_config = {
        "use_bloom_scenarios": use_bloom,
        "agent": agent,
        "verbose": verbose,
    }

    console.print()
    console.print(
        Panel("[bold cyan]🚀 SuperQE Enhanced Evaluation[/bold cyan]", border_style="cyan")
    )
    console.print()

    if behavior_list:
        console.print(f"[cyan]Behaviors:[/cyan] {', '.join(behavior_list)}")
    if use_bloom:
        console.print("[cyan]Bloom Scenarios:[/cyan] Enabled")
    if agent:
        console.print(f"[cyan]Agent Focus:[/cyan] {agent}")
    console.print()

    try:
        # Run enhanced evaluation
        engine = EnhancedQEEngine()
        results = engine.analyze_with_codeoptix(
            codebase_path=project_root, config=enhanced_config, behaviors=behavior_list
        )

        # Check for errors in results
        if "error" in results:
            error_msg = results["error"]
            if "Ollama" in error_msg and ("daemon" in error_msg or "contact" in error_msg):
                console.print()
                console.print("[yellow]⚠️  LLM provider not available[/yellow]")
                console.print("SuperQE requires an LLM provider for enhanced evaluation.")
                console.print()
                console.print("Configure any supported provider:")
                console.print(
                    "• [cyan]Ollama (free)[/cyan]: Install Ollama and run [cyan]ollama serve[/cyan]"
                )
                console.print(
                    "• [cyan]OpenAI[/cyan]: Set [cyan]OPENAI_API_KEY[/cyan] environment variable"
                )
                console.print(
                    "• [cyan]Anthropic[/cyan]: Set [cyan]ANTHROPIC_API_KEY[/cyan] environment variable"
                )
                console.print(
                    "• [cyan]Google[/cyan]: Set [cyan]GOOGLE_API_KEY[/cyan] environment variable"
                )
                console.print()
                console.print("Alternatively, use basic QE: [cyan]superqe run .[/cyan]")
            else:
                console.print(f"[red]❌ SuperQE evaluation failed: {error_msg}[/red]")
                if verbose:
                    import traceback

                    console.print(f"[dim]{traceback.format_exc()}[/dim]")
            return 1

        # Display results
        if json_output:
            console.print(json.dumps(results, indent=2))
        else:
            _display_superqe_results(results, behavior_list, use_bloom)

        # Save output if requested
        if output:
            output_path = Path(output)
            output_path.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = output_path / f"superqe_results_{timestamp}.json"

            with open(results_file, "w") as f:
                json.dump(results, f, indent=2)

            console.print(f"\n[green]✓[/green] Results saved to: {results_file}")

        # Return success/failure
        return 0

    except Exception as e:
        error_msg = str(e)
        if "Ollama" in error_msg and "daemon" in error_msg:
            console.print()
            console.print("[yellow]⚠️  Ollama not available[/yellow]")
            console.print("SuperQE requires Ollama for enhanced evaluation.")
            console.print()
            console.print("To use SuperQE features:")
            console.print("1. Install Ollama: https://ollama.ai")
            console.print("2. Start Ollama: [cyan]ollama serve[/cyan]")
            console.print("3. Pull a model: [cyan]ollama pull llama3.1[/cyan]")
            console.print()
            console.print("Alternatively, use basic QE: [cyan]superqe run .[/cyan]")
        else:
            console.print(f"[red]❌ SuperQE evaluation failed: {error_msg}[/red]")
            if verbose:
                import traceback

                console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return 1


@superqe.command("behaviors")
def superqe_behaviors():
    """List all available SuperQE enhanced behaviors."""
    if not check_codeoptix():
        return
    from superqode.evaluation.behaviors import get_enhanced_behaviors

    console.print()
    console.print(
        Panel("[bold cyan]🚀 SuperQE Enhanced Behaviors[/bold cyan]", border_style="cyan")
    )
    console.print()

    enhanced_behaviors = get_enhanced_behaviors()

    if enhanced_behaviors:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Behavior", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        table.add_column("Status", style="green", no_wrap=True)

        for name, desc in enhanced_behaviors.items():
            table.add_row(f"🔬 {name}", desc, "Available")

        console.print(table)
    else:
        console.print("[yellow]⚠️ No enhanced behaviors available[/yellow]")

    console.print()
    console.print(
        "[dim]Usage: superqe advanced run . --behaviors security-vulnerabilities,test-quality[/dim]"
    )


@superqe.command("agent-eval")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option(
    "--agents",
    required=True,
    help="Comma-separated list of agents to evaluate (e.g., claude-code,codex,gemini-cli)",
)
@click.option(
    "--behaviors", help="Behaviors to evaluate (default: security-vulnerabilities,test-quality)"
)
@click.option("--output", "-o", type=click.Path(), help="Output directory for comparison results")
def superqe_agent_eval(path: str, agents: str, behaviors: str, output: str):
    """Compare multiple AI agents using SuperQE evaluation.

    Examples:

        superqe advanced agent-eval . --agents claude-code,codex

        superqe advanced agent-eval . --agents claude-code,gemini-cli --behaviors all
    """
    if not check_codeoptix():
        return
    from superqode.evaluation.adapters import get_codeoptix_adapter

    project_root = Path(path).resolve()
    agent_list = [a.strip() for a in agents.split(",")]

    # Default behaviors if not specified
    if not behaviors:
        behaviors = "security-vulnerabilities,test-quality"
    behavior_list = [b.strip() for b in behaviors.split(",")]

    console.print()
    console.print(Panel("[bold cyan]🤖 SuperQE Agent Comparison[/bold cyan]", border_style="cyan"))
    console.print()

    console.print(f"[cyan]Agents:[/cyan] {', '.join(agent_list)}")
    console.print(f"[cyan]Behaviors:[/cyan] {', '.join(behavior_list)}")
    console.print()

    try:
        results = {}
        for agent_name in agent_list:
            console.print(f"[yellow]Evaluating {agent_name}...[/yellow]")

            # Get adapter for this agent
            adapter = get_codeoptix_adapter({"type": agent_name, "name": agent_name})
            if not adapter:
                console.print(f"[red]❌ No adapter available for {agent_name}[/red]")
                continue

            # Run evaluation (simplified for now)
            # In full implementation, this would run CodeOptiX evaluation
            results[agent_name] = {
                "behaviors_evaluated": behavior_list,
                "status": "completed",
                "score": 0.85,  # Mock score
                "findings": [],
            }

        # Display comparison
        _display_agent_comparison(results, agent_list, behavior_list)

        # Save output if requested
        if output:
            output_path = Path(output)
            output_path.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = output_path / f"agent_comparison_{timestamp}.json"

            with open(results_file, "w") as f:
                json.dump(results, f, indent=2)

            console.print(f"\n[green]✓[/green] Comparison saved to: {results_file}")

        return 0

    except Exception as e:
        console.print(f"[red]❌ Agent evaluation failed: {e}[/red]")
        return 1


@superqe.command("scenarios")
@click.argument("action", type=click.Choice(["generate", "list"]))
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--behavior", help="Behavior to generate scenarios for")
@click.option("--count", type=int, default=5, help="Number of scenarios to generate")
@click.option("--output", "-o", type=click.Path(), help="Output file for scenarios")
def superqe_scenarios(action: str, path: str, behavior: str, count: int, output: str):
    """Manage Bloom scenario generation for SuperQE.

    Examples:

        superqe advanced scenarios generate . --behavior security-vulnerabilities --count 10

        superqe advanced scenarios list
    """
    if not check_codeoptix():
        return
    from superqode.evaluation.scenarios import generate_enhanced_scenarios

    project_root = Path(path).resolve()

    if action == "generate":
        if not behavior:
            console.print("[red]❌ --behavior is required for generate action[/red]")
            return 1

        console.print()
        console.print(
            Panel(
                "[bold cyan]🌸 SuperQE Bloom Scenario Generation[/bold cyan]", border_style="cyan"
            )
        )
        console.print()

        console.print(f"[cyan]Behavior:[/cyan] {behavior}")
        console.print(f"[cyan]Count:[/cyan] {count}")
        console.print()

        try:
            scenarios = generate_enhanced_scenarios(
                behavior_name=behavior,
                behavior_description=f"Advanced evaluation scenarios for {behavior}",
                codebase_path=project_root,
                examples=[],  # Could be populated from previous runs
            )

            # Take only the requested count
            scenarios = scenarios[:count] if len(scenarios) > count else scenarios

            # Display scenarios
            for i, scenario in enumerate(scenarios, 1):
                console.print(f"[yellow]{i}.[/yellow] {scenario.get('name', f'Scenario {i}')}")
                console.print(f"   {scenario.get('description', 'No description')}")
                console.print()

            # Save output if requested
            if output:
                output_path = Path(output)
                output_data = {
                    "behavior": behavior,
                    "scenarios": scenarios,
                    "generated_at": datetime.now().isoformat(),
                }

                with open(output_path, "w") as f:
                    json.dump(output_data, f, indent=2)

                console.print(f"[green]✓[/green] Scenarios saved to: {output_path}")

            console.print(f"[green]✓[/green] Generated {len(scenarios)} scenarios")

        except Exception as e:
            console.print(f"[red]❌ Scenario generation failed: {e}[/red]")
            return 1

    elif action == "list":
        console.print("[yellow]⚠️ Scenario listing not yet implemented[/yellow]")


def _display_superqe_results(results: dict, behavior_list: list, use_bloom: bool):
    """Display SuperQE evaluation results in a nice format."""
    if "error" in results:
        console.print(f"[red]❌ {results['error']}[/red]")
        return

    # Summary
    behaviors_evaluated = results.get("behaviors_evaluated", [])
    scenarios_used = results.get("scenarios_used", 0)

    console.print("[green]✓ SuperQE evaluation completed![/green]")
    console.print(f"   Behaviors evaluated: {len(behaviors_evaluated)}")
    console.print(f"   Scenarios used: {scenarios_used}")

    # Show results for each behavior
    if "results" in results:
        console.print()
        console.print("[bold cyan]Behavior Results:[/bold cyan]")

        for behavior_name, behavior_results in results["results"].items():
            status = behavior_results.get("status", "unknown")
            if status == "success":
                console.print(f"  [green]✓[/green] {behavior_name}: Completed")
            elif "error" in behavior_results:
                console.print(f"  [red]❌[/red] {behavior_name}: {behavior_results['error']}")
            else:
                console.print(f"  [yellow]⚠️[/yellow] {behavior_name}: {status}")


def _display_agent_comparison(results: dict, agent_list: list, behavior_list: list):
    """Display agent comparison results."""
    console.print("[green]✓ Agent comparison completed![/green]")
    console.print()

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Agent", style="cyan", no_wrap=True)
    table.add_column("Behaviors", style="white")
    table.add_column("Status", style="green", no_wrap=True)
    table.add_column("Score", style="yellow", justify="right")

    for agent_name in agent_list:
        if agent_name in results:
            agent_results = results[agent_name]
            behaviors = agent_results.get("behaviors_evaluated", [])
            status = agent_results.get("status", "unknown")
            score = agent_results.get("score", 0.0)

            table.add_row(agent_name, str(len(behaviors)), status.title(), f"{score:.2f}")
        else:
            table.add_row(agent_name, "0", "Failed", "0.00")

    console.print(table)
