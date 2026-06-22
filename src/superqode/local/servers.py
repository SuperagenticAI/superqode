"""Start, stop, and track local model servers as managed daemons.

Users start LM Studio / MLX / DS4 / llama.cpp / Ollama servers from the TUI or
``superqode local serve`` without leaving the app. Servers are launched as
persistent background processes (``start_new_session`` so they survive our exit)
with stdout/stderr captured to a log file; pid/port/cmd are recorded under
``~/.superqode/servers/<engine>.json`` so a later ``superqode local servers`` or
``superqode local stop`` can manage them. An already-running server is *adopted*
(reported, never double-started).

The readiness probe waits only for the HTTP endpoint to answer, not for a model
to finish loading: every engine here binds its port quickly and loads weights
lazily on the first request, so a bounded wait keeps us well under the live
probe budget even for very large models.

Engine notes:

- ``ollama``    ``ollama serve``; context via ``OLLAMA_CONTEXT_LENGTH`` at serve
                time. We own the pid but usually adopt an already-running daemon.
- ``lmstudio``  ``lms server start``; the LM Studio backend owns the process, so
                we do not track a pid. Stop with ``lms server stop``. Per-model
                context is set later at load time (``lms load -c``).
- ``mlx``       ``<venv-python> -m mlx_lm server``. MUST use the venv interpreter
                so we never pick up a stray ``mlx_lm.server`` from another
                environment (e.g. miniconda). Requires the ``superqode[mlx]``
                extra installed in this environment.
- ``ds4``       ``./ds4-server --ctx N``; built binary lives in the ds4 checkout
                (``~/oss/ds4`` by default). If it is missing we offer to build it.
- ``llama.cpp`` ``llama-server -m <gguf> -c N``.
"""

from __future__ import annotations

import importlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SERVERS_DIR = Path.home() / ".superqode" / "servers"

# How long to wait for the HTTP endpoint to answer after launch. The port binds
# quickly; weights load lazily on first request, so this stays small.
DEFAULT_READY_TIMEOUT = 40.0
_PROBE_TIMEOUT = 1.5
_POLL_INTERVAL = 0.4

# Default ds4 checkout used when the binary is not on PATH.
DS4_CHECKOUT = Path.home() / "oss" / "ds4"
DS4_DEFAULT_CTX = 32768
DS4_DEFAULT_KV_DISK_MB = 8192
DS4_DEFAULT_KV_DIR = Path.home() / ".superqode" / "ds4-kv"


@dataclass
class ServerSpec:
    """Static description of how to launch and probe one engine's server."""

    engine: str
    default_host: str = "127.0.0.1"
    default_port: int = 8080
    # Path appended to the base URL for the readiness probe.
    ready_path: str = "/v1/models"
    # True when launching needs a model id / weight path up front.
    needs_model: bool = False
    # How the engine maps a desired context window onto its start command.
    # One of: "env" (OLLAMA_CONTEXT_LENGTH), "flag" (--ctx N), "load" (set at
    # model load, not server start), "none" (model-defined, no knob).
    ctx_mode: str = "none"
    notes: str = ""


# Spec table. Command building lives in ServerManager so it can resolve the venv
# interpreter and the ds4 binary at runtime.
SPECS: Dict[str, ServerSpec] = {
    "ollama": ServerSpec(
        engine="ollama",
        default_port=11434,
        ready_path="/api/version",
        ctx_mode="env",
        notes="Usually already running; adopted when present.",
    ),
    "lmstudio": ServerSpec(
        engine="lmstudio",
        default_port=1234,
        ready_path="/v1/models",
        ctx_mode="load",
        notes="LM Studio backend owns the process; context set at model load.",
    ),
    "mlx": ServerSpec(
        engine="mlx",
        default_port=8080,
        ready_path="/health",
        needs_model=True,
        ctx_mode="none",
        notes="Needs the superqode[mlx] extra in this environment.",
    ),
    "ds4": ServerSpec(
        engine="ds4",
        default_port=8000,
        ready_path="/v1/models",
        ctx_mode="flag",
        notes="Built ds4-server binary; offers to build when missing.",
    ),
    "llama.cpp": ServerSpec(
        engine="llama.cpp",
        default_port=8081,
        ready_path="/health",
        needs_model=True,
        ctx_mode="flag",
        notes="Pass a .gguf path as the model.",
    ),
}


