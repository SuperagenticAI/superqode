"""The persistent Python kernel that runs *inside* an RLM sandbox.

This file is copied into the boundary and started there, so it must import only
the standard library: the sandbox has no SuperQode installation and must not
need one. It speaks newline-delimited JSON over stdin and stdout.

The channel is bidirectional. Operations that need the host, such as starting a
child agent, cannot run in here: the supervisor and the provider credentials
stay outside the boundary on purpose. So the namespace's ``rlm`` object writes a
``call`` message to the host and blocks for its answer, which is also the
channel a semantic subcall will use later.

Framing is protected from the code it runs. Model-written Python may print, and
a subprocess may inherit file descriptors, so the real stdout is duplicated for
protocol use at startup and descriptor 1 is pointed at stderr. Stray output then
lands in the container log instead of corrupting the message stream.
"""

from __future__ import annotations

import ast
import atexit
import contextlib
import hashlib
import io
import json
import os
import pickle
import re
import shlex
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Sequence, cast

PROTOCOL_VERSION = 1
RESERVED_NAMES = frozenset({"workspace", "shell", "rlm"})
_COMPOUND_PATTERN = re.compile(r"[;&|]|\$\(|`|\n")


class SandboxPolicyError(RuntimeError):
    """A convenience namespace call violated the declared Docker policy."""


def _policy_flag(policy: dict[str, Any], name: str, default: bool = True) -> bool:
    return bool(policy[name]) if name in policy else default


class BoundedTextBuffer(io.TextIOBase):
    """Capture model output without allowing an unbounded protocol frame."""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, int(limit))
        self._parts: list[str] = []
        self._size = 0
        self._omitted = 0

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        text = str(value)
        available = max(0, self.limit - self._size)
        if available:
            kept = text[:available]
            self._parts.append(kept)
            self._size += len(kept)
        self._omitted += max(0, len(text) - available)
        return len(text)

    def getvalue(self) -> str:
        text = "".join(self._parts)
        if self._omitted:
            text += f"\n... [{self._omitted:,} output characters omitted by kernel limit] ...\n"
        return text


class ProtocolChannel:
    """Newline-delimited JSON over descriptors the executed code cannot reach."""

    def __init__(self) -> None:
        self._out = os.fdopen(os.dup(1), "w", encoding="utf-8")
        self._in = os.fdopen(os.dup(0), "r", encoding="utf-8")
        # Anything the executed code writes to the real stdout goes to stderr,
        # which the host collects as a log rather than as protocol traffic.
        os.dup2(2, 1)
        # Detach stdin so executed code cannot consume the command stream.
        null = os.open(os.devnull, os.O_RDONLY)
        os.dup2(null, 0)
        os.close(null)

    def send(self, message: dict[str, Any]) -> None:
        self._out.write(json.dumps(message) + "\n")
        self._out.flush()

    def receive(self) -> dict[str, Any] | None:
        line = self._in.readline()
        if not line:
            return None
        try:
            value = json.loads(line)
        except ValueError:
            return {"op": "invalid"}
        return value if isinstance(value, dict) else {"op": "invalid"}


