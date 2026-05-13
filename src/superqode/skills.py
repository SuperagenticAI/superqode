"""
Skills System for SuperQode.

Markdown-based reusable agent workflows, similar to PyFlue and Fast-Agent.
Skills are loaded from .agents/skills/ directory.

Usage:
- Place .agents/skills/*.md files in your project
- Each skill has frontmatter metadata (name, description, enabled)
- Skills can be invoked as tools or added to system prompts

Example skill:
---
name: code_review
description: Review code for bugs and best practices
enabled: true
---

# Code Review Skill

You are an expert code reviewer. When invoked:
1. Read the file to review
2. Analyze for bugs, security issues
3. Provide detailed feedback
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import frontmatter
except ImportError:
    frontmatter = None


@dataclass
class Skill:
    """A Markdown-defined reusable agent workflow."""

    name: str
    description: str = ""
    instructions: str = ""
    enabled: bool = True
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    path: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SkillsLoader:
    """Load and manage Markdown skills from filesystem."""

    DEFAULT_SKILLS_DIR = ".agents/skills"

    def __init__(self, root: str | Path = "."):
        self.root = Path(root).expanduser().resolve()
        self._skills: Dict[str, Skill] = {}
        self._loaded = False

    def load(self, skills_dir: Optional[str | Path] = None) -> Dict[str, Skill]:
        """Load all skills from the skills directory."""
        if self._loaded:
            return self._skills

        directory = self._resolve_skills_dir(skills_dir)

        if not directory.exists():
            self._loaded = True
            return self._skills

        for path in sorted(directory.rglob("*.md")):
            skill = self._parse_skill(path)
            if skill and skill.enabled:
                self._skills[skill.name] = skill

        self._loaded = True
        return self._skills

    def _resolve_skills_dir(self, skills_dir: Optional[str | Path]) -> Path:
        """Resolve skills directory path."""
        if skills_dir:
            directory = Path(skills_dir).expanduser()
            if not directory.is_absolute():
                directory = self.root / directory
        else:
            directory = self.root / self.DEFAULT_SKILLS_DIR

        return directory

    def _parse_skill(self, path: Path) -> Optional[Skill]:
        """Parse a single Markdown skill file."""
        if not frontmatter:
            return None

        try:
            content = path.read_text(encoding="utf-8")
            post = frontmatter.loads(content)

            metadata = dict(post.metadata or {})

            name = metadata.get("name", "")
            if not name:
                if path.name.upper() == "SKILL.MD":
                    name = path.parent.name
                else:
                    name = path.stem

            if not name:
                return None

            return Skill(
                name=name.strip(),
                description=metadata.get("description", "").strip(),
                instructions=post.content.strip(),
                enabled=metadata.get("enabled", True),
                input_schema=metadata.get("input_schema"),
                output_schema=metadata.get("output_schema"),
                path=path,
                metadata=metadata,
            )

        except Exception:
            return None

    def get(self, name: str) -> Optional[Skill]:
        """Get a skill by name."""
        if not self._loaded:
            self.load()
        return self._skills.get(name)

    def list(self) -> List[Skill]:
        """List all loaded skills."""
        if not self._loaded:
            self.load()
        return list(self._skills.values())

    def reload(self) -> Dict[str, Skill]:
        """Reload skills from disk."""
        self._loaded = False
        self._skills = {}
        return self.load()


# Global skills loader instance
_skills_loader: Optional[SkillsLoader] = None


def get_skills_loader(root: str | Path = ".") -> SkillsLoader:
    """Get or create the global skills loader."""
    global _skills_loader
    if _skills_loader is None:
        _skills_loader = SkillsLoader(root)
    return _skills_loader


def load_skills(
    root: str | Path = ".", skills_dir: Optional[str | Path] = None
) -> Dict[str, Skill]:
    """Load skills from a directory."""
    loader = SkillsLoader(root)
    return loader.load(skills_dir)


def load_project_instructions(root: str | Path = ".") -> str:
    """Load project-level instructions from global, parent, and local files."""
    base = Path(root).expanduser().resolve()
    parts: List[str] = []

    candidate_dirs: List[Path] = []

    for global_dir in [Path.home() / ".superqode", Path.home() / ".config" / "superqode"]:
        candidate_dirs.append(global_dir)

    candidate_dirs.extend(reversed([base, *base.parents]))

    seen: set[Path] = set()
    for directory in candidate_dirs:
        if directory in seen:
            continue
        seen.add(directory)

        for filename in ["AGENTS.md", "CLAUDE.md"]:
            path = directory / filename
            if not path.exists():
                continue

            try:
                content = path.read_text(encoding="utf-8").strip()
            except Exception:
                continue

            if not content:
                continue

            try:
                label = path.relative_to(base)
            except ValueError:
                label = path
            parts.append(f"## Instructions from {label}\n\n{content}")

    return "\n\n".join(parts)
