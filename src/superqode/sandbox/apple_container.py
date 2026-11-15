"""Run reviewed Linux checks in a disposable Apple Container workspace."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import tempfile
from contextlib import ExitStack
from uuid import uuid4

_IMAGE = re.compile(r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}")


def _copy_file(root: Path, destination: Path, raw: str) -> None:
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts) or any(ord(c) < 32 for c in raw):
        raise ValueError("Apple Container files must be literal project-relative paths")
    # Refuse symlinks at every component while opening the file. A project edit
    # between validation and copy must not turn a selected path into a host read.
    with ExitStack() as files:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        files.callback(os.close, directory)
        for part in parts[:-1]:
            directory = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            files.callback(os.close, directory)
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as source:
            mode = os.fstat(source.fileno()).st_mode
            if not stat.S_ISREG(mode):
                raise ValueError("Apple Container snapshots accept regular files only")
            target = destination.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o700 if mode & stat.S_IXUSR else 0o600)


async def _command(argv: list[str], env: dict[str, str]) -> tuple[int, str]:
    child = await asyncio.create_subprocess_exec(
        *argv,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    tail = b""
    try:
        while chunk := await child.stdout.read(4096):
            tail = (tail + chunk)[-1200:]
        return await child.wait(), tail.decode(errors="replace").strip()
    finally:
        if child.returncode is None:
            try:
                child.kill()
            except ProcessLookupError:
                pass
            await child.wait()


async def run_check(argv, cwd, timeout, *, image, files):
    """Check a pinned local image and run against only the explicit file copy."""
    if not isinstance(image, str) or not _IMAGE.fullmatch(image):
        raise ValueError("Apple Container checks require an OCI image pinned by SHA-256 digest")
    if (
        not files
        or any(not isinstance(path, str) for path in files)
        or len(set(files)) != len(files)
    ):
        raise ValueError("Choose distinct project files for the Apple Container snapshot")
    binary = shutil.which("container") if platform.system() == "Darwin" else None
    if not binary or platform.machine() != "arm64":
        raise ValueError("Apple Container checks require the container CLI on an Apple Silicon Mac")
    major = platform.mac_ver()[0].partition(".")[0]
    if not major.isdecimal() or int(major) < 26:
        raise ValueError("Apple Container checks require macOS 26 or later")
    env = {key: os.environ[key] for key in ("HOME", "PATH", "TMPDIR") if key in os.environ}
    name = "superqode-check-" + uuid4().hex
    deadline = asyncio.get_running_loop().time() + timeout
    async with asyncio.timeout_at(deadline):
        status, _ = await _command([binary, "system", "status"], env)
        if status:
            raise ValueError("Start the Apple Container service before running this check")
        present, _ = await _command([binary, "image", "inspect", image], env)
        if present:
            raise ValueError(
                "The pinned image is missing from the Apple Container cache. Prepare it before running this check."
            )

    with tempfile.TemporaryDirectory(prefix="superqode-check-", dir="/private/tmp") as stage:
        snapshot = Path(stage)
        for path in files:
            _copy_file(Path(cwd).resolve(), snapshot, path)
        options = [
            binary,
            "run",
            "--name",
            name,
            "--rm",
            "--network",
            "none",
            "--no-dns",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--cpus",
            "1",
            "--memory",
            "512M",
            "--env",
            "HOME=/tmp",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--volume",
            f"{snapshot}:/workspace",
            "--workdir",
            "/workspace",
            "--entrypoint",
            argv[0],
            image,
            *argv[1:],
        ]
        try:
            async with asyncio.timeout_at(deadline):
                return await _command(options, env)
        finally:
            # A CLI signal is not proof that the guest exited. Address the
            # exact disposable container even after timeout or cancellation.
            try:
                async with asyncio.timeout(15):
                    code, detail = await _command([binary, "delete", "--force", name], env)
            except TimeoutError as error:
                raise ValueError(f"Apple Container cleanup timed out for {name}") from error
            if code and "not found" not in detail.lower() and "notfound" not in detail.lower():
                raise ValueError(f"Apple Container could not clean up {name}: {detail}")
