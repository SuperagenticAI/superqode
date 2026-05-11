"""
Thinking Display Widget.

Shows model reasoning/thinking in real-time with collapsible display.
Uses Textual's rich formatting for styled output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from textual.widget import Widget
from textual.widgets import Static
from textual.css.match import match
from textual.css.query import NoMatches


@dataclass
class ThinkingChunk:
    """A chunk of thinking content."""
    text: str
    timestamp: float = 0.0


class ThinkingDisplay(Widget):
    """Widget to display model thinking/reasoning in real-time.
    
    Features:
    - Collapsible thinking panel (toggle with Ctrl+T)
    - Styled output with dim/italic formatting
    - Auto-scroll to latest thinking
    - Maximum buffer size to prevent memory issues
    """

    CSS = """
    ThinkingDisplay {
        height: auto;
        max-height: 10;
        border: solid $accent;
        border-title: "Thinking";
        padding: 1;
    }
    
    ThinkingDisplay.hidden {
        display: none;
    }
    
    .thinking-text {
        text-style: italic;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        name: str | None = None,
        id: str | None = None,
        classes: str = "",
        max_buffer_size: int = 50000,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self.max_buffer_size = max_buffer_size
        self._is_visible = True
        self._thinking_chunks: list[ThinkingChunk] = []
        self._current_thinking = ""
        self._static = Static("", classes="thinking-text")

    def on_mount(self) -> None:
        """Initialize the widget."""
        self.border_title = "Thinking"
        self.update_styles()

    def toggle(self) -> bool:
        """Toggle visibility of thinking display."""
        self._is_visible = not self._is_visible
        if self._is_visible:
            self.remove_class("hidden")
        else:
            self.add_class("hidden")
        return self._is_visible

    def is_visible(self) -> bool:
        """Check if thinking is visible."""
        return self._is_visible

    def add_thinking(self, text: str) -> None:
        """Add thinking content to the display."""
        if not text:
            return
            
        self._current_thinking += text
        
        # Buffer overflow protection
        if len(self._current_thinking) > self.max_buffer_size:
            # Trim older thinking
            self._current_thinking = self._current_thinking[-self.max_buffer_size:]
        
        self.refresh()

    def commit_thinking(self) -> None:
        """Commit current thinking as a completed chunk."""
        if self._current_thinking.strip():
            self._thinking_chunks.append(
                ThinkingChunk(text=self._current_thinking.strip())
            )
            self._current_thinking = ""
            self.refresh()

    def clear(self) -> None:
        """Clear all thinking content."""
        self._thinking_chunks.clear()
        self._current_thinking = ""
        self.refresh()

    def render(self) -> str:
        """Render thinking content."""
        if not self._is_visible:
            return ""
        
        parts = []
        
        # Show completed thinking chunks
        for chunk in self._thinking_chunks[-5:]:  # Last 5 chunks
            truncated = chunk.text[:200] + "..." if len(chunk.text) > 200 else chunk.text
            parts.append(f"[dim italic]{truncated}[/]")
        
        # Show current thinking
        if self._current_thinking:
            truncated = self._current_thinking[:200] + "..." if len(self._current_thinking) > 200 else self._current_thinking
            parts.append(f"[dim italic]{truncated}[/]")
        
        if not parts:
            return "[dim]No thinking yet...[/dim]"
        
        return "\n".join(parts)

    def watch_classes(self, classes: str) -> None:
        """Handle class changes."""
        super().watch_classes(classes)


class ThinkingBuffer:
    """Buffer to collect thinking content from streaming responses.
    
    Usage:
        buffer = ThinkingBuffer()
        buffer.add_chunk("Analyzing the codebase...")
        buffer.add_chunk("Found 3 potential issues...")
        # Get thinking when complete
        thinking = buffer.get_thinking()
    """

    def __init__(self, max_size: int = 50000):
        self.max_size = max_size
        self._chunks: list[str] = []

    def add_chunk(self, text: str) -> None:
        """Add a chunk of thinking text."""
        self._chunks.append(text)
        
        # Trim if exceeds max size
        total = "".join(self._chunks)
        if len(total) > self.max_size:
            self._chunks = [total[-self.max_size:]]

    def get_thinking(self) -> str:
        """Get all thinking content."""
        return "".join(self._chunks)

    def clear(self) -> None:
        """Clear the buffer."""
        self._chunks.clear()

    def has_content(self) -> bool:
        """Check if buffer has content."""
        return bool(self._chunks)


def parse_thinking_from_response(response_text: str) -> tuple[Optional[str], str]:
    """Parse thinking blocks from model response.
    
    Handles formats like:
    - Anthropic: <think>thinking[/reasoning]
    - OpenAI: <thinking>...</thinking>
    - Google: @extended_thinking
    
    Returns:
        tuple of (thinking_text, remaining_content)
    """
    import re
    
    # Anthropic format:<think>...[/reasoning]
    anthro_match = re.search(r'<think>(.*?)(?:[/ reasoning]|$)', response_text, re.DOTALL)
    if anthro_match:
        thinking = anthro_match.group(1).strip()
        remaining = response_text[:anthro_match.start()] + response_text[anthro_match.end():]
        return thinking, remaining
    
    # OpenAI format: <thinking>...</thinking>
    openai_match = re.search(r'<thinking>(.*?)</thinking>', response_text, re.DOTALL)
    if openai_match:
        thinking = openai_match.group(1).strip()
        remaining = response_text[:openai_match.start()] + response_text[openai_match.end():]
        return thinking, remaining
    
    return None, response_text