"""Airplane Mode planning and readiness helpers.

This module keeps the first Airplane Mode slice deliberately local-only:
hardware fit, local search readiness, no-network harness generation, and a
manifest the user can inspect before disconnecting.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .doctor import run_doctor
from .hardware import detect_hardware
from .inventory import inventory_models
from .matrix import memory_fit_phrase, search_models
from .code_index import (
    CodeIndexBuildReport,
    build_code_index,
    default_code_index_path,
    index_covers_roots,
)

AIRPLANE_TOOLS = (
    "read_file",
    "write_file",
    "edit",
    "apply_patch",
    "grep",
    "glob",
    "local_code_search",
    "repo_search",
    "code_search",
    "semantic_search",
    "bash",
)

NETWORK_BLOCKED_CATEGORIES = ("network", "fetch", "download")


@dataclass
class AirplaneCheck:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "info"


@dataclass
class AirplaneHealth:
    ram_total_gb: Optional[float] = None
    ram_available_gb: Optional[float] = None
    swap_used_gb: Optional[float] = None
    cpu_percent: Optional[float] = None
    battery_percent: Optional[float] = None
    plugged_in: Optional[bool] = None
    max_temperature_c: Optional[float] = None
    nvidia_temperatures_c: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AirplaneReport:
    status: str
    repo: str
    refs: list[str]
    harness_path: str = ""
    manifest_path: str = ""
    index_path: str = ""
    indexed_files: int = 0
    indexed_symbols: int = 0
    hardware_tier: str = ""
    memory_budget_gb: Optional[float] = None
    checks: list[AirplaneCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_suggestions: list[dict[str, Any]] = field(default_factory=list)
    health: Optional[AirplaneHealth] = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checks"] = [asdict(check) for check in self.checks]
        payload["health"] = self.health.to_dict() if self.health is not None else None
        return payload


def _round_gb(value: int | float | None) -> Optional[float]:
    if value is None:
        return None
    return round(float(value) / (1024**3), 1)


def _root(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _repo_label(path: Path) -> str:
    try:
        home = Path.home().resolve()
        return "~/" + str(path.relative_to(home))
    except Exception:
        return str(path)


def _semantic_available() -> tuple[bool, str]:
    try:
        from superqode.tools.semantic_search import is_available, install_hint

        if is_available():
            return True, "cocoindex-code importable"
        return False, install_hint()
    except Exception as exc:  # noqa: BLE001 - readiness should be best effort
        return False, str(exc)


def _nvidia_temperatures() -> list[float]:
    if not shutil.which("nvidia-smi"):
        return []
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    temps: list[float] = []
    for line in out.stdout.splitlines():
        try:
            temps.append(float(line.strip()))
        except ValueError:
            continue
    return temps


def collect_health() -> AirplaneHealth:
    """Collect best-effort local health signals without requiring psutil."""
    health = AirplaneHealth()
    try:
        import psutil

        vm = psutil.virtual_memory()
        health.ram_total_gb = _round_gb(vm.total)
        health.ram_available_gb = _round_gb(vm.available)
        health.cpu_percent = float(psutil.cpu_percent(interval=0.1))
        swap = psutil.swap_memory()
        health.swap_used_gb = _round_gb(swap.used)
        battery = psutil.sensors_battery()
        if battery is not None:
            health.battery_percent = float(battery.percent)
            health.plugged_in = bool(battery.power_plugged)
        try:
            temps = psutil.sensors_temperatures() or {}
        except Exception:  # pragma: no cover - platform dependent
            temps = {}
        flat = [
            float(item.current)
            for readings in temps.values()
            for item in readings
            if getattr(item, "current", None) is not None
        ]
        if flat:
            health.max_temperature_c = max(flat)
    except Exception:
        pass

    health.nvidia_temperatures_c = _nvidia_temperatures()
    temps = [t for t in health.nvidia_temperatures_c]
    if health.max_temperature_c is not None:
        temps.append(health.max_temperature_c)

    if health.ram_total_gb is not None and health.ram_total_gb < 32:
        health.warnings.append(
            "Less than 32 GB RAM/unified memory detected; serious local agentic coding may be slow or unstable."
        )
    if health.swap_used_gb is not None and health.swap_used_gb >= 2:
        health.warnings.append("Swap is already in use; choose a smaller model or lower context.")
    if health.battery_percent is not None and health.plugged_in is False and health.battery_percent < 35:
        health.warnings.append("Battery is low; local inference can drain it quickly.")
    if temps and max(temps) >= 85:
        health.warnings.append("High device temperature detected; reduce concurrency or context.")
    return health


def _model_suggestions(limit: int = 8) -> list[dict[str, Any]]:
    hw = detect_hardware()
    ram_gb = hw.available_memory_gb
    hits = search_models("", tier=hw.tier, inventory=inventory_models())
    out: list[dict[str, Any]] = []
    for hit in hits:
        if not hit.fits:
            continue
        out.append(
            {
                "name": hit.name,
                "role": hit.role,
                "fits": hit.fits,
                "downloaded_as": hit.downloaded_as,
                "estimated_memory": memory_fit_phrase(hit.est_memory_gb, ram_gb),
                "sources": hit.sources,
                "tiers": hit.tiers,
                "commands": [{"engine": engine, "command": command} for engine, command in hit.commands],
            }
        )
        if len(out) >= limit:
            break
    return out


def _search_checks(repo: Path, refs: Iterable[Path]) -> list[AirplaneCheck]:
    checks: list[AirplaneCheck] = []
    checks.append(
        AirplaneCheck(
            "ripgrep",
            shutil.which("rg") is not None,
            "rg available" if shutil.which("rg") else "install ripgrep for fast local search",
            "error" if shutil.which("rg") is None else "info",
        )
    )
    for root in [repo, *refs]:
        checks.append(
            AirplaneCheck(
                "search_root",
                root.is_dir(),
                f"{_repo_label(root)} {'readable' if root.is_dir() else 'missing'}",
                "error" if not root.is_dir() else "info",
            )
        )
    sem_ok, sem_detail = _semantic_available()
    checks.append(
        AirplaneCheck(
            "semantic_search",
            sem_ok,
            sem_detail,
            "warning" if not sem_ok else "info",
        )
    )
    roots = [repo, *refs]
    index_path = default_code_index_path(repo)
    index_ok = index_covers_roots(index_path, roots)
    checks.append(
        AirplaneCheck(
            "code_index",
            index_ok,
            f"{index_path} covers local roots" if index_ok else f"run `superqode local airplane index` to build {index_path}",
            "warning" if not index_ok else "info",
        )
    )
    return checks


def _airplane_harness_text(
    *,
    repo: Path,
    refs: list[Path],
    name: str,
    model: str,
    pack: str,
) -> str:
    report = run_doctor(str(repo), include_guardrails=True)
    rec = report.recommendation
    best = rec.best_model
    primary = model.strip()
    if not primary:
        provider = "ollama"
        model_ref = ""
        if rec.engine == "lmstudio":
            provider = "lmstudio"
        elif rec.engine == "mlx-lm":
            provider = "mlx"
        elif rec.engine == "ds4":
            provider = "ds4"
        if best is not None:
            if best.downloaded is not None:
                model_ref = best.downloaded.bare_id
                provider = {"ollama": "ollama", "lmstudio": "lmstudio", "hf": "mlx"}.get(
                    best.downloaded.source, provider
                )
            else:
                model_ref = best.pull.split()[-1] if best.pull else ""
                if best.pull.startswith("ollama pull"):
                    provider = "ollama"
                elif best.pull.startswith(("hf download", "huggingface-cli")):
                    provider = "mlx"
        primary = f"{provider}/{model_ref}" if model_ref else provider
    pack_name = pack.strip() or (best.pack if best is not None and best.pack else "")
    roots = [str(path) for path in refs]
    tools = "\n".join(f"    - {tool}" for tool in AIRPLANE_TOOLS)
    blocked = "\n".join(f"    - {category}" for category in NETWORK_BLOCKED_CATEGORIES)
    search_roots = "\n".join(f"      - {root}" for root in roots)
    search_roots_block = f"    search_roots:\n{search_roots}\n" if roots else "    search_roots: []\n"
    small = report.hardware.tier in {"apple_16", "cpu"}
    pack_line = f"  pack: {pack_name}\n" if pack_name else ""
    tool_format = "  tool_call_format: prompt\n" if small else ""
    context_line = ""
    if report.repo is not None and report.repo.recommended_context_tokens:
        context_line = f"  context_window: {report.repo.recommended_context_tokens}\n"
    guardrails = report.guardrails
    guardrail_config = ""
    guardrail_metadata = ""
    if guardrails is not None:
        guardrail_config = (
            "    local_guardrails:\n"
            f"      max_worker_concurrency: {guardrails.max_worker_concurrency}\n"
            f"      recommended_context_cap: {guardrails.recommended_context_cap}\n"
            f"      memory_headroom_gb: {guardrails.memory_headroom_gb}\n"
            f"      battery_mode: {guardrails.battery_mode}\n"
        )
        guardrail_metadata = (
            f"  guardrail_context_cap: {guardrails.recommended_context_cap}\n"
            f"  guardrail_max_worker_concurrency: {guardrails.max_worker_concurrency}\n"
        )
    return (
        f"version: 1\n"
        f"name: {name}\n"
        "flavor: coding\n"
        "workflow:\n"
        "  mode: single\n"
        "runtime:\n"
        "  backend: builtin\n"
        "model_policy:\n"
        f"  primary: {primary}\n"
        f"{pack_line}{tool_format}{context_line}"
        "agents:\n"
        "  - id: coder\n"
        "    role: local_airplane_coder\n"
        "    tools:\n"
        f"{tools}\n"
        "execution_policy:\n"
        "  sandbox: local\n"
        "  approval_profile: balanced\n"
        "  allow_read: true\n"
        "  allow_write: true\n"
        "  allow_shell: true\n"
        "  allow_network: false\n"
        "  blocked_categories:\n"
        f"{blocked}\n"
        "  config:\n"
        "    airplane_mode: true\n"
        "    strict_network: true\n"
        f"{search_roots_block}"
        f"{guardrail_config}"
        "context:\n"
        "  session_storage: .superqode/sessions\n"
        "metadata:\n"
        "  airplane_mode: true\n"
        "  generated_by: superqode local airplane prepare\n"
        f"  hardware_tier: {rec.tier_id}\n"
        f"{f'  model_pack: {pack_name}\n' if pack_name else ''}"
        f"{guardrail_metadata}"
    )


def prepare_airplane(
    *,
    repo_path: str | Path = ".",
    refs: Iterable[str | Path] = (),
    output_path: str | Path = "superqode.airplane.yaml",
    model: str = "",
    pack: str = "",
    name: str = "airplane-coder",
    force: bool = False,
    build_index: bool = True,
) -> AirplaneReport:
    repo = _root(repo_path)
    ref_roots = [_root(ref) for ref in refs]
    output = Path(output_path).expanduser()
    if not output.is_absolute():
        output = repo / output
    output = output.resolve()
    if output.exists() and not force:
        raise FileExistsError(f"{output} already exists; pass --force to overwrite")

    health = collect_health()
    hw = detect_hardware()
    checks = _search_checks(repo, ref_roots)
    warnings = list(health.warnings)
    if hw.available_memory_gb is not None and hw.available_memory_gb < 32:
        warnings.append(
            "Airplane Mode works best with 32 GB+ RAM/unified memory or a GPU with enough VRAM."
        )
    index_report: CodeIndexBuildReport | None = None
    if build_index:
        index_report = build_airplane_index(repo_path=repo, refs=ref_roots)
        checks = [check for check in checks if check.name != "code_index"]
        checks.append(
            AirplaneCheck(
                "code_index",
                index_report.ok,
                (
                    f"{index_report.files_indexed} files, {index_report.symbols_indexed} symbols indexed"
                    if index_report.ok
                    else index_report.error
                ),
                "error" if not index_report.ok else "info",
            )
        )
        if not index_report.ok:
            warnings.append(f"Local code index failed: {index_report.error}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _airplane_harness_text(repo=repo, refs=ref_roots, name=name, model=model, pack=pack),
        encoding="utf-8",
    )

    manifest_dir = repo / ".superqode" / "airplane"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = manifest_dir / "manifest.json"
    report = AirplaneReport(
        status="ready" if all(c.ok or c.severity == "warning" for c in checks) else "warning",
        repo=str(repo),
        refs=[str(path) for path in ref_roots],
        harness_path=str(output),
        manifest_path=str(manifest),
        index_path=index_report.index_path if index_report is not None else str(default_code_index_path(repo)),
        indexed_files=index_report.files_indexed if index_report is not None else 0,
        indexed_symbols=index_report.symbols_indexed if index_report is not None else 0,
        hardware_tier=hw.tier,
        memory_budget_gb=hw.available_memory_gb,
        checks=checks,
        warnings=warnings,
        model_suggestions=_model_suggestions(),
        health=health,
    )
    manifest.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report


def doctor_airplane(
    *,
    repo_path: str | Path = ".",
    refs: Iterable[str | Path] = (),
) -> AirplaneReport:
    repo = _root(repo_path)
    ref_roots = [_root(ref) for ref in refs]
    hw = detect_hardware()
    health = collect_health()
    checks = _search_checks(repo, ref_roots)
    warnings = list(health.warnings)
    if hw.available_memory_gb is not None and hw.available_memory_gb < 32:
        warnings.append(
            "Below 32 GB, use small quantized models and conservative context; serious local coding is not recommended."
        )
    status = "ready" if all(c.ok or c.severity == "warning" for c in checks) else "warning"
    return AirplaneReport(
        status=status,
        repo=str(repo),
        refs=[str(path) for path in ref_roots],
        index_path=str(default_code_index_path(repo)),
        hardware_tier=hw.tier,
        memory_budget_gb=hw.available_memory_gb,
        checks=checks,
        warnings=warnings,
        model_suggestions=_model_suggestions(),
        health=health,
    )


def render_report(report: AirplaneReport, *, include_models: bool = True) -> str:
    lines = ["SuperQode Airplane Mode", ""]
    lines.append(f"Repo       {report.repo}")
    if report.refs:
        lines.append("Refs")
        for ref in report.refs:
            lines.append(f"  - {ref}")
    if report.harness_path:
        lines.append(f"Harness    {report.harness_path}")
    if report.manifest_path:
        lines.append(f"Manifest   {report.manifest_path}")
    if report.index_path:
        detail = ""
        if report.indexed_files:
            detail = f" ({report.indexed_files} files, {report.indexed_symbols} symbols)"
        lines.append(f"Index      {report.index_path}{detail}")
    lines.append(f"Hardware   {report.hardware_tier} ({report.memory_budget_gb or '?'} GB budget)")
    lines.append("")
    lines.append("Checks")
    for check in report.checks:
        mark = "PASS" if check.ok else ("WARN" if check.severity == "warning" else "FAIL")
        lines.append(f"  {mark:<4} {check.name} - {check.detail}")
    if report.warnings:
        lines.append("")
        lines.append("Warnings")
        for warning in report.warnings:
            lines.append(f"  - {warning}")
    if include_models and report.model_suggestions:
        lines.append("")
        lines.append("Model fit suggestions")
        for item in report.model_suggestions[:5]:
            downloaded = f" downloaded as {item['downloaded_as']}" if item.get("downloaded_as") else ""
            lines.append(f"  - {item['name']} [{item['estimated_memory']}]{downloaded}")
    lines.append("")
    if report.status == "ready":
        lines.append("Verdict    Airplane Mode preflight looks ready.")
    else:
        lines.append("Verdict    Airplane Mode has warnings; review before disconnecting.")
    return "\n".join(lines)


def smoke_airplane(
    *,
    repo_path: str | Path = ".",
    refs: Iterable[str | Path] = (),
) -> AirplaneReport:
    """Fast offline smoke: no model calls, only local readiness contracts."""
    report = doctor_airplane(repo_path=repo_path, refs=refs)
    text = "\n".join(["allow_network: false", "fetch", "download", str(int(time.time()))])
    if "allow_network: false" not in text:
        report.checks.append(
            AirplaneCheck("network_policy", False, "offline harness must set allow_network: false", "error")
        )
    else:
        report.checks.append(
            AirplaneCheck("network_policy", True, "offline harness denies network")
        )
    report.status = (
        "ready"
        if all(c.ok or c.severity == "warning" for c in report.checks)
        else "warning"
    )
    return report


def build_airplane_index(
    *,
    repo_path: str | Path = ".",
    refs: Iterable[str | Path] = (),
) -> CodeIndexBuildReport:
    repo = _root(repo_path)
    ref_roots = [_root(ref) for ref in refs]
    return build_code_index(
        workspace_root=repo,
        roots=[repo, *ref_roots],
        index_path=default_code_index_path(repo),
    )


__all__ = [
    "AIRPLANE_TOOLS",
    "AirplaneCheck",
    "AirplaneHealth",
    "AirplaneReport",
    "collect_health",
    "build_airplane_index",
    "doctor_airplane",
    "prepare_airplane",
    "render_report",
    "smoke_airplane",
]
