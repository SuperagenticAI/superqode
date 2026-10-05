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
import json
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
class History:
    def search(self, query="", limit=20):
        return _rlm_host("history.search", {"query": query, "limit": limit})
    def read(self, identity, start=0, size=4000):
        return _rlm_host("history.read", {"id": identity, "start": start, "size": size})
    def stats(self):
        return _rlm_host("history.stats", {})

history = History()

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


def llm_query(prompt, context="", model=None):
    return RLMResponse(_rlm_query(prompt, context, model))


def llm_query_batched(prompts, contexts=None, model=None):
    return [RLMResponse(item) for item in _rlm_query_batch(list(prompts), contexts, model)]


context = Context()
workspace = Workspace()
shell = Shell()
"""


BRIDGE_PREAMBLE = """
class RemoteTask:
    def __init__(self, identifier):
        self.id = identifier

    def status(self):
        return _rlm_host("a2a.status", {"id": self.id})

    def poll(self):
        return _rlm_host("a2a.poll", {"id": self.id})

    def wait(self, timeout=20):
        return _rlm_host("a2a.wait", {"id": self.id, "timeout": timeout})

    def reply(self, message):
        return _rlm_host("a2a.reply", {"id": self.id, "message": message})

    def cancel(self):
        return _rlm_host("a2a.cancel", {"id": self.id})

    def follow_up(self, task, request_id=None):
        return RemoteTask(_rlm_host("a2a.follow_up", {"id": self.id, "task": task, "request_id": request_id})["id"])

    def read(self, artifact=None, start=0, size=4000):
        return _rlm_host("a2a.read", {"id": self.id, "artifact": artifact, "start": start, "size": size})

    def summary(self, max_chars=1200):
        return self.read(size=min(max_chars, 20000))

    def __repr__(self):
        return "A2ATask(id=" + repr(self.id) + ")"

class RemoteAgents:
    def peers(self):
        return _rlm_host("a2a.peers", {})

    def tasks(self):
        return _rlm_host("a2a.tasks", {})

    def handle(self, identifier):
        _rlm_host("a2a.status", {"id": identifier})
        return RemoteTask(identifier)

    def start(self, peer, task, context="", required=True, deadline_seconds=None, request_id=None):
        value = _rlm_host("a2a.start", {"peer": peer, "task": task, "context": context,
            "required": required, "deadline_seconds": deadline_seconds, "request_id": request_id})
        return RemoteTask(value["id"])

class LocalAgent:
    def __init__(self, identifier):
        self.id = identifier

    def status(self):
        return _rlm_host("rlm.status", {"agent": self.id})

    def wait(self, timeout=None):
        return _rlm_host("rlm.wait", {"agent": self.id, "timeout": timeout})

    def send(self, message):
        return _rlm_host("rlm.send", {"agent": self.id, "message": message})

    def steer(self, instruction):
        return _rlm_host("rlm.steer", {"agent": self.id, "instruction": instruction})

    def cancel(self):
        return _rlm_host("rlm.cancel", {"agent": self.id})

    def __repr__(self):
        return "AgentHandle(id=" + repr(self.id) + ")"

class LocalAgents:
    def run(self, prompt, model=None):
        return LocalAgent(_rlm_host("rlm.run", {"prompt": prompt, "model": model})["id"])

    def run_batch(self, prompts, model=None):
        return [LocalAgent(v["id"]) for v in _rlm_host("rlm.run_batch", {"prompts": prompts, "model": model})]

    def agents(self, all_agents=False):
        return _rlm_host("rlm.agents", {"all_agents": all_agents})

    def message(self, agent, message, delivery_id=None):
        identifier = agent if isinstance(agent, str) else agent.id
        return _rlm_host("rlm.message", {"agent": identifier, "message": message, "delivery_id": delivery_id})

    def inbox(self, limit=50):
        return _rlm_host("rlm.inbox", {"limit": limit})

    def ack_inbox(self, identity):
        return _rlm_host("rlm.ack_inbox", {"id": identity})

    def parent_id(self):
        return _rlm_host("rlm.parent_id", {})

    def follow_up(self, agent, prompt):
        identifier = agent if isinstance(agent, str) else agent.id
        return LocalAgent(_rlm_host("rlm.follow_up", {"agent": identifier, "prompt": prompt})["id"])

    def wait_all(self, handles):
        return _rlm_host("rlm.wait_all", {"agents": [h.id for h in handles]})

