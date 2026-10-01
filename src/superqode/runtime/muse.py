"""Muse Code runtime over its native, line-framed Muse Session Protocol."""

from __future__ import annotations

import asyncio
import json
import secrets
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from .. import __version__
from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from ..harness.events import HarnessEvent
from ..providers.subscription_env import subscription_child_env
from .errors import RuntimeNotInstalledError


def _command_id() -> str:
    """UUIDv7 command IDs, including on Python versions without uuid.uuid7."""
    value = (int(time.time() * 1000) << 80) | (7 << 76)
    value |= secrets.randbits(12) << 64
    value |= (2 << 62) | secrets.randbits(62)
    return str(uuid.UUID(int=value))


def _arguments(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {"raw": raw}
    return value if isinstance(value, dict) else {"value": value}


class MuseRuntime:
    """Keep Muse's session, tools, sandbox and login in its own process."""

    name = "muse"
    harness_owner = "muse"

    def __init__(
        self,
        *,
        config: AgentConfig,
        approval_callback: Callable[[str, dict[str, Any]], bool] | None = None,
        **_unused: Any,
    ) -> None:
        self.config = config
        self._binary = shutil.which("muse")
        if not self._binary:
            raise RuntimeNotInstalledError(
                "Install Muse Code from https://dev.meta.ai, then muse login."
            )
        self._approval_callback = approval_callback
        self.session_id: str | None = None
        self._model = config.model
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None
        self._stderr_reader: asyncio.Task | None = None
        self._stderr = ""
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 0
        self._queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._write_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self._cancelled = False
        self._turn_id: str | None = None
        self._last_usage: dict[str, Any] = {}
        self._last_error: str | None = None
        self._tool_calls = 0
        self.stripped_api_keys: list[str] = []

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": self.name,
            "harness_owner": self.harness_owner,
            "session_id": self.session_id,
            "model": self._model or "Muse default",
            "structured_events": True,
            "authentication": "muse-login",
        }

    async def _write(self, frame: dict[str, Any]) -> None:
        async with self._write_lock:
            if self._process is None or self._process.stdin is None:
                raise RuntimeError("Muse session host is not running")
            self._process.stdin.write((json.dumps(frame) + "\n").encode())
            await self._process.stdin.drain()

    async def _request(self, method: str, params: dict[str, Any], *, command: bool = True) -> dict:
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        if command:
            params = {**params, "commandId": _command_id()}
        try:
            await self._write(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            return await asyncio.wait_for(future, timeout=30)
        finally:
            self._pending.pop(request_id, None)

    async def _read_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        while chunk := await self._process.stderr.read(4096):
            self._stderr = (self._stderr + chunk.decode(errors="replace"))[-8192:]

    async def _read_frames(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        failure = "Muse session host exited"
        try:
            while line := await self._process.stdout.readline():
                frame = json.loads(line)
                method = frame.get("method")
                if not method:
                    future = self._pending.get(frame.get("id"))
                    if future is not None and not future.done():
                        if "error" in frame:
                            future.set_exception(
                                RuntimeError(frame["error"].get("message", "Muse request failed"))
                            )
                        else:
                            future.set_result(frame.get("result", {}))
                    continue
                if "id" in frame:
                    # A presentation receipt is separate from the decision.
                    await self._write({"jsonrpc": "2.0", "id": frame["id"], "result": {}})
                if self._queue is not None:
                    self._queue.put_nowait((method, frame.get("params", {})))
        except asyncio.CancelledError:
            return
        except Exception as exc:
            failure = f"Muse protocol error: {exc}"
        failure += f". {self._stderr.strip()}" if self._stderr.strip() else ""
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError(failure))
        if self._queue is not None:
            await self._queue.put(("host/exited", {"message": failure}))

    async def _ensure_started(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        self._loop = asyncio.get_running_loop()
        env, self.stripped_api_keys = subscription_child_env("muse")
        # The wrapper otherwise launches its own hourly update worker.
        env["MUSE_UPDATE_INTERVAL_SECONDS"] = "disabled"
        self._stderr = ""
        self._process = await asyncio.create_subprocess_exec(
            self._binary,
            "serve",
            cwd=str(self.config.working_directory),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=4 * 1024 * 1024,
        )
        self._reader = asyncio.create_task(self._read_frames())
        self._stderr_reader = asyncio.create_task(self._read_stderr())
        try:
            await self._request(
                "initialize",
                {
                    "clientInfo": {"name": "superqode", "version": __version__},
                    "capabilities": {"userInputDialogs": False},
                },
                command=False,
            )
            await self._write({"jsonrpc": "2.0", "method": "initialized", "params": {}})
            if self.session_id:
                result = await self._request(
                    "session/resume", {"sessionId": self.session_id, "excludeItems": True}
                )
            else:
                params: dict[str, Any] = {
                    "workspaceRoot": str(self.config.working_directory.resolve()),
                    "approvalMode": "onRequest",
                }
                if self.config.model:
                    params["modelId"] = self.config.model
                result = await self._request("session/start", params)
            session = result["session"]
            self.session_id = session["sessionId"]
            self._model = session.get("modelId") or self._model
        except BaseException:
            await self.aclose()
            raise

    async def _approve(self, params: dict[str, Any]) -> None:
        allowed = False
        if self._approval_callback is not None:
            try:
                allowed = bool(
                    await asyncio.to_thread(
                        self._approval_callback, params["toolName"], _arguments(params["rawArgs"])
                    )
                )
            except Exception:
                allowed = False
        choices = params["availableChoices"]
        choice = next(
            (
                c
                for c in choices
                if c.get("decision") == ("approved" if allowed else "denied")
                and c.get("scope") == "once"
            ),
            None,
        )
        if choice is None:
            raise RuntimeError("Muse did not offer a supported approval decision")
        await self._request(
            "approval/decide",
            {
                "sessionId": self.session_id,
                "approvalId": params["approvalId"],
                "requirementId": params["currentRequirementId"],
                "choiceId": choice["choiceId"],
            },
        )

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        async with self._turn_lock:
            self.reset_cancellation()
            self._last_error = None
            self._last_usage = {}
            self._tool_calls = 0
            items: dict[str, dict] = {}
            text_by_id: dict[str, str] = {}
            approvals: set[str] = set()
            try:
                await self._ensure_started()
                self._queue = asyncio.Queue(maxsize=1024)
                ack = await self._request(
                    "turn/start",
                    {
                        "sessionId": self.session_id,
                        "input": [{"type": "text", "text": prompt}],
                    },
                )
                self._turn_id = ack["turnId"]
                while True:
                    method, params = await self._queue.get()
                    if method == "host/exited":
                        raise RuntimeError(params["message"])
                    if params.get("sessionId") != self.session_id:
                        continue
                    if method in {"approval/request", "approval/requested"}:
                        key = json.dumps(params["currentRequirementId"], sort_keys=True)
                        if key not in approvals:
                            approvals.add(key)
                            await self._approve(params)
                    elif method in {"item/started", "item/completed"}:
                        item = params["item"]
                        if item.get("turnId") != self._turn_id:
                            continue
                        item_id = item["itemId"]
                        items[item_id] = item
                        if item["kind"] == "agentMessage" and method == "item/completed":
                            final = item.get("text", "")
                            prior = text_by_id.get(item_id, "")
                            if final.startswith(prior) and final != prior:
                                yield HarnessEvent(
                                    type="model_delta", data={"text": final[len(prior) :]}
                                )
                            text_by_id[item_id] = final
                        elif item["kind"] == "toolCall":
                            args = _arguments(item.get("args", "{}"))
                            data = {
                                "tool_name": item.get("tool", "tool"),
                                "tool_call_id": item_id,
                                "args": args,
                            }
                            if method == "item/started":
                                self._tool_calls += 1
                                yield HarnessEvent(type="tool_start", data=data)
                            else:
                                yield HarnessEvent(
                                    type="tool_result",
                                    data={
                                        **data,
                                        "success": item["status"] == "completed",
                                        "output": item.get("visibleOutput", ""),
                                        "error": item.get("failureReason"),
                                    },
                                )
                    elif method == "item/delta":
                        item_id = params["itemId"]
                        if (
                            items.get(item_id, {}).get("kind") == "agentMessage"
                            and params.get("field", "text") == "text"
                        ):
                            text = params["delta"]
                            text_by_id[item_id] = text_by_id.get(item_id, "") + text
                            yield HarnessEvent(type="model_delta", data={"text": text})
                    elif method == "turn/completed" and params["turnId"] == self._turn_id:
                        self._last_usage = params.get("usage", {})
                        terminal = params["terminal"]
                        if terminal == "cancelled":
                            self._cancelled = True
                        if terminal not in {"completed", "cancelled"}:
                            self._last_error = (
                                params.get("error", {}).get("message")
                                or params.get("reason")
                                or f"Muse turn ended: {terminal}"
                            )
                        break
            except asyncio.CancelledError:
                self._cancelled = True
                await self.aclose()
                raise
            except Exception as exc:
                self._last_error = str(exc)
                await self.aclose()
            finally:
                self._queue = None
                self._turn_id = None
            if self._last_error and "not logged in" in self._last_error.lower():
                self._last_error = (
                    "Muse Code rejected its saved login. Open `muse` in a terminal, "
                    "run `/login`, then reconnect with `:connect muse`. "
                    "A detected credential does not guarantee a usable session."
                )
            yield HarnessEvent(
                type="turn_complete",
                data={
                    "status": "error"
                    if self._last_error
                    else "cancelled"
                    if self._cancelled
                    else "completed",
                    "error": self._last_error,
                    "usage": {
                        "input_tokens": self._last_usage.get("inputTokens", 0),
                        "output_tokens": self._last_usage.get("outputTokens", 0),
                    },
                },
            )

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta":
                yield event.data["text"]
        if self._last_error:
            raise RuntimeError(self._last_error)

    async def run(self, prompt: str) -> AgentResponse:
        content = "".join([text async for text in self.run_streaming(prompt)])
        return AgentResponse(
            content=content,
            messages=[AgentMessage(role="assistant", content=content)],
            tool_calls_made=self._tool_calls,
            iterations=1,
            stopped_reason="cancelled" if self._cancelled else "complete",
        )

    def cancel(self) -> None:
        self._cancelled = True
        if self._loop and self.session_id and self._turn_id:
            asyncio.run_coroutine_threadsafe(
                self._cancel_turn(
                    "turn/cancel",
                    {
                        "sessionId": self.session_id,
                        "turnId": self._turn_id,
                    },
                ),
                self._loop,
            )

    async def _cancel_turn(self, method: str, params: dict[str, Any]) -> None:
        try:
            await self._request(method, params)
        except Exception:
            await self.aclose()

    def reset_cancellation(self) -> None:
        self._cancelled = False

    async def aclose(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            if process.stdin:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        tasks = [t for t in (self._reader, self._stderr_reader) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._reader = self._stderr_reader = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError("Muse session host closed"))
