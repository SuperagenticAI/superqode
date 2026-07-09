"""
Provider CLI commands for SuperQode.

Commands for listing, showing, and testing BYOK providers.
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from ..providers.registry import (
    PROVIDERS,
    ProviderCategory,
    ProviderTier,
    get_providers_by_category,
    get_providers_by_tier,
    get_free_providers,
    get_local_providers,
)
from ..providers.models import get_models_for_provider
from ..providers.gateway import LiteLLMGateway
from ..providers.local.mlx import get_mlx_client
from ..providers.model_specs import (
    normalize_model_for_provider,
    normalize_provider_id,
    split_provider_model_ref,
)


console = Console()


@click.group()
def providers():
    """Manage BYOK (Bring Your Own Key) providers."""
    pass


@providers.command("scan-free")
@click.option("--provider", help="Filter by provider id or name")
@click.option(
    "--access",
    "access_mode",
    type=click.Choice(["api-key", "account", "acp", "local", "routed"]),
    help="Filter by access path",
)
@click.option(
    "--kind",
    "offer_kind",
    type=click.Choice(["free-tier", "monthly-credits", "free-models", "trial-credits", "local"]),
    help="Filter by offer type",
)
@click.option(
    "--live",
    is_flag=True,
    help="Query live model/pricing catalogs instead of only the curated fallback",
)
@click.option(
    "--source",
    "live_sources",
    multiple=True,
    type=click.Choice(["openrouter", "models-dev", "litellm"]),
    help="Live source to query; repeatable. Defaults to all live sources.",
)
@click.option("--limit", default=100, show_default=True, type=int, help="Maximum live rows")
@click.option("--configured", is_flag=True, help="Only show offers ready on this machine")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def scan_free(
    provider, access_mode, offer_kind, live, live_sources, limit, configured, json_output
):
    """Scan known free-tier, starter-credit, ACP, and local inference paths."""
    import json

    from ..providers.free_inference import (
        list_free_inference_offers,
        offer_status,
        scan_live_free_candidates,
    )

    if live:
        candidates, errors = scan_live_free_candidates(sources=live_sources or None, limit=limit)
        if provider:
            needle = provider.strip().lower()
            candidates = [
                item
                for item in candidates
                if item.provider.lower() == needle
                or needle in item.model.lower()
                or needle in item.name.lower()
            ]
        if access_mode:
            candidates = [item for item in candidates if item.access_mode == access_mode]
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "mode": "live",
                        "sources": list(live_sources) or ["openrouter", "models-dev", "litellm"],
                        "candidates": [item.to_dict() for item in candidates],
                        "errors": errors,
                    },
                    indent=2,
                )
            )
            return

        table = Table(
            title="Live Free Model Route Scan",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Source", style="cyan")
        table.add_column("Provider", style="white")
        table.add_column("Model", style="green")
        table.add_column("Ctx", justify="right")
        table.add_column("Tools", justify="center")
        table.add_column("Source URL", style="dim")
        for item in candidates:
            table.add_row(
                item.source,
                item.provider,
                item.model,
                f"{item.context_window:,}" if item.context_window else "-",
                "yes" if item.supports_tools else "no",
                item.source_url,
            )
        console.print(table)
        if errors:
            console.print()
            for error in errors:
                console.print(f"[yellow]{error['source']} failed:[/yellow] {error['error']}")
        if not candidates:
            console.print("[yellow]No live free model routes found.[/yellow]")
        return

    offers = list_free_inference_offers(
        provider=provider,
        access_mode=access_mode,
        offer_kind=offer_kind,
        configured_only=configured,
    )

    if json_output:
        payload = []
        for offer in offers:
            item = offer.to_dict()
            item["status"] = offer_status(offer)
            payload.append(item)
        click.echo(json.dumps(payload, indent=2))
        return

    table = Table(
        title="Free / Starter Inference Scan",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Provider", style="white")
    table.add_column("Offer", style="green")
    table.add_column("Access", style="cyan")
    table.add_column("Status", style="yellow")
    table.add_column("Models / Path", style="white")
    table.add_column("Verified", style="dim")

    for offer in offers:
        table.add_row(
            offer.provider,
            offer.offer_kind,
            offer.access_mode,
            offer_status(offer),
            ", ".join(offer.models_hint[:2]) or offer.superqode_command,
            offer.last_verified,
        )

    console.print(table)
    if not offers:
        console.print("[yellow]No matching free inference offers found.[/yellow]")
        return

    console.print()
    for offer in offers:
        console.print(f"[bold]{offer.name}[/bold] ({offer.provider})")
        console.print(f"  {offer.summary}")
        console.print(f"  setup: [cyan]{offer.setup}[/cyan]")
        if offer.superqode_command:
            console.print(f"  use: [cyan]{offer.superqode_command}[/cyan]")
        if offer.source_url:
            console.print(f"  source: {offer.source_url}")
        if offer.notes:
            console.print(f"  note: [dim]{offer.notes}[/dim]")


@providers.command("list")
@click.option(
    "--category",
    type=click.Choice(["us", "china", "other-labs", "model-hosts", "local", "free"]),
    help="Filter by category",
)
@click.option(
    "--tier",
    type=click.Choice(["1", "2", "local"]),
    help="Filter by tier",
)
@click.option(
    "--configured",
    is_flag=True,
    help="Show only configured providers",
)
def list_providers(category: Optional[str], tier: Optional[str], configured: bool):
    """List available BYOK providers."""

    # Filter providers
    filtered = dict(PROVIDERS)

    if category:
        category_map = {
            "us": ProviderCategory.US_LABS,
            "china": ProviderCategory.CHINA_LABS,
            "other-labs": ProviderCategory.OTHER_LABS,
            "model-hosts": ProviderCategory.MODEL_HOSTS,
            "local": ProviderCategory.LOCAL,
        }
        if category == "free":
            # Special case: show providers that have free models configured
            filtered = {k: v for k, v in filtered.items() if v.free_models}
        else:
            cat = category_map.get(category)
            if cat:
                filtered = {k: v for k, v in filtered.items() if v.category == cat}

    if tier:
        tier_map = {
            "1": ProviderTier.TIER1,
            "2": ProviderTier.TIER2,
            "free": ProviderTier.FREE,
            "local": ProviderTier.LOCAL,
        }
        t = tier_map.get(tier)
        if t:
            filtered = {k: v for k, v in filtered.items() if v.tier == t}

    # Check configuration status
    provider_status = {}
    for provider_id, provider_def in filtered.items():
        is_configured = False

        if not provider_def.env_vars:
            # Local provider - check if base URL is accessible
            is_configured = True  # Assume local is available
        else:
            # Check if any env var is set
            for env_var in provider_def.env_vars:
                if os.environ.get(env_var):
                    is_configured = True
                    break

        provider_status[provider_id] = is_configured

    if configured:
        filtered = {k: v for k, v in filtered.items() if provider_status.get(k)}

    # Build table
    table = Table(title="BYOK Providers", show_header=True, header_style="bold cyan")
    table.add_column("Provider", style="white")
    table.add_column("Name", style="white")
    table.add_column("Tier", style="dim")
    table.add_column("Category", style="dim")
    table.add_column("Status", style="white")
    table.add_column("Env Var", style="dim")

    # Sort by category then tier
    sorted_providers = sorted(
        filtered.items(), key=lambda x: (x[1].category.value, x[1].tier.value, x[0])
    )

    for provider_id, provider_def in sorted_providers:
        is_configured = provider_status.get(provider_id, False)

        status = "[green]✅ Configured[/green]" if is_configured else "[red]❌ Not configured[/red]"
        if provider_def.category == ProviderCategory.LOCAL and not provider_def.env_vars:
            status = "[blue]🏠 Local[/blue]"

        env_var = provider_def.env_vars[0] if provider_def.env_vars else "(none)"

        tier_str = {
            ProviderTier.TIER1: "Tier 1",
            ProviderTier.TIER2: "Tier 2",
            ProviderTier.FREE: "Free",
            ProviderTier.LOCAL: "Local",
        }.get(provider_def.tier, "")

        table.add_row(
            provider_id,
            provider_def.name,
            tier_str,
            provider_def.category.value,
            status,
            env_var,
        )

    console.print(table)

    # Summary
    configured_count = sum(1 for v in provider_status.values() if v)
    console.print(f"\n[dim]Total: {len(filtered)} providers, {configured_count} configured[/dim]")


@providers.command("show")
@click.argument("provider_id")
def show_provider(provider_id: str):
    """Show details for a specific provider."""

    provider_def = PROVIDERS.get(provider_id)

    if not provider_def:
        console.print(f"[red]Error: Provider '{provider_id}' not found[/red]")
        console.print("\nAvailable providers:")
        for pid in sorted(PROVIDERS.keys()):
            console.print(f"  • {pid}")
        return

    # Check configuration status
    is_configured = False
    configured_env = None

    for env_var in provider_def.env_vars:
        if os.environ.get(env_var):
            is_configured = True
            configured_env = env_var
            break

    # Build info panel
    tier_str = {
        ProviderTier.TIER1: "Tier 1 (First-class support)",
        ProviderTier.TIER2: "Tier 2 (Supported)",
        ProviderTier.FREE: "Free Tier",
        ProviderTier.LOCAL: "Local (Self-hosted)",
    }.get(provider_def.tier, "")

    status = "[green]✅ Configured[/green]" if is_configured else "[red]❌ Not configured[/red]"
    if provider_def.category == ProviderCategory.LOCAL and not provider_def.env_vars:
        status = "[blue]🏠 Local (no API key needed)[/blue]"

    info_lines = [
        f"[bold]Provider:[/bold] {provider_def.name}",
        f"[bold]ID:[/bold] {provider_id}",
        f"[bold]Tier:[/bold] {tier_str}",
        f"[bold]Category:[/bold] {provider_def.category.value}",
        f"[bold]Status:[/bold] {status}",
        "",
    ]

    # Environment variables
    if provider_def.env_vars:
        info_lines.append("[bold]Environment Variables:[/bold]")
        for env_var in provider_def.env_vars:
            is_set = bool(os.environ.get(env_var))
            status_icon = "[green]✓[/green]" if is_set else "[red]✗[/red]"
            info_lines.append(f"  {status_icon} {env_var}")
        info_lines.append("")

    if provider_def.optional_env:
        info_lines.append("[bold]Optional Environment Variables:[/bold]")
        for env_var in provider_def.optional_env:
            is_set = bool(os.environ.get(env_var))
            status_icon = "[green]✓[/green]" if is_set else "[dim]○[/dim]"
            info_lines.append(f"  {status_icon} {env_var}")
        info_lines.append("")

    # Base URL
    if provider_def.base_url_env:
        base_url = os.environ.get(
            provider_def.base_url_env, provider_def.default_base_url or "(not set)"
        )
        info_lines.append(f"[bold]Base URL:[/bold] {base_url}")
        info_lines.append(f"[bold]Base URL Env:[/bold] {provider_def.base_url_env}")
        info_lines.append("")

    # Current models
    current_models = list(get_models_for_provider(provider_id).keys())
    if current_models:
        info_lines.append("[bold]Current Models:[/bold]")
        for model in current_models[:8]:
            info_lines.append(f"  • {model}")
        if len(current_models) > 8:
            info_lines.append(f"  [dim]... and {len(current_models) - 8} more[/dim]")
        info_lines.append("")

    # Free models
    if provider_def.free_models:
        info_lines.append("[bold]Free Models:[/bold]")
        for model in provider_def.free_models:
            info_lines.append(f"  • {model}")
        info_lines.append("")

    # Notes
    if provider_def.notes:
        info_lines.append(f"[bold]Notes:[/bold] {provider_def.notes}")
        info_lines.append("")

    # Docs
    info_lines.append(f"[bold]Documentation:[/bold] {provider_def.docs_url}")

    panel = Panel(
        "\n".join(info_lines),
        title=f"Provider: {provider_def.name}",
        border_style="cyan",
    )
    console.print(panel)

    # Setup instructions if not configured
    if not is_configured and provider_def.env_vars:
        console.print("\n[yellow]To configure this provider:[/yellow]")
        env_var = provider_def.env_vars[0]
        console.print(f'  export {env_var}="your-api-key"')
        console.print(f"\n  Get your API key at: {provider_def.docs_url}")


@providers.command("test")
@click.argument("provider_id")
@click.option("--model", "-m", help="Model to test with")
def test_provider(provider_id: str, model: Optional[str]):
    """Test connection to a provider."""

    provider_def = PROVIDERS.get(provider_id)

    if not provider_def:
        console.print(f"[red]Error: Provider '{provider_id}' not found[/red]")
        return

    # Check if configured
    is_configured = False
    for env_var in provider_def.env_vars:
        if os.environ.get(env_var):
            is_configured = True
            break

    if not is_configured and provider_def.env_vars:
        console.print(f"[red]Error: Provider '{provider_id}' is not configured[/red]")
        console.print(f"\nSet one of: {', '.join(provider_def.env_vars)}")
        console.print(f"Get your API key at: {provider_def.docs_url}")
        return

    current_models = list(get_models_for_provider(provider_id))
    test_model = model or (current_models[0] if current_models else None)

    if not test_model:
        console.print("[red]Error: No model specified and no example models available[/red]")
        return

    console.print(f"Testing {provider_def.name} with model {test_model}...")

    async def run_test():
        gateway = LiteLLMGateway()
        return await gateway.test_connection(provider_id, test_model)

    try:
        result = asyncio.run(run_test())

        if result["success"]:
            console.print(f"\n[green]✅ Success![/green]")
            console.print(f"  Provider: {result['provider']}")
            console.print(f"  Model: {result.get('response_model', test_model)}")
            if result.get("usage"):
                console.print(f"  Tokens used: {result['usage'].get('total_tokens', 'N/A')}")
        else:
            console.print(f"\n[red]❌ Failed[/red]")
            console.print(f"  Error: {result.get('error', 'Unknown error')}")
            if result.get("error_type"):
                console.print(f"  Type: {result['error_type']}")

    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")


@providers.command("monty")
@click.argument("action", type=click.Choice(["check", "smoke", "setup"]))
def monty_command(action: str):
    """Manage optional Monty sandboxed Python REPL support."""
    from ..tools.base import ToolContext
    from ..tools.monty_tool import MontyPythonReplTool, is_monty_available, monty_version

    if action == "check":
        if is_monty_available():
            console.print(f"[green]✅ pydantic-monty is installed[/green] ({monty_version()})")
            console.print(
                "[dim]The python_repl tool is available in standard/full tool profiles.[/dim]"
            )
        else:
            console.print("[red]❌ pydantic-monty is not installed[/red]")
            console.print("Install with:")
            console.print("  [cyan]uv tool install 'superqode\\[monty]'[/cyan]")
            console.print("  [cyan]# or, from a source checkout: uv sync --extra monty[/cyan]")
        return

    if action == "setup":
        console.print("[bold]Monty Setup[/bold]")
        console.print("Monty enables a safe, fast Python REPL tool for agent-written snippets.")
        console.print()
        console.print("[bold]Install optional dependency:[/bold]")
        console.print("  [cyan]uv tool install 'superqode\\[monty]'[/cyan]")
        console.print("  [cyan]# or, from a source checkout: uv sync --extra monty[/cyan]")
        console.print()
        console.print("[bold]Verify:[/bold]")
        console.print("  [cyan]superqode providers monty check[/cyan]")
        console.print("  [cyan]superqode providers monty smoke[/cyan]")
        console.print()
        console.print("[bold]Behavior:[/bold]")
        console.print("  • Tool name: [cyan]python_repl[/cyan]")
        console.print("  • State persists per SuperQode session")
        console.print("  • Filesystem is blocked unless the tool mounts /workspace explicitly")
        console.print("  • Default resource limits cap duration, memory, and recursion depth")
        return

    if not is_monty_available():
        console.print("[red]❌ pydantic-monty is not installed[/red]")
        console.print("Run: [cyan]uv sync --extra monty[/cyan]")
        return

    async def smoke():
        tool = MontyPythonReplTool()
        ctx = ToolContext(session_id="monty-smoke", working_directory=Path.cwd())
        return await tool.execute({"code": "x = 40\nx + 2"}, ctx)

    result = asyncio.run(smoke())
    if result.success and result.output.strip().endswith("42"):
        console.print("[green]✅ Monty smoke test passed[/green]")
        console.print(f"[dim]Output: {result.output.strip()}[/dim]")
    else:
        console.print("[red]❌ Monty smoke test failed[/red]")
        console.print(result.error or result.output)


@providers.command("ds4")
@click.argument("action", type=click.Choice(["doctor", "list", "server"]))
@click.option("--host", default=None, help="Override DS4 base URL (else uses DS4_HOST or default)")
def ds4_command(action: str, host: Optional[str]):
    """Manage the local DS4 (DeepSeek V4 Flash) server.

    Actions:
    - doctor: Connectivity + recommendations (KV-cache, thinking mode)
    - list:   List models with reported context limits
    - server: Print a ready-to-paste ds4-server start command
    """
    from ..providers.local.ds4 import DS4Client, DEFAULT_DS4_HOST
    from ..providers.registry import PROVIDERS

    provider_def = PROVIDERS.get("ds4")
    base_url = (
        host
        or os.environ.get("DS4_HOST")
        or (provider_def.default_base_url if provider_def else DEFAULT_DS4_HOST)
    )

    if action == "server":
        console.print("[bold]Recommended ds4-server start commands[/bold]")
        console.print()
        console.print("[dim]Safe coding default (DS4 upstream default context is 32K):[/dim]")
        console.print(
            "  [cyan]./ds4-server --ctx 32768 "
            "--kv-disk-dir /tmp/ds4-kv --kv-disk-space-mb 8192[/cyan]"
        )
        console.print("[dim]Long local-agent sessions, if memory headroom allows:[/dim]")
        console.print(
            "  [cyan]./ds4-server --ctx 100000 "
            "--kv-disk-dir /tmp/ds4-kv --kv-disk-space-mb 8192[/cyan]"
        )
        console.print("[dim]Think Max requires at least 393,216 context tokens:[/dim]")
        console.print(
            "  [cyan]./ds4-server --ctx 393216 "
            "--kv-disk-dir /tmp/ds4-kv --kv-disk-space-mb 16384[/cyan]"
        )
        console.print()
        console.print("[dim]Managed SuperQode start:[/dim]")
        console.print("  [cyan]superqode local serve ds4 --ctx 32768[/cyan]")
        console.print("[dim]Notes:[/dim]")
        console.print(
            "[dim]  • --kv-disk-dir is what makes prefixes survive restarts and"
            " session switches.[/dim]"
        )
        console.print(
            "[dim]  • --ctx caps the in-memory KV window; raise it only if you have"
            " RAM headroom (full 1M ctx ≈ 26GB).[/dim]"
        )
        console.print(
            "[dim]  • For newer DS4 runtime flags, pass them yourself or use"
            " `superqode local serve ds4 --extra ...`.[/dim]"
        )
        console.print(
            f"[dim]  • SuperQode talks to it at: {base_url} (override with DS4_HOST).[/dim]"
        )
        return

    client = DS4Client(host=base_url)

    if action == "list":

        async def _list():
            available = await client.is_available()
            if not available:
                console.print(f"[red]❌ DS4 not reachable at {base_url}[/red]")
                console.print(
                    "Run [cyan]superqode providers ds4 server[/cyan] for a start command."
                )
                return 1
            models = await client.list_models()
            table = Table(title="DS4 models", header_style="bold")
            table.add_column("Model")
            table.add_column("Context", justify="right")
            table.add_column("Tools", justify="center")
            for m in models:
                table.add_row(
                    m.id,
                    f"{m.context_window:,}",
                    "yes" if m.supports_tools else "no",
                )
            console.print(table)
            return 0

        raise SystemExit(asyncio.run(_list()) or 0)

    # doctor
    async def _doctor() -> int:
        console.print(f"[bold]DS4 doctor[/bold]  ({base_url})")
        console.print()

        status = await client.get_status()
        if not status.available:
            console.print(f"[red]❌ Not reachable:[/red] {status.error}")
            console.print()
            console.print(
                "[yellow]Start the server, then re-run:[/yellow] "
                "[cyan]superqode providers ds4 server[/cyan]"
            )
            return 1

        console.print(
            f"[green]✓ Reachable[/green]  ({status.latency_ms:.0f} ms,"
            f" {status.models_count} model"
            f"{'s' if status.models_count != 1 else ''})"
        )

        models = await client.list_models()
        if models:
            console.print()
            console.print("[bold]Models:[/bold]")
            for m in models:
                console.print(f"  • {m.id}  (ctx {m.context_window:,})")

        # KV-cache reminder. The DS4 server doesn't expose its config, so we
        # can only nudge — but it's the single biggest perf knob.
        console.print()
        console.print("[bold]Recommendations[/bold]")
        console.print(
            "  • [yellow]KV disk cache:[/yellow] start the server with"
            " [cyan]--kv-disk-dir /tmp/ds4-kv --kv-disk-space-mb 8192[/cyan]."
            " Without it, every session restart re-prefills the whole prompt."
        )

        thinking_env = os.environ.get("SUPERQODE_DS4_THINKING", "").strip().lower()
        if not thinking_env:
            console.print(
                "  • [yellow]Thinking mode:[/yellow] unset"
                " (DS4 server default applies). For routine coding sessions"
                " try [cyan]SUPERQODE_DS4_THINKING=low[/cyan]; for tricky"
                " refactors [cyan]high[/cyan] or [cyan]max[/cyan]."
            )
        else:
            console.print(
                f"  • [green]Thinking mode:[/green] {thinking_env} (via SUPERQODE_DS4_THINKING)"
            )

        tool_mode = os.environ.get("SUPERQODE_DS4_TOOL_MODE", "").strip().lower()
        if tool_mode in {"never", "none", "off", "0", "false"}:
            console.print(
                "  • [yellow]Tools:[/yellow] disabled session-wide"
                " (SUPERQODE_DS4_TOOL_MODE=never). Unset to re-enable."
            )
        else:
            console.print(
                "  • [green]Tools:[/green] enabled and prefix-stable"
                " (the rendered request is byte-stable across turns so DS4"
                " can hit its KV checkpoint)."
            )

        return 0

    raise SystemExit(asyncio.run(_doctor()) or 0)


@providers.command("mlx")
@click.argument(
    "action", type=click.Choice(["server", "doctor", "check", "list", "models", "setup"])
)
@click.option(
    "--model", "model_id", default=None, help="HF model id (for example mlx-community/...)"
)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8080, show_default=True, type=int)
@click.option(
    "--extra-arg",
    "extra_args",
    multiple=True,
    help="Extra flag passed through to mlx_lm.server (repeatable)",
)
def mlx_command(action: str, model_id: Optional[str], host: str, port: int, extra_args):
    """Manage a local mlx_lm.server (the WWDC-blessed MLX stack on Apple Silicon).

    Actions:
    - server: Start mlx_lm.server in the foreground (Ctrl+C stops it)
    - doctor: Check the install and whether a server is already answering
    - list: Show running and cached MLX-compatible models
    - models: Show suggested MLX model ids
    - setup: Print the quickest setup path
    """
    import subprocess
    import sys
    from importlib.util import find_spec

    from ..providers.local.mlx import MLXClient

    installed = find_spec("mlx_lm") is not None

    if action in {"doctor", "check"}:
        from ..local.engines import detect_mlx_lm

        status = detect_mlx_lm()
        if status.installed:
            version = f" {status.version}" if status.version else ""
            console.print(f"[green]✓ mlx-lm installed[/green]{version}")
        else:
            console.print("[red]❌ mlx-lm not installed[/red]")
            console.print("Install with: [cyan]uv pip install mlx-lm[/cyan]")
        if status.running:
            console.print(f"[green]✓ Server answering at {status.endpoint}[/green]")
        else:
            console.print(
                f"[yellow]No server at {status.endpoint}.[/yellow] Start one with: "
                "[cyan]superqode providers mlx server --model <hf-id>[/cyan]"
            )
        raise SystemExit(0 if status.installed else 1)

    if action == "list":
        console.print("[bold]MLX models[/bold]")

        async def list_running_models():
            try:
                client = await get_mlx_client()
                if client is None:
                    return []
                return await client.list_models()
            except Exception:
                return []

        running = asyncio.run(list_running_models())
        if running:
            console.print("\n[green]Running server models[/green]")
            for item in running:
                console.print(f"  • {item.id}  (ctx {item.context_window:,})")
        else:
            console.print("\n[yellow]No mlx_lm.server is answering.[/yellow]")

        cached = [
            item
            for item in MLXClient.discover_huggingface_models()
            if MLXClient.is_model_supported(str(item.get("id", "")))
        ]
        console.print("\n[bold]Supported Hugging Face cache models[/bold]")
        if not cached:
            console.print("  No supported MLX models found in the Hugging Face cache.")
            console.print("  Try: superqode providers mlx models")
            return
        for item in cached:
            size_gb = float(item.get("size_bytes") or 0) / (1024**3)
            console.print(f"  • {item['id']}  ({size_gb:.1f}GB)")
        return

    if action == "models":
        console.print("[bold]Suggested MLX models[/bold]")
        for model in MLXClient.suggest_models():
            console.print(f"  • {model}")
        console.print()
        console.print("Start one with: [cyan]superqode providers mlx server --model <hf-id>[/cyan]")
        return

    if action == "setup":
        console.print("[bold]MLX setup[/bold]")
        console.print("1. Install the optional MLX stack:")
        console.print("   [cyan]uv pip install mlx-lm[/cyan]")
        console.print("2. Pick a model:")
        console.print("   [cyan]superqode providers mlx models[/cyan]")
        console.print("3. Start the OpenAI-compatible server:")
        console.print(
            "   [cyan]superqode providers mlx server --model "
            "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit[/cyan]"
        )
        console.print("4. Generate a starter local harness:")
        console.print("   [cyan]superqode local doctor --generate harness.yaml[/cyan]")
        return

    # server
    if not installed:
        console.print("[red]❌ mlx-lm is not installed in this environment.[/red]")
        console.print("Install with: [cyan]uv pip install mlx-lm[/cyan]")
        raise SystemExit(1)
    if not model_id:
        console.print("[red]Pass --model with an HF id, for example:[/red]")
        console.print(
            "  [cyan]superqode providers mlx server"
            " --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit[/cyan]"
        )
        console.print(
            "[dim]Tip: superqode local doctor lists MLX models already in your HF cache.[/dim]"
        )
        raise SystemExit(1)

    cmd = [
        sys.executable,
        "-m",
        "mlx_lm.server",
        "--model",
        model_id,
        "--host",
        host,
        "--port",
        str(port),
    ]
    cmd.extend(extra_args)
    console.print(f"[bold]Starting mlx_lm.server[/bold] on http://{host}:{port}/v1")
    console.print(f"[dim]{' '.join(cmd)}[/dim]")
    console.print(
        f"[dim]Point SuperQode at it with provider [cyan]mlx[/cyan]"
        f" or any OpenAI-compatible route to http://{host}:{port}/v1.[/dim]"
    )
    try:
        raise SystemExit(subprocess.run(cmd).returncode)
    except KeyboardInterrupt:
        console.print("\n[dim]mlx_lm.server stopped.[/dim]")
        raise SystemExit(0) from None


def connect_provider(provider: Optional[str] = None, model: Optional[str] = None) -> int:
    """Connect to a BYOK provider/model via CLI.

    Args:
        provider: Optional provider ID (e.g., 'ollama', 'anthropic')
        model: Optional model ID (e.g., 'llama3.2', 'claude-3-5-sonnet')

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    from ..dialogs.provider import ConnectDialog
    from ..providers.dynamic import resolve_provider_def
    from ..providers.manager import ProviderManager

    manager = ProviderManager()

    def resolve_catalog_provider(provider_id: str):
        """Resolve a dynamic provider, fetching models.dev on a clean install."""
        provider_def = resolve_provider_def(provider_id)
        if provider_def is not None:
            return provider_def
        try:
            import asyncio

            from ..providers.models_dev import get_models_dev

            client = get_models_dev()
            asyncio.run(client.ensure_loaded())
            if client.get_provider(provider_id) is None:
                asyncio.run(client.refresh(force=True))
        except Exception:
            pass
        return resolve_provider_def(provider_id)

    if provider and not model:
        parsed = split_provider_model_ref(provider)
        if parsed.provider and parsed.model:
            provider, model = parsed.provider, parsed.model
        else:
            provider = normalize_provider_id(provider)
    elif provider:
        provider = normalize_provider_id(provider)
        model = normalize_model_for_provider(provider, model)

    # If both provider and model are provided, try direct connection
    if provider and model:
        # Validate provider exists
        provider_def = resolve_catalog_provider(provider)
        if provider_def is None:
            console.print(f"[red]❌ Provider '{provider}' not found.[/red]")
            console.print(f"[dim]Use 'superqode providers list' to see available providers.[/dim]")
            return 1

        # Test connection
        console.print(f"[cyan]🔍 Testing connection to {provider}/{model}...[/cyan]")
        success, error = manager.test_connection(provider, model)

        if not success:
            console.print(f"[red]❌ Connection failed: {error}[/red]")
            if provider_def.env_vars:
                env_var = provider_def.env_vars[0]
                console.print(f"\n[yellow]💡 Set API key:[/yellow]")
                console.print(f"[dim]  export {env_var}=your-key[/dim]")
            return 1

        console.print(f"[green]✓ Connected to {provider}/{model}[/green]")
        console.print(
            "[dim]Note: This is a CLI connection test. For interactive use, run 'superqode' (TUI).[/dim]"
        )
        return 0

    # If only provider is provided, show model selection dialog
    if provider:
        if resolve_catalog_provider(provider) is None:
            console.print(f"[red]❌ Provider '{provider}' not found.[/red]")
            console.print(f"[dim]Use 'superqode providers list' to see available providers.[/dim]")
            return 1

        from ..dialogs.model import ModelDialog

        dialog = ModelDialog(provider, manager)
        model_id = dialog.show()

        if model_id:
            console.print(f"[green]✓ Selected: {provider}/{model_id}[/green]")
            console.print(
                "[dim]Note: This is a CLI selection. For interactive use, run 'superqode' (TUI).[/dim]"
            )
            return 0
        else:
            console.print("[yellow]Connection cancelled.[/yellow]")
            return 1

    # If no provider specified, show full connect dialog
    dialog = ConnectDialog(manager)
    result = dialog.show()

    if result:
        provider_id, model_id = result
        console.print(f"[green]✓ Connected to {provider_id}/{model_id}[/green]")
        console.print(
            "[dim]Note: This is a CLI selection. For interactive use, run 'superqode' (TUI).[/dim]"
        )
        return 0
    else:
        console.print("[yellow]Connection cancelled.[/yellow]")
        return 1


