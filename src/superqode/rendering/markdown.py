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


def _live_theme() -> dict[str, str]:
    """Load the mutable TUI palette lazily to avoid an app/widget import cycle."""
    from superqode.app.constants import THEME

    return THEME


_FENCED_MARKDOWN_RE = re.compile(
    r"```(?:md|markdown)\s*\n(?P<body>.*?)\n```",
    flags=re.IGNORECASE | re.DOTALL,
)


class AgentHeading(Heading):
    """Restrained headings for terminal chat output."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text.copy()
        text.justify = "left"
        level = int(self.tag[1:]) if self.tag[1:].isdigit() else 2
        theme = _live_theme()
        color = theme["purple"] if level <= 2 else theme["pink"]
        prefix = "▌ " if level <= 2 else "• "
        yield Text(prefix, style=f"bold {color}") + Text(text.plain, style=f"bold {color}")


class AgentCodespan(Text):
    """Inline code with subtle purple tint."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        theme = _live_theme()
        text = self.copy()
        text.stylize(f"bold {theme['purple']} on {theme.get('code_bg', theme['bg'])}")
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
        theme = _live_theme()
        code = str(self.text).rstrip()
        lang = (self.lexer_name or "text").strip() or "text"
        lexer = self.NORMALIZE_LEXER.get(lang.lower(), lang)
        icon = self.LANG_ICONS.get(lexer.lower(), self.LANG_ICONS.get(lang.lower(), "📄"))
        # Validate lexer against Pygments; fall back to plain text instead of crashing.
        try:
            from pygments.lexers import get_lexer_by_name

            get_lexer_by_name(lexer)
        except Exception:
            try:
                lexer = Syntax.guess_lexer(code, default="text")
            except Exception:
                lexer = "text"
        # Strip shell/REPL prompts so `$ ls` / `>>> print()` highlight cleanly.
        if lexer == "bash":
            code = re.sub(r"(?m)^\s*\$\s?", "", code)
        elif lexer in ("python", "pycon"):
            code = re.sub(r"(?m)^\s*>>>\s?", "", code)
            code = re.sub(r"(?m)^\s*\.\.\.\s?", "", code)
        lines = code.splitlines()
        line_count = len(lines)
        show_line_numbers = line_count >= 3
        try:
            syntax = Syntax(
                code,
                lexer,
                theme=self.theme,
                word_wrap=False,
                line_numbers=show_line_numbers,
                padding=(0, 1),
                background_color=theme.get("code_bg", theme["bg"]),
            )
        except Exception:
            syntax = Syntax(
                code,
                "text",
                theme=self.theme,
                word_wrap=False,
                line_numbers=show_line_numbers,
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
            title=f"[bold {theme['purple']}]{icon} {lang}[/]{title_suffix}",
            border_style=theme["purple"],
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
    from superqode.app.theme_bridge import active_theme_name

    theme = _live_theme()
    code_themes = {
        "superqode": "monokai",
        "tokyonight": "github-dark",
        "dracula": "dracula",
        "nord": "nord",
        "monokai": "monokai",
        "gruvbox": "gruvbox-dark",
        "high-contrast": "github-dark",
    }
    return AgentMarkdown(
        normalize_agent_markdown(text),
        code_theme=kwargs.pop("code_theme", code_themes.get(active_theme_name(), "monokai")),
        style=kwargs.pop("style", theme["text"]),
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
