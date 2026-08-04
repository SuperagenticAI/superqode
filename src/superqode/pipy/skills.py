"""Skill discovery and formatting.

Ported from ``packages/coding-agent/src/core/skills.ts`` and
``packages/agent/src/harness/skills.ts`` of earendil-works/pi (MIT).

A skill is a ``SKILL.md`` file with YAML frontmatter. The model is shown only
its name, description and location; the body is loaded on demand with the read
tool, which is what keeps the system prompt small however many skills exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from .config import prompts_dir, skills_dir

SKILL_FILE_NAME = "SKILL.md"
MAX_DESCRIPTION_LENGTH = 1024
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    file_path: str
    content: str = ""
    #: Skills marked this way stay invocable by the user but are hidden from
    #: the model, so a manual-only skill does not spend prompt budget.
    disable_model_invocation: bool = False


@dataclass(frozen=True, slots=True)
class SkillDiagnostic:
    file_path: str
    message: str


@dataclass(slots=True)
class SkillLoadResult:
    skills: list[Skill] = field(default_factory=list)
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)


def skill_search_paths(cwd: str | Path) -> list[Path]:
    """Where skills are looked for, most specific first.

    ``.pi/skills`` comes first so an existing pi repository works unchanged.
    PiPy only ever reads from it.
    """
    root = Path(cwd).expanduser().resolve()
    return [
        root / ".pi" / "skills",
        root / ".superqode" / "pipy" / "skills",
        skills_dir(),
    ]


def _validate(path: Path, name: str, description: str) -> list[str]:
    errors: list[str] = []
    if not description.strip():
        errors.append("description is required")
    elif len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append(
            f"description exceeds {MAX_DESCRIPTION_LENGTH} characters ({len(description)})"
        )
    if not _NAME_RE.match(name):
        errors.append(f"invalid skill name {name!r}")
    return errors


def _load_skill_file(path: Path) -> tuple[Skill | None, list[SkillDiagnostic]]:
    try:
        document = frontmatter.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return None, [SkillDiagnostic(str(path), f"could not read skill: {error}")]
    except Exception as error:  # noqa: BLE001 - malformed frontmatter
        return None, [SkillDiagnostic(str(path), f"invalid frontmatter: {error}")]

    metadata = document.metadata or {}
    # Fall back to the containing directory, which is how most skills are named.
    name = str(metadata.get("name") or path.parent.name)
    description = str(metadata.get("description") or "")

    errors = _validate(path, name, description)
    diagnostics = [SkillDiagnostic(str(path), message) for message in errors]
    if not description.strip():
        # Without a description the model has no basis to choose the skill, so
        # loading it would only add noise.
        return None, diagnostics

    return (
        Skill(
            name=name,
            description=description,
            file_path=str(path),
            content=document.content,
            disable_model_invocation=bool(metadata.get("disable-model-invocation", False)),
        ),
        diagnostics,
    )


def _walk_for_skills(directory: Path) -> list[Path]:
    """Find skill files, stopping at the first ``SKILL.md`` on each branch.

    A skill directory owns its subtree: supporting files and nested references
    belong to the skill, not to further skills.
    """
    found: list[Path] = []
    skill_file = directory / SKILL_FILE_NAME
    if skill_file.is_file():
        return [skill_file]
    try:
        children = sorted(directory.iterdir())
    except OSError:
        return found
    for child in children:
        if child.is_dir() and not child.name.startswith("."):
            found.extend(_walk_for_skills(child))
        elif child.is_file() and child.suffix == ".md" and child.name != SKILL_FILE_NAME:
            found.append(child)
    return found


def load_skills(directories: list[Path] | None = None, *, cwd: str | Path = ".") -> SkillLoadResult:
    """Load every discoverable skill, nearest directory winning on name clash."""
    result = SkillLoadResult()
    seen: set[str] = set()
    for directory in directories if directories is not None else skill_search_paths(cwd):
        if not directory.is_dir():
            continue
        for path in _walk_for_skills(directory):
            skill, diagnostics = _load_skill_file(path)
            result.diagnostics.extend(diagnostics)
            if skill is None or skill.name in seen:
                continue
            seen.add(skill.name)
            result.skills.append(skill)
    return result


def _escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def format_skills_for_prompt(skills: list[Skill]) -> str:
    """The ``<available_skills>`` block appended to the system prompt."""
    visible = [skill for skill in skills if not skill.disable_model_invocation]
    if not visible:
        return ""

    lines = [
        "\n\nThe following skills provide specialized instructions for specific tasks.",
        "Use the read tool to load a skill's file when the task matches its description.",
        "When a skill file references a relative path, resolve it against the skill "
        "directory (parent of SKILL.md / dirname of the path) and use that absolute "
        "path in tool commands.",
        "",
        "<available_skills>",
    ]
    for skill in visible:
        lines.append("  <skill>")
        lines.append(f"    <name>{_escape_xml(skill.name)}</name>")
        lines.append(f"    <description>{_escape_xml(skill.description)}</description>")
        lines.append(f"    <location>{_escape_xml(skill.file_path)}</location>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)


def format_skill_invocation(skill: Skill, additional_instructions: str | None = None) -> str:
    """The message sent when a user invokes a skill directly."""
    directory = str(Path(skill.file_path).parent)
    block = (
        f'<skill name="{skill.name}" location="{skill.file_path}">\n'
        f"References are relative to {directory}.\n\n"
        f"{skill.content}\n</skill>"
    )
    return f"{block}\n\n{additional_instructions}" if additional_instructions else block


__all__ = [
    "MAX_DESCRIPTION_LENGTH",
    "SKILL_FILE_NAME",
    "Skill",
    "SkillDiagnostic",
    "SkillLoadResult",
    "format_skill_invocation",
    "format_skills_for_prompt",
    "load_skills",
    "prompts_dir",
    "skill_search_paths",
]