def connect_local_provider(provider: Optional[str] = None, model: Optional[str] = None) -> int:
    """Connect to a local/self-hosted provider/model via CLI.

    Args:
        provider: Optional provider ID (e.g., 'ollama', 'lmstudio', 'mlx')
        model: Optional model ID (e.g., 'llama3.2', 'qwen3-30b')

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    from ..providers.manager import ProviderManager
    from ..providers.registry import get_local_providers, ProviderCategory

    manager = ProviderManager()
    local_providers = get_local_providers()

    # If both provider and model are provided, try direct connection
    if provider and model:
        # Validate provider exists and is local
        if provider not in PROVIDERS:
            console.print(f"[red]❌ Provider '{provider}' not found.[/red]")
            console.print(f"[dim]Use 'superqode providers list' to see available providers.[/dim]")
            return 1

        provider_def = PROVIDERS[provider]
        if provider_def.category != ProviderCategory.LOCAL:
            console.print(f"[red]❌ Provider '{provider}' is not a local provider.[/red]")
            console.print(
                f"[dim]Use 'superqode connect byok {provider}/{model}' for cloud providers.[/dim]"
            )
            console.print(
                f"[dim]Use 'superqode connect local' to see available local providers.[/dim]"
            )
            return 1

        # Test connection (local providers don't need API keys)
        console.print(f"[cyan]🔍 Testing connection to local {provider}/{model}...[/cyan]")
        success, error = manager.test_connection(provider)

        if not success:
            console.print(f"[red]❌ Connection failed: {error}[/red]")
            if provider == "ollama":
                console.print(f"\n[yellow]💡 Make sure Ollama is running:[/yellow]")
                console.print(f"[dim]  1. Start Ollama: ollama serve[/dim]")
                console.print(f"[dim]  2. Verify model: ollama list | grep {model}[/dim]")
                console.print(f"[dim]  3. Pull if needed: ollama pull {model}[/dim]")
            elif provider == "mlx":
                console.print(f"\n[yellow]💡 MLX requires a running server:[/yellow]")
                console.print(f"[dim]  Run: superqode providers mlx server --model {model}[/dim]")
            elif provider == "lmstudio":
                console.print(f"\n[yellow]💡 LM Studio requires the GUI application:[/yellow]")
                console.print(f"[dim]  1. Download: https://lmstudio.ai/[/dim]")
                console.print(f"[dim]  2. Load model in LM Studio[/dim]")
                console.print(f"[dim]  3. Start Local Server[/dim]")
            return 1

        console.print(f"[green]✓ Connected to local {provider}/{model}[/green]")
        console.print(
            "[dim]Note: This is a CLI connection test. For interactive use, run 'superqode' (TUI).[/dim]"
        )
        return 0

    # If only provider is provided, show model selection
    if provider:
        if provider not in PROVIDERS:
            console.print(f"[red]❌ Provider '{provider}' not found.[/red]")
            console.print(f"[dim]Use 'superqode providers list' to see available providers.[/dim]")
            return 1

        provider_def = PROVIDERS[provider]
        if provider_def.category != ProviderCategory.LOCAL:
            console.print(f"[red]❌ Provider '{provider}' is not a local provider.[/red]")
            console.print(
                f"[dim]Use 'superqode connect byok {provider}' for cloud providers.[/dim]"
            )
            return 1

        from ..dialogs.model import ModelDialog

        dialog = ModelDialog(provider, manager)
        model_id = dialog.show()

        if model_id:
            console.print(f"[green]✓ Selected: {provider}/{model_id}[/green]")
            console.print(
                "[dim]Note: This is a CLI selection. For interactive use, run 'superqode' (TUI).[/dim]"
            )
            return 0
        else:
            console.print("[yellow]Connection cancelled.[/yellow]")
            return 1

    # If no provider specified, show local providers
    if not local_providers:
        console.print("[yellow]⚠️  No local providers configured.[/yellow]")
        console.print("[dim]Local providers include: ollama, lmstudio, mlx, vllm, etc.[/dim]")
        return 1

    console.print("\n[bold cyan]💻 Local Providers[/bold cyan]\n")
    console.print("[dim]No API key required - these run on your machine[/dim]\n")

    for idx, (provider_id, provider_def) in enumerate(local_providers.items(), 1):
        console.print(f"  [{idx}] [cyan]{provider_def.name}[/cyan] ({provider_id})")
        console.print(f"      {provider_def.description}")
        if provider_def.example_models:
            example = provider_def.example_models[0]
            console.print(
                f"      Example: [dim]superqode connect local {provider_id}/{example}[/dim]"
            )
        console.print()

    console.print("[dim]💡 Use: superqode connect local <provider>[/<model>][/dim]")
    console.print("[dim]   Example: superqode connect local ollama/llama3.2[/dim]")
    return 0


# Register with main CLI
def register_commands(cli):
    """Register provider commands with the main CLI."""
    cli.add_command(providers)
