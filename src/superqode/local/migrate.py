"""Dry-run migration planning for existing prompts, skills, and harnesses.

The migrator does not rewrite project files. It inventories the developer's
current setup and returns a local-model adaptation plan so the resulting
harness remains owned and reviewable by the project.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from superqode.harness.loader import load_harness_spec
from superqode.local.packs import detect_pack
from superqode.skills import load_skills


PROMPT_FILES = ("AGENTS.md", "CLAUDE.md", "SUPERQODE.md")
HARNESS_FILES = ("harness.yaml", "harness.yml", "superqode.local.yaml", "superqode.yaml")


@dataclass(frozen=True)
class MigrationFile:
    path: str
    kind: str
    bytes: int = 0
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MigrationReport:
    repo: str
    endpoint: str = ""
    model: str = ""
    detected_pack: str = ""
    harness_hint: dict[str, Any] = field(default_factory=dict)
    prompts: tuple[MigrationFile, ...] = ()
    skills: tuple[MigrationFile, ...] = ()
    harnesses: tuple[MigrationFile, ...] = ()
    recommendations: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "endpoint": self.endpoint,
            "model": self.model,
            "detected_pack": self.detected_pack,
            "harness_hint": dict(self.harness_hint),
            "prompts": [item.to_dict() for item in self.prompts],
            "skills": [item.to_dict() for item in self.skills],
            "harnesses": [item.to_dict() for item in self.harnesses],
            "recommendations": list(self.recommendations),
            "next_steps": list(self.next_steps),
        }


def plan_local_migration(
    repo_path: str | Path = ".",
    *,
    endpoint: str = "",
    model: str = "",
) -> MigrationReport:
    """Create a non-mutating migration plan for a local-model harness."""
    repo = Path(repo_path).expanduser().resolve()
    pack = detect_pack(" ".join(part for part in (endpoint, model) if part))

    prompts = tuple(_prompt_files(repo))
    skills = tuple(_skill_files(repo))
    harnesses = tuple(_harness_files(repo))

    recommendations: list[str] = []
    if not prompts:
        recommendations.append(
            "Add an AGENTS.md with project-specific rules; local models benefit from explicit, compact instructions."
        )
    else:
        total_prompt_bytes = sum(item.bytes for item in prompts)
        if total_prompt_bytes > 24_000:
            recommendations.append(
                "Project instructions are large; split reusable behavior into skills and keep AGENTS.md concise for local context budgets."
            )
        if any(item.path.endswith("CLAUDE.md") for item in prompts):
            recommendations.append(
                "CLAUDE.md is supported as a fallback, but AGENTS.md should be the canonical migrated instruction file."
            )

    if not skills:
        recommendations.append(
            "No .agents/skills markdown files found; migrate repeated workflows into skills before optimizing them."
        )
    else:
        recommendations.append(
            "Review each skill for cloud-only assumptions such as web search, unrestricted shell, or provider-specific tool syntax."
        )

    if not harnesses:
        recommendations.append(
            "Generate a local harness from this plan; do not rely on hidden defaults for model, tools, permissions, or context."
        )
    else:
        recommendations.append(
            "Use harness explain/compile on the existing harness before adapting it to a local model."
        )

    if pack:
        recommendations.append(
            f"Detected model policy pack '{pack.name}'; use it as a starting point, then keep smoke-test overrides in your harness."
        )
    elif model:
        recommendations.append(
            "No shipped model pack matched; run local smoke and create a project-owned pack for this model."
        )

    if endpoint:
        recommendations.append(
            "Treat the endpoint as bring-your-own infrastructure: probe capabilities before enabling broad write or shell access."
        )

    harness_hint = _harness_hint(endpoint=endpoint, model=model, pack_name=pack.name if pack else "")
    next_steps = _next_steps(
        repo,
        endpoint=endpoint,
        model=model,
        pack_name=pack.name if pack else "",
    )

    return MigrationReport(
        repo=str(repo),
        endpoint=endpoint,
        model=model,
        detected_pack=pack.name if pack else "",
        harness_hint=harness_hint,
        prompts=prompts,
        skills=skills,
        harnesses=harnesses,
        recommendations=tuple(dict.fromkeys(recommendations)),
        next_steps=tuple(next_steps),
    )


def render_migration_report(report: MigrationReport) -> str:
    lines = ["SuperQode local migration plan", ""]
    lines.append(f"Repo       {report.repo}")
    if report.model:
        lines.append(f"Model      {report.model}")
    if report.endpoint:
        lines.append(f"Endpoint   {report.endpoint}")
    if report.detected_pack:
        lines.append(f"Pack       {report.detected_pack}")
    lines.append("")
    lines.append("Existing setup")
    lines.extend(_section_lines("prompts", report.prompts))
    lines.extend(_section_lines("skills", report.skills))
    lines.extend(_section_lines("harnesses", report.harnesses))
    if report.recommendations:
        lines.append("")
        lines.append("Migration guidance")
        for item in report.recommendations:
            lines.append(f"  - {item}")
    if report.harness_hint:
        lines.append("")
        lines.append("Harness fields to carry forward")
        lines.append("  model_policy:")
        if report.harness_hint.get("primary"):
            lines.append(f"    primary: {report.harness_hint['primary']}")
        if report.harness_hint.get("pack"):
            lines.append(f"    pack: {report.harness_hint['pack']}")
        lines.append("  execution_policy:")
        lines.append("    allow_network: false")
        lines.append("    approval_profile: balanced")
    if report.next_steps:
        lines.append("")
        lines.append("Next steps")
        for item in report.next_steps:
            lines.append(f"  - {item}")
    lines.append("")
    lines.append(
        "Principle   This plan does not replace your setup; it helps you build a harness you own."
    )
    return "\n".join(lines)


def _prompt_files(repo: Path) -> list[MigrationFile]:
    rows: list[MigrationFile] = []
    for name in PROMPT_FILES:
        path = repo / name
        if path.is_file():
            rows.append(
                MigrationFile(
                    path=_rel(path, repo),
                    kind="prompt",
                    bytes=path.stat().st_size,
                    notes=_text_notes(path),
                )
            )
    roles_dir = repo / ".agents" / "roles"
    if roles_dir.is_dir():
        for path in sorted(roles_dir.rglob("*.md")):
            rows.append(
                MigrationFile(
                    path=_rel(path, repo),
                    kind="role-prompt",
                    bytes=path.stat().st_size,
                    notes=_text_notes(path),
                )
            )
    return rows


def _skill_files(repo: Path) -> list[MigrationFile]:
    rows: list[MigrationFile] = []
    loaded = load_skills(repo)
    for skill in sorted(loaded.values(), key=lambda item: item.name):
        path = skill.path
        rows.append(
            MigrationFile(
                path=_rel(path, repo) if path else skill.name,
                kind="skill",
                bytes=path.stat().st_size if path and path.is_file() else 0,
                notes=_skill_notes(skill.instructions),
            )
        )
    return rows


def _harness_files(repo: Path) -> list[MigrationFile]:
    rows: list[MigrationFile] = []
    for name in HARNESS_FILES:
        path = repo / name
        if not path.is_file():
            continue
        notes: list[str] = []
        if name.startswith("superqode") and name != "superqode.local.yaml":
            notes.append("project config; extract harness-owned model/tool policy explicitly")
        else:
            try:
                spec = load_harness_spec(path)
                if spec.model_policy.primary:
                    notes.append(f"model={spec.model_policy.primary}")
                if spec.model_policy.pack:
                    notes.append(f"pack={spec.model_policy.pack}")
                if not spec.execution_policy.allow_network:
                    notes.append("network blocked")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"could not parse as harness: {exc}")
        rows.append(
            MigrationFile(
                path=_rel(path, repo),
                kind="harness" if name != "superqode.yaml" else "config",
                bytes=path.stat().st_size,
                notes=tuple(notes),
            )
        )
    return rows


def _next_steps(repo: Path, *, endpoint: str, model: str, pack_name: str) -> list[str]:
    steps = [
        "Run: superqode local smoke --repo ."
        + (f" --endpoint {endpoint}" if endpoint else "")
        + (f" --model {model}" if model else ""),
    ]
    init = "Run: superqode local init --repo . --skip-smoke"
    if model:
        init += f" --model {model}"
    if pack_name:
        init += f" --pack {pack_name}"
    steps.append(init)
    if model and not pack_name:
        steps.append("Create a project-owned model pack after smoke confirms the model behavior.")
    steps.append("Run: superqode harness explain --spec <harness.yaml> before trusting the harness.")
    if (repo / ".agents" / "skills").is_dir():
        steps.append("Run held-out evals before optimizing migrated skills for the local model.")
    return steps


def _harness_hint(*, endpoint: str, model: str, pack_name: str) -> dict[str, Any]:
    hint: dict[str, Any] = {}
    if model:
        hint["primary"] = f"openai_compatible/{model}" if endpoint else model
    if pack_name:
        hint["pack"] = pack_name
    return hint


def _section_lines(label: str, rows: tuple[MigrationFile, ...]) -> list[str]:
    if not rows:
        return [f"  {label:<9} none found"]
    lines = []
    for row in rows:
        notes = f" ({'; '.join(row.notes)})" if row.notes else ""
        lines.append(f"  {label:<9} {row.path} [{row.kind}, {row.bytes} bytes]{notes}")
    return lines


def _text_notes(path: Path) -> tuple[str, ...]:
    try:
        text = path.read_text(encoding="utf-8").lower()
    except Exception:
        return ()
    notes: list[str] = []
    if "web_search" in text or "search the web" in text:
        notes.append("contains web-search assumption")
    if "claude" in text or "anthropic" in text or "openai" in text:
        notes.append("contains provider-specific wording")
    if len(text) > 16_000:
        notes.append("large prompt")
    return tuple(notes)


def _skill_notes(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    notes: list[str] = []
    if "web_search" in lowered or "search the web" in lowered:
        notes.append("review web-search behavior for local models")
    if "bash" in lowered or "shell" in lowered:
        notes.append("keep shell approval explicit")
    if len(text) > 12_000:
        notes.append("large skill; consider splitting")
    return tuple(notes)


def _rel(path: Path, repo: Path) -> str:
    try:
        return str(path.relative_to(repo))
    except ValueError:
        return str(path)


__all__ = [
    "MigrationFile",
    "MigrationReport",
    "plan_local_migration",
    "render_migration_report",
]
