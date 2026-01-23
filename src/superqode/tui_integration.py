"""
TUI Integration - Connect Enhanced Widgets to Main App.

This module provides the integration layer to use the new enhanced
widgets in the main SuperQode app. It handles:

1. Tool call display with rich formatting
2. Thinking/reasoning display with streaming
3. Response formatting with markdown
4. Connection status for ACP/BYOK
5. Conversation history navigation
6. Enhanced status bar

Usage in app_main.py:
    from superqode.tui_integration import TUIEnhancer

    class SuperQodeApp(App):
        def on_mount(self):
            self.tui = TUIEnhancer(self)
            self.tui.setup()
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from time import monotonic

from rich.text import Text
from textual.containers import Container
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import App


@dataclass
class AgentSession:
    """Tracks the current agent session state."""

    # Connection
    connected: bool = False
    connection_type: str = ""  # "acp", "byok", "local"
    agent_name: str = ""
    agent_version: str = ""
    model_name: str = ""
    provider: str = ""
    session_id: str = ""
    connected_at: Optional[datetime] = None

    # Current operation
    is_streaming: bool = False
    is_thinking: bool = False
    current_tool: str = ""

    # Stats
    message_count: int = 0
    tool_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0

    # Files
    files_read: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)


class TUIEnhancer:
    """
    Enhances the SuperQode TUI with rich widgets.

    Provides a clean API for the main app to use the new widgets
    for tool calls, thinking, responses, and status.
    """

    def __init__(self, app: "App"):
        self.app = app
        self.session = AgentSession()

        # Widget references (set during setup)
        self._tool_panel = None
        self._thinking_panel = None
        self._response_display = None
        self._connection_indicator = None
        self._status_bar = None
        self._conversation_nav = None

        # Callbacks
        self._on_tool_click: Optional[Callable] = None
        self._on_message_select: Optional[Callable] = None

    def setup(self) -> None:
        """
        Set up the enhanced TUI components.

        Call this in the app's on_mount() method.
        """
        # Import widgets lazily
        from superqode.widgets import (
            get_rich_tool_display,
            get_thinking_display,
            get_response_display,
            get_connection_status,
            get_enhanced_status_bar,
            get_conversation_history,
        )

        # Get widget classes
        (ToolCallPanel, _, ToolCallData, ToolKind, ToolState, CompactToolIndicator, *_) = (
            get_rich_tool_display()
        )

        (ThinkingPanel, ExtendedThinkingPanel, ThinkingIndicator, *_) = get_thinking_display()

        (ResponseDisplay, StreamingText, *_) = get_response_display()

        (
            ConnectionIndicator,
            ConnectionPanel,
            ModelSelector,
            ConnectionInfo,
            ConnectionType,
            ConnectionState,
            TokenUsage,
        ) = get_connection_status()

        (EnhancedStatusBar, MiniStatusIndicator, StatusBarState, AgentStatus, *_) = (
            get_enhanced_status_bar()
        )

        (
            ConversationTimeline,
            MessageDetail,
            ConversationNavigator,
            HistoryMessage,
            MessageType,
        ) = get_conversation_history()

        # Store classes for later use
        self._classes = {
            "ToolCallPanel": ToolCallPanel,
            "ToolCallData": ToolCallData,
            "ToolKind": ToolKind,
            "ToolState": ToolState,
            "ThinkingPanel": ThinkingPanel,
            "ThinkingIndicator": ThinkingIndicator,
            "ResponseDisplay": ResponseDisplay,
            "ConnectionIndicator": ConnectionIndicator,
            "ConnectionInfo": ConnectionInfo,
            "ConnectionType": ConnectionType,
            "ConnectionState": ConnectionState,
            "TokenUsage": TokenUsage,
            "EnhancedStatusBar": EnhancedStatusBar,
            "AgentStatus": AgentStatus,
            "ConversationNavigator": ConversationNavigator,
            "HistoryMessage": HistoryMessage,
            "MessageType": MessageType,
        }

    # ========================================================================
    # CONNECTION STATUS
    # ========================================================================

    def connect_agent(
        self,
        agent_name: str,
        model_name: str = "",
        provider: str = "",
        connection_type: str = "byok",
    ) -> None:
        """Record agent connection."""
        self.session.connected = True
        self.session.agent_name = agent_name
        self.session.model_name = model_name
        self.session.provider = provider
        self.session.connection_type = connection_type
        self.session.connected_at = datetime.now()
        self.session.session_id = f"session-{int(datetime.now().timestamp())}"

        self._update_status_bar()

    def disconnect_agent(self) -> None:
        """Record agent disconnection."""
        self.session = AgentSession()
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        """Update the status bar with current session state."""
        if self._status_bar:
            AgentStatus = self._classes.get("AgentStatus")

            status = AgentStatus.IDLE
            if self.session.is_streaming:
                status = AgentStatus.STREAMING
            elif self.session.is_thinking:
                status = AgentStatus.THINKING
            elif self.session.current_tool:
                status = AgentStatus.TOOL_CALL

            self._status_bar.update_state(
                connected=self.session.connected,
                connection_type=self.session.connection_type,
                agent_name=self.session.agent_name,
                model_name=self.session.model_name,
                provider=self.session.provider,
                status=status,
                tool_count=self.session.tool_count,
                prompt_tokens=self.session.prompt_tokens,
                completion_tokens=self.session.completion_tokens,
                total_cost=self.session.total_cost,
                message_count=self.session.message_count,
            )

    # ========================================================================
    # TOOL CALLS
    # ========================================================================

    def start_tool(
        self,
        tool_id: str,
        tool_name: str,
        tool_kind: str,
        arguments: Dict[str, Any] = None,
        file_path: str = None,
    ) -> None:
        """Record start of a tool call."""
        ToolCallData = self._classes.get("ToolCallData")
        ToolKind = self._classes.get("ToolKind")
        ToolState = self._classes.get("ToolState")

        if not ToolCallData:
            return

        # Map tool kind string to enum
        kind_map = {
            "read": ToolKind.FILE_READ,
            "write": ToolKind.FILE_WRITE,
            "edit": ToolKind.FILE_EDIT,
            "delete": ToolKind.FILE_DELETE,
            "shell": ToolKind.SHELL,
            "search": ToolKind.SEARCH,
            "glob": ToolKind.GLOB,
            "lsp": ToolKind.LSP,
            "browser": ToolKind.BROWSER,
            "mcp": ToolKind.MCP,
        }
        kind = kind_map.get(tool_kind.lower(), ToolKind.OTHER)

        tool = ToolCallData(
            id=tool_id,
            name=tool_name,
            kind=kind,
            state=ToolState.RUNNING,
            start_time=datetime.now(),
            arguments=arguments or {},
            file_path=file_path,
        )

        self.session.current_tool = tool_name
        self.session.tool_count += 1

        if self._tool_panel:
            self._tool_panel.add_tool(tool)

        self._update_status_bar()

    def complete_tool(
        self,
        tool_id: str,
        result: str = "",
        error: str = "",
        output: str = "",
        exit_code: int = None,
    ) -> None:
        """Record completion of a tool call."""
        self.session.current_tool = ""

        if self._tool_panel:
            self._tool_panel.complete_tool(tool_id, result=result, error=error)

        self._update_status_bar()

    def update_tool_diff(
        self,
        tool_id: str,
        file_path: str,
        old_content: str,
        new_content: str,
    ) -> None:
        """Update a tool call with diff content."""
        if self._tool_panel:
            from superqode.widgets.rich_tool_display import DiffContent, detect_language

            diff = DiffContent(
                path=file_path,
                old_text=old_content,
                new_text=new_content,
                language=detect_language(file_path),
            )

            self._tool_panel.update_tool(tool_id, diff=diff)

    # ========================================================================
    # THINKING / REASONING (with UnifiedThinkingManager support)
    # ========================================================================

    def start_thinking(self) -> None:
        """Start thinking display."""
        self.session.is_thinking = True

        if self._thinking_panel:
            self._thinking_panel.start_streaming()

        self._update_status_bar()

    def add_thought(self, text: str) -> None:
        """Add a thought to the thinking display."""
        if self._thinking_panel:
            if self.session.is_thinking:
                self._thinking_panel.append_chunk(text)
            else:
                self._thinking_panel.add_thought(text)

    def complete_thinking(self) -> None:
        """Complete thinking display."""
        self.session.is_thinking = False

        if self._thinking_panel:
            self._thinking_panel.complete_thought()

        self._update_status_bar()

    def get_thinking_manager(self) -> Optional["UnifiedThinkingManager"]:
        """
        Get a UnifiedThinkingManager for routing thinking from all sources.

        Returns:
            UnifiedThinkingManager if thinking panel is available, None otherwise
        """
        if not self._thinking_panel:
            return None

        from superqode.widgets.thinking_display import UnifiedThinkingManager

        return UnifiedThinkingManager(
            panel=self._thinking_panel,
            extended_panel=getattr(self, "_extended_thinking_panel", None),
            indicator=getattr(self, "_thinking_indicator", None),
        )

    def create_thinking_callbacks(self, connection_type: str = "byok") -> Dict[str, Callable]:
        """
        Create thinking callbacks for different connection types.

        This method creates the appropriate callbacks for routing thinking
        content to the UI based on the connection type (ACP, BYOK, Local,
        OpenResponses).

        Args:
            connection_type: Type of connection ("acp", "byok", "local", "openresponses")

        Returns:
            Dict with callback functions:
            - on_thinking: Callback for thinking text
            - on_thinking_chunk: Callback for streaming chunks
            - on_thinking_complete: Callback for completion

        Usage:
            callbacks = tui.create_thinking_callbacks("byok")
            agent_loop.on_thinking = callbacks["on_thinking"]
        """
        manager = self.get_thinking_manager()

        if not manager:
            # Fallback to basic logging if no panel
            async def noop_thinking(text: str) -> None:
                pass

            return {
                "on_thinking": noop_thinking,
                "on_thinking_chunk": noop_thinking,
                "on_thinking_complete": lambda: None,
            }

        # Import ThinkingSource
        from superqode.widgets.thinking_display import ThinkingSource

        # Map connection type to source
        source_map = {
            "acp": ThinkingSource.ACP,
            "byok": ThinkingSource.BYOK,
            "local": ThinkingSource.LOCAL,
            "openresponses": ThinkingSource.OPEN_RESPONSES,
        }
        source = source_map.get(connection_type, ThinkingSource.BYOK)

        # Start session
        manager.start_session(source)

        # Create callbacks based on connection type
        if connection_type == "acp":

            async def on_thinking(text: str) -> None:
                self.session.is_thinking = True
                self._update_status_bar()
                await manager.handle_acp_thought(text)

            return {
                "on_thinking": on_thinking,
                "on_thinking_chunk": on_thinking,
                "on_thinking_complete": lambda: (
                    manager.complete_streaming(),
                    setattr(self.session, "is_thinking", False),
                    self._update_status_bar(),
                ),
            }

        elif connection_type == "openresponses":

            async def on_thinking_event(event: Dict[str, Any]) -> None:
                self.session.is_thinking = True
                self._update_status_bar()
                await manager.handle_openresponses_event(event)
                if event.get("type") == "response.reasoning.done":
                    self.session.is_thinking = False
                    self._update_status_bar()

            return {
                "on_thinking": on_thinking_event,
                "on_thinking_chunk": on_thinking_event,
                "on_thinking_complete": lambda: (
                    manager.complete_streaming(),
                    setattr(self.session, "is_thinking", False),
                    self._update_status_bar(),
                ),
            }

        else:  # byok, local

            async def on_thinking_chunk(chunk: Any) -> None:
                self.session.is_thinking = True
                self._update_status_bar()
                await manager.handle_byok_chunk(chunk)

            async def on_thinking_text(text: str) -> None:
                """Handle plain text thinking (for models that don't stream)."""
                self.session.is_thinking = True
                self._update_status_bar()

                # Wrap text in a mock chunk
                class MockChunk:
                    thinking_content = text

                await manager.handle_byok_chunk(MockChunk())

            return {
                "on_thinking": on_thinking_text,
                "on_thinking_chunk": on_thinking_chunk,
                "on_thinking_complete": lambda: (
                    manager.complete_streaming(),
                    setattr(self.session, "is_thinking", False),
                    self._update_status_bar(),
                ),
            }

    # ========================================================================
    # RESPONSE
    # ========================================================================

    def start_response(self, agent_name: str = "", model_name: str = "") -> None:
        """Start streaming response."""
        self.session.is_streaming = True

        if self._response_display:
            self._response_display.clear()
            self._response_display.agent_name = agent_name or self.session.agent_name
            self._response_display.model_name = model_name or self.session.model_name

        self._update_status_bar()

    def append_response(self, text: str) -> None:
        """Append text to streaming response."""
        if self._response_display:
            self._response_display.append_text(text)

    def complete_response(self, token_count: int = 0) -> None:
        """Complete the response."""
        self.session.is_streaming = False
        self.session.message_count += 1
        self.session.completion_tokens += token_count

        if self._response_display:
            self._response_display.complete(token_count=token_count)

        self._update_status_bar()

    # ========================================================================
    # TOKEN TRACKING
    # ========================================================================

    def add_tokens(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        """Add token usage."""
        self.session.prompt_tokens += prompt_tokens
        self.session.completion_tokens += completion_tokens
        self.session.total_cost += cost

        self._update_status_bar()

    # ========================================================================
    # FILE TRACKING
    # ========================================================================

    def track_file_read(self, path: str) -> None:
        """Track a file read."""
        if path not in self.session.files_read:
            self.session.files_read.append(path)

    def track_file_modified(self, path: str) -> None:
        """Track a file modification."""
        if path not in self.session.files_modified:
            self.session.files_modified.append(path)

    # ========================================================================
    # CONVERSATION HISTORY
    # ========================================================================

    def add_user_message(self, content: str) -> None:
        """Add a user message to history."""
        self.session.message_count += 1

        if self._conversation_nav:
            self._conversation_nav.set_counts(
                self.session.message_count,
                self.session.message_count - 1,
            )

    def add_assistant_message(
        self,
        content: str,
        agent_name: str = "",
        model_name: str = "",
        token_count: int = 0,
        duration_ms: float = 0,
    ) -> None:
        """Add an assistant message to history."""
        self.session.message_count += 1

        if self._conversation_nav:
            self._conversation_nav.set_counts(
                self.session.message_count,
                self.session.message_count - 1,
            )

    # ========================================================================
    # UTILITIES
    # ========================================================================

    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of current session."""
        return {
            "connected": self.session.connected,
            "agent": self.session.agent_name,
            "model": self.session.model_name,
            "provider": self.session.provider,
            "messages": self.session.message_count,
            "tools": self.session.tool_count,
            "files_read": len(self.session.files_read),
            "files_modified": len(self.session.files_modified),
            "tokens": {
                "prompt": self.session.prompt_tokens,
                "completion": self.session.completion_tokens,
                "total": self.session.prompt_tokens + self.session.completion_tokens,
            },
            "cost": self.session.total_cost,
        }

    def reset_session(self) -> None:
        """Reset the session (keep connection)."""
        connected = self.session.connected
        agent_name = self.session.agent_name
        model_name = self.session.model_name
        provider = self.session.provider
        connection_type = self.session.connection_type

        self.session = AgentSession()

        if connected:
            self.session.connected = connected
            self.session.agent_name = agent_name
            self.session.model_name = model_name
            self.session.provider = provider
            self.session.connection_type = connection_type

        if self._tool_panel:
            self._tool_panel.clear()

        if self._thinking_panel:
            self._thinking_panel.clear()

        self._update_status_bar()


# ============================================================================
# OPENCODE-STYLE UX HELPERS
# ============================================================================


def format_tool_call_opencode_style(
    tool_name: str,
    tool_kind: str,
    arguments: Dict[str, Any],
    status: str = "running",
) -> Text:
    """
    Format a tool call in OpenCode's style.

    Uses a clean, minimal style with:
    - Tool icon based on kind
    - File path prominently displayed
    - Status indicator
    """
    result = Text()

    # Icons similar to OpenCode
    icons = {
        "read": "📖",
        "write": "✏️",
        "edit": "🔧",
        "shell": "💻",
        "search": "🔍",
        "glob": "📁",
    }
    icon = icons.get(tool_kind.lower(), "⚡")

    # Status indicator
    status_icons = {
        "pending": "○",
        "running": "◐",
        "success": "✓",
        "error": "✗",
    }
    status_icon = status_icons.get(status, "○")

    status_colors = {
        "pending": "#6b7280",
        "running": "#fbbf24",
        "success": "#22c55e",
        "error": "#ef4444",
    }
    status_color = status_colors.get(status, "#6b7280")

    result.append(f"{status_icon} ", style=f"bold {status_color}")
    result.append(f"{icon} ", style="#a855f7")
    result.append(tool_name, style="bold #e4e4e7")

    # Show file path if present
    path = arguments.get("path", arguments.get("file_path", arguments.get("filePath", "")))
    if path:
        result.append(f"  {path}", style="#6b7280")

    # Show command for shell
    command = arguments.get("command", "")
    if command:
        cmd_short = command[:50] + "..." if len(command) > 50 else command
        result.append(f"  $ {cmd_short}", style="#a1a1aa")

    return result


def format_thinking_opencode_style(thoughts: List[str]) -> Text:
    """
    Format thinking in OpenCode's style.

    OpenCode shows thinking in a collapsible section with bullet points.
    """
    result = Text()

    result.append("💭 ", style="bold #ec4899")
    result.append("Thinking", style="italic #ec4899")
    result.append(f"  ({len(thoughts)} thoughts)\n", style="#6b7280")

    for thought in thoughts[-5:]:  # Show last 5
        thought_short = thought[:100] + "..." if len(thought) > 100 else thought
        result.append(f"  • {thought_short}\n", style="italic #a1a1aa")

    return result


def format_response_opencode_style(
    text: str,
    agent_name: str,
    duration: float = 0,
    token_count: int = 0,
) -> Text:
    """
    Format response in OpenCode's style.

    Uses clean typography with agent name header.
    """
    result = Text()

    # Header
    result.append("─" * 50 + "\n", style="#27272a")
    result.append("🤖 ", style="#a855f7")
    result.append(agent_name, style="bold #a855f7")

    if duration > 0:
        result.append(f"  ({duration:.1f}s)", style="#6b7280")

    if token_count > 0:
        result.append(f"  {token_count} tokens", style="#52525b")

    result.append("\n─" * 50 + "\n\n", style="#27272a")

    # Content
    result.append(text, style="#e4e4e7")

    return result


# ============================================================================
# WHAT'S MISSING FOR FULL CODING AGENT
# ============================================================================

MISSING_FEATURES = """
# Features Missing for Full Coding Agent

## 1. CORE AGENT CAPABILITIES

### File Operations
- [ ] Undo/redo for file changes (checkpoint system)
- [ ] File change preview before applying
- [ ] Batch file operations with atomic rollback
- [ ] File watching with auto-refresh

### Code Intelligence
- [ ] Go-to-definition integration
- [ ] Find references
- [ ] Symbol search across codebase
- [ ] Inline code completion suggestions

### Terminal
- [ ] True PTY with full terminal emulation ✓ (implemented)
- [ ] Multiple terminal sessions
- [ ] Terminal output streaming to agent
- [ ] Background task management

## 2. TUI FEATURES

### Display
- [x] Rich tool call display with diffs ✓
- [x] Thinking/reasoning display ✓
- [x] Streaming response formatting ✓
- [x] Connection status indicator ✓
- [ ] Split view (code + chat)
- [ ] Image display in terminal
- [ ] Inline file preview on hover

### Navigation
- [x] Conversation history ✓
- [ ] Message search
- [ ] Jump to file from mention
- [ ] Breadcrumb navigation

### Interaction
- [ ] Keyboard shortcuts for common actions
- [ ] Mouse support for clicking file paths
- [ ] Drag-and-drop file support
- [ ] Copy code blocks with one click

## 3. PROVIDER INTEGRATION

### ACP (Agent Client Protocol)
- [x] OpenCode connection ✓
- [x] OpenHands connection ✓
- [ ] Claude Code connection
- [ ] Cursor connection
- [ ] Auto-discovery of ACP agents

### BYOK (Bring Your Own Key)
- [x] LiteLLM integration ✓
- [ ] Provider-specific features (streaming, tools)
- [ ] API key management UI
- [ ] Rate limit handling
- [ ] Cost tracking per provider

## 4. SESSION MANAGEMENT

### Persistence
- [x] Session save/restore ✓
- [x] Session forking ✓
- [x] Session sharing ✓
- [ ] Session templates
- [ ] Auto-save on crash

### Context
- [ ] Project context injection
- [ ] Custom instructions per project
- [ ] Memory across sessions
- [ ] Context window management

## 5. WORKFLOW FEATURES

### Git Integration
- [x] Git-based snapshots ✓
- [ ] Commit message generation
- [ ] PR description generation
- [ ] Diff review mode
- [ ] Branch management

### Testing
- [ ] Test runner integration
- [ ] Coverage visualization
- [ ] Test generation suggestions

### Documentation
- [ ] README generation
- [ ] Docstring generation
- [ ] API documentation

## 6. SAFETY & PERMISSIONS

### Permissions
- [x] Rule-based permissions ✓
- [x] Permission preview ✓
- [ ] Dangerous command detection
- [ ] Sandbox mode for untrusted operations

### Audit
- [ ] Action audit log
- [ ] Cost tracking
- [ ] Token usage analytics

## PRIORITY IMPLEMENTATION ORDER:

1. **High Priority** (Most impactful for UX):
   - Split view (code + chat)
   - Keyboard shortcuts
   - File change preview
   - Undo/redo system

2. **Medium Priority** (Competitive features):
   - Code intelligence integration
   - Multiple terminal sessions
   - Provider-specific features
   - Context management

3. **Lower Priority** (Nice to have):
   - Image display
   - Drag-and-drop
   - Test integration
   - Documentation generation
"""


def get_missing_features() -> str:
    """Get the list of missing features."""
    return MISSING_FEATURES


def print_missing_features() -> None:
    """Print the missing features to console."""
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    console.print(Markdown(MISSING_FEATURES))
