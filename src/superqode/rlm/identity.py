"""Explicit runtime identities for native RLM execution.

One child agent has more than one identity, and they fail independently:

* The **worker** is a host process running the model loop. It holds provider
  credentials, so it stays on the host even when the Python kernel does not.
* The **sandbox** owns the execution boundary. Under the host profile it is the
  SuperQode process itself; a container profile gives it an id that can outlive
  any single worker and be shared by every kernel in one session.
* The **kernel** is one persistent Python namespace inside that sandbox. Root
  and each child need separate namespaces even when they share a sandbox.

Collapsing these into a single "execution id" would force recovery to guess
which subsystem it was asking about. Keeping them apart lets a restart check the
worker and the sandbox independently, which is what reattachment after a
container restart will need.

The identities are additive: the released journal's flat ``worker_*`` fields
remain the process identity and keep their meaning, so existing sessions recover
unchanged and no second migration is needed when the sandboxed kernel lands.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .sandbox import HOST_BACKEND

#: Bumped when a journal's identity payload changes shape. Recovery accepts any
#: version it understands and treats an absent version as the released layout.
RUNTIME_IDENTITY_VERSION = 1


@dataclass(frozen=True, slots=True)
class WorkerIdentity:
    """A host process running one agent's model loop."""

    pid: int | None = None
    request_path: str | None = None
    result_path: str | None = None
    control_path: str | None = None
    kind: str = "process"

    @property
    def alive(self) -> bool:
        return process_alive(self.pid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "pid": self.pid,
            "request_path": self.request_path,
            "result_path": self.result_path,
            "control_path": self.control_path,
        }


@dataclass(frozen=True, slots=True)
class SandboxIdentity:
    """The boundary model-written Python executes inside.

    ``sandbox_id`` is empty under the host profile, where the boundary is the
    SuperQode process and has nothing to reattach to. A container profile fills
    it with an id whose liveness can be checked independently of any worker.
    """

    backend: str = HOST_BACKEND
    sandbox_id: str = ""
    session_id: str = ""

    @property
    def isolated(self) -> bool:
        return self.backend != HOST_BACKEND

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "sandbox_id": self.sandbox_id,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "SandboxIdentity":
        data = value if isinstance(value, dict) else {}
        return cls(
            backend=str(data.get("backend") or HOST_BACKEND),
            sandbox_id=str(data.get("sandbox_id") or ""),
            session_id=str(data.get("session_id") or ""),
        )


@dataclass(frozen=True, slots=True)
class KernelIdentity:
    """One persistent Python namespace inside a sandbox."""

    kernel_id: str = ""
    sandbox_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kernel_id": self.kernel_id, "sandbox_id": self.sandbox_id}

    @classmethod
    def from_dict(cls, value: Any) -> "KernelIdentity":
        data = value if isinstance(value, dict) else {}
        return cls(
            kernel_id=str(data.get("kernel_id") or ""),
            sandbox_id=str(data.get("sandbox_id") or ""),
        )


def process_alive(pid: int | None) -> bool:
    """Whether a host process id is still running."""
    if not pid or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def execution_alive(worker: WorkerIdentity, sandbox: SandboxIdentity) -> bool:
    """Ask the subsystem that actually owns this execution whether it survives.

    Host executions are host processes, so a pid check is the whole answer. An
    isolated backend must answer for its own sandbox, and until one exists the
    honest answer is that the execution cannot be confirmed, which recovery
    reports as interrupted rather than assuming a pid means anything.
    """
    if not sandbox.isolated:
        return worker.alive
    return False


__all__ = [
    "RUNTIME_IDENTITY_VERSION",
    "KernelIdentity",
    "SandboxIdentity",
    "WorkerIdentity",
    "execution_alive",
    "process_alive",
]
