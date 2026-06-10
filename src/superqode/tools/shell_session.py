"""Persistent interactive shell sessions.

The plain ``bash`` tool runs one command to completion. That cannot drive
REPLs (python, node, psql), dev servers, debuggers, or anything that asks a
question on stdin. Shell sessions solve this: processes run inside a PTY,
stay alive across tool calls, and the model polls output or writes input
with a bounded wait each call.

The surface is one ``shell_session`` tool with an
``action`` parameter (open/write/poll/list/kill). Output accumulates in a
bounded buffer drained per call; oversized output goes through the standard
spill-to-disk truncation so nothing is lost. Sessions are reaped when their
process exits and killed at interpreter shutdown so no orphan REPLs outlive
superqode.

PTY allocation is POSIX-only; on other platforms sessions fall back to
pipes (line-buffered tools still work; full-screen TUIs won't).
"""

from __future__ import annotations

import asyncio
import atexit
import os
import shlex
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import Tool, ToolContext, ToolResult
from .output_spill import truncate_with_spill
from .validation import validate_working_dir_parameter

DEFAULT_YIELD_MS = 1500
MAX_YIELD_MS = 30_000
MAX_SESSIONS = 16
# Per-session buffer hard cap; beyond it the oldest bytes are dropped.
BUFFER_CAP_BYTES = 2 * 1024 * 1024


@dataclass
class _Session:
    session_id: str
    command: str
    cwd: str
    process: subprocess.Popen
    master_fd: Optional[int]
    started_at: float = field(default_factory=time.time)
    buffer: bytearray = field(default_factory=bytearray)
    read_offset: int = 0
    dropped_bytes: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    reader: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    @property
    def exit_code(self) -> Optional[int]:
        return self.process.poll()

    def append(self, chunk: bytes) -> None:
        with self.lock:
            self.buffer.extend(chunk)
            overflow = len(self.buffer) - BUFFER_CAP_BYTES
            if overflow > 0:
                del self.buffer[:overflow]
                self.dropped_bytes += overflow
                self.read_offset = max(0, self.read_offset - overflow)

    def drain_new_output(self) -> str:
        with self.lock:
            chunk = bytes(self.buffer[self.read_offset :])
            self.read_offset = len(self.buffer)
        return chunk.decode("utf-8", errors="replace")

    def write_input(self, text: str) -> None:
        data = text.encode("utf-8", errors="replace")
        if self.master_fd is not None:
            os.write(self.master_fd, data)
        elif self.process.stdin:
            self.process.stdin.write(data)
            self.process.stdin.flush()
        else:
            raise RuntimeError("session has no writable stdin")

    def kill(self) -> None:
        if not self.running:
            return
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            else:
                self.process.terminate()
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                else:
                    self.process.kill()
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def close(self) -> None:
        self.kill()
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None


_sessions: Dict[str, _Session] = {}
_sessions_lock = threading.Lock()


def _cleanup_all_sessions() -> None:
    with _sessions_lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for session in sessions:
        session.close()


atexit.register(_cleanup_all_sessions)


def _reap_exited() -> None:
    """Drop sessions whose process exited and whose output was fully drained."""
    with _sessions_lock:
        for sid in list(_sessions):
            session = _sessions[sid]
            if not session.running and session.read_offset >= len(session.buffer):
                session.close()
                del _sessions[sid]


