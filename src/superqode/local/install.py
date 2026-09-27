"""Platform-aware runtime installation shared by the CLI and TUI.

Plans are read-only. Only an explicit install action executes their argv steps;
model weights and inference are never part of a runtime installation.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ENGINES = ("ollama", "lmstudio", "llama.cpp", "sglang", "vllm", "mlx")
NAMES = dict(zip(ENGINES, ("Ollama", "LM Studio", "llama.cpp", "SGLang", "vLLM", "MLX")))
DOCS = {
    "ollama": "https://ollama.com/download",
    "lmstudio": "https://lmstudio.ai/docs/developer/core/headless",
    "llama.cpp": "https://github.com/ggml-org/llama.cpp/blob/master/docs/install.md",
    "sglang": "https://docs.sglang.io/docs/get-started/install",
    "vllm": "https://docs.vllm.ai/en/stable/getting_started/installation/",
    "mlx": "https://github.com/ml-explore/mlx-lm",
}


def normalize_engine(engine: str) -> str:
    return {"llamacpp": "llama.cpp", "mlx-lm": "mlx"}.get(engine, engine)


def runtime_executable(name: str) -> str:
    """Find newly installed tools even before the user restarts their shell."""
    if shutil.which(name):
        return name
    for directory in (
        Path.home() / ".lmstudio/bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ):
        path = directory / name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return name


def runtime_python(engine: str) -> Path:
    return Path.home() / ".superqode" / "runtimes" / engine / "bin" / "python"


def runtime_installed(engine: str) -> bool:
    engine = normalize_engine(engine)
    binary = {"ollama": "ollama", "lmstudio": "lms", "llama.cpp": "llama-server"}.get(engine)
    if binary:
        resolved = runtime_executable(binary)
        return bool(shutil.which(resolved))
    if engine in ("sglang", "vllm"):
        python = runtime_python(engine)
        if python.is_file():
            try:
                result = subprocess.run(
                    [
                        str(python),
                        "-c",
                        f"import importlib.util; raise SystemExit(importlib.util.find_spec('{engine}') is None)",
                    ],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                return result.returncode == 0
            except (OSError, subprocess.SubprocessError):
                return False
    module = {"mlx": "mlx_lm", "sglang": "sglang", "vllm": "vllm"}.get(engine)
    return bool(module and importlib.util.find_spec(module))


@dataclass(frozen=True)
class InstallPlan:
    engine: str
    title: str
    steps: tuple[tuple[str, ...], ...]
    guidance: str
    docs_url: str
    manual_command: str = ""

    @property
    def command(self) -> str:
        return " && ".join(shlex.join(step) for step in self.steps) or self.manual_command

    def to_dict(self) -> dict:
        return {**asdict(self), "command": self.command, "automatic": bool(self.steps)}


def install_plan(engine: str) -> InstallPlan:
    engine = normalize_engine(engine)
    if engine not in ENGINES:
        raise ValueError(f"Choose a runtime: {', '.join(ENGINES)}")
    system = sys.platform
    steps: tuple[tuple[str, ...], ...] = ()
    manual_command = ""
    guidance = "Use the vendor installer for this platform, then choose Check again."
    brew = shutil.which("brew")
    if engine in ("ollama", "llama.cpp") and brew and system in ("darwin", "linux"):
        steps = ((brew, "install", "ollama" if engine == "ollama" else "llama.cpp"),)
        guidance = "Installs the runtime through Homebrew. Model weights are a separate download."
    elif engine == "ollama" and system == "linux":
        guidance = "Run in a terminal (the vendor installer may request sudo): curl -fsSL https://ollama.com/install.sh | sh"
        manual_command = "curl -fsSL https://ollama.com/install.sh | sh"
    elif engine == "lmstudio" and system in ("darwin", "linux"):
        if shutil.which("curl") and shutil.which("bash"):
            steps = (
                (
                    "bash",
                    "-o",
                    "pipefail",
                    "-c",
                    "curl -fsSL https://lmstudio.ai/install.sh | bash",
                ),
            )
        guidance = "Installs the official headless LM Studio daemon and lms CLI. The desktop app is optional."
    elif engine == "mlx":
        if system == "darwin" and platform.machine() == "arm64":
            from .servers import mlx_install_command

            steps = (tuple(shlex.split(mlx_install_command())),)
            guidance = "Installs mlx-lm into SuperQode's active Python environment."
        else:
            guidance = "MLX requires Apple Silicon on macOS. Choose Ollama or llama.cpp on this machine, or connect to an existing MLX server."
    elif engine in ("sglang", "vllm"):
        guidance = "Choose the vendor's installation for your accelerator (NVIDIA, AMD, CPU, or other supported hardware). You can also connect to an existing server without installing locally."
        if system == "linux" and shutil.which("nvidia-smi") and not shutil.which("uv"):
            guidance += " For automatic isolated installation, first install uv: https://docs.astral.sh/uv/getting-started/installation/ then check again."
        if system == "linux" and shutil.which("nvidia-smi") and shutil.which("uv"):
            target = runtime_python(engine)
            steps = (
                ("uv", "venv", "--python", "3.12", "--allow-existing", str(target.parent.parent)),
                (
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(target),
                    *(["--prerelease=allow"] if engine == "sglang" else []),
                    engine,
                ),
            )
            guidance = "Installs the NVIDIA runtime in its own environment under ~/.superqode/runtimes. Check the vendor guide for compatible GPU drivers; other accelerators need their vendor-specific install."
    return InstallPlan(engine, NAMES[engine], steps, guidance, DOCS[engine], manual_command)


def next_steps(engine: str) -> list[str]:
    """Copyable next actions; placeholders are intentionally not executed."""
    engine = normalize_engine(engine)
    if engine in ("sglang", "vllm"):
        python = runtime_python(engine)
        executable = str(python) if python.is_file() else sys.executable
        prefix = shlex.quote(executable)
        serve = (
            f"{prefix} -m sglang.launch_server --model-path <model-id-or-local-path> --host 127.0.0.1 --port 30000 --tool-call-parser <parser>"
            if engine == "sglang"
            else f"{prefix} -m vllm.entrypoints.openai.api_server --model <model-id-or-local-path> --host 127.0.0.1 --port 8000 --enable-auto-tool-choice --tool-call-parser <parser>"
        )
        return [
            serve,
            "Choose the tool parser for your model: "
            + (
                "https://docs.sglang.io/docs/advanced_features/tool_parser"
                if engine == "sglang"
                else "https://docs.vllm.ai/en/stable/features/tool_calling/"
            ),
            "superqode",
            f":connect local {engine}/<model-id>",
            ":build",
        ]
    start = f"superqode local serve {engine}"
    if engine in ("mlx", "llama.cpp"):
        start += " --model <local-model-path>"
    model_step = {
        "ollama": "ollama pull <model-name>",
        "lmstudio": "lms get <model-name>   (or use a model already downloaded in LM Studio)",
        "llama.cpp": "Choose a downloaded GGUF file, or find one with: superqode local search <model-name> --hub --gguf",
        "mlx": "Choose a cached MLX model, or find one with: superqode local search <model-name> --hub",
    }[engine]
    provider = "llamacpp" if engine == "llama.cpp" else engine
    steps = [start, model_step] if engine == "ollama" else [model_step, start]
    if engine == "lmstudio":
        lms = shlex.quote(runtime_executable("lms"))
        steps = [
            f"{lms} daemon up",
            f"{lms} get <model-name>",
            start,
            f"{lms} load <model-key> --context-length <tokens>",
        ]
    return [*steps, "superqode", f":connect local {provider}", ":build"]
