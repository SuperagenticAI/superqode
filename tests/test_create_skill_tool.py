"""Tests for the self-extensible skill authoring tool."""

import asyncio
from pathlib import Path

from superqode.skills import SkillsLoader
from superqode.tools.base import ToolContext
from superqode.tools.skill_tools import CreateSkillTool, SkillTool, _slugify_skill_name


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(session_id="t", working_directory=tmp_path)


def test_slugify_skill_name():
    assert _slugify_skill_name("Release Checklist") == "release-checklist"
    assert _slugify_skill_name("  Fix Bugs!! ") == "fix-bugs"
    assert _slugify_skill_name("a/b\\c") == "a-b-c"


def test_create_skill_writes_file_and_hot_reloads(tmp_path):
    loader = SkillsLoader(tmp_path)
    loader.load()  # nothing yet
    assert loader.list() == []

    create = CreateSkillTool(loader)
    result = asyncio.run(
        create.execute(
            {
                "name": "Release Checklist",
                "description": "Steps to cut a release",
                "instructions": "1. Bump version\n2. Update CHANGELOG\n3. Tag and push",
            },
            _ctx(tmp_path),
        )
    )

    assert result.success, result.error
    skill_file = tmp_path / ".agents" / "skills" / "release-checklist" / "SKILL.md"
    assert skill_file.exists()

    # Hot-reloaded: the same loader now lists/serves the new skill immediately.
    skill = loader.get("release-checklist")
    assert skill is not None
    assert skill.description == "Steps to cut a release"
    assert "Update CHANGELOG" in skill.instructions


def test_created_skill_is_invocable_via_skill_tool(tmp_path):
    loader = SkillsLoader(tmp_path)
    create = CreateSkillTool(loader)
    asyncio.run(
        create.execute(
            {"name": "greet", "description": "say hi", "instructions": "Say hello warmly."},
            _ctx(tmp_path),
        )
    )

    skill_tool = SkillTool(loader)
    invoked = asyncio.run(skill_tool.execute({"action": "invoke", "name": "greet"}, _ctx(tmp_path)))
    assert invoked.success
    assert "Say hello warmly." in invoked.output


def test_create_skill_requires_name_and_instructions(tmp_path):
    create = CreateSkillTool(SkillsLoader(tmp_path))
    result = asyncio.run(create.execute({"name": "x", "description": "d"}, _ctx(tmp_path)))
    assert not result.success
    assert "required" in result.error.lower()


def test_create_skill_refuses_overwrite_without_flag(tmp_path):
    loader = SkillsLoader(tmp_path)
    create = CreateSkillTool(loader)
    args = {"name": "dup", "description": "d", "instructions": "first"}
    first = asyncio.run(create.execute(args, _ctx(tmp_path)))
    assert first.success

    second = asyncio.run(create.execute(args, _ctx(tmp_path)))
    assert not second.success
    assert "already exists" in second.error

    third = asyncio.run(
        create.execute({**args, "instructions": "second", "overwrite": True}, _ctx(tmp_path))
    )
    assert third.success
    assert "second" in loader.get("dup").instructions
