"""Google Antigravity CLI runtime using the user's Google Sign-In.

The official ``agy`` process owns OAuth and reads its session from the OS
keyring. SuperQode never reads, copies, or refreshes Google credentials.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from .errors import RuntimeNotInstalledError

_MINIMUM_VERSION = (1, 1, 1)


def _version_tuple(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(map(int, match.groups())) if match else None


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
        self._project_id = self._workspace_project_id()
        self._conversation_id: str | None = None
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
        stdout, stderr = await process.communicate()
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
            while True:
                raw = await process.stdout.read(4096)
                if not raw:
                    break
                text = raw.decode(errors="replace")
                chunks.append(text)
                yield text
            stderr = b""
            if process.stderr is not None:
                stderr = await process.stderr.read()
            returncode = await process.wait()
            self._process = None
            if returncode and not self._cancelled:
                detail = stderr.decode(errors="replace").strip()
                raise RuntimeError(
                    detail
                    or "Antigravity CLI failed. Run `agy` once to complete Google Sign-In, "
                    "then retry :connect antigravity."
                )
            if not self._cancelled and (chunks or returncode == 0):
                self._capture_workspace_conversation()

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


__all__ = ["AntigravityCLIRuntime"]
