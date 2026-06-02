"""OpenAI Codex Python SDK runtime adapter.

This backend drives the official ``openai-codex`` Python SDK while preserving
SuperQode's ``AgentRuntime`` shape. It is intentionally Codex-specific: the
native builtin runtime remains the portable SuperQode harness path.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from ..harness.events import HarnessEvent
from ..tools.permissions import Permission, PermissionConfig, PermissionManager, ToolGroup
from .errors import RuntimeNotInstalledError


def _require_sdk():
    try:
        import openai_codex  # noqa: F401
        from openai_codex import ApprovalMode, CodexConfig, Sandbox, Thread  # noqa: F401
        from openai_codex.client import CodexClient  # noqa: F401
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "Codex SDK runtime requires the 'codex-sdk' extra. "
            "Install with: pip install superqode[codex-sdk]"
        ) from exc


def _status_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


def _payload_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return dict(payload)
    if hasattr(payload, "model_dump"):
        dumped = payload.model_dump(mode="json", by_alias=True)
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _next_stream_item(stream) -> tuple[bool, Any]:
    try:
        return True, next(stream)
    except StopIteration:
        return False, None


class CodexSDKRuntime:
    """Official Codex Python SDK-backed runtime."""

    name = "codex-sdk"

    def __init__(
        self,
        *,
        config: AgentConfig | None = None,
        permission_manager: PermissionManager | None = None,
        sandbox_backend: str | None = None,
        **_unused: Any,
    ) -> None:
        _require_sdk()
        if config is None:
            raise ValueError("CodexSDKRuntime requires 'config'")

        self.config = config
        self.session_id = config.session_id or f"codex-{uuid.uuid4().hex[:8]}"
        self.sandbox_backend = sandbox_backend
        self._permission_manager = permission_manager or self._default_permission_manager(config)
        self._client = None
        self._thread = None
        self._init = None
        self._active_turn = None
        self._cancelled = False
        self._start_lock = threading.Lock()

    @staticmethod
    def _default_permission_manager(config: AgentConfig) -> PermissionManager:
        if config.require_confirmation:
            return PermissionManager()
        return PermissionManager(
            PermissionConfig(
                default=Permission.ALLOW,
                groups={
                    ToolGroup.READ: Permission.ALLOW,
                    ToolGroup.WRITE: Permission.ALLOW,
                    ToolGroup.SHELL: Permission.ALLOW,
                    ToolGroup.NETWORK: Permission.ALLOW,
                },
            )
        )

    @property
    def metadata(self):
        self._ensure_started_sync()
        return self._init

    def _ensure_started_sync(self) -> None:
        if self._client is not None and self._thread is not None:
            return
        with self._start_lock:
            if self._client is not None and self._thread is not None:
                return
            from openai_codex import ApprovalMode, CodexConfig, Thread
            from openai_codex.client import CodexClient

            sdk_config = CodexConfig(
                cwd=str(self.config.working_directory),
                client_name="superqode_codex_sdk",
                client_title="SuperQode Codex SDK Runtime",
            )
            client = CodexClient(config=sdk_config, approval_handler=self._approval_handler)
            try:
                client.start()
                self._init = client.initialize()
                started = client.thread_start(
                    {
                        "approvalPolicy": "on-request",
                        "approvalsReviewer": "auto-review",
                        "cwd": str(self.config.working_directory),
                        "model": self.config.model,
                        **(
                            {"modelProvider": self.config.provider}
                            if self.config.provider and self.config.provider != "openai"
                            else {}
                        ),
                        **(
                            {"developerInstructions": self.config.custom_system_prompt}
                            if self.config.custom_system_prompt
                            else {}
                        ),
                        **(
                            {"sandbox": self._thread_sandbox_mode()}
                            if self._thread_sandbox_mode()
                            else {}
                        ),
                    }
                )
            except Exception:
                client.close()
                raise
            self._client = client
            self._thread = Thread(client, started.thread.id)

    def _thread_sandbox_mode(self) -> str | None:
        if self.sandbox_backend in {"full", "full_access", "none"}:
            return "danger-full-access"
        if not self.config.tools_enabled:
            return "read-only"
        return "workspace-write"

    def _turn_sandbox(self):
        from openai_codex import Sandbox

        if self.sandbox_backend in {"full", "full_access", "none"}:
            return Sandbox.full_access
        if not self.config.tools_enabled:
            return Sandbox.read_only
        return Sandbox.workspace_write

    def _approval_handler(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        params = params or {}
        tool_name, arguments = self._approval_tool_request(method, params)
        if not tool_name:
            return {}
        permission = self._permission_manager.check_permission(tool_name, arguments)
        if permission == Permission.ALLOW:
            return {"decision": "accept"}
        reason = (
            f"SuperQode permission policy rejected {tool_name}"
            if permission == Permission.DENY
            else f"SuperQode permission policy requires interactive approval for {tool_name}; "
            "codex-sdk runtime denies unresolved approvals by default"
        )
        return {"decision": "reject", "reason": reason}

    def _approval_tool_request(
        self, method: str, params: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        if method == "item/commandExecution/requestApproval":
            command = (
                params.get("command")
                or params.get("cmd")
                or params.get("script")
                or " ".join(str(part) for part in params.get("argv", []) or [])
            )
            return "bash", {"command": str(command), **params}
        if method == "item/fileChange/requestApproval":
            path = params.get("path") or params.get("filePath") or params.get("targetPath") or ""
            return "patch", {"path": str(path), **params}
        return "", {}

    async def run(self, prompt: str) -> AgentResponse:
        return await asyncio.to_thread(self._run_sync, prompt)

    def _run_sync(self, prompt: str) -> AgentResponse:
        self.reset_cancellation()
        self._ensure_started_sync()
        turn = self._thread.turn(
            prompt,
            model=self.config.model,
            cwd=str(self.config.working_directory),
            sandbox=self._turn_sandbox(),
        )
        self._active_turn = turn
        try:
            result = turn.run()
        finally:
            self._active_turn = None
        return self._response_from_result(prompt, result)

    def _response_from_result(self, prompt: str, result: Any) -> AgentResponse:
        status = _status_value(getattr(result, "status", "complete")) or "complete"
        error = getattr(result, "error", None)
        final = getattr(result, "final_response", None) or ""
        items = list(getattr(result, "items", []) or [])
        usage = getattr(result, "usage", None)
        stopped_reason = "complete" if status in {"completed", "complete", "success"} else status
        return AgentResponse(
            content=final,
            messages=[
                AgentMessage(role="user", content=prompt),
                AgentMessage(role="assistant", content=final),
            ],
            tool_calls_made=sum(1 for item in items if self._item_is_tool_like(item)),
            iterations=1,
            stopped_reason=stopped_reason,
            error=str(error) if error else None,
        )

    @staticmethod
    def _item_is_tool_like(item: Any) -> bool:
        root = getattr(item, "root", item)
        item_type = getattr(root, "type", None)
        return item_type in {"commandExecution", "fileChange", "toolCall", "mcpToolCall"}

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta":
                text = event.data.get("text")
                if text:
                    yield str(text)

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        self.reset_cancellation()
        await asyncio.to_thread(self._ensure_started_sync)
        yield HarnessEvent(type="model_request", data={"runtime": self.name})
        turn = await asyncio.to_thread(
            self._thread.turn,
            prompt,
            model=self.config.model,
            cwd=str(self.config.working_directory),
            sandbox=self._turn_sandbox(),
        )
        self._active_turn = turn
        stream = turn.stream()
        try:
            while True:
                has_next, notification = await asyncio.to_thread(_next_stream_item, stream)
                if not has_next:
                    break
                for event in self._events_from_notification(notification):
                    yield event
        finally:
            self._active_turn = None
            close = getattr(stream, "close", None)
            if close is not None:
                close()
        yield HarnessEvent(type="model_result", data={"runtime": self.name})

    def _events_from_notification(self, notification: Any) -> list[HarnessEvent]:
        method = getattr(notification, "method", "")
        payload = getattr(notification, "payload", None)
        if method == "item/agentMessage/delta":
            return [HarnessEvent(type="model_delta", data={"text": getattr(payload, "delta", "")})]
        if method == "item/commandExecution/outputDelta":
            return [
                HarnessEvent(
                    type="tool_delta",
                    data={
                        "tool_name": "bash",
                        "text": getattr(payload, "delta", ""),
                        "tool_call_id": getattr(payload, "item_id", None),
                    },
                )
            ]
        if method == "item/fileChange/patchUpdated":
            return [
                HarnessEvent(
                    type="diff",
                    data={
                        "tool_name": "patch",
                        "tool_call_id": getattr(payload, "item_id", None),
                        "changes": _payload_dict(payload).get("changes", []),
                    },
                )
            ]
        if method == "item/completed":
            item = getattr(payload, "item", None)
            root = getattr(item, "root", item)
            item_type = getattr(root, "type", "")
            if item_type == "commandExecution":
                return [
                    HarnessEvent(
                        type="tool_result",
                        data={
                            "tool_name": "bash",
                            "tool_call_id": getattr(root, "id", None),
                            "success": _status_value(getattr(root, "status", "")) == "completed",
                            "output": getattr(root, "output", "") or "",
                            "error": getattr(root, "error", None),
                        },
                    )
                ]
            if item_type == "fileChange":
                return [
                    HarnessEvent(
                        type="tool_result",
                        data={
                            "tool_name": "patch",
                            "tool_call_id": getattr(root, "id", None),
                            "success": True,
                            "output": _payload_dict(root),
                        },
                    )
                ]
        if method == "turn/completed":
            turn = getattr(payload, "turn", None)
            return [
                HarnessEvent(
                    type="turn_complete",
                    data={"status": _status_value(getattr(turn, "status", ""))},
                )
            ]
        return []

    def cancel(self) -> None:
        self._cancelled = True
        turn = self._active_turn
        if turn is not None:
            try:
                turn.interrupt()
            except Exception:
                pass

    def reset_cancellation(self) -> None:
        self._cancelled = False

    def close(self) -> None:
        client = self._client
        self._client = None
        self._thread = None
        if client is not None:
            client.close()

    def models(self, *, include_hidden: bool = False):
        self._ensure_started_sync()
        return self._client.model_list(include_hidden=include_hidden)
