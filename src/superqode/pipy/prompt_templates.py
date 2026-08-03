"""Prompt templates and their argument substitution.

Ported from ``packages/agent/src/harness/prompt-templates.ts`` of
earendil-works/pi (MIT).

A template is a Markdown file whose body becomes the user message, with shell
style positional arguments substituted in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from .config import prompts_dir

_POSITIONAL_RE = re.compile(r"\$(\d+)")
_SLICE_RE = re.compile(r"\$\{@:(\d+)(?::(\d+))?\}")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    name: str
    content: str
    description: str = ""
    file_path: str = ""


@dataclass(slots=True)
class PromptTemplateLoadResult:
    templates: list[PromptTemplate] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def prompt_search_paths(cwd: str | Path) -> list[Path]:
    """Where templates are looked for, most specific first."""
    root = Path(cwd).expanduser().resolve()
    return [
        root / ".pi" / "prompts",
        root / ".superqode" / "pipy" / "prompts",
        prompts_dir(),
    ]


def substitute_args(content: str, args: list[str]) -> str:
    """Substitute positional arguments into a template body.

    ``$1`` is the first argument, ``${@:2}`` everything from the second on,
    ``${@:2:3}`` three arguments starting at the second, and ``$ARGUMENTS`` or
    ``$@`` the whole list joined by spaces. A missing argument becomes empty
    rather than being left as a literal, so a partially applied template still
    reads as prose.
    """

    def positional(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1
        return args[index] if 0 <= index < len(args) else ""

    def sliced(match: re.Match[str]) -> str:
        start = max(0, int(match.group(1)) - 1)
        if match.group(2):
            return " ".join(args[start : start + int(match.group(2))])
        return " ".join(args[start:])

    result = _POSITIONAL_RE.sub(positional, content)
    result = _SLICE_RE.sub(sliced, result)
    joined = " ".join(args)
    result = result.replace("$ARGUMENTS", joined)
    return result.replace("$@", joined)


def load_prompt_templates(
    directories: list[Path] | None = None,
    *,
    cwd: str | Path = ".",
) -> PromptTemplateLoadResult:
    """Load templates, nearest directory winning on name clash."""
    result = PromptTemplateLoadResult()
    seen: set[str] = set()
    for directory in directories if directories is not None else prompt_search_paths(cwd):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            try:
                document = frontmatter.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as error:
                result.diagnostics.append(f"{path}: could not read template: {error}")
                continue
            except Exception as error:  # noqa: BLE001 - malformed frontmatter
                result.diagnostics.append(f"{path}: invalid frontmatter: {error}")
                continue
            metadata = document.metadata or {}
            name = str(metadata.get("name") or path.stem)
            if name in seen:
                continue
            seen.add(name)
            result.templates.append(
                PromptTemplate(
                    name=name,
                    content=document.content,
                    description=str(metadata.get("description") or ""),
                    file_path=str(path),
                )
            )
    return result


def format_prompt_template_invocation(
    template: PromptTemplate,
    args: list[str] | None = None,
) -> str:
    return substitute_args(template.content, list(args or []))


__all__ = [
    "PromptTemplate",
    "PromptTemplateLoadResult",
    "format_prompt_template_invocation",
    "load_prompt_templates",
    "prompt_search_paths",
    "substitute_args",
]
