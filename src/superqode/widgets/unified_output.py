"""
Unified Output Display for SuperQode.

A single, beautiful output display that works consistently for all modes:
- BYOK (LiteLLM Gateway)
- ACP (Agent Client Protocol)
- Local (Ollama, etc.)

Features:
- Consistent display across all modes
- Copy to clipboard support (Ctrl+C to copy response)
- Collapsible thinking section
- Rich markdown rendering with syntax highlighting
- Streaming support
- Clear visual hierarchy
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from time import monotonic
from typing import Any, Callable, Dict, List, Optional, Tuple

from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static


# ============================================================================
# THEME - Consistent colors across all displays
# ============================================================================


class Theme:
    """SuperQode unified theme."""

    # Primary colors
    purple = "#a855f7"
    magenta = "#d946ef"
    pink = "#ec4899"
    cyan = "#06b6d4"
    green = "#22c55e"
    orange = "#f97316"
    gold = "#fbbf24"
    blue = "#3b82f6"

    # Status colors
    success = "#22c55e"
    error = "#ef4444"
    warning = "#f59e0b"
    info = "#06b6d4"

    # Text colors
    text = "#e4e4e7"
    text_secondary = "#a1a1aa"
    text_muted = "#71717a"
    text_dim = "#52525b"

    # Background colors
    bg = "#0a0a0a"
    bg_surface = "#111111"
    bg_elevated = "#1a1a1a"
    bg_thinking = "#0d1117"
    bg_response = "#0f0a1a"

    # Border colors
    border = "#27272a"
    border_active = "#a855f7"


# Gradient colors for visual interest
GRADIENT_PURPLE = ["#6d28d9", "#7c3aed", "#8b5cf6", "#a855f7", "#c084fc"]
GRADIENT_SUCCESS = ["#059669", "#10b981", "#34d399", "#6ee7b7"]


# ============================================================================
# CLIPBOARD SUPPORT
# ============================================================================


def copy_to_clipboard(text: str) -> Tuple[bool, str]:
    """
    Copy text to clipboard using OS-native methods.

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        if sys.platform == "darwin":
            # macOS - use pbcopy
            process = subprocess.Popen(
                ["pbcopy"],
                stdin=subprocess.PIPE,
                text=True,
            )
            process.communicate(input=text)
            return (process.returncode == 0, "Copied to clipboard!")

        elif sys.platform == "linux":
            # Linux - try xclip or xsel
            for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
                try:
                    process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        text=True,
                    )
                    process.communicate(input=text)
                    if process.returncode == 0:
                        return (True, "Copied to clipboard!")
                except FileNotFoundError:
                    continue
            return (False, "Install xclip or xsel to copy")

        elif sys.platform == "win32":
            # Windows - use clip
            process = subprocess.Popen(
                ["clip"],
                stdin=subprocess.PIPE,
                text=True,
            )
            process.communicate(input=text)
            return (process.returncode == 0, "Copied to clipboard!")

        return (False, "Clipboard not supported on this platform")

    except Exception as e:
        return (False, f"Copy failed: {str(e)[:30]}")


# ============================================================================
# DATA CLASSES
# ============================================================================


class OutputMode(Enum):
    """Connection mode for output."""

    BYOK = "byok"
    ACP = "acp"
    LOCAL = "local"


class OutputState(Enum):
    """State of the output display."""

    IDLE = "idle"
    THINKING = "thinking"
    STREAMING = "streaming"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class ThinkingEntry:
    """A single thinking/reasoning entry."""

    text: str
    category: str = "general"
    timestamp: float = field(default_factory=monotonic)

    @property
    def icon(self) -> str:
        """Get icon for this thinking category."""
        icons = {
            "planning": "📋",
            "analyzing": "🔬",
            "deciding": "🤔",
            "searching": "🔍",
            "reading": "📖",
            "writing": "✏️",
            "debugging": "🐛",
            "executing": "⚡",
            "verifying": "✅",
            "testing": "🧪",
            "refactoring": "🔧",
            "general": "💭",
        }
        return icons.get(self.category, "💭")


@dataclass
class OutputStats:
    """Statistics for the output."""

    mode: OutputMode = OutputMode.BYOK
    agent_name: str = ""
    model_name: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    thinking_count: int = 0
    tool_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thinking_tokens: int = 0
    cost: float = 0.0

    @property
    def duration(self) -> float:
        """Get duration in seconds."""
        if self.end_time > 0 and self.start_time > 0:
            return self.end_time - self.start_time
        elif self.start_time > 0:
            return monotonic() - self.start_time
        return 0.0

    @property
    def total_tokens(self) -> int:
        """Get total tokens."""
        return self.prompt_tokens + self.completion_tokens


