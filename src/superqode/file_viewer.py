"""
SuperQode File Viewer - Beautiful File Content Display

A rich file viewer with:
- Syntax highlighting for 100+ languages
- Line numbers
- Search highlighting
- Scrollable content
- File info header
"""

from __future__ import annotations

import os
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.table import Table
from rich.box import ROUNDED, SIMPLE


# Language detection by extension
LANGUAGE_MAP = {
    # Python
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    ".pyx": "python",
    # JavaScript/TypeScript
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".mjs": "javascript",
    ".cjs": "javascript",
    # Web
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".vue": "vue",
    ".svelte": "svelte",
    # Data formats
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".csv": "text",
    # Shell
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".fish": "fish",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    # Systems
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".swift": "swift",
    # Other languages
    ".rb": "ruby",
    ".php": "php",
    ".pl": "perl",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
    ".jl": "julia",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".fs": "fsharp",
    ".clj": "clojure",
    ".lisp": "lisp",
    ".scm": "scheme",
    # Config files
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".env": "dotenv",
    ".gitignore": "gitignore",
    ".dockerignore": "gitignore",
    ".editorconfig": "ini",
    # Documentation
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".log": "text",
    # Database
    ".sql": "sql",
    ".sqlite": "sql",
    # Build/Config
    "Makefile": "makefile",
    "Dockerfile": "dockerfile",
    ".dockerfile": "dockerfile",
    "Vagrantfile": "ruby",
    "Gemfile": "ruby",
    "Rakefile": "ruby",
    "CMakeLists.txt": "cmake",
    # Other
    ".diff": "diff",
    ".patch": "diff",
    ".graphql": "graphql",
    ".proto": "protobuf",
    ".tf": "terraform",
    ".hcl": "hcl",
}

# File type icons
FILE_ICONS = {
    "python": "🐍",
    "javascript": "📜",
    "typescript": "💠",
    "html": "🌐",
    "css": "🎨",
    "json": "📋",
    "yaml": "⚙️",
    "markdown": "📝",
    "rust": "🦀",
    "go": "🐹",
    "java": "☕",
    "ruby": "💎",
    "php": "🐘",
    "bash": "💻",
    "sql": "🗄️",
    "dockerfile": "🐳",
    "default": "📄",
}

# SuperQode viewer colors
VIEWER_COLORS = {
    "header": "#a855f7",
    "border": "#2a2a2a",
    "line_no": "#52525b",
    "highlight": "#f59e0b30",
    "search": "#22c55e40",
    "info": "#71717a",
}


@dataclass
class FileInfo:
    """Information about a file."""

    path: str
    name: str
    extension: str
    language: str
    size: int
    lines: int
    encoding: str = "utf-8"
    is_binary: bool = False


def detect_language(path: str) -> str:
    """Detect the programming language from file path."""
    p = Path(path)
    name = p.name
    ext = p.suffix.lower()

    # Check exact filename matches first
    if name in LANGUAGE_MAP:
        return LANGUAGE_MAP[name]

    # Check extension
    if ext in LANGUAGE_MAP:
        return LANGUAGE_MAP[ext]

    return "text"


def get_file_icon(language: str) -> str:
    """Get an icon for a language."""
    return FILE_ICONS.get(language, FILE_ICONS["default"])


def get_file_info(path: str) -> FileInfo:
    """Get information about a file."""
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    stat = p.stat()
    ext = p.suffix.lower()
    language = detect_language(path)

    # Check if binary
    is_binary = False
    try:
        with open(p, "rb") as f:
            chunk = f.read(8192)
            if b"\x00" in chunk:
                is_binary = True
    except Exception:
        pass

    # Count lines
    lines = 0
    if not is_binary:
        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = sum(1 for _ in f)
        except Exception:
            pass

    return FileInfo(
        path=str(p.resolve()),
        name=p.name,
        extension=ext,
        language=language,
        size=stat.st_size,
        lines=lines,
        is_binary=is_binary,
    )


