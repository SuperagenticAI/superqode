"""Local OS-level command sandboxing.

Confines shell commands to the workspace using the operating system's own
isolation primitives — macOS Seatbelt (``sandbox-exec``) and Linux Bubblewrap
(``bwrap``) — so even auto-approved commands cannot write outside the project or
reach the network.

Modes (via ``SUPERQODE_SANDBOX`` env var):
- ``off`` / ``danger-full-access``: no sandbox (default — opt-in for safety).
- ``workspace-write``: read anywhere, write only to the workspace + temp,
  network allowed.
- ``read-only``: read anywhere, write only to temp, network denied.

``build_sandboxed_command`` returns the argv to spawn and whether a sandbox was
actually applied, so callers degrade gracefully when no backend is available.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

MODE_OFF = "off"
MODE_WORKSPACE_WRITE = "workspace-write"
MODE_READ_ONLY = "read-only"
MODE_DANGER = "danger-full-access"

_VALID_MODES = {MODE_OFF, MODE_WORKSPACE_WRITE, MODE_READ_ONLY, MODE_DANGER}


@dataclass
class SandboxPlan:
    """Result of planning a sandboxed spawn."""

    argv: list[str]
    applied: bool
    backend: str  # "seatbelt", "bwrap", or "none"
    reason: str = ""


def current_mode() -> str:
    """Resolve the active sandbox mode from the environment."""
    mode = os.environ.get("SUPERQODE_SANDBOX", MODE_OFF).strip().lower()
    return mode if mode in _VALID_MODES else MODE_OFF


def _backend_for_platform() -> str:
    system = platform.system()
    if system == "Darwin" and shutil.which("sandbox-exec"):
        return "seatbelt"
    if system == "Linux" and shutil.which("bwrap"):
        return "bwrap"
    return "none"


def sandbox_available() -> bool:
    return _backend_for_platform() != "none"


def _seatbelt_profile(cwd: Path, *, allow_network: bool, writable: list[Path]) -> str:
    """Build a Seatbelt (SBPL) profile: read all, write only to allowed roots."""
    write_rules = []
    for path in writable:
        write_rules.append(f'  (subpath "{path}")')
    write_block = "\n".join(write_rules)
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny file-write*)",
        "(allow file-write*",
        write_block,
        '  (literal "/dev/null")',
        '  (literal "/dev/stdout")',
        '  (literal "/dev/stderr")',
        '  (literal "/dev/dtracehelper")',
        '  (subpath "/dev/fd")',
        ")",
    ]
    if not allow_network:
        lines.append("(deny network*)")
    return "\n".join(lines)


def _writable_roots(cwd: Path, mode: str) -> list[Path]:
    roots = [Path("/tmp"), Path("/private/tmp"), Path("/private/var/folders")]
    if mode == MODE_WORKSPACE_WRITE:
        roots.insert(0, cwd.resolve())
    return [r for r in roots if r]


def build_sandboxed_command(command: str, cwd: Path, mode: str | None = None) -> SandboxPlan:
    """Plan how to spawn *command* under the OS sandbox for *mode*.

    Returns a :class:`SandboxPlan`. When no sandbox is applied (``off``,
    ``danger-full-access``, or no backend) the argv runs the command via the
    shell unchanged.
    """
    mode = (mode or current_mode()).lower()
    shell_argv = ["/bin/sh", "-c", command]

    if mode in (MODE_OFF, MODE_DANGER):
        return SandboxPlan(argv=shell_argv, applied=False, backend="none", reason="disabled")

    backend = _backend_for_platform()
    if backend == "none":
        return SandboxPlan(
            argv=shell_argv, applied=False, backend="none", reason="no sandbox backend available"
        )

    allow_network = mode == MODE_WORKSPACE_WRITE
    cwd = Path(cwd)

    if backend == "seatbelt":
        profile = _seatbelt_profile(cwd, allow_network=allow_network, writable=_writable_roots(cwd, mode))
        argv = ["sandbox-exec", "-p", profile, *shell_argv]
        return SandboxPlan(argv=argv, applied=True, backend="seatbelt")

    # Linux bubblewrap: read-only bind the whole FS, rebind writable roots rw.
    argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
    if mode == MODE_WORKSPACE_WRITE:
        resolved = str(cwd.resolve())
        argv += ["--bind", resolved, resolved]
    if not allow_network:
        argv += ["--unshare-net"]
    argv += ["--die-with-parent", *shell_argv]
    return SandboxPlan(argv=argv, applied=True, backend="bwrap")


def sandbox_status() -> dict:
    """Diagnostics summary for the local sandbox."""
    mode = current_mode()
    backend = _backend_for_platform()
    return {
        "mode": mode,
        "backend": backend,
        "available": backend != "none",
        "active": mode not in (MODE_OFF, MODE_DANGER) and backend != "none",
    }