# ============================================================================
# MESSAGES
# ============================================================================


class CopyRequested(Message):
    """User requested to copy content."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content


class CopyComplete(Message):
    """Copy operation completed."""

    def __init__(self, success: bool, message: str) -> None:
        super().__init__()
        self.success = success
        self.message = message


# ============================================================================
# THINKING SECTION WIDGET
# ============================================================================


class ThinkingSection(Container):
    """
    Collapsible thinking/reasoning section.

    Shows agent's thought process with:
    - Category icons
    - Animated streaming indicator
    - Collapse/expand toggle
    - Summary when collapsed
    """

    DEFAULT_CSS = """
    ThinkingSection {
        height: auto;
        max-height: 20;
        background: #0d1117;
        border: round #27272a;
        border-left: tall #ec4899;
        margin: 0 0 1 0;
        padding: 0 1;
    }

    ThinkingSection.collapsed {
        max-height: 2;
    }

    ThinkingSection.streaming {
        border: round #fbbf24;
        border-left: tall #fbbf24;
    }

    ThinkingSection .thinking-header {
        height: 1;
        padding: 0;
    }

    ThinkingSection .thinking-content {
        height: auto;
        max-height: 18;
        overflow-y: auto;
    }
    """

    collapsed: reactive[bool] = reactive(True)
    is_streaming: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entries: List[ThinkingEntry] = []
        self._current_text = ""
        self._tick = 0
        self._timer: Optional[Timer] = None

    def on_mount(self) -> None:
        """Start animation timer."""
        self._timer = self.set_interval(0.3, self._animate)

    def _animate(self) -> None:
        """Animation tick."""
        self._tick += 1
        if self.is_streaming:
            self._update_header()

    def compose(self) -> ComposeResult:
        yield Static(self._render_header(), classes="thinking-header")
        yield ScrollableContainer(
            Static("", id="thinking-text"),
            classes="thinking-content",
        )

    def _render_header(self) -> Text:
        """Render the header line."""
        text = Text()

        # Toggle indicator
        icon = "▾" if not self.collapsed else "▸"
        text.append(f"{icon} ", style=Theme.text_dim)

        # Thinking icon with animation
        if self.is_streaming:
            frames = ["💭", "💬", "💭", "💬"]
            think_icon = frames[self._tick % len(frames)]
            text.append(f"{think_icon} ", style=f"bold {Theme.gold}")
            text.append("Thinking", style=f"bold {Theme.gold}")
            text.append("...", style=f"bold {Theme.gold}")
        else:
            text.append("💭 ", style=Theme.pink)
            text.append("Thinking", style=Theme.text_secondary)

        # Count
        if self._entries:
            text.append(f"  ({len(self._entries)} thoughts)", style=Theme.text_dim)

        # Hint
        if self.collapsed and self._entries:
            text.append("  [click to expand]", style=Theme.text_dim)

        return text

    def _render_content(self) -> Text:
        """Render the thinking content."""
        if self.collapsed:
            return Text()

        text = Text()

        # Show last 10 entries
        visible = self._entries[-10:]
        for entry in visible:
            text.append(f"  {entry.icon} ", style=Theme.cyan)

            # Truncate long entries
            entry_text = entry.text
            if len(entry_text) > 120:
                entry_text = entry_text[:117] + "..."

            text.append(entry_text, style=f"italic {Theme.text_muted}")
            text.append("\n")

        # Show current streaming text
        if self._current_text:
            text.append("  ● ", style=f"bold {Theme.gold}")
            current = self._current_text
            if len(current) > 120:
                current = current[:117] + "..."
            text.append(current, style=f"italic {Theme.gold}")

        return text

    def _update_header(self) -> None:
        """Update the header."""
        try:
            header = self.query_one(".thinking-header", Static)
            header.update(self._render_header())
        except Exception:
            pass

    def _update_content(self) -> None:
        """Update the content."""
        try:
            content = self.query_one("#thinking-text", Static)
            content.update(self._render_content())
        except Exception:
            pass

    def on_click(self) -> None:
        """Toggle on click."""
        self.toggle()

    def toggle(self) -> None:
        """Toggle collapsed state."""
        self.collapsed = not self.collapsed
        self.set_class(self.collapsed, "collapsed")
        self._update_content()

    def start_streaming(self) -> None:
        """Start streaming mode."""
        self.is_streaming = True
        self._current_text = ""
        self.collapsed = False
        self.add_class("streaming")
        self.remove_class("collapsed")
        self._update_header()

    def append_text(self, text: str) -> None:
        """Append text to current streaming thought."""
        self._current_text += text
        self._update_content()

    def complete_thought(self) -> None:
        """Complete the current thought."""
        if self._current_text:
            category = self._classify_thought(self._current_text)
            entry = ThinkingEntry(
                text=self._current_text.strip(),
                category=category,
            )
            self._entries.append(entry)
            self._current_text = ""

        self.is_streaming = False
        self.remove_class("streaming")
        self._update_header()
        self._update_content()

    def add_thought(self, text: str) -> None:
        """Add a complete thought (for ACP mode)."""
        category = self._classify_thought(text)
        entry = ThinkingEntry(text=text.strip(), category=category)
        self._entries.append(entry)
        self._update_header()
        self._update_content()

    def _classify_thought(self, text: str) -> str:
        """Classify thought by content."""
        text_lower = text.lower()

        keywords = {
            "testing": ["test", "pytest", "unittest", "expect"],
            "verifying": ["verify", "confirm", "ensure", "check if"],
            "executing": ["run", "execute", "command", "npm", "pip"],
            "refactoring": ["refactor", "restructure", "clean up"],
            "debugging": ["debug", "error", "fix", "bug", "traceback"],
            "planning": ["plan", "step", "approach", "first", "then"],
            "analyzing": ["analyze", "understand", "examine", "review"],
            "deciding": ["decide", "choose", "option", "should"],
            "searching": ["search", "find", "look for", "grep"],
            "reading": ["read", "content", "open", "view"],
            "writing": ["write", "create", "add", "implement"],
        }

        for category, words in keywords.items():
            if any(w in text_lower for w in words):
                return category

        return "general"

    def clear(self) -> None:
        """Clear all thoughts."""
        self._entries.clear()
        self._current_text = ""
        self.is_streaming = False
        self.remove_class("streaming")
        self._update_header()
        self._update_content()

    @property
    def thought_count(self) -> int:
        """Get number of thoughts."""
        return len(self._entries)

    def get_all_text(self) -> str:
        """Get all thinking text for copying."""
        lines = []
        for entry in self._entries:
            lines.append(f"{entry.icon} {entry.text}")
        if self._current_text:
            lines.append(f"● {self._current_text}")
        return "\n".join(lines)


# ============================================================================
# RESPONSE SECTION WIDGET
# ============================================================================


class ResponseSection(Container):
    """
    Beautiful response display with copy support.

    Features:
    - Rich markdown rendering
    - Syntax-highlighted code blocks
    - Streaming support with animated cursor
    - Copy to clipboard (Ctrl+C)
    - Stats footer
    """

    DEFAULT_CSS = """
    ResponseSection {
        height: auto;
        min-height: 5;
        background: #0f0a1a;
        border: round #a855f7;
        padding: 1;
        margin: 0 0 1 0;
    }

    ResponseSection.streaming {
        border: round #fbbf24;
    }

    ResponseSection.error {
        border: round #ef4444;
    }

    ResponseSection .response-header {
        height: 2;
        margin-bottom: 1;
    }

    ResponseSection .response-content {
        height: auto;
        min-height: 3;
    }

    ResponseSection .response-footer {
        height: 2;
        margin-top: 1;
        border-top: solid #27272a;
    }

    ResponseSection .copy-hint {
        height: 1;
        text-align: right;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "copy_response", "Copy", show=True, priority=True),
        Binding("c", "copy_response", "Copy", show=False),
    ]

    is_streaming: reactive[bool] = reactive(False)
    is_error: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._text = ""
        self._raw_text = ""  # Keep raw text for copying
        self._agent_name = ""
        self._model_name = ""
        self._stats: Optional[OutputStats] = None
        self._tick = 0
        self._timer: Optional[Timer] = None
        self._copy_message = ""
        self._copy_message_time = 0.0

    def on_mount(self) -> None:
        """Start animation timer."""
        self._timer = self.set_interval(0.2, self._animate)

    def _animate(self) -> None:
        """Animation tick."""
        self._tick += 1
        if self.is_streaming:
            self._update_content()

        # Clear copy message after 2 seconds
        if self._copy_message and monotonic() - self._copy_message_time > 2:
            self._copy_message = ""
            self._update_footer()

    def compose(self) -> ComposeResult:
        yield Static(self._render_header(), classes="response-header")
        yield ScrollableContainer(
            Static("", id="response-text"),
            classes="response-content",
        )
        yield Static(self._render_footer(), classes="response-footer")
        yield Static("", classes="copy-hint")

    def _render_header(self) -> Text:
        """Render response header."""
        text = Text()

        # Gradient line
        line = "─" * 50
        for i, char in enumerate(line):
            color = GRADIENT_PURPLE[i % len(GRADIENT_PURPLE)]
            text.append(char, style=color)
        text.append("\n")

        # Agent info
        if self.is_streaming:
            text.append("● ", style=f"bold {Theme.gold}")
            text.append("Generating", style=f"bold {Theme.gold}")
            text.append("...", style=f"bold {Theme.gold}")
        elif self.is_error:
            text.append("✕ ", style=f"bold {Theme.error}")
            text.append("Error", style=f"bold {Theme.error}")
        else:
            text.append("🤖 ", style=Theme.purple)
            if self._agent_name:
                text.append(self._agent_name, style=f"bold {Theme.text}")
            else:
                text.append("Response", style=f"bold {Theme.text}")

        if self._model_name and not self.is_error:
            text.append(f"  [{self._model_name}]", style=Theme.text_dim)

        return text

    def _render_content(self) -> Text | Markdown:
        """Render response content."""
        if not self._text:
            return Text("Waiting for response...", style=Theme.text_dim)

        display_text = self._text

        # Add streaming cursor
        if self.is_streaming:
            cursors = ["▌", "▐", "▌", " "]
            cursor = cursors[self._tick % len(cursors)]
            display_text += cursor

        # Try to render as markdown for complete responses
        if not self.is_streaming and not self.is_error:
            try:
                return Markdown(display_text)
            except Exception:
                pass

        return Text(display_text, style=Theme.text)

    def _render_footer(self) -> Text:
        """Render stats footer."""
        text = Text()

        if self._copy_message:
            # Show copy message
            color = Theme.success if "Copied" in self._copy_message else Theme.warning
            text.append(f"  {self._copy_message}", style=f"bold {color}")
            return text

        if not self._stats:
            text.append("  [Ctrl+C to copy]", style=Theme.text_dim)
            return text

        stats = self._stats
        parts = []

        # Duration
        if stats.duration > 0:
            parts.append(f"⏱ {stats.duration:.1f}s")

        # Tokens
        if stats.total_tokens > 0:
            parts.append(f"📊 {stats.total_tokens:,} tokens")

        # Thinking tokens
        if stats.thinking_tokens > 0:
            parts.append(f"💭 {stats.thinking_tokens:,} thinking")

        # Cost
        if stats.cost > 0:
            parts.append(f"💰 ${stats.cost:.4f}")

        # Tools
        if stats.tool_count > 0:
            parts.append(f"🔧 {stats.tool_count} tools")

        if parts:
            text.append("  " + "  │  ".join(parts), style=Theme.text_dim)

        text.append("    [Ctrl+C to copy]", style=Theme.text_dim)

        return text

    def _update_header(self) -> None:
        """Update header."""
        try:
            self.query_one(".response-header", Static).update(self._render_header())
        except Exception:
            pass

    def _update_content(self) -> None:
        """Update content."""
        try:
            self.query_one("#response-text", Static).update(self._render_content())
        except Exception:
            pass

    def _update_footer(self) -> None:
        """Update footer."""
        try:
            self.query_one(".response-footer", Static).update(self._render_footer())
        except Exception:
            pass

    def start_streaming(self, agent_name: str = "", model_name: str = "") -> None:
        """Start streaming mode."""
        self._text = ""
        self._raw_text = ""
        self._agent_name = agent_name
        self._model_name = model_name
        self.is_streaming = True
        self.is_error = False
        self.add_class("streaming")
        self.remove_class("error")
        self._update_header()
        self._update_content()

    def append_text(self, text: str) -> None:
        """Append text during streaming."""
        self._text += text
        self._raw_text += text
        self._update_content()

    def set_text(self, text: str) -> None:
        """Set complete text."""
        self._text = text
        self._raw_text = text
        self._update_content()

    def complete(self, stats: Optional[OutputStats] = None) -> None:
        """Complete the response."""
        self._stats = stats
        self.is_streaming = False
        self.remove_class("streaming")
        self._update_header()
        self._update_content()
        self._update_footer()

    def set_error(self, error: str) -> None:
        """Set error state."""
        self._text = error
        self._raw_text = error
        self.is_streaming = False
        self.is_error = True
        self.add_class("error")
        self.remove_class("streaming")
        self._update_header()
        self._update_content()

    def action_copy_response(self) -> None:
        """Copy response to clipboard."""
        if not self._raw_text:
            self._copy_message = "Nothing to copy"
            self._copy_message_time = monotonic()
            self._update_footer()
            return

        success, message = copy_to_clipboard(self._raw_text)
        self._copy_message = message
        self._copy_message_time = monotonic()
        self._update_footer()

        # Also post message for parent to handle
        self.post_message(CopyComplete(success, message))

    def clear(self) -> None:
        """Clear the response."""
        self._text = ""
        self._raw_text = ""
        self._stats = None
        self.is_streaming = False
        self.is_error = False
        self.remove_class("streaming", "error")
        self._update_header()
        self._update_content()
        self._update_footer()

    def get_text(self) -> str:
        """Get raw text for copying."""
        return self._raw_text


