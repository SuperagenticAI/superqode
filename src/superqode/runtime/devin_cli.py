"""Cognition Devin CLI runtime driving ``devin --print``.

The official ``devin`` process owns sign-in and its own credential store.
SuperQode never reads, copies, or refreshes Devin tokens — it only launches the
binary and reads stdout.

Two things differ from the ACP path (``:connect acp devin``), which remains the
richer integration:

* ``--print`` emits plain prose, not structured tool calls, so ``metadata``
  reports ``structured_events: False``. Use ACP when you want diffs and
  permission requests surfaced in the TUI.
* A ``--print`` turn is unattended, so a permission prompt would hang forever
  with nobody to answer it. Devin's ``bypass`` mode is therefore the default
  here, paired with ``--sandbox`` wherever the platform supports it. Override
  both with ``SUPERQODE_DEVIN_CLI_PERMISSION_MODE`` and
  ``SUPERQODE_DEVIN_CLI_SANDBOX``.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from collections.abc import AsyncIterator
from typing import Any

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from .devin_status import INSTALL_HINT
from .errors import RuntimeNotInstalledError

from superqode.herdr import child_env

# Modes documented at https://docs.devin.ai/cli/reference/permissions
# ``dangerous`` is the CLI's own alias for ``bypass``.
PERMISSION_MODES = frozenset(
    {"normal", "accept-edits", "bypass", "dangerous", "autonomous", "plan"}
)

# Unattended turns cannot answer a prompt. ``bypass`` is the only documented
# mode that never asks; ``autonomous`` still prompts on edit/write, and
# ``normal`` prompts on every write and shell command.
DEFAULT_PERMISSION_MODE = "bypass"

# Keys a Devin session listing might use for its id (`devin -r brisk-otter`).
# Probed in order because the `devin list --format json` schema is not
# documented; an unrecognised shape falls back to `--continue`.
_SESSION_ID_KEYS = ("id", "session_id", "sessionId", "name", "slug")


def sandbox_supported() -> bool:
    """Whether ``devin --sandbox`` can start on this machine.

    Devin refuses to run rather than dropping isolation, so an unsupported
    platform must not be sent the flag. Windows is unsupported outright and
    Linux needs bubblewrap plus socat; macOS is always supported.
    """
    if sys.platform == "win32":
        return False
    if sys.platform == "darwin":
        return True
    return bool(shutil.which("bwrap") and shutil.which("socat"))


class DevinCLIRuntime:
    """Drive ``devin --print`` while leaving authentication inside Devin's CLI."""

    name = "devin-cli"
    harness_owner = "devin"

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": self.name,
            "harness_owner": self.harness_owner,
            "authentication": "devin-cli-login",
            "structured_events": False,
            "model": self.config.model or "cli-default",
            "permission_mode": self._permission_mode,
            "sandbox": self._sandbox,
            "session_id": self._session_id,
        }

    def __init__(self, *, config: AgentConfig | None = None, **_unused: Any) -> None:
        if config is None:
            raise ValueError("DevinCLIRuntime requires 'config'")
        self.config = config
        self._devin = shutil.which("devin")
        if not self._devin:
            raise RuntimeNotInstalledError(f"Devin CLI was not found. To use it, {INSTALL_HINT}.")
        self._permission_mode = _coerce_permission_mode(
            os.environ.get("SUPERQODE_DEVIN_CLI_PERMISSION_MODE")
        )
        self._sandbox = _coerce_sandbox(os.environ.get("SUPERQODE_DEVIN_CLI_SANDBOX"))
        self._session_id: str | None = None
        self._started_session = False
        self._process: asyncio.subprocess.Process | None = None
        self._cancelled = False
        self._turn_lock = asyncio.Lock()

    def _command(self, prompt: str) -> list[str]:
        command = [self._devin]
        if self._sandbox:
            command.append("--sandbox")
        command.extend(["--permission-mode", self._permission_mode])
        if self.config.model:
            command.extend(["--model", self.config.model])
        if self._session_id:
            command.extend(["--resume", self._session_id])
        elif self._started_session:
            # The id could not be resolved, so fall back to Devin's own notion
            # of the most recent session rather than starting a fresh one.
            command.append("--continue")
        # `--` ends flag parsing so a prompt beginning with `-` is still a
        # prompt. This is Devin's documented single-turn form.
        command.extend(["--print", "--", prompt])
        return command

    async def _capture_session_id(self) -> None:
        """Pin the session this runtime just used, so later turns resume it.

        Best effort: any unexpected output leaves the id unset and the next
        turn falls back to ``--continue``.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                self._devin,
                "list",
                "--format",
                "json",
                cwd=str(self.config.working_directory),
                env=child_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            return
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return
        if process.returncode:
            return
        try:
            payload = json.loads((stdout or b"").decode(errors="replace"))
        except ValueError:
            return
        if isinstance(payload, dict):
            payload = payload.get("sessions") or payload.get("data") or []
        if not isinstance(payload, list) or not payload:
            return
        newest = payload[0]
        if not isinstance(newest, dict):
            return
        for key in _SESSION_ID_KEYS:
            value = newest.get(key)
            if isinstance(value, str) and value.strip():
                self._session_id = value.strip()
                return

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        async with self._turn_lock:
            self.reset_cancellation()
            process = await asyncio.create_subprocess_exec(
                *self._command(prompt),
                cwd=str(self.config.working_directory),
                env=child_env(),
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
                    detail or "Devin CLI failed. Run `devin auth login` to sign in, then retry."
                )
            if not self._cancelled and (chunks or returncode == 0):
                self._started_session = True
                await self._capture_session_id()

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

    def set_model(self, model: str | None) -> None:
        self.config.model = _safe_cli_value(model, setting="model") or ""

    def set_permission_mode(self, mode: str | None) -> None:
        self._permission_mode = _coerce_permission_mode(mode)

    @property
    def permission_mode(self) -> str:
        return self._permission_mode

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def new_session(self) -> None:
        """Drop session continuity so the next turn starts fresh."""
        self._session_id = None
        self._started_session = False


def _safe_cli_value(value: str | None, *, setting: str) -> str | None:
    normalized = str(value or "").strip()
    if normalized.lower() in {"", "auto", "default", "none"}:
        return None
    if normalized.startswith("-") or any(char in normalized for char in "\x00\r\n"):
        raise ValueError(f"invalid Devin CLI {setting}")
    return normalized


def _coerce_permission_mode(mode: str | None) -> str:
    normalized = _safe_cli_value(mode, setting="permission mode")
    if normalized is None:
        return DEFAULT_PERMISSION_MODE
    normalized = normalized.lower().replace("_", "-")
    if normalized not in PERMISSION_MODES:
        allowed = ", ".join(sorted(PERMISSION_MODES))
        raise ValueError(f"Devin permission mode must be one of: {allowed}")
    return normalized


def _coerce_sandbox(value: str | None) -> bool:
    """Resolve the sandbox setting, never enabling it where Devin cannot start."""
    normalized = str(value or "").strip().lower()
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        # An explicit request still loses to platform support, because Devin
        # refuses to start rather than running unsandboxed.
        return sandbox_supported()
    return sandbox_supported()


__all__ = [
    "DevinCLIRuntime",
    "DEFAULT_PERMISSION_MODE",
    "PERMISSION_MODES",
    "sandbox_supported",
]
