"""Inference engine detection: what is installed, what is running, what it can do.

Each detector is cheap (subprocess version checks and sub-2-second HTTP
probes) and failure-tolerant. The result feeds the doctor's recommendation
and the bench's target list.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROBE_TIMEOUT = 1.5


@dataclass
class EngineStatus:
    engine: str
    installed: bool = False
    version: str = ""
    running: bool = False
    endpoint: str = ""
    notes: List[str] = field(default_factory=list)


def _http_json(url: str) -> Optional[dict]:
    try:
        request = Request(url, headers={"User-Agent": "SuperQode"}, method="GET")
        with urlopen(request, timeout=PROBE_TIMEOUT) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def _http_ok(url: str) -> bool:
    try:
        request = Request(url, headers={"User-Agent": "SuperQode"}, method="GET")
        with urlopen(request, timeout=PROBE_TIMEOUT) as response:  # noqa: S310
            return 200 <= response.status < 500
    except HTTPError:
        return True  # server answered, even if with an error status
    except (URLError, OSError, ValueError):
        return False


def _cli_version(cmd: List[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        text = (out.stdout or out.stderr or "").strip()
        return text.splitlines()[0][:80] if text else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _parse_semver(text: str) -> tuple:
    import re

    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        return (0, 0, 0)
    return tuple(int(g or 0) for g in match.groups())


def detect_ollama(
    unified_memory_gb: Optional[int] = None, apple_silicon: bool = False
) -> EngineStatus:
    status = EngineStatus(engine="ollama", endpoint="http://localhost:11434/v1")
    if shutil.which("ollama"):
        status.installed = True
        status.version = _cli_version(["ollama", "--version"])
    payload = _http_json("http://localhost:11434/api/version")
    if payload is not None:
        status.running = True
        status.installed = True
        if not status.version and isinstance(payload.get("version"), str):
            status.version = payload["version"]
    if status.installed and apple_silicon:
        if _parse_semver(status.version) >= (0, 19, 0):
            if unified_memory_gb and unified_memory_gb > 32:
                status.notes.append(
                    "MLX runtime available (0.19+, >32GB): fastest Ollama path on Apple Silicon"
                )
            else:
                status.notes.append(
                    "Ollama 0.19+ MLX runtime needs more than 32GB unified memory; using the standard runtime"
                )
        else:
            status.notes.append("Update to Ollama 0.19+ to get the MLX runtime on Apple Silicon")
    return status


def detect_lmstudio() -> EngineStatus:
    status = EngineStatus(engine="lmstudio", endpoint="http://localhost:1234/v1")
    if shutil.which("lms"):
        status.installed = True
        status.version = _cli_version(["lms", "--version"])
    elif Path("/Applications/LM Studio.app").exists():
        status.installed = True
    if _http_json("http://localhost:1234/v1/models") is not None:
        status.running = True
        status.installed = True
    return status


def detect_mlx_lm() -> EngineStatus:
    status = EngineStatus(engine="mlx-lm", endpoint="http://localhost:8080/v1")
    if find_spec("mlx_lm") is not None:
        status.installed = True
        try:
            import importlib.metadata as md

            status.version = md.version("mlx-lm")
        except Exception:
            pass
    if _http_json("http://localhost:8080/v1/models") is not None or _http_ok(
        "http://localhost:8080/health"
    ):
        status.running = True
    if status.installed:
        status.notes.append("Start with: superqode local serve mlx --model <hf-id>")
    return status


def detect_llama_cpp() -> EngineStatus:
    status = EngineStatus(engine="llama.cpp", endpoint="http://localhost:8081/v1")
    if shutil.which("llama-server"):
        status.installed = True
        status.version = _cli_version(["llama-server", "--version"])
    if _http_ok("http://localhost:8081/health"):
        status.running = True
        status.installed = True
    return status


def detect_python_engine(module: str, engine: str, default_port: int) -> EngineStatus:
    status = EngineStatus(engine=engine, endpoint=f"http://localhost:{default_port}/v1")
    if find_spec(module) is not None:
        status.installed = True
        try:
            import importlib.metadata as md

            status.version = md.version(module)
        except Exception:
            pass
    if _http_json(f"http://localhost:{default_port}/v1/models") is not None:
        status.running = True
    return status


def detect_ds4() -> EngineStatus:
    status = EngineStatus(engine="ds4", endpoint="http://localhost:8000/v1")
    if shutil.which("ds4-server"):
        status.installed = True
    for candidate in (
        Path.home() / "oss" / "ds4" / "ds4-server",
        Path.home() / "oss" / "ds4" / "ds4",
    ):
        if candidate.exists():
            status.installed = True
            status.notes.append(f"local build at {candidate}")
            break
    if _http_json("http://localhost:8000/v1/models") is not None:
        status.running = True
    if status.installed:
        status.notes.append("Start with: superqode local serve ds4 --ctx 32768")
        status.notes.append("Use --ctx 100000 for long sessions; Think Max needs --ctx 393216+")
    return status


def detect_engines(
    unified_memory_gb: Optional[int] = None, apple_silicon: bool = False
) -> Dict[str, EngineStatus]:
    """Detect all known engines. Keys are engine ids used by the matrix."""
    engines = {
        "ollama": detect_ollama(unified_memory_gb, apple_silicon),
        "lmstudio": detect_lmstudio(),
        "mlx-lm": detect_mlx_lm(),
        "llama.cpp": detect_llama_cpp(),
        "vllm": detect_python_engine("vllm", "vllm", 8000),
        "sglang": detect_python_engine("sglang", "sglang", 30000),
        "ds4": detect_ds4(),
    }
    return engines


__all__ = ["EngineStatus", "detect_engines", "PROBE_TIMEOUT"]