# ============================================================================
# UNIFIED OUTPUT DISPLAY
# ============================================================================


class UnifiedOutputDisplay(Container):
    """
    Complete unified output display for all modes.

    Combines thinking and response sections with:
    - Consistent display across BYOK, ACP, Local
    - Copy support for both thinking and response
    - Clear visual hierarchy
    - Mode indicator
    """

    DEFAULT_CSS = """
    UnifiedOutputDisplay {
        height: auto;
        padding: 0 1;
    }

    UnifiedOutputDisplay .output-mode-indicator {
        height: 1;
        text-align: center;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "copy_all", "Copy All", show=True),
        Binding("ctrl+shift+c", "copy_response_only", "Copy Response", show=False),
        Binding("ctrl+t", "toggle_thinking", "Toggle Thinking", show=True),
    ]

    def __init__(self, mode: OutputMode = OutputMode.BYOK, **kwargs):
        super().__init__(**kwargs)
        self._mode = mode
        self._stats = OutputStats(mode=mode)
        self._thinking: Optional[ThinkingSection] = None
        self._response: Optional[ResponseSection] = None

    def compose(self) -> ComposeResult:
        yield Static(self._render_mode_indicator(), classes="output-mode-indicator")
        self._thinking = ThinkingSection(id="thinking-section")
        yield self._thinking
        self._response = ResponseSection(id="response-section")
        yield self._response

    def _render_mode_indicator(self) -> Text:
        """Render mode indicator."""
        text = Text()

        mode_styles = {
            OutputMode.BYOK: ("🔑", "BYOK", Theme.blue),
            OutputMode.ACP: ("🔌", "ACP", Theme.green),
            OutputMode.LOCAL: ("💻", "Local", Theme.orange),
        }

        icon, label, color = mode_styles.get(self._mode, ("●", "Unknown", Theme.text_dim))
        text.append(f"{icon} ", style=color)
        text.append(label, style=f"bold {color}")

        if self._stats.agent_name:
            text.append(f"  │  {self._stats.agent_name}", style=Theme.text_secondary)

        if self._stats.model_name:
            text.append(f" → {self._stats.model_name}", style=Theme.text_dim)

        return text

    def _update_mode_indicator(self) -> None:
        """Update mode indicator."""
        try:
            self.query_one(".output-mode-indicator", Static).update(self._render_mode_indicator())
        except Exception:
            pass

    # ========================================================================
    # PUBLIC API - Unified interface for all modes
    # ========================================================================

    def set_mode(self, mode: OutputMode) -> None:
        """Set the output mode."""
        self._mode = mode
        self._stats.mode = mode
        self._update_mode_indicator()

    def set_agent_info(self, agent_name: str, model_name: str = "") -> None:
        """Set agent info."""
        self._stats.agent_name = agent_name
        self._stats.model_name = model_name
        self._update_mode_indicator()

    def start_session(self) -> None:
        """Start a new output session."""
        self._stats = OutputStats(
            mode=self._mode,
            agent_name=self._stats.agent_name,
            model_name=self._stats.model_name,
            start_time=monotonic(),
        )
        if self._thinking:
            self._thinking.clear()
        if self._response:
            self._response.clear()
        self._update_mode_indicator()

    # ========================================================================
    # THINKING API - Works for all modes
    # ========================================================================

    def start_thinking(self) -> None:
        """Start thinking display (for streaming modes like BYOK)."""
        if self._thinking:
            self._thinking.start_streaming()

    def append_thinking(self, text: str) -> None:
        """Append to current thinking (for streaming)."""
        if self._thinking:
            self._thinking.append_text(text)

    def add_thought(self, text: str) -> None:
        """Add a complete thought (for ACP mode)."""
        if self._thinking:
            self._thinking.add_thought(text)
            self._stats.thinking_count += 1

    def complete_thinking(self) -> None:
        """Complete current thinking."""
        if self._thinking:
            self._thinking.complete_thought()
            self._stats.thinking_count = self._thinking.thought_count

    # ========================================================================
    # RESPONSE API - Works for all modes
    # ========================================================================

    def start_response(self) -> None:
        """Start response streaming."""
        if self._response:
            self._response.start_streaming(
                agent_name=self._stats.agent_name,
                model_name=self._stats.model_name,
            )

    def append_response(self, text: str) -> None:
        """Append to response."""
        if self._response:
            self._response.append_text(text)

    def set_response(self, text: str) -> None:
        """Set complete response."""
        if self._response:
            self._response.set_text(text)

    def complete_response(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        thinking_tokens: int = 0,
        cost: float = 0.0,
        tool_count: int = 0,
    ) -> None:
        """Complete the response with stats."""
        self._stats.end_time = monotonic()
        self._stats.prompt_tokens = prompt_tokens
        self._stats.completion_tokens = completion_tokens
        self._stats.thinking_tokens = thinking_tokens
        self._stats.cost = cost
        self._stats.tool_count = tool_count

        if self._response:
            self._response.complete(self._stats)

    def set_error(self, error: str) -> None:
        """Set error state."""
        if self._response:
            self._response.set_error(error)

    # ========================================================================
    # COPY ACTIONS
    # ========================================================================

    def action_copy_all(self) -> None:
        """Copy both thinking and response."""
        parts = []

        if self._thinking:
            thinking_text = self._thinking.get_all_text()
            if thinking_text:
                parts.append("=== THINKING ===\n" + thinking_text)

        if self._response:
            response_text = self._response.get_text()
            if response_text:
                parts.append("=== RESPONSE ===\n" + response_text)

        if parts:
            full_text = "\n\n".join(parts)
            success, message = copy_to_clipboard(full_text)
            self.post_message(CopyComplete(success, message))

    def action_copy_response_only(self) -> None:
        """Copy only the response."""
        if self._response:
            self._response.action_copy_response()

    def action_toggle_thinking(self) -> None:
        """Toggle thinking section."""
        if self._thinking:
            self._thinking.toggle()

    # ========================================================================
    # CONVENIENCE HANDLERS FOR DIFFERENT MODES
    # ========================================================================

    async def handle_byok_chunk(self, chunk: Any) -> None:
        """
        Handle BYOK StreamChunk.

        Automatically routes thinking_content and content to correct displays.
        """
        # Handle thinking content
        thinking_content = getattr(chunk, "thinking_content", None)
        if thinking_content:
            if self._thinking and not self._thinking.is_streaming:
                self.start_thinking()
            self.append_thinking(thinking_content)

        # Handle response content
        content = getattr(chunk, "content", None)
        if content:
            if self._response and not self._response.is_streaming:
                self.start_response()
            self.append_response(content)

    async def handle_byok_complete(self, response: Any) -> None:
        """Handle BYOK GatewayResponse completion."""
        self.complete_thinking()

        # Extract stats
        usage = getattr(response, "usage", None)
        cost = getattr(response, "cost", None)

        self.complete_response(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            thinking_tokens=getattr(response, "thinking_tokens", 0),
            cost=getattr(cost, "total", 0.0) if cost else 0.0,
        )

    async def handle_acp_thought(self, text: str) -> None:
        """Handle ACP thought chunk (complete thoughts)."""
        self.add_thought(text)

    async def handle_acp_message(self, text: str) -> None:
        """Handle ACP message chunk."""
        if self._response and not self._response.is_streaming:
            self.start_response()
        self.append_response(text)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "Theme",
    "OutputMode",
    "OutputState",
    "OutputStats",
    "ThinkingEntry",
    "ThinkingSection",
    "ResponseSection",
    "UnifiedOutputDisplay",
    "CopyRequested",
    "CopyComplete",
    "copy_to_clipboard",
]
