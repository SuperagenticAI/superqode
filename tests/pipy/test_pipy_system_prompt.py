"""System prompt, resources, skills and prompt templates (checklist R1 to R12)."""

from __future__ import annotations

import pytest

from superqode.pipy.prompt_templates import (
    PromptTemplate,
    format_prompt_template_invocation,
    load_prompt_templates,
    prompt_search_paths,
    substitute_args,
)
from superqode.pipy.resources import CONTEXT_FILE_NAMES, ContextFile, load_context_files
from superqode.pipy.skills import (
    MAX_DESCRIPTION_LENGTH,
    Skill,
    format_skill_invocation,
    format_skills_for_prompt,
    load_skills,
    skill_search_paths,
)
from superqode.pipy.system_prompt import (
    ALWAYS_GUIDELINES,
    BASH_EXPLORATION_GUIDELINE,
    SelfDocs,
    SystemPromptOptions,
    build_system_prompt,
)
from superqode.pipy.tools import create_tools

# -- project context --------------------------------------------------------- #


def test_context_file_names_match_pi():
    assert CONTEXT_FILE_NAMES == ("AGENTS.md", "AGENTS.MD", "CLAUDE.md", "CLAUDE.MD")


def test_loads_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("house rules\n")

    files = load_context_files(tmp_path)

    assert len(files) == 1
    assert files[0].path.endswith("AGENTS.md")
    assert files[0].content.strip() == "house rules"


def test_first_candidate_wins(tmp_path):
    """pi stops at the first match rather than merging near-duplicates."""
    (tmp_path / "AGENTS.md").write_text("agents\n")
    (tmp_path / "CLAUDE.md").write_text("claude\n")

    files = load_context_files(tmp_path)

    assert len(files) == 1
    assert files[0].content.strip() == "agents"


def test_claude_md_is_used_when_agents_md_is_absent(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("claude\n")

    files = load_context_files(tmp_path)

    assert len(files) == 1
    assert files[0].content.strip() == "claude"


def test_empty_context_file_is_skipped(tmp_path):
    (tmp_path / "AGENTS.md").write_text("   \n")

    assert load_context_files(tmp_path) == []


def test_no_context_files(tmp_path):
    assert load_context_files(tmp_path) == []


# -- skills ------------------------------------------------------------------ #


def write_skill(directory, name, description, body="do the thing", extra=""):
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n{extra}---\n{body}\n"
    )
    return skill_dir / "SKILL.md"


def test_skill_search_order_prefers_pi_then_project_then_home(tmp_path):
    paths = skill_search_paths(tmp_path)

    assert paths[0] == tmp_path.resolve() / ".pi" / "skills"
    assert paths[1] == tmp_path.resolve() / ".superqode" / "pipy" / "skills"
    assert len(paths) == 3


def test_loads_a_skill(tmp_path):
    write_skill(tmp_path / ".pi/skills", "review", "Review a diff carefully")

    result = load_skills(cwd=tmp_path)

    assert [s.name for s in result.skills] == ["review"]
    assert result.skills[0].description == "Review a diff carefully"
    assert result.skills[0].content.strip() == "do the thing"


def test_pi_skills_directory_is_read(tmp_path):
    """An existing pi repository works without moving anything."""
    write_skill(tmp_path / ".pi/skills", "frompi", "Lives in the pi directory")

    assert [s.name for s in load_skills(cwd=tmp_path).skills] == ["frompi"]


def test_nearest_directory_wins_on_name_clash(tmp_path):
    write_skill(tmp_path / ".pi/skills", "dup", "from pi")
    write_skill(tmp_path / ".superqode/pipy/skills", "dup", "from superqode")

    skills = load_skills(cwd=tmp_path).skills

    assert len(skills) == 1
    assert skills[0].description == "from pi"


def test_discovery_stops_at_the_first_skill_file(tmp_path):
    """A skill directory owns its subtree, so nested files are its own."""
    root = tmp_path / ".pi/skills"
    write_skill(root, "outer", "The outer skill")
    nested = root / "outer" / "nested"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("---\nname: nested\ndescription: should not load\n---\nx\n")

    assert [s.name for s in load_skills(cwd=tmp_path).skills] == ["outer"]


def test_skill_name_falls_back_to_the_directory(tmp_path):
    skill_dir = tmp_path / ".pi/skills/inferred"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\ndescription: No explicit name\n---\nbody\n")

    assert [s.name for s in load_skills(cwd=tmp_path).skills] == ["inferred"]


def test_skill_without_a_description_is_rejected_with_a_diagnostic(tmp_path):
    skill_dir = tmp_path / ".pi/skills/broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: broken\n---\nbody\n")

    result = load_skills(cwd=tmp_path)

    assert result.skills == []
    assert any("description is required" in d.message for d in result.diagnostics)


