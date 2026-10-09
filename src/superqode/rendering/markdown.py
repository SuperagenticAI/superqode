"""Markdown rendering helpers for agent output."""

from __future__ import annotations

import re
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import CodeBlock, Heading, Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.style import Style
from rich.text import Text

import superqode.code_theme  # noqa: F401  (registers the "superqode" Pygments style)
from superqode.code_theme import SemanticSyntaxTheme

_render_palette = ContextVar("markdown_palette", default=None)

_MARKDOWN_TABLE_RE = re.compile(
    r"(?m)^\s*\|?.+\|.+\n\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


def _live_theme() -> dict[str, str]:
    """Load the mutable TUI palette lazily to avoid an app/widget import cycle."""
    from superqode.app.constants import THEME

    return _render_palette.get() or THEME


def _code_palette() -> dict[str, str]:
    """Use theme roles, preserving brand green in the default palette."""
    theme = _live_theme()
    return {**theme, "green": theme["md_code"]}


_FENCED_MARKDOWN_RE = re.compile(
    r"```(?:md|markdown)\s*\n(?P<body>.*?)\n```",
    flags=re.IGNORECASE | re.DOTALL,
)


@lru_cache(maxsize=64)
def _validated_lexer_name(name: str) -> str:
    """Return a Pygments lexer name, cached for the streaming hot path."""
    try:
        from pygments.lexers import get_lexer_by_name

        get_lexer_by_name(name)
    except Exception:
        return "text"
    return name


class AgentHeading(Heading):
    """Compact theme-aware headings."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text.copy()
        text.justify = "left"
        level = int(self.tag[1:]) if self.tag[1:].isdigit() else 2
        theme = _live_theme()
        color = theme["md_heading"]
        prefix = "▌ " if level <= 2 else "• "
        style = Style(color=color, bold=True, meta={"sq_fg": "md_heading"})
        yield Text(prefix, style=style) + Text(text.plain, style=style)


class AgentCodespan(Text):
    """Inline code using the selected palette's code role."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        theme = _code_palette()
        text = self.copy()
        text.stylize(
            Style(
                color=theme["green"],
                bgcolor=theme["code_bg"],
                meta={"sq_fg": "md_code", "sq_bg": "code_bg"},
            )
        )
        yield text


class AgentCodeBlock(CodeBlock):
    """Code fences rendered as compact SuperQode-style panels."""

    LANG_ICONS = {
        "python": "🐍",
        "py": "🐍",
        "python3": "🐍",
        "py3": "🐍",
        "bash": "⚡",
        "sh": "⚡",
        "shell": "⚡",
        "zsh": "⚡",
        "console": "⚡",
        "terminal": "⚡",
        "shell-session": "⚡",
        "javascript": "📜",
        "js": "📜",
        "typescript": "💠",
        "ts": "💠",
        "jsx": "💠",
        "tsx": "💠",
        "json": "📋",
        "yaml": "📝",
        "yml": "📝",
        "toml": "⚙️",
        "html": "🌐",
        "css": "🎨",
        "sql": "🗄",
        "go": "🐹",
        "golang": "🐹",
        "rust": "🦀",
        "rs": "🦀",
        "java": "☕",
        "ruby": "💎",
        "dockerfile": "🐳",
        "docker": "🐳",
        "diff": "±",
        "markdown": "📖",
        "md": "📖",
    }

    NORMALIZE_LEXER = {
        "py": "python",
        "python3": "python",
        "py3": "python",
        "pycon": "pycon",
        "sh": "bash",
        "shell": "bash",
        "zsh": "bash",
        "console": "bash",
        "shell-session": "bash",
        "shellsession": "bash",
        "terminal": "bash",
        "js": "javascript",
        "ts": "typescript",
        "jsx": "jsx",
        "tsx": "tsx",
        "yml": "yaml",
        "rs": "rust",
        "golang": "go",
        "docker": "dockerfile",
        "md": "markdown",
    }

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        theme = _code_palette()
        code = str(self.text).rstrip()
        lang = (self.lexer_name or "text").strip() or "text"
        lexer = _validated_lexer_name(self.NORMALIZE_LEXER.get(lang.lower(), lang))
        icon = self.LANG_ICONS.get(lexer.lower(), self.LANG_ICONS.get(lang.lower(), "📄"))
        # Strip copied prompts so the source itself receives syntax colors.
        if lexer == "bash":
            code = re.sub(r"(?m)^\s*\$\s?", "", code)
        elif lexer in ("python", "pycon"):
            code = re.sub(r"(?m)^\s*>>>\s?", "", code)
            code = re.sub(r"(?m)^\s*\.\.\.\s?", "", code)
        line_count = code.count("\n") + 1 if code else 0
        syntax = Syntax(
            code,
            lexer,
            theme=SemanticSyntaxTheme(_live_theme()),
            # Wrapping a large code fence multiplies layout and render work.
            # Keep code horizontally stable and let the transcript clip it.
            word_wrap=False,
            line_numbers=line_count >= 3,
            padding=(0, 1),
            background_color=theme.get("code_bg", theme["bg"]),
        )
        title_suffix = (
            f" [dim]({line_count} line{'s' if line_count != 1 else ''})[/]"
            if line_count > 1
            else ""
        )
        yield Panel(
            syntax,
            title=f"[{theme['green']}]{icon} {lang}[/]{title_suffix}",
            border_style=theme["md_code_border"],
            padding=(0, 0),
        )


class AgentMarkdown(Markdown):
    """Rich Markdown tuned for compact coding-agent transcript output."""

    elements = {
        **Markdown.elements,
        "heading_open": AgentHeading,
        "fence": AgentCodeBlock,
        "code_block": AgentCodeBlock,
        "codespan_open": AgentCodespan,
    }

    def __init__(self, *args, palette=None, **kwargs):
        self.palette = palette
        super().__init__(*args, **kwargs)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        # A context-local palette keeps preview rendering isolated from the app.
        from rich.theme import Theme

        token = _render_palette.set(self.palette)
        try:
            theme = _live_theme()
            brand = Theme(
                {
                    "markdown.code": theme["md_code"],
                    "markdown.code_block": theme["md_code_block"],
                    "markdown.h1": theme["md_heading"],
                    "markdown.h2": theme["md_heading"],
                    "markdown.link": theme["link"],
                    "markdown.link_url": theme["md_link_url"],
                    "markdown.block_quote": theme["md_quote"],
                    "markdown.list": theme["text"],
                    "markdown.item.bullet": theme["md_bullet"],
                    "markdown.item.number": theme["md_bullet"],
                    "markdown.hr": theme["md_hr"],
                    "markdown.table.border": theme["border"],
                    "markdown.table.header": theme["md_heading"],
                }
            )
            with console.use_theme(brand):
                yield from super().__rich_console__(console, options)
        finally:
            _render_palette.reset(token)


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
    theme = kwargs.get("palette") or _live_theme()
    return AgentMarkdown(
        normalize_agent_markdown(text),
        code_theme=kwargs.pop("code_theme", active_code_theme()),
        style=kwargs.pop("style", theme["text"]),
        hyperlinks=kwargs.pop("hyperlinks", False),
        **kwargs,
    )


def active_code_theme() -> SemanticSyntaxTheme:
    """Return semantic syntax styles for all SuperQode code views."""
    return SemanticSyntaxTheme()


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
