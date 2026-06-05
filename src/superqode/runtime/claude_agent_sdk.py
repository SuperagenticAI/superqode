"""Anthropic Claude Agent SDK runtime adapter.

Drives the official ``claude-agent-sdk`` (the Python SDK for Claude Code) behind
SuperQode's ``AgentRuntime`` shape, using **API-key auth** (``ANTHROPIC_API_KEY``)
— this is the Agent-SDK path, NOT a Claude subscription. The SDK launches the
local ``claude`` CLI; ``ClaudeSDKClient`` gives continuous conversations,
interrupts, ``set_model``/permission-mode control, and session lifecycle.

The SDK is async-native, so (unlike the Codex adapter) the streaming path reads
``client.receive_response()`` directly — no reader thread/queue.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any, Callable

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from ..harness.events import HarnessEvent
from ..tools.permissions import Permission, PermissionManager
from .errors import RuntimeNotInstalledError

# Curated Claude model catalog — the SDK exposes no model_list(); "" defers to
# Claude Code's configured default.
CLAUDE_MODELS: list[tuple[str, str]] = [
    ("", "Claude Code default"),
    ("claude-opus-4-8", "Claude Opus 4.8"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ("claude-haiku-4-5", "Claude Haiku 4.5"),
]

_PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto")
_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# Claude Code emits capitalized tool names (Bash, Write, Edit, …). Map them to
# SuperQode's internal names so PermissionManager's group/safety logic (which
# keys on bash/write_file/edit_file/patch) applies correctly.
_CLAUDE_TOOL_NAMES = {
    "bash": "bash",
    "write": "write_file",
    "edit": "edit_file",
    "multiedit": "edit_file",
    "notebookedit": "edit_file",
    "read": "read_file",
    "glob": "glob",
    "grep": "grep",
    "webfetch": "web_fetch",
    "websearch": "web_search",
}


def _normalize_tool_name(name: str) -> str:
    return _CLAUDE_TOOL_NAMES.get((name or "").lower(), (name or "").lower())


def _require_sdk() -> None:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "Claude Agent SDK runtime requires the 'claude-agent-sdk' extra. "
            "Install with: pip install superqode[claude-agent-sdk] (and the Claude Code CLI), "
            "then set ANTHROPIC_API_KEY."
        ) from exc


def _coerce_effort(effort: str | None) -> str | None:
    if effort is None:
        return None
    norm = effort.strip().lower()
    if norm in ("", "default", "none"):
        return None
    if norm not in _EFFORT_LEVELS:
        raise ValueError(f"Unsupported Claude reasoning effort: {effort}")
    return norm


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", item)))
            else:
                parts.append(str(getattr(item, "text", item)))
        return "\n".join(parts)
    return str(content)


def _usage_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return dict(usage)
    if hasattr(usage, "model_dump"):
        try:
            return usage.model_dump()
        except Exception:  # noqa: BLE001
            return {}
    return {}


class ClaudeAgentSDKRuntime:
    """Claude Agent SDK-backed runtime (API key)."""

    name = "claude-agent-sdk"

    def __init__(
        self,
        *,
        config: AgentConfig | None = None,
        permission_manager: PermissionManager | None = None,
        approval_callback: Callable[[str, dict[str, Any]], bool] | None = None,
        sandbox_backend: str | None = None,
        **_unused: Any,
    ) -> None:
        _require_sdk()
        if config is None:
            raise ValueError("ClaudeAgentSDKRuntime requires 'config'")
        self.config = config
        self.session_id = config.session_id or f"claude-{uuid.uuid4().hex[:8]}"
        self.sandbox_backend = sandbox_backend
        self._uses_default_permission_manager = permission_manager is None
        self._approval_callback = approval_callback
        self._permission_manager = permission_manager or PermissionManager()
        self._client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cancelled = False
        self._reasoning_effort: str | None = None
        self._permission_mode: str | None = None
        self._pending_model: str | None = None
        self._pending_mode: str | None = None
        self._resume_session_id: str | None = None
        self._needs_reconnect = False
        self._slash_commands: list[str] = []
        self._active_session_id: str | None = None
        self._turn_lock = asyncio.Lock()

    # --- readiness -----------------------------------------------------------
    @staticmethod
    def api_key_present() -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": self.name,
            "session_id": self._active_session_id,
            "slash_commands": list(self._slash_commands),
            "api_key": self.api_key_present(),
        }

    # --- lifecycle -----------------------------------------------------------
    async def _ensure_started(self) -> None:
        if self._client is not None and not self._needs_reconnect:
            return
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        if self._client is not None and self._needs_reconnect:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
            self._needs_reconnect = False

        opts: dict[str, Any] = {
            "cwd": str(self.config.working_directory),
            "can_use_tool": self._approval_handler,
        }
        if self.config.model:
            opts["model"] = self.config.model
        if self._permission_mode:
            opts["permission_mode"] = self._permission_mode
        if self._reasoning_effort:
            opts["effort"] = self._reasoning_effort
        if self.config.custom_system_prompt:
            opts["system_prompt"] = self.config.custom_system_prompt
        if self._resume_session_id:
            opts["resume"] = self._resume_session_id

        client = ClaudeSDKClient(options=ClaudeAgentOptions(**opts))
        await client.connect()
        self._client = client
        self._loop = asyncio.get_running_loop()

    async def _apply_pending(self) -> None:
        if self._pending_model is not None:
            try:
                await self._client.set_model(self._pending_model or None)
            except Exception:  # noqa: BLE001
                pass
            self._pending_model = None
        if self._pending_mode is not None:
            try:
                await self._client.set_permission_mode(self._pending_mode)
            except Exception:  # noqa: BLE001
                pass
            self._pending_mode = None

    # --- approvals (async can_use_tool) -------------------------------------
    async def _approval_handler(self, tool_name: str, tool_input: dict[str, Any], context: Any):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        decision, reason = await asyncio.to_thread(
            self._decide_permission, str(tool_name), dict(tool_input or {})
        )
        if decision == "allow":
            return PermissionResultAllow()
        return PermissionResultDeny(message=reason or f"SuperQode rejected {tool_name}")

    def _decide_permission(self, tool_name: str, args: dict[str, Any]) -> tuple[str, str]:
        if self._uses_default_permission_manager:
            if self._approval_callback is not None:
                ok = self._safe_callback(tool_name, args)
                return ("allow", "") if ok else ("deny", f"SuperQode user rejected {tool_name}")
            return ("deny", self._interactive_unavailable(tool_name))
        # Normalize Claude's tool names (Bash/Write/Edit) to SuperQode's internal
        # names so bash/write/edit policies + dangerous-command checks apply.
        permission = self._permission_manager.check_permission(
            _normalize_tool_name(tool_name), args
        )
        if permission == Permission.ALLOW:
            return ("allow", "")
        if permission == Permission.ASK and self._approval_callback is not None:
            ok = self._safe_callback(tool_name, args)
            return ("allow", "") if ok else ("deny", f"SuperQode user rejected {tool_name}")
        if permission == Permission.DENY:
            return ("deny", f"SuperQode permission policy rejected {tool_name}")
        return ("deny", self._interactive_unavailable(tool_name))

    def _safe_callback(self, tool_name: str, args: dict[str, Any]) -> bool:
        try:
            return bool(self._approval_callback(tool_name, args))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _interactive_unavailable(tool_name: str) -> str:
        return (
            f"SuperQode cannot present interactive approval for {tool_name} outside the TUI; "
            "set a Claude permission mode or pass an explicit PermissionManager"
        )

    # --- run -----------------------------------------------------------------
    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        async with self._turn_lock:
            self.reset_cancellation()
            await self._ensure_started()
            await self._apply_pending()
            yield HarnessEvent(type="model_request", data={"runtime": self.name})
            await self._client.query(prompt)
            completed = False
            tool_names: dict[str, str] = {}
            async for message in self._client.receive_response():
                for event in self._events_from_message(message, tool_names):
                    if event.type == "turn_complete":
                        completed = True
                    yield event
            if not completed:
                if self._cancelled:
                    yield HarnessEvent(type="turn_complete", data={"status": "cancelled"})
                else:
                    raise RuntimeError("Claude stream ended without a ResultMessage")
            yield HarnessEvent(type="model_result", data={"runtime": self.name})

    def _events_from_message(self, message: Any, tool_names: dict[str, str]) -> list[HarnessEvent]:
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ThinkingBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
        )

        events: list[HarnessEvent] = []
        if isinstance(message, SystemMessage):
            data = getattr(message, "data", {}) or {}
            if getattr(message, "subtype", "") == "init":
                self._slash_commands = list(data.get("slash_commands", []) or [])
                self._active_session_id = data.get("session_id") or self._active_session_id
            return events
        if isinstance(message, AssistantMessage):
            for block in getattr(message, "content", []) or []:
                if isinstance(block, TextBlock) and block.text:
                    events.append(HarnessEvent(type="model_delta", data={"text": block.text}))
                elif isinstance(block, ThinkingBlock) and getattr(block, "thinking", ""):
                    events.append(HarnessEvent(type="thinking", data={"text": block.thinking}))
                elif isinstance(block, ToolUseBlock):
                    tool_names[block.id] = block.name
                    events.append(
                        HarnessEvent(
                            type="tool_call",
                            data={
                                "tool_name": block.name,
                                "tool_call_id": block.id,
                                "args": dict(block.input or {}),
                            },
                        )
                    )
            return events
        if isinstance(message, UserMessage):
            for block in getattr(message, "content", []) or []:
                if isinstance(block, ToolResultBlock):
                    events.append(
                        HarnessEvent(
                            type="tool_result",
                            data={
                                "tool_name": tool_names.get(block.tool_use_id, "tool"),
                                "tool_call_id": block.tool_use_id,
                                "success": not bool(getattr(block, "is_error", False)),
                                "output": _content_to_text(getattr(block, "content", "")),
                            },
                        )
                    )
            return events
        if isinstance(message, ResultMessage):
            status = "error" if getattr(message, "is_error", False) else "completed"
            self._active_session_id = (
                getattr(message, "session_id", None) or self._active_session_id
            )
            events.append(
                HarnessEvent(
                    type="turn_complete",
                    data={
                        "status": status,
                        "cost_usd": getattr(message, "total_cost_usd", None),
                        "usage": _usage_dict(getattr(message, "usage", None)),
                    },
                )
            )
            return events
        return events

    async def run(self, prompt: str) -> AgentResponse:
        text_parts: list[str] = []
        tool_calls = 0
        stopped = "complete"
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta":
                text_parts.append(str(event.data.get("text", "")))
            elif event.type == "tool_call":
                tool_calls += 1
            elif event.type == "turn_complete":
                status = str(event.data.get("status", ""))
                if status not in ("completed", "complete", "success"):
                    stopped = status or stopped
        content = "".join(text_parts)
        return AgentResponse(
            content=content,
            messages=[
                AgentMessage(role="user", content=prompt),
                AgentMessage(role="assistant", content=content),
            ],
            tool_calls_made=tool_calls,
            iterations=1,
            stopped_reason=stopped,
            error=None,
        )

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta":
                text = event.data.get("text")
                if text:
                    yield str(text)

    # --- controls (sync; applied on the async path) --------------------------
    def set_model(self, model: str) -> None:
        self.config.model = (model or "").strip()
        self._pending_model = self.config.model

    def set_reasoning_effort(self, effort: str | None) -> None:
        self._reasoning_effort = _coerce_effort(effort)
        self._needs_reconnect = True  # effort is a connect-time option

    def set_permission_mode(self, mode: str) -> None:
        m = (mode or "").strip()
        if m not in _PERMISSION_MODES:
            raise ValueError(f"Unsupported Claude permission mode: {mode}")
        self._permission_mode = m
        self._pending_mode = m

    @property
    def reasoning_effort(self) -> str | None:
        return self._reasoning_effort

    @property
    def permission_mode(self) -> str | None:
        return self._permission_mode

    @property
    def slash_commands(self) -> list[str]:
        return list(self._slash_commands)

    @property
    def thread_id(self) -> str | None:
        return self._active_session_id

    def models(self, *, include_hidden: bool = False) -> list[dict[str, str]]:
        return [{"id": mid, "name": name} for mid, name in CLAUDE_MODELS]

    # --- sessions (sync module-level SDK helpers) ----------------------------
    def list_threads(self, *, limit: int = 20):
        from claude_agent_sdk import list_sessions

        return list_sessions(directory=str(self.config.working_directory), limit=limit)

    def resume_thread(self, session_id: str) -> None:
        self._resume_session_id = session_id
        self._active_session_id = session_id
        self._needs_reconnect = True

    def fork_thread(self, session_id: str):
        from claude_agent_sdk import fork_session

        return fork_session(session_id, directory=str(self.config.working_directory))

    def rename_thread(self, title: str) -> None:
        from claude_agent_sdk import rename_session

        if not self._active_session_id:
            raise RuntimeError("No active Claude session yet — send a message first")
        rename_session(self._active_session_id, title, directory=str(self.config.working_directory))

    def tag_thread(self, tag: str) -> None:
        from claude_agent_sdk import tag_session

        if not self._active_session_id:
            raise RuntimeError("No active Claude session yet — send a message first")
        tag_session(self._active_session_id, tag, directory=str(self.config.working_directory))

    # --- cancel/close --------------------------------------------------------
    def cancel(self) -> None:
        self._cancelled = True
        client, loop = self._client, self._loop
        if client is not None and loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(client.interrupt(), loop)
            except Exception:  # noqa: BLE001
                pass

    def reset_cancellation(self) -> None:
        self._cancelled = False

    def close(self) -> None:
        client, loop = self._client, self._loop
        self._client = None
        if client is not None and loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(client.disconnect(), loop)
            except Exception:  # noqa: BLE001
                pass


__all__ = ["ClaudeAgentSDKRuntime", "CLAUDE_MODELS"]
