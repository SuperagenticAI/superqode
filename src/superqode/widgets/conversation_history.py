"""
Conversation History Widget - Navigate and Search Past Messages.

Provides conversation history management:
- Message timeline navigation
- Search through history
- Jump to specific messages
- Copy/export messages
- Session summaries

Makes it easy to reference and navigate long conversations.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from rich.box import ROUNDED
from textual.reactive import reactive
from textual.widgets import Static, Input
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual import events


class MessageType(Enum):
    """Type of conversation message."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    ERROR = "error"


@dataclass
class HistoryMessage:
    """A message in the conversation history."""

    id: str
    message_type: MessageType
    content: str
    timestamp: datetime = field(default_factory=datetime.now)

    # Optional metadata
    agent_name: str = ""
    model_name: str = ""
    tool_name: str = ""
    token_count: int = 0
    duration_ms: float = 0

    # File references
    files_mentioned: List[str] = field(default_factory=list)

    @property
    def preview(self) -> str:
        """Get a short preview of the message."""
        text = self.content.strip()
        if len(text) > 80:
            return text[:77] + "..."
        return text

    @property
    def time_str(self) -> str:
        """Get formatted timestamp."""
        return self.timestamp.strftime("%H:%M")


MESSAGE_STYLES = {
    MessageType.USER: {"icon": "👤", "color": "#3b82f6", "label": "You"},
    MessageType.ASSISTANT: {"icon": "🤖", "color": "#a855f7", "label": "Agent"},
    MessageType.SYSTEM: {"icon": "⚙️", "color": "#6b7280", "label": "System"},
    MessageType.TOOL: {"icon": "🔧", "color": "#f59e0b", "label": "Tool"},
    MessageType.ERROR: {"icon": "❌", "color": "#ef4444", "label": "Error"},
}