def format_size(size: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class FileViewer:
    """Interactive file viewer with syntax highlighting."""

    def __init__(self, console: Console):
        self.console = console
        self.current_file: Optional[str] = None
        self.content: Optional[str] = None
        self.info: Optional[FileInfo] = None
        self.scroll_offset: int = 0
        self.search_term: Optional[str] = None
        self.highlight_lines: List[int] = []

    def open(self, path: str) -> bool:
        """Open a file for viewing."""
        try:
            self.info = get_file_info(path)

            if self.info.is_binary:
                self.content = None
                return True

            with open(path, "r", encoding="utf-8") as f:
                self.content = f.read()

            self.current_file = path
            self.scroll_offset = 0
            self.search_term = None
            self.highlight_lines = []
            return True

        except Exception as e:
            self.console.print(f"  [red]Error opening file: {e}[/red]")
            return False

    def render(
        self,
        start_line: int = 1,
        end_line: Optional[int] = None,
        show_header: bool = True,
        theme: str = "monokai",
    ) -> None:
        """Render the file content."""
        if self.info is None:
            self.console.print("  [dim]No file open[/dim]")
            return

        if show_header:
            self._render_header()

        if self.info.is_binary:
            self.console.print("  [dim]Binary file - cannot display content[/dim]")
            return

        if self.content is None:
            self.console.print("  [dim]No content to display[/dim]")
            return

        # Get content slice
        lines = self.content.splitlines()
        total_lines = len(lines)

        if end_line is None:
            end_line = min(start_line + 50, total_lines)  # Default 50 lines

        start_idx = max(0, start_line - 1)
        end_idx = min(end_line, total_lines)

        content_slice = "\n".join(lines[start_idx:end_idx])

        # Create syntax highlighted view
        syntax = Syntax(
            content_slice,
            self.info.language,
            theme=theme,
            line_numbers=True,
            start_line=start_line,
            word_wrap=True,
            highlight_lines=set(self.highlight_lines) if self.highlight_lines else None,
            background_color="#000000",
        )

        self.console.print(
            Panel(syntax, border_style=VIEWER_COLORS["border"], box=ROUNDED, padding=(0, 1))
        )

        # Show position info
        if total_lines > end_idx:
            self.console.print(
                f"  [dim]Showing lines {start_line}-{end_idx} of {total_lines}[/dim]"
            )

    def _render_header(self) -> None:
        """Render the file header."""
        if self.info is None:
            return

        icon = get_file_icon(self.info.language)

        header = Text()
        header.append(f" {icon} ", style="bold")
        header.append(self.info.name, style="bold white")
        header.append("  ", style="")
        header.append(f"[{self.info.language}]", style="bold cyan")
        header.append("  ", style="")
        header.append(format_size(self.info.size), style="dim")
        header.append("  ", style="")
        header.append(f"{self.info.lines} lines", style="dim")

        self.console.print(
            Panel(header, border_style=VIEWER_COLORS["header"], box=ROUNDED, padding=(0, 1))
        )

    def search(self, term: str) -> List[Tuple[int, str]]:
        """Search for a term in the file content."""
        if self.content is None:
            return []

        self.search_term = term
        results = []
        self.highlight_lines = []

        for i, line in enumerate(self.content.splitlines(), 1):
            if term.lower() in line.lower():
                results.append((i, line.strip()))
                self.highlight_lines.append(i)

        return results

    def goto_line(self, line: int) -> None:
        """Jump to a specific line."""
        if self.content is None:
            return

        total_lines = len(self.content.splitlines())
        line = max(1, min(line, total_lines))
        self.scroll_offset = line - 1
        self.render(start_line=line)

    def render_search_results(self, results: List[Tuple[int, str]], max_results: int = 10) -> None:
        """Render search results."""
        if not results:
            self.console.print(f"  [dim]No matches found for '{self.search_term}'[/dim]")
            return

        header = Text()
        header.append(f" 🔍 ", style="bold")
        header.append(f"{len(results)} match(es)", style="bold white")
        header.append(f" for '{self.search_term}'", style="dim")

        self.console.print(Panel(header, border_style="#06b6d4", box=ROUNDED, padding=(0, 1)))

        for line_no, content in results[:max_results]:
            line = Text()
            line.append(f"  {line_no:>4}: ", style=VIEWER_COLORS["line_no"])

            # Highlight search term
            content_lower = content.lower()
            term_lower = self.search_term.lower() if self.search_term else ""

            if term_lower in content_lower:
                idx = content_lower.index(term_lower)
                line.append(content[:idx], style="")
                line.append(content[idx : idx + len(term_lower)], style="bold yellow on #f59e0b30")
                line.append(content[idx + len(term_lower) :], style="")
            else:
                line.append(content, style="")

            self.console.print(line)

        if len(results) > max_results:
            self.console.print(f"  [dim]... and {len(results) - max_results} more[/dim]")


def render_file(
    console: Console,
    path: str,
    start_line: int = 1,
    end_line: Optional[int] = None,
    theme: str = "monokai",
) -> None:
    """Render a file with syntax highlighting (simple interface)."""
    viewer = FileViewer(console)
    if viewer.open(path):
        viewer.render(start_line, end_line, theme=theme)


def render_file_preview(
    console: Console, path: str, max_lines: int = 20, theme: str = "monokai"
) -> None:
    """Render a preview of a file (first N lines)."""
    viewer = FileViewer(console)
    if viewer.open(path):
        viewer.render(1, max_lines, theme=theme)


def render_file_info(console: Console, path: str) -> None:
    """Render file information without content."""
    try:
        info = get_file_info(path)
        icon = get_file_icon(info.language)

        table = Table(show_header=False, box=SIMPLE, padding=(0, 2))
        table.add_column("Property", style="dim")
        table.add_column("Value", style="white")

        table.add_row("Name", f"{icon} {info.name}")
        table.add_row("Path", info.path)
        table.add_row("Language", info.language)
        table.add_row("Size", format_size(info.size))
        table.add_row("Lines", str(info.lines))
        table.add_row("Binary", "Yes" if info.is_binary else "No")

        console.print(
            Panel(
                table,
                title="[bold]File Info[/bold]",
                border_style=VIEWER_COLORS["header"],
                box=ROUNDED,
            )
        )

    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")