# Install guidance shown when an engine is not installed. Kept here (not in the
# TUI) so the CLI and TUI give identical advice.
INSTALL_GUIDES: Dict[str, List[str]] = {
    "ollama": [
        "Install Ollama, then it runs in the background automatically:",
        "  macOS:  brew install ollama   (or https://ollama.com/download)",
        "  Linux:  curl -fsSL https://ollama.com/install.sh | sh",
        "Pull a model with: ollama pull qwen3:8b",
    ],
    "lmstudio": [
        "Install LM Studio (GUI) and its CLI:",
        "  1. Download the app: https://lmstudio.ai/",
        "  2. Install the CLI:  npx lmstudio install-cli   (or from the app)",
        "  3. Download a model inside the app (e.g. search 'qwen3-coder')",
    ],
    "mlx": [
        "MLX runs on Apple Silicon. Install mlx-lm into the SAME environment",
        "that runs superqode (not miniconda):",
        "  if you launch via 'superqode':  uv tool install 'superqode[mlx]'",
        "  if you run from a source checkout:  uv pip install -e '.[mlx]'",
        "Then pick a model already in your Hugging Face cache (no surprise download).",
    ],
    "ds4": [
        "DS4 (DeepSeek V4 Flash) ships as a source build:",
        "  superqode local serve ds4 --build     # clones + makes the binary",
        "  cd ~/oss/ds4 && ./download_model.sh   # large GGUF, run when ready",
        "Start safely with: superqode local serve ds4 --ctx 32768",
        "Use --ctx 100000 only for long coding sessions with enough memory headroom.",
    ],
    "llama.cpp": [
        "Install llama.cpp's server binary:",
        "  macOS:  brew install llama.cpp",
        "  Then point --model at a local .gguf file.",
    ],
}


def install_guide(engine: str) -> List[str]:
    return INSTALL_GUIDES.get(engine, [f"No install guide available for {engine}."])


MLX_REQUIREMENT = "mlx-lm>=0.31.0,<0.32.0"


def mlx_install_command(python: Optional[str] = None) -> str:
    """Exact command used by the one-click MLX installer."""
    from superqode.providers.env_introspect import python_package_install_command

    return python_package_install_command(MLX_REQUIREMENT, python=python or sys.executable)


def _has_extra_arg(extra_args: List[str], flag: str) -> bool:
    return flag in extra_args or any(arg.startswith(f"{flag}=") for arg in extra_args)


def discover_gguf_models(limit: int = 50) -> List[dict]:
    """Find cached ``.gguf`` model files across the common local caches.

    Returns dicts ``{"id": <filename>, "path": <abs path>}``. Multimodal
    projector files (``mmproj``) and embedding models are skipped since they
    cannot serve chat completions.
    """
    roots = [
        Path.home() / ".cache" / "huggingface" / "hub",
        Path.home() / ".cache" / "lm-studio" / "models",
        Path.home() / "models",
        Path.home() / ".cache" / "llama.cpp",
        Path.home() / ".local" / "share" / "models",
    ]
    seen: dict[str, dict] = {}
    for root in roots:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*.gguf"):
                low = path.name.lower()
                if "mmproj" in low or "embed" in low or "nomic" in low:
                    continue
                key = str(path)
                if key not in seen:
                    seen[key] = {"id": path.name, "path": key}
                if len(seen) >= limit:
                    return list(seen.values())
        except (OSError, PermissionError):
            continue
    return list(seen.values())