def _spawn(command: str, cwd: Path) -> _Session:
    from .env_policy import build_shell_env

    session_id = uuid.uuid4().hex[:8]
    env = build_shell_env() or dict(os.environ)
    env.setdefault("TERM", "dumb")  # discourage full-screen redraws in REPLs
    master_fd: Optional[int] = None

    if os.name == "posix":
        import pty

        master_fd, slave_fd = pty.openpty()
        process = subprocess.Popen(
            command,
            shell=True,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=str(cwd),
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave_fd)
    else:  # pragma: no cover - windows fallback
        process = subprocess.Popen(
            command,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(cwd),
            env=env,
        )

    session = _Session(
        session_id=session_id,
        command=command,
        cwd=str(cwd),
        process=process,
        master_fd=master_fd,
    )

    def read_loop() -> None:
        if session.master_fd is not None:
            while True:
                try:
                    chunk = os.read(session.master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                session.append(chunk)
        elif process.stdout is not None:  # pragma: no cover - windows fallback
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                session.append(chunk)

    session.reader = threading.Thread(target=read_loop, daemon=True)
    session.reader.start()
    return session


def _get_session(session_id: str) -> Optional[_Session]:
    with _sessions_lock:
        return _sessions.get(session_id)


async def _wait_for_output(session: _Session, yield_ms: int) -> None:
    """Wait up to ``yield_ms`` for the session to produce output or exit.

    Returns early once output has settled (no new bytes for 300ms) so quick
    commands don't burn the full wait.
    """
    deadline = time.monotonic() + yield_ms / 1000.0
    baseline = len(session.buffer)
    quiet_since: Optional[float] = time.monotonic() if baseline > session.read_offset else None
    while time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        if not session.running:
            await asyncio.sleep(0.1)  # let the reader drain the tail
            return
        if len(session.buffer) != baseline:
            baseline = len(session.buffer)
            quiet_since = time.monotonic()
        elif quiet_since is not None and time.monotonic() - quiet_since > 0.3:
            return  # output settled - return early instead of burning the full wait


class ShellSessionTool(Tool):
    """Interactive, persistent shell sessions (REPLs, servers, debuggers)."""

    @property
    def name(self) -> str:
        return "shell_session"

    @property
    def description(self) -> str:
        return (
            "Run and interact with persistent shell processes (REPLs, dev "
            "servers, debuggers, commands that prompt for input). Actions: "
            "'open' starts a process and returns a session_id plus initial "
            "output; 'write' sends input to its stdin (a trailing newline is "
            "added unless you set append_newline=false); 'poll' returns new "
            "output since the last call; 'list' shows sessions; 'kill' stops "
            "one. Each call waits up to yield_ms (default 1500) for output. "
            "Use the regular bash tool for one-shot commands."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["open", "write", "poll", "list", "kill"],
                    "description": "What to do.",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to start (action=open).",
                },
                "session_id": {
                    "type": "string",
                    "description": "Target session (write/poll/kill).",
                },
                "input": {
                    "type": "string",
                    "description": "Text to send to stdin (action=write).",
                },
                "append_newline": {
                    "type": "boolean",
                    "description": "Append a newline to input (default true).",
                },
                "yield_ms": {
                    "type": "integer",
                    "description": f"How long to wait for output, ms (default {DEFAULT_YIELD_MS}, max {MAX_YIELD_MS}).",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for the new process (action=open).",
                },
            },
            "required": ["action"],
        }

    @staticmethod
    def _clamp_yield(args: Dict[str, Any]) -> int:
        try:
            value = int(args.get("yield_ms") or DEFAULT_YIELD_MS)
        except (TypeError, ValueError):
            value = DEFAULT_YIELD_MS
        return max(100, min(value, MAX_YIELD_MS))

    def _format_status(self, session: _Session) -> str:
        if session.running:
            return "running"
        return f"exited with code {session.exit_code}"

    def _bounded(self, text: str, ctx: ToolContext, label: str) -> str:
        cap = ctx.max_output_bytes or 50_000
        content, _truncated, _path = truncate_with_spill(
            text, max_bytes=cap, label=label, prefix="shell_session", direction="head_tail"
        )
        return content

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        action = (args.get("action") or "").strip().lower()
        try:
            if action == "open":
                return await self._open(args, ctx)
            if action == "write":
                return await self._write(args, ctx)
            if action == "poll":
                return await self._poll(args, ctx)
            if action == "list":
                return self._list()
            if action == "kill":
                return self._kill(args)
        except Exception as e:
            return ToolResult(success=False, output="", error=f"shell_session error: {e}")
        return ToolResult(
            success=False,
            output="",
            error=f"Unknown action {action!r}. Use open, write, poll, list, or kill.",
        )

    async def _open(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        command = (args.get("command") or "").strip()
        if not command:
            return ToolResult(success=False, output="", error="action=open requires 'command'")
        try:
            cwd = validate_working_dir_parameter(args.get("working_dir"), ctx.working_directory)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        _reap_exited()
        with _sessions_lock:
            active = sum(1 for s in _sessions.values() if s.running)
        if active >= MAX_SESSIONS:
            return ToolResult(
                success=False,
                output="",
                error=f"Too many live sessions ({MAX_SESSIONS}). Kill one first (action=list / action=kill).",
            )

        session = _spawn(command, cwd)
        with _sessions_lock:
            _sessions[session.session_id] = session

        await _wait_for_output(session, self._clamp_yield(args))
        output = session.drain_new_output()
        status = self._format_status(session)
        header = f"[session {session.session_id}: {status}]"
        body = self._bounded(output, ctx, "Session output") if output else "(no output yet)"
        return ToolResult(
            success=True,
            output=f"{header}\n{body}",
            metadata={
                "session_id": session.session_id,
                "running": session.running,
                "exit_code": session.exit_code,
                "command": command,
            },
        )

    async def _write(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        session_id = (args.get("session_id") or "").strip()
        session = _get_session(session_id)
        if session is None:
            return ToolResult(
                success=False,
                output="",
                error=f"No such session: {session_id!r} (action=list to see sessions)",
            )
        if not session.running:
            return ToolResult(
                success=False,
                output="",
                error=f"Session {session_id} already exited with code {session.exit_code}.",
            )
        text = args.get("input")
        if text is None:
            return ToolResult(success=False, output="", error="action=write requires 'input'")
        text = str(text)
        if args.get("append_newline", True) and not text.endswith("\n"):
            text += "\n"
        session.write_input(text)
        await _wait_for_output(session, self._clamp_yield(args))
        output = session.drain_new_output()
        status = self._format_status(session)
        body = self._bounded(output, ctx, "Session output") if output else "(no output yet)"
        return ToolResult(
            success=True,
            output=f"[session {session.session_id}: {status}]\n{body}",
            metadata={
                "session_id": session.session_id,
                "running": session.running,
                "exit_code": session.exit_code,
            },
        )

    async def _poll(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        session_id = (args.get("session_id") or "").strip()
        session = _get_session(session_id)
        if session is None:
            return ToolResult(
                success=False,
                output="",
                error=f"No such session: {session_id!r} (action=list to see sessions)",
            )
        await _wait_for_output(session, self._clamp_yield(args))
        output = session.drain_new_output()
        status = self._format_status(session)
        body = self._bounded(output, ctx, "Session output") if output else "(no new output)"
        result = ToolResult(
            success=True,
            output=f"[session {session.session_id}: {status}]\n{body}",
            metadata={
                "session_id": session.session_id,
                "running": session.running,
                "exit_code": session.exit_code,
            },
        )
        _reap_exited()
        return result

    def _list(self) -> ToolResult:
        _reap_exited()
        with _sessions_lock:
            sessions = list(_sessions.values())
        if not sessions:
            return ToolResult(success=True, output="No live sessions.", metadata={"sessions": []})
        rows = [
            f"{s.session_id}  {self._format_status(s):>18}  {time.strftime('%H:%M:%S', time.localtime(s.started_at))}  {shlex.split(s.command)[0] if s.command else ''}  {s.command[:60]}"
            for s in sessions
        ]
        return ToolResult(
            success=True,
            output="session_id  status  started  command\n" + "\n".join(rows),
            metadata={
                "sessions": [
                    {
                        "session_id": s.session_id,
                        "running": s.running,
                        "exit_code": s.exit_code,
                        "command": s.command,
                    }
                    for s in sessions
                ]
            },
        )

    def _kill(self, args: Dict[str, Any]) -> ToolResult:
        session_id = (args.get("session_id") or "").strip()
        with _sessions_lock:
            session = _sessions.pop(session_id, None)
        if session is None:
            return ToolResult(success=False, output="", error=f"No such session: {session_id!r}")
        session.close()
        return ToolResult(
            success=True,
            output=f"Killed session {session_id} ({session.command[:60]}).",
            metadata={"session_id": session_id},
        )


__all__ = ["ShellSessionTool", "MAX_SESSIONS", "DEFAULT_YIELD_MS"]
