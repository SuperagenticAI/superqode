"""
Skill tools for SuperQode.

Provides tools to invoke and use Markdown skills in agent execution.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..tools.base import Tool, ToolResult, ToolContext
from ..skills import SkillsLoader, Skill, get_skills_loader


class SkillTool(Tool):
    """Tool to list and invoke available skills."""

    read_only = True

    def __init__(self, skills_loader: Optional[SkillsLoader] = None):
        self._loader = skills_loader
        self._workspace = Path.cwd()

    @property
    def name(self) -> str:
        return "skill"

    @property
    def description(self) -> str:
        return """List and invoke available skills.

A skill is a reusable Markdown-defined agent workflow.
Use list to see available skills, then invoke by name with optional context.

Example:
- skill(action="list") - List all available skills
- skill(action="invoke", name="code_review", context="Review this file")"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "invoke", "info"],
                    "description": "Action to perform: list skills, invoke a skill, or get info",
                },
                "name": {
                    "type": "string",
                    "description": "Skill name to invoke or get info about",
                },
                "context": {
                    "type": "string",
                    "description": "Context/input for the skill when invoking",
                },
            },
            "required": ["action"],
        }

    def _get_loader(self) -> SkillsLoader:
        """Get the skills loader."""
        if self._loader:
            return self._loader
        return get_skills_loader(self._workspace)

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        action = args.get("action", "list")
        name = args.get("name", "")
        context = args.get("context", "")

        loader = self._get_loader()

        if action == "list":
            return await self._list_skills(loader)
        elif action == "info":
            if not name:
                return ToolResult(
                    success=False, output="", error="Skill name required for info action"
                )
            return await self._skill_info(loader, name)
        elif action == "invoke":
            if not name:
                return ToolResult(
                    success=False, output="", error="Skill name required for invoke action"
                )
            return await self._invoke_skill(loader, name, context, ctx)
        else:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")

    async def _list_skills(self, loader: SkillsLoader) -> ToolResult:
        """List all available skills."""
        skills = loader.list()

        if not skills:
            return ToolResult(
                success=True,
                output="No skills found. Add .agents/skills/*.md files to enable skills.",
            )

        lines = [f"Available Skills ({len(skills)}):\n"]

        for skill in skills:
            lines.append(f"## {skill.name}")
            if skill.description:
                lines.append(f"   {skill.description}")
            lines.append(f"   Path: {skill.path}")
            lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            metadata={"count": len(skills)},
        )

    async def _skill_info(self, loader: SkillsLoader, name: str) -> ToolResult:
        """Get detailed info about a skill."""
        skill = loader.get(name)

        if not skill:
            return ToolResult(
                success=False,
                output="",
                error=f"Skill not found: {name}",
            )

        lines = [
            f"Skill: {skill.name}",
            f"Description: {skill.description}",
            f"Enabled: {skill.enabled}",
            f"Path: {skill.path}",
            "",
            "Instructions:",
            skill.instructions[:500] + "..."
            if len(skill.instructions) > 500
            else skill.instructions,
        ]

        return ToolResult(success=True, output="\n".join(lines))

    async def _invoke_skill(
        self, loader: SkillsLoader, name: str, context: str, ctx: ToolContext
    ) -> ToolResult:
        """Invoke a skill and return its instructions."""
        skill = loader.get(name)

        if not skill:
            return ToolResult(
                success=False,
                output="",
                error=f"Skill not found: {name}",
            )

        output_lines = [
            f"# Invoking Skill: {skill.name}",
            "",
            skill.instructions,
        ]

        if context:
            output_lines.extend(
                [
                    "",
                    f"## Context",
                    context,
                ]
            )

        output_lines.extend(
            [
                "",
                f"_(Use these instructions to complete the task)_",
            ]
        )

        return ToolResult(
            success=True,
            output="\n".join(output_lines),
            metadata={
                "skill_name": name,
                "has_context": bool(context),
            },
        )


