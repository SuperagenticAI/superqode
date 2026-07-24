"""
Pure Mode - Minimal Harness for Fair Model Testing.

Integrates with both TUI and CLI for testing model coding capabilities
without the bias of heavy harnesses.
"""

import asyncio
import inspect
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .agent.loop import AgentLoop, AgentConfig, AgentResponse
from .agent.loop_policy import NativeLoopPolicy, core_loop_policy, workbench_loop_policy
from .agent.system_prompts import SystemPromptLevel
from .agent.session_manager import SessionManager, SessionMetadata
from .tools.base import ToolRegistry, ToolResult
from .providers.gateway.litellm_gateway import LiteLLMGateway
from .providers.model_specs import (
    normalize_model_for_provider,
    normalize_provider_id,
    split_provider_model_ref,
)
from .providers.registry import PROVIDERS, ProviderTier, ProviderCategory
from .runtime import AgentRuntime, create_runtime, resolve_runtime_name


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
        self.tool_profile = self._tool_profile_env or "core"
        self.tools = ToolRegistry.for_profile(self.tool_profile)
        self._loop_policy: NativeLoopPolicy = core_loop_policy()
        self.runtime_name = resolve_runtime_name(cli=runtime)
        self._runtime: Optional[AgentRuntime] = None
        self._runtime_close_tasks: set[asyncio.Task] = set()
        self._agent: Optional[AgentLoop] = None
        self._session_manager: Optional[SessionManager] = None
        self._harness_spec = None
        self._harness_definition = None
        self._harness_path = ""
        self._harness_kernel = None
        self._harness_session = None
        self._harness_session_id = ""
        # Extensions are discovered once per PureMode instance. Project-local
        # executable manifests are trust-gated by load_extension_runtime;
        # installed Python entry points are explicit user installations.
        from .extensions import load_extension_runtime

        self._extension_runtime = load_extension_runtime(Path.cwd())
        self._load_env_harness()

        # Callbacks for UI updates
        self.on_tool_call: Optional[Callable[[str, Dict], None]] = None
        self.on_tool_result: Optional[Callable[[str, ToolResult], None]] = None
        self.on_thinking: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_stream_chunk: Optional[Callable[[str], None]] = None
        self.on_permission_request: Optional[Callable[[str, dict[str, Any]], bool]] = None
        self._runtime_tool_delta_buffers: dict[str, dict[str, Any]] = {}
        self._runtime_seen_tool_calls: set = set()
        self._last_stats: dict[str, int | float] = {}

    def _load_env_harness(self) -> None:
        reference = os.getenv("SUPERQODE_HARNESS", "").strip() or "core"
        try:
            self.select_harness(reference)
        except (FileNotFoundError, ValueError):
            # Startup remains usable when a stale harness setting is present.
            self.select_harness("core")

    def select_harness(self, reference: str | Path):
        """Select a built-in harness name or HarnessSpec path."""
        from superqode.harness import resolve_harness

        definition = resolve_harness(reference, root=Path.cwd())
        self._harness_definition = definition
        self._loop_policy = definition.loop_policy
        self._harness_spec = definition.spec if definition.source != "built-in" else None
        self._harness_path = str(definition.path or "")
        profile = str(definition.spec.model_policy.config.get("tool_profile") or "").strip()
        if not profile:
            profile = "none" if definition.id == "no-tool" else "coding"
        self.tool_profile = self._tool_profile_env or profile
        self.tools = ToolRegistry.for_profile(self.tool_profile)
        if definition.source == "built-in" and definition.id != "no-tool":
            self._extension_runtime.apply_tools(self.tools)
        self._harness_kernel = None
        self._harness_session = None
        self._harness_session_id = ""
        self._dispose_runtime()
        self._sync_harness_session_fields()
        return definition

    def load_harness(self, path: str | Path):
        """Load a HarnessSpec for subsequent provider connections."""
        return self.select_harness(path).spec

    def set_harness(self, spec, *, path: str | Path | None = None) -> None:
        """Set an already loaded HarnessSpec."""
        from superqode.harness.catalog import HarnessDefinition

        self._dispose_runtime()
        self._harness_spec = spec
        self._harness_path = str(path or "")
        self._harness_definition = HarnessDefinition(
            id=spec.name.strip().lower(),
            display_name=spec.name,
            description=spec.description,
            runtime=spec.runtime.backend,
            source="file",
            spec=spec,
            loop_policy=workbench_loop_policy(),
            path=Path(path).expanduser().resolve() if path else None,
        )
        self._loop_policy = workbench_loop_policy()
        self._harness_kernel = None
        self._harness_session = None
        self._harness_session_id = ""
        self._sync_harness_session_fields()

    def clear_harness(self) -> None:
        """Return to the built-in core harness."""
        self.select_harness("core")

    def reload_extensions(self):
        """Reload enabled extensions and rebuild the active native runtime.

        Plugin state changes are expected to take effect immediately in the
        TUI. Preserve the current provider/model/session while reconstructing
        the tool registry, hooks and bounded extension context.
        """
        from .extensions import load_extension_runtime

        definition = self._harness_definition
        reference: str | Path = "core"
        if definition is not None:
            reference = definition.path or definition.id
        was_connected = self.session.connected
        provider = self.session.provider
        model = self.session.model
        system_level = self.session.system_level
        working_directory = self.session.working_directory
        session_id = self.get_current_session_id()

        self._extension_runtime = load_extension_runtime(working_directory or Path.cwd())
        self.select_harness(reference)
        if (
            was_connected
            and provider
            and model
            and definition is not None
            and definition.source == "built-in"
        ):
            self.connect(
                provider,
                model,
                system_level,
                working_directory=working_directory,
                session_id=session_id,
            )
        return self._extension_runtime

    def _sync_harness_session_fields(self) -> None:
        """Mirror the loaded HarnessSpec into user-visible session status."""
        definition = self._harness_definition
        if definition is None:
            self.session.harness_name = ""
            self.session.harness_path = ""
            self.session.harness_flavor = ""
            self.session.harness_runtime = ""
            return
        self.session.harness_name = definition.id
        self.session.harness_path = self._harness_path
        self.session.harness_flavor = definition.spec.flavor.value
        self.session.harness_runtime = definition.runtime

    @property
    def harness_enabled(self) -> bool:
        return self._harness_definition is not None

    def _resolve_harness_route(self) -> tuple[str, str]:
        """Return the provider/model the active harness should run against."""
        provider = self.session.provider
        model = self.session.model
        if self._harness_spec is None:
            return provider, model

        primary = str(getattr(self._harness_spec.model_policy, "primary", "") or "").strip()
        configured_provider = str(
            getattr(self._harness_spec.model_policy, "config", {}).get("provider") or ""
        ).strip()
        if primary:
            parsed = split_provider_model_ref(primary, default_provider=configured_provider)
            provider = normalize_provider_id(parsed.provider or configured_provider or provider)
            model = normalize_model_for_provider(provider, parsed.model or primary)

        self._validate_harness_route(provider, model)
        return provider, model

    @staticmethod
    def _validate_harness_route(provider: str, model: str) -> None:
        """Catch common local provider/model mismatches before streaming."""
        return

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
        provider = normalize_provider_id(provider)
        model = normalize_model_for_provider(provider, model)
        selected_id = getattr(self._harness_definition, "id", "core")
        if selected_id == "core":
            system_level = SystemPromptLevel.CORE
        elif selected_id == "no-tool":
            system_level = SystemPromptLevel.NO_TOOL
        self.session.provider = provider
        self.session.model = model
        self.session.system_level = system_level
        self.session.working_directory = working_directory or Path.cwd()
        self.session.connected = True
        if session_id:
            if self._session_manager is None:
                self._session_manager = SessionManager(storage_dir=".superqode/sessions")
            self._session_manager.start_session(
                session_id=session_id,
                provider=provider,
                model=model,
                harness_id=selected_id,
                harness_source=getattr(self._harness_definition, "source", "built-in"),
                harness_digest=getattr(self._harness_definition, "digest", ""),
                tool_contract_version=(
                    "core-tools-v1" if selected_id == "core" else "workbench-v1"
                ),
                continuity=getattr(
                    self._harness_definition,
                    "continuity",
                    "context-replay",
                ),
            )
        if self._harness_spec is not None:
            # HarnessSpec sessions use the same durable session id as the
            # underlying runtime. Carry an explicit resume id into the harness
            # kernel so switching away and back restores the original history.
            if session_id:
                self._harness_session_id = session_id
            self.session.harness_name = self._harness_spec.name
            self.session.harness_path = self._harness_path
            self.session.harness_flavor = self._harness_spec.flavor.value
            self.session.harness_runtime = self._harness_spec.runtime.backend
            if self._harness_spec.is_no_tool:
                self.tool_profile = "none"
                self.tools = ToolRegistry.empty()
            self._dispose_runtime()
            return True

        provider_def = PROVIDERS.get(provider)
        is_ds4 = provider == "ds4"
        if is_ds4 and not self._tool_profile_env and selected_id == "workbench":
            self.tool_profile = "ds4"
            self.tools = ToolRegistry.for_profile(self.tool_profile)
        elif self._tool_profile_env and self.tool_profile != self._tool_profile_env:
            self.tool_profile = self._tool_profile_env
            self.tools = ToolRegistry.for_profile(self.tool_profile)

        if is_ds4:
            # 0 (default) => unlimited iterations (loop until the model stops).
            max_iterations = int(os.getenv("DS4_MAX_ITERATIONS", "0"))
            session_history_limit = int(os.getenv("DS4_SESSION_HISTORY_LIMIT", "8"))
            parallel_tools = False

            # DS4 KV cache configuration
            kv_disk_dir = os.getenv("DS4_KV_DISK_DIR", "/tmp/ds4-kv")
            kv_disk_space = int(os.getenv("DS4_KV_DISK_SPACE_MB", "8192"))
            os.environ["DS4_KV_DISK_DIR"] = kv_disk_dir
            os.environ["DS4_KV_DISK_SPACE_MB"] = str(kv_disk_space)
        else:
            # 0 means unlimited iterations. Users can still cap via env.
            max_iterations = int(os.getenv("SUPERQODE_MAX_ITERATIONS", "0"))
            session_history_limit = int(os.getenv("SUPERQODE_SESSION_HISTORY_LIMIT", "20"))
            parallel_tools = True

        # Create agent loop with job description if provided
        from .extensions import ExtensionContext

        extension_context = ExtensionContext(
            root=self.session.working_directory,
            harness_id=selected_id,
            provider=provider,
            model=model,
            session_id=session_id or "",
        )
        extension_prompt = self._extension_runtime.context_text(extension_context)
        config = AgentConfig(
            provider=provider,
            model=model,
            system_prompt_level=system_level,
            working_directory=self.session.working_directory,
            custom_system_prompt=extension_prompt or None,
            job_description=job_description,
            max_iterations=max_iterations,
            enable_session_storage=True,
            session_storage_dir=".superqode/sessions",
            session_id=session_id,
            session_history_limit=session_history_limit,
            loop_policy=self._loop_policy,
            harness_id=selected_id,
            harness_source=getattr(self._harness_definition, "source", "built-in"),
            harness_digest=getattr(self._harness_definition, "digest", ""),
            tool_contract_version=("core-tools-v1" if selected_id == "core" else "workbench-v1"),
        )

        runtime_kwargs: dict[str, Any] = {}
        if self.runtime_name in (
            "codex-sdk",
            "copilot-sdk",
            "claude-agent-sdk",
            "antigravity-sdk",
        ):
            runtime_kwargs["approval_callback"] = self.on_permission_request
        if self.runtime_name == "builtin":
            runtime_kwargs["hooks"] = self._extension_runtime.build_hooks()

        self._dispose_runtime()
        self._runtime = create_runtime(
            self.runtime_name,
            gateway=self.gateway,
            tools=self.tools,
            config=config,
            on_tool_call=self.on_tool_call,
            on_tool_result=self.on_tool_result,
            on_thinking=self.on_thinking,
            parallel_tools=parallel_tools,
            include_mcp=_env_flag("SUPERQODE_MCP_SEARCH") and self._loop_policy.mcp,
            **runtime_kwargs,
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
        self.cancel()
        self._dispose_runtime()
        self.session = PureSession()
        self._harness_kernel = None
        self._harness_session = None
        self._harness_session_id = ""
        self._sync_harness_session_fields()

    def _dispose_runtime(self) -> None:
        """Close and detach the current runtime without blocking a running UI loop."""
        runtime, self._runtime = self._runtime, None
        self._agent = None
        if runtime is None:
            return
        closer = getattr(runtime, "aclose", None) or getattr(runtime, "close", None)
        if closer is None:
            return
        try:
            result = closer()
        except Exception:  # noqa: BLE001 - cleanup must not make switching unusable
            return
        if not inspect.isawaitable(result):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(result)
            return
        task = loop.create_task(result)
        self._runtime_close_tasks.add(task)
        task.add_done_callback(self._runtime_close_tasks.discard)

    async def aclose(self) -> None:
        """Close the active runtime and await any cleanup scheduled by switching."""
        self.cancel()
        runtime, self._runtime = self._runtime, None
        self._agent = None
        if runtime is not None:
            closer = getattr(runtime, "aclose", None) or getattr(runtime, "close", None)
            if closer is not None:
                result = closer()
                if inspect.isawaitable(result):
                    await result
        pending = list(self._runtime_close_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def set_system_level(self, level: SystemPromptLevel):
        """Change the system prompt level."""
        self.session.system_level = level
        if self._agent:
            self._agent.config.system_prompt_level = level
            self._agent.system_prompt = self._agent._build_system_prompt()

    async def run(self, prompt: str, plan_mode: Optional[bool] = None) -> AgentResponse:
        """Run a task in Pure Mode."""
        if self._harness_spec is not None:
            provider, model = self._resolve_harness_route()
            session = await self._ensure_harness_session()
            result = await session.prompt(
                prompt,
                provider=provider,
                model=model,
                working_directory=self.session.working_directory,
                runtime=self._harness_spec.runtime.backend,
            )
            self.session.total_tool_calls += result.tool_calls_made
            self.session.total_iterations += result.iterations
            self.session.total_requests += 1
            return result.response

        if not self._agent:
            # Self-contained runtimes (e.g. codex-sdk) run via the runtime
            # directly — there's no builtin AgentLoop.
            if self._runtime is not None:
                response = await self._runtime.run(prompt)
                self.session.total_tool_calls += response.tool_calls_made
                self.session.total_iterations += response.iterations
                self.session.total_requests += 1
                return response
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

    def steer(self, message: str) -> bool:
        """Inject a message into the live builtin run (between tool calls).

        Returns True when delivered into an active run; False when there is
        no builtin loop or it is idle - the caller should queue or submit
        the message normally instead.
        """
        agent = self._agent
        if agent is None or not getattr(agent, "run_active", False):
            return False
        return bool(agent.steer(message))

    async def run_streaming(self, prompt: str, plan_mode: Optional[bool] = None):
        """Run a task with streaming output."""
        # Never let a provider/runtime without usage metadata display figures
        # left over from the previous turn.
        self._last_stats = {}
        if self._harness_spec is not None:
            provider, model = self._resolve_harness_route()
            session = await self._ensure_harness_session()
            async for event in session.stream(
                prompt,
                provider=provider,
                model=model,
                working_directory=self.session.working_directory,
                runtime=self._harness_spec.runtime.backend,
            ):
                if event.type not in {"delta", "model_delta"}:
                    continue
                chunk = str(event.data.get("text", ""))
                if self.on_stream_chunk:
                    self.on_stream_chunk(chunk)
                yield chunk
            self.session.total_requests += 1
            return

        if not self._agent:
            # Self-contained runtimes (e.g. codex-sdk) have no builtin AgentLoop
            # (no ``.loop``); stream straight through the runtime instead.
            if self._runtime is not None:
                if hasattr(self._runtime, "run_harness_events"):
                    self._runtime_seen_tool_calls = set()
                    try:
                        async for event in self._runtime.run_harness_events(prompt):
                            chunk = self._handle_runtime_harness_event(event)
                            if chunk:
                                if self.on_stream_chunk:
                                    self.on_stream_chunk(chunk)
                                yield chunk
                    finally:
                        self._flush_runtime_tool_delta_buffers(force=True)
                else:
                    async for chunk in self._runtime.run_streaming(prompt):
                        if self.on_stream_chunk:
                            self.on_stream_chunk(chunk)
                        yield chunk
                self.session.total_requests += 1
                return
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

        self._last_stats = dict(getattr(self._agent, "last_stream_stats", {}) or {})

        self.session.total_requests += 1

    def _handle_runtime_harness_event(self, event) -> str:
        """Forward runtime harness events into PureMode callbacks."""
        if event.type == "model_delta":
            return str(event.data.get("text") or "")
        if event.type == "thinking":
            text = str(event.data.get("text") or "")
            if text and self.on_thinking:
                result = self.on_thinking(text)
                if inspect.isawaitable(result):
                    asyncio.create_task(result)
            return ""
        if event.type == "tool_call":
            # Some runtimes (Claude) emit an explicit tool_call before the result.
            name = str(event.data.get("tool_name") or "tool")
            tool_id = event.data.get("tool_call_id")
            seen = getattr(self, "_runtime_seen_tool_calls", None)
            if seen is not None and tool_id is not None:
                seen.add(tool_id)
            if self.on_tool_call:
                args = dict(event.data.get("args") or {}) or self._tool_args_from_runtime_event(
                    event
                )
                self.on_tool_call(name, args)
            return ""
        if event.type == "tool_delta":
            name = str(event.data.get("tool_name") or "tool")
            text = str(event.data.get("text") or "")
            if text:
                self._buffer_runtime_tool_delta(name, text)
            return ""
        if event.type == "diff":
            if self.on_tool_result:
                changes = event.data.get("changes", [])
                self.on_tool_result(
                    str(event.data.get("tool_name") or "patch"),
                    ToolResult(success=True, output="patch updated", metadata={"changes": changes}),
                )
            return ""
        if event.type == "plan_update":
            todos = event.data.get("todos")
            if isinstance(todos, list):
                args = {"todos": todos}
                if self.on_tool_call:
                    self.on_tool_call("todo_write", args)
                if self.on_tool_result:
                    import json

                    self.on_tool_result(
                        "todo_write",
                        ToolResult(
                            success=True,
                            output=json.dumps(todos),
                            metadata={
                                "todos": todos,
                                "explanation": str(event.data.get("explanation") or ""),
                                "source_event": str(event.data.get("source_event") or ""),
                            },
                        ),
                    )
            return ""
        if event.type == "tool_result":
            name = str(event.data.get("tool_name") or "tool")
            tool_id = event.data.get("tool_call_id")
            seen = getattr(self, "_runtime_seen_tool_calls", None)
            already = seen is not None and tool_id is not None and tool_id in seen
            # Only synthesize a tool_call card if the runtime didn't already emit
            # one for this id (Codex emits only tool_result; Claude emits both).
            if self.on_tool_call and not already:
                self.on_tool_call(name, self._tool_args_from_runtime_event(event))
            if self.on_tool_result:
                self.on_tool_result(
                    name,
                    ToolResult(
                        success=bool(event.data.get("success", True)),
                        output=str(event.data.get("output") or ""),
                        error=(
                            str(event.data.get("error"))
                            if event.data.get("error") is not None
                            else None
                        ),
                        metadata={
                            key: value
                            for key, value in event.data.items()
                            if key not in {"tool_name", "success", "output", "error"}
                        },
                    ),
                )
            return ""
        if event.type == "turn_complete":
            usage = event.data.get("usage")
            if isinstance(usage, dict):
                prompt_tokens = int(
                    usage.get("total_input_tokens")
                    or usage.get("input_tokens")
                    or usage.get("prompt_tokens")
                    or 0
                )
                completion_tokens = int(
                    usage.get("total_output_tokens")
                    or usage.get("output_tokens")
                    or usage.get("completion_tokens")
                    or 0
                )
                thinking_tokens = int(
                    usage.get("total_thought_tokens")
                    or usage.get("thought_tokens")
                    or usage.get("thinking_tokens")
                    or 0
                )
                total_tokens = int(
                    usage.get("total_tokens") or prompt_tokens + completion_tokens + thinking_tokens
                )
                self._last_stats = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "thinking_tokens": thinking_tokens,
                    "total_tokens": total_tokens,
                }
            return ""
        return ""

    def _buffer_runtime_tool_delta(self, name: str, text: str) -> None:
        if not self.on_tool_result:
            return
        now = time.monotonic()
        buffer = self._runtime_tool_delta_buffers.setdefault(
            name,
            {"text": "", "last_flush": now},
        )
        buffer["text"] += text
        buffered = str(buffer["text"])
        if "\n" in text or len(buffered) >= 512 or now - float(buffer["last_flush"]) >= 0.1:
            # "partial" marks streamed output chunks, not completions — the
            # TUI's calm mode must not commit a finished-tool line per chunk.
            self.on_tool_result(
                name, ToolResult(success=True, output=buffered, metadata={"partial": True})
            )
            buffer["text"] = ""
            buffer["last_flush"] = now

    def _flush_runtime_tool_delta_buffers(self, *, force: bool = False) -> None:
        if not self.on_tool_result:
            self._runtime_tool_delta_buffers.clear()
            return
        now = time.monotonic()
        for name, buffer in list(self._runtime_tool_delta_buffers.items()):
            text = str(buffer.get("text") or "")
            if not text:
                continue
            if force or now - float(buffer.get("last_flush") or now) >= 0.1:
                self.on_tool_result(
                    name, ToolResult(success=True, output=text, metadata={"partial": True})
                )
                buffer["text"] = ""
                buffer["last_flush"] = now

    @staticmethod
    def _tool_args_from_runtime_event(event) -> dict[str, Any]:
        data = dict(event.data)
        arguments = data.get("arguments")
        if isinstance(arguments, dict) and arguments:
            return dict(arguments)
        name = str(data.get("tool_name") or "")
        if name == "bash":
            return {"command": data.get("command") or ""}
        if name == "patch":
            return {"path": data.get("path") or ""}
        return {}

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
        elif self._runtime is not None:
            self._runtime.cancel()

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
                **self._last_stats,
            },
            "tools": [t.name for t in self.tools.list()],
            "tool_profile": self.tool_profile,
            "harness": {
                "enabled": self._harness_definition is not None,
                "id": getattr(self._harness_definition, "id", ""),
                "source": getattr(self._harness_definition, "source", ""),
                "digest": (
                    self._harness_definition.digest if self._harness_definition is not None else ""
                ),
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
                "harness_id": s.harness_id or "workbench",
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

        # Sessions created before harness metadata existed used the historical
        # native behavior, now called workbench. Preserve that behavior instead
        # of silently resuming old conversations under the lean core contract.
        resume_harness = metadata.harness_id or "workbench"
        try:
            self.select_harness(resume_harness)
        except (FileNotFoundError, ValueError):
            self.select_harness("workbench")

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
        if self._harness_session_id:
            return self._harness_session_id
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
