"""Static local harness builder.

This composes the local migration, model-pack, and harness-generation pieces
without running a live model prompt. It is designed for the TUI path where a
developer wants a clear, reviewable harness before the final smoke/eval phase.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .doctor import generate_harness_yaml, run_doctor
from .migrate import MigrationReport, plan_local_migration
from .packs import PackDraft, draft_pack, get_pack, write_pack_draft


@dataclass(frozen=True)
class LocalBuildReport:
    repo: str
    output: str
    model: str = ""
    endpoint: str = ""
    pack: str = ""
    harness_written: bool = False
    pack_written: bool = False
    pack_path: str = ""
    migration: MigrationReport | None = None
    pack_draft: PackDraft | None = None
    next_steps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "output": self.output,
            "model": self.model,
            "endpoint": self.endpoint,
            "pack": self.pack,
            "harness_written": self.harness_written,
            "pack_written": self.pack_written,
            "pack_path": self.pack_path,
            "migration": self.migration.to_dict() if self.migration else None,
            "pack_draft": self.pack_draft.to_dict() if self.pack_draft else None,
            "next_steps": list(self.next_steps),
        }


def build_local_harness(
    *,
    repo_path: str | Path = ".",
    model: str = "",
    endpoint: str = "",
    pack: str = "",
    output: str | Path = "superqode.local.yaml",
    write_pack: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> LocalBuildReport:
    """Build a local harness plan and optionally write the harness/pack files.

    This function does not call ``local smoke``, ``warm``, or any model
    completion endpoint.
    """
    repo = Path(repo_path).expanduser().resolve()
    output_path = Path(output).expanduser()
    if not output_path.is_absolute():
        output_path = repo / output_path

    migration = plan_local_migration(repo, endpoint=endpoint, model=model)
    selected_pack = (pack or migration.detected_pack or "").strip()
    pack_draft = None
    pack_written = False
    pack_path = ""
    if not selected_pack:
        pack_draft = draft_pack(model=model, endpoint=endpoint)
        selected_pack = pack_draft.pack.name
    elif get_pack(selected_pack) is None:
        pack_draft = draft_pack(name=selected_pack, model=model, endpoint=endpoint)

    if write_pack and pack_draft is not None and not dry_run:
        written = write_pack_draft(pack_draft, force=force)
        pack_draft = written
        pack_written = True
        pack_path = str(written.path or "")

    doctor = run_doctor(str(repo), include_guardrails=True)
    primary = _primary_for(model=model, endpoint=endpoint)
    harness = generate_harness_yaml(
        doctor,
        name="local-coder",
        pack_override=selected_pack,
        primary_override=primary,
    )

    harness_written = False
    if not dry_run:
        if output_path.exists() and not force:
            raise FileExistsError(f"{output_path} already exists; pass --force to overwrite")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(harness, encoding="utf-8")
        harness_written = True

    return LocalBuildReport(
        repo=str(repo),
        output=str(output_path),
        model=model,
        endpoint=endpoint,
        pack=selected_pack,
        harness_written=harness_written,
        pack_written=pack_written,
        pack_path=pack_path,
        migration=migration,
        pack_draft=pack_draft,
        next_steps=tuple(_next_steps(output_path, model=model, endpoint=endpoint)),
    )


def render_local_build_report(report: LocalBuildReport) -> str:
    lines = ["SuperQode local harness builder", ""]
    lines.append(f"Repo       {report.repo}")
    lines.append(f"Harness    {report.output}")
    if report.model:
        lines.append(f"Model      {report.model}")
    if report.endpoint:
        lines.append(f"Endpoint   {report.endpoint}")
    lines.append(f"Pack       {report.pack}")
    lines.append("")
    lines.append("Build outputs")
    lines.append(
        f"  harness: {'written' if report.harness_written else 'planned'} -> {report.output}"
    )
    if report.pack_draft is not None:
        state = "written" if report.pack_written else "drafted"
        suffix = f" -> {report.pack_path}" if report.pack_path else ""
        lines.append(f"  pack: {state} -> {report.pack}{suffix}")
    else:
        lines.append(f"  pack: existing -> {report.pack}")
    if report.migration is not None:
        lines.append("")
        lines.append("Existing setup")
        lines.append(f"  prompts: {len(report.migration.prompts)}")
        lines.append(f"  skills: {len(report.migration.skills)}")
        lines.append(f"  harnesses: {len(report.migration.harnesses)}")
    if report.next_steps:
        lines.append("")
        lines.append("Final live checks")
        for step in report.next_steps:
            lines.append(f"  - {step}")
    lines.append("")
    lines.append("Principle   Review the harness, customize it, then run live smoke/evals.")
    return "\n".join(lines)


def _primary_for(*, model: str, endpoint: str) -> str:
    if not model:
        return ""
    return f"openai_compatible/{model}" if endpoint else model


def _next_steps(output_path: Path, *, model: str, endpoint: str) -> list[str]:
    smoke = "superqode local smoke --repo ."
    if endpoint:
        smoke += f" --endpoint {endpoint}"
    if model:
        smoke += f" --model {model}"
    return [
        smoke,
        f"superqode harness explain --spec {output_path}",
        f"superqode --harness {output_path}",
    ]


__all__ = ["LocalBuildReport", "build_local_harness", "render_local_build_report"]
