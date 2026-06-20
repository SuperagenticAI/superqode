"""Harness sandbox connector contract.

This module defines the small public surface that local and remote sandbox
providers need to implement for the v2 harness kernel. It is intentionally
provider-lifecycle neutral: callers create/own provider sandboxes, and
connectors adapt them into this protocol.
"""

from __future__ import annotations

import glob as globlib
import importlib
import logging
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SandboxPolicy:
    """Controls model-callable filesystem and shell capabilities."""

    allow_read: bool = True
    allow_write: bool = False
    allow_shell: bool = False
    allowed_commands: tuple[str, ...] = ()
    allow_compound_commands: bool = False


class SandboxCapabilityBackend(str, Enum):
    """Supported sandbox capability profiles."""

    LOCAL = "local"
    LOCAL_OS = "local-os"
    READ_ONLY = "read-only"
    NO_SHELL = "no-shell"
    GIT_WORKTREE = "git-worktree"
    DOCKER = "docker"
    PODMAN = "podman"
    APPLE_CONTAINER = "apple-container"
    E2B = "e2b"
    DAYTONA = "daytona"
    MODAL = "modal"
    VERCEL = "vercel"
    RUNLOOP = "runloop"
    AGENTCORE = "agentcore"
    LANGSMITH = "langsmith"
    REMOTE = "remote"


@dataclass(frozen=True)
class SandboxCapabilities:
    """Capabilities granted by a sandbox backend profile."""

    backend: SandboxCapabilityBackend
    can_read: bool
    can_write: bool
    can_shell: bool
    can_network: bool
    description: str


_OPENAI_SANDBOX_CLIENTS: dict[str, tuple[str, str, Optional[str]]] = {
    "local": ("agents.sandbox.sandboxes.unix_local", "UnixLocalSandboxClient", None),
    "docker": ("agents.sandbox.sandboxes.docker", "DockerSandboxClient", None),
    "e2b": ("agents_e2b", "E2BSandboxClient", "agents-e2b"),
    "daytona": ("agents_daytona", "DaytonaSandboxClient", "agents-daytona"),
    "modal": ("agents_modal", "ModalSandboxClient", "agents-modal"),
    "vercel": ("agents_vercel", "VercelSandboxClient", "agents-vercel"),
    "runloop": ("agents_runloop", "RunloopSandboxClient", "agents-runloop"),
    "blaxel": ("agents_blaxel", "BlaxelSandboxClient", "agents-blaxel"),
    "cloudflare": ("agents_cloudflare", "CloudflareSandboxClient", "agents-cloudflare"),
}


@dataclass(frozen=True)
class SandboxFileInfo:
    """Normalized metadata for a sandbox path."""

    path: str
    is_dir: bool = False
    is_file: bool = False
    size: int = 0
    mtime: float | None = None


@dataclass(frozen=True)
class SandboxShellResult:
    """Result from sandbox shell execution."""

    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "success": self.success,
        }


