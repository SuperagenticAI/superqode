"""Markdown rendering helpers for agent output."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import CodeBlock, Heading, Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

import superqode.code_theme  # noqa: F401  (registers the "superqode" Pygments style)

# NOTE: Only code output is brand-green (AgentCodeBlock panel +
# AgentCodespan). Prose elements (lists, tables, headings, links,
# quotes, hr) intentionally use neutral styles so the transcript
# doesn't look all-green.
_BRAND_GREEN = "#7fb069"
_BRANDED_CODE_STYLES = {
    "markdown.code": _BRAND_GREEN,
    "markdown.code_block": _BRAND_GREEN,
}


_MARKDOWN_TABLE_RE = re.compile(
    r"(?m)^\s*\|?.+\|.+\n\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


def _live_theme() -> dict[str, str]:
    """Load the mutable TUI palette lazily to avoid an app/widget import cycle."""
    from superqode.app.constants import THEME

    return THEME


# Brand-fixed colors for agent output. These must never follow
# theme_bridge.apply_theme(), otherwise any non-superqode palette
# repaints code-block chrome cyan/blue via primary_bright/info.
_BRAND_THEME = {
    "green": "#7fb069",
    "pink": "#ec4899",
    "text": "#e4e4e7",
    "bg": "default",
    "code_bg": "default",
}


def _brand_theme() -> dict[str, str]:
    """Brand palette for agent markdown (immune to :theme switches)."""
    return _BRAND_THEME


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
    """Theme-aware headings; code keeps brand green separately."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text.copy()
        text.justify = "left"
        level = int(self.tag[1:]) if self.tag[1:].isdigit() else 2
        theme = _live_theme()
        color = theme.get("text", "#e4e4e7")
        prefix = "▌ " if level <= 2 else "• "
        yield Text(prefix, style=f"bold {color}") + Text(text.plain, style=f"bold {color}")


class AgentCodespan(Text):
    """Inline code with subtle brand tint (always green, theme-independent)."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        theme = _brand_theme()
        text = self.copy()
        text.stylize(f"{theme['green']} on {theme.get('code_bg', theme['bg'])}")
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
        theme = _brand_theme()
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
            theme="superqode",
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
            border_style=theme["green"],
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

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        # Only code spans/blocks get brand green. Everything else
        # (lists, tables, headings, links, quotes) keeps Rich defaults
        # so prose stays neutral.
        from rich.theme import Theme

        brand = Theme(_BRANDED_CODE_STYLES)
        with console.use_theme(brand):
            yield from super().__rich_console__(console, options)


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
    theme = _live_theme()
    return AgentMarkdown(
        normalize_agent_markdown(text),
        code_theme=kwargs.pop("code_theme", active_code_theme()),
        style=kwargs.pop("style", theme["text"]),
        hyperlinks=kwargs.pop("hyperlinks", False),
        **kwargs,
    )


def active_code_theme() -> str:
    """Return the Pygments theme matching the active TUI theme."""
    # Brand decision: agent code blocks always use the SuperQode green
    # Pygments style regardless of the selected TUI theme, so code never
    # renders cyan/blue (e.g. monokai/github-dark defaults).
    return "superqode"


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
