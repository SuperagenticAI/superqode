"""Sandbox selection and host-mode guardrails for the native RLM harness.

The RLM kernel executes model-written Python, so isolation belongs at the
interpreter boundary. A policy object living inside the namespace cannot
constrain code that is free to import ``os``. This module therefore does two
separate jobs, and only claims the first:

1. Host mode enforces the configured policy as guardrails. They stop mistakes,
   and they make a HarnessSpec's declared execution policy meaningful, which the
   RLM kernel previously ignored altogether. They do not stop an adversarial
   model.
2. It resolves and carries the profile a container-backed kernel needs, so the
   selected backend and granularity are settled before the persistent
   interpreter moves inside that boundary.

Backends other than ``host`` are accepted as configuration and refused at
activation until the sandboxed kernel lands. Silently downgrading a requested
boundary to host execution would be worse than failing.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from superqode.harness.sandbox import SandboxPolicy

HOST_BACKEND = "host"
DOCKER_BACKEND = "docker"
#: Monty is a from-scratch Python interpreter with no subprocess and no real
#: filesystem. It is the research and evaluation profile: it can hold a corpus
#: and query it, and it cannot run tests or change files.
MONTY_BACKEND = "monty"
SUPPORTED_BACKENDS: tuple[str, ...] = (HOST_BACKEND, DOCKER_BACKEND, MONTY_BACKEND)
IMPLEMENTED_BACKENDS: tuple[str, ...] = (HOST_BACKEND, DOCKER_BACKEND, MONTY_BACKEND)

SESSION_GRANULARITY = "session"
CHILD_GRANULARITY = "child"
SUPPORTED_GRANULARITIES: tuple[str, ...] = (SESSION_GRANULARITY, CHILD_GRANULARITY)

DEFAULT_IMAGE = "python:3.12-slim"

#: Names meaning "run on the host with no boundary". ``none`` is what the
#: built-in RLM template declares; ``local`` is the HarnessSpec default for
#: harnesses that never adopted a container profile.
_HOST_ALIASES = frozenset({"", "none", "host", "local", "local-os"})

#: Host mode keeps the permissions the released harness already had. Tightening
#: these defaults would change behaviour for every existing RLM session.
HOST_POLICY = SandboxPolicy(
    allow_read=True,
    allow_write=True,
    allow_shell=True,
    allow_compound_commands=True,
)

_COMPOUND_PATTERN = re.compile(r"[;&|]|\$\(|`|\n")


class SandboxPolicyError(RuntimeError):
    """A Python-namespace call violated the configured RLM sandbox policy."""


class SandboxUnavailableError(RuntimeError):
    """A sandbox backend was requested that this build cannot provide."""


@dataclass(frozen=True, slots=True)
class RLMSandboxConfig:
    """The resolved sandbox profile for one RLM session and its children."""

    backend: str = HOST_BACKEND
    granularity: str = SESSION_GRANULARITY
    policy: SandboxPolicy = HOST_POLICY
    allow_network: bool = True
    env_allowlist: tuple[str, ...] = ()
    image: str = DEFAULT_IMAGE
    python_timeout: float = 120.0
    max_output_chars: int = 1_000_000
    max_checkpoint_bytes: int = 64 * 1024 * 1024

    @property
    def isolated(self) -> bool:
        """Whether model-written Python runs outside the SuperQode process."""
        return self.backend != HOST_BACKEND

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | None = None,
        *,
        execution_policy: Any | None = None,
    ) -> "RLMSandboxConfig":
        """Resolve a profile from ``runtime.config`` over a harness policy.

        ``runtime.config`` wins because it is the RLM-specific surface. The
        execution policy supplies whatever the runtime config does not state.
        """
        data = {str(key): value for key, value in dict(config or {}).items()}
        granularity = str(data.get("sandbox_granularity") or SESSION_GRANULARITY).strip().lower()
        if granularity not in SUPPORTED_GRANULARITIES:
            raise ValueError(
                f"Unknown RLM sandbox granularity {granularity!r}; "
                f"supported: {', '.join(SUPPORTED_GRANULARITIES)}"
            )
        backend = _resolve_backend(data, execution_policy)
        return cls(
            backend=backend,
            granularity=granularity,
            policy=_resolve_policy(data, execution_policy),
            # Host mode keeps its released connectivity. An isolation profile
            # starts offline and requires an explicit network opt-in.
            allow_network=_flag(data, execution_policy, "allow_network", backend == HOST_BACKEND),
            env_allowlist=tuple(
                str(item) for item in data.get("env_allowlist") or () if str(item).strip()
            ),
            image=str(data.get("sandbox_image") or DEFAULT_IMAGE),
            python_timeout=max(1.0, min(3600.0, float(data.get("python_timeout") or 120.0))),
            max_output_chars=max(
                20_000, min(10_000_000, int(data.get("max_output_chars") or 1_000_000))
            ),
            max_checkpoint_bytes=max(
                1_048_576,
                min(1_073_741_824, int(data.get("max_checkpoint_bytes") or 64 * 1024 * 1024)),
            ),
        )

    def require_available(self) -> "RLMSandboxConfig":
        """Fail loudly rather than downgrade an unimplemented boundary."""
        if self.backend not in IMPLEMENTED_BACKENDS:
            raise SandboxUnavailableError(
                f"The {self.backend!r} RLM sandbox is not implemented in this build, "
                "so the session was not started. Model-written Python would have run "
                "on the host with the boundary silently missing. Use 'host' and accept "
                "its documented permissions, or run SuperQode inside an external "
                "isolation boundary."
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        """Serialize using the keys ``from_config`` reads, so it round-trips.

        Detached child workers rebuild their profile from this JSON, so the two
        directions must not drift apart. ``isolated`` is derived and ignored on
        the way back in; it is present for journals and status output.
        """
        return {
            "sandbox": self.backend,
            "sandbox_granularity": self.granularity,
            "sandbox_image": self.image,
            "allow_read": self.policy.allow_read,
            "allow_write": self.policy.allow_write,
            "allow_shell": self.policy.allow_shell,
            "allow_network": self.allow_network,
            "allowed_commands": list(self.policy.allowed_commands),
            "allow_compound_commands": self.policy.allow_compound_commands,
            "env_allowlist": list(self.env_allowlist),
            "isolated": self.isolated,
            "python_timeout": self.python_timeout,
            "max_output_chars": self.max_output_chars,
            "max_checkpoint_bytes": self.max_checkpoint_bytes,
        }

    def describe(self) -> list[str]:
        """Status lines for `:rlm sandbox`, written to be honest about scope."""
        lines = [
            f"backend     {self.backend}",
            f"granularity {self.granularity}",
            f"read        {'yes' if self.policy.allow_read else 'no'}",
            f"write       {'yes' if self.policy.allow_write else 'no'}",
            f"shell       {'yes' if self.policy.allow_shell else 'no'}",
            f"network     {'yes' if self.allow_network else 'no'}",
            f"python      timeout {self.python_timeout:g}s, output {self.max_output_chars:,} chars",
            f"checkpoint  at most {self.max_checkpoint_bytes:,} bytes",
        ]
        if self.policy.allowed_commands:
            lines.append(f"commands    {', '.join(self.policy.allowed_commands)}")
        if self.env_allowlist:
            lines.append(f"env         {', '.join(self.env_allowlist)}")
        else:
            lines.append("env         full host environment")
        if not self.isolated:
            lines.append(
                "isolation   none. Python runs as the SuperQode process, so these "
                "checks catch mistakes, not an adversarial model."
            )
        elif self.backend == DOCKER_BACKEND:
            lines.append(
                "policy      workspace mounts enforce writes; read, shell and command settings "
                "are guardrails because unrestricted Python can use open or subprocess directly."
            )
        return lines


def ensure_read(config: RLMSandboxConfig) -> None:
    if not config.policy.allow_read:
        raise SandboxPolicyError("Reading is disabled by the RLM sandbox policy")


def ensure_write(config: RLMSandboxConfig) -> None:
    if not config.policy.allow_write:
        raise SandboxPolicyError("Writing is disabled by the RLM sandbox policy")


def ensure_command(config: RLMSandboxConfig, command: str | Sequence[str]) -> None:
    """Check one command against the policy before it is executed."""
    policy = config.policy
    if not policy.allow_shell:
        raise SandboxPolicyError("Shell execution is disabled by the RLM sandbox policy")
    if isinstance(command, str):
        if not policy.allow_compound_commands and _COMPOUND_PATTERN.search(command):
            raise SandboxPolicyError(
                f"Compound shell commands are disabled by the RLM sandbox policy: {command!r}"
            )
        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            raise SandboxPolicyError(f"Command cannot be parsed: {command!r}") from exc
    else:
        tokens = [str(item) for item in command]
    if not policy.allowed_commands:
        return
    executable = os.path.basename(tokens[0]) if tokens else ""
    if executable not in policy.allowed_commands:
        raise SandboxPolicyError(
            f"Command {executable!r} is not in the RLM sandbox allowlist "
            f"({', '.join(policy.allowed_commands)})"
        )


def resolved_env(
    config: RLMSandboxConfig,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the child environment, filtered when an allowlist is configured."""
    if config.env_allowlist:
        base = {key: value for key, value in os.environ.items() if key in config.env_allowlist}
    else:
        base = dict(os.environ)
    base.update({str(key): str(value) for key, value in dict(overrides or {}).items()})
    return base