class SandboxBackend(Protocol):
    """Common interface for local and remote harness sandboxes."""

    provider: str
    policy: SandboxPolicy

    @property
    def id(self) -> str: ...

    def list_files(self, path: str = ".") -> list[SandboxFileInfo]: ...

    def stat(self, path: str) -> SandboxFileInfo: ...

    def exists(self, path: str) -> bool: ...

    def read_file(self, path: str, *, offset: int = 1, limit: int | None = None) -> str: ...

    def read_bytes(self, path: str) -> bytes: ...

    def write_file(self, path: str, content: str) -> str: ...

    def write_bytes(self, path: str, content: bytes) -> str: ...

    def mkdir(self, path: str, *, recursive: bool = True) -> str: ...

    def rm(self, path: str, *, recursive: bool = False, force: bool = False) -> str: ...

    def edit_file(self, path: str, old: str, new: str, *, replace_all: bool = False) -> str: ...

    def grep(self, pattern: str, *, path: str = ".", include: str | None = None) -> str: ...

    def glob(self, pattern: str) -> str: ...

    def shell(
        self,
        command: str,
        *,
        timeout: int | None = 120,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxShellResult: ...


HarnessSandboxBackend = SandboxBackend


class LocalSandboxBackend:
    """Path-bounded local sandbox connector."""

    provider = "local"

    def __init__(
        self,
        root: str | Path,
        *,
        policy: SandboxPolicy | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.policy = policy or SandboxPolicy()
        self.env = dict(env or {})

    @property
    def id(self) -> str:
        return f"local:{self.root}"

    def list_files(self, path: str = ".") -> list[SandboxFileInfo]:
        self._require_read()
        target = self.resolve(path)
        paths = [target] if target.is_file() else sorted(target.iterdir())
        return [self._file_info(child) for child in paths]

    def stat(self, path: str) -> SandboxFileInfo:
        self._require_read()
        return self._file_info(self.resolve(path))

    def exists(self, path: str) -> bool:
        self._require_read()
        return self.resolve(path, must_exist=False).exists()

    def read_file(self, path: str, *, offset: int = 1, limit: int | None = None) -> str:
        self._require_read()
        target = self.resolve(path)
        if target.is_dir():
            return "\n".join(
                sorted(child.name + ("/" if child.is_dir() else "") for child in target.iterdir())
            )
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(offset - 1, 0)
        selected = lines[start : start + limit if limit else None]
        return "\n".join(selected)

    def read_bytes(self, path: str) -> bytes:
        self._require_read()
        target = self.resolve(path)
        if target.is_dir():
            raise IsADirectoryError(path)
        return target.read_bytes()

    def write_file(self, path: str, content: str) -> str:
        self._require_write()
        target = self.resolve(path, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {self.relative(target)}"

    def write_bytes(self, path: str, content: bytes) -> str:
        self._require_write()
        target = self.resolve(path, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return f"Wrote {self.relative(target)}"

    def mkdir(self, path: str, *, recursive: bool = True) -> str:
        self._require_write()
        target = self.resolve(path, must_exist=False)
        target.mkdir(parents=recursive, exist_ok=recursive)
        return f"Created {self.relative(target)}"

    def rm(self, path: str, *, recursive: bool = False, force: bool = False) -> str:
        self._require_write()
        target = self.resolve(path, must_exist=False)
        if not target.exists():
            if force:
                return f"Removed {self.relative(target)}"
            raise FileNotFoundError(path)
        if target.is_dir():
            if not recursive:
                raise IsADirectoryError(path)
            shutil.rmtree(target)
        else:
            target.unlink()
        return f"Removed {self.relative(target)}"

    def edit_file(self, path: str, old: str, new: str, *, replace_all: bool = False) -> str:
        self._require_write()
        target = self.resolve(path)
        content = target.read_text(encoding="utf-8", errors="replace")
        count = content.count(old)
        if count == 0:
            raise ValueError(f"Text not found in {path}")
        updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
        target.write_text(updated, encoding="utf-8")
        return f"Edited {self.relative(target)} ({count if replace_all else 1} replacement)"

    def grep(self, pattern: str, *, path: str = ".", include: str | None = None) -> str:
        self._require_read()
        root = self.resolve(path)
        files = root.rglob(include or "*") if root.is_dir() else [root]
        regex = re.compile(pattern)
        matches: list[str] = []
        for file_path in files:
            if not file_path.is_file():
                continue
            for index, line in enumerate(
                file_path.read_text(encoding="utf-8", errors="replace").splitlines(),
                start=1,
            ):
                if regex.search(line):
                    matches.append(f"{self.relative(file_path)}:{index}:{line}")
        return "\n".join(matches)

    def glob(self, pattern: str) -> str:
        self._require_read()
        search = str(self.resolve(pattern, must_exist=False))
        paths = sorted(globlib.glob(search, recursive=True))
        return "\n".join(self.relative(Path(path)) for path in paths)

    def shell(
        self,
        command: str,
        *,
        timeout: int | None = 120,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxShellResult:
        require_shell(self.policy, command)
        workdir = self.resolve(cwd or ".")
        if not workdir.is_dir():
            raise NotADirectoryError(cwd or ".")
        completed = subprocess.run(
            command,
            cwd=workdir,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, **self.env, **(env or {})},
        )
        return SandboxShellResult(
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def resolve(self, path: str, *, must_exist: bool = True) -> Path:
        raw = str(path or ".")
        if raw in {"/", "/workspace"}:
            raw = "."
        elif raw.startswith("/workspace/"):
            raw = raw.removeprefix("/workspace/")
        elif raw.startswith("/"):
            raw = raw[1:]
        target = Path(raw).expanduser()
        if not target.is_absolute():
            target = self.root / target
        target = target.resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path escapes sandbox root: {path}") from exc
        if must_exist and not target.exists():
            raise FileNotFoundError(path)
        return target

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def to_backend_path(self, path: Path) -> str:
        rel = self.relative(path)
        return "/" if not rel else "/" + rel

    def _file_info(self, path: Path) -> SandboxFileInfo:
        stat = path.stat()
        return SandboxFileInfo(
            path=self.to_backend_path(path),
            is_dir=path.is_dir(),
            is_file=path.is_file(),
            size=0 if path.is_dir() else stat.st_size,
            mtime=stat.st_mtime,
        )

    def _require_read(self) -> None:
        if not self.policy.allow_read:
            raise PermissionError("Read access is disabled for this sandbox.")

    def _require_write(self) -> None:
        require_write(self.policy)


def require_write(policy: SandboxPolicy) -> None:
    if not policy.allow_write:
        raise PermissionError("Write access is disabled for this sandbox.")


def require_shell(policy: SandboxPolicy, command: str) -> None:
    if not policy.allow_shell:
        raise PermissionError("Shell execution is disabled for this sandbox.")
    _reject_unsafe_shell(command, policy)
    if policy.allowed_commands:
        executable = _first_executable(command)
        if executable not in policy.allowed_commands:
            raise PermissionError(f"Command is not allowed: {executable}")


def sandbox_policy_from_execution_policy(policy: Any) -> SandboxPolicy:
    """Create a sandbox policy from a HarnessSpec execution policy object."""
    return SandboxPolicy(
        allow_read=bool(getattr(policy, "allow_read", True)),
        allow_write=bool(getattr(policy, "allow_write", False)),
        allow_shell=bool(getattr(policy, "allow_shell", False)),
        allowed_commands=tuple(getattr(policy, "allowed_commands", ()) or ()),
        allow_compound_commands=bool(getattr(policy, "allow_compound_commands", False)),
    )


def get_sandbox_capabilities(
    backend: str | SandboxCapabilityBackend,
) -> SandboxCapabilities:
    """Return capabilities for a sandbox backend profile."""
    selected = SandboxCapabilityBackend(backend)
    capabilities: dict[SandboxCapabilityBackend, SandboxCapabilities] = {
        SandboxCapabilityBackend.LOCAL: SandboxCapabilities(
            selected, True, True, True, True, "Local workspace with no sandbox isolation."
        ),
        SandboxCapabilityBackend.LOCAL_OS: SandboxCapabilities(
            selected,
            True,
            True,
            True,
            False,
            "Local OS sandbox using macOS Seatbelt or Linux Bubblewrap.",
        ),
        SandboxCapabilityBackend.READ_ONLY: SandboxCapabilities(
            selected,
            True,
            False,
            False,
            False,
            "Read-only workspace; no writes, shell, or network.",
        ),
        SandboxCapabilityBackend.NO_SHELL: SandboxCapabilities(
            selected, True, True, False, True, "Local workspace without shell execution."
        ),
        SandboxCapabilityBackend.GIT_WORKTREE: SandboxCapabilities(
            selected, True, True, True, True, "Git worktree-isolated workspace."
        ),
        SandboxCapabilityBackend.DOCKER: SandboxCapabilities(
            selected, True, True, True, False, "Local Docker container-isolated workspace."
        ),
        SandboxCapabilityBackend.PODMAN: SandboxCapabilities(
            selected, True, True, True, False, "Local Podman container-isolated workspace."
        ),
        SandboxCapabilityBackend.APPLE_CONTAINER: SandboxCapabilities(
            selected,
            True,
            True,
            True,
            False,
            "macOS-native local container-isolated workspace.",
        ),
        SandboxCapabilityBackend.E2B: SandboxCapabilities(
            selected, True, True, True, True, "E2B remote sandbox workspace."
        ),
        SandboxCapabilityBackend.DAYTONA: SandboxCapabilities(
            selected, True, True, True, True, "Daytona remote sandbox workspace."
        ),
        SandboxCapabilityBackend.MODAL: SandboxCapabilities(
            selected, True, True, True, True, "Modal cloud sandbox workspace."
        ),
        SandboxCapabilityBackend.VERCEL: SandboxCapabilities(
            selected, True, True, True, True, "Vercel Sandbox cloud workspace."
        ),
        SandboxCapabilityBackend.RUNLOOP: SandboxCapabilities(
            selected, True, True, True, True, "Runloop remote devbox workspace."
        ),
        SandboxCapabilityBackend.AGENTCORE: SandboxCapabilities(
            selected,
            True,
            True,
            True,
            True,
            "Amazon Bedrock AgentCore Code Interpreter sandbox.",
        ),
        SandboxCapabilityBackend.LANGSMITH: SandboxCapabilities(
            selected, True, True, True, True, "LangSmith remote sandbox workspace."
        ),
        SandboxCapabilityBackend.REMOTE: SandboxCapabilities(
            selected, True, True, True, True, "Remote sandbox backend."
        ),
    }
    return capabilities[selected]


def apply_backend_permissions(config: Any, backend: str | SandboxCapabilityBackend) -> Any:
    """Apply backend capability restrictions to an existing permission config."""
    from ..tools.permissions import Permission, PermissionConfig, ToolGroup

    caps = get_sandbox_capabilities(backend)
    groups = dict(config.groups)
    tools = dict(config.tools)

    if not caps.can_read:
        groups[ToolGroup.READ] = Permission.DENY
        groups[ToolGroup.SEARCH] = Permission.DENY
        groups[ToolGroup.DIAGNOSTICS] = Permission.DENY
    if not caps.can_write:
        groups[ToolGroup.WRITE] = Permission.DENY
    if not caps.can_shell:
        groups[ToolGroup.SHELL] = Permission.DENY
        tools["bash"] = Permission.DENY
    if not caps.can_network:
        groups[ToolGroup.NETWORK] = Permission.DENY
        tools["fetch"] = Permission.DENY
        tools["download"] = Permission.DENY
        tools["web_search"] = Permission.DENY
        tools["web_fetch"] = Permission.DENY

    return PermissionConfig(
        default=config.default,
        groups=groups,
        tools=tools,
        allow_patterns=list(config.allow_patterns),
        deny_patterns=list(config.deny_patterns),
    )


def supported_openai_sandbox_backends() -> list[str]:
    """Return OpenAI Agents SandboxAgent backend names understood by the harness."""
    return list(_OPENAI_SANDBOX_CLIENTS.keys())


def supported_sandbox_backends() -> list[str]:
    """Compatibility alias for OpenAI Agents sandbox backend names."""
    return supported_openai_sandbox_backends()


def is_openai_sandbox_backend_available(name: str) -> bool:
    """Return True when an OpenAI Agents sandbox client module imports."""
    entry = _OPENAI_SANDBOX_CLIENTS.get(name.lower())
    if entry is None:
        return False
    module_path, _class_name, _extra = entry
    try:
        importlib.import_module(module_path)
        return True
    except ImportError:
        return False


def is_sandbox_backend_available(name: str) -> bool:
    """Compatibility alias for OpenAI Agents sandbox availability."""
    return is_openai_sandbox_backend_available(name)


def build_openai_sandbox_client(name: str) -> Any:
    """Build an OpenAI Agents sandbox client for the selected backend."""
    from ..runtime.errors import RuntimeNotInstalledError

    key = name.lower().strip()
    if key not in _OPENAI_SANDBOX_CLIENTS:
        raise ValueError(
            f"Unknown sandbox backend '{name}'. Known: {', '.join(sorted(_OPENAI_SANDBOX_CLIENTS))}"
        )
    module_path, class_name, extra = _OPENAI_SANDBOX_CLIENTS[key]
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = f"pip install {extra}" if extra else "pip install superqode[openai-agents]"
        raise RuntimeNotInstalledError(
            f"Sandbox backend '{name}' requires '{module_path}'. Install with: {hint}"
        ) from exc

    cls = getattr(module, class_name, None)
    if cls is None:
        raise RuntimeNotInstalledError(
            f"Module '{module_path}' has no class '{class_name}' for backend '{name}'"
        )
    return cls()


def build_sandbox_client(name: str) -> Any:
    """Compatibility alias for OpenAI Agents sandbox client construction."""
    return build_openai_sandbox_client(name)


def build_openai_sandbox_manifest(config: Any) -> Any:
    """Translate an agent config into an OpenAI Agents sandbox Manifest."""
    from ..runtime.errors import RuntimeNotInstalledError

    try:
        from agents.sandbox import Manifest
        from agents.sandbox.entries import LocalDir
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "openai-agents 0.14+ is required for sandbox manifests. "
            "Install with: pip install 'superqode[openai-agents]'"
        ) from exc

    working_directory = Path(config.working_directory)
    return Manifest(entries={"repo": LocalDir(src=working_directory)})


def build_manifest(config: Any) -> Any:
    """Compatibility alias for OpenAI Agents sandbox Manifest construction."""
    return build_openai_sandbox_manifest(config)


def build_openai_sandbox_agent(
    *,
    name: str,
    instructions: str,
    tools: list,
    model: Any,
    manifest: Any,
) -> Any:
    """Construct an OpenAI Agents SandboxAgent."""
    from ..runtime.errors import RuntimeNotInstalledError

    try:
        from agents.sandbox import SandboxAgent
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "openai-agents 0.14+ is required for SandboxAgent. "
            "Install with: pip install 'superqode[openai-agents]'"
        ) from exc

    return SandboxAgent(
        name=name,
        instructions=instructions,
        tools=tools,
        model=model,
        default_manifest=manifest,
    )


def build_sandbox_agent(
    *,
    name: str,
    instructions: str,
    tools: list,
    model: Any,
    manifest: Any,
) -> Any:
    """Compatibility alias for OpenAI Agents SandboxAgent construction."""
    return build_openai_sandbox_agent(
        name=name,
        instructions=instructions,
        tools=tools,
        model=model,
        manifest=manifest,
    )


def build_openai_sandbox_run_config(client: Any, base_run_config: Any) -> Any:
    """Return an OpenAI Agents RunConfig with sandbox execution enabled."""
    from ..runtime.errors import RuntimeNotInstalledError

    try:
        from agents.run import RunConfig
        from agents.sandbox import SandboxRunConfig
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "openai-agents 0.14+ is required for SandboxRunConfig. "
            "Install with: pip install 'superqode[openai-agents]'"
        ) from exc

    return RunConfig(
        tracing_disabled=getattr(base_run_config, "tracing_disabled", True),
        sandbox=SandboxRunConfig(client=client),
    )


def build_sandbox_run_config(client: Any, base_run_config: Any) -> Any:
    """Compatibility alias for OpenAI Agents sandbox RunConfig construction."""
    return build_openai_sandbox_run_config(client, base_run_config)


def _reject_unsafe_shell(command: str, policy: SandboxPolicy) -> None:
    if policy.allow_compound_commands:
        return
    if "`" in command or "$(" in command or "\n" in command:
        raise PermissionError(
            "Compound shell syntax is disabled for this sandbox. "
            "Enable allow_compound_commands only for trusted workflows."
        )
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise PermissionError(f"Invalid shell command: {exc}") from exc
    banned = {"&&", "||", ";", "|", ">", "<", ">>", "<<"}
    for token in tokens:
        if token in banned or set(token) <= {"&", "|", ";", ">", "<"}:
            raise PermissionError(
                "Compound shell syntax is disabled for this sandbox. "
                "Enable allow_compound_commands only for trusted workflows."
            )


def _first_executable(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise PermissionError(f"Invalid shell command: {exc}") from exc
    return parts[0] if parts else ""
