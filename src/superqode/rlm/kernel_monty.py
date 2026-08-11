"""A persistent Python kernel that runs inside Monty: the research profile.

Monty is a from-scratch Python interpreter with no subprocess, no real
filesystem and no third-party imports. That makes it the wrong place to do
coding work and the right place to do the other half of the RLM pattern:
holding a corpus as data, chunking it, and asking bounded questions about it.

So this profile deliberately offers less than the others. Reads, search and
`llm_query` work; `shell` and repository writes refuse with a message naming the
profile. An agent that cannot run tests cannot pretend to have verified
anything, which is the honest shape for evaluation and for untrusted prompts.

Two implementation choices are worth stating.

**Sync pool driven in a worker thread.** Monty's async sessions require model
code to write ``await llm_query(...)``, which would make the namespace differ by
profile. Instead the sync pool runs in a thread and the injected externals are
sync callables that bridge back to the host loop, so the same Python works
everywhere.

**Externals are injected under private names.** A name defined inside Monty
shadows an external of the same name, so the host functions arrive as
``_rlm_*`` and a small preamble builds the friendly namespace on top of them.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import threading
from pathlib import Path
from typing import Any, Sequence

from .identity import KernelIdentity, SandboxIdentity
from .kernel import PythonExecutionResult, ShellResult
from .kernel_backend import CheckpointReference, KernelHealth
from .sandbox import RLMSandboxConfig

MONTY_BACKEND = "monty"

#: Built inside Monty on top of the injected ``_rlm_*`` externals, so the
#: namespace matches the other profiles rather than exposing bare functions.
PREAMBLE = """
class RLMResponse:
    def __init__(self, data):
        self.id = data["id"]
        self.text = data["text"]
        self.model = data["model"]
        self.truncated = data["truncated"]
        self.error = data["error"]
        self.usage = data["usage"]

    def ok(self):
        return not self.error

    def size(self):
        return len(self.text)

    def __len__(self):
        return len(self.text)

    def __str__(self):
        return self.text

    def __repr__(self):
        if self.error:
            return "RLMResponse(id=" + repr(self.id) + ", error=" + repr(self.error) + ")"
        preview = self.text[:80].replace("\\n", " ")
        return "RLMResponse(id=" + repr(self.id) + ", chars=" + str(len(self.text)) + ", preview=" + repr(preview) + ")"

    def lines(self):
        return self.text.splitlines()

    def chunk(self, start=0, size=4000):
        return self.text[start:start + size]


class ContextChunk:
    def __init__(self, data):
        self.text = data["text"]
        self.path = data["path"]
        self.index = data["index"]
        self.start = data["start"]
        self.end = data["end"]

    def size(self):
        return len(self.text)

    def __len__(self):
        return len(self.text)

    def __str__(self):
        return self.text

    def __repr__(self):
        preview = self.text[:60].replace("\\n", " ")
        return "ContextChunk(path=" + repr(self.path) + ", index=" + str(self.index) + ", chars=" + str(len(self.text)) + ", preview=" + repr(preview) + ")"

    def labelled(self):
        return "# " + self.path + " (chars " + str(self.start) + "-" + str(self.end) + ")\\n" + self.text


class Context:
    def __init__(self, paths=None):
        self.paths = paths

    def files(self):
        return _rlm_ctx_files(self.paths)

    def size(self):
        return _rlm_ctx_len(self.paths)

    def __len__(self):
        return _rlm_ctx_len(self.paths)

    def __repr__(self):
        stats = self.stats()
        return "RLMContext(profile=" + repr(stats["profile"]) + ", files=" + str(stats["files"]) + ", bytes=" + str(stats["bytes"]) + ")"

    def stats(self):
        return _rlm_ctx_stats(self.paths)

    def read(self, path):
        return _rlm_ctx_read(self.paths, path)

    def text(self):
        return _rlm_ctx_text(self.paths)

    def search(self, pattern, limit=200):
        return _rlm_ctx_search(self.paths, pattern, limit)

    def select(self, *patterns):
        return Context(_rlm_ctx_select(self.paths, list(patterns)))

    def chunk(self, size=20000, overlap=0):
        return [ContextChunk(item) for item in _rlm_ctx_chunk(self.paths, size, overlap)]


class Workspace:
    def read(self, path):
        return _rlm_ctx_read(None, path)

    def search(self, pattern, path="."):
        return _rlm_ctx_search(None, pattern, 200)

    def glob(self, pattern):
        return _rlm_ctx_select(None, [pattern])

    def write(self, path, content):
        raise RuntimeError("This RLM profile is read-only: workspace.write is unavailable under the monty sandbox, which has no filesystem. Use the host or docker profile to change files.")

    def edit(self, path, old, new, replace_all=False):
        raise RuntimeError("This RLM profile is read-only: workspace.edit is unavailable under the monty sandbox, which has no filesystem. Use the host or docker profile to change files.")


