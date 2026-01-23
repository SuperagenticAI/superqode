"""
SuperQode Agent Output Display - World's Most Beautiful CLI Agent Output

Features:
- Collapsible thinking/logs section with toggle (Ctrl+T)
- Beautiful final response with rich formatting
- Syntax highlighted code blocks
- Colorful emojis and gradients
- Clear visual separation
- Animated elements
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from time import monotonic

from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.widgets import Static, Collapsible, RichLog
from textual.reactive import reactive
from textual.binding import Binding

from rich.text import Text
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.console import Group
from rich.box import ROUNDED, HEAVY, DOUBLE
from rich.table import Table


# ============================================================================
# THEME - Vibrant SuperQode Colors
# ============================================================================

COLORS = {
    # Primary gradient
    "purple": "#a855f7",
    "magenta": "#d946ef",
    "pink": "#ec4899",
    "rose": "#fb7185",
    "orange": "#f97316",
    "gold": "#fbbf24",
    # Accent colors
    "cyan": "#06b6d4",
    "teal": "#14b8a6",
    "green": "#22c55e",
    "blue": "#3b82f6",
    # Status
    "success": "#22c55e",
    "error": "#ef4444",
    "warning": "#f59e0b",
    "info": "#06b6d4",
    # Backgrounds
    "bg_dark": "#0a0a0a",
    "bg_surface": "#111111",
    "bg_elevated": "#1a1a1a",
    "bg_thinking": "#0d1117",
    "bg_response": "#0f0a1a",
    # Text
    "text": "#e4e4e7",
    "text_muted": "#71717a",
    "text_dim": "#52525b",
    # Borders
    "border": "#2a2a2a",
    "border_active": "#a855f7",
}

# Rainbow gradient for special effects
RAINBOW = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899"]

# Gradient for response header
RESPONSE_GRADIENT = ["#a855f7", "#c026d3", "#d946ef", "#ec4899", "#f43f5e"]


# ============================================================================
# ICONS & EMOJIS
# ============================================================================

THINKING_ICONS = {
    "read": "📖",
    "write": "✏️",
    "search": "🔍",
    "run": "⚡",
    "think": "🧠",
    "analyze": "🔬",
    "create": "🎨",
    "delete": "🗑️",
    "move": "📦",
    "fetch": "🌐",
    "test": "🧪",
    "build": "🔨",
    "deploy": "🚀",
    "debug": "🐛",
    "config": "⚙️",
    "git": "📦",
    "install": "📥",
    "update": "🔄",
}

RESPONSE_DECORATIONS = {
    "sparkle": "✨",
    "star": "⭐",
    "rocket": "🚀",
    "magic": "🪄",
    "gem": "💎",
    "crown": "👑",
    "fire": "🔥",
    "lightning": "⚡",
    "rainbow": "🌈",
    "heart": "💜",
}


def get_thinking_icon(line: str) -> str:
    """Get appropriate icon for a thinking/log line."""
    line_lower = line.lower()

    if any(x in line_lower for x in ["reading", "read", "loading", "fetching"]):
        return THINKING_ICONS["read"]
    elif any(x in line_lower for x in ["writing", "write", "creating", "saving"]):
        return THINKING_ICONS["write"]
    elif any(x in line_lower for x in ["searching", "search", "finding", "looking"]):
        return THINKING_ICONS["search"]
    elif any(x in line_lower for x in ["running", "executing", "command"]):
        return THINKING_ICONS["run"]
    elif any(x in line_lower for x in ["thinking", "analyzing", "processing"]):
        return THINKING_ICONS["think"]
    elif any(x in line_lower for x in ["test", "testing"]):
        return THINKING_ICONS["test"]
    elif any(x in line_lower for x in ["build", "compiling"]):
        return THINKING_ICONS["build"]
    elif any(x in line_lower for x in ["git", "commit", "push", "pull"]):
        return THINKING_ICONS["git"]
    elif any(x in line_lower for x in ["install", "npm", "pip", "yarn"]):
        return THINKING_ICONS["install"]
    elif any(x in line_lower for x in ["error", "fail", "bug"]):
        return THINKING_ICONS["debug"]
    else:
        return "▸"


def strip_markdown(text: str) -> str:
    """Strip markdown formatting from text for clean display."""
    # Strip bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)

    # Strip italic: *text* or _text_
    text = re.sub(r"(?<![*\w])\*([^*]+?)\*(?![*\w])", r"\1", text)
    text = re.sub(r"(?<![_\w])_([^_]+?)_(?![_\w])", r"\1", text)

    # Strip strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"\1", text)

    # Strip inline code: `code`
    text = re.sub(r"`([^`]+?)`", r"\1", text)

    # Strip links: [text](url) -> text
    text = re.sub(r"\[([^\]]+?)\]\([^)]+?\)", r"\1", text)

    # Strip images: ![alt](url) -> alt
    text = re.sub(r"!\[([^\]]*?)\]\([^)]+?\)", r"\1", text)

    # Strip blockquotes: > text -> text
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)

    # Strip headers: # text -> text (keep the text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    return text


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class ThinkingLine:
    """A single line of thinking/log output."""

    text: str
    icon: str = ""
    timestamp: float = field(default_factory=monotonic)

    def __post_init__(self):
        if not self.icon:
            self.icon = get_thinking_icon(self.text)


@dataclass
class CodeBlock:
    """A code block in the response."""

    code: str
    language: str = "text"
    filename: str = ""


@dataclass
class AgentResponse:
    """Parsed agent response with structured content."""

    raw_text: str
    paragraphs: List[str] = field(default_factory=list)
    code_blocks: List[CodeBlock] = field(default_factory=list)
    bullet_points: List[str] = field(default_factory=list)

    def __post_init__(self):
        self._parse_response()

    def _parse_response(self):
        """Parse the raw response into structured parts."""
        text = self.raw_text

        # Extract code blocks
        code_pattern = r"```(\w*)\n(.*?)```"
        for match in re.finditer(code_pattern, text, re.DOTALL):
            lang = match.group(1) or "text"
            code = match.group(2).strip()
            self.code_blocks.append(CodeBlock(code=code, language=lang))

        # Remove code blocks from text for paragraph parsing
        text_without_code = re.sub(code_pattern, "", text, flags=re.DOTALL)

        # Extract bullet points
        bullet_pattern = r"^[\s]*[-*•]\s+(.+)$"
        for match in re.finditer(bullet_pattern, text_without_code, re.MULTILINE):
            self.bullet_points.append(match.group(1).strip())

        # Extract paragraphs (non-empty lines that aren't bullets)
        text_without_bullets = re.sub(bullet_pattern, "", text_without_code, flags=re.MULTILINE)
        for para in text_without_bullets.split("\n\n"):
            para = para.strip()
            if para and len(para) > 10:
                self.paragraphs.append(para)


# ============================================================================
# RENDERING FUNCTIONS
# ============================================================================


def render_thinking_line(line: ThinkingLine, index: int) -> Text:
    """Render a single thinking line with icon and color."""
    result = Text()

    # Alternating subtle background effect via color
    color = COLORS["text_dim"] if index % 2 == 0 else COLORS["text_muted"]

    # Icon
    result.append(f"  {line.icon} ", style=COLORS["cyan"])

    # Text (truncate if too long)
    text = line.text[:100] + "..." if len(line.text) > 100 else line.text
    result.append(text, style=color)

    return result


def render_thinking_section(lines: List[ThinkingLine], collapsed: bool = False) -> Panel:
    """Render the collapsible thinking section."""
    if not lines:
        return Panel(
            Text("No thinking logs", style=COLORS["text_dim"]),
            title="[bold]💭 Thinking[/]",
            border_style=COLORS["border"],
            box=ROUNDED,
        )

    content = Text()

    # Show summary when collapsed
    if collapsed:
        content.append(f"  📊 {len(lines)} operations performed\n", style=COLORS["text_muted"])
        content.append(f"  ⏱️ Click to expand details", style=COLORS["text_dim"])
    else:
        # Show all lines
        for i, line in enumerate(lines[-50:]):  # Last 50 lines
            content.append_text(render_thinking_line(line, i))
            content.append("\n")

    return Panel(
        content,
        title=f"[bold {COLORS['cyan']}]💭 Thinking ({len(lines)} steps)[/]",
        subtitle="[dim]Ctrl+T to toggle[/]",
        border_style=COLORS["border"],
        box=ROUNDED,
        padding=(0, 1),
    )


def render_code_block(block: CodeBlock) -> Panel:
    """Render a beautiful code block with syntax highlighting."""
    # Create syntax highlighted code
    syntax = Syntax(
        block.code,
        block.language,
        theme="monokai",
        line_numbers=True,
        word_wrap=True,
        background_color="#000000",
    )

    # Language badge
    lang_icons = {
        "python": "🐍",
        "javascript": "📜",
        "typescript": "💠",
        "rust": "🦀",
        "go": "🐹",
        "java": "☕",
        "ruby": "💎",
        "bash": "🖥️",
        "shell": "🖥️",
        "sql": "🗄️",
        "html": "🌐",
        "css": "🎨",
        "json": "📋",
        "yaml": "📝",
        "markdown": "📄",
    }
    icon = lang_icons.get(block.language.lower(), "📄")

    title = f"[bold {COLORS['green']}]{icon} {block.language.upper()}[/]"
    if block.filename:
        title += f" [dim]({block.filename})[/]"

    return Panel(
        syntax,
        title=title,
        border_style=COLORS["green"],
        box=ROUNDED,
        padding=(0, 1),
    )


def render_response_header(agent_name: str = "Agent") -> Text:
    """Render a beautiful gradient header for the response."""
    result = Text()

    # Decorative line with gradient
    line_chars = "━" * 50
    for i, char in enumerate(line_chars):
        color_idx = i % len(RESPONSE_GRADIENT)
        result.append(char, style=RESPONSE_GRADIENT[color_idx])

    result.append("\n")

    # Agent name with sparkles
    result.append("  🤖 ", style=COLORS["gold"])
    result.append(agent_name.upper(), style=f"bold {COLORS['purple']}")
    result.append(" Response ", style=f"bold {COLORS['magenta']}")
    result.append("🤖\n", style=COLORS["gold"])

    # Another gradient line
    for i, char in enumerate(line_chars):
        color_idx = (i + 3) % len(RESPONSE_GRADIENT)
        result.append(char, style=RESPONSE_GRADIENT[color_idx])

    return result


def render_paragraph(text: str, width: int = 80) -> Text:
    """Render a paragraph with nice formatting and word wrapping."""
    import textwrap
    import shutil

    # Get terminal width if not specified
    try:
        term_width = shutil.get_terminal_size().columns
        wrap_width = min(term_width - 10, width)
    except Exception:
        wrap_width = width

    result = Text()
    # Strip markdown and wrap text
    clean_text = strip_markdown(text)
    wrapped = textwrap.fill(clean_text, width=wrap_width - 4)
    for line in wrapped.split("\n"):
        result.append("  ", style="")
        result.append(line, style=COLORS["text"])
        result.append("\n", style="")
    return result


def render_bullet_point(text: str, index: int, width: int = 80) -> Text:
    """Render a bullet point with colorful bullet and word wrapping."""
    import textwrap
    import shutil

    # Get terminal width if not specified
    try:
        term_width = shutil.get_terminal_size().columns
        wrap_width = min(term_width - 10, width)
    except Exception:
        wrap_width = width

    result = Text()

    # Rotating colors for bullets
    bullet_colors = [
        COLORS["purple"],
        COLORS["pink"],
        COLORS["cyan"],
        COLORS["green"],
        COLORS["orange"],
    ]
    color = bullet_colors[index % len(bullet_colors)]

    # Strip markdown and wrap the text
    clean_text = strip_markdown(text)
    wrapped = textwrap.fill(clean_text, width=wrap_width - 6)
    lines = wrapped.split("\n")

    for i, line in enumerate(lines):
        if i == 0:
            result.append("  ", style="")
            result.append("◆ ", style=f"bold {color}")
            result.append(line, style=COLORS["text"])
        else:
            result.append("    ", style="")  # Indent continuation
            result.append(line, style=COLORS["text"])
        result.append("\n", style="")

    return result


def render_response_footer(duration: float = 0) -> Text:
    """Render a beautiful footer for the response."""
    result = Text()

    # Gradient line
    line_chars = "─" * 50
    for i, char in enumerate(line_chars):
        color_idx = i % len(RAINBOW)
        result.append(char, style=RAINBOW[color_idx])

    result.append("\n")

    # Stats
    result.append("  🎯 ", style=COLORS["green"])
    result.append("Response complete", style=COLORS["text_muted"])

    if duration > 0:
        result.append(f"  ⏱️ {duration:.1f}s", style=COLORS["text_dim"])

    result.append("  💜", style=COLORS["purple"])

    return result


def render_full_response(
    response: AgentResponse, agent_name: str = "Agent", duration: float = 0
) -> Group:
    """Render the complete beautiful response."""
    elements = []

    # Header
    elements.append(render_response_header(agent_name))
    elements.append(Text("\n"))

    # Main content - paragraphs
    for para in response.paragraphs:
        elements.append(render_paragraph(para))
        elements.append(Text("\n\n"))

    # Bullet points
    if response.bullet_points:
        elements.append(Text("\n"))
        for i, bullet in enumerate(response.bullet_points):
            elements.append(render_bullet_point(bullet, i))
            elements.append(Text("\n"))

    # Code blocks
    for block in response.code_blocks:
        elements.append(Text("\n"))
        elements.append(render_code_block(block))
        elements.append(Text("\n"))

    # Footer
    elements.append(Text("\n"))
    elements.append(render_response_footer(duration))

    return Group(*elements)


# ============================================================================
# TEXTUAL WIDGETS
# ============================================================================


class ThinkingLog(Static):
    """Collapsible thinking/log display widget."""

    DEFAULT_CSS = """
    ThinkingLog {
        height: auto;
        max-height: 15;
        background: #0d1117;
        border: round #2a2a2a;
        margin: 0 0 1 0;
        overflow-y: auto;
    }

    ThinkingLog.collapsed {
        max-height: 3;
    }
    """

    collapsed = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._lines: List[ThinkingLine] = []

    def add_line(self, text: str):
        """Add a thinking line."""
        self._lines.append(ThinkingLine(text=text))
        self.refresh()

    def toggle(self):
        """Toggle collapsed state."""
        self.collapsed = not self.collapsed
        self.set_class(self.collapsed, "collapsed")

    def clear(self):
        """Clear all lines."""
        self._lines.clear()
        self.refresh()

    def render(self) -> Panel:
        return render_thinking_section(self._lines, self.collapsed)


class AgentResponseDisplay(Static):
    """Beautiful agent response display widget."""

    DEFAULT_CSS = """
    AgentResponseDisplay {
        height: auto;
        background: #0f0a1a;
        border: round #a855f7;
        padding: 1;
        margin: 1 0;
    }
    """

    def __init__(
        self, response_text: str = "", agent_name: str = "Agent", duration: float = 0, **kwargs
    ):
        super().__init__(**kwargs)
        self.response_text = response_text
        self.agent_name = agent_name
        self.duration = duration
        self._response: Optional[AgentResponse] = None

    def set_response(self, text: str, agent_name: str = "Agent", duration: float = 0):
        """Set the response content."""
        self.response_text = text
        self.agent_name = agent_name
        self.duration = duration
        self._response = AgentResponse(raw_text=text)
        self.refresh()

    def render(self) -> Group:
        if not self.response_text:
            return Group(Text("Waiting for response...", style=COLORS["text_dim"]))

        if self._response is None:
            self._response = AgentResponse(raw_text=self.response_text)

        return render_full_response(self._response, self.agent_name, self.duration)


class AgentOutputContainer(Container):
    """
    Complete agent output container with thinking logs and response.

    Features:
    - Collapsible thinking section (Ctrl+T)
    - Beautiful response display
    - Clear visual separation
    """

    DEFAULT_CSS = """
    AgentOutputContainer {
        height: auto;
        padding: 0 1;
    }

    AgentOutputContainer .output-header {
        height: 1;
        text-align: center;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+t", "toggle_thinking", "Toggle Thinking", show=True),
    ]

    show_thinking = reactive(True)

    def __init__(self, agent_name: str = "Agent", **kwargs):
        super().__init__(**kwargs)
        self.agent_name = agent_name
        self._thinking_log: Optional[ThinkingLog] = None
        self._response_display: Optional[AgentResponseDisplay] = None
        self._start_time: float = 0

    def compose(self) -> ComposeResult:
        yield Static(self._render_header(), classes="output-header")
        self._thinking_log = ThinkingLog()
        yield self._thinking_log
        self._response_display = AgentResponseDisplay(agent_name=self.agent_name)
        yield self._response_display

    def _render_header(self) -> Text:
        result = Text()
        result.append("🤖 ", style=COLORS["purple"])
        result.append(self.agent_name.upper(), style=f"bold {COLORS['purple']}")
        result.append(" OUTPUT", style=f"bold {COLORS['magenta']}")
        return result

    def start_session(self):
        """Start a new output session."""
        self._start_time = monotonic()
        if self._thinking_log:
            self._thinking_log.clear()

    def add_thinking(self, text: str):
        """Add a thinking/log line."""
        if self._thinking_log:
            self._thinking_log.add_line(text)

    def set_response(self, text: str):
        """Set the final response."""
        duration = monotonic() - self._start_time if self._start_time else 0
        if self._response_display:
            self._response_display.set_response(text, self.agent_name, duration)

    def action_toggle_thinking(self):
        """Toggle thinking section visibility."""
        if self._thinking_log:
            self._thinking_log.toggle()
            self.show_thinking = not self._thinking_log.collapsed


