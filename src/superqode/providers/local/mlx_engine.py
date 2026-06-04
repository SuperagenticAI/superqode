"""In-process MLX engine: drives ``mlx_lm`` via a persistent worker subprocess.

This replaces the HTTP-to-``mlx_lm.server`` path for tool-using runs: SuperQode
owns generation, so it can parse tool calls itself (see :mod:`mlx_tools`) instead
of depending on a server's tool parser. The model stays loaded in the worker
across turns, so multi-turn agent loops don't reload weights.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


class MlxUnavailableError(RuntimeError):
    """Raised when the MLX worker cannot start or mlx_lm is missing."""


@dataclass
class MlxResult:
    text: str
    usage: Dict[str, Any] = field(default_factory=dict)
    backend: str = "mlx_lm"


class MlxEngine:
    """Owns a long-lived worker process that runs mlx_lm generation."""

    _WORKER_MODULE = "superqode.providers.local._mlx_worker"

    def __init__(self, python_executable: Optional[str] = None) -> None:
        # Use the interpreter SuperQode runs under (the uv .venv with mlx-lm).
        self._python = python_executable or sys.executable
        self._proc: Optional[subprocess.Popen[str]] = None
        self._lock = threading.Lock()

    # -- process management ---------------------------------------------------

    def _ensure_proc(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        try:
            self._proc = subprocess.Popen(
                [self._python, "-m", self._WORKER_MODULE],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                text=True,
                bufsize=1,
            )
        except Exception as exc:  # noqa: BLE001
            raise MlxUnavailableError(f"could not start MLX worker: {exc}") from exc
        return self._proc

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
                    proc.stdin.flush()
                proc.wait(timeout=3)
            except Exception:
                proc.kill()

    # -- generation -----------------------------------------------------------

    def generate(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 2048,
        temperature: Optional[float] = None,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> MlxResult:
        """Run one generation through the worker and return the raw text + usage."""
        request = {
            "op": "generate",
            "model": model,
            "messages": messages,
            "tools": tools or None,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        with self._lock:
            proc = self._ensure_proc()
            assert proc.stdin and proc.stdout
            try:
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
            except Exception as exc:  # noqa: BLE001
                self._proc = None
                raise MlxUnavailableError(f"MLX worker write failed: {exc}") from exc

            while True:
                line = proc.stdout.readline()
                if not line:
                    self._proc = None
                    raise MlxUnavailableError("MLX worker exited unexpectedly")
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "progress":
                    if progress_callback:
                        progress_callback(msg.get("phase", ""), msg)
                    continue
                if mtype == "error":
                    raise MlxUnavailableError(msg.get("error", "MLX worker error"))
                if mtype == "result":
                    return MlxResult(
                        text=msg.get("text", ""),
                        usage=msg.get("usage", {}) or {},
                        backend=msg.get("backend", "mlx_lm"),
                    )


# Process-wide singleton so the worker (and loaded model) is reused across turns.
_engine: Optional[MlxEngine] = None


def get_mlx_engine() -> MlxEngine:
    global _engine
    if _engine is None:
        _engine = MlxEngine()
    return _engine


__all__ = ["MlxEngine", "MlxResult", "MlxUnavailableError", "get_mlx_engine"]
