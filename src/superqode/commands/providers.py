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


console = Console()


@click.group()
def providers():
    """Manage BYOK (Bring Your Own Key) providers."""
    pass


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


@providers.command("mlx")
@click.argument("action", type=click.Choice(["list", "server", "models", "check", "setup"]))
@click.option("--model", "-m", help="Model for server command")
@click.option("--host", default="localhost", help="Server host")
@click.option("--port", default=8080, type=int, help="Server port")
def mlx_command(action: str, model: Optional[str], host: str, port: int):
    """Manage MLX (Apple Silicon) models and servers.

    Actions:
    - list: List available MLX models (cached and server)
    - server: Show command to start MLX server
    - models: Show suggested MLX models
    - check: Check if mlx_lm is installed
    - setup: Complete setup guide for MLX
    """
    from ..providers.local.mlx import MLXClient

    if action == "list":
        console.print("[bold]🔍 Discovering MLX models...[/bold]")

        server_running = False
        server_models = []

        # Show server models if available
        async def check_server():
            nonlocal server_running, server_models
            try:
                client = await get_mlx_client()
                if client:
                    console.print("\n[green]🟢 MLX server running:[/green]")
                    models = await client.list_models()
                    server_running = True
                    server_models = models
                    if models:
                        for model in models:
                            console.print(f"  • {model.id} ({model.name})")
                    else:
                        console.print("  No models loaded")
                else:
                    console.print("\n[yellow]🟡 MLX server not running[/yellow]")
            except Exception as e:
                console.print(f"\n[red]❌ Error checking server: {e}[/red]")

        asyncio.run(check_server())

        # Show cached models (only supported ones)
        console.print("\n[blue]📦 Supported models in HuggingFace cache:[/blue]")
        cache_models = MLXClient.discover_huggingface_models()
        supported_cache_models = [m for m in cache_models if MLXClient.is_model_supported(m["id"])]

        if supported_cache_models:
            for model in supported_cache_models:
                size_mb = model["size_bytes"] / (1024 * 1024)
                format_note = ""
                if "mlx" in model["id"].lower():
                    format_note = " (MLX format)"
                elif "4bit" in model["id"].lower() or "8bit" in model["id"].lower():
                    format_note = " (quantized)"
                console.print(f"  • {model['id']} ({size_mb:.1f} MB){format_note}")
        else:
            console.print("  No supported MLX models found in cache")

        # Show guidance if no server running
        if not server_running:
            console.print(
                "\n[green]✅ Supported formats:[/green] MLX (.npz), safetensors (auto-converted)"
            )
            console.print(
                "  [green]✅ Working architectures:[/green] Standard transformers, QWen, Llama, Mistral, Phi"
            )
            console.print(
                "  [red]❌ Known issues:[/red] MoE models (Mixtral, some gpt-oss) not supported"
            )

            if supported_cache_models:
                console.print("\n  [green]📦 You have supported models available![/green]")
                console.print("  To start MLX server:")
                console.print(
                    "  1. [cyan]superqode providers mlx models[/cyan] - See your cached models"
                )
                console.print(
                    "  2. [cyan]superqode providers mlx server --model <model-id>[/cyan] - Start server"
                )
                console.print("  3. [cyan]superqode connect byok mlx <model-id>[/cyan] - Connect")
            else:
                console.print("\n  [yellow]📥 No supported models found in cache[/yellow]")
                console.print("  To get started with MLX:")
                console.print(
                    "  1. [cyan]superqode providers mlx setup[/cyan] - Complete setup guide"
                )
                console.print(
                    "  2. [cyan]mlx_lm.download mlx-community/Llama-3.2-1B-Instruct-4bit[/cyan] - Download model"
                )
                console.print(
                    "  3. [cyan]mlx_lm.server --model mlx-community/Llama-3.2-1B-Instruct-4bit[/cyan] - Start server"
                )
                console.print(
                    "  4. [cyan]superqode connect byok mlx mlx-community/Llama-3.2-1B-Instruct-4bit[/cyan] - Connect"
                )

    elif action == "server":
        if not model:
            console.print("[red]❌ Model required for server command[/red]")
            console.print("Usage: superqode providers mlx server --model <model-id>")
            console.print()
            console.print("[yellow]💡 Get model IDs with:[/yellow]")
            console.print("  [cyan]superqode providers mlx models[/cyan]")
            console.print("  [cyan]superqode providers mlx list[/cyan]")
            return

        console.print(f"[bold]🚀 MLX Server Setup for {model}:[/bold]")
        console.print()

        from ..providers.local.mlx import MLXClient

        cmd_parts = MLXClient.get_server_command(model, host, port)
        cmd_str = " ".join(cmd_parts)

        console.print("[bold]1. Start the MLX server:[/bold]")
        console.print(f"   [cyan]{cmd_str}[/cyan]")
        console.print()
        console.print("[bold]2. In another terminal, verify server is running:[/bold]")
        console.print(f"   [cyan]curl http://localhost:{port}/v1/models[/cyan]")
        console.print()
        console.print("[bold]3. Connect in SuperQode:[/bold]")
        console.print(f"   [cyan]superqode connect byok mlx {model}[/cyan]")
        console.print()
        console.print("[yellow]💡 Pro tips:[/yellow]")
        console.print("   • Large models (20B+) may take 1-2 minutes to load")
        console.print("   • Keep the server terminal open while using MLX models")
        console.print("   • Use Ctrl+C to stop the server when done")

    elif action == "models":
        console.print("[bold]💡 Suggested MLX Models:[/bold]")
        console.print("   (Optimized for Apple Silicon - fast inference, low memory usage)")
        console.print()

        models = MLXClient.suggest_models()
        for i, model_id in enumerate(models, 1):
            console.print(f"  {i}. [cyan]{model_id}[/cyan]")

        console.print()
        console.print("[bold]Quick Start Commands:[/bold]")
        console.print(f"  [cyan]mlx_lm.download {models[0]}[/cyan]  # Download first model")
        console.print(f"  [cyan]mlx_lm.server --model {models[0]}[/cyan]  # Start server")
        console.print(f"  [cyan]superqode connect byok mlx {models[0]}[/cyan]  # Connect")
        console.print()
        console.print("[yellow]💡 Model Recommendations:[/yellow]")
        console.print("   • Start with smaller models for testing (1B-3B parameters)")
        console.print("   • Use 4bit/8bit quantized models for best performance")
        console.print("   • Larger models need more RAM but provide better quality")
        console.print(
            "   • [red]⚠️  MLX Limitation:[/red] Only one active request per server instance"
        )

    elif action == "check":

        async def check_install():
            installed = await MLXClient.check_mlx_lm_installed()
            if installed:
                console.print("[green]✅ mlx_lm is installed[/green]")
                console.print("Version info:")
                # Try to get version
                import subprocess

                try:
                    result = subprocess.run(
                        ["mlx_lm.server", "--version"], capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        console.print(f"  {result.stdout.strip()}")
                    else:
                        console.print("  Version check failed")
                except Exception:
                    console.print("  Version check failed")
            else:
                console.print("[red]❌ mlx_lm is not installed[/red]")
                console.print()
                console.print("Install with:")
                console.print("  pip install mlx-lm")
                console.print()
                console.print("Or for optional dependency:")
                console.print("  pip install superqode[mlx]")

        asyncio.run(check_install())

    elif action == "setup":
        console.print("[bold]🚀 Complete MLX Setup Guide[/bold]")
        console.print()

        # Supported formats info
        console.print("[green]✅ Supported Formats & Architectures:[/green]")
        console.print("  • [cyan]Formats:[/cyan] MLX (.npz), safetensors (auto-converted)")
        console.print(
            "  • [cyan]Architectures:[/cyan] Standard transformers, QWen, Llama, Mistral, Phi"
        )
        console.print("  • [red]Not supported:[/red] MoE models (Mixtral, some gpt-oss variants)")
        console.print()

        # LM Studio section
        console.print("[bold]🖥️  Alternative: LM Studio (GUI Interface)[/bold]")
        console.print("LM Studio provides a user-friendly GUI for running models locally.")
        console.print()
        console.print("[bold]LM Studio Setup:[/bold]")
        console.print("  1. [cyan]Download LM Studio:[/cyan] https://lmstudio.ai/")
        console.print("  2. [cyan]Install and open LM Studio[/cyan]")
        console.print(
            "  3. [cyan]Download a model:[/cyan] Search for models like 'qwen3-30b' or 'llama3.2-3b'"
        )
        console.print("  4. [cyan]Load the model:[/cyan] Click 'Load Model' in LM Studio")
        console.print(
            "  5. [cyan]Start local server:[/cyan] Go to 'Local Server' tab and click 'Start Server'"
        )
        console.print("     • Default port: 1234")
        console.print("     • Keep LM Studio running in background")
        console.print("  6. [cyan]Connect in SuperQode:[/cyan] superqode connect byok lmstudio")
        console.print()
        console.print("[yellow]💡 LM Studio Tips:[/yellow]")
        console.print("  • No command-line installation needed")
        console.print("  • GUI shows model loading progress")
        console.print("  • Can test models directly in LM Studio first")
        console.print("  • Server runs on http://localhost:1234/v1/chat/completions")
        console.print()

        # Check installation
        console.print("[bold]1. Install MLX:[/bold]")

        async def check_and_guide():
            installed = await MLXClient.check_mlx_lm_installed()
            if installed:
                console.print("  [green]✅ mlx_lm is already installed[/green]")
            else:
                console.print("  [yellow]Install MLX framework:[/yellow]")
                console.print("  [cyan]pip install mlx-lm[/cyan]")
                console.print("  [cyan]# or: pip install superqode[mlx][/cyan]")
            console.print()

        asyncio.run(check_and_guide())

        # Show models
        console.print("[bold]2. Choose and Download a Model:[/bold]")
        models = MLXClient.suggest_models()
        console.print("  [yellow]✅ Recommended working models (smallest to largest):[/yellow]")
        for i, model_id in enumerate(models[:6], 1):  # Show first 6
            size_indicator = ""
            if "0.6b" in model_id or "1B" in model_id:
                size_indicator = " [green](fast)[/green]"
            elif "3B" in model_id or "7B" in model_id:
                size_indicator = " [yellow](medium)[/yellow]"
            elif "30B" in model_id:
                size_indicator = " [red](large)[/red]"
            console.print(f"    {i}. [cyan]{model_id}[/cyan]{size_indicator}")
        console.print()
        console.print("  [yellow]Download a model:[/yellow]")
        console.print(f"  [cyan]mlx_lm.download {models[0]}[/cyan]  # ~1-2 minutes (small model)")
        console.print(f"  [cyan]mlx_lm.download {models[3]}[/cyan]  # ~3-5 minutes (medium model)")
        console.print()
        console.print("  [yellow]💡 MLX Limitations:[/yellow]")
        console.print("    • Each model needs its own server instance")
        console.print("    • One server per model for concurrent use")
        console.print("    • Different ports if running multiple servers")
        console.print("    • Only one active request per server instance")
        console.print()

        # Start server
        console.print("[bold]3. Start the MLX Server:[/bold]")
        console.print("  [yellow]In a separate terminal, run:[/yellow]")
        console.print(f"  [cyan]mlx_lm.server --model {models[0]}[/cyan]")
        console.print()
        console.print("  [yellow]Verify server is running:[/yellow]")
        console.print("  [cyan]curl http://localhost:8080/v1/models[/cyan]")
        console.print()
        console.print(
            "  [yellow]⚠️  Important:[/yellow] MLX servers handle only ONE request at a time"
        )
        console.print("    • Keep this terminal open while using the model")
        console.print("    • Start separate servers on different ports for concurrent use")
        console.print()

        # Connect
        console.print("[bold]4. Connect in SuperQode:[/bold]")
        console.print("  [yellow]Open SuperQode and connect:[/yellow]")
        console.print(f"  [cyan]superqode connect byok mlx {models[0]}[/cyan]")
        console.print()

        # Troubleshooting
        console.print("[bold]5. Troubleshooting:[/bold]")
        console.print("  [yellow]If connection fails:[/yellow]")
        console.print("  • Check server is still running in the terminal")
        console.print("  • Large models may take 1-2 minutes to load")
        console.print("  • Try a smaller model first for testing")
        console.print("  • Check RAM usage - MLX needs available memory")
        console.print()
        console.print("  [yellow]Useful commands:[/yellow]")
        console.print("  • [cyan]superqode providers mlx list[/cyan] - See available models")
        console.print("  • [cyan]superqode providers mlx check[/cyan] - Verify installation")
        console.print("  • [cyan]superqode providers mlx models[/cyan] - See all suggestions")


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
            console.print("  [cyan]uv sync --extra monty[/cyan]")
            console.print("  [cyan]pip install 'superqode\\[monty]'[/cyan]")
        return

    if action == "setup":
        console.print("[bold]Monty Setup[/bold]")
        console.print("Monty enables a safe, fast Python REPL tool for agent-written snippets.")
        console.print()
        console.print("[bold]Install optional dependency:[/bold]")
        console.print("  [cyan]uv sync --extra monty[/cyan]")
        console.print("  [cyan]# or: pip install 'superqode\\[monty]'[/cyan]")
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
        return await tool.execute({"code": "x = 40\nx + 2", "reset": True}, ctx)

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
        # The README's canonical example. Show it verbatim so users can copy-paste
        # without us inventing flag combinations that might drift from upstream.
        console.print("[bold]Recommended ds4-server start command[/bold]")
        console.print()
        console.print(
            "  [cyan]./ds4-server --ctx 100000 "
            "--kv-disk-dir /tmp/ds4-kv --kv-disk-space-mb 8192[/cyan]"
        )
        console.print()
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


def connect_provider(provider: Optional[str] = None, model: Optional[str] = None) -> int:
    """Connect to a BYOK provider/model via CLI.

    Args:
        provider: Optional provider ID (e.g., 'ollama', 'anthropic')
        model: Optional model ID (e.g., 'llama3.2', 'claude-3-5-sonnet')

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    from ..dialogs.provider import ConnectDialog
    from ..providers.manager import ProviderManager

    manager = ProviderManager()

    # If both provider and model are provided, try direct connection
    if provider and model:
        # Validate provider exists
        if provider not in PROVIDERS:
            console.print(f"[red]❌ Provider '{provider}' not found.[/red]")
            console.print(f"[dim]Use 'superqode providers list' to see available providers.[/dim]")
            return 1

        # Test connection
        console.print(f"[cyan]🔍 Testing connection to {provider}/{model}...[/cyan]")
        success, error = manager.test_connection(provider)

        if not success:
            console.print(f"[red]❌ Connection failed: {error}[/red]")
            provider_def = PROVIDERS[provider]
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
        if provider not in PROVIDERS:
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