class MessagePreview(Static):
    """Preview widget for a single message."""

    DEFAULT_CSS = """
    MessagePreview {
        height: 2;
        padding: 0 1;
        margin: 0;
    }

    MessagePreview:hover {
        background: #1a1a1a;
    }

    MessagePreview.selected {
        background: #1a1a2a;
        border-left: tall #3b82f6;
    }
    """

    selected: reactive[bool] = reactive(False)

    def __init__(
        self,
        message: HistoryMessage,
        on_select: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.message = message
        self._on_select = on_select

    def on_click(self, event: events.Click) -> None:
        """Handle click."""
        if self._on_select:
            self._on_select()

    def watch_selected(self, selected: bool) -> None:
        """React to selection changes."""
        if selected:
            self.add_class("selected")
        else:
            self.remove_class("selected")

    def render(self) -> Text:
        style = MESSAGE_STYLES.get(self.message.message_type, MESSAGE_STYLES[MessageType.ASSISTANT])

        result = Text()

        # Time and icon
        result.append(f"{self.message.time_str} ", style="#52525b")
        result.append(f"{style['icon']} ", style=style["color"])

        # Sender
        label = self.message.agent_name or style["label"]
        result.append(f"{label}: ", style=f"bold {style['color']}")

        # Preview
        result.append(self.message.preview, style="#a1a1aa")

        return result


class ConversationTimeline(Container):
    """
    Timeline view of conversation history.

    Shows messages in chronological order with quick navigation.
    """

    DEFAULT_CSS = """
    ConversationTimeline {
        height: 100%;
        border: solid #27272a;
        background: #0a0a0a;
    }

    ConversationTimeline .timeline-header {
        height: 3;
        border-bottom: solid #27272a;
        padding: 1;
    }

    ConversationTimeline .timeline-search {
        height: 3;
        border-bottom: solid #27272a;
        padding: 0 1;
    }

    ConversationTimeline .timeline-content {
        height: 1fr;
        overflow-y: auto;
    }

    ConversationTimeline .timeline-footer {
        height: 2;
        border-top: solid #27272a;
        padding: 0 1;
    }
    """

    selected_index: reactive[int] = reactive(-1)
    search_query: reactive[str] = reactive("")

    def __init__(
        self,
        on_message_select: Optional[Callable[[HistoryMessage], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._messages: List[HistoryMessage] = []
        self._filtered: List[HistoryMessage] = []
        self._on_message_select = on_message_select

    def add_message(self, message: HistoryMessage) -> None:
        """Add a message to history."""
        self._messages.append(message)
        self._apply_filter()
        self._update_display()

    def set_messages(self, messages: List[HistoryMessage]) -> None:
        """Set all messages."""
        self._messages = list(messages)
        self._apply_filter()
        self._update_display()

    def clear(self) -> None:
        """Clear history."""
        self._messages.clear()
        self._filtered.clear()
        self.selected_index = -1
        self._update_display()

    def _apply_filter(self) -> None:
        """Apply search filter."""
        if not self.search_query:
            self._filtered = list(self._messages)
        else:
            query = self.search_query.lower()
            self._filtered = [
                m
                for m in self._messages
                if query in m.content.lower() or query in m.agent_name.lower()
            ]

    def watch_search_query(self, query: str) -> None:
        """React to search query changes."""
        self._apply_filter()
        self._update_display()

    def watch_selected_index(self, index: int) -> None:
        """React to selection changes."""
        self._update_selection()

        if 0 <= index < len(self._filtered) and self._on_message_select:
            self._on_message_select(self._filtered[index])

    def _update_selection(self) -> None:
        """Update selection state."""
        try:
            content = self.query_one(".timeline-content", ScrollableContainer)
            for i, widget in enumerate(content.children):
                if isinstance(widget, MessagePreview):
                    widget.selected = i == self.selected_index
        except Exception:
            pass

    def _update_display(self) -> None:
        """Update the display."""
        try:
            header = self.query_one(".timeline-header", Static)
            content = self.query_one(".timeline-content", ScrollableContainer)
            footer = self.query_one(".timeline-footer", Static)
        except Exception:
            return

        # Header
        header_text = Text()
        header_text.append("📜 ", style="bold #3b82f6")
        header_text.append("Conversation History", style="bold #e4e4e7")
        header_text.append(f"  ({len(self._messages)} messages)", style="#6b7280")
        header.update(header_text)

        # Content - message previews
        content.remove_children()
        for i, message in enumerate(self._filtered[-50:]):  # Show last 50
            preview = MessagePreview(
                message,
                on_select=lambda idx=i: self._select_message(idx),
            )
            if i == self.selected_index:
                preview.selected = True
            content.mount(preview)

        # Footer
        footer_text = Text()
        footer_text.append("[↑/↓] Navigate  ", style="#52525b")
        footer_text.append("[Enter] View  ", style="#52525b")
        footer_text.append("[/] Search", style="#52525b")
        footer.update(footer_text)

    def _select_message(self, index: int) -> None:
        """Select a message by index."""
        self.selected_index = index

    def on_key(self, event: events.Key) -> None:
        """Handle keyboard navigation."""
        if event.key == "up":
            self.selected_index = max(0, self.selected_index - 1)
            event.prevent_default()
        elif event.key == "down":
            self.selected_index = min(len(self._filtered) - 1, self.selected_index + 1)
            event.prevent_default()
        elif event.key == "home":
            self.selected_index = 0
            event.prevent_default()
        elif event.key == "end":
            self.selected_index = len(self._filtered) - 1
            event.prevent_default()

    def compose(self):
        """Compose the timeline."""
        yield Static("", classes="timeline-header")
        yield Input(placeholder="Search messages...", classes="timeline-search")
        yield ScrollableContainer(classes="timeline-content")
        yield Static("", classes="timeline-footer")

    def on_mount(self) -> None:
        """Initialize."""
        self._update_display()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input."""
        self.search_query = event.value


class MessageDetail(Container):
    """
    Detailed view of a single message.

    Shows full message content with metadata.
    """

    DEFAULT_CSS = """
    MessageDetail {
        height: auto;
        border: solid #27272a;
        background: #0a0a0a;
        padding: 1;
    }

    MessageDetail .detail-header {
        height: 2;
        margin-bottom: 1;
    }

    MessageDetail .detail-content {
        height: auto;
        padding: 0 1;
    }

    MessageDetail .detail-meta {
        height: auto;
        margin-top: 1;
        border-top: solid #27272a;
        padding-top: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._message: Optional[HistoryMessage] = None

    def set_message(self, message: Optional[HistoryMessage]) -> None:
        """Set the message to display."""
        self._message = message
        self._update_display()

    def _update_display(self) -> None:
        """Update the display."""
        try:
            header = self.query_one(".detail-header", Static)
            content = self.query_one(".detail-content", Static)
            meta = self.query_one(".detail-meta", Static)
        except Exception:
            return

        if not self._message:
            header.update(Text("No message selected", style="#52525b"))
            content.update("")
            meta.update("")
            return

        msg = self._message
        style = MESSAGE_STYLES.get(msg.message_type, MESSAGE_STYLES[MessageType.ASSISTANT])

        # Header
        header_text = Text()
        header_text.append(f"{style['icon']} ", style=style["color"])

        label = msg.agent_name or style["label"]
        header_text.append(label, style=f"bold {style['color']}")

        if msg.model_name:
            header_text.append(f"  ({msg.model_name})", style="#6b7280")

        header_text.append(f"\n{msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')}", style="#52525b")

        header.update(header_text)

        # Content
        content.update(Text(msg.content, style="#e4e4e7"))

        # Metadata
        meta_text = Text()

        if msg.token_count:
            meta_text.append(f"📊 {msg.token_count} tokens", style="#6b7280")

        if msg.duration_ms:
            if meta_text:
                meta_text.append("  │  ", style="#27272a")
            meta_text.append(f"⏱️ {msg.duration_ms:.0f}ms", style="#6b7280")

        if msg.files_mentioned:
            if meta_text:
                meta_text.append("\n")
            meta_text.append(f"📁 Files: {', '.join(msg.files_mentioned[:3])}", style="#6b7280")
            if len(msg.files_mentioned) > 3:
                meta_text.append(f" +{len(msg.files_mentioned) - 3} more", style="#52525b")

        meta.update(meta_text)

    def compose(self):
        """Compose the detail view."""
        yield Static("", classes="detail-header")
        yield Static("", classes="detail-content")
        yield Static("", classes="detail-meta")


class ConversationNavigator(Static):
    """
    Compact conversation navigator for quick jumping.

    Shows message count and allows jumping to messages.
    """

    DEFAULT_CSS = """
    ConversationNavigator {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        on_open_history: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._message_count = 0
        self._current_index = 0
        self._on_open_history = on_open_history

    def set_counts(self, total: int, current: int = 0) -> None:
        """Set message counts."""
        self._message_count = total
        self._current_index = current
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        """Handle click to open history."""
        if self._on_open_history:
            self._on_open_history()

    def render(self) -> Text:
        text = Text()

        text.append("📜 ", style="#3b82f6")

        if self._message_count == 0:
            text.append("No messages", style="#52525b")
        else:
            text.append(f"{self._current_index + 1}/{self._message_count}", style="#a1a1aa")

        return text
