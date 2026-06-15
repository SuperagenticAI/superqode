"""Hardware detection for local inference recommendations.

Detects the three things that decide what a machine can run well:

- Apple Silicon generation and unified memory (the budget for MLX/Ollama)
- NVIDIA GPUs and VRAM (the budget for vLLM/SGLang/llama.cpp CUDA)
- macOS version, because M5 Neural Accelerators need macOS 26.2+

Everything degrades gracefully: detection failures produce ``None`` fields
and a conservative tier, never an exception.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

_APPLE_GEN_RE = re.compile(r"\bM(\d+)\b")


@dataclass
class NvidiaGpu:
    name: str
    vram_gb: float


@dataclass
class HardwareProfile:
    platform: str  # darwin | linux | windows
    is_apple_silicon: bool = False
    chip: str = ""
    apple_generation: Optional[int] = None
    unified_memory_gb: Optional[int] = None
    macos_version: str = ""
    neural_accelerators: bool = False  # M5+ on macOS 26.2+
    nvidia_gpus: List[NvidiaGpu] = field(default_factory=list)
    cpu_only: bool = False

    @property
    def total_vram_gb(self) -> float:
        return round(sum(g.vram_gb for g in self.nvidia_gpus), 1)

    @property
    def available_memory_gb(self) -> Optional[float]:
        """Rough memory budget a local model must fit in.

        Apple Silicon shares unified memory with the OS; NVIDIA is bounded by
        VRAM; CPU-only falls back to system RAM.
        """
        if self.is_apple_silicon and self.unified_memory_gb:
            return float(self.unified_memory_gb)
        if self.nvidia_gpus:
            return self.total_vram_gb
        return _total_memory_gb()

    @property
    def tier(self) -> str:
        """Coarse tier used by the recommendation matrix."""
        if self.is_apple_silicon and self.unified_memory_gb:
            mem = self.unified_memory_gb
            if mem >= 96:
                return "apple_128"
            if mem >= 56:
                return "apple_64"
            if mem >= 30:
                return "apple_32"
            return "apple_16"
        if self.nvidia_gpus:
            vram = self.total_vram_gb
            if vram >= 40:
                return "nvidia_48"
            if vram >= 20:
                return "nvidia_24"
            return "nvidia_16"
        return "cpu"


def _sysctl(name: str) -> str:
    try:
        out = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=3)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _total_memory_gb() -> Optional[int]:
    # POSIX-portable; works on macOS and Linux.
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        phys_pages = int(os.sysconf("SC_PHYS_PAGES"))
        return int((page_size * phys_pages) / (1024**3))
    except (AttributeError, OSError, ValueError):
        return None


def _detect_nvidia() -> List[NvidiaGpu]:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    gpus: List[NvidiaGpu] = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            try:
                gpus.append(NvidiaGpu(name=parts[0], vram_gb=round(float(parts[1]) / 1024, 1)))
            except ValueError:
                continue
    return gpus


def _macos_supports_neural_accelerators(version: str) -> bool:
    try:
        parts = [int(p) for p in version.split(".")[:2]]
        major = parts[0]
        minor = parts[1] if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return False
    return (major, minor) >= (26, 2)


def detect_hardware() -> HardwareProfile:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        chip = _sysctl("machdep.cpu.brand_string")
        is_as = machine == "arm64" or "apple" in chip.lower()
        generation: Optional[int] = None
        match = _APPLE_GEN_RE.search(chip)
        if match:
            try:
                generation = int(match.group(1))
            except ValueError:
                generation = None
        macos_version = platform.mac_ver()[0] or ""
        return HardwareProfile(
            platform="darwin",
            is_apple_silicon=is_as,
            chip=chip,
            apple_generation=generation,
            unified_memory_gb=_total_memory_gb(),
            macos_version=macos_version,
            neural_accelerators=bool(
                is_as
                and generation
                and generation >= 5
                and _macos_supports_neural_accelerators(macos_version)
            ),
            cpu_only=not is_as,
        )

    gpus = _detect_nvidia()
    return HardwareProfile(
        platform=system if system in ("linux", "windows") else "linux",
        unified_memory_gb=_total_memory_gb(),
        nvidia_gpus=gpus,
        cpu_only=not gpus,
    )


__all__ = ["HardwareProfile", "NvidiaGpu", "detect_hardware"]
