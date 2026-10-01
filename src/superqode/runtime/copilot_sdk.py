"""GitHub Copilot SDK runtime adapter.

This backend embeds the official ``github-copilot-sdk`` Python package behind
SuperQode's runtime protocol. GitHub Copilot owns the inner agent loop and
model entitlement. SuperQode supplies the terminal, HarnessSpec context,
permission bridge, normalized events, evaluation, and session controls.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from collections.abc import AsyncIterator
from enum import Enum
from typing import Any, Callable

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from ..harness.events import HarnessEvent
from ..tools.permissions import Permission, PermissionManager
from .errors import RuntimeNotInstalledError

from superqode.herdr import child_env


def _require_sdk() -> None:
    try:
        import copilot  # noqa: F401
    except ImportError as exc:
        from superqode.providers.env_introspect import active_install_command

        raise RuntimeNotInstalledError(
            "GitHub Copilot SDK runtime requires the 'copilot-sdk' extra. "
            f"Install with: {active_install_command('copilot-sdk')}, then authenticate "
            "with `copilot login` or set COPILOT_GITHUB_TOKEN."
        ) from exc


def _event_type(event: Any) -> str:
    value = getattr(event, "type", "")
    if isinstance(value, Enum):
        value = value.value
    return str(value or "").strip().lower()


def _payload_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return dict(payload)
    for method_name in ("to_dict", "model_dump"):
        method = getattr(payload, method_name, None)
        if callable(method):
            try:
                value = method()
            except Exception:  # noqa: BLE001
                continue
            if isinstance(value, dict):
                return dict(value)
    try:
        return dict(vars(payload))
    except (TypeError, AttributeError):
        return {}


def _value(data: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            pass
    return str(value)


def _normalize_tool_name(name: str) -> str:
    normalized = (name or "tool").strip().lower().replace("-", "_")
    aliases = {
        "shell": "bash",
        "run_terminal_command": "bash",
        "terminal": "bash",
        "view": "read_file",
        "read": "read_file",
        "write": "write_file",
        "edit": "edit_file",
        "apply_patch": "patch",
    }
    return aliases.get(normalized, normalized)


def _permission_details(request: Any) -> tuple[str, dict[str, Any]]:
    data = _payload_dict(request)
    kind = _text(
        _value(
            data,
            "tool_name",
            "toolName",
            "kind",
            "type",
            default=type(request).__name__,
        )
    )
    class_name = type(request).__name__.lower()
    if "shell" in class_name or "command" in class_name:
        kind = "bash"
    elif "write" in class_name:
        kind = "write_file"
    elif "read" in class_name:
        kind = "read_file"
    elif "url" in class_name or "network" in class_name:
        kind = "fetch"
    args = _value(data, "arguments", "args", "tool_args", "toolArgs", default={})
    if not isinstance(args, dict):
        args = {"value": args}
    command = _value(data, "full_command_text", "fullCommandText", "command")
    if command:
        kind = "bash"
    if command and "command" not in args:
        args["command"] = command
    return _normalize_tool_name(kind), dict(args)


def _explicit_github_token() -> str:
    """Return the token the user deliberately pointed at Copilot, if any.

    Only ``COPILOT_GITHUB_TOKEN`` counts. ``GH_TOKEN``/``GITHUB_TOKEN`` are set
    by the ``gh`` CLI, CI, and most enterprise git setups, and are usually PATs
    with no Copilot entitlement. Passing one makes the SDK start the CLI with
    ``--no-auto-login``, so it ignores a perfectly good ``copilot login`` and
    then stalls on an account that cannot answer - the exact failure Copilot
    Business users hit.
    """
    return (os.environ.get("COPILOT_GITHUB_TOKEN") or "").strip()


def _permission_decision(allowed: bool, reason: str = "") -> Any:
    # This public namespace exposes the generated union variants accepted by
    # the SDK permission handler.
    if allowed:
        from copilot.rpc import PermissionDecisionApproveOnce

        return PermissionDecisionApproveOnce()
    from copilot.rpc import PermissionDecisionReject

    return PermissionDecisionReject(feedback=reason or "Rejected by SuperQode policy")


_DEFAULT_TURN_TIMEOUT = 600.0
_DEFAULT_STARTUP_TIMEOUT = 60.0


def _turn_timeout() -> float:
    """Seconds to wait for a turn to go idle, from SUPERQODE_COPILOT_TIMEOUT."""
    try:
        timeout = float(os.environ.get("SUPERQODE_COPILOT_TIMEOUT", "") or _DEFAULT_TURN_TIMEOUT)
    except ValueError:
        return _DEFAULT_TURN_TIMEOUT
    return timeout if timeout > 0 else _DEFAULT_TURN_TIMEOUT


def _startup_timeout() -> float:
    """Seconds allowed for runtime resolution, authentication, and session start."""
    try:
        timeout = float(
            os.environ.get("SUPERQODE_COPILOT_STARTUP_TIMEOUT", "") or _DEFAULT_STARTUP_TIMEOUT
        )
    except ValueError:
        return _DEFAULT_STARTUP_TIMEOUT
    return timeout if timeout > 0 else _DEFAULT_STARTUP_TIMEOUT


def _startup_error(exc: BaseException) -> str:
    """Explain a failed client start in terms the user can act on."""
    if isinstance(exc, TimeoutError):
        detail = (
            f"startup exceeded {_startup_timeout():g}s "
            "(set SUPERQODE_COPILOT_STARTUP_TIMEOUT to change the limit)"
        )
    else:
        detail = str(exc).strip() or type(exc).__name__
    hint = (
        "Check `copilot login` (or `:copilot status`). If the Copilot CLI download "
        "is blocked on your network, set COPILOT_CLI_PATH to an installed "
        "`copilot` binary, or use the CLI route with `:copilot cli`."
    )
    return f"Could not start the GitHub Copilot runtime: {detail}. {hint}"


def _turn_error(exc: BaseException, timeout: float) -> str:
    """Explain a failed turn, separating a timeout from a session error."""
    if isinstance(exc, TimeoutError):
        return (
            f"GitHub Copilot did not finish within {timeout:g}s. Raise "
            "SUPERQODE_COPILOT_TIMEOUT if your turns legitimately run longer."
        )
    return str(exc).strip() or f"Copilot turn failed: {type(exc).__name__}"


_TURN_DONE = object()


class CopilotSDKRuntime:
    """Official GitHub Copilot SDK runtime using a Copilot licence or BYOK."""

    name = "copilot-sdk"
    harness_owner = "github-copilot"

    def __init__(
        self,
        *,
        config: AgentConfig | None = None,
        permission_manager: PermissionManager | None = None,
        approval_callback: Callable[[str, dict[str, Any]], bool] | None = None,
        **_unused: Any,
    ) -> None:
        _require_sdk()
        if config is None:
            raise ValueError("CopilotSDKRuntime requires 'config'")
        self.config = config
        self.session_id = config.session_id or f"copilot-{uuid.uuid4().hex[:12]}"
        self._permission_manager = permission_manager or PermissionManager()
        self._uses_default_permission_manager = permission_manager is None
        self._approval_callback = approval_callback
        self._client: Any = None
        self._session: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cancelled = False
        self._pending_model: str | None = None
        self._resume_session_id: str | None = None
        self._turn_lock = asyncio.Lock()
        self._last_usage: dict[str, Any] = {}
        self._active_model = config.model or ""
        self._tool_names: dict[str, str] = {}

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": self.name,
            "harness_owner": self.harness_owner,
            "authentication": "github-copilot",
            "session_id": self.thread_id,
            "model": self._active_model,
            "structured_events": True,
        }

    @property
    def thread_id(self) -> str | None:
        return (
            str(getattr(self._session, "session_id", "") or self._resume_session_id or "") or None
        )

    @property
    def active_model(self) -> str:
        return self._active_model

    @property
    def needs_start(self) -> bool:
        """The next turn has to build the client (and maybe download the CLI)."""
        return self._client is None

    async def _ensure_started(self) -> None:
        if self._client is None:
            from copilot import CopilotClient, RuntimeConnection

            kwargs: dict[str, Any] = {
                "working_directory": str(self.config.working_directory),
            }
            # The official CLI treats GH_TOKEN/GITHUB_TOKEN as higher priority
            # than its OAuth login store. They are commonly unrelated git/CI
            # tokens, so do not let them silently replace a working subscription
            # login on the SDK route. Headless callers have the unambiguous
            # COPILOT_GITHUB_TOKEN escape hatch below.
            from superqode.providers.subscription_env import subscription_child_env

            process_env, _ = subscription_child_env("copilot", child_env())
            process_env.pop("GH_TOKEN", None)
            process_env.pop("GITHUB_TOKEN", None)
            kwargs["env"] = process_env
            # Reuse the user's installed and authenticated official CLI when it
            # exists. This avoids the SDK's first-use runtime download and keeps
            # both SuperQode routes on the same `copilot login` state.
            cli_path = shutil.which("copilot")
            if cli_path:
                kwargs["connection"] = RuntimeConnection.for_stdio(path=cli_path)
            token = _explicit_github_token()
            if token:
                kwargs["github_token"] = token
            self._loop = asyncio.get_running_loop()
            # CopilotClient.__init__ resolves the Copilot CLI and downloads it on
            # first use through a *blocking* urlopen (120s timeout, three tries,
            # sleeping between them). Constructing it inline froze the whole TUI
            # for the length of the download - seconds on a fast link, minutes
            # behind a corporate proxy - so build the client off the event loop.
            self._client = await asyncio.to_thread(CopilotClient, **kwargs)
            await self._client.start()
        if self._session is not None:
            return

        session_kwargs: dict[str, Any] = {
            "on_permission_request": self._approval_handler,
            "streaming": True,
            "working_directory": str(self.config.working_directory),
            "enable_config_discovery": True,
            "session_id": self._resume_session_id or self.session_id,
        }
        if self.config.model:
            session_kwargs["model"] = self.config.model
        if self.config.reasoning_effort:
            session_kwargs["reasoning_effort"] = self.config.reasoning_effort
        if self.config.custom_system_prompt:
            session_kwargs["system_message"] = {
                "mode": "append",
                "content": self.config.custom_system_prompt,
            }

        if self._resume_session_id:
            resume = getattr(self._client, "resume_session", None)
            if resume is None:
                raise RuntimeError("Installed Copilot SDK does not support session resume")
            resume_kwargs = dict(session_kwargs)
            resume_kwargs.pop("session_id", None)
            self._session = await resume(self._resume_session_id, **resume_kwargs)
        else:
            self._session = await self._client.create_session(**session_kwargs)
        self.session_id = str(getattr(self._session, "session_id", self.session_id))

    async def _ensure_started_with_timeout(self) -> None:
        """Start the SDK runtime without ever leaving the caller waiting forever."""
        try:
            await asyncio.wait_for(self._ensure_started(), timeout=_startup_timeout())
        except BaseException:
            # A client whose start/session handshake was cancelled is not safe
            # to reuse. Drop it so a retry starts from a clean lifecycle.
            client = self._client
            self._session = None
            self._client = None
            if client is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(client.stop()), timeout=2.0)
                except BaseException:  # noqa: BLE001 - bounded best-effort cleanup
                    pass
            raise

    async def _apply_pending(self) -> None:
        if self._pending_model is None or self._session is None:
            return
        selected = self._pending_model
        self._pending_model = None
        if not selected:
            return
        await self._session.set_model(selected)
        self._active_model = selected

    async def _approval_handler(self, request: Any, _invocation: Any = None) -> Any:
        tool_name, args = _permission_details(request)
        # The SDK awaits this handler on the event loop, and SuperQode's TUI
        # bridge blocks on a threading.Event until the user answers the prompt.
        # Deciding inline therefore deadlocked the loop: the approval card could
        # never render and the keypress could never be read, so every request
        # sat frozen until the 60s bridge timeout auto-denied it. Decide in a
        # worker thread, exactly as the Claude Agent SDK runtime does.
        allowed, reason = await asyncio.to_thread(self._decide_permission, tool_name, args)
        return _permission_decision(allowed, reason)

    def _decide_permission(self, tool_name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """Resolve one permission request. Blocking; never call on the loop."""
        if self._uses_default_permission_manager and self._approval_callback is not None:
            return self._safe_callback(tool_name, args)

        permission = self._permission_manager.check_permission(tool_name, args)
        if permission == Permission.ALLOW:
            return True, ""
        if permission == Permission.ASK and self._approval_callback is not None:
            return self._safe_callback(tool_name, args)
        reason = (
            f"SuperQode permission policy rejected {tool_name}"
            if permission == Permission.DENY
            else f"SuperQode could not obtain interactive approval for {tool_name}"
        )
        return False, reason

    def _safe_callback(self, tool_name: str, args: dict[str, Any]) -> tuple[bool, str]:
        try:
            allowed = bool(self._approval_callback(tool_name, args))
        except Exception as exc:  # noqa: BLE001
            return False, f"SuperQode approval bridge failed for {tool_name}: {exc}"
        return allowed, "" if allowed else f"SuperQode user rejected {tool_name}"

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        async with self._turn_lock:
            self.reset_cancellation()
            if self.needs_start:
                # Explain the path before startup so a slow handshake reads as
                # work rather than a frozen app.
                startup_text = (
                    "Starting the GitHub Copilot runtime with the installed Copilot CLI…"
                    if shutil.which("copilot")
                    else (
                        "Starting the GitHub Copilot runtime "
                        "(the first run may fetch its pinned CLI)…"
                    )
                )
                yield HarnessEvent(
                    type="thinking",
                    data={"text": startup_text},
                )
            timeout = _turn_timeout()
            try:
                await self._ensure_started_with_timeout()
                await self._apply_pending()
            except Exception as exc:  # noqa: BLE001 - a failed start is a failed turn
                yield HarnessEvent(
                    type="turn_complete",
                    data={"status": "error", "error": _startup_error(exc), "usage": {}},
                )
                yield HarnessEvent(
                    type="model_result",
                    data={"runtime": self.name, "model": self._active_model},
                )
                return
            queue: asyncio.Queue[Any] = asyncio.Queue()
            saw_delta = False
            error_message = ""
            turn_error: BaseException | None = None

            def on_event(event: Any) -> None:
                loop = self._loop
                if loop is not None:
                    loop.call_soon_threadsafe(queue.put_nowait, event)
                else:
                    queue.put_nowait(event)

            unsubscribe = self._session.on(on_event)

            async def send_turn() -> None:
                nonlocal turn_error
                try:
                    await asyncio.wait_for(
                        self._session.send_and_wait(prompt, timeout=timeout),
                        timeout=timeout,
                    )
                except asyncio.CancelledError:
                    raise
                except BaseException as exc:  # noqa: BLE001 - reported as turn_complete
                    turn_error = exc
                finally:
                    loop = self._loop
                    if loop is not None:
                        loop.call_soon_threadsafe(queue.put_nowait, _TURN_DONE)
                    else:
                        queue.put_nowait(_TURN_DONE)

            yield HarnessEvent(
                type="model_request",
                data={"runtime": self.name, "model": self._active_model},
            )
            task = asyncio.create_task(send_turn())
            try:
                while True:
                    item = await queue.get()
                    if item is _TURN_DONE:
                        break
                    kind = _event_type(item)
                    data = _payload_dict(getattr(item, "data", None))
                    if kind == "assistant.message_delta":
                        text = _text(_value(data, "delta_content", "deltaContent", "content"))
                        if text:
                            saw_delta = True
                            yield HarnessEvent(type="model_delta", data={"text": text})
                    elif kind == "assistant.message" and not saw_delta:
                        text = _text(_value(data, "content", "text"))
                        if text:
                            yield HarnessEvent(type="model_delta", data={"text": text})
                    elif kind in {"assistant.reasoning_delta", "assistant.reasoning"}:
                        text = _text(
                            _value(data, "delta_content", "deltaContent", "content", "text")
                        )
                        if text:
                            yield HarnessEvent(type="thinking", data={"text": text})
                    elif kind == "tool.execution_start":
                        tool_data = self._tool_start_data(data)
                        tool_call_id = _text(tool_data.get("tool_call_id"))
                        if tool_call_id:
                            self._tool_names[tool_call_id] = str(tool_data["tool_name"])
                        yield HarnessEvent(type="tool_call", data=tool_data)
                    elif kind in {"tool.execution_partial_result", "tool.execution_progress"}:
                        text = _text(_value(data, "content", "output", "result", "progress"))
                        if text:
                            yield HarnessEvent(
                                type="tool_delta",
                                data={
                                    "tool_name": _text(
                                        _value(data, "tool_name", "toolName", default="tool")
                                    ),
                                    "tool_call_id": _value(
                                        data, "tool_call_id", "toolCallId", "id"
                                    ),
                                    "text": text,
                                },
                            )
                    elif kind == "tool.execution_complete":
                        yield HarnessEvent(
                            type="tool_result",
                            data=self._tool_result_data(data, self._tool_names),
                        )
                    elif kind in {"assistant.usage", "session.usage_checkpoint"}:
                        self._last_usage = data
                    elif kind == "session.model_change":
                        model = _text(_value(data, "model_id", "modelId", "model"))
                        if model:
                            self._active_model = model
                    elif kind == "session.todos_changed":
                        todos = _value(data, "todos", "items", default=[])
                        if isinstance(todos, list):
                            yield HarnessEvent(
                                type="plan_update",
                                data={"todos": todos, "source_event": kind},
                            )
                    elif kind in {"session.error", "model.call_failure"}:
                        error_message = _text(
                            _value(
                                data, "message", "error", "reason", default="Copilot turn failed"
                            )
                        )
                await task
            finally:
                unsubscribe()
                if not task.done():
                    task.cancel()

            if turn_error is not None and not error_message:
                error_message = _turn_error(turn_error, timeout)
            status = "cancelled" if self._cancelled else "error" if error_message else "completed"
            yield HarnessEvent(
                type="turn_complete",
                data={"status": status, "error": error_message or None, "usage": self._last_usage},
            )
            yield HarnessEvent(
                type="model_result",
                data={"runtime": self.name, "model": self._active_model},
            )

    @staticmethod
    def _tool_start_data(data: dict[str, Any]) -> dict[str, Any]:
        name = _text(_value(data, "tool_name", "toolName", "name", default="tool"))
        args = _value(data, "arguments", "args", "tool_args", "toolArgs", default={})
        return {
            "tool_name": _normalize_tool_name(name),
            "tool_call_id": _value(data, "tool_call_id", "toolCallId", "id"),
            "args": dict(args) if isinstance(args, dict) else {"value": args},
        }

    @staticmethod
    def _tool_result_data(
        data: dict[str, Any], tool_names: dict[str, str] | None = None
    ) -> dict[str, Any]:
        tool_call_id = _text(_value(data, "tool_call_id", "toolCallId", "id"))
        description = _payload_dict(_value(data, "tool_description", "toolDescription"))
        name = _text(_value(data, "tool_name", "toolName", "name"))
        if not name:
            name = _text(_value(description, "name"))
        if not name and tool_names is not None:
            name = tool_names.pop(tool_call_id, "")
        result = _payload_dict(_value(data, "result"))
        error = _value(data, "error", "failure", "error_message", "errorMessage")
        error_data = _payload_dict(error)
        success_value = _value(data, "success", default=None)
        success = bool(success_value) if success_value is not None else not bool(error)
        return {
            "tool_name": _normalize_tool_name(name or "tool"),
            "tool_call_id": tool_call_id or None,
            "success": success,
            "output": _text(
                _value(
                    result,
                    "content",
                    "detailed_content",
                    "detailedContent",
                    default=_value(data, "content", "output", default=""),
                )
            ),
            "error": (
                _text(_value(error_data, "message", default=error)) if error is not None else None
            ),
        }

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta" and event.data.get("text"):
                yield str(event.data["text"])

    async def run(self, prompt: str) -> AgentResponse:
        chunks: list[str] = []
        tool_calls = 0
        stopped_reason = "complete"
        error: str | None = None
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta" and event.data.get("text"):
                chunks.append(str(event.data["text"]))
            elif event.type == "tool_call":
                tool_calls += 1
            elif event.type == "turn_complete":
                status = str(event.data.get("status") or "completed")
                if status not in {"complete", "completed", "success"}:
                    stopped_reason = status
                if event.data.get("error"):
                    error = str(event.data["error"])
        content = "".join(chunks)
        return AgentResponse(
            content=content,
            messages=[
                AgentMessage(role="user", content=prompt),
                AgentMessage(role="assistant", content=content),
            ],
            tool_calls_made=tool_calls,
            iterations=1,
            stopped_reason=stopped_reason,
            error=error,
        )

    def set_model(self, model: str) -> None:
        selected = (model or "").strip()
        self.config.model = selected
        self._active_model = selected
        self._pending_model = selected

    async def models(self) -> list[dict[str, Any]]:
        await self._ensure_started_with_timeout()
        models = await self._client.list_models()
        result: list[dict[str, Any]] = []
        for item in models or []:
            data = _payload_dict(item)
            model_id = _text(_value(data, "id", "model_id", "modelId"))
            if not model_id:
                continue
            result.append(
                {
                    "id": model_id,
                    "name": _text(_value(data, "name", "display_name", "displayName")) or model_id,
                    "supports_reasoning_effort": bool(
                        _value(
                            data,
                            "supports_reasoning_effort",
                            "supportsReasoningEffort",
                            default=False,
                        )
                    ),
                }
            )
        return result

    async def list_threads(self) -> list[Any]:
        await self._ensure_started_with_timeout()
        method = getattr(self._client, "list_sessions", None)
        if method is None:
            return []
        return list(await method())

    async def resume_thread(self, session_id: str) -> None:
        selected = (session_id or "").strip()
        if not selected:
            raise ValueError("Copilot session id is required")
        if self._session is not None:
            await self._session.disconnect()
            self._session = None
        self._resume_session_id = selected
        self.session_id = selected
        await self._ensure_started_with_timeout()

    def cancel(self) -> None:
        self._cancelled = True
        session, loop = self._session, self._loop
        if session is not None and loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(session.abort(), loop)
            except Exception:  # noqa: BLE001
                pass

    def reset_cancellation(self) -> None:
        self._cancelled = False

    async def aclose(self) -> None:
        session, self._session = self._session, None
        client, self._client = self._client, None
        if session is not None:
            try:
                await session.disconnect()
            except Exception:  # noqa: BLE001
                pass
        if client is not None:
            await client.stop()


__all__ = ["CopilotSDKRuntime"]
