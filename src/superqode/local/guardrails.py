"""Conservative local-runtime guardrails for on-device model runs."""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .hardware import HardwareProfile, detect_hardware
from .repo import RepoProfile


@dataclass(frozen=True)
class PowerState:
    on_battery: bool | None = None
    source: str = "unknown"
    detail: str = ""


@dataclass(frozen=True)
class LoadState:
    load_1m: float | None = None
    cpu_count: int = 0

    @property
    def normalized_1m(self) -> float | None:
        if self.load_1m is None or self.cpu_count <= 0:
            return None
        return round(self.load_1m / self.cpu_count, 2)


@dataclass(frozen=True)
class LocalGuardrails:
    hardware_tier: str
    max_worker_concurrency: int
    recommended_context_cap: int
    memory_headroom_gb: int
    battery_mode: str
    power: PowerState = field(default_factory=PowerState)
    load: LoadState = field(default_factory=LoadState)
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "hardware_tier": self.hardware_tier,
            "max_worker_concurrency": self.max_worker_concurrency,
            "recommended_context_cap": self.recommended_context_cap,
            "memory_headroom_gb": self.memory_headroom_gb,
            "battery_mode": self.battery_mode,
            "power": {
                "on_battery": self.power.on_battery,
                "source": self.power.source,
                "detail": self.power.detail,
            },
            "load": {
                "load_1m": self.load.load_1m,
                "cpu_count": self.load.cpu_count,
                "normalized_1m": self.load.normalized_1m,
            },
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }


def build_guardrails(
    hardware: HardwareProfile | None = None,
    *,
    repo_profile: RepoProfile | None = None,
) -> LocalGuardrails:
    """Derive conservative run limits for local model execution."""
    hw = hardware or detect_hardware()
    power = detect_power_state()
    load = detect_load_state()
    concurrency = _base_concurrency(hw)
    context_cap = _context_cap(hw)
    headroom = _memory_headroom(hw)
    warnings: list[str] = []
    notes: list[str] = []

    if power.on_battery:
        concurrency = min(concurrency, 1)
        context_cap = min(context_cap, 32768)
        warnings.append("Running on battery; use one worker and avoid maximum context.")
    elif power.on_battery is None:
        notes.append("Power source could not be detected; using conservative defaults.")

    normalized = load.normalized_1m
    if normalized is not None and normalized >= 0.9:
        concurrency = min(concurrency, 1)
        warnings.append("System load is already high; avoid concurrent local model runs.")

    if repo_profile is not None:
        context_cap = min(context_cap, repo_profile.recommended_context_tokens)
        if repo_profile.recommended_context_tokens > context_cap:
            warnings.append("Repository context need exceeds guardrail cap; use focused reads.")
        if repo_profile.recommended_model_size in {"medium-large", "large"} and concurrency > 1:
            concurrency = max(1, concurrency - 1)
            notes.append("Large repository profile reduced recommended worker concurrency.")

    if hw.tier in {"cpu", "apple_16", "nvidia_16"}:
        notes.append("Small hardware tier: prefer prompt tool-calling and smaller quantized models.")
    if hw.tier in {"apple_128", "nvidia_48"}:
        notes.append("High-memory tier: concurrent utility and reviewer roles are reasonable on AC power.")

    return LocalGuardrails(
        hardware_tier=hw.tier,
        max_worker_concurrency=max(1, concurrency),
        recommended_context_cap=context_cap,
        memory_headroom_gb=headroom,
        battery_mode="conservative" if power.on_battery else "normal",
        power=power,
        load=load,
        warnings=tuple(dict.fromkeys(warnings)),
        notes=tuple(dict.fromkeys(notes)),
    )


def detect_power_state() -> PowerState:
    system = platform.system().lower()
    if system == "darwin":
        return _detect_macos_power()
    if system == "linux":
        return _detect_linux_power()
    return PowerState()


