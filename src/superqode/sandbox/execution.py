"""Sandbox command execution providers."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class SandboxRunResult:
    """Result from a sandbox command."""

    backend: str
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    sandbox_id: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "backend": self.backend,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "sandbox_id": self.sandbox_id,
            "success": self.success,
        }


@dataclass(frozen=True)
class SandboxProviderStatus:
    """Provider availability and setup status."""

    backend: str
    available: bool
    detail: str
    required_env: List[str]
    optional_dependency: Optional[str] = None
    executable: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "backend": self.backend,
            "available": self.available,
            "detail": self.detail,
            "required_env": self.required_env,
            "optional_dependency": self.optional_dependency,
            "executable": self.executable,
        }


def _missing_env(env_vars: List[str]) -> List[str]:
    return [name for name in env_vars if not os.environ.get(name)]


def sandbox_provider_status(backend: str) -> SandboxProviderStatus:
    """Return availability status for a sandbox execution backend."""
    if backend == "docker":
        available = shutil.which("docker") is not None
        return SandboxProviderStatus(
            backend=backend,
            available=available,
            detail="docker CLI found" if available else "docker CLI not found",
            required_env=[],
            executable="docker",
        )
    if backend == "e2b":
        missing = _missing_env(["E2B_API_KEY"])
        try:
            __import__("e2b")
            has_dep = True
        except ImportError:
            has_dep = False
        return SandboxProviderStatus(
            backend=backend,
            available=has_dep and not missing,
            detail="ready" if has_dep and not missing else "install e2b and set E2B_API_KEY",
            required_env=["E2B_API_KEY"],
            optional_dependency="e2b",
        )
    if backend == "daytona":
        missing = _missing_env(["DAYTONA_API_KEY"])
        try:
            __import__("daytona")
            has_dep = True
        except ImportError:
            has_dep = False
        return SandboxProviderStatus(
            backend=backend,
            available=has_dep and not missing,
            detail="ready"
            if has_dep and not missing
            else "install daytona and set DAYTONA_API_KEY",
            required_env=["DAYTONA_API_KEY"],
            optional_dependency="daytona",
        )
    if backend == "modal":
        try:
            __import__("modal")
            has_dep = True
        except ImportError:
            has_dep = False
        available = has_dep and bool(
            os.environ.get("MODAL_TOKEN_ID") or os.environ.get("MODAL_PROFILE")
        )
        return SandboxProviderStatus(
            backend=backend,
            available=available,
            detail="ready" if available else "install modal and run modal setup",
            required_env=[],
            optional_dependency="modal",
        )
    if backend == "vercel":
        available = shutil.which("sandbox") is not None
        has_auth = bool(os.environ.get("VERCEL_OIDC_TOKEN") or os.environ.get("VERCEL_TOKEN"))
        return SandboxProviderStatus(
            backend=backend,
            available=available and has_auth,
            detail="ready"
            if available and has_auth
            else "install Vercel sandbox CLI and authenticate",
            required_env=["VERCEL_OIDC_TOKEN or VERCEL_TOKEN"],
            executable="sandbox",
        )
    if backend == "runloop":
        missing = _missing_env(["RUNLOOP_API_KEY"])
        try:
            __import__("runloop_api_client")
            __import__("langchain_runloop")
            has_dep = True
        except ImportError:
            has_dep = False
        return SandboxProviderStatus(
            backend=backend,
            available=has_dep and not missing,
            detail=(
                "ready"
                if has_dep and not missing
                else "install runloop_api_client/langchain_runloop and set RUNLOOP_API_KEY"
            ),
            required_env=["RUNLOOP_API_KEY"],
            optional_dependency="runloop_api_client, langchain_runloop",
        )
    if backend == "agentcore":
        try:
            __import__("bedrock_agentcore")
            __import__("langchain_agentcore_codeinterpreter")
            has_dep = True
        except ImportError:
            has_dep = False
        return SandboxProviderStatus(
            backend=backend,
            available=has_dep,
            detail=(
                "ready"
                if has_dep
                else "install bedrock_agentcore/langchain_agentcore_codeinterpreter and configure AWS auth"
            ),
            required_env=["AWS credentials"],
            optional_dependency="bedrock_agentcore, langchain_agentcore_codeinterpreter",
        )
    if backend == "langsmith":
        missing = _missing_env(["LANGSMITH_API_KEY"])
        try:
            __import__("langsmith")
            __import__("deepagents")
            has_dep = True
        except ImportError:
            has_dep = False
        return SandboxProviderStatus(
            backend=backend,
            available=has_dep and not missing,
            detail=(
                "ready"
                if has_dep and not missing
                else "install langsmith/deepagents and set LANGSMITH_API_KEY"
            ),
            required_env=["LANGSMITH_API_KEY"],
            optional_dependency="langsmith, deepagents",
        )
    return SandboxProviderStatus(
        backend=backend,
        available=False,
        detail=f"unsupported sandbox backend: {backend}",
        required_env=[],
    )


def run_in_sandbox(
    backend: str,
    command: str,
    cwd: Path,
    timeout: int = 300,
    image: str = "python:3.12-slim",
) -> SandboxRunResult:
    """Run a shell command using a sandbox backend."""
    if backend == "docker":
        return _run_docker(command, cwd, timeout, image)
    if backend == "e2b":
        return _run_e2b(command, timeout)
    if backend == "daytona":
        return _run_daytona(command, timeout)
    if backend == "modal":
        return _run_modal(command, timeout, image)
    if backend == "vercel":
        return _run_vercel(command, timeout)
    if backend == "runloop":
        return _run_runloop(command)
    if backend == "agentcore":
        return _run_agentcore(command)
    if backend == "langsmith":
        return _run_langsmith(command)
    raise ValueError(f"Unsupported sandbox execution backend: {backend}")


def _run_docker(command: str, cwd: Path, timeout: int, image: str) -> SandboxRunResult:
    if shutil.which("docker") is None:
        raise RuntimeError("docker CLI not found")
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{cwd.resolve()}:/workspace",
            "-w",
            "/workspace",
            image,
            "sh",
            "-lc",
            command,
        ],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return SandboxRunResult(
        backend="docker",
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _run_e2b(command: str, timeout: int) -> SandboxRunResult:
    try:
        from e2b import Sandbox
    except ImportError as exc:
        raise RuntimeError("E2B support requires `pip install e2b`") from exc

    sandbox = Sandbox.create()
    try:
        result = sandbox.commands.run(command, timeout=timeout)
        stdout = getattr(result, "stdout", "") or getattr(result, "logs", "") or str(result)
        stderr = getattr(result, "stderr", "") or ""
        exit_code = int(getattr(result, "exit_code", getattr(result, "error", 0) or 0))
        sandbox_id = getattr(sandbox, "sandbox_id", None) or getattr(sandbox, "id", None)
        return SandboxRunResult("e2b", command, exit_code, stdout, stderr, sandbox_id)
    finally:
        kill = getattr(sandbox, "kill", None)
        if callable(kill):
            kill()


def _run_daytona(command: str, timeout: int) -> SandboxRunResult:
    try:
        from daytona import Daytona
    except ImportError as exc:
        raise RuntimeError("Daytona support requires `pip install daytona`") from exc

    daytona = Daytona()
    sandbox = daytona.create()
    try:
        response = sandbox.process.exec(command, timeout=timeout)
        stdout = getattr(response, "result", "") or str(response)
        stderr = getattr(response, "error", "") or ""
        exit_code = int(getattr(response, "exit_code", 0) or 0)
        sandbox_id = getattr(sandbox, "id", None)
        return SandboxRunResult("daytona", command, exit_code, stdout, stderr, sandbox_id)
    finally:
        delete = getattr(sandbox, "delete", None)
        if callable(delete):
            delete()


def _run_modal(command: str, timeout: int, image: str) -> SandboxRunResult:
    try:
        import modal
    except ImportError as exc:
        raise RuntimeError("Modal support requires `pip install modal`") from exc

    app = modal.App.lookup("superqode-sandbox", create_if_missing=True)
    modal_image = modal.Image.from_registry(image)
    sandbox = modal.Sandbox.create(
        "sh", "-lc", command, app=app, image=modal_image, timeout=timeout
    )
    exit_code = sandbox.wait()
    stdout = sandbox.stdout.read() if sandbox.stdout else ""
    stderr = sandbox.stderr.read() if sandbox.stderr else ""
    sandbox_id = getattr(sandbox, "object_id", None)
    terminate = getattr(sandbox, "terminate", None)
    if callable(terminate):
        terminate()
    return SandboxRunResult("modal", command, int(exit_code or 0), stdout, stderr, sandbox_id)


def _run_vercel(command: str, timeout: int) -> SandboxRunResult:
    if shutil.which("sandbox") is None:
        raise RuntimeError("Vercel sandbox CLI not found")
    completed = subprocess.run(
        ["sandbox", "run", "--", "sh", "-lc", command],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return SandboxRunResult(
        backend="vercel",
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _coerce_execute_result(result) -> tuple[int, str, str]:
    output = getattr(result, "output", None)
    stdout = getattr(result, "stdout", None) or output or str(result)
    stderr = getattr(result, "stderr", "") or getattr(result, "error", "") or ""
    exit_code = int(getattr(result, "exit_code", getattr(result, "return_code", 0)) or 0)
    return exit_code, stdout, stderr


def _run_runloop(command: str) -> SandboxRunResult:
    try:
        from langchain_runloop import RunloopSandbox
        from runloop_api_client import RunloopSDK
    except ImportError as exc:
        raise RuntimeError(
            "Runloop support requires `pip install runloop_api_client langchain-runloop`"
        ) from exc

    api_key = os.environ.get("RUNLOOP_API_KEY")
    if not api_key:
        raise RuntimeError("RUNLOOP_API_KEY is required for Runloop sandbox execution")

    client = RunloopSDK(bearer_token=api_key)
    devbox = client.devbox.create()
    try:
        backend = RunloopSandbox(devbox=devbox)
        exit_code, stdout, stderr = _coerce_execute_result(backend.execute(command))
        sandbox_id = getattr(devbox, "id", None)
        return SandboxRunResult("runloop", command, exit_code, stdout, stderr, sandbox_id)
    finally:
        shutdown = getattr(devbox, "shutdown", None)
        if callable(shutdown):
            shutdown()


def _run_agentcore(command: str) -> SandboxRunResult:
    try:
        from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter
        from langchain_agentcore_codeinterpreter import AgentCoreSandbox
    except ImportError as exc:
        raise RuntimeError(
            "AgentCore support requires `pip install bedrock-agentcore "
            "langchain-agentcore-codeinterpreter`"
        ) from exc

    interpreter = CodeInterpreter(region=os.environ.get("AWS_REGION", "us-west-2"))
    interpreter.start()
    try:
        backend = AgentCoreSandbox(interpreter=interpreter)
        exit_code, stdout, stderr = _coerce_execute_result(backend.execute(command))
        sandbox_id = getattr(interpreter, "session_id", None)
        return SandboxRunResult("agentcore", command, exit_code, stdout, stderr, sandbox_id)
    finally:
        interpreter.stop()


def _run_langsmith(command: str) -> SandboxRunResult:
    try:
        from deepagents.backends.langsmith import LangSmithSandbox
        from langsmith.sandbox import SandboxClient
    except ImportError as exc:
        raise RuntimeError(
            "LangSmith sandbox support requires `pip install langsmith deepagents`"
        ) from exc

    client = SandboxClient()
    template = os.environ.get("LANGSMITH_SANDBOX_TEMPLATE", "deepagents-deploy")
    ls_sandbox = client.create_sandbox(template_name=template)
    backend = LangSmithSandbox(sandbox=ls_sandbox)
    try:
        exit_code, stdout, stderr = _coerce_execute_result(backend.execute(command))
        sandbox_id = getattr(backend, "id", None)
        return SandboxRunResult("langsmith", command, exit_code, stdout, stderr, sandbox_id)
    finally:
        sandbox_id = getattr(backend, "id", None)
        if sandbox_id:
            client.delete_sandbox(sandbox_id)
