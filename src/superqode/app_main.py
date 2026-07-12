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
import asyncio.base_subprocess as _asyncio_base_subprocess
import json
import os
import pty
import re
import select
import signal
import subprocess
import shutil
import shlex
import time
import math
import random
import concurrent.futures
import threading
from urllib.parse import urlparse
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, Center, ScrollableContainer
from textual.widgets import Static, Input, Footer, RichLog, DirectoryTree, TextArea
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

from superqode.providers.model_specs import (
    normalize_model_for_provider,
    normalize_provider_id,
    split_provider_model_ref,
)


from superqode.app.recipes import PromptCompletionCandidate, LocalRecipe  # noqa: F401


# Import from modular app package
from superqode.app.constants import (
    ASCII_LOGO,
    COMPACT_LOGO,
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
from superqode.widgets.command_palette import CommandPalette, PaletteCommand
from superqode.widgets.rewind_overlay import RewindOverlay, RewindTarget
from superqode.widgets.theme_picker import ThemePicker
from superqode.app.theme_bridge import (
    apply_theme as _apply_theme_palette,
    load_saved_theme,
    save_theme,
    theme_names,
)

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
from superqode.providers.models import LATEST_GOOGLE_FLASH_MODEL, LATEST_GOOGLE_PRO_MODEL
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


from superqode.app.async_utils import _AsyncLoopThread, _safe_subprocess_transport_del  # noqa: F401,E402


# ============================================================================
# SELECTION-AWARE INPUT
# ============================================================================


from superqode.app.inputs import SelectionAwareInput  # noqa: F401


# ============================================================================
# WELCOME SCREEN
# ============================================================================


from superqode.app.welcome import render_welcome, _harness_display_name  # noqa: F401


# ============================================================================
# SESSION HELPERS
# ============================================================================


from superqode.app.session_state import get_session, get_mode, set_mode  # noqa: F401


# ============================================================================
# MAIN APP
# ============================================================================


from superqode.app.mixins.sidebar import SidebarMixin


from superqode.app.mixins.factory import FactoryMixin


from superqode.app.mixins.switchboard import SwitchboardMixin


from superqode.app.mixins.huggingface import HuggingFaceMixin


from superqode.app.mixins.mcp import McpMixin


from superqode.app.mixins.connect import ConnectMixin


from superqode.app.mixins.events import EventHandlerMixin


from superqode.app.mixins.actions_misc import MiscActionsMixin


from superqode.app.mixins.completion import CompletionMixin


from superqode.app.mixins.pickers import PickerNavigationMixin


from superqode.app.mixins.formatting import FormattingMixin


from superqode.app.mixins.model_catalog import ModelCatalogMixin


from superqode.app.mixins.local_models import LocalModelsMixin


from superqode.app.mixins.codex import CodexMixin


from superqode.app.mixins.dialogs import DialogsMixin


from superqode.app.mixins.commands_impl import CommandImplMixin


from superqode.app.mixins.agent_run import AgentRunMixin


from superqode.app.mixins.slash_commands import SlashCommandMixin


from superqode.app.mixins.helpers import HelpersMixin


class SuperQodeApp(HelpersMixin, SlashCommandMixin, AgentRunMixin, CommandImplMixin, DialogsMixin, CodexMixin, LocalModelsMixin, ModelCatalogMixin, FormattingMixin, PickerNavigationMixin, CompletionMixin, MiscActionsMixin, EventHandlerMixin, ConnectMixin, McpMixin, HuggingFaceMixin, SwitchboardMixin, FactoryMixin, SidebarMixin, App):
    CSS = APP_CSS
    TITLE = "SuperQode"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_screen", "Clear", show=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=True),
        Binding("ctrl+t", "toggle_thinking", "Toggle Logs", show=True),
        Binding("ctrl+k", "command_palette", "Commands", show=True),
        Binding("ctrl+r", "rewind", "Rewind", show=True),
        Binding("escape", "smart_cancel", "Cancel", show=True),
        Binding("pageup", "scroll_log_page_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_log_page_down", "Scroll Down", show=False),
        Binding("ctrl+home", "scroll_log_home", "Top", show=False),
        Binding("ctrl+end", "scroll_log_end", "Bottom", show=False),
        Binding("ctrl+x", "cancel_agent", "Cancel Agent", show=False),
        Binding("ctrl+g", "stash_draft", "Stash draft", show=False),
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
        # Arrow keys for runtime navigation
        Binding("up", "navigate_runtime_up", "↑ Previous runtime", show=False),
        Binding("down", "navigate_runtime_down", "↓ Next runtime", show=False),
        Binding("enter", "select_highlighted_runtime", "Select highlighted runtime", show=False),
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
        # Sidebar panel bindings
        Binding("ctrl+1", "sidebar_harness", "Harness", show=False),
        Binding("ctrl+2", "sidebar_files", "Files", show=False),
        Binding("ctrl+3", "sidebar_agent", "Agent", show=False),
        Binding("ctrl+4", "sidebar_context", "Context", show=False),
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
    show_thinking_logs = reactive(True)  # Toggle for thinking logs visibility (default enabled)
    # "normal" folds the agent loop's per-iteration bookkeeping into the live
    # throbber and rate-limits reasoning; "verbose" prints every line as before.
    thinking_verbosity = reactive("normal")
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
    _codex_highlighted_model_index = 0  # Track highlighted Codex SDK model
    _codex_highlighted_effort_index = 0  # Track highlighted Codex SDK reasoning effort
    _awaiting_codex_model = False  # Track if we're waiting for Codex SDK model selection
    _awaiting_codex_effort = False  # Track if we're waiting for Codex SDK effort selection
    _awaiting_mode_selection = False  # Track Chat/Build/Plan picker state
    _mode_highlighted_index = 0  # Track highlighted interaction mode
    _just_showed_byok_picker = (
        False  # Flag to prevent immediate provider selection after showing picker
    )
    _awaiting_permission = False  # Track if waiting for permission response
    _awaiting_agent_question = False  # Track if an agent is waiting for user input
    _available_models: Dict[str, List[str]] = {}  # Available models per agent
    _last_response: str = ""  # Store last agent response for :copy command
    _last_user_message: str = ""  # Store last user prompt for :retry
    _last_run_summary: dict = {}  # Store compact work summary for :work
    _opencode_session_id: str = ""  # Track opencode session for conversation continuity
    _claude_session_id: str = ""  # Track Claude ACP session for multi-turn
    _claude_process = None  # Keep Claude ACP process alive for multi-turn
    _is_first_message: bool = True  # Track if this is the first message in session
    _acp_client = None  # ACP client for agent communication
    _acp_client_key = None  # Current reusable ACP session key
    _acp_loop_runner = None  # Dedicated loop for persistent ACP clients
    _acp_slash_registry = None  # Lazily-built superqode.acp.slash.SlashRegistry
    _plan_mode_enabled: bool = False  # Keep native BYOK/local prompts in plan-only mode
    _chat_mode: bool = False  # Raw direct-to-model chat: no repo context, no tools, speed metrics
    _chat_history: list = None  # Conversation buffer used only while chat mode is on
    _hub_mode: bool = False  # Model-search mode: typed lines search the model catalog
    _force_plan_once: bool = False  # Run the next native prompt as plan-only
    _force_execute_once: bool = False  # Run the next prompt even if plan mode is enabled
    _pending_plan_request: str = ""  # Last planned request available for approval/execution
    _pending_plan_status: str = ""  # pending / approved / rejected

    def __init__(self):
        super().__init__()
        # Apply the persisted accent theme before any widget renders so the
        # whole UI paints in the chosen palette from the first frame.
        self._current_theme = load_saved_theme()
        _apply_theme_palette(self._current_theme)
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
        self._attached_refs: list[str] = []
        self._prompt_completion_candidates: list[PromptCompletionCandidate] = []
        self._prompt_completion_index = 0
        self._prompt_completion_visible = False
        self._history_manager = HistoryManager()
        self._plan_manager = PlanManager()
        self._vim_experience_enabled = self._env_flag("SUPERQODE_VIM_MODE")
        self._last_ex_command = ""
        self._vim_search_query = ""
        self._vim_search_matches: list[int] = []
        self._vim_search_index = -1
        self._vim_search_reverse = False

        # PERFORMANCE: Animation manager for throttled animations
        self._animation_manager = None

        # LiteLLM prewarm is delayed until after the first screen paints so
        # background imports do not compete with TUI startup.


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
                        yield Static("<>", id="prompt-symbol")
                        yield SelectionAwareInput(
                            placeholder=SelectionAwareInput.DEFAULT_PLACEHOLDER,
                            id="prompt-input",
                            suggester=CommandSuggester(),
                            # No restrict parameter - allow all characters including colon
                        )
                    yield Static("", id="prompt-completions")
                    yield Static("", id="queued-input")
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

                # Pinned, auto-updating plan/todo checklist (from todo_write).
                yield Static("", id="todo-panel")

                # Compact active tool strip. This is separate from the existing
                # thinking bars/animations, which remain unchanged.
                yield Static("", id="active-tools")

                # Thinking indicator with changing text at bottom (shown when agent is thinking)
                yield StreamingThinkingIndicator(id="streaming-thinking")

                # Scanning line animation at BOTTOM (shown when agent is thinking)
                yield BottomScanningLine(id="thinking-wave-bottom")

        yield CommandPalette(commands=self._build_palette_commands(), id="command-palette")

    def on_mount(self):
        # Focus input after a short delay to ensure widgets are fully ready
        self.set_timer(0.1, self._focus_input_on_ready)
        self._set_prompt_border_title()
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
        # Apply user keybinding overrides, if any
        self._load_custom_keybindings()
        self.set_timer(0.75, self._prewarm_litellm)
        # Keep the dynamic catalog fresh independently of optional provider
        # health checks. The short delay lets the first frame render first.
        self.set_timer(0.5, self._start_models_dev_refresh)
        self.set_interval(60 * 60, self._start_models_dev_refresh)
        if os.getenv("SUPERQODE_STARTUP_HEALTH", "").strip().lower() in ("1", "true", "yes"):
            self._run_startup_health_check()
        # Auto-connect a connection profile if requested via --connect.
        if os.getenv("SUPERQODE_CONNECT", "").strip():
            self.set_timer(1.0, self._run_startup_connect)


    def _run_startup_connect(self) -> None:
        """Dispatch the connection profile named in SUPERQODE_CONNECT (--connect)."""
        profile_id = os.environ.pop("SUPERQODE_CONNECT", "").strip()
        if not profile_id:
            return
        try:
            from superqode.providers.connection_profiles import get_connection_profile

            profile = get_connection_profile(profile_id)
            if profile is None:
                return
            log = self.query_one("#log", ConversationLog)
            self._dispatch_connection_profile(profile, log)
        except Exception:  # noqa: BLE001 — startup convenience, never fatal
            pass

    # Actions users may safely rebind via ~/.superqode/keybindings.json
    _REBINDABLE_ACTIONS = {
        "toggle_sidebar",
        "toggle_thinking",
        "command_palette",
        "clear_screen",
        "stash_draft",
        "scroll_log_page_up",
        "scroll_log_page_down",
        "scroll_log_home",
        "scroll_log_end",
        "cancel_agent",
        "undo_action",
        "redo_action",
        "toggle_split_view",
        "create_checkpoint",
        "rewind",
    }


    def _focus_input_on_ready(self):
        """Focus the input box once widgets are ready."""
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
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
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
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


    def on_resize(self, event: events.Resize) -> None:
        """Re-flow the welcome screen when only it is shown and the size changes."""
        if not getattr(self, "_welcome_active", False):
            return
        existing = getattr(self, "_welcome_resize_timer", None)
        if existing is not None:
            try:
                existing.stop()
            except Exception:
                pass
        # Debounce: resize fires rapidly while dragging the terminal edge.
        self._welcome_resize_timer = self.set_timer(0.12, self._rerender_welcome)


    # ========================================================================
    # Sidebar Toggle & File Selection
    # ========================================================================


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

    def action_command_palette(self):
        """Open the command palette (Ctrl+K)."""
        try:
            palette = self.query_one("#command-palette", CommandPalette)
            palette.toggle()
        except Exception:
            self._ensure_input_focus()


    def action_scroll_log_page_up(self) -> None:
        """Scroll the conversation log up while keeping input focused."""
        log = self._conversation_log()
        if log is not None:
            log.auto_scroll = False
            log.scroll_page_up(animate=False)

    def action_scroll_log_page_down(self) -> None:
        """Scroll the conversation log down while keeping input focused."""
        log = self._conversation_log()
        if log is not None:
            log.auto_scroll = False
            log.scroll_page_down(animate=False)

    def action_scroll_log_home(self) -> None:
        """Scroll the conversation log to the top."""
        log = self._conversation_log()
        if log is not None:
            log.auto_scroll = False
            log.scroll_home(animate=False)

    def action_scroll_log_end(self) -> None:
        """Scroll the conversation log to the bottom and resume follow mode."""
        log = self._conversation_log()
        if log is not None:
            log.scroll_end(animate=False)
            log.auto_scroll = True


    def on_key(self, event: events.Key) -> None:
        """Handle key events globally - intercept arrow keys during selection modes."""
        # Inline permission prompt: while a permission decision is pending,
        # y/n/a resolve it and escape cancels. Intercepted before the Input
        # widget so the keystroke never lands in the prompt buffer.
        if getattr(self, "_permission_pending", False) and not getattr(
            self, "_awaiting_agent_question", False
        ):
            if event.key in ("y", "n", "a", "escape"):
                event.stop()
                mapping = {"y": "y", "n": "n", "a": "a", "escape": "n"}
                self._handle_permission_input(mapping[event.key])
                self.set_timer(0.05, self._ensure_input_focus)
                return

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
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_model_up()
                elif event.key == "down":
                    self.action_navigate_model_down()
                elif event.key == "enter":
                    self.action_select_highlighted_model()

            elif getattr(self, "_awaiting_codex_model", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_codex_model_up()
                elif event.key == "down":
                    self.action_navigate_codex_model_down()
                elif event.key == "enter":
                    self.action_select_highlighted_codex_model()

            elif getattr(self, "_awaiting_codex_effort", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_codex_effort_up()
                elif event.key == "down":
                    self.action_navigate_codex_effort_down()
                elif event.key == "enter":
                    self.action_select_highlighted_codex_effort()

            elif getattr(self, "_awaiting_byok_provider", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_provider_up()
                elif event.key == "down":
                    self.action_navigate_provider_down()
                elif event.key == "enter":
                    self.action_select_highlighted_provider()
                elif event.key == "r":
                    self.action_refresh_byok_models()

            elif getattr(self, "_awaiting_connect_type", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_connect_type_up()
                elif event.key == "down":
                    self.action_navigate_connect_type_down()
                elif event.key == "enter":
                    self.action_select_highlighted_connect_type()

            elif getattr(self, "_awaiting_runtime_selection", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_runtime_up()
                elif event.key == "down":
                    self.action_navigate_runtime_down()
                elif event.key == "enter":
                    self.action_select_highlighted_runtime()

            elif getattr(self, "_awaiting_session_resume", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_session_resume_up()
                elif event.key == "down":
                    self.action_navigate_session_resume_down()
                elif event.key == "enter":
                    self.action_select_highlighted_session_resume()

            elif getattr(self, "_awaiting_mode_selection", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_mode_up()
                elif event.key == "down":
                    self.action_navigate_mode_down()
                elif event.key == "enter":
                    self.action_select_highlighted_mode()

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
                    self.action_navigate_acp_model_up()
                elif event.key == "down":
                    self.action_navigate_acp_model_down()
                elif event.key == "enter":
                    self.action_select_highlighted_acp_model()

            if handled:
                # Ensure input stays focused after navigation
                self.set_timer(0.05, self._ensure_input_focus)
                return

    # Leader keys are now handled entirely through the popup widget system
    # This ensures zero latency when typing in the input field

    # Ctrl+T cycles through these thinking-log states in order.
    _THINKING_CYCLE = ("normal", "verbose", "off")


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
        if getattr(self, "_awaiting_codex_model", False):
            self._awaiting_codex_model = False
            log = self.query_one("#log", ConversationLog)
            log.add_info("Codex model selection cancelled. Use :codex model to try again.")
            return
        if getattr(self, "_awaiting_codex_effort", False):
            self._awaiting_codex_effort = False
            log = self.query_one("#log", ConversationLog)
            log.add_info("Codex effort selection cancelled. Use :codex effort to try again.")
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
        if getattr(self, "_awaiting_recommendation_selection", False):
            self._awaiting_recommendation_selection = False
            log = self.query_one("#log", ConversationLog)
            log.add_info("Recommendation selection cancelled.")
            return
        if getattr(self, "_awaiting_harness_wizard", False):
            self._awaiting_harness_wizard = False
            self._harness_wizard_state = None
            log = self.query_one("#log", ConversationLog)
            log.add_info("Harness wizard cancelled.")
            return

        # Then check if agent is running (ACP or BYOK)
        log = self.query_one("#log", ConversationLog)

        # Check for ACP operation first. A stale BYOK session may exist even
        # while an ACP agent is active, so cancellation must target ACP before
        # falling back to local/native mode.
        if self._acp_client is not None or self._agent_process is not None:
            self.action_cancel_agent()
            return

        # Check for BYOK/local operation
        if hasattr(self, "_pure_mode") and self._pure_mode and self._pure_mode._agent:
            # Cancel BYOK operation
            self._cancel_requested = True
            self._pure_mode.cancel()
            provider, model = self._active_local_provider_model()
            if provider:
                self._teardown_local_model_runtime(provider, model)
            self._stop_thinking()
            self._stop_stream_animation()
            self.is_busy = False
            log.add_info("🛑 Agent operation cancelled")
            return

        if self.is_busy:
            self.action_cancel_agent()
        else:
            # Idle: a double-Escape rewinds to the last message for editing.
            import time as _time

            now = _time.monotonic()
            last = getattr(self, "_last_idle_escape_at", 0.0)
            self._last_idle_escape_at = now
            input_empty = True
            try:
                input_empty = not self.query_one("#prompt-input", SelectionAwareInput).value.strip()
            except Exception:
                pass
            if input_empty and self._user_message_history(log) and (now - last) < 0.8:
                self._last_idle_escape_at = 0.0
                self._open_rewind_overlay(log)
            else:
                log.add_info("💡 Press Esc again to rewind the conversation  •  :exit to quit")


    def action_focus_input(self):
        """Focus the input box - always available via Ctrl+I or when needed."""
        self._ensure_input_focus()

    # ========================================================================
    # Enhanced Thinking Animation
    # ========================================================================


    # ========================================================================
    # Type-ahead message queue
    # ========================================================================


    # ========================================================================
    # Input Handling
    # ========================================================================


    # ========================================================================
    # Shell with Danger Detection
    # ========================================================================


    # ========================================================================
    # Command Handling
    # ========================================================================


    # Matches a trailing "@token" mention being typed, anywhere in the prompt.
    # The "@" must start the line or follow whitespace so emails/handles inside a
    # word do not trigger the file picker.
    _MENTION_QUERY_RE = re.compile(r"(?:^|\s)@([\w./\-]*)$")


    _IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}


    def on_paste(self, event) -> None:
        """Auto-attach when an image file path is pasted into the terminal."""
        text = (getattr(event, "text", "") or "").strip().strip("'\"")
        if text and "\n" not in text and self._is_image_path(text):
            try:
                log = self.query_one("#log", ConversationLog)
            except Exception:
                return
            path = Path(text).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            self._stage_image_attachment(path, log, source="pasted path")
            try:
                event.stop()
                event.prevent_default()
            except Exception:
                pass


    # Runtimes that are self-contained (own model + auth) and can be used in the
    # TUI without a separate :connect step.
    _SELF_CONTAINED_RUNTIMES = frozenset(
        {"codex-sdk", "claude-agent-sdk", "antigravity-sdk", "antigravity-cli"}
    )


    def action_clear_screen(self):
        log = self.query_one("#log", ConversationLog)
        log.clear()
        team_name = Path.cwd().name or "SuperQode"
        # Temporarily disable auto-scroll so we can scroll to top
        log.auto_scroll = False
        log.write(
            render_welcome(self.agents, team_name, width=self._welcome_width(log)),
            expand=True,
        )
        # Welcome is the only thing on screen again - allow responsive re-flow.
        self._welcome_active = True
        # Scroll to top so user sees the attractive header first
        log.scroll_home(animate=False)
        # Re-enable auto-scroll for future messages
        self.set_timer(0.2, lambda: setattr(log, "auto_scroll", True))
        # Ensure focus returns to input
        self.set_timer(0.1, self._ensure_input_focus)


    # ========================================================================
    # Model Query Interception
    # ========================================================================


    # ========================================================================
    # Message Handling
    # ========================================================================


    # ========================================================================
    # Permission Handling
    # ========================================================================


    # Phrases the agent loop emits purely as bookkeeping. In normal mode these
    # are folded into the live throbber instead of spamming the scrollback.
    _LOOP_BOOKKEEPING_MARKERS = (
        "calling model",
        "iteration",
        "processing request",
        "received response",
        "response complete",
        "reached maximum iterations",
    )


    # ── Calm-mode presentation ──────────────────────────────────────────────
    # In calm mode (anything but :thinking verbose) we don't dump raw reasoning
    # or full tool output. Instead a live throbber shows the current action and
    # each finished tool commits one tidy line; verbose restores full detail.
    _CALM_VERB_ICONS = {
        "read": "📄",
        "write": "📝",
        "edit": "✏️",
        "patch": "✏️",
        "create": "📝",
        "delete": "🗑️",
        "run": "⚡",
        "search": "🔍",
        "find": "🔍",
        "fetch": "🌐",
        "todo": "✅",
        "think": "💭",
    }


    # ========================================================================
    # Provider session commands
    # ========================================================================


    # =========================================================================
    # BYOK ENHANCED COMMANDS
    # =========================================================================


    # ========================================================================
    # Local Provider Commands
    # ========================================================================


    _LOCAL_ENGINE_NAMES = {
        "ollama": "Ollama",
        "lmstudio": "LM Studio",
        "mlx": "MLX",
        "ds4": "DS4",
        "llama.cpp": "llama.cpp",
    }


    # ========================================================================
    # HuggingFace Commands
    # ========================================================================


    # ========================================================================
    # Help & Utility
    # ========================================================================


    def action_quit(self) -> None:
        """Handle quit action (Ctrl+C) - clean up properly before exit."""
        # Get the log widget
        try:
            log = self.query_one("#log", ConversationLog)
            self._do_exit(log)
        except Exception:
            # Fallback: just clean up and exit immediately
            self._cleanup_on_exit()
            self.exit()

    # ========================================================================
    # Coding Agent Features: Approval, Diff, Plan, History, File Viewer
    # ========================================================================


# ============================================================================
# ENTRY POINT
# ============================================================================


def run_textual_app():
    SuperQodeApp().run()


if __name__ == "__main__":
    run_textual_app()
