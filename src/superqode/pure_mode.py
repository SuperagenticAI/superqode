"""
Pure Mode - Minimal Harness for Fair Model Testing.

Integrates with both TUI and CLI for testing model coding capabilities
without the bias of heavy harnesses.
"""

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .agent.loop import AgentLoop, AgentConfig, AgentResponse
from .agent.system_prompts import SystemPromptLevel
from .agent.session_manager import SessionManager, SessionMetadata
from .tools.base import ToolRegistry, ToolResult
from .providers.gateway.litellm_gateway import LiteLLMGateway
from .providers.registry import PROVIDERS, ProviderTier, ProviderCategory
from .runtime import AgentRuntime, create_runtime, resolve_runtime_name


@dataclass
class PureSession:
    """Session state for Pure Mode."""

    provider: str = ""
    model: str = ""
    system_level: SystemPromptLevel = SystemPromptLevel.MINIMAL
    working_directory: Path = field(default_factory=Path.cwd)
    connected: bool = False
    harness_name: str = ""
    harness_path: str = ""
    harness_flavor: str = ""
    harness_runtime: str = ""

    # Stats
    total_tool_calls: int = 0
    total_iterations: int = 0
    total_requests: int = 0


class PureMode:
    """Pure Mode manager for TUI and CLI integration."""

    def __init__(self, runtime: Optional[str] = None):
        self.session = PureSession()
        self.gateway = LiteLLMGateway()
        self._tool_profile_env = os.getenv("SUPERQODE_TOOL_PROFILE", "").strip().lower()
        self.tool_profile = self._tool_profile_env or "coding"
        self.tools = ToolRegistry.for_profile(self.tool_profile)
        self.runtime_name = resolve_runtime_name(cli=runtime)
        self._runtime: Optional[AgentRuntime] = None
        self._agent: Optional[AgentLoop] = None
        self._session_manager: Optional[SessionManager] = None
        self._harness_spec = None
        self._harness_path = ""
        self._harness_kernel = None
        self._harness_session = None
        self._harness_session_id = ""
        self._load_env_harness()

        # Callbacks for UI updates
        self.on_tool_call: Optional[Callable[[str, Dict], None]] = None
        self.on_tool_result: Optional[Callable[[str, ToolResult], None]] = None
        self.on_thinking: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_stream_chunk: Optional[Callable[[str], None]] = None

    def _load_env_harness(self) -> None:
        path = os.getenv("SUPERQODE_HARNESS", "").strip()
        if not path:
            return
        self.load_harness(path)

    def load_harness(self, path: str | Path):
        """Load a HarnessSpec for subsequent provider connections."""
        from superqode.harness import load_harness_spec

        spec_path = Path(path).expanduser()
        self._harness_spec = load_harness_spec(spec_path)
        self._harness_path = str(spec_path)
        self._harness_kernel = None
        self._harness_session = None
        self._harness_session_id = ""
        return self._harness_spec

    def set_harness(self, spec, *, path: str | Path | None = None) -> None:
        """Set an already loaded HarnessSpec."""
        self._harness_spec = spec
        self._harness_path = str(path or "")
        self._harness_kernel = None
        self._harness_session = None
        self._harness_session_id = ""

    def clear_harness(self) -> None:
        """Return to direct runtime mode."""
        self._harness_spec = None
        self._harness_path = ""
        self._harness_kernel = None
        self._harness_session = None
        self._harness_session_id = ""

    @property
    def harness_enabled(self) -> bool:
        return self._harness_spec is not None

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
        session_id: Optional[str] = None,
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
        if self._harness_spec is not None:
            self.session.harness_name = self._harness_spec.name
            self.session.harness_path = self._harness_path
            self.session.harness_flavor = self._harness_spec.flavor.value
            self.session.harness_runtime = self._harness_spec.runtime.backend
            if self._harness_spec.is_no_tool:
                self.tool_profile = "none"
                self.tools = ToolRegistry.empty()
            self._runtime = None
            self._agent = None
            return True

        provider_def = PROVIDERS.get(provider)
        is_ds4 = provider == "ds4"
        if is_ds4 and not self._tool_profile_env:
            self.tool_profile = "ds4"
            self.tools = ToolRegistry.for_profile(self.tool_profile)
        elif self._tool_profile_env and self.tool_profile != self._tool_profile_env:
            self.tool_profile = self._tool_profile_env
            self.tools = ToolRegistry.for_profile(self.tool_profile)

        if is_ds4:
            max_iterations = int(os.getenv("DS4_MAX_ITERATIONS", "6"))
            session_history_limit = int(os.getenv("DS4_SESSION_HISTORY_LIMIT", "8"))
            parallel_tools = False

            # DS4 KV cache configuration
            kv_disk_dir = os.getenv("DS4_KV_DISK_DIR", "/tmp/ds4-kv")
            kv_disk_space = int(os.getenv("DS4_KV_DISK_SPACE_MB", "8192"))
            os.environ["DS4_KV_DISK_DIR"] = kv_disk_dir
            os.environ["DS4_KV_DISK_SPACE_MB"] = str(kv_disk_space)
        else:
            default_max = (
                30 if provider_def and provider_def.category == ProviderCategory.LOCAL else 50
            )
            max_iterations = int(os.getenv("SUPERQODE_MAX_ITERATIONS", str(default_max)))
            session_history_limit = int(os.getenv("SUPERQODE_SESSION_HISTORY_LIMIT", "20"))
            parallel_tools = True

        # Create agent loop with job description if provided
        config = AgentConfig(
            provider=provider,
            model=model,
            system_prompt_level=system_level,
            working_directory=self.session.working_directory,
            job_description=job_description,
            max_iterations=max_iterations,
            enable_session_storage=True,
            session_storage_dir=".superqode/sessions",
            session_id=session_id,
            session_history_limit=session_history_limit,
        )

        self._runtime = create_runtime(
            self.runtime_name,
            gateway=self.gateway,
            tools=self.tools,
            config=config,
            on_tool_call=self.on_tool_call,
            on_tool_result=self.on_tool_result,
            on_thinking=self.on_thinking,
            parallel_tools=parallel_tools,
        )
        self._agent = getattr(self._runtime, "loop", None)

        # Ensure callbacks are set on the agent (in case they were set after agent creation)
        if self._agent:
            self._agent.on_tool_call = self.on_tool_call
            self._agent.on_tool_result = self.on_tool_result
            self._agent.on_thinking = self.on_thinking
            self._session_manager = self._agent._session_manager

        return True

    def disconnect(self):
        """Disconnect from Pure Mode."""
        self.session = PureSession()
        self._agent = None
        self._runtime = None
        self._harness_kernel = None
        self._harness_session = None
        self._harness_session_id = ""

    def set_system_level(self, level: SystemPromptLevel):
        """Change the system prompt level."""
        self.session.system_level = level
        if self._agent:
            self._agent.config.system_prompt_level = level
            self._agent.system_prompt = self._agent._build_system_prompt()

    async def run(self, prompt: str, plan_mode: Optional[bool] = None) -> AgentResponse:
        """Run a task in Pure Mode."""
        if self._harness_spec is not None:
            session = await self._ensure_harness_session()
            result = await session.prompt(
                prompt,
                provider=self.session.provider,
                model=self.session.model,
                working_directory=self.session.working_directory,
                runtime=self._harness_spec.runtime.backend,
            )
            self.session.total_tool_calls += result.tool_calls_made
            self.session.total_iterations += result.iterations
            self.session.total_requests += 1
            return result.response

        if not self._agent:
            raise RuntimeError("Not connected. Call connect() first.")

        previous_plan_mode = self._agent.config.plan_mode
        if plan_mode is not None:
            self._agent.config.plan_mode = plan_mode
        try:
            response = await self._agent.run(prompt)
        finally:
            self._agent.config.plan_mode = previous_plan_mode

        # Update stats
        self.session.total_tool_calls += response.tool_calls_made
        self.session.total_iterations += response.iterations
        self.session.total_requests += 1

        return response

    async def run_streaming(self, prompt: str, plan_mode: Optional[bool] = None):
        """Run a task with streaming output."""
        if self._harness_spec is not None:
            session = await self._ensure_harness_session()
            async for event in session.stream(
                prompt,
                provider=self.session.provider,
                model=self.session.model,
                working_directory=self.session.working_directory,
                runtime=self._harness_spec.runtime.backend,
            ):
                if event.type != "delta":
                    continue
                chunk = str(event.data.get("text", ""))
                if self.on_stream_chunk:
                    self.on_stream_chunk(chunk)
                yield chunk
            self.session.total_requests += 1
            return

        if not self._agent:
            raise RuntimeError("Not connected. Call connect() first.")

        # Reset cancellation flag for new operation
        self._agent.reset_cancellation()

        previous_plan_mode = self._agent.config.plan_mode
        if plan_mode is not None:
            self._agent.config.plan_mode = plan_mode
        try:
            async for chunk in self._agent.run_streaming(prompt):
                if self.on_stream_chunk:
                    self.on_stream_chunk(chunk)
                yield chunk
        finally:
            self._agent.config.plan_mode = previous_plan_mode

        self.session.total_requests += 1

    async def _ensure_harness_session(self):
        if self._harness_spec is None:
            raise RuntimeError("No HarnessSpec loaded.")
        if self._harness_session is not None:
            return self._harness_session
        from superqode.harness import FileHarnessStore, init_harness

        self._harness_kernel = await init_harness(
            self._harness_spec,
            store=FileHarnessStore(Path(self._harness_spec.context.session_storage)),
        )
        self._harness_session_id = self._harness_session_id or ""
        self._harness_session = await self._harness_kernel.session(self._harness_session_id or None)
        self._harness_session_id = self._harness_session.session_id
        return self._harness_session

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        """Return pending approval requests from the active harness or runtime."""
        if self._harness_session is not None:
            pending = self._harness_session.pending_approvals()
            if pending:
                return [dict(item) for item in pending]
        if self._runtime is not None and hasattr(self._runtime, "get_pending_approvals"):
            return [dict(item) for item in self._runtime.get_pending_approvals()]
        return []

    async def approve_and_resume(self, index: int = 0, *, always: bool = False) -> AgentResponse:
        """Approve a pending tool call and resume the active harness or runtime."""
        if self._harness_session is not None and self._harness_session.pending_approvals():
            return await self._harness_session.approve_pending(index=index, always=always)
        if self._runtime is not None and hasattr(self._runtime, "approve_and_resume"):
            return await self._runtime.approve_and_resume(index=index, always=always)
        raise RuntimeError("No pending approval to approve")

    async def reject_and_resume(
        self,
        index: int = 0,
        *,
        message: str | None = None,
        always: bool = False,
    ) -> AgentResponse:
        """Reject a pending tool call and resume the active harness or runtime."""
        if self._harness_session is not None and self._harness_session.pending_approvals():
            return await self._harness_session.reject_pending(
                index=index,
                message=message,
                always=always,
            )
        if self._runtime is not None and hasattr(self._runtime, "reject_and_resume"):
            return await self._runtime.reject_and_resume(
                index=index,
                message=message,
                always=always,
            )
        raise RuntimeError("No pending approval to reject")

    def clear_pending(self) -> None:
        """Clear pending approval state when the underlying runtime supports it."""
        if self._runtime is not None and hasattr(self._runtime, "clear_pending"):
            self._runtime.clear_pending()

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
            "tool_profile": self.tool_profile,
            "harness": {
                "enabled": self._harness_spec is not None,
                "name": self.session.harness_name,
                "path": self.session.harness_path,
                "flavor": self.session.harness_flavor,
                "runtime": self.session.harness_runtime,
            },
        }

    # Session management methods
    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent sessions."""
        if not self._session_manager:
            self._session_manager = SessionManager(storage_dir=".superqode/sessions")
        sessions = self._session_manager.list_all_sessions()
        return [
            {
                "session_id": s.session_id,
                "display_id": s.session_id[:8],
                "provider": s.provider,
                "model": s.model,
                "message_count": s.message_count,
                "updated_at": s.updated_at,
            }
            for s in sessions[:limit]
        ]

    def resolve_session_id(self, session_id_or_prefix: str) -> Optional[str]:
        """Resolve a full session id from an exact id or unique prefix."""
        if not self._session_manager:
            self._session_manager = SessionManager(storage_dir=".superqode/sessions")

        sessions = self._session_manager.list_all_sessions()
        exact = [s.session_id for s in sessions if s.session_id == session_id_or_prefix]
        if exact:
            return exact[0]

        matches = [s.session_id for s in sessions if s.session_id.startswith(session_id_or_prefix)]
        return matches[0] if len(matches) == 1 else None

    def resume_session(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        """Resume a session by ID."""
        if not self._session_manager:
            self._session_manager = SessionManager(storage_dir=".superqode/sessions")

        resolved_session_id = self.resolve_session_id(session_id)
        if not resolved_session_id:
            return None

        metadata = self._session_manager.get_session_info(resolved_session_id)
        if not metadata:
            return None

        # Start session and get messages
        self._session_manager.start_session(session_id=resolved_session_id)
        messages = self._session_manager.get_messages()

        # Reconnect with same settings
        self.connect(
            provider=metadata.provider,
            model=metadata.model,
            system_level=self.session.system_level,
            working_directory=self.session.working_directory,
            session_id=resolved_session_id,
        )

        # Return messages for display
        return [
            {
                "role": m.role,
                "content": m.content,
                "tool_name": getattr(m, "tool_name", None),
            }
            for m in messages
        ]

    def get_current_session_id(self) -> Optional[str]:
        """Get current session ID."""
        if self._agent:
            return self._agent.session_id
        return None

    def fork_current_session(self, new_session_id: Optional[str] = None) -> str:
        """Fork the current session into a new session branch."""
        if not self._session_manager:
            self._session_manager = SessionManager(storage_dir=".superqode/sessions")
        fork_id = self._session_manager.fork_current_session(new_session_id)
        if self._agent:
            self._agent.session_id = fork_id
            self._agent.config.session_id = fork_id
        return fork_id

    def compact(self) -> Dict[str, Any]:
        """Enable context compaction for the active agent and report current state."""
        if not self._agent:
            return {"success": False, "message": "No active provider session to compact."}

        self._agent.config.enable_summarization = True
        messages = (
            self._agent._session_manager.get_messages() if self._agent._session_manager else []
        )
        return {
            "success": True,
            "message": "Context compaction is enabled for subsequent turns.",
            "session_id": self._agent.session_id,
            "message_count": len(messages),
            "max_context_tokens": self._agent.config.max_context_tokens,
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
