"""System prompt assembly.

Ported from ``packages/coding-agent/src/core/system-prompt.ts`` of
earendil-works/pi (MIT).

The shape is pi's: a short preamble, the tool list built from each tool's own
one-line snippet, deduplicated guidelines, a self-documentation pointer, then
project context, skills, and the working directory last. Only the
self-documentation section names SuperQode instead of pi, because pointing a
model at pi.dev from inside PiPy would be wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .resources import ContextFile
from .skills import Skill, format_skills_for_prompt
from .tools.base import AgentTool

PREAMBLE = (
    "You are an expert coding assistant operating inside PiPy, a coding agent "
    "harness. You help users by reading files, executing commands, editing code, "
    "and writing new files."
)

#: Appended after any tool-contributed guidelines, always, and in this order.
ALWAYS_GUIDELINES: tuple[str, ...] = (
    "Be concise in your responses",
    "Show file paths clearly when working with files",
)

#: Added only when bash is the sole way to explore the tree.
BASH_EXPLORATION_GUIDELINE = "Use bash for file operations like ls, rg, find"


@dataclass(slots=True)
class SelfDocs:
    """Where the model should read when asked about PiPy itself."""

    readme: str = ""
    docs: str = ""
    examples: str = ""

    @property
    def available(self) -> bool:
        return bool(self.readme or self.docs or self.examples)


@dataclass(slots=True)
class SystemPromptOptions:
    cwd: str | Path = "."
    tools: list[AgentTool] = field(default_factory=list)
    context_files: list[ContextFile] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    #: Replaces the whole default prompt. Context, skills and cwd are still
    #: appended, matching pi's custom-prompt branch.
    custom_prompt: str | None = None
    #: Appended verbatim after the prompt body.
    append_system_prompt: str | None = None
    self_docs: SelfDocs = field(default_factory=SelfDocs)


def _tools_list(tools: list[AgentTool]) -> str:
    # A tool appears here only when it carries a one-line snippet. That is pi's
    # rule and it is what lets an extension add a tool without it silently
    # bloating the prompt.
    visible = [tool for tool in tools if tool.prompt_snippet]
    if not visible:
        return "(none)"
    return "\n".join(f"- {tool.name}: {tool.prompt_snippet}" for tool in visible)


def _guidelines(tools: list[AgentTool]) -> str:
    names = {tool.name for tool in tools}
    ordered: list[str] = []
    seen: set[str] = set()

    def add(guideline: str) -> None:
        normalized = guideline.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)

    if "bash" in names and not ({"grep", "find", "ls"} & names):
        add(BASH_EXPLORATION_GUIDELINE)
    for tool in tools:
        for guideline in tool.prompt_guidelines:
            add(guideline)
    for guideline in ALWAYS_GUIDELINES:
        add(guideline)

    return "\n".join(f"- {guideline}" for guideline in ordered)


def _project_context(context_files: list[ContextFile]) -> str:
    if not context_files:
        return ""
    parts = ["\n\n<project_context>\n\n", "Project-specific instructions and guidelines:\n\n"]
    for entry in context_files:
        parts.append(
            f'<project_instructions path="{entry.path}">\n{entry.content}\n'
            "</project_instructions>\n\n"
        )
    parts.append("</project_context>\n")
    return "".join(parts)


def _self_docs_section(docs: SelfDocs) -> str:
    if not docs.available:
        return ""
    lines = [
        "\n\nPiPy documentation (read only when the user asks about PiPy itself, "
        "its SDK, extensions, skills, or session tree):",
    ]
    if docs.readme:
        lines.append(f"- Main documentation: {docs.readme}")
    if docs.docs:
        lines.append(f"- Additional docs: {docs.docs}")
    if docs.examples:
        lines.append(f"- Examples: {docs.examples}")
    lines.append(
        "- When working on PiPy topics, read the docs and follow .md "
        "cross-references before implementing"
    )
    return "\n".join(lines)


def build_system_prompt(options: SystemPromptOptions) -> str:
    """Assemble the prompt for one turn."""
    prompt_cwd = str(options.cwd).replace("\\", "/")
    append_section = f"\n\n{options.append_system_prompt}" if options.append_system_prompt else ""

    if options.custom_prompt:
        prompt = options.custom_prompt + append_section
        prompt += _project_context(options.context_files)
        # Skills are only useful when the model can read their files.
        if any(tool.name == "read" for tool in options.tools) and options.skills:
            prompt += format_skills_for_prompt(options.skills)
        return prompt + f"\nCurrent working directory: {prompt_cwd}"

    prompt = (
        f"{PREAMBLE}\n\n"
        f"Available tools:\n{_tools_list(options.tools)}\n\n"
        "In addition to the tools above, you may have access to other custom "
        "tools depending on the project.\n\n"
        f"Guidelines:\n{_guidelines(options.tools)}"
    )
    prompt += _self_docs_section(options.self_docs)
    prompt += append_section
    prompt += _project_context(options.context_files)
    if any(tool.name == "read" for tool in options.tools) and options.skills:
        prompt += format_skills_for_prompt(options.skills)
    return prompt + f"\nCurrent working directory: {prompt_cwd}"


__all__ = [
    "ALWAYS_GUIDELINES",
    "BASH_EXPLORATION_GUIDELINE",
    "PREAMBLE",
    "SelfDocs",
    "SystemPromptOptions",
    "build_system_prompt",
]