def detect_load_state() -> LoadState:
    cpu_count = os.cpu_count() or 0
    try:
        load_1m = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        load_1m = None
    return LoadState(load_1m=load_1m, cpu_count=cpu_count)


def render_guardrails(guardrails: LocalGuardrails) -> str:
    lines = ["SuperQode Local Runtime Guardrails", "=" * 60]
    lines.append(f"Tier          {guardrails.hardware_tier}")
    lines.append(f"Concurrency   {guardrails.max_worker_concurrency}")
    lines.append(f"Context cap   {guardrails.recommended_context_cap:,} tokens")
    lines.append(f"Headroom      {guardrails.memory_headroom_gb}GB memory/VRAM")
    lines.append(f"Battery mode  {guardrails.battery_mode}")
    if guardrails.power.detail:
        lines.append(f"Power         {guardrails.power.detail}")
    if guardrails.load.load_1m is not None:
        norm = guardrails.load.normalized_1m
        detail = f"{guardrails.load.load_1m}"
        if norm is not None:
            detail += f" ({norm} per CPU)"
        lines.append(f"Load          {detail}")
    if guardrails.warnings:
        lines.append("")
        lines.append("Warnings")
        for warning in guardrails.warnings:
            lines.append(f"  - {warning}")
    if guardrails.notes:
        lines.append("")
        lines.append("Notes")
        for note in guardrails.notes:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def _detect_macos_power() -> PowerState:
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return PowerState()
    if out.returncode != 0:
        return PowerState(source="pmset", detail=out.stderr.strip())
    text = out.stdout.strip()
    lowered = text.lower()
    if "battery power" in lowered:
        return PowerState(on_battery=True, source="pmset", detail="battery power")
    if "ac power" in lowered:
        return PowerState(on_battery=False, source="pmset", detail="AC power")
    return PowerState(source="pmset", detail=text.splitlines()[0] if text else "")


def _detect_linux_power() -> PowerState:
    base = Path("/sys/class/power_supply")
    try:
        supplies = list(base.iterdir())
    except OSError:
        return PowerState()
    battery_present = False
    online_values: list[str] = []
    for supply in supplies:
        try:
            supply_type = (supply / "type").read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if supply_type == "battery":
            battery_present = True
        if supply_type in {"mains", "usb", "usb_c"}:
            try:
                online_values.append((supply / "online").read_text(encoding="utf-8").strip())
            except OSError:
                continue
    if online_values:
        on_ac = any(value == "1" for value in online_values)
        return PowerState(
            on_battery=not on_ac,
            source="sysfs",
            detail="AC power" if on_ac else "battery power",
        )
    if battery_present:
        return PowerState(on_battery=True, source="sysfs", detail="battery present")
    return PowerState(on_battery=False, source="sysfs", detail="no battery detected")


def _base_concurrency(hw: HardwareProfile) -> int:
    return {
        "cpu": 1,
        "apple_16": 1,
        "apple_32": 1,
        "apple_64": 2,
        "apple_128": 3,
        "nvidia_16": 1,
        "nvidia_24": 2,
        "nvidia_48": 4,
    }.get(hw.tier, 1)


def _context_cap(hw: HardwareProfile) -> int:
    return {
        "cpu": 8192,
        "apple_16": 16384,
        "apple_32": 32768,
        "apple_64": 65536,
        "apple_128": 131072,
        "nvidia_16": 32768,
        "nvidia_24": 65536,
        "nvidia_48": 131072,
    }.get(hw.tier, 16384)


def _memory_headroom(hw: HardwareProfile) -> int:
    return {
        "cpu": 4,
        "apple_16": 6,
        "apple_32": 8,
        "apple_64": 12,
        "apple_128": 16,
        "nvidia_16": 4,
        "nvidia_24": 6,
        "nvidia_48": 10,
    }.get(hw.tier, 6)


__all__ = [
    "LoadState",
    "LocalGuardrails",
    "PowerState",
    "build_guardrails",
    "detect_load_state",
    "detect_power_state",
    "render_guardrails",
]
