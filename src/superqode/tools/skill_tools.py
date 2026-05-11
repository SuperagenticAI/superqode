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
                return ToolResult(success=False, output="", error="Skill name required for info action")
            return await self._skill_info(loader, name)
        elif action == "invoke":
            if not name:
                return ToolResult(success=False, output="", error="Skill name required for invoke action")
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
            skill.instructions[:500] + "..." if len(skill.instructions) > 500 else skill.instructions,
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
            output_lines.extend([
                "",
                f"## Context",
                context,
            ])

        output_lines.extend([
            "",
            f"_(Use these instructions to complete the task)_",
        ])

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


def create_skill_tools(skills_loader: Optional[SkillsLoader] = None) -> List[Tool]:
    """Create skill-related tools."""
    return [SkillTool(skills_loader), ReadSkillTool(skills_loader)]