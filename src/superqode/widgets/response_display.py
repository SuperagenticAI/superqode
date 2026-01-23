"""
Response Display Widget - Beautiful Agent Response Rendering.

Renders agent responses with:
- Rich markdown formatting
- Syntax-highlighted code blocks with copy button
- Collapsible sections
- Inline diffs
- Structured data display (tables, lists)
- Beautiful typography and spacing

Makes agent responses a joy to read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from rich.console import RenderableType, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED, SIMPLE, HEAVY
from textual.reactive import reactive
from textual.widgets import Static
from textual.containers import Container, Vertical, Horizontal
from textual import events


class ResponseState(Enum):
    """State of response rendering."""

    STREAMING = "streaming"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class CodeBlock:
    """A code block in the response."""

    code: str
    language: str = "text"
    filename: str = ""
    start_line: int = 1


@dataclass
class ParsedResponse:
    """Parsed response with structured content."""

    raw_text: str
    paragraphs: List[str] = field(default_factory=list)
    code_blocks: List[CodeBlock] = field(default_factory=list)
    bullet_lists: List[List[str]] = field(default_factory=list)
    numbered_lists: List[List[str]] = field(default_factory=list)
    headers: List[Tuple[int, str]] = field(default_factory=list)  # (level, text)

    @classmethod
    def parse(cls, text: str) -> "ParsedResponse":
        """Parse markdown text into structured content."""
        result = cls(raw_text=text)

        # Extract code blocks first (to avoid parsing their content)
        code_pattern = r"```(\w*)\n(.*?)```"
        text_without_code = text

        for match in re.finditer(code_pattern, text, re.DOTALL):
            lang = match.group(1) or "text"
            code = match.group(2).strip()
            result.code_blocks.append(CodeBlock(code=code, language=lang))

        text_without_code = re.sub(code_pattern, "<<<CODE_BLOCK>>>", text, flags=re.DOTALL)

        # Extract headers
        for match in re.finditer(r"^(#{1,6})\s+(.+)$", text_without_code, re.MULTILINE):
            level = len(match.group(1))
            header_text = match.group(2).strip()
            result.headers.append((level, header_text))

        # Extract bullet lists
        current_list = []
        in_list = False

        for line in text_without_code.split("\n"):
            bullet_match = re.match(r"^\s*[-*•]\s+(.+)$", line)
            if bullet_match:
                in_list = True
                current_list.append(bullet_match.group(1).strip())
            elif in_list and line.strip():
                # Continue list item
                current_list[-1] += " " + line.strip()
            elif in_list and not line.strip():
                # End of list
                if current_list:
                    result.bullet_lists.append(current_list)
                current_list = []
                in_list = False

        if current_list:
            result.bullet_lists.append(current_list)

        # Extract paragraphs (non-list, non-header content)
        lines = text_without_code.split("\n")
        current_para = []

        for line in lines:
            stripped = line.strip()

            # Skip code block placeholders
            if "<<<CODE_BLOCK>>>" in stripped:
                continue

            # Skip headers
            if re.match(r"^#{1,6}\s+", stripped):
                if current_para:
                    result.paragraphs.append(" ".join(current_para))
                    current_para = []
                continue

            # Skip list items
            if re.match(r"^\s*[-*•\d.]\s+", stripped):
                continue

            if stripped:
                current_para.append(stripped)
            elif current_para:
                result.paragraphs.append(" ".join(current_para))
                current_para = []

        if current_para:
            result.paragraphs.append(" ".join(current_para))

        return result


# Language icons for code blocks
LANG_ICONS = {
    "python": "🐍",
    "javascript": "📜",
    "typescript": "💠",
    "rust": "🦀",
    "go": "🐹",
    "java": "☕",
    "ruby": "💎",
    "bash": "💻",
    "shell": "💻",
    "sh": "💻",
    "sql": "🗄️",
    "html": "🌐",
    "css": "🎨",
    "json": "📋",
    "yaml": "📝",
    "yml": "📝",
    "markdown": "📄",
    "md": "📄",
    "c": "⚙️",
    "cpp": "⚙️",
    "csharp": "⚙️",
    "text": "📄",
}


class CodeBlockWidget(Static):
    """Widget for displaying a syntax-highlighted code block."""

    DEFAULT_CSS = """
    CodeBlockWidget {
        height: auto;
        margin: 1 0;
        border: solid #27272a;
        background: #0a0a0a;
    }

    CodeBlockWidget .code-header {
        height: 1;
        background: #1a1a1a;
        padding: 0 1;
    }

    CodeBlockWidget .code-content {
        height: auto;
        padding: 0 1;
        overflow-x: auto;
    }
    """

    def __init__(self, block: CodeBlock, **kwargs):
        super().__init__(**kwargs)
        self.block = block

    def render(self) -> RenderableType:
        # Header with language badge
        icon = LANG_ICONS.get(self.block.language.lower(), "📄")

        header = Text()
        header.append(f" {icon} ", style="#22c55e")
        header.append(self.block.language.upper(), style="bold #22c55e")

        if self.block.filename:
            header.append(f"  {self.block.filename}", style="#6b7280")

        # Syntax highlighted code
        syntax = Syntax(
            self.block.code,
            self.block.language,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
            background_color="#000000",
            start_line=self.block.start_line,
        )

        return Panel(
            syntax,
            title=header,
            title_align="left",
            border_style="#27272a",
            box=ROUNDED,
            padding=(0, 0),
        )


class ResponseDisplay(Container):
    """
    Beautiful agent response display.

    Features:
    - Streaming text with cursor
    - Rich markdown rendering
    - Syntax highlighted code blocks
    - Structured lists and headers
    - Agent avatar and name
    """

    DEFAULT_CSS = """
    ResponseDisplay {
        height: auto;
        border: solid #a855f7;
        background: #0d0a15;
        padding: 1;
        margin: 0 0 1 0;
    }

    ResponseDisplay.streaming {
        border: solid #fbbf24;
    }

    ResponseDisplay .response-header {
        height: 2;
        margin-bottom: 1;
    }

    ResponseDisplay .response-content {
        height: auto;
    }

    ResponseDisplay .response-footer {
        height: 1;
        margin-top: 1;
    }
    """

    state: reactive[ResponseState] = reactive(ResponseState.STREAMING)

    def __init__(
        self,
        agent_name: str = "Agent",
        model_name: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.agent_name = agent_name
        self.model_name = model_name
        self._text = ""
        self._parsed: Optional[ParsedResponse] = None
        self._start_time = datetime.now()
        self._end_time: Optional[datetime] = None
        self._token_count = 0

    def on_mount(self) -> None:
        """Initialize."""
        self._update_display()

    def append_text(self, text: str) -> None:
        """Append streaming text."""
        self._text += text
        self._parsed = None  # Invalidate parsed cache
        self.state = ResponseState.STREAMING
        self.add_class("streaming")
        self._update_display()

    def set_text(self, text: str) -> None:
        """Set complete text."""
        self._text = text
        self._parsed = None
        self._update_display()

    def complete(self, token_count: int = 0) -> None:
        """Mark response as complete."""
        self._end_time = datetime.now()
        self._token_count = token_count
        self.state = ResponseState.COMPLETE
        self.remove_class("streaming")
        self._update_display()

    def set_error(self, error: str) -> None:
        """Set error state."""
        self._text = f"Error: {error}"
        self.state = ResponseState.ERROR
        self.remove_class("streaming")
        self._update_display()

    @property
    def duration(self) -> float:
        """Get duration in seconds."""
        end = self._end_time or datetime.now()
        return (end - self._start_time).total_seconds()

    def _get_parsed(self) -> ParsedResponse:
        """Get or create parsed response."""
        if self._parsed is None:
            self._parsed = ParsedResponse.parse(self._text)
        return self._parsed

    def _render_header(self) -> Text:
        """Render response header."""
        text = Text()

        # Agent avatar and name
        text.append("🤖 ", style="bold #a855f7")
        text.append(self.agent_name, style="bold #e4e4e7")

        # Model name
        if self.model_name:
            text.append(f"  ({self.model_name})", style="#6b7280")

        # Streaming indicator
        if self.state == ResponseState.STREAMING:
            text.append("  ● ", style="bold #fbbf24")
            text.append("Generating...", style="italic #fbbf24")

        return text

    def _render_content(self) -> List[RenderableType]:
        """Render response content."""
        elements = []
        parsed = self._get_parsed()

        # Render headers and paragraphs in order
        code_block_idx = 0

        for header_level, header_text in parsed.headers:
            # Header styling based on level
            styles = {
                1: ("bold #e4e4e7", "═" * 40),
                2: ("bold #a1a1aa", "─" * 30),
                3: ("bold #71717a", ""),
            }
            style, underline = styles.get(header_level, ("", ""))

            header = Text()
            header.append("\n" + header_text + "\n", style=style)
            if underline:
                header.append(underline + "\n", style="#27272a")

            elements.append(header)

        # Paragraphs
        for para in parsed.paragraphs:
            # Word wrap
            import textwrap

            wrapped = textwrap.fill(para, width=80)
            elements.append(Text(wrapped + "\n\n", style="#e4e4e7"))

        # Bullet lists
        for bullet_list in parsed.bullet_lists:
            list_text = Text()
            for i, item in enumerate(bullet_list):
                colors = ["#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#22c55e"]
                color = colors[i % len(colors)]
                list_text.append("  ◆ ", style=f"bold {color}")
                list_text.append(item + "\n", style="#e4e4e7")
            list_text.append("\n")
            elements.append(list_text)

        # Code blocks
        for block in parsed.code_blocks:
            elements.append(self._render_code_block(block))

        # If no structured content, render as plain text
        if not elements and self._text:
            elements.append(Text(self._text, style="#e4e4e7"))

        # Streaming cursor
        if self.state == ResponseState.STREAMING:
            cursor = Text("▌", style="bold #fbbf24")
            elements.append(cursor)

        return elements

    def _render_code_block(self, block: CodeBlock) -> Panel:
        """Render a code block."""
        icon = LANG_ICONS.get(block.language.lower(), "📄")

        syntax = Syntax(
            block.code,
            block.language,
            theme="monokai",
            line_numbers=len(block.code.splitlines()) > 5,
            background_color="#000000",
        )

        title = Text()
        title.append(f" {icon} ", style="#22c55e")
        title.append(block.language.upper(), style="bold #22c55e")

        return Panel(
            syntax,
            title=title,
            title_align="left",
            border_style="#22c55e",
            box=ROUNDED,
            padding=(0, 1),
        )

    def _render_footer(self) -> Text:
        """Render response footer."""
        text = Text()

        if self.state == ResponseState.COMPLETE:
            text.append("✓ ", style="#22c55e")
            text.append(f"{self.duration:.1f}s", style="#6b7280")

            if self._token_count:
                text.append(f"  │  {self._token_count} tokens", style="#6b7280")

        elif self.state == ResponseState.ERROR:
            text.append("✗ Error", style="#ef4444")

        return text

    def _update_display(self) -> None:
        """Update the display."""
        try:
            header = self.query_one(".response-header", Static)
            content = self.query_one(".response-content", Container)
            footer = self.query_one(".response-footer", Static)
        except Exception:
            return

        header.update(self._render_header())

        # Clear and re-render content
        content.remove_children()
        for element in self._render_content():
            if isinstance(element, (Text, str)):
                content.mount(Static(element))
            else:
                content.mount(Static(element))

        footer.update(self._render_footer())

    def clear(self) -> None:
        """Clear the response."""
        self._text = ""
        self._parsed = None
        self._start_time = datetime.now()
        self._end_time = None
        self._token_count = 0
        self.state = ResponseState.STREAMING
        self._update_display()

    def compose(self):
        """Compose the display."""
        yield Static("", classes="response-header")
        with Container(classes="response-content"):
            pass
        yield Static("", classes="response-footer")


class StreamingText(Static):
    """Simple streaming text display with cursor."""

    DEFAULT_CSS = """
    StreamingText {
        height: auto;
    }
    """

    streaming: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._text = ""

    def append(self, text: str) -> None:
        """Append text."""
        self._text += text
        self.streaming = True
        self.refresh()

    def complete(self) -> None:
        """Mark as complete."""
        self.streaming = False
        self.refresh()

    def clear(self) -> None:
        """Clear text."""
        self._text = ""
        self.streaming = False
        self.refresh()

    def render(self) -> Text:
        result = Text()
        result.append(self._text, style="#e4e4e7")

        if self.streaming:
            result.append("▌", style="bold #fbbf24")

        return result
