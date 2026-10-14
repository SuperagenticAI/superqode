"""Bounded, host-recorded check evidence for Git-visible workspace contents.

Capture runs off the event loop. Ignored files, external dependencies and remote
services are outside this scope. This is a consistency observation, not an OS
snapshot or a security boundary against a hostile same-account process.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import wraps
import hashlib
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import time


SCOPE = "git-visible-files-v1"


def is_test_command(command: str) -> bool:
    for segment in re.split(r"\s*(?:&&|\|\||[;|])\s*", command):
        try:
            words = shlex.split(segment)
        except ValueError:
            continue
        while words and (
            "=" in words[0]
            or words[0] in {"env", "uv", "run", "exec", "npx"}
            or words[0].startswith("-")
        ):
            words.pop(0)
        if not words:
            continue
        executable = words[0].rsplit("/", 1)[-1]
        if executable in {"pytest", "py.test", "unittest", "vitest", "jest", "ctest"}:
            return True
        if executable.startswith("python") and words[1:3] in (["-m", "pytest"], ["-m", "unittest"]):
            return True
        if executable in {
            "npm",
            "pnpm",
            "yarn",
            "bun",
            "cargo",
            "go",
            "dotnet",
            "mvn",
            "gradle",
        } and (words[1:2] == ["test"] or words[1:3] == ["run", "test"]):
            return True
    return False


def capture_workspace(
    root: str | Path, *, max_files=20000, max_bytes=256 * 1024 * 1024, seconds=3.0
) -> dict:
    result = {
        "scope": SCOPE,
        "status": "unverified",
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    started = time.monotonic()
    try:

        def git(*args):
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise ValueError("Workspace fingerprint deadline exceeded")
            return subprocess.run(
                ["git", "-C", str(root), *args], capture_output=True, check=True, timeout=remaining
            ).stdout

        root = Path(os.fsdecode(git("rev-parse", "--show-toplevel")).strip()).resolve()
        result["root"] = str(root)
        paths = sorted(
            set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0"))
            - {b""}
        )
        if len(paths) > max_files:
            raise ValueError("Workspace file-count budget exceeded")
        digest = hashlib.sha256()
        total = 0
        observed = []
        for name in paths:
            path = root / os.fsdecode(name)
            if not path.is_relative_to(root) or ".." in Path(os.fsdecode(name)).parts:
                raise ValueError("Unsafe workspace entry")
            digest.update(name + b"\0")
            try:
                before = path.lstat()
            except FileNotFoundError:
                digest.update(b"deleted\0")
                observed.append((path, None))
                continue
            if not stat.S_ISREG(before.st_mode) or path.resolve() != path:
                raise ValueError(
                    "Symlink, submodule or special file requires separate verification"
                )
            total += before.st_size
            if total > max_bytes:
                raise ValueError("Workspace byte budget exceeded")
            digest.update(str(stat.S_IMODE(before.st_mode)).encode() + b"\0")
            content_digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    if time.monotonic() - started > seconds:
                        raise ValueError("Workspace fingerprint deadline exceeded")
                    content_digest.update(chunk)
            digest.update(content_digest.digest())
            observed.append(
                (path, (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns))
            )
        # Refuse evidence if the inventory or ordinary filesystem versions changed mid-scan.
        after_paths = sorted(
            set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0"))
            - {b""}
        )
        if paths != after_paths:
            raise ValueError("Workspace inventory changed during capture")
        for path, expected in observed:
            try:
                after = path.lstat()
                actual = (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            except FileNotFoundError:
                actual = None
            if actual != expected:
                raise ValueError("Workspace changed during capture")
        result.update(status="captured", sha256=digest.hexdigest(), files=len(paths), bytes=total)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Do not expose subprocess stderr or file contents in evidence.
        result["reason"] = str(error) if isinstance(error, ValueError) else type(error).__name__
    return result


def matching_states(*states: dict) -> bool:
    if not states or any(
        state.get("status") != "captured" or state.get("scope") != SCOPE for state in states
    ):
        return False
    return len({(state.get("root"), state.get("sha256")) for state in states}) == 1 and bool(
        states[0].get("sha256")
    )


async def record_check(command: str, cwd: Path, run):
    """Attach before/after host evidence to either native or Pi-compatible results."""
    if not is_test_command(command):
        return await run()
    before = await asyncio.to_thread(capture_workspace, cwd)
    result = await run()
    after = await asyncio.to_thread(capture_workspace, cwd)
    evidence = {"before": before, "after": after, "stable": matching_states(before, after)}
    attribute = "metadata" if hasattr(result, "metadata") else "details"
    metadata = dict(getattr(result, attribute, None) or {})
    metadata["workspace_evidence"] = evidence
    setattr(result, attribute, metadata)
    return result


def instrument_check_tool(execute, cwd):
    @wraps(execute)
    async def wrapped(call_id, args, signal=None, on_update=None):
        return await record_check(
            str(args.get("command") or ""),
            Path(cwd),
            lambda: execute(call_id, args, signal, on_update),
        )

    return wrapped