class ShellResult:
    """Mirrors the host namespace's result object."""

    __slots__ = ("command", "returncode", "stdout", "stderr")

    def __init__(self, command: str, returncode: int, stdout: str, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

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
    """Repository access inside the boundary.

    The container is the enforcement here. The mount decides what is writable
    and the network mode decides what is reachable, so this object provides the
    same calls as the host namespace without repeating checks that a sandboxed
    interpreter no longer depends on.
    """

    def __init__(self, root: str | Path, policy: dict[str, Any] | None = None) -> None:
        self.root = Path(root).resolve()
        self.policy = policy or {}

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
        if not _policy_flag(self.policy, "allow_read"):
            raise SandboxPolicyError("Reading is disabled by the RLM sandbox policy")
        lines = self._path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, offset - 1)
        return "\n".join(lines[start : start + limit if limit else None])

    def write(self, path: str | Path, content: str) -> str:
        if not _policy_flag(self.policy, "allow_write"):
            raise SandboxPolicyError("Writing is disabled by the RLM sandbox policy")
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target.relative_to(self.root))

    def edit(self, path: str | Path, old: str, new: str, *, replace_all: bool = False) -> str:
        if not _policy_flag(self.policy, "allow_read"):
            raise SandboxPolicyError("Reading is disabled by the RLM sandbox policy")
        if not _policy_flag(self.policy, "allow_write"):
            raise SandboxPolicyError("Writing is disabled by the RLM sandbox policy")
        target = self._path(path)
        content = target.read_text(encoding="utf-8", errors="replace")
        count = content.count(old)
        if count == 0:
            raise ValueError(f"Text not found in {path}")
        target.write_text(
            content.replace(old, new) if replace_all else content.replace(old, new, 1),
            encoding="utf-8",
        )
        return f"edited {target.relative_to(self.root)} ({count if replace_all else 1} replacement)"

    def glob(self, pattern: str) -> list[str]:
        if not _policy_flag(self.policy, "allow_read"):
            raise SandboxPolicyError("Reading is disabled by the RLM sandbox policy")
        return [str(path.relative_to(self.root)) for path in sorted(self.root.glob(pattern))]

    def search(self, pattern: str, path: str | Path = ".") -> list[str]:
        if not _policy_flag(self.policy, "allow_read"):
            raise SandboxPolicyError("Reading is disabled by the RLM sandbox policy")
        root = self._path(path)
        regex = re.compile(pattern)
        matches: list[str] = []
        for file_path in root.rglob("*") if root.is_dir() else (root,):
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
    """Commands run inside the boundary, never on the host."""

    def __init__(self, cwd: str | Path, policy: dict[str, Any] | None = None) -> None:
        self.cwd = Path(cwd).resolve()
        self.policy = policy or {}

    def run(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None = 120,
        env: dict[str, str] | None = None,
    ) -> ShellResult:
        if not _policy_flag(self.policy, "allow_shell"):
            raise SandboxPolicyError("Shell execution is disabled by the RLM sandbox policy")
        shell = isinstance(command, str)
        if shell:
            if not _policy_flag(
                self.policy, "allow_compound_commands"
            ) and _COMPOUND_PATTERN.search(command):
                raise SandboxPolicyError("Compound shell commands are disabled by the RLM policy")
            tokens = shlex.split(command)
        else:
            tokens = [str(item) for item in command]
        allowed = tuple(str(item) for item in self.policy.get("allowed_commands") or ())
        executable = os.path.basename(tokens[0]) if tokens else ""
        if allowed and executable not in allowed:
            raise SandboxPolicyError(
                f"Command {executable!r} is not in the RLM sandbox allowlist ({', '.join(allowed)})"
            )
        completed = subprocess.run(  # noqa: S603 - the container is the boundary
            command,
            cwd=self.cwd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, **(env or {})},
        )
        display = command if isinstance(command, str) else " ".join(map(str, command))
        return ShellResult(display, completed.returncode, completed.stdout, completed.stderr)


class HostCallError(RuntimeError):
    """The host refused or failed an operation requested from inside."""


