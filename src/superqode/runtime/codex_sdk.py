"""OpenAI Codex Python SDK runtime adapter.

This backend drives the official ``openai-codex`` Python SDK while preserving
SuperQode's ``AgentRuntime`` shape. It is intentionally Codex-specific: the
native builtin runtime remains the portable SuperQode harness path.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import threading
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
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


_CODEX_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_FORWARD_COMPATIBILITY_LOCK = threading.Lock()


def _codex_binary_version(binary: str) -> tuple[int, int, int] | None:
    """Return a Codex CLI's numeric version without invoking a shell."""

    try:
        completed = subprocess.run(
            [binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _CODEX_VERSION_RE.search(f"{completed.stdout}\n{completed.stderr}")
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def _bundled_codex_binary() -> str | None:
    """Locate the app-server shipped with the optional Python SDK."""

    try:
        from codex_cli_bin import bundled_codex_path

        return str(bundled_codex_path())
    except (ImportError, OSError):
        return None


def _newer_local_codex_binary() -> tuple[str, str] | None:
    """Return a newer standalone Codex CLI, if the user has one installed.

    The Python SDK deliberately uses its packaged app-server by default.  That
    is normally the safest choice, but it means an updated local Codex CLI can
    expose a newer subscription model catalogue than the packaged binary.  Use
    the local binary only when it is demonstrably newer than the package's
    binary; otherwise retain the SDK default.
    """

    local = shutil.which("codex")
    if not local:
        return None
    bundled = _bundled_codex_binary()
    if bundled:
        try:
            if local == bundled or Path(local).resolve() == Path(bundled).resolve():
                return None
        except OSError:
            pass

    local_version = _codex_binary_version(local)
    if local_version is None:
        return None
    bundled_version = _codex_binary_version(bundled) if bundled else None
    if bundled_version is not None and local_version <= bundled_version:
        return None
    return (local, ".".join(str(part) for part in local_version))


def _enable_forward_compatible_reasoning_efforts() -> None:
    """Let an older generated SDK preserve newly-added Codex effort values.

    The app-server protocol returns the supported efforts with each model.  A
    newer local Codex CLI can add values such as ``max`` and ``ultra`` before
    the Python SDK republishes its generated enum.  Pydantic delegates enum
    conversion to ``Enum(value)``, so a small ``_missing_`` handler preserves
    those string values instead of rejecting the whole model response.

    This is intentionally limited to reasoning effort, an open string-like
    capability advertised by the server, rather than weakening validation for
    unrelated protocol fields.
    """

    try:
        from openai_codex.types import ReasoningEffort
    except (ImportError, AttributeError):
        return
    if getattr(ReasoningEffort, "_superqode_forward_compatible", False):
        return

    def _missing(cls, value):
        if not isinstance(value, str) or not value:
            return None
        with _FORWARD_COMPATIBILITY_LOCK:
            existing = cls._value2member_map_.get(value)
            if existing is not None:
                return existing
            try:
                member = str.__new__(cls, value) if issubclass(cls, str) else object.__new__(cls)
            except TypeError:
                return None
            member._name_ = re.sub(r"\W+", "_", value).upper()
            member._value_ = value
            cls._value2member_map_[value] = member
            return member

    ReasoningEffort._missing_ = classmethod(_missing)
    ReasoningEffort._superqode_forward_compatible = True


def _codex_effort_compatibility_overrides(exc: BaseException) -> tuple[str, ...]:
    """Return a child-process override for newer global reasoning settings.

    When no newer standalone Codex CLI is available, the published Python SDK
    bundles a pinned app-server. A newer Codex CLI may have written
    ``model_reasoning_effort = "ultra"`` before that bundled server understands
    it. Launch the fallback server with its closest supported setting instead
    of mutating the user's global config.
    """

    message = str(exc).lower()
    if "failed to load configuration" not in message or "config.toml" not in message:
        return ()
    if "unknown variant" not in message or "expected one of" not in message:
        return ()
    return ('model_reasoning_effort="xhigh"',)


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
        self._active_model = ""
        self._app_server_source = "SDK-bundled Codex app-server"
        self._local_codex_binary_checked = False
        self._local_codex_binary: tuple[str, str] | None = None
        # Set only when a global Codex effort needs a compatible, per-process
        # override for the SDK's bundled fallback app-server.
        self._app_server_config_overrides: tuple[str, ...] = ()
        self._start_lock = threading.Lock()
        self._turn_lock = threading.Lock()

    @staticmethod
    def _default_permission_manager(config: AgentConfig) -> PermissionManager:
        return PermissionManager()

    @property
    def metadata(self):
        self._ensure_started_sync()
        return self._init

    def _preferred_local_codex_binary(self) -> tuple[str, str] | None:
        """Cache whether a newer standalone Codex CLI is available to this runtime."""

        if not self._local_codex_binary_checked:
            self._local_codex_binary_checked = True
            self._local_codex_binary = _newer_local_codex_binary()
        return self._local_codex_binary

    @staticmethod
    def _sdk_config_supports_codex_bin(CodexConfig) -> bool:
        """Avoid probing the host CLI for older/test SDK config shims."""

        fields = getattr(CodexConfig, "__dataclass_fields__", None)
        return fields is None or "codex_bin" in fields

    def _sdk_config(
        self,
        CodexConfig,
        *,
        config_overrides: tuple[str, ...] = (),
        prefer_local: bool = True,
    ) -> tuple[Any, str]:
        """Build the SDK launch config and identify the app-server it will use.

        A newer standalone CLI is both the source of truth for a Codex
        subscription's currently-enabled models and capable of running those
        models.  The SDK's bundled binary remains a safe fallback for machines
        without a newer local CLI or if the local process cannot start.
        """

        kwargs: dict[str, Any] = {
            "cwd": str(self.config.working_directory),
            "client_name": "superqode_codex_sdk",
            "client_title": "SuperQode Codex SDK Runtime",
            "client_version": self._sdk_client_version(),
        }
        if config_overrides:
            kwargs["config_overrides"] = config_overrides
        prefer_local_setting = os.getenv("SUPERQODE_CODEX_PREFER_LOCAL_CLI", "1").strip().lower()
        local_enabled = prefer_local_setting not in {"0", "false", "no", "off"}
        if prefer_local and local_enabled and self._sdk_config_supports_codex_bin(CodexConfig):
            local = self._preferred_local_codex_binary()
            if local is not None:
                binary, version = local
                try:
                    return (
                        CodexConfig(**kwargs, codex_bin=binary),
                        f"local Codex CLI {version}",
                    )
                except TypeError:
                    # A future SDK may expose a non-dataclass config without
                    # a ``codex_bin`` argument. Fall back to its default.
                    pass
        return CodexConfig(**kwargs), "SDK-bundled Codex app-server"

    def _restart_with_bundled_app_server(self, operation: str, error: BaseException) -> None:
        """Replace an incompatible local app-server after a safe metadata operation.

        Model/account reads have no filesystem side effects, so retrying them
        against the SDK-pinned server is safe. Agent turns are deliberately not
        replayed because a failed decode may occur after tools have executed.
        """
        if not self._app_server_source.startswith("local Codex CLI "):
            raise error

        from openai_codex import CodexConfig, Thread
        from openai_codex.client import CodexClient

        old_client, self._client = self._client, None
        self._thread = None
        if old_client is not None:
            try:
                old_client.close()
            except Exception:  # noqa: BLE001 - continue with the safe fallback
                pass

        config, source = self._sdk_config(CodexConfig, prefer_local=False)
        overrides: tuple[str, ...] = ()
        try:
            client, init, started = self._start_sdk_client(
                CodexClient, config, self._thread_start_params()
            )
        except Exception as bundled_error:
            overrides = _codex_effort_compatibility_overrides(bundled_error)
            if not overrides:
                raise RuntimeError(
                    f"{operation} failed with {self._app_server_source}: {error}; "
                    f"bundled Codex fallback also failed: {bundled_error}"
                ) from bundled_error
            compatible, source = self._sdk_config(
                CodexConfig,
                config_overrides=overrides,
                prefer_local=False,
            )
            client, init, started = self._start_sdk_client(
                CodexClient, compatible, self._thread_start_params()
            )

        self._app_server_config_overrides = overrides
        self._app_server_source = source
        self._init = init
        self._client = client
        self._thread = Thread(client, started.thread.id)
        self._active_model = str(getattr(started, "model", None) or self.config.model or "")

    @staticmethod
    def _sdk_client_version() -> str:
        # Identify SuperQode as the originating client (+ version) so Codex
        # usage from SuperQode is attributable — lets us track adoption and
        # which SuperQode version drove the session.
        try:
            from .. import __version__ as sq_version
        except Exception:  # noqa: BLE001
            sq_version = "0"
        return str(sq_version)

    def _thread_start_params(self) -> dict[str, Any]:
        # "Codex owns it": defer to the machine's ~/.codex configuration
        # (model, approval policy, sandbox, MCP, project trust). Only send what
        # the caller explicitly set, so an empty model/sandbox lets the local
        # Codex config decide. SuperQode imposes nothing extra.
        params: dict[str, Any] = {"cwd": str(self.config.working_directory)}
        if self.config.model:
            params["model"] = self.config.model
        if self.config.provider and self.config.provider != "openai":
            params["modelProvider"] = self.config.provider
        if self.config.custom_system_prompt:
            params["developerInstructions"] = self.config.custom_system_prompt
        if self.sandbox_backend:  # explicit override only; else use ~/.codex
            params["sandbox"] = self._thread_sandbox_mode()
        return params

    def _start_sdk_client(self, CodexClient, sdk_config, thread_params: dict[str, Any]):
        """Start, initialize, and create a thread, closing a failed client."""

        client = CodexClient(config=sdk_config, approval_handler=self._approval_handler)
        try:
            client.start()
            init = client.initialize()
            started = client.thread_start(thread_params)
        except Exception:
            client.close()
            raise
        return client, init, started

    def _ensure_started_sync(self) -> None:
        if self._client is not None and self._thread is not None:
            return
        with self._start_lock:
            if self._client is not None and self._thread is not None:
                return
            from openai_codex import CodexConfig, Thread
            from openai_codex.client import CodexClient

            _enable_forward_compatible_reasoning_efforts()
            thread_params = self._thread_start_params()
            primary_config, primary_source = self._sdk_config(CodexConfig)
            try:
                client, init, started = self._start_sdk_client(
                    CodexClient,
                    primary_config,
                    thread_params,
                )
                source = primary_source
                overrides: tuple[str, ...] = ()
            except Exception as primary_error:
                if primary_source.startswith("local Codex CLI "):
                    # A newer standalone CLI is preferred for its live model
                    # catalogue. If it cannot start, preserve the previous
                    # bundled-SDK behavior rather than leaving the runtime
                    # unusable solely because a PATH entry is unhealthy.
                    bundled_config, bundled_source = self._sdk_config(
                        CodexConfig, prefer_local=False
                    )
                    try:
                        client, init, started = self._start_sdk_client(
                            CodexClient,
                            bundled_config,
                            thread_params,
                        )
                        source = bundled_source
                        overrides = ()
                    except Exception as bundled_error:
                        overrides = _codex_effort_compatibility_overrides(bundled_error)
                        if not overrides:
                            raise RuntimeError(
                                f"{primary_source} failed: {primary_error}; "
                                f"bundled Codex app-server fallback failed: {bundled_error}"
                            ) from bundled_error
                        try:
                            compatible_config, source = self._sdk_config(
                                CodexConfig,
                                config_overrides=overrides,
                                prefer_local=False,
                            )
                            client, init, started = self._start_sdk_client(
                                CodexClient,
                                compatible_config,
                                thread_params,
                            )
                        except Exception as compatibility_error:
                            raise RuntimeError(
                                f"{primary_source} failed: {primary_error}; "
                                f"bundled Codex app-server failed: {bundled_error}; "
                                f"compatibility effort override also failed: {compatibility_error}"
                            ) from compatibility_error
                else:
                    overrides = _codex_effort_compatibility_overrides(primary_error)
                    if not overrides:
                        raise
                    try:
                        compatible_config, source = self._sdk_config(
                            CodexConfig,
                            config_overrides=overrides,
                            prefer_local=False,
                        )
                        client, init, started = self._start_sdk_client(
                            CodexClient,
                            compatible_config,
                            thread_params,
                        )
                    except Exception as compatibility_error:
                        raise RuntimeError(
                            f"Bundled Codex app-server failed: {primary_error}; "
                            f"compatibility effort override also failed: {compatibility_error}"
                        ) from compatibility_error
            self._app_server_config_overrides = overrides
            self._app_server_source = source
            self._init = init
            self._client = client
            self._thread = Thread(client, started.thread.id)
            self._active_model = str(getattr(started, "model", None) or self.config.model or "")

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
            self._active_model = str(model)

    def _coerce_effort(self, effort: str):
        normalized = effort.strip().lower().replace("-", "_")
        if normalized in {"", "default"}:
            return None
        allowed = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
        if normalized not in allowed:
            raise ValueError(f"Unsupported Codex reasoning effort: {effort}")
        if normalized in {"max", "ultra"} and self._preferred_local_codex_binary() is None:
            raise ValueError(
                f"Codex reasoning effort '{effort}' requires a newer local Codex CLI; "
                "update Codex or choose xhigh."
            )
        try:
            _enable_forward_compatible_reasoning_efforts()
            from openai_codex.types import ReasoningEffort

            return ReasoningEffort(normalized)
        except Exception:  # noqa: BLE001 - older SDKs may accept raw strings
            return normalized

    def set_model(self, model: str) -> None:
        """Set the model override used by subsequent Codex turns."""
        self.config.model = model.strip()
        self._active_model = self.config.model

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

    @property
    def active_model(self) -> str:
        """The model resolved by the live Codex thread, not a stale list default."""

        self._ensure_started_sync()
        return self._active_model

    @property
    def app_server_source(self) -> str:
        """Human-readable source of the app-server backing this runtime."""

        self._ensure_started_sync()
        return self._app_server_source

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
            turn_error = ""
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
                            status = str(event.data.get("status") or "")
                            message = str(event.data.get("error") or "")
                            if message or status in {"failed", "error", "errored"}:
                                turn_error = message or f"turn status: {status}"
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
            elif turn_error and not self._cancelled:
                # Surface the provider's reason (usage limits, auth, model
                # eligibility) instead of ending as a silent empty response.
                raise RuntimeError(f"Codex turn failed: {turn_error}")
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
            # A failed turn carries its reason here (e.g. a usage-limit
            # rejection). Dropping it made the TUI show a bare "no response".
            error = getattr(turn, "error", None)
            error_message = ""
            if error is not None:
                error_message = str(
                    getattr(error, "message", None) or getattr(error, "detail", None) or error
                ).strip()
            return [
                HarnessEvent(
                    type="turn_complete",
                    data={
                        "status": _status_value(getattr(turn, "status", "")),
                        "error": error_message,
                    },
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
        try:
            return self._client.model_list(include_hidden=include_hidden)
        except Exception as error:
            self._restart_with_bundled_app_server("Codex model listing", error)
            return self._client.model_list(include_hidden=include_hidden)

    def account(self, *, refresh_token: bool = False):
        self._ensure_started_sync()
        try:
            return self._client.account_read({"refreshToken": refresh_token})
        except Exception as error:
            self._restart_with_bundled_app_server("Codex account read", error)
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
