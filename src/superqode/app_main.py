"""
SuperQode Textual App - Multi-Agent Software Coding Team

Features:
- ASCII logo with gradient colors
- Rich animated thinking indicators (rainbow gradient, particles, matrix)
- Detailed agent connection UI with model/role info
- Pulsing progress bar with wave effects
- Sidebar with team/files
- Command autocompletion
- Multi-agent handoff
- Colorful emojis throughout

Note: This module imports from superqode.app/ package for modular components.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import shutil
import time
import math
import random
import concurrent.futures
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, Center, ScrollableContainer
from textual.widgets import Static, Input, Footer, RichLog, DirectoryTree
from textual.binding import Binding
from textual.reactive import reactive, var
from textual.suggester import Suggester
from textual import work, on, events
from textual.timer import Timer

from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown
from rich.rule import Rule
from rich.console import Group
from rich.box import ROUNDED, DOUBLE, HEAVY

# Import from modular app package
from superqode.app.constants import (
    ASCII_LOGO,
    COMPACT_LOGO,
    TAGLINE_PART1,
    TAGLINE_PART2,
    GRADIENT,
    RAINBOW,
    THEME,
    ICONS,
    AGENT_COLORS,
    AGENT_ICONS,
    THINKING_MSGS,
    COMMANDS,
)
from superqode.app.css import APP_CSS
from superqode.app.models import AgentStatus, AgentInfo, check_installed, load_agents_sync
from superqode.app.suggester import CommandSuggester
from superqode.app.widgets import (
    GradientLogo,
    ColorfulStatusBar,
    GradientTagline,
    PulseWaveBar,
    RainbowProgressBar,
    ScanningLine,
    TopScanningLine,
    BottomScanningLine,
    ProgressChase,
    SparkleTrail,
    ThinkingWave,
    StreamingThinkingIndicator,
    ModeBadge,
    HintsBar,
    ConversationLog,
    ApprovalWidget,
    DiffDisplay,
    PlanDisplay,
    ToolCallDisplay,
    FlashMessage,
    DangerWarning,
)
from superqode.widgets.leader_key import LeaderKeyPopup

# QE roles that should be highlighted as power roles in the TUI.
POWER_QE_ROLES = {
    "unit_tester",
    "integration_tester",
    "api_tester",
    "ui_tester",
    "accessibility_tester",
    "security_tester",
    "usability_tester",
}

# SuperQode modules
from superqode.danger import (
    analyze_command,
    DangerLevel,
    DANGER_STYLES,
    is_safe,
    is_destructive,
    requires_approval,
)
from superqode.diff_view import (
    compute_diff,
    render_diff,
    render_diff_unified,
    render_diff_split,
    DiffMode,
    DiffViewer,
    FileDiff,
)
from superqode.approval import (
    ApprovalManager,
    ApprovalRequest,
    ApprovalAction,
    render_approval_request,
    render_approval_list,
)
from superqode.plan import (
    PlanManager,
    PlanTask,
    TaskStatus,
    TaskPriority,
    render_plan,
    render_plan_compact,
    render_current_task,
)
from superqode.tool_call import (
    ToolCallManager,
    ToolCall as ToolCallData,
    ToolStatus,
    ToolKind,
    render_tool_call,
    render_tool_calls,
)
from superqode.flash import (
    FlashManager,
    FlashStyle,
    flash_success,
    flash_warning,
    flash_error,
    flash_info,
)
from superqode.atomic import AtomicFileManager, atomic_write, atomic_read
from superqode.file_viewer import (
    FileViewer,
    render_file,
    render_file_preview,
    render_file_info,
    get_file_info,
    detect_language,
)
from superqode.history import HistoryManager, HistoryEntry, render_history
from superqode.sidebar import (
    get_file_diff,
    EnhancedSidebar,
    CompactSidebar,
    ColorfulDirectoryTree,
    FilePreview,
    get_file_icon,
    get_folder_icon,
    # Tabbed sidebar components
    CollapsibleSidebar,
    GitStatusWidget,
    FileSearch,
    SidebarTabs,
    GitChangesPanel,
    CodebaseSearch,
    get_git_changes,
)
from superqode.agent_output import (
    format_agent_output_for_log,
    create_simple_response_panel,
    render_thinking_section,
    render_full_response,
    ThinkingLine,
    AgentResponse,
    COLORS as OUTPUT_COLORS,
)

# SuperQode Enhanced Display (unique design system)
from superqode.design_system import (
    COLORS as SQ_COLORS,
    GRADIENT_PURPLE,
    SUPERQODE_ICONS,
    render_gradient_text,
    render_status_indicator,
)
from superqode.undo_manager import UndoManager
from superqode.safety import (
    get_safety_warnings,
    show_safety_warnings,
    get_warning_acknowledgment,
    WarningSeverity,
    should_skip_warnings,
    mark_warnings_acknowledged,
)

# Constants, models, CSS, widgets are imported from superqode.app package
# See imports above for what's available


# ============================================================================
# SELECTION-AWARE INPUT
# ============================================================================


class SelectionAwareInput(Input):
    """
    Custom Input that passes arrow keys and number keys to parent when app is in selection mode.

    Standard Textual Input captures up/down arrows for cursor/history navigation,
    which prevents the App's on_key handler from receiving them during
    provider/model selection modes. This subclass intercepts arrow keys and number keys
    and directly calls the app's navigation/selection actions when in selection mode.
    """

    def _is_in_selection_mode_for_number_keys(self, app) -> bool:
        """Check if the app is in a selection mode that supports number key shortcuts.

        Note: BYOK model selection and local model selection are excluded -
        users should type model names/numbers in the input field for those.
        """
        return (
            getattr(app, "_awaiting_acp_agent_selection", False)
            or getattr(app, "_awaiting_byok_provider", False)
            or getattr(app, "_awaiting_connect_type", False)
            or getattr(app, "_awaiting_local_provider", False)
            or getattr(app, "_awaiting_model_selection", False)
            # Excluded: _awaiting_byok_model, _awaiting_local_model
            # Users should type in the input for model selection
        )

    def on_key(self, event: events.Key) -> None:
        """Intercept key events for selection navigation and number selection."""
        app = self.app

        # Handle number keys during selection modes
        if event.key in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            # For BYOK/local provider/model selection, buffer digits for multi-digit entry
            if (
                getattr(app, "_awaiting_byok_provider", False)
                or getattr(app, "_awaiting_local_provider", False)
                or getattr(app, "_awaiting_byok_model", False)
                or getattr(app, "_awaiting_local_model", False)
            ):
                event.stop()
                event.prevent_default()
                if hasattr(app, "_queue_selection_digit"):
                    app._queue_selection_digit(event.key)
                return

            if self._is_in_selection_mode_for_number_keys(app):
                # Prevent the number from being typed into input
                event.stop()
                event.prevent_default()
                # Call the universal selection handler
                num = int(event.key)
                if hasattr(app, "_select_by_number_universal"):
                    app._select_by_number_universal(num)
                return

        # Check if we should handle arrow keys for selection navigation
        if event.key in ("up", "down"):
            # Check each selection mode and call the appropriate action
            if getattr(app, "_awaiting_acp_agent_selection", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_acp_agent_up()
                else:
                    app.action_navigate_acp_agent_down()
                return

            if getattr(app, "_awaiting_byok_model", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_model_up()
                else:
                    app.action_navigate_model_down()
                return

            if getattr(app, "_awaiting_byok_provider", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_provider_up()
                else:
                    app.action_navigate_provider_down()
                return

            if getattr(app, "_awaiting_connect_type", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_connect_type_up()
                else:
                    app.action_navigate_connect_type_down()
                return

            # Don't handle arrow keys for local providers/models in Input widget
            # Let them bubble up to App-level handler instead
            # This prevents conflicts and ensures consistent behavior

            if getattr(app, "_awaiting_model_selection", False):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    app.action_navigate_opencode_model_up()
                else:
                    app.action_navigate_opencode_model_down()
                return

        # For all other keys or when not in selection mode, let parent handle it
        # Don't call super().on_key() as Input doesn't have this method
        pass


# ============================================================================
# WELCOME SCREEN
# ============================================================================


def render_welcome(agents: List[AgentInfo], team_name: str = "Development Team") -> Group:
    from rich.align import Align

    items = []

    # ═══════════════════════════════════════════════════════════════════════
    # BIG ASCII LOGO with gradient - the hero element (centered)
    # ═══════════════════════════════════════════════════════════════════════
    logo_text = Text()
    logo_text.append("\n", style="")
    lines = ASCII_LOGO.strip().split("\n")
    for i, line in enumerate(lines):
        color = GRADIENT[i % len(GRADIENT)]
        logo_text.append(f"{line}\n", style=f"bold {color}")
    items.append(Align.center(logo_text))

    # Spacing
    items.append(Text("\n", style=""))

    # ═══════════════════════════════════════════════════════════════════════
    # DESCRIPTION SECTION - Compelling description about SuperQode
    # ═══════════════════════════════════════════════════════════════════════
    desc_text = Text()
    desc_text.append(
        "SuperQode = Superior Quality Oriented Development Engine\n", style="bold #ffffff"
    )
    desc_text.append("\n", style="")

    # Use muted colors for most text, only highlight SuperQode and SuperQE with gradient
    desc_text.append("Agentic Code needs ", style=THEME["muted"])
    desc_text.append("Super Quality Engineering (", style=THEME["muted"])
    # Single green color for "SuperQE" in brackets
    desc_text.append("SuperQE", style=f"bold {THEME['success']}")
    desc_text.append(")", style=THEME["muted"])
    desc_text.append(". ", style=THEME["muted"])
    desc_text.append("SuperQode", style=f"bold {THEME['purple']}")
    desc_text.append(" operationalizes ", style=THEME["muted"])
    desc_text.append("SuperQE", style=THEME["muted"])
    desc_text.append(" Agentic Quality Engineering - ", style=THEME["muted"])
    desc_text.append("a multi-agentic team of coding agents", style=THEME["muted"])
    desc_text.append(" that ", style=THEME["muted"])
    desc_text.append("break, validate, and harden code", style=THEME["muted"])
    desc_text.append(" before it reaches production.\n", style=THEME["muted"])
    items.append(Align.center(desc_text))

    # ═══════════════════════════════════════════════════════════════════════
    # KEYBOARD SHORTCUTS GUIDE
    # ═══════════════════════════════════════════════════════════════════════
    shortcuts_text = Text()
    shortcuts_text.append("💡 ", style=f"bold {THEME['cyan']}")
    shortcuts_text.append("Tab", style=f"bold {THEME['cyan']}")
    shortcuts_text.append(" to change section  •  ", style=THEME["muted"])
    shortcuts_text.append("→", style=f"bold {THEME['cyan']}")
    shortcuts_text.append(" for auto-complete\n", style=THEME["muted"])
    items.append(Align.center(shortcuts_text))

    # ═══════════════════════════════════════════════════════════════════════
    # GETTING STARTED COMMANDS - Compact separate display
    # ═══════════════════════════════════════════════════════════════════════
    commands_text = Text()

    # :connect command - compact
    commands_text.append("🔌 ", style="bold")
    commands_text.append(":connect", style=f"bold {THEME['purple']}")
    commands_text.append("  → Connect to ", style=THEME["muted"])
    commands_text.append("ACP", style=f"bold {THEME['cyan']}")
    commands_text.append(" or ", style=THEME["muted"])
    commands_text.append("BYOK", style=f"bold {THEME['pink']}")
    commands_text.append(" agents\n", style=THEME["muted"])

    # :init command - compact
    commands_text.append("🚀 ", style="bold")
    commands_text.append(":init", style=f"bold {THEME['success']}")
    commands_text.append("  → Prepare your Quality Engineering team\n", style=THEME["muted"])

    # :qe command - compact
    commands_text.append("👥 ", style="bold")
    commands_text.append(":qe", style=f"bold {THEME['orange']}")
    commands_text.append(" <role>  → Connect to role (e.g., ", style=THEME["muted"])
    commands_text.append(":qe security_tester", style=f"bold {THEME['orange']}")
    commands_text.append(")\n", style=THEME["muted"])

    # :help command - compact
    commands_text.append("❓ ", style="bold")
    commands_text.append(":help", style=f"bold {THEME['cyan']}")
    commands_text.append("  → Get help with commands and features\n", style=THEME["muted"])

    items.append(Align.center(commands_text))

    return Group(*items)


# ============================================================================
# SESSION HELPERS
# ============================================================================


def get_session():
    from superqode.main import session

    return session


def get_mode():
    from superqode.main import current_mode

    return current_mode


def set_mode(mode: str):
    import superqode.main as m

    m.current_mode = mode


# ============================================================================
# MAIN APP
# ============================================================================


class SuperQodeApp(App):
    CSS = APP_CSS
    TITLE = "SuperQode"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_screen", "Clear", show=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=True),
        Binding("ctrl+t", "toggle_thinking", "Toggle Logs", show=True),
        Binding("escape", "smart_cancel", "Cancel", show=True),
        Binding("ctrl+x", "cancel_agent", "Cancel Agent", show=False),
        Binding("ctrl+d", "toggle_thinking", "Hide Logs", show=False),
        # Number keys for model selection (1-9)
        Binding("1", "select_model_1", "Model 1", show=False),
        Binding("2", "select_model_2", "Model 2", show=False),
        Binding("3", "select_model_3", "Model 3", show=False),
        Binding("4", "select_model_4", "Model 4", show=False),
        Binding("5", "select_model_5", "Model 5", show=False),
        Binding("6", "select_model_6", "Model 6", show=False),
        Binding("7", "select_model_7", "Model 7", show=False),
        Binding("8", "select_model_8", "Model 8", show=False),
        Binding("9", "select_model_9", "Model 9", show=False),
        # Arrow keys for BYOK model navigation
        Binding("up", "navigate_model_up", "↑ Previous model", show=False),
        Binding("down", "navigate_model_down", "↓ Next model", show=False),
        Binding("enter", "select_highlighted_model", "Select highlighted", show=False),
        # Arrow keys for provider navigation
        Binding("up", "navigate_provider_up", "↑ Previous provider", show=False),
        Binding("down", "navigate_provider_down", "↓ Next provider", show=False),
        Binding("enter", "select_highlighted_provider", "Select highlighted provider", show=False),
        # Arrow keys for connection type navigation
        Binding("up", "navigate_connect_type_up", "↑ Previous type", show=False),
        Binding("down", "navigate_connect_type_down", "↓ Next type", show=False),
        Binding("enter", "select_highlighted_connect_type", "Select highlighted type", show=False),
        # Arrow keys for ACP agent navigation
        Binding("up", "navigate_acp_agent_up", "↑ Previous agent", show=False),
        Binding("down", "navigate_acp_agent_down", "↓ Next agent", show=False),
        Binding("enter", "select_highlighted_acp_agent", "Select highlighted agent", show=False),
        # Arrow keys for local provider navigation
        Binding("up", "navigate_local_provider_up", "↑ Previous local provider", show=False),
        Binding("down", "navigate_local_provider_down", "↓ Next local provider", show=False),
        Binding(
            "enter",
            "select_highlighted_local_provider",
            "Select highlighted local provider",
            show=False,
        ),
        # Arrow keys for local model navigation
        Binding("up", "navigate_local_model_up", "↑ Previous local model", show=False),
        Binding("down", "navigate_local_model_down", "↓ Next local model", show=False),
        Binding(
            "enter", "select_highlighted_local_model", "Select highlighted local model", show=False
        ),
        # SuperQode enhanced bindings
        Binding("ctrl+z", "undo_action", "Undo", show=False),
        Binding("ctrl+shift+z", "redo_action", "Redo", show=False),
        Binding("ctrl+\\", "toggle_split_view", "Split", show=False),
        Binding("ctrl+s", "create_checkpoint", "Checkpoint", show=False),
        # Sidebar resize bindings
        Binding("ctrl+[", "shrink_sidebar", "Shrink", show=False),
        Binding("ctrl+]", "expand_sidebar", "Expand", show=False),
        # Sidebar panel bindings (Ctrl+1 through Ctrl+6)
        Binding("ctrl+1", "sidebar_files", "Files", show=False),
        Binding("ctrl+2", "sidebar_agent", "Agent", show=False),
        Binding("ctrl+3", "sidebar_context", "Context", show=False),
        Binding("ctrl+4", "sidebar_terminal", "Terminal", show=False),
        Binding("ctrl+5", "sidebar_diff", "Diff", show=False),
        Binding("ctrl+6", "sidebar_history", "History", show=False),
        # Copy functionality
        Binding("ctrl+shift+c", "copy_response", "Copy", show=False),
        # External editor
        Binding("ctrl+e", "open_editor", "Editor", show=False),
        # Focus input (always return focus to prompt)
        Binding("ctrl+i", "focus_input", "Focus Input", show=False),
        # Leader key
        Binding("ctrl+x", "leader_key", "Leader", show=False),
    ]

    # State
    current_mode = reactive("home")
    current_role = reactive("")
    current_agent = reactive("")
    current_model = reactive("")
    current_provider = reactive("")
    is_busy = reactive(False)
    sidebar_visible = reactive(False)
    show_thinking_logs = reactive(True)  # Toggle for thinking logs visibility
    show_verbose_agent_logs = reactive(False)  # Show raw [agent] session logs (verbose mode)
    approval_mode = reactive(
        "ask"
    )  # "auto", "ask", "deny" - default to ask for safety - permission handling mode
    _agent_process = None  # Track running agent process for cancellation
    _cancel_requested = False  # Flag to signal cancellation
    _stream_animation_frame = 0  # Frame counter for streaming animation
    _awaiting_model_selection = False  # Track if we're waiting for model selection
    _opencode_highlighted_model_index = (
        0  # Track highlighted opencode model for keyboard navigation
    )
    _byok_highlighted_model_index = 0  # Track highlighted model for keyboard navigation
    _byok_highlighted_provider_index = 0  # Track highlighted provider for keyboard navigation
    _byok_highlighted_connect_type_index = (
        0  # Track highlighted connection type for keyboard navigation
    )
    _acp_highlighted_agent_index = 0  # Track highlighted ACP agent for keyboard navigation
    _local_highlighted_provider_index = (
        0  # Track highlighted local provider for keyboard navigation
    )
    _local_highlighted_model_index = 0  # Track highlighted local model for keyboard navigation
    _just_showed_byok_picker = (
        False  # Flag to prevent immediate provider selection after showing picker
    )
    _awaiting_permission = False  # Track if waiting for permission response
    _available_models: Dict[str, List[str]] = {}  # Available models per agent
    _last_response: str = ""  # Store last agent response for :copy command
    _opencode_session_id: str = ""  # Track opencode session for conversation continuity
    _claude_session_id: str = ""  # Track Claude ACP session for multi-turn
    _claude_process = None  # Keep Claude ACP process alive for multi-turn
    _is_first_message: bool = True  # Track if this is the first message in session
    _acp_client = None  # ACP client for agent communication

    def __init__(self):
        super().__init__()
        # Lazy load agents to improve startup time
        self._agents: Optional[List[AgentInfo]] = None
        # Lazy load model lists for faster startup
        self._opencode_models: Optional[List[Dict]] = None
        self._gemini_models: Optional[List[Dict]] = None
        self._claude_models: Optional[List[Dict]] = None
        self._codex_models: Optional[List[Dict]] = None
        self._openhands_models: Optional[List[Dict]] = None

        self._thinking_timer: Optional[Timer] = None
        self._thinking_start = 0.0
        self._thinking_idx = 0
        self._stream_animation_timer: Optional[Timer] = None
        self._permission_pulse_timer: Optional[Timer] = None  # Timer for permission pulse animation
        self._permission_pending = False  # Track if permission is pending
        self._history_manager = HistoryManager()

        # PERFORMANCE: Animation manager for throttled animations
        self._animation_manager = None

        # PERFORMANCE: Prewarm LiteLLM in background for faster first LLM call
        self._prewarm_litellm()

    @property
    def agents(self) -> List[AgentInfo]:
        """Lazy load agents list."""
        if self._agents is None:
            self._agents = self._load_agents()
        return self._agents

    @property
    def opencode_models(self) -> List[Dict]:
        """Lazy load OpenCode models."""
        if self._opencode_models is None:
            self._opencode_models = self._get_opencode_models()
        return self._opencode_models

    def _load_agents(self) -> List[AgentInfo]:
        """Load agents list (called lazily)."""
        try:
            from superqode.agents.discovery import read_agents

            agents_data = asyncio.run(read_agents())
            return [
                AgentInfo(
                    identity=short_name,
                    name=agent.get("name", short_name),
                    short_name=short_name,
                    description=agent.get("description", ""),
                    author=agent.get("author", "SuperQode"),
                    status=AgentStatus.AVAILABLE,
                )
                for short_name, agent in agents_data.items()
            ]
        except Exception as e:
            # Fallback to basic agents if discovery fails
            return [
                AgentInfo(
                    identity="opencode",
                    name="OpenCode",
                    short_name="opencode",
                    description="AI coding assistant",
                    author="OpenCode",
                    status=AgentStatus.AVAILABLE,
                ),
                AgentInfo(
                    identity="gemini",
                    name="Gemini",
                    short_name="gemini",
                    description="Google AI assistant",
                    author="Google",
                    status=AgentStatus.AVAILABLE,
                ),
                AgentInfo(
                    identity="claude",
                    name="Claude",
                    short_name="claude",
                    description="Anthropic AI assistant",
                    author="Anthropic",
                    status=AgentStatus.AVAILABLE,
                ),
            ]

    def _get_opencode_models(self) -> List[Dict]:
        """Get OpenCode models list."""
        return [
            {"id": "glm-4.7-free", "name": "GLM-4.7 (Free)", "context": 8192},
            {"id": "grok-code", "name": "Grok Code", "context": 4096},
            {"id": "kimi-k2.5-free", "name": "Kimi K2.5 (Free)", "context": 8192},
            {"id": "gpt-5-nano", "name": "GPT-5 Nano", "context": 4096},
            {"id": "minimax-m2.1-free", "name": "MiniMax M2.1 (Free)", "context": 4096},
            {"id": "big-pickle", "name": "Big Pickle", "context": 2048},
        ]

    @property
    def gemini_models(self) -> List[Dict]:
        """Lazy load Gemini models."""
        if self._gemini_models is None:
            self._gemini_models = self._get_gemini_models()
        return self._gemini_models

    def _get_gemini_models(self) -> List[Dict]:
        """Get Gemini models list - synced with providers/models.py."""
        return [
            {
                "id": "gemini-3-pro-preview",
                "name": "Gemini 3 Pro Preview",
                "context": 2000000,
                "desc": "Latest Gemini 3 flagship - 2M context",
                "recommended": True,
            },
            {
                "id": "gemini-3-flash-preview",
                "name": "Gemini 3 Flash Preview",
                "context": 1000000,
                "desc": "Fast Gemini 3 - 1M context",
                "recommended": True,
            },
            {
                "id": "gemini-2.5-pro",
                "name": "Gemini 2.5 Pro",
                "context": 2000000,
                "desc": "Previous Pro with 2M context",
            },
            {
                "id": "gemini-2.5-flash",
                "name": "Gemini 2.5 Flash",
                "context": 1000000,
                "desc": "Previous Flash model",
            },
        ]

    @property
    def claude_models(self) -> List[Dict]:
        """Lazy load Claude models."""
        if self._claude_models is None:
            self._claude_models = self._get_claude_models()
        return self._claude_models

    def _get_claude_models(self) -> List[Dict]:
        """Get Claude models list - synced with providers/models.py."""
        return [
            {
                "id": "claude-opus-4-5-20251101",
                "name": "Claude Opus 4.5",
                "context": 200000,
                "desc": "Most capable Claude - latest flagship",
                "recommended": True,
            },
            {
                "id": "claude-sonnet-4-5-20250929",
                "name": "Claude Sonnet 4.5",
                "context": 200000,
                "desc": "Best balance of speed & intelligence",
                "recommended": True,
            },
            {
                "id": "claude-haiku-4-5-20251001",
                "name": "Claude Haiku 4.5",
                "context": 200000,
                "desc": "Fastest and most cost-effective",
            },
            {
                "id": "claude-sonnet-4-20250514",
                "name": "Claude Sonnet 4",
                "context": 200000,
                "desc": "Previous Sonnet generation",
            },
        ]

    @property
    def codex_models(self) -> List[Dict]:
        """Lazy load Codex models."""
        if self._codex_models is None:
            self._codex_models = self._get_codex_models()
        return self._codex_models

    def _get_codex_models(self) -> List[Dict]:
        """Get Codex/OpenAI models list - updated from models.dev."""
        return [
            {"id": "gpt-5.2", "name": "GPT-5.2 (Latest)", "context": 256000},
            {"id": "gpt-5.2-pro", "name": "GPT-5.2 Pro", "context": 256000},
            {"id": "gpt-5.2-chat-latest", "name": "GPT-5.2 Chat", "context": 256000},
            {"id": "gpt-5.2-codex", "name": "GPT-5.2 Codex", "context": 256000},
            {"id": "gpt-5.1", "name": "GPT-5.1", "context": 200000},
            {"id": "gpt-5.1-codex", "name": "GPT-5.1 Codex", "context": 200000},
            {"id": "gpt-5.1-codex-mini", "name": "GPT-5.1 Codex Mini", "context": 200000},
            {"id": "gpt-4o-2024-11-20", "name": "GPT-4o (Nov 2024)", "context": 128000},
            {"id": "gpt-4o", "name": "GPT-4o", "context": 128000},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "context": 128000},
            {"id": "o1", "name": "o1 (Reasoning)", "context": 200000},
            {"id": "o1-mini", "name": "o1-mini", "context": 128000},
        ]

    @property
    def openhands_models(self) -> List[Dict]:
        """Lazy load OpenHands models."""
        if self._openhands_models is None:
            self._openhands_models = self._get_openhands_models()
        return self._openhands_models

    def _get_openhands_models(self) -> List[Dict]:
        """Get OpenHands models list - updated from models.dev."""
        return [
            {"id": "gpt-5.2", "name": "GPT-5.2 (Latest)", "context": 256000},
            {"id": "gpt-5.2-pro", "name": "GPT-5.2 Pro", "context": 256000},
            {
                "id": "claude-opus-4-5-20251101",
                "name": "Claude Opus 4.5 (Latest)",
                "context": 200000,
            },
            {
                "id": "gemini-3-pro-preview",
                "name": "Gemini 3 Pro Preview (Latest)",
                "context": 2000000,
            },
            {
                "id": "gemini-3-flash-preview",
                "name": "Gemini 3 Flash Preview (Latest)",
                "context": 1000000,
            },
            {"id": "gpt-4o", "name": "GPT-4o", "context": 128000},
            {"id": "claude-sonnet-4-5-20250929", "name": "Claude Sonnet 4.5", "context": 200000},
        ]
        self._permission_pending = False  # Track if permission is pending
        self._permission_response: Optional[str] = None  # Store permission response
        self._permission_pulse_timer: Optional[Timer] = None  # Timer for permission pulse animation
        self._permission_pulse_frame = 0  # Frame counter for pulse animation
        self._pending_tool_id: Optional[str] = None  # Track which tool is pending permission
        self._pending_tool_name: Optional[str] = None  # Track pending tool name for approval
        self._pending_tool_input: Optional[dict] = None  # Track pending tool input for approval
        self._approved_tools: set = set()  # Track already approved tool IDs to prevent duplicates
        self._tool_id_map: Dict[str, dict] = {}  # Map tool_id to tool info for detailed logging

        # New feature managers
        self._approval_manager: Optional[ApprovalManager] = None
        self._plan_manager = PlanManager()
        self._tool_manager = ToolCallManager()
        self._file_manager = AtomicFileManager()
        self._history_manager = HistoryManager()
        self._diff_viewer: Optional[DiffViewer] = None
        self._file_viewer: Optional[FileViewer] = None

        # ACP client for agent communication
        self._acp_client = None
        self._acp_message_buffer = ""  # Buffer for streaming messages

        # Available models for agents - specific to each coding agent
        # OpenCode free models from `opencode models` command
        self._opencode_models = [
            {
                "id": "opencode/glm-4.7-free",
                "name": "GLM 4.7",
                "free": True,
                "recommended": True,
                "desc": "Zhipu AI - Great for coding",
            },
            {
                "id": "opencode/grok-code",
                "name": "Grok Code",
                "free": True,
                "recommended": True,
                "desc": "xAI - Fast coding model",
            },
            {
                "id": "opencode/kimi-k2.5-free",
                "name": "Kimi K2.5",
                "free": True,
                "recommended": True,
                "desc": "Moonshot AI - K2.5 free tier",
            },
            {
                "id": "opencode/minimax-m2.1-free",
                "name": "MiniMax M2.1",
                "free": True,
                "recommended": True,
                "desc": "MiniMax - Powerful free model",
            },
            {
                "id": "opencode/gpt-5-nano",
                "name": "GPT-5 Nano",
                "free": True,
                "desc": "OpenAI - Lightweight model",
            },
            {
                "id": "opencode/big-pickle",
                "name": "Big Pickle",
                "free": True,
                "desc": "OpenCode - Experimental",
            },
        ]

        # Gemini models - https://ai.google.dev/gemini-api/docs/models (updated from models.dev)
        self._gemini_models = [
            {
                "id": "gemini/gemini-3-pro-preview",
                "name": "Gemini 3 Pro Preview (Latest)",
                "free": False,
                "recommended": True,
                "desc": "Latest Gemini flagship - 2M context",
            },
            {
                "id": "gemini/gemini-3-flash-preview",
                "name": "Gemini 3 Flash Preview (Latest)",
                "free": False,
                "recommended": True,
                "desc": "Fast Gemini 3 model - 1M context",
            },
            {
                "id": "gemini/gemini-2.5-pro",
                "name": "Gemini 2.5 Pro",
                "free": False,
                "desc": "2M context window",
            },
            {
                "id": "gemini/gemini-2.5-flash",
                "name": "Gemini 2.5 Flash",
                "free": False,
                "desc": "Fast & versatile",
            },
            {
                "id": "gemini/gemini-flash-latest",
                "name": "Gemini Flash Latest",
                "free": False,
                "desc": "Latest Flash variant",
            },
        ]

        # Claude Code models - https://docs.anthropic.com/en/docs/about-claude/models (updated from models.dev)
        # Uses claude-code-acp adapter from Zed Industries
        self._claude_models = [
            {
                "id": "claude/claude-opus-4-5-20251101",
                "name": "Claude Opus 4.5",
                "free": False,
                "recommended": True,
                "desc": "Most capable Claude model",
            },
            {
                "id": "claude/claude-sonnet-4-5-20250929",
                "name": "Claude Sonnet 4.5",
                "free": False,
                "recommended": True,
                "desc": "Best balance of speed & intelligence",
            },
            {
                "id": "claude/claude-haiku-4-5-20251001",
                "name": "Claude Haiku 4.5",
                "free": False,
                "desc": "Fast & efficient",
            },
            {
                "id": "claude/claude-sonnet-4-20250514",
                "name": "Claude Sonnet 4",
                "free": False,
                "desc": "Previous Sonnet",
            },
            {
                "id": "claude/claude-opus-4-20250514",
                "name": "Claude Opus 4",
                "free": False,
                "desc": "Previous Opus",
            },
        ]

        # Codex CLI / OpenAI models - https://platform.openai.com/docs/models (updated from models.dev)
        # Uses codex-acp adapter from Zed Industries
        self._codex_models = [
            {
                "id": "codex/gpt-5.2",
                "name": "GPT-5.2 (Latest)",
                "free": False,
                "recommended": True,
                "desc": "Latest GPT flagship with reasoning",
            },
            {
                "id": "codex/gpt-5.2-pro",
                "name": "GPT-5.2 Pro",
                "free": False,
                "recommended": True,
                "desc": "GPT-5.2 Pro variant",
            },
            {
                "id": "codex/gpt-5.2-chat-latest",
                "name": "GPT-5.2 Chat",
                "free": False,
                "recommended": True,
                "desc": "GPT-5.2 Chat variant",
            },
            {
                "id": "codex/gpt-5.2-codex",
                "name": "GPT-5.2 Codex",
                "free": False,
                "recommended": True,
                "desc": "GPT-5.2 Codex variant",
            },
            {
                "id": "codex/gpt-5.1",
                "name": "GPT-5.1",
                "free": False,
                "recommended": True,
                "desc": "GPT-5 series model",
            },
            {
                "id": "codex/gpt-5.1-codex",
                "name": "GPT-5.1 Codex",
                "free": False,
                "desc": "GPT-5.1 Codex variant",
            },
            {
                "id": "codex/gpt-5.1-codex-mini",
                "name": "GPT-5.1 Codex Mini",
                "free": False,
                "desc": "GPT-5.1 Codex Mini variant",
            },
            {"id": "codex/gpt-4o", "name": "GPT-4o", "free": False, "desc": "GPT-4 Omni model"},
            {
                "id": "codex/gpt-4o-mini",
                "name": "GPT-4o Mini",
                "free": False,
                "desc": "Efficient GPT-4o model",
            },
            {"id": "codex/o1", "name": "o1", "free": False, "desc": "Advanced reasoning model"},
            {
                "id": "codex/o1-mini",
                "name": "o1-mini",
                "free": False,
                "desc": "Fast reasoning model",
            },
        ]

        # OpenHands models - model-agnostic, uses configured LLM
        # https://openhands.dev/
        self._openhands_models = [
            {
                "id": "openhands/default",
                "name": "Default",
                "free": False,
                "recommended": True,
                "desc": "Use configured model",
            },
            {
                "id": "openhands/ollama",
                "name": "Ollama (Local)",
                "free": True,
                "desc": "Local Ollama models",
            },
            {
                "id": "openhands/claude",
                "name": "Claude",
                "free": False,
                "desc": "Anthropic Claude models",
            },
            {
                "id": "openhands/gpt-4",
                "name": "GPT-4",
                "free": False,
                "desc": "OpenAI GPT-4 models",
            },
            {
                "id": "openhands/gemini",
                "name": "Gemini",
                "free": False,
                "desc": "Google Gemini models",
            },
        ]

    def compose(self) -> ComposeResult:
        # Import resizable divider
        from superqode.widgets.resizable_sidebar import ResizableDivider

        with Horizontal(id="main-grid"):
            # Collapsible Sidebar with Plan, Files, Preview panels
            yield CollapsibleSidebar(Path.cwd(), id="sidebar")

            # Resizable divider for sidebar
            yield ResizableDivider(id="sidebar-divider")

            # Main content - Warp style layout
            with Container(id="content"):
                # Colorful status bar - ALWAYS visible at top
                yield ColorfulStatusBar(id="status-bar")

                # Prompt area at TOP (below SuperQode logo) - hidden when agent is thinking
                with Container(id="prompt-area"):
                    yield ModeBadge(id="mode-badge")
                    with Horizontal(id="input-box"):
                        yield Static("🖋️ ", id="prompt-symbol")
                        yield SelectionAwareInput(
                            placeholder="Type here...",
                            id="prompt-input",
                            suggester=CommandSuggester(),
                            # No restrict parameter - allow all characters including colon
                        )
                    yield HintsBar(id="hints")

                # Scanning line animation at TOP (shown when agent is thinking)
                yield TopScanningLine(id="thinking-wave")

                # Conversation/Response area - main content (expandable)
                with Container(id="conversation"):
                    # Initialize with wrap=True and no width constraints
                    yield ConversationLog(
                        id="log",
                        highlight=True,
                        markup=True,
                        wrap=True,
                        min_width=1,
                        max_width=None,
                    )

                # Thinking indicator with changing text at bottom (shown when agent is thinking)
                yield StreamingThinkingIndicator(id="streaming-thinking")

                # Scanning line animation at BOTTOM (shown when agent is thinking)
                yield BottomScanningLine(id="thinking-wave-bottom")

    def on_mount(self):
        # Focus input after a short delay to ensure widgets are fully ready
        self.set_timer(0.1, self._focus_input_on_ready)
        self._load_welcome()
        # Sync approval mode to hints bar
        self._sync_approval_mode()
        # PERFORMANCE: Initialize animation manager for throttled animations
        self._init_animation_manager()
        # Initialize undo manager for checkpoint/restore
        self._init_undo_manager()
        # ACP agent discovery disabled on startup - user can run :acp discover manually if needed
        # self._discover_acp_agents()
        # Initialize sidebar width tracking
        self._init_sidebar_resize()
        # Run provider health check in background
        self._run_startup_health_check()

    def _focus_input_on_ready(self):
        """Focus the input box once widgets are ready."""
        try:
            input_widget = self.query_one("#prompt-input", Input)
            # Ensure input is ready to receive all characters
            input_widget.can_focus = True
            input_widget.focus()
            # Force a refresh to ensure it's ready
            input_widget.refresh()
        except Exception:
            # Retry if not ready
            self.set_timer(0.1, self._focus_input_on_ready)

    def _ensure_input_focus(self):
        """Ensure the input box has focus - called after operations."""
        try:
            input_widget = self.query_one("#prompt-input", Input)
            if not input_widget.has_focus:
                input_widget.focus()
                # Force focus to be active immediately
                input_widget.can_focus = True
        except Exception:
            # Widget might not be ready, retry
            try:
                self.set_timer(0.1, self._ensure_input_focus)
            except Exception:
                pass

    def _init_sidebar_resize(self):
        """Initialize sidebar resize handling."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            sidebar._width = 80  # Initial width
        except Exception:
            pass

    def _run_startup_health_check(self):
        """Run provider health check in background on startup."""
        self.run_worker(self._startup_health_check())

    async def _startup_health_check(self):
        """Check provider health on startup."""
        from superqode.providers.health import get_health_checker

        try:
            checker = get_health_checker()
            # Run health check (results cached for 5 minutes)
            results = await checker.check_all()

            # Count ready providers
            ready_count = len(checker.get_ready_providers())

            if ready_count > 0:
                # Update status in footer or log quietly
                # Don't spam the user on startup
                pass
        except Exception:
            # Silent failure - health check is optional
            pass

        # Also load models.dev data in background
        await self._load_models_dev_data()

    async def _load_models_dev_data(self):
        """Load model data from models.dev in background."""
        try:
            from superqode.providers.models_dev import get_models_dev
            from superqode.providers.models import set_live_models

            client = get_models_dev()
            success = await client.ensure_loaded()

            if success:
                # Get all models and update the global models database
                live_models = {}
                for provider_id in client.get_providers().keys():
                    provider_models = client.get_models_for_provider(provider_id)
                    if provider_models:
                        live_models[provider_id] = provider_models

                if live_models:
                    set_live_models(live_models)

        except Exception:
            # Silent failure - live data is optional
            pass

    def on_resizable_divider_resized(self, event) -> None:
        """Handle sidebar resize via divider drag."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            current_width = getattr(sidebar, "_width", 80)
            new_width = current_width + event.delta_x
            new_width = max(30, min(150, new_width))
            sidebar.styles.width = new_width
            sidebar._width = new_width
        except Exception:
            pass

    def _update_sidebar_agent_panel(self, **kwargs):
        """Update the agent panel in sidebar with current agent info."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            agent_panel = sidebar.get_agent_panel()
            if agent_panel:
                agent_panel.update_agent(**kwargs)
        except Exception:
            pass

    def _update_sidebar_context_panel(self, path: str, token_count: int = 0):
        """Add a file to the context panel."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            context_panel = sidebar.get_context_panel()
            if context_panel:
                context_panel.add_file(path, token_count)
        except Exception:
            pass

    def _update_sidebar_history_panel(self, role: str, content: str, agent_name: str = ""):
        """Add a message to the history panel."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            history_panel = sidebar.get_history_panel()
            if history_panel:
                history_panel.add_message(role, content, agent_name)
        except Exception:
            pass

    def _update_sidebar_diff_panel(
        self,
        path: str,
        status: str = "modified",
        additions: int = 0,
        deletions: int = 0,
        diff_text: str = "",
    ):
        """Add a file to the diff panel."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            diff_panel = sidebar.get_diff_panel()
            if diff_panel:
                diff_panel.add_file(path, status, additions, deletions, diff_text)
        except Exception:
            pass

    def _run_sidebar_terminal_command(self, cmd: str, output: str = "", success: bool = True):
        """Run a command in the sidebar terminal panel."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            terminal_panel = sidebar.get_terminal_panel()
            if terminal_panel:
                terminal_panel.add_command(cmd, output, success)
        except Exception:
            pass

    def _init_undo_manager(self):
        """Initialize the undo manager for checkpoint/restore."""
        try:
            self._undo_manager = UndoManager()
            self._undo_manager.initialize()
        except Exception:
            self._undo_manager = None

    @work(exclusive=False)
    async def _discover_acp_agents(self):
        """Discover available ACP agents in background - truly async and non-blocking."""
        try:
            from superqode.acp_discovery import ACPDiscovery

            discovery = ACPDiscovery()
            # This is now truly async - won't block the main thread
            agents = await discovery.discover_all()

            # Store discovered agents
            self._discovered_acp_agents = {a.short_name: a for a in agents}

            # Log available agents (use set_timer to schedule on main thread)
            available = [a for a in agents if a.status.name == "AVAILABLE"]
            if available:
                # Schedule display on main thread without blocking
                self.set_timer(0.1, lambda: self._show_discovered_agents(available))
        except Exception:
            self._discovered_acp_agents = {}

    def _show_discovered_agents(self, agents):
        """Show discovered agents in log."""
        log = self.query_one("#log", ConversationLog)
        text = Text()
        text.append("\n  ◈ ", style=f"bold {SQ_COLORS.primary}")
        text.append(f"Discovered {len(agents)} ACP agents: ", style=SQ_COLORS.text_muted)
        names = [f"{a.icon} {a.short_name}" for a in agents[:4]]
        text.append(", ".join(names), style=SQ_COLORS.text_secondary)
        if len(agents) > 4:
            text.append(f" +{len(agents) - 4} more", style=SQ_COLORS.text_dim)
        text.append("\n", style="")
        log.write(text)

    def _prewarm_litellm(self):
        """Prewarm LiteLLM in background for faster first LLM call."""
        try:
            from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

            LiteLLMGateway.prewarm()
        except ImportError:
            pass  # LiteLLM not available

    def _init_animation_manager(self):
        """Initialize the animation manager for throttled animations."""
        try:
            from superqode.widgets.animation_manager import AnimationManager, AnimationConfig

            config = AnimationConfig(
                max_fps=10,  # Limit to 10 FPS for performance
                pause_on_blur=True,
                batch_updates=True,
            )
            self._animation_manager = AnimationManager(self, config)
            self._animation_manager.start()
        except ImportError:
            pass  # Animation manager not available

    @property
    def animation_manager(self):
        """Get the animation manager instance."""
        return self._animation_manager

    def _sync_approval_mode(self):
        """Sync approval mode to the hints bar and mode badge."""
        try:
            hints = self.query_one("#hints", HintsBar)
            hints.approval_mode = self.approval_mode
        except Exception:
            pass
        try:
            badge = self.query_one("#mode-badge", ModeBadge)
            badge.approval_mode = self.approval_mode
        except Exception:
            pass

    @work(thread=True)
    def _load_welcome(self):
        # Agents are now lazy loaded - no need to preload
        try:
            from superqode.tui import load_team_config

            team_name = load_team_config().team_name
        except Exception:
            team_name = "Development Team"
        self.call_from_thread(self._show_welcome, team_name)

    def _show_welcome(self, team_name: str):
        log = self.query_one("#log", ConversationLog)
        # Temporarily disable auto-scroll so we can scroll to top
        log.auto_scroll = False
        log.write(render_welcome(self.agents, team_name))
        # Scroll to top so user sees the attractive header first
        log.scroll_home(animate=False)
        # Re-enable auto-scroll for future messages
        self.set_timer(0.2, lambda: setattr(log, "auto_scroll", True))

    # ========================================================================
    # Sidebar Toggle & File Selection
    # ========================================================================

    def _navigate_to_sidebar_changes(self, files_modified: list):
        """Navigate sidebar to Changes tab and highlight modified files."""
        try:
            # Find the sidebar
            sidebar = self.query_one("CollapsibleSidebar", raise_on_error=False)
            if not sidebar:
                return

            # Find the tabs widget
            tabs = sidebar.query_one("SidebarTabs", raise_on_error=False)
            if tabs:
                # Switch to changes tab
                tabs.active_tab = "changes"
                tabs.post_message(tabs.TabChanged("changes"))

            # Find the GitChangesPanel and refresh it
            changes_panel = sidebar.query_one("GitChangesPanel", raise_on_error=False)
            if changes_panel:
                # Refresh to get latest changes from git (this will update UI after refresh completes)
                changes_panel.refresh_changes()

                # After refresh completes, highlight the files
                # Use a small delay to ensure git changes are loaded
                def highlight_after_refresh():
                    try:
                        if files_modified:
                            changes_panel.highlight_files(files_modified)
                    except Exception:
                        pass

                # Wait a bit for refresh to complete, then highlight
                self.set_timer(0.3, highlight_after_refresh)
        except Exception:
            # Silently fail - sidebar might not be available
            pass

    def action_toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        divider = self.query_one("#sidebar-divider")
        if self.sidebar_visible:
            sidebar.add_class("visible")
            divider.remove_class("-hidden")
            sidebar.focus_tree()
        else:
            sidebar.remove_class("visible")
            divider.add_class("-hidden")
            # Return focus to input when sidebar is closed
            self.set_timer(0.1, self._ensure_input_focus)

    def action_shrink_sidebar(self):
        """Shrink sidebar width."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        current_width = getattr(sidebar, "_width", 80)
        new_width = max(30, current_width - 10)
        sidebar.styles.width = new_width
        sidebar._width = new_width

    def action_expand_sidebar(self):
        """Expand sidebar width."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        current_width = getattr(sidebar, "_width", 80)
        new_width = min(150, current_width + 10)
        sidebar.styles.width = new_width
        sidebar._width = new_width

    def action_sidebar_files(self):
        """Switch sidebar to files view."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "files"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    def action_sidebar_agent(self):
        """Switch sidebar to agent panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "agent"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    def action_sidebar_context(self):
        """Switch sidebar to context panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "context"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    def action_sidebar_terminal(self):
        """Switch sidebar to terminal panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "terminal"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    def action_sidebar_diff(self):
        """Switch sidebar to diff panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "diff"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    def action_sidebar_history(self):
        """Switch sidebar to history panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "history"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    def action_copy_response(self):
        """Copy last agent response to clipboard (Ctrl+Shift+C)."""
        log = self.query_one("#log", ConversationLog)
        self._handle_copy(log)

    def action_open_editor(self):
        """Open external editor for composing message (Ctrl+E)."""
        log = self.query_one("#log", ConversationLog)
        self._handle_edit(log)

    def action_leader_key(self):
        """Activate leader key mode (Ctrl+X) - show popup with shortcuts."""
        from superqode.widgets.leader_key import LeaderKeyPopup

        # Create and show the popup widget if it doesn't exist
        # The popup will handle key presses internally, not the App
        if not hasattr(self, "_leader_popup") or self._leader_popup is None:
            self._leader_popup = LeaderKeyPopup(id="leader-popup")
            # Mount it to the screen so it can receive focus
            try:
                self.mount(self._leader_popup)
            except Exception:
                # Already mounted or mount failed, try to get existing one
                try:
                    self._leader_popup = self.query_one("#leader-popup", LeaderKeyPopup)
                except Exception:
                    pass

        if self._leader_popup:
            self._leader_popup.show()
            self._leader_mode = True

    @on(events.TextSelected)
    async def on_text_selected(self) -> None:
        """Automatically copy selected text to clipboard when user selects with mouse.

        Any visible selection on the screen is copied to the
        system clipboard and a small notification is shown. This preserves normal
        Ctrl+C / Ctrl+Z behavior since we rely on Textual's TextSelected event rather
        than intercepting keyboard shortcuts.
        """
        try:
            selection = self.screen.get_selected_text()
        except Exception:
            selection = None

        if selection:
            try:
                self.copy_to_clipboard(selection)
                self.notify(
                    "Copied selection to clipboard",
                    title="Automatic copy",
                    severity="information",
                )
            except Exception:
                # Best-effort: if clipboard or notifications fail, do nothing
                pass

    @on(LeaderKeyPopup.KeyPressed)
    def on_leader_key_popup_key_pressed(self, event: LeaderKeyPopup.KeyPressed) -> None:
        """Handle leader key selection from popup."""
        self._leader_mode = False
        action = event.action
        log = self.query_one("#log", ConversationLog)

        # Execute the action
        if action == "show_help":
            self._show_help(log)
        elif action == "open_editor":
            self._handle_edit(log)
        elif action == "copy_response":
            self._handle_copy(log)
        elif action == "show_select":
            self._handle_select(log)
        elif action == "show_theme":
            self._handle_theme("", log)
        elif action == "show_diagnostics":
            self._handle_diagnostics(".", log)
        elif action == "toggle_sidebar":
            self.action_toggle_sidebar()
        elif action == "quit_app":
            self.action_quit()

        # Return focus to input
        self.set_timer(0.1, self._ensure_input_focus)

    @on(LeaderKeyPopup.Cancelled)
    def on_leader_key_popup_cancelled(self, event: LeaderKeyPopup.Cancelled) -> None:
        """Handle leader mode cancellation."""
        self._leader_mode = False
        # Return focus to input
        self.set_timer(0.1, self._ensure_input_focus)

    def on_key(self, event: events.Key) -> None:
        """Handle key events globally - intercept arrow keys during selection modes."""
        # During selection modes, intercept arrow keys and Enter before Input widget gets them
        if event.key in ("up", "down", "enter"):
            handled = False

            # Check if we're in any selection mode
            if getattr(self, "_awaiting_acp_agent_selection", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_acp_agent_up()
                elif event.key == "down":
                    self.action_navigate_acp_agent_down()
                elif event.key == "enter":
                    self.action_select_highlighted_acp_agent()

            elif getattr(self, "_awaiting_byok_model", False):
                # Keyboard navigation disabled for BYOK model selection
                # Users must enter a number to select a model
                pass

            elif getattr(self, "_awaiting_byok_provider", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_provider_up()
                elif event.key == "down":
                    self.action_navigate_provider_down()
                elif event.key == "enter":
                    self.action_select_highlighted_provider()

            elif getattr(self, "_awaiting_connect_type", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_connect_type_up()
                elif event.key == "down":
                    self.action_navigate_connect_type_down()
                elif event.key == "enter":
                    self.action_select_highlighted_connect_type()

            elif getattr(self, "_awaiting_local_provider", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_local_provider_up()
                elif event.key == "down":
                    self.action_navigate_local_provider_down()
                elif event.key == "enter":
                    self.action_select_highlighted_local_provider()

            elif getattr(self, "_awaiting_local_model", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_local_model_up()
                elif event.key == "down":
                    self.action_navigate_local_model_down()
                elif event.key == "enter":
                    self.action_select_highlighted_local_model()

            elif getattr(self, "_awaiting_model_selection", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_opencode_model_up()
                elif event.key == "down":
                    self.action_navigate_opencode_model_down()
                elif event.key == "enter":
                    self.action_select_highlighted_opencode_model()

            if handled:
                # Ensure input stays focused after navigation
                self.set_timer(0.05, self._ensure_input_focus)
                return

    # Leader keys are now handled entirely through the popup widget system
    # This ensures zero latency when typing in the input field

    def action_toggle_thinking(self):
        """Toggle visibility of thinking/log output."""
        self.show_thinking_logs = not self.show_thinking_logs
        log = self.query_one("#log", ConversationLog)

        # Also toggle on the current TUI logger if one exists
        if hasattr(self, "_current_tui_logger") and self._current_tui_logger:
            self._current_tui_logger.logger.config.show_thinking = self.show_thinking_logs

        if self.show_thinking_logs:
            log.add_info("💭 Thinking logs: ON - you'll see agent's work")
        else:
            log.add_info("💭 Thinking logs: OFF - only final response shown")

    def action_undo_action(self):
        """Undo the last agent operation."""
        if not hasattr(self, "_undo_manager") or not self._undo_manager:
            return

        log = self.query_one("#log", ConversationLog)
        result = self._undo_manager.undo()
        if result:
            text = Text()
            text.append("  ✦ ", style=f"bold {SQ_COLORS.success}")
            text.append("Undone: ", style=SQ_COLORS.text_secondary)
            text.append(result.name, style=f"bold {SQ_COLORS.text_primary}")
            if result.files_changed:
                text.append(f" ({len(result.files_changed)} files)", style=SQ_COLORS.text_dim)
            text.append("\n", style="")
            log.write(text)
        else:
            log.add_info("◇ Nothing to undo")

    def action_redo_action(self):
        """Redo the previously undone operation."""
        if not hasattr(self, "_undo_manager") or not self._undo_manager:
            return

        log = self.query_one("#log", ConversationLog)
        result = self._undo_manager.redo()
        if result:
            text = Text()
            text.append("  ✦ ", style=f"bold {SQ_COLORS.success}")
            text.append("Redone: ", style=SQ_COLORS.text_secondary)
            text.append(result.name, style=f"bold {SQ_COLORS.text_primary}")
            text.append("\n", style="")
            log.write(text)
        else:
            log.add_info("◇ Nothing to redo")

    def action_create_checkpoint(self):
        """Create a manual checkpoint."""
        if not hasattr(self, "_undo_manager") or not self._undo_manager:
            return

        log = self.query_one("#log", ConversationLog)
        checkpoint_id = self._undo_manager.create_checkpoint("Manual checkpoint")
        if checkpoint_id:
            text = Text()
            text.append("  ◆ ", style=f"bold {SQ_COLORS.primary}")
            text.append("Checkpoint created: ", style=SQ_COLORS.text_secondary)
            text.append(checkpoint_id, style=f"bold {SQ_COLORS.text_primary}")
            text.append("\n", style="")
            log.write(text)
        else:
            log.add_info("◇ No changes to checkpoint")

    def action_toggle_split_view(self):
        """Toggle the split view for code + chat."""
        log = self.query_one("#log", ConversationLog)

        # Check if split view is available
        if not hasattr(self, "_split_view_enabled"):
            self._split_view_enabled = False

        self._split_view_enabled = not self._split_view_enabled

        if self._split_view_enabled:
            text = Text()
            text.append("  ◇ ", style=f"bold {SQ_COLORS.primary}")
            text.append("Split view: ", style=SQ_COLORS.text_secondary)
            text.append("ON", style=f"bold {SQ_COLORS.success}")
            text.append(" (use :open <file> to view files)", style=SQ_COLORS.text_dim)
            text.append("\n", style="")
            log.write(text)
        else:
            text = Text()
            text.append("  ◇ ", style=f"bold {SQ_COLORS.primary}")
            text.append("Split view: ", style=SQ_COLORS.text_secondary)
            text.append("OFF", style=SQ_COLORS.text_dim)
            text.append("\n", style="")
            log.write(text)

    def _create_checkpoint_before_agent(self, operation_name: str = "Agent operation"):
        """Create a checkpoint before an agent operation."""
        if hasattr(self, "_undo_manager") and self._undo_manager:
            self._undo_manager.create_checkpoint(f"Before: {operation_name}")

    def action_cancel_agent(self):
        """Cancel the currently running agent operation."""
        if self._agent_process is not None:
            self._cancel_requested = True
            try:
                self._agent_process.terminate()
            except Exception:
                pass
            log = self.query_one("#log", ConversationLog)
            log.add_info("🛑 Cancelling agent operation...")
            self._stop_stream_animation()
            self._stop_thinking()
        elif self.is_busy:
            self._cancel_requested = True
            log = self.query_one("#log", ConversationLog)
            log.add_info("🛑 Cancel requested...")

    def action_smart_cancel(self):
        """Cancel agent if running, cancel selection mode, or do nothing (don't exit)."""
        # First check if we're in any selection mode
        if getattr(self, "_awaiting_local_model", False):
            self._awaiting_local_model = False
            log = self.query_one("#log", ConversationLog)
            # Return to local provider list for a clear "cancel" behavior
            self._show_local_provider_picker(log)
            return
        if getattr(self, "_awaiting_local_provider", False):
            self._awaiting_local_provider = False
            log = self.query_one("#log", ConversationLog)
            log.add_info("Selection cancelled. Use :connect to try again.")
            return
        if getattr(self, "_awaiting_byok_model", False):
            self._awaiting_byok_model = False
            log = self.query_one("#log", ConversationLog)
            log.add_info("Selection cancelled. Use :connect to try again.")
            return
        if getattr(self, "_awaiting_byok_provider", False):
            self._awaiting_byok_provider = False
            log = self.query_one("#log", ConversationLog)
            log.add_info("Selection cancelled. Use :connect to try again.")
            return
        if getattr(self, "_awaiting_connect_type", False):
            self._awaiting_connect_type = False
            log = self.query_one("#log", ConversationLog)
            log.add_info("Selection cancelled.")
            return
        if getattr(self, "_awaiting_acp_agent_selection", False):
            self._awaiting_acp_agent_selection = False
            log = self.query_one("#log", ConversationLog)
            log.add_info("Selection cancelled. Use :connect to try again.")
            return
        if getattr(self, "_awaiting_model_selection", False):
            self._awaiting_model_selection = False
            log = self.query_one("#log", ConversationLog)
            log.add_info("Selection cancelled. Use :connect to try again.")
            return

        # Then check if agent is running (ACP or BYOK)
        log = self.query_one("#log", ConversationLog)

        # Check for BYOK/local operation
        if hasattr(self, "_pure_mode") and self._pure_mode and self._pure_mode._agent:
            # Cancel BYOK operation
            self._pure_mode.cancel()
            log.add_info("🛑 Agent operation cancelled")
            return

        # Check for ACP operation
        if self._agent_process is not None or self.is_busy:
            self.action_cancel_agent()
        else:
            # Do nothing - user can use :exit to quit
            log.add_info("💡 No agent running. Use :exit to quit.")

    def _select_model_by_number(self, num: int):
        """Select a model by number when awaiting model selection."""
        # Only work if we're awaiting selection
        if not self._awaiting_model_selection:
            return

        log = self.query_one("#log", ConversationLog)

        # Handle based on current agent
        if self.current_agent == "opencode":
            if 1 <= num <= len(self._opencode_models):
                model = self._opencode_models[num - 1]
                model_id = model.get("id", "")
                model_name = model.get("name", "")

                self.current_model = model_id
                self.current_provider = "opencode"
                self._awaiting_model_selection = False

                # Update badge with execution mode - ACP for :acp connect
                badge = self.query_one("#mode-badge", ModeBadge)
                badge.model = model_id
                badge.provider = self.current_provider
                badge.execution_mode = "acp"  # ACP mode for agent connections

                # Show confirmation
                t = Text()
                t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
                t.append("Model selected: ", style=THEME["text"])
                t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
                t.append(f" ({model_id})\n", style=THEME["dim"])
                t.append(f"  🆓 This is a FREE model! Ready to chat.\n", style=THEME["success"])
                log.write(t)
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(self._opencode_models)}")

        elif self.current_agent == "gemini":
            if 1 <= num <= len(self._gemini_models):
                model = self._gemini_models[num - 1]
                model_id = model.get("id", "")
                model_name = model.get("name", "")

                self.current_model = model_id
                self.current_provider = "gemini"
                self._awaiting_model_selection = False

                # Update badge
                badge = self.query_one("#mode-badge", ModeBadge)
                badge.model = model_id
                badge.provider = self.current_provider
                badge.execution_mode = "acp"

                # Show confirmation
                t = Text()
                t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
                t.append("Model selected: ", style=THEME["text"])
                t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
                t.append(f" ({model_id})\n", style=THEME["dim"])
                t.append(f"  ✨ Ready to chat with Gemini!\n", style=THEME["success"])
                log.write(t)
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(self._gemini_models)}")

        elif self.current_agent == "claude":
            if 1 <= num <= len(self._claude_models):
                model = self._claude_models[num - 1]
                model_id = model.get("id", "")
                model_name = model.get("name", "")

                self.current_model = model_id
                self.current_provider = "claude"
                self._awaiting_model_selection = False

                # Update badge
                badge = self.query_one("#mode-badge", ModeBadge)
                badge.model = model_id
                badge.provider = self.current_provider
                badge.execution_mode = "acp"

                # Show confirmation
                t = Text()
                t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
                t.append("Model selected: ", style=THEME["text"])
                t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
                t.append(f" ({model_id})\n", style=THEME["dim"])
                t.append(f"  🧡 Ready to chat with Claude Code!\n", style=THEME["success"])
                log.write(t)
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(self._claude_models)}")

        elif self.current_agent == "codex":
            if 1 <= num <= len(self._codex_models):
                model = self._codex_models[num - 1]
                model_id = model.get("id", "")
                model_name = model.get("name", "")

                self.current_model = model_id
                self.current_provider = "codex"
                self._awaiting_model_selection = False

                # Update badge
                badge = self.query_one("#mode-badge", ModeBadge)
                badge.model = model_id
                badge.provider = self.current_provider
                badge.execution_mode = "acp"

                # Show confirmation
                t = Text()
                t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
                t.append("Model selected: ", style=THEME["text"])
                t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
                t.append(f" ({model_id})\n", style=THEME["dim"])
                t.append(f"  📜 Ready to chat with Codex CLI!\n", style=THEME["success"])
                log.write(t)
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(self._codex_models)}")

        elif self.current_agent == "openhands":
            if 1 <= num <= len(self._openhands_models):
                model = self._openhands_models[num - 1]
                model_id = model.get("id", "")
                model_name = model.get("name", "")

                self.current_model = model_id
                self.current_provider = "openhands"
                self._awaiting_model_selection = False

                # Update badge
                badge = self.query_one("#mode-badge", ModeBadge)
                badge.model = model_id
                badge.provider = self.current_provider
                badge.execution_mode = "acp"

                # Show confirmation
                t = Text()
                t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
                t.append("Model selected: ", style=THEME["text"])
                t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
                t.append(f" ({model_id})\n", style=THEME["dim"])
                t.append(f"  🤝 Ready to chat with OpenHands!\n", style=THEME["success"])
                log.write(t)
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(self._openhands_models)}")

    def _select_by_number_universal(self, num: int):
        """Universal number selection handler for all selection modes.

        Handles:
        - Connection type selection (1=ACP, 2=BYOK, 3=LOCAL)
        - BYOK provider selection
        - BYOK model selection
        - Local provider selection
        - Local model selection
        - ACP agent selection
        - OpenCode model selection
        """
        log = self.query_one("#log", ConversationLog)
        # While awaiting typed selection, inject digits into prompt instead of auto-selecting
        if (
            getattr(self, "_awaiting_byok_model", False)
            or getattr(self, "_awaiting_local_model", False)
            or getattr(self, "_awaiting_byok_provider", False)
            or getattr(self, "_awaiting_local_provider", False)
        ):
            try:
                prompt_input = self.query_one("#prompt-input", Input)
                if not prompt_input.has_focus:
                    prompt_input.focus()
                cursor = prompt_input.cursor_position
                value = prompt_input.value
                digit = str(num)
                prompt_input.value = f"{value[:cursor]}{digit}{value[cursor:]}"
                prompt_input.cursor_position = cursor + 1
            except Exception:
                pass
            return True

        # 1. Handle connection type selection first
        if getattr(self, "_awaiting_connect_type", False):
            if num == 1:
                self._awaiting_connect_type = False
                self._awaiting_byok_provider = False
                self._awaiting_byok_model = False
                self._show_agents(log)
                return True
            elif num == 2:
                self._awaiting_connect_type = False
                self._awaiting_byok_provider = False
                self._awaiting_byok_model = False
                if hasattr(self, "_byok_selected_provider"):
                    delattr(self, "_byok_selected_provider")
                if hasattr(self, "_byok_connect_list"):
                    delattr(self, "_byok_connect_list")
                self._just_showed_byok_picker = True
                self._show_connect_picker(log)
                self.set_timer(0.3, lambda: setattr(self, "_just_showed_byok_picker", False))
                return True
            elif num == 3:
                self._awaiting_connect_type = False
                self._awaiting_byok_provider = False
                self._awaiting_byok_model = False
                self._show_local_provider_picker(log)
                return True
            return False

        # 2. Handle ACP agent selection
        if getattr(self, "_awaiting_acp_agent_selection", False):
            agent_list = getattr(self, "_acp_agent_list", [])
            if agent_list and 1 <= num <= len(agent_list):
                self._handle_acp_agent_selection(str(num), log)
                return True
            return False

        # 3. Handle BYOK provider selection
        if getattr(self, "_awaiting_byok_provider", False):
            if getattr(self, "_just_showed_byok_picker", False):
                return False
            provider_list = getattr(self, "_byok_connect_list", [])
            if provider_list and 1 <= num <= len(provider_list):
                self._handle_byok_provider_selection(str(num), log)
                return True
            return False

        # 4. Handle BYOK model selection
        if getattr(self, "_awaiting_byok_model", False):
            model_list = getattr(self, "_byok_model_list", [])
            if model_list and 1 <= num <= len(model_list):
                model = model_list[num - 1]
                provider_id = getattr(self, "_byok_selected_provider", None)
                if provider_id:
                    self._awaiting_byok_model = False
                    self._connect_byok_mode(provider_id, model, log)
                    return True
            return False

        # 5. Handle local provider selection
        if getattr(self, "_awaiting_local_provider", False):
            provider_list = getattr(self, "_local_provider_list", [])
            if provider_list and 1 <= num <= len(provider_list):
                self._handle_local_provider_selection(str(num), log)
                return True
            return False

        # 6. Handle local model selection
        if getattr(self, "_awaiting_local_model", False):
            model_list = getattr(self, "_local_model_list", [])
            if model_list and 1 <= num <= len(model_list):
                self._handle_local_model_selection(str(num), log)
                return True
            return False

        # 7. Handle OpenCode/other model selection (original behavior)
        if self._awaiting_model_selection:
            self._select_model_by_number(num)
            return True

        return False

    def _queue_selection_digit(self, digit: str) -> None:
        """Queue a digit for multi-digit selection in provider/model pickers."""
        buf = getattr(self, "_selection_digit_buffer", "")
        buf += digit
        self._selection_digit_buffer = buf

        # Mirror buffer in prompt input for visibility
        try:
            prompt_input = self.query_one("#prompt-input", Input)
            prompt_input.value = buf
            prompt_input.cursor_position = len(buf)
        except Exception:
            pass

        # Reset timer
        timer = getattr(self, "_selection_digit_timer", None)
        try:
            if timer:
                timer.stop()
        except Exception:
            pass
        self._selection_digit_timer = self.set_timer(0.35, self._apply_selection_buffer)

    def _apply_selection_buffer(self) -> None:
        """Apply buffered numeric selection to the current picker."""
        buf = getattr(self, "_selection_digit_buffer", "")
        if not buf:
            return

        # Clear buffer and prompt
        self._selection_digit_buffer = ""
        self._selection_digit_timer = None
        try:
            prompt_input = self.query_one("#prompt-input", Input)
            prompt_input.value = ""
            prompt_input.cursor_position = 0
        except Exception:
            pass

        log = self.query_one("#log", ConversationLog)

        if getattr(self, "_awaiting_byok_provider", False):
            self._handle_byok_provider_selection(buf, log)
            return
        if getattr(self, "_awaiting_local_provider", False):
            self._handle_local_provider_selection(buf, log)
            return
        if getattr(self, "_awaiting_byok_model", False):
            self._handle_byok_model_selection(buf, log)
            return
        if getattr(self, "_awaiting_local_model", False):
            self._handle_local_model_selection(buf, log)
            return

        # Fallback to universal selection for other modes
        try:
            self._select_by_number_universal(int(buf))
        except Exception:
            pass

    def action_select_model_1(self):
        """Select item 1 in current selection mode."""
        self._select_by_number_universal(1)

    def action_select_model_2(self):
        """Select item 2 in current selection mode."""
        self._select_by_number_universal(2)

    def action_select_model_3(self):
        """Select item 3 in current selection mode."""
        self._select_by_number_universal(3)

    def action_select_model_4(self):
        """Select item 4 in current selection mode."""
        self._select_by_number_universal(4)

    def action_select_model_5(self):
        """Select item 5 in current selection mode."""
        self._select_by_number_universal(5)

    def action_select_model_6(self):
        """Select item 6 in current selection mode."""
        self._select_by_number_universal(6)

    def action_select_model_7(self):
        """Select item 7 in current selection mode."""
        self._select_by_number_universal(7)

    def action_select_model_8(self):
        """Select item 8 in current selection mode."""
        self._select_by_number_universal(8)

    def action_select_model_9(self):
        """Select item 9 in current selection mode."""
        self._select_by_number_universal(9)

    def action_navigate_model_up(self):
        """Navigate to previous model (arrow up)."""
        # Check if we're in model selection mode
        if not getattr(self, "_awaiting_byok_model", False):
            return

        model_list = getattr(self, "_byok_model_list", [])
        if not model_list:
            # Try to get provider and rebuild list if needed
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._show_provider_models(provider_id, log, use_picker=False, clear_log=False)
            return

        current_idx = getattr(self, "_byok_highlighted_model_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._byok_highlighted_model_index = new_idx
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._show_provider_models(provider_id, log, use_picker=False, clear_log=False)
                # Scroll to keep highlighted item visible
                self._scroll_to_highlighted_item(log, new_idx, len(model_list))
                # Ensure input stays focused
                self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_model_down(self):
        """Navigate to next model (arrow down)."""
        # Check if we're in model selection mode
        if not getattr(self, "_awaiting_byok_model", False):
            return

        model_list = getattr(self, "_byok_model_list", [])
        if not model_list:
            # Try to get provider and rebuild list if needed
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._show_provider_models(provider_id, log, use_picker=False, clear_log=False)
            return

        current_idx = getattr(self, "_byok_highlighted_model_index", 0)
        new_idx = min(len(model_list) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._byok_highlighted_model_index = new_idx
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._show_provider_models(provider_id, log, use_picker=False, clear_log=False)
                # Scroll to keep highlighted item visible
                self._scroll_to_highlighted_item(log, new_idx, len(model_list))
                # Ensure input stays focused
                self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_opencode_model_up(self):
        """Navigate to previous opencode model (arrow up)."""
        if not getattr(self, "_awaiting_model_selection", False):
            return

        if self.current_agent != "opencode":
            return

        models = self.opencode_models
        if not models:
            return

        current_idx = getattr(self, "_opencode_highlighted_model_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._opencode_highlighted_model_index = new_idx
            log = self.query_one("#log", ConversationLog)
            # Use stored agent data if available, otherwise get from agent list
            agent = getattr(self, "_opencode_agent_data", None)
            if not agent:
                # Try to get from _acp_agent_list
                agent_list = getattr(self, "_acp_agent_list", [])
                for agent_id, agent_data in agent_list:
                    if agent_id == "opencode":
                        agent = agent_data
                        break
            if not agent:
                # Fallback: create minimal agent dict
                agent = {"name": "OpenCode", "short_name": "opencode"}
            self._show_opencode_models_selection(agent, log, clear_log=False)
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_opencode_model_down(self):
        """Navigate to next opencode model (arrow down)."""
        if not getattr(self, "_awaiting_model_selection", False):
            return

        if self.current_agent != "opencode":
            return

        models = self.opencode_models
        if not models:
            return

        current_idx = getattr(self, "_opencode_highlighted_model_index", 0)
        new_idx = min(len(models) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._opencode_highlighted_model_index = new_idx
            log = self.query_one("#log", ConversationLog)
            # Use stored agent data if available, otherwise get from agent list
            agent = getattr(self, "_opencode_agent_data", None)
            if not agent:
                # Try to get from _acp_agent_list
                agent_list = getattr(self, "_acp_agent_list", [])
                for agent_id, agent_data in agent_list:
                    if agent_id == "opencode":
                        agent = agent_data
                        break
            if not agent:
                # Fallback: create minimal agent dict
                agent = {"name": "OpenCode", "short_name": "opencode"}
            self._show_opencode_models_selection(agent, log, clear_log=False)
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_opencode_model(self):
        """Select the currently highlighted opencode model (Enter key)."""
        if not getattr(self, "_awaiting_model_selection", False):
            return

        if self.current_agent != "opencode":
            return

        models = self.opencode_models
        if not models:
            return

        current_idx = getattr(self, "_opencode_highlighted_model_index", 0)
        if 0 <= current_idx < len(models):
            model = models[current_idx]
            model_id = model.get("id", "")
            # Remove "opencode/" prefix if present
            if model_id.startswith("opencode/"):
                model_id = model_id[9:]

            log = self.query_one("#log", ConversationLog)
            self._awaiting_model_selection = False
            self.current_model = model_id
            self.current_provider = "opencode"

            # Connect to the model
            # _connect_agent is decorated with @work, so calling it directly
            # returns a Worker that will run the async method
            self._connect_agent("opencode", model_id)

    def _scroll_to_highlighted_item(
        self, log: ConversationLog, highlighted_idx: int, total_items: int
    ):
        """Scroll the log to keep the highlighted item visible in the view.

        Uses a simpler approach: scroll to home first, then scroll down just enough
        to show the highlighted item centered in view.
        """
        try:
            log.auto_scroll = False

            # For small lists, just show from top - no scrolling needed
            if total_items <= 8:
                log.scroll_home(animate=False)
                return

            # Each item takes approximately 2-4 lines depending on content
            # Header takes about 5 lines, instructions at bottom take about 10 lines
            lines_per_item = 3
            header_lines = 5
            visible_items = 8  # Approximate visible items in the log

            # If highlighted item is in first visible_items, scroll to top
            if highlighted_idx < visible_items:
                log.scroll_home(animate=False)
            else:
                # Scroll to show the highlighted item in view
                # Calculate target scroll position
                target_offset = (highlighted_idx - visible_items // 2) * lines_per_item

                # Use scroll_to with y offset
                log.scroll_home(animate=False)
                # Then scroll down to the target position
                self.set_timer(
                    0.05, lambda: self._scroll_down_to_item(log, target_offset, lines_per_item)
                )
        except Exception:
            pass  # If scrolling fails, just continue

    def _scroll_down_to_item(self, log: ConversationLog, target_offset: int, lines_per_item: int):
        """Helper to scroll down to show the highlighted item."""
        try:
            # Scroll down by the calculated amount
            scroll_steps = max(0, target_offset // 3)  # Approximate scroll steps
            for _ in range(min(scroll_steps, 30)):  # Limit to prevent excessive scrolling
                log.scroll_down(animate=False)
        except Exception:
            pass

    def _adjust_scroll_for_item(self, log: ConversationLog, highlighted_idx: int, total_items: int):
        """Adjust scroll position to show highlighted item (legacy, kept for compatibility)."""
        try:
            # Use the new simpler approach
            self._scroll_to_highlighted_item(log, highlighted_idx, total_items)
        except Exception:
            pass

    def action_select_highlighted_model(self):
        """Select the currently highlighted model (Enter key)."""
        if not getattr(self, "_awaiting_byok_model", False):
            return

        model_list = getattr(self, "_byok_model_list", [])
        if not model_list:
            return

        current_idx = getattr(self, "_byok_highlighted_model_index", 0)
        if 0 <= current_idx < len(model_list):
            model = model_list[current_idx]
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._awaiting_byok_model = False
                self._connect_byok_mode(provider_id, model, log)

    def action_navigate_provider_up(self):
        """Navigate to previous provider (arrow up)."""
        if not getattr(self, "_awaiting_byok_provider", False):
            return

        provider_list = getattr(self, "_byok_connect_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_byok_highlighted_provider_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._byok_highlighted_provider_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_byok_providers(log, clear_log=False)
            # Scroll to keep highlighted item visible
            self._scroll_to_highlighted_item(log, new_idx, len(provider_list))
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_provider_down(self):
        """Navigate to next provider (arrow down)."""
        if not getattr(self, "_awaiting_byok_provider", False):
            return

        provider_list = getattr(self, "_byok_connect_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_byok_highlighted_provider_index", 0)
        new_idx = min(len(provider_list) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._byok_highlighted_provider_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_byok_providers(log, clear_log=False)
            # Scroll to keep highlighted item visible
            self._scroll_to_highlighted_item(log, new_idx, len(provider_list))
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_provider(self):
        """Select the currently highlighted provider (Enter key)."""
        if not getattr(self, "_awaiting_byok_provider", False):
            return

        provider_list = getattr(self, "_byok_connect_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_byok_highlighted_provider_index", 0)
        if 0 <= current_idx < len(provider_list):
            provider_id, provider_def = provider_list[current_idx]
            log = self.query_one("#log", ConversationLog)
            self._awaiting_byok_provider = False
            # Reset model highlight index when entering a new provider
            self._byok_highlighted_model_index = 0
            self._show_provider_models(provider_id, log, use_picker=False)

    def action_navigate_local_provider_up(self):
        """Navigate to previous local provider (arrow up)."""
        if not getattr(self, "_awaiting_local_provider", False):
            return

        provider_list = getattr(self, "_local_provider_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_local_highlighted_provider_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._local_highlighted_provider_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_local_provider_picker(log, clear_log=False)
            # Scroll to keep highlighted item visible
            self._scroll_to_highlighted_item(log, new_idx, len(provider_list))
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_local_provider_down(self):
        """Navigate to next local provider (arrow down)."""
        if not getattr(self, "_awaiting_local_provider", False):
            return

        provider_list = getattr(self, "_local_provider_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_local_highlighted_provider_index", 0)
        new_idx = min(len(provider_list) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._local_highlighted_provider_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_local_provider_picker(log, clear_log=False)
            # Scroll to keep highlighted item visible
            self._scroll_to_highlighted_item(log, new_idx, len(provider_list))
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_local_provider(self):
        """Select the currently highlighted local provider (Enter key)."""
        if not getattr(self, "_awaiting_local_provider", False):
            return

        provider_list = getattr(self, "_local_provider_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_local_highlighted_provider_index", 0)
        if 0 <= current_idx < len(provider_list):
            provider_id, provider_def = provider_list[current_idx]
            log = self.query_one("#log", ConversationLog)
            self._awaiting_local_provider = False
            # Reset local model highlight index when entering a new provider
            self._local_highlighted_model_index = 0
            self.run_worker(self._show_local_provider_models(provider_id, log))

    def action_navigate_local_model_up(self):
        """Navigate to previous local model (arrow up)."""
        if not getattr(self, "_awaiting_local_model", False):
            return

        model_list = getattr(self, "_local_model_list", [])
        if not model_list:
            return

        current_idx = getattr(self, "_local_highlighted_model_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._local_highlighted_model_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._redraw_local_provider_models(log)
            # Scroll to keep highlighted item visible
            self._scroll_to_highlighted_item(log, new_idx, len(model_list))
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_local_model_down(self):
        """Navigate to next local model (arrow down)."""
        if not getattr(self, "_awaiting_local_model", False):
            return

        model_list = getattr(self, "_local_model_list", [])
        if not model_list:
            return

        current_idx = getattr(self, "_local_highlighted_model_index", 0)
        new_idx = min(len(model_list) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._local_highlighted_model_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._redraw_local_provider_models(log)
            # Scroll to keep highlighted item visible
            self._scroll_to_highlighted_item(log, new_idx, len(model_list))
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_local_model(self):
        """Select the currently highlighted local model (Enter key)."""
        if not getattr(self, "_awaiting_local_model", False):
            return

        model_list = getattr(self, "_local_model_list", [])
        if not model_list:
            return

        current_idx = getattr(self, "_local_highlighted_model_index", 0)
        if 0 <= current_idx < len(model_list):
            model_id = model_list[current_idx]
            provider_id = getattr(self, "_local_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._awaiting_local_model = False
                self._connect_local_mode(provider_id, model_id, log)

    def action_navigate_connect_type_up(self):
        """Navigate to previous connection type (arrow up)."""
        if not getattr(self, "_awaiting_connect_type", False):
            return

        current_idx = getattr(self, "_byok_highlighted_connect_type_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._byok_highlighted_connect_type_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_connect_type_picker(log, clear_log=False)
            # Don't scroll during navigation to keep item in focus
            # The item should already be visible after the update
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_connect_type_down(self):
        """Navigate to next connection type (arrow down)."""
        if not getattr(self, "_awaiting_connect_type", False):
            return

        current_idx = getattr(self, "_byok_highlighted_connect_type_index", 0)
        new_idx = min(2, current_idx + 1)  # 3 types: 0, 1, 2
        if new_idx != current_idx:
            self._byok_highlighted_connect_type_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_connect_type_picker(log, clear_log=False)
            # Don't scroll during navigation to keep item in focus
            # The item should already be visible after the update
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_connect_type(self):
        """Select the currently highlighted connection type (Enter key)."""
        if not getattr(self, "_awaiting_connect_type", False):
            return

        current_idx = getattr(self, "_byok_highlighted_connect_type_index", 0)
        log = self.query_one("#log", ConversationLog)
        self._awaiting_connect_type = False

        if current_idx == 0:
            # ACP - Clear BYOK/LOCAL states
            self._awaiting_byok_provider = False
            self._awaiting_byok_model = False
            self._awaiting_local_provider = False
            self._awaiting_local_model = False
            self._show_agents(log)
        elif current_idx == 1:
            # BYOK - Clear ALL selection states before showing provider picker
            self._awaiting_byok_provider = False
            self._awaiting_byok_model = False
            self._awaiting_acp_agent_selection = False
            self._awaiting_local_provider = False
            self._awaiting_local_model = False
            if hasattr(self, "_byok_selected_provider"):
                delattr(self, "_byok_selected_provider")
            if hasattr(self, "_byok_connect_list"):
                delattr(self, "_byok_connect_list")
            # Reset highlight index for fresh start
            self._byok_highlighted_provider_index = 0
            self._byok_highlighted_model_index = 0
            # Set flag to prevent any immediate input processing
            self._just_showed_byok_picker = True
            self._show_byok_providers(log)
            # Clear the flag after a delay
            self.set_timer(0.3, lambda: setattr(self, "_just_showed_byok_picker", False))
        elif current_idx == 2:
            # LOCAL - Clear ALL selection states before showing provider picker
            self._awaiting_byok_provider = False
            self._awaiting_byok_model = False
            self._awaiting_acp_agent_selection = False
            self._awaiting_local_provider = False  # Will be set in _show_local_provider_picker
            self._awaiting_local_model = False
            # Clear any existing local provider/model state
            if hasattr(self, "_local_selected_provider"):
                delattr(self, "_local_selected_provider")
            if hasattr(self, "_local_provider_list"):
                delattr(self, "_local_provider_list")
            if hasattr(self, "_local_model_list"):
                delattr(self, "_local_model_list")
            if hasattr(self, "_local_cached_models"):
                delattr(self, "_local_cached_models")
            # Reset highlight indices
            self._local_highlighted_provider_index = 0
            self._local_highlighted_model_index = 0
            self._show_local_provider_picker(log)

    def action_navigate_acp_agent_up(self):
        """Navigate to previous ACP agent (arrow up)."""
        if not getattr(self, "_awaiting_acp_agent_selection", False):
            return

        agent_list = getattr(self, "_acp_agent_list", [])
        if not agent_list:
            return

        current_idx = getattr(self, "_acp_highlighted_agent_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._acp_highlighted_agent_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_agents(log, clear_log=False)
            # Don't scroll during navigation to keep item in focus
            # The item should already be visible after the update
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_acp_agent_down(self):
        """Navigate to next ACP agent (arrow down)."""
        if not getattr(self, "_awaiting_acp_agent_selection", False):
            return

        agent_list = getattr(self, "_acp_agent_list", [])
        if not agent_list:
            return

        current_idx = getattr(self, "_acp_highlighted_agent_index", 0)
        new_idx = min(len(agent_list) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._acp_highlighted_agent_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_agents(log, clear_log=False)
            # Don't scroll during navigation to keep item in focus
            # The item should already be visible after the update
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_acp_agent(self):
        """Select the currently highlighted ACP agent (Enter key)."""
        if not getattr(self, "_awaiting_acp_agent_selection", False):
            return

        agent_list = getattr(self, "_acp_agent_list", [])
        if not agent_list:
            return

        current_idx = getattr(self, "_acp_highlighted_agent_index", 0)
        if 0 <= current_idx < len(agent_list):
            agent_id, agent_data = agent_list[current_idx]
            log = self.query_one("#log", ConversationLog)
            self._awaiting_acp_agent_selection = False

            # Check if agent is installed
            from superqode.commands.acp import check_agent_installed

            is_installed = check_agent_installed(agent_data)

            if is_installed:
                # Connect to the agent
                log.add_info(f"Connecting to {agent_data['name']}...")
                self._connect_agent(agent_data["short_name"])
            else:
                log.add_error(f"{agent_data['name']} is not installed.")
                from superqode.agents.registry import get_agent_installation_info

                install_info = get_agent_installation_info(agent_data)
                install_cmd = install_info.get("command", "")
                if install_cmd:
                    log.add_info(f"Install with: {install_cmd}")
                else:
                    log.add_info(f"Use: :acp install {agent_data['short_name']}")

    def _select_byok_model_by_number(self, num: int):
        """Select a BYOK model by number."""
        if not getattr(self, "_awaiting_byok_model", False):
            return

        model_list = getattr(self, "_byok_model_list", [])
        if not model_list:
            return

        if 1 <= num <= len(model_list):
            model = model_list[num - 1]
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._awaiting_byok_model = False
                self._connect_byok_mode(provider_id, model, log)

    def _start_stream_animation(self, log: ConversationLog):
        """Start animation during agent streaming."""
        self._stream_animation_frame = 0
        self._stream_log = log
        self.is_busy = True

        # IMPORTANT: Enable auto-scroll so user sees agent's work in real-time
        log.auto_scroll = True

        # Hide prompt area when agent is thinking
        try:
            prompt_area = self.query_one("#prompt-area")
            prompt_area.add_class("hidden")
        except Exception:
            pass

        # Show streaming thinking indicator with changing text
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = True
            thinking_indicator.add_class("visible")
        except Exception:
            pass

        # Show scanning line animation at TOP
        try:
            thinking_wave = self.query_one("#thinking-wave", TopScanningLine)
            thinking_wave.is_active = True
            thinking_wave.add_class("visible")
        except Exception:
            pass

        # Show scanning line animation at BOTTOM
        try:
            thinking_wave_bottom = self.query_one("#thinking-wave-bottom", BottomScanningLine)
            thinking_wave_bottom.is_active = True
            thinking_wave_bottom.add_class("visible")
        except Exception:
            pass

    def _stop_stream_animation(self):
        """Stop the streaming animation."""
        self.is_busy = False

        # Show prompt area again
        try:
            prompt_area = self.query_one("#prompt-area")
            prompt_area.remove_class("hidden")
            # Re-focus the input
            self.query_one("#prompt-input", Input).focus()
        except Exception:
            pass

        # Hide streaming thinking indicator
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = False
            thinking_indicator.remove_class("visible")
        except Exception:
            pass

        # Hide scanning line animation at TOP
        try:
            thinking_wave = self.query_one("#thinking-wave", TopScanningLine)
            thinking_wave.is_active = False
            thinking_wave.remove_class("visible")
        except Exception:
            pass

        # Hide scanning line animation at BOTTOM
        try:
            thinking_wave_bottom = self.query_one("#thinking-wave-bottom", BottomScanningLine)
            thinking_wave_bottom.is_active = False
            thinking_wave_bottom.remove_class("visible")
        except Exception:
            pass

    @on(CollapsibleSidebar.FileOpened)
    def on_sidebar_file_opened(self, event: CollapsibleSidebar.FileOpened) -> None:
        """Handle file opened from sidebar - show in conversation."""
        event.stop()
        log = self.query_one("#log", ConversationLog)
        self._view_file(str(event.path), log)

    @on(ColorfulDirectoryTree.FileOpenRequested)
    def on_tree_file_open_requested(self, event: ColorfulDirectoryTree.FileOpenRequested) -> None:
        """Handle file open request from tree directly."""
        event.stop()
        log = self.query_one("#log", ConversationLog)
        self._view_file(str(event.path), log)

    def action_focus_input(self):
        """Focus the input box - always available via Ctrl+I or when needed."""
        self._ensure_input_focus()

    # ========================================================================
    # Enhanced Thinking Animation
    # ========================================================================

    def _start_thinking(self, msg: str = "🧠 Thinking..."):
        self.is_busy = True
        self._thinking_start = time.time()
        self._thinking_idx = 0

        # Show streaming thinking indicator with changing text
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = True
            thinking_indicator.add_class("visible")
        except Exception:
            pass

        # Show scanning line animation at TOP
        try:
            thinking_wave = self.query_one("#thinking-wave", TopScanningLine)
            thinking_wave.is_active = True
            thinking_wave.add_class("visible")
        except Exception:
            pass

        # Show scanning line animation at BOTTOM
        try:
            thinking_wave_bottom = self.query_one("#thinking-wave-bottom", BottomScanningLine)
            thinking_wave_bottom.is_active = True
            thinking_wave_bottom.add_class("visible")
        except Exception:
            pass

        # Hide prompt area
        try:
            prompt_area = self.query_one("#prompt-area")
            prompt_area.add_class("hidden")
        except Exception:
            pass

    def _stop_thinking(self, show_done: bool = False):
        """Stop the thinking animation.

        Args:
            show_done: If True, show "Done in X.Xs" message. Default False for streaming.
        """
        self.is_busy = False

        # Hide streaming thinking indicator
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = False
            thinking_indicator.remove_class("visible")
        except Exception:
            pass

        # Hide scanning line animation at TOP
        try:
            thinking_wave = self.query_one("#thinking-wave", TopScanningLine)
            thinking_wave.is_active = False
            thinking_wave.remove_class("visible")
        except Exception:
            pass

        # Hide scanning line animation at BOTTOM
        try:
            thinking_wave_bottom = self.query_one("#thinking-wave-bottom", BottomScanningLine)
            thinking_wave_bottom.is_active = False
            thinking_wave_bottom.remove_class("visible")
        except Exception:
            pass

        # Show prompt area again
        try:
            prompt_area = self.query_one("#prompt-area")
            prompt_area.remove_class("hidden")
            self.query_one("#prompt-input", Input).focus()
        except Exception:
            pass

        # Only show done message if requested (not during streaming)
        if show_done:
            elapsed = time.time() - self._thinking_start
            self.query_one("#log", ConversationLog).add_success(f"Done in {elapsed:.1f}s ✨")

    def _track_byok_usage(self, input_text: str, response: str, tool_calls: int = 0):
        """Track BYOK usage and update status bar."""
        from superqode.providers.usage import get_usage_tracker

        # Estimate tokens (rough: 4 chars per token)
        input_tokens = len(input_text) // 4
        output_tokens = len(response) // 4

        tracker = get_usage_tracker()
        tracker.add_usage(input_tokens, output_tokens)

        for _ in range(tool_calls):
            tracker.add_tool_call()

        # Update status bar
        self._update_byok_status_bar()

    def _update_byok_status_bar(self):
        """Update status bar with current BYOK usage."""
        from superqode.providers.usage import get_usage_tracker

        try:
            status_bar = self.query_one("#status-bar", ColorfulStatusBar)
            tracker = get_usage_tracker()
            summary = tracker.get_summary()

            if summary["connected"]:
                status_bar.update_byok_status(
                    provider=summary["provider"],
                    model=summary["model"],
                    tokens=summary["tokens"],
                    cost=summary["cost"],
                )
        except Exception:
            pass

    # ========================================================================
    # Input Handling
    # ========================================================================

    def on_input_submitted(self, event: Input.Submitted):
        """Handle input submission - only processes on Enter, doesn't interfere with typing."""
        if event.input.id != "prompt-input":
            return

        text = event.value.strip()
        # If a selection digit buffer is active, clear its timer to avoid double-select
        if hasattr(self, "_selection_digit_timer") and self._selection_digit_timer:
            try:
                self._selection_digit_timer.stop()
            except Exception:
                pass
            self._selection_digit_timer = None
            if hasattr(self, "_selection_digit_buffer"):
                self._selection_digit_buffer = ""
        log = self.query_one("#log", ConversationLog)

        # Handle Enter key (empty input) for selections
        if not text:
            # Check if awaiting ACP agent selection
            if getattr(self, "_awaiting_acp_agent_selection", False):
                self.action_select_highlighted_acp_agent()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting BYOK model selection
            if getattr(self, "_awaiting_byok_model", False):
                self.action_select_highlighted_model()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting BYOK provider selection
            if getattr(self, "_awaiting_byok_provider", False):
                self.action_select_highlighted_provider()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting LOCAL model selection
            if getattr(self, "_awaiting_local_model", False):
                self.action_select_highlighted_local_model()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting LOCAL provider selection
            # CRITICAL: Only auto-select if we're actually awaiting user input, not just showing the picker
            # Don't auto-select on empty input immediately after showing picker
            if getattr(self, "_awaiting_local_provider", False):
                # Check if we just showed the picker - if so, don't auto-select yet
                if not getattr(self, "_just_showed_local_picker", False):
                    self.action_select_highlighted_local_provider()
                event.input.value = ""  # Clear input
                return

            # Check if awaiting connection type selection
            if getattr(self, "_awaiting_connect_type", False):
                self.action_select_highlighted_connect_type()
                event.input.value = ""  # Clear input
                return

            # Empty input with no selection mode - do nothing
            return

        # Clear input immediately after submission (user has pressed Enter)
        event.input.value = ""

        # Ensure input stays focused for next message
        try:
            event.input.focus()
        except Exception:
            pass

        log = self.query_one("#log", ConversationLog)

        # Check for commands FIRST (before selection handlers) so :home, :back, :cancel work
        if text.startswith(":"):
            cmd = text[1:].strip().lower()
            # Handle navigation commands during selection
            if cmd in ("home", "back", "cancel") and (
                getattr(self, "_awaiting_connect_type", False)
                or getattr(self, "_awaiting_acp_agent_selection", False)
                or getattr(self, "_awaiting_byok_provider", False)
                or getattr(self, "_awaiting_byok_model", False)
                or getattr(self, "_awaiting_local_provider", False)
            ):
                # Cancel selection mode
                self._awaiting_connect_type = False
                self._awaiting_acp_agent_selection = False
                self._awaiting_byok_provider = False
                self._awaiting_byok_model = False
                self._awaiting_local_provider = False
                # Clear selection state
                if hasattr(self, "_byok_connect_list"):
                    delattr(self, "_byok_connect_list")
                if hasattr(self, "_byok_model_list"):
                    delattr(self, "_byok_model_list")
                if hasattr(self, "_byok_selected_provider"):
                    delattr(self, "_byok_selected_provider")
                if hasattr(self, "_acp_agent_list"):
                    delattr(self, "_acp_agent_list")
                if hasattr(self, "_local_provider_list"):
                    delattr(self, "_local_provider_list")
                # Handle the command - call _go_home directly for :home to ensure it always works
                if cmd == "home":
                    self._go_home(log)
                elif cmd in ("back", "cancel"):
                    log.add_info("Selection cancelled. Use :connect to try again.")
                return

            # Record command in history
            self._history_manager.append_sync(
                text,
                mode=self.current_mode if self.current_mode != "home" else None,
                agent=self.current_agent if self.current_agent else None,
            )
            self._handle_command(text, log)
            return

        # Shell command
        if text.startswith(">"):
            cmd = text[1:].strip()
            if cmd:
                self._run_shell(cmd, log)
            return

        # Check if awaiting connect type selection
        if getattr(self, "_awaiting_connect_type", False):
            if text.strip() == "1":
                self._awaiting_connect_type = False
                # Clear any BYOK state to prevent interference
                self._awaiting_byok_provider = False
                self._awaiting_byok_model = False
                self._show_agents(log)
                return
            elif text.strip() == "2":
                self._awaiting_connect_type = False
                # Clear any BYOK state before showing provider picker
                # This is critical to prevent "2" from being processed as provider selection
                self._awaiting_byok_provider = False
                self._awaiting_byok_model = False
                if hasattr(self, "_byok_selected_provider"):
                    delattr(self, "_byok_selected_provider")
                if hasattr(self, "_byok_connect_list"):
                    delattr(self, "_byok_connect_list")
                # Set flag to prevent this input from being processed as provider selection
                self._just_showed_byok_picker = True
                # Clear input to prevent "2" from being processed again
                event.input.value = ""
                # Show provider picker immediately
                self._show_connect_picker(log)
                # Clear the flag after a delay to allow normal selection
                self.set_timer(0.3, lambda: setattr(self, "_just_showed_byok_picker", False))
                return
            elif text.strip() == "3":
                self._awaiting_connect_type = False
                # Clear any BYOK state to prevent interference
                self._awaiting_byok_provider = False
                self._awaiting_byok_model = False
                self._show_local_provider_picker(log)
                return
            else:
                log.add_error("Invalid selection. Enter 1 for ACP, 2 for BYOK, or 3 for LOCAL")
                return

        # Check if awaiting ACP agent selection
        if getattr(self, "_awaiting_acp_agent_selection", False):
            if self._handle_acp_agent_selection(text, log):
                return

        # Check if awaiting model selection and user typed a number 1-5
        if self._awaiting_model_selection and text in ("1", "2", "3", "4", "5"):
            self._select_model_by_number(int(text))
            return

        # Check if awaiting BYOK provider selection
        if getattr(self, "_awaiting_byok_provider", False):
            # CRITICAL: Prevent immediate processing if we just showed the picker
            # This prevents "2" from being processed as provider selection right after selecting BYOK
            if getattr(self, "_just_showed_byok_picker", False):
                # Clear the flag and completely ignore this input
                # Don't process it at all - it was meant for connection type selection
                return

            # Also check if this is "2" and we're in a transition state
            # This is an extra safeguard
            if text.strip() == "2" and getattr(self, "_just_showed_byok_picker", False):
                return

            # Check for Enter key - empty input means Enter was pressed
            if not text.strip():
                # Use highlighted provider
                self.action_select_highlighted_provider()
                return
            if self._handle_byok_provider_selection(text, log):
                return

        # Check if awaiting LOCAL provider selection
        if getattr(self, "_awaiting_local_provider", False):
            if self._handle_local_provider_selection(text, log):
                return

        # Check if awaiting LOCAL model selection
        if getattr(self, "_awaiting_local_model", False):
            if self._handle_local_model_selection(text, log):
                return

        # Check if awaiting BYOK model selection
        if getattr(self, "_awaiting_byok_model", False):
            if self._handle_byok_model_selection(text, log):
                return

                # Check if awaiting provider selection
                return

                # Check if awaiting model selection
                return
            # Record command in history
            self._history_manager.append_sync(
                text,
                mode=self.current_mode if self.current_mode != "home" else None,
                agent=self.current_agent if self.current_agent else None,
            )
            self._handle_command(text, log)
            return

        # Message - record and send
        self._history_manager.append_sync(
            text,
            mode=self.current_mode if self.current_mode != "home" else None,
            agent=self.current_agent if self.current_agent else None,
        )
        self._handle_message(text, log)

    # ========================================================================
    # Shell with Danger Detection
    # ========================================================================

    @work(exclusive=True, thread=True)
    def _run_shell(self, cmd: str, log: ConversationLog):
        import os

        # Analyze command for danger
        project_dir = str(Path.cwd())
        level, reason, target = analyze_command(project_dir, project_dir, cmd)

        # Show warning for dangerous commands
        if level >= DangerLevel.DANGEROUS:
            style = DANGER_STYLES[level]

            def show_warning():
                t = Text()
                t.append(f"\n  {style['icon']} ", style=f"bold {style['color']}")
                t.append(f"{style['label']}: ", style=f"bold {style['color']}")
                t.append(f"{reason}\n", style=style["color"])
                if target:
                    t.append(f"  📁 Target: {target}\n", style=THEME["muted"])
                if level == DangerLevel.DESTRUCTIVE:
                    t.append(
                        f"  ⚠️  This may affect files outside the project!\n", style=THEME["error"]
                    )
                log.write(t)

            self.call_from_thread(show_warning)

        self.call_from_thread(lambda: setattr(self, "is_busy", True))

        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, cwd=os.getcwd(), timeout=60
            )
            output = (result.stdout + result.stderr).strip()
            ok = result.returncode == 0
            self.call_from_thread(log.add_shell, cmd, output, ok)

            # Record in history
            self._history_manager.append_sync(f">{cmd}", success=ok)

        except subprocess.TimeoutExpired:
            self.call_from_thread(log.add_shell, cmd, "⏰ Timed out", False)
        except Exception as e:
            self.call_from_thread(log.add_error, str(e))
        finally:
            self.call_from_thread(lambda: setattr(self, "is_busy", False))

    # ========================================================================
    # Command Handling
    # ========================================================================

    def _handle_command(self, cmd: str, log: ConversationLog):
        # Command aliases for Vim-friendly shortcuts
        alias_map = {
            "c": "connect",
            "q": "quit",
            "h": "help",
            "s": "sidebar",
            "i": "init",
            "m": "mode",
        }

        parts = cmd[1:].split(maxsplit=1)
        if not parts or not parts[0]:
            return
        c = parts[0].lower()

        # Expand alias if it's a single character
        if len(c) == 1 and c in alias_map:
            c = alias_map[c]
            # Reconstruct command with expanded alias
            cmd = ":" + c + (f" {parts[1]}" if len(parts) > 1 else "")
            parts = cmd[1:].split(maxsplit=1)
            c = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
        else:
            args = parts[1] if len(parts) > 1 else ""

        if c == "help":
            self._show_help(log)
        elif c == "clear":
            self.action_clear_screen()
        elif c in ("exit", "quit"):
            self._do_exit(log)
        elif c == "init":
            self._init_config(args, log)
        elif c == "dev":
            self._set_role("dev", args or "fullstack", log)
        elif c in ("qa", "qe"):
            if not self._has_superqode_config():
                log.add_error("No superqode.yaml found. Run :init to create one.")
                return
            self._set_role("qe", args or "fullstack", log)
        elif c == "devops":
            self._set_role("devops", args or "fullstack", log)
        elif c in ("home", "disconnect"):
            self._go_home(log)
        elif c == "roles":
            self._show_roles(log)
        elif c == "acp":
            self._acp_cmd(args, log)
        elif c == "team":
            self._show_team(log)
        elif c == "superqe":
            self._handle_superqe_command(args, log)
        elif c == "handoff":
            self._handoff(args, log)
        elif c == "context":
            self._show_context(log)
        elif c == "files":
            self._show_files(log)
        elif c == "find":
            self._find_files(args, log)
        elif c == "sidebar":
            self.action_toggle_sidebar()
        elif c == "toggle_thinking":
            # Allow users to type :toggle_thinking to toggle logs
            self.action_toggle_thinking()
        # Copy/Open/Edit commands
        elif c == "copy":
            self._handle_copy(log)
        elif c == "open":
            self._handle_open(log)
        elif c == "select":
            self._handle_select(log)
        elif c == "edit":
            self._handle_edit(log)
        elif c == "diagnostics":
            self._handle_diagnostics(args, log)
        elif c == "theme":
            self._handle_theme(args, log)
        # New coding agent commands
        elif c == "approve":
            self._handle_approve(args, log)
        elif c == "reject":
            self._handle_reject(args, log)
        elif c == "diff":
            self._handle_diff(args, log)
        elif c == "plan":
            self._handle_plan(args, log)
        elif c == "undo":
            self._handle_undo(log)
        elif c == "history":
            self._handle_history(args, log)
        elif c == "view":
            self._handle_view(args, log)
        elif c == "search":
            self._handle_search(args, log)
        elif c == "connect":
            # Parse subcommand: :connect [acp|byok|local] [args...]
            if not args:
                # Clear any BYOK state before showing connection type picker
                self._awaiting_byok_provider = False
                self._awaiting_byok_model = False
                if hasattr(self, "_byok_selected_provider"):
                    delattr(self, "_byok_selected_provider")
                # Show picker to choose acp, byok, or local
                self._show_connect_type_picker(log)
            else:
                parts = args.split(maxsplit=1)
                subcmd = parts[0].lower().strip()
                subargs = parts[1].strip() if len(parts) > 1 else ""

                # Explicitly handle known subcommands
                if subcmd == "acp":
                    # Route to ACP connection (current :acp connect behavior)
                    self._connect_acp_cmd(subargs, log)
                elif subcmd == "byok":
                    # Route to BYOK connection - always show provider picker if no args
                    self._connect_byok_cmd(subargs, log)
                elif subcmd == "local":
                    # Route to LOCAL connection
                    self._connect_local_cmd(subargs, log)
                else:
                    # Try to parse as BYOK provider/model (backward compatibility)
                    # But first check if it's a known subcommand that was missed
                    if subcmd in ("", "help", "?"):
                        # Show connection type picker if empty or help
                        self._show_connect_type_picker(log)
                    else:
                        # Treat as provider/model
                        self._connect_byok_cmd(args, log)
        elif c == "models":
            self._models_cmd(args, log)
        elif c == "usage":
            self._usage_cmd(args, log)
        elif c == "health":
            self._health_cmd(args, log)
        elif c == "mode":
            self._set_approval_mode(args, log)
        elif c == "log":
            self._handle_log_verbosity(args, log)
        elif c == "redo":
            self._handle_redo(log)
        elif c == "checkpoints":
            self._handle_checkpoints(log)
        elif c == "demo":
            self._show_superqode_demo(log)
        elif c == "local":
            self._local_cmd(args, log)
        elif c == "hf":
            self._hf_cmd(args, log)
        else:
            # Agent shortcut
            agent = next((a for a in self.agents if a.short_name == c), None)
            if agent:
                self._connect_agent(agent.short_name)
            else:
                log.add_error(f"Unknown command: {c}")
                log.add_system("Type :help for available commands")

        # Always return focus to input after command completes
        # Use a small delay to ensure command output is displayed first
        self.set_timer(0.1, self._ensure_input_focus)

    def _show_superqode_demo(self, log: ConversationLog):
        """Show a demo of SuperQode's unique design system."""
        from time import sleep

        # Clear screen first
        log.clear()

        # Demo header
        text = Text()
        text.append("\n")

        # Gradient title
        title = "SUPERQODE DESIGN DEMO"
        for i, char in enumerate(title):
            color = GRADIENT_PURPLE[i % len(GRADIENT_PURPLE)]
            text.append(char, style=f"bold {color}")
        text.append("\n")

        # Quantum divider
        for i, char in enumerate("─" * 50):
            color = GRADIENT_PURPLE[i % len(GRADIENT_PURPLE)]
            text.append(char, style=color)
        text.append("\n\n")

        log.write(text)

        # 1. Show agent header style
        header = Text()
        header.append("  1. Agent Header (during work)\n\n", style=f"bold {SQ_COLORS.text_primary}")
        log.write(header)

        # Simulate agent header
        agent_header = Text()
        for i, char in enumerate("─" * 50):
            agent_header.append(char, style=GRADIENT_PURPLE[i % len(GRADIENT_PURPLE)])
        agent_header.append("\n")
        agent_header.append("  ◈ ", style=f"bold {SQ_COLORS.primary}")
        agent_header.append("OPENCODE ", style=f"bold {SQ_COLORS.text_primary}")
        agent_header.append("is working\n", style=SQ_COLORS.text_muted)
        agent_header.append("  Model: ", style=SQ_COLORS.text_dim)
        agent_header.append("claude-3-5-sonnet", style=f"bold {SQ_COLORS.info}")
        agent_header.append("  │  ", style=SQ_COLORS.text_ghost)
        agent_header.append("● ", style=f"bold {SQ_COLORS.success}")
        agent_header.append("AUTO\n\n", style=f"bold {SQ_COLORS.success}")
        log.write(agent_header)

        # 2. Show thinking animation
        think_header = Text()
        think_header.append(
            "  2. Thinking Animation (quantum style)\n\n", style=f"bold {SQ_COLORS.text_primary}"
        )
        log.write(think_header)

        quantum_frames = ["◇", "◆", "◈", "◆"]
        for i in range(4):
            think = Text()
            icon = quantum_frames[i % len(quantum_frames)]
            color = GRADIENT_PURPLE[i % len(GRADIENT_PURPLE)]
            think.append(f"  {icon} ", style=f"bold {color}")
            think.append("Analyzing your request...\n", style=f"italic {SQ_COLORS.text_muted}")
            log.write(think)

        # 3. Show tool calls
        log.write(Text("\n"))
        tool_header = Text()
        tool_header.append(
            "  3. Tool Calls (minimal icons)\n\n", style=f"bold {SQ_COLORS.text_primary}"
        )
        log.write(tool_header)

        tools = [
            ("◐", "↳", "Read", "src/main.py", SQ_COLORS.primary_light),
            ("✦", "⌕", "Search", "function definition", SQ_COLORS.success),
            ("◐", "↲", "Write", "src/utils.py", SQ_COLORS.primary_light),
            ("✦", "▸", "Shell", "npm test", SQ_COLORS.success),
        ]

        for status_icon, kind_icon, name, target, color in tools:
            tool = Text()
            tool.append(f"  {status_icon} ", style=f"bold {color}")
            tool.append(f"{kind_icon} ", style=SQ_COLORS.text_dim)
            tool.append(name, style=SQ_COLORS.text_secondary)
            tool.append(f"  {target}\n", style=SQ_COLORS.text_ghost)
            log.write(tool)

        # 4. Show completion
        log.write(Text("\n"))
        comp_header = Text()
        comp_header.append(
            "  4. Completion (clean, no emojis)\n\n", style=f"bold {SQ_COLORS.text_primary}"
        )
        log.write(comp_header)

        # Success line
        success_gradient = [SQ_COLORS.success, "#14b8a6", SQ_COLORS.info]
        success = Text()
        for i, char in enumerate("─" * 50):
            success.append(char, style=success_gradient[i % len(success_gradient)])
        success.append("\n\n")
        success.append("  ✦ ", style=f"bold {SQ_COLORS.success}")
        success.append("OPENCODE ", style=f"bold {SQ_COLORS.text_primary}")
        success.append("completed successfully\n\n", style=SQ_COLORS.text_muted)

        # Stats
        success.append("  ◇ 2.5s", style=SQ_COLORS.text_dim)
        success.append("  │  ◈ 4 tools", style=SQ_COLORS.primary_light)
        success.append("  │  ↲ 2 modified", style=SQ_COLORS.success)
        success.append("\n\n")
        log.write(success)

        # 5. Show icons reference
        icons_header = Text()
        icons_header.append(
            "  5. SuperQode Icon System\n\n", style=f"bold {SQ_COLORS.text_primary}"
        )
        log.write(icons_header)

        icons = Text()
        icons.append("  Status:   ", style=SQ_COLORS.text_muted)
        icons.append("◇ idle  ", style=SQ_COLORS.text_dim)
        icons.append("◆ active  ", style=SQ_COLORS.primary)
        icons.append("◈ thinking  ", style=SQ_COLORS.primary_light)
        icons.append("✦ success  ", style=SQ_COLORS.success)
        icons.append("✕ error\n", style=SQ_COLORS.error)

        icons.append("  Tools:    ", style=SQ_COLORS.text_muted)
        icons.append("↳ read  ", style=SQ_COLORS.info)
        icons.append("↲ write  ", style=SQ_COLORS.success)
        icons.append("▸ shell  ", style=SQ_COLORS.warning)
        icons.append("⌕ search  ", style=SQ_COLORS.info)
        icons.append("⋮ glob\n", style=SQ_COLORS.text_muted)

        icons.append("  Connect:  ", style=SQ_COLORS.text_muted)
        icons.append("● connected  ", style=SQ_COLORS.success)
        icons.append("○ disconnected\n", style=SQ_COLORS.text_dim)
        log.write(icons)

        # 6. Keyboard shortcuts
        log.write(Text("\n"))
        kb_header = Text()
        kb_header.append("  6. New Keyboard Shortcuts\n\n", style=f"bold {SQ_COLORS.text_primary}")
        log.write(kb_header)

        shortcuts = Text()
        shortcuts.append("  Ctrl+Z     ", style=f"bold {SQ_COLORS.info}")
        shortcuts.append("Undo last agent operation\n", style=SQ_COLORS.text_secondary)
        shortcuts.append("  Ctrl+Shift+Z  ", style=f"bold {SQ_COLORS.info}")
        shortcuts.append("Redo\n", style=SQ_COLORS.text_secondary)
        shortcuts.append("  Ctrl+S     ", style=f"bold {SQ_COLORS.info}")
        shortcuts.append("Create checkpoint\n", style=SQ_COLORS.text_secondary)
        shortcuts.append("  Ctrl+\\     ", style=f"bold {SQ_COLORS.info}")
        shortcuts.append("Toggle split view\n", style=SQ_COLORS.text_secondary)
        log.write(shortcuts)

        # Footer
        log.write(Text("\n"))
        footer = Text()
        for i, char in enumerate("─" * 50):
            footer.append(char, style=GRADIENT_PURPLE[i % len(GRADIENT_PURPLE)])
        footer.append("\n")
        footer.append("  ◇ Try ", style=SQ_COLORS.text_ghost)
        footer.append(":connect acp opencode", style=f"bold {SQ_COLORS.info}")
        footer.append(" to see it in action\n\n", style=SQ_COLORS.text_ghost)
        log.write(footer)

    def action_clear_screen(self):
        log = self.query_one("#log", ConversationLog)
        log.clear()
        try:
            from superqode.tui import load_team_config

            team_name = load_team_config().team_name
        except Exception:
            team_name = "Development Team"
        # Temporarily disable auto-scroll so we can scroll to top
        log.auto_scroll = False
        log.write(render_welcome(self.agents, team_name))
        # Scroll to top so user sees the attractive header first
        log.scroll_home(animate=False)
        # Re-enable auto-scroll for future messages
        self.set_timer(0.2, lambda: setattr(log, "auto_scroll", True))
        # Ensure focus returns to input
        self.set_timer(0.1, self._ensure_input_focus)

    def _clear_for_workspace(self, log: ConversationLog, context: str = ""):
        """Clear screen and show minimal workspace header for focused work.

        Args:
            log: The conversation log widget
            context: Optional context string (e.g., "DEV.FULLSTACK", "OPENCODE")
        """
        log.clear()

        # Show minimal ready message
        t = Text()

        # Ensure focus returns to input after clearing
        self.set_timer(0.1, self._ensure_input_focus)
        t.append("\n")
        if context:
            t.append(f"  ✨ ", style=THEME["purple"])
            t.append(f"Ready as ", style=THEME["muted"])
            t.append(context, style=f"bold {THEME['cyan']}")
            t.append(f" — What would you like to build?\n", style=THEME["muted"])
        else:
            t.append(f"  ✨ Ready — What would you like to build?\n", style=THEME["muted"])
        t.append("\n")
        log.write(t)

    def _init_config(self, args: str, log: ConversationLog):
        """Initialize superqode.yaml in current directory."""
        from pathlib import Path

        force = args.strip() == "--force" or args.strip() == "-f"
        config_path = Path.cwd() / "superqode.yaml"

        if config_path.exists() and not force:
            log.add_info(f"Configuration already exists at {config_path}")
            log.add_system("Use :init --force to overwrite")
            return

        # Use the packaged template
        template_path = Path(__file__).parent / "data" / "superqode-template.yaml"
        if template_path.exists():
            import shutil

            shutil.copy2(template_path, config_path)
            log.add_success(f"Created {config_path} with all roles available")
            log.add_info(
                "⚡ Power QE roles: unit, integration, api, ui, accessibility, security, usability"
            )
            log.add_info(
                "💡 Update each role's job_description in superqode.yaml for best results."
            )
        else:
            # Fallback: create basic config if template not found
            default_config = """# =============================================================================
# SuperQode - Team Configuration
# =============================================================================
# Multi-agent software development team
# Run: superqode (TUI) or superqode --help (CLI)
# =============================================================================

superqode:
  version: "1.0"
  team_name: "Full Stack Development Team"
  description: "AI-powered software development team"

# Default configuration for all roles
default:
  mode: "acp"
  agent: "opencode"
  agent_config:
    provider: "opencode"
    model: "glm-4.7-free"

# =============================================================================
# TEAM ROLES - Enable the ones you need
# =============================================================================
team:
  # Development roles
  dev:
    description: "Software Development"
    roles:
      fullstack:
        description: "Full-stack development and implementation"
        mode: "acp"
        agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "glm-4.7-free"
        enabled: false  # Set to true to enable
        job_description: |
          You are a Senior Full-Stack Developer with expertise in modern web technologies.

          EXPERTISE:
          - Frontend: React, Vue.js, Next.js, TypeScript, Tailwind CSS
          - Backend: Node.js, Python, Go, REST APIs, GraphQL
          - Databases: PostgreSQL, MongoDB, Redis
          - DevOps basics: Docker, CI/CD

          RESPONSIBILITIES:
          - Write clean, maintainable code
          - Implement features end-to-end
          - Follow best practices and coding standards
          - Debug and fix issues

      frontend:
        description: "Frontend/UI development specialist"
        mode: "acp"
        agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "grok-code"
        enabled: false  # Set to true to enable
        job_description: |
          You are a Senior Frontend Developer specializing in modern web UIs.

          EXPERTISE:
          - React, Vue.js, Next.js, TypeScript
          - CSS3, Tailwind CSS, component libraries
          - State management, testing frameworks
          - Performance optimization and accessibility

      backend:
        description: "Backend/API development specialist"
        mode: "acp"
        agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "minimax-m2.1-free"
        enabled: false  # Set to true to enable
        job_description: |
          You are a Senior Backend Developer specializing in APIs and services.

          EXPERTISE:
          - Node.js, Python, Go, REST APIs
          - Databases: PostgreSQL, MongoDB, Redis
          - Authentication and security
          - API design and documentation

  # QE roles
  qe:
    description: "Quality Engineering"
    roles:
      fullstack:
        description: "Full-stack QE engineer"
        mode: "acp"
        agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "grok-code"
        enabled: false  # Set to true to enable
        job_description: |
          You are a Senior QA Engineer with expertise in all testing types.

          EXPERTISE:
          - Unit testing: Jest, Pytest, Go testing
          - Integration testing: Supertest, TestContainers
          - E2E testing: Playwright, Cypress, Selenium
          - API testing: Postman, REST Client, k6
          - Performance testing: k6, Artillery, JMeter
          - Security testing: OWASP ZAP, Burp Suite basics
          - Test automation frameworks and CI/CD integration

  # DevOps roles
  devops:
    description: "DevOps & Infrastructure"
    roles:
      fullstack:
        description: "Full-stack DevOps engineer"
        mode: "acp"
        agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "gpt-5-nano"
        enabled: false  # Set to true to enable
        job_description: |
          You are a Senior DevOps Engineer with full-stack infrastructure expertise.

          EXPERTISE:
          - CI/CD: GitHub Actions, GitLab CI, Jenkins, CircleCI
          - Containers: Docker, Docker Compose, Podman
          - Orchestration: Kubernetes, Helm, Kustomize
          - IaC: Terraform, Pulumi, CloudFormation
          - Cloud: AWS, GCP, Azure (all major services)
          - Monitoring: Prometheus, Grafana, Datadog
          - Logging: ELK Stack, Loki, CloudWatch
          - Secrets: Vault, AWS Secrets Manager

          RESPONSIBILITIES:
          - Design and implement CI/CD pipelines
          - Containerize applications
          - Set up infrastructure as code
          - Configure monitoring and alerting
          - Manage deployments and releases
"""

            with open(config_path, "w") as f:
                f.write(default_config)
            log.add_success(f"Created {config_path} with basic roles available")
            log.add_info(
                "⚡ Power QE roles: unit, integration, api, ui, accessibility, security, usability"
            )
            log.add_info(
                "💡 Update each role's job_description in superqode.yaml for best results."
            )

        t = Text()
        t.append("\n  Quick start:\n", style=THEME["muted"])
        t.append("    :qe fullstack     ", style=f"bold {THEME['orange']}")
        t.append("Start QE (requires superqode.yaml)\n", style=THEME["dim"])
        t.append("    :roles            ", style=f"bold {THEME['cyan']}")
        t.append("List available roles\n", style=THEME["dim"])
        t.append("    :connect acp <name> ", style=f"bold {THEME['success']}")
        t.append("Connect an ACP agent\n", style=THEME["dim"])
        t.append("    Edit superqode.yaml to add or enable roles as needed\n", style=THEME["dim"])
        t.append("\n", style="")
        log.write(t)

    def _has_superqode_config(self) -> bool:
        """Return True when a superqode.yaml configuration exists."""
        from superqode.config.loader import find_config_file

        return bool(find_config_file() or (Path.cwd() / "superqode.yaml").exists())

    def _set_approval_mode(self, args: str, log: ConversationLog):
        """Set the approval mode for agent actions."""
        mode = args.strip().lower()

        if not mode:
            # Show current mode
            t = Text()
            t.append("\n  🔐 ", style=f"bold {THEME['purple']}")
            t.append("Approval Mode\n\n", style=f"bold {THEME['purple']}")

            t.append("  Controls how SuperQode handles tool calls\n", style=THEME["muted"])
            t.append("  (read, write, edit, bash, search, etc.)\n\n", style=THEME["muted"])

            modes = [
                ("auto", "🟢", THEME["success"], "Allow all tools without prompts"),
                ("ask", "🟡", THEME["warning"], "Prompt for external/outside-project tools"),
                ("deny", "🔴", THEME["error"], "Block ALL tools (read-only)"),
            ]

            for m, icon, color, desc in modes:
                current = " ◀ current" if self.approval_mode == m else ""
                t.append(f"    {icon} ", style=color)
                t.append(f":mode {m:<6}", style=f"bold {color}")
                t.append(f" — {desc}", style=THEME["muted"])
                if current:
                    t.append(current, style=f"bold {color}")
                t.append("\n", style="")

            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(
                "ASK mode prompts for external tools & files outside project.\n", style=THEME["dim"]
            )
            t.append("     Tools within project directory are auto-allowed.\n", style=THEME["dim"])
            t.append("     DENY blocks ALL tools. AUTO allows everything.\n", style=THEME["dim"])

            self._show_command_output(log, t)
            return

        if mode in ("auto", "ask", "deny"):
            self.approval_mode = mode
            self._sync_approval_mode()

            icons = {"auto": "🟢", "ask": "🟡", "deny": "🔴"}
            colors = {"auto": THEME["success"], "ask": THEME["warning"], "deny": THEME["error"]}
            descs = {
                "auto": "All tools allowed without prompts",
                "ask": "Prompts for external tools & files outside project",
                "deny": "ALL tool calls will be blocked (read-only)",
            }

            log.add_success(f"{icons[mode]} Approval mode set to {mode.upper()}")
            log.add_system(descs[mode])
        else:
            log.add_error(f"Invalid mode: {mode}")
            log.add_system("Valid modes: auto, ask, deny")

    def _handle_log_verbosity(self, args: str, log: ConversationLog):
        """Handle :log command to control log verbosity."""
        from superqode.logging import LogVerbosity

        level = args.strip().lower()

        if not level:
            # Show current verbosity settings
            t = Text()
            t.append("\n  📋 ", style=f"bold {THEME['purple']}")
            t.append("Log Verbosity Settings\n\n", style=f"bold {THEME['purple']}")

            t.append("  Controls how much detail is shown in agent logs\n\n", style=THEME["muted"])

            # Get current verbosity
            current_verbosity = "normal"
            if hasattr(self, "_current_tui_logger") and self._current_tui_logger:
                current_verbosity = self._current_tui_logger.logger.config.verbosity.value

            levels = [
                ("minimal", "◇", THEME["muted"], "Status only - no content"),
                ("normal", "◆", THEME["cyan"], "Summarized tool outputs"),
                ("verbose", "◈", THEME["purple"], "Full outputs with syntax highlighting"),
            ]

            for lvl, icon, color, desc in levels:
                current = " ◀ current" if current_verbosity == lvl else ""
                t.append(f"    {icon} ", style=color)
                t.append(f":log {lvl:<10}", style=f"bold {color}")
                t.append(f" — {desc}", style=THEME["muted"])
                if current:
                    t.append(current, style=f"bold {color}")
                t.append("\n", style="")

            t.append("\n  💡 ", style=THEME["muted"])
            t.append("Ctrl+T toggles thinking logs on/off\n", style=THEME["dim"])
            t.append(f"     Thinking logs: ", style=THEME["dim"])
            thinking_status = "ON" if self.show_thinking_logs else "OFF"
            thinking_color = THEME["success"] if self.show_thinking_logs else THEME["muted"]
            t.append(f"{thinking_status}\n", style=f"bold {thinking_color}")

            self._show_command_output(log, t)
            return

        # Map level names to LogVerbosity
        verbosity_map = {
            "minimal": LogVerbosity.MINIMAL,
            "min": LogVerbosity.MINIMAL,
            "normal": LogVerbosity.NORMAL,
            "default": LogVerbosity.NORMAL,
            "verbose": LogVerbosity.VERBOSE,
            "full": LogVerbosity.VERBOSE,
            "debug": LogVerbosity.VERBOSE,
        }

        if level in verbosity_map:
            new_verbosity = verbosity_map[level]

            # Update the current TUI logger if one exists
            if hasattr(self, "_current_tui_logger") and self._current_tui_logger:
                self._current_tui_logger.set_verbosity(new_verbosity)

            # Update verbose agent logs flag
            self.show_verbose_agent_logs = new_verbosity == LogVerbosity.VERBOSE

            icons = {"minimal": "◇", "normal": "◆", "verbose": "◈"}
            colors = {
                "minimal": THEME["muted"],
                "normal": THEME["cyan"],
                "verbose": THEME["purple"],
            }
            descs = {
                "minimal": "Showing status only - no output content",
                "normal": "Showing summarized outputs (up to 200 chars)",
                "verbose": "Showing full outputs + raw agent session logs",
            }

            # Normalize level name
            display_level = (
                "minimal"
                if level in ("min",)
                else "verbose"
                if level in ("full", "debug")
                else level
            )

            log.add_success(
                f"{icons.get(display_level, '◆')} Log verbosity: {display_level.upper()}"
            )
            log.add_system(descs.get(display_level, ""))
        else:
            log.add_error(f"Invalid verbosity: {level}")
            log.add_system("Valid levels: minimal, normal, verbose")

    # ========================================================================
    # Model Query Interception
    # ========================================================================

    def _is_model_query(self, text: str) -> bool:
        """Check if the user is asking about which model/AI is being used."""
        text_lower = text.lower().strip()

        # Common patterns for asking about the model
        model_query_patterns = [
            "what model",
            "which model",
            "what ai",
            "which ai",
            "who are you",
            "what are you",
            "which llm",
            "what llm",
            "model are you",
            "model you are",
            "ai are you",
            "ai you are",
            "what's your model",
            "what is your model",
            "your model name",
            "model name",
            "are you gpt",
            "are you claude",
            "are you gemini",
            "are you llama",
            "are you glm",
            "are you qwen",
            "are you deepseek",
        ]

        for pattern in model_query_patterns:
            if pattern in text_lower:
                return True

        return False

    def _answer_model_query(self, log: ConversationLog):
        """Answer the user's question about which model is being used."""
        t = Text()
        t.append("\n")

        if self.current_model:
            # We have model info
            t.append("  🤖 ", style=f"bold {THEME['purple']}")
            t.append("Current AI Model:\n\n", style=f"bold {THEME['text']}")

            t.append("  📊 Model: ", style=THEME["muted"])
            t.append(f"{self.current_model}\n", style=f"bold {THEME['cyan']}")

            if self.current_provider:
                t.append("  ☁️  Provider: ", style=THEME["muted"])
                t.append(f"{self.current_provider}\n", style=f"bold {THEME['success']}")

            if self.current_agent:
                t.append("  🔧 Agent: ", style=THEME["muted"])
                t.append(f"{self.current_agent}\n", style=f"bold {THEME['orange']}")

            # Execution mode
            badge = self.query_one("#mode-badge", ModeBadge)
            if badge.execution_mode:
                mode_labels = {
                    "acp": "ACP (Agent Control Protocol)",
                    "byok": "BYOK (Bring Your Own Key)",
                }
                t.append("  ⚡ Mode: ", style=THEME["muted"])
                t.append(
                    f"{mode_labels.get(badge.execution_mode, badge.execution_mode)}\n",
                    style=THEME["text"],
                )

        elif hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
            # Pure mode
            t.append("  🧪 ", style=f"bold {THEME['pink']}")
            t.append("Session Active:\n\n", style=f"bold {THEME['text']}")

            t.append("  📊 Model: ", style=THEME["muted"])
            t.append(f"{self._pure_mode.session.model}\n", style=f"bold {THEME['cyan']}")

            t.append("  ☁️  Provider: ", style=THEME["muted"])
            t.append(f"{self._pure_mode.session.provider}\n", style=f"bold {THEME['success']}")

        else:
            # Not connected
            t.append("  ℹ️  ", style=f"bold {THEME['muted']}")
            t.append("No AI model connected yet.\n", style=THEME["text"])
            t.append("  Use ", style=THEME["muted"])
            t.append(":connect acp <name>", style=f"bold {THEME['cyan']}")
            t.append(" to connect to an agent.\n", style=THEME["muted"])

        t.append("\n")
        log.write(t)

    # ========================================================================
    # Message Handling
    # ========================================================================

    def _handle_message(self, text: str, log: ConversationLog):
        session = get_session()
        mode = get_mode()

        # Skip permission input handling when using modal dialogs
        # (permissions are handled directly in the modal)

        # Check for BYOK provider/model selection
        if hasattr(self, "_awaiting_byok_provider") and self._awaiting_byok_provider:
            if self._handle_byok_provider_selection(text, log):
                return

        if hasattr(self, "_awaiting_byok_model") and self._awaiting_byok_model:
            # Check for Enter key (empty string or special handling)
            if text.strip() == "" or text.strip().lower() == "enter":
                # Use highlighted model
                self.action_select_highlighted_model()
                return
            if self._handle_byok_model_selection(text, log):
                return

        # Parse @file references and include file content
        file_context = ""
        if "@" in text:
            try:
                from superqode.widgets.file_reference import (
                    expand_file_references,
                    format_file_context,
                    count_file_tokens,
                )

                clean_text, files = expand_file_references(text, Path.cwd())
                if files:
                    file_context = format_file_context(files)
                    token_estimate = count_file_tokens(files)
                    # Show info about included files
                    file_list = ", ".join(f"@{p}" for p, _ in files)
                    log.add_info(
                        f"Including {len(files)} file(s) (~{token_estimate:,} tokens): {file_list}"
                    )
                    # Replace text with clean version
                    text = clean_text
            except Exception:
                pass

        # Enable auto-scroll when user sends a message so they see agent's work
        log.auto_scroll = True

        log.add_user(text)

        # Store file context for the message
        self._current_file_context = file_context

        # Check if in provider mode
        if hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
            self._send_to_pure_mode(text, log)
        elif session.is_connected_to_agent():
            agent = session.connected_agent
            # Get the actual agent name from the connected agent, not from old session state
            name = agent.get("short_name", agent.get("name", "agent")) if agent else "agent"
            # Use standard subprocess approach (ACP requires separate adapter)
            self._send_to_agent(text, name, log)
        elif mode != "home" and "." in mode:
            m, r = mode.split(".", 1)
            self._send_to_role(text, m, r, log)
        else:
            log.add_info("Not connected. Use :connect acp <name> or :qe <role> after :init")

    @work(exclusive=True)
    async def _send_to_pure_mode(self, text: str, log: ConversationLog):
        """Send message to provider session with streaming output."""
        from time import monotonic
        import traceback

        # Prepend file context if available (from @file references)
        file_context = getattr(self, "_current_file_context", "")
        if file_context:
            text = f"{file_context}\n\n{text}"
            self._current_file_context = ""  # Clear after use

        # Inject persona if we're in a role context (like ACP does)
        # This provides double reinforcement: system prompt + message-level persona
        if (
            hasattr(self, "current_mode")
            and hasattr(self, "current_role")
            and self.current_mode
            and self.current_role
        ):
            try:
                from superqode.config import load_config, resolve_role
                from superqode.agents.persona import PersonaInjector
                from superqode.agents.messaging import wrap_message_with_persona

                # Use stored resolved role if available, otherwise resolve it
                resolved = getattr(self, "_current_resolved_role", None)
                if not resolved:
                    resolved = resolve_role(self.current_mode, self.current_role, load_config())

                if resolved:
                    # Build persona context and wrap message (same as ACP)
                    injector = PersonaInjector()
                    persona_context = injector.build_persona(
                        self.current_mode, self.current_role, resolved
                    )
                    text = wrap_message_with_persona(text, persona_context)
            except Exception as e:
                # If persona injection fails, continue without it (don't break the flow)
                pass

        # Check if connected
        if not hasattr(self, "_pure_mode"):
            log.add_error("Not connected to a model. Use :connect byok to select a provider/model.")
            log.add_system("Example: :connect byok ollama/llama3.2")
            return

        if not self._pure_mode.session.connected:
            log.add_error("Connection not established. Please reconnect using :connect byok")
            log.add_system("Example: :connect byok ollama/llama3.2")
            return

        if not self._pure_mode._agent:
            log.add_error("Agent not initialized. Please reconnect using :connect byok")
            log.add_system("Example: :connect byok ollama/llama3.2")
            return

        provider = self._pure_mode.session.provider
        model = self._pure_mode.session.model

        # Set up callbacks for BYOK/Local modes
        # Tool calls are ALWAYS visible (the agent's actual work)
        # Thinking logs are toggleable with Ctrl+T
        from superqode.providers.registry import PROVIDERS, ProviderCategory

        provider_def = PROVIDERS.get(provider)
        is_local = provider_def and provider_def.category == ProviderCategory.LOCAL

        def _safe_call(func, *args):
            """Call function safely - handles threading correctly."""
            try:
                self.call_from_thread(func, *args)
            except RuntimeError as e:
                if "different thread" in str(e).lower():
                    func(*args)
                else:
                    raise

        def on_tool_call(name: str, args: dict):
            """Handle tool call - ALWAYS visible."""
            file_path = args.get("path", args.get("file_path", args.get("filePath", "")))
            command = args.get("command", "")
            _safe_call(log.add_tool_call, name, "running", file_path, command, "")

        def on_tool_result(name: str, result):
            """Handle tool result - ALWAYS visible with JSON parsing."""
            from superqode.tools.base import ToolResult

            if isinstance(result, ToolResult):
                status = "success" if result.success else "error"
                output = result.output if result.output else result.error
                output_str = str(output) if output else ""

                # Try to parse and display JSON nicely
                if status == "success" and output_str:
                    formatted = self._format_tool_output(name, output_str, log)
                    if formatted:
                        return

                # Fallback - show full output, no truncation
                _safe_call(log.add_tool_call, name, status, "", "", output_str)
            else:
                output_str = str(result) if result else ""

                # Try JSON parsing first
                if output_str:
                    formatted = self._format_tool_output(name, output_str, log)
                    if formatted:
                        return

                # Show full output, no truncation
                _safe_call(log.add_tool_call, name, "success", "", "", output_str)

        async def on_thinking_async(text: str):
            """Handle thinking - toggleable with Ctrl+T."""
            if text and text.strip():
                # Use log.add_thinking for cleaner, categorized output with varied emojis
                # This matches ACP style and avoids the "brain emoji" overload
                _safe_call(log.add_thinking, text, "general")

        # Set callbacks on pure_mode (for both local and cloud providers)
        self._pure_mode.on_tool_call = on_tool_call
        self._pure_mode.on_tool_result = on_tool_result
        self._pure_mode.on_thinking = on_thinking_async

        # Ensure callbacks are set on the agent
        if self._pure_mode._agent:
            self._pure_mode._agent.on_tool_call = on_tool_call
            self._pure_mode._agent.on_tool_result = on_tool_result
            self._pure_mode._agent.on_thinking = on_thinking_async

        # Start thinking animation - shows animated bar and thinking indicator
        self._start_thinking(f"🤖 Processing with {provider}/{model}...")

        try:
            start_time = monotonic()
            full_response = ""
            chunk_count = 0
            response_started = False

            # Stop thinking animation (spinning bar), start streaming animation (flowing line)
            self._stop_thinking()
            self._start_stream_animation(log)

            # Use enhanced agent session header (always visible)
            _safe_call(
                log.start_agent_session,
                f"BYOK {provider}",
                model,
                "byok" if not is_local else "local",
                self.approval_mode,
            )

            # Stream the response
            # CRITICAL: Accumulate ALL chunks including final response after tool calls
            try:
                # Accumulate chunks to avoid showing each tiny piece as separate thinking line
                accumulated_chunk = ""
                last_display_time = time.time()

                async for chunk in self._pure_mode.run_streaming(text):
                    chunk_count += 1

                    # Process chunk
                    if chunk is not None:
                        chunk_str = str(chunk) if not isinstance(chunk, str) else chunk

                        # Always accumulate for final display
                        full_response += chunk_str

                        # Accumulate chunks and display in batches to avoid weird chunking
                        if chunk_str.strip():
                            accumulated_chunk += chunk_str
                            response_started = True

                            # Display accumulated chunk every 100ms or when we hit a newline
                            # Response chunks go to log.add_response_chunk (not add_assistant)
                            current_time = time.time()
                            if (
                                "\n" in chunk_str
                                or current_time - last_display_time > 0.1
                                or len(accumulated_chunk) > 100
                            ):
                                _safe_call(log.add_response_chunk, accumulated_chunk)
                                accumulated_chunk = ""
                                last_display_time = current_time

            except StopAsyncIteration:
                # Normal end of stream - display any remaining accumulated chunks
                if accumulated_chunk:
                    _safe_call(log.add_response_chunk, accumulated_chunk)

                # Stop streaming animation
                self._stop_stream_animation()

                # End agent session with summary
                # Extract stats if available from pure_mode
                stats = getattr(self._pure_mode, "_last_stats", {})
                _safe_call(
                    log.end_agent_session,
                    True,
                    full_response,
                    stats.get("prompt_tokens", 0),
                    stats.get("completion_tokens", 0),
                    stats.get("thinking_tokens", 0),
                    stats.get("total_cost", 0.0),
                )
                pass
            except Exception as stream_error:
                # Error during streaming
                error_msg = str(stream_error)
                error_type = type(stream_error).__name__

                # Stop animation and show error
                if is_local:
                    self._stop_thinking()
                self._stop_stream_animation()
                log.add_error(f"❌ Error ({error_type}): {error_msg}")

                # Show detailed error info
                import traceback

                full_traceback = traceback.format_exc()
                log.add_info(f"Full error:\n{full_traceback}")

                # Provider-specific troubleshooting
                if "ollama" in provider.lower():
                    log.add_info("💡 Ollama Troubleshooting:")
                    log.add_info("   1. Check Ollama is running: ollama serve")
                    log.add_info(f"   2. Verify model exists: ollama list | grep {model}")
                    log.add_info(f"   3. Pull model if missing: ollama pull {model}")
                    import os

                    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                    log.add_info(f"   4. Current OLLAMA_HOST: {ollama_host}")
                elif "mlx" in provider.lower():
                    # Check for specific MLX error types
                    if (
                        "broadcast_shapes" in error_msg.lower()
                        or "cannot be broadcast" in error_msg.lower()
                    ):
                        log.add_error("🚨 MLX KV Cache Conflict Detected!")
                        log.add_info("   MLX servers can only handle ONE request at a time.")
                        log.add_info("   Multiple concurrent requests cause memory conflicts.")
                        log.add_info("")
                        log.add_info("   To fix:")
                        log.add_info("   1. Wait for any running requests to complete")
                        log.add_info("   2. Check server status: superqode providers mlx list")
                        log.add_info(
                            f"   3. Restart server: superqode providers mlx server --model {model}"
                        )
                        log.add_info("   4. Try again with only one active session")
                        log.add_info("")
                        log.add_info(
                            "   💡 Tip: Run separate servers on different ports for concurrent use"
                        )
                    else:
                        log.add_info("💡 MLX Troubleshooting:")
                        log.add_info("   1. Check if server crashed: superqode providers mlx list")
                        log.add_info(
                            f"   2. Restart server: superqode providers mlx server --model {model}"
                        )
                        log.add_info(
                            "   3. Verify connection: curl http://localhost:8080/v1/models"
                        )
                        log.add_info("")
                        log.add_info("   ⚠️  MLX servers handle only ONE request at a time")
                        log.add_info("   • Keep server terminal open while using")
                        log.add_info("   • Start separate servers for concurrent model use")

                if not full_response:
                    full_response = f"[Error: {error_type}] {error_msg}"

            # Stop animation
            self._stop_stream_animation()

            elapsed = monotonic() - start_time

            # Clean up the response - remove any error markers that might have been added
            cleaned_response = full_response.strip()

            if cleaned_response:
                # Check if response contains an error message
                if "[Error:" in cleaned_response or cleaned_response.startswith("Error:"):
                    log.add_error(cleaned_response)
                else:
                    # Display the response using ACP-style formatting for consistency
                    response_text = cleaned_response

                    # Get stats for display
                    stats = self._pure_mode.get_status()["stats"]
                    tool_count = stats.get("total_tool_calls", 0)

                    # Compute file diffs using git (BYOK doesn't track files during execution,
                    # but we can detect changes via git diff after the fact)
                    files_modified = []  # We'll detect via git
                    try:
                        # Get git changes to detect modified files
                        root_path = Path(os.getcwd())
                        git_changes = get_git_changes(root_path)
                        files_modified = [
                            change.path for change in git_changes if change.status in ("M", "A")
                        ]
                    except Exception:
                        pass

                    # Compute file diffs for detected files
                    file_diffs = self._compute_file_diffs(files_modified) if files_modified else {}

                    # Use ACP-style outcome display for both ACP and BYOK
                    self._show_final_outcome(
                        response_text,
                        f"BYOK {provider}/{model}",
                        {
                            "tool_count": tool_count,
                            "duration": elapsed,
                            "files_modified": files_modified,
                            "files_read": [],  # BYOK doesn't track file reads during execution
                            "file_diffs": file_diffs,  # NEW: Store diff data
                        },
                        log,
                    )

                    # Track usage
                    self._track_byok_usage(text, response_text, tool_count)
            elif chunk_count > 0:
                # Got chunks but no content - might be tool calls only
                log.add_warning(
                    f"⚠️ Received {chunk_count} chunks but no text content after stripping."
                )
                log.add_info(f"🔍 Debug: Raw response (before strip): {repr(full_response[:500])}")
                log.add_info("Model may have returned tool calls only or whitespace-only response.")
                # Check if there were tool calls
                stats = self._pure_mode.get_status()["stats"]
                tool_count = stats.get("total_tool_calls", 0)
                if tool_count > 0:
                    log.add_info(f"Note: {tool_count} tool calls were executed.")

                    # Compute file diffs even when no text response
                    files_modified = []
                    try:
                        root_path = Path(os.getcwd())
                        git_changes = get_git_changes(root_path)
                        files_modified = [
                            change.path for change in git_changes if change.status in ("M", "A")
                        ]
                    except Exception:
                        pass

                    file_diffs = self._compute_file_diffs(files_modified) if files_modified else {}

                    # Show completion summary with file changes
                    self._show_completion_summary(
                        f"BYOK {provider}/{model}",
                        {
                            "tool_count": tool_count,
                            "duration": elapsed,
                            "files_modified": files_modified,
                            "files_read": [],
                            "file_diffs": file_diffs,
                        },
                        log,
                    )
                else:
                    log.add_warning(
                        "⚠️ No tool calls and no text response. The model may not be responding correctly."
                    )
            else:
                log.add_error("❌ No response received from model.")
                log.add_info(f"🔍 Debug: provider={provider}, model={model}, chunks={chunk_count}")
                log.add_info("💡 Check if the model is running and accessible.")
                if provider == "ollama":
                    log.add_info("   Try: ollama list (to see available models)")
                    log.add_info("   Try: ollama serve (to start the server)")

        except Exception as e:
            self._stop_thinking()
            error_msg = str(e)
            error_trace = traceback.format_exc()

            # Show user-friendly error
            log.add_error(f"Error communicating with {provider}/{model}: {error_msg}")

            # For local providers, add helpful hints
            if provider in ("ollama", "lmstudio", "vllm", "sglang", "mlx", "tgi"):
                # Show experimental warning for vLLM and SGLang
                if provider in ("vllm", "sglang"):
                    log.add_warning(
                        f"⚠️  {provider.upper()} support is EXPERIMENTAL - features may be unstable"
                    )
                log.add_info(f"💡 Make sure {provider} is running:")
                if provider == "ollama":
                    log.add_info("   Run: ollama serve")
                elif provider == "lmstudio":
                    log.add_info("   Open LM Studio and start the local server")
                elif provider == "vllm":
                    log.add_info(
                        "   Start vLLM server: python -m vllm.entrypoints.openai.api_server --model <model>"
                    )
                elif provider == "sglang":
                    log.add_info(
                        "   Start SGLang server: python -m sglang.launch_server --model-path <model> --port 30000"
                    )

            # Log full traceback for debugging (only in verbose mode)
            if hasattr(self, "show_thinking_logs") and self.show_thinking_logs:
                log.add_info(f"Debug: {error_trace}")

    @work(exclusive=True, thread=True)
    def _send_to_agent(self, text: str, name: str, log: ConversationLog):
        """Send message to agent with real-time streaming output."""
        session = get_session()
        agent = session.connected_agent

        # Reset cancellation flag
        self._cancel_requested = False

        self.call_from_thread(self._start_thinking, f"🤖 Connecting to {name}...")

        short_name = agent.get("short_name", "") if agent else ""

        if short_name == "opencode":
            # Check if model is selected
            if not self.current_model:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(
                    log.add_error, "No model selected. Press 1-5 to select a model first."
                )
                return

            # Use unified agent runner with opencode
            model_name = self.current_model
            if model_name.startswith("opencode/"):
                model_name = model_name[9:]  # Remove "opencode/" prefix

            self._run_agent_unified(
                message=text,
                agent_type="opencode",
                model=model_name,
                display_name=name,
                log=log,
                persona_context=None,
            )
        elif short_name == "gemini":
            # Use unified agent runner with gemini
            model_name = self.current_model if self.current_model else "auto"
            if model_name.startswith("gemini/"):
                model_name = model_name[7:]  # Remove "gemini/" prefix

            self._run_agent_unified(
                message=text,
                agent_type="gemini",
                model=model_name,
                display_name=name,
                log=log,
                persona_context=None,
            )
        elif short_name == "claude":
            # Check if model is selected
            if not self.current_model:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(
                    log.add_error, "No model selected. Press 1-4 to select a model first."
                )
                return

            # Use unified agent runner with claude
            model_name = self.current_model
            if model_name.startswith("claude/"):
                model_name = model_name[7:]  # Remove "claude/" prefix

            self._run_agent_unified(
                message=text,
                agent_type="claude",
                model=model_name,
                display_name=name,
                log=log,
                persona_context=None,
            )
        elif short_name == "codex":
            # Check if model is selected
            if not self.current_model:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(
                    log.add_error, "No model selected. Press 1-4 to select a model first."
                )
                return

            # Use unified agent runner with codex
            model_name = self.current_model
            if model_name.startswith("codex/"):
                model_name = model_name[6:]  # Remove "codex/" prefix

            self._run_agent_unified(
                message=text,
                agent_type="codex",
                model=model_name,
                display_name=name,
                log=log,
                persona_context=None,
            )
        else:
            # Handle all other ACP-compatible agents generically
            # This covers: junie, goose, kimi, stakpak, vtcode, auggie,
            # code-assistant, cagent, fast-agent, llmling-agent
            acp_agents = {
                "junie",
                "goose",
                "kimi",
                "stakpak",
                "vtcode",
                "auggie",
                "code-assistant",
                "cagent",
                "fast-agent",
                "llmling-agent",
            }
            if short_name in acp_agents:
                model_name = self.current_model if self.current_model else "auto"
                # Remove any prefix like "junie/" if present
                if "/" in model_name:
                    model_name = model_name.split("/", 1)[1]

                self._run_agent_unified(
                    message=text,
                    agent_type=short_name,
                    model=model_name,
                    display_name=name,
                    log=log,
                    persona_context=None,
                )
            else:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(log.add_info, f"🚧 {name} integration coming soon!")

    def _run_agent_unified(
        self,
        message: str,
        agent_type: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ):
        """
        Unified agent runner - supports multiple ACP-compatible agents via JSON streaming.

        Args:
            message: The message/prompt to send
            agent_type: Agent type ("opencode", "gemini", "claude", "codex", "openhands")
            model: Model name
            display_name: Display name for UI
            log: ConversationLog for output
            persona_context: Optional persona context for role-based execution
        """
        import subprocess
        import json
        from time import monotonic

        # Prepend file context if available (from @file references)
        file_context = getattr(self, "_current_file_context", "")
        if file_context:
            message = f"{file_context}\n\n{message}"
            self._current_file_context = ""  # Clear after use

        # Route ACP-compatible agents to the JSON-RPC ACP client
        # All 14 official ACP agents support the Agent Client Protocol
        acp_agents = (
            "opencode",
            "claude",
            "codex",
            "gemini",
            "junie",
            "goose",
            "kimi",
            "stakpak",
            "vtcode",
            "auggie",
            "code-assistant",
            "cagent",
            "fast-agent",
            "llmling-agent",
        )
        if agent_type in acp_agents:
            self._run_acp_jsonrpc_client(
                message, agent_type, model, display_name, log, persona_context
            )
            return

        try:
            start_time = monotonic()

            # Build command based on agent type
            if agent_type == "gemini":
                cmd = ["gemini", "--output-format", "stream-json"]

                # Add approval mode
                if self.approval_mode == "auto":
                    cmd.append("--yolo")
                elif self.approval_mode == "deny":
                    # Gemini doesn't have deny mode, use default
                    pass

                # Add model if specified
                if model and model != "auto":
                    cmd.extend(["-m", model])

                # Add the message
                cmd.append(message)

                model_display = f"gemini/{model}" if model else "gemini/auto"
            else:  # opencode (default)
                cmd = ["opencode", "run", "--format", "json"]

                # Add session continuity
                if not self._is_first_message:
                    cmd.append("--continue")

                # Add model
                if model:
                    cmd.extend(["-m", f"opencode/{model}"])

                # Add the message
                cmd.append(message)

                model_display = f"opencode/{model}" if model else "opencode/default"

            # Show info with approval mode
            mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
                self.approval_mode, "🟡 ASK"
            )
            session_type = "new session" if self._is_first_message else "continuing session"
            self.call_from_thread(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self.call_from_thread(
                    log.add_info, f"🎭 Persona active: {persona_context.role_name}"
                )

            # Show mode-specific info on first message
            if self._is_first_message:
                if self.approval_mode == "deny":
                    self.call_from_thread(
                        log.add_info, "🔴 DENY mode: ALL tool calls will be blocked"
                    )
                elif self.approval_mode == "ask":
                    self.call_from_thread(
                        log.add_info, "ASK mode: prompts for external tools (y/n/a)"
                    )

            # Build environment
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
            }

            # Start process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=os.getcwd(),
                text=True,
                bufsize=1,
                env=env,
            )

            # Store process reference for cancellation
            self._agent_process = process

            # Stop thinking, start streaming animation
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._start_stream_animation, log)

            # Show header
            self.call_from_thread(
                self._show_agent_header_with_model, display_name, model_display, log
            )

            # Collect output
            text_parts = []
            tool_actions = []
            files_modified = []
            files_read = []

            # Read output line by line
            while True:
                if self._cancel_requested:
                    process.terminate()
                    self.call_from_thread(log.add_info, "🛑 Agent operation cancelled")
                    break

                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    line = line.rstrip("\n\r")
                    if line:
                        # Parse JSON events
                        try:
                            event = json.loads(line)

                            # Handle based on agent type
                            if agent_type == "gemini":
                                self._handle_gemini_event(
                                    event,
                                    text_parts,
                                    tool_actions,
                                    files_modified,
                                    files_read,
                                    log,
                                    process,
                                )
                            else:
                                self._handle_opencode_event(
                                    event,
                                    text_parts,
                                    tool_actions,
                                    files_modified,
                                    files_read,
                                    log,
                                    process,
                                )

                        except json.JSONDecodeError:
                            # Not JSON - show as thinking line with emoji
                            if line.strip() and not line.startswith("Loaded cached"):
                                # Add emoji if line doesn't already have one
                                if not any(
                                    ord(c) > 127 for c in line[:2]
                                ):  # Check if first 2 chars have emoji
                                    emoji = "📋"  # Default console output emoji
                                    self.call_from_thread(
                                        self._show_thinking_line, f"{emoji} {line}", log
                                    )
                                else:
                                    self.call_from_thread(self._show_thinking_line, line, log)

            # Cleanup
            self._agent_process = None
            self.call_from_thread(self._stop_stream_animation)

            process.wait()
            duration = monotonic() - start_time
            self._is_first_message = False

            # Compute file diffs for modified files
            file_diffs = self._compute_file_diffs(files_modified)

            # Build summary
            action_summary = {
                "tool_count": len(tool_actions),
                "files_modified": files_modified,
                "files_read": files_read,
                "duration": duration,
                "file_diffs": file_diffs,  # NEW: Store diff data
            }

            # Show final response
            if text_parts:
                response_text = "".join(text_parts)
                if response_text.strip():
                    self.call_from_thread(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self.call_from_thread(
                        self._show_completion_summary, display_name, action_summary, log
                    )
            elif not self._cancel_requested:
                self.call_from_thread(
                    self._show_completion_summary, display_name, action_summary, log
                )

        except FileNotFoundError:
            self._agent_process = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            agent_name = "gemini" if agent_type == "gemini" else "opencode"
            self.call_from_thread(
                log.add_error, f"❌ {agent_name} CLI not found. Install it first."
            )
        except Exception as e:
            self._agent_process = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(log.add_error, f"❌ Error: {str(e)}")

    def _use_jsonrpc_acp_client(self) -> bool:
        """Return True when the custom JSON-RPC ACP client is enabled."""
        import os

        mode = os.environ.get("SUPERQODE_ACP_CLIENT", "").strip().lower()
        return mode in {"custom", "jsonrpc", "rpc"}

    def _run_acp_jsonrpc_client(
        self,
        message: str,
        agent_type: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ) -> None:
        """Run an ACP agent using the custom JSON-RPC client (opt-in)."""
        import asyncio
        import os
        import time
        from pathlib import Path

        from superqode.acp.client import ACPClient

        # Prepend file context if available (from @file references)
        file_context = getattr(self, "_current_file_context", "")
        if file_context:
            message = f"{file_context}\n\n{message}"
            self._current_file_context = ""

        # Choose command and model display based on agent type
        # All 14 official ACP agents are supported
        if agent_type == "gemini":
            command = "gemini --experimental-acp"
            model_display = f"gemini/{model}" if model and model != "auto" else "gemini/auto"
            if "GEMINI_API_KEY" not in os.environ and "GOOGLE_API_KEY" not in os.environ:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(
                    log.add_error, "❌ GEMINI_API_KEY or GOOGLE_API_KEY not set. Export it first:"
                )
                self.call_from_thread(log.add_info, "  export GEMINI_API_KEY=your_api_key")
                self.call_from_thread(log.add_info, "  or export GOOGLE_API_KEY=your_api_key")
                return
        elif agent_type == "claude":
            command = "claude --acp"
            model_display = f"claude/{model}" if model else "claude/auto"
            if "ANTHROPIC_API_KEY" not in os.environ:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(
                    log.add_error, "❌ ANTHROPIC_API_KEY not set. Export it first:"
                )
                self.call_from_thread(log.add_info, "  export ANTHROPIC_API_KEY=sk-ant-...")
                return
        elif agent_type == "codex":
            command = "codex --acp"
            model_display = f"codex/{model}" if model else "codex/auto"
            if "OPENAI_API_KEY" not in os.environ and "CODEX_API_KEY" not in os.environ:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(
                    log.add_error, "❌ OPENAI_API_KEY or CODEX_API_KEY not set. Export one first:"
                )
                self.call_from_thread(log.add_info, "  export OPENAI_API_KEY=sk-...")
                self.call_from_thread(log.add_info, "  or export CODEX_API_KEY=sk-...")
                return
        elif agent_type == "junie":
            command = "junie --acp"
            model_display = f"junie/{model}" if model else "junie/auto"
        elif agent_type == "goose":
            command = "goose mcp"
            model_display = f"goose/{model}" if model else "goose/auto"
        elif agent_type == "kimi":
            command = "kimi --acp"
            model_display = f"kimi/{model}" if model else "kimi/auto"
            if "MOONSHOT_API_KEY" not in os.environ and "KIMI_API_KEY" not in os.environ:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(
                    log.add_error, "❌ MOONSHOT_API_KEY or KIMI_API_KEY not set. Export it first:"
                )
                self.call_from_thread(log.add_info, "  export MOONSHOT_API_KEY=your_api_key")
                return
        elif agent_type == "opencode":
            command = "opencode acp"
            model_display = f"opencode/{model}" if model else "opencode/auto"
            # OpenCode handles its own API keys via its config
        elif agent_type == "stakpak":
            command = "stakpak --acp"
            model_display = f"stakpak/{model}" if model else "stakpak/auto"
        elif agent_type == "vtcode":
            command = "vtcode --acp"
            model_display = f"vtcode/{model}" if model else "vtcode/auto"
        elif agent_type == "auggie":
            command = "auggie --acp"
            model_display = f"auggie/{model}" if model else "auggie/auto"
            if "AUGMENT_API_KEY" not in os.environ:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(log.add_error, "❌ AUGMENT_API_KEY not set. Export it first:")
                self.call_from_thread(log.add_info, "  export AUGMENT_API_KEY=your_api_key")
                return
        elif agent_type == "code-assistant":
            command = "code-assistant --acp"
            model_display = f"code-assistant/{model}" if model else "code-assistant/auto"
        elif agent_type == "cagent":
            command = "cagent --acp"
            model_display = f"cagent/{model}" if model else "cagent/auto"
        elif agent_type == "fast-agent":
            command = "fast-agent-acp -x"
            model_display = f"fast-agent/{model}" if model else "fast-agent/auto"
        elif agent_type == "llmling-agent":
            command = "llmling-agent --acp"
            model_display = f"llmling-agent/{model}" if model else "llmling-agent/auto"
        else:
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(log.add_error, f"Unsupported ACP agent type: {agent_type}")
            return

        mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
            self.approval_mode, "🟡 ASK"
        )
        session_type = "new session"
        self.call_from_thread(
            log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
        )

        if persona_context and persona_context.is_valid:
            self.call_from_thread(log.add_info, f"🎭 Persona active: {persona_context.role_name}")

        # Stop thinking, start streaming animation
        self.call_from_thread(self._stop_thinking)
        self.call_from_thread(self._start_stream_animation, log)

        # Use enhanced agent session header (always visible)
        self.call_from_thread(
            log.start_agent_session,
            display_name,
            model_display,
            "acp",
            self.approval_mode,
        )

        text_parts: list[str] = []
        tool_actions: list[dict] = []
        files_modified: list[str] = []
        files_read: list[str] = []

        # Buffer for accumulating thinking chunks
        thinking_buffer: list[str] = []
        last_thinking_time = [0.0]  # Use list to allow mutation in nested function

        def _flush_thinking_buffer():
            """Flush accumulated thinking chunks to display."""
            if thinking_buffer:
                full_text = "".join(thinking_buffer).strip()
                if full_text:
                    self.call_from_thread(self._show_thinking_line, f"💭 {full_text}", log)
                thinking_buffer.clear()

        def _pick_option(options: list[dict], preferred_kinds: list[str]) -> str:
            for kind in preferred_kinds:
                match = next((o for o in options if o.get("kind") == kind), None)
                if match:
                    return match.get("optionId", "")
            if options:
                return options[0].get("optionId", "")
            return ""

        async def on_message(text: str) -> None:
            """Handle agent message chunks - stream to response area."""
            if text:
                # Flush any pending thinking before showing response
                _flush_thinking_buffer()

                text_parts.append(text)
                # Stream response chunks directly - always visible
                self.call_from_thread(log.add_response_chunk, text)

        async def on_thinking(text: str) -> None:
            """Handle agent thinking/session logs - toggleable with Ctrl+T."""
            import time

            if not text:
                return

            # Filter out raw agent stdout logs - these are verbose session logs
            # The [agent] prefix comes from non-JSON output from the agent process
            if text.startswith("[agent]"):
                # Only show in verbose mode (`:log verbose`)
                if self.show_verbose_agent_logs:
                    clean_text = text[8:]  # Remove "[agent] " prefix
                    self.call_from_thread(self._show_thinking_line, f"📡 {clean_text}", log)
                return

            # Filter out other verbose prefixes
            if text.startswith("[error]") or text.startswith("[startup"):
                # Show errors but in a cleaner format
                clean_text = text.replace("[error] ", "").replace("[startup error] ", "")
                self.call_from_thread(log.add_error, clean_text)
                return

            # Buffer thinking chunks and display as complete thoughts
            # This prevents word-by-word display when chunks come in small pieces
            current_time = time.time()
            thinking_buffer.append(text)
            buffer_text = "".join(thinking_buffer)

            # Only flush when we have a complete thought:
            # 1. Buffer ends with sentence-ending punctuation followed by space or end
            # 2. Buffer has accumulated substantial text (>150 chars with any word boundary)
            # 3. Text ends with double newline (paragraph break)
            buffer_stripped = buffer_text.rstrip()

            # Check for complete sentences (punctuation followed by end or space)
            ends_with_sentence = (
                buffer_stripped.endswith(".")
                or buffer_stripped.endswith("!")
                or buffer_stripped.endswith("?")
                or buffer_stripped.endswith(":")
            ) and (
                text.endswith((".", "!", "?", ":"))  # Chunk itself ends with punct
                or text.endswith(" ")  # Or followed by space
                or len(buffer_text) > 50  # Or buffer is substantial
            )

            # Check for paragraph breaks
            has_paragraph_break = "\n\n" in buffer_text or buffer_text.endswith("\n")

            # Check for substantial accumulated text
            has_enough_text = len(buffer_text) > 150 and buffer_text.rstrip()[-1] in " \n.!?:"

            should_flush = ends_with_sentence or has_paragraph_break or has_enough_text

            if should_flush:
                _flush_thinking_buffer()

            last_thinking_time[0] = current_time

        async def on_tool_call(tool_call: dict) -> None:
            """Handle tool calls - ALWAYS visible (this is the agent's actual work)."""
            # Flush any pending thinking before showing tool call
            _flush_thinking_buffer()

            title = tool_call.get("title", "")
            raw_input = tool_call.get("rawInput", {})
            kind = tool_call.get("kind", "")
            tool_actions.append({"tool": title, "input": raw_input})

            file_path = raw_input.get("path", raw_input.get("filePath", ""))
            if file_path:
                if kind in ("edit", "write", "delete"):
                    if file_path not in files_modified:
                        files_modified.append(file_path)
                elif kind == "read":
                    if file_path not in files_read:
                        files_read.append(file_path)

            # ALWAYS show tool calls - this is the agent's actual work
            command = raw_input.get("command", "")
            self.call_from_thread(
                log.add_tool_call,
                title,
                "running",
                file_path,
                command,
            )

        async def on_tool_update(update: dict) -> None:
            """Handle tool updates - ALWAYS visible with full JSON parsing."""
            status = update.get("status", "")
            output = update.get("rawOutput") or update.get("output") or update.get("result")
            tool_title = update.get("title") or "Tool"

            if status == "completed":
                # Try to parse and display JSON nicely
                formatted = self._format_tool_output(tool_title, output, log)
                if not formatted:
                    # Fallback to simple display - show full output, no truncation
                    output_str = str(output) if output else ""
                    self.call_from_thread(
                        log.add_tool_call,
                        tool_title,
                        "success",
                        "",
                        "",
                        output_str,
                    )
            elif status == "failed":
                error_msg = str(output) if output else "failed"
                self.call_from_thread(
                    log.add_tool_call,
                    tool_title,
                    "error",
                    "",
                    "",
                    error_msg,
                )

        async def on_plan(entries: list[dict]) -> None:
            """Handle plan updates - ALWAYS visible."""
            if entries:
                # Plans are important - always show
                self.call_from_thread(
                    log.add_thinking, f"📋 Plan: {len(entries)} tasks", "planning"
                )

        async def on_permission_request(options: list[dict], tool_call: dict) -> str:
            tool_name = tool_call.get("title", "unknown")
            tool_input = tool_call.get("rawInput", {})

            if self.approval_mode == "deny":
                self.call_from_thread(
                    self._show_thinking_line, f"🔴 BLOCKED: {tool_name} (DENY mode)", log
                )
                return _pick_option(options, ["reject_once", "reject_always"])

            if self.approval_mode == "auto":
                self.call_from_thread(
                    self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log
                )
                return _pick_option(options, ["allow_once", "allow_always"])

            needs_permission = self._tool_needs_permission(tool_name, tool_input)
            if needs_permission:
                self.call_from_thread(self._show_permission_prompt, tool_name, tool_input, log)
                self._permission_pending = True
                self._permission_response = None

                wait_start = time.monotonic()
                timeout = 60
                while self._permission_pending and (time.monotonic() - wait_start) < timeout:
                    if self._cancel_requested:
                        self._permission_pending = False
                        break
                    time.sleep(0.1)

                if self._permission_response == "allow":
                    return _pick_option(options, ["allow_once", "allow_always"])
                if self._permission_response == "allow_all":
                    self.approval_mode = "auto"
                    self.call_from_thread(self._sync_approval_mode)
                    return _pick_option(options, ["allow_always", "allow_once"])

                self.call_from_thread(log.add_info, f"Denied: {tool_name}")
                return _pick_option(options, ["reject_once", "reject_always"])

            return _pick_option(options, ["allow_once", "allow_always"])

        async def run_prompt() -> tuple[str | None, dict]:
            client = ACPClient(project_root=Path.cwd(), command=command, model=None)
            client.on_message = on_message
            client.on_thinking = on_thinking
            client.on_tool_call = on_tool_call
            client.on_tool_update = on_tool_update
            client.on_permission_request = on_permission_request
            client.on_plan = on_plan

            try:
                ok = await client.start()
                if not ok:
                    return None, {}

                # Store for cancellation cleanup
                self._acp_client = client
                if getattr(client, "_process", None) is not None:
                    self._agent_process = client._process  # type: ignore[attr-defined]

                # Set model for agents that support ACP model selection
                if model and agent_type in ("codex", "openhands", "opencode"):
                    model_id = model
                    if agent_type == "opencode" and not model_id.startswith("opencode/"):
                        model_id = f"opencode/{model_id}"
                    await client.set_model(model_id)

                prompt_task = asyncio.create_task(client.send_prompt(message))

                while not prompt_task.done():
                    if self._cancel_requested:
                        await client.cancel()
                        break
                    await asyncio.sleep(0.1)

                stop_reason = await prompt_task
                return stop_reason, client.get_stats().__dict__
            finally:
                await client.stop()

        try:
            stop_reason, stats = asyncio.run(run_prompt())
            self._acp_client = None
            self._agent_process = None
            self.call_from_thread(self._stop_stream_animation)

            # Get response text
            response_text = "".join(text_parts) if text_parts else ""

            # Use enhanced end_agent_session for consistent output
            self.call_from_thread(
                log.end_agent_session,
                True,  # success
                response_text,
                stats.get("prompt_tokens", 0),
                stats.get("completion_tokens", 0),
                stats.get("thinking_tokens", 0),
                stats.get("cost", 0.0),
            )

            # Also show the final outcome if there's response text
            if response_text.strip():
                action_summary = {
                    "tool_count": stats.get("tool_count", len(tool_actions)),
                    "files_modified": stats.get("files_modified", files_modified),
                    "files_read": stats.get("files_read", files_read),
                    "duration": stats.get("duration", 0.0),
                    "file_diffs": self._compute_file_diffs(
                        stats.get("files_modified", files_modified)
                    ),
                }
                self.call_from_thread(
                    self._show_final_outcome, response_text, display_name, action_summary, log
                )

        except FileNotFoundError:
            self._agent_process = None
            self._acp_client = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(
                log.end_agent_session,
                False,  # failed
                f"❌ {command} not found. Install it first.",
            )
        except Exception as e:
            self._agent_process = None
            self._acp_client = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(
                log.end_agent_session,
                False,  # failed
                f"❌ Error: {str(e)}",
            )

    def _compute_file_diffs(self, files_modified: list) -> dict:
        """Compute diff data for modified files.

        Returns dict mapping file_path -> {"additions": int, "deletions": int, "diff_text": str}
        """
        file_diffs = {}
        root_path = Path(os.getcwd())

        for file_path in files_modified:
            try:
                # Use git diff to get the actual changes
                diff_text = get_file_diff(root_path, file_path, staged=False)
                if diff_text:
                    # Parse diff to get additions/deletions
                    additions = sum(
                        1
                        for line in diff_text.split("\n")
                        if line.startswith("+") and not line.startswith("+++")
                    )
                    deletions = sum(
                        1
                        for line in diff_text.split("\n")
                        if line.startswith("-") and not line.startswith("---")
                    )
                    file_diffs[file_path] = {
                        "additions": additions,
                        "deletions": deletions,
                        "diff_text": diff_text,
                    }
                else:
                    # File might be new or untracked, try to detect
                    file_path_obj = Path(file_path)
                    if file_path_obj.exists():
                        # New file - count lines as additions
                        try:
                            with open(file_path_obj, "r", encoding="utf-8", errors="ignore") as f:
                                line_count = len(f.readlines())
                            file_diffs[file_path] = {
                                "additions": line_count,
                                "deletions": 0,
                                "diff_text": "",
                            }
                        except Exception:
                            file_diffs[file_path] = {
                                "additions": 0,
                                "deletions": 0,
                                "diff_text": "",
                            }
                    else:
                        # File doesn't exist - might be deleted
                        file_diffs[file_path] = {
                            "additions": 0,
                            "deletions": 0,
                            "diff_text": "",
                        }
            except Exception:
                # If we can't compute diff, just mark as modified
                file_diffs[file_path] = {
                    "additions": 0,
                    "deletions": 0,
                    "diff_text": "",
                }

        return file_diffs

    def _handle_gemini_event(
        self,
        event: dict,
        text_parts: list,
        tool_actions: list,
        files_modified: list,
        files_read: list,
        log,
        process,
    ):
        """Handle Gemini CLI JSON events."""
        from time import monotonic

        event_type = event.get("type", "")

        if event_type == "init":
            # Session initialized
            session_id = event.get("session_id", "")
            model = event.get("model", "auto")
            self.call_from_thread(
                self._show_thinking_line, f"🚀 Session started (model: {model})", log
            )

        elif event_type == "message":
            role = event.get("role", "")
            content = event.get("content", "")
            is_delta = event.get("delta", False)

            if role == "assistant" and content:
                text_parts.append(content)
                if is_delta:
                    # Show full content, no truncation
                    self.call_from_thread(self._show_thinking_line, f"💬 {content}", log)

        elif event_type == "tool_use":
            tool_name = event.get("tool_name", "unknown")
            tool_id = event.get("tool_id", "")
            parameters = event.get("parameters", {})

            tool_actions.append({"tool": tool_name, "input": parameters})

            # Track files
            file_path = parameters.get(
                "file_path", parameters.get("path", parameters.get("dir_path", ""))
            )
            if file_path:
                if tool_name.lower() in ("write_file", "edit_file", "patch_file", "create_file"):
                    if file_path not in files_modified:
                        files_modified.append(file_path)
                elif tool_name.lower() in ("read_file", "list_directory"):
                    if file_path not in files_read:
                        files_read.append(file_path)

            # Format tool message
            msg = self._format_tool_message_rich(tool_name, parameters)

            # Ensure _approved_tools is initialized
            approved_tools = self._ensure_approved_tools()

            # Skip if this tool was already approved (prevent duplicates)
            if tool_id and tool_id in approved_tools:
                self.call_from_thread(self._show_thinking_line, msg, log)
            # Handle approval modes
            elif self.approval_mode == "deny":
                self.call_from_thread(
                    self._show_thinking_line, f"🔴 BLOCKED: {tool_name} (DENY mode)", log
                )
                self.call_from_thread(log.add_error, f"🛑 Tool blocked: {tool_name}")
                process.terminate()
            elif self.approval_mode == "ask":
                needs_permission = self._tool_needs_permission(tool_name, parameters)
                if needs_permission:
                    self._pending_tool_id = tool_id  # Track which tool is pending
                    self.call_from_thread(self._show_permission_prompt, tool_name, parameters, log)
                    self._permission_pending = True
                    self._permission_response = None

                    wait_start = monotonic()
                    timeout = 60
                    while self._permission_pending and (monotonic() - wait_start) < timeout:
                        if self._cancel_requested:
                            self._permission_pending = False
                            process.terminate()
                            self.call_from_thread(log.add_info, "🛑 Cancelled")
                            break
                        time.sleep(0.1)

                    if self._permission_response == "deny" or self._permission_response is None:
                        self.call_from_thread(log.add_info, f"Denied: {tool_name}")
                        process.terminate()
                    elif self._permission_response == "allow":
                        # Add to approved tools to prevent duplicate prompts
                        approved_tools = self._ensure_approved_tools()
                        if self._pending_tool_id:
                            approved_tools.add(self._pending_tool_id)
                        self.call_from_thread(
                            self._show_thinking_line, f"✅ Allowed: {tool_name}", log
                        )
                    elif self._permission_response == "allow_all":
                        self.approval_mode = "auto"
                        self.call_from_thread(self._sync_approval_mode)
                        self.call_from_thread(
                            self._show_thinking_line, f"✅ Allowed all: {tool_name}", log
                        )
                else:
                    self.call_from_thread(self._show_thinking_line, msg, log)
            else:
                self.call_from_thread(self._show_thinking_line, msg, log)

        elif event_type == "tool_result":
            tool_id = event.get("tool_id", "")
            tool_name = event.get("tool_name", "unknown")  # Get tool name for special handling
            status = event.get("status", "")
            output = event.get("output", "")

            if status == "success":
                # Special handling for todo_read tool - format nicely with emojis
                if tool_name == "todo_read" and output:
                    try:
                        import json

                        todos = json.loads(str(output))
                        if todos:
                            formatted_todos = self._format_todo_list(todos)
                            # Count tasks by status
                            completed = sum(1 for t in todos if t.get("status") == "completed")
                            in_progress = sum(1 for t in todos if t.get("status") == "in_progress")
                            pending = sum(1 for t in todos if t.get("status") == "pending")

                            # Show summary
                            summary_parts = []
                            if completed > 0:
                                summary_parts.append(f"{completed} done")
                            if in_progress > 0:
                                summary_parts.append(f"{in_progress} active")
                            if pending > 0:
                                summary_parts.append(f"{pending} pending")

                            summary = ", ".join(summary_parts) if summary_parts else "empty"

                            self.call_from_thread(
                                self._show_thinking_line, f"📋 Task List ({summary}):", log
                            )
                            for todo_line in formatted_todos:
                                self.call_from_thread(
                                    self._show_thinking_line, f"  {todo_line}", log
                                )
                        else:
                            self.call_from_thread(
                                self._show_thinking_line, f"📋 No tasks in todo list", log
                            )
                    except (json.JSONDecodeError, KeyError):
                        # Fallback to normal display if JSON parsing fails
                        output_str = str(output)
                        self.call_from_thread(
                            self._show_thinking_line, f"✅ Result: {output_str}", log
                        )
                elif output:
                    output_str = str(output)
                    # Show full output, no truncation
                    self.call_from_thread(self._show_thinking_line, f"✅ Result: {output_str}", log)
                else:
                    self.call_from_thread(self._show_thinking_line, f"✅ Tool completed", log)
            else:
                # Show full error message, no truncation
                error_msg = str(output) if output else "failed"
                self.call_from_thread(self._show_thinking_line, f"❌ Tool failed: {error_msg}", log)

        elif event_type == "result":
            # Final result with stats
            stats = event.get("stats", {})
            total_tokens = stats.get("total_tokens", 0)
            tool_calls = stats.get("tool_calls", 0)
            duration_ms = stats.get("duration_ms", 0)
            if total_tokens > 0:
                self.call_from_thread(
                    self._show_thinking_line,
                    f"⚡ Done ({total_tokens} tokens, {tool_calls} tools)",
                    log,
                )

    def _handle_opencode_event(
        self,
        event: dict,
        text_parts: list,
        tool_actions: list,
        files_modified: list,
        files_read: list,
        log,
        process,
    ):
        """Handle OpenCode JSON events."""
        from time import monotonic

        event_type = event.get("type", "")
        part = event.get("part", {})

        # Skip permission-related events
        if event_type in ("permission", "permission_request", "approval", "confirm"):
            return

        if event_type == "text":
            text_content = part.get("text", "")
            if text_content and text_content.strip():
                # Skip permission-related text
                text_lower = text_content.lower()
                if any(
                    skip in text_lower
                    for skip in [
                        "allow",
                        "deny",
                        "permission",
                        "approve",
                        "reject",
                        "[y/n]",
                        "(y/n)",
                        "proceed",
                        "continue?",
                    ]
                ):
                    return
                text_parts.append(text_content)
                # Show full content, no truncation
                self.call_from_thread(self._show_thinking_line, f"💬 {text_content}", log)

        elif event_type == "tool_use":
            tool_name = part.get("tool", "unknown")
            state = part.get("state", {})
            tool_input = state.get("input", {})

            # Track tool actions
            file_path = tool_input.get(
                "filePath", tool_input.get("path", tool_input.get("file", ""))
            )
            tool_actions.append({"tool": tool_name, "input": tool_input})

            # Track files
            if file_path:
                if tool_name.lower() in ("write", "edit", "patch", "create"):
                    if file_path not in files_modified:
                        files_modified.append(file_path)
                elif tool_name.lower() == "read":
                    if file_path not in files_read:
                        files_read.append(file_path)

            # Format tool message
            msg = self._format_tool_message_rich(tool_name, tool_input)

            # Handle approval modes
            if self.approval_mode == "deny":
                self.call_from_thread(
                    self._show_thinking_line, f"🔴 BLOCKED: {tool_name} (DENY mode)", log
                )
                self.call_from_thread(log.add_error, f"🛑 Tool blocked: {tool_name}")
                self.call_from_thread(log.add_info, "💡 Use :mode auto or :mode ask to allow tools")
                process.terminate()
            elif self.approval_mode == "ask":
                needs_permission = self._tool_needs_permission(tool_name, tool_input)
                if needs_permission:
                    self.call_from_thread(self._show_permission_prompt, tool_name, tool_input, log)
                    self._permission_pending = True
                    self._permission_response = None

                    wait_start = monotonic()
                    timeout = 60
                    while self._permission_pending and (monotonic() - wait_start) < timeout:
                        if self._cancel_requested:
                            self._permission_pending = False
                            process.terminate()
                            self.call_from_thread(log.add_info, "🛑 Cancelled")
                            break
                        time.sleep(0.1)

                    if self._permission_response == "deny" or self._permission_response is None:
                        self.call_from_thread(log.add_info, f"Denied: {tool_name}")
                        process.terminate()
                    elif self._permission_response == "allow":
                        self.call_from_thread(
                            self._show_thinking_line, f"✅ Allowed: {tool_name}", log
                        )
                    elif self._permission_response == "allow_all":
                        self.approval_mode = "auto"
                        self.call_from_thread(self._sync_approval_mode)
                        self.call_from_thread(
                            self._show_thinking_line, f"✅ Allowed all: {tool_name}", log
                        )
                else:
                    self.call_from_thread(self._show_thinking_line, msg, log)
            else:
                self.call_from_thread(self._show_thinking_line, msg, log)

        elif event_type == "step_start":
            pass  # Skip

        elif event_type == "thinking" or event_type == "reasoning":
            thinking_text = part.get("text", part.get("content", ""))
            if thinking_text:
                # Show full thinking text, no truncation
                self.call_from_thread(self._show_thinking_line, f"🧠 {thinking_text}", log)

        elif event_type == "tool_result":
            tool_name = part.get("tool", "")
            success = part.get("success", True)
            result_content = part.get("content", part.get("result", ""))
            if success:
                # Special handling for todo_read tool - format nicely with emojis
                if tool_name == "todo_read" and result_content:
                    try:
                        import json

                        todos = json.loads(result_content)
                        if todos:
                            formatted_todos = self._format_todo_list(todos)
                            # Count tasks by status
                            completed = sum(1 for t in todos if t.get("status") == "completed")
                            in_progress = sum(1 for t in todos if t.get("status") == "in_progress")
                            pending = sum(1 for t in todos if t.get("status") == "pending")

                            # Show summary
                            summary_parts = []
                            if completed > 0:
                                summary_parts.append(f"{completed} done")
                            if in_progress > 0:
                                summary_parts.append(f"{in_progress} active")
                            if pending > 0:
                                summary_parts.append(f"{pending} pending")

                            summary = ", ".join(summary_parts) if summary_parts else "empty"

                            self.call_from_thread(
                                self._show_thinking_line, f"📋 Task List ({summary}):", log
                            )
                            for todo_line in formatted_todos:
                                self.call_from_thread(
                                    self._show_thinking_line, f"  {todo_line}", log
                                )
                        else:
                            self.call_from_thread(
                                self._show_thinking_line, f"📋 No tasks in todo list", log
                            )
                    except (json.JSONDecodeError, KeyError):
                        # Fallback to normal display if JSON parsing fails
                        result_str = str(result_content)
                        self.call_from_thread(
                            self._show_thinking_line, f"✅ {tool_name}: {result_str}", log
                        )
                elif result_content:
                    result_str = str(result_content)
                    # Show full result, no truncation
                    self.call_from_thread(
                        self._show_thinking_line, f"✅ {tool_name}: {result_str}", log
                    )
                else:
                    self.call_from_thread(
                        self._show_thinking_line, f"✅ {tool_name} completed", log
                    )
            else:
                # Show full error message, no truncation
                error_msg = str(result_content) if result_content else "failed"
                self.call_from_thread(
                    self._show_thinking_line, f"❌ {tool_name} failed: {error_msg}", log
                )

        elif event_type == "step_finish":
            reason = part.get("reason", "")
            tokens = part.get("tokens", {})
            if tokens and reason != "tool-calls":
                output_tokens = tokens.get("output", 0)
                cache = tokens.get("cache", {})
                cache_read = cache.get("read", 0)
                if cache_read > 0:
                    self.call_from_thread(
                        self._show_thinking_line,
                        f"⚡ Step done ({output_tokens} tokens, {cache_read} cached)",
                        log,
                    )
                elif output_tokens > 0:
                    self.call_from_thread(
                        self._show_thinking_line, f"⚡ Step done ({output_tokens} tokens)", log
                    )
        else:
            if event_type and event_type not in ("metadata", "session"):
                content = part.get("text", part.get("content", part.get("message", "")))
                if content:
                    # Show full content, no truncation
                    self.call_from_thread(self._show_thinking_line, f"📋 {content}", log)

    def _handle_terminal_method(
        self,
        method: str,
        params: dict,
        terminals: dict,
        terminal_counter_ref: list,
        log: ConversationLog,
    ) -> tuple[dict, bool]:
        """
        Handle terminal-related ACP methods.

        Args:
            method: The ACP method name
            params: Method parameters
            terminals: Dict tracking terminal processes
            terminal_counter_ref: List with single int for counter (mutable reference)
            log: ConversationLog for output

        Returns:
            Tuple of (response_dict, was_handled)
        """
        if method == "terminal/create":
            command = params.get("command", "")
            args = params.get("args", [])
            cwd = params.get("cwd", os.getcwd())
            env_vars = params.get("env", [])

            terminal_counter_ref[0] += 1
            terminal_id = f"terminal-{terminal_counter_ref[0]}"

            # Build full command
            if args:
                full_command = f"{command} {' '.join(args)}"
            else:
                full_command = command

            # Build environment
            term_env = os.environ.copy()
            for var in env_vars:
                if isinstance(var, dict):
                    term_env[var.get("name", "")] = var.get("value", "")

            self.call_from_thread(self._show_thinking_line, f"🖥️ Running: {full_command}", log)

            try:
                term_process = subprocess.Popen(
                    full_command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    cwd=cwd,
                    env=term_env,
                    text=True,
                )

                terminals[terminal_id] = {
                    "process": term_process,
                    "output": "",
                    "exit_code": None,
                }

                return {"terminalId": terminal_id}, True
            except Exception as e:
                self.call_from_thread(self._show_thinking_line, f"⚠️ Terminal error: {e}", log)
                return {"terminalId": terminal_id}, True

        elif method == "terminal/output":
            terminal_id = params.get("terminalId", "")
            terminal = terminals.get(terminal_id)

            if terminal:
                term_process = terminal["process"]
                try:
                    if term_process.poll() is not None:
                        remaining, _ = term_process.communicate(timeout=1)
                        if remaining:
                            terminal["output"] += remaining
                        terminal["exit_code"] = term_process.returncode
                    else:
                        import select

                        if hasattr(select, "select"):
                            readable, _, _ = select.select([term_process.stdout], [], [], 0.1)
                            if readable:
                                chunk = term_process.stdout.read(4096)
                                if chunk:
                                    terminal["output"] += chunk
                except Exception:
                    pass

                result = {
                    "output": terminal["output"],
                    "truncated": len(terminal["output"]) > 100000,
                }
                if terminal["exit_code"] is not None:
                    result["exitStatus"] = {"exitCode": terminal["exit_code"]}
                return result, True
            else:
                return {"output": "", "truncated": False}, True

        elif method == "terminal/wait_for_exit":
            terminal_id = params.get("terminalId", "")
            terminal = terminals.get(terminal_id)

            if terminal:
                term_process = terminal["process"]
                try:
                    remaining, _ = term_process.communicate(timeout=120)
                    if remaining:
                        terminal["output"] += remaining
                    terminal["exit_code"] = term_process.returncode

                    if terminal["output"]:
                        # Show full terminal output, no truncation
                        output_preview = terminal["output"].strip()
                        if output_preview:
                            self.call_from_thread(
                                self._show_thinking_line, f"📋 {output_preview}", log
                            )

                    return {"exitCode": terminal["exit_code"], "signal": None}, True
                except subprocess.TimeoutExpired:
                    term_process.kill()
                    terminal["exit_code"] = -1
                    return {"exitCode": -1, "signal": "SIGKILL"}, True
            else:
                return {"exitCode": -1, "signal": None}, True

        elif method == "terminal/kill":
            terminal_id = params.get("terminalId", "")
            terminal = terminals.get(terminal_id)
            if terminal and terminal["process"]:
                terminal["process"].terminate()
            return {}, True

        elif method == "terminal/release":
            terminal_id = params.get("terminalId", "")
            if terminal_id in terminals:
                del terminals[terminal_id]
            return {}, True

        return {}, False

    def _format_todo_list(self, todos: list) -> list:
        """Format a TODO list with emojis and nice display."""
        if not todos:
            return ["📋 No tasks"]

        formatted_lines = []

        # Status emoji mapping
        status_emojis = {"completed": "✅", "in_progress": "🔄", "pending": "⏳", "cancelled": "❌"}

        # Priority indicators (subtle)
        priority_indicators = {"high": "🔴", "medium": "🟡", "low": "🟢"}

        for i, todo in enumerate(todos, 1):
            status = todo.get("status", "pending")
            content = todo.get("content", "")
            priority = todo.get("priority", "medium")

            # Get emojis
            status_emoji = status_emojis.get(status, "○")
            priority_emoji = priority_indicators.get(priority, "")

            # Format the line
            line = f"{status_emoji} {i}. {content}"
            if priority_emoji:
                line += f" {priority_emoji}"

            formatted_lines.append(line)

        return formatted_lines

    def _cleanup_terminals(self, terminals: dict):
        """Clean up any running terminal processes."""
        for tid, term in terminals.items():
            try:
                if term["process"] and term["process"].poll() is None:
                    term["process"].terminate()
            except Exception:
                pass
        terminals.clear()

    # Legacy method - calls the unified runner
    def _run_opencode_unified(
        self,
        message: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ):
        """Legacy wrapper - calls _run_agent_unified with opencode agent type."""
        self._run_agent_unified(
            message=message,
            agent_type="opencode",
            model=model,
            display_name=display_name,
            log=log,
            persona_context=persona_context,
        )

    def _run_claude_acp(
        self,
        message: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ):
        """
        Run Claude Code using the ACP protocol via claude-code-acp adapter.

        Claude Code ACP uses full bidirectional JSON-RPC protocol, not simple JSON streaming.
        This method uses subprocess with JSON-RPC communication.
        Supports multi-turn by keeping the process alive and reusing session.
        """
        import subprocess
        import json
        from time import monotonic

        try:
            start_time = monotonic()

            model_display = f"claude/{model}" if model else "claude/auto"

            # Show info with approval mode
            mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
                self.approval_mode, "🟡 ASK"
            )
            session_type = "new session" if self._is_first_message else "continuing session"
            self.call_from_thread(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self.call_from_thread(
                    log.add_info, f"🎭 Persona active: {persona_context.role_name}"
                )

            # Build environment - need ANTHROPIC_API_KEY
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
            }

            # Check for API key
            if "ANTHROPIC_API_KEY" not in env:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(
                    log.add_error, "❌ ANTHROPIC_API_KEY not set. Export it first:"
                )
                self.call_from_thread(log.add_info, "  export ANTHROPIC_API_KEY=sk-ant-...")
                return

            # Check if we can reuse existing process and session
            reuse_session = False
            process = None

            if (
                self._claude_process is not None
                and self._claude_process.poll() is None
                and self._claude_session_id
            ):
                # Process is still running and we have a session - reuse it
                process = self._claude_process
                reuse_session = True
                self.call_from_thread(
                    self._show_thinking_line, "🔄 Continuing conversation...", log
                )
            else:
                # Start new process
                cmd = ["claude-code-acp"]
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=os.getcwd(),
                    text=True,
                    bufsize=1,
                    env=env,
                )
                self._claude_process = process
                self._claude_session_id = ""

            # Store process reference for cancellation
            self._agent_process = process

            # Stop thinking, start streaming animation
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._start_stream_animation, log)

            # Show header
            self.call_from_thread(
                self._show_agent_header_with_model, display_name, model_display, log
            )

            # Collect output
            text_parts = []
            tool_actions = []
            files_modified = []
            files_read = []

            # Terminal tracking for this session
            terminals = {}
            terminal_counter = 0

            # JSON-RPC request ID counter
            request_id = getattr(self, "_claude_request_id", 0)
            session_id = self._claude_session_id if reuse_session else None

            def send_request(method: str, params: dict = None) -> int:
                """Send a JSON-RPC request to the agent."""
                nonlocal request_id
                request_id += 1
                self._claude_request_id = request_id
                request = {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params or {},
                    "id": request_id,
                }
                try:
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                except Exception as e:
                    self.call_from_thread(self._show_thinking_line, f"⚠️ Send error: {e}", log)
                return request_id

            def send_response(req_id: int, result: dict):
                """Send a JSON-RPC response to the agent."""
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": req_id,
                }
                try:
                    process.stdin.write(json.dumps(response) + "\n")
                    process.stdin.flush()
                except Exception:
                    pass

            # Step 1: Initialize the protocol
            self.call_from_thread(self._show_thinking_line, "🔌 Initializing ACP protocol...", log)
            send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": True, "writeTextFile": True},
                        "terminal": True,
                    },
                    "clientInfo": {
                        "name": "SuperQode",
                        "title": "SuperQode - Multi-Agent Coding Team",
                        "version": "0.1.0",
                    },
                },
            )

            # Read and process messages
            pending_requests = {}
            initialized = False
            session_created = False
            prompt_sent = False

            while True:
                if self._cancel_requested:
                    process.terminate()
                    self.call_from_thread(log.add_info, "🛑 Agent operation cancelled")
                    break

                # Read a line from stdout
                try:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if not line:
                        continue

                    line = line.strip()
                    if not line:
                        continue

                    # Parse JSON-RPC message
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        # Not JSON - might be debug output
                        if line and not line.startswith("Loaded"):
                            self.call_from_thread(self._show_thinking_line, f"📋 {line}", log)
                        continue

                    # Handle response to our request
                    if "result" in msg or "error" in msg:
                        msg_id = msg.get("id")

                        if "error" in msg:
                            error = msg["error"]
                            error_msg = error.get("message", "Unknown error")
                            self.call_from_thread(log.add_error, f"❌ ACP Error: {error_msg}")
                            break

                        result = msg.get("result", {})

                        # Handle initialize response
                        if not initialized:
                            initialized = True
                            agent_info = result.get("agentInfo", {})
                            agent_name = agent_info.get("title", "Claude Code")
                            self.call_from_thread(
                                self._show_thinking_line, f"✅ Connected to {agent_name}", log
                            )

                            # Step 2: Create a new session
                            send_request(
                                "session/new",
                                {
                                    "cwd": os.getcwd(),
                                    "mcpServers": [],
                                },
                            )
                            continue

                        # Handle session/new response
                        if not session_created:
                            session_id = result.get("sessionId", "")
                            session_created = True

                            # Check available models
                            models = result.get("models", {})
                            available_models = models.get("availableModels", [])
                            if available_models:
                                model_names = [
                                    m.get("name", m.get("modelId", ""))
                                    for m in available_models[:3]
                                ]
                                self.call_from_thread(
                                    self._show_thinking_line,
                                    f"📊 Models: {', '.join(model_names)}",
                                    log,
                                )

                            self.call_from_thread(
                                self._show_thinking_line, f"🚀 Session started", log
                            )

                            # Step 3: Send the prompt
                            send_request(
                                "session/prompt",
                                {
                                    "sessionId": session_id,
                                    "prompt": [{"type": "text", "text": message}],
                                },
                            )
                            prompt_sent = True
                            continue

                        # Handle prompt response (completion)
                        if prompt_sent:
                            stop_reason = result.get("stopReason", "end_turn")
                            self.call_from_thread(
                                self._show_thinking_line, f"✅ Completed ({stop_reason})", log
                            )
                            break

                    # Handle request from agent (notifications/requests)
                    elif "method" in msg:
                        method = msg.get("method", "")
                        params = msg.get("params", {})
                        req_id = msg.get("id")

                        if method == "session/update":
                            # Handle session updates (streaming content)
                            update = params.get("update", params)
                            update_type = update.get("sessionUpdate", "")

                            if update_type == "agent_message_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    text_parts.append(text)
                                    # Show full text, no truncation
                                    self.call_from_thread(
                                        self._show_thinking_line, f"💬 {text}", log
                                    )

                            elif update_type == "agent_thought_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    # Show full thinking text, no truncation
                                    self.call_from_thread(
                                        self._show_thinking_line, f"🧠 {text}", log
                                    )

                            elif update_type == "tool_call":
                                tool_id = update.get("toolCallId", "")
                                title = update.get("title", "")
                                raw_input = update.get("rawInput", {})
                                status = update.get("status", "")

                                # Track tool_id to title mapping for detailed logging
                                if not hasattr(self, "_tool_id_map"):
                                    self._tool_id_map = {}
                                self._tool_id_map[tool_id] = {"title": title, "input": raw_input}

                                tool_actions.append({"tool": title, "input": raw_input})

                                # Track files
                                file_path = raw_input.get("path", raw_input.get("filePath", ""))
                                if file_path:
                                    kind = update.get("kind", "")
                                    if kind in ("edit", "write", "delete"):
                                        if file_path not in files_modified:
                                            files_modified.append(file_path)
                                    elif kind == "read":
                                        if file_path not in files_read:
                                            files_read.append(file_path)

                                msg_text = self._format_tool_message_rich(title, raw_input)
                                self.call_from_thread(self._show_thinking_line, msg_text, log)

                            elif update_type == "tool_call_update":
                                tool_id = update.get("toolCallId", "")
                                status = update.get("status", "")
                                output = update.get("output", update.get("result", ""))
                                # Get tool info from our tracking map
                                tool_info = getattr(self, "_tool_id_map", {}).get(tool_id, {})
                                tool_title = tool_info.get("title", "Tool")
                                if status == "completed":
                                    if output:
                                        output_str = str(output)
                                        # Show full output, no truncation
                                        self.call_from_thread(
                                            self._show_thinking_line,
                                            f"✅ {tool_title}: {output_str}",
                                            log,
                                        )
                                    else:
                                        self.call_from_thread(
                                            self._show_thinking_line,
                                            f"✅ {tool_title} completed",
                                            log,
                                        )
                                elif status == "failed":
                                    # Show full error message, no truncation
                                    error_msg = str(output) if output else "failed"
                                    self.call_from_thread(
                                        self._show_thinking_line,
                                        f"❌ {tool_title} failed: {error_msg}",
                                        log,
                                    )

                            elif update_type == "plan":
                                entries = update.get("entries", [])
                                if entries:
                                    self.call_from_thread(
                                        self._show_thinking_line,
                                        f"📋 Plan: {len(entries)} tasks",
                                        log,
                                    )

                        elif method == "session/request_permission":
                            # Handle permission request
                            options = params.get("options", [])
                            tool_call = params.get("toolCall", {})
                            tool_name = tool_call.get("title", "unknown")
                            tool_input = tool_call.get("rawInput", {})

                            # Handle based on approval mode
                            if self.approval_mode == "deny":
                                # Reject
                                self.call_from_thread(
                                    self._show_thinking_line,
                                    f"🔴 BLOCKED: {tool_name} (DENY mode)",
                                    log,
                                )
                                reject_option = next(
                                    (o for o in options if o.get("kind") == "reject_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": reject_option.get("optionId", ""),
                                        }
                                    },
                                )
                            elif self.approval_mode == "auto":
                                # Auto-allow
                                allow_option = next(
                                    (o for o in options if o.get("kind") == "allow_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": allow_option.get("optionId", ""),
                                        }
                                    },
                                )
                                self.call_from_thread(
                                    self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log
                                )
                            else:
                                # ASK mode - check if needs permission
                                needs_permission = self._tool_needs_permission(
                                    tool_name, tool_input
                                )
                                if needs_permission:
                                    self.call_from_thread(
                                        self._show_permission_prompt, tool_name, tool_input, log
                                    )
                                    self._permission_pending = True
                                    self._permission_response = None

                                    wait_start = monotonic()
                                    timeout = 60
                                    while (
                                        self._permission_pending
                                        and (monotonic() - wait_start) < timeout
                                    ):
                                        if self._cancel_requested:
                                            self._permission_pending = False
                                            break
                                        time.sleep(0.1)

                                    if (
                                        self._permission_response == "deny"
                                        or self._permission_response is None
                                    ):
                                        reject_option = next(
                                            (o for o in options if o.get("kind") == "reject_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": reject_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self.call_from_thread(log.add_info, f"Denied: {tool_name}")
                                    else:
                                        allow_option = next(
                                            (o for o in options if o.get("kind") == "allow_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": allow_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self.call_from_thread(
                                            self._show_thinking_line,
                                            f"✅ Allowed: {tool_name}",
                                            log,
                                        )
                                        if self._permission_response == "allow_all":
                                            self.approval_mode = "auto"
                                            self.call_from_thread(self._sync_approval_mode)
                                else:
                                    # Auto-allow safe operations
                                    allow_option = next(
                                        (o for o in options if o.get("kind") == "allow_once"),
                                        options[0] if options else {"optionId": ""},
                                    )
                                    send_response(
                                        req_id,
                                        {
                                            "outcome": {
                                                "outcome": "selected",
                                                "optionId": allow_option.get("optionId", ""),
                                            }
                                        },
                                    )

                        elif method == "fs/read_text_file":
                            # Handle file read request
                            path = params.get("path", "")
                            if path not in files_read:
                                files_read.append(path)

                            try:
                                read_path = Path(os.getcwd()) / path
                                content = read_path.read_text(encoding="utf-8", errors="ignore")
                                send_response(req_id, {"content": content})
                            except Exception:
                                send_response(req_id, {"content": ""})

                        elif method == "fs/write_text_file":
                            # Handle file write request
                            path = params.get("path", "")
                            content = params.get("content", "")

                            if path not in files_modified:
                                files_modified.append(path)

                            try:
                                write_path = Path(os.getcwd()) / path
                                write_path.parent.mkdir(parents=True, exist_ok=True)
                                write_path.write_text(content, encoding="utf-8")
                                send_response(req_id, {})
                            except Exception as e:
                                send_response(req_id, {"error": str(e)})

                        elif method.startswith("terminal/"):
                            # Handle terminal methods using helper
                            terminal_counter_ref = [terminal_counter]
                            result, handled = self._handle_terminal_method(
                                method, params, terminals, terminal_counter_ref, log
                            )
                            terminal_counter = terminal_counter_ref[0]
                            if handled:
                                send_response(req_id, result)
                            else:
                                if req_id is not None:
                                    send_response(req_id, {})

                        else:
                            # Unknown method - send empty response if it has an ID
                            if req_id is not None:
                                send_response(req_id, {})

                except Exception as e:
                    self.call_from_thread(self._show_thinking_line, f"⚠️ Read error: {e}", log)
                    break

            # Cleanup terminals
            self._cleanup_terminals(terminals)

            self._agent_process = None
            self.call_from_thread(self._stop_stream_animation)

            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

            duration = monotonic() - start_time
            self._is_first_message = False

            # Compute file diffs for modified files
            file_diffs = self._compute_file_diffs(files_modified)

            # Build summary
            action_summary = {
                "tool_count": len(tool_actions),
                "files_modified": files_modified,
                "files_read": files_read,
                "duration": duration,
                "file_diffs": file_diffs,  # NEW: Store diff data
            }

            # Show final response
            if text_parts:
                response_text = "".join(text_parts)
                if response_text.strip():
                    self.call_from_thread(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self.call_from_thread(
                        self._show_completion_summary, display_name, action_summary, log
                    )
            elif not self._cancel_requested:
                self.call_from_thread(
                    self._show_completion_summary, display_name, action_summary, log
                )

        except FileNotFoundError:
            self._agent_process = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(log.add_error, "❌ claude-code-acp not found. Install it first:")
            self.call_from_thread(log.add_info, "  npm install -g @zed-industries/claude-code-acp")
        except Exception as e:
            self._agent_process = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(log.add_error, f"❌ Error: {str(e)}")

    def _run_codex_acp(
        self,
        message: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ):
        """
        Run Codex CLI using the ACP protocol via codex-acp adapter.

        Codex ACP uses full bidirectional JSON-RPC protocol, similar to Claude Code.
        This method uses subprocess with JSON-RPC communication.
        """
        import subprocess
        import json
        from time import monotonic

        try:
            start_time = monotonic()

            # Build command - codex-acp is the ACP adapter
            # Try npx first, then global install
            cmd = ["npx", "@openai/codex-acp"]

            model_display = f"codex/{model}" if model else "codex/auto"

            # Show info with approval mode
            mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
                self.approval_mode, "🟡 ASK"
            )
            session_type = "new session" if self._is_first_message else "continuing session"
            self.call_from_thread(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self.call_from_thread(
                    log.add_info, f"🎭 Persona active: {persona_context.role_name}"
                )

            # Build environment - need OPENAI_API_KEY or CODEX_API_KEY
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
            }

            # Check for API key
            if "OPENAI_API_KEY" not in env and "CODEX_API_KEY" not in env:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(
                    log.add_error, "❌ OPENAI_API_KEY or CODEX_API_KEY not set. Export one first:"
                )
                self.call_from_thread(log.add_info, "  export OPENAI_API_KEY=sk-...")
                self.call_from_thread(log.add_info, "  or export CODEX_API_KEY=sk-...")
                return

            # Start process with bidirectional communication
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd(),
                text=True,
                bufsize=1,
                env=env,
            )

            # Store process reference for cancellation
            self._agent_process = process

            # Stop thinking, start streaming animation
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._start_stream_animation, log)

            # Show header
            self.call_from_thread(
                self._show_agent_header_with_model, display_name, model_display, log
            )

            # Collect output
            text_parts = []
            tool_actions = []
            files_modified = []
            files_read = []

            # Terminal tracking for this session
            terminals = {}
            terminal_counter = 0

            # JSON-RPC request ID counter
            request_id = 0
            session_id = None

            def send_request(method: str, params: dict = None) -> int:
                """Send a JSON-RPC request to the agent."""
                nonlocal request_id
                request_id += 1
                request = {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params or {},
                    "id": request_id,
                }
                try:
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                except Exception as e:
                    self.call_from_thread(self._show_thinking_line, f"⚠️ Send error: {e}", log)
                return request_id

            def send_response(req_id: int, result: dict):
                """Send a JSON-RPC response to the agent."""
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": req_id,
                }
                try:
                    process.stdin.write(json.dumps(response) + "\n")
                    process.stdin.flush()
                except Exception:
                    pass

            # Step 1: Initialize the protocol
            self.call_from_thread(self._show_thinking_line, "🔌 Initializing ACP protocol...", log)
            send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": True, "writeTextFile": True},
                        "terminal": True,
                    },
                    "clientInfo": {
                        "name": "SuperQode",
                        "title": "SuperQode - Multi-Agent Coding Team",
                        "version": "0.1.0",
                    },
                },
            )

            # Read and process messages
            pending_requests = {}
            initialized = False
            session_created = False
            prompt_sent = False

            while True:
                if self._cancel_requested:
                    process.terminate()
                    self.call_from_thread(log.add_info, "🛑 Agent operation cancelled")
                    break

                # Read a line from stdout
                try:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if not line:
                        continue

                    line = line.strip()
                    if not line:
                        continue

                    # Parse JSON-RPC message
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        # Not JSON - might be debug output
                        if line and not line.startswith("Loaded"):
                            self.call_from_thread(self._show_thinking_line, f"📋 {line}", log)
                        continue

                    # Handle response to our request
                    if "result" in msg or "error" in msg:
                        msg_id = msg.get("id")

                        if "error" in msg:
                            error = msg["error"]
                            error_msg = error.get("message", "Unknown error")
                            self.call_from_thread(log.add_error, f"❌ ACP Error: {error_msg}")
                            break

                        result = msg.get("result", {})

                        # Handle initialize response
                        if not initialized:
                            initialized = True
                            agent_info = result.get("agentInfo", {})
                            agent_name = agent_info.get("title", "Codex CLI")
                            self.call_from_thread(
                                self._show_thinking_line, f"✅ Connected to {agent_name}", log
                            )

                            # Step 2: Create a new session
                            send_request(
                                "session/new",
                                {
                                    "cwd": os.getcwd(),
                                    "mcpServers": [],
                                },
                            )
                            continue

                        # Handle session/new response
                        if not session_created:
                            session_id = result.get("sessionId", "")
                            session_created = True

                            # Check available models
                            models = result.get("models", {})
                            available_models = models.get("availableModels", [])
                            if available_models:
                                model_names = [
                                    m.get("name", m.get("modelId", ""))
                                    for m in available_models[:3]
                                ]
                                self.call_from_thread(
                                    self._show_thinking_line,
                                    f"📊 Models: {', '.join(model_names)}",
                                    log,
                                )

                            # Step 2.5: Set the model if specified (for Codex ACP)
                            if model:
                                # Try to set the model - codex-acp expects model ID without prefix
                                model_id = model
                                # Remove any codex/ prefix if present
                                if model_id.startswith("codex/"):
                                    model_id = model_id[6:]
                                # Send set_model request
                                send_request(
                                    "session/set_model",
                                    {
                                        "sessionId": session_id,
                                        "modelId": model_id,
                                    },
                                )
                                self.call_from_thread(
                                    self._show_thinking_line, f"🎯 Setting model: {model_id}", log
                                )

                            self.call_from_thread(
                                self._show_thinking_line, f"🚀 Session started", log
                            )

                            # Step 3: Send the prompt
                            send_request(
                                "session/prompt",
                                {
                                    "sessionId": session_id,
                                    "prompt": [{"type": "text", "text": message}],
                                },
                            )
                            prompt_sent = True
                            continue

                        # Handle prompt response (completion)
                        if prompt_sent:
                            stop_reason = result.get("stopReason", "end_turn")
                            self.call_from_thread(
                                self._show_thinking_line, f"✅ Completed ({stop_reason})", log
                            )
                            break

                    # Handle request from agent (notifications/requests)
                    elif "method" in msg:
                        method = msg.get("method", "")
                        params = msg.get("params", {})
                        req_id = msg.get("id")

                        if method == "session/update":
                            # Handle session updates (streaming content)
                            update = params.get("update", params)
                            update_type = update.get("sessionUpdate", "")

                            if update_type == "agent_message_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    text_parts.append(text)
                                    # Show full text, no truncation
                                    self.call_from_thread(
                                        self._show_thinking_line, f"💬 {text}", log
                                    )

                            elif update_type == "agent_thought_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    # Show full thinking text, no truncation
                                    self.call_from_thread(
                                        self._show_thinking_line, f"🧠 {text}", log
                                    )

                            elif update_type == "tool_call":
                                tool_id = update.get("toolCallId", "")
                                title = update.get("title", "")
                                raw_input = update.get("rawInput", {})
                                status = update.get("status", "")

                                # Track tool_id to title mapping for detailed logging
                                if not hasattr(self, "_tool_id_map"):
                                    self._tool_id_map = {}
                                self._tool_id_map[tool_id] = {"title": title, "input": raw_input}

                                tool_actions.append({"tool": title, "input": raw_input})

                                # Track files
                                file_path = raw_input.get("path", raw_input.get("filePath", ""))
                                if file_path:
                                    kind = update.get("kind", "")
                                    if kind in ("edit", "write", "delete"):
                                        if file_path not in files_modified:
                                            files_modified.append(file_path)
                                    elif kind == "read":
                                        if file_path not in files_read:
                                            files_read.append(file_path)

                                msg_text = self._format_tool_message_rich(title, raw_input)
                                self.call_from_thread(self._show_thinking_line, msg_text, log)

                            elif update_type == "tool_call_update":
                                tool_id = update.get("toolCallId", "")
                                status = update.get("status", "")
                                output = update.get("output", update.get("result", ""))
                                # Get tool info from our tracking map
                                tool_info = getattr(self, "_tool_id_map", {}).get(tool_id, {})
                                tool_title = tool_info.get("title", "Tool")
                                if status == "completed":
                                    if output:
                                        output_str = str(output)
                                        # Show full output, no truncation
                                        self.call_from_thread(
                                            self._show_thinking_line,
                                            f"✅ {tool_title}: {output_str}",
                                            log,
                                        )
                                    else:
                                        self.call_from_thread(
                                            self._show_thinking_line,
                                            f"✅ {tool_title} completed",
                                            log,
                                        )
                                elif status == "failed":
                                    # Show full error message, no truncation
                                    error_msg = str(output) if output else "failed"
                                    self.call_from_thread(
                                        self._show_thinking_line,
                                        f"❌ {tool_title} failed: {error_msg}",
                                        log,
                                    )

                            elif update_type == "plan":
                                entries = update.get("entries", [])
                                if entries:
                                    self.call_from_thread(
                                        self._show_thinking_line,
                                        f"📋 Plan: {len(entries)} tasks",
                                        log,
                                    )

                        elif method == "session/request_permission":
                            # Handle permission request
                            options = params.get("options", [])
                            tool_call = params.get("toolCall", {})
                            tool_name = tool_call.get("title", "unknown")
                            tool_input = tool_call.get("rawInput", {})

                            # Handle based on approval mode
                            if self.approval_mode == "deny":
                                # Reject
                                self.call_from_thread(
                                    self._show_thinking_line,
                                    f"🔴 BLOCKED: {tool_name} (DENY mode)",
                                    log,
                                )
                                reject_option = next(
                                    (o for o in options if o.get("kind") == "reject_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": reject_option.get("optionId", ""),
                                        }
                                    },
                                )
                            elif self.approval_mode == "auto":
                                # Auto-allow
                                allow_option = next(
                                    (o for o in options if o.get("kind") == "allow_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": allow_option.get("optionId", ""),
                                        }
                                    },
                                )
                                self.call_from_thread(
                                    self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log
                                )
                            else:
                                # ASK mode - check if needs permission
                                needs_permission = self._tool_needs_permission(
                                    tool_name, tool_input
                                )
                                if needs_permission:
                                    self.call_from_thread(
                                        self._show_permission_prompt, tool_name, tool_input, log
                                    )
                                    self._permission_pending = True
                                    self._permission_response = None

                                    wait_start = monotonic()
                                    timeout = 60
                                    while (
                                        self._permission_pending
                                        and (monotonic() - wait_start) < timeout
                                    ):
                                        if self._cancel_requested:
                                            self._permission_pending = False
                                            break
                                        time.sleep(0.1)

                                    if (
                                        self._permission_response == "deny"
                                        or self._permission_response is None
                                    ):
                                        reject_option = next(
                                            (o for o in options if o.get("kind") == "reject_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": reject_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self.call_from_thread(log.add_info, f"Denied: {tool_name}")
                                    else:
                                        allow_option = next(
                                            (o for o in options if o.get("kind") == "allow_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": allow_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self.call_from_thread(
                                            self._show_thinking_line,
                                            f"✅ Allowed: {tool_name}",
                                            log,
                                        )
                                        if self._permission_response == "allow_all":
                                            self.approval_mode = "auto"
                                            self.call_from_thread(self._sync_approval_mode)
                                else:
                                    # Auto-allow safe operations
                                    allow_option = next(
                                        (o for o in options if o.get("kind") == "allow_once"),
                                        options[0] if options else {"optionId": ""},
                                    )
                                    send_response(
                                        req_id,
                                        {
                                            "outcome": {
                                                "outcome": "selected",
                                                "optionId": allow_option.get("optionId", ""),
                                            }
                                        },
                                    )

                        elif method == "fs/read_text_file":
                            # Handle file read request
                            path = params.get("path", "")
                            if path not in files_read:
                                files_read.append(path)

                            try:
                                read_path = Path(os.getcwd()) / path
                                content = read_path.read_text(encoding="utf-8", errors="ignore")
                                send_response(req_id, {"content": content})
                            except Exception:
                                send_response(req_id, {"content": ""})

                        elif method == "fs/write_text_file":
                            # Handle file write request
                            path = params.get("path", "")
                            content = params.get("content", "")

                            if path not in files_modified:
                                files_modified.append(path)

                            try:
                                write_path = Path(os.getcwd()) / path
                                write_path.parent.mkdir(parents=True, exist_ok=True)
                                write_path.write_text(content, encoding="utf-8")
                                send_response(req_id, {})
                            except Exception as e:
                                send_response(req_id, {"error": str(e)})

                        elif method.startswith("terminal/"):
                            # Handle terminal methods using helper
                            terminal_counter_ref = [terminal_counter]
                            result, handled = self._handle_terminal_method(
                                method, params, terminals, terminal_counter_ref, log
                            )
                            terminal_counter = terminal_counter_ref[0]
                            if handled:
                                send_response(req_id, result)
                            else:
                                if req_id is not None:
                                    send_response(req_id, {})

                        else:
                            # Unknown method - send empty response if it has an ID
                            if req_id is not None:
                                send_response(req_id, {})

                except Exception as e:
                    self.call_from_thread(self._show_thinking_line, f"⚠️ Read error: {e}", log)
                    break

            # Cleanup terminals
            self._cleanup_terminals(terminals)

            self._agent_process = None
            self.call_from_thread(self._stop_stream_animation)

            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

            duration = monotonic() - start_time
            self._is_first_message = False

            # Compute file diffs for modified files
            file_diffs = self._compute_file_diffs(files_modified)

            # Build summary
            action_summary = {
                "tool_count": len(tool_actions),
                "files_modified": files_modified,
                "files_read": files_read,
                "duration": duration,
                "file_diffs": file_diffs,  # NEW: Store diff data
            }

            # Show final response
            if text_parts:
                response_text = "".join(text_parts)
                if response_text.strip():
                    self.call_from_thread(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self.call_from_thread(
                        self._show_completion_summary, display_name, action_summary, log
                    )
            elif not self._cancel_requested:
                self.call_from_thread(
                    self._show_completion_summary, display_name, action_summary, log
                )

        except FileNotFoundError:
            self._agent_process = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(log.add_error, "❌ codex-acp not found. Install it first:")
            self.call_from_thread(log.add_info, "  npm install -g @openai/codex")
            self.call_from_thread(log.add_info, "  or npx @openai/codex-acp")
        except Exception as e:
            self._agent_process = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(log.add_error, f"❌ Error: {str(e)}")

    def _run_openhands_acp(
        self,
        message: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ):
        """
        Run OpenHands using the ACP protocol.

        OpenHands uses full bidirectional JSON-RPC protocol via `openhands acp`.
        """
        import subprocess
        import json
        from time import monotonic

        try:
            start_time = monotonic()

            # Build command - openhands acp
            cmd = ["openhands", "acp"]

            model_display = (
                f"openhands/{model}" if model and model != "default" else "openhands/default"
            )

            # Show info with approval mode
            mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
                self.approval_mode, "🟡 ASK"
            )
            session_type = "new session" if self._is_first_message else "continuing session"
            self.call_from_thread(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self.call_from_thread(
                    log.add_info, f"🎭 Persona active: {persona_context.role_name}"
                )

            # Build environment
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
            }

            # Start process with bidirectional communication
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd(),
                text=True,
                bufsize=1,
                env=env,
            )

            # Store process reference for cancellation
            self._agent_process = process

            # Stop thinking, start streaming animation
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._start_stream_animation, log)

            # Show header
            self.call_from_thread(
                self._show_agent_header_with_model, display_name, model_display, log
            )

            # Collect output
            text_parts = []
            tool_actions = []
            files_modified = []
            files_read = []

            # Terminal tracking for this session
            terminals = {}
            terminal_counter = 0

            # JSON-RPC request ID counter
            request_id = 0
            session_id = None

            def send_request(method: str, params: dict = None) -> int:
                """Send a JSON-RPC request to the agent."""
                nonlocal request_id
                request_id += 1
                request = {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params or {},
                    "id": request_id,
                }
                try:
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                except Exception as e:
                    self.call_from_thread(self._show_thinking_line, f"⚠️ Send error: {e}", log)
                return request_id

            def send_response(req_id: int, result: dict):
                """Send a JSON-RPC response to the agent."""
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": req_id,
                }
                try:
                    process.stdin.write(json.dumps(response) + "\n")
                    process.stdin.flush()
                except Exception:
                    pass

            # Step 1: Initialize the protocol
            self.call_from_thread(self._show_thinking_line, "🔌 Initializing ACP protocol...", log)
            send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": True, "writeTextFile": True},
                        "terminal": True,
                    },
                    "clientInfo": {
                        "name": "SuperQode",
                        "title": "SuperQode - Multi-Agent Coding Team",
                        "version": "0.1.0",
                    },
                },
            )

            # Read and process messages
            pending_requests = {}
            initialized = False
            session_created = False
            prompt_sent = False

            while True:
                if self._cancel_requested:
                    process.terminate()
                    self.call_from_thread(log.add_info, "🛑 Agent operation cancelled")
                    break

                # Read a line from stdout
                try:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if not line:
                        continue

                    line = line.strip()
                    if not line:
                        continue

                    # Parse JSON-RPC message
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        # Not JSON - might be debug output
                        if line and not line.startswith("Loaded"):
                            self.call_from_thread(self._show_thinking_line, f"📋 {line}", log)
                        continue

                    # Handle response to our request
                    if "result" in msg or "error" in msg:
                        msg_id = msg.get("id")

                        if "error" in msg:
                            error = msg["error"]
                            error_msg = error.get("message", "Unknown error")
                            self.call_from_thread(log.add_error, f"❌ ACP Error: {error_msg}")
                            break

                        result = msg.get("result", {})

                        # Handle initialize response
                        if not initialized:
                            initialized = True
                            agent_info = result.get("agentInfo", {})
                            agent_name = agent_info.get("title", "OpenHands")
                            self.call_from_thread(
                                self._show_thinking_line, f"✅ Connected to {agent_name}", log
                            )

                            # Step 2: Create a new session
                            send_request(
                                "session/new",
                                {
                                    "cwd": os.getcwd(),
                                    "mcpServers": [],
                                },
                            )
                            continue

                        # Handle session/new response
                        if not session_created:
                            session_id = result.get("sessionId", "")
                            session_created = True

                            # Check available models
                            models = result.get("models", {})
                            available_models = models.get("availableModels", [])
                            if available_models:
                                model_names = [
                                    m.get("name", m.get("modelId", ""))
                                    for m in available_models[:3]
                                ]
                                self.call_from_thread(
                                    self._show_thinking_line,
                                    f"📊 Models: {', '.join(model_names)}",
                                    log,
                                )

                            self.call_from_thread(
                                self._show_thinking_line, f"🚀 Session started", log
                            )

                            # Step 3: Send the prompt
                            send_request(
                                "session/prompt",
                                {
                                    "sessionId": session_id,
                                    "prompt": [{"type": "text", "text": message}],
                                },
                            )
                            prompt_sent = True
                            continue

                        # Handle prompt response (completion)
                        if prompt_sent:
                            stop_reason = result.get("stopReason", "end_turn")
                            self.call_from_thread(
                                self._show_thinking_line, f"✅ Completed ({stop_reason})", log
                            )
                            break

                    # Handle request from agent (notifications/requests)
                    elif "method" in msg:
                        method = msg.get("method", "")
                        params = msg.get("params", {})
                        req_id = msg.get("id")

                        # Handle OpenHands-specific metadata
                        _meta = params.get("_meta", {})
                        if _meta:
                            field_meta = _meta.get("field_meta", {})
                            if oh_metrics := field_meta.get("openhands.dev/metrics"):
                                status_line = oh_metrics.get("status_line", "")
                                if status_line:
                                    self.call_from_thread(
                                        self._show_thinking_line, f"📊 {status_line}", log
                                    )

                        if method == "session/update":
                            # Handle session updates (streaming content)
                            update = params.get("update", params)
                            update_type = update.get("sessionUpdate", "")

                            if update_type == "agent_message_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    text_parts.append(text)
                                    # Show full text, no truncation
                                    self.call_from_thread(
                                        self._show_thinking_line, f"💬 {text}", log
                                    )

                            elif update_type == "agent_thought_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    # Show full thinking text, no truncation
                                    self.call_from_thread(
                                        self._show_thinking_line, f"🧠 {text}", log
                                    )

                            elif update_type == "tool_call":
                                tool_id = update.get("toolCallId", "")
                                title = update.get("title", "")
                                raw_input = update.get("rawInput", {})
                                status = update.get("status", "")

                                # Track tool_id to title mapping for detailed logging
                                if not hasattr(self, "_tool_id_map"):
                                    self._tool_id_map = {}
                                self._tool_id_map[tool_id] = {"title": title, "input": raw_input}

                                tool_actions.append({"tool": title, "input": raw_input})

                                # Track files
                                file_path = raw_input.get("path", raw_input.get("filePath", ""))
                                if file_path:
                                    kind = update.get("kind", "")
                                    if kind in ("edit", "write", "delete"):
                                        if file_path not in files_modified:
                                            files_modified.append(file_path)
                                    elif kind == "read":
                                        if file_path not in files_read:
                                            files_read.append(file_path)

                                msg_text = self._format_tool_message_rich(title, raw_input)
                                self.call_from_thread(self._show_thinking_line, msg_text, log)

                            elif update_type == "tool_call_update":
                                tool_id = update.get("toolCallId", "")
                                status = update.get("status", "")
                                output = update.get("output", update.get("result", ""))
                                # Get tool info from our tracking map
                                tool_info = getattr(self, "_tool_id_map", {}).get(tool_id, {})
                                tool_title = tool_info.get("title", "Tool")
                                if status == "completed":
                                    if output:
                                        output_str = str(output)
                                        # Show full output, no truncation
                                        self.call_from_thread(
                                            self._show_thinking_line,
                                            f"✅ {tool_title}: {output_str}",
                                            log,
                                        )
                                    else:
                                        self.call_from_thread(
                                            self._show_thinking_line,
                                            f"✅ {tool_title} completed",
                                            log,
                                        )
                                elif status == "failed":
                                    # Show full error message, no truncation
                                    error_msg = str(output) if output else "failed"
                                    self.call_from_thread(
                                        self._show_thinking_line,
                                        f"❌ {tool_title} failed: {error_msg}",
                                        log,
                                    )

                            elif update_type == "plan":
                                entries = update.get("entries", [])
                                if entries:
                                    self.call_from_thread(
                                        self._show_thinking_line,
                                        f"📋 Plan: {len(entries)} tasks",
                                        log,
                                    )

                        elif method == "session/request_permission":
                            # Handle permission request
                            options = params.get("options", [])
                            tool_call = params.get("toolCall", {})
                            tool_name = tool_call.get("title", "unknown")
                            tool_input = tool_call.get("rawInput", {})

                            # Handle based on approval mode
                            if self.approval_mode == "deny":
                                # Reject
                                self.call_from_thread(
                                    self._show_thinking_line,
                                    f"🔴 BLOCKED: {tool_name} (DENY mode)",
                                    log,
                                )
                                reject_option = next(
                                    (o for o in options if o.get("kind") == "reject_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": reject_option.get("optionId", ""),
                                        }
                                    },
                                )
                            elif self.approval_mode == "auto":
                                # Auto-allow
                                allow_option = next(
                                    (o for o in options if o.get("kind") == "allow_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": allow_option.get("optionId", ""),
                                        }
                                    },
                                )
                                self.call_from_thread(
                                    self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log
                                )
                            else:
                                # ASK mode - check if needs permission
                                needs_permission = self._tool_needs_permission(
                                    tool_name, tool_input
                                )
                                if needs_permission:
                                    self.call_from_thread(
                                        self._show_permission_prompt, tool_name, tool_input, log
                                    )
                                    self._permission_pending = True
                                    self._permission_response = None

                                    wait_start = monotonic()
                                    timeout = 60
                                    while (
                                        self._permission_pending
                                        and (monotonic() - wait_start) < timeout
                                    ):
                                        if self._cancel_requested:
                                            self._permission_pending = False
                                            break
                                        time.sleep(0.1)

                                    if (
                                        self._permission_response == "deny"
                                        or self._permission_response is None
                                    ):
                                        reject_option = next(
                                            (o for o in options if o.get("kind") == "reject_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": reject_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self.call_from_thread(log.add_info, f"Denied: {tool_name}")
                                    else:
                                        allow_option = next(
                                            (o for o in options if o.get("kind") == "allow_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": allow_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self.call_from_thread(
                                            self._show_thinking_line,
                                            f"✅ Allowed: {tool_name}",
                                            log,
                                        )
                                        if self._permission_response == "allow_all":
                                            self.approval_mode = "auto"
                                            self.call_from_thread(self._sync_approval_mode)
                                else:
                                    # Auto-allow safe operations
                                    allow_option = next(
                                        (o for o in options if o.get("kind") == "allow_once"),
                                        options[0] if options else {"optionId": ""},
                                    )
                                    send_response(
                                        req_id,
                                        {
                                            "outcome": {
                                                "outcome": "selected",
                                                "optionId": allow_option.get("optionId", ""),
                                            }
                                        },
                                    )

                        elif method == "fs/read_text_file":
                            # Handle file read request
                            path = params.get("path", "")
                            if path not in files_read:
                                files_read.append(path)

                            try:
                                read_path = Path(os.getcwd()) / path
                                content = read_path.read_text(encoding="utf-8", errors="ignore")
                                send_response(req_id, {"content": content})
                            except Exception:
                                send_response(req_id, {"content": ""})

                        elif method == "fs/write_text_file":
                            # Handle file write request
                            path = params.get("path", "")
                            content = params.get("content", "")

                            if path not in files_modified:
                                files_modified.append(path)

                            try:
                                write_path = Path(os.getcwd()) / path
                                write_path.parent.mkdir(parents=True, exist_ok=True)
                                write_path.write_text(content, encoding="utf-8")
                                send_response(req_id, {})
                            except Exception as e:
                                send_response(req_id, {"error": str(e)})

                        elif method.startswith("terminal/"):
                            # Handle terminal methods using helper
                            terminal_counter_ref = [terminal_counter]
                            result, handled = self._handle_terminal_method(
                                method, params, terminals, terminal_counter_ref, log
                            )
                            terminal_counter = terminal_counter_ref[0]
                            if handled:
                                send_response(req_id, result)
                            else:
                                if req_id is not None:
                                    send_response(req_id, {})

                        else:
                            # Unknown method - send empty response if it has an ID
                            if req_id is not None:
                                send_response(req_id, {})

                except Exception as e:
                    self.call_from_thread(self._show_thinking_line, f"⚠️ Read error: {e}", log)
                    break

            # Cleanup terminals
            self._cleanup_terminals(terminals)

            self._agent_process = None
            self.call_from_thread(self._stop_stream_animation)

            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

            duration = monotonic() - start_time
            self._is_first_message = False

            # Compute file diffs for modified files
            file_diffs = self._compute_file_diffs(files_modified)

            # Build summary
            action_summary = {
                "tool_count": len(tool_actions),
                "files_modified": files_modified,
                "files_read": files_read,
                "duration": duration,
                "file_diffs": file_diffs,  # NEW: Store diff data
            }

            # Show final response
            if text_parts:
                response_text = "".join(text_parts)
                if response_text.strip():
                    self.call_from_thread(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self.call_from_thread(
                        self._show_completion_summary, display_name, action_summary, log
                    )
            elif not self._cancel_requested:
                self.call_from_thread(
                    self._show_completion_summary, display_name, action_summary, log
                )

        except FileNotFoundError:
            self._agent_process = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(log.add_error, "❌ openhands not found. Install it first:")
            self.call_from_thread(log.add_info, "  uv tool install openhands -U --python 3.12")
            self.call_from_thread(log.add_info, "  openhands login")
        except Exception as e:
            self._agent_process = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(log.add_error, f"❌ Error: {str(e)}")

    # ========================================================================
    # Permission Handling
    # ========================================================================

    def _is_permission_request(self, line: str) -> bool:
        """Check if a line is a permission request from the agent."""
        permission_keywords = [
            "permission",
            "allow",
            "approve",
            "confirm",
            "run command",
            "execute",
            "write file",
            "delete",
            "y/n",
            "[y/N]",
            "[Y/n]",
            "(yes/no)",
            "allow?",
            "proceed",
            "continue?",
        ]
        line_lower = line.lower()
        return any(kw in line_lower for kw in permission_keywords)

    def _send_permission_response(self, process, response: str):
        """Send a permission response to the process."""
        try:
            if process.stdin:
                process.stdin.write(f"{response}\n")
                process.stdin.flush()
        except Exception:
            pass

    def _get_tool_signature(self, tool_name: str, tool_input: dict) -> str:
        """Generate a unique signature for a tool call to track approvals."""
        # Create a signature from tool name and key parameters
        file_path = tool_input.get("filePath", tool_input.get("path", tool_input.get("file", "")))
        command = tool_input.get("command", "")
        key = f"{tool_name}:{file_path or command}"
        return key

    def _ensure_approved_tools(self) -> set:
        """Ensure _approved_tools is initialized and return it.

        This helper method ensures the _approved_tools set always exists,
        preventing AttributeError when approval mode is set to 'ask'.
        """
        if not hasattr(self, "_approved_tools"):
            self._approved_tools = set()
        return self._approved_tools

    def _tool_needs_permission(self, tool_name: str, tool_input: dict) -> bool:
        """Check if a tool call needs user permission.

        Returns True if permission is needed:
        - External tools (web, fetch, etc.)
        - File operations outside current project directory
        - Bash commands that might affect system

        Returns False (auto-allow) for:
        - Read operations within project
        - Write/edit operations within project directory
        - Search/list operations within project
        - Tools that have already been approved in this session
        """
        # Ensure _approved_tools is initialized
        approved_tools = self._ensure_approved_tools()

        # Check if this tool was already approved in this session
        tool_sig = self._get_tool_signature(tool_name, tool_input)
        if tool_sig in approved_tools:
            return False

            # Also check _pending_tool_id patterns in approved tools
        if approved_tools:
            # Check if any approved tool matches this one (by tool name prefix)
            for approved in approved_tools:
                if approved and approved.startswith(f"{tool_name}:"):
                    # Same tool type was approved before - allow similar calls
                    return False

        tool_lower = tool_name.lower()
        cwd = os.getcwd()

        # External tools always need permission
        external_tools = ("web", "fetch", "http", "curl", "wget", "browser", "url")
        if any(ext in tool_lower for ext in external_tools):
            return True

        # Get file path from tool input
        file_path = tool_input.get("filePath", tool_input.get("path", tool_input.get("file", "")))

        if file_path:
            # Resolve to absolute path
            try:
                abs_path = os.path.abspath(file_path)
                # Check if file is within current working directory
                if abs_path.startswith(cwd):
                    # File is within project - auto-allow
                    return False
                else:
                    # File is outside project - needs permission
                    return True
            except Exception:
                # If we can't resolve path, ask for permission
                return True

        # Bash/shell commands - check if they might affect outside project
        if tool_lower in ("bash", "shell", "terminal", "exec", "run"):
            command = tool_input.get("command", "")
            # Dangerous commands that might affect system
            dangerous_patterns = (
                "sudo",
                "rm -rf /",
                "chmod",
                "chown",
                "mkfs",
                "dd ",
                "curl",
                "wget",
                "> /",
                ">> /",
                "/etc/",
                "/usr/",
                "/var/",
                "/home/",
                "~/",
            )
            if any(pattern in command for pattern in dangerous_patterns):
                return True
            # Even commands within project should ask for permission in ASK mode
            return True

        # Read operations - auto-allow
        if tool_lower in ("read", "cat", "head", "tail", "less", "view"):
            return False

        # Search/list operations - auto-allow
        if tool_lower in ("search", "grep", "find", "list", "ls", "glob", "tree"):
            return False

        # Write/edit within project - ask for permission (side effects)
        if tool_lower in ("write", "edit", "patch", "create", "mkdir"):
            return True

        # Unknown tools - ask for permission to be safe
        return True

    def _show_permission_prompt(self, tool_name: str, tool_input: dict, log: ConversationLog):
        """Show interactive permission prompt for ASK mode."""
        # Store the pending tool info for later use when approved
        self._pending_tool_name = tool_name
        self._pending_tool_input = tool_input

        # Calculate the reason for permission
        reason = ""
        file_path = tool_input.get("filePath", tool_input.get("path", tool_input.get("file", "")))
        if file_path and not os.path.abspath(file_path).startswith(os.getcwd()):
            reason = "Outside project directory"
        elif tool_name.lower() in ("web", "fetch", "http", "curl", "wget", "browser"):
            reason = "External network access"
        elif tool_name.lower() in ("bash", "shell", "terminal"):
            reason = "System command"

        # Show modal permission dialog instead of inline prompt
        self._show_permission_modal(tool_name, tool_input, reason)

    def _show_permission_modal(self, tool_name: str, tool_input: dict, reason: str):
        """Show a modal permission dialog for ASK mode."""
        from textual.screen import ModalScreen
        from textual.containers import Container, Vertical, Horizontal
        from textual.widgets import Static, Button

        class TUIPermissionScreen(ModalScreen[str]):
            """Modal screen for TUI permission requests."""

            CSS = """
            TUIPermissionScreen {
                align: center middle;
            }

            #permission-dialog {
                width: 38;
                height: auto;
                max-height: 12;
                background: #000000;
                border: tall #ffffff;
                padding: 0 1;
            }

            #permission-title {
                text-align: center;
                color: #ffffff;
                margin-bottom: 0;
                height: 1;
                text-style: bold;
            }

            #permission-content {
                height: auto;
                max-height: 4;
                overflow-y: auto;
                margin-bottom: 0;
                padding: 0;
                background: transparent;
                border: none;
            }

            #permission-buttons {
                height: auto;
                align: center middle;
                margin-top: 0;
            }

            .permission-btn {
                margin: 0 1;
                min-width: 8;
                background: #333333;
                border: tall #ffffff;
                color: #ffffff;
            }

            .permission-btn:hover {
                background: #666666;
                border: tall #ffffff;
                color: #ffffff;
            }

            .allow-btn {
                background: #333333;
                color: #ffffff;
            }

            .allow-btn:hover {
                background: #666666;
                color: #ffffff;
            }

            .deny-btn {
                background: #333333;
                color: #ffffff;
            }

            .deny-btn:hover {
                background: #666666;
                color: #ffffff;
            }

            .allow-all-btn {
                background: #333333;
                color: #ffffff;
            }

            .allow-all-btn:hover {
                background: #666666;
                color: #ffffff;
            }

            #permission-hints {
                text-align: center;
                color: #cccccc;
                margin-top: 0;
                height: 1;
                text-style: dim;
            }
            """

            def __init__(self, tool_name: str, tool_input: dict, reason: str):
                super().__init__()
                self.tool_name = tool_name
                self.tool_input = tool_input
                self.reason = reason

            def compose(self):
                from rich.text import Text

                with Container(id="permission-dialog"):
                    # Title (subtle, no emoji)
                    title = f"{self.tool_name}"
                    if self.reason:
                        title += f" • {self.reason}"
                    yield Static(title, id="permission-title")

                    # Content (simplified)
                    content = self._format_permission_content()
                    yield Static(content, id="permission-content")

                    # Buttons (subtle, full text)
                    with Horizontal(id="permission-buttons"):
                        yield Button("yes", id="btn-allow", classes="permission-btn allow-btn")
                        yield Button("no", id="btn-deny", classes="permission-btn deny-btn")
                        yield Button(
                            "allow", id="btn-allow-all", classes="permission-btn allow-all-btn"
                        )

                    # Hints (very subtle)
                    yield Static("[y/n/a]", id="permission-hints")

            def _format_permission_content(self):
                """Format the permission request content."""
                from rich.text import Text

                t = Text()

                # Show only essential info - first parameter if available (high contrast white text)
                if self.tool_input:
                    # Show first 1-2 key parameters
                    items = list(self.tool_input.items())[:2]
                    for key, value in items:
                        val_str = str(value)
                        if len(val_str) > 25:
                            val_str = val_str[:22] + "..."
                        t.append(f"{key}: ", style="#ffffff")
                        t.append(f"{val_str}", style="#cccccc")
                        if key != items[-1][0]:  # Add separator if not last item
                            t.append(" • ", style="#888888")

                return t

            def on_button_pressed(self, event):
                """Handle button presses."""
                button_id = event.button.id

                if button_id == "btn-allow":
                    self.dismiss("allow")
                elif button_id == "btn-deny":
                    self.dismiss("deny")
                elif button_id == "btn-allow-all":
                    self.dismiss("allow_all")

            def on_key(self, event):
                """Handle key presses."""
                if event.key == "y":
                    self.dismiss("allow")
                elif event.key == "n":
                    self.dismiss("deny")
                elif event.key == "a":
                    self.dismiss("allow_all")
                elif event.key == "escape":
                    self.dismiss("")

        # Show the modal and handle the result
        def on_modal_result(result: str):
            self._handle_modal_permission_result(result)
            # Return focus to input after modal is dismissed
            self.set_timer(0.1, self._ensure_input_focus)

        screen = TUIPermissionScreen(tool_name, tool_input, reason)
        self.push_screen(screen, on_modal_result)

    def _handle_modal_permission_result(self, result: str):
        """Handle the result from the modal permission dialog."""
        if not result:
            # Cancelled
            self._permission_response = "deny"
        elif result == "allow":
            self._permission_response = "allow"
            # Add to approved tools to prevent duplicate prompts
            approved_tools = self._ensure_approved_tools()
            if hasattr(self, "_pending_tool_name") and hasattr(self, "_pending_tool_input"):
                tool_sig = self._get_tool_signature(
                    self._pending_tool_name, self._pending_tool_input or {}
                )
                approved_tools.add(tool_sig)
            # Show confirmation
            try:
                log = self.query_one("#log", ConversationLog)
                log.add_info("Approved")
            except Exception:
                pass
        elif result == "deny":
            self._permission_response = "deny"
            try:
                log = self.query_one("#log", ConversationLog)
                log.add_info("Denied")
            except Exception:
                pass
        elif result == "allow_all":
            self._permission_response = "allow_all"
            # Add to approved tools
            approved_tools = self._ensure_approved_tools()
            if hasattr(self, "_pending_tool_name") and hasattr(self, "_pending_tool_input"):
                tool_sig = self._get_tool_signature(
                    self._pending_tool_name, self._pending_tool_input or {}
                )
                approved_tools.add(tool_sig)
            try:
                log = self.query_one("#log", ConversationLog)
                log.add_info("All tools approved (AUTO mode)")
            except Exception:
                pass

        # Clear permission state
        self._permission_pending = False
        self._reset_input_placeholder()

    def _start_permission_pulse(self):
        """Start pulsing animation on input box to draw attention."""
        self._permission_pulse_frame = 0
        if hasattr(self, "_permission_pulse_timer") and self._permission_pulse_timer:
            self._permission_pulse_timer.stop()
        self._permission_pulse_timer = self.set_interval(0.4, self._update_permission_pulse)

    def _stop_permission_pulse(self):
        """Stop the permission pulse animation."""
        if hasattr(self, "_permission_pulse_timer") and self._permission_pulse_timer:
            self._permission_pulse_timer.stop()
            self._permission_pulse_timer = None
        # Reset input box style
        try:
            input_box = self.query_one("#input-box")
            input_box.styles.border = ("tall", "#1a1a1a")
        except Exception:
            pass

    def _update_permission_pulse(self):
        """Update the pulsing animation on input box."""
        if not self._permission_pending:
            self._stop_permission_pulse()
            return

        self._permission_pulse_frame = getattr(self, "_permission_pulse_frame", 0) + 1

        # Smooth gradient through warm colors
        colors = ["#f59e0b", "#fbbf24", "#f97316", "#fbbf24"]
        color = colors[self._permission_pulse_frame % len(colors)]

        try:
            input_box = self.query_one("#input-box")
            input_box.styles.border = ("tall", color)
        except Exception:
            pass

    def _handle_permission_input(self, response: str) -> bool:
        """Handle permission input from user. Returns True if handled."""
        if not self._permission_pending:
            return False

        response = response.strip().lower()

        if response in ("y", "yes", "allow", "ok"):
            self._permission_response = "allow"
            self._permission_pending = False
            # Add to approved tools to prevent duplicate prompts
            approved_tools = self._ensure_approved_tools()
            if hasattr(self, "_pending_tool_name") and hasattr(self, "_pending_tool_input"):
                tool_sig = self._get_tool_signature(
                    self._pending_tool_name, self._pending_tool_input or {}
                )
                approved_tools.add(tool_sig)
            # Show confirmation in log
            try:
                log = self.query_one("#log", ConversationLog)
                log.add_info("Approved")
            except Exception:
                pass
            return True
        elif response in ("n", "no", "deny", "reject"):
            self._permission_response = "deny"
            self._permission_pending = False
            try:
                log = self.query_one("#log", ConversationLog)
                log.add_info("Denied")
            except Exception:
                pass
            return True
        elif response in ("a", "all", "allow all", "yes all"):
            self._permission_response = "allow_all"
            self._permission_pending = False
            # Add to approved tools
            approved_tools = self._ensure_approved_tools()
            if hasattr(self, "_pending_tool_name") and hasattr(self, "_pending_tool_input"):
                tool_sig = self._get_tool_signature(
                    self._pending_tool_name, self._pending_tool_input or {}
                )
                approved_tools.add(tool_sig)
            try:
                log = self.query_one("#log", ConversationLog)
                log.add_info("All tools approved (AUTO mode)")
            except Exception:
                pass
            return True

        return False

    def _reset_input_placeholder(self):
        """Reset input placeholder to default and stop any animations."""
        # Stop permission pulse animation
        self._stop_permission_pulse()

        # Reset approval notification flag
        self._approval_notification_shown = False

        # Reset input box border explicitly
        try:
            input_box = self.query_one("#input-box")
            input_box.styles.border = ("tall", "#1a1a1a")
        except Exception:
            pass

        try:
            input_widget = self.query_one("#prompt-input", Input)
            input_widget.placeholder = "Ask anything or type : for commands..."
        except Exception:
            pass

    def _show_permission_auto_approved(self, line: str, log: ConversationLog):
        """Show permission auto-approved (AUTO mode)."""
        t = Text()
        t.append("  🟢 ", style="#22c55e")
        t.append(f"{line}", style="#a1a1aa")
        t.append(" → ", style="#52525b")
        t.append("AUTO-APPROVED\n", style="bold #22c55e")
        log.write(t)

    def _show_permission_denied(self, line: str, log: ConversationLog):
        """Show permission denied (DENY mode)."""
        t = Text()
        t.append("  🔴 ", style="#ef4444")
        t.append(f"{line}", style="#a1a1aa")
        t.append(" → ", style="#52525b")
        t.append("DENIED\n", style="bold #ef4444")
        log.write(t)

    def _show_permission_ask(self, line: str, log: ConversationLog):
        """Show permission request in ASK mode - shows indicator but allows operation."""
        t = Text()
        t.append(
            "\n  ╭─────────────────────────────────────────────────────────╮\n", style="#f59e0b"
        )
        t.append("  │  🟡 ", style="#f59e0b")
        t.append("TOOL CALL (ASK MODE)", style="bold #f59e0b")
        t.append("                             │\n", style="#f59e0b")
        t.append("  ├─────────────────────────────────────────────────────────┤\n", style="#f59e0b")

        # Don't truncate - show full line (wrap if needed)
        # Split long lines into multiple lines to show everything
        display_line = line
        # Calculate available width (use terminal width or large value)
        import shutil

        try:
            term_width = shutil.get_terminal_size().columns
            available_width = max(term_width - 10, 100)  # Leave some margin
        except Exception:
            available_width = 200  # Large fallback

        # If line is longer than available width, split it into multiple lines
        if len(display_line) > available_width:
            # Split into chunks and display each on a new line
            chunks = [
                display_line[i : i + available_width]
                for i in range(0, len(display_line), available_width)
            ]
            for i, chunk in enumerate(chunks):
                padding = max(0, available_width - len(chunk))
                t.append(f"  │  {chunk}{' ' * padding}│\n", style="#e4e4e7")
        else:
            padding = max(0, available_width - len(display_line))
            t.append(f"  │  {display_line}{' ' * padding}│\n", style="#e4e4e7")

        t.append("  ├─────────────────────────────────────────────────────────┤\n", style="#f59e0b")
        t.append("  │  ", style="#f59e0b")
        t.append("✅ Allowed", style="#22c55e")
        t.append(" (use :mode deny to block destructive ops) │\n", style="#71717a")
        t.append("  ╰─────────────────────────────────────────────────────────╯\n", style="#f59e0b")
        log.write(t)

    # Keep old methods for compatibility
    def _show_permission_alert(self, line: str, log: ConversationLog):
        """Show a permission alert to the user (legacy)."""
        self._show_permission_ask(line, log)

    def _handle_permission_auto(self, process, line: str):
        """Auto-handle permission requests (legacy)."""
        self._send_permission_response(process, "y")

    def _show_agent_header_with_model(self, name: str, model: str, log: ConversationLog):
        """Show agent output header with model information and approval mode.

        SuperQode style: Quantum-inspired, minimal, clean.
        """
        header = Text()
        header.append("\n")

        # Gradient line using SuperQode purple palette
        line = "─" * 60
        for i, char in enumerate(line):
            color = GRADIENT_PURPLE[i % len(GRADIENT_PURPLE)]
            header.append(char, style=color)
        header.append("\n")

        # Agent name with quantum icon (no emoji)
        header.append(f"  ◈ ", style=f"bold {SQ_COLORS.primary}")
        header.append(f"{name.upper()} ", style=f"bold {SQ_COLORS.text_primary}")
        header.append("is working", style=SQ_COLORS.text_muted)
        header.append("\n")

        # Model info
        header.append(f"  Model: ", style=SQ_COLORS.text_dim)
        header.append(f"{model}", style=f"bold {SQ_COLORS.info}")
        header.append("  │  ", style=SQ_COLORS.text_ghost)

        # Show approval mode indicator (using ● instead of colored circles emoji)
        mode_colors = {"auto": SQ_COLORS.success, "ask": SQ_COLORS.warning, "deny": SQ_COLORS.error}
        mode_labels = {"auto": "AUTO", "ask": "ASK", "deny": "DENY"}

        mode = getattr(self, "approval_mode", "ask")
        color = mode_colors.get(mode, SQ_COLORS.warning)
        label = mode_labels.get(mode, "ASK")

        header.append("● ", style=f"bold {color}")
        header.append(f"{label}", style=f"bold {color}")
        header.append("\n")
        header.append(f"  [Ctrl+T] hide logs  ", style=SQ_COLORS.text_ghost)
        header.append("[Esc] cancel  ", style=SQ_COLORS.text_ghost)
        header.append("[Ctrl+Z] undo\n", style=SQ_COLORS.text_ghost)
        log.write(header)

        # Create checkpoint before agent operation
        self._create_checkpoint_before_agent(f"{name} operation")

    def _show_agent_header(self, name: str, log: ConversationLog):
        """Show agent output header."""
        header = Text()
        header.append("\n")
        # Simple gradient line
        line = "━" * 50
        gradient = ["#a855f7", "#c026d3", "#d946ef", "#ec4899"]
        for i, char in enumerate(line):
            header.append(char, style=gradient[i % len(gradient)])
        header.append("\n")
        header.append(f"  🤖 ", style="#a855f7")
        header.append(f"{name.upper()} ", style="bold #a855f7")
        header.append("is working...", style="#71717a")
        header.append("  [Ctrl+T to hide logs]  [Esc to cancel]\n", style="#52525b")
        log.write(header)

    def _format_tool_message(self, tool_name: str, tool_input: dict) -> str:
        """Format a tool use message with permission indicator based on approval mode."""
        # Check if this is a destructive operation
        is_destructive = tool_name.lower() in (
            "write",
            "edit",
            "bash",
            "shell",
            "terminal",
            "delete",
            "rm",
        )

        # Get tool icon
        tool_icons = {
            "read": "📖",
            "write": "✏️",
            "edit": "✏️",
            "bash": "💻",
            "shell": "💻",
            "terminal": "💻",
            "search": "🔍",
            "grep": "🔍",
            "find": "🔍",
            "list": "📁",
            "ls": "📁",
            "glob": "📁",
            "git": "📦",
            "fetch": "🌐",
            "web": "🌐",
        }
        icon = "🔧"
        for key, emoji in tool_icons.items():
            if key in tool_name.lower():
                icon = emoji
                break

        # Format tool message
        if tool_name == "read" and "filePath" in tool_input:
            file_path = tool_input["filePath"]
            if len(file_path) > 50:
                file_path = "..." + file_path[-47:]
            msg = f"{icon} Reading: {file_path}"
        elif tool_name == "write" and "filePath" in tool_input:
            file_path = tool_input["filePath"]
            if len(file_path) > 50:
                file_path = "..." + file_path[-47:]
            msg = f"{icon} Writing: {file_path}"
        elif tool_name == "edit" and "filePath" in tool_input:
            file_path = tool_input["filePath"]
            if len(file_path) > 50:
                file_path = "..." + file_path[-47:]
            msg = f"{icon} Editing: {file_path}"
        elif tool_name in ("bash", "shell", "terminal"):
            cmd = tool_input.get("command", "")
            if len(cmd) > 50:
                cmd = cmd[:47] + "..."
            msg = f"{icon} Running: {cmd}"
        elif tool_name in ("search", "grep"):
            pattern = tool_input.get("pattern", tool_input.get("query", ""))
            if len(pattern) > 30:
                pattern = pattern[:27] + "..."
            msg = f"{icon} Searching: {pattern}"
        elif tool_name in ("list", "ls", "glob"):
            path = tool_input.get("path", tool_input.get("directory", "."))
            msg = f"{icon} Listing: {path}"
        else:
            # Generic tool message
            msg = f"{icon} {tool_name}"
            if tool_input:
                first_key = list(tool_input.keys())[0] if tool_input else None
                if first_key:
                    val = str(tool_input[first_key])[:30]
                    msg = f"{icon} {tool_name}: {val}"

        # Add permission indicator for destructive operations
        if is_destructive:
            mode = getattr(self, "approval_mode", "ask")
            if mode == "auto":
                msg = f"🟢 {msg}"
            elif mode == "ask":
                msg = f"🟡 {msg}"
            elif mode == "deny":
                msg = f"🔴 {msg}"

        return msg

    def _format_tool_output(self, tool_name: str, output: Any, log: ConversationLog) -> bool:
        """Format and display tool output with proper JSON parsing.

        Returns True if output was formatted and displayed, False otherwise.
        """
        import json

        if not output:
            return False

        output_str = str(output)

        # Try to parse as JSON
        try:
            # Check if it looks like JSON
            stripped = output_str.strip()
            if not stripped.startswith("{") and not stripped.startswith("["):
                return False

            data = json.loads(output_str)

            tool_lower = tool_name.lower()

            # Handle TODO/Task lists
            if "todo" in tool_lower or self._is_todo_list(data):
                self._display_todo_list(data, log)
                return True

            # Handle file search results (glob, grep, search)
            if any(x in tool_lower for x in ("glob", "search", "grep", "find")):
                self._display_file_results(data, tool_name, log)
                return True

            # Handle task lists (Claude Code style)
            if "task" in tool_lower and isinstance(data, list):
                self._display_task_list(data, log)
                return True

            # Handle errors
            if isinstance(data, dict) and ("error" in data or "errors" in data):
                self._display_error_result(data, log)
                return True

            # Handle plan entries
            if isinstance(data, list) and data and isinstance(data[0], dict) and "step" in data[0]:
                self._display_plan(data, log)
                return True

            # Handle generic success/result dicts
            if isinstance(data, dict) and ("success" in data or "result" in data or "ok" in data):
                self._display_success_result(data, tool_name, log)
                return True

            # For other JSON, show formatted
            if isinstance(data, list):
                if len(data) <= 10:
                    self._display_generic_list(data, tool_name, log)
                else:
                    # Truncate large lists
                    summary = f"[{len(data)} items] " + str(data[:3])[:-1] + ", ...]"
                    self.call_from_thread(log.add_tool_call, tool_name, "success", "", "", summary)
                return True
            elif isinstance(data, dict):
                if len(data) <= 6:
                    self._display_generic_dict(data, tool_name, log)
                else:
                    # Truncate large dicts
                    summary = f"{{... {len(data)} keys ...}}"
                    self.call_from_thread(log.add_tool_call, tool_name, "success", "", "", summary)
                return True

        except (json.JSONDecodeError, TypeError, KeyError):
            pass

        # If we got here and it's a long string that looks like data, truncate it
        if len(output_str) > 500:
            summary = output_str[:500] + "... (truncated)"
            self.call_from_thread(log.add_tool_call, tool_name, "success", "", "", summary)
            return True

        return False

    def _is_todo_list(self, data: Any) -> bool:
        """Check if data looks like a TODO list."""
        if not isinstance(data, list) or not data:
            return False
        first = data[0]
        if not isinstance(first, dict):
            return False
        return any(k in first for k in ("status", "title", "priority", "completed"))

    def _display_todo_list(self, data: Any, log: ConversationLog) -> None:
        """Display a TODO list with nice formatting."""
        from rich.text import Text

        if isinstance(data, dict) and "todos" in data:
            data = data["todos"]

        if not isinstance(data, list):
            return

        if not data:
            self.call_from_thread(log.write, Text("  📋 No tasks", style="#71717a"))
            return

        # Count statuses
        completed = sum(
            1 for t in data if isinstance(t, dict) and t.get("status") in ("completed", "done")
        )
        in_progress = sum(
            1 for t in data if isinstance(t, dict) and t.get("status") in ("in_progress", "active")
        )
        pending = sum(
            1 for t in data if isinstance(t, dict) and t.get("status") in ("pending", None)
        )

        # Header with summary
        parts = []
        if completed:
            parts.append(f"✅ {completed}")
        if in_progress:
            parts.append(f"🔄 {in_progress}")
        if pending:
            parts.append(f"○ {pending}")

        header = Text()
        header.append("  📋 ", style="#06b6d4")
        header.append(f"Tasks: {' · '.join(parts) if parts else 'none'}\n", style="#e4e4e7")
        self.call_from_thread(log.write, header)

        # Task items (limit to 8)
        for item in data[:8]:
            if not isinstance(item, dict):
                continue

            status = item.get("status", "pending")
            title = item.get("title", item.get("name", item.get("description", str(item))))
            priority = item.get("priority", "normal")

            # Status icons
            status_icons = {
                "completed": ("✅", "#22c55e"),
                "done": ("✅", "#22c55e"),
                "in_progress": ("🔄", "#a855f7"),
                "active": ("🔄", "#a855f7"),
                "pending": ("○", "#71717a"),
                "blocked": ("🚫", "#ef4444"),
            }
            icon, color = status_icons.get(status, ("○", "#71717a"))

            # Priority styling
            title_style = "#e4e4e7"
            if priority in ("high", "important"):
                title_style = "#f59e0b"
            elif priority in ("critical", "urgent"):
                title_style = "#ef4444"
            elif status in ("completed", "done"):
                title_style = "#71717a"

            line = Text()
            line.append(f"    {icon} ", style=color)
            line.append(f"{str(title)}\n", style=title_style)
            self.call_from_thread(log.write, line)

        if len(data) > 8:
            more = Text()
            more.append(f"    ... and {len(data) - 8} more\n", style="#71717a")
            self.call_from_thread(log.write, more)

    def _display_file_results(self, data: Any, tool_name: str, log: ConversationLog) -> None:
        """Display file search results."""
        from rich.text import Text

        files = []
        if isinstance(data, list):
            files = [str(f) for f in data if f]
        elif isinstance(data, dict):
            files = data.get("files", data.get("matches", data.get("results", [])))
            if not isinstance(files, list):
                return

        if not files:
            self.call_from_thread(log.write, Text("  🔍 No matches found\n", style="#71717a"))
            return

        # Header
        header = Text()
        header.append("  🔍 ", style="#06b6d4")
        header.append(f"Found {len(files)} file{'s' if len(files) != 1 else ''}\n", style="#e4e4e7")
        self.call_from_thread(log.write, header)

        # File list (limit to 6)
        for f in files[:6]:
            ext = str(f).split(".")[-1].lower() if "." in str(f) else ""
            icons = {
                "py": "🐍",
                "js": "📜",
                "ts": "📜",
                "rs": "🦀",
                "go": "🐹",
                "md": "📝",
                "json": "⚙️",
                "yaml": "⚙️",
            }
            icon = icons.get(ext, "📄")

            path_str = str(f)
            if len(path_str) > 55:
                path_str = "..." + path_str[-52:]

            line = Text()
            line.append(f"    {icon} ", style="#52525b")
            line.append(f"{path_str}\n", style="#06b6d4")
            self.call_from_thread(log.write, line)

        if len(files) > 6:
            more = Text()
            more.append(f"    ... and {len(files) - 6} more\n", style="#71717a")
            self.call_from_thread(log.write, more)

    def _display_task_list(self, data: list, log: ConversationLog) -> None:
        """Display Claude Code style task list."""
        from rich.text import Text

        header = Text()
        header.append("  📝 ", style="#a855f7")
        header.append(f"{len(data)} task{'s' if len(data) != 1 else ''}\n", style="#e4e4e7")
        self.call_from_thread(log.write, header)

        for task in data[:5]:
            if not isinstance(task, dict):
                continue

            status = task.get("status", "pending")
            subject = task.get("subject", task.get("title", ""))
            task_id = task.get("id", "")

            icons = {
                "completed": ("✅", "#22c55e"),
                "in_progress": ("⏳", "#a855f7"),
                "pending": ("○", "#71717a"),
            }
            icon, color = icons.get(status, ("○", "#71717a"))

            line = Text()
            line.append(f"    {icon} ", style=color)
            if task_id:
                line.append(f"[{task_id}] ", style="#52525b")
            line.append(
                f"{str(subject)}\n", style="#e4e4e7" if status != "completed" else "#71717a"
            )
            self.call_from_thread(log.write, line)

    def _display_error_result(self, data: dict, log: ConversationLog) -> None:
        """Display error result."""
        from rich.text import Text

        errors = data.get("errors", [data.get("error")]) if isinstance(data, dict) else []

        header = Text()
        header.append("  ⚠️ ", style="#ef4444")
        header.append(f"{len(errors)} error{'s' if len(errors) != 1 else ''}\n", style="#ef4444")
        self.call_from_thread(log.write, header)

        for err in errors[:3]:
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            line = Text()
            line.append("    ✕ ", style="#ef4444")
            line.append(f"{str(msg)}\n", style="#ef4444")
            self.call_from_thread(log.write, line)

    def _display_plan(self, data: list, log: ConversationLog) -> None:
        """Display plan steps."""
        from rich.text import Text

        header = Text()
        header.append("  📋 ", style="#a855f7")
        header.append("Plan:\n", style="#e4e4e7")
        self.call_from_thread(log.write, header)

        for i, step in enumerate(data[:5], 1):
            if not isinstance(step, dict):
                continue

            desc = step.get("description", step.get("step", step.get("action", "")))
            status = step.get("status", "pending")

            icon = "✓" if status in ("completed", "done") else str(i)
            color = "#22c55e" if status in ("completed", "done") else "#a855f7"

            line = Text()
            line.append(f"    {icon}. ", style=color)
            line.append(f"{str(desc)}\n", style="#e4e4e7")
            self.call_from_thread(log.write, line)

    def _display_success_result(self, data: dict, tool_name: str, log: ConversationLog) -> None:
        """Display success/result dict."""
        from rich.text import Text

        success = data.get("success", data.get("ok", True))
        result_val = data.get("result", data.get("message", data.get("output", "")))

        line = Text()
        if success:
            line.append("  ✓ ", style="#22c55e")
            if result_val:
                line.append(f"{str(result_val)}\n", style="#e4e4e7")
            else:
                line.append("Success\n", style="#22c55e")
        else:
            line.append("  ✕ ", style="#ef4444")
            error = data.get("error", data.get("message", "Failed"))
            line.append(f"{str(error)}\n", style="#ef4444")
        self.call_from_thread(log.write, line)

    def _display_generic_list(self, data: list, tool_name: str, log: ConversationLog) -> None:
        """Display a generic list."""
        from rich.text import Text

        header = Text()
        header.append(f"  ✦ {tool_name}: ", style="#a855f7")
        header.append(f"{len(data)} items\n", style="#e4e4e7")
        self.call_from_thread(log.write, header)

        for item in data[:5]:
            line = Text()
            line.append("    • ", style="#52525b")

            if isinstance(item, dict):
                display = None
                for key in ("name", "title", "path", "message", "value", "text"):
                    if key in item:
                        display = item[key]
                        break
                if display is None:
                    display = str(item)
                line.append(f"{str(display)}\n", style="#e4e4e7")
            else:
                line.append(f"{str(item)}\n", style="#e4e4e7")
            self.call_from_thread(log.write, line)

        if len(data) > 5:
            more = Text()
            more.append(f"    ... and {len(data) - 5} more\n", style="#71717a")
            self.call_from_thread(log.write, more)

    def _display_generic_dict(self, data: dict, tool_name: str, log: ConversationLog) -> None:
        """Display a generic dict."""
        from rich.text import Text

        for key, val in list(data.items())[:4]:
            line = Text()
            line.append(f"  {key}: ", style="#a855f7")
            val_str = str(val)
            if len(val_str) > 50:
                val_str = val_str[:47] + "..."
            line.append(f"{val_str}\n", style="#e4e4e7")
            self.call_from_thread(log.write, line)

        if len(data) > 4:
            more = Text()
            more.append(f"  ... +{len(data) - 4} more fields\n", style="#71717a")
            self.call_from_thread(log.write, more)

    def _strip_ansi(self, text: str) -> str:
        """Remove ANSI escape codes from text."""
        import re

        ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        return ansi_escape.sub("", text)

    def _show_thinking_line(self, line: str, log: ConversationLog):
        """Show a thinking/log line - SuperQode quantum style.

        Uses quantum-inspired animation (◇◆◈) instead of arrows.
        Automatically adds emoji if line doesn't have one.
        """
        # Check if thinking logs should be shown
        if not self.show_thinking_logs:
            return

        # Skip empty lines
        if not line.strip():
            return

        # Ensure auto-scroll is ON during agent work so user sees updates
        log.auto_scroll = True

        # Check if line already has an emoji (check first 3 characters)
        has_emoji = False
        if line.strip():
            first_chars = line.strip()[:3]
            # Check if any character is an emoji (Unicode emoji range)
            for char in first_chars:
                # Check for emoji ranges
                code = ord(char)
                if (
                    0x1F600 <= code <= 0x1F64F  # Emoticons
                    or 0x1F300 <= code <= 0x1F5FF  # Misc Symbols and Pictographs
                    or 0x1F680 <= code <= 0x1F6FF  # Transport and Map
                    or 0x1F1E0 <= code <= 0x1F1FF  # Flags
                    or 0x2600 <= code <= 0x26FF  # Misc symbols
                    or 0x2700 <= code <= 0x27BF  # Dingbats
                    or 0xFE00 <= code <= 0xFE0F  # Variation Selectors
                    or 0x1F900 <= code <= 0x1F9FF  # Supplemental Symbols and Pictographs
                    or 0x1FA00 <= code <= 0x1FA6F
                ):  # Chess Symbols, etc.
                    has_emoji = True
                    break

        # Add appropriate emoji based on content type if line doesn't have one
        if not has_emoji:
            emoji = self._get_emoji_for_line(line)
            line = f"{emoji} {line}"

        # Show the line with animated quantum prefix
        text = Text()
        frame = getattr(self, "_stream_animation_frame", 0)

        # Quantum animation frames
        quantum_frames = ["◇", "◆", "◈", "◆"]
        quantum_icon = quantum_frames[frame % len(quantum_frames)]

        # Cycling colors from SuperQode palette
        prefix_color = GRADIENT_PURPLE[frame % len(GRADIENT_PURPLE)]

        # Show with quantum prefix - don't truncate, show full line
        # Split long lines into multiple lines to prevent any truncation
        text.append(f"  {quantum_icon} ", style=f"bold {prefix_color}")

        # If line is very long, we'll let it wrap naturally
        # Rich will handle wrapping if console width is set correctly
        text.append(f"{line}\n", style=SQ_COLORS.text_muted)

        # Write the text - ensure console width is unlimited
        log.write(text)

    def _should_show_thinking_for_local(self, text: str) -> bool:
        """Determine if a thinking log should be shown for local models.

        Aggressively filters out verbose content and keeps only important status messages.
        Returns True for important thinking logs, False for everything else to suppress.
        """
        if not text or not text.strip():
            return False

        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        # Always keep lines with emojis (status indicators from AgentLoop)
        if any(ord(char) >= 0x1F600 for char in text_stripped[:3]):
            return True

        # Keep ONLY explicit status messages from AgentLoop (these are important)
        # These are the structured messages AgentLoop generates, not model thinking
        # Use more specific patterns to avoid matching code
        agent_status_patterns = [
            "processing request",
            "calling model",
            "executing tool",
            "received response",
            "iteration",
            "response complete",
            "reached maximum iterations",
            "operation cancelled by user",
        ]
        # Check if text starts with or contains these patterns (more specific)
        for pattern in agent_status_patterns:
            if pattern in text_lower:
                # Make sure it's not code (e.g., "def complete():" shouldn't match "complete")
                if not self._looks_like_code(text_stripped):
                    return True

        # Suppress ALL "Extended Thinking" content from models (often contains code)
        if "extended thinking" in text_lower or text_lower.startswith("[extended thinking]"):
            return False

        # Keep tool-related status messages (formatted by _format_tool_message_rich)
        tool_status_patterns = [
            "reading:",
            "modifying:",
            "running:",
            "searching:",
            "listing:",
            "creating:",
            "tool completed",
            "tool failed",
        ]
        if any(pattern in text_lower for pattern in tool_status_patterns):
            return True

        # Check if it looks like code - if so, suppress it
        if self._looks_like_code(text_stripped):
            return False

        # For local models, be VERY aggressive - suppress everything else by default
        # Only show explicit AgentLoop status messages and tool status, everything else is noise
        # This includes all model thinking content, code lines, and verbose output
        return False

    def _looks_like_code(self, text: str) -> bool:
        """Check if a line looks like code (to be suppressed for local models).

        More aggressive detection to catch all code-like patterns.
        """
        text_stripped = text.strip()

        # Empty or whitespace-only lines
        if not text_stripped:
            return True

        # Very short lines that are likely code fragments
        if len(text_stripped) < 15:
            # But keep if it's a status message
            if any(
                word in text_stripped.lower()
                for word in ["ok", "done", "error", "fail", "complete"]
            ):
                return False
            # Likely code fragment if it has code characters
            if any(
                char in text_stripped
                for char in ["=", "(", ")", "[", "]", "{", "}", ":", "->", ".", ","]
            ):
                return True

        # Lines starting with common code keywords (more comprehensive)
        code_keywords = [
            "def ",
            "class ",
            "import ",
            "from ",
            "if ",
            "for ",
            "while ",
            "return ",
            "async ",
            "await ",
            "try:",
            "except",
            "finally:",
            "with ",
            "elif ",
            "else:",
            "pass",
            "break",
            "continue",
            "yield ",
            "const ",
            "let ",
            "var ",
            "function ",
            "export ",
            "require(",
            "public ",
            "private ",
            "protected ",
            "static ",
            "final ",
            "#",  # Comments
            "//",  # Comments
            "/*",  # Comments
        ]
        if any(text_stripped.startswith(keyword) for keyword in code_keywords):
            return True

        # Lines that are mostly code patterns
        code_patterns = [
            " = ",  # Assignment
            "()",  # Function call
            "[]",  # List access
            "{}",  # Dict access
            "->",  # Type hint
            "=>",  # Arrow function
            "::",  # Scope resolution
        ]
        pattern_count = sum(1 for pattern in code_patterns if pattern in text_stripped)

        # If multiple code patterns, likely code
        if pattern_count >= 2:
            return True

        # Lines ending with colon or semicolon (likely code)
        if text_stripped.endswith(":") or text_stripped.endswith(";"):
            if len(text_stripped) < 60:  # Reasonable length for code
                return True

        # Lines that are just variable assignments or function calls
        if " = " in text_stripped:
            # Check if it's a simple assignment (not a status message)
            parts = text_stripped.split(" = ", 1)
            if len(parts) == 2:
                # If left side looks like a variable name (short, alphanumeric/underscore)
                left = parts[0].strip()
                if len(left) < 40 and (
                    left.replace("_", "").replace(".", "").isalnum() or "[" in left or "." in left
                ):
                    return True

        # Lines with function call patterns
        if "(" in text_stripped and ")" in text_stripped:
            # Check if it looks like a function call (not just parentheses in text)
            if text_stripped.count("(") == text_stripped.count(")") and len(text_stripped) < 80:
                # Likely a function call
                return True

        # Lines with array/list access patterns
        if "[" in text_stripped and "]" in text_stripped:
            if len(text_stripped) < 60:
                return True

        # Lines that are just indentation (likely code structure)
        if text_stripped.startswith("    ") or text_stripped.startswith("\t"):
            if len(text_stripped.strip()) < 30:
                return True

        return False

    def _get_emoji_for_line(self, line: str) -> str:
        """Get appropriate emoji based on line content type with variety."""
        import random

        line_lower = line.lower()
        line_hash = abs(hash(line))  # For consistent selection per line

        # File operations - multiple emojis per category
        if any(keyword in line_lower for keyword in ["read", "reading", "opened", "file"]):
            emojis = ["📄", "📖", "📑", "📰", "📃", "📋", "🗂️", "📁"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["write", "writing", "wrote", "saved", "created"]
        ):
            emojis = ["📝", "🖊️", "🖋️", "✏️", "📝", "💾", "💿"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower
            for keyword in ["edit", "editing", "modified", "updated", "changed"]
        ):
            emojis = ["✏️", "🔧", "🔄", "♻️", "🛠️", "📝", "✂️", "🔨"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["delete", "deleted", "removed"]):
            emojis = ["🗑️", "❌", "🗑", "💥", "🔥", "⚡", "🗯️"]
            return emojis[line_hash % len(emojis)]

        # Code/compilation - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["compile", "compiling", "build", "building", "make"]
        ):
            emojis = ["🔨", "⚙️", "🛠️", "🔧", "🏗️", "📦", "🎯", "⚡"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["code", "coding", "programming", "script"]):
            emojis = ["💻", "⌨️", "🖥️", "💾", "🔤", "📟", "🖱️", "⌨"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["test", "testing", "tested", "spec"]):
            emojis = ["🧪", "🔬", "⚗️", "🧫", "🔍", "✅", "✔️", "🎯"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["import", "importing", "require", "package"]
        ):
            emojis = ["📦", "📚", "📖", "📗", "📘", "📙", "📕", "🎁"]
            return emojis[line_hash % len(emojis)]

        # Search/query - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["search", "searching", "find", "finding", "grep", "query"]
        ):
            emojis = ["🔍", "🔎", "🔎", "👀", "🔭", "🔬", "🔦", "💡"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["scan", "scanning", "analyze", "analyzing"]):
            emojis = ["🔎", "🔬", "🔍", "📊", "📈", "📉", "🔭", "👁️"]
            return emojis[line_hash % len(emojis)]

        # Network/web - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["http", "https", "url", "web", "api", "request", "fetch"]
        ):
            emojis = ["🌐", "🌍", "🌎", "🌏", "💻", "📡", "📶", "🔄"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower
            for keyword in ["connect", "connecting", "connected", "connection"]
        ):
            emojis = ["🔌", "🔗", "⛓️", "🔗", "📡", "📶", "🌐", "💫"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["download", "downloading", "upload", "uploading"]
        ):
            emojis = ["⬇️", "⬆️", "📥", "📤", "💾", "📦", "🔄", "⚡"]
            return emojis[line_hash % len(emojis)]

        # Terminal/commands - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["run", "running", "execute", "executing", "command", "cmd"]
        ):
            emojis = ["🖥️", "💻", "⌨️", "⚡", "🚀", "▶️", "▶", "🎬"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["terminal", "shell", "bash", "sh", "zsh"]):
            emojis = ["💻", "🖥️", "⌨️", "🖱️", "📟", "💾", "🔤", "⌨"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower
            for keyword in ["install", "installing", "installed", "setup", "setting up"]
        ):
            emojis = ["⚙️", "🔧", "🛠️", "📦", "📥", "✅", "🎯", "🔨"]
            return emojis[line_hash % len(emojis)]

        # Errors/warnings - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["error", "failed", "failure", "exception", "traceback"]
        ):
            emojis = ["❌", "🚫", "⚠️", "💥", "🔥", "⚡", "🚨", "⛔"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["warn", "warning", "caution", "alert"]):
            emojis = ["⚠️", "🚨", "⚡", "💡", "🔔", "📢", "📣", "🔴"]
            return emojis[line_hash % len(emojis)]

        # Success/completion - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["success", "succeeded", "complete", "completed", "done", "finished"]
        ):
            emojis = ["✅", "✔️", "🎉", "🎊", "✨", "🌟", "💫", "🎯"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["ready", "initialized", "started", "launch"]
        ):
            emojis = ["✨", "🚀", "⚡", "💫", "🌟", "🎯", "✅", "🎬"]
            return emojis[line_hash % len(emojis)]

        # Thinking/processing - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["think", "thinking", "process", "processing", "analyze"]
        ):
            emojis = ["🧠", "💭", "🤔", "💡", "🔍", "🔎", "🔬", "📊"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["plan", "planning", "strategy"]):
            emojis = ["💭", "📋", "📝", "📄", "🗺️", "🧭", "🎯", "📊"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["wait", "waiting", "pending"]):
            emojis = ["⏳", "⏰", "🕐", "🕑", "🕒", "⏱️", "⏲️", "💤"]
            return emojis[line_hash % len(emojis)]

        # Data/analysis - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["data", "result", "output", "response", "json", "xml"]
        ):
            emojis = ["📊", "📈", "📉", "📋", "📄", "📑", "📝", "💾"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["model", "models", "ai", "llm", "gpt", "claude"]
        ):
            emojis = ["🤖", "👾", "🤖", "🧠", "💻", "🔮", "✨", "🌟"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["token", "tokens", "cost", "usage"]):
            emojis = ["📈", "💰", "💵", "💴", "💶", "💷", "💸", "📊"]
            return emojis[line_hash % len(emojis)]

        # Configuration/setup - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["config", "configuration", "setting", "settings", "option"]
        ):
            emojis = ["⚙️", "🔧", "🛠️", "📋", "📝", "📄", "🗂️", "🔨"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["init", "initialize", "initializing", "setup"]
        ):
            emojis = ["🔧", "⚙️", "🛠️", "🚀", "✨", "🎯", "📦", "🔨"]
            return emojis[line_hash % len(emojis)]

        # Git/version control - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["git", "commit", "push", "pull", "branch", "merge"]
        ):
            emojis = ["🌿", "🌳", "🌲", "🌱", "🍃", "🌾", "🔀", "📦"]
            return emojis[line_hash % len(emojis)]

        # Database - multiple emojis
        elif any(keyword in line_lower for keyword in ["database", "db", "sql", "query", "table"]):
            emojis = ["🗄️", "💾", "📊", "📈", "🗃️", "📦", "🗂️", "💿"]
            return emojis[line_hash % len(emojis)]

        # Security - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["auth", "authentication", "login", "password", "key", "secret"]
        ):
            emojis = ["🔐", "🔒", "🔑", "🛡️", "🔰", "🛡", "🔓", "🗝️"]
            return emojis[line_hash % len(emojis)]

        # Default - expanded emoji pool with variety
        else:
            # Use different default emojis based on line characteristics
            if len(line) > 100:
                long_emojis = ["📋", "📄", "📑", "📰", "📃", "📊", "📈", "📉"]
                return long_emojis[line_hash % len(long_emojis)]
            elif any(char.isdigit() for char in line[:10]):
                number_emojis = ["🔢", "🔟", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "📊"]
                return number_emojis[line_hash % len(number_emojis)]
            elif ":" in line and "=" in line:
                config_emojis = ["📝", "⚙️", "🔧", "📋", "📄", "🗂️", "🔨", "🛠️"]
                return config_emojis[line_hash % len(config_emojis)]
            else:
                # Expanded pool of emojis for generic console output
                generic_emojis = [
                    "📋",
                    "📄",
                    "💬",
                    "📝",
                    "🔍",
                    "💡",
                    "📌",
                    "📍",
                    "✨",
                    "⭐",
                    "🌟",
                    "💫",
                    "🎯",
                    "🔮",
                    "🎪",
                    "🎨",
                    "🧩",
                    "🎲",
                    "🎭",
                    "🎬",
                    "🎸",
                    "🎵",
                    "🎶",
                    "🎤",
                    "🚀",
                    "⚡",
                    "🔥",
                    "💥",
                    "🎉",
                    "🎊",
                    "🎁",
                    "🎈",
                    "🌐",
                    "🌍",
                    "🌎",
                    "🌏",
                    "🌙",
                    "⭐",
                    "🌟",
                    "☀️",
                    "💻",
                    "⌨️",
                    "🖥️",
                    "🖱️",
                    "📱",
                    "📲",
                    "💾",
                    "💿",
                    "🔧",
                    "⚙️",
                    "🛠️",
                    "🔨",
                    "⚒️",
                    "🪓",
                    "🔩",
                    "⚡",
                    "🧠",
                    "💭",
                    "🤔",
                    "💡",
                    "🔍",
                    "🔎",
                    "🔬",
                    "📊",
                    "✅",
                    "✔️",
                    "🎯",
                    "🎪",
                    "🎨",
                    "🎭",
                    "🎬",
                    "🎸",
                ]
                # Use line hash for consistent emoji per line type
                return generic_emojis[line_hash % len(generic_emojis)]

    def _show_final_response(
        self, response_text: str, name: str, duration: float, log: ConversationLog
    ):
        """Show the final response with proper formatting and word wrapping."""
        from rich.panel import Panel
        from rich.syntax import Syntax
        import re

        # Store the response for :copy command
        self._last_response = response_text

        # Header separator
        sep = Text()
        sep.append("\n")
        sep.append("  ━" * 30 + "\n", style="#a855f7")
        sep.append(f"  ✅ {name} ", style="bold #22c55e")
        sep.append(f"completed in {duration:.1f}s\n", style="#71717a")
        sep.append("  ━" * 30 + "\n", style="#a855f7")
        log.write(sep)

        # Clean up the response text - collapse multiple blank lines
        clean_text = self._strip_markdown(response_text.strip())
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)  # Max 2 newlines

        # Check if response contains markdown code blocks
        has_code_blocks = "```" in response_text

        if has_code_blocks:
            # Parse and render code blocks separately for better display
            self._render_with_code_blocks(response_text.strip(), log)
        else:
            # Simple text response - wrap properly
            self._render_plain_text(clean_text, log)

        # Simple footer line (no copy/open hints for cleaner UX)
        footer = Text()
        footer.append("\n", style="")
        log.write(footer)

    def _strip_markdown(self, text: str) -> str:
        """Strip markdown formatting from text for clean display."""
        import re

        # Don't strip code blocks - they're handled separately
        # Store code blocks temporarily
        code_blocks = []

        def save_code_block(match):
            code_blocks.append(match.group(0))
            return f"__CODE_BLOCK_{len(code_blocks) - 1}__"

        text = re.sub(r"```[\w]*\n.*?```", save_code_block, text, flags=re.DOTALL)

        # Strip bold: **text** or __text__
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"__(.+?)__", r"\1", text)

        # Strip italic: *text* or _text_ (but not in the middle of words)
        text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"\1", text)
        text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"\1", text)

        # Strip strikethrough: ~~text~~
        text = re.sub(r"~~(.+?)~~", r"\1", text)

        # Strip inline code: `code` (but keep the text)
        text = re.sub(r"`([^`]+?)`", r"\1", text)

        # Strip links: [text](url) -> text
        text = re.sub(r"\[([^\]]+?)\]\([^)]+?\)", r"\1", text)

        # Strip images: ![alt](url) -> alt
        text = re.sub(r"!\[([^\]]*?)\]\([^)]+?\)", r"\1", text)

        # Strip horizontal rules: --- or *** or ___
        text = re.sub(r"^[\-\*_]{3,}\s*$", "", text, flags=re.MULTILINE)

        # Strip blockquotes: > text -> text
        text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)

        # Restore code blocks
        for i, block in enumerate(code_blocks):
            text = text.replace(f"__CODE_BLOCK_{i}__", block)

        return text

    def _render_with_code_blocks(self, text: str, log: ConversationLog):
        """Render text that contains code blocks."""
        from rich.syntax import Syntax
        from rich.panel import Panel
        import re

        # Split by code blocks
        code_pattern = r"```(\w*)\n(.*?)```"
        parts = re.split(code_pattern, text, flags=re.DOTALL)

        i = 0
        while i < len(parts):
            part = parts[i]

            # Check if this is a language identifier (comes before code)
            if i + 2 < len(parts) and parts[i + 1]:
                # This part is text before code block - strip markdown
                if part.strip():
                    clean_part = self._strip_markdown(part.strip())
                    self._render_plain_text(clean_part, log)

                # Next is language, then code
                lang = parts[i + 1] or "text"
                code = parts[i + 2] if i + 2 < len(parts) else ""

                if code.strip():
                    # Render code block with syntax highlighting
                    syntax = Syntax(
                        code.strip(),
                        lang,
                        theme="monokai",
                        line_numbers=False,
                        word_wrap=True,
                        background_color="#000000",
                    )

                    lang_icons = {
                        "python": "🐍",
                        "javascript": "📜",
                        "typescript": "💠",
                        "bash": "🖥️",
                        "shell": "🖥️",
                        "json": "📋",
                        "yaml": "📝",
                        "html": "🌐",
                        "css": "🎨",
                        "sql": "🗄️",
                        "go": "🐹",
                        "rust": "🦀",
                        "java": "☕",
                        "ruby": "💎",
                    }
                    icon = lang_icons.get(lang.lower(), "📄")

                    panel = Panel(
                        syntax,
                        title=f"[bold #22c55e]{icon} {lang.upper()}[/]",
                        border_style="#22c55e",
                        padding=(0, 1),
                    )
                    log.write(panel)
                    log.write(Text("\n"))

                i += 3
            else:
                # Regular text part - strip markdown
                if part.strip():
                    clean_part = self._strip_markdown(part.strip())
                    self._render_plain_text(clean_part, log)
                i += 1

    def _render_plain_text(self, text: str, log: ConversationLog):
        """Render plain text with proper word wrapping - no markdown syntax."""
        import textwrap
        import shutil
        import re

        # Get terminal width - use full width available
        try:
            term_width = shutil.get_terminal_size().columns
            # Use full width, only account for minimal padding (2 chars on each side)
            width = term_width - 4  # Minimal padding for readability
            if width < 40:
                width = 40  # Minimum reasonable width
        except Exception:
            # Fallback: use a reasonable default that's wider
            width = 120

        # Collapse multiple blank lines first
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Process line by line
        lines = text.split("\n")
        prev_was_blank = False

        for line in lines:
            line = line.strip()

            if not line:
                # Only add one blank line, skip consecutive blanks
                if not prev_was_blank:
                    log.write(Text(""))
                    prev_was_blank = True
                continue

            prev_was_blank = False

            # Check for bullet points (markdown style - , * , or • )
            if line.startswith(("- ", "* ", "• ")):
                bullet_text = line[2:].strip()
                # Strip any remaining markdown from bullet text
                bullet_text = self._strip_inline_markdown(bullet_text)
                wrapped = textwrap.fill(bullet_text, width=width - 6)
                content = Text()
                content.append("  • ", style="bold #a855f7")
                first_line = True
                for wrap_line in wrapped.split("\n"):
                    if first_line:
                        content.append(f"{wrap_line}\n", style="#e4e4e7")
                        first_line = False
                    else:
                        content.append(f"    {wrap_line}\n", style="#e4e4e7")
                log.write(content)

            # Check for numbered lists
            elif line and line[0].isdigit() and ". " in line[:4]:
                num_end = line.index(". ")
                num = line[: num_end + 1]
                rest = line[num_end + 2 :].strip()
                # Strip any remaining markdown
                rest = self._strip_inline_markdown(rest)
                wrapped = textwrap.fill(rest, width=width - 8)
                content = Text()
                content.append(f"  {num} ", style="bold #06b6d4")
                first_line = True
                for wrap_line in wrapped.split("\n"):
                    if first_line:
                        content.append(f"{wrap_line}\n", style="#e4e4e7")
                        first_line = False
                    else:
                        content.append(f"      {wrap_line}\n", style="#e4e4e7")
                log.write(content)

            # Check for headers (markdown style)
            elif line.startswith("#"):
                header_level = len(line) - len(line.lstrip("#"))
                header_text = line.lstrip("#").strip()
                # Strip any markdown from header
                header_text = self._strip_inline_markdown(header_text)
                # Wrap header text too if it's long
                if len(header_text) > width - 10:
                    header_text = header_text[: width - 13] + "..."
                content = Text()
                if header_level == 1:
                    content.append(f"\n  ═══ {header_text} ═══\n\n", style="bold #a855f7")
                elif header_level == 2:
                    content.append(f"\n  ── {header_text} ──\n\n", style="bold #d946ef")
                else:
                    content.append(f"\n  {header_text}\n", style="bold #ec4899")
                log.write(content)

            # Regular paragraph text
            else:
                # Strip any remaining markdown
                clean_line = self._strip_inline_markdown(line)
                wrapped = textwrap.fill(clean_line, width=width - 4)
                content = Text()
                for wrap_line in wrapped.split("\n"):
                    content.append(f"  {wrap_line}\n", style="#e4e4e7")
                log.write(content)

    def _strip_inline_markdown(self, text: str) -> str:
        """Strip inline markdown formatting (bold, italic, code, links)."""
        import re

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

        return text

    # Keep old method name for compatibility
    def _show_beautiful_response(
        self,
        response_text: str,
        name: str,
        duration: float,
        thinking_count: int,
        log: ConversationLog,
    ):
        """Alias for _show_final_response."""
        self._show_final_response(response_text, name, duration, log)

    def _format_tool_message_rich(self, tool_name: str, tool_input: dict) -> str:
        """Format a tool use message with SuperQode quantum-inspired icons.

        Uses minimal icons: ↳ (read), ↲ (write), ▸ (shell), ⌕ (search), ⋮ (list)
        """
        tool_lower = tool_name.lower()

        # SuperQode icon mapping (minimal, no emoji)
        tool_icons = {
            "read": "↳",  # Arrow in - reading
            "write": "↲",  # Arrow out - writing
            "edit": "⟳",  # Rotate - editing
            "patch": "⟳",  # Rotate - patching
            "bash": "▸",  # Play - shell
            "shell": "▸",
            "terminal": "▸",
            "exec": "▸",
            "search": "⌕",  # Magnifier - search
            "grep": "⌕",
            "find": "⌕",
            "glob": "⋮",  # Vertical dots - glob
            "list": "⋮",
            "ls": "⋮",
            "tree": "⋮",
            "git": "◎",  # Target - git
            "fetch": "◎",
            "web": "◎",
            "http": "◎",
            "create": "↲",  # Arrow out - creating
            "mkdir": "⋮",
            "delete": "✕",  # X - delete
            "rm": "✕",
        }

        # Find matching icon
        icon = "•"  # Default bullet
        for key, ic in tool_icons.items():
            if key in tool_lower:
                icon = ic
                break

        # Format based on tool type - NO TRUNCATION, show full content
        file_path = tool_input.get("filePath", tool_input.get("path", tool_input.get("file", "")))

        if tool_lower == "read" and file_path:
            # Show full path, no truncation
            return f"{icon} Reading: {file_path}"
        elif tool_lower in ("write", "edit", "patch") and file_path:
            # Show full path, no truncation
            return f"{icon} Modifying: {file_path}"
        elif tool_lower in ("bash", "shell", "terminal", "exec"):
            cmd = tool_input.get("command", "")
            # Show full command, no truncation
            return f"{icon} Running: {cmd}"
        elif tool_lower in ("search", "grep", "find"):
            query = tool_input.get("pattern", tool_input.get("query", tool_input.get("search", "")))
            # Show full query, no truncation
            return f"{icon} Searching: {query}"
        elif tool_lower in ("list", "ls", "glob"):
            path = tool_input.get("path", tool_input.get("directory", "."))
            return f"{icon} Listing: {path}"
        elif tool_lower == "create" and file_path:
            # Show full path, no truncation
            return f"{icon} Creating: {file_path}"
        elif tool_lower == "todo_write":
            # Special handling for todo_write - show clean summary instead of JSON
            todos = tool_input.get("todos", [])
            todo_count = len(todos) if todos else 0
            return f"{icon} Creating todo list with {todo_count} items"
        else:
            # Generic format - show full tool_input as JSON string, no truncation
            if tool_input:
                import json

                try:
                    # Try to format as JSON for readability
                    tool_input_str = json.dumps(tool_input, indent=None, ensure_ascii=False)
                except Exception:
                    # Fallback to string representation if not JSON-serializable
                    tool_input_str = str(tool_input)
                # Show full JSON/string, no truncation
                return f"{icon} {tool_name}: {tool_input_str}"
            return f"{icon} {tool_name}"

    def _show_final_outcome(
        self, response_text: str, name: str, summary: dict, log: ConversationLog
    ):
        """Show final outcome with SuperQode quantum design.

        Clean, minimal, professional - no emoji celebration.
        Uses crystalline borders and quantum-inspired icons.
        Now includes file changes section with visual indicators.
        """
        from rich.panel import Panel
        import re
        from superqode.widgets.response_changes import render_file_changes_section

        # Store the response for :copy command
        log._last_response = response_text

        duration = summary.get("duration", 0)
        tool_count = summary.get("tool_count", 0)
        files_modified = summary.get("files_modified", [])
        files_read = summary.get("files_read", [])
        file_diffs = summary.get("file_diffs", {})  # NEW: Get diff data

        # FALLBACK: Always check git for file changes if files_modified is empty
        # This ensures file changes are detected even if agent tracking missed them
        if not files_modified:
            try:
                root_path = Path(os.getcwd())
                git_changes = get_git_changes(root_path)
                files_modified = [
                    change.path for change in git_changes if change.status in ("M", "A")
                ]
                if files_modified:
                    # Compute file diffs for git-detected changes
                    file_diffs = self._compute_file_diffs(files_modified)
            except Exception:
                pass  # If git check fails, continue with empty lists

        # Disable auto-scroll while we write content
        log.auto_scroll = False

        # Clear thinking logs and show fresh outcome
        log.clear()

        # Create enhanced header - SuperQode style with more visual appeal
        header = Text()
        header.append("\n")

        # Top decorative border - animated gradient
        top_border = "═" * 70
        success_gradient = [
            SQ_COLORS.success,
            "#16a34a",
            "#14b8a6",
            "#06b6d4",
            "#0ea5e9",
            "#3b82f6",
        ]
        for i, char in enumerate(top_border):
            header.append(char, style=success_gradient[i % len(success_gradient)])
        header.append("\n")

        # Main title section with enhanced styling
        header.append("  ", style="")
        header.append("✦ ", style=f"bold {SQ_COLORS.success}")
        header.append("SUCCESS", style=f"bold {SQ_COLORS.success}")
        header.append("  │  ", style=SQ_COLORS.border_subtle)
        header.append(f"{name.upper()}", style=f"bold {SQ_COLORS.text_primary}")
        header.append(" completed", style=SQ_COLORS.text_muted)
        header.append("\n\n")

        # Enhanced stats panel with better visual hierarchy
        stats = Text()

        # Calculate totals for better presentation
        total_additions = sum(d.get("additions", 0) for d in file_diffs.values())
        total_deletions = sum(d.get("deletions", 0) for d in file_diffs.values())
        net_changes = total_additions - total_deletions

        # Stats header
        stats.append("  ", style="")
        stats.append("┌─ ", style=SQ_COLORS.border_subtle)
        stats.append("Execution Summary", style=f"bold {SQ_COLORS.text_primary}")
        stats.append(" ─┐\n", style=SQ_COLORS.border_subtle)

        # Performance metrics
        stats.append("  │ ", style=SQ_COLORS.border_subtle)
        stats.append("⚡ Performance", style=f"bold {SQ_COLORS.primary_light}")
        stats.append("  ", style="")
        if duration < 5:
            duration_style = SQ_COLORS.success
            duration_icon = "⚡"
        elif duration < 15:
            duration_style = "#fbbf24"
            duration_icon = "⏱"
        else:
            duration_style = "#f97316"
            duration_icon = "⏳"
        stats.append(f"{duration_icon} {duration:.2f}s", style=f"bold {duration_style}")
        stats.append("\n", style="")

        # Tools executed
        if tool_count > 0:
            stats.append("  │ ", style=SQ_COLORS.border_subtle)
            stats.append("🔧 Tools", style=f"bold {SQ_COLORS.primary_light}")
            stats.append("  ", style="")
            stats.append(f"◈ {tool_count} executed", style=SQ_COLORS.text_secondary)
            if tool_count > 10:
                stats.append(" (high activity)", style=SQ_COLORS.text_muted)
            stats.append("\n", style="")

        # Files modified - enhanced
        if files_modified:
            stats.append("  │ ", style=SQ_COLORS.border_subtle)
            stats.append("📝 Files Modified", style=f"bold {SQ_COLORS.success}")
            stats.append("  ", style="")
            stats.append(f"↲ {len(files_modified)}", style=f"bold {SQ_COLORS.success}")
            if total_additions > 0 or total_deletions > 0:
                stats.append("  (", style=SQ_COLORS.text_muted)
                if total_additions > 0:
                    stats.append(f"+{total_additions}", style=f"bold {SQ_COLORS.success}")
                if total_deletions > 0:
                    if total_additions > 0:
                        stats.append(" / ", style=SQ_COLORS.text_muted)
                    stats.append(f"-{total_deletions}", style=f"bold #ef4444")
                stats.append(" lines)", style=SQ_COLORS.text_muted)
            stats.append("\n", style="")

        # Files read
        if files_read:
            stats.append("  │ ", style=SQ_COLORS.border_subtle)
            stats.append("📖 Files Analyzed", style=f"bold {SQ_COLORS.info}")
            stats.append("  ", style="")
            stats.append(f"↳ {len(files_read)}", style=f"bold {SQ_COLORS.info}")
            stats.append("\n", style="")

        # Net impact indicator
        if files_modified and (total_additions > 0 or total_deletions > 0):
            stats.append("  │ ", style=SQ_COLORS.border_subtle)
            stats.append("📊 Net Impact", style=f"bold {SQ_COLORS.primary_light}")
            stats.append("  ", style="")
            if net_changes > 0:
                stats.append(f"+{net_changes} lines added", style=f"bold {SQ_COLORS.success}")
            elif net_changes < 0:
                stats.append(f"{net_changes} lines removed", style=f"bold #ef4444")
            else:
                stats.append("balanced changes", style=SQ_COLORS.text_muted)
            stats.append("\n", style="")

        # Close stats panel
        stats.append("  └", style=SQ_COLORS.border_subtle)
        stats.append("─" * 65, style=SQ_COLORS.border_subtle)
        stats.append("┘\n\n", style=SQ_COLORS.border_subtle)

        log.write(header)
        log.write(stats)

        # Enhanced response section with better visual design
        if response_text.strip():
            response_header = Text()
            response_header.append("  ", style="")
            response_header.append("┌─ ", style=SQ_COLORS.border_subtle)
            response_header.append("🤖 Agent Response", style=f"bold {SQ_COLORS.text_primary}")
            response_header.append(" ─", style=SQ_COLORS.border_subtle)
            response_header.append("─" * 50, style=SQ_COLORS.border_subtle)
            response_header.append("┐\n", style=SQ_COLORS.border_subtle)
            log.write(response_header)

            # Clean and render the response
            clean_text = self._strip_markdown(response_text.strip())
            clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)

            if "```" in response_text:
                self._render_with_code_blocks(response_text.strip(), log)
            else:
                self._render_plain_text(clean_text, log)

            # Close response panel
            response_footer = Text()
            response_footer.append("  └", style=SQ_COLORS.border_subtle)
            response_footer.append("─" * 65, style=SQ_COLORS.border_subtle)
            response_footer.append("┘\n\n", style=SQ_COLORS.border_subtle)
            log.write(response_footer)

        # NEW: File Changes Section with visual indicators
        if files_modified:
            from superqode.widgets.response_changes import render_file_changes_section
            from rich.console import Console
            from io import StringIO

            changes_section = render_file_changes_section(files_modified, file_diffs, max_files=10)

            # Render Rich Group to string and write to log
            console = Console(file=StringIO(), width=120, legacy_windows=False)
            console.print(changes_section)
            rendered_text = console.file.getvalue()
            log.write(rendered_text)

        # Enhanced footer with better command presentation
        footer = Text()
        footer.append("\n  ", style="")
        footer.append("┌─ ", style=SQ_COLORS.border_subtle)
        footer.append("⚡ Quick Actions", style=f"bold {SQ_COLORS.text_primary}")
        footer.append(" ─", style=SQ_COLORS.border_subtle)
        footer.append("─" * 50, style=SQ_COLORS.border_subtle)
        footer.append("┐\n", style=SQ_COLORS.border_subtle)

        footer.append("  │ ", style=SQ_COLORS.border_subtle)
        footer.append("📋 ", style=SQ_COLORS.info)
        footer.append(":sidebar", style=f"bold {SQ_COLORS.info}")
        footer.append("  ", style="")
        footer.append("View changes in sidebar", style=SQ_COLORS.text_muted)
        footer.append("\n", style="")

        if files_modified:
            footer.append("  │ ", style=SQ_COLORS.border_subtle)
            footer.append("🔍 ", style=SQ_COLORS.info)
            footer.append(":diff", style=f"bold {SQ_COLORS.info}")
            footer.append("  ", style="")
            footer.append("View detailed diffs", style=SQ_COLORS.text_muted)
            footer.append("\n", style="")

        footer.append("  │ ", style=SQ_COLORS.border_subtle)
        footer.append("↶ ", style=SQ_COLORS.info)
        footer.append(":undo", style=f"bold {SQ_COLORS.info}")
        footer.append("  ", style="")
        footer.append("or ", style=SQ_COLORS.text_muted)
        footer.append("[Ctrl+Z]", style=f"bold {SQ_COLORS.primary_light}")
        footer.append("  ", style="")
        footer.append("Revert changes", style=SQ_COLORS.text_muted)
        footer.append("\n", style="")

        footer.append("  └", style=SQ_COLORS.border_subtle)
        footer.append("─" * 65, style=SQ_COLORS.border_subtle)
        footer.append("┘\n", style=SQ_COLORS.border_subtle)

        # Bottom decorative border
        bottom_border = "═" * 70
        for i, char in enumerate(bottom_border):
            footer.append(char, style=success_gradient[i % len(success_gradient)])
        footer.append("\n\n", style="")
        log.write(footer)

        # NEW: Trigger sidebar auto-navigation if files were modified
        if files_modified:
            self.set_timer(0.2, lambda: self._navigate_to_sidebar_changes(files_modified))

        # Schedule scroll to top with a small delay to ensure content is rendered
        # Use set_timer to give the UI time to fully render before scrolling
        self.set_timer(0.1, lambda: log.scroll_home())

    def _show_completion_summary(self, name: str, summary: dict, log: ConversationLog):
        """Show completion summary when there's no text response."""
        from superqode.widgets.response_changes import (
            render_file_changes_compact,
            render_file_changes_section,
        )

        duration = summary.get("duration", 0)
        tool_count = summary.get("tool_count", 0)
        files_modified = summary.get("files_modified", [])
        files_read = summary.get("files_read", [])
        file_diffs = summary.get("file_diffs", {})  # NEW: Get diff data

        # FALLBACK: Always check git for file changes if files_modified is empty
        # This ensures file changes are detected even if agent tracking missed them
        if not files_modified:
            try:
                root_path = Path(os.getcwd())
                git_changes = get_git_changes(root_path)
                files_modified = [
                    change.path for change in git_changes if change.status in ("M", "A")
                ]
                if files_modified:
                    # Compute file diffs for git-detected changes
                    file_diffs = self._compute_file_diffs(files_modified)
            except Exception:
                pass  # If git check fails, continue with empty lists

        # Disable auto-scroll
        log.auto_scroll = False

        # Clear and show fresh summary
        log.clear()

        t = Text()
        t.append("\n\n")

        # Celebration header
        celebration = "═" * 50
        gradient = ["#22c55e", "#10b981", "#14b8a6", "#06b6d4"]
        for i, char in enumerate(celebration):
            t.append(char, style=gradient[i % len(gradient)])
        t.append("\n")
        t.append("     🎉 ", style="#fbbf24")
        t.append("DONE!", style="bold #22c55e")
        t.append(" 🎉\n", style="#fbbf24")
        for i, char in enumerate(celebration):
            t.append(char, style=gradient[i % len(gradient)])
        t.append("\n\n")

        # Stats
        t.append(f"  ⏱️ Completed in {duration:.1f}s\n", style="#71717a")

        if tool_count > 0:
            t.append(f"  ⚡ {tool_count} tools executed\n", style="#a855f7")

        # NEW: Show file changes with visual indicators
        if files_modified:
            changes_text = render_file_changes_compact(files_modified, file_diffs)
            t.append_text(changes_text)
        elif files_read:
            t.append(f"  📖 {len(files_read)} files analyzed\n", style="#06b6d4")

        t.append("\n", style="")
        log.write(t)

        # NEW: Show full file changes section if files were modified
        if files_modified:
            from rich.console import Console
            from io import StringIO

            changes_section = render_file_changes_section(files_modified, file_diffs, max_files=10)

            # Render Rich Group to string and write to log
            console = Console(file=StringIO(), width=120, legacy_windows=False)
            console.print(changes_section)
            rendered_text = console.file.getvalue()
            log.write(rendered_text)

        # NEW: Trigger sidebar auto-navigation if files were modified
        if files_modified:
            self.set_timer(0.2, lambda: self._navigate_to_sidebar_changes(files_modified))

        # Schedule scroll to top with a small delay to ensure content is rendered
        self.set_timer(0.1, lambda: log.scroll_home())

    @work(exclusive=True, thread=True)
    def _send_to_role(self, text: str, mode: str, role: str, log: ConversationLog):
        """Send message to role - supports both ACP agents (opencode) and SuperQode agents (with tools)."""
        self._cancel_requested = False
        self.call_from_thread(self._start_thinking, f"⚡ Running {mode}.{role}...")

        try:
            from superqode.config import load_config, resolve_role
            from superqode.agents.persona import PersonaInjector
            from superqode.agents.messaging import wrap_message_with_persona

            resolved = resolve_role(mode, role, load_config())

            if not resolved:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(log.add_error, f"Role {mode}.{role} not found")
                return

            # Handle ACP agents (like opencode)
            if resolved.coding_agent == "opencode":
                # Build persona context and wrap message
                injector = PersonaInjector()
                persona_context = injector.build_persona(mode, role, resolved)
                wrapped_message = wrap_message_with_persona(text, persona_context)

                # Get model from config
                model_name = None
                if resolved.agent_config and resolved.agent_config.model:
                    model_name = resolved.agent_config.model
                elif resolved.model:
                    model_name = resolved.model
                else:
                    model_name = "glm-4.7-free"

                # Map model names
                model_mapping = {
                    "glm-4.7": "glm-4.7-free",
                    "glm-4.7-free": "glm-4.7-free",
                    "grok-code": "grok-code",
                    "kimi-k2.5": "kimi-k2.5-free",
                    "kimi-k2.5-free": "kimi-k2.5-free",
                    "minimax-m2.1": "minimax-m2.1-free",
                    "minimax-m2.1-free": "minimax-m2.1-free",
                    "gpt-5-nano": "gpt-5-nano",
                    "big-pickle": "big-pickle",
                }
                model_name = model_mapping.get(model_name, model_name)

                # Use unified OpenCode runner (same code path as :acp connect opencode)
                self._run_opencode_unified(
                    message=wrapped_message,
                    model=model_name,
                    display_name=f"{mode}.{role}",
                    log=log,
                    persona_context=persona_context,
                )
            # Handle BYOK/LOCAL mode - use provider session if connected
            elif (
                resolved.execution_mode in ("byok", "local")
                and resolved.provider
                and resolved.model
            ):
                # Check if provider session is connected (should be from _set_role)
                session = get_session()
                if hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
                    # Use provider session for BYOK/LOCAL
                    self._send_to_pure_mode(text, log)
                else:
                    # Not connected yet, try to connect
                    self.call_from_thread(self._stop_thinking)
                    self.call_from_thread(
                        log.add_error, f"Not connected to {resolved.provider}/{resolved.model}"
                    )
                    self.call_from_thread(
                        log.add_info, f"Connecting to {resolved.provider}/{resolved.model}..."
                    )
                    # Store resolved role for persona injection
                    self._current_resolved_role = resolved
                    self._connect_byok_mode(
                        resolved.provider, resolved.model, log, resolved_role=resolved
                    )
                    # After connection, send the message
                    if hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
                        self._send_to_pure_mode(text, log)
            # Handle SuperQode agents (with provider/model, full tool access)
            elif resolved.agent_type == "superqode" and resolved.provider and resolved.model:
                # Use SuperQodeAgent with AgentLoop (has full codebase access via tools)
                self._run_superqode_agent(
                    message=text, mode=mode, role=role, resolved=resolved, log=log
                )
            else:
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(
                    log.add_info,
                    f"🚧 Agent for {mode}.{role} not supported yet (agent_type: {resolved.agent_type}, coding_agent: {resolved.coding_agent})",
                )
        except Exception as e:
            self._agent_process = None
            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(log.add_error, str(e))

    @work(exclusive=True, thread=True)
    async def _run_superqode_agent(
        self, message: str, mode: str, role: str, resolved, log: ConversationLog
    ):
        """Run SuperQode agent with full tool access (AgentLoop) and streaming output."""
        try:
            from superqode.agents.unified import create_unified_agent

            # Create and initialize agent
            agent = create_unified_agent(resolved)
            if not await agent.initialize():
                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(log.add_error, f"Failed to initialize {mode}.{role} agent")
                return

            self.call_from_thread(self._stop_thinking)

            # Show agent info
            model_display = f"{resolved.provider}/{resolved.model}"
            self.call_from_thread(
                log.add_info, f"🤖 Using {model_display} with full codebase access"
            )

            # Track tool usage for summary
            tool_stats = {"tools_called": 0, "files_analyzed": set(), "tool_names": []}

            # Set up tool callbacks to track progress
            if hasattr(agent, "_agent_loop") and agent._agent_loop:

                def on_tool_call(tool_name: str, args: dict):
                    tool_stats["tools_called"] += 1
                    tool_stats["tool_names"].append(tool_name)

                    # Track files being analyzed
                    if tool_name == "read_file" and "path" in args:
                        tool_stats["files_analyzed"].add(args["path"])
                    elif tool_name == "grep" and "path" in args:
                        tool_stats["files_analyzed"].add(args["path"])
                    elif tool_name == "code_search" and "path" in args:
                        tool_stats["files_analyzed"].add(args["path"])

                    # Show progress
                    file_count = len(tool_stats["files_analyzed"])
                    self.call_from_thread(
                        log.add_info,
                        f"🔍 Analyzing... ({tool_stats['tools_called']} tools, {file_count} files)",
                    )

                def on_tool_result(tool_name: str, result):
                    if not result.success:
                        self.call_from_thread(
                            log.add_info, f"⚠️  {tool_name} completed with warnings"
                        )

                async def on_thinking(text: str):
                    """Handle thinking logs from BYOK models."""
                    # Display thinking logs in the conversation log
                    # Format similar to ACP thinking logs
                    self.call_from_thread(log.add_info, f"💭 {text}")

                agent._agent_loop.on_tool_call = on_tool_call
                agent._agent_loop.on_tool_result = on_tool_result
                agent._agent_loop.on_thinking = on_thinking

            # Check if agent supports streaming
            if hasattr(agent, "send_message_streaming"):
                # Stream response with timeout to prevent hanging
                full_response = ""
                had_content = False
                streaming_timed_out = False

                try:

                    async def stream_with_timeout():
                        async for chunk in agent.send_message_streaming(message):
                            if chunk.strip():
                                nonlocal had_content
                                had_content = True
                                full_response += chunk
                                self.call_from_thread(log.add_assistant, chunk)

                    await asyncio.wait_for(stream_with_timeout(), timeout=120.0)
                except asyncio.TimeoutError:
                    streaming_timed_out = True
                    error_msg = (
                        f"⏰ Streaming timed out for {agent.provider}/{agent.model} after 2 minutes"
                    )
                    self.call_from_thread(log.add_error, error_msg)

                # If no content was streamed but tools were used, prompt for summary
                # (only if not timed out)
                if not had_content and not streaming_timed_out and tool_stats["tools_called"] > 0:
                    self.call_from_thread(log.add_info, "💭 Generating analysis summary...")
                    # The agent should continue and provide a summary
                    # Wait a bit and check if we get more content
                    await asyncio.sleep(0.5)

                # Show completion summary
                self.call_from_thread(self._stop_stream_animation)

                if tool_stats["tools_called"] > 0 and not streaming_timed_out:
                    files_count = len(tool_stats["files_analyzed"])
                    summary = (
                        f"\n✅ Analysis Complete: "
                        f"{tool_stats['tools_called']} tools executed, "
                        f"{files_count} files analyzed"
                    )
                    self.call_from_thread(log.add_info, summary)

                if (
                    not full_response.strip()
                    and tool_stats["tools_called"] > 0
                    and not streaming_timed_out
                ):
                    self.call_from_thread(
                        log.add_error,
                        "⚠️  Agent executed tools but did not provide a summary. "
                        "Please review the tool outputs above.",
                    )

                # Reset mode badge to HOME after QE testing completes
                self.call_from_thread(self._reset_mode_badge_after_qe)
            else:
                # Fallback to non-streaming with timeout to prevent hanging
                try:
                    # Add timeout to prevent hanging on slow/unresponsive models
                    import asyncio

                    response = await asyncio.wait_for(
                        agent.send_message(message),
                        timeout=120.0,  # 2 minute timeout
                    )
                except asyncio.TimeoutError:
                    response = None
                    error_msg = f"⏰ Model {agent.provider}/{agent.model} timed out after 2 minutes"
                    self.call_from_thread(log.add_error, error_msg)

                self.call_from_thread(self._stop_thinking)
                self.call_from_thread(self._stop_stream_animation)

                if response and response.content and response.content.strip():
                    self.call_from_thread(log.add_assistant, response.content)

                    # Show stats from metadata
                    if response.metadata:
                        tool_calls = response.metadata.get("tool_calls_made", 0)
                        if tool_calls > 0:
                            summary = f"\n✅ Analysis Complete: {tool_calls} tools executed"
                            self.call_from_thread(log.add_info, summary)
                elif response is None:
                    # Already handled timeout error above
                    pass
                else:
                    # No valid response content - show appropriate error
                    if response and hasattr(response, "error") and response.error:
                        error_msg = f"Agent error: {response.error}"
                    elif response and response.content:
                        # Content exists but is just whitespace
                        error_msg = "Agent returned empty response (whitespace only)"
                    else:
                        error_msg = "No response from agent"
                    self.call_from_thread(log.add_error, error_msg)

                # Reset mode badge to HOME after QE testing completes
                self.call_from_thread(self._reset_mode_badge_after_qe)

            # Cleanup
            await agent.cleanup()

        except Exception as e:
            import traceback

            self.call_from_thread(self._stop_thinking)
            self.call_from_thread(self._stop_stream_animation)
            self.call_from_thread(log.add_error, f"Error: {str(e)}")
            self.call_from_thread(log.add_info, traceback.format_exc())

    # ========================================================================
    # Role & Agent Management
    # ========================================================================

    def _set_role(self, mode: str, role: str, log: ConversationLog):
        try:
            from superqode.config import load_config, resolve_role

            # Show safety warnings for QE mode
            if mode == "qe":
                safety_warnings = get_safety_warnings()

                # Display warnings in TUI
                for warning in safety_warnings:
                    if should_skip_warnings(warning):
                        continue

                    # Create warning panel
                    warning_text = Text()
                    warning_text.append(f"{warning.title}\n\n", style="bold red")
                    warning_text.append(warning.message, style="white")
                    warning_text.append("\n\nRecommendations:\n", style="bold yellow")

                    for i, rec in enumerate(warning.recommendations, 1):
                        warning_text.append(f"{i}. {rec}\n", style="dim cyan")

                    # Choose border color based on severity
                    border_color = {
                        WarningSeverity.INFO: "blue",
                        WarningSeverity.WARNING: "yellow",
                        WarningSeverity.CRITICAL: "red",
                    }[warning.severity]

                    panel = Panel(
                        warning_text,
                        title=f"⚠️  SAFETY WARNING - {warning.severity.value.upper()}",
                        border_style=border_color,
                        padding=(1, 2),
                    )

                    log.write(panel)
                    log.write(Text(""))  # Add spacing

                # Add a clear separator after warnings
                if any(not should_skip_warnings(w) for w in safety_warnings):
                    log.write(Rule(style="yellow"))
                    log.write(
                        Text(
                            "Please review the safety warnings above before proceeding.\n",
                            style="bold yellow",
                        )
                    )

                # For TUI, we don't require interactive acknowledgment
                # Users can cancel with :back or :cancel if they change their mind
                requires_ack = [
                    w
                    for w in safety_warnings
                    if w.requires_acknowledgment and not should_skip_warnings(w)
                ]
                if requires_ack:
                    # Mark warnings as acknowledged for future skipping
                    for warning in requires_ack:
                        if warning.skippable_after_first:
                            mark_warnings_acknowledged(warning)

            # Try to resolve role from team config first
            resolved = resolve_role(mode, role, load_config())

            # For QE mode, if team config doesn't have the role, try to create a default QE role
            if not resolved and mode == "qe":
                from superqode.superqe.roles import get_role

                try:
                    # Check if this is a valid QE role
                    qe_role = get_role(role, Path.cwd())
                    # Create a synthetic ResolvedRole for QE roles
                    from superqode.config.schema import ResolvedRole

                    resolved = ResolvedRole(
                        mode=mode,
                        role=role,
                        description=f"QE {role.replace('_', ' ')}",
                        coding_agent="superqode",  # QE roles use superqode agent
                        agent_type="superqode",  # QE roles use superqode agent type
                        agent_id="",
                        provider="",
                        model="",
                        execution_mode="byok",  # QE roles run locally
                        job_description="",
                        mcp_servers=[],
                    )
                except ValueError:
                    # Not a valid QE role, resolved remains None
                    pass

            if resolved:
                key = f"{mode}.{role}"
                session = get_session()
                session.switch_to_role_mode(key)
                set_mode(key)

                self.current_mode = mode
                self.current_role = role
                self.current_agent = ""
                if (
                    mode == "qe"
                    and role in POWER_QE_ROLES
                    and not getattr(self, "_power_roles_hint_shown", False)
                ):
                    log.add_info(f"⚡ Power QE role selected: {role}")
                    log.add_info(
                        "💡 Tip: Update this role's job_description in superqode.yaml for best results."
                    )
                    self._power_roles_hint_shown = True

                # Reset session for new role
                self._is_first_message = True
                self._opencode_session_id = ""

                # Get execution mode from resolved role
                exec_mode = getattr(resolved, "execution_mode", "acp")
                agent_id = getattr(resolved, "agent_id", "") or resolved.coding_agent

                # Get model/provider from agent_config if ACP mode
                model = resolved.model
                provider = resolved.provider
                agent_config = getattr(resolved, "agent_config", None)
                if agent_config:
                    model = model or getattr(agent_config, "model", "")
                    provider = provider or getattr(agent_config, "provider", "")

                self.current_model = model or ""
                self.current_provider = provider or ""

                badge = self.query_one("#mode-badge", ModeBadge)
                badge.mode = mode
                badge.role = role
                badge.agent = agent_id if exec_mode == "acp" else ""
                badge.model = model or ""
                badge.provider = provider or ""
                badge.execution_mode = exec_mode

                # Update session execution mode
                session.execution_mode = exec_mode

                # Store resolved role for persona injection
                self._current_resolved_role = resolved

                # If BYOK or LOCAL mode, connect to provider/model
                if exec_mode in ("byok", "local") and provider and model:
                    # Connect via BYOK mode (LOCAL uses same connection mechanism)
                    # Pass resolved role so job description can be injected
                    self._connect_byok_mode(provider, model, log, resolved_role=resolved)
                else:
                    # Clear screen and show fresh workspace
                    self._clear_for_workspace(log, f"{mode.upper()}.{role.upper()}")
            else:
                if mode == "qe":
                    # Show available QE roles for better user experience
                    from superqode.superqe.roles import list_roles

                    available_qe_roles = [r["name"] for r in list_roles()]
                    log.add_error(f"QE role '{role}' not found.")
                    log.write(f"Available QE roles: {', '.join(available_qe_roles)}")
                    log.write("Use :qe <role_name> to start a QE session.")
                else:
                    log.add_error(f"Role {mode}.{role} not found")
        except Exception as e:
            log.add_error(str(e))

    def _go_home(self, log: ConversationLog):
        # First, cancel any running agent process
        if self._agent_process is not None:
            self._cancel_requested = True
            try:
                self._agent_process.terminate()
                log.add_info("🛑 Agent process terminated")
            except Exception:
                pass
            self._agent_process = None

        # Stop ACP client if running
        if self._acp_client is not None:
            import asyncio

            try:
                # Schedule the stop coroutine
                asyncio.create_task(self._acp_client.stop())
            except Exception:
                pass
            self._acp_client = None

        # Stop any animations
        self._stop_thinking()
        self._stop_stream_animation()
        self.is_busy = False

        # Reset session tracking for conversation continuity
        self._is_first_message = True
        self._opencode_session_id = None
        approved_tools = self._ensure_approved_tools()
        approved_tools.clear()  # Clear approved tools for new session
        self._pending_tool_name = None
        self._pending_tool_input = None
        self._tool_id_map = {}  # Clear tool tracking for new session

        session = get_session()

        if session.is_connected_to_agent():
            session.disconnect_agent()

        self.current_mode = "home"
        self.current_role = ""
        self.current_agent = ""
        self.current_model = ""
        self.current_provider = ""
        set_mode("home")
        session.state = "superqode"
        session.execution_mode = "acp"  # Reset execution mode

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.mode = "home"
        badge.role = ""
        badge.agent = ""
        badge.model = ""
        badge.provider = ""
        badge.execution_mode = ""

        # Clear and show homepage
        self.action_clear_screen()

    def _reset_mode_badge_after_qe(self):
        """Reset mode badge to HOME after QE testing completes."""
        try:
            badge = self.query_one("#mode-badge", ModeBadge)
            badge.mode = "home"
            badge.role = ""
            badge.agent = ""
            badge.model = ""
            badge.provider = ""
            badge.execution_mode = ""
        except Exception:
            pass  # Silently fail if badge not found

    # ========================================================================
    # Provider session commands
    # ========================================================================

    def _connect_pure_mode(self, provider: str, model: str, level, log: ConversationLog):
        """Connect to provider session with specified provider/model."""
        from superqode.pure_mode import PureMode
        from superqode.tools.base import ToolResult

        if not hasattr(self, "_pure_mode"):
            self._pure_mode = PureMode()

        # Set up callbacks for tool calls
        def on_tool_call(name: str, args: dict):
            self.call_from_thread(self._show_pure_tool_call, name, args, log)

        def on_tool_result(name: str, result: ToolResult):
            self.call_from_thread(self._show_pure_tool_result, name, result, log)

        self._pure_mode.on_tool_call = on_tool_call
        self._pure_mode.on_tool_result = on_tool_result

        # Connect
        self._pure_mode.connect(provider, model, level)

        # Update state
        session = get_session()
        session.execution_mode = "pure"

        self.current_mode = "pure"
        self.current_agent = "pure"
        self.current_model = model
        self.current_provider = provider

        # Update badge
        badge = self.query_one("#mode-badge", ModeBadge)
        badge.mode = "pure"
        badge.agent = ""
        badge.model = model
        badge.provider = provider
        badge.execution_mode = "pure"

        # Clear screen and show fresh workspace
        self._clear_for_workspace(log, f"PURE • {provider}")

    # ========================================================================
    # SuperQE Commands
    # ========================================================================

    def _handle_superqe_command(self, args: str, log: ConversationLog):
        """Handle :superqe commands in TUI."""
        from superqode.evaluation import CODEOPTIX_AVAILABLE

        if not CODEOPTIX_AVAILABLE:
            self._show_command_output(
                log,
                Panel(
                    "🔄 [bold yellow]SuperQE is initializing...[/bold yellow]\n\n"
                    "CodeOptiX integration is being loaded.\n"
                    "Please wait a moment and try again.\n\n"
                    "💡 Meanwhile, you can use basic QE:\n"
                    "[cyan]:qe run .[/cyan] - Quality engineering with any LLM provider\n\n"
                    "SuperQE supports: Ollama, OpenAI, Anthropic, Google",
                    title="⏳ Loading SuperQE",
                    border_style="yellow",
                ),
            )
            return

        # Parse superqe subcommand
        parts = args.split(maxsplit=1)
        subcmd = parts[0].lower() if parts else "help"
        subargs = parts[1] if len(parts) > 1 else ""

        if subcmd == "run":
            self._superqe_run(subargs, log)
        elif subcmd == "behaviors":
            self._superqe_behaviors(log)
        elif subcmd == "agent-eval":
            self._superqe_agent_eval(subargs, log)
        elif subcmd == "scenarios":
            self._superqe_scenarios(subargs, log)
        elif subcmd in ("help", ""):
            self._superqe_help(log)
        else:
            self._show_command_output(log, f"[red]Unknown SuperQE command: {subcmd}[/red]")

    def _superqe_run(self, args: str, log: ConversationLog):
        """Handle :superqe run command."""
        # Parse arguments similar to CLI
        behaviors = None
        use_bloom = False

        if args:
            # Simple parsing: look for --behaviors and --use-bloom
            if "--behaviors" in args:
                parts = args.split("--behaviors", 1)
                if len(parts) > 1:
                    behaviors_part = parts[1].split("--")[0].strip()
                    behaviors = behaviors_part

            if "--use-bloom" in args:
                use_bloom = True

        # Show SuperQE evaluation in progress
        self._show_command_output(
            log,
            Panel(
                f"🚀 [bold cyan]SuperQE Enhanced Evaluation[/bold cyan]\n\n"
                f"Behaviors: {behaviors or 'default'}\n"
                f"Bloom Scenarios: {'Enabled' if use_bloom else 'Disabled'}\n\n"
                "Running advanced CodeOptiX evaluation...",
                border_style="cyan",
            ),
        )

        # Show Ollama requirement message
        self._show_command_output(
            log,
            Panel(
                "🔧 [yellow]SuperQE requires Ollama[/yellow]\n\n"
                "SuperQE uses Ollama for advanced AI-powered evaluation.\n\n"
                "To run SuperQE evaluations:\n"
                "1. Install Ollama: [link=https://ollama.ai]https://ollama.ai[/link]\n"
                "2. Start Ollama: [cyan]ollama serve[/cyan]\n"
                "3. Pull a model: [cyan]ollama pull llama3.1[/cyan]\n"
                "4. Run: [cyan]:superqe run . --behaviors security-vulnerabilities[/cyan]\n\n"
                "For basic QE without Ollama: [cyan]:qe run .[/cyan]",
                border_style="yellow",
            ),
        )

    def _superqe_behaviors(self, log: ConversationLog):
        """Handle :superqe behaviors command."""
        from superqode.evaluation.behaviors import get_enhanced_behaviors

        behaviors = get_enhanced_behaviors()

        if behaviors:
            from rich.table import Table

            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Behavior", style="cyan", no_wrap=True)
            table.add_column("Description", style="white")

            for name, desc in behaviors.items():
                table.add_row(f"🔬 {name}", desc)

            self._show_command_output(log, table)
        else:
            self._show_command_output(log, "[yellow]No enhanced behaviors available[/yellow]")

    def _superqe_agent_eval(self, args: str, log: ConversationLog):
        """Handle :superqe agent-eval command."""
        self._show_command_output(
            log, "[yellow]Agent evaluation not yet implemented in TUI[/yellow]"
        )

    def _superqe_scenarios(self, args: str, log: ConversationLog):
        """Handle :superqe scenarios command."""
        self._show_command_output(
            log, "[yellow]Scenario generation not yet implemented in TUI[/yellow]"
        )

    def _superqe_help(self, log: ConversationLog):
        """Show SuperQE help."""
        help_text = """
[bold cyan]🚀 SuperQE Commands[/bold cyan]

[cyan]:superqe run [options][/cyan] - Run enhanced evaluation
  Options: --behaviors security-vulnerabilities,test-quality --use-bloom

[cyan]:superqe behaviors[/cyan] - List available enhanced behaviors

[cyan]:superqe agent-eval[/cyan] - Compare multiple AI agents

[cyan]:superqe scenarios[/cyan] - Manage Bloom scenario generation

[green]✨ SuperQE features are fully integrated with SuperQode![/green]
        """.strip()

        self._show_command_output(log, help_text)

    def _show_pure_tool_call(self, name: str, args: dict, log: ConversationLog):
        """Show tool call inline - matches ACP format."""
        # For local models, completely disable thinking logs (including tool calls)
        if hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
            from superqode.providers.registry import PROVIDERS, ProviderCategory

            provider = self._pure_mode.session.provider
            provider_def = PROVIDERS.get(provider)
            if provider_def and provider_def.category == ProviderCategory.LOCAL:
                return  # Suppress all thinking logs for local models

        # Use same formatting as ACP for consistency
        msg = self._format_tool_message_rich(name, args)
        # Call directly since we're already in the UI thread via call_from_thread from on_tool_call
        self._show_thinking_line(msg, log)

    def _show_pure_tool_result(self, name: str, result, log: ConversationLog):
        """Show tool result inline - matches ACP format."""
        # For local models, completely disable thinking logs (including tool results)
        if hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
            from superqode.providers.registry import PROVIDERS, ProviderCategory

            provider = self._pure_mode.session.provider
            provider_def = PROVIDERS.get(provider)
            if provider_def and provider_def.category == ProviderCategory.LOCAL:
                return  # Suppress all thinking logs for local models

        if result.success:
            # Show detailed result preview (same as ACP)
            if result.output:
                result_str = str(result.output)
                # Show full result, no truncation (same as ACP)
                # Call directly since we're already in the UI thread via call_from_thread from on_tool_result
                self._show_thinking_line(f"✅ {name}: {result_str}", log)
            else:
                # Call directly since we're already in the UI thread
                self._show_thinking_line(f"✅ {name} completed", log)
        else:
            # Show full error message, no truncation (same as ACP)
            error_msg = str(result.error) if result.error else "failed"
            # Call directly since we're already in the UI thread
            self._show_thinking_line(f"❌ {name} failed: {error_msg}", log)

    def _show_byok_thinking_line(self, text: str, log: ConversationLog):
        """Show thinking line for BYOK - handles threading correctly.

        The agent loop runs in an async context which might be in the same thread
        as the Textual app. This method safely handles both cases.
        """
        # Use call_from_thread, but catch the error if we're already in UI thread
        try:
            self.call_from_thread(self._show_thinking_line, text, log)
        except RuntimeError as e:
            # If we get "must run in a different thread" error, we're already in UI thread
            # Call directly
            if "different thread" in str(e).lower():
                self._show_thinking_line(text, log)
            else:
                # Re-raise other errors
                raise

    def _handle_byok_provider_selection(self, selection: str, log: ConversationLog):
        """Handle provider selection from :connect picker."""
        # Only process if we're actually awaiting provider selection
        if not getattr(self, "_awaiting_byok_provider", False):
            return False

        # Check for _byok_connect_list (from :connect command)
        if hasattr(self, "_byok_connect_list") and self._byok_connect_list:
            selection = selection.strip()
            provider_id = None
            provider_def = None

            # Try numeric selection first
            try:
                idx = int(selection) - 1
                if 0 <= idx < len(self._byok_connect_list):
                    provider_id, provider_def = self._byok_connect_list[idx]
            except ValueError:
                # Not a number - try to match by provider name/ID
                selection_lower = selection.lower()
                for pid, pdef in self._byok_connect_list:
                    if selection_lower == pid.lower() or selection_lower in pdef.name.lower():
                        provider_id, provider_def = pid, pdef
                        break

            if provider_id:
                self._awaiting_byok_provider = False
                # CRITICAL: Clear _awaiting_byok_model to prevent any auto-connection
                # The model list must be shown first, and user must explicitly select a model
                self._awaiting_byok_model = False
                # CRITICAL: Store the selection that was used to select the provider
                # This prevents the same input from being processed as a model selection
                self._last_provider_selection = selection.strip()
                # CRITICAL: Prevent _show_provider_models from setting _awaiting_byok_model immediately
                # This prevents the same input from being processed as a model selection
                self._skip_set_awaiting_model = True
                # Reset model highlight index when entering a new provider
                self._byok_highlighted_model_index = 0
                # Always use numbered list (not picker) to ensure model list is shown
                # Disable picker mode to prevent any auto-selection issues
                self._show_provider_models(provider_id, log, use_picker=False)
                # Set _awaiting_byok_model AFTER showing the models with a longer delay
                # to ensure the user sees the model list and must enter a NEW input to select
                # Use a longer delay (0.5s) to ensure the UI has fully updated
                self.set_timer(0.5, lambda: setattr(self, "_awaiting_byok_model", True))
                # Clear the last provider selection after a delay to allow normal model selection
                self.set_timer(0.6, lambda: setattr(self, "_last_provider_selection", None))
                return True
            else:
                # Invalid selection
                log.add_error(f"Unknown provider: {selection}")
                log.add_info("Enter a number or provider name (e.g., 'openai', 'anthropic')")
                return True

        return False

    def _handle_local_provider_selection(self, selection: str, log: ConversationLog):
        """Handle local provider selection from :connect local picker."""
        # Check for _local_provider_list (from :connect local command)
        if hasattr(self, "_local_provider_list") and self._local_provider_list:
            try:
                # Strip whitespace and try to parse as number
                selection = selection.strip()
                idx = int(selection) - 1
                if 0 <= idx < len(self._local_provider_list):
                    provider_id, provider_def = self._local_provider_list[idx]
                    self._awaiting_local_provider = False
                    # Reset model highlight index when entering a new provider
                    self._local_highlighted_model_index = 0
                    # Show models for this local provider (async function)
                    self.run_worker(self._show_local_provider_models(provider_id, log))
                    return True
                else:
                    log.add_error(
                        f"Invalid selection. Enter a number between 1 and {len(self._local_provider_list)}"
                    )
                    return True  # Return True to prevent further processing
            except ValueError:
                # Not a number, might be a provider name - try to match
                selection_lower = selection.lower()
                for provider_id, provider_def in self._local_provider_list:
                    if (
                        selection_lower == provider_id.lower()
                        or selection_lower in provider_def.name.lower()
                    ):
                        self._awaiting_local_provider = False
                        # Reset model highlight index when entering a new provider
                        self._local_highlighted_model_index = 0
                        self.run_worker(self._show_local_provider_models(provider_id, log))
                        return True
                log.add_error(f"Unknown provider: {selection}")
                return True  # Return True to prevent further processing

        return False

    def _handle_local_model_selection(self, selection: str, log: ConversationLog):
        """Handle local model selection from :connect local picker."""
        if not hasattr(self, "_local_selected_provider"):
            return False

        provider_id = self._local_selected_provider
        model_list = getattr(self, "_local_model_list", [])

        model = None

        if selection.isdigit():
            # Number selection
            idx = int(selection)
            if model_list and 1 <= idx <= len(model_list):
                model = model_list[idx - 1]
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(model_list)}")
                return True
        else:
            # Search by model name/ID
            selection_lower = selection.lower().strip()

            # Try exact match first
            for m in model_list:
                if selection_lower == m.lower():
                    model = m
                    break
                # Try partial match (contains)
                if selection_lower in m.lower():
                    if model is None:  # First match
                        model = m
                    else:
                        # Multiple matches - prefer shorter match
                        if len(m) < len(model):
                            model = m

            if not model:
                log.add_error(f"Model '{selection}' not found for {provider_id}")
                if model_list:
                    log.add_info(f"Available models: {', '.join(model_list[:5])}")
                    if len(model_list) > 5:
                        log.add_info(f"... and {len(model_list) - 5} more")
                return True

        self._awaiting_local_model = False
        self._connect_local_mode(provider_id, model, log)
        return True

    def _handle_acp_agent_selection(self, selection: str, log: ConversationLog) -> bool:
        """Handle ACP agent selection from numbered list."""
        # Check for _acp_agent_list (from :connect acp command)
        if hasattr(self, "_acp_agent_list") and self._acp_agent_list:
            try:
                idx = int(selection) - 1
                if 0 <= idx < len(self._acp_agent_list):
                    agent_id, agent_data = self._acp_agent_list[idx]
                    self._awaiting_acp_agent_selection = False

                    # Check if agent is installed
                    from superqode.commands.acp import check_agent_installed

                    is_installed = check_agent_installed(agent_data)

                    if is_installed:
                        # Connect to the agent
                        log.add_info(f"Connecting to {agent_data['name']}...")
                        self._connect_agent(agent_data["short_name"])
                        return True
                    else:
                        # Show install message
                        from superqode.agents.registry import get_agent_installation_info

                        install_info = get_agent_installation_info(agent_data)
                        install_cmd = install_info.get("command", "")

                        t = Text()
                        t.append(f"\n  ⚠️  ", style=THEME["warning"])
                        t.append(
                            f"{agent_data['name']} is not installed.\n\n",
                            style=f"bold {THEME['text']}",
                        )

                        if install_cmd:
                            t.append(f"  Install with:\n", style=THEME["muted"])
                            t.append(f"    ", style=THEME["dim"])
                            t.append(f"{install_cmd}\n", style=THEME["cyan"])
                            t.append(f"\n  Or use: ", style=THEME["dim"])
                            t.append(
                                f":acp install {agent_data['short_name']}\n", style=THEME["cyan"]
                            )
                        else:
                            t.append(
                                f"  Installation instructions not available.\n",
                                style=THEME["muted"],
                            )
                            t.append(f"  Try: ", style=THEME["dim"])
                            t.append(
                                f":acp install {agent_data['short_name']}\n", style=THEME["cyan"]
                            )

                        log.write(t)
                        return True
                else:
                    log.add_error(
                        f"Invalid selection. Choose a number between 1 and {len(self._acp_agent_list)}"
                    )
                    return True
            except ValueError:
                # Not a number, might be a command or agent name
                pass

        return False

    def _handle_byok_model_selection(self, selection: str, log: ConversationLog):
        """Handle model selection from :connect picker with search support."""
        if not hasattr(self, "_byok_selected_provider"):
            return False

        # CRITICAL: Only process model selection if we're actually awaiting it
        # and the model list has been displayed (not immediately after provider selection)
        if not getattr(self, "_awaiting_byok_model", False):
            return False

        # CRITICAL: Prevent the same input that selected the provider from being
        # processed as a model selection
        last_provider_selection = getattr(self, "_last_provider_selection", None)
        if last_provider_selection and selection.strip() == last_provider_selection:
            # This is the same input that selected the provider - ignore it
            return False

        provider_id = self._byok_selected_provider
        model_list = getattr(self, "_byok_model_list", [])

        # CRITICAL: Ensure model list is populated before allowing selection
        if not model_list:
            return False

        model = None

        if selection.isdigit():
            # Number selection
            idx = int(selection)
            if model_list and 1 <= idx <= len(model_list):
                model = model_list[idx - 1]
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(model_list)}")
                return True
        else:
            # Search by model name/ID
            selection_lower = selection.lower().strip()

            # CRITICAL: Prevent provider names from matching models
            # If the selection matches the provider name, don't auto-select
            if selection_lower == provider_id.lower() or selection_lower in provider_id.lower():
                log.add_error(
                    f"'{selection}' is the provider name. Please enter a model number (1-{len(model_list)}) or model name."
                )
                return True

            # Try exact match first
            for m in model_list:
                if selection_lower == m.lower():
                    model = m
                    break
                # Try partial match (contains)
                if selection_lower in m.lower():
                    if model is None:  # First match
                        model = m
                    else:
                        # Multiple matches - be more specific
                        if selection_lower in m.lower() and len(m) < len(model):
                            model = m  # Prefer shorter match

            if not model:
                log.add_error(f"Model '{selection}' not found for {provider_id}")
                log.add_info(f"Available models: {', '.join(model_list[:5])}")
                if len(model_list) > 5:
                    log.add_info(f"... and {len(model_list) - 5} more")
                return True

        self._awaiting_byok_model = False
        self._connect_byok_mode(provider_id, model, log)
        return True

    def _connect_byok_mode(
        self, provider: str, model: str, log: ConversationLog, resolved_role=None
    ):
        """Connect to BYOK mode with specified provider/model.

        Args:
            provider: Provider ID (e.g., "ollama", "anthropic")
            model: Model name (e.g., "llama3.2:3b", "claude-sonnet-4")
            log: Conversation log for output
            resolved_role: Optional ResolvedRole object for role-based connections
                          (used to inject job description into system prompt)
        """
        # Clear any existing ACP connection when switching to BYOK
        if hasattr(self, "_acp_client") and self._acp_client:
            # Disconnect ACP client if switching from ACP to BYOK
            import asyncio

            try:
                asyncio.create_task(self._acp_client.stop())
            except Exception:
                pass
            self._acp_client = None

        # Clear session state
        session = get_session()
        if hasattr(session, "connected_agent"):
            session.connected_agent = None
        if hasattr(session, "acp_manager"):
            session.acp_manager = None
        from superqode.providers.registry import PROVIDERS, ProviderCategory
        from superqode.pure_mode import PureMode
        from superqode.agent.system_prompts import SystemPromptLevel
        from superqode.providers.usage import get_usage_tracker
        import os

        # Get provider info
        provider_def = PROVIDERS.get(provider)
        provider_name = provider_def.name if provider_def else provider.upper()

        # Show experimental warning for vLLM and SGLang
        if provider in ("vllm", "sglang"):
            t = Text()
            t.append(f"\n  ⚠️  ", style=THEME["warning"])
            t.append(f"Experimental Provider Warning\n\n", style=f"bold {THEME['warning']}")
            t.append(f"  {provider_name} support is ", style=THEME["text"])
            t.append(f"EXPERIMENTAL", style=f"bold {THEME['warning']}")
            t.append(f". Features may be unstable and behavior may change.\n", style=THEME["text"])
            t.append(f"  Please report any issues you encounter.\n\n", style=THEME["dim"])
            log.write(t)

        # Check API key before connecting (except for local providers)
        if (
            provider_def
            and provider_def.category != ProviderCategory.LOCAL
            and provider_def.env_vars
        ):
            has_key = False
            for env_var in provider_def.env_vars:
                if os.environ.get(env_var):
                    has_key = True
                    break

            if not has_key:
                t = Text()
                t.append(f"\n  ⚠️  ", style=THEME["warning"])
                t.append("API Key Required\n\n", style=f"bold {THEME['warning']}")
                t.append(f"  Provider: ", style=THEME["muted"])
                t.append(f"{provider_name}\n", style=THEME["text"])
                t.append(f"  Required: ", style=THEME["muted"])
                t.append(f"{' or '.join(provider_def.env_vars)}\n\n", style=THEME["yellow"])
                t.append(f"  Setup:\n", style=THEME["muted"])
                t.append(f"    1. Get API key from: ", style=THEME["dim"])
                if provider_def.docs_url:
                    t.append(f"{provider_def.docs_url}\n", style=THEME["cyan"])
                else:
                    t.append(f"{provider_name} website\n", style=THEME["cyan"])
                t.append(f"    2. Export key:\n", style=THEME["dim"])
                for env_var in provider_def.env_vars[:1]:  # Show first option
                    t.append(f"       export {env_var}='your-api-key'\n", style=THEME["cyan"])
                t.append(
                    f"    3. Add to ~/.zshrc or ~/.bashrc for persistence\n\n", style=THEME["dim"]
                )
                t.append(f"  Then run: ", style=THEME["muted"])
                t.append(f":connect {provider}/{model}\n", style=THEME["success"])
                log.write(t)
                return

        # Store previous provider for quick switching
        if hasattr(self, "current_provider") and self.current_provider:
            self._previous_provider = (self.current_provider, self.current_model)

        # For BYOK, we use the provider session infrastructure with STANDARD system prompt
        # (includes role context) instead of MINIMAL
        if not hasattr(self, "_pure_mode"):
            self._pure_mode = PureMode()

        # Set up callbacks
        # Note: BYOK runs in the same event loop as Textual, but callbacks are invoked from async code
        # Use call_later to ensure UI updates happen on the next event loop tick
        # (ACP uses call_from_thread() because it runs in a separate subprocess)
        def on_tool_call(name: str, args: dict):
            # Schedule UI update on the next event loop tick
            self.call_later(self._show_pure_tool_call, name, args, log)

        def on_tool_result(name: str, result):
            # Schedule UI update on the next event loop tick
            self.call_later(self._show_pure_tool_result, name, result, log)

        async def on_thinking_async(text: str):
            """Handle thinking logs from AgentLoop - same formatting as ACP.

            For local models, completely disable thinking logs - only show the animation.
            """
            # For local models, completely disable all thinking logs
            # Only the animation (_start_thinking) will be shown, not individual thinking log lines
            if provider_def and provider_def.category == ProviderCategory.LOCAL:
                return  # Suppress all thinking logs for local models

            # Schedule UI update on the next event loop tick
            # ACP uses call_from_thread() because it runs in a separate subprocess
            self.call_later(self._show_thinking_line, text, log)

        # For local models, completely disable thinking logs by setting callback to None
        # This prevents the agent from even trying to call on_thinking
        if provider_def and provider_def.category == ProviderCategory.LOCAL:
            self._pure_mode.on_tool_call = on_tool_call
            self._pure_mode.on_tool_result = on_tool_result
            self._pure_mode.on_thinking = None  # Completely disable thinking logs for local models
        else:
            self._pure_mode.on_tool_call = on_tool_call
            self._pure_mode.on_tool_result = on_tool_result
            self._pure_mode.on_thinking = on_thinking_async

        # Use STANDARD for cloud providers, MINIMAL for local to avoid confusion
        from superqode.providers.registry import ProviderCategory
        from superqode.agent.system_prompts import get_job_description_prompt
        from superqode.config import find_config_file
        from pathlib import Path

        system_level = (
            SystemPromptLevel.MINIMAL
            if provider_def and provider_def.category == ProviderCategory.LOCAL
            else SystemPromptLevel.STANDARD
        )

        # Determine project root (where superqode.yaml is located)
        # For local models, restrict to project root to prevent filesystem traversal
        config_file = find_config_file()
        if config_file:
            project_root = config_file.parent.resolve()
        else:
            # If no config file found, use current directory
            project_root = Path.cwd().resolve()

        # For local providers, use project root as working directory
        # For cloud providers, use current directory (existing behavior)
        working_dir = (
            project_root
            if (provider_def and provider_def.category == ProviderCategory.LOCAL)
            else None
        )

        # Extract job description from resolved role if available
        job_description = None
        if resolved_role:
            base_job_description = getattr(resolved_role, "job_description", None) or ""
            if base_job_description:
                # Build job description prompt for the role
                job_description = get_job_description_prompt(
                    base_job_description, role_config=resolved_role
                )

        # Connect with job description and working directory for role-based connections
        self._pure_mode.connect(
            provider,
            model,
            system_level,
            working_directory=working_dir,
            job_description=job_description,
            role_config=resolved_role,
        )

        # Update state
        session = get_session()
        # Determine execution mode: "local" for local providers, "byok" for cloud
        is_local = provider_def and provider_def.category == ProviderCategory.LOCAL
        # Check if session already has execution_mode set (from role)
        if hasattr(session, "execution_mode") and session.execution_mode == "local":
            exec_mode = "local"
        elif is_local:
            exec_mode = "local"
        else:
            exec_mode = "byok"

        session.execution_mode = exec_mode

        self.current_mode = exec_mode
        self.current_agent = ""
        self.current_model = model
        self.current_provider = provider

        # Start usage tracking
        tracker = get_usage_tracker()
        tracker.set_provider(provider, model)

        # Save to persistent config
        self._save_byok_config(provider, model)

        # Update badge
        badge = self.query_one("#mode-badge", ModeBadge)
        badge.mode = exec_mode
        badge.agent = ""
        badge.model = model
        badge.provider = provider
        badge.execution_mode = exec_mode

        # Clear screen and show fresh workspace
        mode_label = "LOCAL" if exec_mode == "local" else "BYOK"
        self._clear_for_workspace(log, f"{mode_label} • {provider_name}")

        # Show connection success message
        log.add_success(f"✓ Connected to {provider_name}/{model}")

        # For local providers, show setup instructions immediately
        if provider_def and provider_def.category == ProviderCategory.LOCAL:
            if provider == "ollama":
                import os

                ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                log.add_info(f"Ollama host: {ollama_host}")
                log.add_info("💡 Make sure Ollama is running:")
                log.add_info("   1. Start Ollama: ollama serve")
                log.add_info(f"   2. Verify model: ollama list | grep {model}")
                log.add_info(f"   3. Pull if needed: ollama pull {model}")
            elif provider == "mlx":
                # Show MLX-specific guidance
                log.add_info("💡 MLX models require a running server")
                log.add_info("To start the MLX server:")
                log.add_info(
                    f"   1. [cyan]superqode providers mlx setup[/cyan] - Complete setup guide"
                )
                log.add_info(
                    f"   2. [cyan]superqode providers mlx server --model {model}[/cyan] - Get server command"
                )
                log.add_info("   3. Run the server command in a separate terminal")
                log.add_info("   4. Try your message again")
                log.add_info("")
                log.add_info(
                    "✅ [green]Supported formats:[/green] MLX (.npz), safetensors (auto-converted)"
                )
                log.add_info(
                    "✅ [green]Working architectures:[/green] Standard transformers, QWen, Llama, Mistral, Phi"
                )
                log.add_info(
                    "❌ [red]Not supported:[/red] MoE models (Mixtral, some gpt-oss variants)"
                )
            elif provider == "lmstudio":
                # Show LM Studio-specific guidance
                log.add_info("💡 LM Studio requires the GUI application and local server")
                log.add_info("Complete setup:")
                log.add_info("   1. [cyan]Download LM Studio:[/cyan] https://lmstudio.ai/")
                log.add_info("   2. [cyan]Open LM Studio application[/cyan]")
                log.add_info(
                    "   3. [cyan]Download a model[/cyan] (search for 'qwen3-30b' or 'llama3.2-3b')"
                )
                log.add_info("   4. [cyan]Load the model[/cyan] in LM Studio")
                log.add_info(
                    "   5. [cyan]Start Local Server[/cyan] (Local Server tab → Start Server)"
                )
                log.add_info("   6. [cyan]Try your message again[/cyan]")
                log.add_info("")
                log.add_info(
                    "✅ [green]Supported:[/green] OpenAI-compatible API at localhost:1234/v1/chat/completions"
                )
                log.add_info("✅ [green]Models:[/green] Any GGUF model loaded in LM Studio")
                log.add_info("💡 [yellow]Tip:[/yellow] Test your model in LM Studio's chat first")

            log.add_info("Testing connection...")
            log.add_info("(This runs in background - you can start chatting)")
            self.run_worker(self._test_local_connection(provider, model, log))
        else:
            log.add_info("Ready to chat! Type your message below.")

    async def _test_local_connection(self, provider: str, model: str, log: ConversationLog):
        """Test connection to a local provider."""
        try:
            from superqode.providers.gateway.litellm_gateway import LiteLLMGateway
            from superqode.providers.gateway.base import Message
            import os

            gateway = LiteLLMGateway()

            # Show what we're testing
            model_string = gateway.get_model_string(provider, model)
            log.add_info(f"Testing: {model_string}")

            # Check base URL for Ollama
            if provider == "ollama":
                ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                log.add_info(f"Ollama host: {ollama_host}")

            # Make a simple test request
            test_messages = [Message(role="user", content="Say 'test'")]
            response = await gateway.chat_completion(
                messages=test_messages,
                model=model,
                provider=provider,
                max_tokens=10,
            )

            if response and response.content:
                log.add_success(f"✓ Connected to {provider}/{model}")
                log.add_info(f"Test response: {response.content[:50]}")
                # Clear screen and show fresh workspace
                self._clear_for_workspace(log, f"BYOK • {provider}")
            else:
                log.add_warning(f"⚠️  Connected but no response content. Response: {response}")
                self._clear_for_workspace(log, f"BYOK • {provider}")

            # Ensure focus returns to input after connection test
            # Use set_timer since we're in the app's event loop, not a separate thread
            self.set_timer(0.1, self._ensure_input_focus)

        except Exception as e:
            import traceback

            error_msg = str(e)
            error_type = type(e).__name__
            log.add_error(f"✗ Connection test failed ({error_type}): {error_msg}")

            # Show full traceback for debugging
            if hasattr(self, "show_thinking_logs") and self.show_thinking_logs:
                log.add_info(f"Traceback:\n{traceback.format_exc()}")

            # Show helpful hints based on provider
            if provider == "ollama":
                log.add_info("💡 Troubleshooting:")
                log.add_info("   1. Make sure Ollama is running: ollama serve")
                log.add_info(f"   2. Check if model exists: ollama list")
                log.add_info(f"   3. Pull the model if needed: ollama pull {model}")
                log.add_info(f"   4. Test manually: curl http://localhost:11434/api/tags")
                log.add_info(
                    f"   5. Check Ollama host: echo $OLLAMA_HOST (default: http://localhost:11434)"
                )
            elif provider == "lmstudio":
                log.add_info("💡 Troubleshooting:")
                log.add_info("   1. Open LM Studio application")
                log.add_info("   2. Load a model in LM Studio")
                log.add_info("   3. Start the local server (usually on port 1234)")
            elif provider in ("vllm", "sglang", "mlx", "tgi"):
                log.add_info(f"💡 Make sure {provider} server is running and accessible")
                log.add_info(f"   Check the base URL in environment or provider config")

            # Still allow connection attempt (user might fix the issue)
            self._clear_for_workspace(log, f"BYOK • {provider}")

            # Ensure focus returns to input even after error
            # Use set_timer since we're in the app's event loop, not a separate thread
            self.set_timer(0.1, self._ensure_input_focus)

    # =========================================================================
    # BYOK ENHANCED COMMANDS
    # =========================================================================

    def _connect_byok_cmd(self, args: str, log: ConversationLog):
        """Handle :connect byok command - Interactive provider/model picker."""
        args = args.strip()

        # If no args provided, show the provider picker
        # This is the main entry point for :connect byok
        if not args:
            # Clear any existing state that might interfere
            self._awaiting_byok_model = False
            self._awaiting_byok_provider = False
            if hasattr(self, "_byok_selected_provider"):
                delattr(self, "_byok_selected_provider")
            if hasattr(self, "_byok_model_list"):
                delattr(self, "_byok_model_list")
            # Show the provider list
            self._show_connect_picker(log)
            return

        # :connect - (switch to previous)
        if args == "-":
            self._connect_previous(log)
            return

        # :connect ! (show history)
        if args == "!":
            self._connect_history(log)
            return

        # :connect last (reconnect to last used)
        if args == "last":
            self._connect_last(log)
            return

        # :connect <provider>[/<model>] (direct connect with / separator)
        if args:
            # Prevent "byok", "acp", "local" from being treated as provider names
            # These are subcommands, not providers
            if args.lower().strip() in ("byok", "acp", "local"):
                # This shouldn't happen if parsing is correct, but be defensive
                self._show_connect_picker(log)
                return

            # Support provider/model syntax
            if "/" in args:
                parts = args.split("/", 1)
                provider = parts[0].strip()
                model = parts[1].strip() if len(parts) > 1 else None
                if provider and model:
                    self._connect_byok_mode(provider, model, log)
                    return

            # Support space-separated syntax
            parts = args.split(maxsplit=1)
            provider = parts[0].strip()
            model = parts[1].strip() if len(parts) > 1 else None

            # Double-check provider is not a subcommand
            if provider.lower() in ("byok", "acp", "local"):
                self._show_connect_picker(log)
                return

            if model:
                # Direct connect with provider and model
                self._connect_byok_mode(provider, model, log)
            else:
                # Show models for this provider - always use numbered list
                self._show_provider_models(provider, log, use_picker=False)
            return

    def _connect_local_cmd(self, args: str, log: ConversationLog):
        """Handle :connect local command - Interactive local provider/model picker."""
        args = args.strip()

        # :connect local - (switch to previous)
        if args == "-":
            self._connect_previous(log)
            return

        # :connect local ! (show history)
        if args == "!":
            self._connect_history(log)
            return

        # :connect local last (reconnect to last used)
        if args == "last":
            self._connect_last(log)
            return

        # :connect local <provider>[/<model>] (direct connect with / separator)
        if args:
            # Support provider/model syntax
            if "/" in args:
                parts = args.split("/", 1)
                provider = parts[0].strip()
                model = parts[1].strip() if len(parts) > 1 else None
                if provider and model:
                    self._connect_local_mode(provider, model, log)
                    return

            # Support space-separated syntax
            parts = args.split(maxsplit=1)
            provider = parts[0]
            model = parts[1] if len(parts) > 1 else None

            if model:
                # Direct connect with provider and model
                self._connect_local_mode(provider, model, log)
            else:
                # Show models for this local provider
                self._show_local_provider_models(provider, log)
            return

        # :connect local (show interactive local provider picker)
        # CRITICAL: Clear any existing state to ensure we show provider picker, not models
        self._awaiting_local_provider = False
        self._awaiting_local_model = False
        if hasattr(self, "_local_selected_provider"):
            delattr(self, "_local_selected_provider")
        if hasattr(self, "_local_provider_list"):
            delattr(self, "_local_provider_list")
        if hasattr(self, "_local_model_list"):
            delattr(self, "_local_model_list")
        if hasattr(self, "_local_highlighted_provider_index"):
            self._local_highlighted_provider_index = 0
        if hasattr(self, "_local_highlighted_model_index"):
            self._local_highlighted_model_index = 0

        # Now show the provider picker
        self._show_local_provider_picker(log)

    def _connect_previous(self, log: ConversationLog):
        """Switch to previous provider/model."""
        if hasattr(self, "_previous_provider") and self._previous_provider:
            provider, model = self._previous_provider
            self._connect_byok_mode(provider, model, log)
        else:
            log.add_info("No previous provider to switch to")
            log.add_system("Use :connect to select a provider")

    def _connect_history(self, log: ConversationLog):
        """Show connection history."""
        history = self._load_byok_history()

        if not history:
            log.add_info("No connection history yet")
            log.add_system("Use :connect to connect to a provider")
            return

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Connection History\n\n", style=f"bold {THEME['text']}")

        for i, entry in enumerate(history[:10], 1):
            provider, model = entry.split("/", 1) if "/" in entry else (entry, "")
            t.append(f"  [{i}] ", style=THEME["dim"])
            t.append(f"{provider}", style=f"bold {THEME['success']}")
            if model:
                t.append(f"/{model}", style=THEME["muted"])
            t.append("\n", style="")

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":connect <number>", style=THEME["success"])
        t.append(" to reconnect\n", style=THEME["muted"])

        log.write(t)

    def _connect_last(self, log: ConversationLog):
        """Connect to the last used provider/model."""
        config = self._load_byok_config()

        if config.get("last_provider") and config.get("last_model"):
            self._connect_byok_mode(config["last_provider"], config["last_model"], log)
        else:
            log.add_info("No previous connection saved")
            log.add_system("Use :connect to select a provider")

    def _connect_local_mode(self, provider: str, model: str, log: ConversationLog):
        """Connect to LOCAL mode with specified provider/model.

        This is a wrapper around _connect_byok_mode() that ensures
        local providers are properly identified. Local providers are
        already handled in _connect_byok_mode() via ProviderCategory.LOCAL.
        """
        # HuggingFace cached models need a local runtime (e.g., MLX/TGI), not HF Inference API
        if provider == "huggingface-local":
            model_lower = model.lower()
            if "mlx" in model_lower or model_lower.startswith("mlx-community/"):
                log.add_info("Routing cached MLX model to MLX local provider.")
                provider = "mlx"
            else:
                log.add_error(
                    "HuggingFace cached models require a local runtime (mlx/tgi/vllm/sglang)."
                )
                log.add_info("Use: :connect local <provider> <model>")
                return

        # Local providers use the same connection mechanism as BYOK
        # but are identified by ProviderCategory.LOCAL
        self._connect_byok_mode(provider, model, log)

    def _show_local_provider_picker(self, log: ConversationLog, clear_log: bool = True):
        """Show interactive local provider picker with discovery.

        Args:
            log: The conversation log widget
            clear_log: If True, clear the log before writing (default: True).
                      Set to False when updating during navigation to reduce flickering.
        """
        # CRITICAL: Force complete state reset - we MUST show provider picker, not models
        # Clear ALL local-related state to prevent any auto-selection
        self._awaiting_local_provider = True
        self._awaiting_local_model = False  # MUST be False - we're selecting provider, not model
        # Clear any BYOK selection state so numeric input routes to local picker
        self._awaiting_byok_provider = False
        self._awaiting_byok_model = False
        self._just_showed_byok_picker = False

        # Delete local selection state (but keep _local_provider_list - we'll set it later)
        for attr in ["_local_selected_provider", "_local_model_list", "_local_cached_models"]:
            if hasattr(self, attr):
                delattr(self, attr)

        # Reset indices - will be set properly below
        self._local_highlighted_provider_index = 0
        if hasattr(self, "_local_highlighted_model_index"):
            self._local_highlighted_model_index = 0

        from superqode.providers.registry import PROVIDERS, ProviderCategory, get_local_providers
        from superqode.providers.local.discovery import get_discovery_service
        import asyncio

        # Get local providers from registry FIRST
        local_providers = get_local_providers()

        # Filter out unsupported providers from TUI display
        # (they remain in registry for backward compatibility)
        unsupported_local_providers = {"llamacpp", "ollama-cloud"}
        local_providers = {
            pid: pdef
            for pid, pdef in local_providers.items()
            if pid not in unsupported_local_providers
        }

        # Add HuggingFace to local providers list (it's in MODEL_HOSTS category but available via :connect local)
        if "huggingface-local" in PROVIDERS:
            local_providers["huggingface-local"] = PROVIDERS["huggingface-local"]

        t = Text()
        t.append(f"\n", style="")
        t.append("  " + "=" * 60 + "\n", style=THEME["muted"])
        t.append(f"  ◈ ", style=f"bold {THEME['purple']}")
        t.append("SELECT LOCAL PROVIDER", style=f"bold {THEME['purple']}")
        t.append(
            f" - Choose from {len(local_providers)} providers\n", style=f"bold {THEME['text']}"
        )
        t.append("  " + "=" * 60 + "\n", style=THEME["muted"])
        t.append("  💻 Local/self-hosted models - No API key required\n\n", style=THEME["muted"])

        if not local_providers:
            t.append("  ⚠️  No local providers configured\n", style=THEME["warning"])
            t.append(
                "  Local providers include: ollama, lmstudio, mlx, vllm, etc.\n", style=THEME["dim"]
            )
            if clear_log:
                log.clear()
            log.write(t)
            return

        # Sort providers: prioritize main ones (Ollama, MLX, LM Studio, vLLM, SGLang) first
        priority_order = ["ollama", "mlx", "lmstudio", "vllm", "sglang"]

        def sort_key(item):
            provider_id, _ = item
            if provider_id in priority_order:
                return (0, priority_order.index(provider_id))
            return (1, provider_id)

        # Show local providers with highlighting
        highlighted_idx = getattr(self, "_local_highlighted_provider_index", 0)
        local_providers_list = sorted(local_providers.items(), key=sort_key)

        # Debug: Ensure all providers are included
        if not local_providers_list:
            t.append("  ⚠️  No local providers found in registry\n", style=THEME["warning"])
            if clear_log:
                log.clear()
            log.write(t)
            return

        # Display all providers - ensure we show the complete list
        provider_count = len(local_providers_list)
        t.append(f"  Available Local Providers ({provider_count}):\n\n", style=THEME["text"])

        # Debug: Log all provider IDs to verify they're all included
        provider_ids = [pid for pid, _ in local_providers_list]

        # Provider-specific emojis
        provider_emojis = {
            "ollama": "🐼",  # Panda
            "lmstudio": "🎨",  # Paint palette (GUI application)
            "mlx": "🍏",  # Green Apple (Apple Silicon)
            "vllm": "🚀",  # Rocket (high performance)
            "sglang": "🪝",  # Hook
            "tgi": "📚",  # Books
            "huggingface": "🤗",  # HuggingFace signature emoji
            "openai-compatible": "🔌",  # Plug (generic connection)
        }

        # Iterate through ALL providers - no filtering, no limits
        # Make display more compact to show all providers
        for idx, (provider_id, provider_def) in enumerate(local_providers_list, 1):
            # Get provider-specific emoji or fallback to default
            status_icon = provider_emojis.get(provider_id, "🟢")

            # Show all providers uniformly without highlighting/arrow indicators
            t.append(f"    [{idx}] ", style=THEME["dim"])
            t.append(f"{status_icon} ", style=THEME["success"])
            t.append(f"{provider_def.name}", style=f"bold {THEME['cyan']}")
            if provider_id in ("vllm", "sglang"):
                t.append(" [EXPERIMENTAL]", style=f"bold {THEME['warning']}")
            t.append(f" ({provider_id})", style=THEME["muted"])

            # Show notes on same line if short, otherwise new line
            if provider_def.notes and len(provider_def.notes) < 60:
                t.append(f" - {provider_def.notes}", style=THEME["dim"])
            t.append("\n", style="")

        # Show summary of all providers at the end
        t.append(f"\n  📋 All {provider_count} Local Providers: ", style=THEME["muted"])
        provider_names = ", ".join([pdef.name for _, pdef in local_providers_list])
        t.append(f"{provider_names}\n", style=THEME["dim"])

        t.append("\n", style="")
        t.append("  " + "=" * 60 + "\n", style=THEME["muted"])
        t.append(f"\n  ⌨️  ", style=f"bold {THEME['success']}")
        t.append(f"ENTER A NUMBER (1-{provider_count})", style=f"bold {THEME['success']}")
        t.append(f" to select a provider\n\n", style=f"bold {THEME['text']}")
        t.append(f"    Example: Type ", style=THEME["dim"])
        t.append(f"1", style=f"bold {THEME['cyan']}")
        t.append(f" then press Enter for {local_providers_list[0][1].name}\n", style=THEME["dim"])
        t.append(f"\n  💡 Alternative: ", style=THEME["muted"])
        t.append(f":connect local <provider>/<model>\n", style=THEME["cyan"])
        t.append(f"    Example: ", style=THEME["dim"])
        t.append(f":connect local ollama/llama3.2\n", style=THEME["cyan"])

        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(t)
            log.scroll_home(animate=False)
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))
        else:
            # Update during navigation - clear and write but preserve scroll position better
            # by not calling scroll_home which resets to top
            log.auto_scroll = False
            log.clear()
            log.write(t)
            # Don't scroll to home on navigation updates to reduce flickering
            # The scroll will be adjusted by _scroll_to_highlighted_item if needed
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))

        # Set up selection handler for local providers
        # CRITICAL: Always set these flags to ensure provider picker is shown, NOT model selection
        # This MUST happen AFTER we write to log, to prevent any race conditions
        self._awaiting_local_provider = True
        self._awaiting_local_model = False  # Make sure we're NOT in model selection mode
        self._local_provider_list = local_providers_list  # Use sorted list
        # Preserve current highlight if already set, otherwise start with first
        if not hasattr(self, "_local_highlighted_provider_index"):
            self._local_highlighted_provider_index = 0
        # CRITICAL: Ensure NO provider is selected - we must show the picker
        if hasattr(self, "_local_selected_provider"):
            delattr(self, "_local_selected_provider")
        if hasattr(self, "_local_model_list"):
            delattr(self, "_local_model_list")
        if hasattr(self, "_local_cached_models"):
            delattr(self, "_local_cached_models")

        # CRITICAL: Set flag to prevent auto-selection when picker first appears
        # This prevents empty input from immediately selecting the first provider
        self._just_showed_local_picker = True
        # Clear the flag after a delay to allow normal selection
        self.set_timer(0.5, lambda: setattr(self, "_just_showed_local_picker", False))

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

    def _show_connect_type_picker(self, log: ConversationLog, clear_log: bool = True):
        """Show picker to choose between ACP, BYOK, and LOCAL connection types.

        Args:
            log: The conversation log widget
            clear_log: If True, clear the log before writing (default: True).
                      Set to False when updating during navigation to reduce flickering.
        """
        # Clear any BYOK state to prevent interference
        self._awaiting_byok_provider = False
        self._awaiting_byok_model = False
        if hasattr(self, "_byok_selected_provider"):
            delattr(self, "_byok_selected_provider")
        if hasattr(self, "_byok_connect_list"):
            delattr(self, "_byok_connect_list")

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Select Connection Type\n\n", style=f"bold {THEME['text']}")

        # Show connection types with highlighting
        highlighted_idx = getattr(self, "_byok_highlighted_connect_type_index", 0)

        for i, (num, name, color, desc, example) in enumerate(
            [
                (
                    1,
                    "🔌 ACP Agents",
                    THEME["pink"],
                    "Connect via ACP (Agent Communication Protocol)",
                    ":connect acp opencode",
                ),
                (
                    2,
                    "🔑 BYOK Providers",
                    THEME["success"],
                    "Bring Your Own Key - Direct provider/model connection",
                    ":connect byok anthropic/claude-4-5-sonnet",
                ),
                (
                    3,
                    "💻 LOCAL Providers",
                    THEME["cyan"],
                    "Local/self-hosted models - No API key required",
                    ":connect local ollama/llama3.2",
                ),
            ]
        ):
            is_highlighted = i == highlighted_idx
            if is_highlighted:
                t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                t.append(f"[{num}] ", style=f"bold {THEME['success']}")
                t.append(f"{name}", style=f"bold {THEME['success']}")
                t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                t.append(f"     {desc}\n", style=THEME["muted"])
                t.append(f"     Example: ", style=THEME["dim"])
                t.append(f"{example}\n\n", style=THEME["cyan"])
            else:
                t.append(f"    [{num}] ", style=THEME["dim"])
                t.append(f"{name}", style=f"bold {color}")
                t.append("\n", style="")
                t.append(f"     {desc}\n", style=THEME["muted"])
                t.append(f"     Example: ", style=THEME["dim"])
                t.append(f"{example}\n\n", style=THEME["cyan"])

        t.append(f"  💡 Quick Connect:\n", style=THEME["muted"])
        t.append(f"    ⌨️  ", style=THEME["dim"])
        t.append(f"↑↓", style=THEME["cyan"])
        t.append(" Arrow keys to navigate  ", style=THEME["dim"])
        t.append(f"Enter", style=THEME["cyan"])
        t.append(" to select highlighted type\n", style=THEME["dim"])
        t.append(f"    Or type ", style=THEME["dim"])
        t.append("1", style=THEME["cyan"])
        t.append(" for ACP, ", style=THEME["dim"])
        t.append("2", style=THEME["cyan"])
        t.append(" for BYOK, or ", style=THEME["dim"])
        t.append("3", style=THEME["cyan"])
        t.append(" for LOCAL\n", style=THEME["dim"])
        t.append(f"    Or use: ", style=THEME["dim"])
        t.append(":connect acp", style=THEME["pink"])
        t.append(", ", style=THEME["dim"])
        t.append(":connect byok", style=THEME["success"])
        t.append(", or ", style=THEME["dim"])
        t.append(":connect local", style=THEME["cyan"])
        t.append("\n", style="")

        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(t)
            log.scroll_home(animate=False)
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))
        else:
            # Update during navigation - clear and write but don't scroll to home
            log.auto_scroll = False
            log.clear()
            log.write(t)
            # Don't scroll to home on navigation updates to reduce flickering
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))

        # Set up selection handler
        self._awaiting_connect_type = True
        self._byok_highlighted_connect_type_index = highlighted_idx  # Preserve current highlight

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

    def _show_byok_providers(self, log: ConversationLog, clear_log: bool = True):
        """Show BYOK provider picker - alias for _show_connect_picker."""
        # CRITICAL: Explicitly clear ALL state that might cause it to skip to models
        # This must be done BEFORE calling _show_connect_picker
        # BUT: During navigation (clear_log=False), preserve the connect list
        self._awaiting_byok_model = False
        self._awaiting_byok_provider = False  # Set to False first
        if hasattr(self, "_byok_selected_provider"):
            delattr(self, "_byok_selected_provider")
        if hasattr(self, "_byok_model_list"):
            delattr(self, "_byok_model_list")
        # Only clear connect list on initial display, not during navigation
        if clear_log and hasattr(self, "_byok_connect_list"):
            delattr(self, "_byok_connect_list")
        # Set flag to prevent any immediate model display (only on initial display)
        if clear_log:
            self._just_showed_byok_picker = True
            # Clear the flag after a delay
            self.set_timer(0.5, lambda: setattr(self, "_just_showed_byok_picker", False))
        # Now show the provider picker - it will set _awaiting_byok_provider = True
        self._show_connect_picker(log, clear_log=clear_log)

    def _show_connect_picker(self, log: ConversationLog, clear_log: bool = True):
        """Show interactive provider picker with model counts and API key guidance."""
        from superqode.providers.registry import PROVIDERS, ProviderCategory, get_free_providers
        from superqode.providers.models import get_models_for_provider, get_data_source
        import os

        # CRITICAL: Clear any model selection state to ensure we show provider list, not models
        # This must be done FIRST before any other logic
        # Force clear ALL BYOK-related state to prevent any auto-selection
        # BUT: During navigation (clear_log=False), preserve the connect list
        self._awaiting_byok_model = False
        self._awaiting_byok_provider = (
            False  # Set to False first, then True after we build the list
        )
        if hasattr(self, "_byok_selected_provider"):
            delattr(self, "_byok_selected_provider")
        if hasattr(self, "_byok_model_list"):
            delattr(self, "_byok_model_list")
        # Only clear the connect list on initial display, not during navigation
        if clear_log and hasattr(self, "_byok_connect_list"):
            delattr(self, "_byok_connect_list")

        # Reset provider highlight index only on initial display, preserve during navigation
        if clear_log:
            # On initial display, reset to 0
            if not hasattr(self, "_byok_highlighted_provider_index"):
                self._byok_highlighted_provider_index = 0
            else:
                self._byok_highlighted_provider_index = 0
        else:
            # During navigation, preserve the current index (don't reset)
            if not hasattr(self, "_byok_highlighted_provider_index"):
                self._byok_highlighted_provider_index = 0

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Select Provider\n\n", style=f"bold {THEME['text']}")

        # Show data source info
        data_source = get_data_source()
        t.append(f"  📊 Source: {data_source}\n\n", style=THEME["dim"])

        # Get providers with free models
        free_providers = get_free_providers()
        free_provider_ids = set(free_providers.keys())

        # Helper function to get provider info
        def get_provider_info(pid, pdef):
            configured = False
            missing_keys = []
            if not pdef.env_vars:
                configured = True
            else:
                for env_var in pdef.env_vars:
                    if os.environ.get(env_var):
                        configured = True
                        break
                    else:
                        missing_keys.append(env_var)

            try:
                models = get_models_for_provider(pid)
                model_count = len(models)
            except Exception:
                model_count = len(pdef.example_models) if pdef.example_models else 0

            return (pid, pdef, configured, missing_keys, model_count)

        # Group by category
        category_order = {
            ProviderCategory.US_LABS: ("🇺🇸 US Labs", THEME["cyan"]),
            ProviderCategory.CHINA_LABS: ("🇨🇳 China Labs", THEME["error"]),
            ProviderCategory.OTHER_LABS: ("🌍 Other Labs", THEME["success"]),
            ProviderCategory.MODEL_HOSTS: ("🌐 Model Hosts", THEME["purple"]),
            ProviderCategory.LOCAL: ("🏠 Local / Self-Hosted", THEME["muted"]),
        }

        providers_by_category = {}
        for pid, pdef in PROVIDERS.items():
            category = pdef.category
            if category not in providers_by_category:
                providers_by_category[category] = []

            providers_by_category[category].append(get_provider_info(pid, pdef))

        idx = 1
        provider_list = []

        # Show Free Models section first if there are any
        if free_provider_ids:
            t.append(f"  🆓 Free Models\n", style=f"bold {THEME['success']}")
            free_providers_list = []
            for pid in free_provider_ids:
                pdef = PROVIDERS.get(pid)
                if not pdef:
                    continue
                free_providers_list.append(get_provider_info(pid, pdef))

            # Sort free providers by name
            free_providers_list.sort(key=lambda x: x[1].name)

            for pid, pdef, configured, missing_keys, model_count in free_providers_list:
                status = "✓" if configured else "○"
                status_style = THEME["success"] if configured else THEME["warning"]

                # Highlight current selection
                is_highlighted = (idx - 1) == getattr(self, "_byok_highlighted_provider_index", 0)
                if is_highlighted:
                    t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                    t.append(f"[{idx:2}] ", style=f"bold {THEME['success']}")
                    t.append(f"{status} ", style=status_style)
                    t.append(f"{pid:<15}", style=f"bold {THEME['success']}")
                    t.append(f"{pdef.name}", style=f"bold {THEME['success']}")
                    t.append(f" 🆓", style=f"bold {THEME['success']}")
                    if model_count > 0:
                        t.append(
                            f" ({model_count} model{'s' if model_count > 1 else ''})",
                            style=f"bold {THEME['success']}",
                        )
                    if not configured and pdef.env_vars:
                        t.append(
                            f" • Needs: {', '.join(missing_keys)}", style=f"bold {THEME['success']}"
                        )
                    t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                else:
                    t.append(f"    [{idx:2}] ", style=THEME["dim"])
                    t.append(f"{status} ", style=status_style)
                    t.append(f"{pid:<15}", style=THEME["text"])
                    t.append(f"{pdef.name}", style=THEME["muted"])
                    t.append(f" 🆓", style=THEME["success"])

                    # Show model count
                    if model_count > 0:
                        t.append(f" ({model_count} model", style=THEME["dim"])
                        if model_count > 1:
                            t.append("s", style=THEME["dim"])
                        t.append(")", style=THEME["dim"])

                    # Show API key requirement if not configured
                    if not configured and pdef.env_vars:
                        t.append(f" • Needs: {', '.join(missing_keys)}", style=THEME["yellow"])

                    t.append("\n", style="")

                provider_list.append((pid, pdef))
                idx += 1

            t.append("\n", style="")

        # Show providers grouped by category
        for category in [
            ProviderCategory.US_LABS,
            ProviderCategory.CHINA_LABS,
            ProviderCategory.OTHER_LABS,
            ProviderCategory.MODEL_HOSTS,
            ProviderCategory.LOCAL,
        ]:
            if category not in providers_by_category:
                continue

            label, color = category_order[category]

            # Sort providers by name within category
            category_providers = sorted(providers_by_category[category], key=lambda x: x[1].name)

            # Count non-free providers in this category
            non_free_providers = [p for p in category_providers if p[0] not in free_provider_ids]

            # Show category header if there are any providers (even if all are free, show the header)
            if category_providers:
                t.append(f"  {label}\n", style=f"bold {color}")

            for pid, pdef, configured, missing_keys, model_count in category_providers:
                # Skip if already shown in Free Models section
                if pid in free_provider_ids:
                    continue

                status = "✓" if configured else "○"
                status_style = THEME["success"] if configured else THEME["warning"]

                # Highlight current selection
                is_highlighted = (idx - 1) == getattr(self, "_byok_highlighted_provider_index", 0)
                if is_highlighted:
                    t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                    t.append(f"[{idx:2}] ", style=f"bold {THEME['success']}")
                    t.append(f"{status} ", style=status_style)
                    t.append(f"{pid:<15}", style=f"bold {THEME['success']}")
                    t.append(f"{pdef.name}", style=f"bold {THEME['success']}")
                    if model_count > 0:
                        t.append(
                            f" ({model_count} model{'s' if model_count > 1 else ''})",
                            style=f"bold {THEME['success']}",
                        )
                    if not configured and pdef.env_vars:
                        t.append(
                            f" • Needs: {', '.join(missing_keys)}", style=f"bold {THEME['success']}"
                        )
                    t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                else:
                    t.append(f"    [{idx:2}] ", style=THEME["dim"])
                    t.append(f"{status} ", style=status_style)
                    t.append(f"{pid:<15}", style=THEME["text"])
                    t.append(f"{pdef.name}", style=THEME["muted"])

                # Show free badge if provider offers free models
                if pid in free_provider_ids:
                    t.append(f" 🆓", style=THEME["success"])

                # Show model count
                if model_count > 0:
                    t.append(f" ({model_count} model", style=THEME["dim"])
                    if model_count > 1:
                        t.append("s", style=THEME["dim"])
                    t.append(")", style=THEME["dim"])

                # Show API key requirement if not configured
                if not configured and pdef.env_vars:
                    t.append(f" • Needs: {', '.join(missing_keys)}", style=THEME["yellow"])

                t.append("\n", style="")

                provider_list.append((pid, pdef))
                idx += 1

            t.append("\n", style="")

        # Add arrow key navigation instructions
        t.append(f"  💡 Quick Connect:\n", style=THEME["muted"])
        t.append(f"    ⌨️  ", style=THEME["dim"])
        t.append(f"↑↓", style=THEME["cyan"])
        t.append(" Arrow keys to navigate  ", style=THEME["dim"])
        t.append(f"Enter", style=THEME["cyan"])
        t.append(" to select highlighted provider\n", style=THEME["dim"])
        t.append(f"    Or enter number (1-{len(provider_list)})  ", style=THEME["dim"])
        t.append("to select provider\n", style=THEME["text"])
        t.append(f"    Or: ", style=THEME["dim"])
        t.append(f":connect byok <provider>/<model>", style=THEME["success"])
        t.append(" for direct connect\n", style=THEME["text"])
        t.append(f"    Use ", style=THEME["dim"])
        t.append(f":back", style=THEME["cyan"])
        t.append(" or ", style=THEME["dim"])
        t.append(f":home", style=THEME["cyan"])
        t.append(" to cancel\n", style=THEME["text"])
        t.append(f"\n  💡 API Key Setup:\n", style=THEME["muted"])
        t.append(f"    Export API key: ", style=THEME["dim"])
        t.append("export ANTHROPIC_API_KEY='your-key'\n", style=THEME["cyan"])
        t.append(f"    Or in ~/.zshrc: ", style=THEME["dim"])
        t.append("export ANTHROPIC_API_KEY='your-key'\n", style=THEME["cyan"])
        t.append(f"    See provider docs: ", style=THEME["dim"])
        t.append("https://docs.superqode.ai/providers\n\n", style=THEME["cyan"])

        # Ensure we have providers to show
        if not provider_list:
            log.add_error("No providers available. Please check your provider configuration.")
            return

        # Clear log and show content from top (like agent finish work)
        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(t)
            log.scroll_home(animate=False)
            # Re-enable auto-scroll after a short delay
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))
        else:
            # Update during navigation - clear and write but don't scroll to home
            log.auto_scroll = False
            log.clear()
            log.write(t)
            # Don't scroll to home on navigation updates to reduce flickering
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))

        # Store for selection handling
        self._byok_connect_list = provider_list
        # CRITICAL: Set provider selection mode and clear model selection mode
        # This must be set AFTER building the list to ensure we show providers, not models
        self._awaiting_byok_provider = True
        self._awaiting_byok_model = False
        # Clear any selected provider to prevent auto-showing models
        if hasattr(self, "_byok_selected_provider"):
            delattr(self, "_byok_selected_provider")
        # Preserve current highlight if already set, otherwise start with first
        # Only reset on initial display, preserve during navigation
        if clear_log:
            if not hasattr(self, "_byok_highlighted_provider_index"):
                self._byok_highlighted_provider_index = 0
        else:
            # During navigation, preserve the index (it's already set by navigation methods)
            if not hasattr(self, "_byok_highlighted_provider_index"):
                self._byok_highlighted_provider_index = 0

        # Set flag to prevent immediate provider selection from any pending input (only on initial display)
        if clear_log:
            self._just_showed_byok_picker = True
            # Clear the flag after a short delay to allow normal selection
            self.set_timer(0.2, lambda: setattr(self, "_just_showed_byok_picker", False))

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

    def _show_provider_models(
        self,
        provider_id: str,
        log: ConversationLog,
        use_picker: bool = False,
        clear_log: bool = True,
    ):
        """Show models for a specific provider with smart grouping and API key guidance.

        Args:
            provider_id: Provider ID
            log: Conversation log
            use_picker: If True, use interactive picker widget. If False, use numbered list.
            clear_log: If True, clear log and scroll to top. If False, update in place (for navigation).
        """
        # CRITICAL SAFEGUARD: If we just showed the BYOK picker, don't show models
        # This prevents "2" or other inputs from immediately selecting a provider
        if getattr(self, "_just_showed_byok_picker", False):
            if not getattr(self, "_awaiting_byok_model", False):
                log.add_error(
                    f"Unexpected model display for {provider_id}. Showing provider list instead."
                )
                self._show_connect_picker(log)
                return

        from superqode.providers.registry import PROVIDERS, ProviderCategory
        from superqode.providers.models import (
            get_models_for_provider,
            get_data_source,
            ModelCapability,
        )
        import os

        # Try interactive picker first if enabled
        if use_picker:
            try:
                self._show_provider_models_picker(provider_id, log)
                return
            except Exception as e:
                # Fall back to numbered list if picker fails
                pass

        provider_def = PROVIDERS.get(provider_id)
        if not provider_def:
            log.add_error(f"Unknown provider: {provider_id}")
            return

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"{provider_def.name} Models\n", style=f"bold {THEME['text']}")

        # Check configuration status
        configured = False
        missing_keys = []
        if provider_def.env_vars:
            for env_var in provider_def.env_vars:
                if os.environ.get(env_var):
                    configured = True
                    break
                else:
                    missing_keys.append(env_var)
        else:
            configured = True  # No API key needed

        if not configured:
            t.append(f"\n  ⚠️  ", style=THEME["warning"])
            t.append("API Key Required\n", style=f"bold {THEME['warning']}")
            t.append(f"    Set: ", style=THEME["muted"])
            t.append(
                f"export {'='.join(provider_def.env_vars[:1])}='your-api-key'\n",
                style=THEME["cyan"],
            )
            if len(provider_def.env_vars) > 1:
                t.append(f"    Or: ", style=THEME["muted"])
                t.append(
                    f"export {'='.join(provider_def.env_vars[1:2])}='your-api-key'\n",
                    style=THEME["cyan"],
                )
            if provider_def.docs_url:
                t.append(f"    Get key: ", style=THEME["muted"])
                t.append(f"{provider_def.docs_url}\n", style=THEME["cyan"])
            t.append("\n", style="")

        # Check if this is a local provider
        if provider_def.category == ProviderCategory.LOCAL:
            # CRITICAL: Only show models if we're actually in model selection mode
            # If we're supposed to show the provider picker, don't show models!
            if not getattr(self, "_awaiting_local_model", False) and not getattr(
                self, "_awaiting_byok_model", False
            ):
                # We should be showing provider picker, not models!
                # Redirect to local provider picker instead
                log.add_info(f"Showing local providers. Select a provider first.")
                self._show_local_provider_picker(log)
                return
            # Load local models asynchronously (only if we're in model selection mode)
            self.run_worker(self._show_local_provider_models(provider_id, log))
            return

        t.append(f"  📊 Source: {get_data_source()}\n\n", style=THEME["dim"])

        # Get models from database
        db_models = get_models_for_provider(provider_id)

        if db_models:
            # Helper function to detect latest models for any provider
            def is_latest_model(model_id: str, info) -> bool:
                """Detect if a model is the latest version for its provider."""
                model_lower = model_id.lower()
                name_lower = info.name.lower()

                # Generic patterns that indicate latest models
                latest_indicators = [
                    "latest",
                    "preview",
                    "newest",
                    "current",
                    # Version patterns (highest versions)
                    "5.2",
                    "5.1",
                    "4.7",
                    "4.5",
                    "3.2",
                    "3.1",
                    "3.0",
                    # Specific latest model patterns by provider
                    "gpt-5.2",
                    "gpt-5.1",
                    "gemini-3",
                    "gemini 3",
                    "gemini3",
                    "claude-opus-4-5",
                    "claude-sonnet-4-5",
                    "claude-haiku-4-5",
                    "glm-4.7",
                    "glm-4-plus",
                    "glm-4-air",
                    "glm-4",  # Zhipu GLM-4.7
                    "deepseek-v3.2",
                    "deepseek-v3",
                    "deepseek-r1",  # DeepSeek V3.2
                    "grok-3",
                    "grok-3-",  # xAI Grok-3
                    "mistral-large-2411",
                    "codestral-latest",  # Mistral
                    "qwen3",
                    "qwen2.5",  # Alibaba Qwen
                    "llama-3.3",
                    "llama3.3",  # Meta Llama
                    "moonshot-v1-128k",
                    "kimi-k2",  # Moonshot
                    "abab6.5",  # MiniMax
                ]

                # Check for latest indicators
                if any(
                    indicator in model_lower or indicator in name_lower
                    for indicator in latest_indicators
                ):
                    return True

                # Check release date - if released in 2025, likely latest
                if info.released and info.released.startswith("2025"):
                    # Prioritize models from late 2025 (newer)
                    if "-12" in info.released or "-11" in info.released:
                        return True
                    # Also include other 2025 models
                    return True

                return False

            # Group models by category
            recommended = []  # Code-optimized or reasoning models
            budget = []  # < $1 input price
            free = []  # Free models
            others = []  # Everything else

            for model_id, info in db_models.items():
                is_latest = is_latest_model(model_id, info)

                if info.input_price == 0 and info.output_price == 0:
                    free.append((model_id, info))
                elif is_latest or info.is_code_optimized or info.supports_reasoning:
                    # Latest models always go to recommended, even if not explicitly code-optimized
                    recommended.append((model_id, info))
                elif info.input_price < 1.0:
                    budget.append((model_id, info))
                else:
                    others.append((model_id, info))

            # Sort each group - prioritize latest models across all providers
            def get_latest_priority(model_id: str, info) -> int:
                """Get priority score for latest models - lower is higher priority."""
                model_lower = model_id.lower()
                name_lower = info.name.lower()

                # Highest priority: Very latest models (2025-12, 2025-11 releases)
                if info.released:
                    if "-12" in info.released:
                        return -10  # Highest priority
                    elif "-11" in info.released:
                        return -9
                    elif "-10" in info.released:
                        return -8
                    elif info.released.startswith("2025"):
                        return -7

                # High priority: Latest version indicators
                # Priority order: -10 (highest) to -6 (medium)
                latest_patterns = [
                    # Latest flagship models (2025-12 releases)
                    ("gpt-5.2", -10),
                    ("5.2", -10),
                    ("gemini-3", -10),
                    ("gemini 3", -10),
                    ("gemini3", -10),
                    # Latest major versions (2025 releases)
                    ("glm-4.7", -9),
                    ("glm-4-plus", -9),
                    ("glm-4-air", -9),  # Zhipu GLM-4.7
                    ("deepseek-v3.2", -9),
                    ("deepseek-v3", -9),
                    ("deepseek-r1", -9),  # DeepSeek V3.2
                    ("grok-3", -9),
                    ("grok-3-", -9),  # xAI Grok-3
                    ("claude-opus-4-5", -9),
                    ("claude-sonnet-4-5", -9),
                    ("claude-haiku-4-5", -9),  # Claude 4.5
                    # Recent major versions
                    ("gpt-5.1", -8),
                    ("5.1", -8),
                    ("mistral-large-2411", -8),
                    ("codestral-latest", -8),  # Mistral
                    ("qwen3", -8),
                    ("qwen2.5", -7),  # Alibaba Qwen
                    ("llama-3.3", -7),
                    ("llama3.3", -7),  # Meta Llama
                    ("kimi-k2", -8),  # Moonshot Kimi
                    ("abab6.5", -8),  # MiniMax
                ]

                for pattern, prio in latest_patterns:
                    if pattern in model_lower or pattern in name_lower:
                        return prio

                # Medium priority: Preview/latest indicators
                if "preview" in model_lower or "latest" in model_lower or "newest" in model_lower:
                    return -6

                return 0  # Default priority

            def sort_key_recommended(x):
                model_id, info = x
                priority = get_latest_priority(model_id, info)
                # Then by code-optimized, then by price
                return (priority, not info.is_code_optimized, info.input_price)

            def sort_key_others(x):
                model_id, info = x
                priority = get_latest_priority(model_id, info)
                return (priority, info.name)

            recommended.sort(key=sort_key_recommended)
            budget.sort(key=lambda x: x[1].input_price)
            free.sort(key=lambda x: x[1].name)
            others.sort(key=sort_key_others)

            idx = 1
            model_list = []

            # Show Recommended models first
            if recommended:
                t.append(f"  🎯 Recommended for Coding:\n", style=f"bold {THEME['success']}")

                # Show latest models first (all providers)
                def is_latest_display(m):
                    model_id, info = m
                    return get_latest_priority(model_id, info) < 0

                latest_models = [m for m in recommended if is_latest_display(m)]
                other_recommended = [m for m in recommended if m not in latest_models]
                # Combine: latest models first, then others
                sorted_recommended = latest_models + other_recommended

                for model_id, info in sorted_recommended[
                    :15
                ]:  # Increased limit to show more latest models
                    # Highlight current selection - make it VERY visible
                    is_highlighted = (idx - 1) == getattr(self, "_byok_highlighted_model_index", 0)
                    if is_highlighted:
                        # Simple highlight - just bold and arrow
                        t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                        t.append(f"[{idx:2}] ", style=f"bold {THEME['success']}")
                        t.append(f"{info.name:<25}", style=f"bold {THEME['success']}")
                        t.append(f"{info.price_display:>12}", style=f"bold {THEME['success']}")
                        t.append(
                            f" • {info.context_display:>6} ctx", style=f"bold {THEME['success']}"
                        )
                        caps = []
                        if info.supports_tools:
                            caps.append("🔧")
                        if info.supports_vision:
                            caps.append("👁️")
                        if info.supports_reasoning:
                            caps.append("🧠")
                        if info.is_code_optimized:
                            caps.append("💻")
                        if caps:
                            t.append(f" • {' '.join(caps)}", style=f"bold {THEME['success']}")
                        t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                        t.append(f"         {model_id}\n", style=THEME["muted"])
                    else:
                        t.append(f"    [{idx:2}] ", style=THEME["dim"])
                        # Highlight latest models
                        is_latest = get_latest_priority(model_id, info) < 0
                        name_style = (
                            f"bold {THEME['success']}" if is_latest else f"bold {THEME['text']}"
                        )
                        t.append(f"{info.name:<25}", style=name_style)
                        t.append(f"{info.price_display:>12}", style=THEME["gold"])
                        t.append(f" • {info.context_display:>6} ctx", style=THEME["cyan"])

                        # Capabilities
                        caps = []
                        if info.supports_tools:
                            caps.append("🔧")
                        if info.supports_vision:
                            caps.append("👁️")
                        if info.supports_reasoning:
                            caps.append("🧠")
                        if info.is_code_optimized:
                            caps.append("💻")
                        if caps:
                            t.append(f" • {' '.join(caps)}", style=THEME["dim"])

                        t.append(f"\n         {model_id}\n", style=THEME["muted"])

                    model_list.append(model_id)
                    idx += 1
                t.append("\n", style="")

            # Show Budget options
            if budget:
                t.append(f"  💰 Budget-Friendly (< $1/1M):\n", style=f"bold {THEME['cyan']}")
                for model_id, info in budget[:6]:
                    t.append(f"    [{idx:2}] ", style=THEME["dim"])
                    t.append(f"{info.name:<25}", style=f"bold {THEME['text']}")
                    t.append(f"{info.price_display:>12}", style=THEME["gold"])
                    t.append(f" • {info.context_display:>6} ctx", style=THEME["cyan"])

                    caps = []
                    if info.supports_tools:
                        caps.append("🔧")
                    if caps:
                        t.append(f" • {' '.join(caps)}", style=THEME["dim"])

                    t.append(f"\n         {model_id}\n", style=THEME["muted"])

                    model_list.append(model_id)
                    idx += 1
                t.append("\n", style="")

            # Show Free models
            if free:
                t.append(f"  🆓 Free Models:\n", style=f"bold {THEME['success']}")
                for model_id, info in free[:6]:
                    t.append(f"    [{idx:2}] ", style=THEME["dim"])
                    t.append(f"{info.name:<25}", style=f"bold {THEME['success']}")
                    t.append(f"{'FREE':>12}", style=THEME["success"])
                    t.append(f" • {info.context_display:>6} ctx", style=THEME["cyan"])

                    caps = []
                    if info.supports_tools:
                        caps.append("🔧")
                    if info.is_code_optimized:
                        caps.append("💻")
                    if caps:
                        t.append(f" • {' '.join(caps)}", style=THEME["dim"])

                    t.append(f"\n         {model_id}\n", style=THEME["muted"])

                    model_list.append(model_id)
                    idx += 1
                t.append("\n", style="")

            # Show others if there are many (latest models first)
            if others and idx < 30:  # Increased limit
                remaining = 30 - idx
                # Prioritize latest models in others too
                latest_others = [m for m in others if get_latest_priority(m[0], m[1]) < 0]
                regular_others = [m for m in others if m not in latest_others]
                sorted_others = latest_others + regular_others

                for model_id, info in sorted_others[:remaining]:
                    t.append(f"    [{idx:2}] ", style=THEME["dim"])
                    # Highlight latest models
                    is_latest = get_latest_priority(model_id, info) < 0
                    name_style = f"bold {THEME['success']}" if is_latest else THEME["text"]
                    t.append(f"{info.name:<25}", style=name_style)
                    t.append(f"{info.price_display:>12}", style=THEME["gold"])
                    t.append(f" • {info.context_display:>6} ctx", style=THEME["cyan"])
                    t.append(f"\n         {model_id}\n", style=THEME["muted"])

                    model_list.append(model_id)
                    idx += 1

            if len(db_models) > len(model_list):
                remaining = len(db_models) - len(model_list)
                t.append(f"    ... and {remaining} more model(s)\n", style=THEME["dim"])
        else:
            # Fall back to example models - prioritize latest ones
            t.append(f"  Available models:\n", style=THEME["muted"])
            model_list = []

            # Special case: Hugging Face BYOK should show recommended models
            if provider_id == "huggingface":
                try:
                    from superqode.providers.huggingface import RECOMMENDED_MODELS

                    all_models = []
                    for category_models in RECOMMENDED_MODELS.values():
                        all_models.extend(category_models)

                    seen = set()
                    unique_models = []
                    for m in all_models:
                        if m not in seen:
                            seen.add(m)
                            unique_models.append(m)

                    if unique_models:
                        t.append(f"  Recommended models:\n", style=THEME["muted"])
                        for idx, model in enumerate(unique_models[:30], 1):
                            is_highlighted = (idx - 1) == getattr(
                                self, "_byok_highlighted_model_index", 0
                            )
                            if is_highlighted:
                                t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                                t.append(f"[{idx:2}] ", style=f"bold {THEME['success']}")
                                t.append(f"{model}", style=f"bold {THEME['success']}")
                                t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                            else:
                                t.append(f"    [{idx:2}] ", style=THEME["dim"])
                                t.append(f"{model}\n", style=THEME["text"])
                            model_list.append(model)
                except Exception:
                    pass

            if not model_list:
                # Sort example models to show latest first
                def sort_example_models(model_id: str) -> int:
                    """Sort example models - latest first."""
                    model_lower = model_id.lower()
                    # Latest models get higher priority (lower number)
                    if any(
                        x in model_lower
                        for x in ["4.7", "5.2", "5.1", "3.2", "3.3", "k2", "6.5"]
                    ):
                        return 0
                    elif any(x in model_lower for x in ["4.5", "4-plus", "4-air", "2.5"]):
                        return 1
                    else:
                        return 2

                sorted_models = sorted(provider_def.example_models, key=sort_example_models)

                for idx, model in enumerate(sorted_models[:15], 1):  # Show more models
                    # Highlight current selection
                    is_highlighted = (idx - 1) == getattr(
                        self, "_byok_highlighted_model_index", 0
                    )
                    if is_highlighted:
                        t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                        t.append(f"[{idx:2}] ", style=f"bold {THEME['success']}")
                        # Highlight latest models
                        is_latest = any(
                            x in model.lower()
                            for x in ["4.7", "5.2", "5.1", "3.2", "3.3", "k2", "6.5"]
                        )
                        name_style = (
                            f"bold {THEME['success']}"
                            if is_latest
                            else f"bold {THEME['success']}"
                        )
                        t.append(f"{model}", style=name_style)
                        t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                    else:
                        t.append(f"    [{idx:2}] ", style=THEME["dim"])
                        # Highlight latest models
                        is_latest = any(
                            x in model.lower()
                            for x in ["4.7", "5.2", "5.1", "3.2", "3.3", "k2", "6.5"]
                        )
                        name_style = f"bold {THEME['success']}" if is_latest else THEME["text"]
                        t.append(f"{model}\n", style=name_style)
                    model_list.append(model)

        t.append(f"\n  💡 Quick Connect:\n", style=THEME["muted"])
        t.append(f"    Type number (1-{len(model_list)}) to select by number\n", style=THEME["dim"])
        t.append(f"    Or type model name to search and select\n", style=THEME["dim"])
        t.append(f"    Or: ", style=THEME["dim"])
        t.append(f":connect {provider_id}/<model>", style=THEME["success"])
        t.append(" for direct connect\n", style=THEME["text"])
        t.append(f"    Use ", style=THEME["dim"])
        t.append(f":back", style=THEME["cyan"])
        t.append(" to return to provider list, or ", style=THEME["dim"])
        t.append(f":home", style=THEME["cyan"])
        t.append(" to cancel\n", style=THEME["text"])
        t.append("\n", style="")

        # Clear log and show content from top (like agent finish work)
        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(t)
            log.scroll_home(animate=False)
            # Re-enable auto-scroll after a short delay
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))
        else:
            # Update during navigation - clear and write but don't scroll to home
            log.auto_scroll = False
            log.clear()
            log.write(t)
            # Don't scroll to home on navigation updates to reduce flickering
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))

        # Store for selection - use model_list which matches display order
        # This ensures navigation index matches the displayed models
        # CRITICAL: Always set the model list to match the display order
        # model_list is always defined (initialized in both if db_models and else blocks)
        self._byok_model_list = model_list if model_list else []

        if db_models:
            self._byok_model_info = db_models  # Store model info for picker
        else:
            self._byok_model_info = {}
        self._byok_selected_provider = provider_id
        # Only set _awaiting_byok_model if it's not being handled by the caller
        # This prevents the same input from being processed as model selection
        # immediately after provider selection
        if not hasattr(self, "_skip_set_awaiting_model") or not self._skip_set_awaiting_model:
            self._awaiting_byok_model = True
        else:
            # Clear the flag so it doesn't affect future calls
            self._skip_set_awaiting_model = False
        # Preserve current highlight if already set, otherwise start with first
        # Only reset on initial display, preserve during navigation
        if clear_log:
            if not hasattr(self, "_byok_highlighted_model_index"):
                self._byok_highlighted_model_index = 0
            else:
                # Reset to 0 on initial display
                self._byok_highlighted_model_index = 0
        else:
            # During navigation, preserve the index (it's already set by navigation methods)
            if not hasattr(self, "_byok_highlighted_model_index"):
                self._byok_highlighted_model_index = 0

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

    def _show_provider_models_picker(self, provider_id: str, log: ConversationLog):
        """Show interactive model picker widget with keyboard navigation."""
        from superqode.providers.registry import PROVIDERS
        from superqode.providers.models import get_models_for_provider, get_data_source
        from superqode.widgets.model_picker import ModelPickerWidget, ModelOption

        provider_def = PROVIDERS.get(provider_id)
        if not provider_def:
            log.add_error(f"Unknown provider: {provider_id}")
            return

        # Get models
        db_models = get_models_for_provider(provider_id)

        if not db_models:
            # Fall back to numbered list
            self._show_provider_models(provider_id, log, use_picker=False)
            return

        # Helper to check if model is latest (same logic as in _show_provider_models)
        def is_latest_model(model_id: str, info) -> bool:
            """Check if model is latest."""
            model_lower = model_id.lower()
            name_lower = info.name.lower()

            # Check release date
            if info.released and info.released.startswith("2025"):
                if "-12" in info.released or "-11" in info.released:
                    return True
                return True

            # Check latest patterns
            latest_patterns = [
                "gpt-5.2",
                "5.2",
                "gemini-3",
                "gemini 3",
                "gemini3",
                "glm-4.7",
                "glm-4-plus",
                "deepseek-v3.2",
                "grok-3",
                "claude-opus-4-5",
                "claude-sonnet-4-5",
                "claude-haiku-4-5",
                "preview",
                "latest",
            ]

            return any(
                pattern in model_lower or pattern in name_lower for pattern in latest_patterns
            )

        # Convert to ModelOption format
        model_options = []
        for model_id, info in db_models.items():
            # Get capabilities
            caps = []
            if info.supports_tools:
                caps.append("🔧")
            if info.supports_vision:
                caps.append("👁️")
            if info.supports_reasoning:
                caps.append("🧠")
            if info.is_code_optimized:
                caps.append("💻")

            # Check if latest
            is_latest = is_latest_model(model_id, info)

            model_options.append(
                ModelOption(
                    id=model_id,
                    name=info.name,
                    price=info.price_display,
                    context=info.context_display,
                    capabilities=caps,
                    is_latest=is_latest,
                )
            )

        # Sort by latest first (same logic as numbered list)
        def sort_models(m: ModelOption) -> tuple:
            priority = 0
            if m.is_latest:
                priority = -10
            return (priority, m.name)

        model_options.sort(key=sort_models)

        # Create and mount picker widget
        from superqode.widgets.model_picker import ModelPickerWidget

        picker = ModelPickerWidget(provider_def.name, model_options)

        # Set up message handlers using textual's message system
        def handle_model_selected(event: ModelPickerWidget.ModelSelected) -> None:
            """Handle model selection from picker."""
            self._awaiting_byok_model = False
            self._connect_byok_mode(provider_id, event.model_id, log)
            # Remove picker widget
            try:
                picker.remove()
            except Exception:
                pass

        def handle_picker_cancelled(event: ModelPickerWidget.Cancelled) -> None:
            """Handle picker cancellation."""
            self._awaiting_byok_model = False
            try:
                picker.remove()
            except Exception:
                pass

        # Use textual's message watching
        from textual.message import Message

        self.set_timer(0.1, lambda: self._setup_picker_handlers(picker, provider_id, log))

        # Mount picker to the app
        self.mount(picker)

        # Store for cleanup
        self._model_picker_widget = picker
        self._picker_provider_id = provider_id
        self._picker_log = log

    def _setup_picker_handlers(self, picker, provider_id: str, log: ConversationLog):
        """Set up picker message handlers."""
        from superqode.widgets.model_picker import ModelPickerWidget

        @on(picker, ModelPickerWidget.ModelSelected)
        def on_model_selected(event: ModelPickerWidget.ModelSelected) -> None:
            """Handle model selection from picker."""
            self._awaiting_byok_model = False
            self._connect_byok_mode(provider_id, event.model_id, log)
            try:
                picker.remove()
            except Exception:
                pass

        @on(picker, ModelPickerWidget.Cancelled)
        def on_picker_cancelled(event: ModelPickerWidget.Cancelled) -> None:
            """Handle picker cancellation."""
            self._awaiting_byok_model = False
            try:
                picker.remove()
            except Exception:
                pass

    async def _show_local_provider_models(self, provider_id: str, log: ConversationLog):
        """Show models for a local provider by discovering them."""
        from superqode.providers.registry import PROVIDERS
        from superqode.providers.local import (
            OllamaClient,
            LMStudioClient,
            VLLMClient,
            SGLangClient,
            MLXClient,
            TGIClient,
            estimate_tool_support,
        )

        provider_def = PROVIDERS.get(provider_id)
        if not provider_def:
            log.add_error(f"Unknown provider: {provider_id}")
            return

        # Ensure local model selection is active, and BYOK selection is inactive
        self._awaiting_local_provider = False
        self._awaiting_local_model = True
        self._awaiting_byok_provider = False
        self._awaiting_byok_model = False

        # Show experimental warning for vLLM and SGLang
        if provider_id in ("vllm", "sglang"):
            t = Text()
            t.append(f"\n  ⚠️  ", style=THEME["warning"])
            t.append(f"Experimental Provider Warning\n\n", style=f"bold {THEME['warning']}")
            t.append(f"  {provider_def.name} support is ", style=THEME["text"])
            t.append(f"EXPERIMENTAL", style=f"bold {THEME['warning']}")
            t.append(f". Features may be unstable and behavior may change.\n", style=THEME["text"])
            t.append(f"  Please report any issues you encounter.\n", style=THEME["dim"])
            log.write(t)

        log.add_info(f"Discovering models from {provider_def.name}...")

        # Special handling for HuggingFace (show locally cached models)
        if provider_id == "huggingface-local":
            from superqode.providers.huggingface import discover_cached_models

            cached = discover_cached_models()
            cached_models = [m["id"] for m in cached]

            # Display models
            t = Text()
            t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
            t.append(f"{provider_def.name} Models\n", style=f"bold {THEME['text']}")
            t.append(
                f"  {len(cached_models)} locally cached model(s)\n\n", style=THEME["dim"]
            )

            # Store model list for selection
            self._local_selected_provider = provider_id
            self._local_model_list = cached_models
            self._local_cached_models = cached_models
            self._awaiting_local_model = True
            self._awaiting_local_provider = False

            highlighted_idx = getattr(self, "_local_highlighted_model_index", 0)

            if cached_models:
                for idx, model_id in enumerate(cached_models, 1):
                    is_highlighted = (idx - 1) == highlighted_idx

                    if is_highlighted:
                        t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                        t.append(f"[{idx:2}] ", style=f"bold {THEME['success']}")
                    else:
                        t.append(f"    [{idx:2}] ", style=THEME["dim"])

                    name_style = (
                        f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}"
                    )
                    t.append(f"{model_id}", style=name_style)
                    if is_highlighted:
                        t.append(f"  ← SELECTED", style=f"bold {THEME['success']}")
                    t.append(f"\n", style="")
            else:
                t.append(f"  ○ No local HuggingFace models found\n\n", style=THEME["muted"])

            t.append(f"  💡 ", style=THEME["muted"])
            t.append(f"Select a model number or name\n", style=THEME["text"])
            t.append(f"  Use ", style=THEME["muted"])
            t.append(f":hf search <query>", style=THEME["cyan"])
            t.append(f" to find and download models\n", style=THEME["muted"])

            log.write(t)
            return

        # Map provider ID to client class
        client_map = {
            "ollama": OllamaClient,
            "lmstudio": LMStudioClient,
            "vllm": VLLMClient,
            "sglang": SGLangClient,
            "mlx": MLXClient,
            "tgi": TGIClient,
        }

        client_class = client_map.get(provider_id)
        if not client_class:
            log.add_error(f"Local provider '{provider_id}' not yet supported")
            return

        # Create client and check availability
        client = client_class()
        server_running = await client.is_available()

        # For MLX and LM Studio, try to discover models even if server check fails
        # Sometimes the server is running but the availability check fails
        if provider_id in ("mlx", "lmstudio") and not server_running:
            # Try anyway - the list_models() call will handle errors gracefully
            pass

        # Always show guidance for providers that need manual setup
        if provider_id == "mlx":
            t = Text()
            if server_running:
                t.append(f"\n  🟢 ", style=THEME["success"])
                t.append(f"MLX server is running\n", style=THEME["text"])
            else:
                t.append(f"\n  ⚠️  ", style=THEME["warning"])
                t.append(f"MLX server is not running\n", style=THEME["text"])

            t.append(f"\n  MLX requires starting a server for each model:\n", style=THEME["muted"])
            t.append(
                f"    mlx_lm.server --model mlx-community/Llama-3.2-1B-Instruct-4bit\n",
                style=THEME["cyan"],
            )
            t.append(
                f"    # Or get command: superqode providers mlx server --model <model>\n",
                style=THEME["dim"],
            )
            t.append(f"    # Setup guide: superqode providers mlx setup\n", style=THEME["dim"])
            log.write(t)
        elif provider_id == "lmstudio":
            t = Text()
            if server_running:
                t.append(f"\n  🟢 ", style=THEME["success"])
                t.append(f"LM Studio server is running\n", style=THEME["text"])
            else:
                t.append(f"\n  ⚠️  ", style=THEME["warning"])
                t.append(f"LM Studio server is not running\n", style=THEME["text"])

            t.append(f"\n  LM Studio Setup (GUI Application):\n", style=THEME["muted"])
            t.append(f"    1. Download: https://lmstudio.ai/\n", style=THEME["cyan"])
            t.append(f"    2. Open LM Studio application\n", style=THEME["cyan"])
            t.append(
                f"    3. Download a model (search for 'qwen3-30b' or 'llama3.2-3b')\n",
                style=THEME["cyan"],
            )
            t.append(f"    4. Load the model in LM Studio\n", style=THEME["cyan"])
            t.append(
                f"    5. Go to 'Local Server' tab → Click 'Start Server'\n", style=THEME["cyan"]
            )
            t.append(f"    6. Return here and select your model\n", style=THEME["dim"])
            t.append(
                "\n    💡 Server runs on http://localhost:1234/v1/chat/completions\n",
                style=THEME["muted"],
            )
            log.write(t)

        # Get models - try discovery even if server check failed
        try:
            models = await client.list_models()
        except Exception as e:
            # Log error but continue - show helpful message below
            models = []
            import traceback

            error_msg = str(e)
            if provider_id == "mlx":
                log.add_info(f"MLX model discovery failed: {error_msg}")
                log.add_info("Make sure MLX server is running with a model loaded")
            elif provider_id == "lmstudio":
                log.add_info(f"LM Studio model discovery failed: {error_msg}")
                log.add_info("Make sure LM Studio server is running with a model loaded")

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"{provider_def.name} Models\n", style=f"bold {THEME['text']}")
        t.append(f"  {len(models)} model(s) available\n", style=THEME["dim"])
        t.append(f"  💡 ", style=THEME["muted"])
        t.append("Type number to select • Scroll with mouse to see more\n\n", style=THEME["muted"])

        if models:
            idx = 1
            model_list = []
            highlighted_idx = getattr(self, "_local_highlighted_model_index", 0)

            for model in models:
                is_highlighted = (idx - 1) == highlighted_idx

                if is_highlighted:
                    t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                    t.append(f"[{idx:2}] ", style=f"bold {THEME['success']}")
                else:
                    t.append(f"    [{idx:2}] ", style=THEME["dim"])

                # Running status
                if model.running:
                    t.append("● ", style=THEME["success"])
                else:
                    t.append("○ ", style=THEME["dim"])

                name_style = (
                    f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}"
                )
                t.append(f"{model.name}", style=name_style)
                if is_highlighted:
                    t.append(f"  ← SELECTED", style=f"bold {THEME['success']}")
                t.append(f"\n", style="")
                t.append(f"       ", style="")
                id_style = f"bold {THEME['success']}" if is_highlighted else THEME["muted"]
                t.append(f"{model.id}\n", style=id_style)

                # Model details
                details = []
                if model.size_display != "unknown":
                    details.append(model.size_display)
                if model.quantization != "unknown":
                    details.append(model.quantization)
                if model.context_window > 0:
                    details.append(f"{model.context_window:,} ctx")

                if details:
                    t.append(f"       ", style="")
                    t.append(" • ".join(details), style=THEME["dim"])
                    t.append("\n", style="")

                # Tool support
                tool_level = estimate_tool_support(model)
                if tool_level == "excellent":
                    t.append(f"       ", style="")
                    t.append("🔧🔧 Excellent tool support", style=THEME["success"])
                    t.append("\n", style="")
                elif tool_level == "good":
                    t.append(f"       ", style="")
                    t.append("🔧 Good tool support", style=THEME["cyan"])
                    t.append("\n", style="")
                elif tool_level == "none":
                    t.append(f"       ", style="")
                    t.append("No tool support", style=THEME["dim"])
                    t.append("\n", style="")

                if model.supports_vision:
                    t.append(f"       ", style="")
                    t.append("👁️ Vision support", style=THEME["cyan"])
                    t.append("\n", style="")

                t.append("\n", style="")
                model_list.append(model.id)
                idx += 1
        else:
            t.append(f"  ○ No models found\n\n", style=THEME["muted"])
            if provider_id == "ollama":
                t.append(f"  💡 Pull a model with:\n", style=THEME["muted"])
                t.append(f"    ollama pull llama3.2\n", style=THEME["cyan"])
            elif provider_id == "mlx":
                t.append(
                    f"  💡 MLX requires starting a server for each model:\n", style=THEME["muted"]
                )
                t.append(
                    f"    mlx_lm.server --model mlx-community/Llama-3.2-1B-Instruct-4bit\n",
                    style=THEME["cyan"],
                )
                t.append(
                    f"    # Or see: superqode providers mlx server --model <model>\n",
                    style=THEME["dim"],
                )
                if not server_running:
                    t.append(
                        f"\n  ⚠️  MLX server is not running. Start it first!\n",
                        style=THEME["warning"],
                    )
            elif provider_id == "lmstudio":
                t.append(f"  💡 LM Studio requires:\n", style=THEME["muted"])
                t.append(f"    1. Start LM Studio application\n", style=THEME["cyan"])
                t.append(f"    2. Download and load a model\n", style=THEME["cyan"])
                t.append(f"    3. Start the local server (Local Server tab)\n", style=THEME["cyan"])
                if not server_running:
                    t.append(
                        f"\n  ⚠️  LM Studio server is not running. Start the server in LM Studio first!\n",
                        style=THEME["warning"],
                    )
            model_list = []

        if not model_list:
            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(f":connect {provider_id} <model>", style=THEME["success"])
            t.append(" to connect\n", style=THEME["muted"])

        log.clear()
        log.auto_scroll = False
        log.write(t)
        log.scroll_home(animate=False)
        self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))

        # Store for selection
        self._local_model_list = model_list
        self._local_cached_models = models  # Cache full model objects for redraw
        self._local_selected_provider = provider_id
        self._awaiting_local_model = True
        # Preserve current highlight if already set, otherwise start with first
        if not hasattr(self, "_local_highlighted_model_index"):
            self._local_highlighted_model_index = 0

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

    def _redraw_local_provider_models(self, log: ConversationLog):
        """Redraw the local provider models list with updated highlighting.

        This is a synchronous method used during navigation to update the
        display without re-fetching models from the provider.
        """
        from superqode.providers.registry import PROVIDERS
        from superqode.providers.local import estimate_tool_support

        provider_id = getattr(self, "_local_selected_provider", None)
        models = getattr(self, "_local_cached_models", [])
        model_list = getattr(self, "_local_model_list", [])

        if not provider_id:
            return

        # HuggingFace cached models are stored as plain IDs
        if provider_id == "huggingface-local":
            if not model_list:
                return
            provider_def = PROVIDERS.get(provider_id)
            if not provider_def:
                return

            t = Text()
            t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
            t.append(f"{provider_def.name} Models\n", style=f"bold {THEME['text']}")
            t.append(
                f"  {len(model_list)} locally cached model(s)\n\n", style=THEME["dim"]
            )

            highlighted_idx = getattr(self, "_local_highlighted_model_index", 0)
            for idx, model_id in enumerate(model_list, 1):
                is_highlighted = (idx - 1) == highlighted_idx
                if is_highlighted:
                    t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                    t.append(f"[{idx:2}] ", style=f"bold {THEME['success']}")
                else:
                    t.append(f"    [{idx:2}] ", style=THEME["dim"])

                name_style = (
                    f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}"
                )
                t.append(f"{model_id}", style=name_style)
                if is_highlighted:
                    t.append(f"  ← SELECTED", style=f"bold {THEME['success']}")
                t.append(f"\n", style="")

            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append("Select a model number or name\n", style=THEME["text"])
            t.append(f"  Use ", style=THEME["muted"])
            t.append(f":hf search <query>", style=THEME["cyan"])
            t.append(f" to find and download models\n", style=THEME["muted"])

            log.auto_scroll = False
            log.clear()
            log.write(t)
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))
            return

        if not models:
            return

        provider_def = PROVIDERS.get(provider_id)
        if not provider_def:
            return

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"{provider_def.name} Models\n", style=f"bold {THEME['text']}")
        t.append(f"  {len(models)} model(s) available\n", style=THEME["dim"])
        t.append(f"  💡 ", style=THEME["muted"])
        t.append("Type number to select • Scroll with mouse to see more\n\n", style=THEME["muted"])

        highlighted_idx = getattr(self, "_local_highlighted_model_index", 0)

        for idx, model in enumerate(models, 1):
            is_highlighted = (idx - 1) == highlighted_idx

            if is_highlighted:
                t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                t.append(f"[{idx:2}] ", style=f"bold {THEME['success']}")
            else:
                t.append(f"    [{idx:2}] ", style=THEME["dim"])

            # Running status
            if model.running:
                t.append("● ", style=THEME["success"])
            else:
                t.append("○ ", style=THEME["dim"])

            name_style = f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}"
            t.append(f"{model.name}", style=name_style)
            if is_highlighted:
                t.append(f"  ← SELECTED", style=f"bold {THEME['success']}")
            t.append(f"\n", style="")
            t.append(f"       ", style="")
            id_style = f"bold {THEME['success']}" if is_highlighted else THEME["muted"]
            t.append(f"{model.id}\n", style=id_style)

            # Model details
            details = []
            if model.size_display != "unknown":
                details.append(model.size_display)
            if model.quantization != "unknown":
                details.append(model.quantization)
            if model.context_window > 0:
                details.append(f"{model.context_window:,} ctx")

            if details:
                t.append(f"       ", style="")
                t.append(" • ".join(details), style=THEME["dim"])
                t.append("\n", style="")

            # Tool support
            tool_level = estimate_tool_support(model)
            if tool_level == "excellent":
                t.append(f"       ", style="")
                t.append("🔧🔧 Excellent tool support", style=THEME["success"])
                t.append("\n", style="")
            elif tool_level == "good":
                t.append(f"       ", style="")
                t.append("🔧 Good tool support", style=THEME["cyan"])
                t.append("\n", style="")
            elif tool_level == "none":
                t.append(f"       ", style="")
                t.append("No tool support", style=THEME["dim"])
                t.append("\n", style="")

            if model.supports_vision:
                t.append(f"       ", style="")
                t.append("👁️ Vision support", style=THEME["cyan"])
                t.append("\n", style="")

            t.append("\n", style="")

        if not model_list:
            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(f":connect {provider_id} <model>", style=THEME["success"])
            t.append(" to connect\n", style=THEME["muted"])

        log.clear()
        log.auto_scroll = False
        log.write(t)
        log.scroll_home(animate=False)
        self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))

    def _models_cmd(self, args: str, log: ConversationLog):
        """Handle :models command - Show/switch models."""
        args = args.strip()

        if args == "update":
            # :models update - Refresh from models.dev
            self._models_update_cmd(log)
            return

        if args.startswith("search "):
            # :models search <query>
            query = args[7:].strip()
            self._models_search_cmd(query, log)
            return

        if args == "info":
            # :models info - Show data source info
            self._models_info_cmd(log)
            return

        if args.startswith("set "):
            # :models set <model>
            model = args[4:].strip()
            self._set_byok_model(model, log)
            return

        if args:
            # :models <provider> - Show models for provider
            self._show_provider_models(args, log)
            return

        # :models - Show models for current provider
        session = get_session()
        if session.execution_mode not in ("byok", "local") or not hasattr(self, "_pure_mode"):
            log.add_info("Not connected to BYOK provider")
            log.add_system("Use :connect to select a provider first")
            return

        provider = getattr(self._pure_mode, "_provider", None)
        if provider:
            self._show_provider_models(provider, log)
        else:
            log.add_info("No provider selected")

    def _models_update_cmd(self, log: ConversationLog):
        """Handle :models update - Refresh model data from models.dev."""
        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Updating Model Database\n\n", style=f"bold {THEME['text']}")
        t.append("  ⏳ Fetching from models.dev...\n", style=THEME["muted"])
        log.write(t)

        # Run the update in background
        self.run_worker(self._do_models_update(log))

    async def _do_models_update(self, log: ConversationLog):
        """Actually perform the models.dev update."""
        try:
            from superqode.providers.models_dev import get_models_dev
            from superqode.providers.models import set_live_models

            client = get_models_dev()
            success = await client.refresh(force=True)

            if success:
                # Update global models database
                live_models = {}
                for provider_id in client.get_providers().keys():
                    provider_models = client.get_models_for_provider(provider_id)
                    if provider_models:
                        live_models[provider_id] = provider_models

                if live_models:
                    set_live_models(live_models)

                # Show success
                cache_info = client.get_cache_info()
                t = Text()
                t.append(f"\n  ✓ ", style=f"bold {THEME['success']}")
                t.append("Model database updated!\n\n", style=f"bold {THEME['text']}")
                t.append(f"  Providers: ", style=THEME["muted"])
                t.append(f"{cache_info['provider_count']}\n", style=THEME["text"])
                t.append(f"  Models:    ", style=THEME["muted"])
                t.append(f"{cache_info['model_count']}\n", style=THEME["text"])
                t.append(f"  Source:    ", style=THEME["muted"])
                t.append("models.dev\n", style=THEME["cyan"])
                log.write(t)
            else:
                t = Text()
                t.append(f"\n  ✗ ", style=f"bold {THEME['error']}")
                t.append("Failed to fetch from models.dev\n", style=THEME["text"])
                t.append("  Using cached/built-in data\n", style=THEME["muted"])
                log.write(t)

        except Exception as e:
            t = Text()
            t.append(f"\n  ✗ ", style=f"bold {THEME['error']}")
            t.append(f"Update failed: {e}\n", style=THEME["text"])
            log.write(t)

    def _models_search_cmd(self, query: str, log: ConversationLog):
        """Handle :models search <query> - Search across all models."""
        from superqode.providers.models import search_models, get_data_source

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"Search: ", style=f"bold {THEME['text']}")
        t.append(f'"{query}"\n', style=THEME["cyan"])
        t.append(f"  Data source: {get_data_source()}\n\n", style=THEME["dim"])

        results = search_models(query, limit=15)

        if not results:
            t.append("  No models found matching query\n", style=THEME["muted"])
            log.write(t)
            return

        for idx, model in enumerate(results, 1):
            t.append(f"  [{idx:2}] ", style=THEME["dim"])
            t.append(f"{model.provider}", style=f"bold {THEME['success']}")
            t.append(f" / ", style=THEME["dim"])
            t.append(f"{model.name}\n", style=f"bold {THEME['text']}")

            # Model ID
            t.append(f"       ", style="")
            t.append(f"{model.id}\n", style=THEME["muted"])

            # Pricing and context
            t.append(f"       ", style="")
            t.append(f"{model.price_display}", style=THEME["gold"])
            t.append(f" per 1M  •  ", style=THEME["dim"])
            t.append(f"{model.context_display}", style=THEME["cyan"])
            t.append(" ctx\n", style=THEME["dim"])

            t.append("\n", style="")

        t.append(f"  💡 ", style=THEME["muted"])
        t.append(":connect <provider>/<model>", style=THEME["success"])
        t.append(" to connect\n", style=THEME["muted"])

        log.write(t)

    def _models_info_cmd(self, log: ConversationLog):
        """Handle :models info - Show model database info."""
        from superqode.providers.models import (
            is_using_live_data,
            get_data_source,
            get_all_models,
            get_all_providers,
        )

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Model Database Info\n\n", style=f"bold {THEME['text']}")

        t.append(f"  Source:     ", style=THEME["muted"])
        source = get_data_source()
        if "live" in source:
            t.append(f"{source}\n", style=f"bold {THEME['success']}")
        else:
            t.append(f"{source}\n", style=THEME["text"])

        providers = get_all_providers()
        models = get_all_models()

        t.append(f"  Providers:  ", style=THEME["muted"])
        t.append(f"{len(providers)}\n", style=THEME["text"])

        t.append(f"  Models:     ", style=THEME["muted"])
        t.append(f"{len(models)}\n", style=THEME["text"])

        # Show cache info if live
        if is_using_live_data():
            try:
                from superqode.providers.models_dev import get_models_dev

                client = get_models_dev()
                cache_info = client.get_cache_info()

                t.append(f"\n  Cache:\n", style=THEME["muted"])
                t.append(f"    File:     ", style=THEME["dim"])
                t.append(f"{cache_info['cache_file']}\n", style=THEME["text"])

                if cache_info.get("fetched_at"):
                    t.append(f"    Fetched:  ", style=THEME["dim"])
                    t.append(f"{cache_info['fetched_at'][:19]}\n", style=THEME["text"])

                t.append(f"    Expired:  ", style=THEME["dim"])
                expired = cache_info.get("is_expired", False)
                t.append(
                    f"{'Yes' if expired else 'No'}\n",
                    style=THEME["error"] if expired else THEME["success"],
                )

            except Exception:
                pass

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":models update", style=THEME["success"])
        t.append(" to refresh from models.dev\n", style=THEME["muted"])

        log.write(t)

    def _set_byok_model(self, model: str, log: ConversationLog):
        """Switch model without reconnecting."""
        session = get_session()
        if session.execution_mode not in ("byok", "local") or not hasattr(self, "_pure_mode"):
            log.add_error("Not connected to BYOK provider")
            return

        provider = getattr(self._pure_mode, "_provider", None)
        if not provider:
            log.add_error("No provider selected")
            return

        # Reconnect with new model
        self._connect_byok_mode(provider, model, log)

    def _usage_cmd(self, args: str, log: ConversationLog):
        """Handle :usage command - Show token/cost usage."""
        from superqode.providers.usage import get_usage_tracker

        tracker = get_usage_tracker()
        args = args.strip()

        if args == "reset":
            tracker.reset()
            log.add_success("Usage stats reset")
            return

        summary = tracker.get_summary()

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Session Usage\n\n", style=f"bold {THEME['text']}")

        if not summary["connected"]:
            t.append("  Not connected to any provider\n", style=THEME["muted"])
            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(":connect", style=THEME["success"])
            t.append(" to select a provider\n", style=THEME["muted"])
            log.write(t)
            return

        # Provider/Model
        t.append(f"  Provider: ", style=THEME["muted"])
        t.append(f"{summary['provider']}", style=f"bold {THEME['success']}")
        t.append(f" / ", style=THEME["dim"])
        t.append(f"{summary['model']}\n\n", style=THEME["cyan"])

        # Token counts
        t.append(f"  Total Tokens:  ", style=THEME["muted"])
        total = summary["tokens"]
        if total >= 1000:
            t.append(f"{total / 1000:.1f}K", style=f"bold {THEME['text']}")
        else:
            t.append(f"{total}", style=f"bold {THEME['text']}")
        t.append("\n", style="")

        t.append(f"  ├─ Input:      ", style=THEME["dim"])
        input_tokens = summary.get("input_tokens", 0)
        if input_tokens >= 1000:
            t.append(f"{input_tokens / 1000:.1f}K\n", style=THEME["text"])
        else:
            t.append(f"{input_tokens}\n", style=THEME["text"])

        t.append(f"  └─ Output:     ", style=THEME["dim"])
        output_tokens = summary.get("output_tokens", 0)
        if output_tokens >= 1000:
            t.append(f"{output_tokens / 1000:.1f}K\n\n", style=THEME["text"])
        else:
            t.append(f"{output_tokens}\n\n", style=THEME["text"])

        # Cost
        cost = summary["cost"]
        t.append(f"  Estimated Cost: ", style=THEME["muted"])
        if cost > 0:
            t.append(f"${cost:.4f}\n", style=f"bold {THEME['gold']}")
        else:
            t.append("Free\n", style=f"bold {THEME['success']}")

        # Messages
        t.append(f"\n  Messages:      ", style=THEME["muted"])
        t.append(f"{summary['messages']}\n", style=THEME["text"])

        t.append(f"  Tool Calls:    ", style=THEME["muted"])
        t.append(f"{summary['tools']}\n", style=THEME["text"])

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":usage reset", style=THEME["success"])
        t.append(" to reset stats\n", style=THEME["muted"])

        log.write(t)

    def _load_byok_config(self) -> dict:
        """Load BYOK config from file."""
        import json
        from pathlib import Path

        config_path = Path.home() / ".superqode" / "config.json"
        try:
            if config_path.exists():
                data = json.loads(config_path.read_text())
                return data.get("byok", {})
        except Exception:
            pass
        return {}

    def _save_byok_config(self, provider: str, model: str):
        """Save BYOK config to file."""
        import json
        from pathlib import Path

        config_path = Path.home() / ".superqode" / "config.json"
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)

            # Load existing config
            data = {}
            if config_path.exists():
                data = json.loads(config_path.read_text())

            # Update BYOK section
            if "byok" not in data:
                data["byok"] = {}

            data["byok"]["last_provider"] = provider
            data["byok"]["last_model"] = model

            # Update history
            history = data["byok"].get("history", [])
            entry = f"{provider}/{model}"
            if entry in history:
                history.remove(entry)
            history.insert(0, entry)
            data["byok"]["history"] = history[:20]  # Keep last 20

            config_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _load_byok_history(self) -> list:
        """Load BYOK connection history."""
        config = self._load_byok_config()
        return config.get("history", [])

    def _health_cmd(self, args: str, log: ConversationLog):
        """Handle :health command - Check provider connectivity."""
        self.run_worker(self._check_provider_health(log))

    async def _check_provider_health(self, log: ConversationLog):
        """Check provider health asynchronously."""
        from superqode.providers.health import get_health_checker, ProviderStatus

        log.add_info("Checking provider health...")

        checker = get_health_checker()
        results = await checker.check_all(force=True)

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Provider Health Status\n\n", style=f"bold {THEME['text']}")

        # Group by status
        ready = []
        not_configured = []
        errors = []

        for pid, result in sorted(results.items()):
            if result.status == ProviderStatus.READY:
                ready.append((pid, result))
            elif result.status == ProviderStatus.NOT_CONFIGURED:
                not_configured.append((pid, result))
            else:
                errors.append((pid, result))

        # Ready providers
        if ready:
            t.append(f"  ✓ Ready ({len(ready)})\n", style=f"bold {THEME['success']}")
            for pid, result in ready:
                t.append(f"    {result.status_icon} ", style=THEME["success"])
                t.append(f"{pid}", style=THEME["text"])
                if result.model_available:
                    t.append(f"  {result.model_available}", style=THEME["muted"])
                t.append("\n", style="")
            t.append("\n", style="")

        # Not configured
        if not_configured:
            t.append(f"  ○ Not Configured ({len(not_configured)})\n", style=f"{THEME['dim']}")
            for pid, result in not_configured[:5]:  # Show first 5
                t.append(f"    {result.status_icon} ", style=THEME["dim"])
                t.append(f"{pid}", style=THEME["muted"])
                t.append(f"  {result.message}\n", style=THEME["dim"])
            if len(not_configured) > 5:
                t.append(f"    ... and {len(not_configured) - 5} more\n", style=THEME["dim"])
            t.append("\n", style="")

        # Errors
        if errors:
            t.append(f"  ✗ Errors ({len(errors)})\n", style=f"bold {THEME['error']}")
            for pid, result in errors:
                t.append(f"    {result.status_icon} ", style=THEME["error"])
                t.append(f"{pid}", style=THEME["text"])
                t.append(f"  {result.message}\n", style=THEME["dim"])
            t.append("\n", style="")

        t.append(f"  💡 ", style=THEME["muted"])
        t.append(":connect <provider>", style=THEME["success"])
        t.append(" to connect to a ready provider\n", style=THEME["muted"])

        self.call_from_thread(log.write, t)

    # ========================================================================
    # Local Provider Commands
    # ========================================================================

    def _local_cmd(self, args: str, log: ConversationLog):
        """Handle :local command - Manage local LLM providers."""
        args = args.strip()
        parts = args.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        if sub == "" or sub == "status":
            # :local - Show all local providers status
            self.run_worker(self._local_status(log))
        elif sub == "scan":
            # :local scan - Scan for running providers
            self.run_worker(self._local_scan(log))
        elif sub == "models":
            # :local models - List all local models
            self.run_worker(self._local_models(log))
        elif sub == "test":
            # :local test <model> - Test tool calling
            if subargs:
                self.run_worker(self._local_test(subargs, log))
            else:
                log.add_info("Usage: :local test <model>")
        elif sub == "info":
            # :local info <model> - Show model info
            if subargs:
                self.run_worker(self._local_info(subargs, log))
            else:
                log.add_info("Usage: :local info <model>")
        elif sub == "recommend":
            # :local recommend - Show recommended coding models
            self._local_recommend(log)
        else:
            log.add_info(f"Unknown subcommand: {sub}")
            log.add_system("Available: status, scan, models, test, info, recommend")

    async def _local_status(self, log: ConversationLog):
        """Show status of all local providers."""
        from superqode.providers.local import (
            get_discovery_service,
            LocalProviderType,
        )

        log.add_info("Scanning local providers...")

        discovery = get_discovery_service()
        discovered = await discovery.scan_all()

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Local Provider Status\n\n", style=f"bold {THEME['text']}")

        if discovered:
            for key, provider in discovered.items():
                # Provider type icon
                type_icons = {
                    LocalProviderType.OLLAMA: "🦙",
                    LocalProviderType.LMSTUDIO: "🎬",
                    LocalProviderType.VLLM: "⚡",
                    LocalProviderType.SGLANG: "🔥",
                    LocalProviderType.TGI: "🤗",
                    LocalProviderType.MLX: "🍎",
                    LocalProviderType.LLAMACPP: "🔧",
                    LocalProviderType.OPENAI_COMPAT: "🔌",
                }
                icon = type_icons.get(provider.provider_type, "●")

                t.append(f"  {icon} ", style=f"bold {THEME['success']}")
                t.append(f"{provider.provider_type.value}", style=f"bold {THEME['text']}")
                t.append(f"  {provider.host}", style=THEME["muted"])
                if provider.version:
                    t.append(f"  v{provider.version}", style=THEME["dim"])
                t.append("\n", style="")

                t.append(f"    Models: {provider.model_count}", style=THEME["muted"])
                if provider.running_count > 0:
                    t.append(f"  Running: ", style=THEME["muted"])
                    t.append(f"{provider.running_count}", style=f"bold {THEME['success']}")
                t.append(f"  Latency: {provider.latency_ms:.0f}ms\n", style=THEME["dim"])

                # Show running models
                if provider.running_models:
                    for model in provider.running_models[:3]:
                        t.append(f"      ● ", style=THEME["success"])
                        t.append(f"{model.id}\n", style=THEME["text"])
                t.append("\n", style="")
        else:
            t.append(f"  ○ No local providers detected\n\n", style=THEME["muted"])
            t.append(f"  💡 Start Ollama with: ", style=THEME["muted"])
            t.append("ollama serve\n", style=THEME["cyan"])

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":local models", style=THEME["success"])
        t.append(" to see all available models\n", style=THEME["muted"])

        # We are running in the app's event loop here, so write directly
        log.write(t)

    async def _local_scan(self, log: ConversationLog):
        """Scan for running local providers."""
        from superqode.providers.local import get_discovery_service

        log.add_info("Scanning all ports for local providers...")

        discovery = get_discovery_service()
        discovered = await discovery.scan_all()

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Local Provider Scan Results\n\n", style=f"bold {THEME['text']}")

        if discovered:
            t.append(
                f"  ✓ Found {len(discovered)} provider(s)\n\n", style=f"bold {THEME['success']}"
            )
            for key, provider in discovered.items():
                t.append(f"  ● ", style=THEME["success"])
                t.append(f"{provider.provider_type.value}", style=f"bold {THEME['text']}")
                t.append(f" at port {provider.port}\n", style=THEME["muted"])
        else:
            t.append(f"  ○ No local providers found\n\n", style=THEME["muted"])
            t.append("  Ports scanned: 11434, 1234, 8000, 8080, 30000, 5000\n", style=THEME["dim"])

        log.write(t)

    async def _local_models(self, log: ConversationLog):
        """List all models from discovered local providers."""
        from superqode.providers.local import (
            get_discovery_service,
            estimate_tool_support,
        )

        discovery = get_discovery_service()
        discovered = await discovery.scan_all()

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Local Models\n\n", style=f"bold {THEME['text']}")

        total = 0
        for key, provider in discovered.items():
            if provider.models:
                t.append(
                    f"  {provider.provider_type.value.upper()}\n", style=f"bold {THEME['cyan']}"
                )
                for model in provider.models[:10]:  # Limit to 10 per provider
                    status = "●" if model.running else "○"
                    status_style = THEME["success"] if model.running else THEME["dim"]
                    t.append(f"    {status} ", style=status_style)
                    t.append(f"{model.id}", style=THEME["text"])

                    # Show tool support estimate
                    tool_level = estimate_tool_support(model)
                    if tool_level == "excellent":
                        t.append(f"  [tools ✓✓]", style=THEME["success"])
                    elif tool_level == "good":
                        t.append(f"  [tools ✓]", style=THEME["cyan"])
                    elif tool_level == "none":
                        t.append(f"  [no tools]", style=THEME["dim"])

                    if model.size_display != "unknown":
                        t.append(f"  {model.size_display}", style=THEME["muted"])
                    t.append("\n", style="")
                    total += 1

                if len(provider.models) > 10:
                    t.append(f"    ... and {len(provider.models) - 10} more\n", style=THEME["dim"])
                t.append("\n", style="")

        if total == 0:
            t.append(f"  ○ No models found\n", style=THEME["muted"])
            t.append(f"  💡 Pull a model with: ", style=THEME["muted"])
            t.append("ollama pull llama3.2\n", style=THEME["cyan"])

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":local test <model>", style=THEME["success"])
        t.append(" to test tool calling\n", style=THEME["muted"])

        log.write(t)

    async def _local_test(self, model_id: str, log: ConversationLog):
        """Test tool calling capability for a model."""
        from superqode.providers.local import (
            test_tool_calling,
            get_tool_capability_info,
        )

        # First show heuristic info
        info = get_tool_capability_info(model_id)

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"Testing Tool Calling: {model_id}\n\n", style=f"bold {THEME['text']}")

        t.append(f"  Heuristic Assessment:\n", style=THEME["muted"])
        t.append(f"    Likely supports tools: ", style=THEME["text"])
        if info.supports_tools:
            t.append("Yes\n", style=f"bold {THEME['success']}")
        else:
            t.append("No\n", style=THEME["dim"])
        if info.notes:
            t.append(f"    Note: {info.notes}\n", style=THEME["dim"])
        t.append("\n", style="")

        log.write(t)
        log.add_info("Running actual test...")

        # Run actual test
        result = await test_tool_calling(model_id)

        t2 = Text()
        t2.append(f"\n  Test Results:\n", style=f"bold {THEME['text']}")

        if result.supports_tools:
            t2.append(f"    ✓ ", style=f"bold {THEME['success']}")
            t2.append("Tool calling works!\n", style=THEME["success"])
            if result.parallel_tools:
                t2.append(f"    ✓ Parallel tools: Yes\n", style=THEME["success"])
            if result.tool_choice:
                t2.append(
                    f"    ✓ Tool choice modes: {', '.join(result.tool_choice)}\n",
                    style=THEME["cyan"],
                )
        else:
            t2.append(f"    ✗ ", style=f"bold {THEME['error']}")
            t2.append("Tool calling not supported\n", style=THEME["error"])
            if result.error:
                t2.append(f"    Error: {result.error}\n", style=THEME["dim"])

        if result.latency_ms > 0:
            t2.append(f"    Latency: {result.latency_ms:.0f}ms\n", style=THEME["dim"])
        if result.notes:
            t2.append(f"    Note: {result.notes}\n", style=THEME["muted"])

        log.write(t2)

    async def _local_info(self, model_id: str, log: ConversationLog):
        """Show detailed info about a local model."""
        from superqode.providers.local import (
            OllamaClient,
            get_tool_capability_info,
        )

        client = OllamaClient()
        model = await client.get_model_info(model_id)

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"Model: {model_id}\n\n", style=f"bold {THEME['text']}")

        if model:
            t.append(f"  Family:         ", style=THEME["muted"])
            t.append(f"{model.family}\n", style=THEME["text"])
            t.append(f"  Parameters:     ", style=THEME["muted"])
            t.append(f"{model.parameter_count or 'unknown'}\n", style=THEME["text"])
            t.append(f"  Quantization:   ", style=THEME["muted"])
            t.append(f"{model.quantization}\n", style=THEME["text"])
            t.append(f"  Context Window: ", style=THEME["muted"])
            t.append(f"{model.context_window:,} tokens\n", style=THEME["text"])
            t.append(f"  Size:           ", style=THEME["muted"])
            t.append(f"{model.size_display}\n", style=THEME["text"])
            t.append(f"  Running:        ", style=THEME["muted"])
            if model.running:
                t.append("Yes\n", style=f"bold {THEME['success']}")
            else:
                t.append("No\n", style=THEME["dim"])

            # Tool support
            info = get_tool_capability_info(model_id)
            t.append(f"\n  Tool Support:\n", style=f"bold {THEME['cyan']}")
            t.append(f"    Supports Tools: ", style=THEME["muted"])
            if info.supports_tools:
                t.append("Yes\n", style=THEME["success"])
                t.append(f"    Parallel Tools: ", style=THEME["muted"])
                t.append(f"{'Yes' if info.parallel_tools else 'No'}\n", style=THEME["text"])
            else:
                t.append("Unknown (run :local test to verify)\n", style=THEME["dim"])

            if model.supports_vision:
                t.append(f"\n  ✓ Supports Vision/Images\n", style=THEME["success"])
        else:
            t.append(f"  ○ Model not found\n", style=THEME["error"])

        log.write(t)

    def _local_recommend(self, log: ConversationLog):
        """Show recommended local models for coding."""
        from superqode.providers.local import get_recommended_coding_models

        recommendations = get_recommended_coding_models()

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Recommended Models for Coding\n\n", style=f"bold {THEME['text']}")

        for rec in recommendations:
            t.append(f"  ● ", style=THEME["cyan"])
            t.append(f"{rec['model']}", style=f"bold {THEME['text']}")
            t.append(f"  ({rec['params']})\n", style=THEME["muted"])

            t.append(f"    Tool Support: ", style=THEME["dim"])
            tool_style = THEME["success"] if rec["tool_support"] == "excellent" else THEME["cyan"]
            t.append(f"{rec['tool_support']}", style=tool_style)

            t.append(f"  │  Code Quality: ", style=THEME["dim"])
            code_style = THEME["success"] if rec["coding_quality"] == "excellent" else THEME["cyan"]
            t.append(f"{rec['coding_quality']}\n", style=code_style)

            t.append(f"    {rec['notes']}\n\n", style=THEME["dim"])

        t.append(f"  💡 Install with: ", style=THEME["muted"])
        t.append("ollama pull <model>\n", style=THEME["cyan"])

        self._show_command_output(log, t)

    # ========================================================================
    # HuggingFace Commands
    # ========================================================================

    def _hf_cmd(self, args: str, log: ConversationLog):
        """Handle :hf command - HuggingFace Hub integration."""
        args = args.strip()
        parts = args.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        if sub == "" or sub == "status":
            # :hf - Show HF status
            self._hf_status(log)
        elif sub == "search":
            # :hf search <query>
            if subargs:
                self.run_worker(self._hf_search(subargs, log))
            else:
                log.add_info("Usage: :hf search <query>")
        elif sub == "trending":
            # :hf trending - Show trending models
            self.run_worker(self._hf_trending(log))
        elif sub == "coding":
            # :hf coding - Show coding models
            self.run_worker(self._hf_coding(log))
        elif sub == "info":
            # :hf info <model_id>
            if subargs:
                self.run_worker(self._hf_info(subargs, log))
            else:
                log.add_info("Usage: :hf info <model_id>")
        elif sub == "gguf":
            # :hf gguf <model_id> - List GGUF files
            if subargs:
                self.run_worker(self._hf_gguf(subargs, log))
            else:
                log.add_info("Usage: :hf gguf <model_id>")
        elif sub == "download":
            # :hf download <model_id> [quant]
            if subargs:
                self.run_worker(self._hf_download(subargs, log))
            else:
                log.add_info("Usage: :hf download <model_id> [quantization]")
        elif sub == "endpoints":
            # :hf endpoints - List inference endpoints
            self.run_worker(self._hf_endpoints(log))
        elif sub == "recommend":
            # :hf recommend - Recommended models
            self._hf_recommend(log)
        elif sub == "transformers":
            # :hf transformers - Show transformers runner status
            self._hf_transformers_status(log)
        else:
            log.add_info(f"Unknown subcommand: {sub}")
            log.add_system(
                "Available: search, trending, coding, info, gguf, download, endpoints, recommend, transformers"
            )

    def _hf_status(self, log: ConversationLog):
        """Show HuggingFace status."""
        import os
        from superqode.providers.huggingface import get_hf_hub, get_transformers_runner

        hub = get_hf_hub()
        runner = get_transformers_runner()

        t = Text()
        t.append(f"\n  🤗 ", style=f"bold {THEME['purple']}")
        t.append("HuggingFace Status\n\n", style=f"bold {THEME['text']}")

        # Authentication
        t.append(f"  Authentication: ", style=THEME["muted"])
        if hub.is_authenticated:
            t.append("Configured (HF_TOKEN set)\n", style=f"bold {THEME['success']}")
        else:
            t.append("Not configured\n", style=THEME["warning"])
            t.append(f"    Set HF_TOKEN for private/gated models\n", style=THEME["dim"])

        # Cache directory
        t.append(f"  Cache Dir:      ", style=THEME["muted"])
        t.append(f"{hub.cache_dir}\n", style=THEME["text"])

        # Transformers availability
        t.append(f"\n  Transformers Runner:\n", style=f"bold {THEME['cyan']}")
        deps = runner.check_dependencies()
        for dep, available in deps.items():
            icon = "✓" if available else "○"
            style = THEME["success"] if available else THEME["dim"]
            t.append(f"    {icon} {dep}\n", style=style)

        if runner.is_loaded:
            t.append(f"\n  Loaded Model: ", style=THEME["muted"])
            t.append(f"{runner.loaded_model_id}\n", style=f"bold {THEME['success']}")

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":hf search <query>", style=THEME["success"])
        t.append(" to find models\n", style=THEME["muted"])

        log.write(t)

    async def _hf_search(self, query: str, log: ConversationLog):
        """Search HuggingFace Hub for models."""
        from superqode.providers.huggingface import get_hf_hub

        log.add_info(f"Searching HF Hub for '{query}'...")

        hub = get_hf_hub()
        models = await hub.search_models(query=query, limit=15)

        t = Text()
        t.append(f"\n  🤗 ", style=f"bold {THEME['purple']}")
        t.append(f"Search Results: '{query}'\n\n", style=f"bold {THEME['text']}")

        if models:
            for model in models:
                t.append(f"  ● ", style=THEME["cyan"])
                t.append(f"{model.id}\n", style=f"bold {THEME['text']}")

                t.append(f"    ", style="")
                t.append(f"↓{model.downloads_display}", style=THEME["muted"])
                t.append(f"  ♥{model.likes}", style=THEME["pink"])
                if model.is_gguf:
                    t.append(f"  [GGUF]", style=THEME["success"])
                if model.gated:
                    t.append(f"  [gated]", style=THEME["warning"])
                if model.license:
                    t.append(f"  {model.license}", style=THEME["dim"])
                t.append("\n", style="")

            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(":hf info <model>", style=THEME["success"])
            t.append(" for details\n", style=THEME["muted"])
        else:
            t.append(f"  ○ No models found\n", style=THEME["muted"])

        log.write(t)

    async def _hf_trending(self, log: ConversationLog):
        """Show trending text generation models."""
        from superqode.providers.huggingface import get_hf_hub

        log.add_info("Fetching trending models...")

        hub = get_hf_hub()
        models = await hub.get_trending(limit=15)

        t = Text()
        t.append(f"\n  🔥 ", style=f"bold {THEME['orange']}")
        t.append("Trending Text Generation Models\n\n", style=f"bold {THEME['text']}")

        for i, model in enumerate(models, 1):
            t.append(f"  {i:2}. ", style=THEME["muted"])
            t.append(f"{model.id}\n", style=f"bold {THEME['text']}")
            t.append(f"      ↓{model.downloads_display}", style=THEME["dim"])
            if model.is_gguf:
                t.append(f"  [GGUF]", style=THEME["success"])
            t.append("\n", style="")

        log.write(t)

    async def _hf_coding(self, log: ConversationLog):
        """Show popular coding models."""
        from superqode.providers.huggingface import get_hf_hub

        log.add_info("Fetching coding models...")

        hub = get_hf_hub()
        models = await hub.get_popular_coding(limit=15)

        t = Text()
        t.append(f"\n  💻 ", style=f"bold {THEME['cyan']}")
        t.append("Popular Coding Models\n\n", style=f"bold {THEME['text']}")

        for model in models:
            t.append(f"  ● ", style=THEME["success"])
            t.append(f"{model.id}\n", style=f"bold {THEME['text']}")
            t.append(f"    ↓{model.downloads_display}", style=THEME["dim"])
            if model.is_gguf:
                t.append(f"  [GGUF]", style=THEME["success"])
            if model.gated:
                t.append(f"  [gated]", style=THEME["warning"])
            t.append("\n", style="")

        log.write(t)

    async def _hf_info(self, model_id: str, log: ConversationLog):
        """Show detailed info about a HF model."""
        from superqode.providers.huggingface import get_hf_hub

        log.add_info(f"Fetching info for {model_id}...")

        hub = get_hf_hub()
        model = await hub.get_model_info(model_id)

        t = Text()
        t.append(f"\n  🤗 ", style=f"bold {THEME['purple']}")
        t.append(f"Model: {model_id}\n\n", style=f"bold {THEME['text']}")

        if model:
            t.append(f"  Author:      ", style=THEME["muted"])
            t.append(f"{model.author}\n", style=THEME["text"])
            t.append(f"  Downloads:   ", style=THEME["muted"])
            t.append(f"{model.downloads:,}\n", style=THEME["text"])
            t.append(f"  Likes:       ", style=THEME["muted"])
            t.append(f"{model.likes}\n", style=THEME["text"])
            t.append(f"  License:     ", style=THEME["muted"])
            t.append(f"{model.license or 'unspecified'}\n", style=THEME["text"])
            t.append(f"  Library:     ", style=THEME["muted"])
            t.append(f"{model.library or 'unknown'}\n", style=THEME["text"])
            t.append(f"  Task:        ", style=THEME["muted"])
            t.append(f"{model.pipeline_tag or 'unknown'}\n", style=THEME["text"])

            if model.gated:
                t.append(f"\n  ⚠️  This is a gated model\n", style=THEME["warning"])
                t.append(f"     Request access at: huggingface.co/{model_id}\n", style=THEME["dim"])

            if model.is_gguf:
                t.append(f"\n  💡 ", style=THEME["muted"])
                t.append(":hf gguf", style=THEME["success"])
                t.append(f" {model_id}", style=THEME["text"])
                t.append(" to list GGUF files\n", style=THEME["muted"])
        else:
            t.append(f"  ○ Model not found\n", style=THEME["error"])

        log.write(t)

    async def _hf_gguf(self, model_id: str, log: ConversationLog):
        """List GGUF files for a model."""
        from superqode.providers.huggingface import get_hf_hub

        log.add_info(f"Fetching GGUF files for {model_id}...")

        hub = get_hf_hub()
        files = await hub.list_gguf_files(model_id)

        t = Text()
        t.append(f"\n  📦 ", style=f"bold {THEME['purple']}")
        t.append(f"GGUF Files: {model_id}\n\n", style=f"bold {THEME['text']}")

        if files:
            for f in files:
                t.append(f"  ● ", style=THEME["success"])
                t.append(f"{f.filename}\n", style=THEME["text"])
                t.append(f"    ", style="")
                t.append(f"{f.quantization}", style=f"bold {THEME['cyan']}")
                t.append(f"  {f.size_display}\n", style=THEME["muted"])

            t.append(f"\n  💡 ", style=THEME["muted"])
            t.append(":hf download", style=THEME["success"])
            t.append(f" {model_id} Q4_K_M", style=THEME["text"])
            t.append(" to download\n", style=THEME["muted"])
        else:
            t.append(f"  ○ No GGUF files found\n", style=THEME["muted"])
            t.append(f"  This model may not have GGUF versions\n", style=THEME["dim"])

        log.write(t)

    async def _hf_download(self, args: str, log: ConversationLog):
        """Download a model from HuggingFace Hub."""
        from superqode.providers.huggingface import get_hf_downloader

        parts = args.split()
        model_id = parts[0]
        quantization = parts[1] if len(parts) > 1 else "Q4_K_M"

        log.add_info(f"Downloading {model_id} ({quantization})...")

        downloader = get_hf_downloader()

        def progress_callback(progress):
            if not progress.completed:
                msg = f"Downloading: {progress.progress_percent:.1f}% ({progress.speed_mbps:.1f} MB/s)"
                # This callback runs in executor thread, so we need call_from_thread
                self.call_from_thread(log.add_system, msg)

        result = await downloader.download_for_ollama(
            model_id, quantization=quantization, progress_callback=progress_callback
        )

        t = Text()
        if result.success:
            t.append(f"\n  ✓ ", style=f"bold {THEME['success']}")
            t.append("Download complete!\n\n", style=THEME["success"])
            t.append(f"  Path: {result.path}\n", style=THEME["text"])
            if result.ollama_model_name:
                t.append(f"\n  To use in Ollama:\n", style=THEME["muted"])
                t.append(f"    ollama create {result.ollama_model_name} -f ", style=THEME["cyan"])
                t.append(
                    f"{result.path.parent}/{result.path.stem}.Modelfile\n", style=THEME["text"]
                )
        else:
            t.append(f"\n  ✗ ", style=f"bold {THEME['error']}")
            t.append(f"Download failed: {result.error}\n", style=THEME["error"])

        log.write(t)

    async def _hf_endpoints(self, log: ConversationLog):
        """List HuggingFace Inference Endpoints."""
        from superqode.providers.huggingface import get_hf_endpoints_client

        client = get_hf_endpoints_client()

        if not client.is_authenticated:
            t = Text()
            t.append(f"\n  ⚠️  ", style=THEME["warning"])
            t.append("HF_TOKEN not set\n", style=THEME["text"])
            t.append(f"  Set HF_TOKEN to list your Inference Endpoints\n", style=THEME["muted"])
            log.write(t)
            return

        log.add_info("Fetching Inference Endpoints...")

        endpoints = await client.list_endpoints()

        t = Text()
        t.append(f"\n  🚀 ", style=f"bold {THEME['purple']}")
        t.append("Your Inference Endpoints\n\n", style=f"bold {THEME['text']}")

        if endpoints:
            for ep in endpoints:
                status_icon = "●" if ep.is_running else "○"
                status_style = THEME["success"] if ep.is_running else THEME["dim"]

                t.append(f"  {status_icon} ", style=status_style)
                t.append(f"{ep.name}", style=f"bold {THEME['text']}")
                t.append(f"  ({ep.state.value})\n", style=THEME["muted"])
                t.append(f"    Model: {ep.model_id}\n", style=THEME["dim"])
                if ep.url:
                    t.append(f"    URL: {ep.url}\n", style=THEME["dim"])
        else:
            t.append(f"  ○ No Inference Endpoints found\n", style=THEME["muted"])
            t.append(
                f"  Create endpoints at: huggingface.co/inference-endpoints\n", style=THEME["dim"]
            )

        log.write(t)

    def _hf_recommend(self, log: ConversationLog):
        """Show recommended HF models."""
        from superqode.providers.huggingface import RECOMMENDED_MODELS

        t = Text()
        t.append(f"\n  🌟 ", style=f"bold {THEME['purple']}")
        t.append("Recommended HuggingFace Models\n\n", style=f"bold {THEME['text']}")

        categories = [
            ("general", "General Purpose", THEME["cyan"]),
            ("coding", "Coding", THEME["success"]),
            ("small", "Small/Fast", THEME["orange"]),
            ("chat", "Chat/Assistant", THEME["pink"]),
        ]

        for cat_id, cat_name, color in categories:
            models = RECOMMENDED_MODELS.get(cat_id, [])
            t.append(f"  {cat_name}:\n", style=f"bold {color}")
            for model in models[:4]:
                t.append(f"    ● {model}\n", style=THEME["text"])
            t.append("\n", style="")

        t.append(f"  💡 These work with HF Inference API (free tier)\n", style=THEME["muted"])

        self._show_command_output(log, t)

    def _hf_transformers_status(self, log: ConversationLog):
        """Show transformers runner status."""
        from superqode.providers.huggingface import get_transformers_runner

        runner = get_transformers_runner()
        deps = runner.check_dependencies()
        device = runner.get_device_info() if runner.is_available() else {}

        t = Text()
        t.append(f"\n  🔧 ", style=f"bold {THEME['purple']}")
        t.append("Transformers Runner Status\n\n", style=f"bold {THEME['text']}")

        # Dependencies
        t.append(f"  Dependencies:\n", style=f"bold {THEME['cyan']}")
        for dep, available in deps.items():
            icon = "✓" if available else "○"
            style = THEME["success"] if available else THEME["dim"]
            t.append(f"    {icon} {dep}\n", style=style)

        # Device info
        if device.get("available"):
            t.append(f"\n  Compute:\n", style=f"bold {THEME['cyan']}")
            if device.get("cuda_available"):
                t.append(
                    f"    ✓ CUDA: {device.get('cuda_device_name', 'Unknown')}\n",
                    style=THEME["success"],
                )
                t.append(
                    f"      VRAM: {device.get('cuda_memory_gb', 0):.1f}GB\n", style=THEME["dim"]
                )
            elif device.get("mps_available"):
                t.append(f"    ✓ Apple MPS (Metal) available\n", style=THEME["success"])
            else:
                t.append(f"    ○ CPU only\n", style=THEME["muted"])

        # Loaded model
        if runner.is_loaded:
            info = runner.get_loaded_info()
            t.append(f"\n  Loaded Model:\n", style=f"bold {THEME['success']}")
            t.append(f"    {info['model_id']}\n", style=THEME["text"])
            t.append(f"    Memory: {info['memory_usage_gb']:.1f}GB\n", style=THEME["dim"])
        else:
            t.append(f"\n  No model loaded\n", style=THEME["muted"])
            t.append(f"  Use :hf load <model_id> to load a model\n", style=THEME["dim"])

        if not runner.is_available():
            t.append(f"\n  ⚠️  Install dependencies:\n", style=THEME["warning"])
            t.append(f"    pip install transformers accelerate torch\n", style=THEME["cyan"])

        log.write(t)

    def _connect_acp_cmd(self, args: str, log: ConversationLog):
        """Handle :connect acp command - Connect to ACP agent."""
        if not args:
            # Show agent list if no agent specified
            self._show_agents(log)
            return

        # Clear any existing BYOK connection when switching to ACP
        if hasattr(self, "_pure_mode") and self._pure_mode:
            # Disconnect provider session if switching from BYOK to ACP
            self._pure_mode.disconnect()

        # Clear session state
        session = get_session()
        if hasattr(session, "execution_mode"):
            session.execution_mode = "acp"
        if hasattr(session, "connected_agent"):
            # Will be set by _connect_agent
            pass

        # Parse: acp <agent> [model]
        parts = args.split(maxsplit=1)
        agent_name = parts[0]
        model_hint = parts[1] if len(parts) > 1 else None
        self._connect_agent(agent_name, model_hint)

    def _acp_cmd(self, args: str, log: ConversationLog):
        """Handle :acp command with subcommands (list, install, model)."""
        parts = args.split(maxsplit=1) if args else []
        sub = parts[0].lower() if parts else "list"
        subargs = parts[1] if len(parts) > 1 else ""

        if sub in ("list", ""):
            self._show_agents(log)
        elif sub == "connect":
            # Deprecated: Use :connect acp instead
            log.add_warning(":acp connect is deprecated. Use :connect acp instead.")
            log.add_info("Routing to :connect acp...")
            self._connect_acp_cmd(subargs, log)
        elif sub == "install":
            if subargs:
                self._install_agent(subargs, log)
            else:
                log.add_info("Usage: :acp install <name>")
        elif sub == "model":
            if subargs:
                self._set_model(subargs, log)
            else:
                log.add_info("Usage: :acp model <model_id>")
        else:
            log.add_info(f"Unknown: {sub}. Try: list, connect, install, model")

    def _set_model(self, model_name: str, log: ConversationLog):
        """Set the model for the current agent."""
        model_name = model_name.strip()

        if not self.current_agent:
            log.add_error("Not connected to any agent. Use :acp connect <name> first")
            return

        # For opencode, validate against available models
        if self.current_agent == "opencode":
            # Check if it's a number (1-5) for quick selection
            if model_name.isdigit():
                idx = int(model_name) - 1
                if 0 <= idx < len(self._opencode_models):
                    model_name = self._opencode_models[idx]["id"]
                else:
                    log.add_error(f"Invalid selection. Choose 1-{len(self._opencode_models)}")
                    return

            # Check if it's a valid opencode model
            valid_ids = [m["id"] for m in self._opencode_models]

            # Allow short names too (e.g., "glm-4.7-free" -> "opencode/glm-4.7-free")
            if not model_name.startswith("opencode/"):
                full_id = f"opencode/{model_name}"
                if full_id in valid_ids:
                    model_name = full_id

            if model_name not in valid_ids:
                log.add_error(f"Unknown model: {model_name}")
                log.add_info("Available models (use number or full ID):")
                for i, m in enumerate(self.opencode_models, 1):
                    log.add_info(f"  [{i}] {m['id']} - {m['name']}")
                return

            # Find model info
            model_info = next((m for m in self._opencode_models if m["id"] == model_name), None)
            model_display = model_info["name"] if model_info else model_name
        else:
            model_display = model_name

        # Store the model
        self.current_model = model_name
        self._awaiting_model_selection = False  # Clear the flag

        # Update badge
        badge = self.query_one("#mode-badge", ModeBadge)
        badge.model = model_name

        t = Text()
        t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
        t.append("Model changed to ", style=THEME["text"])
        t.append(f"{model_display}", style=f"bold {THEME['cyan']}")
        t.append(f" ({model_name})\n", style=THEME["dim"])

        if self.current_agent == "opencode":
            t.append(f"  🆓 This is a FREE model!\n", style=THEME["success"])

        log.write(t)

    def _show_agents(self, log: ConversationLog, clear_log: bool = True):
        """Show all ACP agents with installation status."""
        # Schedule async execution
        self._show_agents_async(log, clear_log=clear_log)

    @work(exclusive=True)
    async def _show_agents_async(self, log: ConversationLog, clear_log: bool = True):
        """Show all ACP agents with installation status (async implementation)."""
        import traceback
        from superqode.agents.registry import get_all_acp_agents
        from superqode.agents.registry import get_agent_installation_info
        from superqode.commands.acp import check_agent_installed

        try:
            agents = await get_all_acp_agents()
        except Exception as e:
            log.add_error(f"Error loading agents: {e}")
            log.add_error(f"Details: {traceback.format_exc()}")
            return

        if not agents:
            log.add_info("No ACP agents found.")
            return

        t = Text()
        t.append(f"\n  🤖 ", style=f"bold {THEME['cyan']}")
        t.append("All ACP Coding Agents\n\n", style=f"bold {THEME['cyan']}")

        # Separate by installation status
        installed = []
        not_installed = []

        for agent_id, agent_data in agents.items():
            is_installed = check_agent_installed(agent_data)
            if is_installed:
                installed.append((agent_id, agent_data))
            else:
                not_installed.append((agent_id, agent_data))

        # ACP agent emojis (from https://zed.dev/acp)
        agent_emojis = {
            "opencode": "🤖",  # Robot
            "claude": "🧠",  # Brain (Claude Code)
            "claude.com": "🧠",  # Brain (Claude Code)
            "gemini": "💎",  # Gem (Gemini CLI)
            "geminicli": "💎",  # Gem (Gemini CLI)
            "codex": "📝",  # Memo/code
            "codex.openai.com": "📝",  # Memo/code
            "moltbot": "🦞",  # Lobster (OpenClaw)
            "molt.bot": "🦞",  # Lobster (OpenClaw)
            "goose": "🪿",  # Goose
            "goose.ai": "🪿",  # Goose
            "kimi": "🔮",  # Crystal ball (Kimi CLI)
            "kimi.com": "🔮",  # Crystal ball
            "augmentcode": "⚡",  # Lightning (Auggie)
            "auggie": "⚡",  # Lightning
            "codeassistant": "🔧",  # Wrench (Code Assistant)
            "cagent": "🎯",  # Target
            "fastagent": "🚀",  # Rocket (fast-agent)
            "fast-agent": "🚀",  # Rocket
            "llmlingagent": "🧬",  # DNA (LLMling-Agent)
            "llmling-agent": "🧬",  # DNA
            "stakpak": "📦",  # Package
            "vtcode": "🎨",  # Paint palette
            "openhands": "🤲",  # Open hands
        }

        priority_order = {
            "opencode": 0,
            "opencode.ai": 0,
            "moltbot": 1,
            "molt.bot": 1,
            "claude": 2,
            "claude.com": 2,
            "codex": 3,
            "codex.openai.com": 3,
        }

        # Sort function: priority agents first, then alphabetically by name
        def sort_key(item):
            agent_id, agent_data = item
            agent_short_name = agent_data.get("short_name", agent_id)
            priority = priority_order.get(agent_id) or priority_order.get(agent_short_name)
            if priority is not None:
                return (0, priority, agent_data["name"])
            return (1, 999, agent_data["name"])

        # Combine into a single numbered list (installed first, then not installed)
        # But ensure opencode is always first within each group
        installed_sorted = sorted(installed, key=sort_key)
        not_installed_sorted = sorted(not_installed, key=sort_key)
        all_agents = installed_sorted + not_installed_sorted

        # Store the list for selection
        self._acp_agent_list = all_agents
        self._awaiting_acp_agent_selection = True
        # Preserve current highlight if already set, otherwise start with first
        if not hasattr(self, "_acp_highlighted_agent_index"):
            self._acp_highlighted_agent_index = 0

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

        # Show installed agents with numbers and highlighting
        if installed_sorted:
            t.append(
                f"  ✓ Installed ({len(installed_sorted)}):\n", style=f"bold {THEME['success']}"
            )
            for num, (agent_id, agent_data) in enumerate(installed_sorted, 1):
                idx = num - 1
                is_highlighted = idx == getattr(self, "_acp_highlighted_agent_index", 0)

                # Get emoji for this agent
                agent_short_name = agent_data.get("short_name", agent_id)
                emoji = agent_emojis.get(agent_id) or agent_emojis.get(agent_short_name, "🤖")

                if is_highlighted:
                    t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                    t.append(f"[{num:2}] ", style=f"bold {THEME['success']}")
                    t.append(f"{emoji} ", style=THEME["success"])
                    t.append(f"{agent_data['short_name']:<15}", style=f"bold {THEME['success']}")
                    t.append(
                        f"{agent_data['name']}  ← SELECTED\n", style=f"bold {THEME['success']}"
                    )
                else:
                    t.append(f"    [{num:2}] ", style=f"bold {THEME['text']}")
                    t.append(f"{emoji} ", style=THEME["success"])
                    t.append(f"{agent_data['short_name']:<15}", style=f"bold {THEME['text']}")
                    t.append(f"{agent_data['name']}\n", style=THEME["muted"])
            t.append("\n", style="")

        # Show not installed agents with numbers and installation commands
        if not_installed_sorted:
            start_num = len(installed_sorted) + 1
            t.append(
                f"  ○ Not Installed ({len(not_installed_sorted)}):\n",
                style=f"bold {THEME['warning']}",
            )
            for num, (agent_id, agent_data) in enumerate(not_installed_sorted, start_num):
                idx = num - 1
                is_highlighted = idx == getattr(self, "_acp_highlighted_agent_index", 0)
                install_info = get_agent_installation_info(agent_data)
                install_cmd = install_info.get("command", "")

                # Get emoji for this agent
                agent_short_name = agent_data.get("short_name", agent_id)
                emoji = agent_emojis.get(agent_id) or agent_emojis.get(agent_short_name, "🤖")

                if is_highlighted:
                    t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                    t.append(f"[{num:2}] ", style=f"bold {THEME['success']}")
                    t.append(f"{emoji} ", style=THEME["warning"])
                    t.append(f"{agent_data['short_name']:<15}", style=f"bold {THEME['success']}")
                    t.append(
                        f"{agent_data['name']:<25}  ← SELECTED\n", style=f"bold {THEME['success']}"
                    )
                    if install_cmd:
                        if len(install_cmd) > 35:
                            install_cmd = install_cmd[:32] + "..."
                        t.append(f"         → {install_cmd}\n", style=THEME["cyan"])
                else:
                    t.append(f"    [{num:2}] ", style=f"bold {THEME['text']}")
                    t.append(f"{emoji} ", style=THEME["warning"])
                    t.append(f"{agent_data['short_name']:<15}", style=f"bold {THEME['text']}")
                    t.append(f"{agent_data['name']:<25}", style=THEME["muted"])

                    if install_cmd:
                        # Truncate long commands
                        if len(install_cmd) > 35:
                            install_cmd = install_cmd[:32] + "..."
                        t.append(f" → ", style=THEME["dim"])
                        t.append(f"{install_cmd}\n", style=THEME["cyan"])
                    else:
                        t.append(f" → Installation info not available\n", style=THEME["dim"])
            t.append("\n", style="")

        t.append(f"  💡 Quick Actions:\n", style=THEME["muted"])
        t.append(f"    ⌨️  ", style=THEME["dim"])
        t.append(f"↑↓", style=THEME["cyan"])
        t.append(" Arrow keys to navigate  ", style=THEME["dim"])
        t.append(f"Enter", style=THEME["cyan"])
        t.append(" to select highlighted agent\n", style=THEME["dim"])
        t.append(
            f"    Or type number (1-{len(all_agents)}) to connect to an installed agent\n",
            style=THEME["dim"],
        )
        t.append(f"    Use ", style=THEME["dim"])
        t.append(f":connect acp <name>", style=THEME["pink"])
        t.append(f" to connect by name\n", style=THEME["dim"])
        t.append(f"    Use ", style=THEME["dim"])
        t.append(f":acp install <name>", style=THEME["cyan"])
        t.append(f" to install missing agents\n", style=THEME["dim"])
        t.append(f"    Use ", style=THEME["dim"])
        t.append(f":home", style=THEME["cyan"])
        t.append(f" or ", style=THEME["dim"])
        t.append(f":back", style=THEME["cyan"])
        t.append(f" to cancel selection\n", style=THEME["dim"])

        self._show_command_output(log, t, clear_log=clear_log)

    @work(exclusive=True)
    async def _connect_agent(self, agent_id: str, model_hint: str = None):
        log = self.query_one("#log", ConversationLog)

        try:
            from superqode.agents.discovery import get_agent_by_short_name_async

            agent = await get_agent_by_short_name_async(agent_id)

            if agent:
                session = get_session()
                session.connect_to_agent(agent)

                self.current_agent = agent.get("short_name", agent_id)
                self.current_mode = "agent"
                self.current_role = ""

                # Reset session for new agent connection
                self._is_first_message = True
                self._opencode_session_id = ""

                # Clear screen for fresh workspace
                self._clear_for_workspace(log, self.current_agent.upper())

                # For OpenCode, handle model selection
                if self.current_agent == "opencode":
                    # If model hint provided, try to auto-select it
                    if model_hint:
                        self._auto_select_opencode_model(model_hint, agent, log)
                    else:
                        self._show_opencode_models_selection(agent, log)
                elif self.current_agent == "gemini":
                    # For Gemini, handle model selection
                    if model_hint:
                        self._auto_select_gemini_model(model_hint, agent, log)
                    else:
                        self._show_gemini_models_selection(agent, log)
                elif self.current_agent == "claude":
                    # For Claude Code, handle model selection
                    if model_hint:
                        self._auto_select_claude_model(model_hint, agent, log)
                    else:
                        self._show_claude_models_selection(agent, log)
                elif self.current_agent == "codex":
                    # For Codex CLI, handle model selection
                    if model_hint:
                        self._auto_select_codex_model(model_hint, agent, log)
                    else:
                        self._show_codex_models_selection(agent, log)
                elif self.current_agent == "openhands":
                    # For OpenHands, handle model selection
                    if model_hint:
                        self._auto_select_openhands_model(model_hint, agent, log)
                    else:
                        self._show_openhands_models_selection(agent, log)
                else:
                    # For other agents, just connect
                    self.current_model = agent.get("model", "")
                    self.current_provider = agent.get("provider", "")

                    badge = self.query_one("#mode-badge", ModeBadge)
                    badge.agent = self.current_agent
                    badge.mode = ""
                    badge.role = ""
                    badge.model = self.current_model
                    badge.provider = self.current_provider
            else:
                log.add_error(f"Agent '{agent_id}' not found")
        except Exception as e:
            log.add_error(str(e))

    def _auto_select_opencode_model(
        self, model_hint: str, agent: Dict[str, Any], log: ConversationLog
    ):
        """Auto-select an OpenCode model based on user hint."""
        model_hint_lower = model_hint.lower().strip()

        # Try to find a matching model
        matched_model = None
        for model in self._opencode_models:
            model_id = model.get("id", "").lower()
            model_name = model.get("name", "").lower()

            # Check if hint matches model id or name
            if model_hint_lower in model_id or model_hint_lower in model_name:
                matched_model = model
                break

        if matched_model:
            model_id = matched_model.get("id", "")
            model_name = matched_model.get("name", "")

            self.current_model = model_id
            self.current_provider = "opencode"
            self._awaiting_model_selection = False

            # Update badge - ACP mode for agent connections
            badge = self.query_one("#mode-badge", ModeBadge)
            badge.agent = self.current_agent
            badge.model = model_id
            badge.provider = self.current_provider
            badge.execution_mode = "acp"  # ACP mode for :acp connect

            # Show confirmation
            t = Text()
            t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
            t.append("Connected with model: ", style=THEME["text"])
            t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
            t.append(f" ({model_id})\n", style=THEME["dim"])
            t.append(f"  🆓 This is a FREE model! Ready to chat.\n", style=THEME["success"])
            log.write(t)
        else:
            # No match found, show available models
            log.add_info(f"Model '{model_hint}' not found. Available models:")
            self._show_opencode_models_selection(agent, log)

    def _show_opencode_models_selection(
        self, agent: Dict[str, Any], log: ConversationLog, clear_log: bool = True
    ):
        """Show OpenCode available models for selection.

        Args:
            agent: Agent data dictionary
            log: Conversation log widget
            clear_log: If True, clear the log before writing (default: True).
                      Set to False when updating during navigation to reduce flickering.
        """
        name = agent.get("name", "OpenCode")
        color = AGENT_COLORS.get("opencode", THEME["success"])
        icon = AGENT_ICONS.get("opencode", "🌿")

        # Initialize highlighted index if not set
        if not hasattr(self, "_opencode_highlighted_model_index"):
            self._opencode_highlighted_model_index = 0

        highlighted_idx = getattr(self, "_opencode_highlighted_model_index", 0)

        t = Text()
        t.append(f"\n  ╭{'─' * 58}╮\n", style=color)
        t.append(f"  │  {icon} ", style=color)
        t.append("Connected to ", style=THEME["text"])
        t.append("OPENCODE", style=f"bold {color}")
        t.append(f"{'':>32}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show available FREE models
        t.append(f"  │  🆓 ", style=color)
        t.append("SELECT A FREE MODEL", style=f"bold {THEME['success']}")
        t.append(f"{'':>34}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        for i, model in enumerate(self.opencode_models):
            model_id = model.get("id", "")
            model_name = model.get("name", "")
            desc = model.get("desc", "")
            is_recommended = model.get("recommended", False)
            is_highlighted = i == highlighted_idx

            # Number for selection
            num = i + 1
            t.append(f"  │  ", style=color)

            if is_highlighted:
                t.append(f"▶ ", style=f"bold {THEME['success']}")
                t.append(f"[{num}]", style=f"bold {THEME['success']}")
                t.append(f" {model_name:<18}", style=f"bold {THEME['success']}")
                if is_recommended:
                    t.append("⭐ ", style=THEME["gold"])
                else:
                    t.append("   ", style="")
                t.append("  ← SELECTED", style=f"bold {THEME['success']}")
            else:
                t.append(f"  [{num}]", style=f"bold {THEME['cyan']}")
                t.append(f" {model_name:<18}", style=f"bold {THEME['text']}")
                if is_recommended:
                    t.append("⭐ ", style=THEME["gold"])
                else:
                    t.append("   ", style="")

            # Truncate desc to fit
            desc_short = desc[:25] + ".." if len(desc) > 25 else desc
            padding = 27 - len(desc_short) - (12 if is_highlighted else 0)
            t.append(
                f"{desc_short}{' ' * padding}│\n",
                style=THEME["dim"] if not is_highlighted else THEME["muted"],
            )

        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show how to select - ARROW KEYS OR TYPE NUMBER
        t.append(f"  │  ⌨️  ", style=color)
        t.append("↑↓", style=f"bold {THEME['cyan']}")
        t.append(" Arrow keys to navigate  ", style=THEME["muted"])
        t.append("Enter", style=f"bold {THEME['cyan']}")
        t.append(" to select", style=THEME["muted"])
        t.append(f"{'':>8}│\n", style=color)
        t.append(f"  │      Or type ", style=color)
        t.append("1", style=f"bold {THEME['cyan']}")
        t.append("-", style=THEME["muted"])
        t.append(f"{len(self.opencode_models)}", style=f"bold {THEME['cyan']}")
        t.append(" in prompt and press Enter", style=THEME["muted"])
        t.append(f"{'':>10}│\n", style=color)

        t.append(f"  ╰{'─' * 58}╯\n", style=color)

        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(t)
            log.scroll_home(animate=False)
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))
        else:
            # Update during navigation - clear and write but don't scroll to home
            log.auto_scroll = False
            log.clear()
            log.write(t)
            # Don't scroll to home on navigation updates to reduce flickering
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))

        # Set flag to await model selection
        self._awaiting_model_selection = True
        # Store agent data for navigation
        self._opencode_agent_data = agent

        # DO NOT auto-select model - user must choose
        self.current_model = ""  # No model selected yet
        self.current_provider = ""

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.agent = self.current_agent
        badge.mode = ""
        badge.role = ""
        badge.model = ""
        badge.provider = ""

    def _show_gemini_models_selection(self, agent: Dict[str, Any], log: ConversationLog):
        """Show Gemini available models for selection."""
        name = agent.get("name", "Gemini CLI")
        color = THEME["cyan"]
        icon = "✨"

        t = Text()
        t.append(f"\n  ╭{'─' * 58}╮\n", style=color)
        t.append(f"  │  {icon} ", style=color)
        t.append("Connected to ", style=THEME["text"])
        t.append("GEMINI CLI", style=f"bold {color}")
        t.append(f"{'':>32}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show available models
        t.append(f"  │  🤖 ", style=color)
        t.append("SELECT A MODEL", style=f"bold {THEME['cyan']}")
        t.append(f"{'':>38}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        for i, model in enumerate(self.gemini_models):
            model_id = model.get("id", "")
            model_name = model.get("name", "")
            desc = model.get("desc", "")
            is_recommended = model.get("recommended", False)

            # Number for selection
            num = i + 1
            t.append(f"  │  ", style=color)
            t.append(f"[{num}]", style=f"bold {THEME['cyan']}")
            t.append(f" {model_name:<18}", style=f"bold {THEME['text']}")

            if is_recommended:
                t.append("⭐ ", style=THEME["gold"])
            else:
                t.append("   ", style="")

            # Truncate desc to fit
            desc_short = desc[:25] + ".." if len(desc) > 25 else desc
            padding = 27 - len(desc_short)
            t.append(f"{desc_short}{' ' * padding}│\n", style=THEME["dim"])

        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show how to select
        t.append(f"  │  ⌨️  ", style=color)
        t.append("Type ", style=THEME["muted"])
        t.append("1", style=f"bold {THEME['cyan']}")
        t.append("-", style=THEME["muted"])
        t.append(f"{len(self._gemini_models)}", style=f"bold {THEME['cyan']}")
        t.append(" in prompt and press Enter", style=THEME["muted"])
        t.append(f"{'':>14}│\n", style=color)

        t.append(f"  ╰{'─' * 58}╯\n", style=color)

        log.write(t)

        # Set flag to await model selection
        self._awaiting_model_selection = True

        # No model selected yet
        self.current_model = ""
        self.current_provider = "gemini"

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.agent = self.current_agent
        badge.mode = ""
        badge.role = ""
        badge.model = ""
        badge.provider = "gemini"

    def _auto_select_gemini_model(
        self, model_hint: str, agent: Dict[str, Any], log: ConversationLog
    ):
        """Auto-select a Gemini model based on user hint."""
        model_hint_lower = model_hint.lower().strip()

        # Try to find a matching model
        matched_model = None
        for model in self._gemini_models:
            model_id = model.get("id", "").lower()
            model_name = model.get("name", "").lower()

            # Check various match patterns
            if model_hint_lower in model_id or model_hint_lower in model_name:
                matched_model = model
                break

            # Check for partial matches
            if "flash" in model_hint_lower and "flash" in model_name:
                matched_model = model
                break
            if "pro" in model_hint_lower and "pro" in model_name:
                matched_model = model
                break
            if "2.5" in model_hint_lower and "2.5" in model_name:
                matched_model = model
                break

        if matched_model:
            model_id = matched_model.get("id", "")
            model_name = matched_model.get("name", "")

            self.current_model = model_id
            self.current_provider = "gemini"
            self._awaiting_model_selection = False

            badge = self.query_one("#mode-badge", ModeBadge)
            badge.agent = self.current_agent
            badge.model = model_id
            badge.provider = "gemini"

            t = Text()
            t.append(f"\n  ✨ ", style=THEME["cyan"])
            t.append("Model selected: ", style=THEME["text"])
            t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
            t.append(f" ({model_id})\n", style=THEME["dim"])
            t.append(f"  💬 Ready! Type your message.\n", style=THEME["success"])
            log.write(t)
        else:
            # No match found, show available models
            log.add_info(f"Model '{model_hint}' not found. Available models:")
            self._show_gemini_models_selection(agent, log)

    def _show_claude_models_selection(self, agent: Dict[str, Any], log: ConversationLog):
        """Show Claude Code available models for selection."""
        name = agent.get("name", "Claude Code")
        color = THEME["orange"]
        icon = "🧡"

        t = Text()
        t.append(f"\n  ╭{'─' * 58}╮\n", style=color)
        t.append(f"  │  {icon} ", style=color)
        t.append("Connected to ", style=THEME["text"])
        t.append("CLAUDE CODE", style=f"bold {color}")
        t.append(f"{'':>31}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show available models
        t.append(f"  │  🤖 ", style=color)
        t.append("SELECT A MODEL", style=f"bold {THEME['cyan']}")
        t.append(f"{'':>38}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        for i, model in enumerate(self.claude_models):
            model_id = model.get("id", "")
            model_name = model.get("name", "")
            desc = model.get("desc", "")
            is_recommended = model.get("recommended", False)

            # Number for selection
            num = i + 1
            t.append(f"  │  ", style=color)
            t.append(f"[{num}]", style=f"bold {THEME['cyan']}")
            t.append(f" {model_name:<18}", style=f"bold {THEME['text']}")

            if is_recommended:
                t.append("⭐ ", style=THEME["gold"])
            else:
                t.append("   ", style="")

            # Truncate desc to fit
            desc_short = desc[:25] + ".." if len(desc) > 25 else desc
            padding = 27 - len(desc_short)
            t.append(f"{desc_short}{' ' * padding}│\n", style=THEME["dim"])

        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show how to select
        t.append(f"  │  ⌨️  ", style=color)
        t.append("Type ", style=THEME["muted"])
        t.append("1", style=f"bold {THEME['cyan']}")
        t.append("-", style=THEME["muted"])
        t.append(f"{len(self._claude_models)}", style=f"bold {THEME['cyan']}")
        t.append(" in prompt and press Enter", style=THEME["muted"])
        t.append(f"{'':>14}│\n", style=color)

        t.append(f"  ╰{'─' * 58}╯\n", style=color)

        # Show API key requirement
        t.append(f"\n  💡 ", style=THEME["gold"])
        t.append("Requires ", style=THEME["muted"])
        t.append("ANTHROPIC_API_KEY", style=f"bold {THEME['cyan']}")
        t.append(" environment variable\n", style=THEME["muted"])

        log.write(t)

        # Set flag to await model selection
        self._awaiting_model_selection = True

        # No model selected yet
        self.current_model = ""
        self.current_provider = "claude"

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.agent = self.current_agent
        badge.mode = ""
        badge.role = ""
        badge.model = ""
        badge.provider = "claude"

    def _auto_select_claude_model(
        self, model_hint: str, agent: Dict[str, Any], log: ConversationLog
    ):
        """Auto-select a Claude model based on user hint."""
        model_hint_lower = model_hint.lower().strip()

        # Try to find a matching model
        matched_model = None
        for model in self._claude_models:
            model_id = model.get("id", "").lower()
            model_name = model.get("name", "").lower()

            # Check various match patterns
            if model_hint_lower in model_id or model_hint_lower in model_name:
                matched_model = model
                break

            # Check for partial matches
            if "sonnet" in model_hint_lower and "sonnet" in model_name:
                matched_model = model
                break
            if "haiku" in model_hint_lower and "haiku" in model_name:
                matched_model = model
                break
            if "opus" in model_hint_lower and "opus" in model_name:
                matched_model = model
                break
            if "4" in model_hint_lower and "4" in model_name:
                matched_model = model
                break
            if "3.5" in model_hint_lower and "3.5" in model_name:
                matched_model = model
                break

        if matched_model:
            model_id = matched_model.get("id", "")
            model_name = matched_model.get("name", "")

            self.current_model = model_id
            self.current_provider = "claude"
            self._awaiting_model_selection = False

            badge = self.query_one("#mode-badge", ModeBadge)
            badge.agent = self.current_agent
            badge.model = model_id
            badge.provider = "claude"

            t = Text()
            t.append(f"\n  🧡 ", style=THEME["orange"])
            t.append("Model selected: ", style=THEME["text"])
            t.append(f"{model_name}", style=f"bold {THEME['orange']}")
            t.append(f" ({model_id})\n", style=THEME["dim"])
            t.append(f"  💬 Ready! Type your message.\n", style=THEME["success"])
            log.write(t)
        else:
            # No match found, show available models
            log.add_info(f"Model '{model_hint}' not found. Available models:")
            self._show_claude_models_selection(agent, log)

    def _show_codex_models_selection(self, agent: Dict[str, Any], log: ConversationLog):
        """Show Codex CLI available models for selection."""
        name = agent.get("name", "Codex CLI")
        color = THEME["green"]
        icon = "📜"

        t = Text()
        t.append(f"\n  ╭{'─' * 58}╮\n", style=color)
        t.append(f"  │  {icon} ", style=color)
        t.append("Connected to ", style=THEME["text"])
        t.append("CODEX CLI", style=f"bold {color}")
        t.append(f"{'':>33}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show available models
        t.append(f"  │  🤖 ", style=color)
        t.append("SELECT A MODEL", style=f"bold {THEME['cyan']}")
        t.append(f"{'':>38}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        for i, model in enumerate(self.codex_models):
            model_id = model.get("id", "")
            model_name = model.get("name", "")
            desc = model.get("desc", "")
            is_recommended = model.get("recommended", False)

            # Number for selection
            num = i + 1
            t.append(f"  │  ", style=color)
            t.append(f"[{num}]", style=f"bold {THEME['cyan']}")
            t.append(f" {model_name:<18}", style=f"bold {THEME['text']}")

            if is_recommended:
                t.append("⭐ ", style=THEME["gold"])
            else:
                t.append("   ", style="")

            # Truncate desc to fit
            desc_short = desc[:25] + ".." if len(desc) > 25 else desc
            padding = 27 - len(desc_short)
            t.append(f"{desc_short}{' ' * padding}│\n", style=THEME["dim"])

        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show how to select
        t.append(f"  │  ⌨️  ", style=color)
        t.append("Type ", style=THEME["muted"])
        t.append("1", style=f"bold {THEME['cyan']}")
        t.append("-", style=THEME["muted"])
        t.append(f"{len(self._codex_models)}", style=f"bold {THEME['cyan']}")
        t.append(" in prompt and press Enter", style=THEME["muted"])
        t.append(f"{'':>14}│\n", style=color)

        t.append(f"  ╰{'─' * 58}╯\n", style=color)

        # Show API key requirement
        t.append(f"\n  💡 ", style=THEME["gold"])
        t.append("Requires ", style=THEME["muted"])
        t.append("OPENAI_API_KEY", style=f"bold {THEME['cyan']}")
        t.append(" or ", style=THEME["muted"])
        t.append("CODEX_API_KEY", style=f"bold {THEME['cyan']}")
        t.append(" environment variable\n", style=THEME["muted"])

        log.write(t)

        # Set flag to await model selection
        self._awaiting_model_selection = True

        # No model selected yet
        self.current_model = ""
        self.current_provider = "codex"

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.agent = self.current_agent
        badge.mode = ""
        badge.role = ""
        badge.model = ""
        badge.provider = "codex"

    def _auto_select_codex_model(
        self, model_hint: str, agent: Dict[str, Any], log: ConversationLog
    ):
        """Auto-select a Codex model based on user hint."""
        model_hint_lower = model_hint.lower().strip()

        # Try to find a matching model
        matched_model = None
        for model in self._codex_models:
            model_id = model.get("id", "").lower()
            model_name = model.get("name", "").lower()

            # Check various match patterns
            if model_hint_lower in model_id or model_hint_lower in model_name:
                matched_model = model
                break

            # Check for partial matches
            if "o3" in model_hint_lower and "o3" in model_name:
                matched_model = model
                break
            if "o4" in model_hint_lower and "o4" in model_name:
                matched_model = model
                break
            if "gpt" in model_hint_lower and "gpt" in model_name:
                matched_model = model
                break
            if "mini" in model_hint_lower and "mini" in model_name:
                matched_model = model
                break

        if matched_model:
            model_id = matched_model.get("id", "")
            model_name = matched_model.get("name", "")

            self.current_model = model_id
            self.current_provider = "codex"
            self._awaiting_model_selection = False

            badge = self.query_one("#mode-badge", ModeBadge)
            badge.agent = self.current_agent
            badge.model = model_id
            badge.provider = "codex"

            t = Text()
            t.append(f"\n  📜 ", style=THEME["green"])
            t.append("Model selected: ", style=THEME["text"])
            t.append(f"{model_name}", style=f"bold {THEME['green']}")
            t.append(f" ({model_id})\n", style=THEME["dim"])
            t.append(f"  💬 Ready! Type your message.\n", style=THEME["success"])
            log.write(t)
        else:
            # No match found, show available models
            log.add_info(f"Model '{model_hint}' not found. Available models:")
            self._show_codex_models_selection(agent, log)

    def _show_openhands_models_selection(self, agent: Dict[str, Any], log: ConversationLog):
        """Show OpenHands available models for selection."""
        name = agent.get("name", "OpenHands")
        color = THEME["orange"]
        icon = "🤝"

        t = Text()
        t.append(f"\n  ╭{'─' * 58}╮\n", style=color)
        t.append(f"  │  {icon} ", style=color)
        t.append("Connected to ", style=THEME["text"])
        t.append("OPENHANDS", style=f"bold {color}")
        t.append(f"{'':>33}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show available models
        t.append(f"  │  🤖 ", style=color)
        t.append("SELECT A MODEL", style=f"bold {THEME['cyan']}")
        t.append(f"{'':>38}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        for i, model in enumerate(self.openhands_models):
            model_id = model.get("id", "")
            model_name = model.get("name", "")
            desc = model.get("desc", "")
            is_recommended = model.get("recommended", False)

            # Number for selection
            num = i + 1
            t.append(f"  │  ", style=color)
            t.append(f"[{num}]", style=f"bold {THEME['cyan']}")
            t.append(f" {model_name:<18}", style=f"bold {THEME['text']}")

            if is_recommended:
                t.append("⭐ ", style=THEME["gold"])
            else:
                t.append("   ", style="")

            # Truncate desc to fit
            desc_short = desc[:25] + ".." if len(desc) > 25 else desc
            padding = 27 - len(desc_short)
            t.append(f"{desc_short}{' ' * padding}│\n", style=THEME["dim"])

        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show how to select
        t.append(f"  │  ⌨️  ", style=color)
        t.append("Type ", style=THEME["muted"])
        t.append("1", style=f"bold {THEME['cyan']}")
        t.append("-", style=THEME["muted"])
        t.append(f"{len(self._openhands_models)}", style=f"bold {THEME['cyan']}")
        t.append(" in prompt and press Enter", style=THEME["muted"])
        t.append(f"{'':>14}│\n", style=color)

        t.append(f"  ╰{'─' * 58}╯\n", style=color)

        # Show setup info
        t.append(f"\n  💡 ", style=THEME["gold"])
        t.append("Setup: ", style=THEME["muted"])
        t.append(
            "uv tool install openhands -U --python 3.12 && openhands login",
            style=f"bold {THEME['cyan']}",
        )
        t.append("\n", style="")

        log.write(t)

        # Set flag to await model selection
        self._awaiting_model_selection = True

        # No model selected yet
        self.current_model = ""
        self.current_provider = "openhands"

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.agent = self.current_agent
        badge.mode = ""
        badge.role = ""
        badge.model = ""
        badge.provider = "openhands"

    def _auto_select_openhands_model(
        self, model_hint: str, agent: Dict[str, Any], log: ConversationLog
    ):
        """Auto-select an OpenHands model based on user hint."""
        model_hint_lower = model_hint.lower().strip()

        # Try to find a matching model
        matched_model = None
        for model in self._openhands_models:
            model_id = model.get("id", "").lower()
            model_name = model.get("name", "").lower()

            # Check various match patterns
            if model_hint_lower in model_id or model_hint_lower in model_name:
                matched_model = model
                break

            # Check for partial matches
            if "ollama" in model_hint_lower and "ollama" in model_name:
                matched_model = model
                break
            if "local" in model_hint_lower and "local" in model_name:
                matched_model = model
                break
            if "claude" in model_hint_lower and "claude" in model_name:
                matched_model = model
                break
            if "gpt" in model_hint_lower and "gpt" in model_name:
                matched_model = model
                break
            if "gemini" in model_hint_lower and "gemini" in model_name:
                matched_model = model
                break
            if "default" in model_hint_lower and "default" in model_name:
                matched_model = model
                break

        if matched_model:
            model_id = matched_model.get("id", "")
            model_name = matched_model.get("name", "")

            self.current_model = model_id
            self.current_provider = "openhands"
            self._awaiting_model_selection = False

            badge = self.query_one("#mode-badge", ModeBadge)
            badge.agent = self.current_agent
            badge.model = model_id
            badge.provider = "openhands"

            t = Text()
            t.append(f"\n  🤝 ", style=THEME["orange"])
            t.append("Model selected: ", style=THEME["text"])
            t.append(f"{model_name}", style=f"bold {THEME['orange']}")
            t.append(f" ({model_id})\n", style=THEME["dim"])
            t.append(f"  💬 Ready! Type your message.\n", style=THEME["success"])
            log.write(t)
        else:
            # No match found, show available models
            log.add_info(f"Model '{model_hint}' not found. Available models:")
            self._show_openhands_models_selection(agent, log)

    @work(exclusive=True)
    async def _install_agent(self, agent_id: str, log: ConversationLog):
        agent = next((a for a in self._agents if a.short_name == agent_id), None)
        if not agent:
            log.add_error(f"Agent '{agent_id}' not found")
            return

        if agent.is_ready:
            log.add_success(f"{agent.icon} {agent.name} is already installed!")
            return

        try:
            from superqode.agents.discovery import get_agent_by_short_name_async

            full = await get_agent_by_short_name_async(agent_id)
            if full and "actions" in full:
                cmd = full.get("actions", {}).get("*", {}).get("install", {}).get("command", "")
                if cmd:
                    t = Text()
                    t.append(
                        f"\n  📦 Install {agent.icon} {agent.name}:\n\n",
                        style=f"bold {THEME['orange']}",
                    )
                    t.append(f"  $ {cmd}\n", style=THEME["success"])
                    log.write(t)
                    return
        except Exception:
            pass

        log.add_info(f"No install command found for {agent.name}")

    # ========================================================================
    # Multi-Agent: Handoff & Context
    # ========================================================================

    def _handoff(self, args: str, log: ConversationLog):
        if not args:
            log.add_info("Usage: :handoff <mode>.<role> [context]")
            log.add_system("Example: :handoff qa.fullstack Please review the code")
            return

        parts = args.split(maxsplit=1)
        target = parts[0]
        context = parts[1] if len(parts) > 1 else ""

        if "." not in target:
            log.add_error("Target must be mode.role (e.g., qe.fullstack)")
            return

        from_role = f"{self.current_mode}.{self.current_role}" if self.current_role else "home"
        log.add_handoff(from_role, target, context)

        mode, role = target.split(".", 1)
        self._set_role(mode, role, log)

    def _show_context(self, log: ConversationLog):
        t = Text()
        t.append(f"\n  📎 ", style=f"bold {THEME['cyan']}")
        t.append("Current Context\n\n", style=f"bold {THEME['cyan']}")

        t.append(f"  🏷️  Mode: ", style=THEME["muted"])
        t.append(f"{self.current_mode}\n", style=THEME["purple"])

        if self.current_role:
            t.append(f"  👤 Role: ", style=THEME["muted"])
            t.append(f"{self.current_role}\n", style=THEME["success"])

        if self.current_agent:
            icon = AGENT_ICONS.get(self.current_agent, "🤖")
            t.append(f"  {icon} Agent: ", style=THEME["muted"])
            t.append(f"{self.current_agent}\n", style=THEME["orange"])

        if self.current_model:
            t.append(f"  📊 Model: ", style=THEME["muted"])
            t.append(f"{self.current_model}\n", style=THEME["cyan"])

        if self.current_provider:
            t.append(f"  ☁️  Provider: ", style=THEME["muted"])
            t.append(f"{self.current_provider}\n", style=THEME["pink"])

        t.append(f"  📁 Directory: ", style=THEME["muted"])
        t.append(f"{Path.cwd()}\n", style=THEME["text"])

        log.write(t)

    def _show_team(self, log: ConversationLog):
        try:
            from superqode.tui import load_team_config

            config = load_team_config()

            t = Text()
            t.append(f"\n  👥 ", style=f"bold {THEME['purple']}")
            t.append(config.team_name, style=f"bold {THEME['purple']}")
            t.append("\n\n", style="")

            for mode in ["dev", "qe", "devops"]:
                roles = config.get_roles_by_mode(mode)
                if not roles:
                    continue

                mode_colors = {
                    "dev": THEME["success"],
                    "qe": THEME["orange"],
                    "devops": THEME["cyan"],
                }
                mode_icons = {"dev": "💻", "qe": "🧪", "devops": "⚙️"}
                color = mode_colors.get(mode, THEME["purple"])
                icon = mode_icons.get(mode, "🔧")

                t.append(f"  {icon} {mode.upper()}\n", style=f"bold {color}")
                for role in roles:
                    status = "✅" if role.enabled else "○"
                    t.append(
                        f"    {status} ", style=THEME["success"] if role.enabled else THEME["muted"]
                    )
                    t.append(f":{mode} {role.role:<12}", style=color)
                    t.append(f" 📊 {role.model}\n", style=THEME["muted"])

            self._show_command_output(log, t)
        except Exception as e:
            log.add_error(str(e))

    # ========================================================================
    # Help & Utility
    # ========================================================================

    def _show_help(self, log: ConversationLog):
        t = Text()
        t.append(f"\n  ❓ ", style=f"bold {THEME['purple']}")
        t.append("SuperQode Commands\n\n", style=f"bold {THEME['purple']}")

        # Connection modes overview
        t.append(f"  ═══ Connection Modes ═══\n\n", style=f"bold {THEME['gold']}")

        t.append(f"  🔗 ACP (Full Coding Agent)\n", style=f"bold {THEME['cyan']}")
        t.append(f"    :connect acp <name>     ", style=THEME["cyan"])
        t.append(f"Connect to ACP agent (opencode, claude, etc.)\n", style=THEME["muted"])
        t.append(f"    :dev <role>             ", style=THEME["cyan"])
        t.append(f"Connect via role in development mode\n\n", style=THEME["muted"])

        t.append(f"  ⚡ BYOK (Direct LLM + Role Prompts)\n", style=f"bold {THEME['success']}")
        t.append(f"    :connect byok <p> <m>    ", style=THEME["success"])
        t.append(f"Connect to provider/model with role context\n", style=THEME["muted"])
        t.append(f"    :connect                ", style=THEME["success"])
        t.append(f"Interactive picker (choose acp, byok, or local)\n", style=THEME["muted"])
        t.append(f"    :dev <role>             ", style=THEME["success"])
        t.append(f"Connect via role (if mode=byok in YAML)\n\n", style=THEME["muted"])

        t.append(f"  ═══ All Commands ═══\n\n", style=f"bold {THEME['gold']}")

        sections = [
            (
                "💻 Team Roles",
                THEME["success"],
                [
                    (":init", "Initialize project configuration"),
                    (":dev <role>", "Connect to role in development mode"),
                    (":qe <role>", "Connect to role in quality engineering mode"),
                    (":devops <role>", "Connect to role in DevOps mode"),
                    (":roles", "Show all roles with execution modes"),
                    (":team", "Show team configuration"),
                ],
            ),
            (
                "🔌 Connection & Providers",
                THEME["cyan"],
                [
                    (":connect", "Interactive picker (choose acp, byok, or local)"),
                    (":connect acp <name>", "Connect to ACP agent (opencode, claude, etc.)"),
                    (":connect byok", "Interactive BYOK provider/model picker"),
                    (":connect byok <provider>", "Select provider, then pick model"),
                    (":connect byok <p> <m>", "Direct connect to provider/model"),
                    (":connect byok -", "Switch to previous provider"),
                    (":connect byok !", "Show connection history"),
                    (":connect byok last", "Reconnect to last used provider/model"),
                    (":connect local", "Interactive local provider picker"),
                    (":connect local <provider>", "Select local provider, pick model"),
                    (":connect local <p>/<m>", "Direct connect to local provider/model"),
                    (":connect local -", "Switch to previous local provider"),
                    (":connect local !", "Show local connection history"),
                    (":connect local last", "Reconnect to last used local provider/model"),
                ],
            ),
            (
                "🤖 ACP Agents",
                THEME["cyan"],
                [
                    (":acp list", "List all available ACP agents"),
                    (":acp install <name>", "Install an ACP agent"),
                    (":acp model <id>", "Switch model for current agent"),
                ],
            ),
            (
                "⚡ BYOK & Models",
                THEME["success"],
                [
                    (":models", "List models for current provider"),
                    (":models <provider>", "List models for a specific provider"),
                    (":models set <m>", "Switch to a different model"),
                    (":models search <q>", "Search all available models"),
                    (":models update", "Refresh models database from models.dev"),
                    (":models info", "Show model database information"),
                    (":usage", "Show session token usage and cost"),
                    (":usage reset", "Reset usage statistics"),
                    (":health", "Check provider connectivity status"),
                ],
            ),
            (
                "🦙 Local Models",
                THEME["orange"],
                [
                    (":local", "Show local provider status"),
                    (":local scan", "Scan for running local providers"),
                    (":local models", "List all available local models"),
                    (":local test <model>", "Test tool calling with a local model"),
                    (":local info <model>", "Show detailed model information"),
                    (":local recommend", "Show recommended coding models"),
                ],
            ),
            (
                "🤗 HuggingFace",
                THEME["pink"],
                [
                    (":hf", "Show HuggingFace status"),
                    (":hf search <query>", "Search HuggingFace Hub for models"),
                    (":hf trending", "Show trending models on HuggingFace"),
                    (":hf coding", "Show popular coding models"),
                    (":hf info <model>", "Show model details"),
                    (":hf gguf <model>", "List GGUF files for a model"),
                    (":hf download <model>", "Download GGUF files"),
                    (":hf endpoints", "List your Inference Endpoints"),
                    (":hf recommend", "Show recommended HuggingFace models"),
                ],
            ),
            (
                "🔄 Multi-Agent Coordination",
                THEME["orange"],
                [
                    (":handoff <role>", "Hand off current task to another role"),
                    (":context", "Show current work context"),
                    (":disconnect", "Disconnect from current agent/role"),
                    (":home", "Go home / disconnect from all"),
                ],
            ),
            (
                "✅ Approval & Changes",
                THEME["warning"],
                [
                    (":approve [all]", "Approve pending changes (or all)"),
                    (":reject [all]", "Reject pending changes (or all)"),
                    (":diff [mode]", "View file differences (unified/side-by-side)"),
                    (":undo", "Undo the last change"),
                    (":redo", "Redo the last undone change"),
                    (":view <file>", "View a file or artifact"),
                    (":view info <file>", "Show file information without content"),
                ],
            ),
            (
                "📋 Planning & History",
                THEME["purple"],
                [
                    (":plan", "Show the agent's current plan"),
                    (":history", "Show command history"),
                    (":history clear", "Clear command history"),
                    (":checkpoints", "Show undo/redo checkpoints"),
                ],
            ),
            (
                "💲 Shell & Files",
                THEME["cyan"],
                [
                    ("><command>", "Run a shell command"),
                    (":files", "List files in current directory"),
                    (":find <query>", "Search for files by name"),
                    (":search <query>", "Search file contents"),
                    (":sidebar", "Toggle sidebar (Ctrl+B)"),
                    (":open <file>", "Open a file in viewer"),
                ],
            ),
            (
                "📝 Copy & Edit",
                THEME["teal"],
                [
                    (":edit", "Open external editor (Ctrl+E)"),
                    (":copy", "Copy last response to clipboard (Ctrl+Shift+C)"),
                    (":select", "Open selectable text view"),
                    ("@filename", "Reference a file in your message"),
                    (":diagnostics [path]", "Show code diagnostics for path"),
                ],
            ),
            (
                "🏠 Navigation & System",
                THEME["purple"],
                [
                    (":home", "Go home / disconnect from all"),
                    (":clear", "Clear screen (Ctrl+L)"),
                    (":help", "Show this help message"),
                    (":exit", "Exit SuperQode (Ctrl+C)"),
                    (":demo", "Show SuperQode design demo"),
                ],
            ),
            (
                "🔐 Approval Mode",
                THEME["warning"],
                [
                    (":mode", "Show current approval mode"),
                    (":mode auto", "Allow all changes without prompts"),
                    (":mode ask", "Prompt before each tool execution"),
                    (":mode deny", "Block ALL tool executions"),
                ],
            ),
            (
                "📋 Log Verbosity",
                THEME["cyan"],
                [
                    (":log", "Show current log verbosity"),
                    (":log minimal", "Status only - no output content"),
                    (":log normal", "Summarized outputs (default)"),
                    (":log verbose", "Full outputs with highlighting"),
                ],
            ),
            (
                "⌨️ Keyboard Shortcuts",
                THEME["gold"],
                [
                    ("Ctrl+B", "Toggle sidebar"),
                    ("Ctrl+E", "Open external editor"),
                    ("Ctrl+L", "Clear screen"),
                    ("Ctrl+Shift+C", "Copy last response"),
                    ("Ctrl+C", "Exit / Cancel"),
                    ("Tab", "Change section in pickers"),
                    ("→", "Auto-complete command"),
                ],
            ),
        ]

        for title, color, cmds in sections:
            t.append(f"  {title}\n", style=f"bold {color}")
            for cmd, desc in cmds:
                t.append(f"    {cmd:<22}", style=color)
                t.append(f" {desc}\n", style=THEME["muted"])
            t.append("\n", style="")

        self._show_command_output(log, t)

    def _show_command_output(self, log: ConversationLog, content, clear_log: bool = True):
        """Clear screen and show command output cleanly, scrolled to top.

        Args:
            log: The conversation log widget
            content: The content to display (Text or string)
            clear_log: If True, clear the log before writing (default: True).
                      Set to False when updating during navigation to reduce flickering.
        """
        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(content)
            log.scroll_home(animate=False)
            # Re-enable auto-scroll after a short delay
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))
        else:
            # Update during navigation - clear and write but don't scroll to home
            log.auto_scroll = False
            log.clear()
            log.write(content)
            # Don't scroll to home on navigation updates to reduce flickering
            self.set_timer(0.1, lambda: setattr(log, "auto_scroll", True))

    def _show_roles(self, log: ConversationLog):
        try:
            from superqode.tui import load_team_config

            config = load_team_config()

            t = Text()
            t.append(f"\n  👥 ", style=f"bold {THEME['purple']}")
            t.append(f"{config.team_name} — Roles\n", style=f"bold {THEME['purple']}")

            for mode in ["dev", "qe", "devops"]:
                roles = config.get_roles_by_mode(mode)
                if not roles:
                    continue

                mode_colors = {
                    "dev": THEME["success"],
                    "qe": THEME["orange"],
                    "devops": THEME["cyan"],
                }
                mode_icons = {"dev": "💻", "qe": "🧪", "devops": "⚙️"}
                color = mode_colors.get(mode, THEME["purple"])
                icon = mode_icons.get(mode, "🔧")

                t.append(f"\n  {icon} {mode.upper()}\n", style=f"bold {color}")
                for role in roles:
                    status = "✅" if role.enabled else "○"
                    t.append(
                        f"    {status} ", style=THEME["success"] if role.enabled else THEME["muted"]
                    )
                    t.append(f":{mode} {role.role:<15}", style=color)
                    t.append(f" 📊 {role.model:<12}", style=THEME["muted"])
                    t.append(f" {role.description}", style=THEME["dim"])
                    if mode == "qe" and role.role in POWER_QE_ROLES:
                        t.append(" ⚡ POWER", style=f"bold {THEME['warning']}")
                    t.append("\n", style=THEME["dim"])

            total = len(config.roles)
            enabled = config.enabled_count
            t.append(f"\n  💡 {enabled}/{total} roles enabled\n", style=THEME["muted"])
            t.append(
                "  ⚡ Power QE roles: unit, integration, api, ui, accessibility, security, usability\n",
                style=THEME["muted"],
            )
            t.append(
                "  💡 Tip: Edit each role's job_description in superqode.yaml for better results\n",
                style=THEME["dim"],
            )
            self._show_command_output(log, t)
        except Exception as e:
            log.add_error(str(e))

    def _show_files(self, log: ConversationLog):
        try:
            cwd = Path.cwd()
            t = Text()
            t.append(f"\n  📁 ", style=f"bold {THEME['cyan']}")
            t.append(f"{cwd.name}\n\n", style=f"bold {THEME['cyan']}")

            items = sorted([i for i in cwd.iterdir() if not i.name.startswith(".")])[:15]
            for item in items:
                if item.is_dir():
                    t.append(f"  📁 {item.name}/\n", style=THEME["purple"])
                else:
                    t.append(f"  📄 {item.name}\n", style=THEME["text"])

            if len(list(cwd.iterdir())) > 15:
                t.append(f"\n  ... and more files\n", style=THEME["muted"])

            self._show_command_output(log, t)
        except Exception as e:
            log.add_error(str(e))

    def _find_files(self, query: str, log: ConversationLog):
        if not query:
            log.add_info("Usage: :find <query>")
            return

        try:
            from superqode.file_explorer import fuzzy_find_files

            results = fuzzy_find_files(query, max_results=10)

            if results:
                t = Text()
                t.append(f"\n  🔍 ", style=f"bold {THEME['cyan']}")
                t.append(f"Results for '{query}'\n\n", style=f"bold {THEME['cyan']}")

                for item in results:
                    path = item[0] if isinstance(item, tuple) else item
                    t.append(f"  📄 {path.name}", style=THEME["text"])
                    t.append(f"  {path.parent}\n", style=THEME["muted"])

                log.write(t)
            else:
                log.add_info(f"No files matching '{query}'")
        except Exception as e:
            log.add_error(str(e))

    def _do_exit(self, log: ConversationLog):
        """Show a beautiful goodbye screen and exit."""
        self._cleanup_on_exit()
        # Run async cleanup safely - wrap in try/except to prevent event loop errors
        try:
            loop = asyncio.get_running_loop()
            if loop and loop.is_running():
                asyncio.ensure_future(self._exit_sequence_async(log))
            else:
                # If no loop running, just exit directly
                self._show_goodbye_sync(log)
                self.exit()
        except RuntimeError:
            # Event loop is closed or not running - exit directly
            self._show_goodbye_sync(log)
            self.exit()

    async def _exit_sequence_async(self, log: ConversationLog):
        """Await ACP/subprocess cleanup, then show goodbye and exit."""
        # Stop ACP client
        if self._acp_client is not None:
            try:
                await asyncio.wait_for(self._acp_client.stop(), timeout=2.0)
            except Exception:
                pass
            self._acp_client = None

        # Cancel all pending workers
        try:
            self.workers.cancel_all()
        except Exception:
            pass

        # Cancel any pending asyncio tasks related to this app
        try:
            for task in asyncio.all_tasks():
                if not task.done() and task != asyncio.current_task():
                    task.cancel()
        except Exception:
            pass

        # Show goodbye screen
        log.clear()
        term_width = shutil.get_terminal_size().columns
        t = Text()
        t.append("\n\n\n")
        goodbye_art = """
   ______                ____               __
  / ____/___  ____  ____/ / /_  __  _____  / /
 / / __/ __ \\/ __ \\/ __  / __ \\/ / / / _ \\/ /
/ /_/ / /_/ / /_/ / /_/ / /_/ / /_/ /  __/_/
\\____/\\____/\\____/\\__,_/_.___/\\__, /\\___(_)
                             /____/
"""
        for i, line in enumerate(goodbye_art.strip().split("\n")):
            color = GRADIENT[i % len(GRADIENT)]
            padding = max(0, (term_width - len(line)) // 2)
            t.append(" " * padding)
            t.append(line, style=f"bold {color}")
            t.append("\n")
        t.append("\n\n")
        thanks_text = "Thanks for using SuperQode!"
        padding = max(0, (term_width - len(thanks_text) - 4) // 2)
        t.append(" " * padding)
        t.append("👋 ", style="")
        t.append("Thanks for using ", style="#e4e4e7")
        t.append("Super", style="bold #a855f7")
        t.append("Qode", style="bold #ec4899")
        t.append("! 👋\n\n", style="#e4e4e7")
        fun_text = "Keep building amazing things!"
        padding = max(0, (term_width - len(fun_text) - 4) // 2)
        t.append(" " * padding)
        t.append("🚀 ", style="")
        t.append("Keep building amazing things!", style="italic #71717a")
        t.append(" 🚀\n\n\n", style="")
        log.write(t)

        # Exit after a short delay to show the goodbye screen
        self.set_timer(0.5, lambda: self.exit())

    def _show_goodbye_sync(self, log: ConversationLog):
        """Show goodbye screen synchronously (fallback when event loop unavailable)."""
        try:
            log.clear()
            term_width = shutil.get_terminal_size().columns
            t = Text()
            t.append("\n\n\n")
            goodbye_art = """
   ______                ____               __
  / ____/___  ____  ____/ / /_  __  _____  / /
 / / __/ __ \\/ __ \\/ __  / __ \\/ / / / _ \\/ /
/ /_/ / /_/ / /_/ / /_/ / /_/ / /_/ /  __/_/
\\____/\\____/\\____/\\__,_/_.___/\\__, /\\___(_)
                             /____/
"""
            for i, line in enumerate(goodbye_art.strip().split("\n")):
                color = GRADIENT[i % len(GRADIENT)]
                padding = max(0, (term_width - len(line)) // 2)
                t.append(" " * padding)
                t.append(line, style=f"bold {color}")
                t.append("\n")
            t.append("\n\n")
            thanks_text = "Thanks for using SuperQode!"
            padding = max(0, (term_width - len(thanks_text) - 4) // 2)
            t.append(" " * padding)
            t.append("👋 Thanks for using ", style="#e4e4e7")
            t.append("Super", style="bold #a855f7")
            t.append("Qode", style="bold #ec4899")
            t.append("! 👋\n\n", style="#e4e4e7")
            log.write(t)
        except Exception:
            pass

    def _cleanup_on_exit(self):
        """Clean up all running processes and timers before exit."""
        # Cancel any pending operations
        self._cancel_requested = True

        # Stop any running agent process
        if self._agent_process is not None:
            try:
                self._agent_process.terminate()
                self._agent_process.wait(timeout=1)
            except Exception:
                try:
                    self._agent_process.kill()
                except Exception:
                    pass
            self._agent_process = None

        # Force kill ACP client process if it exists (sync cleanup)
        if self._acp_client is not None:
            try:
                if hasattr(self._acp_client, "_process") and self._acp_client._process:
                    self._acp_client._process.terminate()
            except Exception:
                pass

        # Stop all timers
        if self._thinking_timer:
            self._thinking_timer.stop()
            self._thinking_timer = None

        if self._stream_animation_timer:
            self._stream_animation_timer.stop()
            self._stream_animation_timer = None

        if self._permission_pulse_timer:
            self._permission_pulse_timer.stop()
            self._permission_pulse_timer = None

        # Clear busy state
        self.is_busy = False
        self._permission_pending = False

        # Stop any pending workers
        try:
            self.workers.cancel_all()
        except Exception:
            pass

    def action_quit(self) -> None:
        """Handle quit action (Ctrl+C) - clean up properly before exit."""
        # Get the log widget
        try:
            log = self.query_one("#conversation-log", ConversationLog)
            self._do_exit(log)
        except Exception:
            # Fallback: just clean up and exit immediately
            self._cleanup_on_exit()
            self.exit()

    # ========================================================================
    # Coding Agent Features: Approval, Diff, Plan, History, File Viewer
    # ========================================================================

    def _handle_copy(self, log: ConversationLog):
        """Handle :copy command - copy last response or error to clipboard or view it."""
        # Check for error first, then response (check both app and log for response)
        last_error = log.get_last_error()
        if last_error:
            # Copy error
            content_to_copy = last_error
            content_type = "error"
        elif self._last_response or log.get_last_response():
            # Copy response - prefer app's _last_response, fallback to log's
            content_to_copy = self._last_response or log.get_last_response()
            content_type = "response"
        else:
            log.add_info("No response or error to copy yet")
            return

        # Strip markdown for clean copy
        clean_response = self._strip_markdown(content_to_copy)

        # Save to file first (always useful)
        output_file = Path.home() / ".superqode" / f"last_{content_type}.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(clean_response)

        content_label = "Error" if content_type == "error" else "Response"
        try:
            # Try to copy to clipboard using pbcopy (macOS) or xclip (Linux)
            import subprocess
            import sys

            if sys.platform == "darwin":
                # macOS
                process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                process.communicate(clean_response.encode("utf-8"))
                log.add_success(f"✅ {content_label} copied to clipboard!")
                log.add_info(f"📄 Also saved to: {output_file}")
            elif sys.platform.startswith("linux"):
                # Linux - try xclip first, then xsel
                try:
                    process = subprocess.Popen(
                        ["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE
                    )
                    process.communicate(clean_response.encode("utf-8"))
                    log.add_success(f"✅ {content_label} copied to clipboard!")
                    log.add_info(f"📄 Also saved to: {output_file}")
                except FileNotFoundError:
                    try:
                        process = subprocess.Popen(
                            ["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE
                        )
                        process.communicate(clean_response.encode("utf-8"))
                        log.add_success(f"✅ {content_label} copied to clipboard!")
                        log.add_info(f"📄 Also saved to: {output_file}")
                    except FileNotFoundError:
                        log.add_info(f"📄 {content_label} saved to: {output_file}")
                        log.add_info("💡 Use :open to view and select text")
            else:
                log.add_success(f"✅ {content_label} saved to: {output_file}")
                log.add_info("💡 Use :open to view and select text")
        except Exception as e:
            log.add_success(f"✅ {content_label} saved to: {output_file}")
            log.add_info("💡 Use :open to view and select text")

    def _handle_open(self, log: ConversationLog):
        """Handle :open command - open last response in external viewer for text selection."""
        if not self._last_response:
            log.add_info("No response to open yet")
            return

        # Strip markdown for clean view
        clean_response = self._strip_markdown(self._last_response)

        # Save to file
        output_file = Path.home() / ".superqode" / "last_response.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(clean_response)

        try:
            import subprocess
            import sys

            if sys.platform == "darwin":
                # macOS - open in default text editor
                subprocess.Popen(["open", str(output_file)])
                log.add_success(f"✅ Opened in default editor - select and copy text there")
            elif sys.platform.startswith("linux"):
                # Linux - try xdg-open
                subprocess.Popen(["xdg-open", str(output_file)])
                log.add_success(f"✅ Opened in default editor - select and copy text there")
            else:
                # Windows
                subprocess.Popen(["notepad", str(output_file)])
                log.add_success(f"✅ Opened in Notepad - select and copy text there")
        except Exception as e:
            log.add_info(f"📄 Response saved to: {output_file}")
            log.add_info("Open this file manually to select and copy text")

    def _handle_theme(self, args: str, log: ConversationLog):
        """Handle :theme command - change or list themes."""
        from superqode.design_system import get_theme, set_theme, list_themes, get_active_theme_name

        theme_name = args.strip().lower() if args else ""

        if not theme_name:
            # List themes
            t = Text()
            t.append(f"\n◈ Themes\n", style=f"bold {THEME['purple']}")
            t.append(f"  Current: {get_active_theme_name()}\n\n", style=THEME["muted"])

            for name, description in list_themes():
                is_active = name == get_active_theme_name()
                marker = "▸" if is_active else " "
                style = f"bold {THEME['cyan']}" if is_active else THEME["text"]
                t.append(f"  {marker} ", style=THEME["primary"] if is_active else THEME["muted"])
                t.append(f"{name:<12}", style=style)
                t.append(f" {description}\n", style=THEME["muted"])

            t.append(f"\n  Usage: :theme <name>\n", style=THEME["dim"])
            log.write(t)
            return

        # Set theme
        if set_theme(theme_name):
            log.add_success(f"Theme changed to: {theme_name}")
            log.add_info("Restart the app to see all changes")

            # Save to config
            try:
                config_path = Path.home() / ".superqode" / "config.json"
                config_path.parent.mkdir(parents=True, exist_ok=True)

                import json

                config = {}
                if config_path.exists():
                    config = json.loads(config_path.read_text())

                config["theme"] = theme_name
                config_path.write_text(json.dumps(config, indent=2))
            except Exception:
                pass
        else:
            themes = [name for name, _ in list_themes()]
            log.add_error(f"Unknown theme: {theme_name}")
            log.add_info(f"Available: {', '.join(themes)}")

    def _handle_diagnostics(self, args: str, log: ConversationLog):
        """Handle :diagnostics command - show code diagnostics."""
        from superqode.tools.diagnostics import quick_diagnostics

        path = args.strip() if args else "."
        target_path = Path.cwd() / path

        if not target_path.exists():
            log.add_error(f"Path not found: {path}")
            return

        # Collect files
        files_to_check = []
        if target_path.is_file():
            files_to_check = [target_path]
        else:
            # Check common code files
            for ext in [".py", ".js", ".ts", ".go", ".rs", ".c", ".cpp"]:
                files_to_check.extend(list(target_path.rglob(f"*{ext}"))[:50])

        all_diagnostics = []
        for file_path in files_to_check[:50]:
            try:
                diags = quick_diagnostics(file_path)
                all_diagnostics.extend(diags)
            except Exception:
                continue

        if not all_diagnostics:
            log.add_success(f"No diagnostics found in {path}")
            return

        # Display diagnostics
        t = Text()
        t.append(f"\n◈ Diagnostics for {path}\n", style=f"bold {THEME['purple']}")
        t.append(f"  Found {len(all_diagnostics)} issue(s)\n\n", style=THEME["muted"])

        for diag in all_diagnostics[:20]:
            severity = diag.get("severity", "error")
            if severity == "error":
                icon = "✕"
                color = THEME["error"]
            elif severity == "warning":
                icon = "⚠"
                color = THEME["warning"]
            else:
                icon = "ℹ"
                color = THEME["cyan"]

            t.append(f"  {icon} ", style=f"bold {color}")
            t.append(
                f"{diag['file']}:{diag['line']}:{diag.get('column', 1)}\n", style=THEME["cyan"]
            )
            t.append(f"    {diag['message']}\n", style=THEME["text"])

        if len(all_diagnostics) > 20:
            t.append(f"\n  ... and {len(all_diagnostics) - 20} more\n", style=THEME["muted"])

        log.write(t)

    def _handle_edit(self, log: ConversationLog):
        """Handle :edit command - open external editor to compose message."""
        import tempfile
        import subprocess
        import sys
        import os

        # Get editor from environment
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")

        if not editor:
            # Default editors by platform
            if sys.platform == "darwin":
                # Try common macOS editors
                for ed in ["code", "nano", "vim", "vi"]:
                    try:
                        subprocess.run(["which", ed], capture_output=True, check=True)
                        editor = ed
                        break
                    except Exception:
                        continue
                if not editor:
                    editor = "nano"
            elif sys.platform.startswith("linux"):
                editor = "nano"
            else:
                editor = "notepad"

        # Create temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", prefix="superqode_", delete=False
        ) as f:
            # Add helpful comment
            f.write("# Type your message below. Save and close the editor when done.\n")
            f.write("# Lines starting with # are comments and will be removed.\n")
            f.write("# Use @filename to reference files (e.g., @src/main.py)\n\n")
            temp_path = f.name

        log.add_info(f"Opening {editor}... Save and close to send message.")

        # Suspend TUI and open editor
        try:
            # For code (VS Code), use --wait flag
            if "code" in editor.lower():
                cmd = [editor, "--wait", temp_path]
            else:
                cmd = [editor, temp_path]

            # Run editor - this blocks until editor closes
            with self.app.suspend():
                result = subprocess.run(cmd)

            # Read the file content
            with open(temp_path, "r") as f:
                content = f.read()

            # Remove temp file
            try:
                os.unlink(temp_path)
            except Exception:
                pass

            # Process content - remove comments
            lines = content.split("\n")
            message_lines = [line for line in lines if not line.strip().startswith("#")]
            message = "\n".join(message_lines).strip()

            if message:
                # Put message in input and submit
                prompt_input = self.query_one("#prompt-input", Input)
                prompt_input.value = message
                # Auto-submit the message
                self._handle_message(message, log)
                prompt_input.value = ""
            else:
                log.add_info("No message entered (empty or only comments)")

        except FileNotFoundError:
            log.add_error(f"Editor '{editor}' not found. Set $EDITOR environment variable.")
        except Exception as e:
            log.add_error(f"Error opening editor: {e}")
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    def _handle_select(self, log: ConversationLog):
        """Handle :select command - show response in a selectable text screen."""
        if not self._last_response:
            log.add_info("No response to select yet")
            return

        # Push a screen with TextArea for selection
        from textual.screen import ModalScreen
        from textual.widgets import TextArea, Static, Button
        from textual.containers import Vertical, Horizontal
        from textual.binding import Binding

        class SelectableScreen(ModalScreen):
            """Screen with selectable text area."""

            BINDINGS = [
                Binding("escape", "dismiss", "Close"),
                Binding("ctrl+c", "copy_selection", "Copy"),
            ]

            CSS = """
            SelectableScreen {
                align: center middle;
            }

            SelectableScreen > Vertical {
                width: 90%;
                height: 90%;
                background: #0a0a0a;
                border: round #7c3aed;
                padding: 1;
            }

            SelectableScreen .title {
                text-align: center;
                color: #a855f7;
                text-style: bold;
                height: 2;
            }

            SelectableScreen TextArea {
                height: 1fr;
                background: #000000;
                border: solid #1a1a1a;
            }

            SelectableScreen .hints {
                text-align: center;
                color: #71717a;
                height: 2;
            }

            SelectableScreen .buttons {
                height: 3;
                align: center middle;
            }

            SelectableScreen Button {
                margin: 0 1;
            }
            """

            def __init__(self, content: str):
                super().__init__()
                self._content = content

            def compose(self):
                with Vertical():
                    yield Static("📋 Select & Copy Response", classes="title")
                    yield TextArea(self._content, id="text-area", read_only=True)
                    yield Static(
                        "Select text with mouse • Ctrl+C to copy • Escape to close", classes="hints"
                    )
                    with Horizontal(classes="buttons"):
                        yield Button("Copy All", id="copy-all", variant="primary")
                        yield Button("Close", id="close-btn", variant="default")

            def on_button_pressed(self, event):
                if event.button.id == "copy-all":
                    self._copy_all()
                elif event.button.id == "close-btn":
                    self.dismiss()

            def action_copy_selection(self):
                """Copy selected text or all text."""
                try:
                    ta = self.query_one("#text-area", TextArea)
                    selected = ta.selected_text
                    if selected:
                        self._copy_to_clipboard(selected)
                        self.notify("Selection copied!", severity="information")
                    else:
                        self._copy_all()
                except Exception:
                    self._copy_all()

            def _copy_all(self):
                """Copy all text to clipboard."""
                self._copy_to_clipboard(self._content)
                self.notify("Response copied to clipboard!", severity="information")

            def _copy_to_clipboard(self, text: str):
                """Copy text to system clipboard."""
                try:
                    import subprocess
                    import sys

                    if sys.platform == "darwin":
                        subprocess.run(["pbcopy"], input=text.encode(), check=True)
                    elif sys.platform.startswith("linux"):
                        try:
                            subprocess.run(
                                ["xclip", "-selection", "clipboard"],
                                input=text.encode(),
                                check=True,
                            )
                        except FileNotFoundError:
                            subprocess.run(
                                ["xsel", "--clipboard", "--input"], input=text.encode(), check=True
                            )
                    elif sys.platform == "win32":
                        subprocess.run(["clip"], input=text.encode(), check=True)
                except Exception:
                    pass

            def action_dismiss(self):
                self.dismiss()

        # Clean up the response for selection
        clean_response = self._strip_markdown(self._last_response)

        def on_screen_dismissed(_):
            # Return focus to input after screen is dismissed
            self.set_timer(0.1, self._ensure_input_focus)

        screen = SelectableScreen(clean_response)
        self.push_screen(screen, callback=on_screen_dismissed)

    def _handle_approve(self, args: str, log: ConversationLog):
        """Handle :approve command."""
        if self._approval_manager is None:
            log.add_info("No pending approvals")
            return

        pending = self._approval_manager.get_pending()
        if not pending:
            log.add_info("No pending approvals")
            return

        if args.lower() == "all":
            count = self._approval_manager.approve_all()
            log.add_success(f"✅ Approved {count} change(s)")
            return

        # Approve first pending
        req = pending[0]
        always = args.lower() == "always"
        self._approval_manager.approve(req.id, always=always)

        msg = f"✅ Approved: {req.title}"
        if always:
            msg += " (always)"
        log.add_success(msg)

        # Apply the change if it's a file change
        if req.new_content and req.file_path:
            try:
                self._file_manager.write(req.file_path, req.new_content)
                log.add_success(f"📄 Written: {req.file_path}")
            except Exception as e:
                log.add_error(f"Failed to write: {e}")

    def _handle_reject(self, args: str, log: ConversationLog):
        """Handle :reject command."""
        if self._approval_manager is None:
            log.add_info("No pending approvals")
            return

        pending = self._approval_manager.get_pending()
        if not pending:
            log.add_info("No pending approvals")
            return

        if args.lower() == "all":
            count = self._approval_manager.reject_all()
            log.add_error(f"❌ Rejected {count} change(s)")
            return

        # Reject first pending
        req = pending[0]
        always = args.lower() == "always"
        self._approval_manager.reject(req.id, always=always)

        msg = f"❌ Rejected: {req.title}"
        if always:
            msg += " (never allow)"
        log.add_error(msg)

    def _handle_diff(self, args: str, log: ConversationLog):
        """Handle :diff command."""
        from rich.console import Console

        console = Console()

        # Initialize diff_viewer if it doesn't exist
        if not hasattr(self, "_diff_viewer") or self._diff_viewer is None:
            self._diff_viewer = DiffViewer(console)

        # Check for mode argument
        if args.lower() == "split":
            self._diff_viewer.set_mode(DiffMode.SPLIT)
            log.add_info("Diff mode: split (side-by-side)")
            return
        elif args.lower() == "unified":
            self._diff_viewer.set_mode(DiffMode.UNIFIED)
            log.add_info("Diff mode: unified")
            return
        elif args.lower() == "compact":
            self._diff_viewer.set_mode(DiffMode.COMPACT)
            log.add_info("Diff mode: compact")
            return

        # Show pending diffs
        if self._approval_manager:
            pending = self._approval_manager.get_pending()
            if pending:
                t = Text()
                t.append(f"\n  📊 ", style=f"bold {THEME['cyan']}")
                t.append(f"Pending Changes ({len(pending)})\n\n", style=f"bold {THEME['cyan']}")

                for req in pending:
                    if req.old_content is not None and req.new_content:
                        diff = compute_diff(
                            req.old_content, req.new_content, req.file_path or "file"
                        )
                        t.append(f"  📄 {req.file_path or 'file'}", style=f"bold {THEME['cyan']}")
                        t.append(f"  +{diff.additions}", style=f"bold {THEME['success']}")
                        t.append("/", style=THEME["muted"])
                        t.append(f"-{diff.deletions}\n", style=f"bold {THEME['error']}")

                log.write(t)
                return

        log.add_info("No pending diffs. Use :diff split or :diff unified to set mode.")

    def _handle_plan(self, args: str, log: ConversationLog):
        """Handle :plan command."""
        from rich.console import Console

        console = Console()

        if args.lower() == "clear":
            self._plan_manager.clear()
            log.add_success("Plan cleared")
            return

        if not self._plan_manager.tasks:
            log.add_info("No plan yet. The agent will create one when working.")
            return

        # Render the plan
        t = Text()
        t.append(f"\n  📋 ", style=f"bold {THEME['purple']}")
        t.append(f"{self._plan_manager.current_plan_name}\n", style=f"bold {THEME['purple']}")

        completed, total, percentage = self._plan_manager.get_progress()
        t.append(f"  Progress: {completed}/{total} ({percentage:.0f}%)\n\n", style=THEME["muted"])

        status_icons = {
            TaskStatus.PENDING: ("⏳", THEME["muted"]),
            TaskStatus.IN_PROGRESS: ("🔄", THEME["cyan"]),
            TaskStatus.COMPLETED: ("✅", THEME["success"]),
            TaskStatus.FAILED: ("❌", THEME["error"]),
        }

        for i, task in enumerate(self._plan_manager.tasks, 1):
            icon, color = status_icons.get(task.status, ("○", THEME["muted"]))
            t.append(f"  {icon} ", style=color)
            t.append(f"{i}. ", style=THEME["muted"])

            if task.status == TaskStatus.COMPLETED:
                t.append(task.content, style=f"strike {color}")
            else:
                t.append(
                    task.content,
                    style=color if task.status == TaskStatus.IN_PROGRESS else THEME["text"],
                )
            t.append("\n", style="")

        log.write(t)

    def _handle_undo(self, log: ConversationLog):
        """Handle :undo command - uses enhanced undo manager."""
        # Try enhanced undo manager first
        if hasattr(self, "_undo_manager") and self._undo_manager:
            result = self._undo_manager.undo()
            if result:
                text = Text()
                text.append("  ✦ ", style=f"bold {SQ_COLORS.success}")
                text.append("Undone: ", style=SQ_COLORS.text_secondary)
                text.append(result.name, style=f"bold {SQ_COLORS.text_primary}")
                if result.files_changed:
                    text.append(f" ({len(result.files_changed)} files)", style=SQ_COLORS.text_dim)
                text.append("\n", style="")
                log.write(text)
                return

        # Fallback to file manager undo
        version = self._file_manager.undo()

        if version:
            text = Text()
            text.append("  ✦ ", style=f"bold {SQ_COLORS.success}")
            text.append(
                f"Undone: {version.operation} on {version.path}\n", style=SQ_COLORS.text_secondary
            )
            log.write(text)
        else:
            log.add_info("◇ Nothing to undo")

    def _handle_redo(self, log: ConversationLog):
        """Handle :redo command."""
        if hasattr(self, "_undo_manager") and self._undo_manager:
            result = self._undo_manager.redo()
            if result:
                text = Text()
                text.append("  ✦ ", style=f"bold {SQ_COLORS.success}")
                text.append("Redone: ", style=SQ_COLORS.text_secondary)
                text.append(result.name, style=f"bold {SQ_COLORS.text_primary}")
                text.append("\n", style="")
                log.write(text)
                return
        log.add_info("◇ Nothing to redo")

    def _handle_checkpoints(self, log: ConversationLog):
        """Handle :checkpoints command - list available checkpoints."""
        if not hasattr(self, "_undo_manager") or not self._undo_manager:
            log.add_info("◇ Checkpoints not available")
            return

        checkpoints = self._undo_manager.get_checkpoints(10)

        if not checkpoints:
            log.add_info(
                "◇ No checkpoints yet. They're created automatically before agent operations."
            )
            return

        text = Text()
        text.append("\n  ◈ ", style=f"bold {SQ_COLORS.primary}")
        text.append(f"Checkpoints ({len(checkpoints)})\n\n", style=f"bold {SQ_COLORS.primary}")

        current = self._undo_manager.get_current_checkpoint()

        for cp in reversed(checkpoints):
            is_current = current and cp.id == current.id
            prefix = "▸ " if is_current else "  "
            style = f"bold {SQ_COLORS.text_primary}" if is_current else SQ_COLORS.text_secondary

            text.append(
                f"  {prefix}", style=SQ_COLORS.primary if is_current else SQ_COLORS.text_dim
            )
            text.append(f"{cp.name}", style=style)
            text.append(f"  {cp.timestamp.strftime('%H:%M:%S')}", style=SQ_COLORS.text_ghost)
            if cp.files_changed:
                text.append(f"  ({len(cp.files_changed)} files)", style=SQ_COLORS.text_dim)
            text.append("\n", style="")

        text.append(
            f"\n  Use :restore <name> to restore a checkpoint\n", style=SQ_COLORS.text_ghost
        )
        log.write(text)

    def _handle_agents_discover(self, log: ConversationLog):
        """Handle :acp discover command."""
        text = Text()
        text.append("\n  ◈ ", style=f"bold {SQ_COLORS.primary}")
        text.append("Discovering ACP agents...\n", style=SQ_COLORS.text_secondary)
        log.write(text)

        # Run discovery in background
        self._discover_acp_agents()

    def _handle_history(self, args: str, log: ConversationLog):
        """Handle :history command."""
        if args.lower() == "clear":
            self._history_manager.clear()
            log.add_success("History cleared")
            return

        entries = self._history_manager.get_recent(20)

        if not entries:
            log.add_info("No history yet")
            return

        t = Text()
        t.append(f"\n  📜 ", style=f"bold {THEME['purple']}")
        t.append(f"Command History ({len(entries)} entries)\n\n", style=f"bold {THEME['purple']}")

        from datetime import datetime

        for entry in entries:
            dt = datetime.fromtimestamp(entry.timestamp)
            time_str = dt.strftime("%H:%M:%S")

            t.append(f"  {time_str} ", style=THEME["muted"])

            if entry.agent:
                t.append(f"[{entry.agent}] ", style=f"bold {THEME['cyan']}")
            elif entry.mode:
                t.append(f"[{entry.mode}] ", style=f"bold {THEME['success']}")

            cmd = entry.input[:50] + "..." if len(entry.input) > 50 else entry.input
            t.append(f"{cmd}\n", style=THEME["text"])

        log.write(t)

    def _handle_view(self, args: str, log: ConversationLog):
        """Handle :view command for file viewing."""
        if not args:
            log.add_info("Usage: :view <file_path> or :view info <file_path>")
            return

        parts = args.split(maxsplit=1)

        # Check for subcommand
        if parts[0].lower() == "info" and len(parts) > 1:
            self._view_file_info(parts[1], log)
            return

        # View file content
        file_path = args.strip()
        self._view_file(file_path, log)

    def _view_file(self, file_path: str, log: ConversationLog):
        """View file content with syntax highlighting."""
        from rich.console import Console
        from rich.syntax import Syntax

        try:
            info = get_file_info(file_path)

            # Header
            t = Text()
            t.append(f"\n  📄 ", style=f"bold {THEME['cyan']}")
            t.append(info.name, style=f"bold {THEME['cyan']}")
            t.append(f"  [{info.language}]", style=f"bold {THEME['purple']}")
            t.append(f"  {info.lines} lines\n", style=THEME["muted"])
            log.write(t)

            if info.is_binary:
                log.add_info("Binary file - cannot display content")
                return

            # Read and display content
            content = atomic_read(file_path)
            lines = content.splitlines()

            # Show first 50 lines
            preview_lines = lines[:50]
            preview_content = "\n".join(preview_lines)

            syntax = Syntax(
                preview_content,
                info.language,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
                background_color="#000000",
            )

            log.write(Panel(syntax, border_style=THEME["border"], box=ROUNDED, padding=(0, 1)))

            if len(lines) > 50:
                log.add_info(f"Showing first 50 of {len(lines)} lines")

        except FileNotFoundError:
            log.add_error(f"File not found: {file_path}")
        except Exception as e:
            log.add_error(f"Error viewing file: {e}")

    def _view_file_info(self, file_path: str, log: ConversationLog):
        """View file information without content."""
        try:
            info = get_file_info(file_path)

            t = Text()
            t.append(f"\n  📄 ", style=f"bold {THEME['cyan']}")
            t.append("File Info\n\n", style=f"bold {THEME['cyan']}")

            t.append(f"  Name:     ", style=THEME["muted"])
            t.append(f"{info.name}\n", style=THEME["text"])

            t.append(f"  Path:     ", style=THEME["muted"])
            t.append(f"{info.path}\n", style=THEME["text"])

            t.append(f"  Language: ", style=THEME["muted"])
            t.append(f"{info.language}\n", style=f"bold {THEME['purple']}")

            t.append(f"  Size:     ", style=THEME["muted"])
            # Format size
            size = info.size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            t.append(f"{size_str}\n", style=THEME["text"])

            t.append(f"  Lines:    ", style=THEME["muted"])
            t.append(f"{info.lines}\n", style=THEME["text"])

            t.append(f"  Binary:   ", style=THEME["muted"])
            t.append(f"{'Yes' if info.is_binary else 'No'}\n", style=THEME["text"])

            log.write(t)

        except FileNotFoundError:
            log.add_error(f"File not found: {file_path}")
        except Exception as e:
            log.add_error(f"Error: {e}")

    def _handle_search(self, args: str, log: ConversationLog):
        """Handle :search command for searching in files."""
        if not args:
            log.add_info("Usage: :search <term> [file_path]")
            return

        parts = args.split(maxsplit=1)
        term = parts[0]
        file_path = parts[1] if len(parts) > 1 else None

        if file_path:
            # Search in specific file
            self._search_in_file(term, file_path, log)
        else:
            # Search in current directory
            self._search_in_directory(term, log)

    def _search_in_file(self, term: str, file_path: str, log: ConversationLog):
        """Search for a term in a specific file."""
        try:
            content = atomic_read(file_path)
            lines = content.splitlines()

            results = []
            for i, line in enumerate(lines, 1):
                if term.lower() in line.lower():
                    results.append((i, line.strip()))

            if not results:
                log.add_info(f"No matches for '{term}' in {file_path}")
                return

            t = Text()
            t.append(f"\n  🔍 ", style=f"bold {THEME['cyan']}")
            t.append(
                f"{len(results)} match(es) for '{term}' in {file_path}\n\n",
                style=f"bold {THEME['cyan']}",
            )

            for line_no, content in results[:15]:
                t.append(f"  {line_no:>4}: ", style=THEME["muted"])

                # Highlight the search term
                content_lower = content.lower()
                term_lower = term.lower()

                if term_lower in content_lower:
                    idx = content_lower.index(term_lower)
                    t.append(content[:idx], style=THEME["text"])
                    t.append(
                        content[idx : idx + len(term)],
                        style=f"bold {THEME['warning']} on #f59e0b30",
                    )
                    t.append(content[idx + len(term) :], style=THEME["text"])
                else:
                    t.append(content, style=THEME["text"])
                t.append("\n", style="")

            if len(results) > 15:
                t.append(f"\n  ... and {len(results) - 15} more matches\n", style=THEME["muted"])

            log.write(t)

        except FileNotFoundError:
            log.add_error(f"File not found: {file_path}")
        except Exception as e:
            log.add_error(f"Error: {e}")

    def _search_in_directory(self, term: str, log: ConversationLog):
        """Search for a term in all files in current directory."""
        import os

        results = []
        cwd = Path.cwd()

        # Search in common code files
        extensions = {
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".java",
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".rb",
            ".php",
            ".swift",
            ".kt",
            ".md",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".xml",
            ".html",
            ".css",
            ".scss",
            ".sql",
            ".sh",
            ".bash",
        }

        for root, dirs, files in os.walk(cwd):
            # Skip hidden and common ignore directories
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in {"node_modules", "venv", "__pycache__", "dist", "build", ".git"}
            ]

            for file in files:
                if Path(file).suffix.lower() in extensions:
                    file_path = Path(root) / file
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        for i, line in enumerate(content.splitlines(), 1):
                            if term.lower() in line.lower():
                                rel_path = file_path.relative_to(cwd)
                                results.append((str(rel_path), i, line.strip()))
                                if len(results) >= 50:
                                    break
                    except Exception:
                        continue

                    if len(results) >= 50:
                        break

            if len(results) >= 50:
                break

        if not results:
            log.add_info(f"No matches for '{term}' in current directory")
            return

        t = Text()
        t.append(f"\n  🔍 ", style=f"bold {THEME['cyan']}")
        t.append(f"{len(results)} match(es) for '{term}'\n\n", style=f"bold {THEME['cyan']}")

        current_file = None
        for file_path, line_no, content in results[:30]:
            if file_path != current_file:
                current_file = file_path
                t.append(f"\n  📄 {file_path}\n", style=f"bold {THEME['purple']}")

            t.append(f"    {line_no:>4}: ", style=THEME["muted"])

            # Truncate long lines
            if len(content) > 60:
                content = content[:57] + "..."

            t.append(f"{content}\n", style=THEME["text"])

        if len(results) > 30:
            t.append(f"\n  ... and {len(results) - 30} more matches\n", style=THEME["muted"])

        log.write(t)


# ============================================================================
# ENTRY POINT
# ============================================================================


def run_textual_app():
    SuperQodeApp().run()


if __name__ == "__main__":
    run_textual_app()