class RLMProxy:
    """Recursive operations, forwarded to the supervisor on the host.

    Child agents need provider credentials and the host supervisor, neither of
    which belongs inside the boundary, so every call here is a round trip.
    """

    def __init__(self, call: Any, agent_id: str = "root") -> None:
        self._call = call
        self._agent_id = agent_id

    def run(self, prompt: str, *, model: str | None = None) -> Any:
        return self._call("rlm.run", {"prompt": prompt, "model": model})

    spawn = run

    def run_batch(self, prompts: Sequence[str], *, model: str | None = None) -> Any:
        return self._call("rlm.run_batch", {"prompts": list(prompts), "model": model})

    spawn_batch = run_batch

    def agents(self, *, all_agents: bool = False) -> Any:
        return self._call("rlm.agents", {"all_agents": all_agents})

    def wait_all(self, handles: Sequence[Any]) -> Any:
        return self._call("rlm.wait_all", {"agents": [_agent_id(item) for item in handles]})

    def send(self, agent: Any, message: str) -> Any:
        return self._call("rlm.send", {"agent": _agent_id(agent), "message": message})

    def steer(self, agent: Any, instruction: str) -> Any:
        return self._call("rlm.steer", {"agent": _agent_id(agent), "instruction": instruction})

    def cancel(self, agent: Any) -> Any:
        return self._call("rlm.cancel", {"agent": _agent_id(agent)})

    def delete(self, agent: Any) -> Any:
        return self._call("rlm.delete", {"agent": _agent_id(agent)})

    def wait(self, agent: Any) -> Any:
        return self._call("rlm.wait", {"agent": _agent_id(agent)})

    def help(self) -> str:
        return (
            "Use workspace for repository work, shell.run for commands, and rlm.run or "
            "rlm.run_batch for live child agents. Agent handles support status, send, steer, "
            "wait, cancel, and delete."
        )


class AgentProxy:
    """A child handle whose operations execute on the host."""

    def __init__(self, call: Any, agent_id: str, status: dict[str, Any] | None = None) -> None:
        self._call = call
        self.id = agent_id
        self._status = dict(status or {})

    @property
    def parent_id(self) -> str:
        return str(self.status().get("parent_id") or "")

    def status(self) -> dict[str, Any]:
        self._status = dict(self._call("rlm.status", {"agent": self.id}) or {})
        return self._status

    def send(self, message: str) -> None:
        self._call("rlm.send", {"agent": self.id, "message": message})

    def steer(self, instruction: str) -> None:
        self._call("rlm.steer", {"agent": self.id, "instruction": instruction})

    def wait(self, timeout: float | None = None) -> str:
        return str(self._call("rlm.wait", {"agent": self.id, "timeout": timeout}) or "")

    def cancel(self) -> None:
        self._call("rlm.cancel", {"agent": self.id})

    def delete(self) -> None:
        self._call("rlm.delete", {"agent": self.id})

    def __repr__(self) -> str:
        return f"AgentHandle(id={self.id!r}, status={self._status.get('status')!r})"


class ResponseProxy:
    """A subcall answer inside the sandbox, mirroring the host handle.

    The compact ``repr`` is the point: returning one of these keeps a long
    answer in the environment as data instead of copying it into the root
    conversation.
    """

    __slots__ = ("id", "text", "model", "prompt_chars", "truncated", "error", "usage")

    def __init__(self, data: dict[str, Any]) -> None:
        self.id = str(data.get("id") or "")
        self.text = str(data.get("text") or "")
        self.model = str(data.get("model") or "")
        self.prompt_chars = int(data.get("prompt_chars") or 0)
        self.truncated = bool(data.get("truncated"))
        self.error = str(data.get("error") or "")
        self.usage = dict(data.get("usage") or {})

    @property
    def ok(self) -> bool:
        return not self.error

    def size(self) -> int:
        """Portable alternative to ``len``; see the host handle."""
        return len(self.text)

    def __len__(self) -> int:
        return len(self.text)

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        if self.error:
            return f"RLMResponse(id={self.id!r}, error={self.error!r})"
        preview = self.text[:80].replace("\n", " ")
        suffix = "..." if len(self.text) > 80 else ""
        flag = ", truncated=True" if self.truncated else ""
        return (
            f"RLMResponse(id={self.id!r}, chars={len(self.text)}{flag}, "
            f"preview={preview + suffix!r})"
        )

    def lines(self) -> list[str]:
        return self.text.splitlines()

    def chunk(self, start: int = 0, size: int = 4000) -> str:
        return self.text[start : start + size]

    def search(self, pattern: str) -> list[str]:
        regex = re.compile(pattern)
        return [line for line in self.text.splitlines() if regex.search(line)]