def docker_available(timeout: float = 5.0) -> tuple[bool, str]:
    """Probe the Docker daemon so `:rlm sandbox doctor` reports facts."""
    try:
        completed = subprocess.run(  # noqa: S603,S607 - fixed diagnostic command
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, "docker executable not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"docker did not respond within {timeout:g}s"
    except OSError as error:
        return False, f"docker probe failed: {error}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        return False, detail[0] if detail else "docker daemon is not available"
    return True, f"docker daemon {completed.stdout.strip() or 'available'}"


def _resolve_backend(data: Mapping[str, Any], execution_policy: Any | None) -> str:
    raw = data.get("sandbox")
    if raw is None and execution_policy is not None:
        raw = getattr(execution_policy, "sandbox", None)
    backend = str(raw or HOST_BACKEND).strip().lower()
    if backend in _HOST_ALIASES:
        return HOST_BACKEND
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"Unknown RLM sandbox backend {backend!r}; supported: {', '.join(SUPPORTED_BACKENDS)}"
        )
    return backend


def _resolve_policy(data: Mapping[str, Any], execution_policy: Any | None) -> SandboxPolicy:
    commands = data.get("allowed_commands")
    if commands is None and execution_policy is not None:
        commands = getattr(execution_policy, "allowed_commands", None)
    return SandboxPolicy(
        allow_read=_flag(data, execution_policy, "allow_read", HOST_POLICY.allow_read),
        allow_write=_flag(data, execution_policy, "allow_write", HOST_POLICY.allow_write),
        allow_shell=_flag(data, execution_policy, "allow_shell", HOST_POLICY.allow_shell),
        allowed_commands=tuple(str(item) for item in commands or () if str(item).strip()),
        allow_compound_commands=bool(
            data.get("allow_compound_commands", HOST_POLICY.allow_compound_commands)
        ),
    )


def _flag(
    data: Mapping[str, Any],
    execution_policy: Any | None,
    name: str,
    default: bool,
) -> bool:
    if name in data:
        return bool(data[name])
    if execution_policy is not None and hasattr(execution_policy, name):
        return bool(getattr(execution_policy, name))
    return default


__all__ = [
    "CHILD_GRANULARITY",
    "DEFAULT_IMAGE",
    "DOCKER_BACKEND",
    "MONTY_BACKEND",
    "HOST_BACKEND",
    "HOST_POLICY",
    "IMPLEMENTED_BACKENDS",
    "RLMSandboxConfig",
    "SESSION_GRANULARITY",
    "SUPPORTED_BACKENDS",
    "SUPPORTED_GRANULARITIES",
    "SandboxPolicyError",
    "SandboxUnavailableError",
    "docker_available",
    "ensure_command",
    "ensure_read",
    "ensure_write",
    "resolved_env",
]
