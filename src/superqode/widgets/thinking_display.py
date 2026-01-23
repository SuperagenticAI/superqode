"""
Thinking Display Widget - Model Reasoning Visualization.

Shows the model's thinking process in an elegant, expandable display:
- Streaming thinking text with typing effect
- Collapsible sections
- Thought categorization (planning, analyzing, deciding)
- Visual timeline of thoughts
- Support for extended thinking (Claude-style)

Provides transparency into how the model reasons about problems.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from rich.console import RenderableType, Group
from rich.panel import Panel
from rich.text import Text
from rich.box import ROUNDED
from textual.reactive import reactive
from textual.widgets import Static
from textual.containers import Container, Vertical
from textual.timer import Timer
from textual import events


class ThoughtType(Enum):
    """Type of thought/reasoning."""

    PLANNING = "planning"
    ANALYZING = "analyzing"
    DECIDING = "deciding"
    SEARCHING = "searching"
    READING = "reading"
    WRITING = "writing"
    DEBUGGING = "debugging"
    REFLECTING = "reflecting"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    TESTING = "testing"
    REFACTORING = "refactoring"
    GENERAL = "general"


# Thought styling - colorful icons for visual clarity
THOUGHT_STYLES = {
    ThoughtType.PLANNING: {"icon": "📋", "color": "#3b82f6", "label": "Planning"},
    ThoughtType.ANALYZING: {"icon": "🔬", "color": "#8b5cf6", "label": "Analyzing"},
    ThoughtType.DECIDING: {"icon": "🤔", "color": "#f59e0b", "label": "Deciding"},
    ThoughtType.SEARCHING: {"icon": "🔍", "color": "#06b6d4", "label": "Searching"},
    ThoughtType.READING: {"icon": "📖", "color": "#14b8a6", "label": "Reading"},
    ThoughtType.WRITING: {"icon": "✏️", "color": "#22c55e", "label": "Writing"},
    ThoughtType.DEBUGGING: {"icon": "🐛", "color": "#ef4444", "label": "Debugging"},
    ThoughtType.REFLECTING: {"icon": "💭", "color": "#ec4899", "label": "Reflecting"},
    ThoughtType.EXECUTING: {"icon": "⚡", "color": "#f97316", "label": "Executing"},
    ThoughtType.VERIFYING: {"icon": "✅", "color": "#10b981", "label": "Verifying"},
    ThoughtType.TESTING: {"icon": "🧪", "color": "#6366f1", "label": "Testing"},
    ThoughtType.REFACTORING: {"icon": "🔧", "color": "#a855f7", "label": "Refactoring"},
    ThoughtType.GENERAL: {"icon": "💡", "color": "#a1a1aa", "label": "Thinking"},
}


@dataclass
class ThoughtChunk:
    """A chunk of thinking text."""

    text: str
    thought_type: ThoughtType = ThoughtType.GENERAL
    timestamp: datetime = field(default_factory=datetime.now)
    is_streaming: bool = False


def classify_thought(text: str) -> ThoughtType:
    """
    Classify a thought based on its content.

    Uses keyword matching to determine the type of reasoning/activity
    the agent is performing. Order matters - more specific matches first.
    """
    text_lower = text.lower()

    # Testing - check first as it's specific
    if any(
        w in text_lower
        for w in ["test", "pytest", "unittest", "assertion", "expect", "should pass", "should fail"]
    ):
        return ThoughtType.TESTING

    # Verifying - checking if something works
    if any(
        w in text_lower
        for w in ["verify", "confirm", "validate", "check if", "ensure", "make sure", "works"]
    ):
        return ThoughtType.VERIFYING

    # Executing - running commands
    if any(
        w in text_lower
        for w in ["run", "execute", "running", "executing", "shell", "command", "npm", "pip"]
    ):
        return ThoughtType.EXECUTING

    # Refactoring - restructuring code
    if any(
        w in text_lower
        for w in ["refactor", "restructure", "reorganize", "clean up", "simplify", "extract"]
    ):
        return ThoughtType.REFACTORING

    # Debugging - fixing issues
    if any(
        w in text_lower
        for w in ["debug", "error", "fix", "issue", "problem", "bug", "traceback", "exception"]
    ):
        return ThoughtType.DEBUGGING

    # Planning - strategizing approach
    if any(
        w in text_lower
        for w in ["plan", "step", "approach", "strategy", "first", "then", "next", "let me", "i'll"]
    ):
        return ThoughtType.PLANNING

    # Analyzing - understanding code/problem
    if any(
        w in text_lower
        for w in ["analyze", "understand", "examine", "look at", "check", "inspect", "review"]
    ):
        return ThoughtType.ANALYZING

    # Deciding - making choices
    if any(
        w in text_lower
        for w in ["decide", "choose", "option", "should i", "best way", "which", "either", "or"]
    ):
        return ThoughtType.DECIDING

    # Searching - finding files/code
    if any(
        w in text_lower
        for w in ["search", "find", "look for", "grep", "locate", "where is", "looking for"]
    ):
        return ThoughtType.SEARCHING

    # Reading - examining content
    if any(
        w in text_lower
        for w in ["read", "reading", "content", "see what", "open", "view", "contents of"]
    ):
        return ThoughtType.READING

    # Writing - creating/modifying code
    if any(
        w in text_lower
        for w in ["write", "create", "add", "implement", "modify", "update", "change", "edit"]
    ):
        return ThoughtType.WRITING

    # Reflecting - meta-thinking
    if any(
        w in text_lower
        for w in ["think", "consider", "hmm", "wait", "actually", "interesting", "notice"]
    ):
        return ThoughtType.REFLECTING

    return ThoughtType.GENERAL


class ThinkingBubble(Static):
    """Single thinking bubble widget."""

    DEFAULT_CSS = """
    ThinkingBubble {
        height: auto;
        margin: 0 0 0 2;
        padding: 0;
    }
    """

    def __init__(self, chunk: ThoughtChunk, **kwargs):
        super().__init__(**kwargs)
        self.chunk = chunk

    def render(self) -> Text:
        style = THOUGHT_STYLES.get(self.chunk.thought_type, THOUGHT_STYLES[ThoughtType.GENERAL])

        result = Text()
        result.append(f"{style['icon']} ", style=style["color"])

        # Truncate long thoughts
        text = self.chunk.text
        if len(text) > 150:
            text = text[:147] + "..."

        result.append(text, style=f"italic #a1a1aa")

        # Streaming indicator
        if self.chunk.is_streaming:
            result.append(" ●", style="bold #fbbf24")

        return result


class ThinkingPanel(Container):
    """
    Panel displaying model thinking/reasoning.

    Features:
    - Collapsible display
    - Streaming support
    - Thought categorization
    - Summary when collapsed
    """

    DEFAULT_CSS = """
    ThinkingPanel {
        height: auto;
        max-height: 30%;
        border: solid #27272a;
        border-left: tall #ec4899;
        background: #0d0d0d;
        padding: 0 1;
        margin: 0 0 1 0;
    }

    ThinkingPanel.collapsed {
        max-height: 3;
    }

    ThinkingPanel .thinking-header {
        height: 1;
        margin-bottom: 1;
    }

    ThinkingPanel .thinking-content {
        height: auto;
        max-height: 20;
        overflow-y: auto;
    }
    """

    collapsed: reactive[bool] = reactive(False)
    is_streaming: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._chunks: List[ThoughtChunk] = []
        self._current_text = ""
        self._timer: Optional[Timer] = None

    def on_mount(self) -> None:
        """Start animation timer."""
        self._timer = self.set_interval(0.5, self._tick)

    def _tick(self) -> None:
        """Animation tick."""
        if self.is_streaming:
            self._update_header()

    def toggle(self) -> None:
        """Toggle collapsed state."""
        self.collapsed = not self.collapsed
        self.set_class(self.collapsed, "collapsed")
        self._update_display()

    def on_click(self, event: events.Click) -> None:
        """Toggle on click."""
        self.toggle()

    def start_streaming(self) -> None:
        """Start a new streaming thought."""
        self.is_streaming = True
        self._current_text = ""
        self._update_header()

    def append_chunk(self, text: str) -> None:
        """Append text to current streaming thought."""
        self._current_text += text
        self._update_display()

    def complete_thought(self) -> None:
        """Complete the current streaming thought."""
        if self._current_text:
            thought_type = classify_thought(self._current_text)
            chunk = ThoughtChunk(
                text=self._current_text.strip(),
                thought_type=thought_type,
                is_streaming=False,
            )
            self._chunks.append(chunk)

        self._current_text = ""
        self.is_streaming = False
        self._update_display()

    def add_thought(self, text: str) -> None:
        """Add a complete thought."""
        thought_type = classify_thought(text)
        chunk = ThoughtChunk(
            text=text.strip(),
            thought_type=thought_type,
            is_streaming=False,
        )
        self._chunks.append(chunk)
        self._update_display()

    def _update_header(self) -> None:
        """Update the header."""
        try:
            header = self.query_one(".thinking-header", Static)
        except Exception:
            return

        text = Text()
        text.append("💭 ", style="bold #ec4899")
        text.append("Thinking", style="bold #e4e4e7")

        if self.is_streaming:
            text.append("  ● ", style="bold #fbbf24")
            text.append("Streaming...", style="italic #fbbf24")
        elif self._chunks:
            text.append(f"  ({len(self._chunks)} thoughts)", style="#6b7280")

        # Collapse indicator
        icon = "▶" if self.collapsed else "▼"
        text.append(f"  {icon}", style="#52525b")

        header.update(text)

    def _update_display(self) -> None:
        """Update the display."""
        self._update_header()

        if self.collapsed:
            return

        try:
            content = self.query_one(".thinking-content", Container)
        except Exception:
            return

        # Clear existing bubbles
        content.remove_children()

        # Add thought bubbles
        visible_chunks = self._chunks[-10:]  # Show last 10
        for chunk in visible_chunks:
            bubble = ThinkingBubble(chunk)
            content.mount(bubble)

        # Add current streaming chunk
        if self._current_text:
            streaming_chunk = ThoughtChunk(
                text=self._current_text,
                thought_type=classify_thought(self._current_text),
                is_streaming=True,
            )
            content.mount(ThinkingBubble(streaming_chunk))

    def clear(self) -> None:
        """Clear all thoughts."""
        self._chunks.clear()
        self._current_text = ""
        self.is_streaming = False

        try:
            content = self.query_one(".thinking-content", Container)
            content.remove_children()
        except Exception:
            pass

        self._update_header()

    def compose(self):
        """Compose the panel."""
        yield Static("", classes="thinking-header")
        with Container(classes="thinking-content"):
            pass


class ExtendedThinkingPanel(Container):
    """
    Extended thinking display for Claude-style extended thinking.

    Shows the full thinking trace with:
    - Collapsible major sections
    - Search through thoughts
    - Copy thinking text
    """

    DEFAULT_CSS = """
    ExtendedThinkingPanel {
        height: auto;
        max-height: 50%;
        border: double #a855f7;
        background: #0d0d0d;
        padding: 1;
        margin: 0 0 1 0;
    }

    ExtendedThinkingPanel .extended-header {
        height: 2;
        border-bottom: solid #27272a;
        margin-bottom: 1;
    }

    ExtendedThinkingPanel .extended-content {
        height: auto;
        max-height: 40;
        overflow-y: auto;
    }

    ExtendedThinkingPanel .extended-footer {
        height: 1;
        border-top: solid #27272a;
        margin-top: 1;
    }
    """

    collapsed: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._thinking_text = ""
        self._token_count = 0

    def set_thinking(self, text: str, token_count: int = 0) -> None:
        """Set the extended thinking text."""
        self._thinking_text = text
        self._token_count = token_count
        self._update_display()

    def append_thinking(self, text: str) -> None:
        """Append to thinking text."""
        self._thinking_text += text
        self._update_display()

    def _update_display(self) -> None:
        """Update the display."""
        try:
            header = self.query_one(".extended-header", Static)
            content = self.query_one(".extended-content", Static)
            footer = self.query_one(".extended-footer", Static)
        except Exception:
            return

        # Header
        header_text = Text()
        header_text.append("🧠 ", style="bold #a855f7")
        header_text.append("Extended Thinking", style="bold #e4e4e7")

        if self._token_count:
            header_text.append(f"  ({self._token_count} tokens)", style="#6b7280")

        header.update(header_text)

        # Content
        if self.collapsed:
            content_text = Text()
            lines = self._thinking_text.splitlines()
            if lines:
                preview = lines[0][:80] + "..." if len(lines[0]) > 80 else lines[0]
                content_text.append(preview, style="italic #a1a1aa")
                if len(lines) > 1:
                    content_text.append(f"\n... ({len(lines)} lines)", style="#52525b")
            content.update(content_text)
        else:
            content.update(Text(self._thinking_text, style="#a1a1aa"))

        # Footer
        footer_text = Text()
        word_count = len(self._thinking_text.split())
        footer_text.append(f"📊 {word_count} words", style="#6b7280")
        footer_text.append("  │  ", style="#27272a")
        footer_text.append("[Space] Toggle", style="#52525b")
        footer.update(footer_text)

    def toggle(self) -> None:
        """Toggle collapsed state."""
        self.collapsed = not self.collapsed
        self._update_display()

    def on_key(self, event: events.Key) -> None:
        """Handle key events."""
        if event.key == "space":
            self.toggle()
            event.prevent_default()

    def clear(self) -> None:
        """Clear thinking."""
        self._thinking_text = ""
        self._token_count = 0
        self._update_display()

    def compose(self):
        """Compose the panel."""
        yield Static("", classes="extended-header")
        yield Static("", classes="extended-content")
        yield Static("", classes="extended-footer")


class ThinkingIndicator(Static):
    """Compact thinking indicator for status bar."""

    DEFAULT_CSS = """
    ThinkingIndicator {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    """

    thinking: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._frame = 0
        self._thought_count = 0

    def set_thinking(self, is_thinking: bool) -> None:
        """Set thinking state."""
        self.thinking = is_thinking
        self.refresh()

    def set_count(self, count: int) -> None:
        """Set thought count."""
        self._thought_count = count
        self.refresh()

    def animate(self) -> None:
        """Advance animation frame."""
        self._frame += 1
        if self.thinking:
            self.refresh()

    def render(self) -> Text:
        text = Text()

        if self.thinking:
            # Animated thinking indicator
            frames = ["💭", "💬", "💭", "💬"]
            icon = frames[self._frame % len(frames)]
            text.append(f"{icon} ", style="bold #ec4899")
            text.append("Thinking...", style="italic #ec4899")
        elif self._thought_count > 0:
            text.append("💭 ", style="#6b7280")
            text.append(f"{self._thought_count}", style="#a1a1aa")
        else:
            text.append("💭 -", style="#52525b")

        return text


class ThinkingSource(Enum):
    """Source of thinking/reasoning content."""

    ACP = "acp"  # ACP agent_thought_chunk
    BYOK = "byok"  # BYOK StreamChunk.thinking_content
    LOCAL = "local"  # Local models (through BYOK gateway)
    OPEN_RESPONSES = "openresponses"  # Open Responses reasoning.delta


@dataclass
class ThinkingStats:
    """Statistics for thinking/reasoning."""

    source: ThinkingSource
    token_count: int = 0
    thought_count: int = 0
    duration_ms: float = 0.0


class UnifiedThinkingManager:
    """
    Routes thinking from any source to ThinkingPanel.

    Provides a unified interface for handling thinking/reasoning content
    from multiple connection modes:
    - ACP: agent_thought_chunk events
    - BYOK: StreamChunk.thinking_content
    - Local: Route through BYOK gateway
    - OpenResponses: response.reasoning.delta events

    Usage:
        panel = ThinkingPanel()
        manager = UnifiedThinkingManager(panel)

        # In ACP mode
        await manager.handle_acp_thought("Planning approach...")

        # In BYOK mode
        await manager.handle_byok_chunk(chunk)

        # In Open Responses mode
        await manager.handle_openresponses_event(event)
    """

    def __init__(
        self,
        panel: ThinkingPanel,
        extended_panel: Optional[ExtendedThinkingPanel] = None,
        indicator: Optional[ThinkingIndicator] = None,
    ):
        self.panel = panel
        self.extended_panel = extended_panel
        self.indicator = indicator
        self._current_source: Optional[ThinkingSource] = None
        self._stats = ThinkingStats(source=ThinkingSource.BYOK)
        self._start_time: Optional[float] = None
        self._is_streaming = False

    def start_session(self, source: ThinkingSource) -> None:
        """Start a new thinking session."""
        self._current_source = source
        self._stats = ThinkingStats(source=source)
        self._start_time = (
            asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else None
        )
        self._is_streaming = False
        self.panel.clear()
        if self.extended_panel:
            self.extended_panel.clear()

    def end_session(self) -> ThinkingStats:
        """End the current thinking session and return stats."""
        if self._start_time:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    self._stats.duration_ms = (loop.time() - self._start_time) * 1000
            except RuntimeError:
                pass

        if self._is_streaming:
            self.panel.complete_thought()
            self._is_streaming = False

        if self.indicator:
            self.indicator.set_thinking(False)
            self.indicator.set_count(self._stats.thought_count)

        return self._stats

    async def handle_acp_thought(self, text: str) -> None:
        """
        Handle ACP agent_thought_chunk.

        ACP sends complete thought chunks, not streaming deltas.
        """
        if not text:
            return

        self._current_source = ThinkingSource.ACP
        self._stats.thought_count += 1

        # ACP thoughts are complete - add directly
        self.panel.add_thought(text)

        if self.indicator:
            self.indicator.set_thinking(True)

    async def handle_byok_chunk(self, chunk: Any) -> None:
        """
        Handle BYOK StreamChunk.thinking_content.

        BYOK sends streaming deltas that need to be accumulated.

        Args:
            chunk: StreamChunk with optional thinking_content field
        """
        thinking_content = getattr(chunk, "thinking_content", None)
        if not thinking_content:
            return

        self._current_source = ThinkingSource.BYOK

        # Start streaming if not already
        if not self._is_streaming:
            self.panel.start_streaming()
            self._is_streaming = True
            if self.indicator:
                self.indicator.set_thinking(True)

        # Append chunk to current streaming thought
        self.panel.append_chunk(thinking_content)

        # Also update extended panel if available
        if self.extended_panel:
            self.extended_panel.append_thinking(thinking_content)

    async def handle_byok_response(self, response: Any) -> None:
        """
        Handle complete BYOK GatewayResponse.thinking_content.

        Called after non-streaming completion with full thinking.

        Args:
            response: GatewayResponse with optional thinking_content field
        """
        thinking_content = getattr(response, "thinking_content", None)
        thinking_tokens = getattr(response, "thinking_tokens", None)

        if not thinking_content:
            return

        self._current_source = ThinkingSource.BYOK
        self._stats.thought_count += 1

        if thinking_tokens:
            self._stats.token_count = thinking_tokens

        # Add complete thought
        self.panel.add_thought(thinking_content)

        # Update extended panel with full content
        if self.extended_panel:
            self.extended_panel.set_thinking(thinking_content, thinking_tokens or 0)

        if self.indicator:
            self.indicator.set_count(self._stats.thought_count)

    async def handle_openresponses_event(self, event: Dict[str, Any]) -> None:
        """
        Handle Open Responses streaming event.

        Open Responses sends multiple event types:
        - response.reasoning.delta: Reasoning text delta
        - response.reasoning.done: Reasoning complete
        - response.output_text.delta: Regular output delta

        Args:
            event: Open Responses streaming event dict
        """
        event_type = event.get("type", "")

        if event_type == "response.reasoning.delta":
            delta = event.get("delta", "")
            if delta:
                self._current_source = ThinkingSource.OPEN_RESPONSES

                if not self._is_streaming:
                    self.panel.start_streaming()
                    self._is_streaming = True
                    if self.indicator:
                        self.indicator.set_thinking(True)

                self.panel.append_chunk(delta)

                if self.extended_panel:
                    self.extended_panel.append_thinking(delta)

        elif event_type == "response.reasoning.done":
            # Reasoning complete - finalize
            if self._is_streaming:
                self.panel.complete_thought()
                self._is_streaming = False
                self._stats.thought_count += 1

            # Extract token count if available
            usage = event.get("usage", {})
            reasoning_tokens = usage.get("reasoning_tokens", 0)
            if reasoning_tokens:
                self._stats.token_count = reasoning_tokens

            if self.indicator:
                self.indicator.set_thinking(False)
                self.indicator.set_count(self._stats.thought_count)

    async def handle_local_thought(self, text: str) -> None:
        """
        Handle Local model thinking (routed through BYOK).

        Local models may provide thinking through various mechanisms
        depending on the model and server.
        """
        if not text:
            return

        self._current_source = ThinkingSource.LOCAL
        self._stats.thought_count += 1

        self.panel.add_thought(text)

        if self.indicator:
            self.indicator.set_thinking(True)

    def complete_streaming(self) -> None:
        """Complete any in-progress streaming thought."""
        if self._is_streaming:
            self.panel.complete_thought()
            self._is_streaming = False
            self._stats.thought_count += 1

        if self.indicator:
            self.indicator.set_thinking(False)

    def get_stats(self) -> ThinkingStats:
        """Get current thinking statistics."""
        return self._stats

    @property
    def current_source(self) -> Optional[ThinkingSource]:
        """Get the current thinking source."""
        return self._current_source

    @property
    def is_streaming(self) -> bool:
        """Check if currently streaming thinking content."""
        return self._is_streaming
