"""Non-destructive readiness smoke test for local coding models."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from superqode.providers.local.base import is_embedding_model
from superqode.providers.local.context_probe import probe_base_url

from .bench import BenchResult, endpoint_reachable, list_endpoint_models, run_agentic_bench
from .servers import get_manager


@dataclass
class SmokeCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class SmokeReport:
    status: str
    engine: str = ""
    endpoint: str = ""
    model: str = ""
    repo: str = ""
    context_window: Optional[int] = None
    context_source: str = ""
    ttft_s: Optional[float] = None
    decode_tps: Optional[float] = None
    agentic_score: Optional[float] = None
    checks: list[SmokeCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "checks": [asdict(check) for check in self.checks],
        }


def _base_from_endpoint(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/")


def _first_running_engine() -> tuple[str, str]:
    manager = get_manager()
    for row in manager.list_all():
        if row.get("running") and row.get("base_url"):
            return str(row["engine"]), str(row["base_url"])
    return "", ""


def _status_from(report: SmokeReport, bench: BenchResult | None) -> str:
    failed = [check for check in report.checks if not check.ok and check.name in {"server", "model", "chat"}]
    if failed:
        return "failed"
    if report.warnings:
        return "warning"
    if bench and bench.agentic_score is not None and bench.agentic_score < 100:
        return "warning"
    return "ready"


def run_smoke(
    *,
    engine: str = "",
    endpoint: str = "",
    model: str = "",
    repo_path: str | Path | None = None,
    api_key: str = "",
    max_tokens: int = 384,
) -> SmokeReport:
    """Run a local coding readiness probe without reading or editing the repo."""
    repo = str(Path(repo_path).resolve()) if repo_path else ""
    chosen_engine = engine
    chosen_endpoint = endpoint
    if not chosen_endpoint:
        if chosen_engine:
            status = get_manager().status(chosen_engine)
            if status.get("running"):
                chosen_endpoint = str(status.get("base_url") or "")
        else:
            chosen_engine, chosen_endpoint = _first_running_engine()

    report = SmokeReport(
        status="failed",
        engine=chosen_engine,
        endpoint=chosen_endpoint,
        repo=repo,
    )

    if not chosen_endpoint:
        report.checks.append(SmokeCheck("server", False, "no running local server found"))
        report.next_steps.append("Start one with: superqode local serve <engine>")
        return report

    if not endpoint_reachable(chosen_endpoint):
        report.checks.append(SmokeCheck("server", False, f"no response from {chosen_endpoint}"))
        report.next_steps.append(
            f"Start the server (superqode local serve {chosen_engine or '<engine>'}) "
            "or check the --endpoint URL."
        )
        return report

    models = list_endpoint_models(chosen_endpoint)
    chat_models = [item for item in models if not is_embedding_model(item)]
    if not models:
        report.checks.append(SmokeCheck("server", True, f"reachable at {chosen_endpoint}"))
        report.checks.append(SmokeCheck("model", False, "server returned no models"))
        report.next_steps.append("Load or install a chat model, then run: superqode local models")
        return report
    if not chat_models:
        report.checks.append(SmokeCheck("server", True, f"reachable at {chosen_endpoint}"))
        report.checks.append(SmokeCheck("model", False, "only embedding/reranker models found"))
        report.next_steps.append("Load a chat/coding model, not an embedding model.")
        return report

    chosen_model = model or chat_models[0]
    report.model = chosen_model
    report.checks.append(SmokeCheck("server", True, f"reachable at {chosen_endpoint}"))
    report.checks.append(SmokeCheck("model", True, chosen_model))

    context = asyncio.run(probe_base_url(_base_from_endpoint(chosen_endpoint), chosen_model))
    if context:
        report.context_window, report.context_source = context
        report.checks.append(
            SmokeCheck("context", True, f"{report.context_window:,} tokens from {report.context_source}")
        )
    else:
        report.checks.append(SmokeCheck("context", False, "loaded context window not reported"))
        report.warnings.append(
            "Context window was not detected; generated harness will use conservative fallbacks."
        )

    bench = run_agentic_bench(chosen_endpoint, chosen_model, max_tokens=max_tokens, api_key=api_key)
    report.ttft_s = bench.ttft_s
    report.decode_tps = bench.decode_tps
    report.agentic_score = bench.agentic_score
    if not bench.ok:
        report.checks.append(SmokeCheck("chat", False, bench.error or "agentic probe failed"))
        report.next_steps.append(f"Warm the model: superqode local warm {chosen_engine or '<engine>'} --model {chosen_model}")
        report.status = _status_from(report, bench)
        return report

    report.checks.append(SmokeCheck("chat", True, f"TTFT {bench.ttft_s}s"))
    report.checks.append(
        SmokeCheck("read_file_tool", bool(bench.tool_call_success), "read_file probe")
    )
    report.checks.append(SmokeCheck("patch_format", bool(bench.edit_format_success), "diff probe"))
    report.checks.append(SmokeCheck("shell_tool", bool(bench.shell_call_success), "bash probe"))
    report.checks.append(
        SmokeCheck("context_recall", bool(bench.context_recall_success), "sentinel recall")
    )

    if bench.ttft_s is not None and bench.ttft_s > 5:
        report.warnings.append(
            "High TTFT; model is cold or context/prefill is too large for this hardware."
        )
        report.next_steps.append(
            f"Run: superqode local warm {chosen_engine or '<engine>'} --model {chosen_model}"
        )
    if bench.tool_call_success is False:
        report.warnings.append(
            "Native tool calls look unreliable; use prompt tool-call format in the harness."
        )
    if bench.edit_format_success is False:
        report.warnings.append("Patch/edit format looked unreliable for this model.")
    if bench.shell_call_success is False:
        report.warnings.append("Shell tool calls looked unreliable; keep shell approval required.")
    if bench.context_recall_success is False:
        report.warnings.append("Long-context recall probe failed; use smaller context or compact sooner.")
    for note in bench.agentic_notes:
        if note not in report.warnings:
            report.warnings.append(note)

    report.status = _status_from(report, bench)
    return report


def render_smoke(report: SmokeReport) -> str:
    lines = ["SuperQode local smoke", ""]
    target = report.model or "(no model)"
    route = report.endpoint or "(no endpoint)"
    lines.append(f"Route      {report.engine or 'local'}  {target}")
    lines.append(f"Endpoint   {route}")
    if report.repo:
        lines.append(f"Repo       {report.repo}")
    if report.ttft_s is not None:
        decode = f"{report.decode_tps} tok/s" if report.decode_tps is not None else "n/a"
        lines.append(f"Speed      TTFT {report.ttft_s}s / decode {decode}")
    if report.context_window:
        lines.append(f"Context    {report.context_window:,} ({report.context_source})")
    lines.append("")
    lines.append("Checks")
    for check in report.checks:
        mark = "PASS" if check.ok else "WARN"
        if check.name in {"server", "model", "chat"} and not check.ok:
            mark = "FAIL"
        detail = f" - {check.detail}" if check.detail else ""
        lines.append(f"  {mark:<4} {check.name}{detail}")
    if report.warnings:
        lines.append("")
        lines.append("Warnings")
        for warning in report.warnings:
            lines.append(f"  - {warning}")
    if report.next_steps:
        lines.append("")
        lines.append("Next steps")
        for step in report.next_steps:
            lines.append(f"  - {step}")
    lines.append("")
    if report.status == "ready":
        lines.append("Verdict    Local coding harness ready.")
    elif report.status == "warning":
        lines.append("Verdict    Local coding harness usable with warnings.")
    else:
        lines.append("Verdict    Local coding harness is not ready yet.")
    return "\n".join(lines)


__all__ = ["SmokeCheck", "SmokeReport", "render_smoke", "run_smoke"]