def test_overlong_description_is_reported(tmp_path):
    write_skill(tmp_path / ".pi/skills", "long", "x" * (MAX_DESCRIPTION_LENGTH + 1))

    result = load_skills(cwd=tmp_path)

    assert any("exceeds" in d.message for d in result.diagnostics)


def test_missing_skill_directories_are_skipped(tmp_path):
    assert load_skills(cwd=tmp_path).skills == []


def test_skills_prompt_block_shape():
    skills = [Skill(name="review", description="Review a diff", file_path="/s/review/SKILL.md")]

    block = format_skills_for_prompt(skills)

    assert "<available_skills>" in block
    assert "    <name>review</name>" in block
    assert "    <location>/s/review/SKILL.md</location>" in block
    assert block.rstrip().endswith("</available_skills>")


def test_skills_prompt_escapes_xml():
    skills = [Skill(name="a&b", description="<danger>", file_path="/x'y")]

    block = format_skills_for_prompt(skills)

    assert "a&amp;b" in block
    assert "&lt;danger&gt;" in block
    assert "&apos;" in block


def test_model_invocation_can_be_disabled():
    skills = [
        Skill(name="visible", description="d", file_path="/a"),
        Skill(name="hidden", description="d", file_path="/b", disable_model_invocation=True),
    ]

    block = format_skills_for_prompt(skills)

    assert "visible" in block and "hidden" not in block


def test_no_skills_produces_no_block():
    assert format_skills_for_prompt([]) == ""


def test_skill_invocation_block():
    skill = Skill(name="review", description="d", file_path="/s/review/SKILL.md", content="steps")

    text = format_skill_invocation(skill, "focus on tests")

    assert text.startswith('<skill name="review" location="/s/review/SKILL.md">')
    assert "References are relative to /s/review." in text
    assert text.endswith("focus on tests")


# -- prompt templates -------------------------------------------------------- #


@pytest.mark.parametrize(
    ("content", "args", "expected"),
    [
        ("fix $1", ["bug"], "fix bug"),
        ("$1 and $2", ["a", "b"], "a and b"),
        ("missing $3", ["a"], "missing "),
        ("all: $ARGUMENTS", ["a", "b"], "all: a b"),
        ("all: $@", ["a", "b"], "all: a b"),
        ("rest: ${@:2}", ["a", "b", "c"], "rest: b c"),
        ("slice: ${@:2:2}", ["a", "b", "c", "d"], "slice: b c"),
        ("no args: $ARGUMENTS", [], "no args: "),
    ],
)
def test_argument_substitution_matches_pi(content, args, expected):
    assert substitute_args(content, args) == expected


def test_loads_prompt_templates(tmp_path):
    directory = tmp_path / ".pi/prompts"
    directory.mkdir(parents=True)
    (directory / "fix.md").write_text("---\ndescription: Fix a bug\n---\nPlease fix $1\n")

    result = load_prompt_templates(cwd=tmp_path)

    assert [t.name for t in result.templates] == ["fix"]
    assert result.templates[0].description == "Fix a bug"


def test_template_search_order(tmp_path):
    paths = prompt_search_paths(tmp_path)
    assert paths[0] == tmp_path.resolve() / ".pi" / "prompts"


def test_template_invocation_substitutes():
    template = PromptTemplate(name="fix", content="Fix $1 in $2")

    assert format_prompt_template_invocation(template, ["the bug", "main.py"]) == (
        "Fix the bug in main.py"
    )


# -- system prompt ----------------------------------------------------------- #


def prompt_for(tool_names, **kwargs):
    return build_system_prompt(
        SystemPromptOptions(cwd="/repo", tools=create_tools(tuple(tool_names), "/repo"), **kwargs)
    )


def test_tool_list_uses_each_tools_snippet():
    prompt = prompt_for(["read", "bash"])

    assert "- read: Read file contents" in prompt
    assert "- bash: Execute bash commands (ls, grep, find, etc.)" in prompt


def test_tool_without_a_snippet_is_hidden():
    from superqode.pipy.tools import AgentTool

    quiet = AgentTool(
        name="quiet",
        label="quiet",
        description="d",
        parameters={"type": "object"},
        execute_fn=lambda *a, **k: None,
    )
    prompt = build_system_prompt(SystemPromptOptions(cwd="/repo", tools=[quiet]))

    assert "Available tools:\n(none)" in prompt


def test_no_tools_shows_none():
    assert "Available tools:\n(none)" in build_system_prompt(SystemPromptOptions(cwd="/repo"))


def test_bash_exploration_guideline_only_without_search_tools():
    with_bash_only = prompt_for(["read", "bash"])
    with_grep = prompt_for(["read", "bash", "grep"])

    assert BASH_EXPLORATION_GUIDELINE in with_bash_only
    assert BASH_EXPLORATION_GUIDELINE not in with_grep


