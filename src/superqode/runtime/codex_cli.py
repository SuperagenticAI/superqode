"""Codex harness driven directly through the user's installed CLI."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from superqode.agent.loop import AgentConfig, AgentMessage, AgentResponse
from superqode.harness.events import HarnessEvent
from superqode.herdr import child_env
from superqode.tools.permissions import Permission

from .codex_events import CodexEvents
from .codex_transport import CodexTransport
from .errors import RuntimeNotInstalledError


def codex_binary(explicit: str | None = None) -> str | None:
    """An explicit selection never falls back to another executable."""
    selected = explicit or os.getenv("SUPERQODE_CODEX_BIN") or "codex"
    return shutil.which(selected)


class CodexCLIRuntime:
    name = "codex-cli"

    def __init__(
        self,
        *,
        config: AgentConfig | None = None,
        permission_manager=None,
        approval_callback=None,
        sandbox_backend=None,
        billing_requested="agent-managed",
        codex_bin: str | None = None,
        request_timeout: float = 60,
        **_unused,
    ):
        if config is None:
            raise ValueError("CodexCLIRuntime requires 'config'")
        self.binary = codex_binary(codex_bin)
        if self.binary is None:
            raise RuntimeNotInstalledError(
                "Install Codex CLI, then run `codex login`. Set SUPERQODE_CODEX_BIN to select its path."
            )
        self.config = config
        self.billing_requested = billing_requested
        self.sandbox_backend = sandbox_backend
        self.session_id = config.session_id or f"codex-{uuid.uuid4().hex[:8]}"
        self.subscription_status = {"auth_method": "unknown", "billing_verified": "unknown"}
        self.rate_limits: dict[str, Any] = {}
        self.token_usage: dict[str, Any] = {}
        self.timings: dict[str, float] = {}
        self.metadata: dict[str, Any] = {}
        self._permission_manager = permission_manager
        self._approval_callback = approval_callback
        self._request_timeout = request_timeout
        self._transport: CodexTransport | None = None
        self._start_lock = asyncio.Lock()
        self._thread_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self._interaction_lock = asyncio.Lock()
        self._thread_id: str | None = None
        self._active_turn: str | None = None
        self._active_model = ""
        self._reasoning_effort: str | None = config.reasoning_effort
        self._collaboration_mode: str | None = None
        self._approval_policy: str | None = None
        self._login_id: str | None = None
        self.login_status: dict[str, Any] = {}
        self._next_turn_sandbox: str | None = None
        self._review: dict[str, Any] | None = None
        self._queue: asyncio.Queue | None = None
        self._failure: BaseException | None = None
        self._cancelled = False
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._control_tasks: set[asyncio.Task] = set()

    @property
    def model(self):
        return self.config.model

    @property
    def active_model(self):
        return self._active_model

    @property
    def reasoning_effort(self):
        return self._reasoning_effort

    @property
    def app_server_source(self):
        version = (self.metadata.get("serverInfo") or {}).get("version") or self.metadata.get(
            "userAgent", ""
        )
        return f"installed Codex CLI: {self.binary}" + (f" ({version})" if version else "")

    @property
    def thread_id(self):
        return self._thread_id

    @property
    def codex_sessions_dir(self):
        return str(Path(os.getenv("CODEX_HOME") or Path.home() / ".codex") / "sessions")

    def set_model(self, model: str):
        self.config.model = model.strip()
        self._active_model = self.config.model

    def set_reasoning_effort(self, effort: str):
        effort = effort.strip().lower()
        if effort in {"", "default", "auto"}:
            self._reasoning_effort = None
        elif effort in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
            self._reasoning_effort = effort
        else:
            raise ValueError(f"Unsupported Codex reasoning effort: {effort}")

    @staticmethod
    def _sandbox(mode):
        aliases = {
            "read-only": "readOnly",
            "readonly": "readOnly",
            "read": "readOnly",
            "workspace-write": "workspaceWrite",
            "workspace_write": "workspaceWrite",
            "workspace": "workspaceWrite",
            "full": "dangerFullAccess",
            "full_access": "dangerFullAccess",
            "full-access": "dangerFullAccess",
            "danger-full-access": "dangerFullAccess",
            "none": "dangerFullAccess",
        }
        if mode not in aliases:
            raise ValueError(f"Unsupported Codex sandbox: {mode}")
        return aliases[mode]

    def set_sandbox_backend(self, mode):
        if mode:
            self._sandbox(mode)
        self.sandbox_backend = mode

    def set_next_turn_sandbox(self, mode):
        self._sandbox(mode)
        self._next_turn_sandbox = mode

    def set_review(self, prompt: str = "", *, base=None, commit=None):
        if sum(bool(value) for value in (prompt, base, commit)) > 1:
            raise ValueError("Choose review instructions, --base, or --commit")
        self._require_idle()
        self._review = (
            {"type": "baseBranch", "branch": base}
            if base
            else {"type": "commit", "sha": commit}
            if commit
            else {"type": "custom", "instructions": prompt}
            if prompt
            else {"type": "uncommittedChanges"}
        )

    def _require_idle(self):
        if self._turn_lock.locked() or self._active_turn:
            raise RuntimeError(
                "A Codex turn is running; cancel it or wait before changing the session"
            )

    def set_approval_policy(self, policy):
        self._require_idle()
        if policy not in {"on-request", "never"}:
            raise ValueError("Approval policy must be on-request or never")
        self._approval_policy = policy

    async def set_plan_mode(self, enabled):
        self._require_idle()
        # Check the installed server's supported presets before selecting one.
        await self._ensure_started()
        result = await self._timed_request("collaborationMode/list")
        mode = "plan" if enabled else "default"
        if mode not in {item.get("mode") for item in result.get("data", [])}:
            raise RuntimeError(f"This Codex CLI does not advertise {mode} collaboration mode")
        self._require_idle()
        self._collaboration_mode = mode
        return {"mode": mode, "applies": "next turn"}

    def _on_error(self, error):
        self._failure = error
        if self._queue is not None:
            # Always leave room for terminal errors even after an event flood.
            if self._queue.full():
                self._queue.get_nowait()
            self._queue.put_nowait(error)

    def _on_notification(self, method, params):
        if method == "account/updated":
            self.subscription_status = {"auth_method": "unknown", "billing_verified": "unknown"}
        elif method == "account/login/completed":
            self.login_status = {key: params.get(key) for key in ("success", "error")}
            if params.get("loginId") == self._login_id:
                self._login_id = None
        elif method == "account/rateLimits/updated":
            self.rate_limits = params.get("rateLimits") or params
        elif method == "thread/tokenUsage/updated" and params.get("threadId") == self._thread_id:
            self.token_usage = params.get("tokenUsage") or {}
        if self._queue is None:
            return
        if params.get("threadId") not in {None, self._thread_id}:
            return
        turn_id = params.get("turnId") or (params.get("turn") or {}).get("id")
        if self._active_turn and turn_id and turn_id != self._active_turn:
            return
        try:
            self._queue.put_nowait((method, params))
        except asyncio.QueueFull:
            self._on_error(RuntimeError("Codex event queue overflowed; the turn was not replayed"))
            if self._transport:
                self._spawn_control(self._transport.close())

    async def _timed_request(self, method, params=None):
        assert self._transport is not None
        start = time.monotonic()
        try:
            return await self._transport.request(method, params)
        finally:
            self.timings[method] = (time.monotonic() - start) * 1000

    async def _ensure_started(self):
        async with self._start_lock:
            if self._closed:
                raise RuntimeError("Codex runtime is closed; reconnect to start another session")
            if self._failure:
                raise RuntimeError(
                    f"Codex connection failed: {self._failure}; reconnect to continue"
                )
            if self._transport is not None:
                return
            self._loop = asyncio.get_running_loop()
            argv = [self.binary]
            env = child_env()
            if self.billing_requested == "subscription":
                from superqode.providers.subscription_env import subscription_child_env

                env, _ = subscription_child_env("codex", env)
                argv += ["-c", 'forced_login_method="chatgpt"', "-c", 'model_provider="openai"']
            argv += ["app-server", "--listen", "stdio://"]
            transport = CodexTransport(
                self._on_notification,
                self._server_request,
                self._on_error,
                request_timeout=self._request_timeout,
            )
            self._transport = transport
            start = time.monotonic()
            try:
                await transport.start(argv, cwd=str(self.config.working_directory), env=env)
                from superqode import __version__

                self.metadata = await self._timed_request(
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "superqode",
                            "title": "SuperQode",
                            "version": __version__,
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                )
                await transport.notify("initialized")
                self.timings["startup"] = (time.monotonic() - start) * 1000
            except BaseException as exc:
                await transport.close()
                self._transport = None
                if isinstance(exc, Exception) and transport.stderr_tail:
                    raise RuntimeError(
                        f"Installed Codex CLI could not initialize: {exc}\n{transport.stderr_tail[-4000:]}"
                    ) from exc
                raise

    async def account(self, *, refresh_token=False):
        await self._ensure_started()
        return await self._timed_request("account/read", {"refreshToken": refresh_token})

    async def verify_account(self):
        if self.billing_requested != "subscription":
            return
        self.subscription_status = {"auth_method": "unknown", "billing_verified": "unknown"}
        data = await self.account()
        account = data.get("account") or {}
        if (
            account.get("type") not in {"chatgpt", "chatgptAuthTokens"}
            or data.get("requiresOpenaiAuth") is not True
        ):
            await self.aclose()
            raise RuntimeError(
                "Codex subscription access is not verified. Run `codex login` with ChatGPT. No API billing fallback was attempted."
            )
        self.subscription_status = {
            "auth_method": "chatgpt",
            "billing_verified": "chatgpt-account",
            "plan": account.get("planType") or "unavailable",
        }

    def _thread_params(self):
        params: dict[str, Any] = {"cwd": str(self.config.working_directory)}
        if self.config.model:
            params["model"] = self.config.model
        if self.billing_requested == "subscription":
            params["modelProvider"] = "openai"
        elif self.config.provider and self.config.provider != "openai":
            params["modelProvider"] = self.config.provider
        if self.config.custom_system_prompt:
            params["developerInstructions"] = self.config.custom_system_prompt
        if self.sandbox_backend:
            params["sandbox"] = self._sandbox(self.sandbox_backend)
        elif not self.config.tools_enabled:
            params["sandbox"] = "readOnly"
        return params

    def _accept_thread(self, result):
        if self.billing_requested == "subscription" and result.get("modelProvider") != "openai":
            self.subscription_status["billing_verified"] = "unknown"
            self._failure = RuntimeError(
                "Codex resolved a different provider. No API billing fallback was attempted."
            )
            raise self._failure
        new_id = result.get("thread", {}).get("id")
        if new_id != self._thread_id:
            self.token_usage = {}
        self._thread_id = new_id
        if not self._thread_id:
            raise RuntimeError("Codex response did not include a thread id")
        self._active_model = result.get("model") or self.config.model

    async def ensure_thread(self):
        await self._ensure_started()
        async with self._thread_lock:
            if self._thread_id is None:
                await self.verify_account()
                self._accept_thread(
                    await self._timed_request("thread/start", self._thread_params())
                )
                return True
            return False

    async def models(self, *, include_hidden=False):
        await self._ensure_started()
        return await self._timed_request("model/list", {"includeHidden": include_hidden})

    async def list_threads(
        self, *, limit=20, archived=False, cursor=None, all_cwds=False, descendants=False
    ):
        await self._ensure_started()
        params = {"limit": limit, "archived": archived, "sortKey": "updated_at"}
        if not all_cwds:
            params["cwd"] = str(self.config.working_directory)
        if cursor:
            params["cursor"] = cursor
        if descendants:
            if not self._thread_id:
                return {"data": []}
            params["ancestorThreadId"] = self._thread_id
            params["sourceKinds"] = [
                "subAgent",
                "subAgentReview",
                "subAgentCompact",
                "subAgentThreadSpawn",
                "subAgentOther",
            ]
        return await self._timed_request("thread/list", params)

    async def _load_thread(self, method, thread_id):
        async with self._turn_lock:
            await self._ensure_started()
            async with self._thread_lock:
                await self.verify_account()
                params = {**self._thread_params(), "threadId": thread_id}
                params.pop("developerInstructions", None)
                result = await self._timed_request(method, params)
                self._accept_thread(result)
                return result

    async def resume_thread(self, thread_id):
        return await self._load_thread("thread/resume", thread_id)

    async def fork_thread(self, thread_id):
        return await self._load_thread("thread/fork", thread_id)

    async def new_thread(self, name=""):
        self._require_idle()
        async with self._turn_lock:
            await self._ensure_started()
            async with self._thread_lock:
                await self.verify_account()
                result = await self._timed_request("thread/start", self._thread_params())
                self._accept_thread(result)
            if name:
                await self.rename_thread(name)
            return result

    async def read_thread(self, *, include_turns=False):
        await self.ensure_thread()
        return await self._timed_request(
            "thread/read", {"threadId": self._thread_id, "includeTurns": include_turns}
        )

    async def rename_thread(self, name):
        await self.ensure_thread()
        return await self._timed_request(
            "thread/name/set", {"threadId": self._thread_id, "name": name}
        )

    async def compact_thread(self):
        self._require_idle()
        async with self._turn_lock:
            await self.ensure_thread()
            return await self._timed_request("thread/compact/start", {"threadId": self._thread_id})

    async def archive_thread(self, thread_id):
        self._require_idle()
        async with self._turn_lock:
            await self._ensure_started()
            result = await self._timed_request("thread/archive", {"threadId": thread_id})
            if thread_id == self._thread_id:
                self._thread_id = None
                self._active_model = ""
                self.token_usage = {}
            return result

    async def unarchive_thread(self, thread_id):
        await self._ensure_started()
        return await self._timed_request("thread/unarchive", {"threadId": thread_id})

    async def login(self, *, device=False):
        self._require_idle()
        async with self._turn_lock:
            await self._ensure_started()
            if self._login_id:
                raise RuntimeError("A Codex login is pending; finish it or use :codex login cancel")
            result = await self._timed_request(
                "account/login/start", {"type": "chatgptDeviceCode" if device else "chatgpt"}
            )
            self._login_id = result.get("loginId")
            self.login_status = {"pending": True}
            return result

    async def cancel_login(self):
        await self._ensure_started()
        if not self._login_id:
            raise RuntimeError("No Codex sign-in is pending")
        result = await self._timed_request("account/login/cancel", {"loginId": self._login_id})
        self._login_id = None
        self.login_status = {"pending": False}
        return result

    async def inspect(self, topic, *, reload=False, cursor=None):
        """A bounded, explicit set of Codex-owned inventories, never host inventories."""
        cwd = str(self.config.working_directory)
        methods = {
            "skills": ("skills/list", {"cwds": [cwd], "forceReload": reload}),
            "hooks": ("hooks/list", {"cwds": [cwd]}),
            "plugins": ("plugin/list", {"cwds": [cwd], "forceRefetch": reload}),
            "apps": ("app/list", {"limit": 50, "forceRefetch": reload}),
            "features": ("experimentalFeature/list", {"limit": 50}),
            "permissions": ("permissionProfile/list", {"cwd": cwd}),
            "mcp": ("mcpServerStatus/list", {"limit": 50}),
        }
        if topic not in methods:
            raise ValueError(f"Unsupported Codex inventory: {topic}")
        await self._ensure_started()
        method, params = methods[topic]
        if cursor:
            if topic not in {"apps", "features", "permissions", "mcp"}:
                raise ValueError(f"{topic} does not accept a pagination cursor")
            params["cursor"] = cursor
        if self._thread_id and topic in {"apps", "features", "mcp"}:
            params["threadId"] = self._thread_id
        return await self._timed_request(method, params)

    async def reload_mcp(self):
        self._require_idle()
        await self._ensure_started()
        return await self._timed_request("config/mcpServer/reload")

    async def usage(self, *, tokens=False):
        await self._ensure_started()
        result = await self._timed_request(
            "account/usage/read" if tokens else "account/rateLimits/read",
            {} if tokens else {"excludeResetCreditDetails": True, "supportsLunaReserve": False},
        )
        if not tokens:
            self.rate_limits = result.get("rateLimits") or {}
        return result

    async def read_config(self):
        await self._ensure_started()
        config = await self._timed_request(
            "config/read", {"cwd": str(self.config.working_directory), "includeLayers": True}
        )
        requirements = await self._timed_request("configRequirements/read")
        return {"configuration": config, "requirements": requirements}

    async def doctor(self):
        """The CLI's own diagnostics require a separate noninteractive process."""
        process = await asyncio.create_subprocess_exec(
            self.binary,
            "doctor",
            "--json",
            cwd=str(self.config.working_directory),
            env=child_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self._request_timeout
            )
            if not stdout:
                raise RuntimeError(
                    f"Codex doctor returned no JSON report (exit {process.returncode}); run codex doctor in a terminal"
                )
            # Doctor may return a nonzero status when the report contains failed checks.
            return {"exitCode": process.returncode, "report": json.loads(stdout)}
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    async def background_terminals(self, *, stop=False, cursor=None):
        await self._ensure_started()
        if not self._thread_id:
            if stop:
                raise RuntimeError("No Codex thread is active")
            return {"data": []}
        params = {"threadId": self._thread_id}
        if cursor and not stop:
            params["cursor"] = cursor
        return await self._timed_request(
            "thread/backgroundTerminals/clean" if stop else "thread/backgroundTerminals/list",
            params,
        )

    async def logout(self):
        self._require_idle()
        await self._ensure_started()
        result = await self._timed_request("account/logout")
        self.subscription_status = {"auth_method": "unknown", "billing_verified": "unknown"}
        self._login_id = None
        return result

    async def _server_request(self, method, params):
        # The TUI has one composer for approvals/questions. Keep that UI
        # serialized while the independent transport reader keeps running.
        async with self._interaction_lock:
            return await self._handle_server_request(method, params)

    async def _handle_server_request(self, method, params):
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            tool = "bash" if "commandExecution" in method else "patch"
            arguments = {
                **params,
                "command": params.get("command", ""),
                "path": params.get("path", ""),
            }
            allowed = False
            permission = (
                self._permission_manager.check_permission(tool, arguments)
                if self._permission_manager
                else Permission.ASK
            )
            if permission == Permission.ALLOW:
                allowed = True
            elif permission == Permission.ASK and self._approval_callback:
                if inspect.iscoroutinefunction(self._approval_callback):
                    allowed = bool(await self._approval_callback(tool, arguments))
                else:
                    allowed = bool(
                        await asyncio.to_thread(self._approval_callback, tool, arguments)
                    )
            return {"decision": "accept" if allowed else "decline"}
        if method == "item/tool/requestUserInput":
            from superqode.tools.question_tool import Question, QuestionType, get_question_handler

            handler = get_question_handler()
            if handler is None:
                raise RuntimeError(
                    "Codex requested user input outside an interactive SuperQode session"
                )
            answers = {}
            for question in params.get("questions", []):
                options = question.get("options") or []
                try:
                    answer = await handler(
                        Question(
                            question=question.get("question", ""),
                            question_type=QuestionType.CHOICE if options else QuestionType.TEXT,
                            options=[option["label"] for option in options],
                            allow_custom=question.get("isOther", True),
                        )
                    )
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                    # Skipping the question cancels its answer future, not
                    # the RPC task. Send an empty answer so Codex can continue.
                    return {"answers": {}}
                values = answer.value if isinstance(answer.value, list) else [str(answer.value)]
                answers[question["id"]] = {"answers": values}
            return {"answers": answers}
        if method == "mcpServer/elicitation/request":
            self._on_notification(
                "warning",
                {
                    "message": "Codex MCP elicitation cancelled: SuperQode does not yet support this form or URL flow."
                },
            )
            return {"action": "cancel", "content": None}
        if method == "item/permissions/requestApproval":
            self._on_notification(
                "warning",
                {
                    "message": "Codex additional permissions declined: use the command approval prompt or configure the Codex sandbox."
                },
            )
            return {"permissions": {}, "scope": "turn"}
        raise RuntimeError(f"SuperQode does not support Codex server request {method}")

    async def run_harness_events(self, prompt: str, *, images=None):
        async with self._turn_lock:
            self.reset_cancellation()
            start = time.monotonic()
            mapper = CodexEvents()
            turn_finished = False
            try:
                created = await self.ensure_thread()
                if not created:
                    await self.verify_account()
                if self._cancelled:
                    yield HarnessEvent(type="turn_complete", data={"status": "cancelled"})
                    return
                self._queue = asyncio.Queue(maxsize=8192)
                yield HarnessEvent(type="model_request", data={"runtime": self.name})
                params = {
                    "threadId": self._thread_id,
                    "input": [{"type": "text", "text": prompt, "text_elements": []}],
                }
                for image in images or ():
                    params["input"].append(
                        {"type": "localImage", "path": str(image.path.resolve())}
                    )
                if self.config.model:
                    params["model"] = self.config.model
                if self._reasoning_effort:
                    params["effort"] = self._reasoning_effort
                if self._approval_policy:
                    params["approvalPolicy"] = self._approval_policy
                if self._collaboration_mode:
                    params["collaborationMode"] = {
                        "mode": self._collaboration_mode,
                        "settings": {
                            "model": self.config.model or self._active_model,
                            "reasoning_effort": self._reasoning_effort,
                            "developer_instructions": None,
                        },
                    }
                sandbox = self._next_turn_sandbox or self.sandbox_backend
                self._next_turn_sandbox = None
                if sandbox or not self.config.tools_enabled:
                    policy = {"type": self._sandbox(sandbox or "read-only")}
                    if policy["type"] != "dangerFullAccess":
                        policy["networkAccess"] = False
                    if policy["type"] == "workspaceWrite":
                        policy.update(
                            writableRoots=[str(self.config.working_directory.resolve())],
                            excludeTmpdirEnvVar=False,
                            excludeSlashTmp=False,
                        )
                    params["sandboxPolicy"] = policy
                review, self._review = self._review, None
                if review:
                    result = await self._timed_request(
                        "review/start", {"threadId": self._thread_id, "target": review}
                    )
                else:
                    result = await self._timed_request("turn/start", params)
                self._active_turn = result.get("turn", {}).get("id")
                if not self._active_turn:
                    raise RuntimeError("Codex turn/start did not include a turn id")
                if self._cancelled:
                    await self._interrupt()
                first_event = True
                while True:
                    notification = await self._queue.get()
                    if isinstance(notification, BaseException):
                        raise notification
                    method, payload = notification
                    turn_id = payload.get("turnId") or (payload.get("turn") or {}).get("id")
                    if turn_id and turn_id != self._active_turn:
                        continue
                    if first_event:
                        self.timings["first_event"] = (time.monotonic() - start) * 1000
                        first_event = False
                    if method == "turn/completed":
                        turn_finished = True
                    for event in mapper.map(method, payload):
                        if event.type == "model_delta" and "first_text" not in self.timings:
                            self.timings["first_text"] = (time.monotonic() - start) * 1000
                        yield event
                    if method == "turn/completed":
                        turn = payload.get("turn", {})
                        if turn.get("status") == "failed":
                            raise RuntimeError(
                                f"Codex turn failed: {(turn.get('error') or {}).get('message', 'unknown error')}"
                            )
                        break
                self.timings["turn"] = (time.monotonic() - start) * 1000
                yield HarnessEvent(
                    type="model_result",
                    data={"runtime": self.name, "timings_ms": dict(self.timings)},
                )
            except (asyncio.CancelledError, GeneratorExit):
                if self._active_turn and not turn_finished:
                    await self._stop_active_turn()
                elif self._queue is not None and not turn_finished:
                    await self.aclose()
                raise
            except Exception:
                # A failed start may have run tools before its response was lost.
                if self._active_turn is None and self._queue is not None:
                    await self.aclose()
                elif self._active_turn and not turn_finished:
                    await self._stop_active_turn()
                raise
            finally:
                if self._transport:
                    await self._transport.cancel_server_requests()
                self._active_turn = None
                self._queue = None

    async def run_streaming(self, prompt: str):
        from contextlib import aclosing

        async with aclosing(self.run_harness_events(prompt)) as events:
            async for event in events:
                if event.type == "model_delta":
                    yield str(event.data.get("text") or "")

    async def run(self, prompt: str, *, images=None):
        text, calls, status, usage = [], 0, "completed", {}
        async for event in self.run_harness_events(prompt, images=images):
            if event.type == "model_delta":
                text.append(str(event.data.get("text") or ""))
            elif event.type == "tool_call":
                calls += 1
            elif event.type == "turn_complete":
                status, usage = event.data.get("status"), event.data.get("usage", {})
        content = "".join(text)
        response = AgentResponse(
            content=content,
            messages=[
                AgentMessage(role="user", content=prompt),
                AgentMessage(role="assistant", content=content),
            ],
            tool_calls_made=calls,
            iterations=1,
            stopped_reason="complete" if status == "completed" else status,
        )
        response.usage = usage
        return response

    async def steer(self, message: str):
        if not self._active_turn:
            return False
        await self._timed_request(
            "turn/steer",
            {
                "threadId": self._thread_id,
                "expectedTurnId": self._active_turn,
                "input": [{"type": "text", "text": message, "text_elements": []}],
            },
        )
        return True

    async def _interrupt(self):
        if self._active_turn and self._transport:
            await self._timed_request(
                "turn/interrupt", {"threadId": self._thread_id, "turnId": self._active_turn}
            )

    async def _stop_active_turn(self):
        """Do not release the turn lock while an interrupted turn is still live."""
        try:
            async with asyncio.timeout(5):
                await self._interrupt()
                while self._queue is not None:
                    message = await self._queue.get()
                    if isinstance(message, BaseException):
                        raise message
                    method, params = message
                    if (
                        method == "turn/completed"
                        and params.get("turn", {}).get("id") == self._active_turn
                    ):
                        return
        except Exception:
            await self.aclose()

    def _spawn_control(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._control_tasks.add(task)

        def done(task):
            self._control_tasks.discard(task)
            if not task.cancelled() and task.exception():
                self._on_error(task.exception())

        task.add_done_callback(done)

    def cancel(self):
        self._cancelled = True
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(lambda: self._spawn_control(self._interrupt()))

    def reset_cancellation(self):
        self._cancelled = False
        self.timings.pop("first_text", None)

    async def aclose(self):
        self._closed = True
        self._on_error(RuntimeError("Codex runtime closed"))
        if self._transport:
            await self._transport.close()
            self._transport = None
        tasks = [task for task in self._control_tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self):
        await self.aclose()