class ChunkProxy:
    """One slice of the corpus, carrying where it came from."""

    __slots__ = ("text", "path", "index", "start", "end")

    def __init__(self, data: dict[str, Any]) -> None:
        self.text = str(data.get("text") or "")
        self.path = str(data.get("path") or "")
        self.index = int(data.get("index") or 0)
        self.start = int(data.get("start") or 0)
        self.end = int(data.get("end") or 0)

    def size(self) -> int:
        return len(self.text)

    def __len__(self) -> int:
        return len(self.text)

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        preview = self.text[:60].replace("\n", " ")
        suffix = "..." if len(self.text) > 60 else ""
        return (
            f"ContextChunk(path={self.path!r}, index={self.index}, "
            f"chars={len(self.text)}, preview={preview + suffix!r})"
        )

    def labelled(self) -> str:
        return f"# {self.path} (chars {self.start}-{self.end})\n{self.text}"


class ContextProxy:
    """The corpus, served by the host.

    The host reads the same files this container has mounted, so serving it from
    there keeps one implementation of discovery, filtering and chunking instead
    of a second copy that could drift. A narrowed view carries its own path list
    rather than a handle, so neither side has to keep it alive.
    """

    __slots__ = ("_call", "_paths")

    def __init__(self, call: Any, paths: list[str] | None = None) -> None:
        self._call = call
        self._paths = paths

    def _ask(self, operation: str, payload: dict[str, Any] | None = None) -> Any:
        body = dict(payload or {})
        body["paths"] = self._paths
        return self._call(operation, body)

    def files(self) -> Any:
        return self._ask("ctx.files")

    def size(self) -> int:
        return int(self._ask("ctx.len") or 0)

    def __len__(self) -> int:
        return int(self._ask("ctx.len") or 0)

    def __repr__(self) -> str:
        stats = self._ask("ctx.stats") or {}
        return (
            f"RLMContext(profile={stats.get('profile')!r}, files={stats.get('files')}, "
            f"bytes={stats.get('bytes')})"
        )

    def stats(self) -> Any:
        return self._ask("ctx.stats")

    def read(self, path: str) -> Any:
        return self._ask("ctx.read", {"path": str(path)})

    def text(self) -> Any:
        return self._ask("ctx.text")

    def search(self, pattern: str, *, limit: int = 200) -> Any:
        return self._ask("ctx.search", {"pattern": str(pattern), "limit": int(limit)})

    def select(self, *patterns: str) -> "ContextProxy":
        chosen = self._ask("ctx.select", {"patterns": [str(item) for item in patterns]})
        return ContextProxy(self._call, [str(item) for item in chosen or ()])

    def chunk(self, size: int = 20_000, *, overlap: int = 0) -> Any:
        return self._ask("ctx.chunk", {"size": int(size), "overlap": int(overlap)})


def _agent_id(value: Any) -> str:
    return str(getattr(value, "id", value))