# ============================================================================
# HELPER FUNCTIONS FOR APP INTEGRATION
# ============================================================================


def format_agent_output_for_log(
    thinking_lines: List[str],
    response_text: str,
    agent_name: str = "Agent",
    duration: float = 0,
    show_thinking: bool = True,
) -> Group:
    """
    Format complete agent output for display in conversation log.

    Args:
        thinking_lines: List of thinking/log lines
        response_text: Final response text
        agent_name: Name of the agent
        duration: Time taken in seconds
        show_thinking: Whether to show thinking section

    Returns:
        Rich Group ready for display
    """
    elements = []

    # Thinking section (collapsible)
    if thinking_lines and show_thinking:
        lines = [ThinkingLine(text=t) for t in thinking_lines]
        elements.append(render_thinking_section(lines, collapsed=False))
        elements.append(Text("\n"))
    elif thinking_lines:
        # Show collapsed summary
        elements.append(
            Text(f"  💭 {len(thinking_lines)} thinking steps (hidden)\n", style=COLORS["text_dim"])
        )

    # Response
    if response_text:
        response = AgentResponse(raw_text=response_text)
        elements.append(render_full_response(response, agent_name, duration))

    return Group(*elements)


def create_simple_response_panel(text: str, agent_name: str = "Agent") -> Panel:
    """Create a simple but beautiful response panel."""
    content = Text()

    # Add sparkle decoration
    content.append("✨ ", style=COLORS["gold"])

    # Format the text nicely
    lines = text.strip().split("\n")
    for i, line in enumerate(lines):
        if line.strip():
            content.append(line, style=COLORS["text"])
        if i < len(lines) - 1:
            content.append("\n")

    return Panel(
        content,
        title=f"[bold {COLORS['purple']}]🤖 {agent_name}[/]",
        border_style=COLORS["purple"],
        box=ROUNDED,
        padding=(1, 2),
    )
