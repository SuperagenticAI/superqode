"""
ACP Client for SuperQode.

Handles communication with ACP-compatible coding agents like OpenCode.
This is the primary interface for all ACP agent communication.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Callable, Awaitable, Optional, Dict, List, Protocol
from dataclasses import dataclass, field
from time import monotonic

from superqode.acp.permission_store import (
    ACPPermissionStore,
    PermissionDecision,
)
from superqode.acp.session_store import ACPSessionStore, StoredSession
from superqode.acp.types import (
    PermissionOption,
    ToolCall,
    ToolCallUpdate,
    ContentBlock,
    InitializeResponse,
    NewSessionResponse,
    SessionPromptResponse,
    CreateTerminalResponse,
    TerminalOutputResponse,
    WaitForTerminalExitResponse,
    AvailableMode,
    AvailableModel,
    ModesResponse,
    ModelsResponse,
    SlashCommand,
    AvailableCommandsResponse,
)


PROTOCOL_VERSION = 1
CLIENT_NAME = "SuperQode"
CLIENT_VERSION = "0.1.20"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_log_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value)
    return safe.strip("._") or "agent"


def default_acp_traffic_log_dir() -> Path:
    """Resolve the default ACP traffic log directory."""
    home = os.environ.get("SUPERQODE_HOME")
    if home:
        return Path(home).expanduser() / "acp-logs"
    return Path.home() / ".superqode" / "acp-logs"


@dataclass
class ACPMessage:
    """A message received from the agent."""

    type: str
    data: dict[str, Any]


@dataclass
class ACPStats:
    """Statistics from an ACP session."""

    tool_count: int = 0
    files_modified: List[str] = field(default_factory=list)
    files_read: List[str] = field(default_factory=list)
    duration: float = 0.0
    stop_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thinking_tokens: int = 0
    cost: float = 0.0


class ACPTerminalService(Protocol):
    """Host-owned terminal service for ACP terminal/* requests.

    The fallback implementation inside ``ACPClient`` keeps existing
    behavior working for headless callers. TUI callers can provide this
    service to own terminal rendering, lifecycle, and future PTY handling.
    """

    async def create(self, params: dict) -> CreateTerminalResponse: ...

    async def output(self, params: dict) -> TerminalOutputResponse: ...

    async def kill(self, params: dict) -> dict: ...

    async def release(self, params: dict) -> dict: ...

    async def wait_for_exit(self, params: dict) -> WaitForTerminalExitResponse: ...


@dataclass
class ACPClient:
    """
    ACP (Agent Client Protocol) client for communicating with coding agents.

    This client manages the subprocess communication with an ACP-compatible agent
    and handles the JSON-RPC protocol.
    """

    project_root: Path
    command: str  # e.g., "opencode acp"
    model: Optional[str] = None
    startup_timeout: float = 30.0
    prompt_timeout: float = 180.0
    request_timeout: float = 30.0

    # Callbacks for handling agent events
    on_message: Optional[Callable[[str], Awaitable[None]]] = None
    on_thinking: Optional[Callable[[str], Awaitable[None]]] = None
    on_tool_call: Optional[Callable[[ToolCall], Awaitable[None]]] = None
    on_tool_update: Optional[Callable[[ToolCallUpdate], Awaitable[None]]] = None
    on_permission_request: Optional[
        Callable[[List[PermissionOption], ToolCall], Awaitable[str]]
    ] = None
    on_plan: Optional[Callable[[List[dict]], Awaitable[None]]] = None
    on_user_message: Optional[Callable[[str], Awaitable[None]]] = None
    on_available_commands: Optional[Callable[[List[dict]], Awaitable[None]]] = None
    on_mode_update: Optional[Callable[[str], Awaitable[None]]] = None
    on_usage_update: Optional[Callable[[dict], Awaitable[None]]] = None
    terminal_service: Optional[ACPTerminalService] = None
    traffic_log_path: Optional[Path] = None
    traffic_log_enabled: Optional[bool] = None

    # Persistent permission store. When set, ``_handle_permission_request``
    # consults the store before invoking the user callback. If the user
    # picks an ``always`` decision, we save it. Optional — leaving these
    # unset preserves the previous always-ask behavior verbatim.
    permission_store: Optional["ACPPermissionStore"] = None
    permission_scope: Optional[str] = None

    # Persistent session store. When configured, newly-created sessions
    # are recorded on disk and the client can resume prior sessions via
    # ``load_session()`` if the agent advertises ``loadSession`` capability.
    # ``agent_identity`` scopes the index so listings stay per-agent.
    session_store: Optional["ACPSessionStore"] = None
    agent_identity: Optional[str] = None
    # If set, the client tries to resume this session id (gated on the
    # agent's ``loadSession`` capability) instead of creating a fresh one
    # on startup. Falls back to ``session/new`` if resume fails.
    resume_session_id: Optional[str] = None

    # Internal state
    _process: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    _request_id: int = field(default=0, repr=False)
    _pending_requests: Dict[int, asyncio.Future] = field(default_factory=dict, repr=False)
    _inbound_tasks: set[asyncio.Task] = field(default_factory=set, repr=False)
    _session_id: str = field(default="", repr=False)
    _tool_calls: Dict[str, ToolCall] = field(default_factory=dict, repr=False)
    _read_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _terminal_count: int = field(default=0, repr=False)
    _terminals: Dict[str, dict] = field(default_factory=dict, repr=False)

    # Tracking stats
    _files_modified: List[str] = field(default_factory=list, repr=False)
    _files_read: List[str] = field(default_factory=list, repr=False)
    _tool_actions: List[dict] = field(default_factory=list, repr=False)
    _start_time: float = field(default=0.0, repr=False)
    _message_buffer: str = field(default="", repr=False)
    _current_mode_id: Optional[str] = field(default=None, repr=False)
    _available_modes: List[dict] = field(default_factory=list, repr=False)
    _current_model_id: Optional[str] = field(default=None, repr=False)
    _available_models: List[dict] = field(default_factory=list, repr=False)
    _config_options: List[dict] = field(default_factory=list, repr=False)
    _available_commands: List[dict] = field(default_factory=list, repr=False)
    _usage: Dict[str, Any] = field(default_factory=dict, repr=False)
    _traffic_log_resolved_path: Optional[Path] = field(default=None, repr=False)

    # Agent-advertised capabilities from the initialize response.
    # ``loadSession`` is the one we care about for resume; if the agent
    # didn't advertise it, ``load_session()`` raises rather than failing
    # silently on the wire. Default ``{}`` so attribute access via
    # ``.get()`` always works even before initialize completes.
    _agent_capabilities: Dict[str, Any] = field(default_factory=dict, repr=False)

    def reset_stats(self) -> None:
        """Reset tracking stats for a new prompt."""
        self._files_modified = []
        self._files_read = []
        self._tool_actions = []
        self._start_time = monotonic()
        self._message_buffer = ""
        self._usage = {}

    def get_stats(self) -> ACPStats:
        """Get current session stats."""
        return ACPStats(
            tool_count=len(self._tool_actions),
            files_modified=self._files_modified.copy(),
            files_read=self._files_read.copy(),
            duration=monotonic() - self._start_time if self._start_time else 0.0,
            prompt_tokens=int(
                self._usage.get("input_tokens") or self._usage.get("prompt_tokens") or 0
            ),
            completion_tokens=int(
                self._usage.get("output_tokens") or self._usage.get("completion_tokens") or 0
            ),
            thinking_tokens=int(self._usage.get("thought_tokens") or 0),
            cost=self._usage_cost_amount(self._usage),
        )

    def get_message_buffer(self) -> str:
        """Get accumulated message text."""
        return self._message_buffer

    def is_running(self) -> bool:
        """Return True when the ACP subprocess and session are usable."""
        return (
            self._process is not None
            and self._process.returncode is None
            and bool(self._session_id)
            and self._read_task is not None
            and not self._read_task.done()
        )

    def get_traffic_log_path(self) -> Optional[Path]:
        """Return the active ACP traffic log path, if logging is enabled."""
        return self._traffic_log_resolved_path

    async def start(self) -> bool:
        """Start the ACP agent subprocess."""
        try:
            await self._initialize_traffic_log()

            # Use command as-is - model selection is handled via ACP protocol
            # Don't add -m flag as not all agents support it (e.g., opencode acp)
            cmd = self.command

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            # OpenCode's verbose logs are useful for debugging, but expensive on
            # normal runs because every non-JSON line has to be parsed and routed
            # through the TUI.
            if "opencode" in cmd and os.environ.get("SUPERQODE_ACP_PRINT_LOGS"):
                cmd = f"{cmd} --print-logs"

            self._process = await asyncio.create_subprocess_shell(
                cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
                cwd=str(self.project_root),
                env=env,
                limit=10 * 1024 * 1024,  # 10MB buffer
            )

            # Start reading output
            self._read_task = asyncio.create_task(self._read_loop())

            # Initialize the protocol
            await self._initialize()

            # Resume the requested session if possible, else create new.
            # We only try resume when the caller asked for it AND the
            # agent advertised loadSession capability — otherwise we'd
            # send a method the agent doesn't implement and get an error.
            resumed = False
            if self.resume_session_id and self._agent_capabilities.get("loadSession"):
                try:
                    await self._load_session(self.resume_session_id)
                    resumed = True
                except Exception as e:
                    if self.on_thinking:
                        await self.on_thinking(f"[resume failed, falling back to new session] {e}")

            if not resumed:
                await self._new_session()

            return True

        except Exception as e:
            if self.on_thinking:
                await self.on_thinking(f"[startup error] {e}")
            return False

    async def stop(self) -> None:
        """Stop the ACP agent subprocess."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._process:
            if self._process.returncode is None:
                try:
                    self._process.terminate()
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
            self._process = None

    async def _initialize_traffic_log(self) -> None:
        """Create the ACP traffic log file when logging is enabled.

        Logging is opt-in because raw ACP traffic may include prompts, file
        contents, diffs, terminal output, or other sensitive project data.
        Enable with ``traffic_log_path`` or ``SUPERQODE_ACP_TRAFFIC_LOG=1``.
        """
        enabled = (
            self.traffic_log_enabled
            if self.traffic_log_enabled is not None
            else _env_flag("SUPERQODE_ACP_TRAFFIC_LOG", default=False)
        )
        explicit_path = self.traffic_log_path or (
            Path(os.environ["SUPERQODE_ACP_TRAFFIC_LOG_PATH"]).expanduser()
            if os.environ.get("SUPERQODE_ACP_TRAFFIC_LOG_PATH")
            else None
        )
        if explicit_path is None and not enabled:
            self._traffic_log_resolved_path = None
            return

        if explicit_path is not None:
            log_path = explicit_path
        else:
            agent_name = self.agent_identity or self.command.split()[0] or "agent"
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            log_path = (
                default_acp_traffic_log_dir() / f"{_safe_log_name(agent_name)}-{timestamp}.jsonl"
            )

        self._traffic_log_resolved_path = log_path
        await asyncio.to_thread(log_path.parent.mkdir, parents=True, exist_ok=True)
        header = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "direction": "meta",
            "event": "start",
            "command": self.command,
            "cwd": str(self.project_root),
            "agent_identity": self.agent_identity,
            "model": self.model,
        }
        await self._write_traffic_log(header)

    async def _write_traffic_log(self, record: dict[str, Any]) -> None:
        log_path = self._traffic_log_resolved_path
        if log_path is None:
            return

        def append() -> None:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                f.write("\n")

        try:
            await asyncio.to_thread(append)
        except OSError:
            # Traffic logging is diagnostic only and must never break ACP.
            pass

    async def _log_traffic(self, direction: str, payload: Any) -> None:
        if self._traffic_log_resolved_path is None:
            return
        await self._write_traffic_log(
            {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "direction": direction,
                "payload": payload,
            }
        )

    async def send_prompt(self, prompt: str) -> Optional[str]:
        """
        Send a prompt to the agent and wait for completion.

        Returns the stop reason.
        """
        # Reset stats for this prompt
        self.reset_stats()

        content_blocks: List[ContentBlock] = [{"type": "text", "text": prompt}]

        response = await self._call_method(
            "session/prompt",
            timeout=self.prompt_timeout,
            prompt=content_blocks,
            sessionId=self._session_id,
        )

        stop_reason = response.get("stopReason") if response else None
        if response:
            usage = response.get("usage")
            if isinstance(usage, dict):
                self._merge_usage(usage)
                if self.on_usage_update:
                    await self.on_usage_update(dict(self._usage))

        # Bump last_used_at so "list recent sessions" reflects real
        # activity, not just creation time. Best-effort; store warns
        # internally on failure.
        if self.session_store is not None and self.agent_identity and self._session_id:
            await self.session_store.touch(self.agent_identity, self._session_id)

        return stop_reason

    async def cancel(self) -> bool:
        """Cancel the current operation."""
        try:
            await self._send_notification(
                "session/cancel",
                sessionId=self._session_id,
                _meta={},
            )
            return True
        except Exception:
            return False

    async def switch_model(self, new_model: str) -> bool:
        """
        Switch to a new model, creating a new session.

        When the user changes the model, we need to:
        1. Stop the current session cleanly
        2. Update the model configuration
        3. Start fresh with a new session

        Args:
            new_model: The new model identifier to switch to.

        Returns:
            True if switch was successful, False otherwise.
        """
        try:
            # Cancel any pending operations
            await self.cancel()

            # Stop the current agent process
            await self.stop()

            # Update model
            self.model = new_model

            # Reset internal state
            self._session_id = ""
            self._tool_calls.clear()
            self._terminals.clear()
            self._terminal_count = 0
            self.reset_stats()

            # Start fresh with new session
            return await self.start()

        except Exception as e:
            if self.on_thinking:
                await self.on_thinking(f"[model switch error] {e}")
            return False

    async def reset_session(self) -> bool:
        """
        Reset the current session without changing the model.

        Creates a new session with the same configuration.

        Returns:
            True if reset was successful, False otherwise.
        """
        try:
            # Cancel any pending operations
            await self.cancel()

            # Reset internal state
            self._tool_calls.clear()
            self._terminals.clear()
            self._terminal_count = 0
            self.reset_stats()

            # Create new session
            await self._new_session()

            return True

        except Exception as e:
            if self.on_thinking:
                await self.on_thinking(f"[session reset error] {e}")
            return False

    def get_current_model(self) -> Optional[str]:
        """Get the currently configured model."""
        return self.model

    def get_session_id(self) -> str:
        """Get the current session ID."""
        return self._session_id

    def supports_resume(self) -> bool:
        """Whether the connected agent advertised ``loadSession`` support.

        Only meaningful after ``start()`` has completed initialize.
        Useful for CLIs that want to grey out a resume menu rather than
        attempt and fail.
        """
        return bool(self._agent_capabilities.get("loadSession"))

    def get_agent_capabilities(self) -> Dict[str, Any]:
        """Return a copy of the agent capabilities reported at initialize."""
        return dict(self._agent_capabilities)

    def get_session_modes(self) -> dict[str, Any]:
        """Return the latest ACP session mode state reported by the agent."""
        return {
            "availableModes": list(self._available_modes),
            "currentModeId": self._current_mode_id,
        }

    def get_session_models(self) -> dict[str, Any]:
        """Return the latest ACP session model state reported by the agent."""
        return {
            "availableModels": list(self._available_models),
            "currentModelId": self._current_model_id,
        }

    def get_session_config_options(self) -> List[dict]:
        """Return the latest session config options reported by the agent."""
        return list(self._config_options)

    def get_available_commands_cached(self) -> List[dict]:
        """Return the latest slash commands pushed via ``available_commands_update``."""
        return list(self._available_commands)

    def get_usage(self) -> Dict[str, Any]:
        """Return the latest token / context usage payload."""
        return dict(self._usage)

    async def list_persisted_sessions(
        self, *, cwd_only: bool = True, limit: int = 50
    ) -> List["StoredSession"]:
        """List prior sessions for this client's agent identity.

        ``cwd_only=True`` (the default) scopes the listing to the
        current project root — typically what a user wants. Pass
        ``cwd_only=False`` for the global cross-project view.
        """
        if self.session_store is None or not self.agent_identity:
            return []
        cwd = str(self.project_root) if cwd_only else None
        return await self.session_store.list_for_agent(self.agent_identity, cwd=cwd, limit=limit)

    # ========================================================================
    # Internal Methods
    # ========================================================================

    async def _initialize(self) -> InitializeResponse:
        """Initialize the ACP protocol."""
        response = await self._call_method(
            "initialize",
            timeout=self.startup_timeout,
            protocolVersion=PROTOCOL_VERSION,
            clientCapabilities={
                "fs": {
                    "readTextFile": True,
                    "writeTextFile": True,
                },
                "terminal": True,
            },
            clientInfo={
                "name": CLIENT_NAME,
                "title": "SuperQode - Multi-Agent Coding Team",
                "version": CLIENT_VERSION,
            },
        )
        # Stash whatever the agent told us about itself. We only act on
        # ``loadSession`` today, but keeping the full dict means future
        # capability checks (e.g. ``promptCapabilities.embeddedContent``)
        # don't require a re-roundtrip.
        self._agent_capabilities = response.get("agentCapabilities") or {}
        return response

    async def _new_session(self) -> NewSessionResponse:
        """Create a new session and persist it if a store is configured."""
        from superqode.mcp.config import get_acp_mcp_servers

        params: Dict[str, Any] = {
            "cwd": str(self.project_root),
            "mcpServers": get_acp_mcp_servers(),
        }
        if self.model:
            params["model"] = self.model

        response = await self._call_method(
            "session/new",
            timeout=self.startup_timeout,
            **params,
        )
        self._session_id = response.get("sessionId", "")
        self._apply_session_state_from_response(response)
        await self._select_requested_model()
        await self._persist_current_session()
        return response

    async def _select_requested_model(self) -> None:
        """Switch the session to ``self.model`` via ``session/set_model``.

        Several agents (notably opencode) ignore the ``model`` field in
        ``session/new`` and always start on their default model — so without
        this every session ran the default (e.g. big-pickle) no matter which
        model the user picked. The ACP-canonical way to choose a model is
        ``session/set_model`` against an advertised ``availableModels`` id.

        No-ops when no model was requested, the agent advertised no models,
        or the session is already on the requested model. Best-effort: a
        failed switch leaves the session on its default rather than erroring.
        """
        if not self.model or not self._session_id:
            return

        # Newer OpenCode ACP exposes model selection as a generic
        # configOption rather than session/models. Prefer that path when
        # present; otherwise OpenCode starts on its default model (currently
        # big-pickle) even if session/new included a model field.
        model_option = self._model_config_option()
        if model_option is not None:
            available_ids = {item["id"] for item in self._models_from_config_option(model_option)}
            if self.model not in available_ids:
                if self.on_thinking:
                    await self.on_thinking(
                        f"[model switch skipped] ACP agent did not advertise requested model: {self.model}"
                    )
                return
            if self._current_model_id == self.model:
                return
            switched = await self.set_config_option(
                str(model_option.get("id") or "model"), self.model
            )
            if switched:
                self._current_model_id = self.model
            elif self.on_thinking:
                await self.on_thinking(f"[model switch failed] {self.model}")
            return

        available = self._available_models or []
        if not available:
            # Agent doesn't expose model selection — nothing to do.
            return
        available_ids = {self._model_id(m) for m in available if self._model_id(m)}
        # Only switch to a model the agent actually advertises; otherwise we'd
        # send a bogus id and (best case) get rejected.
        if self.model not in available_ids:
            if self.on_thinking:
                await self.on_thinking(
                    f"[model switch skipped] ACP agent did not advertise requested model: {self.model}"
                )
            return
        if self._current_model_id == self.model:
            return
        switched = await self.set_model(self.model)
        if not switched and self.on_thinking:
            await self.on_thinking(f"[model switch failed] {self.model}")

    async def _load_session(self, session_id: str) -> Dict[str, Any]:
        """Send ``session/load`` for a prior session id.

        The agent will re-emit historical updates (or a subset, depending
        on the agent) so the client can rebuild any cached UI state. We
        persist the touch on success so the resume bumps last_used_at.
        """
        from superqode.mcp.config import get_acp_mcp_servers

        params: Dict[str, Any] = {
            "cwd": str(self.project_root),
            "mcpServers": get_acp_mcp_servers(),
            "sessionId": session_id,
        }
        response = await self._call_method(
            "session/load",
            timeout=self.startup_timeout,
            **params,
        )
        self._session_id = session_id
        self._apply_session_state_from_response(response)
        await self._persist_current_session(touch_only=True)
        return response

    def _apply_session_state_from_response(self, response: Dict[str, Any]) -> None:
        """Capture session state returned by ``session/new`` or ``session/load``."""
        self._apply_config_options_from_response(response)

        modes = response.get("modes")
        if isinstance(modes, dict):
            available = modes.get("availableModes")
            if isinstance(available, list):
                self._available_modes = available
            current = modes.get("currentModeId")
            if isinstance(current, str):
                self._current_mode_id = current

        models = response.get("models")
        if isinstance(models, dict):
            available = models.get("availableModels")
            if isinstance(available, list):
                self._available_models = available
            current = models.get("currentModelId")
            if isinstance(current, str):
                self._current_model_id = current

    def _apply_config_options_from_response(self, response: Dict[str, Any]) -> None:
        """Capture generic ACP config options and derive model state from them."""
        options = response.get("configOptions")
        if not isinstance(options, list):
            return
        self._config_options = [item for item in options if isinstance(item, dict)]

        model_option = self._model_config_option()
        if model_option is None:
            return
        current = model_option.get("currentValue")
        if isinstance(current, str) and current:
            self._current_model_id = current
        models = self._models_from_config_option(model_option)
        if models:
            self._available_models = models

    @staticmethod
    def _model_id(model: Any) -> Optional[str]:
        """Return a model id from known ACP/OpenCode model shapes."""
        if not isinstance(model, dict):
            return None
        for key in ("modelId", "modelID", "id", "value"):
            value = model.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _model_config_option(self) -> Optional[dict]:
        """Return the generic config option that represents model selection."""
        for option in self._config_options:
            if not isinstance(option, dict):
                continue
            if option.get("id") == "model" or option.get("category") == "model":
                return option
        return None

    def _models_from_config_option(self, option: dict) -> List[dict]:
        """Convert a generic select config option into AvailableModel objects."""
        out: List[dict] = []

        def append_items(items: Any) -> None:
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("options"), list):
                    append_items(item.get("options"))
                    continue
                model_id = self._model_id(item)
                if not model_id:
                    continue
                out.append(
                    {
                        "id": model_id,
                        "modelId": model_id,
                        "name": item.get("name") or item.get("label") or model_id,
                        **({"description": item["description"]} if item.get("description") else {}),
                    }
                )

        append_items(option.get("options"))
        return out

    @staticmethod
    def _usage_cost_amount(usage: Dict[str, Any]) -> float:
        cost = usage.get("cost")
        if isinstance(cost, dict):
            try:
                return float(cost.get("amount") or 0.0)
            except (TypeError, ValueError):
                return 0.0
        try:
            return float(cost or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _merge_usage(self, usage: Dict[str, Any]) -> None:
        """Merge usage from ACP prompt responses or usage_update events."""
        for key, value in usage.items():
            if value is not None:
                self._usage[key] = value

    async def _persist_current_session(self, *, touch_only: bool = False) -> None:
        """Record the current session in the store (if configured).

        ``touch_only=True`` skips the metadata payload — used after a
        resume so we just bump ``last_used_at`` without overwriting any
        prior model / agent info the user may have set.
        """
        if self.session_store is None or not self.agent_identity:
            return
        if not self._session_id:
            return
        if touch_only:
            await self.session_store.touch(self.agent_identity, self._session_id)
            return
        metadata: Dict[str, Any] = {}
        if self.model:
            metadata["model"] = self.model
        await self.session_store.record(
            self.agent_identity,
            self._session_id,
            str(self.project_root),
            metadata=metadata,
        )

    async def _call_method(
        self,
        method: str,
        *,
        timeout: Optional[float] = None,
        **params,
    ) -> Dict[str, Any]:
        """Call a JSON-RPC method and wait for response."""
        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id,
        }

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        # Send request
        await self._send_json(request)

        # Wait for response
        try:
            response = await asyncio.wait_for(future, timeout=timeout or self.request_timeout)
            return response
        except asyncio.TimeoutError:
            del self._pending_requests[request_id]
            raise

    async def _send_notification(self, method: str, **params) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._send_json(notification)

    async def _send_json(self, data: dict) -> None:
        """Send JSON data to the agent."""
        if self._process and self._process.stdin:
            await self._log_traffic("client->agent", data)
            json_bytes = json.dumps(data).encode("utf-8") + b"\n"
            self._process.stdin.write(json_bytes)
            await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        """Read and process output from the agent."""
        if not self._process or not self._process.stdout:
            return

        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                    await self._log_traffic("agent->client", data)
                    if self._is_jsonrpc_response(data):
                        await self._handle_message(data)
                    else:
                        task = asyncio.create_task(self._handle_message(data))
                        self._inbound_tasks.add(task)
                        task.add_done_callback(self._inbound_tasks.discard)
                except json.JSONDecodeError:
                    # Not JSON - might be debug output, log it
                    if self.on_thinking and line_str:
                        await self.on_thinking(f"[agent] {line_str}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self.on_thinking:
                await self.on_thinking(f"[error] {e}")
        finally:
            if self._inbound_tasks:
                for task in list(self._inbound_tasks):
                    task.cancel()
                await asyncio.gather(*self._inbound_tasks, return_exceptions=True)
                self._inbound_tasks.clear()

    @staticmethod
    def _is_jsonrpc_response(data: Any) -> bool:
        """Return True when ``data`` is a JSON-RPC response object."""
        return isinstance(data, dict) and ("result" in data or "error" in data)

    async def _handle_message(self, data: dict) -> None:
        """Handle an incoming JSON-RPC message."""
        # Check if it's a response to a pending request
        if "result" in data or "error" in data:
            request_id = data.get("id")
            if request_id is not None and request_id in self._pending_requests:
                future = self._pending_requests.pop(request_id)
                if "error" in data:
                    future.set_exception(Exception(data["error"].get("message", "Unknown error")))
                else:
                    future.set_result(data.get("result", {}))
            return

        # It's a request from the agent - handle it
        method = data.get("method", "")
        params = data.get("params", {})
        request_id = data.get("id")

        try:
            result = await self._handle_agent_request(method, params)

            # Send response if this was a request (not notification)
            if request_id is not None:
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": request_id,
                }
                await self._send_json(response)

        except Exception as e:
            if request_id is not None:
                error_response = {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": str(e),
                    },
                    "id": request_id,
                }
                await self._send_json(error_response)

    async def _handle_agent_request(self, method: str, params: dict) -> Any:
        """Handle a request from the agent."""

        if method == "session/update":
            await self._handle_session_update(params)
            return {}

        elif method == "session/request_permission":
            return await self._handle_permission_request(params)

        elif method == "fs/read_text_file":
            return self._handle_read_file(params)

        elif method == "fs/write_text_file":
            return self._handle_write_file(params)

        elif method == "terminal/create":
            return await self._handle_terminal_create(params)

        elif method == "terminal/output":
            return await self._handle_terminal_output(params)

        elif method == "terminal/kill":
            return await self._handle_terminal_kill(params)

        elif method == "terminal/release":
            return await self._handle_terminal_release(params)

        elif method == "terminal/wait_for_exit":
            return await self._handle_terminal_wait_for_exit(params)

        else:
            raise Exception(f"Unknown method: {method}")

    async def _handle_session_update(self, params: dict) -> None:
        """Handle session update notifications."""
        # The params dict IS the update - sessionUpdate is a direct key
        update = params
        update_type = update.get("sessionUpdate", "")

        # Also check if update is nested (some implementations do this)
        if not update_type and "update" in params:
            update = params.get("update", {})
            update_type = update.get("sessionUpdate", "")
        if isinstance(update_type, dict):
            update = update_type
            update_type = update.get("sessionUpdate", "") or update.get("type", "")

        if update_type in ("agent_message_chunk", "agent_message"):
            content = update.get("content", {})
            text = self._content_to_text(content)
            if text:
                self._message_buffer += text
                if self.on_message:
                    await self.on_message(text)

        elif update_type in ("user_message_chunk", "user_message"):
            content = update.get("content", {})
            text = self._content_to_text(content)
            if text and self.on_user_message:
                await self.on_user_message(text)

        elif update_type in ("agent_thought_chunk", "agent_thought"):
            content = update.get("content", {})
            text = self._content_to_text(content)
            if text and self.on_thinking:
                await self.on_thinking(text)

        elif update_type == "tool_call":
            tool_call_id = update.get("toolCallId", "")
            self._tool_calls[tool_call_id] = update

            # Track tool action — surface parentToolCallId so consumers
            # (TUI, stats) can render nested calls under their parent
            # without having to dig into `_meta` themselves.
            kind = update.get("kind", "other")
            title = update.get("title", "")
            raw_input = update.get("rawInput", {})
            parent_id = (update.get("_meta") or {}).get("parentToolCallId")
            self._tool_actions.append(
                {
                    "tool": title,
                    "kind": kind,
                    "input": raw_input,
                    "tool_call_id": tool_call_id,
                    "parent_tool_call_id": parent_id,
                }
            )

            # Track file operations from tool call
            locations = update.get("locations", [])
            for loc in locations:
                path = loc.get("path", "")
                if path:
                    if kind in ("edit", "write", "delete"):
                        if path not in self._files_modified:
                            self._files_modified.append(path)
                    elif kind == "read":
                        if path not in self._files_read:
                            self._files_read.append(path)

            if self.on_tool_call:
                await self.on_tool_call(update)

        elif update_type == "tool_call_update":
            tool_call_id = update.get("toolCallId", "")
            if tool_call_id in self._tool_calls:
                # Merge update into existing tool call
                for key, value in update.items():
                    if value is not None:
                        self._tool_calls[tool_call_id][key] = value
            else:
                # Late-arriving update with no prior tool_call event —
                # some agents (notably OpenHands, some Codex builds)
                # skip the create event. Synthesize a placeholder so we
                # don't silently drop the update, then merge.
                synthesized = {
                    "sessionUpdate": "tool_call",
                    "toolCallId": tool_call_id,
                    "title": "Tool call",
                }
                for key, value in update.items():
                    if value is not None:
                        synthesized[key] = value
                self._tool_calls[tool_call_id] = synthesized
                # Surface as a tool_call (not update) for the first sight.
                if self.on_tool_call:
                    await self.on_tool_call(synthesized)
                return
            if self.on_tool_update:
                await self.on_tool_update(update)

        elif update_type == "plan":
            entries = update.get("entries", [])
            if self.on_plan:
                await self.on_plan(entries)

        elif update_type == "available_commands_update":
            commands = update.get("availableCommands", [])
            if isinstance(commands, list):
                self._available_commands = commands
                if self.on_available_commands:
                    await self.on_available_commands(commands)

        elif update_type == "current_mode_update":
            mode_id = update.get("currentModeId")
            if isinstance(mode_id, str):
                self._current_mode_id = mode_id
                if self.on_mode_update:
                    await self.on_mode_update(mode_id)

        elif update_type == "usage_update":
            usage = {k: v for k, v in update.items() if k != "sessionUpdate"}
            self._merge_usage(usage)
            if self.on_usage_update:
                await self.on_usage_update(dict(self._usage))

    def _content_to_text(self, content: Any) -> str:
        """Convert ACP content blocks into a displayable text string."""
        if content is None:
            return ""
        if isinstance(content, list):
            parts = [self._content_to_text(item) for item in content]
            return "".join([p for p in parts if p])
        if not isinstance(content, dict):
            return str(content)

        content_type = content.get("type")
        if content_type == "text":
            return content.get("text", "")
        if content_type == "image":
            mime = content.get("mimeType", "image")
            data = content.get("data", "")
            size = len(data) if isinstance(data, str) else 0
            return f"[image:{mime} {size} bytes]"
        if content_type == "audio":
            mime = content.get("mimeType", "audio")
            return f"[audio:{mime}]"
        if content_type in ("resource", "embedded_resource", "embeddedResource"):
            name = content.get("name") or content.get("uri") or "resource"
            return f"[resource:{name}]"
        if content_type in ("resource_link", "link"):
            name = content.get("title") or content.get("uri") or "link"
            return f"[link:{name}]"

        text = content.get("text")
        if text:
            return text
        return ""

    async def _handle_permission_request(self, params: dict) -> dict:
        """Handle permission request from agent.

        Resolution order:
        1. Persistent store (if configured) — auto-respond with the
           remembered ``allow_always`` / ``reject_always`` outcome so
           the user isn't re-prompted across sessions.
        2. User callback — prompts the user for a fresh decision. If
           the user picks an ``always`` option, persist it.
        3. Default fall-through — ``allow_once`` if present, otherwise
           the first option, otherwise ``cancelled``.
        """
        options = params.get("options", [])
        tool_call = params.get("toolCall", {})

        # Store tool call if not already stored
        tool_call_id = tool_call.get("toolCallId", "")
        if tool_call_id and tool_call_id not in self._tool_calls:
            self._tool_calls[tool_call_id] = tool_call

        # Step 1: persistent store lookup.
        if self.permission_store is not None and self.permission_scope:
            tool_key = (
                tool_call.get("title")
                or (tool_call.get("rawInput") or {}).get("tool_name")
                or "unknown"
            )
            stored = await self.permission_store.get(self.permission_scope, tool_key)
            if stored is not None:
                target_kind = stored.value  # "allow_always" | "reject_always"
                for opt in options:
                    if opt.get("kind") == target_kind:
                        return {
                            "outcome": {
                                "outcome": "selected",
                                "optionId": opt.get("optionId", ""),
                            }
                        }
                # Stored decision exists but the agent didn't offer a
                # matching ``always`` option. Fall back to the matching
                # once-variant so the decision is still respected this
                # turn even if it can't be re-locked.
                fallback_kind = "allow_once" if stored.allowed else "reject_once"
                for opt in options:
                    if opt.get("kind") == fallback_kind:
                        return {
                            "outcome": {
                                "outcome": "selected",
                                "optionId": opt.get("optionId", ""),
                            }
                        }

        # Step 2: user callback. If they pick an ``always`` option, save it.
        if self.on_permission_request:
            option_id = await self.on_permission_request(options, tool_call)
            if self.permission_store is not None and self.permission_scope and option_id:
                picked = next(
                    (o for o in options if o.get("optionId") == option_id),
                    None,
                )
                if picked is not None:
                    decision = PermissionDecision.from_option_kind(picked.get("kind"))
                    if decision is not None:
                        tool_key = (
                            tool_call.get("title")
                            or (tool_call.get("rawInput") or {}).get("tool_name")
                            or "unknown"
                        )
                        await self.permission_store.set(self.permission_scope, tool_key, decision)
            return {
                "outcome": {
                    "outcome": "selected",
                    "optionId": option_id,
                }
            }

        # Default: allow once
        for opt in options:
            if opt.get("kind") == "allow_once":
                return {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": opt.get("optionId", ""),
                    }
                }

        # Fallback to first option
        if options:
            return {
                "outcome": {
                    "outcome": "selected",
                    "optionId": options[0].get("optionId", ""),
                }
            }

        return {"outcome": {"outcome": "cancelled"}}

    def _handle_read_file(self, params: dict) -> dict:
        """Handle file read request."""
        path = params.get("path", "")
        line = params.get("line")
        limit = params.get("limit")

        # Track file read
        if path and path not in self._files_read:
            self._files_read.append(path)

        read_path = self.project_root / path
        try:
            text = read_path.read_text(encoding="utf-8", errors="ignore")

            if line is not None:
                line = max(0, line - 1)
                lines = text.splitlines()
                if limit is None:
                    text = "\n".join(lines[line:])
                else:
                    text = "\n".join(lines[line : line + limit])

            return {"content": text}
        except IOError:
            return {"content": ""}

    def _handle_write_file(self, params: dict) -> dict:
        """Handle file write request."""
        path = params.get("path", "")
        content = params.get("content", "")

        # Track file modification
        if path and path not in self._files_modified:
            self._files_modified.append(path)

        write_path = self.project_root / path
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(content, encoding="utf-8")
        return {}

    # ========================================================================
    # Mode and Model Management (ACP Protocol Completeness)
    # ========================================================================

    async def get_available_modes(self) -> List[AvailableMode]:
        """Get list of available modes from the agent."""
        if self._available_modes:
            return self._available_modes
        try:
            response = await self._call_method(
                "session/modes",
                sessionId=self._session_id,
            )
            modes = response.get("modes")
            if isinstance(modes, dict):
                available = modes.get("availableModes", [])
                current = modes.get("currentModeId")
                if isinstance(available, list):
                    self._available_modes = available
                if isinstance(current, str):
                    self._current_mode_id = current
                return self._available_modes
            if isinstance(modes, list):
                self._available_modes = modes
                return modes
            return response.get("availableModes", [])
        except Exception:
            return []

    async def get_available_models(self) -> List[AvailableModel]:
        """Get list of available models from the agent."""
        if self._available_models:
            return self._available_models
        try:
            response = await self._call_method(
                "session/models",
                sessionId=self._session_id,
            )
            models = response.get("models")
            if isinstance(models, dict):
                available = models.get("availableModels", [])
                current = models.get("currentModelId")
                if isinstance(available, list):
                    self._available_models = available
                if isinstance(current, str):
                    self._current_model_id = current
                return self._available_models
            if isinstance(models, list):
                self._available_models = models
                return models
            available = response.get("availableModels", [])
            if isinstance(available, list):
                self._available_models = available
            return self._available_models
        except Exception:
            return []

    async def set_mode(self, mode_id: str) -> bool:
        """Set the current mode for the session."""
        try:
            await self._call_method(
                "session/set_mode",
                sessionId=self._session_id,
                modeId=mode_id,
            )
            self._current_mode_id = mode_id
            return True
        except Exception:
            return False

    async def set_model(self, model_id: str) -> bool:
        """Set the current model for the session."""
        try:
            await self._call_method(
                "session/set_model",
                sessionId=self._session_id,
                modelId=model_id,
            )
            self._current_model_id = model_id
            return True
        except Exception:
            return False

    async def set_config_option(self, config_id: str, value: str) -> bool:
        """Set a generic ACP session config option."""
        try:
            response = await self._call_method(
                "session/set_config_option",
                sessionId=self._session_id,
                configId=config_id,
                value=value,
            )
            self._apply_session_state_from_response(response)
            if config_id == "model":
                self._current_model_id = value
            return True
        except Exception:
            return False

    async def get_current_mode(self) -> Optional[str]:
        """Get the current mode."""
        if self._current_mode_id:
            return self._current_mode_id
        try:
            response = await self._call_method(
                "session/modes",
                sessionId=self._session_id,
            )
            modes = response.get("modes")
            if isinstance(modes, dict):
                current = modes.get("currentModeId")
                if isinstance(current, str):
                    self._current_mode_id = current
                    return current
            current = response.get("currentModeId") or response.get("currentMode")
            if isinstance(current, str):
                self._current_mode_id = current
                return current
            return None
        except Exception:
            return None

    async def get_current_model(self) -> Optional[str]:
        """Get the current model."""
        if self._current_model_id:
            return self._current_model_id
        try:
            response = await self._call_method(
                "session/models",
                sessionId=self._session_id,
            )
            models = response.get("models")
            if isinstance(models, dict):
                current = models.get("currentModelId")
                if isinstance(current, str):
                    self._current_model_id = current
                    return current
            current = response.get("currentModelId") or response.get("currentModel")
            if isinstance(current, str):
                self._current_model_id = current
                return current
            return None
        except Exception:
            return None

    # ========================================================================
    # Slash Commands (ACP Protocol Completeness)
    # ========================================================================

    async def get_available_commands(self) -> List[SlashCommand]:
        """Get list of available slash commands from the agent."""
        if self._available_commands:
            return self._available_commands
        try:
            response = await self._call_method(
                "session/commands",
                sessionId=self._session_id,
            )
            commands = response.get("availableCommands") or response.get("commands", [])
            if isinstance(commands, list):
                self._available_commands = commands
                return commands
            return []
        except Exception:
            return []

    async def execute_command(
        self, command_name: str, args: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Execute a slash command."""
        try:
            response = await self._call_method(
                "session/execute_command",
                sessionId=self._session_id,
                command=command_name,
                args=args or {},
            )
            return response.get("result")
        except Exception as e:
            return None

    # ========================================================================
    # Batch Operations (ACP Protocol Completeness)
    # ========================================================================

    async def batch_request(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute multiple requests in a batch."""
        try:
            response = await self._call_method(
                "batch",
                requests=requests,
            )
            return response.get("responses", [])
        except Exception:
            return []

    # ========================================================================
    # Terminal Handling
    # ========================================================================

    async def _handle_terminal_create(self, params: dict) -> CreateTerminalResponse:
        """Handle terminal create request."""
        if self.terminal_service is not None:
            return await self.terminal_service.create(params)

        command = params.get("command", "")
        args = params.get("args", [])
        cwd = params.get("cwd")
        env_vars = params.get("env", [])

        self._terminal_count += 1
        terminal_id = f"terminal-{self._terminal_count}"

        # Build environment
        env = os.environ.copy()
        for var in env_vars:
            env[var["name"]] = var["value"]

        # Build full command
        if args:
            full_command = f"{command} {' '.join(args)}"
        else:
            full_command = command

        # Start the process
        try:
            process = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.PIPE,
                cwd=cwd or str(self.project_root),
                env=env,
            )

            self._terminals[terminal_id] = {
                "process": process,
                "output": "",
                "truncated": False,
                "exit_code": None,
                "signal": None,
            }

            # Start reading output in background
            asyncio.create_task(self._read_terminal_output(terminal_id))

            return {"terminalId": terminal_id}

        except Exception as e:
            raise Exception(f"Failed to create terminal: {e}")

    async def _read_terminal_output(self, terminal_id: str) -> None:
        """Read output from a terminal process."""
        terminal = self._terminals.get(terminal_id)
        if not terminal:
            return

        process = terminal["process"]
        output_limit = 100 * 1024  # 100KB limit

        try:
            while True:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    break

                text = chunk.decode("utf-8", errors="replace")

                if len(terminal["output"]) + len(text) > output_limit:
                    terminal["truncated"] = True
                    remaining = output_limit - len(terminal["output"])
                    terminal["output"] += text[:remaining]
                    break
                else:
                    terminal["output"] += text

            # Process finished
            await process.wait()
            terminal["exit_code"] = process.returncode

        except Exception:
            pass

    async def _handle_terminal_output(self, params: dict) -> TerminalOutputResponse:
        """Handle terminal output request."""
        if self.terminal_service is not None:
            return await self.terminal_service.output(params)

        terminal_id = params.get("terminalId", "")
        terminal = self._terminals.get(terminal_id)

        if not terminal:
            return {
                "output": "",
                "truncated": False,
            }

        result: TerminalOutputResponse = {
            "output": terminal["output"],
            "truncated": terminal["truncated"],
        }

        if terminal["exit_code"] is not None:
            result["exitStatus"] = {"exitCode": terminal["exit_code"]}

        return result

    async def _handle_terminal_kill(self, params: dict) -> dict:
        """Handle terminal kill request."""
        if self.terminal_service is not None:
            return await self.terminal_service.kill(params)

        terminal_id = params.get("terminalId", "")
        terminal = self._terminals.get(terminal_id)

        if terminal and terminal["process"]:
            terminal["process"].terminate()

        return {}

    async def _handle_terminal_release(self, params: dict) -> dict:
        """Handle terminal release request."""
        if self.terminal_service is not None:
            return await self.terminal_service.release(params)

        terminal_id = params.get("terminalId", "")
        if terminal_id in self._terminals:
            del self._terminals[terminal_id]
        return {}

    async def _handle_terminal_wait_for_exit(self, params: dict) -> WaitForTerminalExitResponse:
        """Handle terminal wait for exit request."""
        if self.terminal_service is not None:
            return await self.terminal_service.wait_for_exit(params)

        terminal_id = params.get("terminalId", "")
        terminal = self._terminals.get(terminal_id)

        if not terminal:
            return {"exitCode": -1, "signal": None}

        process = terminal["process"]

        # Wait for process to complete
        await process.wait()
        terminal["exit_code"] = process.returncode

        return {
            "exitCode": terminal["exit_code"],
            "signal": terminal["signal"],
        }
