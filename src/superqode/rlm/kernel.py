"""Persistent Python execution for the native RLM harness.

The first runtime deliberately matches the host-permission behaviour of other
unrestricted coding harnesses. Isolation belongs at the kernel-process
boundary; it cannot be promised by Python wrapper objects alone.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import pickle
import re
import subprocess
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence, cast

from superqode.pipy.messages import TextContent
from superqode.pipy.tools.base import AgentTool, AgentToolResult

from .context import ContextPolicy, RLMContext
from .sandbox import (
    RLMSandboxConfig,
    ensure_command,
    ensure_read,
    ensure_write,
    resolved_env,
)

DEFAULT_PYTHON_OBSERVATION_CHARS = 20_000


class _BoundedTextBuffer(io.TextIOBase):
    """Bound output even in unsafe host mode so memory use stays predictable."""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, int(limit))
        self.parts: list[str] = []
        self.size = 0
        self.omitted = 0

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        text = str(value)
        available = max(0, self.limit - self.size)
        if available:
            kept = text[:available]
            self.parts.append(kept)
            self.size += len(kept)
        self.omitted += max(0, len(text) - available)
        return len(text)

    def getvalue(self) -> str:
        value = "".join(self.parts)
        if self.omitted:
            value += f"\n... [{self.omitted:,} output characters omitted by kernel limit] ...\n"
        return value


@dataclass(frozen=True, slots=True)
class ShellResult:
    """A compact, Python-friendly command result."""

    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def __repr__(self) -> str:
        fields = [f"returncode={self.returncode}"]
        if self.stdout:
            fields.append(f"stdout={self.stdout!r}")
        if self.stderr:
            fields.append(f"stderr={self.stderr!r}")
        return f"ShellResult({', '.join(fields)})"


class Workspace:
    """Convenience repository API injected into the Python namespace.

    The policy checks here are guardrails. They make a harness's declared
    execution policy real for ordinary use, but Python in this namespace can
    still reach the filesystem directly, so they are not an isolation boundary.
    """

    def __init__(self, root: str | Path, *, sandbox: RLMSandboxConfig | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.sandbox = sandbox or RLMSandboxConfig()

    def _path(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        target = (
            candidate.resolve() if candidate.is_absolute() else (self.root / candidate).resolve()
        )
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {path}") from exc
        return target

    def read(self, path: str | Path, *, offset: int = 1, limit: int | None = None) -> str:
        ensure_read(self.sandbox)
        target = self._path(path)
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, offset - 1)
        selected = lines[start : start + limit if limit else None]
        return "\n".join(selected)

    def write(self, path: str | Path, content: str) -> str:
        ensure_write(self.sandbox)
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target.relative_to(self.root))

    def edit(self, path: str | Path, old: str, new: str, *, replace_all: bool = False) -> str:
        # An edit both reads and rewrites, so it needs each permission.
        ensure_read(self.sandbox)
        ensure_write(self.sandbox)
        target = self._path(path)
        content = target.read_text(encoding="utf-8", errors="replace")
        count = content.count(old)
        if count == 0:
            raise ValueError(f"Text not found in {path}")
        updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
        target.write_text(updated, encoding="utf-8")
        return f"edited {target.relative_to(self.root)} ({count if replace_all else 1} replacement)"

    def glob(self, pattern: str) -> list[str]:
        ensure_read(self.sandbox)
        return [str(path.relative_to(self.root)) for path in sorted(self.root.glob(pattern))]

    def search(self, pattern: str, path: str | Path = ".") -> list[str]:
        ensure_read(self.sandbox)
        root = self._path(path)
        regex = re.compile(pattern)
        files = root.rglob("*") if root.is_dir() else (root,)
        matches: list[str] = []
        for file_path in files:
            if not file_path.is_file():
                continue
            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, 1):
                if regex.search(line):
                    matches.append(f"{file_path.relative_to(self.root)}:{number}:{line}")
        return matches


class Shell:
    """Command runner made available inside the Python namespace."""

    def __init__(self, cwd: str | Path, *, sandbox: RLMSandboxConfig | None = None) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.sandbox = sandbox or RLMSandboxConfig()

    def run(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None = 120,
        env: dict[str, str] | None = None,
    ) -> ShellResult:
        ensure_command(self.sandbox, command)
        shell = isinstance(command, str)
        completed = subprocess.run(
            command,
            cwd=self.cwd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=resolved_env(self.sandbox, env),
        )
        display = command if isinstance(command, str) else " ".join(map(str, command))
        return ShellResult(display, completed.returncode, completed.stdout, completed.stderr)


class RLMNamespace:
    """Root object for RLM-specific Python operations."""

    def __init__(self, supervisor: Any | None = None, *, agent_id: str = "root") -> None:
        self._supervisor = supervisor
        self._agent_id = agent_id

    def bind(self, supervisor: Any, *, agent_id: str) -> None:
        self._supervisor = supervisor
        self._agent_id = agent_id

    def run(self, prompt: str, *, model: str | None = None):
        """Start one live child RLM session and return its handle immediately."""
        return self._require_supervisor().spawn(prompt, parent_id=self._agent_id, model=model)

    spawn = run

    def run_batch(self, prompts: Sequence[str], *, model: str | None = None):
        return self._require_supervisor().spawn_batch(
            prompts,
            parent_id=self._agent_id,
            model=model,
        )

    spawn_batch = run_batch

    def agents(self, *, all_agents: bool = False) -> list[dict[str, Any]]:
        parent_id = None if all_agents else self._agent_id
        return self._require_supervisor().snapshots(parent_id=parent_id)

    def wait_all(self, handles: Sequence[Any]) -> list[str]:
        supervisor = self._require_supervisor()
        identifiers = [str(getattr(handle, "id", handle)) for handle in handles]
        return supervisor.call(supervisor.wait_all(identifiers))

    def send(self, agent: Any, message: str) -> None:
        supervisor = self._require_supervisor()
        supervisor.call(supervisor.send(str(getattr(agent, "id", agent)), message))

    def steer(self, agent: Any, instruction: str) -> None:
        supervisor = self._require_supervisor()
        supervisor.call(supervisor.steer(str(getattr(agent, "id", agent)), instruction))

    def cancel(self, agent: Any) -> None:
        supervisor = self._require_supervisor()
        supervisor.call(supervisor.cancel(str(getattr(agent, "id", agent))))

    def delete(self, agent: Any) -> None:
        self._require_supervisor().delete(str(getattr(agent, "id", agent)))

    def help(self) -> str:
        return (
            "Use workspace for repository work, shell.run for commands, and rlm.run or "
            "rlm.run_batch for live child agents. Agent handles support status, send, steer, "
            "wait, cancel, and delete."
        )

    def _require_supervisor(self):
        if self._supervisor is None:
            raise RuntimeError("Recursive RLM supervision is not configured for this kernel")
        return self._supervisor


class SubcallNamespace:
    """`llm_query` for synchronous kernel code.

    The executor is async and owned by the host; kernel code runs in a worker
    thread. This bridges the two, and deliberately exposes no way to change the
    quota: the limits belong to the executor, not to anything reachable here.
    """

    def __init__(self, executor: Any | None = None, loop: Any | None = None) -> None:
        self._executor = executor
        self._loop = loop

    def bind(self, executor: Any, loop: Any) -> None:
        self._executor = executor
        self._loop = loop

    def query(self, prompt: str, *, context: str = "", model: str | None = None) -> Any:
        executor = self._require()
        return self._call(executor.query(str(prompt), context=str(context or ""), model=model))

    def query_batch(
        self,
        prompts: Sequence[str],
        *,
        contexts: Sequence[str] | None = None,
        model: str | None = None,
    ) -> list[Any]:
        executor = self._require()
        return self._call(
            executor.query_batch([str(item) for item in prompts], contexts=contexts, model=model)
        )

    def usage(self) -> dict[str, Any]:
        return dict(self._require().snapshot())

    def _require(self) -> Any:
        if self._executor is None or self._loop is None:
            raise RuntimeError("Semantic subcalls are not configured for this kernel")
        return self._executor

    def _call(self, coroutine: Any) -> Any:
        loop = self._loop
        if loop is None:
            coroutine.close()
            raise RuntimeError("Semantic subcalls are not configured for this kernel")
        if threading.get_ident() == getattr(loop, "_thread_id", None):
            coroutine.close()
            raise RuntimeError("llm_query must be called from the Python tool, not the event loop")
        return asyncio.run_coroutine_threadsafe(coroutine, loop).result()


@dataclass(frozen=True, slots=True)
class PythonExecutionResult:
    output: str
    value_repr: str
    error: str | None = None

    @property
    def text(self) -> str:
        parts = [part for part in (self.output.rstrip(), self.value_repr) if part]
        if self.error:
            parts.append(self.error.rstrip())
        return "\n".join(parts) or "(no output)"

    def observation(self, max_chars: int = DEFAULT_PYTHON_OBSERVATION_CHARS) -> tuple[str, bool]:
        """Build a bounded model observation without changing persistent state.

        Repository-sized values belong in persistent Python variables, not in
        the root model's history. The tool boundary applies this limit after
        execution; assigning a value keeps it available for later bounded
        inspection even when its displayed representation is truncated.
        """
        text = self.text
        limit = max(256, int(max_chars))
        if len(text) <= limit:
            return text, False
        omitted = len(text) - limit
        marker = (
            f"\n... [Python observation truncated; {omitted:,} characters omitted. "
            "Keep large values in a variable and inspect bounded slices.] ...\n"
        )
        available = max(0, limit - len(marker))
        head = available * 3 // 4
        tail = available - head
        return text[:head] + marker + (text[-tail:] if tail else ""), True


class PersistentPythonKernel:
    """One persistent Python namespace owned by one RLM session."""

    def __init__(
        self,
        cwd: str | Path,
        *,
        supervisor: Any | None = None,
        agent_id: str = "root",
        checkpoint_path: str | Path | None = None,
        sandbox: RLMSandboxConfig | None = None,
        context_policy: ContextPolicy | None = None,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.sandbox = sandbox or RLMSandboxConfig()
        self.workspace = Workspace(self.cwd, sandbox=self.sandbox)
        self.shell = Shell(self.cwd, sandbox=self.sandbox)
        self.rlm = RLMNamespace(supervisor, agent_id=agent_id)
        self.subcalls = SubcallNamespace()
        self.context = RLMContext(self.cwd, policy=context_policy)
        self.checkpoint_path = (
            Path(checkpoint_path).expanduser() if checkpoint_path is not None else None
        )
        self._agent_event_cursor = 0
        self.globals: dict[str, Any] = {
            "__name__": "__rlm__",
            "__builtins__": __builtins__,
            "workspace": self.workspace,
            "shell": self.shell,
            "rlm": self.rlm,
            "llm_query": self.subcalls.query,
            "llm_query_batched": self.subcalls.query_batch,
            "context": self.context,
        }
        self._lock = threading.Lock()
        self._restored_names = self._restore_checkpoint()

    @property
    def restored_names(self) -> tuple[str, ...]:
        return self._restored_names

    def checkpoint(self) -> dict[str, Any]:
        """Persist every independently serializable user variable."""
        path = self.checkpoint_path
        if path is None:
            return {"saved": [], "skipped": [], "path": None}
        saved: dict[str, bytes] = {}
        skipped: list[str] = []
        size = 0
        for name, value in self.globals.items():
            if name in _RESERVED_NAMES or name.startswith("__"):
                continue
            try:
                serialized = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
                if size + len(serialized) > self.sandbox.max_checkpoint_bytes:
                    skipped.append(name)
                    continue
                saved[name] = serialized
                size += len(serialized)
            except Exception:  # noqa: BLE001 - isolate each value
                skipped.append(name)
        payload = pickle.dumps({"version": 1, "variables": saved}, protocol=pickle.HIGHEST_PROTOCOL)
        if len(payload) > self.sandbox.max_checkpoint_bytes:
            return {
                "saved": [],
                "skipped": sorted(saved) + sorted(skipped),
                "path": str(path),
                "error": f"checkpoint exceeds {self.sandbox.max_checkpoint_bytes} bytes",
            }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)
        except OSError as error:
            return {
                "saved": [],
                "skipped": sorted(saved) + sorted(skipped),
                "path": str(path),
                "error": str(error),
            }
        return {"saved": sorted(saved), "skipped": sorted(skipped), "path": str(path)}

    def drain_agent_events(self) -> list[dict[str, Any]]:
        supervisor = self.rlm._supervisor
        if supervisor is None:
            return []
        events, cursor = supervisor.events_since(self._agent_event_cursor)
        self._agent_event_cursor = cursor
        return events

    async def execute(self, code: str) -> PythonExecutionResult:
        return await asyncio.to_thread(self._execute_sync, code)

    def _execute_sync(self, code: str) -> PythonExecutionResult:
        with self._lock:
            stream_limit = max(1, self.sandbox.max_output_chars // 2)
            stdout = _BoundedTextBuffer(stream_limit)
            stderr = _BoundedTextBuffer(stream_limit)
            value: Any = None
            try:
                module = ast.parse(code, mode="exec")
                body = list(module.body)
                final = (
                    cast(ast.Expr, body.pop()) if body and isinstance(body[-1], ast.Expr) else None
                )
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    if body:
                        prefix = ast.Module(body=body, type_ignores=[])
                        exec(compile(prefix, "<rlm-python>", "exec"), self.globals, self.globals)
                    if final is not None:
                        expression = ast.Expression(final.value)
                        value = eval(
                            compile(expression, "<rlm-python>", "eval"),
                            self.globals,
                            self.globals,
                        )
            except BaseException:  # noqa: BLE001 - traceback is returned to the model
                combined = stdout.getvalue() + stderr.getvalue()
                self.checkpoint()
                return PythonExecutionResult(
                    combined,
                    "",
                    traceback.format_exc()[: self.sandbox.max_output_chars],
                )
            self.checkpoint()
            return PythonExecutionResult(
                stdout.getvalue() + stderr.getvalue(),
                "" if value is None else repr(value)[: self.sandbox.max_output_chars],
            )

    def _restore_checkpoint(self) -> tuple[str, ...]:
        path = self.checkpoint_path
        if path is None or not path.is_file():
            return ()
        if path.stat().st_size > self.sandbox.max_checkpoint_bytes:
            return ()
        try:
            payload = pickle.loads(path.read_bytes())  # noqa: S301 - trusted RLM state directory
        except Exception:  # noqa: BLE001 - a bad checkpoint cannot break session resume
            return ()
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return ()
        variables = payload.get("variables")
        if not isinstance(variables, dict):
            return ()
        restored: list[str] = []
        for raw_name, serialized in variables.items():
            name = str(raw_name)
            if (
                name in _RESERVED_NAMES
                or name.startswith("__")
                or not isinstance(serialized, bytes)
            ):
                continue
            try:
                self.globals[name] = pickle.loads(  # noqa: S301 - trusted RLM state directory
                    serialized
                )
            except Exception:  # noqa: BLE001 - restore independent values when possible
                continue
            restored.append(name)
        return tuple(sorted(restored))


_KERNELS: dict[str, PersistentPythonKernel] = {}
_KERNELS_LOCK = threading.Lock()


def kernel_for(
    session_key: str,
    cwd: str | Path,
    *,
    supervisor: Any | None = None,
    agent_id: str = "root",
    checkpoint_path: str | Path | None = None,
    sandbox: RLMSandboxConfig | None = None,
    context_policy: ContextPolicy | None = None,
) -> PersistentPythonKernel:
    """Return the process-local persistent kernel for a session."""
    with _KERNELS_LOCK:
        kernel = _KERNELS.get(session_key)
        if kernel is None:
            kernel = PersistentPythonKernel(
                cwd,
                supervisor=supervisor,
                agent_id=agent_id,
                checkpoint_path=checkpoint_path,
                sandbox=sandbox,
                context_policy=context_policy,
            )
            _KERNELS[session_key] = kernel
        elif supervisor is not None:
            kernel.rlm.bind(supervisor, agent_id=agent_id)
        return kernel


def create_python_tool(kernel: PersistentPythonKernel) -> AgentTool:
    observation = PythonExecutionResult.observation

    async def execute(tool_call_id, args, signal=None, on_update=None) -> AgentToolResult:
        del tool_call_id, signal, on_update
        code = str(args.get("code") or "")
        if not code.strip():
            raise ValueError("Python code cannot be empty")
        result = await kernel.execute(code)
        agent_events = kernel.drain_agent_events()
        observed, truncated = observation(result)
        if result.error:
            raise RuntimeError(observed)
        return AgentToolResult(
            content=[TextContent(text=observed)],
            details={
                "runtime": "python",
                "persistent": True,
                "cwd": str(kernel.cwd),
                "agent_events": agent_events,
                "observation_chars": len(result.text),
                "observation_truncated": truncated,
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


_RESERVED_NAMES = frozenset(
    {"workspace", "shell", "rlm", "llm_query", "llm_query_batched", "context"}
)


__all__ = [
    "PersistentPythonKernel",
    "PythonExecutionResult",
    "RLMNamespace",
    "Shell",
    "ShellResult",
    "Workspace",
    "create_python_tool",
    "kernel_for",
]
