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


def _hidden_paths() -> list[Path]:
    """Host paths the active Factory worker scope must not expose to commands."""
    try:
        from superqode.factory.protection import hidden_paths
    except Exception:  # pragma: no cover - optional during partial installs
        return []
    return [Path(path) for path in hidden_paths()]


def _seatbelt_profile(
    cwd: Path, *, allow_network: bool, writable: list[Path], hidden: list[Path] = ()
) -> str:
    """Build a Seatbelt (SBPL) profile: read all, write only to allowed roots."""
    import json

    write_rules = []
    for path in writable:
        write_rules.append(f"  (subpath {json.dumps(str(path), ensure_ascii=False)})")
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
    for path in hidden:
        lines.append(f"(deny file-read* file-write* (subpath {json.dumps(str(path))}))")
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
    return build_sandboxed_argv(["/bin/sh", "-c", command], cwd, mode)


def build_sandboxed_argv(
    shell_argv: list[str], cwd: Path, mode: str | None = None, *, allow_network: bool | None = None
) -> SandboxPlan:
    mode = (mode or current_mode()).lower()
    if mode in (MODE_OFF, MODE_DANGER):
        return SandboxPlan(argv=shell_argv, applied=False, backend="none", reason="disabled")

    backend = _backend_for_platform()
    if backend == "none":
        return SandboxPlan(
            argv=shell_argv, applied=False, backend="none", reason="no sandbox backend available"
        )

    if allow_network is None:
        allow_network = mode == MODE_WORKSPACE_WRITE
    cwd = Path(cwd)
    hidden = _hidden_paths()

    if backend == "seatbelt":
        profile = _seatbelt_profile(
            cwd, allow_network=allow_network, writable=_writable_roots(cwd, mode), hidden=hidden
        )
        argv = ["sandbox-exec", "-p", profile, *shell_argv]
        return SandboxPlan(argv=argv, applied=True, backend="seatbelt")

    # Linux bubblewrap: read-only bind the whole FS, rebind writable roots rw.
    argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
    if mode == MODE_WORKSPACE_WRITE:
        resolved = str(cwd.resolve())
        argv += ["--bind", resolved, resolved]
    for path in hidden:
        # Mask protected evaluators: an empty directory or an empty file.
        if path.is_dir():
            argv += ["--tmpfs", str(path)]
        elif path.exists():
            argv += ["--ro-bind", "/dev/null", str(path)]
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


def build_verification_argv(argv: list[str], *, candidate: Path, scratch: Path) -> SandboxPlan:
    """Strict Python-probe sandbox: no host-data reads, source writes or network.

    Unlike interactive sandbox modes, this plan never permits unconfined
    execution. The caller must reject an unapplied plan. Runtime roots contain
    the current interpreter and standard library; no user home is exposed.
    """
    import json
    import sys

    candidate, scratch = candidate.resolve(), scratch.resolve()
    backend = _backend_for_platform()
    if backend == "none":
        return SandboxPlan([], False, "none", "protected verification requires an OS sandbox")
    if (
        candidate == scratch
        or candidate.is_relative_to(scratch)
        or scratch.is_relative_to(candidate)
    ):
        return SandboxPlan(
            [], False, backend, "candidate and scratch must be separate sibling workspaces"
        )
    if not argv or Path(argv[0]).resolve() != Path(sys.executable).resolve():
        return SandboxPlan(
            [], False, backend, "protected probes require the current Python interpreter"
        )
    runtime = {Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
    if any(
        path == Path("/") or path == candidate or candidate.is_relative_to(path) for path in runtime
    ):
        return SandboxPlan(
            [], False, backend, "interpreter runtime root would expose the verification workspace"
        )
    readable = {candidate, scratch, *runtime}
    if backend == "seatbelt":
        # Cryptex library paths are OS assets; never allow /System wholesale,
        # since /System/Volumes/Data also contains customer files.
        readable.update(
            Path(path)
            for path in (
                "/System/Library",
                "/usr/lib",
                "/System/Volumes/Preboot/Cryptexes/OS/usr/lib",
                "/System/Volumes/Preboot/Cryptexes/OS/System/Library",
                "/System/Cryptexes/OS/usr/lib",
                "/System/Cryptexes/OS/System/Library",
            )
        )
        rules = "\n".join(f"  (subpath {json.dumps(str(path))})" for path in sorted(readable))
        executables = {Path(argv[0]).absolute(), Path(argv[0]).resolve()}
        exec_rules = "\n".join(
            f"  (literal {json.dumps(str(path))})" for path in sorted(executables)
        )
        profile = "\n".join(
            [
                "(version 1)",
                "(deny default)",
                f"(allow process-exec\n{exec_rules}\n)",
                "(allow sysctl-read)",
                "(allow file-map-executable)",
                "(allow file-read-metadata)",
                f"(allow file-read*\n{rules}\n",
                '  (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random")',
                '  (subpath "/dev/fd") (literal "/dev/stdout") (literal "/dev/stderr"))',
                # dyld opens the root directory during bootstrap. A literal rule
                # permits that directory, without granting reads below it.
                '(allow file-read-data (literal "/"))',
                f'(allow file-write* (subpath {json.dumps(str(scratch))}) (literal "/dev/null") (literal "/dev/stdout") (literal "/dev/stderr") (subpath "/dev/fd"))',
            ]
        )
        return SandboxPlan(["sandbox-exec", "-p", profile, *argv], True, backend)
    # Mount only the interpreter, system libraries and the candidate. No / bind.
    readable.update(
        path for path in (Path("/lib"), Path("/lib64"), Path("/usr/lib")) if path.exists()
    )
    options = [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
    ]
    for path in sorted(readable, key=lambda item: (len(item.parts), str(item))):
        if path != scratch:
            options += ["--ro-bind", str(path), str(path)]
    options += ["--bind", str(scratch), str(scratch), "--chdir", str(candidate), *argv]
    return SandboxPlan(options, True, backend)
