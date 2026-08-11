"""A persistent Python kernel that runs inside a Docker container.

One container per root session, one kernel process per agent inside it. That
granularity is deliberate: a container per child would pay image and mount costs
on every ``rlm.run`` and put four containers on the default parallelism, while a
shared container still gives root and each child a separate namespace and lets
children see one another's repository changes.

The host keeps what must not enter the boundary. Provider credentials and the
supervisor stay outside, so the container reaches them only by asking, over the
same channel that carries execution.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Sequence

from .identity import KernelIdentity, SandboxIdentity
from .kernel import PythonExecutionResult, ShellResult
from .kernel_backend import CheckpointReference, KernelHealth
from .sandbox import DOCKER_BACKEND, RLMSandboxConfig, ensure_command

#: Where the container finds the kernel server and its own writable state. Both
#: are fixed so a reattaching process can find them without stored paths.
SERVER_MOUNT = "/opt/superqode-rlm"
STATE_MOUNT = "/state"
WORKSPACE_MOUNT = "/workspace"

SESSION_LABEL = "superqode.rlm.session"
KIND_LABEL = "superqode.rlm.kind"
KIND_VALUE = "kernel"

HostCall = Callable[[str, dict[str, Any]], Awaitable[Any]]

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


class DockerUnavailableError(RuntimeError):
    """Docker cannot provide the boundary that was requested."""


def safe_name(value: str) -> str:
    """A Docker-legal name derived from a session identifier."""
    cleaned = _UNSAFE_NAME.sub("-", str(value)).strip("-._")
    return cleaned[:48] or "session"


def container_run_command(
    *,
    image: str,
    name: str,
    session_id: str,
    workspace: Path,
    server_dir: Path,
    state_dir: Path,
    config: RLMSandboxConfig,
    uid: int,
    gid: int,
    memory: str = "2g",
    cpus: str = "2",
    pids_limit: int = 512,
) -> list[str]:
    """Build the container command.

    Kept as a pure function so the security-critical parts are asserted in tests
    rather than trusted. Two of them are absences and cannot be read off the
    list: the Docker socket is never mounted, and the host environment is never
    forwarded. Only names the profile lists explicitly are passed in.
    """
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        f"{SESSION_LABEL}={session_id}",
        "--label",
        f"{KIND_LABEL}={KIND_VALUE}",
        # Reap the processes a model's shell commands leave behind.
        "--init",
        # Run as the invoking user so files written through the bind mount are
        # not owned by root on the host.
        "--user",
        f"{uid}:{gid}",
        "--workdir",
        WORKSPACE_MOUNT,
        "--volume",
        f"{workspace}:{WORKSPACE_MOUNT}{'' if config.policy.allow_write else ':ro'}",
        # The kernel server is mounted read-only: the sandbox runs it but must
        # not be able to rewrite it.
        "--volume",
        f"{server_dir}:{SERVER_MOUNT}:ro",
        # A host directory rather than a named volume: a named volume is created
        # owned by root, which a non-root container user cannot write to, and
        # fixing that would need a privileged helper container. The session owns
        # this directory, so checkpoints survive the container being recreated.
        "--volume",
        f"{state_dir}:{STATE_MOUNT}",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=256m,mode=1777",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--memory",
        memory,
        "--cpus",
        cpus,
        "--pids-limit",
        str(pids_limit),
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
    ]
    command += ["--network", "bridge" if config.allow_network else "none"]
    for variable in config.env_allowlist:
        value = os.environ.get(variable)
        if value is not None:
            command += ["--env", f"{variable}={value}"]
    command += [image, "sleep", "infinity"]
    return command


def kernel_exec_command(
    container: str, kernel_id: str, config: RLMSandboxConfig | None = None
) -> list[str]:
    resolved = config or RLMSandboxConfig.from_config({"sandbox": DOCKER_BACKEND})
    return [
        "docker",
        "exec",
        "--interactive",
        "--workdir",
        WORKSPACE_MOUNT,
        container,
        "python3",
        f"{SERVER_MOUNT}/kernel_server.py",
        kernel_id,
        WORKSPACE_MOUNT,
        json.dumps(
            {
                "allow_read": resolved.policy.allow_read,
                "allow_write": resolved.policy.allow_write,
                "allow_shell": resolved.policy.allow_shell,
                "allowed_commands": list(resolved.policy.allowed_commands),
                "allow_compound_commands": resolved.policy.allow_compound_commands,
            },
            separators=(",", ":"),
        ),
    ]


def shell_exec_command(container: str, command: str) -> list[str]:
    return [
        "docker",
        "exec",
        "--workdir",
        WORKSPACE_MOUNT,
        container,
        "sh",
        "-lc",
        command,
    ]


class KernelChannel:
    """One kernel process, framed as JSON lines.

    The transport is a subprocess, which is what makes the protocol testable
    without Docker: the same channel drives ``docker exec`` and a plain local
    ``python kernel_server.py``.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        host_call: HostCall | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.command = list(command)
        self.host_call = host_call
        self.log_path = log_path
        self._process: asyncio.subprocess.Process | None = None
        self._log: Any = None
        self._lock = asyncio.Lock()

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> dict[str, Any]:
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = self.log_path.open("ab")
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=self._log or asyncio.subprocess.DEVNULL,
        )
        ready = await self._read()
        if ready is None or ready.get("type") != "ready":
            raise RuntimeError(f"RLM kernel did not start: {ready!r}")
        return ready

    async def request(self, message: dict[str, Any], *, timeout: float | None = None) -> dict:
        """Send one operation and service host calls until its result arrives."""
        async with self._lock:
            return await asyncio.wait_for(self._exchange(message), timeout)

    async def _exchange(self, message: dict[str, Any]) -> dict[str, Any]:
        await self._write(message)
        while True:
            received = await self._read()
            if received is None:
                raise RuntimeError("The RLM kernel closed its channel")
            if received.get("type") == "call":
                await self._service(received)
                continue
            if received.get("type") == "result":
                return received

    async def _service(self, message: dict[str, Any]) -> None:
        call_id = message.get("call_id")
        name = str(message.get("name") or "")
        payload = message.get("payload")
        if self.host_call is None:
            await self._write(
                {
                    "type": "call_result",
                    "call_id": call_id,
                    "ok": False,
                    "error": f"{name} is not available from this kernel",
                }
            )
            return
        try:
            value = await self.host_call(name, payload if isinstance(payload, dict) else {})
        except Exception as error:  # noqa: BLE001 - the sandbox must see the failure
            await self._write(
                {"type": "call_result", "call_id": call_id, "ok": False, "error": str(error)}
            )
            return
        await self._write({"type": "call_result", "call_id": call_id, "ok": True, "value": value})

    async def _write(self, message: dict[str, Any]) -> None:
        process = self._require()
        assert process.stdin is not None
        process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        await process.stdin.drain()

    async def _read(self) -> dict[str, Any] | None:
        process = self._require()
        assert process.stdout is not None
        line = await process.stdout.readline()
        if not line:
            return None
        try:
            value = json.loads(line.decode("utf-8"))
        except ValueError:
            return {"type": "result", "error": "The kernel produced unreadable output"}
        return value if isinstance(value, dict) else None

    def _require(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise RuntimeError("The RLM kernel channel is not started")
        return self._process

    async def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.returncode is None and process.stdin is not None:
                process.stdin.write(b'{"op": "shutdown"}\n')
                await process.stdin.drain()
                process.stdin.close()
            await asyncio.wait_for(process.wait(), timeout=5)
        except (TimeoutError, ConnectionResetError, BrokenPipeError, RuntimeError):
            with contextlib.suppress(OSError, ProcessLookupError):
                process.kill()
        finally:
            if self._log is not None:
                self._log.close()
                self._log = None


class DockerKernelBackend:
    """Model-written Python executes inside a container, not on the host."""

    def __init__(
        self,
        cwd: str | Path,
        *,
        config: RLMSandboxConfig,
        session_id: str,
        state_dir: str | Path,
        host_call: HostCall | None = None,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.config = config
        self.session_id = safe_name(session_id)
        self.state_dir = Path(state_dir).expanduser()
        self.host_call = host_call
        self.container_name = f"superqode-rlm-{self.session_id}"
        self._identity = SandboxIdentity(backend=DOCKER_BACKEND, session_id=self.session_id)
        self._channels: dict[str, KernelChannel] = {}

    @property
    def identity(self) -> SandboxIdentity:
        return self._identity

    async def start(self) -> SandboxIdentity:
        """Reattach to this session's container, or create it."""
        if shutil.which("docker") is None:
            raise DockerUnavailableError("The docker CLI was not found on PATH")
        existing = await self._find_container()
        if existing:
            self._identity = SandboxIdentity(
                backend=DOCKER_BACKEND, sandbox_id=existing, session_id=self.session_id
            )
            return self._identity
        server_dir = self._stage_server()
        kernel_state = self.state_dir / "kernels"
        kernel_state.mkdir(parents=True, exist_ok=True)
        code, out, err = await self._docker(
            container_run_command(
                image=self.config.image,
                name=self.container_name,
                session_id=self.session_id,
                workspace=self.cwd,
                server_dir=server_dir,
                state_dir=kernel_state.resolve(),
                config=self.config,
                uid=os.getuid(),
                gid=os.getgid(),
            )
        )
        if code != 0:
            raise DockerUnavailableError(f"Could not start the RLM container: {err.strip() or out}")
        self._identity = SandboxIdentity(
            backend=DOCKER_BACKEND, sandbox_id=out.strip(), session_id=self.session_id
        )
        return self._identity

    async def create_kernel(self, kernel_id: str) -> KernelIdentity:
        await self._channel(kernel_id)
        return KernelIdentity(kernel_id=kernel_id, sandbox_id=self._identity.sandbox_id)

    async def execute(self, kernel_id: str, code: str) -> PythonExecutionResult:
        channel = await self._channel(kernel_id)
        result = await channel.request(
            {
                "op": "execute",
                "code": code,
                "checkpoint_path": f"{STATE_MOUNT}/{kernel_id}.pkl",
            }
        )
        return PythonExecutionResult(
            str(result.get("output") or ""),
            str(result.get("value_repr") or ""),
            result.get("error") or None,
        )

    async def shell(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> ShellResult:
        """Run a command inside the boundary.

        Completion gates come through here. A gate that ran on the host while
        Python ran in the container would defeat the boundary it is meant to
        verify inside.
        """
        del env  # The container's environment is fixed by the profile.
        ensure_command(self.config, command)
        display = command if isinstance(command, str) else " ".join(map(str, command))
        code, out, err = await self._docker(
            shell_exec_command(self._require_container(), display), timeout=timeout
        )
        return ShellResult(display, code, out, err)

    async def checkpoint(self, kernel_id: str) -> CheckpointReference:
        """Capture state inside the boundary and describe it to the host."""
        channel = await self._channel(kernel_id)
        result = await channel.request(
            {"op": "checkpoint", "path": f"{STATE_MOUNT}/{kernel_id}.pkl"}
        )
        return CheckpointReference(
            path=str(result.get("path") or ""),
            digest=str(result.get("digest") or ""),
            saved=tuple(str(item) for item in result.get("saved") or ()),
            skipped=tuple(str(item) for item in result.get("skipped") or ()),
            size=int(result.get("size") or 0),
            # The payload never leaves the container, so the host holds a
            # description and never unpickles bytes the sandbox produced.
            inside_boundary=True,
            error=str(result.get("error") or ""),
        )

    async def restore(self, kernel_id: str, reference: CheckpointReference) -> tuple[str, ...]:
        # Checked before anything is started: restoring state the sandbox did
        # not write is the one way this path could import untrusted pickles.
        path = reference.path or f"{STATE_MOUNT}/{kernel_id}.pkl"
        if not str(path).startswith(f"{STATE_MOUNT}/"):
            raise ValueError(f"Refusing to restore RLM state from outside {STATE_MOUNT}: {path}")
        channel = await self._channel(kernel_id)
        result = await channel.request({"op": "restore", "path": path})
        return tuple(str(item) for item in result.get("restored") or ())

    async def health(self) -> KernelHealth:
        container = self._identity.sandbox_id
        if not container:
            return KernelHealth(alive=False, backend=DOCKER_BACKEND, detail="no container")
        code, out, _err = await self._docker(
            ["docker", "inspect", "--format", "{{.State.Status}}", container]
        )
        status = out.strip() or "unknown"
        return KernelHealth(
            alive=code == 0 and status == "running",
            backend=DOCKER_BACKEND,
            detail=f"container {container[:12]} {status}",
            kernels=tuple(sorted(self._channels)),
        )

    async def close_kernel(self, kernel_id: str) -> None:
        channel = self._channels.pop(kernel_id, None)
        if channel is not None:
            await channel.close()

    async def close(self, *, remove_container: bool = True) -> None:
        for kernel_id in list(self._channels):
            await self.close_kernel(kernel_id)
        if remove_container and self._identity.sandbox_id:
            await self._docker(["docker", "rm", "--force", self._identity.sandbox_id])

    async def _channel(self, kernel_id: str) -> KernelChannel:
        existing = self._channels.get(kernel_id)
        if existing is not None and existing.alive:
            return existing
        channel = KernelChannel(
            kernel_exec_command(self._require_container(), kernel_id, self.config),
            host_call=self.host_call,
            log_path=self.state_dir / f"{kernel_id}.kernel.log",
        )
        await channel.start()
        self._channels[kernel_id] = channel
        # Restore before anything runs, exactly as the in-process kernel does at
        # construction. Without this a reattached kernel would execute first,
        # and the checkpoint written after that call would overwrite the state
        # it was supposed to recover.
        with contextlib.suppress(Exception):
            await channel.request(
                {"op": "restore", "path": f"{STATE_MOUNT}/{kernel_id}.pkl"}, timeout=30
            )
        return channel

    def _require_container(self) -> str:
        container = self._identity.sandbox_id
        if not container:
            raise DockerUnavailableError("The RLM container has not been started")
        return container

    def _stage_server(self) -> Path:
        """Copy the kernel server where the container can mount it read-only."""
        server_dir = self.state_dir / "server"
        server_dir.mkdir(parents=True, exist_ok=True)
        source = Path(__file__).with_name("kernel_server.py")
        shutil.copyfile(source, server_dir / "kernel_server.py")
        return server_dir.resolve()

    async def _find_container(self) -> str:
        """Only reattach to a container this session owns."""
        code, out, _err = await self._docker(
            [
                "docker",
                "ps",
                "--quiet",
                # Full ids, so a reattached sandbox identity matches the one
                # `docker run` reported when the container was created.
                "--no-trunc",
                "--filter",
                f"label={SESSION_LABEL}={self.session_id}",
                "--filter",
                f"label={KIND_LABEL}={KIND_VALUE}",
                "--filter",
                "status=running",
            ]
        )
        if code != 0:
            return ""
        return out.strip().splitlines()[0].strip() if out.strip() else ""

    async def _docker(
        self, command: Sequence[str], *, timeout: float | None = 120
    ) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError:
            process.kill()
            return 124, "", f"docker timed out after {timeout}s"
        return (
            process.returncode or 0,
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"),
        )


__all__ = [
    "KIND_LABEL",
    "SERVER_MOUNT",
    "SESSION_LABEL",
    "STATE_MOUNT",
    "WORKSPACE_MOUNT",
    "DockerKernelBackend",
    "DockerUnavailableError",
    "KernelChannel",
    "container_run_command",
    "kernel_exec_command",
    "safe_name",
    "shell_exec_command",
]
