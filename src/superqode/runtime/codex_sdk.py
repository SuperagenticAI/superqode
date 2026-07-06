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
from typing import Any, Callable

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from ..harness.events import HarnessEvent
from ..tools.permissions import Permission, PermissionManager
from .errors import RuntimeNotInstalledError


def _require_sdk():
    try:
        import openai_codex  # noqa: F401
        from openai_codex import ApprovalMode, CodexConfig, Sandbox, Thread  # noqa: F401
        from openai_codex.client import CodexClient  # noqa: F401
    except ImportError as exc:
        from superqode.providers.env_introspect import install_command

        raise RuntimeNotInstalledError(
            "Codex SDK runtime requires the 'codex-sdk' extra. "
            f"Install with: {install_command('codex-sdk')}"
        ) from exc


def _status_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


def _payload_value(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    data = _payload_dict(obj)
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return default


def _payload_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return dict(payload)
    if hasattr(payload, "model_dump"):
        dumped = payload.model_dump(mode="json", by_alias=True)
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(payload, "__dict__"):
        return dict(vars(payload))
    return {}


def _todos_from_codex_plan(plan: Any) -> list[dict[str, str]]:
    todos: list[dict[str, str]] = []
    for index, item in enumerate(plan or (), 1):
        data = _payload_dict(item)
        step = str(data.get("step") or data.get("text") or data.get("content") or "").strip()
        if not step:
            continue
        todos.append(
            {
                "id": str(data.get("id") or index),
                "content": step,
                "status": _normalize_codex_plan_status(data.get("status")),
                "priority": str(data.get("priority") or "medium").lower(),
            }
        )
    return todos


def _todos_from_codex_todo_items(items: Any) -> list[dict[str, str]]:
    todos: list[dict[str, str]] = []
    for index, item in enumerate(items or (), 1):
        data = _payload_dict(item)
        text = str(data.get("text") or data.get("step") or data.get("content") or "").strip()
        if not text:
            continue
        todos.append(
            {
                "id": str(data.get("id") or index),
                "content": text,
                "status": "completed" if bool(data.get("completed")) else "pending",
                "priority": str(data.get("priority") or "medium").lower(),
            }
        )
    return todos


def _normalize_codex_plan_status(value: Any) -> str:
    raw = str(getattr(value, "value", value) or "").replace("-", "_")
    normalized = ""
    for char in raw:
        if char.isupper() and normalized:
            normalized += "_"
        normalized += char.lower()
    normalized = normalized.strip("_")
    if normalized in {"inprogress", "in_progress", "active", "running"}:
        return "in_progress"
    if normalized in {"complete", "completed", "done"}:
        return "completed"
    if normalized in {"cancelled", "canceled", "failed"}:
        return "cancelled"
    return "pending"


_STREAM_DONE = object()


def _start_stream_reader(stream, loop, queue: asyncio.Queue) -> threading.Thread:
    def read_stream() -> None:
        try:
            for notification in stream:
                asyncio.run_coroutine_threadsafe(queue.put(notification), loop).result()
        except BaseException as exc:  # noqa: BLE001
            asyncio.run_coroutine_threadsafe(queue.put(exc), loop).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(_STREAM_DONE), loop).result()

    thread = threading.Thread(target=read_stream, name="codex-sdk-stream", daemon=True)
    thread.start()
    return thread


