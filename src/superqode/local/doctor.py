"""The Local Stack Doctor: from "this machine" to a tuned local agent.

``run_doctor()`` detects hardware, inventories engines and models, applies
the recommendation matrix, and can generate a harness spec tuned by the
matching model policy pack. ``render_report()`` produces the human view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .engines import EngineStatus, detect_engines
from .guardrails import LocalGuardrails, build_guardrails, render_guardrails
from .hardware import HardwareProfile, detect_hardware
from .inventory import LocalModel, inventory_models
from .matrix import StackRecommendation, load_matrix, recommend
from .repo import RepoProfile, analyze_repository, render_repo_profile


@dataclass
class DoctorReport:
    hardware: HardwareProfile
    engines: Dict[str, EngineStatus]
    inventory: List[LocalModel]
    recommendation: StackRecommendation
    matrix_version: str = ""
    apple_fm_available: Optional[bool] = None
    repo: Optional[RepoProfile] = None
    guardrails: Optional[LocalGuardrails] = None


def _detect_apple_fm(profile: HardwareProfile) -> Optional[bool]:
    """Is the on-device Apple Foundation Model usable as a utility model?"""
    if profile.platform != "darwin" or not profile.is_apple_silicon:
        return None
    try:
        from ..providers.apple_fm import apple_fm_available

        return apple_fm_available()
    except Exception:
        return None


def run_doctor(repo_path: str | None = None, *, include_guardrails: bool = False) -> DoctorReport:
    hardware = detect_hardware()
    engines = detect_engines(
        unified_memory_gb=hardware.unified_memory_gb,
        apple_silicon=hardware.is_apple_silicon,
    )
    inventory = inventory_models()
    matrix = load_matrix()
    recommendation = recommend(hardware, engines, inventory, matrix)
    repo = analyze_repository(repo_path) if repo_path else None
    return DoctorReport(
        hardware=hardware,
        engines=engines,
        inventory=inventory,
        recommendation=recommendation,
        matrix_version=str(matrix.get("version", "")),
        apple_fm_available=_detect_apple_fm(hardware),
        repo=repo,
        guardrails=build_guardrails(hardware, repo_profile=repo) if include_guardrails else None,
    )


def render_report(report: DoctorReport) -> str:
    hw = report.hardware
    rec = report.recommendation
    lines: List[str] = []

    lines.append("SuperQode Local Stack Doctor")
    lines.append("=" * 60)

    # Hardware
    if hw.is_apple_silicon:
        accel = " + Neural Accelerators" if hw.neural_accelerators else ""
        lines.append(
            f"Hardware   {hw.chip or 'Apple Silicon'}, "
            f"{hw.unified_memory_gb or '?'}GB unified memory"
            f" (macOS {hw.macos_version}{accel})"
        )
    elif hw.nvidia_gpus:
        gpus = ", ".join(f"{g.name} {g.vram_gb}GB" for g in hw.nvidia_gpus)
        lines.append(f"Hardware   {gpus} ({hw.total_vram_gb}GB VRAM total)")
    else:
        lines.append(f"Hardware   CPU only, {hw.unified_memory_gb or '?'}GB RAM")
    lines.append(f"Tier       {rec.tier_id}: {rec.description}")
    lines.append("")

    # Engines
    lines.append("Engines")
    for engine_id in rec.engine_ranked:
        status = report.engines.get(engine_id)
        if status is None:
            continue
        state = (
            "running" if status.running else ("installed" if status.installed else "not installed")
        )
        version = f" {status.version}" if status.version else ""
        marker = "*" if engine_id == rec.engine else " "
        lines.append(f"  {marker} {engine_id:<10} {state}{version}")
        for note in status.notes:
            lines.append(f"      - {note}")
    extra_running = [
        e for e, s in report.engines.items() if s.running and e not in rec.engine_ranked
    ]
    for engine_id in extra_running:
        lines.append(f"    {engine_id:<10} running (outside this tier's ranking)")
    lines.append("")

    # Models
    lines.append("Recommended models")
    for candidate in rec.models:
        source = f"  source: {candidate.source}" if candidate.source else ""
        if candidate.downloaded:
            where = candidate.downloaded.model_id
            size = f", {candidate.downloaded.size_gb}GB" if candidate.downloaded.size_gb else ""
            lines.append(
                f"  + {candidate.name} [{candidate.role}]  downloaded ({where}{size}){source}"
            )
        else:
            lines.append(
                f"  - {candidate.name} [{candidate.role}]  get it: {candidate.pull}{source}"
            )
    lines.append(f"  ({len(report.inventory)} local models found in total)")
    lines.append("")

    if report.apple_fm_available:
        lines.append("Apple Intelligence on-device model is available: a free utility model for")
        lines.append(
            "  graders, memory extraction, and summaries (SUPERQODE_UTILITY_PROVIDER=apple-fm)."
        )
        lines.append("")

    if report.repo is not None:
        lines.append(render_repo_profile(report.repo))
        lines.append("")

    if report.guardrails is not None:
        lines.append(render_guardrails(report.guardrails))
        lines.append("")

    # Verdict
    lines.append("Verdict")
    best = rec.best_model
    if rec.engine and best:
        ready = "ready now" if best.downloaded else f"after: {best.pull}"
        lines.append(f"  Engine {rec.engine} + {best.name} ({ready})")
        lines.append("  Generate a tuned harness: superqode local doctor --generate harness.yaml")
    elif rec.engine:
        lines.append(f"  Engine {rec.engine} is ready; pull one of the models above.")
    else:
        ranked = ", ".join(rec.engine_ranked) or "an inference engine"
        lines.append(f"  Install one of: {ranked}")
    for note in rec.notes:
        lines.append(f"  note: {note}")
    if report.matrix_version:
        lines.append("")
        lines.append(f"Matrix version: {report.matrix_version}")
    return "\n".join(lines)


def generate_harness_yaml(
    report: DoctorReport, name: str = "local-coder", *, minimal: bool = False
) -> str:
    """A tuned harness spec for the doctor's verdict."""
    rec = report.recommendation
    best = rec.best_model
    engine = rec.engine or (rec.engine_ranked[0] if rec.engine_ranked else "ollama")

    provider_for_engine = {
        "ollama": "ollama",
        "lmstudio": "lmstudio",
        "mlx-lm": "mlx",
        "llama.cpp": "openai_compatible",
        "vllm": "vllm",
        "sglang": "openai_compatible",
        "ds4": "ds4",
    }
    provider = provider_for_engine.get(engine, "ollama")

    model_ref = ""
    if best is not None:
        if best.downloaded is not None:
            model_ref = best.downloaded.bare_id
            # The provider must be able to serve the downloaded copy: an HF
            # cache model is served by mlx_lm.server, not by Ollama.
            provider = {"ollama": "ollama", "lmstudio": "lmstudio", "hf": "mlx"}.get(
                best.downloaded.source, provider
            )
        else:
            # Derive a sensible id from the pull command's last token, and
            # keep the provider consistent with where that pull lands.
            model_ref = best.pull.split()[-1] if best.pull else ""
            if best.pull.startswith("ollama pull"):
                provider = "ollama"
            elif "ds4" in best.pull:
                provider, model_ref = "ds4", "deepseek-v4-flash"
            elif best.pull.startswith(("hf download", "huggingface-cli")):
                provider = "mlx"
    primary = f"{provider}/{model_ref}" if model_ref else provider

    pack_line = f"  pack: {best.pack}\n" if best is not None and best.pack else ""
    small = report.hardware.tier in ("apple_16", "cpu")
    tool_format = "  tool_call_format: prompt\n" if small else ""
    repo = report.repo
    workflow_mode = "chain" if repo is not None and repo.workflow_shape != "single" else "single"
    workflow_preset = (
        repo.workflow_shape if repo is not None and repo.workflow_shape != "single" else ""
    )
    context_limit = repo.recommended_context_tokens if repo is not None else None
    context_line = f"  context_window: {context_limit}\n" if context_limit else ""
    repo_metadata = ""
    if repo is not None:
        repo_metadata = (
            f"  repo_model_size: {repo.recommended_model_size}\n"
            f"  repo_context_tokens: {repo.recommended_context_tokens}\n"
            f"  repo_workflow_shape: {repo.workflow_shape}\n"
        )
    guardrail_config = ""
    guardrail_metadata = ""
    if report.guardrails is not None:
        guardrails = report.guardrails
        guardrail_config = (
            "  config:\n"
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

    if minimal:
        header = f"version: 1\nname: {name}\ninherits: coding\n"
    else:
        header = f"version: 1\nname: {name}\nflavor: coding\n"
    if minimal:
        return (
            header + "workflow:\n"
            f"  mode: {workflow_mode}\n"
            f"{f'  preset: {workflow_preset}\n' if workflow_preset else ''}"
            "model_policy:\n"
            f"  primary: {primary}\n"
            f"{pack_line}{tool_format}{context_line}"
            f"{'execution_policy:\n' + guardrail_config if guardrail_config else ''}"
            "metadata:\n"
            f"  generated_by: superqode local doctor\n"
            f"  hardware_tier: {rec.tier_id}\n"
            f"{repo_metadata}"
            f"{guardrail_metadata}"
        )

    return (
        header + "workflow:\n"
        f"  mode: {workflow_mode}\n"
        f"{f'  preset: {workflow_preset}\n' if workflow_preset else ''}"
        "runtime:\n"
        "  backend: builtin\n"
        "model_policy:\n"
        f"  primary: {primary}\n"
        f"{pack_line}{tool_format}{context_line}"
        "execution_policy:\n"
        "  sandbox: local\n"
        "  approval_profile: balanced\n"
        "  allow_write: true\n"
        "  allow_shell: true\n"
        f"{guardrail_config}"
        "context:\n"
        "  session_storage: .superqode/sessions\n"
        f"metadata:\n"
        f"  generated_by: superqode local doctor\n"
        f"  hardware_tier: {rec.tier_id}\n"
        f"{repo_metadata}"
        f"{guardrail_metadata}"
    )


__all__ = ["DoctorReport", "generate_harness_yaml", "render_report", "run_doctor"]
