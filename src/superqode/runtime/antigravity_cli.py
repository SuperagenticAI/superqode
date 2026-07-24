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
from .antigravity_status import MINIMUM_ANTIGRAVITY_CLI_VERSION, version_tuple
from .errors import RuntimeNotInstalledError

_MINIMUM_VERSION = MINIMUM_ANTIGRAVITY_CLI_VERSION
_version_tuple = version_tuple


class AntigravityCLIRuntime:
    """Drive ``agy --print`` while leaving authentication inside Google's CLI."""

    name = "antigravity-cli"
    harness_owner = "antigravity"

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": self.name,
            "harness_owner": self.harness_owner,
            "authentication": "google-sign-in",
            "structured_events": False,
            "model": self.config.model or "cli-default",
            "agent": self._agent_name,
            "reasoning_effort": self._reasoning_effort,
            "project_id": self._project_id,
            "conversation_id": self._conversation_id,
        }

    def __init__(self, *, config: AgentConfig | None = None, **_unused: Any) -> None:
        if config is None:
            raise ValueError("AntigravityCLIRuntime requires 'config'")
        self.config = config
        self._agy = shutil.which("agy")
        if not self._agy:
            raise RuntimeNotInstalledError(
                "Antigravity CLI was not found. Install it from "
                "https://antigravity.google/docs/cli-install"
            )
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

    def _command(self, prompt: str) -> list[str]:
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
            command.extend(["--model", self.config.model])
        if self._agent_name:
            command.extend(["--agent", self._agent_name])
        if self._reasoning_effort:
            command.extend(["--effort", self._reasoning_effort])
        command.extend(["--print", prompt])
        return command

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

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        async with self._turn_lock:
            self.reset_cancellation()
            await self._check_version()
            process = await asyncio.create_subprocess_exec(
                *self._command(prompt),
                cwd=str(self.config.working_directory),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._process = process
            chunks: list[str] = []
            assert process.stdout is not None
            stderr_task = asyncio.create_task(self._read_bounded_stderr(process.stderr))
            try:
                while True:
                    raw = await process.stdout.read(4096)
                    if not raw:
                        break
                    text = raw.decode(errors="replace")
                    chunks.append(text)
                    yield text
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
            if not self._cancelled and (chunks or returncode == 0):
                self._capture_workspace_conversation()

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
        chunks = [chunk async for chunk in self.run_streaming(prompt)]
        content = "".join(chunks)
        return AgentResponse(
            content=content,
            messages=[
                AgentMessage(role="user", content=prompt),
                AgentMessage(role="assistant", content=content),
            ],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="cancelled" if self._cancelled else "complete",
            error=None,
        )

    def cancel(self) -> None:
        self._cancelled = True
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()

    def reset_cancellation(self) -> None:
        self._cancelled = False

    def set_agent(self, agent: str | None) -> None:
        self._agent_name = _safe_cli_value(agent, setting="agent")

    @property
    def agent_name(self) -> str | None:
        return self._agent_name

    def set_model(self, model: str | None) -> None:
        self.config.model = _safe_cli_value(model, setting="model") or ""

    def set_reasoning_effort(self, effort: str | None) -> None:
        normalized = _coerce_cli_effort(effort)
        # A prior version probe may have run before an effort was selected.
        if normalized and self._cli_version is not None and self._cli_version < (1, 1, 5):
            raise RuntimeError("agy 1.1.5 or newer is required for reasoning effort")
        self._reasoning_effort = normalized

    @property
    def reasoning_effort(self) -> str | None:
        return self._reasoning_effort


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
    allowed = {"low", "medium", "high"}
    if normalized not in allowed:
        raise ValueError("agy effort must be auto, low, medium, or high")
    return normalized


__all__ = ["AntigravityCLIRuntime"]
