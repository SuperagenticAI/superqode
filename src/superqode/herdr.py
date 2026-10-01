"""Best-effort lifecycle reporting for a SuperQode TUI hosted by Herdr."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SOURCE = "superqode"
DISPLAY_SOURCE = "superqode:display"
REPORT_TIMEOUT = 0.5


def child_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy an environment without the parent's Herdr pane authority.

    Nested harnesses and shell tools are not independent occupants of the
    parent's pane. A process launched in a separate Herdr pane receives its own
    environment from Herdr instead.
    """
    return {
        key: value
        for key, value in (os.environ if env is None else env).items()
        if not key.startswith("HERDR_")
    }


def sdk_env_overrides() -> dict[str, str]:
    """Disable ownership for SDKs that overlay options onto the inherited env."""
    return {key: "" for key in os.environ if key.startswith("HERDR_")}


def valid_resume_argv(argv: tuple[str, ...]) -> bool:
    """Match Herdr's portable resume argument limits before sending a report."""
    return bool(
        argv
        and len(argv) <= 64
        and re.fullmatch(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*", argv[0])
        and sum(len(arg.encode("utf-8")) for arg in argv) <= 8192
        and not any("'" in arg or any(unicodedata.category(c) == "Cc" for c in arg) for arg in argv)
    )


def launch_prefix() -> tuple[str, ...]:
    """Source checkouts resume their own code rather than an older installed tool."""
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").is_file() and (root / ".venv").is_dir() and shutil.which("uv"):
        prefix = ("uv", "run", "--project", str(root), "--no-sync", "superqode")
        if valid_resume_argv(prefix):
            return prefix
    return ("superqode",)


@dataclass(frozen=True)
class _Report:
    state: str
    message: str
    harness: str
    model: str
    session_id: str
    resume_argv: tuple[str, ...]


class HerdrReporter:
    """One bounded writer per pane; pending reports keep only the latest state."""

    @classmethod
    def from_env(cls) -> HerdrReporter | None:
        if os.environ.get("HERDR_ENV") != "1" or not all(
            os.environ.get(key) for key in ("HERDR_PANE_ID", "HERDR_BIN_PATH", "HERDR_SOCKET_PATH")
        ):
            return None
        try:
            return cls(dict(os.environ))
        except (OSError, RuntimeError):
            return None

    def __init__(self, env: Mapping[str, str]):
        self._env = dict(env)
        self._binary = env["HERDR_BIN_PATH"]
        self._pane = env["HERDR_PANE_ID"]
        self._condition = threading.Condition()
        self._pending: _Report | None = None
        self._closed = False
        self._seq = time.time_ns()
        self._thread = threading.Thread(
            target=self._write_loop, name="superqode-herdr", daemon=True
        )
        self._thread.start()

    def report(
        self,
        state: str,
        *,
        message: str = "",
        harness: str = "",
        model: str = "",
        session_id: str = "",
        resume_argv: tuple[str, ...] = (),
    ) -> None:
        if state not in {"idle", "working", "blocked"}:
            raise ValueError(f"Invalid Herdr state: {state}")
        # Metadata contains concise display labels, never prompts or tool arguments.
        argv = tuple(resume_argv)
        if argv and not valid_resume_argv(argv):
            argv = ()
        snapshot = _Report(state, message[:240], harness[:120], model[:120], session_id, argv)
        with self._condition:
            if self._closed:
                return
            self._pending = snapshot
            self._condition.notify()

    def close(self) -> None:
        """Release after in-flight reports, including on Ctrl+C and startup failure."""
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify()
        self._thread.join(timeout=4 * REPORT_TIMEOUT + 0.2)

    def _next_seq(self) -> str:
        self._seq = max(self._seq + 1, time.time_ns())
        return str(self._seq)

    def _send(self, command: str, *args: str, source: str = SOURCE) -> bool:
        try:
            result = subprocess.run(
                [
                    self._binary,
                    "pane",
                    command,
                    self._pane,
                    "--source",
                    source,
                    "--seq",
                    self._next_seq(),
                    *args,
                ],
                env=self._env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=REPORT_TIMEOUT,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _write_loop(self) -> None:
        delivered_state: tuple[str, str, str] | None = None
        delivered_resume: tuple[str, tuple[str, ...]] | None = None
        delivered_metadata: tuple[str, str, str, str, str] | None = None
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed:
                    break
                snapshot = self._pending
                self._pending = None
            assert snapshot is not None
            state = (snapshot.state, snapshot.message, snapshot.session_id)
            if state != delivered_state:
                args = ["--agent", SOURCE, "--state", snapshot.state]
                if snapshot.message:
                    args += ["--message", snapshot.message]
                if snapshot.session_id:
                    args += ["--agent-session-id", snapshot.session_id]
                if not self._send("report-agent", *args):
                    continue
                delivered_state = state
            resume = (snapshot.session_id, snapshot.resume_argv)
            if snapshot.resume_argv and resume != delivered_resume:
                args = ["--agent", SOURCE, "--session-start-source", "resume"]
                if snapshot.session_id:
                    args += ["--agent-session-id", snapshot.session_id]
                if self._send("report-agent-session", *args, "--", *snapshot.resume_argv):
                    delivered_resume = resume
            summary = (
                snapshot.message
                or {"idle": "Ready", "working": "Working", "blocked": "Decision needed"}[
                    snapshot.state
                ]
            )
            restore = (
                ("conversation" if snapshot.session_id else "fresh")
                if snapshot.resume_argv
                else "none"
            )
            metadata = (summary, snapshot.harness, snapshot.model, snapshot.session_id, restore)
            if metadata != delivered_metadata and self._send(
                "report-metadata",
                "--agent",
                SOURCE,
                "--applies-to-source",
                SOURCE,
                "--token",
                f"summary={summary}",
                "--token",
                f"harness={snapshot.harness}",
                "--token",
                f"model={snapshot.model}",
                "--token",
                f"session={snapshot.session_id}",
                "--token",
                f"restore={restore}",
                source=DISPLAY_SOURCE,
            ):
                delivered_metadata = metadata
        self._send("release-agent", "--agent", SOURCE)