def test_guidelines_end_with_the_always_pair():
    prompt = prompt_for(["read", "bash", "edit", "write"])
    guidelines = prompt.split("Guidelines:\n", 1)[1].split("\nCurrent working directory")[0]

    assert guidelines.split("\n")[-2:] == [f"- {line}" for line in ALWAYS_GUIDELINES]


def test_guidelines_are_deduplicated():
    prompt = prompt_for(["read", "bash", "edit", "write", "grep", "find", "ls"])
    guidelines = (
        prompt.split("Guidelines:\n", 1)[1].split("\nCurrent working directory")[0].split("\n")
    )

    assert len(guidelines) == len(set(guidelines))


def test_project_context_block():
    prompt = build_system_prompt(
        SystemPromptOptions(
            cwd="/repo", context_files=[ContextFile(path="AGENTS.md", content="house rules")]
        )
    )

    assert "<project_context>" in prompt
    assert '<project_instructions path="AGENTS.md">\nhouse rules\n</project_instructions>' in prompt
    assert "</project_context>" in prompt


def test_skills_require_the_read_tool():
    skills = [Skill(name="review", description="d", file_path="/a")]

    with_read = prompt_for(["read"], skills=skills)
    without_read = prompt_for(["bash"], skills=skills)

    assert "<available_skills>" in with_read
    assert "<available_skills>" not in without_read


def test_cwd_is_always_last():
    prompt = prompt_for(
        ["read"],
        skills=[Skill(name="s", description="d", file_path="/a")],
        context_files=[ContextFile(path="AGENTS.md", content="rules")],
    )

    assert prompt.endswith("\nCurrent working directory: /repo")


def test_windows_separators_are_normalised():
    prompt = build_system_prompt(SystemPromptOptions(cwd="C:\\repo\\project"))

    assert prompt.endswith("Current working directory: C:/repo/project")


def test_append_system_prompt():
    prompt = prompt_for(["read"], append_system_prompt="Extra house style.")

    assert "Extra house style." in prompt


def test_custom_prompt_replaces_the_body_but_keeps_the_tail():
    prompt = build_system_prompt(
        SystemPromptOptions(
            cwd="/repo",
            custom_prompt="You are a haiku bot.",
            tools=create_tools(("read",), "/repo"),
            skills=[Skill(name="s", description="d", file_path="/a")],
            context_files=[ContextFile(path="AGENTS.md", content="rules")],
        )
    )

    assert prompt.startswith("You are a haiku bot.")
    assert "Available tools:" not in prompt
    assert "<project_context>" in prompt
    assert "<available_skills>" in prompt
    assert prompt.endswith("Current working directory: /repo")


def test_self_docs_section_is_omitted_when_unset():
    assert "documentation" not in prompt_for(["read"])


def test_self_docs_section_points_at_pipy_not_pi():
    prompt = build_system_prompt(
        SystemPromptOptions(cwd="/repo", self_docs=SelfDocs(readme="/x/README.md", docs="/x/docs"))
    )

    assert "PiPy documentation" in prompt
    assert "/x/README.md" in prompt
    assert "pi.dev" not in prompt


def test_golden_prompt_for_the_default_four_tools():
    prompt = prompt_for(["read", "bash", "edit", "write"])

    assert prompt == (
        "You are an expert coding assistant operating inside PiPy, a coding agent "
        "harness. You help users by reading files, executing commands, editing code, "
        "and writing new files.\n"
        "\n"
        "Available tools:\n"
        "- read: Read file contents\n"
        "- bash: Execute bash commands (ls, grep, find, etc.)\n"
        "- edit: Make precise file edits with exact text replacement, including "
        "multiple disjoint edits in one call\n"
        "- write: Create or overwrite files\n"
        "\n"
        "In addition to the tools above, you may have access to other custom tools "
        "depending on the project.\n"
        "\n"
        "Guidelines:\n"
        "- Use bash for file operations like ls, rg, find\n"
        "- Use read to examine files instead of cat or sed.\n"
        "- Use edit for precise changes (edits[].oldText must match exactly)\n"
        "- When changing multiple separate locations in one file, use one edit call "
        "with multiple entries in edits[] instead of multiple edit calls\n"
        "- Each edits[].oldText is matched against the original file, not after "
        "earlier edits are applied. Do not emit overlapping or nested edits. Merge "
        "nearby changes into one edit.\n"
        "- Keep edits[].oldText as small as possible while still being unique in the "
        "file. Do not pad with large unchanged regions.\n"
        "- Use write only for new files or complete rewrites.\n"
        "- Be concise in your responses\n"
        "- Show file paths clearly when working with files"
        "\nCurrent working directory: /repo"
    )