def _mlx_importable(python: str) -> bool:
    try:
        result = subprocess.run(  # noqa: S603
            [python, "-c", "import mlx_lm"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def install_mlx(python: Optional[str] = None, timeout: int = 1200) -> tuple[bool, str]:
    """Install mlx-lm into the environment that runs SuperQode (best effort).

    Uses ``uv pip install --python <interpreter>`` so it lands in the exact env
    that ``sys.executable`` belongs to (a uv-tool env or a source venv), never a
    stray miniconda. Falls back to ``pip`` if uv is unavailable. Returns
    ``(ok, message)``.
    """
    import importlib

    python = python or sys.executable
    cmd = shlex.split(mlx_install_command(python))

    try:
        result = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (False, f"install command failed: {exc}")

    importlib.invalidate_caches()
    if _mlx_importable(python):
        return (True, "mlx-lm installed")
    tail = (result.stderr or result.stdout or "").strip().splitlines()
    return (False, tail[-1] if tail else "install finished but mlx_lm is still not importable")


def parse_inline_start(text: str) -> tuple[str, dict, str]:
    """Parse the TUI inline 'start this server?' prompt input.

    Accepts an empty string (Enter = defaults), a cancel word, or
    space-separated ``key=value`` overrides (``port`` / ``ctx`` / ``host`` /
    ``model``); a bare integer is treated as a port.

    Returns ``(action, opts, error)`` where action is ``"start"``,
    ``"cancel"``, or ``"error"`` (with ``error`` carrying the message).
    """
    raw = text.strip()
    low = raw.lower()
    if low in ("n", "no", "skip", "cancel", "q"):
        return ("cancel", {}, "")

    opts: dict = {}
    for tok in raw.split():
        lt = tok.lower()
        if lt in ("y", "yes", "start"):
            continue
        if "=" in tok:
            key, _, val = tok.partition("=")
            key = key.lower().strip()
            val = val.strip()
            try:
                if key in ("port", "p"):
                    opts["port"] = int(val)
                elif key == "ctx":
                    opts["ctx"] = int(val)
                elif key == "host":
                    opts["host"] = val
                elif key in ("model", "m"):
                    opts["model"] = val
                else:
                    return ("error", {}, f"unknown option {key!r}")
            except ValueError:
                return ("error", {}, f"bad number for {key!r}")
        elif tok.isdigit():
            opts["port"] = int(tok)
        else:
            return ("error", {}, f"could not parse {tok!r}")
    return ("start", opts, "")


def _hf_model_cached(model_id: str) -> bool:
    """True if a Hugging Face model id looks already downloaded locally.

    Used to avoid kicking off a multi-GB download without the user's consent.
    Returns True for local paths / bare names (nothing to download remotely).
    """
    if not model_id or "/" not in model_id:
        return True
    if os.path.exists(model_id):  # an explicit local path
        return True
    roots: List[Path] = []
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        roots.append(Path(hf_home) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    slug = "models--" + model_id.replace("/", "--")
    return any((root / slug).exists() for root in roots)


@dataclass
class LocalReadiness:
    """Whether an engine is ready to use, and what the user should do if not."""

    engine: str
    installed: bool
    running: bool
    base_url: str
    state: str  # "running" | "stopped" | "missing"
    start_hint: str  # one-line actionable command for the "stopped" case
    needs_model: bool
    startable: bool = True
    app_running: bool = False
    cli_available: bool = False
    install_guide: List[str] = field(default_factory=list)


@dataclass
class ServerHandle:
    """A server SuperQode started or adopted, persisted to the registry."""

    engine: str
    host: str
    port: int
    base_url: str
    cmd: List[str] = field(default_factory=list)
    pid: Optional[int] = None
    log_path: Optional[str] = None
    started_at: float = 0.0
    adopted: bool = False
    model: Optional[str] = None
    ctx: Optional[int] = None
    # Informational messages about how port/ctx/model were applied.
    notes: List[str] = field(default_factory=list)

    @property
    def registry_path(self) -> Path:
        return SERVERS_DIR / f"{self.engine}.json"

    def to_dict(self) -> dict:
        return asdict(self)


class ServerError(RuntimeError):
    """Raised when a server cannot be started (not installed, missing model)."""


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only; the wider codebase avoids a hard httpx dependency
# in the detection path).
# ---------------------------------------------------------------------------


def _probe(url: str, timeout: float = _PROBE_TIMEOUT) -> bool:
    try:
        request = Request(url, headers={"User-Agent": "SuperQode"}, method="GET")
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return 200 <= response.status < 500
    except HTTPError:
        return True  # answered, even if with an error status
    except (URLError, OSError, ValueError):
        return False


class ServerManager:
    """Launch, adopt, probe, and stop local model servers."""

    def __init__(self, registry_dir: Path = SERVERS_DIR) -> None:
        self.registry_dir = registry_dir

    # -- registry --------------------------------------------------------

    def _registry_path(self, engine: str) -> Path:
        return self.registry_dir / f"{engine}.json"

    def _save(self, handle: ServerHandle) -> None:
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self._registry_path(handle.engine).write_text(
            json.dumps(handle.to_dict(), indent=2), encoding="utf-8"
        )

    def _load(self, engine: str) -> Optional[ServerHandle]:
        path = self._registry_path(engine)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ServerHandle(**data)
        except (ValueError, OSError, TypeError):
            return None

    def _forget(self, engine: str) -> None:
        path = self._registry_path(engine)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    # -- status ----------------------------------------------------------

    def base_url(self, engine: str, host: str, port: int) -> str:
        # Every supported engine exposes an OpenAI-compatible route at /v1; the
        # readiness path (e.g. /health) is a separate, lighter probe.
        return f"http://{host}:{port}/v1"

    def is_running(
        self, engine: str, host: Optional[str] = None, port: Optional[int] = None
    ) -> bool:
        spec = SPECS[engine]
        host = host or spec.default_host
        port = port or spec.default_port
        return _probe(f"http://{host}:{port}{spec.ready_path}")

    def status(self, engine: str) -> dict:
        """Return a status dict for one engine (running, managed, pid, url)."""
        spec = SPECS[engine]
        handle = self._load(engine)
        host = handle.host if handle else spec.default_host
        port = handle.port if handle else spec.default_port
        running = self.is_running(engine, host, port)
        managed = handle is not None and handle.pid is not None and _pid_alive(handle.pid)
        if handle is not None and not running:
            # Stale registry entry; the server is gone.
            self._forget(engine)
            handle = None
        return {
            "engine": engine,
            "running": running,
            "managed": managed,
            "pid": handle.pid if handle else None,
            "host": host,
            "port": port,
            "base_url": self.base_url(engine, host, port),
            "model": handle.model if handle else None,
            "log_path": handle.log_path if handle else None,
        }

    def list_all(self) -> List[dict]:
        return [self.status(engine) for engine in SPECS]

    def precheck(
        self, engine: str, host: Optional[str] = None, port: Optional[int] = None
    ) -> "LocalReadiness":
        """Classify an engine as running / installed-but-stopped / missing.

        This is the gate the TUI calls before listing models: it tells the
        developer whether they need to start (or install) anything, and gives a
        single actionable next step.
        """
        spec = SPECS[engine]
        host = host or spec.default_host
        port = port or spec.default_port
        running = self.is_running(engine, host, port)
        installed = running or self.is_installed(engine)
        cli_available = shutil.which("lms") is not None if engine == "lmstudio" else False

        if running:
            state = "running"
        elif installed:
            state = "stopped"
        else:
            state = "missing"

        app_running = self.app_running(engine)
        startable = running or self.can_start(engine)

        if spec.needs_model:
            start_hint = f":local serve {engine} --model <model-id>"
        elif engine == "lmstudio" and not startable:
            start_hint = "Open LM Studio and start the Local Server on port 1234"
        else:
            start_hint = f":local serve {engine}"

        return LocalReadiness(
            engine=engine,
            installed=installed,
            running=running,
            base_url=self.base_url(engine, host, port),
            state=state,
            start_hint=start_hint,
            needs_model=spec.needs_model,
            startable=startable,
            app_running=app_running,
            cli_available=cli_available,
            install_guide=install_guide(engine),
        )

    # -- installed check -------------------------------------------------

    def app_running(self, engine: str) -> bool:
        """True when an engine's companion GUI/backend app is already open."""
        if engine != "lmstudio":
            return False
        try:
            result = subprocess.run(  # noqa: S603
                ["pgrep", "-x", "LM Studio"],
                capture_output=True,
                timeout=1,
                check=False,
            )
            if result.returncode == 0:
                return True
            result = subprocess.run(  # noqa: S603
                ["pgrep", "-f", "LM Studio"],
                capture_output=True,
                timeout=1,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def can_start(self, engine: str) -> bool:
        """True when SuperQode can launch the server process itself."""
        if engine == "lmstudio":
            # The GUI app alone is enough to be "installed", but starting the
            # local server from SuperQode needs both the CLI and an already-open
            # LM Studio backend.
            return shutil.which("lms") is not None and self.app_running(engine)
        return self.is_installed(engine)

    def is_installed(self, engine: str) -> bool:
        if engine == "ollama":
            return shutil.which("ollama") is not None
        if engine == "lmstudio":
            return shutil.which("lms") is not None or Path("/Applications/LM Studio.app").exists()
        if engine == "mlx":
            # Refresh the import cache: mlx-lm may have just been pip-installed
            # into this same interpreter, in which case a stale finder would
            # still report it missing.
            importlib.invalidate_caches()
            return find_spec("mlx_lm") is not None
        if engine == "ds4":
            return self._ds4_binary() is not None
        if engine == "llama.cpp":
            return shutil.which("llama-server") is not None
        return False

    def _ds4_binary(self) -> Optional[Path]:
        on_path = shutil.which("ds4-server")
        if on_path:
            return Path(on_path)
        candidate = DS4_CHECKOUT / "ds4-server"
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
        return None

    # -- command building ------------------------------------------------

    def build_command(
        self,
        engine: str,
        *,
        host: str,
        port: int,
        model: Optional[str] = None,
        ctx: Optional[int] = None,
        extra_args: Optional[List[str]] = None,
    ) -> tuple[List[str], Dict[str, str], Optional[Path]]:
        """Return (argv, env_overrides, cwd) for launching ``engine``.

        Raises ServerError when prerequisites (binary, model, extra) are missing.
        """
        spec = SPECS[engine]
        extra_args = list(extra_args or [])
        if spec.needs_model and not model:
            raise ServerError(f"{engine} needs a model: pass --model")

        if engine == "ollama":
            env = {"OLLAMA_HOST": f"{host}:{port}"}
            if ctx:
                env["OLLAMA_CONTEXT_LENGTH"] = str(ctx)
            return (["ollama", "serve", *extra_args], env, None)

        if engine == "lmstudio":
            cmd = ["lms", "server", "start", "-p", str(port)]
            if host not in ("127.0.0.1", "localhost"):
                cmd += ["--bind", host]
            return (cmd + extra_args, {}, None)

        if engine == "mlx":
            # Always the venv interpreter, never a stray mlx_lm.server on PATH.
            cmd = [
                sys.executable,
                "-m",
                "mlx_lm",
                "server",
                "--model",
                str(model),
                "--host",
                host,
                "--port",
                str(port),
            ]
            return (cmd + extra_args, {}, None)

        if engine == "ds4":
            binary = self._ds4_binary()
            if binary is None:
                raise ServerError(
                    "ds4-server not built. Build it with: superqode local serve ds4 --build"
                )
            ctx = ctx or DS4_DEFAULT_CTX
            cmd = [str(binary), "--host", host, "--port", str(port), "--ctx", str(ctx)]
            if not _has_extra_arg(extra_args, "--kv-disk-dir"):
                cmd += ["--kv-disk-dir", str(DS4_DEFAULT_KV_DIR)]
            if not _has_extra_arg(extra_args, "--kv-disk-space-mb"):
                cmd += ["--kv-disk-space-mb", str(DS4_DEFAULT_KV_DISK_MB)]
            return (cmd + extra_args, {}, binary.parent)

        if engine == "llama.cpp":
            cmd = ["llama-server", "-m", str(model), "--host", host, "--port", str(port)]
            if ctx:
                cmd += ["-c", str(ctx)]
            return (cmd + extra_args, {}, None)

        raise ServerError(f"Unknown engine: {engine}")

    # -- start / stop ----------------------------------------------------

    def start(
        self,
        engine: str,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
        model: Optional[str] = None,
        ctx: Optional[int] = None,
        extra_args: Optional[List[str]] = None,
        wait: bool = True,
        timeout: float = DEFAULT_READY_TIMEOUT,
        allow_download: bool = False,
    ) -> ServerHandle:
        """Start (or adopt) the engine's server and return a handle.

        If a server is already answering on the target host/port it is adopted
        rather than re-launched. MLX will not download a missing model from
        Hugging Face unless ``allow_download`` is set (so we never pull several
        GB without the user's consent).
        """
        if engine not in SPECS:
            raise ServerError(f"Unknown engine: {engine}")
        spec = SPECS[engine]
        host = host or spec.default_host
        port = port or spec.default_port
        if engine == "ds4" and ctx is None:
            ctx = DS4_DEFAULT_CTX

        # Guard against silent multi-GB downloads. MLX pulls from Hugging Face on
        # launch; refuse unless the model is already cached or the caller opted in.
        if engine == "mlx" and model and not allow_download and not _hf_model_cached(model):
            raise ServerError(
                f"{model} is not downloaded yet. Starting MLX would download it from "
                "Hugging Face (this can be several GB). Re-run with --allow-download to "
                "proceed, or choose a model already in your cache "
                "(superqode providers mlx list)."
            )

        # Adopt an already-running server.
        if self.is_running(engine, host, port):
            adopt_notes: List[str] = []
            if ctx:
                adopt_notes.append(
                    f"already running on port {port}; --ctx {ctx:,} not applied "
                    "(stop it first to relaunch with a new context window)"
                )
            handle = ServerHandle(
                engine=engine,
                host=host,
                port=port,
                base_url=self.base_url(engine, host, port),
                adopted=True,
                model=model,
                ctx=ctx,
                notes=adopt_notes,
                started_at=time.time(),
            )
            self._save(handle)
            return handle

        if not self.is_installed(engine):
            raise ServerError(f"{engine} is not installed on this machine")

        cmd, env_overrides, cwd = self.build_command(
            engine, host=host, port=port, model=model, ctx=ctx, extra_args=extra_args
        )

        self.registry_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.registry_dir / f"{engine}.log"
        env = {**os.environ, **env_overrides}

        if engine == "lmstudio":
            handle = self._start_lmstudio(
                cmd,
                env=env,
                host=host,
                port=port,
                model=model,
                ctx=ctx,
                log_path=log_path,
                wait=wait,
                timeout=timeout,
            )
            self._save(handle)
            return handle

        log_handle = open(log_path, "ab")  # noqa: SIM115 (lives with the daemon)
        try:
            proc = subprocess.Popen(  # noqa: S603
                cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=str(cwd) if cwd else None,
                env=env,
                start_new_session=True,  # survive SuperQode exiting (managed daemon)
            )
        except (OSError, ValueError) as exc:
            log_handle.close()
            raise ServerError(f"Failed to launch {engine}: {exc}") from exc

        # lms hands off to the LM Studio backend and exits; we do not own its pid.
        owned_pid: Optional[int] = None if engine == "lmstudio" else proc.pid

        handle = ServerHandle(
            engine=engine,
            host=host,
            port=port,
            base_url=self.base_url(engine, host, port),
            cmd=cmd,
            pid=owned_pid,
            log_path=str(log_path),
            started_at=time.time(),
            model=model,
            ctx=ctx,
            notes=self._ctx_notes(engine, ctx, model),
        )

        if wait:
            ready = self._wait_ready(engine, host, port, timeout, proc, owned_pid)
            if not ready:
                tail = _tail(log_path)
                raise ServerError(
                    f"{engine} did not become ready within {timeout:.0f}s.\nLast log lines:\n{tail}"
                )
            # LM Studio sets context at model load, not server start. Once the
            # server is up, load the requested model at the requested context.
            if engine == "lmstudio" and model:
                handle.notes.extend(self._lms_load(model, ctx))

        self._save(handle)
        return handle

    def _start_lmstudio(
        self,
        cmd: List[str],
        *,
        env: Dict[str, str],
        host: str,
        port: int,
        model: Optional[str],
        ctx: Optional[int],
        log_path: Path,
        wait: bool,
        timeout: float,
    ) -> ServerHandle:
        """Run the LM Studio CLI handoff and surface its output immediately."""
        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=env,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ServerError(f"Failed to launch lmstudio: {exc}") from exc

        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        log_path.write_text(output + ("\n" if output else ""), encoding="utf-8")
        if result.returncode != 0:
            detail = output or f"lms exited with status {result.returncode}"
            raise ServerError(
                "LM Studio did not accept the server start command.\n"
                f"Command: {shlex.join(cmd)}\n"
                f"{detail}\n"
                "Open LM Studio, load a chat model, then start the Local Server "
                "from the app or try the command again."
            )

        handle = ServerHandle(
            engine="lmstudio",
            host=host,
            port=port,
            base_url=self.base_url("lmstudio", host, port),
            cmd=cmd,
            pid=None,
            log_path=str(log_path),
            started_at=time.time(),
            model=model,
            ctx=ctx,
            notes=self._ctx_notes("lmstudio", ctx, model),
        )

        if wait:
            class _NoOwnedProcess:
                def poll(self):
                    return None

            ready = self._wait_ready("lmstudio", host, port, timeout, _NoOwnedProcess(), None)
            if not ready:
                tail = _tail(log_path)
                raise ServerError(
                    "LM Studio accepted the command, but the local server did not "
                    f"answer at {handle.base_url} within {timeout:.0f}s.\n"
                    f"Command: {shlex.join(cmd)}\n"
                    f"Last log lines:\n{tail}\n"
                    "Check LM Studio's Local Server tab, then run :connect local again."
                )
            if model:
                handle.notes.extend(self._lms_load(model, ctx))

        return handle

    def _ctx_notes(self, engine: str, ctx: Optional[int], model: Optional[str]) -> List[str]:
        """Explain how (or whether) the requested context window was applied."""
        notes: List[str] = []
        spec = SPECS[engine]
        if not ctx:
            return notes
        if spec.ctx_mode == "env":
            notes.append(f"context window set to {ctx:,} via OLLAMA_CONTEXT_LENGTH")
        elif spec.ctx_mode == "flag":
            notes.append(f"context window set to {ctx:,}")
        elif spec.ctx_mode == "load":
            if not model:
                notes.append(
                    f"context {ctx:,} applies at model load; pass --model to load one at that size"
                )
        elif spec.ctx_mode == "none":
            notes.append(
                f"MLX context is fixed by the model (--ctx {ctx:,} ignored); "
                "choose a model converted for the window you need"
            )
        return notes

    def _lms_load(self, model: str, ctx: Optional[int], timeout: int = 600) -> List[str]:
        """Load a model into LM Studio at a given context (best effort)."""
        if not shutil.which("lms"):
            return ["lms CLI not found; load the model from the LM Studio app"]
        cmd = ["lms", "load", model, "-y"]
        if ctx:
            cmd += ["-c", str(ctx)]
        try:
            result = subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return [f"could not load {model}: {exc}"]
        if result.returncode == 0:
            suffix = f" at ctx {ctx:,}" if ctx else ""
            return [f"loaded {model}{suffix}"]
        err = (result.stderr or result.stdout or "").strip().splitlines()
        return [f"lms load failed: {err[-1] if err else 'unknown error'}"]

    def _wait_ready(
        self,
        engine: str,
        host: str,
        port: int,
        timeout: float,
        proc: subprocess.Popen,
        owned_pid: Optional[int],
    ) -> bool:
        spec = SPECS[engine]
        url = f"http://{host}:{port}{spec.ready_path}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if owned_pid is not None and proc.poll() is not None:
                return False  # process exited before binding
            if _probe(url):
                return True
            time.sleep(_POLL_INTERVAL)
        return False

    def stop(self, engine: str) -> bool:
        """Stop a managed server. Returns True if anything was stopped."""
        if engine == "lmstudio":
            if shutil.which("lms"):
                try:
                    subprocess.run(  # noqa: S603
                        ["lms", "server", "stop"],
                        capture_output=True,
                        timeout=15,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
            self._forget(engine)
            return True

        handle = self._load(engine)
        self._forget(engine)
        if handle is None or handle.pid is None:
            return False
        if handle.adopted:
            return False  # never kill a server we only adopted
        return _terminate(handle.pid)


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False  # no such process
    except PermissionError:
        return True  # exists but owned by another user
    except OSError:
        return False


def _terminate(pid: int, grace: float = 5.0) -> bool:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            return False
    deadline = time.time() + grace
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.2)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    return True


def _tail(path: Path, lines: int = 12) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no log)"
    return "\n".join(text.splitlines()[-lines:])


# ---------------------------------------------------------------------------
# DS4 build helper
# ---------------------------------------------------------------------------


def ds4_build_plan() -> dict:
    """Describe how to obtain a built ds4-server, without doing anything heavy.

    Returns a dict the CLI/TUI render: whether a checkout exists, the build
    command, and the (gated) model-download command.
    """
    checkout = DS4_CHECKOUT
    has_checkout = (checkout / "Makefile").exists()
    binary = checkout / "ds4-server"
    return {
        "checkout": str(checkout),
        "has_checkout": has_checkout,
        "has_binary": binary.exists(),
        "clone_cmd": ["git", "clone", "https://github.com/antirez/ds4", str(checkout)],
        "build_cmd": ["make"],  # macOS Metal default target
        "download_cmd": ["./download_model.sh"],  # large GGUF; user-gated
    }


def ds4_build(checkout: Path = DS4_CHECKOUT, timeout: int = 1800) -> Path:
    """Clone (if needed) and ``make`` the ds4-server binary. Returns its path.

    Does NOT download the model weights: that is a separate, user-gated step.
    """
    if not (checkout / "Makefile").exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(  # noqa: S603
            ["git", "clone", "https://github.com/antirez/ds4", str(checkout)],
            check=True,
            timeout=timeout,
        )
    subprocess.run(["make"], cwd=str(checkout), check=True, timeout=timeout)  # noqa: S603,S607
    binary = checkout / "ds4-server"
    if not binary.exists():
        raise ServerError(f"Build finished but {binary} is missing")
    return binary


_DEFAULT_MANAGER: Optional[ServerManager] = None


def get_manager() -> ServerManager:
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = ServerManager()
    return _DEFAULT_MANAGER


__all__ = [
    "ServerSpec",
    "ServerHandle",
    "ServerManager",
    "ServerError",
    "LocalReadiness",
    "SPECS",
    "SERVERS_DIR",
    "INSTALL_GUIDES",
    "install_guide",
    "install_mlx",
    "parse_inline_start",
    "get_manager",
    "ds4_build",
    "ds4_build_plan",
]
