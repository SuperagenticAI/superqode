"""Markdown rendering helpers for agent output."""

from __future__ import annotations

import re
from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import CodeBlock, Heading, Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text


_MARKDOWN_TABLE_RE = re.compile(
    r"(?m)^\s*\|?.+\|.+\n\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_FENCED_MARKDOWN_RE = re.compile(
    r"```(?:md|markdown)\s*\n(?P<body>.*?)\n```",
    flags=re.IGNORECASE | re.DOTALL,
)


class AgentHeading(Heading):
    """Restrained headings for terminal chat output."""

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        text = self.text.copy()
        text.justify = "left"
        level = int(self.tag[1:]) if self.tag[1:].isdigit() else 2
        color = "#c084fc" if level <= 2 else "#a78bfa"
        prefix = "▌ " if level <= 2 else "• "
        yield Text(prefix, style=f"bold {color}") + Text(text.plain, style=f"bold {color}")


class AgentCodeBlock(CodeBlock):
    """Code fences rendered as compact SuperQode-style panels."""

    LANG_ICONS = {
        "python": "🐍",
        "py": "🐍",
        "javascript": "📜",
        "js": "📜",
        "typescript": "💠",
        "ts": "💠",
        "bash": "🖥",
        "sh": "🖥",
        "shell": "🖥",
        "json": "📋",
        "yaml": "📝",
        "yml": "📝",
        "html": "🌐",
        "css": "🎨",
        "sql": "🗄",
        "go": "🐹",
        "rust": "🦀",
        "java": "☕",
        "ruby": "💎",
    }

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        code = str(self.text).rstrip()
        lang = self.lexer_name or "text"
        icon = self.LANG_ICONS.get(lang.lower(), "📄")
        syntax = Syntax(
            code,
            lang,
            theme=self.theme,
            word_wrap=True,
            padding=(0, 1),
            background_color="#050505",
        )
        yield Panel(
            syntax,
            title=f"[bold #22c55e]{icon} {lang}[/]",
            border_style="#22c55e",
            padding=(0, 0),
        )


class AgentMarkdown(Markdown):
    """Rich Markdown tuned for compact coding-agent transcript output."""

    elements = {
        **Markdown.elements,
        "heading_open": AgentHeading,
        "fence": AgentCodeBlock,
        "code_block": AgentCodeBlock,
    }


def _is_markdown_table(text: str) -> bool:
    return bool(_MARKDOWN_TABLE_RE.search(text.strip()))


def normalize_agent_markdown(text: str) -> str:
    """Prepare agent text for terminal markdown rendering.

    Conservative cleanup only:
    - unwrap ``md``/``markdown`` fences when the fenced body is a real table;
    - collapse excessive blank lines;
    - strip trailing whitespace.
    """
    if not text:
        return ""

    def unwrap_table(match: re.Match[str]) -> str:
        body = match.group("body").strip()
        return body if _is_markdown_table(body) else match.group(0)

    normalized = _FENCED_MARKDOWN_RE.sub(unwrap_table, text)
    normalized = "\n".join(line.rstrip() for line in normalized.splitlines())
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def render_agent_markdown(text: str, **kwargs: Any) -> Markdown:
    """Return a Rich renderable for polished agent markdown."""
    return AgentMarkdown(
        normalize_agent_markdown(text),
        code_theme=kwargs.pop("code_theme", "monokai"),
        style=kwargs.pop("style", "#e5e7eb"),
        hyperlinks=kwargs.pop("hyperlinks", False),
        **kwargs,
    )


def markdown_to_plain_text(text: str) -> str:
    """Convert agent markdown to readable plain text for copy/select exports.

    This intentionally preserves fenced code blocks verbatim while removing
    inline styling noise from prose.
    """
    if not text:
        return ""

    code_blocks: list[str] = []

    def save_code_block(match: re.Match[str]) -> str:
        code_blocks.append(match.group(0))
        return f"@@SUPERQODE_CODE_BLOCK_{len(code_blocks) - 1}@@"

    plain = re.sub(r"```[\w+-]*\n.*?```", save_code_block, text, flags=re.DOTALL)
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", plain)
    plain = re.sub(r"__(.+?)__", r"\1", plain)
    plain = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"\1", plain)
    plain = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"\1", plain)
    plain = re.sub(r"~~(.+?)~~", r"\1", plain)
    plain = re.sub(r"`([^`]+?)`", r"\1", plain)
    plain = re.sub(r"\[([^\]]+?)\]\([^)]+?\)", r"\1", plain)
    plain = re.sub(r"!\[([^\]]*?)\]\([^)]+?\)", r"\1", plain)
    plain = re.sub(r"^>\s*", "", plain, flags=re.MULTILINE)
    plain = re.sub(r"\n{3,}", "\n\n", plain)

    for i, block in enumerate(code_blocks):
        plain = plain.replace(f"@@SUPERQODE_CODE_BLOCK_{i}@@", block)
    return plain.strip()
