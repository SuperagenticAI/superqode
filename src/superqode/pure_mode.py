"""
Pure Mode - Minimal Harness for Fair Model Testing.

Integrates with both TUI and CLI for testing model coding capabilities
without the bias of heavy harnesses.
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .agent.loop import AgentLoop, AgentConfig, AgentResponse
from .agent.system_prompts import SystemPromptLevel
from .tools.base import ToolRegistry, ToolResult
from .providers.gateway.litellm_gateway import LiteLLMGateway
from .providers.registry import PROVIDERS, ProviderTier, ProviderCategory


@dataclass
class PureSession:
    """Session state for Pure Mode."""

    provider: str = ""
    model: str = ""
    system_level: SystemPromptLevel = SystemPromptLevel.MINIMAL
    working_directory: Path = field(default_factory=Path.cwd)
    connected: bool = False

    # Stats
    total_tool_calls: int = 0
    total_iterations: int = 0
    total_requests: int = 0


class PureMode:
    """Pure Mode manager for TUI and CLI integration."""

    def __init__(self):
        self.session = PureSession()
        self.gateway = LiteLLMGateway()
        self.tools = ToolRegistry.default()
        self._agent: Optional[AgentLoop] = None

        # Callbacks for UI updates
        self.on_tool_call: Optional[Callable[[str, Dict], None]] = None
        self.on_tool_result: Optional[Callable[[str, ToolResult], None]] = None
        self.on_thinking: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_stream_chunk: Optional[Callable[[str], None]] = None

    def get_providers_for_picker(self) -> List[Dict[str, Any]]:
        """Get providers formatted for the TUI picker."""
        providers = []

        # Group by tier
        tier_order = [ProviderTier.TIER1, ProviderTier.TIER2, ProviderTier.FREE, ProviderTier.LOCAL]

        for tier in tier_order:
            tier_providers = [p for p in PROVIDERS.values() if p.tier == tier]
            for p in sorted(tier_providers, key=lambda x: x.name):
                # Check if configured (has env var set)
                import os

                configured = any(os.environ.get(env) for env in p.env_vars) if p.env_vars else True

                providers.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "tier": tier.name,
                        "category": p.category.value,
                        "configured": configured,
                        "example_models": p.example_models[:3],
                        "notes": p.notes,
                    }
                )

        return providers

    def get_models_for_provider(self, provider_id: str) -> List[str]:
        """Get example models for a provider."""
        provider = PROVIDERS.get(provider_id)
        if provider:
            return provider.example_models
        return []

    def connect(
        self,
        provider: str,
        model: str,
        system_level: SystemPromptLevel = SystemPromptLevel.MINIMAL,
        working_directory: Optional[Path] = None,
        job_description: Optional[str] = None,
        role_config: Optional[Any] = None,
    ) -> bool:
        """Connect to a provider in Pure Mode.

        Args:
            provider: Provider ID (e.g., "ollama", "anthropic")
            model: Model name (e.g., "llama3.2:3b")
            system_level: System prompt verbosity level
            working_directory: Optional working directory
            job_description: Optional job description for role-based connections
            role_config: Optional ResolvedRole config for role context
        """
        self.session.provider = provider
        self.session.model = model
        self.session.system_level = system_level
        self.session.working_directory = working_directory or Path.cwd()
        self.session.connected = True

        # Create agent loop with job description if provided
        config = AgentConfig(
            provider=provider,
            model=model,
            system_prompt_level=system_level,
            working_directory=self.session.working_directory,
            job_description=job_description,
        )

        self._agent = AgentLoop(
            gateway=self.gateway,
            tools=self.tools,
            config=config,
            on_tool_call=self.on_tool_call,
            on_tool_result=self.on_tool_result,
            on_thinking=self.on_thinking,
        )

        # Ensure callbacks are set on the agent (in case they were set after agent creation)
        if self._agent:
            self._agent.on_tool_call = self.on_tool_call
            self._agent.on_tool_result = self.on_tool_result
            self._agent.on_thinking = self.on_thinking

        return True

    def disconnect(self):
        """Disconnect from Pure Mode."""
        self.session = PureSession()
        self._agent = None

    def set_system_level(self, level: SystemPromptLevel):
        """Change the system prompt level."""
        self.session.system_level = level
        if self._agent:
            self._agent.config.system_prompt_level = level
            self._agent.system_prompt = self._agent._build_system_prompt()

    async def run(self, prompt: str) -> AgentResponse:
        """Run a task in Pure Mode."""
        if not self._agent:
            raise RuntimeError("Not connected. Call connect() first.")

        response = await self._agent.run(prompt)

        # Update stats
        self.session.total_tool_calls += response.tool_calls_made
        self.session.total_iterations += response.iterations
        self.session.total_requests += 1

        return response

    async def run_streaming(self, prompt: str):
        """Run a task with streaming output."""
        if not self._agent:
            raise RuntimeError("Not connected. Call connect() first.")

        # Reset cancellation flag for new operation
        self._agent.reset_cancellation()

        async for chunk in self._agent.run_streaming(prompt):
            if self.on_stream_chunk:
                self.on_stream_chunk(chunk)
            yield chunk

        self.session.total_requests += 1

    def cancel(self):
        """Cancel the current agent operation."""
        if self._agent:
            self._agent.cancel()

    def get_status(self) -> Dict[str, Any]:
        """Get current Pure Mode status."""
        return {
            "connected": self.session.connected,
            "provider": self.session.provider,
            "model": self.session.model,
            "system_level": self.session.system_level.value,
            "working_directory": str(self.session.working_directory),
            "stats": {
                "total_requests": self.session.total_requests,
                "total_tool_calls": self.session.total_tool_calls,
                "total_iterations": self.session.total_iterations,
            },
            "tools": [t.name for t in self.tools.list()],
        }


def render_provider_picker(console: Console) -> tuple[str, str]:
    """Interactive provider picker for TUI.

    Returns:
        Tuple of (provider_id, model)
    """
    pure = PureMode()
    providers = pure.get_providers_for_picker()

    console.print()
    console.print(
        Panel.fit(
            "[bold magenta]🧪 Pure Mode[/bold magenta]\n"
            "Select a provider to test model coding capabilities",
            border_style="magenta",
        )
    )
    console.print()

    # Group by tier
    current_tier = None
    tier_names = {
        "TIER1": "⭐ Tier 1 (First-Class Support)",
        "TIER2": "🔷 Tier 2 (Supported)",
        "FREE": "🆓 Free Providers",
        "LOCAL": "🏠 Local Providers",
    }

    provider_list = []
    idx = 1

    for p in providers:
        if p["tier"] != current_tier:
            current_tier = p["tier"]
            console.print(f"\n[bold]{tier_names.get(current_tier, current_tier)}[/bold]")

        status = "✅" if p["configured"] else "○"
        models_hint = ", ".join(p["example_models"][:2]) if p["example_models"] else ""

        console.print(f"  [{idx}] {status} [bold]{p['name']:<15}[/bold] [dim]{models_hint}[/dim]")
        provider_list.append(p)
        idx += 1

    console.print()

    # Get provider selection
    while True:
        try:
            choice = console.input("[bold cyan]Select provider (number): [/bold cyan]")
            provider_idx = int(choice) - 1
            if 0 <= provider_idx < len(provider_list):
                selected_provider = provider_list[provider_idx]
                break
            console.print("[red]Invalid selection[/red]")
        except ValueError:
            console.print("[red]Please enter a number[/red]")

    provider_id = selected_provider["id"]

    # Get model selection
    models = pure.get_models_for_provider(provider_id)

    if models:
        console.print(f"\n[bold]Available models for {selected_provider['name']}:[/bold]")
        for i, model in enumerate(models, 1):
            console.print(f"  [{i}] {model}")
        console.print(f"  [0] Enter custom model")
        console.print()

        while True:
            try:
                choice = console.input("[bold cyan]Select model (number or name): [/bold cyan]")
                if choice == "0":
                    model = console.input("[bold cyan]Enter model name: [/bold cyan]")
                    break
                elif choice.isdigit():
                    model_idx = int(choice) - 1
                    if 0 <= model_idx < len(models):
                        model = models[model_idx]
                        break
                else:
                    # Assume it's a model name
                    model = choice
                    break
                console.print("[red]Invalid selection[/red]")
            except ValueError:
                console.print("[red]Please enter a number or model name[/red]")
    else:
        model = console.input("[bold cyan]Enter model name: [/bold cyan]")

    return provider_id, model


def render_system_level_picker(console: Console) -> SystemPromptLevel:
    """Interactive system prompt level picker."""
    console.print()
    console.print("[bold]System Prompt Level:[/bold]")
    console.print("  [1] [yellow]none[/yellow]     - No system prompt (pure model behavior)")
    console.print("  [2] [green]minimal[/green]  - Just 'You are a coding assistant' [default]")
    console.print("  [3] [cyan]standard[/cyan] - Basic tool usage guidance")
    console.print("  [4] [magenta]full[/magenta]     - Detailed instructions (like other agents)")
    console.print()

    choice = console.input("[bold cyan]Select level (1-4, default=2): [/bold cyan]").strip()

    level_map = {
        "1": SystemPromptLevel.NONE,
        "2": SystemPromptLevel.MINIMAL,
        "3": SystemPromptLevel.STANDARD,
        "4": SystemPromptLevel.FULL,
        "": SystemPromptLevel.MINIMAL,  # Default
    }

    return level_map.get(choice, SystemPromptLevel.MINIMAL)


def render_pure_status(pure: PureMode, console: Console):
    """Render Pure Mode status panel."""
    status = pure.get_status()

    if not status["connected"]:
        console.print("[dim]Pure Mode not connected[/dim]")
        return

    t = Text()
    t.append("🧪 ", style="bold magenta")
    t.append("PURE MODE", style="bold magenta reverse")
    t.append("\n\n")

    t.append("Provider: ", style="bold")
    t.append(f"{status['provider']}\n", style="cyan")

    t.append("Model: ", style="bold")
    t.append(f"{status['model']}\n", style="cyan")

    t.append("System Prompt: ", style="bold")
    t.append(f"{status['system_level']}\n", style="yellow")

    t.append("\nStats:\n", style="bold")
    t.append(f"  Requests: {status['stats']['total_requests']}\n", style="dim")
    t.append(f"  Tool Calls: {status['stats']['total_tool_calls']}\n", style="dim")
    t.append(f"  Iterations: {status['stats']['total_iterations']}\n", style="dim")

    t.append(f"\nTools: {len(status['tools'])}\n", style="dim")

    console.print(Panel(t, border_style="magenta"))


def render_tool_call_inline(name: str, args: Dict, console: Console):
    """Render a tool call inline."""
    console.print(f"  [dim]→[/dim] [yellow]{name}[/yellow]", end="")
    if args:
        # Show key args
        key_args = []
        if "path" in args:
            key_args.append(f"path={args['path']}")
        if "command" in args:
            cmd = (
                args["command"][:30] + "..."
                if len(args.get("command", "")) > 30
                else args.get("command", "")
            )
            key_args.append(f"cmd={cmd}")
        if "pattern" in args:
            key_args.append(f"pattern={args['pattern']}")
        if key_args:
            console.print(f" [dim]({', '.join(key_args)})[/dim]")
        else:
            console.print()
    else:
        console.print()


def render_tool_result_inline(name: str, result: ToolResult, console: Console):
    """Render a tool result inline."""
    if result.success:
        console.print(f"  [green]✓[/green] [dim]{name}[/dim]")
    else:
        console.print(f"  [red]✗[/red] [dim]{name}: {result.error}[/dim]")