class Shell:
    def run(self, command, timeout=120, env=None):
        raise RuntimeError("This RLM profile cannot run commands: the monty sandbox has no subprocess. Use the host or docker profile to run tests.")


def llm_query(prompt, context=""):
    return RLMResponse(_rlm_query(prompt, context))


def llm_query_batched(prompts, contexts=None):
    return [RLMResponse(item) for item in _rlm_query_batch(list(prompts), contexts)]


context = Context()
workspace = Workspace()
shell = Shell()
"""


class MontyUnavailableError(RuntimeError):
    """Monty was selected but the optional dependency is not installed."""


def load_monty() -> Any:
    try:
        return importlib.import_module("pydantic_monty")
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise MontyUnavailableError(
            "The monty RLM sandbox needs the optional 'pydantic-monty' dependency. "
            "Install it with: uv pip install 'superqode[monty]'"
        ) from error


class MontyKernelBackend:
    """Model-written Python runs in Monty, with no host access at all."""

    def __init__(
        self,
        cwd: str | Path,
        *,
        config: RLMSandboxConfig,
        session_id: str,
        state_dir: str | Path,
        executor: Any | None = None,
        context: Any | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.config = config
        self.session_id = session_id
        self.state_dir = Path(state_dir).expanduser()
        self.executor = executor
        self.context = context
        self.loop = loop
        self._identity = SandboxIdentity(backend=MONTY_BACKEND, session_id=session_id)
        self._pool: Any = None
        self._stack: contextlib.ExitStack | None = None
        self._sessions: dict[str, Any] = {}
        self._lock = threading.Lock()

    @property
    def identity(self) -> SandboxIdentity:
        return self._identity

    async def start(self) -> SandboxIdentity:
        if self._pool is not None:
            return self._identity
        module = load_monty()
        if self.loop is None:
            self.loop = asyncio.get_running_loop()

        def open_pool() -> tuple[Any, contextlib.ExitStack]:
            stack = contextlib.ExitStack()
            pool = stack.enter_context(module.Monty())
            return pool, stack

        self._pool, self._stack = await asyncio.to_thread(open_pool)
        self._identity = SandboxIdentity(
            backend=MONTY_BACKEND, sandbox_id=f"monty-{self.session_id}", session_id=self.session_id
        )
        return self._identity

    async def create_kernel(self, kernel_id: str) -> KernelIdentity:
        await self._session(kernel_id)
        return KernelIdentity(kernel_id=kernel_id, sandbox_id=self._identity.sandbox_id)

    async def execute(self, kernel_id: str, code: str) -> PythonExecutionResult:
        session = await self._session(kernel_id)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._feed, session, code),
                timeout=self.config.python_timeout,
            )
        except TimeoutError:
            # A timed-out Monty session is never reused. Monty's restricted VM
            # has no host access, and a replacement session restores only its
            # last completed snapshot.
            with self._lock:
                self._sessions.pop(kernel_id, None)
            return PythonExecutionResult(
                "",
                "",
                f"Python execution timed out after {self.config.python_timeout:g}s; "
                "the Monty session was discarded",
            )

    async def shell(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> ShellResult:
        """Refuse rather than run somewhere the profile does not claim to reach."""
        del timeout, env
        display = command if isinstance(command, str) else " ".join(map(str, command))
        return ShellResult(
            display,
            127,
            "",
            "The monty RLM profile has no subprocess, so commands and completion "
            "gates cannot run. Use the host or docker profile to verify work.",
        )

    async def checkpoint(self, kernel_id: str) -> CheckpointReference:
        session = self._sessions.get(kernel_id)
        if session is None:
            return CheckpointReference(error="No Monty kernel to checkpoint")
        import hashlib

        payload = await asyncio.to_thread(session.dump)
        target = self.state_dir / f"{kernel_id}.monty"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        except OSError as error:
            return CheckpointReference(error=str(error))
        return CheckpointReference(
            path=str(target),
            digest=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
            # A Monty snapshot, not a pickle. The host stores the bytes and
            # never interprets them; only Monty loads them back.
            inside_boundary=True,
        )

    async def restore(self, kernel_id: str, reference: CheckpointReference) -> tuple[str, ...]:
        path = Path(reference.path or (self.state_dir / f"{kernel_id}.monty"))
        if not path.is_file():
            return ()
        payload = path.read_bytes()
        module = load_monty()
        await self.start()

        def load() -> Any:
            stack = self._stack
            assert stack is not None
            return stack.enter_context(self._pool.checkout(script_name=f"{kernel_id}.py"))

        del module
        session = await asyncio.to_thread(load)
        await asyncio.to_thread(session.load_snapshot, payload)
        with self._lock:
            self._sessions[kernel_id] = session
        return ("<monty snapshot>",)

    async def health(self) -> KernelHealth:
        return KernelHealth(
            alive=self._pool is not None,
            backend=MONTY_BACKEND,
            detail="research profile: no shell, no writes",
            kernels=tuple(sorted(self._sessions)),
        )

    async def close_kernel(self, kernel_id: str) -> None:
        with self._lock:
            self._sessions.pop(kernel_id, None)

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self._pool = None
        with self._lock:
            self._sessions.clear()
        if stack is not None:
            await asyncio.to_thread(stack.close)

    async def _session(self, kernel_id: str) -> Any:
        existing = self._sessions.get(kernel_id)
        if existing is not None:
            return existing
        await self.start()

        def checkout() -> Any:
            stack = self._stack
            assert stack is not None
            return stack.enter_context(self._pool.checkout(script_name=f"{kernel_id}.py"))

        session = await asyncio.to_thread(checkout)
        await asyncio.to_thread(self._feed, session, PREAMBLE)
        with self._lock:
            self._sessions[kernel_id] = session
        return session

    def _feed(self, session: Any, code: str) -> PythonExecutionResult:
        """Run one snippet. Called in a worker thread, never on the loop."""
        printed: list[str] = []
        try:
            value = session.feed_run(
                code,
                external_lookup=self._externals(),
                print_callback=lambda _stream, text: printed.append(text),
            )
        except Exception as error:  # noqa: BLE001 - the failure is returned to the model
            return PythonExecutionResult("".join(printed), "", f"{type(error).__name__}: {error}")
        return PythonExecutionResult("".join(printed), "" if value is None else repr(value))

    def _externals(self) -> dict[str, Any]:
        """Host functions Monty can call, named so a shim cannot shadow them."""
        return {
            "_rlm_query": self._query,
            "_rlm_query_batch": self._query_batch,
            "_rlm_ctx_files": lambda paths: self._view(paths).files(),
            "_rlm_ctx_len": lambda paths: len(self._view(paths)),
            "_rlm_ctx_stats": lambda paths: self._view(paths).stats(),
            "_rlm_ctx_text": lambda paths: self._view(paths).text(),
            "_rlm_ctx_read": lambda paths, path: self._view(paths).read(path),
            "_rlm_ctx_search": lambda paths, pattern, limit: self._view(paths).search(
                pattern, limit=int(limit)
            ),
            "_rlm_ctx_select": lambda paths, patterns: self._view(paths)
            .select(*[str(item) for item in patterns])
            .files(),
            "_rlm_ctx_chunk": lambda paths, size, overlap: [
                {
                    "text": chunk.text,
                    "path": chunk.path,
                    "index": chunk.index,
                    "start": chunk.start,
                    "end": chunk.end,
                }
                for chunk in self._view(paths).chunk(int(size), overlap=int(overlap))
            ],
        }

    def _view(self, paths: Any) -> Any:
        from .context import RLMContext

        base = self.context or RLMContext(self.cwd)
        if not paths:
            return base
        return RLMContext(base.root, policy=base.policy, paths=[str(item) for item in paths])

    def _query(self, prompt: str, context: str = "") -> dict[str, Any]:
        response = self._await(self._require_executor().query(str(prompt), context=str(context)))
        return _response_dict(response)

    def _query_batch(self, prompts: Any, contexts: Any = None) -> list[dict[str, Any]]:
        responses = self._await(
            self._require_executor().query_batch(
                [str(item) for item in prompts],
                contexts=[str(item) for item in contexts] if contexts else None,
            )
        )
        return [_response_dict(item) for item in responses]

    def _require_executor(self) -> Any:
        if self.executor is None:
            raise RuntimeError("Semantic subcalls are not configured for this kernel")
        return self.executor

    def _await(self, coroutine: Any) -> Any:
        """Bridge a host coroutine from the Monty worker thread."""
        loop = self.loop
        if loop is None:
            coroutine.close()
            raise RuntimeError("The Monty kernel is not attached to an event loop")
        return asyncio.run_coroutine_threadsafe(coroutine, loop).result()


def _response_dict(response: Any) -> dict[str, Any]:
    return {
        "id": response.id,
        "text": response.text,
        "model": response.model,
        "truncated": response.truncated,
        "error": response.error,
        "usage": dict(response.usage),
    }


__all__ = [
    "MONTY_BACKEND",
    "PREAMBLE",
    "MontyKernelBackend",
    "MontyUnavailableError",
    "load_monty",
]