class CodexSDKRuntime:
    """Official Codex Python SDK-backed runtime."""

    name = "codex-sdk"

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
            raise ValueError("CodexSDKRuntime requires 'config'")

        self.config = config
        self.session_id = config.session_id or f"codex-{uuid.uuid4().hex[:8]}"
        self.sandbox_backend = sandbox_backend
        self._uses_default_permission_manager = permission_manager is None
        self._approval_callback = approval_callback
        self._permission_manager = permission_manager or self._default_permission_manager(config)
        self._client = None
        self._thread = None
        self._init = None
        self._active_turn = None
        self._cancelled = False
        self._reasoning_effort: str | None = None
        self._next_turn_sandbox: str | None = None
        self._start_lock = threading.Lock()
        self._turn_lock = threading.Lock()

    @staticmethod
    def _default_permission_manager(config: AgentConfig) -> PermissionManager:
        return PermissionManager()

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

            # Identify SuperQode as the originating client (+ version) so Codex
            # usage from SuperQode is attributable — lets us track adoption and
            # which SuperQode version drove the session.
            try:
                from .. import __version__ as _sq_version
            except Exception:  # noqa: BLE001
                _sq_version = "0"

            sdk_config = CodexConfig(
                cwd=str(self.config.working_directory),
                client_name="superqode_codex_sdk",
                client_title="SuperQode Codex SDK Runtime",
                client_version=str(_sq_version),
            )
            client = CodexClient(config=sdk_config, approval_handler=self._approval_handler)
            try:
                client.start()
                self._init = client.initialize()
                # "Codex owns it": defer to the machine's ~/.codex configuration
                # (model, approval policy, sandbox, MCP, project trust). Only send
                # what the caller explicitly set, so an empty model/sandbox lets
                # the local Codex config decide. SuperQode imposes nothing extra.
                thread_params: dict[str, Any] = {"cwd": str(self.config.working_directory)}
                if self.config.model:
                    thread_params["model"] = self.config.model
                if self.config.provider and self.config.provider != "openai":
                    thread_params["modelProvider"] = self.config.provider
                if self.config.custom_system_prompt:
                    thread_params["developerInstructions"] = self.config.custom_system_prompt
                if self.sandbox_backend:  # explicit override only; else use ~/.codex
                    thread_params["sandbox"] = self._thread_sandbox_mode()
                started = client.thread_start(thread_params)
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
        return self._sdk_sandbox(self.sandbox_backend)

    @staticmethod
    def _sdk_sandbox(mode: str | None):
        from openai_codex import Sandbox

        if mode in {"full", "full_access", "full-access", "danger-full-access", "none"}:
            return Sandbox.full_access
        if mode in {"read", "readonly", "read-only"}:
            return Sandbox.read_only
        if mode in {"workspace", "workspace_write", "workspace-write"}:
            return Sandbox.workspace_write
        return None

    def _configured_turn_sandbox(self):
        if self._next_turn_sandbox:
            mode = self._next_turn_sandbox
            self._next_turn_sandbox = None
            return self._sdk_sandbox(mode)
        if self.sandbox_backend:
            return self._turn_sandbox()
        if not self.config.tools_enabled:
            from openai_codex import Sandbox

            return Sandbox.read_only
        return None

    def _thread_class(self):
        from openai_codex import Thread

        return Thread

    def _set_thread_from_response(self, response: Any) -> None:
        thread = getattr(response, "thread", response)
        thread_id = getattr(thread, "id", "")
        if not thread_id:
            raise RuntimeError("Codex SDK response did not include a thread id")
        self._thread = self._thread_class()(self._client, thread_id)
        model = getattr(response, "model", None)
        if model:
            self.config.model = str(model)

    @staticmethod
    def _coerce_effort(effort: str):
        normalized = effort.strip().lower().replace("-", "_")
        if normalized in {"", "default", "none"}:
            return None
        allowed = {"minimal", "low", "medium", "high", "xhigh"}
        if normalized not in allowed:
            raise ValueError(f"Unsupported Codex reasoning effort: {effort}")
        try:
            from openai_codex.types import ReasoningEffort

            return ReasoningEffort(normalized)
        except Exception:  # noqa: BLE001 - older SDKs may accept raw strings
            return normalized

    def set_model(self, model: str) -> None:
        """Set the model override used by subsequent Codex turns."""
        self.config.model = model.strip()

    def set_reasoning_effort(self, effort: str | None) -> None:
        """Set the reasoning effort override used by subsequent Codex turns."""
        coerced = None if effort is None else self._coerce_effort(effort)
        self._reasoning_effort = (
            None if coerced is None else str(getattr(coerced, "value", coerced))
        )

    def set_sandbox_backend(self, mode: str | None) -> None:
        """Set the sandbox override used by subsequent Codex turns."""
        if mode is not None and self._sdk_sandbox(mode) is None:
            raise ValueError(f"Unsupported Codex sandbox mode: {mode}")
        self.sandbox_backend = mode

    def set_next_turn_sandbox(self, mode: str) -> None:
        """Set a one-shot sandbox override for the next Codex turn."""
        if self._sdk_sandbox(mode) is None:
            raise ValueError(f"Unsupported Codex sandbox mode: {mode}")
        self._next_turn_sandbox = mode

    @property
    def reasoning_effort(self) -> str | None:
        return self._reasoning_effort

    def _turn_kwargs(self) -> dict[str, Any]:
        """Per-turn options for the SDK's public ``Thread.turn()``.

        Only kwargs ``Thread.turn()`` actually accepts (model / cwd / sandbox / …).
        ``modelProvider`` and ``developerInstructions`` are *wire* fields set once
        in ``thread_start`` — passing them to ``turn()`` raises ``TypeError``.
        "Codex owns it": an empty model and no sandbox override let ~/.codex decide.
        """
        kwargs: dict[str, Any] = {"cwd": str(self.config.working_directory)}
        if self.config.model:
            kwargs["model"] = self.config.model
        sandbox = self._configured_turn_sandbox()
        if sandbox is not None:
            kwargs["sandbox"] = sandbox
        if self._reasoning_effort:
            kwargs["effort"] = self._coerce_effort(self._reasoning_effort)
        return kwargs

    def _approval_handler(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        params = params or {}
        tool_name, arguments = self._approval_tool_request(method, params)
        if not tool_name:
            return {}
        if self._uses_default_permission_manager:
            if self._approval_callback is not None:
                return self._callback_approval_decision(tool_name, arguments)
            return {
                "decision": "reject",
                "reason": self._interactive_approval_unavailable(tool_name),
            }
        permission = self._permission_manager.check_permission(tool_name, arguments)
        if permission == Permission.ALLOW:
            return {"decision": "accept"}
        if permission == Permission.ASK and self._approval_callback is not None:
            return self._callback_approval_decision(tool_name, arguments)
        if permission == Permission.DENY:
            reason = f"SuperQode permission policy rejected {tool_name}"
        else:
            reason = self._interactive_approval_unavailable(tool_name)
        return {"decision": "reject", "reason": reason}

    def _callback_approval_decision(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            approved = bool(self._approval_callback(tool_name, arguments))
        except Exception as exc:  # noqa: BLE001
            return {
                "decision": "reject",
                "reason": f"SuperQode approval bridge failed for {tool_name}: {exc}",
            }
        if approved:
            return {"decision": "accept"}
        return {"decision": "reject", "reason": f"SuperQode user rejected {tool_name}"}

    @staticmethod
    def _interactive_approval_unavailable(tool_name: str) -> str:
        return (
            f"SuperQode codex-sdk cannot present interactive approval for {tool_name} "
            "outside the TUI; configure Codex trust/policy in ~/.codex or pass an "
            "explicit SuperQode PermissionManager to approve non-interactively"
        )

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
        with self._turn_lock:
            self.reset_cancellation()
            self._ensure_started_sync()
            turn = self._thread.turn(prompt, **self._turn_kwargs())
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
        stopped_reason = "complete" if status in {"completed", "complete", "success"} else status
        response = AgentResponse(
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
        usage = getattr(result, "usage", None)
        if usage is not None:
            response.usage = usage
        return response

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
        await asyncio.to_thread(self._turn_lock.acquire)
        try:
            self.reset_cancellation()
            await asyncio.to_thread(self._ensure_started_sync)
            yield HarnessEvent(type="model_request", data={"runtime": self.name})
            turn = await asyncio.to_thread(lambda: self._thread.turn(prompt, **self._turn_kwargs()))
            self._active_turn = turn
            stream = turn.stream()
            completed = False
            seen_agent_delta_item_ids: set[str] = set()
            queue: asyncio.Queue = asyncio.Queue()
            _start_stream_reader(stream, asyncio.get_running_loop(), queue)
            try:
                while True:
                    notification = await queue.get()
                    if notification is _STREAM_DONE:
                        break
                    if isinstance(notification, BaseException):
                        raise notification
                    for event in self._events_from_notification(
                        notification,
                        seen_agent_delta_item_ids=seen_agent_delta_item_ids,
                    ):
                        if event.type == "turn_complete":
                            completed = True
                        yield event
            finally:
                self._active_turn = None
                close = getattr(stream, "close", None)
                if close is not None:
                    close()
            if not completed:
                if self._cancelled:
                    yield HarnessEvent(type="turn_complete", data={"status": "cancelled"})
                else:
                    raise RuntimeError("Codex stream ended without turn/completed")
            yield HarnessEvent(type="model_result", data={"runtime": self.name})
        finally:
            self._turn_lock.release()

    def _events_from_notification(
        self,
        notification: Any,
        *,
        seen_agent_delta_item_ids: set[str] | None = None,
    ) -> list[HarnessEvent]:
        method = getattr(notification, "method", "")
        payload = getattr(notification, "payload", None)
        if method == "item/agentMessage/delta":
            item_id = getattr(payload, "item_id", None)
            if item_id and seen_agent_delta_item_ids is not None:
                seen_agent_delta_item_ids.add(str(item_id))
            return [HarnessEvent(type="model_delta", data={"text": getattr(payload, "delta", "")})]
        if method in {"item/commandExecution/outputDelta", "item/fileChange/outputDelta"}:
            tool_name = "patch" if method == "item/fileChange/outputDelta" else "bash"
            return [
                HarnessEvent(
                    type="tool_delta",
                    data={
                        "tool_name": tool_name,
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
        if method == "turn/plan/updated":
            return [
                HarnessEvent(
                    type="plan_update",
                    data={
                        "tool_name": "todo_write",
                        "todos": _todos_from_codex_plan(
                            _payload_value(payload, "plan", default=[])
                        ),
                        "explanation": _payload_value(payload, "explanation", default="") or "",
                        "source_event": method,
                    },
                )
            ]
        if method == "item/started":
            item = getattr(payload, "item", None)
            root = getattr(item, "root", item)
            item_type = getattr(root, "type", "")
            if item_type == "commandExecution":
                return [
                    HarnessEvent(
                        type="tool_call",
                        data={
                            "tool_name": "bash",
                            "tool_call_id": getattr(root, "id", None),
                            "arguments": {"command": _payload_value(root, "command", default="")},
                        },
                    )
                ]
            if item_type == "fileChange":
                return [
                    HarnessEvent(
                        type="tool_call",
                        data={
                            "tool_name": "patch",
                            "tool_call_id": getattr(root, "id", None),
                            "arguments": {
                                "path": _payload_value(root, "path", "file_path", "filePath")
                            },
                        },
                    )
                ]
            if item_type == "mcpToolCall":
                server = _payload_value(root, "server", default="")
                tool = _payload_value(root, "tool", default="")
                return [
                    HarnessEvent(
                        type="tool_call",
                        data={
                            "tool_name": f"mcp:{server}/{tool}",
                            "tool_call_id": getattr(root, "id", None),
                            "arguments": _payload_value(root, "arguments", "args") or {},
                        },
                    )
                ]
            if item_type == "dynamicToolCall":
                return [
                    HarnessEvent(
                        type="tool_call",
                        data={
                            "tool_name": str(_payload_value(root, "tool", default="dynamic_tool")),
                            "tool_call_id": getattr(root, "id", None),
                            "arguments": _payload_value(root, "arguments", "args") or {},
                        },
                    )
                ]
            return []
        if method == "item/completed":
            item = getattr(payload, "item", None)
            root = getattr(item, "root", item)
            item_type = getattr(root, "type", "")
            if item_type == "agentMessage":
                item_id = getattr(root, "id", None)
                if (
                    item_id
                    and seen_agent_delta_item_ids is not None
                    and str(item_id) in seen_agent_delta_item_ids
                ):
                    return []
                text = _payload_value(root, "text", default="")
                return [HarnessEvent(type="model_delta", data={"text": str(text)})] if text else []
            if item_type == "todo_list":
                return [
                    HarnessEvent(
                        type="plan_update",
                        data={
                            "tool_name": "todo_write",
                            "tool_call_id": getattr(root, "id", None),
                            "todos": _todos_from_codex_todo_items(
                                _payload_value(root, "items", default=[])
                            ),
                            "source_event": method,
                        },
                    )
                ]
            if item_type == "commandExecution":
                status = _status_value(getattr(root, "status", ""))
                output = _payload_value(
                    root,
                    "aggregated_output",
                    "aggregatedOutput",
                    "output",
                    default="",
                )
                exit_code = _payload_value(root, "exit_code", "exitCode")
                return [
                    HarnessEvent(
                        type="tool_result",
                        data={
                            "tool_name": "bash",
                            "tool_call_id": getattr(root, "id", None),
                            "command": _payload_value(root, "command", default=""),
                            "success": status == "completed" and exit_code in {None, 0},
                            "output": output or "",
                            "error": _payload_value(root, "error"),
                            "exit_code": exit_code,
                            "status": status,
                        },
                    )
                ]
            if item_type == "fileChange":
                status = _status_value(getattr(root, "status", ""))
                return [
                    HarnessEvent(
                        type="tool_result",
                        data={
                            "tool_name": "patch",
                            "tool_call_id": getattr(root, "id", None),
                            "path": _payload_value(root, "path", "file_path", "filePath"),
                            "success": status in {"applied", "completed", "success", ""},
                            "output": _payload_dict(root),
                            "status": status,
                        },
                    )
                ]
            if item_type == "mcpToolCall":
                status = _status_value(getattr(root, "status", ""))
                server = _payload_value(root, "server", default="")
                tool = _payload_value(root, "tool", default="")
                return [
                    HarnessEvent(
                        type="tool_result",
                        data={
                            "tool_name": f"mcp:{server}/{tool}",
                            "tool_call_id": getattr(root, "id", None),
                            "success": status in {"completed", "success"},
                            "output": _payload_value(root, "result"),
                            "error": _payload_value(root, "error"),
                            "status": status,
                        },
                    )
                ]
            if item_type == "dynamicToolCall":
                status = _status_value(getattr(root, "status", ""))
                success = _payload_value(root, "success")
                return [
                    HarnessEvent(
                        type="tool_result",
                        data={
                            "tool_name": str(_payload_value(root, "tool", default="dynamic_tool")),
                            "tool_call_id": getattr(root, "id", None),
                            "success": (
                                bool(success)
                                if success is not None
                                else status in {"completed", "success"}
                            ),
                            "output": _payload_value(root, "content_items", "contentItems"),
                            "status": status,
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

    def account(self, *, refresh_token: bool = False):
        self._ensure_started_sync()
        return self._client.account_read({"refreshToken": refresh_token})

    def logout(self):
        self._ensure_started_sync()
        return self._client.account_logout()

    def list_threads(self, *, limit: int = 20, archived: bool = False):
        self._ensure_started_sync()
        return self._client.thread_list(
            {
                "limit": limit,
                "archived": archived,
                "cwd": str(self.config.working_directory),
            }
        )

    def resume_thread(self, thread_id: str):
        self._ensure_started_sync()
        response = self._client.thread_resume(
            thread_id,
            {
                "cwd": str(self.config.working_directory),
                **({"model": self.config.model} if self.config.model else {}),
            },
        )
        self._set_thread_from_response(response)
        return response

    def fork_thread(self, thread_id: str):
        self._ensure_started_sync()
        response = self._client.thread_fork(
            thread_id,
            {
                "cwd": str(self.config.working_directory),
                **({"model": self.config.model} if self.config.model else {}),
            },
        )
        self._set_thread_from_response(response)
        return response

    def archive_thread(self, thread_id: str):
        self._ensure_started_sync()
        return self._client.thread_archive(thread_id)

    def rename_thread(self, name: str):
        self._ensure_started_sync()
        return self._thread.set_name(name)

    def compact_thread(self):
        self._ensure_started_sync()
        return self._thread.compact()

    def read_thread(self, *, include_turns: bool = False):
        self._ensure_started_sync()
        return self._thread.read(include_turns=include_turns)

    @property
    def thread_id(self) -> str | None:
        thread = self._thread
        return str(getattr(thread, "id", "")) if thread is not None else None

    @property
    def codex_sessions_dir(self) -> str:
        from pathlib import Path

        return str(Path.home() / ".codex" / "sessions")
