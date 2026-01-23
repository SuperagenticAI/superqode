"""
Code Context Viewer Widget.

A SuperQode-original widget for displaying code with contextual
highlighting, inline diffs, and related issue information.

Design: Smart code display that emphasizes the specific lines
where issues were found, with collapsible related findings.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from rich.console import RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class LineType(Enum):
    """Type of line in the context view."""

    CONTEXT = "context"  # Normal context line
    ADDED = "added"  # Added line (green)
    REMOVED = "removed"  # Removed line (red)
    ISSUE = "issue"  # Line with issue (highlighted)
    FOCUS = "focus"  # The main focus line


@dataclass
class CodeLine:
    """A single line of code with metadata."""

    number: int
    content: str
    line_type: LineType = LineType.CONTEXT
    annotation: str = ""  # Inline annotation (e.g., "← HERE")

    @property
    def prefix(self) -> str:
        """Get the line prefix based on type."""
        if self.line_type == LineType.ADDED:
            return "+"
        elif self.line_type == LineType.REMOVED:
            return "-"
        else:
            return " "


@dataclass
class RelatedFinding:
    """A related finding in other parts of the codebase."""

    file_path: str
    line_number: int
    description: str
    similarity: float = 0.0  # 0.0 to 1.0


@dataclass
class CodeContext:
    """Context for displaying code with an issue."""

    file_path: str
    language: str
    issue_title: str
    issue_description: str = ""
    lines: List[CodeLine] = field(default_factory=list)
    focus_line: Optional[int] = None
    related_findings: List[RelatedFinding] = field(default_factory=list)


# Language detection from file extension
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".md": "markdown",
    ".toml": "toml",
}


def detect_language(file_path: str) -> str:
    """Detect language from file path."""
    for ext, lang in LANGUAGE_MAP.items():
        if file_path.endswith(ext):
            return lang
    return "text"


class CodeContextViewer(Static):
    """Code Context Viewer Widget.

    Displays code with contextual highlighting around issues,
    showing before/after diffs and related findings.

    Usage:
        viewer = CodeContextViewer()
        viewer.set_context(CodeContext(
            file_path="src/api/user.py",
            language="python",
            issue_title="Unhandled null reference",
            lines=[
                CodeLine(23, "def get_user(user_id: str):"),
                CodeLine(24, "    user = db.find(user_id)"),
                CodeLine(25, "    return user.name", LineType.ISSUE, "← HERE"),
            ],
            focus_line=25,
        ))
    """

    DEFAULT_CSS = """
    CodeContextViewer {
        height: auto;
        border: solid #3f3f46;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    # Reactive state
    show_related: reactive[bool] = reactive(False)

    def __init__(
        self,
        title: str = "Code Context",
        show_line_numbers: bool = True,
        context_lines: int = 3,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.title = title
        self.show_line_numbers = show_line_numbers
        self.context_lines = context_lines
        self._context: Optional[CodeContext] = None

    def set_context(self, context: CodeContext) -> None:
        """Set the code context to display."""
        self._context = context
        self.refresh()

    def set_from_diff(
        self,
        file_path: str,
        issue_title: str,
        before: str,
        after: str,
        focus_line: Optional[int] = None,
    ) -> None:
        """Set context from a before/after diff."""
        # Simple diff - just show the change
        before_lines = before.splitlines() if before else []
        after_lines = after.splitlines() if after else []

        lines = []
        language = detect_language(file_path)

        # Build a simple unified view
        max_lines = max(len(before_lines), len(after_lines))

        for i in range(max_lines):
            line_num = i + 1
            before_line = before_lines[i] if i < len(before_lines) else None
            after_line = after_lines[i] if i < len(after_lines) else None

            if before_line == after_line:
                # Unchanged
                lines.append(CodeLine(line_num, after_line or "", LineType.CONTEXT))
            elif before_line is None:
                # Added
                lines.append(CodeLine(line_num, after_line, LineType.ADDED))
            elif after_line is None:
                # Removed
                lines.append(CodeLine(line_num, before_line, LineType.REMOVED))
            else:
                # Changed - show both
                lines.append(CodeLine(line_num, before_line, LineType.REMOVED))
                lines.append(CodeLine(line_num, after_line, LineType.ADDED))

        self._context = CodeContext(
            file_path=file_path,
            language=language,
            issue_title=issue_title,
            lines=lines,
            focus_line=focus_line,
        )
        self.refresh()

    def add_related_finding(self, finding: RelatedFinding) -> None:
        """Add a related finding."""
        if self._context:
            self._context.related_findings.append(finding)
            self.refresh()

    def toggle_related(self) -> None:
        """Toggle visibility of related findings."""
        self.show_related = not self.show_related

    def clear(self) -> None:
        """Clear the context."""
        self._context = None
        self.refresh()

    def _get_line_style(self, line: CodeLine) -> Tuple[str, str]:
        """Get style and prefix for a line type."""
        if line.line_type == LineType.ADDED:
            return "#22c55e", "+"
        elif line.line_type == LineType.REMOVED:
            return "#ef4444", "-"
        elif line.line_type == LineType.ISSUE:
            return "#eab308", "!"
        elif line.line_type == LineType.FOCUS:
            return "#3b82f6", "▶"
        else:
            return "#a1a1aa", " "

    def _render_line(self, line: CodeLine, max_num_width: int) -> Text:
        """Render a single code line."""
        color, prefix = self._get_line_style(line)

        result = Text()

        # Line number (right-aligned)
        if self.show_line_numbers:
            num_str = str(line.number).rjust(max_num_width)
            result.append(f"{num_str} │", style="#6b7280")

        # Prefix (+/-/!)
        result.append(prefix, style=f"bold {color}")

        # Content with background for changes
        if line.line_type == LineType.ADDED:
            result.append(line.content, style=f"{color} on #1a2e1a")
        elif line.line_type == LineType.REMOVED:
            result.append(line.content, style=f"{color} on #2e1a1a")
        elif line.line_type == LineType.ISSUE:
            result.append(line.content, style=f"bold {color}")
        else:
            result.append(line.content, style="#e2e8f0")

        # Annotation
        if line.annotation:
            padding = max(0, 50 - len(line.content))
            result.append(" " * padding)
            result.append(f"  # {line.annotation}", style=f"italic {color}")

        return result

    def render(self) -> RenderableType:
        """Render the code context."""
        content = Text()

        if not self._context:
            content.append("\n  No code context set\n", style="#6b7280")
            return Panel(
                content,
                title=f"[bold #3b82f6]{self.title}[/]",
                border_style="#3f3f46",
            )

        ctx = self._context

        # Issue header
        content.append("  Issue: ", style="#6b7280")
        content.append(ctx.issue_title, style="bold #eab308")
        content.append("\n\n")

        # Code lines
        if ctx.lines:
            max_num_width = len(str(max(line.number for line in ctx.lines)))

            for line in ctx.lines:
                content.append(self._render_line(line, max_num_width))
                content.append("\n")
        else:
            content.append("  No code to display\n", style="#6b7280")

        # Related findings section
        if ctx.related_findings:
            content.append("\n")

            if self.show_related:
                content.append("  ▼ Related: ", style="#6b7280")
                content.append(
                    f"{len(ctx.related_findings)} similar patterns found\n", style="#a1a1aa"
                )

                for finding in ctx.related_findings[:5]:  # Limit to 5
                    content.append("    • ", style="#3f3f46")
                    content.append(f"{finding.file_path}", style="#3b82f6")
                    content.append(f":{finding.line_number}", style="#6b7280")
                    content.append(f" - {finding.description}\n", style="#a1a1aa")
            else:
                content.append("  ▶ Related: ", style="#6b7280")
                content.append(
                    f"{len(ctx.related_findings)} similar patterns found", style="#a1a1aa"
                )
                content.append(" (expand to view)\n", style="#52525b")

        # Build title with file path
        title_text = f"{self.title}: {ctx.file_path}"
        if len(title_text) > 50:
            title_text = f"{self.title}: ...{ctx.file_path[-40:]}"

        return Panel(
            content,
            title=f"[bold #3b82f6]{title_text}[/]",
            border_style="#3f3f46",
            padding=(0, 0),
        )


class CompactCodeContext(CodeContextViewer):
    """Compact version of CodeContextViewer for smaller displays."""

    DEFAULT_CSS = """
    CompactCodeContext {
        height: auto;
        max-height: 12;
        border: solid #3f3f46;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("context_lines", 2)
        super().__init__(**kwargs)