a2a = RemoteAgents()
rlm = LocalAgents()
"""


class MontyUnavailableError(RuntimeError):
    """Monty was selected but the optional dependency is not installed."""


def load_monty() -> Any:
    try:
        return importlib.import_module("pydantic_monty")
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise MontyUnavailableError(
            "The monty RLM sandbox needs the optional 'pydantic-monty' dependency. "
            # The documented install path is `uv tool install superqode`, and
            # `uv pip install` does not reach a uv tool environment.
            "Install it with: uv tool install --force 'superqode[monty]' "
            "(or `uv pip install 'superqode[monty]'` in a virtualenv)."
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
        host_call: Any | None = None,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.config = config
        self.session_id = session_id
        self.state_dir = Path(state_dir).expanduser()
        self.executor = executor
        self.context = context
        self.loop = loop
        self.host_call = host_call
        self._checkouts: dict[str, Any] = {}
        self._revocations: dict[str, threading.Event] = {}
        self._thread_state = threading.local()
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
            pool = stack.enter_context(
                module.Monty(
                    max_processes=self.config.monty_max_workers,
                    checkout_timeout=5.0,
                    request_timeout=self.config.python_timeout + 5,
                )
            )
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
            result = await asyncio.wait_for(
                asyncio.to_thread(self._feed, session, code),
                timeout=self.config.python_timeout,
            )
            if not result.error:
                checkpoint = await self.checkpoint(kernel_id)
                if not checkpoint.ok:
                    return PythonExecutionResult(
                        result.output,
                        result.value_repr,
                        "Monty state was not committed: " + checkpoint.error,
                    )
            return result
        except TimeoutError:
            self._revocations[kernel_id].set()
            # A timed-out Monty session is never reused. Monty's restricted VM
            # has no host access, and a replacement session restores only its
            # last completed snapshot.
            await self.close_kernel(kernel_id)
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
        if len(payload) > self.config.max_checkpoint_bytes:
            return CheckpointReference(error="Monty checkpoint exceeds the configured size limit")
        target = self.state_dir / f"{kernel_id}.monty"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(payload)
            temporary.chmod(0o600)
            temporary.replace(target)
            from superqode.tools.monty_program import runtime_identity

            runtime, _ = runtime_identity(load_monty())
            manifest = target.with_suffix(".runtime.json")
            temporary_manifest = manifest.with_suffix(".tmp")
            temporary_manifest.write_text(
                json.dumps({"runtime": runtime, "limits": self._limits()}), encoding="utf-8"
            )
            temporary_manifest.chmod(0o600)
            temporary_manifest.replace(manifest)
            reference_path = target.with_suffix(".reference.json")
            temporary_reference = reference_path.with_suffix(".tmp")
            temporary_reference.write_text(
                json.dumps({"digest": hashlib.sha256(payload).hexdigest(), "size": len(payload)}),
                encoding="utf-8",
            )
            temporary_reference.chmod(0o600)
            temporary_reference.replace(reference_path)
        except OSError as error:
            return CheckpointReference(error=str(error))
        return CheckpointReference(
            path=str(target),
            digest=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
            # An idle Monty session dump, not a pickle. The host stores the
            # bytes and never interprets them; only Monty loads them back.
            inside_boundary=True,
        )

    async def restore(self, kernel_id: str, reference: CheckpointReference) -> tuple[str, ...]:
        path = Path(reference.path or (self.state_dir / f"{kernel_id}.monty"))
        if not reference.inside_boundary or path.is_symlink():
            raise PermissionError("Monty restore requires a trusted host checkpoint reference")
        if not path.is_file():
            return ()
        if path.stat().st_size > self.config.max_checkpoint_bytes:
            raise ValueError("Monty checkpoint exceeds the configured size limit")
        payload = path.read_bytes()
        import hashlib

        if not reference.digest or hashlib.sha256(payload).hexdigest() != reference.digest:
            raise ValueError("Monty checkpoint integrity check failed")
        module = load_monty()
        from superqode.tools.monty_program import runtime_identity

        runtime, _ = await asyncio.to_thread(runtime_identity, module)
        manifest = json.loads(path.with_suffix(".runtime.json").read_text(encoding="utf-8"))
        if manifest.get("runtime") != runtime:
            raise ValueError("Monty worker identity changed; checkpoint migration is required")
        if manifest.get("limits") != self._limits():
            raise ValueError("Monty checkpoint resource policy changed; start a new kernel")
        await self.start()

        def load() -> Any:
            return self._checkout(kernel_id)

        del module
        session = await asyncio.to_thread(load)
        # ``session.dump()`` between feeds produces an *idle* dump. Monty v1
        # restores those with ``load_session``; ``load_snapshot`` is only for
        # mid-feed suspended snapshots and raises on idle dumps.
        try:
            await asyncio.to_thread(session.load_session, payload)
        except Exception as error:  # noqa: BLE001 - surface Monty dump/version errors clearly
            await self.close_kernel(kernel_id)
            message = str(error)
            lower = message.lower()
            if (
                "load_session" in lower
                or "load_snapshot" in lower
                or "version" in lower
                or "too old" in lower
                or "dump" in lower
            ):
                raise RuntimeError(
                    "Failed to restore Monty checkpoint: "
                    f"{type(error).__name__}: {message}. "
                    "Idle dumps from session.dump() must be restored with "
                    "load_session, and dump format is Monty-version-specific "
                    "(v1 dumps are not loadable on older workers)."
                ) from error
            raise
        rebound = await asyncio.to_thread(self._feed, session, PREAMBLE + BRIDGE_PREAMBLE)
        if rebound.error:
            await self.close_kernel(kernel_id)
            raise RuntimeError(rebound.error)
        with self._lock:
            self._sessions[kernel_id] = session
        return ("<monty session>",)

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
            event = self._revocations.get(kernel_id)
            if event is not None:
                event.set()
            checkout = self._checkouts.pop(kernel_id, None)
        if checkout is not None:
            await asyncio.to_thread(checkout.__exit__, None, None, None)

    async def close(self) -> None:
        for kernel_id in list(self._checkouts):
            await self.close_kernel(kernel_id)
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
        target = self.state_dir / f"{kernel_id}.monty"
        reference_path = target.with_suffix(".reference.json")
        if target.is_file():
            if not reference_path.is_file():
                raise ValueError("Monty checkpoint has no trusted host reference")
            if reference_path.stat().st_size > 4096:
                raise ValueError("Invalid Monty checkpoint reference")
            reference = json.loads(reference_path.read_text(encoding="utf-8"))
            await self.restore(
                kernel_id,
                CheckpointReference(
                    path=str(target),
                    digest=reference["digest"],
                    size=reference["size"],
                    inside_boundary=True,
                ),
            )
            return self._sessions[kernel_id]

        def checkout() -> Any:
            return self._checkout(kernel_id)

        session = await asyncio.to_thread(checkout)
        await asyncio.to_thread(self._feed, session, PREAMBLE + BRIDGE_PREAMBLE)
        with self._lock:
            self._sessions[kernel_id] = session
        return session

    def _feed(self, session: Any, code: str) -> PythonExecutionResult:
        """Run one snippet. Called in a worker thread, never on the loop."""
        from .kernel import _BoundedTextBuffer

        self._thread_state.revoked = next(
            (self._revocations[k] for k, v in self._sessions.items() if v is session),
            threading.Event(),
        )
        printed = _BoundedTextBuffer(self.config.max_output_chars)
        try:
            value = session.feed_run(
                code,
                external_lookup=self._externals(),
                print_callback=lambda _stream, text: printed.write(text),
            )
        except Exception as error:  # noqa: BLE001 - the failure is returned to the model
            return PythonExecutionResult(printed.getvalue(), "", f"{type(error).__name__}: {error}")
        return PythonExecutionResult(
            printed.getvalue(), "" if value is None else repr(value)[: self.config.max_output_chars]
        )

    def _externals(self) -> dict[str, Any]:
        """Host functions Monty can call, named so a shim cannot shadow them."""
        return {
            "_rlm_host": self._host,
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
            "_rlm_ctx_select": lambda paths, patterns: (
                self._view(paths).select(*[str(item) for item in patterns]).files()
            ),
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

    def _limits(self):
        return {
            "max_memory": self.config.monty_memory_bytes,
            "max_feed_duration_secs": self.config.python_timeout,
            "max_turn_duration_secs": self.config.python_timeout,
            "max_total_sleep_secs": self.config.python_timeout,
            "max_recursion_depth": self.config.monty_recursion_depth,
            "max_suspensions": self.config.monty_suspensions,
        }

    def _checkout(self, kernel_id):
        checkout = self._pool.checkout(script_name=f"{kernel_id}.py", limits=self._limits())
        session = checkout.__enter__()
        self._checkouts[kernel_id] = checkout
        self._revocations[kernel_id] = threading.Event()
        return session

    def _host(self, name, payload):
        if self.host_call is None:
            raise RuntimeError("The host capability is not configured")
        return self._await(self.host_call(str(name), dict(payload)))

    def _view(self, paths: Any) -> Any:
        from .context import RLMContext

        base = self.context or RLMContext(self.cwd)
        if not paths:
            return base
        return RLMContext(base.root, policy=base.policy, paths=[str(item) for item in paths])

    def _query(self, prompt: str, context: str = "", model=None) -> dict[str, Any]:
        response = self._await(
            self._require_executor().query(str(prompt), context=str(context), model=model)
        )
        return _response_dict(response)

    def _query_batch(self, prompts: Any, contexts: Any = None, model=None) -> list[dict[str, Any]]:
        responses = self._await(
            self._require_executor().query_batch(
                [str(item) for item in prompts],
                contexts=[str(item) for item in contexts] if contexts else None,
                model=model,
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
        revoked = getattr(self._thread_state, "revoked", threading.Event())
        if revoked.is_set():
            coroutine.close()
            raise RuntimeError("Monty execution was revoked")

        async def guarded():
            from .capabilities import admission_guard, check_admission

            token = admission_guard.set(lambda: not revoked.is_set())
            try:
                check_admission()
                return await coroutine
            finally:
                admission_guard.reset(token)

        future = asyncio.run_coroutine_threadsafe(guarded(), loop)
        try:
            return future.result(timeout=self.config.python_timeout)
        except BaseException:
            future.cancel()
            raise


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