class ReadSkillTool(Tool):
    """Tool to read a skill file directly."""

    read_only = True

    def __init__(self, skills_loader: Optional[SkillsLoader] = None):
        self._loader = skills_loader
        self._workspace = Path.cwd()

    @property
    def name(self) -> str:
        return "read_skill"

    @property
    def description(self) -> str:
        return """Read a skill file's content directly.

Use this to read SKILL.md files or other skill resources.
Provide the skill name to read its instructions."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill to read",
                },
            },
            "required": ["name"],
        }

    def _get_loader(self) -> SkillsLoader:
        if self._loader:
            return self._loader
        return get_skills_loader(self._workspace)

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        name = args.get("name", "")

        if not name:
            return ToolResult(success=False, output="", error="Skill name required")

        loader = self._get_loader()
        skill = loader.get(name)

        if not skill:
            return ToolResult(
                success=False,
                output="",
                error=f"Skill not found: {name}",
            )

        return ToolResult(
            success=True,
            output=skill.instructions,
            metadata={"name": skill.name, "description": skill.description},
        )


def _slugify_skill_name(name: str) -> str:
    """Turn a free-text skill name into a safe directory slug."""
    import re

    slug = re.sub(r"[^a-z0-9._-]+", "-", name.strip().lower())
    slug = slug.strip("-._")
    return slug


class CreateSkillTool(Tool):
    """Tool that lets the agent author a new reusable skill at runtime.

    A skill is a Markdown ``SKILL.md`` of instructions (no executable code), so
    authoring one is safe: it teaches the agent a reusable workflow that becomes
    immediately invocable via the ``skill`` tool. This is what makes SuperQode
    self-extensible — the agent can grow its own playbook mid-session.
    """

    def __init__(self, skills_loader: Optional[SkillsLoader] = None):
        self._loader = skills_loader
        self._workspace = Path.cwd()

    @property
    def name(self) -> str:
        return "create_skill"

    @property
    def description(self) -> str:
        return """Author a new reusable skill that becomes available immediately.

A skill is a Markdown playbook of instructions for a repeatable workflow (no
code is executed). After creating one, invoke it later with
skill(action="invoke", name="<name>"). Use this when you discover a workflow
worth reusing across turns or sessions.

Example:
- create_skill(name="release_checklist", description="Steps to cut a release",
    instructions="1. Bump version\\n2. Update CHANGELOG\\n3. Tag and push")"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short skill name (becomes the invocation name)",
                },
                "description": {
                    "type": "string",
                    "description": "One-line summary of what the skill does",
                },
                "instructions": {
                    "type": "string",
                    "description": "The Markdown body: the reusable steps/guidance",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Replace an existing skill with the same name (default false)",
                },
            },
            "required": ["name", "description", "instructions"],
        }

    def _get_loader(self) -> SkillsLoader:
        if self._loader:
            return self._loader
        return get_skills_loader(self._workspace)

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        import json

        raw_name = str(args.get("name", "")).strip()
        description = str(args.get("description", "")).strip()
        instructions = str(args.get("instructions", "")).strip()
        overwrite = bool(args.get("overwrite", False))

        if not raw_name or not instructions:
            return ToolResult(
                success=False, output="", error="Both 'name' and 'instructions' are required."
            )

        slug = _slugify_skill_name(raw_name)
        if not slug:
            return ToolResult(
                success=False,
                output="",
                error=f"Could not derive a valid skill name from '{raw_name}'.",
            )

        loader = self._get_loader()
        skills_dir = Path(loader.root) / SkillsLoader.DEFAULT_SKILLS_DIR
        skill_path = skills_dir / slug / "SKILL.md"

        if skill_path.exists() and not overwrite:
            return ToolResult(
                success=False,
                output="",
                error=f"Skill '{slug}' already exists. Pass overwrite=true to replace it.",
            )

        # JSON encodes as valid double-quoted YAML scalars (safe for any chars).
        document = (
            "---\n"
            f"name: {json.dumps(slug)}\n"
            f"description: {json.dumps(description)}\n"
            "enabled: true\n"
            "---\n\n"
            f"{instructions}\n"
        )

        try:
            skill_path.parent.mkdir(parents=True, exist_ok=True)
            skill_path.write_text(document, encoding="utf-8")
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"Could not write skill: {exc}")

        # Hot-reload so the new skill is usable immediately this session.
        loader.reload()

        return ToolResult(
            success=True,
            output=(
                f"Created skill '{slug}' at {skill_path}.\n"
                f'Invoke it with skill(action="invoke", name="{slug}").'
            ),
            metadata={"name": slug, "path": str(skill_path)},
        )


def create_skill_tools(skills_loader: Optional[SkillsLoader] = None) -> List[Tool]:
    """Create skill-related tools."""
    return [
        SkillTool(skills_loader),
        ReadSkillTool(skills_loader),
        CreateSkillTool(skills_loader),
    ]
