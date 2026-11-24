"""Google Antigravity CLI runtime using the user's Google Sign-In.

The official ``agy`` process owns OAuth and reads its session from the OS
keyring. SuperQode never reads, copies, or refreshes Google credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from ..harness.events import HarnessEvent
from .antigravity_status import MINIMUM_ANTIGRAVITY_CLI_VERSION, version_tuple
from .errors import RuntimeNotInstalledError

from superqode.herdr import child_env
from superqode.vendor_command_help import antigravity_model_for_effort

_MINIMUM_VERSION = MINIMUM_ANTIGRAVITY_CLI_VERSION
_STREAM_JSON_VERSION = (1, 5, 0)
_STDOUT_LIMIT = 16 * 1024 * 1024
_version_tuple = version_tuple


class AntigravityCLIRuntime:
    """Drive ``agy`` with structured NDJSON streaming while leaving auth in Google's CLI."""

    name = "antigravity-cli"
    harness_owner = "antigravity"

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": self.name,
            "harness_owner": self.harness_owner,
            "authentication": "google-sign-in",
            "structured_events": True,
            "model": self.config.model or "cli-default",
            "agent": self._agent_name,
            "reasoning_effort": self._reasoning_effort,
            "project_id": self._project_id,
            "conversation_id": self._conversation_id,
        }

    @property
    def session_id(self) -> str | None:
        return self._conversation_id

    @property
    def thread_id(self) -> str | None:
        return self._conversation_id

    def resume_thread(self, session_id: str) -> None:
        conversation = _safe_cli_value(session_id, setting="conversation")
        if conversation != self._conversation_id:
            self._conversation_id = conversation
            self._persistent_dirty = True

    def __init__(
        self,
        *,
        config: AgentConfig | None = None,
        persistent: bool = True,
        **_unused: Any,
    ) -> None:
        if config is None:
            raise ValueError("AntigravityCLIRuntime requires 'config'")
        self.config = config
        self._agy = shutil.which("agy")
        if not self._agy:
            raise RuntimeNotInstalledError(
                "Antigravity CLI was not found. Install it from "
                "https://antigravity.google/docs/cli-install"
            )
        self._persistent = bool(persistent)
        self._checked_version = False
        self._cli_version: tuple[int, ...] | None = None
        self._project_id = self._workspace_project_id()
        self._conversation_id: str | None = None
        self._agent_name = _safe_cli_value(
            os.environ.get("SUPERQODE_ANTIGRAVITY_CLI_AGENT"), setting="agent"
        )
        self._reasoning_effort = _coerce_cli_effort(
            config.reasoning_effort or os.environ.get("SUPERQODE_ANTIGRAVITY_CLI_EFFORT")
        )
        self._process: asyncio.subprocess.Process | None = None
        self._persistent_process: asyncio.subprocess.Process | None = None
        self._persistent_stderr_task: asyncio.Task[bytes] | None = None
        self._persistent_dirty = False
        self._persistent_signature: tuple[str | None, ...] | None = None
        self._cancelled = False
        self._turn_lock = asyncio.Lock()

    async def _check_version(self) -> None:
        if self._checked_version:
            return
        process = await asyncio.create_subprocess_exec(
            self._agy,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=3.0)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError(
                "Timed out while checking `agy --version`; run `agy update`"
            ) from exc
        text = (stdout or stderr).decode(errors="replace").strip()
        version = _version_tuple(text)
        if process.returncode or version is None:
            raise RuntimeError(
                f"Could not determine Antigravity CLI version: {text or 'no output'}"
            )
        if version < _MINIMUM_VERSION:
            raise RuntimeError(
                f"Antigravity CLI {text} is too old for subprocess use. "
                "Run `agy update`; SuperQode requires 1.1.1 or newer because that release "
                "fixes --print hangs and error exit codes."
            )
        if self._reasoning_effort and version < (1, 1, 5):
            raise RuntimeError(
                f"Antigravity CLI {text} does not support --effort. "
                "Run `agy update` or set effort to auto."
            )
        self._cli_version = version
        self._checked_version = True

    def _base_flags(self) -> list[str]:
        command = [
            self._agy,
            "--sandbox",
            "--print-timeout",
            "10m",
        ]
        if self._conversation_id:
            command.extend(["--conversation", self._conversation_id])
        elif self._project_id:
            command.extend(["--project", self._project_id])
        else:
            command.append("--new-project")
        if self.config.model:
            model = antigravity_model_for_effort(self.config.model, self._reasoning_effort)
            command.extend(["--model", model])
        if self._agent_name:
            command.extend(["--agent", self._agent_name])
        if self._reasoning_effort:
            command.extend(["--effort", self._reasoning_effort])
        return command

    def _command(self, prompt: str, *, stream_json: bool = True) -> list[str]:
        command = self._base_flags()
        if stream_json and (self._cli_version is None or self._cli_version >= _STREAM_JSON_VERSION):
            command.extend(["--output-format", "stream-json"])
        command.extend(["--print", prompt])
        return command

    def _persistent_command(self) -> list[str]:
        command = self._base_flags()
        command.extend(["--input-format", "stream-json", "--output-format", "stream-json"])
        return command

    def _session_signature(self) -> tuple[str | None, ...]:
        return (
            self.config.model or None,
            self._agent_name,
            self._reasoning_effort,
            self._project_id,
        )

    def _supports_stream_json(self) -> bool:
        return self._cli_version is None or self._cli_version >= _STREAM_JSON_VERSION

    def _workspace_project_id(self) -> str | None:
        """Return an Antigravity project that explicitly contains this workspace."""
        workspace = Path(self.config.working_directory).expanduser().resolve()
        metadata_dir = workspace / ".antigravitycli"
        for candidate in sorted(metadata_dir.glob("*.json")):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            resources = data.get("projectResources", {}).get("resources", [])
            for resource in resources:
                uri = resource.get("gitFolder", {}).get("folderUri", "")
                if uri.startswith("file://"):
                    try:
                        resource_path = Path(uri.removeprefix("file://")).resolve()
                    except OSError:
                        continue
                    if resource_path == workspace:
                        return str(data.get("id") or candidate.stem)
        return None

    def _capture_workspace_conversation(self) -> None:
        """Capture only the latest conversation mapped to this exact workspace."""
        cache = Path.home() / ".gemini" / "antigravity-cli" / "cache" / "last_conversations.json"
        try:
            mappings = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        workspace = str(Path(self.config.working_directory).expanduser().resolve())
        conversation_id = mappings.get(workspace)
        if isinstance(conversation_id, str) and conversation_id.strip():
            self._conversation_id = conversation_id.strip()

    async def _close_persistent_process(self) -> None:
        process, self._persistent_process = self._persistent_process, None
        stderr_task, self._persistent_stderr_task = self._persistent_stderr_task, None
        self._persistent_dirty = False
        self._persistent_signature = None
        if process is not None:
            if process.stdin is not None and not process.stdin.is_closing():
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
            try:
                await stderr_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _ensure_persistent_process(self) -> asyncio.subprocess.Process:
        signature = self._session_signature()
        if (
            self._persistent_process is not None
            and self._persistent_process.returncode is None
            and not self._persistent_dirty
            and self._persistent_signature == signature
        ):
            return self._persistent_process
        await self._close_persistent_process()
        process = await asyncio.create_subprocess_exec(
            *self._persistent_command(),
            cwd=str(self.config.working_directory),
            env=child_env(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STDOUT_LIMIT,
        )
        self._persistent_process = process
        self._persistent_stderr_task = asyncio.create_task(
            self._read_bounded_stderr(process.stderr)
        )
        self._persistent_dirty = False
        self._persistent_signature = signature
        return process

    def _parse_stream_line(
        self, raw_line: str, state: dict[str, Any]
    ) -> tuple[list[HarnessEvent], bool]:
        """Parse one NDJSON line (or plain text fallback) into HarnessEvents."""
        stripped = raw_line.strip()
        if not stripped:
            return [], False
        try:
            payload = json.loads(stripped)
        except ValueError:
            # Older agy builds or test doubles may emit plain text.
            state["saw_text_delta"] = True
            return [HarnessEvent(type="model_delta", data={"text": raw_line})], False
        if not isinstance(payload, dict) or "event" not in payload:
            state["saw_text_delta"] = True
            return [HarnessEvent(type="model_delta", data={"text": raw_line})], False

        events: list[HarnessEvent] = []
        kind = str(payload.get("event") or "")
        conv_id = payload.get("conversation_id")
        if isinstance(conv_id, str) and conv_id.strip():
            self._conversation_id = conv_id.strip()

        if kind == "init":
            init_data = payload.get("init") if isinstance(payload.get("init"), dict) else {}
            if not state["emitted_request"]:
                state["emitted_request"] = True
                events.append(
                    HarnessEvent(
                        type="model_request",
                        data={
                            "runtime": self.name,
                            "model": init_data.get("model") or self.config.model or "cli-default",
                            "conversation_id": self._conversation_id,
                        },
                    )
                )
            return events, False

        if kind == "step_update":
            step = (
                payload.get("step_update") if isinstance(payload.get("step_update"), dict) else {}
            )
            step_conv = step.get("conversation_id")
            if isinstance(step_conv, str) and step_conv.strip():
                self._conversation_id = step_conv.strip()
            step_type = str(step.get("step_type") or "")
            step_state = str(step.get("state") or "").upper()
            step_index = step.get("step_index")

            thinking_delta = step.get("thinking_delta") or step.get("thought_delta")
            if not thinking_delta and step_type in {"thinking", "thought"}:
                thinking_delta = step.get("text_delta") or step.get("text")
            if isinstance(thinking_delta, str) and thinking_delta:
                events.append(HarnessEvent(type="thinking", data={"text": thinking_delta}))

            if step_type == "tool":
                tool_info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
                tool_name = str(step.get("tool_name") or tool_info.get("name") or "tool")
                call_id = str(
                    step.get("tool_call_id") or tool_info.get("id") or f"agy-step-{step_index}"
                )
                if call_id not in state["seen_tools"]:
                    state["seen_tools"].add(call_id)
                    raw_args = tool_info.get("parameters") or tool_info.get("args") or {}
                    args = dict(raw_args) if isinstance(raw_args, dict) else {}
                    events.append(
                        HarnessEvent(
                            type="tool_call",
                            data={
                                "tool_name": tool_name,
                                "tool_call_id": call_id,
                                "args": args,
                            },
                        )
                    )
                if step_state in {"DONE", "ERROR", "FAILED", "CANCELLED"}:
                    err = step.get("error") or tool_info.get("error")
                    success = step_state == "DONE" and not err
                    events.append(
                        HarnessEvent(
                            type="tool_result",
                            data={
                                "tool_name": tool_name,
                                "tool_call_id": call_id,
                                "success": success,
                                "output": tool_info.get("output"),
                                "error": str(err) if err else None,
                                "duration_seconds": step.get("duration_seconds"),
                            },
                        )
                    )
            elif step_type not in {"user_input", "thinking", "thought"}:
                text_delta = step.get("text_delta")
                if isinstance(text_delta, str) and text_delta:
                    state["saw_text_delta"] = True
                    events.append(HarnessEvent(type="model_delta", data={"text": text_delta}))
            return events, False

        if kind == "result":
            res = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            res_conv = res.get("conversation_id")
            if isinstance(res_conv, str) and res_conv.strip():
                self._conversation_id = res_conv.strip()
            status = str(res.get("status") or "SUCCESS").upper()
            error = str(res.get("error") or "").strip()
            if status in {"ERROR", "FAILED"} and not self._cancelled:
                raise RuntimeError(
                    error
                    or "Antigravity CLI failed. Run `agy` once to complete Google Sign-In, "
                    "then retry :connect antigravity."
                )
            response_text = res.get("response")
            if not state["saw_text_delta"] and isinstance(response_text, str) and response_text:
                state["saw_text_delta"] = True
                events.append(HarnessEvent(type="model_delta", data={"text": response_text}))
            usage = dict(res.get("usage") or {}) if isinstance(res.get("usage"), dict) else {}
            state["completed"] = True
            state["usage"] = usage
            events.append(
                HarnessEvent(
                    type="turn_complete",
                    data={
                        "status": "cancelled" if self._cancelled else "completed",
                        "conversation_id": self._conversation_id,
                        "usage": usage,
                        "duration_seconds": res.get("duration_seconds"),
                    },
                )
            )
            events.append(
                HarnessEvent(
                    type="model_result",
                    data={
                        "runtime": self.name,
                        "conversation_id": self._conversation_id,
                        "usage": usage,
                    },
                )
            )
            return events, True

        return events, False

    async def _run_persistent_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        reusing = (
            self._persistent_process is not None
            and self._persistent_process.returncode is None
            and not self._persistent_dirty
            and self._persistent_signature == self._session_signature()
        )
        process = await self._ensure_persistent_process()
        self._process = process
        assert process.stdin is not None and process.stdout is not None
        payload = json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"
        state: dict[str, Any] = {
            "emitted_request": False,
            "saw_text_delta": False,
            "seen_tools": set(),
            "completed": False,
            "usage": {},
        }
        try:
            process.stdin.write(payload.encode("utf-8"))
            await process.stdin.drain()
            if reusing:
                state["emitted_request"] = True
                yield HarnessEvent(
                    type="model_request",
                    data={
                        "runtime": self.name,
                        "model": self.config.model or "cli-default",
                        "conversation_id": self._conversation_id,
                    },
                )
            while True:
                if self._cancelled:
                    break
                raw = await process.stdout.readline()
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace")
                events, terminal = self._parse_stream_line(text, state)
                for event in events:
                    yield event
                if terminal:
                    break
        finally:
            self._process = None
            if self._cancelled or not state["completed"] or process.returncode is not None:
                await self._close_persistent_process()

        if not state["completed"] and not self._cancelled:
            raise _PersistentStreamUnavailable("Antigravity persistent stream ended before result")

    async def _run_oneshot_events(
        self, prompt: str, *, stream_json: bool = True
    ) -> AsyncIterator[HarnessEvent]:
        process = await asyncio.create_subprocess_exec(
            *self._command(prompt, stream_json=stream_json),
            cwd=str(self.config.working_directory),
            env=child_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STDOUT_LIMIT,
        )
        self._process = process
        assert process.stdout is not None
        stderr_task = asyncio.create_task(self._read_bounded_stderr(process.stderr))
        state: dict[str, Any] = {
            "emitted_request": False,
            "saw_text_delta": False,
            "seen_tools": set(),
            "completed": False,
            "usage": {},
        }
        try:
            while True:
                if self._cancelled:
                    break
                raw = await process.stdout.readline()
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace")
                if stream_json:
                    events, terminal = self._parse_stream_line(text, state)
                    for event in events:
                        yield event
                    if terminal:
                        break
                else:
                    state["saw_text_delta"] = True
                    yield HarnessEvent(type="model_delta", data={"text": text})
            returncode = await process.wait()
            stderr = await stderr_task
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            self._process = None
            if not stderr_task.done():
                stderr_task.cancel()
        if returncode and not self._cancelled:
            detail = stderr.decode(errors="replace").strip()
            raise RuntimeError(
                detail
                or "Antigravity CLI failed. Run `agy` once to complete Google Sign-In, "
                "then retry :connect antigravity."
            )
        if (
            not self._cancelled
            and not self._conversation_id
            and (state["saw_text_delta"] or returncode == 0)
        ):
            self._capture_workspace_conversation()
        if not state["completed"]:
            yield HarnessEvent(
                type="turn_complete",
                data={
                    "status": "cancelled" if self._cancelled else "completed",
                    "conversation_id": self._conversation_id,
                    "usage": state["usage"],
                },
            )
            yield HarnessEvent(
                type="model_result",
                data={
                    "runtime": self.name,
                    "conversation_id": self._conversation_id,
                    "usage": state["usage"],
                },
            )

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        async with self._turn_lock:
            self.reset_cancellation()
            await self._check_version()
            use_stream_json = self._supports_stream_json()
            if self._persistent and use_stream_json:
                emitted_any = False
                try:
                    async for event in self._run_persistent_events(prompt):
                        emitted_any = True
                        yield event
                    return
                except _PersistentStreamUnavailable:
                    if emitted_any or self._cancelled:
                        raise
                    # Fall back cleanly to one-shot stream-json if the installed
                    # binary closed early before answering.
                    self._persistent = False
            async for event in self._run_oneshot_events(prompt, stream_json=use_stream_json):
                yield event

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta" and event.data.get("text"):
                yield str(event.data["text"])

    @staticmethod
    async def _read_bounded_stderr(
        stream: asyncio.StreamReader | None, *, limit: int = 64 * 1024
    ) -> bytes:
        """Drain stderr concurrently while retaining only the latest diagnostics."""
        if stream is None:
            return b""
        buffered = bytearray()
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            buffered.extend(chunk)
            if len(buffered) > limit:
                del buffered[:-limit]
        return bytes(buffered)

    async def run(self, prompt: str) -> AgentResponse:
        chunks: list[str] = []
        tool_calls = 0
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta" and event.data.get("text"):
                chunks.append(str(event.data["text"]))
            elif event.type == "tool_call":
                tool_calls += 1
        content = "".join(chunks)
        return AgentResponse(
            content=content,
            messages=[
                AgentMessage(role="user", content=prompt),
                AgentMessage(role="assistant", content=content),
            ],
            tool_calls_made=tool_calls,
            iterations=1,
            stopped_reason="cancelled" if self._cancelled else "complete",
            error=None,
        )

    def cancel(self) -> None:
        self._cancelled = True
        for proc in (self._process, self._persistent_process):
            if proc is not None and proc.returncode is None:
                proc.terminate()

    def reset_cancellation(self) -> None:
        self._cancelled = False

    async def aclose(self) -> None:
        await self._close_persistent_process()

    def set_agent(self, agent: str | None) -> None:
        updated = _safe_cli_value(agent, setting="agent")
        if updated != self._agent_name:
            self._agent_name = updated
            self._persistent_dirty = True

    @property
    def agent_name(self) -> str | None:
        return self._agent_name

    def set_model(self, model: str | None) -> None:
        updated = _safe_cli_value(model, setting="model") or ""
        if updated != self.config.model:
            self.config.model = updated
            self._persistent_dirty = True

    def set_reasoning_effort(self, effort: str | None) -> None:
        normalized = _coerce_cli_effort(effort)
        # A prior version probe may have run before an effort was selected.
        if normalized and self._cli_version is not None and self._cli_version < (1, 1, 5):
            raise RuntimeError("agy 1.1.5 or newer is required for reasoning effort")
        if normalized != self._reasoning_effort:
            self._reasoning_effort = normalized
            self._persistent_dirty = True

    @property
    def reasoning_effort(self) -> str | None:
        return self._reasoning_effort


class _PersistentStreamUnavailable(RuntimeError):
    """Raised when persistent stream-json closes before delivering a result."""


def _safe_cli_value(value: str | None, *, setting: str) -> str | None:
    normalized = str(value or "").strip()
    if normalized.lower() in {"", "auto", "default", "none"}:
        return None
    if normalized.startswith("-") or any(char in normalized for char in "\x00\r\n"):
        raise ValueError(f"invalid Antigravity CLI {setting}")
    return normalized


def _coerce_cli_effort(effort: str | None) -> str | None:
    normalized = _safe_cli_value(effort, setting="effort")
    if normalized is None:
        return None
    normalized = normalized.lower().replace("_", "-")
    allowed = {"low", "medium", "high", "xhigh", "max"}
    if normalized not in allowed:
        raise ValueError("agy effort must be auto, low, medium, high, xhigh, or max")
    return normalized


__all__ = ["AntigravityCLIRuntime"]
