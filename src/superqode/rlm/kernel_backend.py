"""Where model-written Python actually executes.

1A made a harness's declared execution policy real for ordinary use, but a
policy object cannot constrain code that can import ``os``. Isolation needs the
interpreter itself to sit inside the boundary, which is what this contract is
for: the host keeps the model loop and the provider credentials, and a backend
owns the Python.

Two consequences shape the interface:

* ``shell`` belongs to the backend, not to the host. A completion gate that ran
  on the host while Python ran in a container would be a hole straight through
  the boundary, so gates and commands go wherever the kernel went.
* State crossing back out is untrusted. A checkpoint produced inside a sandbox
  the model influences must never be unpickled by the host, so a backend hands
  back a :class:`CheckpointReference` describing state it holds rather than the
  state itself.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from superqode.pipy.messages import TextContent
from superqode.pipy.tools.base import AgentTool, AgentToolResult

from .identity import KernelIdentity, SandboxIdentity
from .kernel import PersistentPythonKernel, PythonExecutionResult, Shell, ShellResult, kernel_for
from .sandbox import HOST_BACKEND, RLMSandboxConfig

ROOT_KERNEL = "root"


@dataclass(frozen=True, slots=True)
class KernelHealth:
    """Whether the boundary and its kernels are still usable."""

    alive: bool
    backend: str
    detail: str = ""
    kernels: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "alive": self.alive,
            "backend": self.backend,
            "detail": self.detail,
            "kernels": list(self.kernels),
        }


@dataclass(frozen=True, slots=True)
class CheckpointReference:
    """Everything the host may learn about state it must not trust.

    Under an isolated backend the payload is written and read only inside the
    boundary. The host keeps a location, a digest and a bounded manifest of
    names, and never calls ``pickle.loads`` on bytes the sandbox produced:
    unpickling state a model could influence would hand it host execution.
    """

    path: str = ""
    digest: str = ""
    saved: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    size: int = 0
    inside_boundary: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        """A checkpoint that failed to write must not read as an empty one."""
        return not self.error and bool(self.path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "digest": self.digest,
            "saved": list(self.saved),
            "skipped": list(self.skipped),
            "size": self.size,
            "inside_boundary": self.inside_boundary,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CheckpointReference":
        data = value if isinstance(value, dict) else {}
        return cls(
            path=str(data.get("path") or ""),
            digest=str(data.get("digest") or ""),
            saved=tuple(str(item) for item in data.get("saved") or ()),
            skipped=tuple(str(item) for item in data.get("skipped") or ()),
            size=int(data.get("size") or 0),
            inside_boundary=bool(data.get("inside_boundary", False)),
            error=str(data.get("error") or ""),
        )


class PersistentKernelBackend(Protocol):
    """One execution boundary owning one or more persistent Python namespaces."""

    @property
    def identity(self) -> SandboxIdentity: ...

    async def start(self) -> SandboxIdentity: ...

    async def create_kernel(self, kernel_id: str) -> KernelIdentity: ...

    async def execute(self, kernel_id: str, code: str) -> PythonExecutionResult: ...

    async def shell(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> ShellResult: ...

    async def checkpoint(self, kernel_id: str) -> CheckpointReference: ...

    async def restore(self, kernel_id: str, reference: CheckpointReference) -> tuple[str, ...]: ...

    async def health(self) -> KernelHealth: ...

    async def close_kernel(self, kernel_id: str) -> None: ...

    async def close(self) -> None: ...


class HostKernelBackend:
    """The released behaviour, behind the contract.

    Python runs as the SuperQode process. This backend makes no isolation
    claim; it exists so the host profile and a sandboxed profile are selected
    the same way, and so nothing about the released path changes when they are.
    """

    def __init__(
        self,
        cwd: str | Path,
        *,
        config: RLMSandboxConfig | None = None,
        session_key: str = "",
        checkpoint_path: str | Path | None = None,
        supervisor: Any | None = None,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.config = config or RLMSandboxConfig()
        self.session_key = session_key or str(self.cwd)
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path is not None else None
        self.supervisor = supervisor
        self._identity = SandboxIdentity(backend=HOST_BACKEND, session_id=self.session_key)
        self._kernels: dict[str, PersistentPythonKernel] = {}

    @property
    def identity(self) -> SandboxIdentity:
        return self._identity

    async def start(self) -> SandboxIdentity:
        return self._identity

    async def create_kernel(self, kernel_id: str) -> KernelIdentity:
        self._kernel(kernel_id)
        return KernelIdentity(kernel_id=kernel_id, sandbox_id=self._identity.sandbox_id)

    async def execute(self, kernel_id: str, code: str) -> PythonExecutionResult:
        return await self._kernel(kernel_id).execute(code)

    async def shell(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> ShellResult:
        runner = Shell(self.cwd, sandbox=self.config)
        return await asyncio.to_thread(runner.run, command, timeout=timeout, env=env)

    async def checkpoint(self, kernel_id: str) -> CheckpointReference:
        result = await asyncio.to_thread(self._kernel(kernel_id).checkpoint)
        path = str(result.get("path") or "")
        payload = Path(path).read_bytes() if path and Path(path).is_file() else b""
        return CheckpointReference(
            path=path,
            digest=hashlib.sha256(payload).hexdigest() if payload else "",
            saved=tuple(str(item) for item in result.get("saved") or ()),
            skipped=tuple(str(item) for item in result.get("skipped") or ()),
            size=len(payload),
            inside_boundary=False,
            error=str(result.get("error") or ""),
        )

    async def restore(self, kernel_id: str, reference: CheckpointReference) -> tuple[str, ...]:
        del reference  # A host kernel restores from its own checkpoint path.
        kernel = self._kernel(kernel_id)
        return await asyncio.to_thread(kernel._restore_checkpoint)

    async def health(self) -> KernelHealth:
        return KernelHealth(
            alive=True,
            backend=HOST_BACKEND,
            detail="Python runs as the SuperQode process",
            kernels=tuple(sorted(self._kernels)),
        )

    async def close_kernel(self, kernel_id: str) -> None:
        self._kernels.pop(kernel_id, None)

    async def close(self) -> None:
        self._kernels.clear()

    def kernel(self, kernel_id: str = ROOT_KERNEL) -> PersistentPythonKernel:
        """The in-process kernel, for callers that still hold one directly."""
        return self._kernel(kernel_id)

    def _kernel(self, kernel_id: str) -> PersistentPythonKernel:
        existing = self._kernels.get(kernel_id)
        if existing is not None:
            return existing
        # The root kernel keeps the released session key and checkpoint path so
        # sessions written before this contract resume unchanged.
        key = self.session_key if kernel_id == ROOT_KERNEL else f"{self.session_key}#{kernel_id}"
        checkpoint = self.checkpoint_path
        if checkpoint is not None and kernel_id != ROOT_KERNEL:
            checkpoint = checkpoint.with_suffix(f".{kernel_id}.pkl")
        kernel = kernel_for(
            key,
            self.cwd,
            supervisor=self.supervisor,
            agent_id=kernel_id,
            checkpoint_path=checkpoint,
            sandbox=self.config,
        )
        self._kernels[kernel_id] = kernel
        return kernel


def create_backend_python_tool(
    backend: PersistentKernelBackend,
    kernel_id: str = ROOT_KERNEL,
    *,
    drain_events: Any | None = None,
    cwd: str | Path = "",
) -> AgentTool:
    """The one model-facing tool, executed by a backend rather than in process.

    The boundary is started on first use because a session is wired
    synchronously and starting a container is not something to do while merely
    opening a session that may never run anything.
    """
    state = {"started": False}

    async def execute(tool_call_id, args, signal=None, on_update=None) -> AgentToolResult:
        del tool_call_id, signal, on_update
        code = str(args.get("code") or "")
        if not code.strip():
            raise ValueError("Python code cannot be empty")
        if not state["started"]:
            await backend.start()
            await backend.create_kernel(kernel_id)
            state["started"] = True
        result = await backend.execute(kernel_id, code)
        agent_events = list(drain_events() if drain_events is not None else [])
        if result.error:
            raise RuntimeError(result.text)
        return AgentToolResult(
            content=[TextContent(text=result.text)],
            details={
                "runtime": "python",
                "persistent": True,
                "cwd": str(cwd),
                "sandbox": backend.identity.backend,
                "kernel_id": kernel_id,
                "agent_events": agent_events,
            },
        )

    return AgentTool(
        name="python",
        label="Python",
        description="Execute Python code in the persistent RLM kernel.",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source to execute in the persistent session namespace.",
                }
            },
            "required": ["code"],
            "additionalProperties": False,
        },
        execute_fn=execute,
        prompt_snippet="Execute code in the persistent Python environment",
        execution_mode="sequential",
    )


__all__ = [
    "ROOT_KERNEL",
    "CheckpointReference",
    "HostKernelBackend",
    "KernelHealth",
    "PersistentKernelBackend",
    "create_backend_python_tool",
]
