"""Native desktop host for the existing ACP client and permission protocol."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
import json
import sys
import uuid

from superqode.acp.client import ACPClient
from .redaction import redact


def scoped_path(root: Path, supplied: str) -> Path:
    target = (root / supplied).resolve()
    if (
        not target.is_relative_to(root)
        or any(part in {".git", ".ssh", ".aws"} for part in target.relative_to(root).parts)
        or target.name.startswith(".env")
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


async def run_acp(request, directory, emit, secrets):
    route = request["_desktop_route"]
    if request.get("expected_digest") and request["expected_digest"] != route["digest"]:
        raise ValueError("The ACP launch route changed. Start a new task.")

    async def event(name, data):
        emit("harness_event", {"event": name, "payload": data})

    async def permission(options, tool):
        token = uuid.uuid4().hex
        emit("approval", {"request_id": token, "tool": tool, "options": options})
        while True:
            raw = await asyncio.to_thread(sys.stdin.readline)
            if not raw:
                raise RuntimeError("Desktop disconnected while waiting for ACP permission")
            decision = json.loads(raw)
            if decision.get("request_id") == token:
                break
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
    client = DesktopACPClient(
        root,
        route["command"],
        model=request.get("model") or None,
        subscription_vendor=route.get("subscription_vendor"),
        extra_env=route.get("extra_env"),
        traffic_log_enabled=False,
        resume_session_id=request.get("session_id"),
        require_resume=bool(request.get("session_id")),
        prompt_timeout=1800,
        terminal_service=terminals,
        on_permission_request=permission,
        on_message=lambda text: event("delta", {"text": text}),
        on_thinking=lambda text: event("thinking", {"text": text}),
        on_tool_call=lambda tool: event("tool_call", tool),
        on_tool_update=lambda tool: event("tool_update", tool),
        on_plan=lambda plan: event("plan", {"entries": plan}),
        on_usage_update=lambda usage: event("usage", usage),
        on_available_commands=lambda commands: event("commands", {"commands": commands}),
        on_session_info_update=lambda info: event("session_info", info),
    )
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
        emit("stage", {"message": "Starting the ACP agent and opening its session"})
        if not await client.start():
            raise RuntimeError(
                client.last_startup_error
                or "ACP startup or exact session resume failed. Start a new task if the agent cannot resume."
            )
        controls = request.get("acp_options") or {}
        if controls.get("model") and not await select_session_model(client, str(controls["model"])):
            raise ValueError("The agent rejected the requested model")
        if controls.get("mode") and not await client.set_mode(str(controls["mode"])):
            raise ValueError("The agent rejected the requested mode")
        for identity, value in (controls.get("config") or {}).items():
            if not await client.set_config_option(str(identity), str(value)):
                raise ValueError("The agent rejected configuration option " + str(identity))
        emit(
            "harness_event",
            {
                "event": "acp_session",
                "payload": {
                    "capabilities": client.get_agent_capabilities(),
                    "models": client.get_session_models(),
                    "modes": client.get_session_modes(),
                    "config_options": client.get_session_config_options(),
                },
            },
        )
        from .images import load_snapshots

        emit("stage", {"message": "Sending your prompt to the connected ACP agent"})
        reason = await client.send_prompt(request["prompt"], images=load_snapshots(request))
        if reason in {None, "error", "cancelled"}:
            raise RuntimeError("ACP did not complete the task: " + str(reason))
        result = {
            "status": "completed",
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
        await terminals.close()
        await client.stop()
