"""Native desktop host for the existing ACP client and permission protocol."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
import json
import sys
import time
import uuid
import threading

from superqode.acp.client import ACPClient
from .redaction import redact


def scoped_path(root: Path, supplied: str) -> Path:
    target = (root / supplied).resolve()
    if (
        not target.is_relative_to(root)
        or any(
            part.casefold() in {".git", ".ssh", ".aws"} for part in target.relative_to(root).parts
        )
        or target.name.casefold().startswith(".env")
    ):
        raise PermissionError("ACP file access is outside the allowed project scope")
    return target


async def select_session_model(client, model: str) -> bool:
    """Use the model-selection protocol advertised by this exact ACP session."""
    option = next(
        (
            item
            for item in client.get_session_config_options()
            if item.get("id") == "model" or item.get("category") == "model"
        ),
        None,
    )
    if option:
        return await client.set_config_option(str(option["id"]), model)
    return await client.set_model(model)


class DesktopACPClient(ACPClient):
    async def _handle_agent_request(self, method, params):
        if self.negotiated_version == 2:
            # Reject removed v1 host methods before *any* host side effect.
            return await super()._handle_agent_request(method, params)
        if not self.allow_host_tools and (
            method.startswith("fs/") or method.startswith("terminal/")
        ):
            raise PermissionError("Connection setup cannot read, write or execute project tools")
        if method in {"fs/read_text_file", "fs/write_text_file"}:
            path = scoped_path(self.project_root, str(params.get("path") or ""))
            if path.is_file() and path.stat().st_size > 1_000_000:
                raise ValueError("ACP file exceeds the desktop preview size limit")
            if method == "fs/write_text_file":
                if len(str(params.get("content", ""))) > 1_000_000:
                    raise ValueError("ACP write exceeds the desktop preview size limit")
                options = [
                    {"kind": "allow_once", "optionId": "allow"},
                    {"kind": "reject_once", "optionId": "deny"},
                ]
                choice = await self.on_permission_request(
                    options,
                    {
                        "title": "Write " + str(path.relative_to(self.project_root)),
                        "path": str(path),
                        "content": params.get("content", ""),
                    },
                )
                if choice != "allow":
                    raise PermissionError("File write denied in the native app")
        return await super()._handle_agent_request(method, params)


class DesktopTerminals:
    def __init__(self, root, permission, emit):
        self.root, self.permission, self.emit = root, permission, emit
        self.terminals = {}

    async def create(self, params):
        cwd = scoped_path(self.root, str(params.get("cwd") or "."))
        command = str(params.get("command") or "")
        args = [str(arg) for arg in params.get("args", [])]
        choice = await self.permission(
            [
                {"kind": "allow_once", "optionId": "allow"},
                {"kind": "reject_once", "optionId": "deny"},
            ],
            {
                "title": "Run command",
                "command": command,
                "args": args,
                "cwd": str(cwd),
                "env": params.get("env", []),
            },
        )
        if choice != "allow":
            raise PermissionError("Terminal command denied in the native app")
        import os

        env = dict(os.environ)
        for entry in params.get("env", []):
            env[str(entry["name"])] = str(entry["value"])
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        identity = uuid.uuid4().hex
        item = {"process": process, "output": "", "truncated": False}
        self.terminals[identity] = item
        item["reader"] = asyncio.create_task(self._read(identity, item))
        return {"terminalId": identity}

    async def _read(self, identity, item):
        while chunk := await item["process"].stdout.read(4096):
            text = chunk.decode("utf-8", errors="replace")
            self.emit("output", {"text": text, "terminal_id": identity})
            remaining = max(0, 100_000 - len(item["output"]))
            item["output"] += text[:remaining]
            item["truncated"] |= len(text) > remaining
        await item["process"].wait()

    async def output(self, params):
        item = self.terminals[params["terminalId"]]
        code = item["process"].returncode
        return {
            "output": item["output"],
            "truncated": item["truncated"],
            **({"exitStatus": {"exitCode": code}} if code is not None else {}),
        }

    async def wait_for_exit(self, params):
        item = self.terminals[params["terminalId"]]
        await item["reader"]
        return {"exitCode": item["process"].returncode}

    async def kill(self, params):
        item = self.terminals.get(params["terminalId"])
        if item and item["process"].returncode is None:
            item["process"].terminate()
            try:
                await asyncio.wait_for(item["process"].wait(), 2)
            except asyncio.TimeoutError:
                item["process"].kill()
                await item["process"].wait()
        return {}

    async def release(self, params):
        await self.kill(params)
        item = self.terminals.pop(params["terminalId"], None)
        if item:
            await item["reader"]
        return {}

    async def close(self):
        for identity in list(self.terminals):
            await self.release({"terminalId": identity})


class ACPInputRouter:
    """A single daemon reader routes permissions and independent ACP controls."""

    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.decisions = {}
        self.closed = asyncio.Event()
        self.controller = None
        self.tasks = set()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        try:
            for line in sys.stdin:
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                self.loop.call_soon_threadsafe(self.deliver, value)
        except (OSError, ValueError, RuntimeError):
            pass
        finally:
            try:
                self.loop.call_soon_threadsafe(self.disconnect)
            except RuntimeError:
                pass

    def disconnect(self):
        self.closed.set()
        for future in self.decisions.values():
            if not future.done():
                future.set_exception(ConnectionError("Desktop disconnected"))

    def deliver(self, value):
        if value.get("operation") == "acp_control" and self.controller:
            task = asyncio.create_task(self.controller(value))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        else:
            future = self.decisions.get(value.get("request_id"))
            if future and not future.done():
                future.set_result(value)

    async def decision(self, token):
        if self.closed.is_set():
            raise ConnectionError("Desktop disconnected")
        future = self.loop.create_future()
        self.decisions[token] = future
        try:
            return await future
        finally:
            self.decisions.pop(token, None)


async def run_acp(request, directory, emit, secrets):
    route = request["_desktop_route"]
    if request.get("_local_harness"):
        from .local_harnesses import materialize_worker_files

        materialize_worker_files(request["_local_harness"], request["state_root"])
    if request.get("expected_digest") and request["expected_digest"] != route["digest"]:
        raise ValueError("The ACP launch route changed. Start a new task.")

    async def event(name, data):
        emit("harness_event", {"event": name, "payload": data})

    inputs = ACPInputRouter()
    approval_lock = asyncio.Lock()
    session_end = asyncio.Event()

    async def permission(options, tool):
        async with approval_lock:
            token = uuid.uuid4().hex
            try:
                emit("approval", {"request_id": token, "tool": tool, "options": options})
                decision = await inputs.decision(token)
            except (asyncio.CancelledError, ConnectionError):
                emit("approval_cancelled", {"request_id": token})
                return ""
        duration = "always" if decision.get("scope") == "always" else "once"
        wanted = ("allow_" if decision.get("allow") is True else "reject_") + duration
        selected = next(
            (option.get("optionId", "") for option in options if option.get("kind") == wanted), ""
        )
        # Never turn an allow-once click into an allow-always decision.
        if not selected:
            raise PermissionError("The agent did not offer the requested one-time permission")
        return selected

    root = Path(request["cwd"]).resolve()
    terminals = DesktopTerminals(root, permission, emit)
    bridge = None

    async def prepare_v2(client):
        nonlocal bridge
        if bridge:
            await bridge.close()
            bridge = None
        from superqode.acp.protocol import capability

        if capability(client.get_agent_capabilities(), "session", "mcp", "http"):
            from .acp_mcp import HostMcpBridge

            bridge = HostMcpBridge(root, permission, terminals)
            client.host_mcp_servers = [await bridge.start()]
            secrets.append(bridge.token)
        else:
            emit(
                "host_tools",
                {
                    "available": False,
                    "message": "This agent uses its own tools and permission policy; desktop host tools are unavailable.",
                },
            )

    client = DesktopACPClient(
        root,
        route["command"],
        launch_argv=route.get("command_argv") or __import__("shlex").split(route["command"]),
        model=request.get("model") or None,
        subscription_vendor=route.get("subscription_vendor"),
        extra_env=route.get("extra_env"),
        traffic_log_enabled=False,
        resume_session_id=request.get("session_id"),
        require_resume=bool(request.get("session_id")),
        prompt_timeout=1800,
        terminal_service=terminals,
        protocol_version=(request.get("acp_options") or {}).get("protocol_version"),
        protocol_policy=(request.get("acp_options") or {}).get("protocol_policy"),
        session_protocol_version=request.get("_acp_resume_protocol_version"),
        pending_submission_path=Path(request.get("state_root", directory))
        / "acp-submissions.sqlite3",
        on_permission_request=permission,
        on_v2_ready=prepare_v2,
        on_message_update=lambda snapshot: event("acp_message", snapshot),
        on_session_update=lambda params: event("acp_update", params),
        on_message=lambda text: event("delta", {"text": text}),
        on_thinking=lambda text: event("thinking", {"text": text}),
        on_tool_call=lambda tool: event("tool_call", tool),
        on_tool_update=lambda tool: event("tool_update", tool),
        on_plan=lambda plan: event("plan", {"entries": plan}),
        on_usage_update=lambda usage: event("usage", usage),
        on_available_commands=lambda commands: event(
            "commands", {"commands": commands, "observed_at": time.time()}
        ),
        on_session_info_update=lambda info: event("session_info", info),
    )

    async def control(value):
        try:
            if client.negotiated_version != 2:
                raise ValueError("This connection does not negotiate ACP v2")
            action = value.get("action")
            identity = value.get("session_id") or client.get_session_id()
            if action == "close":
                await client.close_session(identity)
                session_end.set()
            elif action == "cancel":
                if not await client.cancel(identity):
                    raise ValueError("Session cancellation could not be delivered")
            elif action in {"tool", "terminal"}:
                await client.cancel_item(identity, value["item_id"], terminal=action == "terminal")
            else:
                raise ValueError("Unsupported ACP control")
            emit("acp_control", {"request_id": value.get("request_id"), "accepted": True})
        except Exception as exc:
            emit(
                "acp_control",
                {"request_id": value.get("request_id"), "accepted": False, "message": str(exc)},
            )

    inputs.controller = control
    try:
        emit(
            "provenance",
            {
                "harness": route["id"],
                "protocol": "ACP",
                "digest": route["digest"],
                "auth": route.get("auth"),
                "command": route["command"],
            },
        )
        if not await client.start():
            raise RuntimeError(
                client.last_startup_error
                or "ACP startup or exact session resume failed. Start a new task if the agent cannot resume."
            )
        local = request.get("_local_harness") or {}
        if local.get("harness") == "opencode" and not await select_session_model(
            client, local["config"]["model"]
        ):
            raise ValueError(
                "The agent rejected the configured local model. No fallback was attempted."
            )
        controls = request.get("acp_options") or {}
        if controls.get("model") and not await select_session_model(client, str(controls["model"])):
            raise ValueError("The agent rejected the requested model")
        if controls.get("mode") and not await client.set_mode(str(controls["mode"])):
            raise ValueError("The agent rejected the requested mode")
        for identity, value in (controls.get("config") or {}).items():
            if controls.get("model") and str(identity) == "model":
                continue
            if not await client.set_config_option(
                str(identity), value if client.negotiated_version == 2 else str(value)
            ):
                raise ValueError("The agent rejected configuration option " + str(identity))
        emit(
            "harness_event",
            {
                "event": "acp_session",
                "payload": {
                    "observed_at": time.time(),
                    "session_id": client.get_session_id(),
                    "initialization": client.get_initialization_info(),
                    **client.get_initialization_info(),
                    "capabilities": client.get_agent_capabilities(),
                    "models": client.get_session_models(),
                    "modes": client.get_session_modes(),
                    "config_options": client.get_session_config_options(),
                },
            },
        )
        from .images import load_snapshots

        reason = await client.send_prompt(
            request["prompt"],
            images=load_snapshots(request),
            **(
                {"idempotency_key": request.get("submission_key")}
                if client.negotiated_version == 2
                else {}
            ),
        )
        if reason in {None, "error"}:
            raise RuntimeError("ACP did not complete the task: " + str(reason))
        if client.negotiated_version == 2:
            state = client.sessions.get(client.get_session_id())
            emit(
                "foreground_complete",
                {
                    "stop_reason": reason,
                    "session_id": state.session_id,
                    "background": state.background,
                },
            )
            # Foreground idle is not the lifetime of a session. Retain the
            # transport until it is explicitly closed or confirmed quiet.
            while not state.quiet and not session_end.is_set():
                if inputs.closed.is_set() or client._v2_disconnected:
                    raise ConnectionError(
                        "ACP session disconnected while background activity may remain"
                    )
                state.changed.clear()
                if not state.quiet:
                    try:
                        await asyncio.wait_for(state.changed.wait(), 0.25)
                    except asyncio.TimeoutError:
                        pass
            # An item can become quiet before its cancel RPC response arrives.
            # Deliver control acknowledgements before publishing a terminal result.
            await asyncio.gather(*list(inputs.tasks), return_exceptions=True)
        result = {
            "status": "cancelled" if reason == "cancelled" else "completed",
            "protocol_version": client.negotiated_version,
            "protocol_policy": client.protocol_policy,
            "protocol_status": client.get_initialization_info(),
            "session_id": client.get_session_id(),
            "harness": route["name"],
            "harness_digest": route["digest"],
            "native_continuity": False,
            "acp_continuity": client.supports_resume(),
            "protocol": "ACP",
            "stop_reason": reason,
            "stats": asdict(client.get_stats()),
            "artifact_dir": str(directory),
        }
        (directory / "result.json").write_text(json.dumps(redact(result, secrets), indent=2))
        emit("result", result)
    finally:
        for task in inputs.tasks:
            task.cancel()
        await asyncio.gather(*inputs.tasks, return_exceptions=True)
        await terminals.close()
        if bridge:
            await bridge.close()
        await client.stop()
