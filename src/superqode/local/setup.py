"""Guided first-run flow for local model download, serving, and harness setup."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .doctor import DoctorReport, run_doctor
from .matrix import ModelSearchHit, search_models
from .servers import DS4_DEFAULT_CTX


@dataclass(frozen=True)
class LocalSetupGuide:
    """A non-mutating setup plan for local model users."""

    query: str
    repo: str
    report: DoctorReport
    hits: list[ModelSearchHit] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        rec = self.report.recommendation
        best = rec.best_model
        repo_profile = self.report.repo
        guardrails = self.report.guardrails
        return {
            "query": self.query,
            "repo": self.repo,
            "tier": rec.tier_id,
            "engine": rec.engine,
            "recommended_model": best.name if best else "",
            "recommended_pull": best.pull if best and not best.downloaded else "",
            "downloaded_model": best.downloaded.bare_id if best and best.downloaded else "",
            "repo_context_tokens": (
                repo_profile.recommended_context_tokens if repo_profile is not None else None
            ),
            "context_cap": (
                guardrails.recommended_context_cap if guardrails is not None else None
            ),
            "hits": [hit.to_dict() for hit in self.hits],
        }


def build_local_setup_guide(query: str = "", *, repo_path: str | Path = ".") -> LocalSetupGuide:
    """Build a setup guide without downloading models or starting servers."""

    repo = str(repo_path or ".")
    report = run_doctor(repo, include_guardrails=True)
    search_query = (query or "").strip()
    if not search_query and report.recommendation.best_model is not None:
        search_query = report.recommendation.best_model.name
    hits = search_models(search_query, tier=report.hardware.tier) if search_query else []
    return LocalSetupGuide(query=search_query, repo=repo, report=report, hits=hits[:3])


def _chosen_model_id(guide: LocalSetupGuide) -> str:
    best = guide.report.recommendation.best_model
    if best is None:
        return "<model>"
    if best.downloaded is not None:
        return best.downloaded.bare_id
    if best.pull:
        return best.pull.split()[-1]
    return best.name


def _pack_hint(guide: LocalSetupGuide) -> str:
    best = guide.report.recommendation.best_model
    if best is not None and best.pack:
        return f" --pack {best.pack}"
    for hit in guide.hits:
        if hit.packs:
            return f" --pack {hit.packs[0]}"
    return ""


def _serve_command(engine: str, model_id: str, context: int) -> str:
    if engine == "mlx-lm":
        return f"superqode local serve mlx --model {model_id} --ctx {context}"
    if engine == "llama.cpp":
        return f"superqode local serve llama.cpp --model /path/to/model.gguf --ctx {context}"
    if engine == "ds4":
        return f"superqode local serve ds4 --ctx {min(context, DS4_DEFAULT_CTX)}"
    if engine == "lmstudio":
        return "superqode local serve lmstudio"
    if engine == "ollama":
        return f"superqode local serve ollama --ctx {context}"
    return "superqode local serve <engine>"


def render_local_setup_guide(guide: LocalSetupGuide, *, tui_first: bool = False) -> str:
    """Render the local setup guide for CLI or TUI output."""

    report = guide.report
    rec = report.recommendation
    repo = report.repo
    guardrails = report.guardrails
    best = rec.best_model
    model_id = _chosen_model_id(guide)
    context = (
        guardrails.recommended_context_cap
        if guardrails is not None
        else (repo.recommended_context_tokens if repo is not None else 32768)
    )
    pack = _pack_hint(guide)
    serve = _serve_command(rec.engine or "", model_id, context)
    tui_serve = serve.replace("superqode local", ":local", 1)

    lines: list[str] = [
        "SuperQode Local Model Setup",
        "=" * 60,
        "This is a guide only: it does not download a model or start a server.",
        "Use the TUI path first; CLI equivalents are shown for scripts and docs.",
        "",
        "1. Pick a model",
    ]
    if guide.query:
        lines.append(f"   TUI  : :local search {guide.query}")
        lines.append(f"   CLI  : superqode local search {guide.query}")
    else:
        lines.append("   TUI  : :local labs   or   :hub qwen3-coder")
        lines.append("   CLI  : superqode local labs")
    if best is not None:
        ready = (
            f"already downloaded as {best.downloaded.bare_id}"
            if best.downloaded
            else f"download with: {best.pull}"
        )
        lines.append(f"   Best : {best.name} on {rec.engine or 'your preferred engine'} ({ready})")
    if guide.hits:
        lines.append("   Matches:")
        for hit in guide.hits:
            marker = "downloaded" if hit.downloaded_as else "available"
            lines.append(f"     - {hit.name} [{marker}]")
            for engine, command in hit.commands[:3]:
                lines.append(f"       {engine}: {command}")
            if hit.hub_repo:
                lines.append(f"       SuperQode: superqode models download {hit.hub_repo}")

    lines.extend(
        [
            "",
            "2. Download explicitly",
            "   Run the download command yourself in a terminal when you are ready.",
            "   SuperQode will not pull multi-GB model weights from this guide.",
        ]
    )
    if best is not None and best.pull and not best.downloaded:
        lines.append(f"   Suggested: {best.pull}")

    lines.extend(["", "3. Start or connect to a server"])
    if tui_first:
        lines.append(f"   TUI  : {tui_serve}")
        lines.append(f"   CLI  : {serve}")
    else:
        lines.append(f"   CLI  : {serve}")
        lines.append(f"   TUI  : {tui_serve}")
    lines.append("   Manual guides stay valid too: Ollama, LM Studio, MLX, DS4, llama.cpp, vLLM, or SGLang.")

    lines.extend(["", "4. Choose context for this repo"])
    if repo is not None:
        lines.append(f"   Repo estimate : ~{repo.estimated_tokens:,} code tokens")
        lines.append(f"   Repo advice   : {repo.recommended_context_tokens:,} token context")
    if guardrails is not None:
        lines.append(f"   Safe cap      : {guardrails.recommended_context_cap:,} tokens")
    if rec.engine == "ds4":
        lines.append(
            f"   DS4 default   : {DS4_DEFAULT_CTX:,} tokens; raise it only when memory and latency allow."
        )
    lines.append("   Bigger context can help large repos, but it costs memory and can slow local decoding.")

    lines.extend(["", "5. Build your own harness"])
    build_cmd = f"superqode local build --repo {guide.repo} --model {model_id}{pack}"
    tui_build = build_cmd.replace("superqode local", ":local", 1)
    if tui_first:
        lines.append(f"   TUI  : {tui_build}")
        lines.append(f"   CLI  : {build_cmd}")
    else:
        lines.append(f"   CLI  : {build_cmd}")
        lines.append(f"   TUI  : {tui_build}")
    lines.append(
        "   Packs are starter templates. Customize prompts, skills, memory, routing, and context for your project."
    )
    lines.append(
        "   Do not rely on anyone else's harness as-is, including ours: bring or build your own."
    )

    lines.extend(["", "6. Smoke test before real work"])
    if tui_first:
        lines.append(f"   TUI  : :local smoke --repo {guide.repo} --model {model_id}")
        lines.append(f"   CLI  : superqode local smoke --repo {guide.repo} --model {model_id}")
    else:
        lines.append(f"   CLI  : superqode local smoke --repo {guide.repo} --model {model_id}")
        lines.append(f"   TUI  : :local smoke --repo {guide.repo} --model {model_id}")
    lines.append("   Then run: superqode --harness superqode.local.yaml")
    return "\n".join(lines)
