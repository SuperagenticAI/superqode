"""
Enhanced App Layout - OpenCode-Style TUI.

This module provides an enhanced app layout that integrates all the new
TUI widgets for a competitive coding agent experience.

To use: Import EnhancedAppMixin and mix it into SuperQodeApp, or use
the compose_enhanced() method in your existing compose().
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Static, Input, Footer
from textual.reactive import reactive

from rich.text import Text


class EnhancedLayout(Container):
    """
    Enhanced layout container with OpenCode-style UX.

    Layout:
    ┌─────────────────────────────────────────────────────────────────┐
    │ [Enhanced Status Bar - connection, model, tokens, cost]         │
    ├──────────────────────┬──────────────────────────────────────────┤
    │                      │ [Tool Call Panel - collapsible]          │
    │                      ├──────────────────────────────────────────┤
    │   [Sidebar]          │ [Thinking Panel - collapsible]           │
    │   - Files            ├──────────────────────────────────────────┤
    │   - Git Status       │                                          │
    │   - Context          │ [Conversation / Response Area]           │
    │                      │                                          │
    │                      │                                          │
    │                      ├──────────────────────────────────────────┤
    │                      │ [Prompt Input]                           │
    └──────────────────────┴──────────────────────────────────────────┘
    """

    DEFAULT_CSS = """
    EnhancedLayout {
        height: 100%;
        width: 100%;
    }

    EnhancedLayout #enhanced-main {
        height: 100%;
    }

    EnhancedLayout #enhanced-sidebar {
        width: 30;
        border-right: solid #27272a;
        background: #0a0a0a;
    }

    EnhancedLayout #enhanced-sidebar.collapsed {
        width: 0;
        display: none;
    }

    EnhancedLayout #enhanced-content {
        width: 1fr;
    }

    EnhancedLayout #enhanced-status {
        height: 1;
        dock: top;
    }

    EnhancedLayout #enhanced-tools {
        height: auto;
        max-height: 30%;
    }

    EnhancedLayout #enhanced-tools.collapsed {
        max-height: 3;
    }

    EnhancedLayout #enhanced-thinking {
        height: auto;
        max-height: 20%;
    }

    EnhancedLayout #enhanced-thinking.collapsed {
        max-height: 2;
    }

    EnhancedLayout #enhanced-conversation {
        height: 1fr;
        overflow-y: auto;
    }

    EnhancedLayout #enhanced-prompt-area {
        height: auto;
        min-height: 3;
        max-height: 10;
        dock: bottom;
        border-top: solid #27272a;
        padding: 1;
    }

    EnhancedLayout #enhanced-prompt-input {
        width: 100%;
    }
    """

    # State
    sidebar_visible: reactive[bool] = reactive(True)
    tools_collapsed: reactive[bool] = reactive(True)
    thinking_collapsed: reactive[bool] = reactive(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tui_enhancer = None

    def compose(self) -> ComposeResult:
        """Compose the enhanced layout."""
        # Import widgets
        from superqode.widgets import (
            get_rich_tool_display,
            get_thinking_display,
            get_connection_status,
            get_enhanced_status_bar,
        )

        # Get classes
        ToolCallPanel, *_ = get_rich_tool_display()
        ThinkingPanel, *_ = get_thinking_display()
        ConnectionIndicator, *_ = get_connection_status()
        EnhancedStatusBar, *_ = get_enhanced_status_bar()

        # Status bar at top
        yield EnhancedStatusBar(id="enhanced-status")

        # Main horizontal split
        with Horizontal(id="enhanced-main"):
            # Sidebar
            with Container(id="enhanced-sidebar"):
                yield Static(self._render_sidebar_header(), id="sidebar-header")
                yield Static("", id="sidebar-content")

            # Main content area
            with Vertical(id="enhanced-content"):
                # Tool calls panel (collapsible)
                yield ToolCallPanel(id="enhanced-tools", classes="collapsed")

                # Thinking panel (collapsible)
                yield ThinkingPanel(id="enhanced-thinking", classes="collapsed")

                # Conversation area
                with ScrollableContainer(id="enhanced-conversation"):
                    yield Static("", id="conversation-content")

                # Prompt area
                with Container(id="enhanced-prompt-area"):
                    yield Static(self._render_prompt_prefix(), id="prompt-prefix")
                    yield Input(
                        placeholder="Ask anything... (type :help for commands)",
                        id="enhanced-prompt-input",
                    )

    def _render_sidebar_header(self) -> Text:
        """Render sidebar header."""
        text = Text()
        text.append("📁 ", style="#3b82f6")
        text.append("Files", style="bold #e4e4e7")
        return text

    def _render_prompt_prefix(self) -> Text:
        """Render prompt prefix."""
        text = Text()
        text.append("🖋️ ", style="#a855f7")
        return text

    def toggle_sidebar(self) -> None:
        """Toggle sidebar visibility."""
        self.sidebar_visible = not self.sidebar_visible
        sidebar = self.query_one("#enhanced-sidebar")
        if self.sidebar_visible:
            sidebar.remove_class("collapsed")
        else:
            sidebar.add_class("collapsed")

    def toggle_tools(self) -> None:
        """Toggle tools panel."""
        self.tools_collapsed = not self.tools_collapsed
        tools = self.query_one("#enhanced-tools")
        if self.tools_collapsed:
            tools.add_class("collapsed")
        else:
            tools.remove_class("collapsed")

    def toggle_thinking(self) -> None:
        """Toggle thinking panel."""
        self.thinking_collapsed = not self.thinking_collapsed
        thinking = self.query_one("#enhanced-thinking")
        if self.thinking_collapsed:
            thinking.add_class("collapsed")
        else:
            thinking.remove_class("collapsed")

    def get_status_bar(self):
        """Get the status bar widget."""
        try:
            return self.query_one("#enhanced-status")
        except Exception:
            return None

    def get_tool_panel(self):
        """Get the tool panel widget."""
        try:
            return self.query_one("#enhanced-tools")
        except Exception:
            return None

    def get_thinking_panel(self):
        """Get the thinking panel widget."""
        try:
            return self.query_one("#enhanced-thinking")
        except Exception:
            return None


def create_enhanced_app_mixin():
    """
    Create a mixin class that adds enhanced TUI features to SuperQodeApp.

    Usage:
        from superqode.app_enhanced import create_enhanced_app_mixin

        EnhancedMixin = create_enhanced_app_mixin()

        class MyApp(EnhancedMixin, SuperQodeApp):
            pass
    """

    class EnhancedAppMixin:
        """Mixin that adds enhanced TUI features."""

        def setup_enhanced_tui(self):
            """Set up enhanced TUI components."""
            from superqode.tui_integration import TUIEnhancer

            self._tui_enhancer = TUIEnhancer(self)
            self._tui_enhancer.setup()

        @property
        def tui(self):
            """Get the TUI enhancer."""
            if not hasattr(self, "_tui_enhancer"):
                self.setup_enhanced_tui()
            return self._tui_enhancer

        # Tool call helpers
        def _show_tool_start(self, tool_id, tool_name, tool_kind, arguments=None, file_path=None):
            """Show tool start with enhanced display."""
            self.tui.start_tool(tool_id, tool_name, tool_kind, arguments, file_path)

        def _show_tool_complete(self, tool_id, result="", error=""):
            """Show tool completion."""
            self.tui.complete_tool(tool_id, result=result, error=error)

        # Thinking helpers
        def _show_thinking_start(self):
            """Start thinking display."""
            self.tui.start_thinking()

        def _show_thinking_chunk(self, text):
            """Add thinking chunk."""
            self.tui.add_thought(text)

        def _show_thinking_complete(self):
            """Complete thinking."""
            self.tui.complete_thinking()

        # Response helpers
        def _show_response_start(self, agent_name="", model_name=""):
            """Start response streaming."""
            self.tui.start_response(agent_name, model_name)

        def _show_response_chunk(self, text):
            """Add response chunk."""
            self.tui.append_response(text)

        def _show_response_complete(self, token_count=0):
            """Complete response."""
            self.tui.complete_response(token_count)

        # Connection helpers
        def _connect_agent_enhanced(
            self, agent_name, model_name="", provider="", connection_type="byok"
        ):
            """Connect to agent with enhanced status."""
            self.tui.connect_agent(agent_name, model_name, provider, connection_type)

        def _disconnect_agent_enhanced(self):
            """Disconnect agent."""
            self.tui.disconnect_agent()

    return EnhancedAppMixin


# ============================================================================
# EXAMPLE: How to integrate into app_main.py
# ============================================================================

INTEGRATION_EXAMPLE = '''
# In app_main.py, modify the SuperQodeApp class:

from superqode.app_enhanced import create_enhanced_app_mixin
from superqode.tui_integration import TUIEnhancer

EnhancedMixin = create_enhanced_app_mixin()

class SuperQodeApp(EnhancedMixin, App):
    # ... existing code ...

    def on_mount(self):
        # Existing mount code...
        self.query_one("#prompt-input", Input).focus()
        self._load_welcome()

        # NEW: Set up enhanced TUI
        self.setup_enhanced_tui()

    # In the ACP message handling, update to use enhanced widgets:

    async def _handle_acp_tool_call(self, update):
        """Handle tool call from ACP agent."""
        tool_id = update.get("toolCallId", "")
        title = update.get("title", "")
        kind = update.get("kind", "other")
        raw_input = update.get("rawInput", {})

        # NEW: Use enhanced tool display
        self._show_tool_start(tool_id, title, kind, raw_input)

        # Track files
        file_path = raw_input.get("path", "")
        if file_path:
            if kind in ("edit", "write"):
                self.tui.track_file_modified(file_path)
            elif kind == "read":
                self.tui.track_file_read(file_path)

    async def _handle_acp_tool_update(self, update):
        """Handle tool update from ACP agent."""
        tool_id = update.get("toolCallId", "")
        status = update.get("status", "")
        output = update.get("output", "")

        if status == "completed":
            # NEW: Use enhanced display
            self._show_tool_complete(tool_id, result=output)
        elif status == "failed":
            self._show_tool_complete(tool_id, error=output)

    async def _handle_acp_thought(self, update):
        """Handle thought/reasoning from ACP agent."""
        content = update.get("content", {})
        text = content.get("text", "")

        if text:
            # NEW: Use enhanced thinking display
            self._show_thinking_chunk(text)

    async def _handle_acp_message(self, update):
        """Handle message chunk from ACP agent."""
        content = update.get("content", {})
        text = content.get("text", "")

        if text:
            # NEW: Use enhanced response display
            self._show_response_chunk(text)

    # When connecting to an agent:

    def _connect_to_opencode(self, model):
        """Connect to OpenCode."""
        # Existing connection code...

        # NEW: Update enhanced status
        self._connect_agent_enhanced(
            agent_name="OpenCode",
            model_name=model,
            provider="opencode",
            connection_type="acp",
        )
'''


def get_integration_example() -> str:
    """Get the integration example code."""
    return INTEGRATION_EXAMPLE