class SandboxKernel:
    """One persistent namespace, executed inside the boundary."""

    def __init__(
        self,
        channel: ProtocolChannel,
        workspace: str | Path,
        kernel_id: str,
        policy: dict[str, Any] | None = None,
    ) -> None:
        self.channel = channel
        self.kernel_id = kernel_id
        self.cwd = Path(workspace).resolve()
        self.policy = policy or {}
        self.max_output_chars = max(1, int(self.policy.get("max_output_chars") or 1_000_000))
        self.max_checkpoint_bytes = max(
            1, int(self.policy.get("max_checkpoint_bytes") or 64 * 1024 * 1024)
        )
        self._call_id = 0
        self.globals: dict[str, Any] = {
            "__name__": "__rlm__",
            "__builtins__": __builtins__,
            "workspace": Workspace(self.cwd, policy),
            "shell": Shell(self.cwd, policy),
            "rlm": RLMProxy(self.host_call, kernel_id),
            # Subcalls run on the host: they need provider credentials, and a
            # quota the sandbox could reach would not be a quota.
            "llm_query": self._llm_query,
            "llm_query_batched": self._llm_query_batched,
            "context": ContextProxy(self.host_call),
        }

    def _llm_query(self, prompt: str, *, context: str = "", model: str | None = None) -> Any:
        return self.host_call(
            "llm.query", {"prompt": str(prompt), "context": str(context or ""), "model": model}
        )

    def _llm_query_batched(
        self,
        prompts: Sequence[str],
        *,
        contexts: Sequence[str] | None = None,
        model: str | None = None,
    ) -> Any:
        return self.host_call(
            "llm.query_batch",
            {
                "prompts": [str(item) for item in prompts],
                "contexts": [str(item) for item in contexts or ()],
                "model": model,
            },
        )

    def host_call(self, name: str, payload: dict[str, Any]) -> Any:
        """Ask the host to perform an operation and block for its answer."""
        self._call_id += 1
        call_id = self._call_id
        self.channel.send({"type": "call", "call_id": call_id, "name": name, "payload": payload})
        while True:
            message = self.channel.receive()
            if message is None:
                raise HostCallError("The host closed the channel during a call")
            if message.get("type") != "call_result" or message.get("call_id") != call_id:
                continue
            if not message.get("ok"):
                raise HostCallError(str(message.get("error") or "Host call failed"))
            return _revive(message.get("value"), self.host_call)

    def execute(self, code: str) -> dict[str, Any]:
        stream_limit = max(1, self.max_output_chars // 2)
        stdout = BoundedTextBuffer(stream_limit)
        stderr = BoundedTextBuffer(stream_limit)
        value: Any = None
        try:
            module = ast.parse(code, mode="exec")
            body = list(module.body)
            final = cast(ast.Expr, body.pop()) if body and isinstance(body[-1], ast.Expr) else None
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                if body:
                    exec(  # noqa: S102 - executing model code is this program's purpose
                        compile(ast.Module(body=body, type_ignores=[]), "<rlm-python>", "exec"),
                        self.globals,
                        self.globals,
                    )
                if final is not None:
                    value = eval(  # noqa: S307 - last expression mirrors a REPL
                        compile(ast.Expression(final.value), "<rlm-python>", "eval"),
                        self.globals,
                        self.globals,
                    )
        except BaseException:  # noqa: BLE001 - the traceback is returned to the model
            return {
                "output": stdout.getvalue() + stderr.getvalue(),
                "value_repr": "",
                "error": traceback.format_exc()[: self.max_output_chars],
            }
        return {
            "output": stdout.getvalue() + stderr.getvalue(),
            "value_repr": "" if value is None else repr(value)[: self.max_output_chars],
            "error": None,
        }

    def checkpoint(self, path: str | Path) -> dict[str, Any]:
        """Serialize state inside the boundary and describe it to the host."""
        target = Path(path)
        saved: dict[str, bytes] = {}
        skipped: list[str] = []
        size = 0
        for name, value in self.globals.items():
            if name in RESERVED_NAMES or name.startswith("__"):
                continue
            try:
                serialized = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
                if size + len(serialized) > self.max_checkpoint_bytes:
                    skipped.append(name)
                    continue
                saved[name] = serialized
                size += len(serialized)
            except Exception:  # noqa: BLE001 - isolate each value
                skipped.append(name)
        payload = pickle.dumps({"version": 1, "variables": saved}, protocol=pickle.HIGHEST_PROTOCOL)
        if len(payload) > self.max_checkpoint_bytes:
            return {
                "saved": [],
                "skipped": sorted(saved) + sorted(skipped),
                "error": f"checkpoint exceeds {self.max_checkpoint_bytes} bytes",
            }
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(target)
        except OSError as error:
            return {"saved": [], "skipped": sorted(saved) + sorted(skipped), "error": str(error)}
        return {
            "saved": sorted(saved),
            "skipped": sorted(skipped),
            "path": str(target),
            "digest": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }

    def restore(self, path: str | Path) -> dict[str, Any]:
        """Read state written inside this boundary. It never crosses to the host."""
        target = Path(path)
        if not target.is_file():
            return {"restored": []}
        if target.stat().st_size > self.max_checkpoint_bytes:
            return {
                "restored": [],
                "error": f"checkpoint exceeds {self.max_checkpoint_bytes} bytes",
            }
        try:
            payload = pickle.loads(target.read_bytes())  # noqa: S301 - sandbox-local state
        except Exception as error:  # noqa: BLE001 - a bad checkpoint cannot break resume
            return {"restored": [], "error": str(error)}
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return {"restored": []}
        variables = payload.get("variables")
        if not isinstance(variables, dict):
            return {"restored": []}
        restored: list[str] = []
        for raw_name, serialized in variables.items():
            name = str(raw_name)
            if name in RESERVED_NAMES or name.startswith("__") or not isinstance(serialized, bytes):
                continue
            try:
                self.globals[name] = pickle.loads(serialized)  # noqa: S301 - sandbox-local state
            except Exception:  # noqa: BLE001 - restore what can be restored
                continue
            restored.append(name)
        return {"restored": sorted(restored)}


def _revive(value: Any, call: Any) -> Any:
    """Rebuild the handles the host described, so they behave like objects."""
    if isinstance(value, dict) and value.get("__rlm__") == "agent":
        return AgentProxy(call, str(value.get("id") or ""), value.get("status"))
    if isinstance(value, dict) and value.get("__rlm__") == "response":
        return ResponseProxy(value)
    if isinstance(value, dict) and value.get("__rlm__") == "chunk":
        return ChunkProxy(value)
    if isinstance(value, list):
        return [_revive(item, call) for item in value]
    return value


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv[1:])
    kernel_id = arguments[0] if arguments else "root"
    workspace = arguments[1] if len(arguments) > 1 else "/workspace"
    try:
        policy = json.loads(arguments[2]) if len(arguments) > 2 else {}
    except (TypeError, ValueError):
        policy = {}
    if not isinstance(policy, dict):
        policy = {}
    pid_path = Path(arguments[3]) if len(arguments) > 3 and arguments[3] else None
    if pid_path is not None:
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        atexit.register(lambda: pid_path.unlink(missing_ok=True))

    channel = ProtocolChannel()
    kernel = SandboxKernel(channel, workspace, kernel_id, policy)
    channel.send({"type": "ready", "kernel_id": kernel_id, "protocol": PROTOCOL_VERSION})

    while True:
        message = channel.receive()
        if message is None:
            return 0
        operation = str(message.get("op") or "")
        request_id = message.get("id")
        if operation == "shutdown":
            return 0
        if operation == "ping":
            channel.send({"type": "result", "id": request_id, "alive": True})
            continue
        if operation == "execute":
            result = kernel.execute(str(message.get("code") or ""))
            checkpoint_path = message.get("checkpoint_path")
            if checkpoint_path:
                # Mirrors the host kernel: state is captured after every call,
                # including a failed one, because a failure can still have
                # mutated the namespace.
                result["checkpoint"] = kernel.checkpoint(str(checkpoint_path))
            channel.send({"type": "result", "id": request_id, **result})
            continue
        if operation == "checkpoint":
            channel.send(
                {
                    "type": "result",
                    "id": request_id,
                    **kernel.checkpoint(str(message.get("path") or "")),
                }
            )
            continue
        if operation == "restore":
            channel.send(
                {
                    "type": "result",
                    "id": request_id,
                    **kernel.restore(str(message.get("path") or "")),
                }
            )
            continue
        channel.send(
            {"type": "result", "id": request_id, "error": f"Unknown operation: {operation!r}"}
        )


if __name__ == "__main__":  # pragma: no cover - container entry point
    raise SystemExit(main())
