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


class SuperQodeApp(CodexMixin, LocalModelsMixin, ModelCatalogMixin, FormattingMixin, PickerNavigationMixin, CompletionMixin, MiscActionsMixin, EventHandlerMixin, ConnectMixin, McpMixin, HuggingFaceMixin, SwitchboardMixin, FactoryMixin, SidebarMixin, App):
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

    @property
    def agents(self) -> List[AgentInfo]:
        """Lazy load agents list."""
        if self._agents is None:
            self._agents = self._load_agents()
        return self._agents


    def _load_agents(self) -> List[AgentInfo]:
        """Load agents list (called lazily)."""
        try:
            try:
                asyncio.get_running_loop()
                return self._fallback_agents()
            except RuntimeError:
                pass
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
            return self._fallback_agents()

    def _fallback_agents(self) -> List[AgentInfo]:
        """Basic agents used when async discovery cannot run synchronously."""
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

    def _set_prompt_border_title(self) -> None:
        """Give the prompt box a neutral code-focused title."""
        try:
            input_box = self.query_one("#input-box")
            input_box.border_title = "✎ Code"
        except Exception:
            pass

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

    def _load_custom_keybindings(self) -> None:
        """Apply user keybinding overrides from ~/.superqode/keybindings.json.

        Format: a JSON object of {"action_name": "key"} for any action in
        ``_REBINDABLE_ACTIONS`` (e.g. {"toggle_sidebar": "f2"}).
        """
        path = Path.home() / ".superqode" / "keybindings.json"
        try:
            if not path.exists():
                return
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        applied = 0
        for action, key in data.items():
            if action in self._REBINDABLE_ACTIONS and isinstance(key, str) and key.strip():
                try:
                    self.bind(key.strip(), action)
                    applied += 1
                except Exception:
                    pass
        if applied:
            try:
                self.query_one("#log", ConversationLog).add_info(
                    f"⌨ Applied {applied} custom keybinding(s) from {path}."
                )
            except Exception:
                pass

    def _build_palette_commands(self) -> list[PaletteCommand]:
        """Build the command palette from the real TUI command surface."""
        return [
            PaletteCommand(
                "start_coding",
                "Start Coding",
                "Connect an agent/model and begin implementation work",
                "🔌",
                ":connect",
                "connection",
            ),
            PaletteCommand(
                "resume",
                "Resume Session",
                "Continue a previous coding session by id or prefix",
                "↩",
                "/resume",
                "session",
            ),
            PaletteCommand(
                "harness_status",
                "Status",
                "Show provider, model, session, branch, and approval mode",
                "▣",
                ":status",
                "harness",
            ),
            PaletteCommand(
                "retry",
                "Retry Last Prompt",
                "Run the previous user prompt again",
                "↻",
                ":retry",
                "harness",
            ),
            PaletteCommand(
                "work_summary",
                "Last Work Summary",
                "Show tools, files, and commands from the last run",
                "▤",
                ":work",
                "harness",
            ),
            PaletteCommand(
                "doctor_current",
                "Doctor Current Provider",
                "Check active provider/model readiness",
                "🩺",
                ":doctor current",
                "connection",
            ),
            PaletteCommand(
                "recommend",
                "Recommend Model",
                "Pick a model for coding, review, testing, budget, or large context",
                "◆",
                ":recommend coding",
                "connection",
            ),
            PaletteCommand(
                "connect_byok",
                "Connect BYOK",
                "Pick a cloud provider and model",
                "⚡",
                ":connect byok",
                "connection",
            ),
            PaletteCommand(
                "connect_local",
                "Connect Local",
                "Pick Ollama, LM Studio, vLLM, or another local provider",
                "🦙",
                ":connect local",
                "connection",
            ),
            PaletteCommand(
                "acp_agents",
                "ACP Agents",
                "List available ACP coding agents",
                "🤖",
                ":acp list",
                "connection",
            ),
            PaletteCommand(
                "models",
                "Models",
                "Show or switch models for the current provider",
                "📊",
                ":models",
                "connection",
            ),
            PaletteCommand(
                "model_status",
                "Current Model",
                "Show active model, capabilities, and runtime settings",
                "◇",
                ":model",
                "connection",
            ),
            PaletteCommand(
                "health",
                "Provider Health",
                "Check configured provider connectivity",
                "🩺",
                ":health",
                "connection",
            ),
            PaletteCommand(
                "provider_guide",
                "Provider Setup",
                "Show setup, cost, context, and tool-support labels",
                "☁",
                ":providers",
                "connection",
            ),
            PaletteCommand(
                "review_diff",
                "Review Diff",
                "Inspect current workspace changes",
                "🧾",
                ":diff",
                "changes",
            ),
            PaletteCommand(
                "tools",
                "Tools",
                "Show active tool profile and available tools",
                "🧰",
                ":tools",
                "harness",
            ),
            PaletteCommand(
                "skills",
                "Skills",
                "List, inspect, create, or import local skills",
                "✦",
                ":skills",
                "harness",
            ),
            PaletteCommand(
                "recipes",
                "Recipes",
                "Run reusable local workflow recipes",
                "◇",
                ":recipes",
                "harness",
            ),
            PaletteCommand(
                "harness",
                "Harness",
                "Show or load the active HarnessSpec",
                "▣",
                ":harness",
                "harness",
            ),
            PaletteCommand(
                "harness_inspect",
                "Harness Inspect",
                "Summarize active HarnessSpec policy, tools, workflow, hooks, and checks",
                "▤",
                ":harness inspect",
                "harness",
            ),
            PaletteCommand(
                "harness_doctor",
                "Harness Doctor",
                "Check active HarnessSpec readiness and blockers",
                "🩺",
                ":harness doctor",
                "harness",
            ),
            PaletteCommand(
                "harness_graph",
                "Harness Graph",
                "Show planned workflow graph for the active harness",
                "◇",
                ":harness graph",
                "harness",
            ),
            PaletteCommand(
                "harness_runs",
                "Harness Runs",
                "List persisted harness runs",
                "▦",
                ":harness runs",
                "harness",
            ),
            PaletteCommand(
                "harness_wizard",
                "Harness Wizard",
                "Create a HarnessSpec from TUI-friendly wizard defaults",
                "✦",
                ":harness wizard ",
                "harness",
            ),
            PaletteCommand(
                "harness_replay",
                "Harness Replay",
                "Prefill replay plan command for a persisted run",
                "↻",
                ":harness replay ",
                "harness",
            ),
            PaletteCommand(
                "harness_fork",
                "Harness Fork",
                "Prefill fork command for a persisted run",
                "⑂",
                ":harness fork ",
                "harness",
            ),
            PaletteCommand(
                "harness_events",
                "Harness Events",
                "Prefill event timeline command for a persisted run",
                "≡",
                ":harness events ",
                "harness",
            ),
            PaletteCommand(
                "harness_evidence",
                "Harness Evidence",
                "Prefill evidence receipt command for a persisted run",
                "◫",
                ":harness evidence ",
                "harness",
            ),
            PaletteCommand(
                "mcp",
                "MCP Status",
                "Show configured MCP servers and connected tools",
                "🔗",
                ":mcp status",
                "harness",
            ),
            PaletteCommand(
                "connect",
                "Connect",
                "Choose ACP, BYOK, or local provider",
                "🔌",
                ":connect",
                "connection",
            ),
            PaletteCommand(
                "sessions",
                "Sessions",
                "Browse recent coding sessions",
                "📂",
                "/sessions",
                "session",
            ),
            PaletteCommand(
                "switchboard",
                "Session Switchboard",
                "Open durable graph, handoffs, approvals, and share tree actions",
                "▦",
                ":switchboard",
                "session",
            ),
            PaletteCommand(
                "factory",
                "Software Factory",
                "Switch models, harnesses, and routes without locking work to one vendor",
                "▧",
                ":factory",
                "session",
            ),
            PaletteCommand(
                "session_current",
                "Current Session",
                "Show active session status",
                "▣",
                ":session current",
                "session",
            ),
            PaletteCommand(
                "fork", "Fork Session", "Branch the current session", "⑂", "/fork", "session"
            ),
            PaletteCommand(
                "compact",
                "Compact Context",
                "Compress conversation context where supported",
                "🗜",
                "/compact",
                "session",
            ),
            PaletteCommand(
                "context",
                "Context",
                "Show current mode, role, provider, model, and cwd",
                "📋",
                ":context",
                "harness",
            ),
            PaletteCommand(
                "attach",
                "Attach Reference",
                "Insert a file path or URL reference into the next prompt",
                "@",
                ":attach ",
                "view",
            ),
            PaletteCommand(
                "prompt_file",
                "Load Prompt File",
                "Load prompt text from a local file into the input",
                "¶",
                ":prompt ",
                "view",
            ),
            PaletteCommand("diff", "Diff", "Inspect file changes", "🧾", ":diff", "changes"),
            PaletteCommand(
                "approve", "Approve Changes", "Approve pending work", "✅", ":approve", "changes"
            ),
            PaletteCommand(
                "reject", "Reject Changes", "Reject pending work", "⛔", ":reject", "changes"
            ),
            PaletteCommand("undo", "Undo", "Undo the last tracked change", "↶", ":undo", "changes"),
            PaletteCommand(
                "sandbox_status",
                "Sandbox Status",
                "Show sandbox readiness",
                "▣",
                ":sandbox",
                "advanced",
            ),
            PaletteCommand(
                "plugins",
                "Plugins",
                "Show discovered plugin manifests",
                "◇",
                ":plugins",
                "advanced",
            ),
            PaletteCommand(
                "benchmark",
                "Benchmark Harness",
                "Show benchmark targets and task-file usage",
                "▤",
                ":benchmark",
                "advanced",
            ),
            PaletteCommand(
                "sidebar",
                "Toggle Sidebar",
                "Show or hide files/context panels",
                "▣",
                "Ctrl+B",
                "view",
            ),
            PaletteCommand(
                "files", "Files", "List files in the current directory", "📁", ":files", "view"
            ),
            PaletteCommand("find", "Find File", "Search for files by name", "🔍", ":find", "view"),
            PaletteCommand(
                "search",
                "Search Contents",
                "Search text in the current workspace",
                "⌕",
                ":search",
                "view",
            ),
            PaletteCommand(
                "mode",
                "Approval Mode",
                "Show or change tool approval mode",
                "🔐",
                ":mode",
                "safety",
            ),
            PaletteCommand(
                "context",
                "Context Window",
                "Show/pin the detected context window + compaction budgets",
                "🪟",
                ":context",
                "harness",
            ),
            PaletteCommand(
                "workspace",
                "Search Workspace",
                "Register repos for fast multi-repo (--all-repos) search",
                "📁",
                ":workspace list",
                "harness",
            ),
            PaletteCommand(
                "thinking",
                "Thinking Detail",
                "Cycle thinking-log detail (Normal / Verbose / Off)",
                "🔎",
                ":thinking",
                "system",
            ),
            PaletteCommand("help", "Help", "Show command reference", "?", ":help", "system"),
            PaletteCommand(
                "clear", "Clear", "Clear the conversation view", "⌫", "Ctrl+L", "system"
            ),
            PaletteCommand("quit", "Quit", "Exit SuperQode", "✕", "Ctrl+C", "system"),
        ]

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


    def _refresh_harness_panel(self) -> None:
        """Refresh the harness workbench sidebar, if mounted."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            harness_panel = sidebar.get_harness_panel()
            if harness_panel:
                harness_panel.refresh_summary()
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
        team_name = Path.cwd().name or "SuperQode"
        self._call_ui(self._show_welcome, team_name)

    def _welcome_width(self, log) -> Optional[int]:
        """Usable inner width of the log, used to lay the welcome out responsively."""
        try:
            w = log.scrollable_content_region.width
            return w if w and w > 0 else None
        except Exception:
            return None

    def _show_welcome(self, team_name: str):
        log = self.query_one("#log", ConversationLog)
        # Temporarily disable auto-scroll so we can scroll to top
        log.auto_scroll = False
        # expand=True makes the renderable fill the full log width so the
        # centered welcome blocks sit in the middle of the screen, not the left.
        log.write(
            render_welcome(self.agents, team_name, width=self._welcome_width(log)),
            expand=True,
        )
        # Mark that the log currently shows only the welcome, so resizes can
        # re-flow it responsively until the user starts interacting.
        self._welcome_active = True
        self._maybe_show_onboarding(log)
        # Scroll to top so user sees the attractive header first
        log.scroll_home(animate=False)
        # Re-enable auto-scroll for future messages
        self.set_timer(0.2, lambda: setattr(log, "auto_scroll", True))

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

    def _rerender_welcome(self) -> None:
        if not getattr(self, "_welcome_active", False):
            return
        try:
            log = self.query_one("#log", ConversationLog)
        except Exception:
            return
        team_name = Path.cwd().name or "SuperQode"
        log.auto_scroll = False
        log.clear()
        log.write(
            render_welcome(self.agents, team_name, width=self._welcome_width(log)),
            expand=True,
        )
        log.scroll_home(animate=False)
        self.set_timer(0.2, lambda: setattr(log, "auto_scroll", True))

    @staticmethod
    def _onboarding_marker() -> Path:
        return Path.home() / ".superqode" / ".onboarded"

    def _maybe_show_onboarding(self, log: ConversationLog) -> None:
        """Show a one-time getting-started card on the very first launch."""
        marker = self._onboarding_marker()
        try:
            if marker.exists():
                return
        except Exception:
            return

        t = Text()
        t.append("\n  ╭─ ", style=THEME["purple"])
        t.append("Welcome to SuperQode 👋", style=f"bold {THEME['purple']}")
        t.append("  First time? Here's the 30-second start.\n", style=THEME["muted"])
        t.append("  │\n", style=THEME["purple"])
        t.append("  │  Quick Start\n", style=f"bold {THEME['success']}")
        t.append("  │\n", style=THEME["purple"])
        t.append("  │  1. ", style=f"bold {THEME['cyan']}")
        t.append("Connect  ", style=f"bold {THEME['text']}")
        t.append(":connect", style=f"bold {THEME['success']}")
        t.append("       pick ACP, BYOK, or local provider\n", style=THEME["muted"])
        t.append("  │  2. ", style=f"bold {THEME['cyan']}")
        t.append("Pick     ", style=f"bold {THEME['text']}")
        t.append("↑/↓ then Enter", style=f"bold {THEME['success']}")
        t.append("  or type a number\n", style=THEME["muted"])
        t.append("  │  3. ", style=f"bold {THEME['cyan']}")
        t.append("Start    ", style=f"bold {THEME['text']}")
        t.append("just type", style=f"bold {THEME['success']}")
        t.append("       describe what to build\n", style=THEME["muted"])
        t.append("  │\n", style=THEME["purple"])
        t.append("  │  Or skip straight in:\n", style=THEME["muted"])
        t.append("  │  ", style=THEME["muted"])
        t.append(":recommend coding", style=f"bold {THEME['success']}")
        t.append("    get model suggestions\n", style=THEME["muted"])
        t.append("  │  ", style=THEME["muted"])
        t.append(":acp list", style=f"bold {THEME['purple']}")
        t.append("             browse all coding agents\n", style=THEME["muted"])
        t.append("  │  ", style=THEME["muted"])
        t.append(":help", style=f"bold {THEME['cyan']}")
        t.append("                 full command reference\n", style=THEME["muted"])
        t.append("  │\n", style=THEME["purple"])
        t.append("  │  ", style=THEME["dim"])
        t.append("Tips: ", style=THEME["muted"])
        t.append("@file", style=THEME["cyan"])
        t.append(" to reference  •  ", style=THEME["dim"])
        t.append("Ctrl+K", style=THEME["cyan"])
        t.append(" for palettes  •  ", style=THEME["dim"])
        t.append("Ctrl+G", style=THEME["cyan"])
        t.append(" to stash\n", style=THEME["dim"])
        t.append("  ╰─ This welcome card won't show again - ", style=THEME["purple"])
        t.append(":help", style=f"bold {THEME['cyan']}")
        t.append(" anytime  •  ", style=THEME["purple"])
        t.append("Ctrl+L", style=f"bold {THEME['cyan']}")
        t.append(" to redraw.\n", style=THEME["purple"])
        log.write(t)

        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("1", encoding="utf-8")
        except Exception:
            pass

    # ========================================================================
    # Sidebar Toggle & File Selection
    # ========================================================================


    def _call_ui(self, func, *args):
        """Run a UI callback from either worker threads or the app thread."""
        try:
            return self.call_from_thread(func, *args)
        except RuntimeError as e:
            message = str(e).lower()
            if "different thread" in message or "app thread" in message:
                return func(*args)
            raise

    def _show_error_card(
        self,
        log: ConversationLog,
        title: str,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        hint: str = "",
    ):
        """Render a compact, copyable error with recovery actions."""
        t = Text()
        t.append("\n  ✕ ", style=f"bold {THEME['error']}")
        t.append(f"{title}\n\n", style=f"bold {THEME['error']}")
        if provider or model:
            t.append("  Target      ", style=THEME["muted"])
            t.append(f"{provider or '-'}", style=THEME["cyan"])
            if model:
                t.append("/", style=THEME["dim"])
                t.append(model, style=THEME["cyan"])
            t.append("\n")
        t.append("  Cause       ", style=THEME["muted"])
        t.append(f"{message}\n", style=THEME["text"])
        if hint:
            t.append("  Hint        ", style=THEME["muted"])
            t.append(f"{hint}\n", style=THEME["warning"])
        t.append("\n  Actions     ", style=THEME["muted"])
        t.append(":retry", style=THEME["cyan"])
        t.append("  ", style=THEME["muted"])
        t.append(":copy error", style=THEME["cyan"])
        t.append("  ", style=THEME["muted"])
        t.append(":doctor current", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        log.write(t)
        log._last_error = f"{title}: {message}"


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

    def _conversation_log(self) -> ConversationLog | None:
        try:
            return self.query_one("#log", ConversationLog)
        except Exception:
            return None

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


    @staticmethod
    def _os_clipboard_copy(text: str) -> bool:
        """Push ``text`` to the real OS clipboard via the platform CLI.

        Uses pbcopy (macOS), xclip/xsel (Linux), or clip (Windows) — the same
        proven path as ``:copy``. Returns True only if a backend accepted it.
        """
        import subprocess
        import sys

        if sys.platform == "darwin":
            candidates = [["pbcopy"]]
        elif sys.platform.startswith("linux"):
            candidates = [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
        elif sys.platform.startswith("win"):
            candidates = [["clip"]]
        else:
            candidates = []

        data = text.encode("utf-8")
        for cmd in candidates:
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                proc.communicate(data)
                if proc.returncode == 0:
                    return True
            except FileNotFoundError:
                continue
            except Exception:
                continue
        return False

    def _copy_text_to_clipboard(self, text: str) -> bool:
        """Copy ``text`` to the clipboard as reliably as possible.

        Tries the real OS clipboard first (pbcopy/xclip/xsel/clip), which is what
        makes mouse-drag copy actually work locally, then always also emits
        Textual's OSC 52 ``copy_to_clipboard`` so it still works over SSH/remote
        sessions where the local CLI can't reach the user's clipboard. Returns
        True if at least one path succeeded.
        """
        if not text:
            return False
        copied = self._os_clipboard_copy(text)
        # Always also emit OSC 52 — harmless when the CLI worked, and the only
        # path that reaches the *local* clipboard from a remote/SSH session.
        try:
            self.copy_to_clipboard(text)
            copied = True
        except Exception:
            pass
        return copied


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

    def _current_thinking_state(self) -> str:
        if not self.show_thinking_logs:
            return "off"
        return "verbose" if self.thinking_verbosity == "verbose" else "normal"

    def _apply_thinking_state(self, state: str) -> None:
        """Set the reactive flags for a thinking state ('normal'|'verbose'|'off')."""
        if state == "off":
            self.show_thinking_logs = False
        else:
            self.show_thinking_logs = True
            self.thinking_verbosity = "verbose" if state == "verbose" else "normal"
        # Mirror onto the current TUI logger if one exists.
        if getattr(self, "_current_tui_logger", None):
            self._current_tui_logger.logger.config.show_thinking = self.show_thinking_logs

    def action_toggle_thinking(self):
        """Cycle thinking-log detail: Normal → Verbose → Off."""
        current = self._current_thinking_state()
        nxt = self._THINKING_CYCLE[
            (self._THINKING_CYCLE.index(current) + 1) % len(self._THINKING_CYCLE)
        ]
        self._apply_thinking_state(nxt)
        log = self.query_one("#log", ConversationLog)
        blurbs = {
            "normal": "Thinking: NORMAL — iterations fold into a live status, reasoning is trimmed",
            "verbose": "Thinking: VERBOSE — full per-iteration reasoning and loop logs",
            "off": "Thinking: OFF — compact stream view, only tool calls and the answer",
        }
        log.add_info(blurbs[nxt])


    def _create_checkpoint_before_agent(self, operation_name: str = "Agent operation"):
        """Create a checkpoint before an agent operation."""
        if hasattr(self, "_undo_manager") and self._undo_manager:
            self._undo_manager.create_checkpoint(f"Before: {operation_name}")


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


    @staticmethod
    def _runtime_install_message(runtime_name: str, install_hint: str | None) -> str:
        from superqode.providers.env_introspect import environment_info

        env = environment_info()
        command = install_hint or "uv tool install ..."
        return (
            f"Runtime '{runtime_name}' is not installed.\n"
            f"SuperQode is running from: {env.label} ({env.python})\n"
            f"This command modifies: {env.target}\n"
            f"Run: {command}"
        )


    def _queue_selection_digit(self, digit: str) -> None:
        """Queue a digit for multi-digit selection in provider/model pickers."""
        buf = getattr(self, "_selection_digit_buffer", "")
        buf += digit
        self._selection_digit_buffer = buf

        # Mirror buffer in prompt input for visibility
        try:
            prompt_input = self.query_one("#prompt-input", SelectionAwareInput)
            prompt_input.value = buf
            prompt_input.cursor_position = len(buf)
        except Exception:
            pass


    def _apply_selection_buffer(self) -> None:
        """Apply buffered numeric selection to the current picker."""
        buf = getattr(self, "_selection_digit_buffer", "")
        if not buf:
            return

        # Clear buffer and prompt
        self._selection_digit_buffer = ""
        self._selection_digit_timer = None
        try:
            prompt_input = self.query_one("#prompt-input", SelectionAwareInput)
            prompt_input.value = ""
            prompt_input.cursor_position = 0
        except Exception:
            pass

        log = self.query_one("#log", ConversationLog)

        if getattr(self, "_awaiting_acp_agent_selection", False):
            self._handle_acp_agent_selection(buf, log)
            return
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
        if getattr(self, "_awaiting_codex_model", False):
            self._handle_codex_model_selection(buf, log)
            return
        if getattr(self, "_awaiting_codex_effort", False):
            self._handle_codex_effort_selection(buf, log)
            return

        # Fallback to universal selection for other modes
        try:
            self._select_by_number_universal(int(buf))
        except Exception:
            pass


    @staticmethod
    def _scroll_to_rendered_selected_block(log: ConversationLog) -> bool:
        """Bring the selected row and its supporting content into view."""
        try:
            selected_y = next(
                index
                for index, line in enumerate(log.lines)
                if "SELECTED" in line.text or "▶" in line.text
            )
        except (AttributeError, StopIteration):
            return False

        try:
            # Follow-mode is disabled only around this managed scroll (a write
            # with auto_scroll on would yank to the footer). It is restored in
            # the finally so later feedback writes — errors, setup guidance —
            # scroll into view instead of landing invisibly below the picker.
            # Nothing writes between here and the next picker render, which
            # disables follow-mode itself before writing.
            log.auto_scroll = False

            from textual.geometry import Region

            visible_height = max(
                4,
                int(
                    getattr(getattr(log, "scrollable_content_region", None), "height", 0)
                    or getattr(getattr(log, "size", None), "height", 18)
                    or 18
                ),
            )
            block_height = min(visible_height, 5)
            log.scroll_to_region(
                Region(0, selected_y, 1, block_height),
                animate=False,
                x_axis=False,
                y_axis=True,
            )
            return True
        except Exception:
            return False
        finally:
            log.auto_scroll = True


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
            self.query_one("#prompt-input", SelectionAwareInput).focus()
        except Exception:
            pass

        # Hide streaming thinking indicator
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = False
            thinking_indicator.status = ""
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
        # Reset per-turn thinking state (live status step + reasoning rate limiter).
        self._thinking_step = 0
        self._last_thinking_flush = 0.0
        self._calm_actions = 0

        # Show streaming thinking indicator with changing text
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = True
            # Start each turn with the whimsical phrases; loop bookkeeping in
            # normal mode will swap in a steady "Working… (step N)" status.
            thinking_indicator.status = ""
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

        # Calm mode: commit the end-of-turn action roll-up before tearing down.
        if self._is_calm_output() and getattr(self, "_calm_actions", 0) > 0:
            try:
                self._show_calm_summary(self.query_one("#log", ConversationLog))
            except Exception:
                pass

        # Hide streaming thinking indicator
        try:
            thinking_indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            thinking_indicator.is_active = False
            thinking_indicator.status = ""
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
            self.query_one("#prompt-input", SelectionAwareInput).focus()
        except Exception:
            pass

        # Only show done message if requested (not during streaming)
        if show_done:
            elapsed = time.time() - self._thinking_start
            self.query_one("#log", ConversationLog).add_success(f"Done in {elapsed:.1f}s ✨")


    def _update_terminal_title(self, task: str = "") -> None:
        """Reflect the active model and current task in the terminal/tab title."""
        agent = getattr(self, "current_agent", "") or getattr(self, "current_model", "") or ""
        sub_parts = []
        if agent:
            sub_parts.append(str(agent))
        if task:
            compact = " ".join(str(task).split())
            sub_parts.append(compact[:40] + ("…" if len(compact) > 40 else ""))
        try:
            self.title = "SuperQode"
            # Textual emits the OS terminal-title escape from title/sub_title.
            self.sub_title = " · ".join(sub_parts)
        except Exception:
            pass

    def _resolve_context_window(self, provider: str, model: str) -> int:
        """Best-effort lookup of a model's context window for the usage meter."""
        if not model:
            return 0
        try:
            from superqode.providers.models import get_model_info

            info = get_model_info(provider, model)
            if info and getattr(info, "context_window", 0):
                return int(info.context_window)
        except Exception:
            pass
        return 0

    # ========================================================================
    # Type-ahead message queue
    # ========================================================================

    def _enqueue_message(self, text: str) -> None:
        """Deliver a message typed while the agent works.

        Builtin (local/BYOK) runs accept live steering: the message is
        injected between the agent's tool calls and shapes the *current* run.
        Anything else (ACP/codex connections, selection flows) falls back to
        the type-ahead queue that sends when the agent is free.
        """
        pure = getattr(self, "_pure_mode", None)
        if (
            pure is not None
            and not self._in_selection_mode()
            and not getattr(self, "_awaiting_agent_question", False)
        ):
            try:
                if pure.steer(text):
                    try:
                        self.query_one("#prompt-input", SelectionAwareInput).value = ""
                    except Exception:
                        pass
                    try:
                        log = self.query_one("#log", ConversationLog)
                        preview = " ".join(str(text).split())
                        if len(preview) > 70:
                            preview = preview[:67].rstrip() + "..."
                        log.add_info(f"↪ steering the current run: {preview}")
                    except Exception:
                        pass
                    return
            except Exception:
                pass

        if not hasattr(self, "_typeahead_queue"):
            self._typeahead_queue = []
        self._typeahead_queue.append(text)
        try:
            self.query_one("#prompt-input", SelectionAwareInput).value = ""
        except Exception:
            pass
        self._render_queued_input()


    def _clear_message_queue(self, log: ConversationLog | None = None) -> None:
        self._typeahead_queue = []
        self._render_queued_input()
        if log is not None:
            log.add_info("Cleared the queued messages.")

    def _drain_message_queue(self) -> None:
        """Send the next queued message if the agent is idle."""
        queue = getattr(self, "_typeahead_queue", [])
        if not queue or getattr(self, "is_busy", False):
            return
        # Don't interrupt selection/question flows.
        if getattr(self, "_awaiting_agent_question", False) or self._in_selection_mode():
            return
        text = queue.pop(0)
        self._render_queued_input()
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            input_widget.value = text
            self.post_message(Input.Submitted(input_widget, text))
        except Exception:
            pass

    def _in_selection_mode(self) -> bool:
        return any(
            getattr(self, flag, False)
            for flag in (
                "_awaiting_acp_agent_selection",
                "_awaiting_byok_provider",
                "_awaiting_byok_model",
                "_awaiting_connect_type",
                "_awaiting_local_provider",
                "_awaiting_local_model",
                "_awaiting_local_connect_start",
                "_awaiting_local_server_start",
                "_awaiting_local_dep_install",
                "_awaiting_model_selection",
                "_awaiting_recommendation_selection",
                "_awaiting_session_resume",
                "_awaiting_mode_selection",
            )
        )

    def watch_is_busy(self, old: bool, new: bool) -> None:
        """When the agent becomes idle, drain any queued type-ahead messages."""
        if old and not new and getattr(self, "_typeahead_queue", []):
            # Small delay lets the completion render settle before the next turn.
            self.set_timer(0.2, self._drain_message_queue)

    # ========================================================================
    # Input Handling
    # ========================================================================


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

            self._call_ui(show_warning)

        self._call_ui(lambda: setattr(self, "is_busy", True))

        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, cwd=os.getcwd(), timeout=60
            )
            output = (result.stdout + result.stderr).strip()
            ok = result.returncode == 0
            self._call_ui(log.add_shell, cmd, output, ok)

            # Record in history
            self._history_manager.append_sync(f">{cmd}", success=ok)

        except subprocess.TimeoutExpired:
            self._call_ui(log.add_shell, cmd, "⏰ Timed out", False)
        except Exception as e:
            self._call_ui(log.add_error, str(e))
        finally:
            self._call_ui(lambda: setattr(self, "is_busy", False))

    # ========================================================================
    # Command Handling
    # ========================================================================

    @staticmethod
    def _env_flag(name: str) -> bool:
        value = os.environ.get(name, "").strip().lower()
        return value in {"1", "true", "yes", "on"}

    def _vim_enabled(self) -> bool:
        return bool(getattr(self, "_vim_experience_enabled", False))

    def _record_ex_command(self, cmd: str, command_name: str) -> None:
        if not cmd.startswith(":"):
            return
        if command_name in {"vim", "set"}:
            return
        normalized = ":" + cmd[1:].strip()
        if normalized in {":", ":history"}:
            return
        self._last_ex_command = normalized

    def _vim_cmd(self, args: str, log: ConversationLog) -> None:
        arg = (args or "").strip().lower()
        if arg in {"on", "1", "true", "yes"}:
            self._vim_experience_enabled = True
            log.add_success("Vim mode enabled. Use q: for command history and @: to repeat.")
            return
        if arg in {"off", "0", "false", "no"}:
            self._vim_experience_enabled = False
            log.add_success("Vim mode disabled.")
            return
        if arg in {"", "status"}:
            state = "on" if self._vim_enabled() else "off"
            t = Text()
            t.append("\n  Vim Mode\n\n", style=f"bold {THEME['purple']}")
            t.append("  Status: ", style=THEME["muted"])
            t.append(
                f"{state}\n",
                style=f"bold {THEME['success'] if self._vim_enabled() else THEME['muted']}",
            )
            t.append("  Toggle: ", style=THEME["muted"])
            t.append(":vim on", style=THEME["cyan"])
            t.append(" / ", style=THEME["muted"])
            t.append(":vim off\n", style=THEME["cyan"])
            t.append("  History: ", style=THEME["muted"])
            t.append("q:", style=THEME["cyan"])
            t.append("  Repeat: ", style=THEME["muted"])
            t.append("@:\n", style=THEME["cyan"])
            t.append("  Aliases: ", style=THEME["muted"])
            t.append(":w, :e <file>, :ls, :grep <term>\n", style=THEME["cyan"])
            self._show_command_output(log, t)
            return
        log.add_info("Usage: :vim [on|off|status]")

    def _set_cmd(self, args: str, log: ConversationLog) -> None:
        arg = (args or "").strip().lower()
        if arg in {"vim", "vim on"}:
            self._vim_cmd("on", log)
            return
        if arg in {"novim", "no-vim", "vim off"}:
            self._vim_cmd("off", log)
            return
        if arg in {"", "all"}:
            self._vim_cmd("status", log)
            return
        log.add_info("Usage: :set vim | :set novim")

    def _vim_command_history(self, log: ConversationLog) -> None:
        entries = [
            entry
            for entry in self._history_manager.get_recent(50)
            if str(getattr(entry, "input", "")).startswith(":")
        ][-20:]
        if not entries:
            log.add_info("No Ex command history yet.")
            return

        t = Text()
        t.append("\n  q: Command History\n\n", style=f"bold {THEME['purple']}")
        for index, entry in enumerate(entries, 1):
            t.append(f"  {index:>2}  ", style=THEME["muted"])
            t.append(str(entry.input), style=THEME["text"])
            t.append("\n")
        t.append("\n  Repeat the latest with ", style=THEME["muted"])
        t.append("@:", style=THEME["cyan"])
        t.append(".\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _repeat_last_ex_command(self, log: ConversationLog) -> None:
        command = getattr(self, "_last_ex_command", "")
        if not command:
            log.add_info("No Ex command to repeat yet.")
            return
        log.add_info(f"Repeating {command}")
        self._handle_command(command, log)

    def _try_vim_search_input(self, text: str, log: ConversationLog) -> bool:
        if text in {"n", "N"}:
            self._vim_search_next(log, reverse=(text == "N"))
            return True
        if text.startswith("?") and len(text) > 1:
            self._vim_search(log, text[1:].strip(), reverse=True)
            return True
        if text.startswith("/") and len(text) > 1 and not self._is_known_slash_input(text):
            self._vim_search(log, text[1:].strip(), reverse=False)
            return True
        return False

    @staticmethod
    def _is_known_slash_input(text: str) -> bool:
        candidate = text.strip().lower()
        if not candidate.startswith("/"):
            return False
        try:
            from superqode.widgets.slash_complete import DEFAULT_COMMANDS

            known = {command.command.lower() for command in DEFAULT_COMMANDS}
        except Exception:
            known = {command.lower() for command in COMMANDS if command.startswith("/")}
        first_word = candidate.split(maxsplit=1)[0]
        return candidate in known or first_word in known

    def _vim_search(self, log: ConversationLog, query: str, *, reverse: bool = False) -> None:
        query = (query or "").strip()
        if not query:
            self._set_vim_search_highlight(log, "")
            self._vim_search_feedback(log, "Usage: /pattern or ?pattern")
            return

        messages = list(getattr(log, "_messages", []))
        lowered = query.lower()
        matches = [
            index
            for index, (_role, content, _agent) in enumerate(messages)
            if lowered in str(content).lower()
        ]
        self._vim_search_query = query
        self._vim_search_matches = matches
        self._vim_search_reverse = reverse

        if not matches:
            self._vim_search_index = -1
            self._set_vim_search_highlight(log, "")
            self._vim_search_feedback(log, f"No matches for {query!r}")
            return

        self._set_vim_search_highlight(log, query)
        self._vim_search_index = len(matches) - 1 if reverse else 0
        self._scroll_to_vim_search_match(log)

    def _vim_search_next(self, log: ConversationLog, *, reverse: bool = False) -> None:
        matches = getattr(self, "_vim_search_matches", [])
        if not matches:
            self._vim_search_feedback(log, "No previous Vim search. Use /pattern or ?pattern.")
            return

        direction = -1 if reverse else 1
        self._vim_search_index = (self._vim_search_index + direction) % len(matches)
        self._scroll_to_vim_search_match(log)

    def _scroll_to_vim_search_match(self, log: ConversationLog) -> None:
        matches = getattr(self, "_vim_search_matches", [])
        if not matches or self._vim_search_index < 0:
            return
        message_index = matches[self._vim_search_index]
        try:
            log.auto_scroll = False
            messages = list(getattr(log, "_messages", []))
            target_y = 0
            for _role, content, _agent in messages[:message_index]:
                target_y += max(2, len(str(content).splitlines()) + 2)
            visible_height = max(6, int(getattr(getattr(log, "size", None), "height", 18) or 18))
            log.scroll_to(y=max(0, target_y - max(1, visible_height // 3)), animate=False)
        except Exception:
            pass

        query = getattr(self, "_vim_search_query", "")
        self._set_vim_search_highlight(log, query)
        self._vim_search_feedback(
            log,
            f"Match {self._vim_search_index + 1}/{len(matches)} for {query!r}. "
            "Use n/N to navigate.",
        )

    def _set_vim_search_highlight(self, log: ConversationLog, query: str) -> None:
        setter = getattr(log, "set_search_highlight", None)
        if callable(setter):
            setter(query)

    def _vim_search_feedback(self, log: ConversationLog, message: str) -> None:
        try:
            self.notify(message, timeout=2)
            return
        except Exception:
            pass
        try:
            log.add_info(message)
        except Exception:
            pass

    def _try_acp_slash_command(self, name: str, args: str, log: ConversationLog) -> bool:
        """Dispatch a slash command through the ACP local registry if registered.

        Returns True if the registry handled it (so the caller should stop
        processing); False if the command isn't registered (fall through to
        the rest of ``_handle_command``).

        Output is written to the conversation log. Async handlers run on the
        dedicated ACP loop runner when present so we don't block the UI loop.
        """
        from superqode.acp.slash import (
            SlashRegistry,
            UnknownSlashCommandError,
            builtin_registry,
        )

        client = self._acp_client
        if client is None:
            return False

        registry: SlashRegistry
        if self._acp_slash_registry is None:
            self._acp_slash_registry = builtin_registry()
        registry = self._acp_slash_registry

        if not registry.has(name):
            return False

        # Reconstruct the input line the registry expects.
        line = f"/{name}" if not args else f"/{name} {args}"

        async def _run() -> str:
            try:
                return await registry.dispatch(client, line)
            except UnknownSlashCommandError:
                # Shouldn't happen given the has() guard, but stay defensive.
                return f"unknown local slash command: {name}"
            except Exception as exc:  # noqa: BLE001 - surface to log, don't crash UI
                return f"slash command {name!r} failed: {exc}"

        try:
            if self._acp_loop_runner is not None:
                output = self._acp_loop_runner.run(_run(), timeout=15.0)
            else:
                import asyncio as _asyncio

                output = _asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"slash command {name!r} dispatch error: {exc}")
            return True

        if output:
            log.write(output)
        return True

    def _handle_command(self, cmd: str, log: ConversationLog):
        # Command aliases for Vim-friendly shortcuts. The single-letter
        # :h/:s/:i shortcuts were retired in favour of the full commands.
        alias_map = {
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

        self._record_ex_command(cmd, c)

        # ACP local slash commands win when an agent is connected. They cover
        # introspection commands (:status, :model, :session, :history, etc.)
        # for the connected agent so the agent's own slash surface isn't the
        # only way to query it. Unknown commands fall through to the normal
        # elif chain below.
        if self._acp_client is not None and self._try_acp_slash_command(c, args, log):
            return

        if c == "help":
            self._show_help(log)
        elif c == "vim":
            self._vim_cmd(args, log)
        elif c == "set":
            self._set_cmd(args, log)
        elif c == "clear":
            self.action_clear_screen()
        elif c in ("exit", "quit", "q"):
            self._do_exit(log)
        elif c == "init":
            self._init_config(args, log)
        elif c == "config":
            self._run_cli_group("config", args or "show", log, "Config command")
        elif c == "auth":
            self._run_cli_group("auth", args or "info", log, "Auth command")
        elif c == "serve":
            self._run_cli_group("serve", args or "status", log, "Serve command")
        elif c == "daemon":
            self._run_cli_group("daemon", args, log, "Daemon command")
        elif c == "profiles":
            self._run_cli_group("profiles", args or "list", log, "Profiles command")
        elif c in ("home", "disconnect"):
            self._go_home(log)
        elif c == "acp":
            self._acp_cmd(args, log)
        elif c in ("agents", "agent"):
            self._agents_cmd(args, log)
        elif c == "a2a":
            self.run_worker(self._a2a_cmd(args, log))
        elif c == "runtime":
            self._runtime_cmd(args, log)
        elif c == "codex":
            self._codex_cmd(args, log)
        elif c == "claude":
            self._claude_cmd(args, log)
        elif c in ("grok", "xai-grok"):
            self._grok_cmd(args, log)
        elif c in ("antigravity", "agy"):
            self._antigravity_cmd(args, log)
        elif c == "approve":
            self.run_worker(self._approval_cmd("approve", args, log))
        elif c == "reject":
            self.run_worker(self._approval_cmd("reject", args, log))
        elif c == "mcp":
            self.run_worker(self._mcp_cmd(args, log))
        elif c == "chat":
            self._chat_cmd(args, log)
        elif c == "build":
            self._build_cmd(args, log)
        elif c == "mode":
            self._mode_cmd(args, log)
        elif c == "hub":
            self._hub_cmd(args, log)
        elif c == "context":
            self._show_context(log)
        elif c == "status":
            self._show_harness_status(log)
        elif c == "harness":
            self._harness_cmd(args, log)
        elif c in ("workflow", "workflows"):
            self.run_worker(self._workflow_cmd(args, log))
        elif c == "retry":
            self._retry_last_message(log)
        elif c in ("doctor", "doctor-current"):
            self._doctor_cmd(args, log)
        elif c in ("session", "sessions-current"):
            self._session_cmd(args, log)
        elif c in ("work", "summary"):
            self._work_cmd(args, log)
        elif c == "files":
            self._show_files(log)
        elif c == "find":
            self._find_files(args, log)
        elif c in ("sidebar", "sodebar"):
            self.action_toggle_sidebar()
        elif c == "toggle_thinking":
            # Allow users to type :toggle_thinking to toggle logs
            self.action_toggle_thinking()
        # Copy/Open/Edit commands
        elif c == "copy":
            self._handle_copy(log, args)
        elif c == "open":
            self._handle_open(log)
        elif c == "select":
            self._handle_select(log, args)
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
        elif c in ("models", "catalog"):
            self._models_cmd(args, log)
        elif c in ("permissions", "policy"):
            self._handle_permissions(log)
        elif c == "diff":
            self._handle_diff(args, log)
        elif c == "plan":
            self._handle_plan(args, log)
        elif c == "undo":
            self._handle_undo(log)
        elif c == "history":
            self._handle_history(args, log)
        elif c == "transcript":
            self._handle_select(log, "transcript")
        elif c == "timeline":
            self._handle_timeline(log)
        elif c == "rewind":
            self._handle_rewind(args, log)
        elif c == "tree":
            self._show_session_tree(log)
        elif c == "share":
            self._handle_share(args, log)
        elif c == "trust":
            self._handle_trust(args, log)
        elif c == "export":
            self._handle_export(args, log)
        elif c == "w":
            self._handle_export(args, log)
        elif c == "sandbox":
            self._handle_sandbox(args, log)
        elif c == "compare":
            self.run_worker(self._compare_cmd(args, log))
        elif c in ("paste", "image", "img"):
            self._handle_paste_image(args, log)
        elif c == "queue":
            self._handle_queue(args, log)
        elif c == "stash":
            self._handle_stash(args, log)
        elif c == "view":
            self._handle_view(args, log)
        elif c == "e":
            self._handle_view(args, log)
        elif c == "search":
            self._handle_search(args, log)
        elif c == "grep":
            self._handle_search(args, log)
        elif c == "tools":
            self._show_tools(args, log)
        elif c == "skills":
            self._skills_cmd(args, log)
        elif c == "skillopt":
            self._skillopt_cmd(args, log)
        elif c in ("recipe", "recipes", "workflow", "workflows"):
            self.run_worker(self._recipe_cmd(args, log))
        elif c == "attach":
            self._attach_cmd(args, log)
        elif c == "prompt":
            self._prompt_file_cmd(args, log)
        elif c in ("switchboard", "sw"):
            self._handle_switchboard(args, log)
        elif c == "factory":
            self._handle_factory(args, log)
        elif c == "sessions":
            self._handle_sessions_command(args, log)
        elif c == "ls":
            self._show_sessions(log)
        elif c == "session":
            self._handle_session(args, log)
        elif c == "resume":
            self._handle_resume_session(args, log)
        elif c == "update":
            self._handle_update(args, log)
        elif c in ("fork", "clone"):
            self._handle_fork_session(args, log)
        elif c == "compact":
            self._handle_compact(log)
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
                elif subcmd == "setup":
                    try:
                        setup_tokens = shlex.split(subargs or "")
                    except ValueError as exc:
                        log.add_error(f"Could not parse :connect setup arguments: {exc}")
                        return
                    self._run_cli_passthrough(
                        ["connect", "setup", *setup_tokens],
                        log,
                        "Connect setup",
                    )
                elif subcmd in ("codex", "claude", "antigravity", "grok"):
                    # Product/runtime connection profiles (Codex, Claude, Grok, …).
                    from superqode.providers.connection_profiles import get_connection_profile

                    profile = get_connection_profile(subcmd)
                    if profile is not None:
                        self._dispatch_connection_profile(profile, log)
                    else:
                        log.add_error(f"Unknown connection: {subcmd}")
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
        elif c == "model":
            self._model_cmd(args, log)
        elif c in ("providers", "provider"):
            self._providers_cmd(args, log)
        elif c in ("recommend", "model-guide"):
            self._recommend_cmd(args, log)
        elif c == "sandbox":
            self._sandbox_cmd(args, log)
        elif c in ("plugins", "plugin"):
            self._plugins_cmd(args, log)
        elif c == "memory":
            self._memory_cmd(args, log)
        elif c == "local":
            self._local_cmd(args, log)
        elif c in ("benchmark", "benchmarks"):
            self._benchmark_cmd(args, log)
        elif c == "usage":
            self._usage_cmd(args, log)
        elif c == "health":
            self._health_cmd(args, log)
        elif c == "mode":
            self._set_approval_mode(args, log)
        elif c == "log":
            self._handle_log_verbosity(args, log)
        elif c == "thinking":
            self._handle_thinking_verbosity(args, log)
        elif c == "workspace":
            self._handle_workspace(args, log)
        elif c == "context":
            self._handle_context(args, log)
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

    def _show_tools(self, args: str, log: ConversationLog):
        """Show the active tool profile and available tools."""
        from superqode.tools.base import ToolRegistry

        arg = (args or "").strip().lower()
        if arg in {"recent", "runs", "history"}:
            log.write(Text(log.format_tool_runs_index() + "\n", style=THEME["text"]))
            return
        if arg.isdigit():
            detail = log.format_tool_run_detail(int(arg))
            if detail.startswith("No tool run #"):
                log.add_info(detail)
                return
            self._open_text_overlay(detail, f"Tool Run #{int(arg)}")
            return

        active_tools = []
        active_profile = "unknown"
        if hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
            status = self._pure_mode.get_status()
            active_tools = status.get("tools", [])
            active_profile = status.get("tool_profile", "full")
        else:
            profile = (args or "full").strip().lower()
            if profile == "minimal":
                registry = ToolRegistry.default()
            elif profile == "standard":
                registry = ToolRegistry.standard()
            elif profile in ("ds4", "local-fast", "local_fast"):
                registry = ToolRegistry.ds4()
                profile = "ds4"
            elif profile in ("coding", "code"):
                registry = ToolRegistry.coding()
                profile = "coding"
            else:
                registry = ToolRegistry.full()
                profile = "full"
            active_tools = [tool.name for tool in registry.list()]
            active_profile = profile

        t = Text()
        t.append("\n  🧰 ", style=f"bold {THEME['cyan']}")
        t.append("Tool Profile\n\n", style=f"bold {THEME['cyan']}")
        t.append("  Active profile: ", style=THEME["muted"])
        t.append(f"{active_profile}\n", style=f"bold {THEME['success']}")
        t.append("  Tool count: ", style=THEME["muted"])
        t.append(f"{len(active_tools)}\n\n", style=f"bold {THEME['text']}")

        categories = {
            "File": {
                "read_file",
                "write_file",
                "list_directory",
                "edit_file",
                "insert_text",
                "patch",
                "multi_edit",
            },
            "Search": {
                "grep",
                "glob",
                "code_search",
                "web_search",
                "web_fetch",
                "fetch",
                "download",
            },
            "Runtime": {"bash", "diagnostics", "lsp", "batch"},
            "Workflow": {
                "todo_write",
                "todo_read",
                "compact",
                "agent",
                "coordinate",
                "ask_user",
                "confirm",
            },
            "Skills": {"skill", "read_skill"},
        }
        remaining = set(active_tools)
        for title, names in categories.items():
            tools = sorted(name for name in active_tools if name in names)
            if not tools:
                continue
            remaining.difference_update(tools)
            t.append(f"  {title}\n", style=f"bold {THEME['gold']}")
            t.append(f"    {', '.join(tools)}\n", style=THEME["muted"])

        if remaining:
            t.append("  Other\n", style=f"bold {THEME['gold']}")
            t.append(f"    {', '.join(sorted(remaining))}\n", style=THEME["muted"])

        t.append("\n  Commands: ", style=THEME["muted"])
        t.append("/tools", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append("/mode", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":mcp tools", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _handle_timeline(self, log: ConversationLog):
        """Open a replay-style timeline of the current TUI session."""
        self._open_text_overlay(log.format_session_timeline(), "Session Timeline")


    def _handle_stash(self, args: str, log: ConversationLog):
        """Manage stashed prompt drafts: restore (pop), list, or clear."""
        arg = (args or "").strip().lower()
        stash = getattr(self, "_draft_stash", [])
        if arg in ("list", "ls"):
            if not stash:
                log.add_info("No stashed drafts. Press Ctrl+G while typing to stash one.")
                return
            t = Text()
            t.append("\n  📥 ", style=f"bold {THEME['purple']}")
            t.append(f"Stashed drafts ({len(stash)})\n\n", style=f"bold {THEME['text']}")
            for index, draft in enumerate(reversed(stash), 1):
                preview = " ".join(str(draft).split())
                if len(preview) > 96:
                    preview = preview[:93].rstrip() + "..."
                t.append(f"  {index}. ", style=THEME["dim"])
                t.append(f"{preview}\n", style=THEME["text"])
            t.append("\n  ", style="")
            t.append(":stash", style=f"bold {THEME['cyan']}")
            t.append(" restores the most recent  •  ", style=THEME["muted"])
            t.append(":stash clear", style=f"bold {THEME['cyan']}")
            t.append(" drops all.\n", style=THEME["muted"])
            log.write(t)
            return
        if arg in ("clear", "drop", "reset"):
            self._draft_stash = []
            log.add_info("Cleared stashed drafts.")
            return
        # Default / "pop": restore the most recent stash into the prompt.
        if not stash:
            log.add_info("No stashed drafts. Press Ctrl+G while typing to stash one.")
            return
        draft = stash.pop()
        self._draft_stash = stash
        self._set_prompt_prefill(draft)
        log.add_info(f"📤 Restored stashed draft ({len(stash)} remaining). Edit and press Enter.")

    def _handle_queue(self, args: str, log: ConversationLog):
        """View or clear the type-ahead message queue."""
        arg = (args or "").strip().lower()
        queue = getattr(self, "_typeahead_queue", [])
        if arg in ("clear", "reset", "drop"):
            self._clear_message_queue(log)
            return
        if not queue:
            log.add_info(
                "No queued messages. Type while the agent is busy to queue your next message."
            )
            return
        t = Text()
        t.append("\n  ⏳ ", style=f"bold {THEME['warning']}")
        t.append(f"Queued messages ({len(queue)})\n\n", style=f"bold {THEME['text']}")
        for index, msg in enumerate(queue, 1):
            preview = " ".join(str(msg).split())
            if len(preview) > 100:
                preview = preview[:97].rstrip() + "..."
            t.append(f"  {index}. ", style=THEME["dim"])
            t.append(f"{preview}\n", style=THEME["text"])
        t.append("\n  ", style="")
        t.append(":queue clear", style=f"bold {THEME['cyan']}")
        t.append(" to drop them.\n", style=THEME["muted"])
        log.write(t)

    def _user_message_history(self, log: ConversationLog) -> list[str]:
        """Return prior user messages (oldest first) for rewind/edit."""
        return [
            text for role, text, _agent in log._messages if role == "user" and str(text).strip()
        ]


    def _handle_export(self, args: str, log: ConversationLog) -> None:
        """Export the current conversation to HTML, Markdown, or JSON."""
        from superqode.rendering.html_export import render_transcript_html
        from superqode.rendering.transcript_export import (
            default_transcript_metadata,
            render_transcript_json,
            render_transcript_markdown,
        )

        messages = list(getattr(log, "_messages", []))
        if not messages:
            log.add_info("Nothing to export yet.")
            return

        try:
            export_format, out_path = self._resolve_export_target(args)
        except ValueError as exc:
            log.add_error(f"Could not parse :export arguments: {exc}")
            return
        metadata = default_transcript_metadata(
            cwd=str(Path.cwd()),
            runtime=getattr(self, "current_runtime", "") or "",
            provider=getattr(self, "current_provider", "") or "",
            model=getattr(self, "current_model", "") or "",
        )

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if export_format == "json":
                content = render_transcript_json(messages, metadata=metadata)
            elif export_format == "markdown":
                content = render_transcript_markdown(messages, metadata=metadata)
            else:
                content = render_transcript_html(messages, title="SuperQode Transcript")
            out_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            log.add_error(f"Could not export transcript: {exc}")
            return
        log.add_success(f"Exported {export_format} transcript -> {out_path}")

    def _resolve_export_target(self, args: str) -> tuple[str, Path]:
        """Resolve ``:export [format] [path]`` into a format and output path."""
        format_aliases = {
            "html": "html",
            "htm": "html",
            "markdown": "markdown",
            "md": "markdown",
            "json": "json",
        }
        suffix_by_format = {
            "html": ".html",
            "markdown": ".md",
            "json": ".json",
        }
        tokens = shlex.split((args or "").strip()) if (args or "").strip() else []
        export_format = "html"
        path_arg = ""
        if tokens and tokens[0].lower() in format_aliases:
            export_format = format_aliases[tokens[0].lower()]
            path_arg = " ".join(tokens[1:]).strip()
        elif tokens:
            path_arg = " ".join(tokens).strip()
            suffix_format = {
                ".html": "html",
                ".htm": "html",
                ".md": "markdown",
                ".markdown": "markdown",
                ".json": "json",
            }.get(Path(path_arg).suffix.lower())
            if suffix_format:
                export_format = suffix_format

        suffix = suffix_by_format[export_format]
        if path_arg:
            out_path = Path(path_arg).expanduser()
            if out_path.suffix.lower() not in {
                ".html",
                ".htm",
                ".md",
                ".markdown",
                ".json",
            }:
                out_path = out_path.with_suffix(suffix)
            return export_format, out_path

        stamp = time.strftime("%Y%m%d-%H%M%S")
        return export_format, Path(".superqode") / "exports" / f"transcript-{stamp}{suffix}"

    def _handle_sandbox(self, args: str, log: ConversationLog) -> None:
        """Show or set the local OS command sandbox.

        ``:sandbox`` shows status; ``:sandbox <off|workspace-write|read-only>``
        sets the mode for this session. When active, shell commands are confined
        to the workspace (and network is denied in read-only) via the OS sandbox
        (macOS Seatbelt / Linux bubblewrap).
        """
        from superqode.sandbox.local_sandbox import (
            MODE_OFF,
            MODE_READ_ONLY,
            MODE_WORKSPACE_WRITE,
            sandbox_status,
        )

        valid = {MODE_OFF, MODE_WORKSPACE_WRITE, MODE_READ_ONLY}
        arg = (args or "").strip().lower()
        if arg:
            if arg not in valid:
                log.add_error(f"Unknown sandbox mode '{arg}'. Use: {', '.join(sorted(valid))}")
                return
            os.environ["SUPERQODE_SANDBOX"] = arg
            status = sandbox_status()
            if arg != MODE_OFF and not status["available"]:
                log.add_info(
                    f"Sandbox mode set to '{arg}', but no backend is available on this system "
                    "(needs macOS sandbox-exec or Linux bwrap). Commands run unconfined."
                )
            else:
                log.add_success(f"🛡 Sandbox mode set to '{arg}'.")
            return

        status = sandbox_status()
        t = Text()
        t.append("\n🛡 Command sandbox\n", style=f"bold {THEME['purple']}")
        t.append(f"  Mode:      {status['mode']}\n", style=THEME["text"])
        t.append(f"  Backend:   {status['backend']}\n", style=THEME["text"])
        t.append(
            f"  Active:    {'yes' if status['active'] else 'no'}\n",
            style=THEME["success"] if status["active"] else THEME["muted"],
        )
        t.append("\n  Modes: ", style=THEME["dim"])
        t.append("off", style=THEME["cyan"])
        t.append(" · ", style=THEME["dim"])
        t.append("workspace-write", style=THEME["cyan"])
        t.append(" (write workspace, network on) · ", style=THEME["dim"])
        t.append("read-only", style=THEME["cyan"])
        t.append(" (no writes/network)\n", style=THEME["dim"])
        t.append("  Set with :sandbox <mode>\n", style=THEME["dim"])
        try:
            from superqode.agent.network_policy import load_allowlist, strict_mode

            allow_count = len(load_allowlist())
            t.append(
                f"\n  Network policy: {allow_count} trusted domains"
                f"{' · strict (deny untrusted)' if strict_mode() else ''}\n",
                style=THEME["dim"],
            )
            t.append(
                "  Trusted installs auto-run; untrusted egress is gated.\n",
                style=THEME["dim"],
            )
        except Exception:
            pass
        log.write(t)

    async def _compare_cmd(self, args: str, log: ConversationLog) -> None:
        """Fan the last user message across several models concurrently.

        ``:compare <m1> <m2> ...`` — each token is ``provider/model`` or a bare
        ``model`` (using the connected provider). Read-only: a single chat
        completion per target, no tools, so it is safe to run in parallel. This
        leans on SuperQode's multi-runtime reach — comparing across providers in
        one shot is something single-stack harnesses can't do.
        """
        from superqode.agent.parallel_compare import (
            default_compare_runner,
            parse_compare_specs,
            run_parallel_compare,
        )

        prompt = self._last_user_message or log.get_last_message("user")
        if not prompt:
            log.add_info("Send a message first, then :compare <models> to compare answers to it.")
            return

        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :compare arguments: {exc}")
            return
        default_provider = getattr(getattr(self._pure_mode, "session", None), "provider", "") or ""
        specs = parse_compare_specs(tokens, default_provider=default_provider)
        if not specs:
            log.add_info(
                "Usage: :compare <provider/model> <model> …  (e.g. :compare openai/gpt-4o anthropic/claude-3-5-sonnet)"
            )
            return

        labels = ", ".join(spec.label for spec in specs)
        log.add_info(f"⚖ Comparing {len(specs)} models on your last message: {labels}")

        results = await run_parallel_compare(prompt, specs, default_compare_runner)
        self._render_compare_results(results, log)


    def _apply_and_persist_theme(self, name: str) -> bool:
        """Apply a theme palette live, persist it, and refresh the visible UI."""
        if not _apply_theme_palette(name):
            return False
        self._current_theme = name
        save_theme(name)
        # Re-render widgets that read THEME at render time.
        try:
            self.screen.refresh(layout=True)
        except Exception:
            pass
        return True

    def _handle_rewind(self, args: str, log: ConversationLog):
        """Rewind the conversation to an earlier user message.

        ``:rewind`` (or Ctrl+R) opens the transcript overlay to choose a point;
        ``:rewind <n>`` / ``:rewind last`` rewind directly. Rewinding truncates
        the agent's stored history so it forgets everything after that message,
        then loads the message back into the prompt for editing and resending.
        """
        messages = self._user_message_history(log)
        if not messages:
            log.add_info("No previous messages to rewind to yet.")
            return

        arg = (args or "").strip().lower()
        if arg.isdigit():
            index = int(arg)
            if not (1 <= index <= len(messages)):
                log.add_info(
                    f"No message #{index}. Use :rewind to choose ({len(messages)} available)."
                )
                return
            self._perform_rewind(index, log)
            return
        if arg in ("last", "prev", "previous"):
            self._perform_rewind(len(messages), log)
            return
        if arg == "":
            self._open_rewind_overlay(log)
            return
        log.add_info("Usage: :rewind  •  :rewind <number>  •  :rewind last")

    def _open_rewind_overlay(self, log: ConversationLog) -> None:
        """Push the interactive transcript/rewind overlay."""
        messages = self._user_message_history(log)
        if not messages:
            log.add_info("No previous messages to rewind to yet.")
            return
        targets = [
            RewindTarget(occurrence=i + 1, preview=" ".join(str(text).split())[:200])
            for i, text in enumerate(messages)
        ]
        transcript = list(getattr(log, "_messages", []))

        def _on_dismissed(occurrence: int | None) -> None:
            self.set_timer(0.1, self._ensure_input_focus)
            if occurrence:
                self._perform_rewind(occurrence, log)

        self.push_screen(RewindOverlay(transcript, targets), callback=_on_dismissed)

    def _perform_rewind(self, occurrence: int, log: ConversationLog) -> None:
        """Truncate context to before the Nth user message and reload it.

        ``occurrence`` is 1-based among user messages. Removes the stored agent
        history from that point on, trims the in-memory transcript record, and
        prefills the prompt so the user can edit and resend.
        """
        messages = self._user_message_history(log)
        total = len(messages)
        if not (1 <= occurrence <= total):
            log.add_info(f"No message #{occurrence} to rewind to.")
            return
        target_text = messages[occurrence - 1]

        # Truncate the agent's persisted history so it forgets later turns.
        removed = 0
        session_manager = getattr(self._pure_mode, "_session_manager", None)
        if session_manager is not None:
            try:
                removed = session_manager.rewind_to_user_message(occurrence)
            except Exception as exc:  # pragma: no cover - defensive
                log.add_error(f"Could not rewind stored history: {exc}")

        # Trim the in-memory transcript record to the chosen point so future
        # rewinds, copies and transcripts reflect the rewound conversation.
        self._trim_transcript_to_user_occurrence(log, occurrence)

        self._set_prompt_prefill(target_text)
        suffix = f" — cleared {removed} stored message(s)" if removed else ""
        log.add_info(
            f"↩ Rewound to message {occurrence}/{total}{suffix}. Edit and press Enter to resend."
        )

    @staticmethod
    def _trim_transcript_to_user_occurrence(log: ConversationLog, occurrence: int) -> None:
        """Drop transcript entries from the Nth user message onward."""
        records = getattr(log, "_messages", None)
        if records is None:
            return
        seen = 0
        cut = None
        for index, (role, _text, _agent) in enumerate(records):
            if role == "user" and str(_text).strip():
                seen += 1
                if seen == occurrence:
                    cut = index
                    break
        if cut is not None:
            del records[cut:]

    def _skills_cmd(self, args: str, log: ConversationLog):
        """Handle local skill inventory and setup commands.

        Covers the most useful day-to-day skill flow:
        users can see the skills currently visible to the agent, inspect one,
        create a template, or import an existing local SKILL.md/markdown skill.
        """
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :skills arguments: {exc}")
            return
        action = tokens[0].lower() if tokens else "list"
        rest = tokens[1:]
        if action in {"ls", "show"}:
            action = "list"

        skills_root = Path.cwd() / ".agents" / "skills"

        if action in {"list", "available", "status"}:
            from superqode.skills import load_skills

            skills = sorted(load_skills(Path.cwd()).values(), key=lambda item: item.name.lower())
            t = Text()
            t.append("\n  ✦ ", style=f"bold {THEME['purple']}")
            t.append("Skills\n\n", style=f"bold {THEME['text']}")
            t.append("  Directory   ", style=THEME["muted"])
            t.append(f"{skills_root}\n", style=THEME["text"])
            t.append("  Loaded      ", style=THEME["muted"])
            t.append(f"{len(skills)}\n\n", style=f"bold {THEME['cyan']}")
            if not skills:
                t.append("  No local skills found.\n", style=THEME["muted"])
                t.append("  Create one with ", style=THEME["muted"])
                t.append(":skills add repo-review", style=THEME["cyan"])
                t.append(" or import an existing SKILL.md.\n", style=THEME["muted"])
            for index, skill in enumerate(skills, 1):
                t.append(f"  [{index}] ", style=THEME["dim"])
                t.append(skill.name, style=f"bold {THEME['cyan']}")
                if skill.description:
                    t.append(f" - {skill.description}", style=THEME["muted"])
                t.append("\n")
                if skill.path:
                    t.append(f"      {skill.path}\n", style=THEME["dim"])
            t.append("\n  Commands: ", style=THEME["muted"])
            t.append(":skills info <name>", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":skills add <name>", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":skills import <path>\n", style=THEME["cyan"])
            t.append("            ", style=THEME["muted"])
            t.append(
                ":skills optimize <name> --harness <path> --tasks <path> --live\n",
                style=THEME["cyan"],
            )
            self._show_command_output(log, t)
            return

        if action in {"info", "read"}:
            if not rest:
                log.add_error("Usage: :skills info <name>")
                return
            from superqode.skills import load_skills

            name = rest[0]
            skills = load_skills(Path.cwd())
            skill = skills.get(name)
            if skill is None:
                lowered = name.lower()
                skill = next(
                    (item for item in skills.values() if item.name.lower() == lowered), None
                )
            if skill is None:
                log.add_error(f"Skill not found: {name}")
                log.add_info("Use :skills to list loaded skills.")
                return
            t = Text()
            t.append("\n  ✦ ", style=f"bold {THEME['purple']}")
            t.append(skill.name, style=f"bold {THEME['text']}")
            t.append("\n\n", style="")
            if skill.description:
                t.append("  Description ", style=THEME["muted"])
                t.append(f"{skill.description}\n", style=THEME["text"])
            if skill.path:
                t.append("  Path        ", style=THEME["muted"])
                t.append(f"{skill.path}\n", style=THEME["dim"])
            t.append("\n", style="")
            preview = skill.instructions.strip()
            if len(preview) > 2400:
                preview = preview[:2400].rstrip() + "\n..."
            t.append(preview or "(empty skill)", style=THEME["text"])
            t.append("\n", style="")
            self._show_command_output(log, t)
            return

        if action in {"search", "find"}:
            if not rest:
                log.add_error("Usage: :skills search <query>")
                return
            from superqode.skills import load_skills

            query = " ".join(rest).lower()
            skills = [
                skill
                for skill in load_skills(Path.cwd()).values()
                if query in skill.name.lower()
                or query in skill.description.lower()
                or query in skill.instructions.lower()
            ]
            t = Text()
            t.append("\n  ✦ ", style=f"bold {THEME['purple']}")
            t.append(f"Skill Search: {query}\n\n", style=f"bold {THEME['text']}")
            if not skills:
                t.append("  No matching skills found.\n", style=THEME["muted"])
            for skill in sorted(skills, key=lambda item: item.name.lower()):
                t.append(f"  {skill.name}", style=f"bold {THEME['cyan']}")
                if skill.description:
                    t.append(f" - {skill.description}", style=THEME["muted"])
                t.append("\n")
                if skill.path:
                    t.append(f"    {skill.path}\n", style=THEME["dim"])
            self._show_command_output(log, t)
            return

        if action in {"doctor", "validate", "check"}:
            self._skills_doctor(skills_root, log)
            return

        if action in {"optimize", "optimise"}:
            if not rest:
                log.add_error(
                    "Usage: :skills optimize <name> --harness harness.yaml --tasks eval-tasks.yaml --live"
                )
                return
            if "--live" not in rest:
                log.add_error(":skills optimize requires --live so eval tasks produce real scores.")
                return
            self.run_worker(self._skills_optimize_cmd(rest, log))
            return

        if action in {"enable", "disable"}:
            if not rest:
                log.add_error(f"Usage: :skills {action} <name>")
                return
            changed = self._set_skill_enabled(skills_root, rest[0], enabled=action == "enable")
            if changed:
                log.add_success(f"Skill {rest[0]} {action}d.")
            else:
                log.add_error(f"Skill not found or could not be updated: {rest[0]}")
            return

        if action in {"add", "create", "new"}:
            if not rest:
                log.add_error("Usage: :skills add <name> [description]")
                return
            name = rest[0].strip().replace("/", "-")
            description = " ".join(rest[1:]).strip() or f"{name} workflow"
            skill_dir = skills_root / name
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                log.add_error(f"Skill already exists: {skill_file}")
                return
            skill_dir.mkdir(parents=True, exist_ok=True)
            content = (
                "---\n"
                f"name: {name}\n"
                f"description: {description}\n"
                "enabled: true\n"
                "---\n\n"
                f"# {name}\n\n"
                "Describe when to use this skill, what context to gather, and the steps the agent should follow.\n"
            )
            skill_file.write_text(content, encoding="utf-8")
            log.add_success(f"Created skill template: {skill_file}")
            log.add_info("Edit the SKILL.md instructions, then run :skills to confirm it loads.")
            return

        if action in {"import", "add-local"}:
            if not rest:
                log.add_error("Usage: :skills import <path-to-SKILL.md-or-directory>")
                return
            source = Path(rest[0]).expanduser()
            if not source.is_absolute():
                source = Path.cwd() / source
            if not source.exists():
                log.add_error(f"Path not found: {source}")
                return
            skills_root.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                name = source.name
                destination = skills_root / name
                if destination.exists():
                    log.add_error(f"Destination already exists: {destination}")
                    return
                shutil.copytree(source, destination)
                log.add_success(f"Imported skill directory: {destination}")
                return
            destination_dir = skills_root / source.stem
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / (
                "SKILL.md" if source.name.upper() == "SKILL.MD" else source.name
            )
            if destination.exists():
                log.add_error(f"Destination already exists: {destination}")
                return
            shutil.copy2(source, destination)
            log.add_success(f"Imported skill file: {destination}")
            return

        if action in {"remove", "rm", "delete", "uninstall"}:
            if not rest:
                log.add_error("Usage: :skills remove <name>")
                return
            target = skills_root / rest[0]
            if not target.exists():
                log.add_error(f"Skill path not found: {target}")
                return
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            log.add_success(f"Removed skill: {target}")
            return

        log.add_info(
            "Usage: :skills [list|info <name>|add <name>|import <path>|optimize <name> --harness <path> --tasks <path> --live|remove <name>]"
        )

    async def _skills_optimize_cmd(self, tokens: list[str], log: ConversationLog) -> None:
        """Run the GEPA skill optimizer from the TUI without blocking input."""
        await self._superqode_cli_cmd(["skills", "optimize", *tokens], log, "Skill optimization")

    def _skillopt_cmd(self, args: str, log: ConversationLog) -> None:
        """Run legacy SkillOpt workspace/check commands from the TUI."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :skillopt arguments: {exc}")
            return
        if not tokens or tokens[0] not in {"export", "check"}:
            log.add_info(
                "Usage: :skillopt export <skill> --tasks <path> --project <dir> | :skillopt check --baseline <path> --candidate <path>"
            )
            return
        self.run_worker(self._superqode_cli_cmd(["skillopt", *tokens], log, "SkillOpt command"))

    async def _superqode_cli_cmd(
        self,
        command_parts: list[str],
        log: ConversationLog,
        label: str,
    ) -> None:
        """Run a SuperQode CLI command from the TUI without blocking input."""
        import sys

        command = [
            sys.executable,
            "-m",
            "superqode.main",
            *command_parts,
        ]
        display_command = " ".join(shlex.quote(part) for part in command)
        log.add_info(f"Starting {label}:\n  {display_command}")

        def _run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                cwd=Path.cwd(),
                text=True,
                capture_output=True,
                check=False,
            )

        try:
            completed = await asyncio.to_thread(_run)
        except Exception as exc:
            log.add_error(f"{label} failed to start: {exc}")
            return

        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        if completed.returncode == 0:
            log.add_success(f"{label} completed.")
            if output:
                log.write(Text(output + "\n", style=THEME["text"], overflow="fold"))
        else:
            log.add_error(f"{label} failed with exit code {completed.returncode}.")
            if output:
                log.write(Text(output + "\n", style=THEME["error"], overflow="fold"))

    def _run_cli_passthrough(
        self,
        command_parts: list[str],
        log: ConversationLog,
        label: str,
    ) -> None:
        """Run a CLI-backed command from the TUI."""
        self.run_worker(self._superqode_cli_cmd(command_parts, log, label))

    def _run_cli_group(self, group: str, args: str, log: ConversationLog, label: str) -> None:
        """Run `superqode <group> ...` from a TUI command handler."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :{group} arguments: {exc}")
            return
        self._run_cli_passthrough([group, *tokens], log, label)

    def _find_skill_file(self, skills_root: Path, name: str) -> Path | None:
        """Find a local skill file by directory, file stem, or frontmatter name."""
        candidates = [
            skills_root / name / "SKILL.md",
            skills_root / name,
            skills_root / f"{name}.md",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        if not skills_root.exists():
            return None
        for path in sorted(skills_root.rglob("*.md")):
            if path.stem.lower() == name.lower() or path.parent.name.lower() == name.lower():
                return path
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:1000].lower()
            except Exception:
                continue
            if f"name: {name.lower()}" in head:
                return path
        return None

    def _set_skill_enabled(self, skills_root: Path, name: str, *, enabled: bool) -> bool:
        """Toggle a skill's frontmatter enabled flag."""
        path = self._find_skill_file(skills_root, name)
        if path is None:
            return False
        try:
            text = path.read_text(encoding="utf-8")
            value = "true" if enabled else "false"
            if text.startswith("---"):
                end = text.find("\n---", 3)
                if end != -1:
                    front = text[:end]
                    body = text[end:]
                    lines = front.splitlines()
                    replaced = False
                    for idx, line in enumerate(lines):
                        if line.strip().startswith("enabled:"):
                            lines[idx] = f"enabled: {value}"
                            replaced = True
                            break
                    if not replaced:
                        lines.append(f"enabled: {value}")
                    path.write_text("\n".join(lines) + body, encoding="utf-8")
                    return True
            path.write_text(f"---\nenabled: {value}\n---\n\n{text}", encoding="utf-8")
            return True
        except Exception:
            return False

    def _skills_doctor(self, skills_root: Path, log: ConversationLog) -> None:
        """Validate local skill files and show actionable issues."""
        t = Text()
        t.append("\n  ✦ ", style=f"bold {THEME['purple']}")
        t.append("Skills Doctor\n\n", style=f"bold {THEME['text']}")
        t.append("  Directory   ", style=THEME["muted"])
        t.append(f"{skills_root}\n\n", style=THEME["text"])

        if not skills_root.exists():
            t.append("  warning  ", style=THEME["warning"])
            t.append(
                "Skills directory does not exist. Use :skills add <name>.\n", style=THEME["text"]
            )
            self._show_command_output(log, t)
            return

        files = sorted(skills_root.rglob("*.md"))
        names: dict[str, Path] = {}
        issues: list[tuple[str, str]] = []
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:
                issues.append((str(path), f"unreadable: {exc}"))
                continue
            name = path.parent.name if path.name.upper() == "SKILL.MD" else path.stem
            description = ""
            if text.startswith("---"):
                end = text.find("\n---", 3)
                if end != -1:
                    front = text[:end]
                    for line in front.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("name:"):
                            name = stripped.split(":", 1)[1].strip().strip('"').strip("'") or name
                        elif stripped.startswith("description:"):
                            description = stripped.split(":", 1)[1].strip()
            else:
                issues.append((str(path), "missing frontmatter block"))
            if not description:
                issues.append((str(path), "missing description"))
            lowered = name.lower()
            if lowered in names:
                issues.append((str(path), f"duplicate skill name also used by {names[lowered]}"))
            else:
                names[lowered] = path

        t.append("  Files       ", style=THEME["muted"])
        t.append(f"{len(files)}\n", style=THEME["text"])
        t.append("  Names       ", style=THEME["muted"])
        t.append(f"{len(names)}\n", style=THEME["text"])
        t.append("  Issues      ", style=THEME["muted"])
        t.append(f"{len(issues)}\n\n", style=THEME["warning"] if issues else THEME["success"])

        if not issues:
            t.append("  ok  All local skills look valid.\n", style=THEME["success"])
        else:
            for path, issue in issues[:30]:
                t.append("  warning  ", style=THEME["warning"])
                t.append(f"{path}: {issue}\n", style=THEME["text"])
            if len(issues) > 30:
                t.append(f"  ... and {len(issues) - 30} more issue(s)\n", style=THEME["dim"])
        self._show_command_output(log, t)

    def _find_recipe(self, name: str) -> LocalRecipe | None:
        recipes = self._load_local_recipes()
        recipe = recipes.get(name)
        if recipe is not None:
            return recipe
        lowered = name.lower()
        return next((item for item in recipes.values() if item.name.lower() == lowered), None)

    async def _recipe_cmd(self, args: str, log: ConversationLog):
        """Handle reusable local workflow recipes."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :recipe arguments: {exc}")
            return
        action = tokens[0].lower() if tokens else "list"
        rest = tokens[1:]
        if action in {"ls", "show"}:
            action = "list"

        if action in {"list", "available", "status"}:
            self._show_recipes(log)
            return

        if action in {"info", "read"}:
            if not rest:
                log.add_error("Usage: :recipe info <name>")
                return
            recipe = self._find_recipe(rest[0])
            if recipe is None:
                log.add_error(f"Recipe not found: {rest[0]}")
                return
            self._show_recipe_info(recipe, log)
            return

        if action in {"doctor", "validate", "check"}:
            if rest:
                recipe = self._find_recipe(rest[0])
                if recipe is None:
                    log.add_error(f"Recipe not found: {rest[0]}")
                    return
                self._show_recipe_doctor(recipe, log)
            else:
                self._show_recipes_doctor(log)
            return

        if action in {"run", "start", "use"}:
            if not rest:
                log.add_error("Usage: :recipe run <name> [extra prompt text]")
                return
            name = rest[0]
            extra = " ".join(rest[1:]).strip()
            recipe = self._find_recipe(name)
            if recipe is None:
                log.add_error(f"Recipe not found: {name}")
                return
            await self._run_recipe(recipe, extra, log)
            return

        log.add_info("Usage: :recipe [list|info <name>|doctor [name]|run <name> [input]]")

    def _show_recipes(self, log: ConversationLog) -> None:
        recipes = sorted(self._load_local_recipes().values(), key=lambda item: item.name.lower())
        t = Text()
        t.append("\n  ◇ ", style=f"bold {THEME['purple']}")
        t.append("Recipes\n\n", style=f"bold {THEME['text']}")
        for directory in self._recipe_dirs():
            t.append("  Directory   ", style=THEME["muted"])
            t.append(f"{directory}\n", style=THEME["dim"])
        t.append("  Loaded      ", style=THEME["muted"])
        t.append(f"{len(recipes)}\n\n", style=THEME["cyan"])
        if not recipes:
            t.append("  No local recipes found.\n", style=THEME["muted"])
            t.append("  Add YAML or JSON recipes under .superqode/recipes.\n", style=THEME["muted"])
        for index, recipe in enumerate(recipes, 1):
            t.append(f"  [{index}] ", style=THEME["dim"])
            t.append(recipe.name, style=f"bold {THEME['cyan']}")
            if recipe.description:
                t.append(f" - {recipe.description}", style=THEME["muted"])
            t.append("\n")
            details = []
            if recipe.provider and recipe.model:
                details.append(f"{recipe.provider}/{recipe.model}")
            if recipe.mode or recipe.role:
                details.append(".".join(part for part in [recipe.mode, recipe.role] if part))
            if recipe.skills:
                details.append(f"{len(recipe.skills)} skill(s)")
            if recipe.attachments or recipe.mcp_resources:
                details.append(
                    f"{len(recipe.attachments) + len(recipe.mcp_resources)} attachment(s)"
                )
            if details:
                t.append(f"      {', '.join(details)}\n", style=THEME["dim"])
            if recipe.path:
                t.append(f"      {recipe.path}\n", style=THEME["dim"])
        t.append("\n  Commands: ", style=THEME["muted"])
        t.append(":recipe run <name>", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":recipe doctor <name>", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _show_recipe_info(self, recipe: LocalRecipe, log: ConversationLog) -> None:
        t = Text()
        t.append("\n  ◇ ", style=f"bold {THEME['purple']}")
        t.append(recipe.name, style=f"bold {THEME['text']}")
        t.append("\n\n")
        fields = [
            ("Description", recipe.description),
            ("Path", str(recipe.path) if recipe.path else ""),
            (
                "Provider",
                f"{recipe.provider}/{recipe.model}" if recipe.provider or recipe.model else "",
            ),
            ("Role", ".".join(part for part in [recipe.mode, recipe.role] if part)),
            ("Harness", recipe.harness),
            ("Skills", ", ".join(recipe.skills)),
            ("Attachments", ", ".join([*recipe.attachments, *recipe.mcp_resources])),
            ("Variables", ", ".join(recipe.variables)),
            ("Prompt file", recipe.prompt_file),
        ]
        for label, value in fields:
            if value:
                t.append(f"  {label:<12}", style=THEME["muted"])
                t.append(f"{value}\n", style=THEME["text"])
        if recipe.prompt:
            preview = recipe.prompt[:1200].rstrip()
            t.append("\n", style="")
            t.append(preview, style=THEME["text"])
            if len(recipe.prompt) > len(preview):
                t.append("\n...", style=THEME["dim"])
            t.append("\n", style="")
        self._show_command_output(log, t)

    def _recipe_prompt_text(self, recipe: LocalRecipe, extra: str = "") -> str:
        prompt = recipe.prompt
        if recipe.prompt_file and recipe.path:
            path = Path(recipe.prompt_file).expanduser()
            if not path.is_absolute():
                path = recipe.path.parent / path
            if path.exists() and path.is_file():
                prompt = path.read_text(encoding="utf-8").strip()
        if recipe.variables:
            prompt += "\n\nRecipe variables to fill: " + ", ".join(recipe.variables)
        if recipe.skills:
            prompt += "\n\nUse these skills when relevant: " + ", ".join(recipe.skills)
        if extra:
            prompt += "\n\nUser input:\n" + extra
        return prompt.strip()

    def _recipe_issues(self, recipe: LocalRecipe) -> list[str]:
        issues: list[str] = []
        if not recipe.prompt and not recipe.prompt_file:
            issues.append("missing prompt or prompt_file")
        if recipe.prompt_file and recipe.path:
            prompt_path = Path(recipe.prompt_file).expanduser()
            if not prompt_path.is_absolute():
                prompt_path = recipe.path.parent / prompt_path
            if not prompt_path.exists() or not prompt_path.is_file():
                issues.append(f"prompt_file not found: {recipe.prompt_file}")
        if recipe.provider:
            try:
                from superqode.providers.registry import PROVIDERS

                if recipe.provider not in PROVIDERS:
                    issues.append(f"unknown provider: {recipe.provider}")
            except Exception:
                issues.append("provider registry unavailable")
        if recipe.skills:
            loaded = set(self._all_local_skill_names())
            for skill in recipe.skills:
                if skill not in loaded:
                    issues.append(f"missing skill: {skill}")
        if recipe.attachments:
            base = recipe.path.parent if recipe.path else Path.cwd()
            for ref in recipe.attachments:
                if ref.startswith(("http://", "https://", "@")):
                    continue
                path = Path(ref).expanduser()
                if not path.is_absolute():
                    path = base / path
                if not path.exists():
                    issues.append(f"attachment not found: {ref}")
        if recipe.harness and recipe.path:
            harness_path = Path(recipe.harness).expanduser()
            if not harness_path.is_absolute():
                harness_path = recipe.path.parent / harness_path
            if not harness_path.exists():
                issues.append(f"harness spec not found: {recipe.harness}")
        return issues

    def _show_recipe_doctor(self, recipe: LocalRecipe, log: ConversationLog) -> None:
        issues = self._recipe_issues(recipe)
        t = Text()
        t.append("\n  ◇ ", style=f"bold {THEME['purple']}")
        t.append(f"Recipe Doctor: {recipe.name}\n\n", style=f"bold {THEME['text']}")
        if not issues:
            t.append("  ok  Recipe looks runnable.\n", style=THEME["success"])
        else:
            for issue in issues:
                t.append("  warning  ", style=THEME["warning"])
                t.append(f"{issue}\n", style=THEME["text"])
        self._show_command_output(log, t)

    def _show_recipes_doctor(self, log: ConversationLog) -> None:
        recipes = sorted(self._load_local_recipes().values(), key=lambda item: item.name.lower())
        t = Text()
        t.append("\n  ◇ ", style=f"bold {THEME['purple']}")
        t.append("Recipes Doctor\n\n", style=f"bold {THEME['text']}")
        if not recipes:
            t.append("  warning  No local recipes found.\n", style=THEME["warning"])
        total_issues = 0
        for recipe in recipes:
            issues = self._recipe_issues(recipe)
            total_issues += len(issues)
            style = THEME["success"] if not issues else THEME["warning"]
            t.append(f"  {recipe.name:<24}", style=f"bold {THEME['cyan']}")
            t.append("ok\n" if not issues else f"{len(issues)} issue(s)\n", style=style)
            for issue in issues[:5]:
                t.append(f"      {issue}\n", style=THEME["dim"])
        t.append("\n  Issues      ", style=THEME["muted"])
        t.append(f"{total_issues}\n", style=THEME["warning"] if total_issues else THEME["success"])
        self._show_command_output(log, t)

    async def _run_recipe(self, recipe: LocalRecipe, extra: str, log: ConversationLog) -> None:
        issues = self._recipe_issues(recipe)
        if issues:
            log.add_error(
                f"Recipe {recipe.name} has {len(issues)} issue(s). Run :recipe doctor {recipe.name}."
            )
            return
        prompt = self._recipe_prompt_text(recipe, extra)
        refs = list(getattr(self, "_attached_refs", []))
        base = recipe.path.parent if recipe.path else Path.cwd()
        for ref in recipe.attachments:
            if ref.startswith(("http://", "https://", "@", "mcp://")):
                normalized = ref
            else:
                path = Path(ref).expanduser()
                if not path.is_absolute():
                    path = base / path
                path = path.resolve()
                try:
                    normalized = "@" + str(path.relative_to(Path.cwd()))
                except ValueError:
                    normalized = "@" + str(path)
            if normalized not in refs:
                refs.append(normalized)
        for ref in recipe.mcp_resources:
            normalized = ref if ref.startswith("mcp://") else f"mcp://{ref}"
            if normalized not in refs:
                refs.append(normalized)
        self._attached_refs = refs
        self._sync_attachment_prefill()

        if recipe.harness and recipe.path:
            harness_path = Path(recipe.harness).expanduser()
            if not harness_path.is_absolute():
                harness_path = recipe.path.parent / harness_path
            try:
                from superqode.harness import load_harness_spec

                spec = load_harness_spec(harness_path)
                self.active_harness_path = harness_path
                self.active_harness_name = spec.name
                os.environ["SUPERQODE_HARNESS"] = str(harness_path)
                pure = self._ensure_pure_mode()
                pure.set_harness(spec, path=harness_path)
                self._refresh_harness_panel()
                log.add_info(f"Loaded harness for recipe: {spec.name}")
            except Exception as exc:
                log.add_error(f"Could not load recipe harness: {exc}")
                return

        if (
            recipe.provider
            and recipe.model
            and (self.current_provider != recipe.provider or self.current_model != recipe.model)
        ):
            try:
                from superqode.providers.registry import PROVIDERS, ProviderCategory

                provider_def = PROVIDERS.get(recipe.provider)
                if provider_def and provider_def.category == ProviderCategory.LOCAL:
                    self._connect_local_mode(recipe.provider, recipe.model, log)
                else:
                    self._connect_byok_mode(recipe.provider, recipe.model, log)
            except Exception as exc:
                log.add_error(f"Could not connect recipe model: {exc}")

        if not prompt:
            log.add_error(f"Recipe {recipe.name} produced an empty prompt.")
            return
        if hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
            log.add_info(f"Running recipe: {recipe.name}")
            self._handle_message(prompt, log)
        else:
            self._set_prompt_prefill(prompt)
            log.add_info(f"Loaded recipe prompt: {recipe.name}")
            log.add_info("Connect a model, then press Enter to run it.")

    def _set_prompt_prefill(self, value: str) -> None:
        """Put text in the prompt input and focus it."""
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            input_widget.value = value
            input_widget.cursor_position = len(value)
            input_widget.focus()
        except Exception:
            pass


    # Matches a trailing "@token" mention being typed, anywhere in the prompt.
    # The "@" must start the line or follow whitespace so emails/handles inside a
    # word do not trigger the file picker.
    _MENTION_QUERY_RE = re.compile(r"(?:^|\s)@([\w./\-]*)$")


    @staticmethod
    def _runtime_completion_candidates() -> list[PromptCompletionCandidate]:
        """Runtime names for `:runtime <name>` completion, with install status."""
        from superqode.runtime import list_runtimes

        candidates = [
            PromptCompletionCandidate(
                value="list",
                label="list",
                description="Show all runtimes and their status",
                kind="runtime",
            )
        ]
        for info in list_runtimes():
            if info.usable:
                desc = info.description
            elif info.installed and not info.ready:
                desc = f"not ready — {info.status_detail or 'check setup'}"
            else:
                desc = f"not installed — {info.install_hint or 'optional extra required'}"
            candidates.append(
                PromptCompletionCandidate(
                    value=info.name,
                    label=info.name,
                    description=desc,
                    kind="runtime",
                )
            )
        return candidates


    @staticmethod
    def _candidate_after_prefix(
        value: str,
        prefix: str,
        candidates: list[PromptCompletionCandidate],
    ) -> list[PromptCompletionCandidate]:
        partial = value[len(prefix) :]
        matches: list[PromptCompletionCandidate] = []
        seen: set[str] = set()
        for candidate in sorted(candidates, key=lambda item: item.label.lower()):
            if not candidate.label.lower().startswith(partial.lower()):
                continue
            replacement = prefix + candidate.label
            if replacement == value or replacement in seen:
                continue
            seen.add(replacement)
            matches.append(
                PromptCompletionCandidate(
                    value=replacement,
                    label=candidate.label,
                    description=candidate.description,
                    kind=candidate.kind,
                )
            )
        return matches


    def _path_candidates_after_prefix(
        self,
        value: str,
        prefix: str,
        *,
        files_only: bool = False,
    ) -> list[PromptCompletionCandidate]:
        partial = value[len(prefix) :]
        return [
            PromptCompletionCandidate(
                value=prefix + path,
                label=path,
                description=description,
                kind="path",
            )
            for path, description in self._path_token_candidates(partial, files_only=files_only)
        ]


    @staticmethod
    def _path_token_candidates(partial: str, *, files_only: bool = False) -> list[tuple[str, str]]:
        expanded = partial.replace("\\ ", " ")
        raw_dir, raw_name = os.path.split(expanded)
        base = Path(raw_dir or ".").expanduser()
        if not base.is_absolute():
            base = Path.cwd() / base
        if not base.exists() or not base.is_dir():
            return []
        try:
            entries = sorted(
                base.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
            )
        except OSError:
            return []
        candidates: list[tuple[str, str]] = []
        for entry in entries:
            if raw_name and not entry.name.lower().startswith(raw_name.lower()):
                continue
            if entry.name.startswith(".") and not raw_name.startswith("."):
                continue
            if files_only and not entry.is_file():
                continue
            rel = os.path.join(raw_dir, entry.name) if raw_dir else entry.name
            if entry.is_dir():
                candidates.append((rel + "/", "directory"))
            else:
                candidates.append((rel, f"{entry.stat().st_size} bytes"))
            if len(candidates) >= 8:
                break
        return candidates


    @staticmethod
    def _static_command_candidates(value: str) -> list[PromptCompletionCandidate]:
        lowered = value.lower()
        if lowered in {":c", ":co", ":con", ":conn", ":conne", ":connec"}:
            commands = [
                ":connect",
                ":connect acp",
                ":connect antigravity",
                ":connect grok",
                ":connect byok",
                ":connect local",
            ]
            return [
                PromptCompletionCandidate(
                    value=command,
                    label=command,
                    description=SuperQodeApp._command_description(command),
                    kind="command",
                )
                for command in commands
                if command != value
            ]
        matches = [
            PromptCompletionCandidate(
                value=command,
                label=command,
                description=SuperQodeApp._command_description(command),
                kind="command",
            )
            for command in sorted(
                dict.fromkeys(COMMANDS),
                key=lambda command: SuperQodeApp._command_completion_sort_key(lowered, command),
            )
            if command.lower().startswith(lowered) and command != value
        ]
        if value in COMMANDS and matches:
            matches.insert(
                0,
                PromptCompletionCandidate(
                    value=value,
                    label=value,
                    description=SuperQodeApp._command_description(value),
                    kind="command",
                ),
            )
        return matches[:8]


    @staticmethod
    def _command_description(command: str) -> str:
        descriptions = {
            ":mcp": "manage Model Context Protocol servers",
            ":skills": "manage local project skills",
            ":recipe": "run reusable local workflows",
            ":recipes": "list and run reusable local workflows",
            ":attach": "stage files or URLs for the next prompt",
            ":prompt": "load a prompt file into the input buffer",
            ":model": "inspect or switch active provider/model",
            ":connect": "connect ACP, BYOK, or local runtime",
            ":exit": "exit SuperQode",
            ":quit": "exit SuperQode",
            ":vim": "optional Vim-style command helpers",
            ":set": "set optional TUI modes",
            ":w": "export the current transcript",
            ":e": "view a file",
            ":ls": "list saved sessions",
            ":switchboard": "open durable session graph, handoffs, approvals, and share tree",
            ":sw": "alias for :switchboard",
            ":factory": "switch models, harnesses, and routes without vendor lock-in",
            ":grep": "search the workspace",
            ":status": "show harness status",
            ":tools": "show tool profiles",
        }
        for prefix, description in descriptions.items():
            if command.startswith(prefix):
                return description
        return ""


    @staticmethod
    def _recipe_dirs() -> list[Path]:
        return [Path.cwd() / ".superqode" / "recipes", Path.cwd() / ".agents" / "recipes"]

    @staticmethod
    def _string_tuple(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, (list, tuple)):
            return tuple(str(item) for item in value if str(item).strip())
        return ()

    @staticmethod
    def _load_recipe_file(path: Path) -> LocalRecipe | None:
        try:
            raw = path.read_text(encoding="utf-8")
            if path.suffix.lower() == ".json":
                data = json.loads(raw)
            else:
                import yaml

                data = yaml.safe_load(raw) or {}
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        recipe_data = data.get("recipe") if isinstance(data.get("recipe"), dict) else data
        name = str(recipe_data.get("name") or path.stem).strip()
        if not name:
            return None
        model = str(recipe_data.get("model") or "").strip()
        provider = str(recipe_data.get("provider") or "").strip()
        if not provider and model:
            parsed_model = split_provider_model_ref(model)
            if parsed_model.provider:
                provider, model = parsed_model.provider, parsed_model.model
        variables = recipe_data.get("variables") or ()
        if isinstance(variables, dict):
            variables = tuple(str(key) for key in variables)
        return LocalRecipe(
            name=name,
            description=str(recipe_data.get("description") or "").strip(),
            path=path,
            prompt=str(recipe_data.get("prompt") or "").strip(),
            prompt_file=str(
                recipe_data.get("prompt_file") or recipe_data.get("promptFile") or ""
            ).strip(),
            provider=provider,
            model=model,
            mode=str(recipe_data.get("mode") or "").strip(),
            role=str(recipe_data.get("role") or "").strip(),
            skills=SuperQodeApp._string_tuple(recipe_data.get("skills")),
            attachments=SuperQodeApp._string_tuple(
                recipe_data.get("attachments") or recipe_data.get("attach")
            ),
            mcp_resources=SuperQodeApp._string_tuple(
                recipe_data.get("mcp_resources") or recipe_data.get("mcpResources")
            ),
            harness=str(
                recipe_data.get("harness") or recipe_data.get("harness_spec") or ""
            ).strip(),
            variables=SuperQodeApp._string_tuple(variables),
            raw=dict(recipe_data),
        )


    @staticmethod
    def _recipe_completion_candidates() -> list[PromptCompletionCandidate]:
        return [
            PromptCompletionCandidate(
                value=recipe.name,
                label=recipe.name,
                description=recipe.description,
                kind="recipe",
            )
            for recipe in SuperQodeApp._load_local_recipes().values()
        ]


    @staticmethod
    def _parse_mcp_resource_ref(ref: str) -> tuple[str, str] | None:
        if not ref.startswith("mcp://"):
            return None
        body = ref[len("mcp://") :]
        if "/" not in body:
            return None
        server_id, uri = body.split("/", 1)
        if not server_id or not uri:
            return None
        return server_id, uri

    @staticmethod
    def _extract_mcp_refs_from_text(text: str) -> tuple[str, list[str]]:
        """Remove inline MCP refs from prompt text and return them separately."""
        parts = text.split()
        refs: list[str] = []
        kept: list[str] = []
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("mcp://") and SuperQodeApp._parse_mcp_resource_ref(stripped):
                refs.append(stripped)
            else:
                kept.append(part)
        return " ".join(kept).strip(), refs

    @staticmethod
    def _truncate_mcp_content(text: str, remaining_chars: int) -> tuple[str, bool]:
        if len(text) <= remaining_chars:
            return text, False
        return text[: max(0, remaining_chars)].rstrip(), True

    async def _resolve_mcp_attachment_context(self, log: ConversationLog | None = None) -> str:
        """Read staged MCP resource refs into bounded prompt context."""
        refs = list(dict.fromkeys(getattr(self, "_current_mcp_refs", []) or []))
        if not refs:
            return ""
        try:
            from superqode.mcp.integration import get_mcp_manager

            manager = await get_mcp_manager()
        except Exception as exc:
            if log is not None:
                log.add_error(f"Could not initialize MCP manager for resource context: {exc}")
            return ""

        blocks: list[str] = []
        total_chars = 0
        max_resources = 5
        max_total_chars = 30000
        loaded = 0
        skipped = 0
        for ref in refs[:max_resources]:
            parsed = self._parse_mcp_resource_ref(ref)
            if parsed is None:
                skipped += 1
                continue
            server_id, uri = parsed
            try:
                content = await manager.read_resource(server_id, uri)
            except Exception as exc:
                skipped += 1
                blocks.append(
                    f'<mcp-resource server="{server_id}" uri="{uri}" error="{str(exc)}"></mcp-resource>'
                )
                continue
            if content is None:
                skipped += 1
                blocks.append(
                    f'<mcp-resource server="{server_id}" uri="{uri}" error="not found"></mcp-resource>'
                )
                continue
            text = getattr(content, "text", None)
            mime_type = getattr(content, "mime_type", None) or ""
            if not text:
                skipped += 1
                blob = getattr(content, "blob", None)
                reason = "binary content" if blob else "empty content"
                blocks.append(
                    f'<mcp-resource server="{server_id}" uri="{uri}" mime_type="{mime_type}" skipped="{reason}"></mcp-resource>'
                )
                continue
            remaining = max_total_chars - total_chars
            if remaining <= 0:
                skipped += 1
                break
            clipped, truncated = self._truncate_mcp_content(text, remaining)
            total_chars += len(clipped)
            truncated_attr = ' truncated="true"' if truncated else ""
            blocks.append(
                f'<mcp-resource server="{server_id}" uri="{uri}" mime_type="{mime_type}"{truncated_attr}>\n'
                f"{clipped}\n"
                "</mcp-resource>"
            )
            loaded += 1
            if truncated:
                break
        self._current_mcp_refs = []
        if log is not None and (loaded or skipped):
            message = f"Including {loaded} MCP resource(s)"
            if skipped:
                message += f"; {skipped} skipped or unavailable"
            log.add_info(message + ".")
        if not blocks:
            return ""
        return "<mcp-resources>\n" + "\n\n".join(blocks) + "\n</mcp-resources>"

    def _resolve_mcp_attachment_context_sync(self, log: ConversationLog | None = None) -> str:
        """Synchronous wrapper for thread-based agent runners."""
        try:
            return asyncio.run(self._resolve_mcp_attachment_context(log))
        except RuntimeError:
            # If a loop is already active in this thread, skip rather than deadlock.
            if log is not None:
                log.add_error("Could not resolve MCP resources from this runner.")
            return ""


    @staticmethod
    def _provider_description(provider_id: str) -> str:
        try:
            from superqode.providers.dynamic import resolve_provider_def

            provider = resolve_provider_def(provider_id)
            return provider.name if provider else ""
        except Exception:
            return ""


    @staticmethod
    def _configured_mcp_server_ids() -> list[str]:
        try:
            from superqode.mcp.config import load_mcp_config

            servers = load_mcp_config(Path.cwd() / ".superqode" / "mcp.json")
            return list(servers.keys())
        except Exception:
            return []


    @staticmethod
    def _all_provider_ids() -> list[str]:
        try:
            from superqode.providers.dynamic import all_provider_ids

            return all_provider_ids()
        except Exception:
            return []


    def _sync_attachment_prefill(self) -> None:
        if not getattr(self, "_attached_refs", None):
            self._set_prompt_prefill("")
            return
        prefill = " ".join(dict.fromkeys(self._attached_refs)) + " "
        self._set_prompt_prefill(prefill)


    def _attach_cmd(self, args: str, log: ConversationLog):
        """Insert file or URL references into the next prompt."""
        value = args.strip()
        if not value:
            self._show_command_output(log, self._render_attachments())
            return
        try:
            raw_refs = shlex.split(value)
        except ValueError as exc:
            log.add_error(f"Could not parse :attach arguments: {exc}")
            return
        action = raw_refs[0].lower() if raw_refs else ""
        if action in {"list", "ls", "show"}:
            self._show_command_output(log, self._render_attachments())
            return
        if action in {"clear", "reset"}:
            self._attached_refs = []
            self._set_prompt_prefill("")
            log.add_info("Cleared staged prompt references.")
            return
        if action in {"remove", "rm", "delete"}:
            if len(raw_refs) < 2:
                log.add_error("Usage: :attach remove <index|reference>")
                return
            target = raw_refs[1]
            refs = list(getattr(self, "_attached_refs", []))
            removed = None
            if target.isdigit():
                index = int(target) - 1
                if 0 <= index < len(refs):
                    removed = refs.pop(index)
            elif target in refs:
                refs.remove(target)
                removed = target
            if removed is None:
                log.add_error(f"Attachment not found: {target}")
                return
            self._attached_refs = refs
            self._sync_attachment_prefill()
            log.add_info(f"Removed staged reference: {removed}")
            return
        refs: list[str] = []
        for raw in raw_refs:
            if raw.startswith(("http://", "https://")):
                refs.append(raw)
                continue
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            if not path.exists():
                log.add_error(f"Cannot attach missing path: {raw}")
                continue
            try:
                refs.append("@" + str(path.relative_to(Path.cwd())))
            except ValueError:
                refs.append("@" + str(path))
        if not refs:
            return
        self._attached_refs.extend(refs)
        self._attached_refs = list(dict.fromkeys(self._attached_refs))
        self._sync_attachment_prefill()
        log.add_info(f"Attached {len(refs)} reference(s) to the next prompt.")

    _IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}

    def _is_image_path(self, value: str) -> bool:
        """True if value looks like a path to a readable image file."""
        try:
            path = Path(value.strip().strip("'\"")).expanduser()
            return path.suffix.lower() in self._IMAGE_EXTENSIONS and path.is_file()
        except Exception:
            return False

    def _grab_clipboard_image(self) -> Optional[Path]:
        """Best-effort capture of an image on the system clipboard to a temp PNG.

        Tries macOS ``pngpaste`` first, then an AppleScript fallback, then
        Pillow's ImageGrab (cross-platform). Returns the saved path or None.
        """
        import shutil
        import subprocess
        import sys
        import tempfile

        target_dir = Path.cwd() / ".superqode" / "pasted"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            target_dir = Path(tempfile.gettempdir())
        out = target_dir / f"clipboard-{int(time.time())}.png"

        if shutil.which("pngpaste"):
            try:
                result = subprocess.run(["pngpaste", str(out)], capture_output=True, timeout=10)
                if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
                    return out
            except Exception:
                pass

        if sys.platform == "darwin":
            script = (
                "set theData to the clipboard as «class PNGf»\n"
                f'set theFile to open for access POSIX file "{out}" with write permission\n'
                "write theData to theFile\nclose access theFile"
            )
            try:
                result = subprocess.run(
                    ["osascript", "-e", script], capture_output=True, timeout=10
                )
                if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
                    return out
            except Exception:
                pass

        try:
            from PIL import ImageGrab  # type: ignore

            image = ImageGrab.grabclipboard()
            if image is not None and hasattr(image, "save"):
                image.save(out, "PNG")
                if out.exists() and out.stat().st_size > 0:
                    return out
        except Exception:
            pass
        return None

    def _stage_image_attachment(
        self, path: Path, log: ConversationLog, *, source: str = ""
    ) -> bool:
        """Stage an image file for the next prompt and inform the user."""
        try:
            ref = "@" + str(path.relative_to(Path.cwd()))
        except ValueError:
            ref = "@" + str(path)
        if not hasattr(self, "_attached_refs"):
            self._attached_refs = []
        self._attached_refs.append(ref)
        self._attached_refs = list(dict.fromkeys(self._attached_refs))
        self._sync_attachment_prefill()
        label = f" ({source})" if source else ""
        log.add_success(f"🖼  Attached image{label}: {path.name}")
        model = getattr(self, "current_model", "") or ""
        if model and not self._model_supports_vision(model):
            log.add_info(
                "Note: the active model may not support images. Connect a vision model to use it."
            )
        return True


    def _handle_paste_image(self, args: str, log: ConversationLog):
        """`:paste` — attach an image from a path or the system clipboard."""
        value = (args or "").strip().strip("'\"")
        if value:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            if self._is_image_path(str(path)):
                self._stage_image_attachment(path, log, source="path")
            else:
                log.add_error(f"Not a readable image: {value}")
            return
        image_path = self._grab_clipboard_image()
        if image_path is not None:
            self._stage_image_attachment(image_path, log, source="clipboard")
        else:
            log.add_info(
                "No image found on the clipboard. Copy an image, then run :paste — "
                "or use :paste <path-to-image>."
            )

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

    def _prompt_file_cmd(self, args: str, log: ConversationLog):
        """Load a prompt file into the input buffer."""
        value = args.strip()
        if not value:
            log.add_info("Usage: :prompt <file>")
            return
        try:
            parts = shlex.split(value)
        except ValueError as exc:
            log.add_error(f"Could not parse :prompt arguments: {exc}")
            return
        if not parts:
            log.add_info("Usage: :prompt <file>")
            return
        path = Path(parts[0]).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists() or not path.is_file():
            log.add_error(f"Prompt file not found: {path}")
            return
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            log.add_error(f"Could not read prompt file: {exc}")
            return
        self._set_prompt_prefill(content)
        log.add_info(f"Loaded prompt file into input: {path}")


    async def _add_mcp_server_config(
        self,
        manager,
        server_id: str,
        target: str,
    ) -> tuple[bool, str]:
        """Persist and register an MCP server config."""
        from superqode.mcp.config import load_mcp_config, save_mcp_config

        config = self._mcp_server_config_from_target(server_id, target)
        servers = load_mcp_config()
        if server_id in servers:
            return False, f"MCP server already exists: {server_id}"
        servers[server_id] = config
        save_mcp_config(servers)
        manager.add_server(config)
        return True, f"Saved MCP server {server_id}."

    @staticmethod
    def _resolve_mcp_resource_ref(manager, target: str):
        """Resolve a user-facing MCP resource reference to a resource object."""
        target = target.strip()
        resources = list(manager.list_all_resources())
        if not target:
            return None
        if target.isdigit():
            index = int(target) - 1
            return resources[index] if 0 <= index < len(resources) else None
        if target.startswith("mcp://"):
            target = target[len("mcp://") :]
        server_hint = ""
        resource_hint = target
        if "/" in target:
            server_hint, resource_hint = target.split("/", 1)

        matches = []
        lowered = resource_hint.lower()
        for resource in resources:
            if server_hint and resource.server_id.lower() != server_hint.lower():
                continue
            candidates = [
                resource.uri,
                resource.name,
                f"{resource.server_id}/{resource.uri}",
                f"{resource.server_id}/{resource.name}",
            ]
            if any(candidate and candidate.lower() == lowered for candidate in candidates):
                matches.append(resource)
                continue
            if any(candidate and candidate.lower().startswith(lowered) for candidate in candidates):
                matches.append(resource)
        return matches[0] if len(matches) == 1 else None


    def _show_mcp_doctor(self, manager, server_filter: str, log: ConversationLog) -> None:
        """Render MCP server configuration and runtime diagnostics."""
        configs = manager.get_server_configs()
        if server_filter:
            configs = {server_filter: configs[server_filter]} if server_filter in configs else {}
        t = Text()
        t.append("\n  🔗 ", style=f"bold {THEME['cyan']}")
        t.append("MCP Doctor\n\n", style=f"bold {THEME['text']}")
        if not configs:
            t.append("  No matching MCP server configured.\n", style=THEME["warning"])
            t.append("  Add one with :mcp add <name> <url|command>.\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return
        summary = manager.get_status_summary()
        for server_id, config in configs.items():
            conn = manager.get_connection(server_id)
            state = manager.get_connection_state(server_id).value
            config_obj = config.config
            transport = getattr(config_obj, "transport", type(config_obj).__name__)
            if hasattr(config_obj, "url"):
                target = getattr(config_obj, "url", "")
            else:
                target = " ".join(
                    [getattr(config_obj, "command", ""), *getattr(config_obj, "args", [])]
                )
            server_summary = summary.get("servers", {}).get(server_id, {})
            style = (
                THEME["success"]
                if state == "connected"
                else THEME["warning"]
                if state == "error"
                else THEME["muted"]
            )
            t.append(f"  {server_id}\n", style=f"bold {THEME['cyan']}")
            t.append("    state      ", style=THEME["muted"])
            t.append(f"{state}\n", style=style)
            t.append("    transport  ", style=THEME["muted"])
            t.append(f"{transport}\n", style=THEME["text"])
            t.append("    target     ", style=THEME["muted"])
            t.append(f"{target or '-'}\n", style=THEME["text"])
            t.append("    enabled    ", style=THEME["muted"])
            t.append(f"{config.enabled}  auto_connect={config.auto_connect}\n", style=THEME["text"])
            t.append("    exposed    ", style=THEME["muted"])
            t.append(
                f"{server_summary.get('tools', 0)} tools, {server_summary.get('resources', 0)} resources, {server_summary.get('prompts', 0)} prompts\n",
                style=THEME["text"],
            )
            error = getattr(conn, "error_message", None) if conn else server_summary.get("error")
            if error:
                t.append("    error      ", style=THEME["muted"])
                t.append(f"{error}\n", style=THEME["error"])
            t.append("\n")
        t.append("  Commands: ", style=THEME["muted"])
        t.append(":mcp connect <server>", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":mcp reconnect <server>", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _get_session_manager(self):
        """Get a local JSONL session manager."""
        from superqode.agent.session_manager import SessionManager

        return SessionManager(storage_dir=".superqode/sessions")

    def _current_session_id(self) -> str:
        """Resolve the active or most-recent local session id."""
        try:
            if hasattr(self, "_pure_mode") and self._pure_mode:
                sid = self._pure_mode.get_current_session_id()
                if sid:
                    return sid
        except Exception:
            pass
        try:
            sessions = self._get_session_manager().list_all_sessions()
            if sessions:
                return sessions[0].session_id
        except Exception:
            pass
        return ""

    def _handle_session(self, args: str, log: ConversationLog):
        """Session subcommands: `:session` (info) and `:session rename <name>`."""
        parts = (args or "").strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        manager = self._get_session_manager()

        if sub in ("rename", "name", "title"):
            rest = parts[1].strip() if len(parts) > 1 else ""
            if not rest:
                log.add_info("Usage: :session rename [<id>] <new title>")
                return
            # Optional leading id/prefix: "<id> <title...>".
            sid = ""
            tokens = rest.split(maxsplit=1)
            if len(tokens) == 2:
                candidate = tokens[0]
                matches = [
                    s for s in manager.list_all_sessions() if s.session_id.startswith(candidate)
                ]
                if len(matches) == 1:
                    sid = matches[0].session_id
                    rest = tokens[1].strip()
            if not sid:
                sid = self._current_session_id()
            if not sid:
                log.add_error("No session to rename yet. Start a conversation first.")
                return
            metadata = manager.get_session_info(sid)
            if metadata is None:
                log.add_error(f"Session not found: {sid[:8]}")
                return
            metadata.title = rest
            try:
                manager.store._save_metadata(metadata)
            except Exception as exc:
                log.add_error(f"Could not save session title: {exc}")
                return
            log.add_success(f"Renamed session {sid[:8]} → “{rest}”")
            return

        # No/unknown subcommand: show current session info.
        sid = self._current_session_id()
        if not sid:
            log.add_info("No active session. Connect and send a message, or :sessions to list.")
            return
        metadata = manager.get_session_info(sid)
        t = Text()
        t.append("\n  📂 ", style=f"bold {THEME['purple']}")
        t.append("Current Session\n\n", style=f"bold {THEME['text']}")
        t.append("  Id      ", style=THEME["muted"])
        t.append(f"{sid[:12]}\n", style=f"bold {THEME['cyan']}")
        if metadata is not None:
            t.append("  Title   ", style=THEME["muted"])
            t.append(f"{metadata.title or '(unnamed)'}\n", style=THEME["text"])
            t.append("  Model   ", style=THEME["muted"])
            t.append(
                f"{metadata.provider or '-'} / {metadata.model or 'unknown'}\n", style=THEME["text"]
            )
            t.append("  Messages ", style=THEME["muted"])
            t.append(f"{metadata.message_count}\n", style=THEME["text"])
        t.append("\n  ", style="")
        t.append(":session rename <name>", style=f"bold {THEME['cyan']}")
        t.append(" to label it.\n", style=THEME["muted"])
        log.write(t)

    def _handle_update(self, args: str, log: ConversationLog):
        """Check whether a newer SuperQode release is available on PyPI."""
        from importlib.metadata import version as _pkg_version

        try:
            current = _pkg_version("superqode")
        except Exception:
            current = "unknown"
        log.add_info(f"Installed SuperQode version: {current}. Checking for updates…")
        self.run_worker(self._check_update_worker(current, log), exclusive=False)

    async def _check_update_worker(self, current: str, log: ConversationLog):
        """Fetch the latest version from PyPI without blocking the UI."""
        import asyncio
        import json as _json
        import urllib.request

        def _fetch() -> str:
            with urllib.request.urlopen("https://pypi.org/pypi/superqode/json", timeout=8) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            return str(data.get("info", {}).get("version", ""))

        try:
            latest = await asyncio.to_thread(_fetch)
        except Exception as exc:
            self._call_ui(log.add_error, f"Could not check for updates: {exc}")
            return
        if not latest:
            self._call_ui(log.add_info, "Could not determine the latest version.")
            return
        if self._version_is_newer(latest, current):
            t = Text()
            t.append("\n  ⬆ ", style=f"bold {THEME['success']}")
            t.append(f"Update available: {current} → {latest}\n", style=f"bold {THEME['text']}")
            t.append("  Upgrade with ", style=THEME["muted"])
            t.append("uv tool upgrade superqode", style=f"bold {THEME['cyan']}")
            t.append(" or ", style=THEME["muted"])
            t.append("uv tool upgrade superqode", style=f"bold {THEME['cyan']}")
            t.append("\n", style="")
            self._call_ui(log.write, t)
        else:
            self._call_ui(log.add_success, f"SuperQode is up to date ({current}).")

    @staticmethod
    def _version_is_newer(latest: str, current: str) -> bool:
        """Compare dotted version strings; True if latest > current."""

        def parse(v: str) -> tuple:
            out = []
            for part in str(v).split("."):
                num = "".join(ch for ch in part if ch.isdigit())
                out.append(int(num) if num else 0)
            return tuple(out)

        try:
            return parse(latest) > parse(current)
        except Exception:
            return False

    def _show_sessions(self, log: ConversationLog):
        """Show recent local coding sessions."""
        manager = self._get_session_manager()
        sessions = manager.list_all_sessions()

        t = Text()
        t.append("\n  📂 ", style=f"bold {THEME['purple']}")
        t.append("Recent Sessions\n\n", style=f"bold {THEME['purple']}")

        if not sessions:
            t.append("  No sessions found yet.\n", style=THEME["muted"])
            t.append("  Connect with ", style=THEME["muted"])
            t.append(":connect byok", style=THEME["cyan"])
            t.append(" or ", style=THEME["muted"])
            t.append(":connect local", style=THEME["cyan"])
            t.append(" and send a message to create one.\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        for session in sessions[:12]:
            display_id = session.session_id[:8]
            model = session.model or "unknown"
            provider = session.provider or "-"
            t.append(f"  {display_id:<10}", style=f"bold {THEME['cyan']}")
            t.append(f"{provider:<14}", style=THEME["success"])
            t.append(f"{model:<28}", style=THEME["text"])
            t.append(f"{session.message_count:>3} msgs  ", style=THEME["muted"])
            t.append(f"{session.updated_at[:19]}\n", style=THEME["dim"])

        t.append("\n  Use ", style=THEME["muted"])
        t.append("/resume <id>", style=THEME["cyan"])
        t.append(" to continue or ", style=THEME["muted"])
        t.append("/fork <optional-new-id>", style=THEME["cyan"])
        t.append(" to branch the active session.\n", style=THEME["muted"])
        t.append("  Use ", style=THEME["muted"])
        t.append(":switchboard", style=THEME["cyan"])
        t.append(" for graph, handoff, approvals, and share-tree actions.\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _handle_sessions_command(self, args: str, log: ConversationLog) -> None:
        """Handle :sessions subcommands without stealing :session."""
        try:
            tokens = shlex.split((args or "").strip())
        except ValueError as exc:
            log.add_error(f"Could not parse :sessions arguments: {exc}")
            return

        if not tokens:
            self._show_sessions(log)
            return

        subcommand = tokens[0].lower()
        rest = tokens[1:]
        if subcommand in {"resume", "switch", "select"}:
            if rest:
                self._handle_resume_session(" ".join(rest), log)
            else:
                self._show_session_resume_picker(log)
            return
        if subcommand in {"list", "ls", "recent"}:
            self._show_sessions(log)
            return
        switchboard_subcommands = {
            "graph",
            "tree",
            "switchboard",
            "info",
            "history",
            "children",
            "handoff",
            "fork-agent",
            "approvals",
            "share-tree",
        }
        if subcommand in switchboard_subcommands:
            self._handle_switchboard(" ".join(tokens), log)
            return

        self._run_cli_passthrough(["sessions", *tokens], log, "Sessions command")


    def _handle_session_resume_selection(self, selection: str, log: ConversationLog) -> bool:
        """Handle a typed number, id prefix, or title fragment in the resume picker."""
        sessions = getattr(self, "_session_resume_list", [])
        if not sessions:
            return False
        choice = (selection or "").strip()
        if not choice:
            self.action_select_highlighted_session_resume()
            return True

        target = None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                target = sessions[idx]
        if target is None:
            lowered = choice.lower()
            matches = [
                session
                for session in sessions
                if session.session_id.lower().startswith(lowered)
                or lowered in (session.title or "").lower()
            ]
            if len(matches) == 1:
                target = matches[0]
            elif len(matches) > 1:
                log.add_error(f"Selection is ambiguous: {choice}")
                return True
        if target is None:
            log.add_error(f"Session not found in picker: {choice}")
            return True

        self._handle_resume_session(target.session_id, log)
        return True

    def _show_session_tree(self, log: ConversationLog):
        """Show saved sessions grouped by parent/fork relationship."""
        self._handle_switchboard("graph", log)


    def _handle_factory(self, args: str, log: ConversationLog) -> None:
        """Software Factory commands for model/harness/provider independence."""
        try:
            tokens = shlex.split((args or "").strip())
        except ValueError as exc:
            log.add_error(f"Could not parse :factory arguments: {exc}")
            return
        subcommand = tokens[0].lower() if tokens else "status"
        rest = tokens[1:]
        if subcommand in {"", "status"}:
            self._factory_status(rest, log)
        elif subcommand in {"help", "?"}:
            self._factory_help(log)
        elif subcommand in {"policy"}:
            self._factory_policy(log)
        elif subcommand in {"init-policy", "init"}:
            self._factory_init_policy(rest, log)
        elif subcommand in {"routes", "route", "models"}:
            self._factory_routes(log)
        elif subcommand in {"mode", "policy"}:
            self._factory_mode(rest, log)
        elif subcommand in {"switch-model", "model"}:
            self._factory_switch_model(rest, log)
        elif subcommand in {"switch-harness", "harness"}:
            self._factory_switch_harness(rest, log)
        elif subcommand in {"fork-model"}:
            self._factory_fork_model(rest, log)
        elif subcommand in {"fork-harness"}:
            self._factory_fork_harness(rest, log)
        elif subcommand in {"lineage", "timeline"}:
            self._factory_lineage(rest, log)
        else:
            self._run_cli_passthrough(["factory", *tokens], log, "Factory command")

    def _factory(self):
        from superqode.session.factory import SoftwareFactory

        return SoftwareFactory(storage_dir=".superqode/sessions")


    def _handle_share(self, args: str, log: ConversationLog) -> None:
        """Create, list, import, and revoke local share artifacts."""
        try:
            tokens = shlex.split((args or "").strip())
        except ValueError as exc:
            log.add_error(f"Could not parse :share arguments: {exc}")
            return
        subcommand = tokens[0].lower() if tokens else "status"
        rest = tokens[1:]
        if subcommand in {"", "status"}:
            self._show_share_status(log)
        elif subcommand in {"create", "pack", "package"}:
            self._share_create(rest, log)
        elif subcommand == "export":
            self._share_export(rest, log)
        elif subcommand in {"import", "load"}:
            self._share_import(rest, log)
        elif subcommand in {"list", "ls"}:
            self._share_list(log)
        elif subcommand in {"revoke", "delete", "rm"}:
            self._share_revoke(rest, log)
        else:
            log.add_info("Usage: :share [create|export|import|list|revoke] [session-id|path]")

    def _share_dir(self) -> Path:
        return Path(".superqode") / "shares"

    def _show_share_status(self, log: ConversationLog) -> None:
        current_id = self._current_session_id()
        share_count = len(list(self._share_dir().glob("*.superqode-share.json")))
        t = Text()
        t.append("\n  Share\n\n", style=f"bold {THEME['purple']}")
        t.append("  Mode     ", style=THEME["muted"])
        t.append("local/offline artifacts\n", style=THEME["text"])
        t.append("  Current  ", style=THEME["muted"])
        t.append(
            f"{current_id or 'none'}\n", style=THEME["cyan"] if current_id else THEME["warning"]
        )
        t.append("  Artifacts ", style=THEME["muted"])
        t.append(f"{share_count} in .superqode/shares\n\n", style=THEME["text"])
        t.append("  Commands:\n", style=THEME["muted"])
        t.append("    :share create [--tree] [session] [path]\n", style=THEME["cyan"])
        t.append("    :share export [session] [path] [--json|--markdown]\n", style=THEME["cyan"])
        t.append("    :share import <artifact> [new-session-id]\n", style=THEME["cyan"])
        t.append("    :share list  |  :share revoke <artifact>\n", style=THEME["cyan"])
        self._show_command_output(log, t)

    def _resolve_share_session_id(self, value: str = "") -> str:
        from superqode.headless import resolve_session_id

        requested = (value or "").strip()
        if requested:
            return resolve_session_id(requested, ".superqode/sessions")
        current_id = self._current_session_id()
        if not current_id:
            raise ValueError("No active session. Use :sessions to choose one.")
        return resolve_session_id(current_id, ".superqode/sessions")

    def _share_create(self, tokens: list[str], log: ConversationLog) -> None:
        include_tree = False
        cleaned: list[str] = []
        for token in tokens:
            if token.lower() in {"--tree", "tree"}:
                include_tree = True
            else:
                cleaned.append(token)
        session_arg, path_arg = self._parse_share_session_and_path(cleaned)
        try:
            session_id = self._resolve_share_session_id(session_arg)
            artifact_path = self._write_share_artifact(
                session_id,
                path_arg,
                include_tree=include_tree,
            )
        except Exception as exc:
            log.add_error(f"Could not create share artifact: {exc}")
            return
        label = "share-tree" if include_tree else "share"
        log.add_success(f"Created {label} artifact -> {artifact_path}")
        log.add_info(
            "Send this file to another SuperQode user; they can import it with :share import."
        )

    def _share_export(self, tokens: list[str], log: ConversationLog) -> None:
        from superqode.headless import export_session

        fmt = "markdown"
        cleaned: list[str] = []
        for token in tokens:
            lowered = token.lower()
            if lowered in {"--json", "json"}:
                fmt = "json"
            elif lowered in {"--markdown", "--md", "markdown", "md"}:
                fmt = "markdown"
            else:
                cleaned.append(token)
        session_arg, path_arg = self._parse_share_session_and_path(cleaned)
        try:
            session_id = self._resolve_share_session_id(session_arg)
            content = export_session(session_id, fmt=fmt, storage_dir=".superqode/sessions")
            suffix = ".json" if fmt == "json" else ".md"
            out_path = self._share_output_path(session_id, path_arg, suffix, stem="session")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            log.add_error(f"Could not export share file: {exc}")
            return
        log.add_success(f"Exported {fmt} session -> {out_path}")

    @staticmethod
    def _parse_share_session_and_path(tokens: list[str]) -> tuple[str, str]:
        if not tokens:
            return "", ""
        if len(tokens) == 1:
            token = tokens[0]
            suffix = Path(token).suffix
            if suffix or "/" in token or token.startswith("."):
                return "", token
            return token, ""
        return tokens[0], tokens[1]


    def _share_output_path(
        self,
        session_id: str,
        path_arg: str,
        suffix: str,
        *,
        stem: str,
    ) -> Path:
        if path_arg:
            out_path = Path(path_arg).expanduser()
            if not out_path.name.lower().endswith(suffix.lower()):
                out_path = out_path.with_suffix(suffix)
            return out_path
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in session_id)
        return self._share_dir() / f"{stem}-{safe_id}-{stamp}{suffix}"

    def _share_import(self, tokens: list[str], log: ConversationLog) -> None:
        if not tokens:
            log.add_info("Usage: :share import <artifact.superqode-share.json> [new-session-id]")
            return
        path = Path(tokens[0]).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        new_id = tokens[1] if len(tokens) > 1 else ""
        try:
            imported_id = self._import_share_artifact(path, new_id)
        except Exception as exc:
            log.add_error(f"Could not import share artifact: {exc}")
            return
        log.add_success(f"Imported shared session -> {imported_id}")
        log.add_info(f"Resume it with :resume {imported_id[:8]}")

    def _import_share_artifact(self, path: Path, new_session_id: str = "") -> str:
        from superqode.session.share_artifacts import import_share_artifact

        return import_share_artifact(
            path,
            new_session_id=new_session_id,
            storage_dir=".superqode/sessions",
        )

    def _share_list(self, log: ConversationLog) -> None:
        from superqode.session.share_artifacts import list_share_artifacts

        artifacts = list_share_artifacts(self._share_dir())
        t = Text()
        t.append("\n  Local Share Artifacts\n\n", style=f"bold {THEME['purple']}")
        if not artifacts:
            t.append("  No share artifacts found.\n", style=THEME["muted"])
            t.append("  Create one with ", style=THEME["muted"])
            t.append(":share create", style=THEME["cyan"])
            t.append(".\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return
        for index, artifact in enumerate(artifacts, 1):
            t.append(f"  [{index}] ", style=THEME["dim"])
            t.append(artifact.path.name, style=f"bold {THEME['cyan']}")
            if artifact.source_session_id:
                t.append(f"  session {artifact.source_session_id[:8]}", style=THEME["muted"])
            t.append("\n")
        t.append("\n  Import: ", style=THEME["muted"])
        t.append(":share import .superqode/shares/<file>", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _share_revoke(self, tokens: list[str], log: ConversationLog) -> None:
        from superqode.session.share_artifacts import revoke_share_artifact

        if not tokens:
            log.add_info("Usage: :share revoke <artifact-name-or-path>")
            return
        try:
            path = revoke_share_artifact(tokens[0], self._share_dir())
        except FileNotFoundError:
            log.add_error(f"Share artifact not found: {tokens[0]}")
            return
        except Exception as exc:
            log.add_error(f"Could not revoke share artifact: {exc}")
            return
        log.add_success(f"Revoked local share artifact -> {path}")

    def _handle_trust(self, args: str, log: ConversationLog) -> None:
        """Show or change local trust for the current project."""
        from superqode.project_trust import set_project_trust

        arg = (args or "").strip().lower()
        if arg in {"yes", "on", "trust", "trusted"}:
            record = set_project_trust(Path.cwd(), True, note="trusted from TUI")
            log.add_success(f"Trusted project -> {record.path}")
            return
        if arg in {"no", "off", "untrust", "untrusted"}:
            record = set_project_trust(Path.cwd(), False, note="untrusted from TUI")
            log.add_success(f"Marked project untrusted -> {record.path}")
            return
        if arg not in {"", "status", "doctor"}:
            log.add_info("Usage: :trust [status|yes|no|doctor]")
            return
        self._show_trust_status(log, doctor=(arg == "doctor"))

    def _show_trust_status(self, log: ConversationLog, *, doctor: bool = False) -> None:
        from superqode.project_trust import (
            get_project_trust,
            project_risk_signals,
            trust_store_path,
        )

        record = get_project_trust(Path.cwd())
        signals = project_risk_signals(Path.cwd())
        trusted = record.trusted
        t = Text()
        t.append("\n  Project Trust\n\n", style=f"bold {THEME['purple']}")
        t.append("  Project  ", style=THEME["muted"])
        t.append(f"{record.path}\n", style=THEME["text"])
        t.append("  Status   ", style=THEME["muted"])
        t.append(
            "trusted\n" if trusted else "untrusted\n",
            style=THEME["success"] if trusted else THEME["warning"],
        )
        if record.trusted_at:
            t.append("  Since    ", style=THEME["muted"])
            t.append(f"{record.trusted_at}\n", style=THEME["dim"])
        t.append("  Store    ", style=THEME["muted"])
        t.append(f"{trust_store_path()}\n", style=THEME["dim"])
        if signals:
            t.append("\n  Trust-sensitive files:\n", style=THEME["muted"])
            for signal_name in signals:
                t.append(
                    f"    - {signal_name}\n",
                    style=THEME["warning"] if not trusted else THEME["text"],
                )
        elif doctor:
            t.append(
                "\n  No project-local plugins, MCP config, or hooks detected.\n",
                style=THEME["muted"],
            )
        t.append("\n  Commands: ", style=THEME["muted"])
        t.append(":trust yes", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":trust no", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":trust doctor", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _ensure_project_trusted_for(self, log: ConversationLog, action: str) -> bool:
        """Require project trust before enabling project-local executable surfaces."""
        from superqode.project_trust import get_project_trust

        record = get_project_trust(Path.cwd())
        if record.trusted:
            return True
        log.add_error(f"Project is untrusted; refusing to {action}.")
        log.add_info(
            "Review this workspace, then run :trust yes to allow project-local plugins/MCP."
        )
        return False

    def _ensure_pure_mode(self):
        """Ensure the PureMode object exists for session operations."""
        if not hasattr(self, "_pure_mode"):
            from superqode.pure_mode import PureMode

            self._pure_mode = PureMode()
        return self._pure_mode

    def _install_pure_permission_bridge(self, pure, log: ConversationLog) -> None:
        """Route self-contained runtime approval callbacks through the TUI prompt."""

        def on_permission_request(tool_name: str, arguments: dict) -> bool:
            if getattr(self, "_active_plan_mode_for_current_message", False):
                try:
                    self._call_ui(
                        log.add_info,
                        f"Plan mode blocked runtime approval for {tool_name}.",
                    )
                except Exception:
                    pass
                return False
            return self._request_runtime_permission(tool_name, arguments, log)

        pure.on_permission_request = on_permission_request


    def _set_status_runtime(self, runtime_name: str) -> None:
        """Show the active runtime in the visible status bar (hidden for builtin)."""
        try:
            from superqode.app.widgets import ColorfulStatusBar

            display = "" if runtime_name in ("", "builtin") else runtime_name
            self.query_one("#status-bar", ColorfulStatusBar).active_runtime = display
        except Exception:  # noqa: BLE001
            pass

    def _refresh_plan_status_badge(self) -> None:
        """Show whether plan mode is active or awaiting a decision."""
        try:
            from superqode.app.widgets import ColorfulStatusBar

            state = ""
            pending = getattr(self, "_pending_plan_request", "").strip()
            pending_status = getattr(self, "_pending_plan_status", "")
            if pending and pending_status == "pending":
                state = "pending"
            elif getattr(self, "_active_plan_mode_for_current_message", False):
                state = "active"
            elif getattr(self, "_plan_mode_enabled", False):
                state = "ON"
            self.query_one("#status-bar", ColorfulStatusBar).plan_state = state
        except Exception:  # noqa: BLE001
            pass
        self._refresh_prompt_mode_label()

    def _prompt_interaction_mode(self) -> tuple[str, str]:
        """Return the status mode and matching placeholder."""
        if getattr(self, "_chat_mode", False):
            return "chat", "Chat with the connected model. No repo context or tools."
        if getattr(self, "_plan_mode_enabled", False) or getattr(
            self, "_active_plan_mode_for_current_message", False
        ):
            return "plan", "Plan first. No native tools until you approve execution."
        return "build", SelectionAwareInput.DEFAULT_PLACEHOLDER

    def _refresh_prompt_mode_label(self) -> None:
        """Keep the prompt label in sync with Chat, Build, and Plan modes."""
        status_mode, placeholder = self._prompt_interaction_mode()
        try:
            symbol = self.query_one("#prompt-symbol")
            symbol.update("<>")
        except Exception:  # noqa: BLE001
            pass
        try:
            from superqode.app.widgets import ColorfulStatusBar

            self.query_one("#status-bar", ColorfulStatusBar).interaction_mode = status_mode
        except Exception:  # noqa: BLE001
            pass
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            if input_widget.placeholder not in {
                "Approve tool? y / n / a",
                "Answer the agent question...",
            }:
                input_widget.placeholder = placeholder
        except Exception:  # noqa: BLE001
            pass


    def _runtime_cmd(self, args: str, log) -> None:
        """Handle :runtime / :runtime list / :runtime <name>.

        With no args: open the RuntimeDialog picker.
        With "list":  print an inline status table.
        With a name:  swap runtime mid-session (env + disconnect; next message reconnects).
        """
        import os as _os
        from superqode.runtime import list_runtimes, resolve_runtime_name

        sub = args.strip().lower()

        if sub.startswith("doctor"):
            self._run_cli_group("runtime", args, log, "Runtime command")
            return

        if sub == "list":
            runtimes = list_runtimes()
            if any(not info.installed and info.install_hint for info in runtimes):
                from superqode.providers.env_introspect import environment_info

                env = environment_info()
                log.add_info(
                    f"SuperQode is running from: {env.label} ({env.python}); "
                    f"install commands target {env.target}."
                )
            for info in runtimes:
                marker = "▸" if info.name == resolve_runtime_name() else " "
                if not info.installed:
                    status = f"missing — {info.install_hint or ''}"
                elif not info.implemented:
                    status = "stub"
                elif not info.ready:
                    status = f"unavailable — {info.status_detail or ''}"
                else:
                    status = "ready"
                log.add_info(f"  {marker} {info.name:18} {status:30} {info.description}")
            return

        if not sub:
            # Bare `:runtime` shows the interactive runtime picker.
            self._show_runtime_picker(log)
            return

        # Direct switch by name.
        info_by_name = {r.name: r for r in list_runtimes()}
        if sub not in info_by_name:
            log.add_error(f"Unknown runtime '{sub}'. Known: {', '.join(sorted(info_by_name))}")
            return
        info = info_by_name[sub]
        if not info.installed:
            log.add_error(self._runtime_install_message(sub, info.install_hint))
            return
        if not info.implemented:
            log.add_error(f"Runtime '{sub}' is a stub and not yet usable.")
            return
        if not info.ready:
            log.add_error(f"Runtime '{sub}' is not ready: {info.status_detail or 'check setup'}")
            return

        # A friendly setup path for the Codex subscription: someone without
        # the product installed should get install steps, not a stack trace
        # from a missing ~/.codex login.
        if sub == "codex-sdk":
            codex_auth = Path.home() / ".codex" / "auth.json"
            has_env_key = bool(
                _os.environ.get("OPENAI_API_KEY") or _os.environ.get("CODEX_API_KEY")
            )
            if not codex_auth.exists() and not has_env_key:
                if shutil.which("codex") is None:
                    log.add_error(
                        "The Codex CLI is not installed, so the Codex "
                        "subscription route is unavailable."
                    )
                    log.add_info("Install it:  npm i -g @openai/codex")
                else:
                    log.add_error(
                        "Codex is installed but not signed in (~/.codex/auth.json missing)."
                    )
                log.add_info("Sign in with `codex login`, then re-run :connect codex.")
                log.add_info("No subscription? Use BYOK instead: :connect byok openai <model>")
                return

        current = resolve_runtime_name()
        if sub in self._SELF_CONTAINED_RUNTIMES:
            existing = getattr(self, "_pure_mode", None)
            if (
                existing is not None
                and getattr(existing, "runtime_name", "") == sub
                and getattr(existing.session, "connected", False)
                and Path(getattr(existing.session, "working_directory", Path.cwd())).resolve()
                == Path.cwd().resolve()
                and getattr(existing, "_runtime", None) is not None
            ):
                self._install_pure_permission_bridge(existing, log)
                _os.environ["SUPERQODE_RUNTIME"] = sub
                self._set_status_runtime(sub)
                if sub == "codex-sdk":
                    self.run_worker(self._resolve_codex_active_model(log), exclusive=False)
                    log.add_info("Already connected via codex-sdk; reusing warm Codex app-server.")
                else:
                    log.add_info(f"Already connected via {sub}; reusing the active session.")
                return
        # For self-contained runtimes, ``current`` only reflects the env/runtime
        # name (which --connect/SUPERQODE_RUNTIME may already have set) — not
        # whether a session is actually connected. The connected case is handled
        # above; reaching here means NOT connected, so fall through to
        # auto-connect instead of short-circuiting.
        if sub == current and sub not in self._SELF_CONTAINED_RUNTIMES:
            log.add_info(f"Already on runtime '{sub}'.")
            return

        _os.environ["SUPERQODE_RUNTIME"] = sub
        if hasattr(self, "_pure_mode") and self._pure_mode is not None:
            try:
                self._pure_mode.disconnect()
            except Exception:  # noqa: BLE001 — best-effort
                pass
            self._pure_mode.runtime_name = sub
        # Update the status bar badge if it's mounted.
        # Update the visible status-bar runtime badge. A non-self-contained swap
        # clears any stale model; the self-contained path below sets it.
        self._set_status_runtime(sub)
        if sub not in self._SELF_CONTAINED_RUNTIMES:
            self._set_status_model("")
        # Self-contained runtimes (e.g. codex-sdk) bring their own model + auth
        # (via their local config like ~/.codex) and don't need a BYOK key or an
        # ACP connect. Auto-connect so the user can start chatting immediately;
        # model="" defers entirely to the runtime's local configuration.
        if sub in self._SELF_CONTAINED_RUNTIMES:
            try:
                pure = self._ensure_pure_mode()
                self._install_pure_permission_bridge(pure, log)
                pure.runtime_name = sub
                provider = {
                    "claude-agent-sdk": "anthropic",
                    "antigravity-sdk": "google",
                    "antigravity-cli": "google",
                }.get(sub, "openai")
                pure.connect(provider=provider, model="", working_directory=Path.cwd())
                self._announce_self_contained_connection(sub, log)
            except Exception as exc:  # noqa: BLE001
                log.add_error(f"Switched to {sub} but auto-connect failed: {exc}")
                config_hint = self._codex_config_error_hint_text(exc)
                if config_hint:
                    log.add_info(config_hint)
        else:
            log.add_info(
                f"Runtime swapped: {current} → {sub}. "
                "Next message will reconnect with the new backend."
            )

    # Runtimes that are self-contained (own model + auth) and can be used in the
    # TUI without a separate :connect step.
    _SELF_CONTAINED_RUNTIMES = frozenset(
        {"codex-sdk", "claude-agent-sdk", "antigravity-sdk", "antigravity-cli"}
    )


    # ---- Claude Agent SDK :claude command surface --------------------------
    def _claude_cmd(self, args: str, log) -> None:
        """Handle :claude / :claude <subcommand> (Claude Agent SDK, API key)."""
        parts = (args or "").split(maxsplit=1)
        sub = parts[0].strip().lower() if parts and parts[0].strip() else "connect"
        rest = parts[1].strip() if len(parts) > 1 else ""
        if sub in ("connect", "start"):
            self._runtime_cmd("claude-agent-sdk", log)
        elif sub in ("status", "doctor"):
            self._claude_status(log)
        elif sub == "model":
            self._claude_model_cmd(rest, log)
        elif sub in ("permission", "permission-mode", "mode"):
            self._claude_permission_cmd(rest, log)
        elif sub in ("sessions", "threads"):
            self._claude_sessions_cmd(log)
        elif sub == "resume":
            if not rest:
                log.add_info("Usage: :claude resume <session-id>")
            else:
                self._claude_runtime_action(log, "resumed session", lambda r: r.resume_thread(rest))
        elif sub == "rename":
            if not rest:
                log.add_info("Usage: :claude rename <name>")
            else:
                self._claude_runtime_action(log, "renamed session", lambda r: r.rename_thread(rest))
        elif sub == "tag":
            if not rest:
                log.add_info("Usage: :claude tag <tag>")
            else:
                self._claude_runtime_action(log, "tagged session", lambda r: r.tag_thread(rest))
        elif sub == "commands":
            self._claude_commands_cmd(log)
        elif sub == "command":
            if not rest:
                log.add_info("Usage: :claude command <name> [args]")
            else:
                # Claude slash commands are sent as a "/name args" prompt.
                self._handle_message(f"/{rest}", log)
        elif sub == "review":
            self._handle_message(
                "Review the current changes/working tree for correctness and risks; "
                "do not modify files — report findings only.",
                log,
            )
        else:
            log.add_error(f"Unknown claude command: {sub}")
            log.add_info(
                "Usage: :claude [status|model|permission|sessions|resume|rename|tag|commands|command|review]"
            )

    # ---- Google Antigravity CLI :antigravity command surface -----------------
    def _antigravity_cmd(self, args: str, log) -> None:
        """Handle Antigravity CLI handoff/profile commands.

        The current public agy CLI is an interactive terminal UI, not a documented
        ACP server. Keep SuperQode's integration honest: make it discoverable,
        migration-aware, and easy to launch from the current repository without
        pretending we can stream structured tool events yet.
        """
        parts = (args or "").split(maxsplit=1)
        sub = parts[0].strip().lower() if parts and parts[0].strip() else "connect"
        if sub in ("connect", "start", "cli"):
            self._runtime_cmd("antigravity-cli", log)
        elif sub in ("sdk", "api-key-sdk"):
            self._runtime_cmd("antigravity-sdk", log)
        elif sub in ("superqode", "byok"):
            self._connect_byok_cmd("google", log)
        elif sub in ("launch", "open"):
            self._show_antigravity_connect(log)
        elif sub in ("status", "doctor"):
            self._show_antigravity_status(log)
        elif sub in ("migrate", "migration", "gemini"):
            self._show_antigravity_migration(log)
        elif sub in ("help", "?"):
            self._show_antigravity_help(log)
        else:
            log.add_error(f"Unknown antigravity command: {sub}")
            log.add_info("Usage: :antigravity [cli|sdk|superqode|status|migrate|launch|help]")

    def _antigravity_command_line(self) -> str:
        return f"cd {shlex.quote(str(Path.cwd()))} && agy"

    def _antigravity_version(self) -> str:
        agy = shutil.which("agy")
        if not agy:
            return ""
        for args in (["agy", "--version"], ["agy", "version"]):
            try:
                result = subprocess.run(args, capture_output=True, text=True, timeout=5)
            except Exception:
                continue
            text = (result.stdout or result.stderr or "").strip()
            if result.returncode == 0 and text:
                return text.splitlines()[0].strip()
        return ""


    def _show_antigravity_status(self, log) -> None:
        agy_path = shutil.which("agy")
        settings = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
        version = self._antigravity_version()
        t = Text()
        t.append("\n  Antigravity CLI status\n\n", style=f"bold {THEME['text']}")
        t.append("    Binary    ", style=THEME["muted"])
        t.append(f"{agy_path or 'not found'}\n", style=THEME["success" if agy_path else "warning"])
        if version:
            t.append("    Version   ", style=THEME["muted"])
            t.append(f"{version}\n", style=THEME["text"])
        t.append("    Settings  ", style=THEME["muted"])
        t.append(str(settings), style=THEME["text" if settings.exists() else "dim"])
        t.append("  ")
        t.append(
            "(found)\n" if settings.exists() else "(not found yet)\n",
            style=THEME["success" if settings.exists() else "dim"],
        )
        t.append("    Auth      ", style=THEME["muted"])
        t.append("OS keyring / browser sign-in handled by agy\n", style=THEME["text"])
        t.append("\n  Commands:\n", style=THEME["muted"])
        t.append("    :antigravity launch    ", style=THEME["cyan"])
        t.append("show the current-repo agy launch command\n", style=THEME["muted"])
        t.append("    :antigravity migrate   ", style=THEME["cyan"])
        t.append("show Gemini CLI migration commands\n", style=THEME["muted"])
        log.write(t)

    def _show_antigravity_migration(self, log) -> None:
        t = Text()
        t.append("\n  Gemini CLI -> Antigravity CLI\n\n", style=f"bold {THEME['text']}")
        t.append(
            "  Google is moving individual Google AI Pro/Ultra/free Code Assist users "
            "from Gemini CLI to Antigravity CLI.\n",
            style=THEME["muted"],
        )
        t.append(
            "  Keep Gemini CLI available for enterprise/API-key ACP users, but prefer "
            "agy for consumer Google accounts.\n\n",
            style=THEME["muted"],
        )
        t.append("  Migration commands:\n", style=THEME["muted"])
        t.append(
            "    curl -fsSL https://antigravity.google/cli/install.sh | bash\n", style=THEME["cyan"]
        )
        t.append("    agy\n", style=THEME["cyan"])
        t.append("    agy plugin import gemini\n", style=THEME["cyan"])
        t.append("\n  Paths:\n", style=THEME["muted"])
        t.append("    Gemini CLI:       ~/.gemini/\n", style=THEME["dim"])
        t.append("    Antigravity CLI:  ~/.gemini/antigravity-cli/\n", style=THEME["dim"])
        t.append("\n  SuperQode route:\n", style=THEME["muted"])
        t.append("    :connect antigravity  # Google Sign-In route\n", style=THEME["cyan"])
        log.write(t)

    def _show_antigravity_help(self, log) -> None:
        t = Text()
        t.append("\n  Antigravity in SuperQode\n\n", style=f"bold {THEME['text']}")
        t.append("  :connect antigravity       ", style=THEME["cyan"])
        t.append("Antigravity harness through signed-in agy\n", style=THEME["muted"])
        t.append("  :antigravity sdk           ", style=THEME["cyan"])
        t.append("Antigravity harness through its API-key SDK\n", style=THEME["muted"])
        t.append("  :antigravity superqode     ", style=THEME["cyan"])
        t.append("SuperQode harness with a Google API key\n", style=THEME["muted"])
        t.append("  :antigravity launch        ", style=THEME["cyan"])
        t.append("show the separate agy CLI handoff\n", style=THEME["muted"])
        t.append("  :antigravity status        ", style=THEME["cyan"])
        t.append("check binary/settings status\n", style=THEME["muted"])
        t.append("  :antigravity migrate       ", style=THEME["cyan"])
        t.append("show Gemini CLI migration steps\n", style=THEME["muted"])
        t.append(
            "\n  Structured SuperQode tool cards require an ACP/headless event stream. "
            "agy does not document that yet.\n",
            style=THEME["dim"],
        )
        log.write(t)

    # ---- xAI Grok Build :grok command surface ------------------------------
    def _grok_cmd(self, args: str, log) -> None:
        """Handle Grok Build ACP and the explicit native-harness opt-in."""
        parts = (args or "").split(maxsplit=1)
        sub = parts[0].strip().lower() if parts and parts[0].strip() else "connect"
        rest = parts[1].strip() if len(parts) > 1 else ""
        if sub in ("connect", "start"):
            # Subscription default = Grok Build, xAI's own agent over ACP
            # (matching the Codex and Claude profiles). SuperQode's harness on
            # the same plan is the explicit opt-in `:grok api`.
            self._connect_acp_cmd(("grok " + rest).strip(), log)
        elif sub == "api":
            self._grok_api_cmd(rest, log)
        elif sub in ("models", "ls"):
            self._show_grok_models(log)
        elif sub == "model":
            if rest:
                self._grok_api_cmd(rest, log)
            else:
                self._show_grok_model_picker(log)
        elif sub in ("status", "doctor"):
            self._show_grok_status(log)
        elif sub in ("login", "auth"):
            self._show_grok_login(log)
        elif sub in ("help", "?"):
            self._show_grok_help(log)
        else:
            log.add_error(f"Unknown grok command: {sub}")
            log.add_info(
                "Usage: :grok [connect [model]|model [name]|models|api [model|off]|"
                "status|login|help] (ACP: :connect acp grok)"
            )

    def _grok_api_cmd(self, rest: str, log) -> None:
        """Connect SuperQode harness using the Grok CLI subscription session.

        Imports the local ``grok login`` session token into SuperQode's auth
        store and connects the ``grok-cli`` provider (CLI chat proxy). Grok
        Build is the default ``:connect grok`` / ``:grok connect`` route;
        this native-harness path is always an explicit opt-in.
        """
        from superqode.providers import grok_cli_auth

        arg = (rest or "").strip()
        if arg.lower() in ("off", "remove", "logout"):
            if grok_cli_auth.remove_cli_token():
                log.add_info("Removed the imported Grok CLI token from SuperQode's auth store.")
            else:
                log.add_info("No imported Grok CLI token to remove.")
            return

        model = arg or "grok-build"
        for prefix in ("grok-cli/", "xai/", "grok/"):
            if model.lower().startswith(prefix):
                model = model[len(prefix) :]
                break

        if not self._import_grok_token(log):
            return

        log.add_info(
            "Imported the Grok CLI session token (stored in ~/.superqode/auth.json, 0600)."
        )
        log.add_info(
            f"SuperQode harness on Grok subscription → grok-cli/{model}. "
            "For xAI's own Grok Build agent instead, use :connect grok. "
            "Remove token anytime with :grok api off."
        )
        self._connect_byok_mode("grok-cli", model, log)

    def _import_grok_token(self, log) -> bool:
        """Import the local `grok login` session into the auth store.

        Shared by connect and the model picker. Returns False (with guidance
        written to the log) when there is no usable CLI login.
        """
        from superqode.providers import grok_cli_auth

        # Someone without the product installed should get install steps, not
        # be told to run a command that does not exist on their machine.
        if shutil.which("grok") is None:
            log.add_error(
                "The Grok CLI is not installed, so the subscription route is unavailable."
            )
            log.add_info(
                "Install it (macOS/Linux/WSL): curl -fsSL https://x.ai/cli/install.sh | bash"
            )
            log.add_info("Windows PowerShell:           irm https://x.ai/cli/install.ps1 | iex")
            log.add_info("Then sign in with `grok login` and re-run :connect grok.")
            log.add_info("No subscription? Use BYOK instead: :connect byok xai grok-4.5")
            return False

        auth = grok_cli_auth.import_cli_token()
        if auth is None:
            log.add_error("No Grok CLI login found (~/.grok/auth.json).")
            log.add_info("Run `grok login` first, or use BYOK: :connect byok xai grok-4.5")
            log.add_info("For Grok Build ACP instead: :connect acp grok")
            return False
        if auth.is_expired():
            grok_cli_auth.remove_cli_token()
            log.add_error("The Grok CLI session looks expired (CLI sessions last ~7 days).")
            log.add_info("Run `grok login` again, then re-run :connect grok.")
            return False
        # Login state may have changed since the last catalog probe.
        grok_cli_auth.clear_cli_models_cache()
        return True


    def _show_grok_status(self, log) -> None:
        """Show local Grok CLI readiness without reading or displaying credentials."""
        grok_path = shutil.which("grok")
        auth_path = Path.home() / ".grok" / "auth.json"
        has_api_key = bool(os.environ.get("XAI_API_KEY"))
        t = Text()
        t.append("\n  Grok Build status\n\n", style=f"bold {THEME['text']}")
        t.append("    Binary    ", style=THEME["muted"])
        t.append(
            f"{grok_path or 'not found'}\n",
            style=THEME["success" if grok_path else "warning"],
        )
        t.append("    CLI auth  ", style=THEME["muted"])
        t.append(
            "configured\n" if auth_path.exists() else "not found\n",
            style=THEME["success" if auth_path.exists() else "dim"],
        )
        t.append("    BYOK      ", style=THEME["muted"])
        t.append(
            "XAI_API_KEY set\n" if has_api_key else "not set\n",
            style=THEME["success" if has_api_key else "dim"],
        )
        try:
            from superqode.providers.grok_cli_auth import cli_token_status

            token = cli_token_status()
        except Exception:  # noqa: BLE001 - status must never crash
            token = {}
        t.append("    API token ", style=THEME["muted"])
        if token.get("imported") and not token.get("imported_expired"):
            t.append("imported (:grok api off to remove)\n", style=THEME["success"])
        elif token.get("imported"):
            t.append(
                "imported but expired — run `grok login`, then :grok api\n", style=THEME["warning"]
            )
        elif token.get("cli_login"):
            t.append("available: run :grok api to use SuperQode's harness\n", style=THEME["dim"])
        else:
            t.append("not imported\n", style=THEME["dim"])
        t.append("    Default   ", style=THEME["muted"])
        t.append("Grok Build (currently Grok 4.5)\n", style=THEME["text"])
        t.append("\n  Commands:\n", style=THEME["muted"])
        t.append("    grok login                ", style=THEME["cyan"])
        t.append("sign in to an eligible X/SuperGrok account\n", style=THEME["muted"])
        t.append("    grok login --device-auth  ", style=THEME["cyan"])
        t.append("sign in from SSH or a headless host\n", style=THEME["muted"])
        t.append("    :connect grok             ", style=THEME["cyan"])
        t.append("Grok Build, xAI's own agent (ACP)\n", style=THEME["muted"])
        t.append("    :grok api [model]         ", style=THEME["cyan"])
        t.append("SuperQode harness on your subscription (opt-in)\n", style=THEME["muted"])
        t.append("    :grok api off             ", style=THEME["cyan"])
        t.append("remove imported session token\n", style=THEME["muted"])
        log.write_feedback(t)

    def _show_grok_login(self, log) -> None:
        """Give login commands instead of launching an interactive browser flow in the TUI."""
        t = Text()
        t.append("\n  Grok subscription login\n\n", style=f"bold {THEME['text']}")
        t.append("  Run in a terminal:\n", style=THEME["muted"])
        t.append("    grok login\n", style=THEME["cyan"])
        t.append("\n  For SSH or a headless machine:\n", style=THEME["muted"])
        t.append("    grok login --device-auth\n", style=THEME["cyan"])
        t.append("\n  Then connect Grok Build (xAI's own agent):\n", style=THEME["muted"])
        t.append("    :connect grok\n", style=THEME["cyan"])
        t.append("\n  Or run SuperQode's harness on the same plan:\n", style=THEME["muted"])
        t.append("    :grok api [model]\n", style=THEME["cyan"])
        t.append(
            "\n  The official CLI stores login in ~/.grok/auth.json. "
            ":grok api imports the session token into SuperQode for the harness path.\n",
            style=THEME["dim"],
        )
        log.write_feedback(t)

    def _show_grok_help(self, log) -> None:
        t = Text()
        t.append("\n  Grok in SuperQode\n\n", style=f"bold {THEME['text']}")
        t.append("  :connect grok              ", style=THEME["cyan"])
        t.append("Grok Build, xAI's own coding agent (ACP)\n", style=THEME["muted"])
        t.append("  :grok connect [model]      ", style=THEME["cyan"])
        t.append("same as :connect grok; optional model hint\n", style=THEME["muted"])
        t.append("  :grok api [model]          ", style=THEME["cyan"])
        t.append("SuperQode harness on your subscription (opt-in)\n", style=THEME["muted"])
        t.append("  :grok models               ", style=THEME["cyan"])
        t.append("list the signed-in CLI's model catalog\n", style=THEME["muted"])
        t.append("  :grok model [name]         ", style=THEME["cyan"])
        t.append("pick a subscription model for the SuperQode harness path\n", style=THEME["muted"])
        t.append("  :grok api off              ", style=THEME["cyan"])
        t.append("remove the imported session token\n", style=THEME["muted"])
        t.append("  :grok status               ", style=THEME["cyan"])
        t.append("check CLI and local auth readiness\n", style=THEME["muted"])
        t.append("  :grok login                ", style=THEME["cyan"])
        t.append("show browser and device-login commands\n", style=THEME["muted"])
        t.append(
            "\n  Subscription access and model eligibility are determined by xAI. "
            "For direct API billing, use BYOK with XAI_API_KEY and xai/grok-4.5.\n",
            style=THEME["dim"],
        )
        log.write_feedback(t)


    def _claude_runtime_action(self, log, label: str, action) -> None:
        try:
            runtime = self._claude_runtime_or_connect(log)
            action(runtime)
            log.add_success(f"Claude {label}")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not {label}: {exc}")

    def _claude_status(self, log) -> None:
        import importlib.util
        import shutil

        text = Text()
        text.append("\n  Claude Agent SDK status\n\n", style=f"bold {THEME['cyan']}")
        sdk_ok = importlib.util.find_spec("claude_agent_sdk") is not None
        text.append("  SDK          ", style=THEME["muted"])
        text.append(
            "installed\n" if sdk_ok else "missing\n",
            style=THEME["success" if sdk_ok else "error"],
        )
        cli_ok = shutil.which("claude") is not None
        text.append("  Claude CLI   ", style=THEME["muted"])
        text.append(
            "found\n" if cli_ok else "not found (install Claude Code)\n",
            style=THEME["success" if cli_ok else "warning"],
        )
        key_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
        text.append("  API key      ", style=THEME["muted"])
        text.append(
            "ANTHROPIC_API_KEY set\n" if key_ok else "ANTHROPIC_API_KEY not set\n",
            style=THEME["success" if key_ok else "error"],
        )
        pure = getattr(self, "_pure_mode", None)
        runtime = getattr(pure, "_runtime", None) if pure is not None else None
        connected = runtime is not None and getattr(pure, "runtime_name", "") == "claude-agent-sdk"
        text.append("  Connected    ", style=THEME["muted"])
        text.append(
            "yes\n" if connected else "no (use :claude)\n",
            style=THEME["success" if connected else "warning"],
        )
        if connected:
            model = getattr(runtime, "config", None)
            model_id = getattr(model, "model", "") or "Claude Code default"
            text.append("  Model        ", style=THEME["muted"])
            text.append(f"{model_id}\n", style=THEME["text"])
            text.append("  Permission   ", style=THEME["muted"])
            text.append(
                f"{getattr(runtime, 'permission_mode', None) or 'default'}\n", style=THEME["text"]
            )
            cmds = getattr(runtime, "slash_commands", [])
            text.append("  Slash cmds   ", style=THEME["muted"])
            text.append(f"{len(cmds)} available\n", style=THEME["text"])
        if not (sdk_ok and key_ok):
            text.append("\n  Setup: ", style=THEME["muted"])
            text.append('uv tool install "superqode[claude-agent-sdk]"', style=THEME["cyan"])
            text.append(" + install Claude Code + export ANTHROPIC_API_KEY\n", style=THEME["muted"])
        log.write(text)


    def _claude_permission_cmd(self, mode: str, log) -> None:
        modes = ("default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto")
        if not mode:
            log.add_info(
                f"Permission modes: {', '.join(modes)}.  Set with :claude permission <mode>"
            )
            return
        try:
            runtime = self._claude_runtime_or_connect(log)
            runtime.set_permission_mode(mode)
            log.add_success(f"Claude permission mode set to {mode}")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not set permission mode: {exc}")

    def _claude_sessions_cmd(self, log) -> None:
        try:
            runtime = self._claude_runtime_or_connect(log)
            sessions = runtime.list_threads(limit=20)
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not list Claude sessions: {exc}")
            return
        t = Text()
        t.append("\n  Claude sessions\n\n", style=f"bold {THEME['text']}")
        if not sessions:
            t.append("  (none)\n", style=THEME["muted"])
        for s in list(sessions)[:20]:
            sid = getattr(s, "session_id", getattr(s, "id", "")) or "?"
            title = getattr(s, "title", "") or ""
            t.append("  • ", style=THEME["dim"])
            t.append(f"{sid}", style=THEME["text"])
            if title:
                t.append(f"  {title}", style=THEME["muted"])
            t.append("\n", style="")
        t.append("\n  Resume with ", style=THEME["muted"])
        t.append(":claude resume <session-id>\n", style=THEME["cyan"])
        log.write(t)

    def _claude_commands_cmd(self, log) -> None:
        runtime = getattr(getattr(self, "_pure_mode", None), "_runtime", None)
        cmds = list(getattr(runtime, "slash_commands", []) or []) if runtime else []
        t = Text()
        t.append("\n  Claude slash commands\n\n", style=f"bold {THEME['text']}")
        if not cmds:
            t.append(
                "  (none yet — send a message first so the SDK reports them)\n",
                style=THEME["muted"],
            )
        for name in cmds:
            t.append("  • ", style=THEME["dim"])
            t.append(f"/{name}\n", style=THEME["cyan"])
        t.append("\n  Run with ", style=THEME["muted"])
        t.append(":claude command <name> [args]\n", style=THEME["cyan"])
        log.write(t)


    def _harness_cmd(self, args: str, log) -> None:
        """Handle :harness status/list/templates/off/<path>."""
        import os as _os

        parts = args.split(maxsplit=1)
        sub = parts[0].strip() if parts else "status"
        subargs = parts[1].strip() if len(parts) > 1 else ""
        if not sub:
            sub = "status"

        try:
            from superqode.harness import (
                BUILTIN_TEMPLATES,
                get_harness_template,
                list_harnesses,
                resolve_harness,
            )
        except Exception as exc:
            log.add_error(f"Harness support is unavailable: {exc}")
            return

        if sub in ("status", "current"):
            pure = getattr(self, "_pure_mode", None)
            status = pure.get_status().get("harness", {}) if pure else {}
            if status.get("enabled"):
                log.add_info(
                    f"Harness: {_harness_display_name(status.get('name'))} "
                    f"({status.get('flavor')}, runtime={status.get('runtime')})"
                )
                if status.get("path"):
                    log.add_info(f"Spec: {status.get('path')}")
            else:
                env_path = _os.getenv("SUPERQODE_HARNESS", "").strip()
                if env_path:
                    log.add_info(f"Harness configured for next connection: {env_path}")
                else:
                    log.add_info("No harness is active. Use :harness use core.")
            return

        if sub in ("list", "available"):
            for entry in list_harnesses(Path.cwd()):
                marker = "*" if entry.default else " "
                status = "ready" if entry.available else (entry.issue or "unavailable")
                log.add_info(
                    f"{marker} {entry.id:18} {entry.source:10} {entry.runtime:14} "
                    f"tools={len(entry.tools):2} {status}"
                )
            return

        if sub == "show":
            if not subargs:
                log.add_error("Usage: :harness show <name-or-path>")
                return
            try:
                entry = resolve_harness(subargs, root=Path.cwd())
            except Exception as exc:
                log.add_error(f"Could not resolve harness: {exc}")
                return
            log.add_info(
                f"Harness: {_harness_display_name(entry.id)} ({entry.source}, "
                f"runtime={entry.runtime}, tools={len(entry.tools)})"
            )
            log.add_info(entry.description)
            log.add_info(f"Tools: {', '.join(entry.tools) or 'none'}")
            log.add_info(f"Digest: {entry.digest}")
            return

        if sub in ("templates", "list-templates"):
            for name in sorted(BUILTIN_TEMPLATES):
                if "_" in name:
                    continue
                spec = get_harness_template(name)
                log.add_info(
                    f"  {name:18} {spec.flavor.value:8} {spec.runtime.backend:14} {spec.description}"
                )
            return

        if sub in ("wizard", "init", "create"):
            self._harness_wizard_cmd(subargs, log)
            return

        if sub in ("inspect", "show", "summary"):
            self._show_harness_inspect(log)
            return

        if sub in ("doctor", "check"):
            self._show_harness_doctor(log)
            return

        if sub in ("graph", "plan"):
            self._show_harness_graph(log, run_id=subargs if sub == "graph" else "")
            return

        if sub in ("runs", "history"):
            self._show_harness_runs(log)
            return

        if sub in ("replay", "replay-plan"):
            if not subargs:
                log.add_error("Usage: :harness replay <run_id>")
                return
            self._show_harness_replay(log, subargs)
            return

        if sub in ("fork", "branch"):
            if not subargs:
                log.add_error("Usage: :harness fork <run_id> [after_index]")
                return
            self._show_harness_fork(log, subargs)
            return

        if sub in ("evidence", "receipt"):
            if not subargs:
                log.add_error("Usage: :harness evidence <run_id>")
                return
            self._show_harness_evidence(log, subargs)
            return

        if sub in ("events", "timeline"):
            if not subargs:
                log.add_error("Usage: :harness events <run_id>")
                return
            self._show_harness_events(log, subargs)
            return

        if sub in ("improve", "optimize", "optimize-inspect", "optimize-ledger"):
            try:
                tokens = shlex.split(subargs or "")
            except ValueError as exc:
                log.add_error(f"Could not parse :harness {sub} arguments: {exc}")
                return
            if sub == "optimize" and not tokens:
                log.add_info(
                    "Usage: :harness optimize --spec <path> --tasks <path> [--export-only]"
                )
                return
            if sub == "improve" and not tokens:
                log.add_info(
                    "Usage: :harness improve --spec <path> --tasks <path> [--from-failures failures.json] [--export-only]"
                )
                return
            if sub in {"optimize-inspect", "optimize-ledger"} and not tokens:
                log.add_info(f"Usage: :harness {sub} <run_dir>")
                return
            label = "Harness self-improvement" if sub == "improve" else "Harness optimization"
            self.run_worker(self._superqode_cli_cmd(["harness", sub, *tokens], log, label))
            return

        cli_backed_harness_subcommands = {
            "audit-candidate",
            "auto-bench",
            "candidates",
            "compile",
            "diff",
            "drain",
            "eval",
            "eval-packs",
            "explain",
            "import-agent",
            "import-omnigent",
            "inbox",
            "list-backends",
            "logbook",
            "mine-failures",
            "registry",
            "run",
            "test",
            "validate",
            "worker",
            "observability",
        }
        if sub in cli_backed_harness_subcommands:
            try:
                tokens = shlex.split(subargs or "")
            except ValueError as exc:
                log.add_error(f"Could not parse :harness {sub} arguments: {exc}")
                return
            self._run_cli_passthrough(["harness", sub, *tokens], log, "Harness command")
            return

        if sub in ("off", "disable", "none"):
            _os.environ["SUPERQODE_HARNESS"] = "core"
            if hasattr(self, "_pure_mode") and self._pure_mode is not None:
                self._pure_mode.clear_harness()
                if self._pure_mode.session.connected:
                    self._pure_mode.disconnect()
            self._refresh_harness_panel()
            log.add_info(
                "Restored the core harness. Reconnect with :connect byok or :connect local."
            )
            return

        if sub in ("load", "use"):
            reference = subargs
        else:
            reference = args.strip()

        if not reference:
            log.add_info(
                "Usage: :harness <spec.yaml> | :harness wizard [name] --starter <template> --output <path> [--load] | :harness inspect | :harness doctor | :harness graph | :harness replay <run_id> | :harness fork <run_id> | :harness evidence <run_id> | :harness runs | :harness mine-failures --eval-result eval.json | :harness audit-candidate --base <path> --candidate <path> | :harness candidates list | :harness improve --spec <path> --tasks <path> | :harness optimize --spec <path> --tasks <path> | :harness optimize-inspect <run_dir> | :harness optimize-ledger <run_dir> | :harness templates | :harness off"
            )
            return

        try:
            entry = resolve_harness(reference, root=Path.cwd())
        except Exception as exc:
            log.add_error(f"Could not resolve harness: {exc}")
            return

        _os.environ["SUPERQODE_HARNESS"] = str(entry.path or entry.id)
        pure = self._ensure_pure_mode()
        if hasattr(pure, "select_harness"):
            pure.select_harness(str(entry.path or entry.id))
        else:
            pure.set_harness(entry.spec, path=entry.path)
        if pure.session.connected:
            pure.disconnect()
        self._refresh_harness_panel()

        log.add_success(
            f"✓ Harness: {_harness_display_name(entry.id)} loaded "
            f"({entry.spec.flavor.value}, runtime={entry.runtime}, tools={len(entry.tools)})"
        )
        log.add_info(
            "Reconnect with :connect byok or :connect local to run the TUI through this spec."
        )

    def _harness_wizard_cmd(self, args: str, log) -> None:
        """Create a HarnessSpec from wizard answers supplied as TUI flags."""
        try:
            from superqode.harness import (
                APPROVAL_PROFILES,
                TOOL_CALL_FORMATS,
                WIZARD_STARTERS,
                WizardAnswers,
                build_wizard_spec,
                explain_harness,
                render_explanation,
                save_harness_spec,
            )
        except Exception as exc:
            log.add_error(f"Harness wizard is unavailable: {exc}")
            return

        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :harness wizard arguments: {exc}")
            return

        if not tokens:
            self._start_harness_wizard_flow(log)
            return

        starter_keys = {key for key, _label in WIZARD_STARTERS}
        approval_keys = {key for key, _label in APPROVAL_PROFILES}
        tool_format_keys = {key for key, _label in TOOL_CALL_FORMATS}
        workflow_keys = {
            "single",
            "plan-implement-review",
            "fix-and-verify",
            "parallel-review",
            "security-review",
        }
        output = Path("harness.yaml")
        force = False
        load_after_write = False
        answers_kwargs: dict[str, Any] = {
            "name": "my-harness",
            "starter": "qwen-coding",
            "provider": "",
            "model": "",
            "allow_write": True,
            "allow_shell": True,
            "allow_network": False,
            "approval_profile": "balanced",
            "tool_call_format": "auto",
            "workflow_preset": "single",
        }

        def _require_value(index: int, flag: str) -> str:
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
                raise ValueError(f"{flag} requires a value")
            return tokens[index + 1]

        i = 0
        positional: list[str] = []
        try:
            while i < len(tokens):
                token = tokens[i]
                if token in {"--help", "-h"}:
                    self._show_harness_wizard_help(log)
                    return
                if token in {"--starter", "-t"}:
                    answers_kwargs["starter"] = _require_value(i, token)
                    i += 2
                    continue
                if token in {"--output", "-o"}:
                    output = Path(_require_value(i, token)).expanduser()
                    i += 2
                    continue
                if token == "--provider":
                    answers_kwargs["provider"] = _require_value(i, token)
                    i += 2
                    continue
                if token == "--model":
                    answers_kwargs["model"] = _require_value(i, token)
                    i += 2
                    continue
                if token in {"--workflow", "--workflow-preset"}:
                    answers_kwargs["workflow_preset"] = _require_value(i, token)
                    i += 2
                    continue
                if token in {"--approval", "--approval-profile"}:
                    answers_kwargs["approval_profile"] = _require_value(i, token)
                    i += 2
                    continue
                if token in {"--tool-format", "--tool-call-format"}:
                    answers_kwargs["tool_call_format"] = _require_value(i, token)
                    i += 2
                    continue
                if token in {"--read-only", "--no-write"}:
                    answers_kwargs["allow_write"] = False
                    i += 1
                    continue
                if token == "--no-shell":
                    answers_kwargs["allow_shell"] = False
                    i += 1
                    continue
                if token == "--allow-network":
                    answers_kwargs["allow_network"] = True
                    i += 1
                    continue
                if token == "--no-network":
                    answers_kwargs["allow_network"] = False
                    i += 1
                    continue
                if token == "--force":
                    force = True
                    i += 1
                    continue
                if token == "--load":
                    load_after_write = True
                    i += 1
                    continue
                if token.startswith("-"):
                    raise ValueError(f"Unknown option {token}")
                positional.append(token)
                i += 1
        except ValueError as exc:
            log.add_error(str(exc))
            self._show_harness_wizard_help(log)
            return

        if positional:
            answers_kwargs["name"] = positional[0]
        if len(positional) > 1:
            log.add_error(f"Unexpected extra argument: {positional[1]}")
            self._show_harness_wizard_help(log)
            return

        if answers_kwargs["starter"] not in starter_keys:
            log.add_error(
                f"Unknown starter {answers_kwargs['starter']!r}. Try: {', '.join(sorted(starter_keys))}"
            )
            return
        if answers_kwargs["approval_profile"] not in approval_keys:
            log.add_error(
                f"Unknown approval profile {answers_kwargs['approval_profile']!r}. Try: {', '.join(sorted(approval_keys))}"
            )
            return
        if answers_kwargs["tool_call_format"] not in tool_format_keys:
            log.add_error(
                f"Unknown tool-call format {answers_kwargs['tool_call_format']!r}. Try: {', '.join(sorted(tool_format_keys))}"
            )
            return
        if answers_kwargs["workflow_preset"] not in workflow_keys:
            log.add_error(
                f"Unknown workflow {answers_kwargs['workflow_preset']!r}. Try: {', '.join(sorted(workflow_keys))}"
            )
            return

        if output.exists() and not force:
            log.add_error(f"{output} already exists. Add --force to overwrite it.")
            return

        try:
            answers = WizardAnswers(**answers_kwargs)
            spec = build_wizard_spec(answers)
            path = save_harness_spec(spec, output)
            (Path(".agents") / "skills").mkdir(parents=True, exist_ok=True)
            (Path(".agents") / "roles").mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.add_error(f"Could not create harness: {exc}")
            return

        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Wizard\n\n", style=f"bold {THEME['text']}")
        t.append("  Wrote       ", style=THEME["muted"])
        t.append(str(path), style=f"bold {THEME['cyan']}")
        t.append("\n  Starter     ", style=THEME["muted"])
        t.append(answers.starter, style=THEME["text"])
        t.append("\n  Runtime     ", style=THEME["muted"])
        t.append(spec.runtime.backend, style=THEME["text"])
        t.append("\n  Model       ", style=THEME["muted"])
        t.append(spec.model_policy.primary or "active connection", style=THEME["text"])
        t.append("\n\n")
        explanation = render_explanation(
            explain_harness(spec, provider=answers.provider, model=answers.model)
        )
        for line in explanation.splitlines()[:18]:
            t.append("  ", style="")
            t.append(line, style=THEME["text"])
            t.append("\n")
        t.append("\n  Next        ", style=THEME["muted"])
        t.append(f":harness {path}", style=THEME["cyan"])
        t.append("  ", style="")
        t.append(f":harness doctor", style=THEME["cyan"])
        t.append("\n")
        self._show_command_output(log, t)

        if load_after_write:
            self._harness_cmd(f"load {path}", log)

    def _start_harness_wizard_flow(self, log) -> None:
        """Start the step-by-step HarnessSpec wizard in the TUI."""
        self._awaiting_harness_wizard = True
        self._harness_wizard_state = {
            "step": "name",
            "history": [],
            "answers": {
                "name": "my-harness",
                "starter": "qwen-coding",
                "provider": "",
                "model": "",
                "allow_write": True,
                "allow_shell": True,
                "allow_network": False,
                "approval_profile": "balanced",
                "tool_call_format": "auto",
                "workflow_preset": "single",
            },
            "output": self._default_harness_wizard_output(),
            "load": True,
            "force": False,
        }
        self._render_harness_wizard_step(log)

    def _handle_harness_wizard_input(self, text: str, log) -> bool:
        """Advance the guided HarnessSpec wizard."""
        state = getattr(self, "_harness_wizard_state", None)
        if not getattr(self, "_awaiting_harness_wizard", False) or not state:
            return False

        raw = (text or "").strip()
        lowered = raw.lower()
        # Typed commands always win over the wizard (same rule as the pickers):
        # ":quit" must quit the app from any step, ":help" must help, etc. The
        # wizard keeps only its own :cancel/:back control words; every other
        # ":"/"/"/"!" line falls through to the normal command dispatcher.
        if raw[:1] in (":", "/", "!") and lowered not in {
            ":cancel",
            "/cancel",
            ":back",
            "/back",
        }:
            return False
        if lowered in {"cancel", ":cancel", "/cancel", "quit", "exit"}:
            self._awaiting_harness_wizard = False
            self._harness_wizard_state = None
            log.add_info("Harness wizard cancelled.")
            return True
        if lowered in {"back", ":back", "/back"}:
            history = state.get("history", [])
            if history:
                state["step"] = history.pop()
            self._render_harness_wizard_step(log)
            return True

        step = state["step"]
        answers = state["answers"]

        try:
            if step == "name":
                if raw:
                    answers["name"] = raw
                self._harness_wizard_next(state, "starter")
            elif step == "starter":
                starter = self._harness_wizard_choice(
                    raw,
                    [key for key, _ in self._wizard_starters()],
                    default=str(answers.get("starter") or "qwen-coding"),
                )
                if starter is None:
                    log.add_error("Choose a starter by number or name.")
                    self._render_harness_wizard_step(log)
                    return True
                answers["starter"] = starter
                if starter == "no-tool":
                    answers["allow_write"] = False
                    answers["allow_shell"] = False
                self._harness_wizard_next(state, "provider")
            elif step == "provider":
                answers["provider"] = raw
                self._harness_wizard_next(state, "model")
            elif step == "model":
                answers["model"] = raw
                self._harness_wizard_next(state, "tools")
            elif step == "tools":
                choice = self._harness_wizard_choice(
                    raw,
                    ["full", "read-only", "no-shell", "no-tools"],
                    default="full",
                )
                if choice is None:
                    log.add_error("Choose tools by number or name.")
                    self._render_harness_wizard_step(log)
                    return True
                if choice == "full":
                    answers["allow_write"] = True
                    answers["allow_shell"] = True
                elif choice == "read-only":
                    answers["allow_write"] = False
                    answers["allow_shell"] = False
                elif choice == "no-shell":
                    answers["allow_write"] = True
                    answers["allow_shell"] = False
                elif choice == "no-tools":
                    answers["starter"] = "no-tool"
                    answers["allow_write"] = False
                    answers["allow_shell"] = False
                self._harness_wizard_next(state, "permissions")
            elif step == "permissions":
                choice = self._harness_wizard_choice(
                    raw,
                    ["balanced", "careful", "yolo", "balanced-network"],
                    default="balanced",
                )
                if choice is None:
                    log.add_error("Choose permissions by number or name.")
                    self._render_harness_wizard_step(log)
                    return True
                answers["allow_network"] = choice == "balanced-network"
                answers["approval_profile"] = "balanced" if choice == "balanced-network" else choice
                self._harness_wizard_next(state, "tool_format")
            elif step == "tool_format":
                choice = self._harness_wizard_choice(
                    raw,
                    ["auto", "native", "prompt"],
                    default="auto",
                )
                if choice is None:
                    log.add_error("Choose a tool-call format by number or name.")
                    self._render_harness_wizard_step(log)
                    return True
                answers["tool_call_format"] = choice
                self._harness_wizard_next(state, "workflow")
            elif step == "workflow":
                choice = self._harness_wizard_choice(
                    raw,
                    [
                        "single",
                        "plan-implement-review",
                        "fix-and-verify",
                        "parallel-review",
                        "security-review",
                    ],
                    default="single",
                )
                if choice is None:
                    log.add_error("Choose a workflow by number or name.")
                    self._render_harness_wizard_step(log)
                    return True
                answers["workflow_preset"] = choice
                self._harness_wizard_next(state, "output")
            elif step == "output":
                load_answer = self._parse_yes_no(raw) if raw else None
                if load_answer is not None:
                    state["load"] = load_answer
                    self._finish_harness_wizard_flow(log)
                    return True
                if raw:
                    state["output"] = raw
                self._harness_wizard_next(state, "load")
            elif step == "load":
                if raw:
                    load = self._parse_yes_no(raw)
                    if load is None:
                        log.add_error("Answer yes or no.")
                        self._render_harness_wizard_step(log)
                        return True
                    state["load"] = load
                self._finish_harness_wizard_flow(log)
                return True
            else:
                log.add_error("Harness wizard state was invalid; restarting.")
                self._start_harness_wizard_flow(log)
                return True
        except Exception as exc:
            log.add_error(f"Harness wizard failed: {exc}")
            self._awaiting_harness_wizard = False
            self._harness_wizard_state = None
            return True

        self._render_harness_wizard_step(log)
        return True

    @staticmethod
    def _harness_wizard_next(state: dict[str, Any], next_step: str) -> None:
        state.setdefault("history", []).append(state["step"])
        state["step"] = next_step

    @staticmethod
    def _default_harness_wizard_output() -> str:
        base = Path("harness.yaml")
        if not base.exists():
            return str(base)
        for index in range(2, 1000):
            candidate = Path(f"harness-{index}.yaml")
            if not candidate.exists():
                return str(candidate)
        return "harness-new.yaml"

    @staticmethod
    def _parse_yes_no(raw: str) -> bool | None:
        lowered = raw.strip().lower()
        if lowered in {"y", "yes", "true", "1"}:
            return True
        if lowered in {"n", "no", "false", "0"}:
            return False
        return None

    @staticmethod
    def _harness_wizard_choice(
        raw: str,
        keys: list[str],
        *,
        default: str | None = None,
    ) -> str | None:
        value = raw.strip().lower()
        if not value and default:
            return default
        if value.isdigit():
            index = int(value) - 1
            return keys[index] if 0 <= index < len(keys) else None
        for key in keys:
            if value == key.lower():
                return key
        matches = [key for key in keys if key.lower().startswith(value)]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _wizard_starters() -> tuple[tuple[str, str], ...]:
        from superqode.harness import WIZARD_STARTERS

        return WIZARD_STARTERS


    def _finish_harness_wizard_flow(self, log) -> None:
        state = getattr(self, "_harness_wizard_state", None)
        if not state:
            return
        answers_kwargs = dict(state["answers"])
        output = Path(state["output"]).expanduser()
        load_after_write = bool(state.get("load", True))

        if output.exists() and not state.get("force", False):
            state["output"] = self._default_harness_wizard_output()
            log.add_error(
                f"{output} already exists. Suggested next available path: {state['output']}"
            )
            state["step"] = "output"
            self._render_harness_wizard_step(log)
            return

        try:
            from superqode.harness import (
                WizardAnswers,
                build_wizard_spec,
                explain_harness,
                render_explanation,
                save_harness_spec,
            )

            answers = WizardAnswers(**answers_kwargs)
            spec = build_wizard_spec(answers)
            path = save_harness_spec(spec, output)
            (Path(".agents") / "skills").mkdir(parents=True, exist_ok=True)
            (Path(".agents") / "roles").mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.add_error(f"Could not create harness: {exc}")
            self._awaiting_harness_wizard = False
            self._harness_wizard_state = None
            return

        self._awaiting_harness_wizard = False
        self._harness_wizard_state = None

        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Created\n\n", style=f"bold {THEME['text']}")
        t.append("  Wrote       ", style=THEME["muted"])
        t.append(str(path), style=f"bold {THEME['cyan']}")
        t.append("\n  Name        ", style=THEME["muted"])
        t.append(spec.name, style=THEME["text"])
        t.append("\n  Runtime     ", style=THEME["muted"])
        t.append(spec.runtime.backend, style=THEME["text"])
        t.append("\n  Model       ", style=THEME["muted"])
        t.append(spec.model_policy.primary or "active connection", style=THEME["text"])
        t.append("\n\n")
        explanation = render_explanation(
            explain_harness(
                spec,
                provider=answers.provider,
                model=answers.model,
            )
        )
        for line in explanation.splitlines()[:14]:
            t.append("  ", style="")
            t.append(line, style=THEME["text"])
            t.append("\n")
        t.append("\n  Next        ", style=THEME["muted"])
        t.append(f":harness {path}", style=THEME["cyan"])
        t.append("  ", style="")
        t.append(":harness doctor", style=THEME["cyan"])
        t.append("\n")
        self._show_command_output(log, t)

        if load_after_write:
            self._harness_cmd(f"load {path}", log)

    def _show_harness_wizard_help(self, log) -> None:
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Wizard Usage\n\n", style=f"bold {THEME['text']}")
        t.append("  :harness wizard [name] [options]\n\n", style=THEME["cyan"])
        t.append("  Common:\n", style=f"bold {THEME['text']}")
        t.append(
            "    :harness wizard my-coder --starter qwen-coding --output harness.yaml --load\n",
            style=THEME["text"],
        )
        t.append(
            "    :harness wizard reviewer --starter no-tool --output reviewer.yaml\n",
            style=THEME["text"],
        )
        t.append("\n  Options:\n", style=f"bold {THEME['text']}")
        for line in (
            "--starter/-t <template>",
            "--output/-o <path>",
            "--provider <id> --model <id>",
            "--workflow <single|plan-implement-review|fix-and-verify|parallel-review|security-review>",
            "--approval <balanced|careful|yolo>",
            "--tool-format <auto|native|prompt>",
            "--read-only, --no-shell, --allow-network",
            "--force, --load",
        ):
            t.append("    " + line + "\n", style=THEME["text"])
        self._show_command_output(log, t)

    def _show_harness_inspect(self, log) -> None:
        """Show a readable summary for the active HarnessSpec."""
        spec, path = self._active_harness_spec()
        if spec is None:
            log.add_error("No HarnessSpec is active. Load one with :harness <spec.yaml>.")
            return
        try:
            from superqode.harness import inspect_harness
        except Exception as exc:
            log.add_error(f"Harness inspect is unavailable: {exc}")
            return
        summary = inspect_harness(spec)
        workflow = summary["workflow"]
        permissions = summary["permissions"]
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Inspect\n\n", style=f"bold {THEME['text']}")
        t.append("  Name        ", style=THEME["muted"])
        t.append(f"{summary['name']} v{summary['version']}", style=f"bold {THEME['cyan']}")
        t.append(f"  {summary['flavor']}\n", style=THEME["dim"])
        if summary["description"]:
            t.append("  Summary     ", style=THEME["muted"])
            t.append(summary["description"], style=THEME["text"])
            t.append("\n")
        if path:
            t.append("  Spec        ", style=THEME["muted"])
            t.append(path, style=THEME["dim"])
            t.append("\n")
        t.append("  Runtime     ", style=THEME["muted"])
        t.append(summary["runtime"]["backend"], style=THEME["text"])
        t.append("\n  Workflow    ", style=THEME["muted"])
        t.append(workflow["mode"], style=f"bold {THEME['success']}")
        if workflow["preset"]:
            t.append(f"  preset={workflow['preset']}", style=THEME["dim"])
        t.append(f"  parallelism={workflow['parallelism']}\n", style=THEME["dim"])
        t.append("  Model       ", style=THEME["muted"])
        t.append(summary["model_policy"]["primary"] or "active connection", style=THEME["text"])
        t.append("\n  Permissions ", style=THEME["muted"])
        t.append(
            f"read={permissions['allow_read']} write={permissions['allow_write']} shell={permissions['allow_shell']} network={permissions['allow_network']}",
            style=THEME["text"],
        )
        t.append(f"  approvals={permissions['approval_profile']}\n", style=THEME["dim"])
        t.append("  Tools       ", style=THEME["muted"])
        t.append(", ".join(summary["tools"]) if summary["tools"] else "-", style=THEME["text"])
        t.append("\n  Skills      ", style=THEME["muted"])
        t.append(", ".join(summary["skills"]) if summary["skills"] else "-", style=THEME["text"])
        t.append("\n  MCP         ", style=THEME["muted"])
        t.append(
            ", ".join(summary["mcp"]["servers"]) if summary["mcp"]["servers"] else "none declared",
            style=THEME["text"],
        )
        t.append("\n  Checks  ", style=THEME["muted"])
        t.append("enabled" if summary["checks"]["enabled"] else "disabled", style=THEME["text"])
        t.append("\n  Run store   ", style=THEME["muted"])
        t.append(summary["observability"]["run_store"], style=THEME["text"])

        t.append("\n\n  Agents\n", style=f"bold {THEME['text']}")
        for agent in summary["agents"]:
            t.append("  - ", style=THEME["dim"])
            t.append(agent["id"], style=f"bold {THEME['cyan']}")
            if agent["role"]:
                t.append(f"  {agent['role']}", style=THEME["muted"])
            if agent["model"]:
                t.append(f"  model={agent['model']}", style=THEME["dim"])
            t.append("\n")
        if not summary["agents"]:
            t.append("  - prompt step generated from run input\n", style=THEME["muted"])
        t.append("\n  Next        ", style=THEME["muted"])
        t.append(":harness doctor", style=THEME["cyan"])
        t.append("  ", style="")
        t.append(":harness graph", style=THEME["cyan"])
        t.append("\n")
        self._show_command_output(log, t)

    def _show_harness_doctor(self, log) -> None:
        """Show active HarnessSpec readiness checks."""
        spec, _path = self._active_harness_spec()
        if spec is None:
            log.add_error("No HarnessSpec is active. Load one with :harness <spec.yaml>.")
            return
        try:
            from superqode.harness import doctor_harness
        except Exception as exc:
            log.add_error(f"Harness doctor is unavailable: {exc}")
            return
        report = doctor_harness(spec)
        status_style = (
            THEME["error"]
            if report.status == "error"
            else THEME["warning"]
            if report.status == "warning"
            else THEME["success"]
        )
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Doctor\n\n", style=f"bold {THEME['text']}")
        t.append("  Harness     ", style=THEME["muted"])
        t.append(report.name, style=f"bold {THEME['cyan']}")
        t.append("\n  Status      ", style=THEME["muted"])
        t.append(report.status, style=f"bold {status_style}")
        t.append("\n\n  Checks\n", style=f"bold {THEME['text']}")
        for check in report.checks:
            style = (
                THEME["error"]
                if check.status == "error"
                else THEME["warning"]
                if check.status == "warning"
                else THEME["success"]
            )
            icon = "!" if check.status == "error" else "!" if check.status == "warning" else "✓"
            t.append(f"  {icon} ", style=style)
            t.append(f"{check.name:<14}", style=f"bold {style}")
            t.append(check.message, style=THEME["text"])
            if check.data.get("missing"):
                t.append(f"  missing: {', '.join(check.data['missing'])}", style=THEME["muted"])
            t.append("\n")
        self._show_command_output(log, t)

    def _show_harness_graph(self, log, run_id: str = "") -> None:
        """Show the planned graph or a persisted actual graph."""
        spec, _path = self._active_harness_spec()
        if spec is None:
            log.add_error("No HarnessSpec is active. Load one with :harness <spec.yaml>.")
            return
        try:
            from superqode.harness import FileHarnessStore, plan_harness_graph, render_harness_graph
        except Exception as exc:
            log.add_error(f"Harness graph is unavailable: {exc}")
            return
        run_id = run_id.strip()
        if run_id:
            try:
                graph = FileHarnessStore(Path(spec.context.session_storage)).get_event_graph(run_id)
            except Exception as exc:
                log.add_error(f"Could not load harness graph for {run_id}: {exc}")
                return
            title = f"Harness Graph  {run_id}"
            graph_note = "This is the persisted actual event graph."
        else:
            graph = plan_harness_graph(spec)
            title = "Harness Graph"
            graph_note = "This is the planned graph. Completed runs persist the actual event graph."
        graph_text = render_harness_graph(graph)
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append(title + "\n\n", style=f"bold {THEME['text']}")
        for line in graph_text.splitlines():
            t.append("  ", style="")
            t.append(line, style=THEME["cyan"] if "->" in line else THEME["text"])
            t.append("\n")
        t.append(f"\n  {graph_note}\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _show_harness_runs(self, log) -> None:
        """Show recent persisted harness runs."""
        spec, _path = self._active_harness_spec()
        if spec is None:
            log.add_error("No HarnessSpec is active. Load one with :harness <spec.yaml>.")
            return
        try:
            from superqode.harness import FileHarnessStore
        except Exception as exc:
            log.add_error(f"Harness runs are unavailable: {exc}")
            return
        runs = FileHarnessStore(Path(spec.context.session_storage)).list_runs()
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Runs\n\n", style=f"bold {THEME['text']}")
        if not runs:
            t.append("  No persisted harness runs found.\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return
        for run in runs[:12]:
            t.append("  ", style="")
            t.append(run.run_id, style=f"bold {THEME['cyan']}")
            t.append(
                f"  {run.status}",
                style=THEME["success"] if run.status == "succeeded" else THEME["warning"],
            )
            if run.metadata.get("workflow"):
                t.append("  workflow", style=THEME["purple"])
            t.append(f"  {run.prompt_preview}\n", style=THEME["muted"])
        t.append("\n  Inspect graph with ", style=THEME["muted"])
        t.append(":harness graph <run_id>\n", style=THEME["cyan"])
        self._show_command_output(log, t)

    def _show_harness_evidence(self, log, run_id: str) -> None:
        """Show a readable evidence report for a persisted harness run."""
        spec, _path = self._active_harness_spec()
        if spec is None:
            log.add_error("No HarnessSpec is active. Load one with :harness <spec.yaml>.")
            return
        try:
            from superqode.harness import FileHarnessStore, build_harness_evidence
        except Exception as exc:
            log.add_error(f"Harness evidence is unavailable: {exc}")
            return
        try:
            evidence = build_harness_evidence(
                FileHarnessStore(Path(spec.context.session_storage)),
                run_id.strip(),
            )
        except Exception as exc:
            log.add_error(f"Could not load harness evidence for {run_id}: {exc}")
            return
        run = evidence["run"]
        workflow = evidence["workflow"]
        changes = evidence["changes"] if isinstance(evidence["changes"], dict) else {}
        checks = evidence["checks"] if isinstance(evidence["checks"], dict) else {}
        result = evidence["result"]
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Evidence\n\n", style=f"bold {THEME['text']}")
        t.append("  Run         ", style=THEME["muted"])
        t.append(run["run_id"], style=f"bold {THEME['cyan']}")
        t.append(
            f"  {run['status']}\n",
            style=THEME["success"] if run["status"] == "succeeded" else THEME["warning"],
        )
        t.append("  Harness     ", style=THEME["muted"])
        t.append(f"{run['harness']}  {run['runtime']}", style=THEME["text"])
        t.append("\n  Model       ", style=THEME["muted"])
        t.append(f"{run['provider']}/{run['model']}", style=THEME["text"])
        if workflow.get("mode"):
            t.append("\n  Workflow    ", style=THEME["muted"])
            t.append(str(workflow["mode"]), style=THEME["text"])
        t.append("\n\n  Steps\n", style=f"bold {THEME['text']}")
        for step in workflow.get("completed_steps") or []:
            t.append("  ✓ ", style=THEME["success"])
            t.append(str(step.get("step_id") or "-"), style=f"bold {THEME['cyan']}")
            if step.get("child_run_id"):
                t.append(f"  {step['child_run_id']}", style=THEME["dim"])
            if step.get("detail"):
                t.append(f"  {step['detail']}", style=THEME["muted"])
            t.append("\n")
        for step in workflow.get("failed_steps") or []:
            t.append("  ! ", style=THEME["error"])
            t.append(str(step.get("step_id") or "-"), style=f"bold {THEME['error']}")
            if step.get("detail"):
                t.append(f"  {step['detail']}", style=THEME["muted"])
            t.append("\n")
        file_count = int(changes.get("file_count") or 0)
        t.append("\n  Changes     ", style=THEME["muted"])
        t.append(
            f"{file_count} file(s) (+{int(changes.get('additions') or 0)} -{int(changes.get('deletions') or 0)})",
            style=THEME["text"],
        )
        t.append("\n  Checks  ", style=THEME["muted"])
        t.append(str(checks.get("status") or "unknown"), style=THEME["text"])
        t.append(f"  {len(checks.get('steps') or [])} step(s)", style=THEME["dim"])
        t.append("\n  Approvals   ", style=THEME["muted"])
        t.append(f"{len(evidence.get('approvals') or [])} event(s)", style=THEME["text"])
        t.append("\n  Result      ", style=THEME["muted"])
        t.append(str(result.get("status") or run["status"]), style=THEME["text"])
        if result.get("content_preview"):
            t.append("\n\n", style="")
            t.append(str(result["content_preview"]), style=THEME["text"])
        t.append("\n\n  Next        ", style=THEME["muted"])
        t.append(f":harness graph {run['run_id']}", style=THEME["cyan"])
        t.append("  ", style="")
        t.append(f":harness events {run['run_id']}", style=THEME["cyan"])
        t.append("\n")
        self._show_command_output(log, t)

    def _show_harness_replay(self, log, run_id: str) -> None:
        """Show replay readiness for a persisted harness run."""
        spec, _path = self._active_harness_spec()
        if spec is None:
            log.add_error("No HarnessSpec is active. Load one with :harness <spec.yaml>.")
            return
        try:
            from superqode.harness import FileHarnessStore, build_harness_replay_plan
        except Exception as exc:
            log.add_error(f"Harness replay is unavailable: {exc}")
            return
        try:
            plan = build_harness_replay_plan(
                FileHarnessStore(Path(spec.context.session_storage)),
                run_id.strip(),
            )
        except Exception as exc:
            log.add_error(f"Could not build harness replay plan for {run_id}: {exc}")
            return
        run = plan["run"]
        events = plan["events"]
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Replay\n\n", style=f"bold {THEME['text']}")
        t.append("  Run         ", style=THEME["muted"])
        t.append(run["run_id"], style=f"bold {THEME['cyan']}")
        t.append("\n  Status      ", style=THEME["muted"])
        t.append(str(run["status"]), style=THEME["text"])
        t.append("\n  Prompt      ", style=THEME["muted"])
        t.append(str(run.get("prompt_preview") or "-"), style=THEME["text"])
        t.append("\n  Persistence ", style=THEME["muted"])
        t.append(str(run.get("prompt_persistence") or "unknown"), style=THEME["text"])
        t.append("  full=", style=THEME["dim"])
        t.append(
            str(run.get("has_full_prompt")),
            style=THEME["success"] if run.get("has_full_prompt") else THEME["warning"],
        )
        t.append("\n  Events      ", style=THEME["muted"])
        t.append(f"{events['count']} ({events['first']} -> {events['last']})", style=THEME["text"])
        if plan.get("limitations"):
            t.append("\n\n  Limitations\n", style=f"bold {THEME['warning']}")
            for item in plan["limitations"]:
                t.append(f"  - {item}\n", style=THEME["muted"])
        t.append("\n  Next        ", style=THEME["muted"])
        t.append(f":harness fork {run['run_id']}", style=THEME["cyan"])
        t.append("  ", style="")
        t.append(f":harness events {run['run_id']}", style=THEME["cyan"])
        t.append("\n")
        self._show_command_output(log, t)

    def _show_harness_fork(self, log, args: str) -> None:
        """Fork a persisted harness run at an optional event index."""
        spec, _path = self._active_harness_spec()
        if spec is None:
            log.add_error("No HarnessSpec is active. Load one with :harness <spec.yaml>.")
            return
        parts = args.split()
        run_id = parts[0]
        after = None
        if len(parts) > 1:
            try:
                after = int(parts[1])
            except ValueError:
                log.add_error("Usage: :harness fork <run_id> [after_index]")
                return
        try:
            from superqode.harness import FileHarnessStore, fork_harness_run
        except Exception as exc:
            log.add_error(f"Harness fork is unavailable: {exc}")
            return
        try:
            fork = fork_harness_run(
                FileHarnessStore(Path(spec.context.session_storage)),
                run_id,
                after=after,
            )
        except Exception as exc:
            log.add_error(f"Could not fork harness run {run_id}: {exc}")
            return
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Fork\n\n", style=f"bold {THEME['text']}")
        t.append("  Source      ", style=THEME["muted"])
        t.append(str(fork["fork_of"]), style=THEME["cyan"])
        t.append("\n  Fork        ", style=THEME["muted"])
        t.append(str(fork["run_id"]), style=f"bold {THEME['success']}")
        t.append("\n  Events      ", style=THEME["muted"])
        t.append(str(fork["events"]), style=THEME["text"])
        t.append("\n\n  Next        ", style=THEME["muted"])
        t.append(f":harness events {fork['run_id']}", style=THEME["cyan"])
        t.append("  ", style="")
        t.append(f":harness graph {fork['run_id']}", style=THEME["cyan"])
        t.append("\n")
        self._show_command_output(log, t)

    def _show_harness_events(self, log, run_id: str) -> None:
        """Show the persisted event timeline for a harness run."""
        spec, _path = self._active_harness_spec()
        if spec is None:
            log.add_error("No HarnessSpec is active. Load one with :harness <spec.yaml>.")
            return
        try:
            from superqode.harness import FileHarnessStore
        except Exception as exc:
            log.add_error(f"Harness events are unavailable: {exc}")
            return
        run_id = run_id.strip()
        try:
            events = FileHarnessStore(Path(spec.context.session_storage)).get_events(run_id)
        except Exception as exc:
            log.add_error(f"Could not load harness events for {run_id}: {exc}")
            return

        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Events\n\n", style=f"bold {THEME['text']}")
        t.append("  Run         ", style=THEME["muted"])
        t.append(run_id, style=f"bold {THEME['cyan']}")
        t.append(f"  {len(events)} event(s)\n\n", style=THEME["dim"])
        if not events:
            t.append("  No persisted events found.\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return
        for index, event in enumerate(events[:80]):
            style = self._harness_event_style(event.type)
            t.append(f"  {index:04d} ", style=THEME["dim"])
            t.append(f"{event.type:<30}", style=f"bold {style}")
            preview = self._harness_event_preview(event)
            if preview:
                t.append(preview, style=THEME["text"])
            t.append("\n")
        if len(events) > 80:
            t.append(f"  ... {len(events) - 80} more event(s)\n", style=THEME["muted"])
        t.append("\n  Next        ", style=THEME["muted"])
        t.append(f":harness graph {run_id}", style=THEME["cyan"])
        t.append("  ", style="")
        t.append(f":harness evidence {run_id}", style=THEME["cyan"])
        t.append("\n")
        self._show_command_output(log, t)

    def _harness_event_style(self, event_type: str) -> str:
        """Return a theme color for a harness event type."""
        if "failed" in event_type or "error" in event_type:
            return THEME["error"]
        if "completed" in event_type or "result" in event_type:
            return THEME["success"]
        if event_type.startswith("checks."):
            return THEME["gold"]
        if event_type.startswith("workflow."):
            return THEME["cyan"]
        if event_type.startswith("workspace."):
            return THEME["purple"]
        if event_type == "harness.hook.error":
            return THEME["error"]
        if event_type == "harness.permission.check":
            return THEME["warning"]
        if event_type.startswith("harness.compaction."):
            return THEME["gold"]
        if event_type == "harness.stop":
            return THEME["success"]
        if event_type.startswith("harness."):
            return THEME["purple"]
        if event_type.startswith("approval"):
            return THEME["warning"]
        return THEME["text"]

    def _harness_event_preview(self, event) -> str:
        """Build a compact one-line event preview."""
        data = getattr(event, "data", {}) or {}
        fields = []
        for key in (
            "step_id",
            "status",
            "detail",
            "name",
            "command",
            "child_run_id",
            "file_count",
            "returncode",
            "error",
            "content_preview",
            "tool",
            "handler",
            "point",
            "stopped_reason",
            "iterations",
            "tool_calls_made",
        ):
            value = data.get(key)
            if value in (None, "", [], {}):
                continue
            fields.append(f"{key}={value}")
        arguments = data.get("arguments")
        if isinstance(arguments, dict):
            keys = arguments.get("keys")
            if keys:
                fields.append("arg_keys=" + ",".join(str(k) for k in keys[:8]))
            preview = arguments.get("preview")
            if isinstance(preview, dict):
                for key, value in list(preview.items())[:4]:
                    fields.append(f"{key}={value}")
        preview = "  ".join(fields)
        preview = preview.replace("\n", " ")
        return preview[:137] + "..." if len(preview) > 140 else preview

    def _active_harness_spec(self):
        """Return the active HarnessSpec and source path, if one is configured."""
        import os as _os

        pure = getattr(self, "_pure_mode", None)
        spec = getattr(pure, "_harness_spec", None) if pure is not None else None
        path = getattr(pure, "_harness_path", "") if pure is not None else ""
        if spec is not None:
            return spec, path

        env_path = _os.getenv("SUPERQODE_HARNESS", "").strip()
        if not env_path:
            return None, ""
        try:
            from superqode.harness import load_harness_spec

            return load_harness_spec(env_path), env_path
        except Exception:
            return None, env_path


    def _workflow_steps_from_spec(self, spec, prompt: str):
        """Build runnable workflow steps from HarnessSpec agents and a user prompt."""
        from superqode.harness import workflow_steps_from_spec

        return workflow_steps_from_spec(spec, prompt)

    def _show_workflow_center(self, log) -> None:
        """Render the active HarnessSpec workflow center."""
        spec, path = self._active_harness_spec()
        if spec is not None:
            from superqode.harness import apply_workflow_preset

            spec = apply_workflow_preset(spec)
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Workflow Run Center\n\n", style=f"bold {THEME['text']}")

        if spec is None:
            t.append("  Harness     ", style=THEME["muted"])
            t.append("not loaded\n", style=THEME["warning"])
            if path:
                t.append("  Spec        ", style=THEME["muted"])
                t.append(f"{path} could not be loaded\n", style=THEME["error"])
            t.append("\n  Load one with ", style=THEME["muted"])
            t.append(":harness <spec.yaml>", style=THEME["cyan"])
            t.append(" or inspect templates with ", style=THEME["muted"])
            t.append(":harness templates\n", style=THEME["cyan"])
            self._show_command_output(log, t)
            return

        provider, model = self._workflow_provider_model(spec)
        workflow = spec.workflow
        t.append("  Harness     ", style=THEME["muted"])
        t.append(spec.name, style=f"bold {THEME['cyan']}")
        t.append(f"  {spec.flavor.value}", style=THEME["dim"])
        if path:
            t.append(f"\n  Spec        {path}", style=THEME["dim"])
        t.append("\n  Runtime     ", style=THEME["muted"])
        t.append(spec.runtime.backend, style=THEME["text"])
        t.append("\n  Workflow    ", style=THEME["muted"])
        t.append(workflow.mode.value, style=f"bold {THEME['success']}")
        if workflow.preset:
            t.append(f"  preset={workflow.preset}", style=THEME["dim"])
        t.append(f"  parallelism={workflow.parallelism}", style=THEME["dim"])
        t.append("\n  Model       ", style=THEME["muted"])
        if provider and model:
            t.append(f"{provider}/{model}", style=THEME["text"])
        else:
            t.append("not connected", style=THEME["warning"])

        agents = list(getattr(spec, "agents", ()) or ())
        t.append("\n\n  Steps\n", style=f"bold {THEME['text']}")
        if agents:
            for index, agent in enumerate(agents, 1):
                t.append(f"  [{index}] ", style=THEME["dim"])
                t.append(agent.id, style=f"bold {THEME['cyan']}")
                if agent.role:
                    t.append(f"  {agent.role}", style=THEME["muted"])
                if agent.model:
                    t.append(f"  model={agent.model}", style=THEME["dim"])
                t.append("\n")
        else:
            t.append("  [1] prompt step generated from the run input\n", style=THEME["muted"])

        t.append("\n  Commands    ", style=THEME["muted"])
        t.append(":workflow run <task>", style=THEME["cyan"])
        t.append("  ", style="")
        t.append(":workflow status", style=THEME["cyan"])
        t.append("\n", style="")
        self._show_command_output(log, t)

    def _show_workflow_presets(self, log) -> None:
        """Show built-in HarnessSpec workflow presets."""
        from superqode.harness import list_workflow_presets

        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Workflow Presets\n\n", style=f"bold {THEME['text']}")
        for preset in list_workflow_presets():
            t.append("  ", style="")
            t.append(preset.name, style=f"bold {THEME['cyan']}")
            t.append(f"  {preset.mode.value}", style=THEME["success"])
            t.append(f"  {preset.description}\n", style=THEME["muted"])
        t.append("\n  Use in HarnessSpec YAML: ", style=THEME["muted"])
        t.append("workflow: { preset: parallel-review }\n", style=THEME["cyan"])
        self._show_command_output(log, t)

    def _workflow_preview_text(self, spec, prompt: str) -> Text:
        """Render a preflight preview for the active HarnessSpec workflow."""
        from superqode.harness import apply_workflow_preset

        spec = apply_workflow_preset(spec)
        provider, model = self._workflow_provider_model(spec)
        steps = self._workflow_steps_from_spec(spec, prompt or "your task")
        policy = spec.execution_policy
        blocked = 0
        warnings = 0

        def status(ok: bool, warn: bool = False) -> tuple[str, str, str]:
            nonlocal blocked, warnings
            if ok:
                return "✓", "ready", THEME["success"]
            if warn:
                warnings += 1
                return "!", "warn", THEME["warning"]
            blocked += 1
            return "!", "blocked", THEME["error"]

        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Workflow Preview\n\n", style=f"bold {THEME['text']}")
        t.append("  Harness     ", style=THEME["muted"])
        t.append(spec.name, style=f"bold {THEME['cyan']}")
        t.append(f"  {spec.flavor.value}\n", style=THEME["dim"])
        t.append("  Workflow    ", style=THEME["muted"])
        t.append(spec.workflow.mode.value, style=f"bold {THEME['success']}")
        if spec.workflow.preset:
            t.append(f"  preset={spec.workflow.preset}", style=THEME["dim"])
        t.append(f"  parallelism={spec.workflow.parallelism}\n", style=THEME["dim"])
        t.append("  Runtime     ", style=THEME["muted"])
        t.append(spec.runtime.backend, style=THEME["text"])
        t.append("\n  Model       ", style=THEME["muted"])
        if provider and model:
            t.append(f"{provider}/{model}", style=THEME["text"])
        else:
            t.append("not selected", style=THEME["warning"])
        t.append("\n  Task        ", style=THEME["muted"])
        t.append(
            prompt or "(no task supplied)", style=THEME["text"] if prompt else THEME["warning"]
        )

        t.append("\n\n  Steps\n", style=f"bold {THEME['text']}")
        for index, step in enumerate(steps, 1):
            step_id = step.id or f"step-{index}"
            t.append("  ✓ ", style=THEME["success"])
            t.append(f"{index:02d}. ", style=THEME["dim"])
            t.append(step_id, style=f"bold {THEME['cyan']}")
            role = step.metadata.get("role") if isinstance(step.metadata, dict) else ""
            if role:
                t.append(f"  {role}", style=THEME["muted"])
            t.append("\n")

        t.append("\n  Readiness\n", style=f"bold {THEME['text']}")
        icon, label, style = status(bool(provider and model))
        t.append(f"  {icon} model       {label}", style=style)
        if not provider or not model:
            t.append("  connect BYOK/local or set model_policy.primary", style=THEME["muted"])
        t.append("\n")

        icon, label, style = status(bool(steps))
        t.append(f"  {icon} steps       {label}  {len(steps)} step(s)\n", style=style)

        icon, label, style = status(policy.allow_read, warn=True)
        t.append(f"  {icon} read        {label}\n", style=style)

        write_required = spec.flavor.value == "coding"
        icon, label, style = status(policy.allow_write or not write_required, warn=write_required)
        t.append(f"  {icon} write       {label}", style=style)
        if not policy.allow_write:
            t.append("  read-only harness", style=THEME["muted"])
        t.append("\n")

        icon, label, style = status(policy.allow_shell or not policy.allowed_commands, warn=True)
        t.append(f"  {icon} shell       {label}", style=style)
        if policy.allowed_commands:
            t.append(f"  {', '.join(policy.allowed_commands[:3])}", style=THEME["muted"])
        t.append("\n")

        t.append("  ✓ approvals   ", style=THEME["success"])
        t.append(policy.approval_profile, style=THEME["text"])
        t.append("\n")

        mcp_servers = []
        if isinstance(spec.runtime.config, dict):
            raw_mcp = spec.runtime.config.get("mcp_servers") or spec.runtime.config.get("mcp")
            if isinstance(raw_mcp, dict):
                mcp_servers = list(raw_mcp)
            elif isinstance(raw_mcp, list):
                mcp_servers = [str(item) for item in raw_mcp]
        icon, label, style = status(True, warn=bool(mcp_servers))
        t.append(f"  {icon} MCP         {label}", style=style)
        if mcp_servers:
            t.append(f"  declared: {', '.join(mcp_servers[:4])}", style=THEME["muted"])
        else:
            t.append("  none declared", style=THEME["muted"])
        t.append("\n")

        overall = "blocked" if blocked else "warnings" if warnings else "ready"
        overall_style = (
            THEME["error"] if blocked else THEME["warning"] if warnings else THEME["success"]
        )
        t.append("\n  Result      ", style=THEME["muted"])
        t.append(overall, style=f"bold {overall_style}")
        t.append(f"  ({blocked} blocked, {warnings} warning(s))\n", style=THEME["dim"])
        if not blocked:
            t.append("\n  Run with    ", style=THEME["muted"])
            t.append(
                f':workflow run "{prompt}"\n' if prompt else ":workflow run <task>\n",
                style=THEME["cyan"],
            )
        return t

    def _show_workflow_preview(self, log, prompt: str = "") -> None:
        """Show a readiness preview for the active workflow."""
        spec, path = self._active_harness_spec()
        if spec is None:
            t = Text()
            t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
            t.append("Workflow Preview\n\n", style=f"bold {THEME['text']}")
            t.append("  Harness     ", style=THEME["muted"])
            t.append("not loaded\n", style=THEME["warning"])
            if path:
                t.append("  Spec        ", style=THEME["muted"])
                t.append(f"{path} could not be loaded\n", style=THEME["error"])
            t.append("\n  Load one with ", style=THEME["muted"])
            t.append(":harness <spec.yaml>\n", style=THEME["cyan"])
            self._show_command_output(log, t)
            return
        self._show_command_output(log, self._workflow_preview_text(spec, prompt))

    def _workflow_timeline_text(
        self,
        *,
        title: str,
        mode: str,
        step_ids: list[str],
        states: dict[str, str],
        details: dict[str, str] | None = None,
    ) -> Text:
        """Render a compact workflow timeline for the TUI log."""
        details = details or {}
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append(title, style=f"bold {THEME['text']}")
        t.append(f"  {mode}\n\n", style=THEME["dim"])
        status_icons = {
            "pending": "○",
            "running": "●",
            "done": "✓",
            "failed": "!",
        }
        status_styles = {
            "pending": THEME["dim"],
            "running": THEME["cyan"],
            "done": THEME["success"],
            "failed": THEME["error"],
        }
        for index, step_id in enumerate(step_ids, 1):
            state = states.get(step_id, "pending")
            style = status_styles.get(state, THEME["text"])
            t.append(f"  {status_icons.get(state, '○')} ", style=f"bold {style}")
            t.append(f"{index:02d}. ", style=THEME["dim"])
            t.append(step_id, style=f"bold {style}" if state != "pending" else style)
            t.append(f"  {state}", style=style)
            if details.get(step_id):
                t.append(f"  {details[step_id]}", style=THEME["muted"])
            t.append("\n")
        return t

    async def _workflow_cmd(self, args: str, log) -> None:
        """Handle HarnessSpec workflow status and explicit workflow runs."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :workflow arguments: {exc}")
            return
        action = tokens[0].lower() if tokens else "status"
        rest = tokens[1:]
        if action in {"presets", "templates"}:
            self._show_workflow_presets(log)
            return
        if action in {"preview", "doctor", "check"}:
            self._show_workflow_preview(log, " ".join(rest).strip())
            return
        if action in {"status", "list", "center", "dashboard", "show"}:
            self._show_workflow_center(log)
            return
        if action not in {"run", "start"}:
            log.add_info(
                "Usage: :workflow status | :workflow preview <task> | :workflow run <task>"
            )
            return

        prompt = " ".join(rest).strip()
        if not prompt:
            log.add_error("Usage: :workflow run <task>")
            return
        spec, path = self._active_harness_spec()
        if spec is None:
            log.add_error("No HarnessSpec is active. Load one with :harness <spec.yaml>.")
            return

        provider, model = self._workflow_provider_model(spec)
        if not provider or not model:
            log.add_error(
                "Connect a BYOK/local provider or set model_policy.primary before running workflows."
            )
            return

        try:
            from superqode.harness import FileHarnessStore, init_harness, run_workflow
        except Exception as exc:
            log.add_error(f"Workflow support is unavailable: {exc}")
            return

        steps = self._workflow_steps_from_spec(spec, prompt)
        step_ids = [step.id or f"step-{index + 1}" for index, step in enumerate(steps)]
        states = dict.fromkeys(step_ids, "pending")
        details: dict[str, str] = {}
        log.write(
            self._workflow_timeline_text(
                title="Workflow started",
                mode=spec.workflow.mode.value,
                step_ids=step_ids,
                states=states,
                details=details,
            )
        )

        def on_progress(progress) -> None:
            step_id = progress.step_id
            if step_id not in states:
                step_ids.append(step_id)
            states[step_id] = progress.status
            if progress.detail:
                details[step_id] = progress.detail
            log.write(
                self._workflow_timeline_text(
                    title="Workflow timeline",
                    mode=progress.mode.value,
                    step_ids=step_ids,
                    states=states,
                    details=details,
                )
            )

        try:
            pure = getattr(self, "_pure_mode", None)
            kernel = getattr(pure, "_harness_kernel", None) if pure is not None else None
            if kernel is None or not isinstance(getattr(kernel, "store", None), FileHarnessStore):
                kernel = await init_harness(
                    spec,
                    store=FileHarnessStore(Path(spec.context.session_storage)),
                )
                if pure is not None:
                    pure._harness_kernel = kernel
            result = await run_workflow(
                kernel,
                steps,
                provider=provider,
                model=model,
                working_directory=Path.cwd(),
                runtime=spec.runtime.backend,
                sandbox_backend=spec.execution_policy.sandbox,
                session_id=f"workflow-{int(time.time())}",
                progress_callback=on_progress,
            )
        except Exception as exc:
            log.add_error(f"Workflow failed: {exc}")
            return

        self._last_workflow_result = result
        self._refresh_harness_panel()
        done = Text()
        done.append("\n  ✓ ", style=f"bold {THEME['success']}")
        done.append("Workflow complete", style=f"bold {THEME['text']}")
        done.append(
            f"  {result.mode.value}, {len(result.results)} result(s)\n\n", style=THEME["dim"]
        )
        if getattr(result, "run_id", ""):
            done.append("Run graph: ", style=THEME["muted"])
            done.append(f":harness graph {result.run_id}\n\n", style=THEME["cyan"])
        if result.content:
            done.append(result.content, style=THEME["text"])
            done.append("\n", style="")
        log.write(done)

    async def _approval_cmd(self, action: str, args: str, log) -> None:
        """Handle :approve / :reject for the OpenAI Agents HITL flow.

        Usage:
            :approve              # approve pending #0 (the first interruption)
            :approve 1            # approve pending #1
            :approve always       # approve #0 and remember the choice
            :reject               # reject pending #0
            :reject 1 "<msg>"     # reject pending #1 with explicit message
        """
        pure = getattr(self, "_pure_mode", None)
        if pure is None or not hasattr(pure, "get_pending_approvals"):
            log.add_error("No active session supports interactive approvals.")
            return

        pending = pure.get_pending_approvals()
        if not pending:
            log.add_info("No pending approvals.")
            return

        # Parse args: optional integer index, optional "always", optional quoted message
        tokens = args.strip().split(maxsplit=1)
        index = 0
        always = False
        message: Optional[str] = None
        if tokens:
            head = tokens[0].lower()
            tail = tokens[1] if len(tokens) > 1 else ""
            if head.isdigit():
                index = int(head)
                if tail.lower().startswith("always"):
                    always = True
                    rest = tail.split(maxsplit=1)
                    if len(rest) > 1:
                        message = rest[1].strip().strip('"').strip("'")
                elif tail:
                    message = tail.strip().strip('"').strip("'")
            elif head == "always":
                always = True
                if tail:
                    message = tail.strip().strip('"').strip("'")
            else:
                # Treat the whole arg as the rejection message.
                message = args.strip().strip('"').strip("'")

        if index < 0 or index >= len(pending):
            log.add_error(f"Approval index {index} out of range (0..{len(pending) - 1}).")
            return
        choice = pending[index]
        try:
            if action == "approve":
                response = await pure.approve_and_resume(index=index, always=always)
                log.add_info(
                    f"Approved tool '{choice['tool_name']}'" + (" (always)" if always else "") + "."
                )
            else:
                response = await pure.reject_and_resume(index=index, message=message, always=always)
                log.add_info(
                    f"Rejected tool '{choice['tool_name']}'"
                    + (f": {message}" if message else "")
                    + "."
                )
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"{action.capitalize()} failed: {type(exc).__name__}: {exc}")
            return

        # Show resumed run result.
        if getattr(response, "stopped_reason", "") == "needs_approval":
            self._announce_pending_approvals(pure, log)
        elif response.error:
            log.add_error(f"Run failed: {response.error}")
        elif response.content:
            log.add_info(response.content)

    def _announce_pending_approvals(self, source, log) -> None:
        """Surface pending approvals from an active runtime or HarnessSpec session."""
        try:
            pending = source.get_pending_approvals()
        except Exception:  # noqa: BLE001
            return
        if not pending:
            return
        card = Text()
        card.append("🔐 Tool approval needed\n\n", style=f"bold {THEME['warning']}")
        card.append(f"{len(pending)} pending item(s)\n", style=THEME["text"])
        for entry in pending:
            tool = entry.get("tool_name") or "<unknown>"
            args_preview = str(entry.get("arguments", {}))
            if len(args_preview) > 120:
                args_preview = args_preview[:117] + "..."
            card.append("\n[", style=THEME["muted"])
            card.append(str(entry.get("index", 0)), style=f"bold {THEME['cyan']}")
            card.append("] ", style=THEME["muted"])
            card.append(tool, style=f"bold {THEME['text']}")
            card.append(f"  {args_preview}", style=THEME["muted"])
        card.append("\n\n")
        card.append(":approve [N]", style=f"bold {THEME['success']}")
        card.append("  •  ", style=THEME["dim"])
        card.append(":reject [N]", style=f"bold {THEME['error']}")
        card.append(' ["message"]', style=THEME["muted"])
        log.write(
            Panel(
                card,
                title=f"[bold {THEME['warning']}]Action approval[/]",
                border_style=THEME["warning"],
                box=ROUNDED,
                padding=(1, 2),
            )
        )

    def _handle_resume_session(self, args: str, log: ConversationLog):
        """Resume a previous local provider session."""
        session_id = args.strip()
        if not session_id:
            self._show_session_resume_picker(log)
            return

        pure_mode = self._ensure_pure_mode()
        messages = pure_mode.resume_session(session_id)
        if not messages:
            log.add_error(f"Session not found or prefix is ambiguous: {session_id}")
            log.add_info("Use /sessions to view recent session ids.")
            return

        resolved_id = pure_mode.get_current_session_id() or session_id
        self._awaiting_session_resume = False
        log.add_info(f"Resumed session {resolved_id[:8]} with {len(messages)} messages.")
        for message in messages[-6:]:
            role = str(message.get("role", "?")).upper()
            content = str(message.get("content", "")).replace("\n", " ")[:120]
            log.add_info(f"[{role}] {content}")

    def _handle_fork_session(self, args: str, log: ConversationLog):
        """Fork the active local provider session."""
        if not hasattr(self, "_pure_mode") or not self._pure_mode.get_current_session_id():
            log.add_error("No active local provider session to fork.")
            log.add_info("Use /resume <id> or connect with :connect byok/:connect local first.")
            return

        new_id = args.strip() or None
        try:
            fork_id = self._pure_mode.fork_current_session(new_id)
        except Exception as exc:
            log.add_error(f"Could not fork session: {exc}")
            return
        log.add_info(f"Forked current session to {fork_id}.")

    def _handle_compact(self, log: ConversationLog):
        """Compact or enable compaction for the active local provider session."""
        if not hasattr(self, "_pure_mode") or not self._pure_mode.session.connected:
            log.add_error("No active local provider session to compact.")
            log.add_info("Use :connect byok or :connect local first.")
            return

        result = self._pure_mode.compact()
        if result.get("success"):
            log.add_info(result["message"])
            log.add_info(
                f"Session {result.get('session_id', '')[:8]}: {result.get('message_count', 0)} stored messages, max context {result.get('max_context_tokens')} tokens."
            )
        else:
            log.add_error(result.get("message", "Compaction is not available."))

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
            t.append(" - What would you like to build?\n", style=THEME["muted"])
        else:
            t.append("  ✨ Ready - What would you like to build?\n", style=THEME["muted"])
        t.append("\n")
        log.write(t)

    def _init_config(self, args: str, log: ConversationLog):
        """Initialize superqode.yaml and local-first starter harnesses."""
        from pathlib import Path

        from superqode.main import _scaffold_project_config

        force = args.strip() == "--force" or args.strip() == "-f"
        config_path = Path.cwd() / "superqode.yaml"

        if config_path.exists() and not force:
            log.add_info(f"Configuration already exists at {config_path}")
            log.add_system("Use :init --force to overwrite")
            return

        try:
            created_config, harness_paths = _scaffold_project_config(force=force)
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not initialize project config: {exc}")
            return

        log.add_success(f"Created local-first config at {created_config}")
        for path in harness_paths:
            log.add_success(f"Created local-first harness at {path}")
        log.add_info(
            "💡 Defaults use Ollama and qwen3:8b. Use :connect local and :harness .superqode/harnesses/coding.yaml."
        )

        t = Text()
        t.append("\n  Quick start:\n", style=THEME["muted"])
        t.append("    :connect local          ", style=f"bold {THEME['cyan']}")
        t.append("Connect Ollama, LM Studio, MLX, or DS4\n", style=THEME["dim"])
        t.append("    :harness .superqode/harnesses/coding.yaml\n", style=f"bold {THEME['purple']}")
        t.append("Use the generated local-first harness\n", style=THEME["dim"])
        t.append("    :local init --yes       ", style=f"bold {THEME['success']}")
        t.append("Generate a hardware-tuned local harness when ready\n", style=THEME["dim"])
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
                t.append(f" - {desc}", style=THEME["muted"])
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

    def _active_agent_loop(self):
        """The live AgentLoop for the current BYOK/local session, if any."""
        pure = getattr(self, "_pure_mode", None)
        return getattr(pure, "_agent", None) if pure is not None else None

    def _handle_context(self, args: str, log: ConversationLog):
        """Show or override the context window used for adaptive compaction.

        :context              show detected window, source, and compaction budgets
        :context <tokens>     pin the window (e.g. :context 8192)
        :context auto         clear the override and re-detect from the server
        """
        agent = self._active_agent_loop()
        if agent is None:
            log.add_error("No active model session. Connect a local/BYOK model first.")
            return

        arg = args.strip().lower()

        if arg in ("", "show", "status"):
            self.run_worker(self._context_show_worker(agent, log), exclusive=False)
            return

        if arg in ("auto", "detect", "reprobe", "re-probe"):
            agent.config.context_window = 0
            agent._cached_context_window = 0
            self.run_worker(self._context_show_worker(agent, log, redetect=True), exclusive=False)
            return

        try:
            tokens = int(arg.replace("k", "000") if arg.endswith("k") else arg)
        except ValueError:
            log.add_error("Usage: :context [<tokens> | auto]")
            return
        if tokens < 512:
            log.add_error("Context window must be at least 512 tokens.")
            return

        agent.config.context_window = tokens
        agent._cached_context_window = tokens
        agent._context_window_source = "configured"
        threshold, keep_recent, window = agent._compaction_budgets()
        log.add_success(f"🪟 Context window pinned to {window:,} tokens")
        log.add_system(
            f"Compaction triggers at {threshold:,} tokens · keeps ~{keep_recent:,} recent."
        )

    async def _context_show_worker(self, agent, log, redetect: bool = False) -> None:
        try:
            if redetect:
                await agent._ensure_context_window()
            else:
                # Resolve once if it hasn't been (e.g. before the first turn).
                if not getattr(agent, "_cached_context_window", 0):
                    await agent._ensure_context_window()
            threshold, keep_recent, window = agent._compaction_budgets()
            source = getattr(agent, "_context_window_source", "unknown")
        except Exception as exc:
            self._call_ui(log.add_error, f"Context detection failed: {exc}")
            return

        t = Text()
        t.append("\n  🪟 ", style=f"bold {THEME['cyan']}")
        t.append("Context window\n\n", style=f"bold {THEME['text']}")
        t.append(f"    Window:      {window:,} tokens  ", style=THEME["text"])
        t.append(f"({source})\n", style=THEME["muted"])
        t.append(f"    Compact at:  {threshold:,} tokens\n", style=THEME["muted"])
        t.append(f"    Keep recent: ~{keep_recent:,} tokens\n", style=THEME["muted"])
        auto = os.environ.get("SUPERQODE_AUTO_COMPACT", "").strip().lower()
        on = auto not in ("0", "false", "no", "off")
        t.append(
            f"    Auto-compact: {'ON' if on else 'OFF'}\n",
            style=THEME["success" if on else "muted"],
        )
        t.append("\n    ", style="")
        t.append(":context <n>", style=f"bold {THEME['cyan']}")
        t.append(" to pin  ·  ", style=THEME["muted"])
        t.append(":context auto", style=f"bold {THEME['cyan']}")
        t.append(" to re-detect\n", style=THEME["muted"])
        self._call_ui(self._show_command_output, log, t)

    def _handle_workspace(self, args: str, log: ConversationLog):
        """Manage the multi-repo search workspace: :workspace add|remove|list."""
        from superqode.search_registry import (
            add_workspace_root,
            list_workspace_roots,
            remove_workspace_root,
        )

        parts = args.strip().split(maxsplit=1)
        sub = (parts[0].lower() if parts else "list") or "list"
        target = parts[1].strip() if len(parts) > 1 else ""

        if sub in ("add", "a"):
            if not target:
                log.add_error("Usage: :workspace add <path>")
                return
            try:
                added = add_workspace_root(target)
            except ValueError as exc:
                log.add_error(str(exc))
                return
            log.add_success(f"📁 Added to workspace: {added}")
            log.add_system("Search it with `--all-repos` (or pass its absolute path).")
            return

        if sub in ("remove", "rm", "del", "delete"):
            if not target:
                log.add_error("Usage: :workspace remove <path>")
                return
            removed = remove_workspace_root(target)
            if removed:
                log.add_success(f"🗑️  Removed from workspace: {target}")
            else:
                log.add_info(f"Not in workspace: {target}")
            return

        if sub in ("list", "ls", ""):
            roots = list_workspace_roots()
            t = Text()
            t.append("Search workspace\n\n", style=f"bold {THEME['purple']}")
            if not roots:
                t.append("  No repos registered yet.\n\n", style=THEME["muted"])
                t.append("  Add one with ", style=THEME["muted"])
                t.append(":workspace add <path>", style=f"bold {THEME['cyan']}")
                t.append("\n", style="")
            else:
                for r in roots:
                    t.append("  📁 ", style=THEME["cyan"])
                    t.append(f"{r}\n", style=THEME["text"])
                t.append(f"\n  {len(roots)} repo(s) · search all with ", style=THEME["muted"])
                t.append("--all-repos", style=f"bold {THEME['cyan']}")
                t.append("\n", style="")
            self._show_command_output(log, t)
            return

        log.add_error(f"Unknown :workspace action: {sub}")
        log.add_system("Valid: add <path>, remove <path>, list")

    def _handle_thinking_verbosity(self, args: str, log: ConversationLog):
        """Handle :thinking command to control thinking-log detail.

        Usage: :thinking [normal|verbose|off]   (no arg shows current state)
        """
        level = args.strip().lower()
        aliases = {
            "normal": "normal",
            "summary": "normal",
            "calm": "normal",
            "verbose": "verbose",
            "full": "verbose",
            "debug": "verbose",
            "off": "off",
            "hide": "off",
            "none": "off",
        }

        if not level:
            current = self._current_thinking_state()
            t = Text()
            t.append("Thinking-log detail\n\n", style=f"bold {THEME['purple']}")
            rows = [
                (
                    "normal",
                    "◆",
                    THEME["cyan"],
                    "Iterations fold into a live status; reasoning trimmed",
                ),
                ("verbose", "◈", THEME["purple"], "Every iteration + full streamed reasoning"),
                ("off", "◇", THEME["muted"], "Hidden; only tool calls and the final answer"),
            ]
            for lvl, icon, color, desc in rows:
                marker = " ◀ current" if current == lvl else ""
                t.append(f"    {icon} ", style=color)
                t.append(f":thinking {lvl:<8}", style=f"bold {color}")
                t.append(f" - {desc}", style=THEME["muted"])
                if marker:
                    t.append(marker, style=f"bold {color}")
                t.append("\n", style="")
            t.append("\n  💡 ", style=THEME["muted"])
            t.append("Ctrl+T cycles Normal → Verbose → Off\n", style=THEME["dim"])
            self._show_command_output(log, t)
            return

        if level not in aliases:
            log.add_error(f"Invalid thinking level: {level}")
            log.add_system("Valid levels: normal, verbose, off")
            return

        state = aliases[level]
        self._apply_thinking_state(state)
        icons = {"normal": "◆", "verbose": "◈", "off": "◇"}
        descs = {
            "normal": "Iterations fold into a live status; reasoning is trimmed",
            "verbose": "Showing every iteration and the full streamed reasoning",
            "off": "Thinking logs hidden — only tool calls and the final answer",
        }
        log.add_success(f"{icons[state]} Thinking: {state.upper()}")
        log.add_system(descs[state])

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
            current_log = self.query_one("#log", ConversationLog)
            current_verbosity = getattr(current_log, "tool_output_mode", current_verbosity)

            levels = [
                ("minimal", "◇", THEME["muted"], "Status only - no content"),
                ("normal", "◆", THEME["cyan"], "Summarized tool outputs"),
                ("verbose", "◈", THEME["purple"], "Full outputs with syntax highlighting"),
            ]

            for lvl, icon, color, desc in levels:
                current = " ◀ current" if current_verbosity == lvl else ""
                t.append(f"    {icon} ", style=color)
                t.append(f":log {lvl:<10}", style=f"bold {color}")
                t.append(f" - {desc}", style=THEME["muted"])
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
            log.tool_output_mode = display_level

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


    # ========================================================================
    # Message Handling
    # ========================================================================

    def _handle_message(self, text: str, log: ConversationLog):
        session = get_session()
        mode = get_mode()

        # Skip permission input handling when using modal dialogs
        # (permissions are handled directly in the modal)
        if self._handle_agent_question_input(text, log):
            return

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

        if getattr(self, "_awaiting_recommendation_selection", False):
            if self._handle_recommendation_selection(text, log):
                return

        if getattr(self, "is_busy", False):
            # Type-ahead: queue the message and send it when the agent is free.
            self._enqueue_message(text)
            return

        # Hub (model-search) mode: a typed line is a model name to look up, so
        # the user can browse the catalog without retyping ":local search".
        if getattr(self, "_hub_mode", False):
            log.add_user(text)
            self._last_user_message = text
            self.run_worker(self._local_search(text, log))
            return

        # Chat mode: a raw, direct-to-model conversation. No repo context, no
        # tools, no system scaffolding, no @file/MCP/plan expansion. This is the
        # fastest way to feel the model's latency and decode speed.
        if getattr(self, "_chat_mode", False):
            chat_ready, chat_message, _who = self._direct_chat_status()
            if not chat_ready:
                log.add_error(chat_message)
                self._chat_mode = False
                self._refresh_prompt_mode_label()
                return
            log.add_user(text)
            self._last_user_message = text
            self._update_terminal_title(text)
            self.is_busy = True
            self._cancel_requested = False
            self._chat_worker(text, log)
            return

        text, inline_mcp_refs = self._extract_mcp_refs_from_text(text)
        staged_mcp_refs = [
            ref for ref in getattr(self, "_attached_refs", []) if ref.startswith("mcp://")
        ]
        self._current_mcp_refs = list(dict.fromkeys([*inline_mcp_refs, *staged_mcp_refs]))

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

        plan_requested = getattr(self, "_force_plan_once", False) or (
            getattr(self, "_plan_mode_enabled", False)
            and not getattr(self, "_force_execute_once", False)
        )
        self._active_plan_mode_for_current_message = plan_requested
        self._force_plan_once = False
        self._force_execute_once = False
        if plan_requested:
            self._pending_plan_request = text
            self._pending_plan_status = "pending"
        self._refresh_plan_status_badge()

        log.add_user(text)
        self._last_user_message = text
        self._update_terminal_title(text)

        # Store file context for the message
        self._current_file_context = file_context

        # Check if in provider mode
        if hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
            self.is_busy = True
            self._cancel_requested = False
            self._send_to_pure_mode(text, log)
        elif session.is_connected_to_agent():
            self.is_busy = True
            self._cancel_requested = False
            agent = session.connected_agent
            # Get the actual agent name from the connected agent, not from old session state
            name = agent.get("short_name", agent.get("name", "agent")) if agent else "agent"
            if plan_requested:
                text = (
                    "PLAN MODE: Analyze the request and produce a concrete implementation plan. "
                    "Do not edit files, run commands that modify state, or make changes.\n\n"
                    f"{text}"
                )
            # Use standard subprocess approach (ACP requires separate adapter)
            self._send_to_agent(text, name, log)
        else:
            log.add_info("Not connected. Use :connect to choose a runtime or agent.")

    async def _ask_agent_question(self, question, log: ConversationLog):
        """Show an agent question in the TUI and await the next input submission."""
        from superqode.tools.question_tool import Answer

        future: concurrent.futures.Future = concurrent.futures.Future()

        def show_question():
            self._awaiting_agent_question = True
            self._pending_agent_question = question
            self._pending_agent_question_future = future
            self._permission_pending = True

            card = Text()
            card.append("🤔 Agent needs your input\n\n", style=f"bold {THEME['warning']}")
            card.append(str(question.question), style=f"bold {THEME['text']}")
            card.append("\n")
            if getattr(question, "options", None):
                card.append("\n")
                for idx, option in enumerate(question.options, 1):
                    card.append(f"  [{idx}] ", style=f"bold {THEME['cyan']}")
                    card.append(str(option), style=THEME["text"])
                    card.append("\n")
            if getattr(question, "default", None):
                card.append("\n  default: ", style=THEME["muted"])
                card.append(str(question.default), style=f"bold {THEME['muted']}")
                card.append("\n")
            card.append("\n  type a number, or your own answer", style=THEME["muted"])
            card.append("  •  ", style=THEME["dim"])
            card.append(":cancel", style=f"bold {THEME['cyan']}")
            card.append(" to skip", style=THEME["muted"])

            log.write(
                Panel(
                    card,
                    border_style=THEME["warning"],
                    box=ROUNDED,
                    padding=(1, 2),
                )
            )

            try:
                input_widget = self.query_one("#prompt-input", SelectionAwareInput)
                input_widget.placeholder = "Answer the agent question..."
                input_widget.focus()
            except Exception:
                pass
            self._start_permission_pulse()

        try:
            self._call_ui(show_question)
        except RuntimeError as e:
            message = str(e).lower()
            if "different thread" in message or "app thread" in message:
                show_question()
            else:
                raise

        answer = await asyncio.wrap_future(future)
        return Answer(value=answer["value"], custom=answer.get("custom", False))

    def _handle_agent_question_input(self, response: str, log: ConversationLog) -> bool:
        """Resolve a pending ask_user/confirm question from the prompt input."""
        if not getattr(self, "_awaiting_agent_question", False):
            return False

        future = getattr(self, "_pending_agent_question_future", None)
        question = getattr(self, "_pending_agent_question", None)
        if future is None or question is None:
            self._awaiting_agent_question = False
            return False

        raw = response.strip()
        lowered = raw.lower()

        # Quit must always quit, even mid-question. Fall through to the normal
        # command dispatcher; app teardown resolves the pending future. (Other
        # ":" input stays a literal answer — free-text replies are legitimate.)
        if lowered in (":quit", "/quit", ":exit", "/exit", ":q", "/q"):
            return False

        if lowered in (":cancel", "/cancel", ":back", "/back"):
            if not future.done():
                future.cancel()
            self._awaiting_agent_question = False
            self._pending_agent_question = None
            self._pending_agent_question_future = None
            self._permission_pending = False
            self._reset_input_placeholder()
            log.add_info("Agent question cancelled.")
            return True

        value: Any = raw
        custom = False
        default = getattr(question, "default", None)
        q_type = getattr(getattr(question, "question_type", None), "value", "text")
        options = list(getattr(question, "options", []) or [])

        if q_type == "confirm":
            if lowered in ("y", "yes", "true", "1", "ok", "confirm", "confirmed"):
                value = True
            elif lowered in ("n", "no", "false", "0", "deny", "denied"):
                value = False
            elif default is not None:
                value = str(default).lower() in ("yes", "true", "1", "y")
            else:
                log.add_info("Answer yes or no.")
                return True
        elif not raw and default is not None:
            value = default
        elif q_type in ("choice", "multi_choice") and options:
            selected: list[str] = []
            parts = [part.strip() for part in raw.split(",") if part.strip()]
            for part in parts:
                if part.isdigit() and 1 <= int(part) <= len(options):
                    selected.append(options[int(part) - 1])
                elif part in options:
                    selected.append(part)
                else:
                    custom = True
                    selected.append(part)
            value = selected if q_type == "multi_choice" else (selected[0] if selected else raw)

        if not future.done():
            future.set_result({"value": value, "custom": custom})

        self._awaiting_agent_question = False
        self._pending_agent_question = None
        self._pending_agent_question_future = None
        self._permission_pending = False
        self._reset_input_placeholder()
        log.add_info("Answered agent question. Continuing...")
        return True

    def _hub_cmd(self, args: str, log: ConversationLog):
        """Model-search mode: type a model name to find it (no `:local search`).

        ``:hub`` toggles the mode; ``:hub <name>`` does a one-shot search.
        """
        arg = (args or "").strip()
        low = arg.lower()

        if low in ("off", "stop", "exit"):
            self._hub_mode = False
            log.add_info("Model search OFF. Back to normal input.")
            return
        if low in ("on", "start"):
            self._hub_mode = True
        elif arg:
            # One-shot search; do not change the mode.
            self.run_worker(self._local_search(arg, log))
            return
        else:
            self._hub_mode = not getattr(self, "_hub_mode", False)

        if self._hub_mode:
            t = Text()
            t.append("\n  🔎 Model search ON\n", style=f"bold {THEME['cyan']}")
            t.append(
                "  Just type a model name to find it in the trusted catalog.\n",
                style=THEME["muted"],
            )
            t.append(
                "  Shows size, fit for your hardware, and the get-command.\n", style=THEME["muted"]
            )
            t.append("  Add ", style=THEME["muted"])
            t.append("--hub", style=f"bold {THEME['cyan']}")
            t.append(" on a line for the latest live from Hugging Face.\n", style=THEME["muted"])
            t.append("  Turn off with ", style=THEME["muted"])
            t.append(":hub off", style=f"bold {THEME['cyan']}")
            t.append("\n", style="")
            log.write(t)
        else:
            log.add_info("Model search OFF. Back to normal input.")

    def _direct_chat_status(self) -> tuple[bool, str, str]:
        """Return whether raw chat can talk to the active direct model session."""
        pure = getattr(self, "_pure_mode", None)
        pure_session = getattr(pure, "session", None)
        connected = bool(getattr(pure_session, "connected", False))
        provider = str(getattr(pure_session, "provider", "") or "").strip()
        model = str(getattr(pure_session, "model", "") or "").strip()

        execution_mode = str(self.__dict__.get("current_mode", "") or "").strip().lower()
        if not execution_mode:
            try:
                execution_mode = str(getattr(self, "current_mode", "") or "").strip().lower()
            except Exception:
                execution_mode = ""
        try:
            session_mode = str(getattr(get_session(), "execution_mode", "") or "").strip().lower()
        except Exception:
            session_mode = ""
        if execution_mode not in {"local", "byok", "pure", "acp"} and session_mode:
            execution_mode = session_mode

        direct_modes = {"local", "byok", "pure"}
        if connected and provider and model and execution_mode in direct_modes:
            return True, "", f"{provider}/{model}"

        if execution_mode == "acp" or getattr(self, "_acp_client", None) is not None:
            return (
                False,
                "Chat mode is only for Local/BYOK direct model sessions. "
                "ACP connections are full coding agents; use Build mode or Plan mode with them.",
                "",
            )

        return (
            False,
            "Chat mode needs a Local or BYOK direct model connection. "
            "Use :connect local or :connect byok first. ACP agents use Build/Plan mode.",
            "",
        )

    def _chat_cmd(self, args: str, log: ConversationLog):
        """Toggle raw direct-to-model chat mode (no repo context, no tools)."""
        arg = (args or "").strip().lower()
        if arg in ("clear", "reset"):
            self._chat_history = []
            log.add_info("Chat history cleared.")
            return
        if arg in ("off", "stop", "exit", "0", "false"):
            enable = False
        elif arg in ("on", "start", "1", "true"):
            enable = True
        else:
            enable = not getattr(self, "_chat_mode", False)

        if enable:
            chat_ready, chat_message, who = self._direct_chat_status()
            if not chat_ready:
                self._chat_mode = False
                self._refresh_prompt_mode_label()
                log.add_info(chat_message)
                return

        self._chat_mode = enable
        self._refresh_prompt_mode_label()
        if enable:
            self._chat_history = []
            t = Text()
            t.append("\n  💬 Chat mode ON\n", style=f"bold {THEME['cyan']}")
            t.append(
                "  Local/BYOK direct model chat: no repo context, no tools, no harness.\n",
                style=THEME["muted"],
            )
            t.append("  Every reply reports TTFT and decode tok/s.\n", style=THEME["muted"])
            t.append(f"  Model: {who}\n", style=THEME["dim"])
            t.append("  ACP agents use Build/Plan mode, not raw chat.\n", style=THEME["muted"])
            t.append("  Turn off with ", style=THEME["muted"])
            t.append(":chat off", style=f"bold {THEME['cyan']}")
            t.append("\n", style="")
            log.write(t)
        else:
            log.add_info("Chat mode OFF. Back to the full coding harness.")

    def _build_cmd(self, args: str, log: ConversationLog):
        """Return prompts to the repo-aware coding harness."""
        self._chat_mode = False
        self._plan_mode_enabled = False
        self._force_plan_once = False
        self._active_plan_mode_for_current_message = False
        self._refresh_plan_status_badge()
        log.add_success("Build mode ON. Repo context and tools are available for coding tasks.")
        log.add_info("Use :chat on for direct model chat, or :plan on to plan before edits.")


    def _current_interaction_mode_name(self) -> str:
        if getattr(self, "_chat_mode", False):
            return "chat"
        if getattr(self, "_plan_mode_enabled", False):
            return "plan"
        return "build"

    def _mode_cmd(self, args: str, log: ConversationLog) -> None:
        """Switch or pick Chat, Build, or Plan mode."""
        mode = (args or "").strip().lower()
        aliases = {
            "": "",
            "chat": "chat",
            "c": "chat",
            "build": "build",
            "b": "build",
            "code": "build",
            "plan": "plan",
            "p": "plan",
        }
        if mode in aliases and aliases[mode]:
            self._apply_interaction_mode(aliases[mode], log)
            return
        if mode in {"", "pick", "switch", "toggle"}:
            self._show_mode_picker(log)
            return
        log.add_info("Usage: :mode [chat|build|plan]")


    def _handle_mode_selection(self, text: str, log: ConversationLog) -> bool:
        value = (text or "").strip().lower()
        modes = self._mode_picker_items()
        if value.isdigit():
            idx = int(value) - 1
            if 0 <= idx < len(modes):
                self._apply_interaction_mode(modes[idx][0], log)
                return True
        for mode, label, _ in modes:
            if value in {mode, label.lower()}:
                self._apply_interaction_mode(mode, log)
                return True
        log.add_info("Choose 1-3, chat, build, or plan.")
        return True

    def _apply_interaction_mode(self, mode: str, log: ConversationLog) -> None:
        mode = (mode or "").strip().lower()
        self._awaiting_mode_selection = False
        if mode == "chat":
            self._chat_cmd("on", log)
        elif mode == "build":
            self._build_cmd("", log)
        elif mode == "plan":
            self._chat_mode = False
            self._plan_mode_enabled = True
            self._refresh_plan_status_badge()
            log.add_success("Plan mode ON. New prompts will plan before native tools run.")
            log.add_info(
                "Use :mode build to return to the coding harness, or :plan run to execute."
            )
        else:
            log.add_info("Usage: :mode [chat|build|plan]")


    @work(exclusive=True)
    async def _chat_worker(self, text: str, log: ConversationLog):
        """Worker wrapper so chat streaming runs off the input handler."""
        await self._send_chat_message(text, log)

    async def _send_chat_message(self, text: str, log: ConversationLog):
        """Stream a raw model reply and report speed (TTFT + decode tok/s)."""
        from time import monotonic
        from superqode.providers.gateway.base import Message
        from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

        try:
            provider = self._pure_mode.session.provider
            model = self._pure_mode.session.model
            if not provider or not model:
                self._call_ui(
                    log.add_error,
                    "No model is selected. Reconnect with :connect local before chatting.",
                )
                return
            history = self._chat_history
            if not isinstance(history, list):
                history = self._chat_history = []
            history.append(Message(role="user", content=text))
            who = f"{provider}/{model}"
            self._call_ui(lambda: log.reset_response_stream(who))

            # Use the same animated thinking indicator + scanning waves as the
            # agent path so chat mode looks alive during a slow first token
            # (a 30B local model can take many seconds to prefill).
            self._call_ui(self._start_thinking, f"💬 {provider}/{model}")

            gateway = LiteLLMGateway()
            t0 = monotonic()
            first_token_t = None
            pieces: list[str] = []
            thinking_chars = 0
            usage_completion = None

            async for chunk in gateway.stream_completion(
                messages=list(history),
                model=model,
                provider=provider,
                tools=None,
                temperature=0.7,
                max_tokens=2048,
            ):
                if getattr(self, "_cancel_requested", False):
                    break
                if chunk.thinking_content:
                    if first_token_t is None:
                        first_token_t = monotonic()
                    thinking_chars += len(chunk.thinking_content)
                if chunk.content:
                    if first_token_t is None:
                        first_token_t = monotonic()
                    pieces.append(chunk.content)
                    self._call_ui(log.add_response_chunk, chunk.content)
                if chunk.usage and chunk.usage.completion_tokens:
                    usage_completion = chunk.usage.completion_tokens

            end_t = monotonic()
            full = "".join(pieces)
            history.append(Message(role="assistant", content=full))

            if not full.strip():
                if thinking_chars > 0:
                    note = (
                        f"Model produced {thinking_chars} chars of hidden reasoning but no "
                        "final answer (it likely ran out of the 2048-token budget). "
                        "Try a shorter prompt or a non-reasoning model."
                    )
                else:
                    note = (
                        "Model returned no text. Check the model is loaded in the server "
                        "and not an embedding-only model."
                    )
                self._call_ui(log.add_info, note)
                return
            self._call_ui(lambda: log.write_final_response(full, agent=who))

            ttft = (first_token_t - t0) if first_token_t is not None else None
            decode_dur = (end_t - first_token_t) if first_token_t is not None else None
            tokens = usage_completion or max(1, len(full) // 4)
            tps = (tokens / decode_dur) if decode_dur and decode_dur > 0 else None
            self._call_ui(self._write_chat_stats, log, ttft, tps, tokens, end_t - t0)
        except Exception as exc:  # noqa: BLE001 - surface any model/transport error
            self._call_ui(log.add_error, f"Chat error: {exc}")
        finally:
            # Stops the indicator + scanning waves and restores the prompt.
            self._call_ui(self._stop_thinking)


    @work(exclusive=True)
    async def _send_to_pure_mode(self, text: str, log: ConversationLog):
        """Send message to provider session with streaming output."""
        from time import monotonic
        import traceback

        # Handle session commands
        if text.strip().startswith("/sessions"):
            parts = text.strip().split(maxsplit=2)
            if len(parts) >= 2 and parts[1].lower() in {"resume", "switch", "select"}:
                session_id = parts[2] if len(parts) >= 3 else ""
                self._call_ui(self._handle_resume_session, session_id, log)
                return
            sessions = self._pure_mode.list_sessions() if hasattr(self, "_pure_mode") else []
            if not sessions:
                log.add_info("No sessions found.")
            else:
                for s in sessions:
                    log.add_info(
                        f"  {s['session_id']} | {s['model'] or 'N/A'} | {s['message_count']} msgs"
                    )
            return
        elif text.strip().startswith("/resume"):
            parts = text.strip().split()
            if len(parts) < 2:
                log.add_info("Usage: /resume <session_id>")
                return
            session_id = parts[1]
            if hasattr(self, "_pure_mode"):
                messages = self._pure_mode.resume_session(session_id)
                if messages:
                    log.add_info(f"Resumed session {session_id[:8]}")
                    for m in messages:
                        role = m.get("role", "?").upper()
                        content = m.get("content", "")[:100]
                        log.add_info(f"[{role}] {content}...")
                else:
                    log.add_info(f"Session {session_id} not found.")
            return
        elif text.strip().startswith("/compact"):
            if hasattr(self, "_pure_mode") and hasattr(self._pure_mode, "compact"):
                self._pure_mode.compact()
                log.add_info("Context compacted.")
            return

        mcp_context = await self._resolve_mcp_attachment_context(log)
        if mcp_context:
            text = f"{mcp_context}\n\n{text}"

        # Prepend file context if available (from @file references)
        file_context = getattr(self, "_current_file_context", "")
        if file_context:
            text = f"{file_context}\n\n{text}"
            self._current_file_context = ""  # Clear after use

        # Check if connected
        if not hasattr(self, "_pure_mode"):
            log.add_error("Not connected to a model. Use :connect byok to select a provider/model.")
            log.add_system("Example: :connect local ollama/qwen3.6:35b-a3b")
            self.is_busy = False
            return

        if not self._pure_mode.session.connected:
            log.add_error("Connection not established. Please reconnect using :connect byok")
            log.add_system("Example: :connect local ollama/qwen3.6:35b-a3b")
            self.is_busy = False
            return

        # A builtin AgentLoop (._agent), a harness, OR a self-contained runtime
        # (e.g. codex-sdk, which has no ._agent) all count as initialized.
        if (
            not self._pure_mode._agent
            and not getattr(self._pure_mode, "harness_enabled", False)
            and getattr(self._pure_mode, "_runtime", None) is None
        ):
            log.add_error("Agent not initialized. Please reconnect using :connect byok")
            log.add_system("Example: :connect local ollama/qwen3.6:35b-a3b")
            self.is_busy = False
            return

        provider = self._pure_mode.session.provider
        model = self._pure_mode.session.model
        if getattr(self._pure_mode, "harness_enabled", False) and hasattr(
            self._pure_mode, "_resolve_harness_route"
        ):
            try:
                provider, model = self._pure_mode._resolve_harness_route()
            except Exception:
                # Let the run path raise the user-facing error with full context.
                provider = self._pure_mode.session.provider
                model = self._pure_mode.session.model
        plan_mode_for_run = bool(getattr(self, "_active_plan_mode_for_current_message", False))
        if plan_mode_for_run:
            text = (
                "PLAN MODE: Analyze the request and produce a concrete implementation plan. "
                "Do not call tools, edit files, run commands, or make changes. "
                "Include goal, steps, files likely involved, risks, and verification.\n\n"
                f"{text}"
            )

        # Set up callbacks for BYOK/Local modes
        # Tool calls are ALWAYS visible (the agent's actual work)
        # Thinking logs are toggleable with Ctrl+T
        from superqode.providers.registry import PROVIDERS, ProviderCategory

        provider_def = PROVIDERS.get(provider)
        is_local = provider_def and provider_def.category == ProviderCategory.LOCAL
        tool_actions: list[dict] = []
        files_read: list[str] = []
        files_modified: list[str] = []
        commands_run: list[str] = []
        pre_existing_modified: set[str] = set()
        try:
            root_path = Path(os.getcwd())
            pre_existing_modified = {
                change.path for change in get_git_changes(root_path) if change.status in ("M", "A")
            }
        except Exception:
            pre_existing_modified = set()

        def _append_unique(items: list[str], value: str):
            if value and value not in items:
                items.append(value)

        def _record_tool_activity(name: str, args: dict):
            tool_lower = name.lower()
            file_path = args.get("path") or args.get("file_path") or args.get("filePath") or ""
            command = args.get("command", "")
            query = args.get("query") or args.get("pattern") or args.get("include") or ""
            started_at = monotonic()
            kind = "tool"
            if command:
                kind = "command"
            elif file_path and any(
                marker in tool_lower
                for marker in ("write", "edit", "insert", "patch", "multi_edit", "delete")
            ):
                kind = "write"
            elif file_path or tool_lower in (
                "grep",
                "glob",
                "repo_search",
                "code_search",
                "list_directory",
            ):
                kind = "read"

            tool_actions.append(
                {
                    "name": name,
                    "kind": kind,
                    "path": file_path,
                    "command": command,
                    "query": query,
                    "status": "running",
                    "started_at": started_at,
                    "duration": 0.0,
                }
            )

            if command:
                _append_unique(commands_run, command)

            if file_path:
                if any(
                    marker in tool_lower
                    for marker in ("write", "edit", "insert", "patch", "multi_edit", "delete")
                ):
                    _append_unique(files_modified, file_path)
                elif any(
                    marker in tool_lower for marker in ("read", "list", "grep", "glob", "search")
                ):
                    _append_unique(files_read, file_path)
            elif tool_lower in ("grep", "glob", "repo_search", "code_search", "list_directory"):
                search_root = args.get("path") or args.get("directory") or "."
                _append_unique(files_read, str(search_root))

        def _complete_tool_activity(name: str, status: str):
            completed_at = monotonic()
            for action in reversed(tool_actions):
                if action.get("name") == name and action.get("status") == "running":
                    action["status"] = status
                    action["duration"] = max(
                        0.0, completed_at - action.get("started_at", completed_at)
                    )
                    return
            tool_actions.append(
                {
                    "name": name,
                    "kind": "tool",
                    "path": "",
                    "command": "",
                    "query": "",
                    "status": status,
                    "started_at": completed_at,
                    "duration": 0.0,
                }
            )

        def _safe_call(func, *args):
            """Call function safely - handles threading correctly."""
            try:
                self._call_ui(func, *args)
            except RuntimeError as e:
                message = str(e).lower()
                if "different thread" in message or "app thread" in message:
                    func(*args)
                else:
                    raise

        def on_tool_call(name: str, args: dict):
            """Handle tool call - calm mode folds it into the live throbber."""
            _record_tool_activity(name, args)
            if self._is_calm_output():
                _safe_call(self._calm_tool_running, name, args, log)
                return
            file_path = args.get("path", args.get("file_path", args.get("filePath", "")))
            command = args.get("command", "")
            if not file_path and not command:
                command = (
                    args.get("query")
                    or args.get("pattern")
                    or args.get("old_text")
                    or args.get("task")
                    or ""
                )
            _safe_call(log.add_tool_call, name, "running", file_path, command, "", args)

        def on_tool_result(name: str, result):
            """Handle tool result - calm mode shows one tidy line; verbose full."""
            from superqode.tools.base import ToolResult

            if isinstance(result, ToolResult):
                status = "success" if result.success else "error"
                _complete_tool_activity(name, status)
                if self._is_calm_output():
                    meta = result.metadata or {}
                    done_args = {"path": meta.get("path")} if meta.get("path") else {}
                    _safe_call(self._calm_tool_done, name, done_args, log, result.success)
                    return
                output = result.output if result.output else result.error
                output_str = str(output) if output else ""
                metadata = result.metadata or {}
                result_path = str(metadata.get("path") or "")
                if result_path:
                    try:
                        path_obj = Path(result_path)
                        if path_obj.is_absolute():
                            result_path = os.path.relpath(path_obj, os.getcwd())
                    except Exception:
                        pass
                diff_text = str(metadata.get("diff_text") or "")
                additions = metadata.get("additions")
                deletions = metadata.get("deletions")
                if not diff_text and output_str and self._looks_like_diff(output_str):
                    diff_text = output_str
                    output_str = "updated"

                # Try to parse and display JSON nicely
                if status == "success" and output_str and not diff_text:
                    formatted = self._format_tool_output(name, output_str, log)
                    if formatted:
                        return

                # Fallback - show full output, no truncation
                _safe_call(
                    log.add_tool_call,
                    name,
                    status,
                    result_path,
                    "",
                    output_str,
                    None,
                    diff_text,
                    None,
                    additions if isinstance(additions, int) else None,
                    deletions if isinstance(deletions, int) else None,
                    metadata,
                )
            else:
                _complete_tool_activity(name, "success")
                if self._is_calm_output():
                    _safe_call(self._calm_tool_done, name, {}, log, True)
                    return
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
            if not (text and text.strip()):
                return
            # Normal mode: fold the agent loop's per-iteration bookkeeping into
            # the live throbber instead of writing each line to the scrollback.
            loop_status = self._thinking_loop_status(text)
            if loop_status is not None and self.thinking_verbosity != "verbose":
                self._call_ui(self._set_thinking_status, loop_status)
                return
            # Calm mode: keep raw reasoning quiet; just pulse the throbber.
            if self.thinking_verbosity != "verbose":
                self._call_ui(self._set_thinking_status, "💭 Thinking…")
                self._call_ui(self._maybe_show_thinking_hint, log)
                return
            # Verbose: cleaner, categorized output with varied emojis (ACP style).
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
                self._agent_session_label(provider),
                model,
                "byok" if not is_local else "local",
                self.approval_mode,
            )

            # Stream the response
            # CRITICAL: Accumulate ALL chunks including final response after tool calls
            try:
                from superqode.tools.question_tool import (
                    get_question_handler,
                    set_question_handler,
                )

                previous_question_handler = get_question_handler()

                async def tui_question_handler(question):
                    return await self._ask_agent_question(question, log)

                set_question_handler(tui_question_handler)

                # Accumulate chunks to avoid showing each tiny piece as separate thinking line
                accumulated_chunk = ""
                last_display_time = time.time()

                try:
                    async for chunk in self._pure_mode.run_streaming(
                        text, plan_mode=plan_mode_for_run
                    ):
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

                    if accumulated_chunk:
                        _safe_call(log.add_response_chunk, accumulated_chunk)
                finally:
                    if get_question_handler() is tui_question_handler:
                        set_question_handler(previous_question_handler)

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
                if hasattr(self._pure_mode, "get_pending_approvals"):
                    self._announce_pending_approvals(self._pure_mode, log)
                pass
            except Exception as stream_error:
                # Error during streaming
                error_msg = str(stream_error)
                error_type = type(stream_error).__name__

                # Stop animation and show error
                if is_local:
                    self._stop_thinking()
                self._stop_stream_animation()
                self._show_error_card(
                    log,
                    f"{error_type} while running agent",
                    error_msg,
                    provider=provider,
                    model=model,
                    hint=(
                        self._codex_error_hint(error_msg)
                        if getattr(self._pure_mode, "runtime_name", "") == "codex-sdk"
                        else "Use :retry after fixing the provider or model issue."
                    ),
                )

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
                    tool_count = max(stats.get("total_tool_calls", 0), len(tool_actions))

                    # Merge tool-tracked writes with git changes detected after the run.
                    try:
                        root_path = Path(os.getcwd())
                        git_changes = get_git_changes(root_path)
                        git_files_modified = [
                            change.path
                            for change in git_changes
                            if change.status in ("M", "A")
                            and change.path not in pre_existing_modified
                        ]
                        for changed_path in git_files_modified:
                            _append_unique(files_modified, changed_path)
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
                            "files_read": files_read,
                            "file_diffs": file_diffs,  # NEW: Store diff data
                            "tools": tool_actions,
                            "commands_run": commands_run,
                            "provider": provider,
                            "model": model,
                            "prompt": text,
                            "skip_git_fallback": True,
                        },
                        log,
                    )
                    self._last_run_summary = {
                        "tool_count": tool_count,
                        "duration": elapsed,
                        "files_modified": files_modified,
                        "files_read": files_read,
                        "file_diffs": file_diffs,
                        "tools": tool_actions,
                        "commands_run": commands_run,
                        "provider": provider,
                        "model": model,
                        "prompt": text,
                        "response": response_text,
                        "skip_git_fallback": True,
                    }

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
                tool_count = max(stats.get("total_tool_calls", 0), len(tool_actions))
                if tool_count > 0:
                    log.add_info(f"Note: {tool_count} tool calls were executed.")

                    # Compute file diffs even when no text response.
                    try:
                        root_path = Path(os.getcwd())
                        git_changes = get_git_changes(root_path)
                        git_files_modified = [
                            change.path
                            for change in git_changes
                            if change.status in ("M", "A")
                            and change.path not in pre_existing_modified
                        ]
                        for changed_path in git_files_modified:
                            _append_unique(files_modified, changed_path)
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
                            "files_read": files_read,
                            "file_diffs": file_diffs,
                            "tools": tool_actions,
                            "commands_run": commands_run,
                            "provider": provider,
                            "model": model,
                            "prompt": text,
                            "skip_git_fallback": True,
                        },
                        log,
                    )
                    self._last_run_summary = {
                        "tool_count": tool_count,
                        "duration": elapsed,
                        "files_modified": files_modified,
                        "files_read": files_read,
                        "file_diffs": file_diffs,
                        "tools": tool_actions,
                        "commands_run": commands_run,
                        "provider": provider,
                        "model": model,
                        "prompt": text,
                        "response": "",
                        "skip_git_fallback": True,
                    }
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
            self._stop_stream_animation()
            self.is_busy = False
            error_msg = str(e)
            error_trace = traceback.format_exc()

            # Show user-friendly error
            self._show_error_card(
                log,
                "Provider communication failed",
                error_msg,
                provider=provider,
                model=model,
                hint="Check provider readiness with :doctor current, then use :retry.",
            )

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

        self._active_plan_mode_for_current_message = False
        self.is_busy = False

    @work(exclusive=True, thread=True)
    def _send_to_agent(self, text: str, name: str, log: ConversationLog):
        """Send message to agent with real-time streaming output."""
        session = get_session()
        agent = session.connected_agent

        # Reset cancellation flag
        self._cancel_requested = False

        self._call_ui(self._start_thinking, f"🤖 Connecting to {name}...")

        short_name = agent.get("short_name", "") if agent else ""

        if short_name == "opencode":
            # Check if model is selected
            if not self.current_model:
                self._call_ui(self._stop_thinking)
                self._call_ui(
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
                self._call_ui(self._stop_thinking)
                self._call_ui(
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
                self._call_ui(self._stop_thinking)
                self._call_ui(
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
            # Handle all other ACP-compatible agents generically.
            acp_agents = {
                "bub",
                "cagent",
                "codeassistant",
                "fast-agent",
                "goose",
                "hermes",
                "junie",
                "kimi",
                "llmlingagent",
                "minion",
                "mistral-vibe",
                "openhands",
                "pi",
                "stakpak",
                "vtcode",
                "auggie",
                "amp",
                "grok",
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
                self._call_ui(self._stop_thinking)
                self._call_ui(log.add_info, f"🚧 {name} integration coming soon!")

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
        mcp_context = self._resolve_mcp_attachment_context_sync(log)
        if mcp_context:
            message = f"{mcp_context}\n\n{message}"

        # Route ACP-compatible agents to the JSON-RPC ACP client
        # All 15 official ACP agents support the Agent Client Protocol
        acp_agents = (
            "opencode",
            "claude",
            "codex",
            "gemini",
            "bub",
            "cagent",
            "codeassistant",
            "fast-agent",
            "goose",
            "hermes",
            "junie",
            "kimi",
            "llmlingagent",
            "minion",
            "mistral-vibe",
            "openhands",
            "pi",
            "stakpak",
            "vtcode",
            "auggie",
            "amp",
            "grok",
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
            self._call_ui(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self._call_ui(log.add_info, f"🎭 Persona active: {persona_context.role_name}")

            # Show mode-specific info on first message
            if self._is_first_message:
                if self.approval_mode == "deny":
                    self._call_ui(log.add_info, "🔴 DENY mode: ALL tool calls will be blocked")
                elif self.approval_mode == "ask":
                    self._call_ui(log.add_info, "ASK mode: prompts for external tools (y/n/a)")

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
            self._call_ui(self._stop_thinking)
            self._call_ui(self._start_stream_animation, log)

            # Show header
            self._call_ui(self._show_agent_header_with_model, display_name, model_display, log)

            # Collect output
            text_parts = []
            tool_actions = []
            files_modified = []
            files_read = []

            # Read output line by line
            while True:
                if self._cancel_requested:
                    process.terminate()
                    self._call_ui(log.add_info, "🛑 Agent operation cancelled")
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
                                    self._call_ui(self._show_thinking_line, f"{emoji} {line}", log)
                                else:
                                    self._call_ui(self._show_thinking_line, line, log)

            # Cleanup
            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

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
                    self._call_ui(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self._call_ui(self._show_completion_summary, display_name, action_summary, log)
            elif not self._cancel_requested:
                self._call_ui(self._show_completion_summary, display_name, action_summary, log)

        except FileNotFoundError:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            agent_name = "gemini" if agent_type == "gemini" else "opencode"
            self._call_ui(log.add_error, f"❌ {agent_name} CLI not found. Install it first.")
        except Exception as e:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, f"❌ Error: {str(e)}")

    def _run_fast_agent_cli(
        self,
        message: str,
        model: str,
        display_name: str,
        log: ConversationLog,
    ) -> None:
        """Run FastAgent through its installed CLI when ACP is unavailable."""
        import subprocess
        from time import monotonic

        start_time = monotonic()
        cmd = ["fast-agent", "go", "--message", message]
        if model and model != "auto":
            cmd[2:2] = ["--model", model]

        text_parts: list[str] = []
        try:
            self._call_ui(self._stop_thinking)
            self._call_ui(self._start_stream_animation, log)
            self._call_ui(
                log.start_agent_session,
                display_name,
                model or "auto",
                "cli",
                self.approval_mode,
            )

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._agent_process = process

            assert process.stdout is not None
            for line in process.stdout:
                if self._cancel_requested:
                    process.terminate()
                    self._call_ui(log.add_info, "🛑 Agent operation cancelled")
                    break
                if line:
                    text_parts.append(line)
                    self._call_ui(log.add_response_chunk, line)

            if self._cancel_requested:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                self._call_ui(
                    log.end_agent_session,
                    False,
                    "🛑 Agent operation cancelled",
                )
                return

            return_code = process.wait()
            response_text = "".join(text_parts).strip()
            if return_code != 0:
                self._call_ui(
                    log.end_agent_session,
                    False,
                    response_text or f"fast-agent exited with code {return_code}",
                )
                return

            if not response_text:
                self._call_ui(
                    log.end_agent_session,
                    False,
                    "No response received from fast-agent CLI.",
                )
                return

            self._call_ui(
                log.end_agent_session,
                True,
                response_text,
            )
            self._call_ui(
                self._show_final_outcome,
                response_text,
                display_name,
                {
                    "tool_count": 0,
                    "files_modified": [],
                    "files_read": [],
                    "duration": monotonic() - start_time,
                    "file_diffs": {},
                },
                log,
            )
        except FileNotFoundError:
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(
                log.end_agent_session,
                False,
                "fast-agent CLI not found. Install with: uv tool install fast-agent-mcp",
            )
        except Exception as e:
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.end_agent_session, False, f"❌ Error: {str(e)}")
        finally:
            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

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
        # All 15 official ACP agents are supported
        if agent_type == "gemini":
            command = "gemini --experimental-acp"
            model_display = f"gemini/{model}" if model and model != "auto" else "gemini/auto"
            if "GEMINI_API_KEY" not in os.environ and "GOOGLE_API_KEY" not in os.environ:
                self._call_ui(self._stop_thinking)
                self._call_ui(
                    log.add_error, "❌ GEMINI_API_KEY or GOOGLE_API_KEY not set. Export it first:"
                )
                self._call_ui(log.add_info, "  export GEMINI_API_KEY=your_api_key")
                self._call_ui(log.add_info, "  or export GOOGLE_API_KEY=your_api_key")
                return
        elif agent_type == "claude":
            command = "claude --acp"
            model_display = f"claude/{model}" if model else "claude/auto"
            if "ANTHROPIC_API_KEY" not in os.environ:
                self._call_ui(self._stop_thinking)
                self._call_ui(log.add_error, "❌ ANTHROPIC_API_KEY not set. Export it first:")
                self._call_ui(log.add_info, "  export ANTHROPIC_API_KEY=sk-ant-...")
                return
        elif agent_type == "codex":
            command = "codex --acp"
            model_display = f"codex/{model}" if model else "codex/auto"
            if "OPENAI_API_KEY" not in os.environ and "CODEX_API_KEY" not in os.environ:
                self._call_ui(self._stop_thinking)
                self._call_ui(
                    log.add_error, "❌ OPENAI_API_KEY or CODEX_API_KEY not set. Export one first:"
                )
                self._call_ui(log.add_info, "  export OPENAI_API_KEY=sk-...")
                self._call_ui(log.add_info, "  or export CODEX_API_KEY=sk-...")
                return
        elif agent_type == "grok":
            command = "grok agent stdio"
            model_display = f"grok/{model}" if model and model != "auto" else "grok/grok-build"
            if shutil.which("grok") is None:
                self._call_ui(self._stop_thinking)
                self._call_ui(log.add_error, "Grok CLI not found. Install it before connecting.")
                self._call_ui(log.add_info, "  curl -fsSL https://x.ai/cli/install.sh | bash")
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
                self._call_ui(self._stop_thinking)
                self._call_ui(
                    log.add_error, "❌ MOONSHOT_API_KEY or KIMI_API_KEY not set. Export it first:"
                )
                self._call_ui(log.add_info, "  export MOONSHOT_API_KEY=your_api_key")
                return
        elif agent_type == "opencode":
            command = "opencode acp"
            model_display = f"opencode/{model}" if model else "opencode/auto"
            # OpenCode handles its own API keys via its config
        elif agent_type == "openhands":
            command = "openhands acp"
            model_display = f"openhands/{model}" if model else "openhands/auto"
            # OpenHands reads its own configuration from ~/.openhands/settings.json
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
                self._call_ui(self._stop_thinking)
                self._call_ui(log.add_error, "❌ AUGMENT_API_KEY not set. Export it first:")
                self._call_ui(log.add_info, "  export AUGMENT_API_KEY=your_api_key")
                return
        elif agent_type == "codeassistant":
            command = "code-assistant --acp"
            model_display = f"codeassistant/{model}" if model else "codeassistant/auto"
        elif agent_type == "cagent":
            command = "cagent --acp"
            model_display = f"cagent/{model}" if model else "cagent/auto"
        elif agent_type == "fast-agent":
            command = os.getenv(
                "SUPERQODE_FAST_AGENT_ACP_COMMAND",
                "uvx --from fast-agent-mcp@latest fast-agent-acp",
            )
            model_display = f"fast-agent/{model}" if model else "fast-agent/auto"
        elif agent_type == "llmlingagent":
            command = "llmling-agent --acp"
            model_display = f"llmlingagent/{model}" if model else "llmlingagent/auto"
        elif agent_type == "bub":
            command = "bub acp serve"
            model_display = f"bub/{model}" if model else "bub/auto"
        elif agent_type == "hermes":
            command = "hermes acp"
            model_display = f"hermes/{model}" if model else "hermes/auto"
        elif agent_type == "minion":
            command = "mcode acp"
            model_display = f"minion/{model}" if model else "minion/auto"
        elif agent_type == "mistral-vibe":
            command = "vibe-acp"
            model_display = f"mistral-vibe/{model}" if model else "mistral-vibe/auto"
        elif agent_type == "pi":
            command = "pi-acp"
            model_display = f"pi/{model}" if model else "pi/auto"
        elif agent_type == "amp":
            command = "acp-amp"
            model_display = f"amp/{model}" if model else "amp/auto"
            # Amp handles its own authentication via `amp login`
        else:
            self._call_ui(self._stop_thinking)
            self._call_ui(log.add_error, f"Unsupported ACP agent type: {agent_type}")
            return

        mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
            self.approval_mode, "🟡 ASK"
        )
        session_type = "new session"
        self._call_ui(
            log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
        )

        if persona_context and persona_context.is_valid:
            self._call_ui(log.add_info, f"🎭 Persona active: {persona_context.role_name}")

        # Stop thinking, start streaming animation
        self._call_ui(self._stop_thinking)
        self._call_ui(self._start_stream_animation, log)

        # Use enhanced agent session header (always visible)
        self._call_ui(
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
            """Flush accumulated thinking chunks to display.

            In normal mode the reasoning is condensed to a single trimmed line so
            it reads as a calm summary rather than a wall of streamed text. In
            verbose mode the full thought is shown verbatim.
            """
            if thinking_buffer:
                full_text = "".join(thinking_buffer).strip()
                if full_text:
                    if self.thinking_verbosity != "verbose":
                        # Collapse whitespace and cap length for a tidy one-liner.
                        condensed = " ".join(full_text.split())
                        if len(condensed) > 240:
                            condensed = condensed[:237].rstrip() + "…"
                        full_text = condensed
                    self._call_ui(self._show_thinking_line, f"💭 {full_text}", log)
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
                self._call_ui(log.add_response_chunk, text)

        async def on_thinking(text: str) -> None:
            """Handle agent thinking/session logs - toggleable with Ctrl+T."""
            import time

            if not text:
                return

            # Handle raw agent stdout logs - these show what the agent is doing
            # The [agent] prefix comes from non-JSON output from the agent process
            if text.startswith("[agent]"):
                clean_text = text[8:]  # Remove "[agent] " prefix
                # Calm mode: surface it live in the throbber, don't fill scrollback.
                if self._is_calm_output():
                    snippet = " ".join(clean_text.split())[:60]
                    if snippet:
                        self._call_ui(self._set_thinking_status, f"📡 {snippet}")
                    return
                self._call_ui(self._show_thinking_line, f"📡 {clean_text}", log)
                return

            # Filter out other verbose prefixes
            if text.startswith("[error]") or text.startswith("[startup"):
                # Show errors but in a cleaner format
                clean_text = text.replace("[error] ", "").replace("[startup error] ", "")
                self._call_ui(log.add_error, clean_text)
                return

            # Normal mode: fold the agent loop's per-iteration bookkeeping into
            # the live throbber rather than printing each line. Verbose mode lets
            # these flow through to the scrollback as before.
            loop_status = self._thinking_loop_status(text)
            if loop_status is not None and self.thinking_verbosity != "verbose":
                self._call_ui(self._set_thinking_status, loop_status)
                return

            if not self.show_thinking_logs:
                return

            # Calm mode: keep raw reasoning out of the scrollback - just show a
            # quiet "Thinking…" pulse and the one-time toggle hint.
            if self.thinking_verbosity != "verbose":
                self._call_ui(self._set_thinking_status, "💭 Thinking…")
                self._call_ui(self._maybe_show_thinking_hint, log)
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

        # One committed calm line per tool call id, whether the completion
        # arrives on the initial tool_call or a later tool_call_update.
        calm_committed_tool_ids: set = set()

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

            # Calm mode: fold the action into the live throbber instead of a
            # row. Some agents send a single tool_call already carrying its
            # final status with no follow-up update; without honoring it here
            # the tool never left a visible line at all.
            command = raw_input.get("command", "")
            if self._is_calm_output():
                from superqode.acp.render import normalize_acp_tool_status

                call_status = normalize_acp_tool_status(tool_call.get("status", ""))
                call_id = str(tool_call.get("toolCallId") or "")
                if call_status in ("completed", "failed"):
                    if call_id not in calm_committed_tool_ids:
                        if call_id:
                            calm_committed_tool_ids.add(call_id)
                        self._call_ui(
                            self._calm_tool_done,
                            title,
                            raw_input,
                            log,
                            call_status == "completed",
                        )
                else:
                    self._call_ui(self._calm_tool_running, title, raw_input, log)
                return
            # Verbose: show the tool call row - the agent's actual work.
            self._call_ui(
                log.add_tool_call,
                title,
                "running",
                file_path,
                command,
                "",  # output
                raw_input,  # Pass arguments so format_tool_call_compact can display them properly
            )

        async def on_tool_update(update: dict) -> None:
            """Handle tool updates, keeping normal streaming output compact.

            Order of preference for the "output" cell:
            1. Diff blocks from ``content`` — rendered as a unified diff
               so the user sees what changed in the file (this is the
               feature the user explicitly asked for).
            2. Text blocks from ``content`` — the spec-canonical channel.
            3. Legacy ``rawOutput`` / ``output`` / ``result`` — same as
               before, but suppressed for completed Read/Execute calls
               in normal mode (where the one-liner action row already
               tells the story).
            Verbose mode (``log.tool_output_mode == "verbose"``) opts
            back into the full payload.
            """
            from superqode.acp.render import (
                display_title_from_update,
                extract_tool_arguments,
                normalize_acp_tool_status,
                render_acp_tool_output,
            )

            status = normalize_acp_tool_status(update.get("status", ""))
            raw_output = update.get("rawOutput") or update.get("output") or update.get("result")
            content = update.get("content")
            kind = update.get("kind") or ""
            tool_title = display_title_from_update(update)
            raw_input = extract_tool_arguments(update)
            file_path = raw_input.get("path", raw_input.get("filePath", ""))
            command = raw_input.get("command", "")
            mode = getattr(log, "tool_output_mode", "normal")

            # Calm mode: one tidy line on completion/failure, throbber while
            # running - no raw output/diffs (flip to :thinking verbose for all).
            if self._is_calm_output():
                call_id = str(update.get("toolCallId") or "")
                if status in ("completed", "failed"):
                    if call_id and call_id in calm_committed_tool_ids:
                        return  # already committed from the initial tool_call
                    if call_id:
                        calm_committed_tool_ids.add(call_id)
                    self._call_ui(
                        self._calm_tool_done, tool_title, raw_input, log, status == "completed"
                    )
                elif status == "running":
                    self._call_ui(self._calm_tool_running, tool_title, raw_input, log)
                return

            if status == "completed":
                output_str = render_acp_tool_output(
                    kind=kind,
                    status="completed",
                    content=content,
                    raw_output=raw_output,
                    mode=mode,
                )

                # Diff path: emit directly without JSON-parsing — the
                # output is already formatted unified diff text.
                if output_str and self._looks_like_diff(output_str):
                    self._call_ui(
                        log.add_tool_call,
                        tool_title,
                        "success",
                        file_path,
                        command,
                        "updated",
                        raw_input,
                        output_str,
                    )
                    return

                # Suppressed path: no output line, just the action row
                # stays as the visual record. The user can flip to
                # verbose with `:log verbose` if they need details.
                if output_str is None:
                    return

                # Legacy path: JSON parsing for structured outputs,
                # fallback to summary line.
                formatted = self._format_tool_output(tool_title, output_str, log)
                if not formatted:
                    self._call_ui(
                        log.add_tool_call,
                        tool_title,
                        "success",
                        file_path,
                        command,
                        output_str,
                        raw_input,
                    )
            elif status == "failed":
                # Errors are *always* shown, even in minimal mode.
                # A failure is the one place where hiding output
                # would cost more than the noise saves.
                error_payload = (
                    render_acp_tool_output(
                        kind=kind,
                        status="failed",
                        content=content,
                        raw_output=raw_output,
                        mode="verbose",  # never suppress errors
                    )
                    or "failed"
                )
                self._call_ui(
                    log.add_tool_call,
                    tool_title,
                    "error",
                    file_path,
                    command,
                    str(error_payload),
                    raw_input,
                )
            elif status == "running":
                self._call_ui(
                    log.add_tool_call,
                    tool_title,
                    "running",
                    file_path,
                    command,
                    "",
                    raw_input,
                )

        async def on_plan(entries: list[dict]) -> None:
            """Handle plan updates - ALWAYS visible."""
            if entries:
                # Plans are important - always show
                self._call_ui(log.add_thinking, f"📋 Plan: {len(entries)} tasks", "planning")

        async def on_available_commands(commands: list[dict]) -> None:
            """Remember agent-advertised commands without spamming the transcript."""
            if commands:
                self._call_ui(log.add_info, f"Agent commands available: {len(commands)}")

        async def on_mode_update(mode_id: str) -> None:
            """Surface ACP mode changes from the agent."""
            if mode_id:
                self._call_ui(log.add_info, f"ACP mode: {mode_id}")

        async def on_usage_update(usage: dict) -> None:
            """Surface compact ACP context usage updates."""
            used = usage.get("used")
            size = usage.get("size")
            if isinstance(used, int) and isinstance(size, int) and size:
                pct = (used / size) * 100
                self._call_ui(
                    log.add_info, f"Context: {used / 1000:.1f}K/{size / 1000:.1f}K ({pct:.1f}%)"
                )

        async def on_permission_request(options: list[dict], tool_call: dict) -> str:
            tool_name = tool_call.get("title", "unknown")
            tool_input = tool_call.get("rawInput", {})

            if self.approval_mode == "deny":
                self._call_ui(self._show_thinking_line, f"🔴 BLOCKED: {tool_name} (DENY mode)", log)
                return _pick_option(options, ["reject_once", "reject_always"])

            if self.approval_mode == "auto":
                self._call_ui(self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log)
                return _pick_option(options, ["allow_once", "allow_always"])

            needs_permission = self._tool_needs_permission(tool_name, tool_input)
            if needs_permission:
                self._call_ui(self._show_permission_prompt, tool_name, tool_input, log)
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
                    self._call_ui(self._sync_approval_mode)
                    return _pick_option(options, ["allow_always", "allow_once"])

                self._call_ui(log.add_info, f"Denied: {tool_name}")
                return _pick_option(options, ["reject_once", "reject_always"])

            return _pick_option(options, ["allow_once", "allow_always"])

        async def run_prompt() -> tuple[str | None, dict]:
            total_start = time.monotonic()
            model_id = self._normalize_acp_model_id(agent_type, model)

            project_root = Path.cwd()
            client_key = (str(project_root), command, model_id or "")
            ui_terminals = getattr(self, "_acp_ui_terminals", None)
            if ui_terminals is None:
                ui_terminals = {}
                self._acp_ui_terminals = ui_terminals
            terminal_counter_ref = getattr(self, "_acp_ui_terminal_counter_ref", None)
            if terminal_counter_ref is None:
                terminal_counter_ref = [0]
                self._acp_ui_terminal_counter_ref = terminal_counter_ref

            app = self

            class AppTerminalService:
                async def _run(self, method: str, params: dict) -> dict:
                    result, _handled = await asyncio.to_thread(
                        app._handle_terminal_method,
                        method,
                        params,
                        ui_terminals,
                        terminal_counter_ref,
                        log,
                    )
                    return result

                async def create(self, params: dict) -> dict:
                    return await self._run("terminal/create", params)

                async def output(self, params: dict) -> dict:
                    return await self._run("terminal/output", params)

                async def kill(self, params: dict) -> dict:
                    return await self._run("terminal/kill", params)

                async def release(self, params: dict) -> dict:
                    return await self._run("terminal/release", params)

                async def wait_for_exit(self, params: dict) -> dict:
                    return await self._run("terminal/wait_for_exit", params)

            client = getattr(self, "_acp_client", None)
            if (
                client is None
                or getattr(self, "_acp_client_key", None) != client_key
                or not client.is_running()
            ):
                if client is not None:
                    try:
                        await client.stop()
                    except Exception:
                        pass
                client = ACPClient(
                    project_root=project_root,
                    command=command,
                    model=model_id,
                    startup_timeout=float(os.getenv("SUPERQODE_ACP_STARTUP_TIMEOUT", "15")),
                    request_timeout=float(os.getenv("SUPERQODE_ACP_REQUEST_TIMEOUT", "12")),
                    prompt_timeout=float(os.getenv("SUPERQODE_ACP_PROMPT_TIMEOUT", "180")),
                )
                self._acp_client = client
                self._acp_client_key = client_key

            client.on_message = on_message
            client.on_thinking = on_thinking
            client.on_tool_call = on_tool_call
            client.on_tool_update = on_tool_update
            client.on_permission_request = on_permission_request
            client.on_plan = on_plan
            client.on_available_commands = on_available_commands
            client.on_mode_update = on_mode_update
            client.on_usage_update = on_usage_update
            client.terminal_service = AppTerminalService()

            try:
                if client.is_running():
                    self._call_ui(log.add_info, "Reusing warm ACP session. Sending prompt...")
                else:
                    self._call_ui(log.add_info, f"Starting ACP process: {command}")
                    ok = await client.start()
                    if not ok:
                        self._acp_client = None
                        self._acp_client_key = None
                        if agent_type == "grok":
                            self._call_ui(
                                log.add_info,
                                "If Grok is not signed in, run `grok login` or `grok login --device-auth`, then retry.",
                            )
                        return None, {}

                # Store for cancellation cleanup
                self._acp_client = client
                self._acp_client_key = client_key
                if getattr(client, "_process", None) is not None:
                    self._agent_process = client._process  # type: ignore[attr-defined]

                if not text_parts and not tool_actions:
                    self._call_ui(log.add_info, "ACP session ready. Sending prompt...")
                prompt_task = asyncio.create_task(client.send_prompt(message))
                prompt_started_at = time.monotonic()
                waiting_notice_sent = False

                while not prompt_task.done():
                    if self._cancel_requested:
                        try:
                            await client.cancel()
                        except Exception:
                            pass
                        prompt_task.cancel()
                        try:
                            await prompt_task
                        except asyncio.CancelledError:
                            pass
                        await client.stop()
                        self._acp_client = None
                        self._acp_client_key = None
                        self._agent_process = None
                        stats = client.get_stats().__dict__
                        stats["duration"] = time.monotonic() - total_start
                        return "cancelled", stats
                    if (
                        not waiting_notice_sent
                        and time.monotonic() - prompt_started_at > 3.0
                        and not text_parts
                        and not tool_actions
                    ):
                        self._call_ui(
                            log.add_info,
                            "Waiting for the ACP agent/model to emit its first update...",
                        )
                        waiting_notice_sent = True
                    await asyncio.sleep(0.1)

                stop_reason = await prompt_task
                stats = client.get_stats().__dict__
                stats["duration"] = time.monotonic() - total_start
                return stop_reason, stats
            except Exception:
                try:
                    await client.stop()
                finally:
                    self._acp_client = None
                    self._acp_client_key = None
                    self._agent_process = None
                raise

        try:
            if self._acp_loop_runner is None:
                self._acp_loop_runner = _AsyncLoopThread()
            stop_reason, stats = self._acp_loop_runner.run(run_prompt())
            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

            # Get response text
            response_text = "".join(text_parts) if text_parts else ""
            if stop_reason == "cancelled":
                self._call_ui(
                    log.end_agent_session,
                    False,
                    "🛑 Agent operation cancelled",
                    stats.get("prompt_tokens", 0),
                    stats.get("completion_tokens", 0),
                    stats.get("thinking_tokens", 0),
                    stats.get("cost", 0.0),
                )
                self._cancel_requested = False
                self.is_busy = False
                return
            if not response_text.strip() and not tool_actions:
                self._call_ui(
                    log.end_agent_session,
                    False,
                    (
                        "No response received from the ACP agent. "
                        "Check the agent configuration and run :log verbose for startup output."
                    ),
                    stats.get("prompt_tokens", 0),
                    stats.get("completion_tokens", 0),
                    stats.get("thinking_tokens", 0),
                    stats.get("cost", 0.0),
                )
                self.is_busy = False
                return

            # Use enhanced end_agent_session for consistent output
            self._call_ui(
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
                self._call_ui(
                    self._show_final_outcome, response_text, display_name, action_summary, log
                )

        except FileNotFoundError:
            self._agent_process = None
            self._acp_client = None
            self._acp_client_key = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(
                log.end_agent_session,
                False,  # failed
                f"❌ {command} not found. Install it first.",
            )
        except Exception as e:
            self._agent_process = None
            self._acp_client = None
            self._acp_client_key = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(
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
            self._call_ui(self._show_thinking_line, f"🚀 Session started (model: {model})", log)

        elif event_type == "message":
            role = event.get("role", "")
            content = event.get("content", "")
            is_delta = event.get("delta", False)

            if role == "assistant" and content:
                text_parts.append(content)
                if is_delta:
                    # Show full content, no truncation
                    self._call_ui(self._show_thinking_line, f"💬 {content}", log)

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
                self._call_ui(self._show_thinking_line, msg, log)
            # Handle approval modes
            elif self.approval_mode == "deny":
                self._call_ui(self._show_thinking_line, f"🔴 BLOCKED: {tool_name} (DENY mode)", log)
                self._call_ui(log.add_error, f"🛑 Tool blocked: {tool_name}")
                process.terminate()
            elif self.approval_mode == "ask":
                needs_permission = self._tool_needs_permission(tool_name, parameters)
                if needs_permission:
                    self._pending_tool_id = tool_id  # Track which tool is pending
                    self._call_ui(self._show_permission_prompt, tool_name, parameters, log)
                    self._permission_pending = True
                    self._permission_response = None

                    wait_start = monotonic()
                    timeout = 60
                    while self._permission_pending and (monotonic() - wait_start) < timeout:
                        if self._cancel_requested:
                            self._permission_pending = False
                            process.terminate()
                            self._call_ui(log.add_info, "🛑 Cancelled")
                            break
                        time.sleep(0.1)

                    if self._permission_response == "deny" or self._permission_response is None:
                        self._call_ui(log.add_info, f"Denied: {tool_name}")
                        process.terminate()
                    elif self._permission_response == "allow":
                        # Add to approved tools to prevent duplicate prompts
                        approved_tools = self._ensure_approved_tools()
                        if self._pending_tool_id:
                            approved_tools.add(self._pending_tool_id)
                        self._call_ui(self._show_thinking_line, f"✅ Allowed: {tool_name}", log)
                    elif self._permission_response == "allow_all":
                        self.approval_mode = "auto"
                        self._call_ui(self._sync_approval_mode)
                        self._call_ui(self._show_thinking_line, f"✅ Allowed all: {tool_name}", log)
                else:
                    self._call_ui(self._show_thinking_line, msg, log)
            else:
                self._call_ui(self._show_thinking_line, msg, log)

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
                        self._call_ui(self._set_todos, todos)
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

                            self._call_ui(
                                self._show_thinking_line, f"📋 Task List ({summary}):", log
                            )
                            for todo_line in formatted_todos:
                                self._call_ui(self._show_thinking_line, f"  {todo_line}", log)
                        else:
                            self._call_ui(
                                self._show_thinking_line, f"📋 No tasks in todo list", log
                            )
                    except (json.JSONDecodeError, KeyError):
                        # Fallback to normal display if JSON parsing fails
                        output_str = str(output)
                        self._call_ui(self._show_thinking_line, f"✅ Result: {output_str}", log)
                elif output:
                    output_str = str(output)
                    # Show full output, no truncation
                    self._call_ui(self._show_thinking_line, f"✅ Result: {output_str}", log)
                else:
                    self._call_ui(self._show_thinking_line, f"✅ Tool completed", log)
            else:
                # Show full error message, no truncation
                error_msg = str(output) if output else "failed"
                self._call_ui(self._show_thinking_line, f"❌ Tool failed: {error_msg}", log)

        elif event_type == "result":
            # Final result with stats
            stats = event.get("stats", {})
            total_tokens = stats.get("total_tokens", 0)
            tool_calls = stats.get("tool_calls", 0)
            duration_ms = stats.get("duration_ms", 0)
            if total_tokens > 0:
                self._call_ui(
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
                self._call_ui(self._show_thinking_line, f"💬 {text_content}", log)

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
                self._call_ui(self._show_thinking_line, f"🔴 BLOCKED: {tool_name} (DENY mode)", log)
                self._call_ui(log.add_error, f"🛑 Tool blocked: {tool_name}")
                self._call_ui(log.add_info, "💡 Use :mode auto or :mode ask to allow tools")
                process.terminate()
            elif self.approval_mode == "ask":
                needs_permission = self._tool_needs_permission(tool_name, tool_input)
                if needs_permission:
                    self._call_ui(self._show_permission_prompt, tool_name, tool_input, log)
                    self._permission_pending = True
                    self._permission_response = None

                    wait_start = monotonic()
                    timeout = 60
                    while self._permission_pending and (monotonic() - wait_start) < timeout:
                        if self._cancel_requested:
                            self._permission_pending = False
                            process.terminate()
                            self._call_ui(log.add_info, "🛑 Cancelled")
                            break
                        time.sleep(0.1)

                    if self._permission_response == "deny" or self._permission_response is None:
                        self._call_ui(log.add_info, f"Denied: {tool_name}")
                        process.terminate()
                    elif self._permission_response == "allow":
                        self._call_ui(self._show_thinking_line, f"✅ Allowed: {tool_name}", log)
                    elif self._permission_response == "allow_all":
                        self.approval_mode = "auto"
                        self._call_ui(self._sync_approval_mode)
                        self._call_ui(self._show_thinking_line, f"✅ Allowed all: {tool_name}", log)
                else:
                    self._call_ui(self._show_thinking_line, msg, log)
            else:
                self._call_ui(self._show_thinking_line, msg, log)

        elif event_type == "step_start":
            pass  # Skip

        elif event_type == "thinking" or event_type == "reasoning":
            thinking_text = part.get("text", part.get("content", ""))
            if thinking_text:
                # Show full thinking text, no truncation
                self._call_ui(self._show_thinking_line, f"🧠 {thinking_text}", log)

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
                        self._call_ui(self._set_todos, todos)
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

                            self._call_ui(
                                self._show_thinking_line, f"📋 Task List ({summary}):", log
                            )
                            for todo_line in formatted_todos:
                                self._call_ui(self._show_thinking_line, f"  {todo_line}", log)
                        else:
                            self._call_ui(
                                self._show_thinking_line, f"📋 No tasks in todo list", log
                            )
                    except (json.JSONDecodeError, KeyError):
                        # Fallback to normal display if JSON parsing fails
                        result_str = str(result_content)
                        self._call_ui(
                            self._show_thinking_line, f"✅ {tool_name}: {result_str}", log
                        )
                elif result_content:
                    result_str = str(result_content)
                    # Show full result, no truncation
                    self._call_ui(self._show_thinking_line, f"✅ {tool_name}: {result_str}", log)
                else:
                    self._call_ui(self._show_thinking_line, f"✅ {tool_name} completed", log)
            else:
                # Show full error message, no truncation
                error_msg = str(result_content) if result_content else "failed"
                self._call_ui(self._show_thinking_line, f"❌ {tool_name} failed: {error_msg}", log)

        elif event_type == "step_finish":
            reason = part.get("reason", "")
            tokens = part.get("tokens", {})
            if tokens and reason != "tool-calls":
                output_tokens = tokens.get("output", 0)
                cache = tokens.get("cache", {})
                cache_read = cache.get("read", 0)
                if cache_read > 0:
                    self._call_ui(
                        self._show_thinking_line,
                        f"⚡ Step done ({output_tokens} tokens, {cache_read} cached)",
                        log,
                    )
                elif output_tokens > 0:
                    self._call_ui(
                        self._show_thinking_line, f"⚡ Step done ({output_tokens} tokens)", log
                    )
        else:
            if event_type and event_type not in ("metadata", "session"):
                content = part.get("text", part.get("content", part.get("message", "")))
                if content:
                    # Show full content, no truncation
                    self._call_ui(self._show_thinking_line, f"📋 {content}", log)

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

        def terminal_output_for_status(terminal: dict) -> str:
            output_text = str(terminal.get("output") or "").strip()
            exit_code = terminal.get("exit_code")
            if exit_code == 0:
                return output_text
            if terminal.get("timed_out"):
                timeout = terminal.get("timeout_seconds")
                prefix = (
                    f"Run timed out after {timeout:g}s and was killed."
                    if isinstance(timeout, (int, float))
                    else "Run timed out and was killed."
                )
            elif exit_code is not None:
                prefix = f"Run failed (exit {exit_code})."
            else:
                prefix = "Run failed."
            return f"{prefix}\n{output_text}" if output_text else prefix

        def emit_terminal_tool(terminal: dict, status: str, output: str = "") -> None:
            command_text = terminal.get("command", "")
            terminal_id = terminal.get("terminal_id", "")
            args = {
                "terminalId": terminal_id,
                "command": command_text,
            }
            # Calm mode: throbber while running, one tidy line when finished.
            if self._is_calm_output():
                if status == "running":
                    self._call_ui(self._calm_tool_running, "terminal", args, log)
                else:
                    self._call_ui(self._calm_tool_done, "terminal", args, log, status != "error")
                return
            output_text = output.strip()
            self._call_ui(
                log.add_tool_call,
                "terminal",
                status,
                "",
                command_text,
                output_text,
                args,
                "",
                None,
                None,
                None,
                {
                    "command": command_text,
                    "exit_code": terminal.get("exit_code"),
                    "timed_out": terminal.get("timed_out", False),
                    "timeout": terminal.get("timeout_seconds"),
                },
            )

        def emit_terminal_final_once(terminal: dict) -> None:
            if terminal.get("rendered_final"):
                return
            terminal["rendered_final"] = True
            exit_code = terminal.get("exit_code")
            status = "success" if exit_code == 0 else "error"
            emit_terminal_tool(terminal, status, terminal_output_for_status(terminal))

        def pty_supported() -> bool:
            return os.name != "nt" and os.getenv("SUPERQODE_ACP_TERMINAL_PTY", "1").lower() not in {
                "0",
                "false",
                "no",
                "off",
            }

        def drain_terminal_output(terminal: dict, timeout: float = 0.0) -> None:
            if terminal.get("pty"):
                master_fd = terminal.get("master_fd")
                if master_fd is None:
                    return
                while True:
                    try:
                        readable, _, _ = select.select([master_fd], [], [], timeout)
                    except (OSError, ValueError):
                        return
                    timeout = 0.0
                    if not readable:
                        return
                    try:
                        chunk = os.read(master_fd, 4096)
                    except BlockingIOError:
                        return
                    except OSError:
                        return
                    if not chunk:
                        return
                    terminal["output"] += chunk.decode("utf-8", errors="replace")
                return

            term_process = terminal["process"]
            stdout = term_process.stdout

            def read_pipe_chunk() -> str:
                if stdout is None:
                    return ""
                try:
                    data = os.read(stdout.fileno(), 4096)
                except (BlockingIOError, OSError, ValueError):
                    return ""
                if not data:
                    return ""
                return data.decode("utf-8", errors="replace")

            if term_process.poll() is not None:
                while True:
                    try:
                        readable, _, _ = (
                            select.select([stdout], [], [], 0.0) if stdout else ([], [], [])
                        )
                    except (OSError, ValueError):
                        break
                    if not readable:
                        break
                    chunk = read_pipe_chunk()
                    if not chunk:
                        break
                    terminal["output"] += chunk
                terminal["exit_code"] = term_process.returncode
                return

            readable, _, _ = select.select([stdout], [], [], timeout) if stdout else ([], [], [])
            if readable:
                chunk = read_pipe_chunk()
                if chunk:
                    terminal["output"] += chunk

        def kill_terminal_process(term_process: subprocess.Popen) -> None:
            if os.name != "nt":
                try:
                    os.killpg(term_process.pid, signal.SIGKILL)
                    return
                except Exception:
                    pass
            try:
                term_process.kill()
            except Exception:
                pass

        def close_terminal_pty(terminal: dict) -> None:
            master_fd = terminal.pop("master_fd", None)
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except OSError:
                    pass

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

            self._call_ui(self._show_thinking_line, f"🖥️ Running: {full_command}", log)

            try:
                master_fd = None
                use_pty = pty_supported()
                if use_pty:
                    master_fd, slave_fd = pty.openpty()
                    try:
                        os.set_blocking(master_fd, False)
                    except AttributeError:
                        pass
                    try:
                        term_process = subprocess.Popen(
                            full_command,
                            shell=True,
                            stdin=slave_fd,
                            stdout=slave_fd,
                            stderr=slave_fd,
                            cwd=cwd,
                            env=term_env,
                            close_fds=True,
                            start_new_session=True,
                        )
                    finally:
                        os.close(slave_fd)
                else:
                    term_process = subprocess.Popen(
                        full_command,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.PIPE,
                        cwd=cwd,
                        env=term_env,
                        text=True,
                        start_new_session=(os.name != "nt"),
                    )

                terminals[terminal_id] = {
                    "process": term_process,
                    "output": "",
                    "exit_code": None,
                    "command": full_command,
                    "terminal_id": terminal_id,
                    "rendered_final": False,
                    "pty": use_pty,
                    "master_fd": master_fd,
                }
                emit_terminal_tool(terminals[terminal_id], "running")

                return {"terminalId": terminal_id}, True
            except Exception as e:
                self._call_ui(self._show_thinking_line, f"⚠️ Terminal error: {e}", log)
                return {"terminalId": terminal_id}, True

        elif method == "terminal/output":
            terminal_id = params.get("terminalId", "")
            terminal = terminals.get(terminal_id)

            if terminal:
                term_process = terminal["process"]
                try:
                    drain_terminal_output(terminal, timeout=0.1)
                    if term_process.poll() is not None:
                        terminal["exit_code"] = term_process.returncode
                        drain_terminal_output(terminal, timeout=0.0)
                except Exception:
                    pass

                result = {
                    "output": terminal["output"],
                    "truncated": len(terminal["output"]) > 100000,
                }
                if terminal["exit_code"] is not None:
                    result["exitStatus"] = {"exitCode": terminal["exit_code"]}
                    emit_terminal_final_once(terminal)
                return result, True
            else:
                return {"output": "", "truncated": False}, True

        elif method == "terminal/wait_for_exit":
            terminal_id = params.get("terminalId", "")
            terminal = terminals.get(terminal_id)

            if terminal:
                term_process = terminal["process"]
                try:
                    timeout = float(params.get("timeoutMs", 300000)) / 1000
                    deadline = time.monotonic() + timeout
                    while term_process.poll() is None:
                        if time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(term_process.args, timeout)
                        drain_terminal_output(terminal, timeout=0.1)
                    drain_terminal_output(terminal, timeout=0.0)
                    terminal["exit_code"] = term_process.returncode

                    emit_terminal_final_once(terminal)

                    return {"exitCode": terminal["exit_code"], "signal": None}, True
                except subprocess.TimeoutExpired:
                    terminal["timed_out"] = True
                    terminal["timeout_seconds"] = timeout
                    kill_terminal_process(term_process)
                    try:
                        term_process.wait(timeout=2)
                    except Exception:
                        pass
                    drain_terminal_output(terminal, timeout=0.0)
                    terminal["exit_code"] = -1
                    terminal["output"] += "\n[terminal timed out]"
                    emit_terminal_final_once(terminal)
                    return {"exitCode": -1, "signal": "SIGKILL"}, True
            else:
                return {"exitCode": -1, "signal": None}, True

        elif method == "terminal/kill":
            terminal_id = params.get("terminalId", "")
            terminal = terminals.get(terminal_id)
            if terminal and terminal["process"]:
                kill_terminal_process(terminal["process"])
                close_terminal_pty(terminal)
            return {}, True

        elif method == "terminal/release":
            terminal_id = params.get("terminalId", "")
            if terminal_id in terminals:
                close_terminal_pty(terminals[terminal_id])
                del terminals[terminal_id]
            return {}, True

        return {}, False

    def _set_todos(self, todos: list) -> None:
        """Update the pinned live todo/plan panel from the latest todo data."""
        try:
            panel = self.query_one("#todo-panel", Static)
        except Exception:
            return
        items = [t for t in (todos or []) if isinstance(t, dict)]
        self._sync_plan_manager_from_todos(items)
        # Hide once every task is finished (or there are none) to avoid clutter.
        active = [t for t in items if t.get("status") not in ("completed", "cancelled")]
        if not items or not active:
            panel.update("")
            panel.remove_class("visible")
            return

        status_icons = {
            "completed": ("✅", THEME["success"]),
            "in_progress": ("🔄", THEME["cyan"]),
            "pending": ("⏳", THEME["muted"]),
            "cancelled": ("❌", THEME["error"]),
        }
        done = sum(1 for t in items if t.get("status") == "completed")
        t = Text()
        t.append("  📋 Plan  ", style=f"bold {THEME['purple']}")
        t.append(f"{done}/{len(items)} done\n", style=THEME["muted"])
        for index, todo in enumerate(items[:6], 1):
            status = todo.get("status", "pending")
            icon, color = status_icons.get(status, ("○", THEME["muted"]))
            content = " ".join(str(todo.get("content", "")).split())
            if len(content) > 70:
                content = content[:67].rstrip() + "..."
            text_style = THEME["dim"] if status in ("completed", "cancelled") else THEME["text"]
            t.append(f"  {icon} ", style=color)
            t.append(content, style=text_style)
            t.append("\n", style="")
        if len(items) > 6:
            t.append(f"  +{len(items) - 6} more\n", style=THEME["dim"])
        panel.update(t)
        panel.add_class("visible")

    def _sync_plan_manager_from_todos(self, todos: list[dict]) -> None:
        """Mirror live todo_write/SDK plan updates into :plan state."""
        self._plan_manager.clear()
        if not todos:
            return
        self._plan_manager.current_plan_name = "Agent Plan"
        status_map = {
            "pending": TaskStatus.PENDING,
            "in_progress": TaskStatus.IN_PROGRESS,
            "completed": TaskStatus.COMPLETED,
            "cancelled": TaskStatus.FAILED,
            "canceled": TaskStatus.FAILED,
            "failed": TaskStatus.FAILED,
            "skipped": TaskStatus.SKIPPED,
        }
        priority_map = {
            "low": TaskPriority.LOW,
            "medium": TaskPriority.MEDIUM,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL,
        }
        for index, todo in enumerate(todos, 1):
            content = " ".join(str(todo.get("content") or todo.get("text") or "").split())
            if not content:
                continue
            priority = priority_map.get(str(todo.get("priority") or "medium").lower())
            task = self._plan_manager.add_task(content, priority=priority or TaskPriority.MEDIUM)
            task.id = str(todo.get("id") or index)
            status = status_map.get(
                str(todo.get("status") or "pending").lower(), TaskStatus.PENDING
            )
            self._plan_manager.update_status(task.id, status)

    def _set_todos_from_input(self, tool_input: dict) -> None:
        """Update the todo panel from a todo_write tool input payload."""
        if isinstance(tool_input, dict):
            todos = tool_input.get("todos")
            if isinstance(todos, list):
                self._set_todos(todos)


    def _cleanup_terminals(self, terminals: dict):
        """Clean up any running terminal processes."""
        for tid, term in terminals.items():
            try:
                if term["process"] and term["process"].poll() is None:
                    term["process"].terminate()
                master_fd = term.pop("master_fd", None)
                if master_fd is not None:
                    os.close(master_fd)
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
            self._call_ui(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self._call_ui(log.add_info, f"🎭 Persona active: {persona_context.role_name}")

            # Build environment - need ANTHROPIC_API_KEY
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
            }

            # Check for API key
            if "ANTHROPIC_API_KEY" not in env:
                self._call_ui(self._stop_thinking)
                self._call_ui(log.add_error, "❌ ANTHROPIC_API_KEY not set. Export it first:")
                self._call_ui(log.add_info, "  export ANTHROPIC_API_KEY=sk-ant-...")
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
                self._call_ui(self._show_thinking_line, "🔄 Continuing conversation...", log)
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
            self._call_ui(self._stop_thinking)
            self._call_ui(self._start_stream_animation, log)

            # Show header
            self._call_ui(self._show_agent_header_with_model, display_name, model_display, log)

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
                    self._call_ui(self._show_thinking_line, f"⚠️ Send error: {e}", log)
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
            self._call_ui(self._show_thinking_line, "🔌 Initializing ACP protocol...", log)
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
                    self._call_ui(log.add_info, "🛑 Agent operation cancelled")
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
                            self._call_ui(self._show_thinking_line, f"📋 {line}", log)
                        continue

                    # Handle response to our request
                    if "result" in msg or "error" in msg:
                        msg_id = msg.get("id")

                        if "error" in msg:
                            error = msg["error"]
                            error_msg = error.get("message", "Unknown error")
                            self._call_ui(log.add_error, f"❌ ACP Error: {error_msg}")
                            break

                        result = msg.get("result", {})

                        # Handle initialize response
                        if not initialized:
                            initialized = True
                            agent_info = result.get("agentInfo", {})
                            agent_name = agent_info.get("title", "Claude Code")
                            self._call_ui(
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
                                self._call_ui(
                                    self._show_thinking_line,
                                    f"📊 Models: {', '.join(model_names)}",
                                    log,
                                )

                            self._call_ui(self._show_thinking_line, f"🚀 Session started", log)

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
                            self._call_ui(
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
                                    self._call_ui(self._show_thinking_line, f"💬 {text}", log)

                            elif update_type == "agent_thought_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    # Show full thinking text, no truncation
                                    self._call_ui(self._show_thinking_line, f"🧠 {text}", log)

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
                                self._call_ui(self._show_thinking_line, msg_text, log)

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
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ {tool_title}: {output_str}",
                                            log,
                                        )
                                    else:
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ {tool_title} completed",
                                            log,
                                        )
                                elif status == "failed":
                                    # Show full error message, no truncation
                                    error_msg = str(output) if output else "failed"
                                    self._call_ui(
                                        self._show_thinking_line,
                                        f"❌ {tool_title} failed: {error_msg}",
                                        log,
                                    )

                            elif update_type == "plan":
                                entries = update.get("entries", [])
                                if entries:
                                    self._call_ui(
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
                                self._call_ui(
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
                                self._call_ui(
                                    self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log
                                )
                            else:
                                # ASK mode - check if needs permission
                                needs_permission = self._tool_needs_permission(
                                    tool_name, tool_input
                                )
                                if needs_permission:
                                    self._call_ui(
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
                                        self._call_ui(log.add_info, f"Denied: {tool_name}")
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
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ Allowed: {tool_name}",
                                            log,
                                        )
                                        if self._permission_response == "allow_all":
                                            self.approval_mode = "auto"
                                            self._call_ui(self._sync_approval_mode)
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
                    self._call_ui(self._show_thinking_line, f"⚠️ Read error: {e}", log)
                    break

            # Cleanup terminals
            self._cleanup_terminals(terminals)

            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

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
                    self._call_ui(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self._call_ui(self._show_completion_summary, display_name, action_summary, log)
            elif not self._cancel_requested:
                self._call_ui(self._show_completion_summary, display_name, action_summary, log)

        except FileNotFoundError:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, "❌ claude-code-acp not found. Install it first:")
            self._call_ui(log.add_info, "  npm install -g @zed-industries/claude-code-acp")
        except Exception as e:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, f"❌ Error: {str(e)}")


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
            self._call_ui(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self._call_ui(log.add_info, f"🎭 Persona active: {persona_context.role_name}")

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
            self._call_ui(self._stop_thinking)
            self._call_ui(self._start_stream_animation, log)

            # Show header
            self._call_ui(self._show_agent_header_with_model, display_name, model_display, log)

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
                    self._call_ui(self._show_thinking_line, f"⚠️ Send error: {e}", log)
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
            self._call_ui(self._show_thinking_line, "🔌 Initializing ACP protocol...", log)
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
                    self._call_ui(log.add_info, "🛑 Agent operation cancelled")
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
                            self._call_ui(self._show_thinking_line, f"📋 {line}", log)
                        continue

                    # Handle response to our request
                    if "result" in msg or "error" in msg:
                        msg_id = msg.get("id")

                        if "error" in msg:
                            error = msg["error"]
                            error_msg = error.get("message", "Unknown error")
                            self._call_ui(log.add_error, f"❌ ACP Error: {error_msg}")
                            break

                        result = msg.get("result", {})

                        # Handle initialize response
                        if not initialized:
                            initialized = True
                            agent_info = result.get("agentInfo", {})
                            agent_name = agent_info.get("title", "OpenHands")
                            self._call_ui(
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
                                self._call_ui(
                                    self._show_thinking_line,
                                    f"📊 Models: {', '.join(model_names)}",
                                    log,
                                )

                            self._call_ui(self._show_thinking_line, f"🚀 Session started", log)

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
                            self._call_ui(
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
                                    self._call_ui(
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
                                    self._call_ui(self._show_thinking_line, f"💬 {text}", log)

                            elif update_type == "agent_thought_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    # Show full thinking text, no truncation
                                    self._call_ui(self._show_thinking_line, f"🧠 {text}", log)

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
                                self._call_ui(self._show_thinking_line, msg_text, log)

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
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ {tool_title}: {output_str}",
                                            log,
                                        )
                                    else:
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ {tool_title} completed",
                                            log,
                                        )
                                elif status == "failed":
                                    # Show full error message, no truncation
                                    error_msg = str(output) if output else "failed"
                                    self._call_ui(
                                        self._show_thinking_line,
                                        f"❌ {tool_title} failed: {error_msg}",
                                        log,
                                    )

                            elif update_type == "plan":
                                entries = update.get("entries", [])
                                if entries:
                                    self._call_ui(
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
                                self._call_ui(
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
                                self._call_ui(
                                    self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log
                                )
                            else:
                                # ASK mode - check if needs permission
                                needs_permission = self._tool_needs_permission(
                                    tool_name, tool_input
                                )
                                if needs_permission:
                                    self._call_ui(
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
                                        self._call_ui(log.add_info, f"Denied: {tool_name}")
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
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ Allowed: {tool_name}",
                                            log,
                                        )
                                        if self._permission_response == "allow_all":
                                            self.approval_mode = "auto"
                                            self._call_ui(self._sync_approval_mode)
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
                    self._call_ui(self._show_thinking_line, f"⚠️ Read error: {e}", log)
                    break

            # Cleanup terminals
            self._cleanup_terminals(terminals)

            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

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
                    self._call_ui(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self._call_ui(self._show_completion_summary, display_name, action_summary, log)
            elif not self._cancel_requested:
                self._call_ui(self._show_completion_summary, display_name, action_summary, log)

        except FileNotFoundError:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, "❌ openhands not found. Install it first:")
            self._call_ui(log.add_info, "  uv tool install openhands -U --python 3.12")
            self._call_ui(log.add_info, "  openhands login")
        except Exception as e:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, f"❌ Error: {str(e)}")

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

        side_effect_tools = (
            "write",
            "edit",
            "patch",
            "create",
            "mkdir",
            "delete",
            "remove",
            "rm",
            "move",
            "rename",
            "replace",
            "insert",
            "append",
            "multi_edit",
            "apply_patch",
        )

        # Side-effecting filesystem tools should be visible in ASK mode even
        # when they target the project. This is the permission dialog users
        # expect from coding agents before edits land.
        if any(name in tool_lower for name in side_effect_tools):
            return True

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

        # Unknown tools - ask for permission to be safe
        return True

    def _show_permission_prompt(self, tool_name: str, tool_input: dict, log: ConversationLog):
        """Render an inline permission request in the conversation log.

        Keys y / n / a / Esc are handled in App.on_key while
        ``self._permission_pending`` is True (callers set this before invoking).
        """
        # Store the pending tool info for later use when approved
        self._pending_tool_name = tool_name
        self._pending_tool_input = tool_input
        self._permission_pending = True

        # Calculate the reason for permission
        reason = ""
        file_path = tool_input.get("filePath", tool_input.get("path", tool_input.get("file", "")))
        tool_lower = tool_name.lower()
        if file_path and not os.path.abspath(file_path).startswith(os.getcwd()):
            reason = "outside project"
        elif any(name in tool_lower for name in ("write", "edit", "patch", "create", "delete")):
            reason = "file change"
        elif tool_lower in ("web", "fetch", "http", "curl", "wget", "browser"):
            reason = "external network"
        elif tool_lower in ("bash", "shell", "terminal"):
            reason = "system command"
        risk_label, risk_style = self._permission_risk(tool_name, tool_input, reason)

        prompt = Text()
        prompt.append("🔐 Permission required\n\n", style=f"bold {THEME['warning']}")
        prompt.append("Tool: ", style=THEME["muted"])
        prompt.append(tool_name, style=f"bold {THEME['text']}")
        if reason:
            prompt.append("  •  ", style=THEME["dim"])
            prompt.append(reason, style=THEME["muted"])
        prompt.append("\n")
        prompt.append("Risk: ", style=THEME["muted"])
        prompt.append(risk_label, style=f"bold {risk_style}")
        prompt.append("\n")

        if tool_input:
            prompt.append("\n")
            for key, value in list(tool_input.items())[:4]:
                val_str = str(value)
                if len(val_str) > 140:
                    val_str = val_str[:137] + "…"
                prompt.append(f"  {key}: ", style=THEME["muted"])
                prompt.append(val_str, style=THEME["text"])
                prompt.append("\n")

        prompt.append("\n")
        prompt.append("[y]", style=f"bold {THEME['success']}")
        prompt.append("es  ", style=THEME["muted"])
        prompt.append("[n]", style=f"bold {THEME['error']}")
        prompt.append("o  ", style=THEME["muted"])
        prompt.append("[a]", style=f"bold {THEME['cyan']}")
        prompt.append("llow session  ", style=THEME["muted"])
        prompt.append("[esc]", style=f"bold {THEME['muted']}")
        prompt.append(" cancel\n", style=THEME["muted"])

        log.write(
            Panel(
                prompt,
                title=f"[bold {THEME['warning']}]Action approval[/]",
                border_style=THEME["warning"],
                box=ROUNDED,
                padding=(1, 2),
            )
        )
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            input_widget.placeholder = "Approve tool? y / n / a"
            input_widget.focus()
        except Exception:
            pass
        self._start_permission_pulse()

    def _request_runtime_permission(
        self,
        tool_name: str,
        tool_input: dict,
        log: ConversationLog,
        *,
        timeout: float = 60.0,
    ) -> bool:
        """Synchronously bridge a runtime approval callback to the TUI prompt."""
        if self.approval_mode == "deny":
            try:
                self._call_ui(log.add_info, f"Denied {tool_name} by approval mode.")
            except Exception:
                pass
            return False
        if self.approval_mode == "auto":
            try:
                self._call_ui(log.add_info, f"Approved {tool_name} by AUTO mode.")
            except Exception:
                pass
            return True
        if getattr(self, "_runtime_permission_allow_all", False):
            try:
                self._call_ui(log.add_info, f"Approved {tool_name} by session approval.")
            except Exception:
                pass
            return True

        if getattr(self, "_permission_pending", False):
            try:
                self._call_ui(log.add_error, "Another approval prompt is already pending.")
            except Exception:
                pass
            return False

        self._permission_response = None
        self._permission_response_event = threading.Event()
        try:
            self._call_ui(self._show_permission_prompt, tool_name, tool_input, log)
        except Exception as exc:
            self._permission_response_event = None
            try:
                self._call_ui(log.add_error, f"Could not show approval prompt: {exc}")
            except Exception:
                pass
            return False

        event = self._permission_response_event
        resolved = event.wait(timeout)

        if not resolved or getattr(self, "_permission_pending", False):
            self._permission_pending = False
            self._permission_response = "deny"
            self._permission_response_event = None
            try:
                self._call_ui(log.add_info, f"Approval timed out for {tool_name}.")
                self._call_ui(self._reset_input_placeholder)
            except Exception:
                pass
            return False

        response = getattr(self, "_permission_response", None)
        self._permission_response_event = None
        if response == "allow_all":
            self._runtime_permission_allow_all = True
            return True
        return response == "allow"

    def _permission_risk(
        self, tool_name: str, tool_input: dict, reason: str = ""
    ) -> tuple[str, str]:
        """Return a coarse risk label/color for a permission request."""
        tool_lower = tool_name.lower()
        command = str(tool_input.get("command", "") or "").lower()
        path = str(
            tool_input.get("filePath", tool_input.get("path", tool_input.get("file", ""))) or ""
        )
        dangerous = (
            "rm -rf",
            "sudo",
            "chmod 777",
            "chown",
            "mkfs",
            "dd ",
            ">/dev/",
            ":(){",
        )
        if any(pattern in command for pattern in dangerous):
            return "critical", THEME["error"]
        if reason == "outside project" or path.startswith(("/etc/", "/usr/", "/var/", "/bin/")):
            return "high", THEME["error"]
        if reason == "external network":
            return "high", THEME["warning"]
        if tool_lower in ("bash", "shell", "terminal") or "exec" in tool_lower:
            return "medium", THEME["warning"]
        if any(name in tool_lower for name in ("delete", "remove", "rm")):
            return "high", THEME["error"]
        if reason == "file change":
            return "medium", THEME["warning"]
        return "low", THEME["success"]

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
                log.add_info("Approved for this session")
            except Exception:
                pass

        # Clear permission state
        self._permission_pending = False
        event = getattr(self, "_permission_response_event", None)
        if event is not None:
            event.set()
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
            event = getattr(self, "_permission_response_event", None)
            if event is not None:
                event.set()
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
            self._reset_input_placeholder()
            return True
        elif response in ("n", "no", "deny", "reject"):
            self._permission_response = "deny"
            self._permission_pending = False
            event = getattr(self, "_permission_response_event", None)
            if event is not None:
                event.set()
            try:
                log = self.query_one("#log", ConversationLog)
                log.add_info("Denied")
            except Exception:
                pass
            self._reset_input_placeholder()
            return True
        elif response in ("a", "all", "allow all", "yes all"):
            self._permission_response = "allow_all"
            self._permission_pending = False
            event = getattr(self, "_permission_response_event", None)
            if event is not None:
                event.set()
            # Add to approved tools
            approved_tools = self._ensure_approved_tools()
            if hasattr(self, "_pending_tool_name") and hasattr(self, "_pending_tool_input"):
                tool_sig = self._get_tool_signature(
                    self._pending_tool_name, self._pending_tool_input or {}
                )
                approved_tools.add(tool_sig)
            try:
                log = self.query_one("#log", ConversationLog)
                log.add_info("Approved for this session")
            except Exception:
                pass
            self._reset_input_placeholder()
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
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            input_widget.placeholder = SelectionAwareInput.DEFAULT_PLACEHOLDER
        except Exception:
            pass

    def _set_input_placeholder(self, text: str) -> None:
        """Best-effort prompt hint for inline decisions."""
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            input_widget.placeholder = text
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


    def _looks_like_diff(self, text: str) -> bool:
        """Detect unified-diff-shaped text produced by acp/render.py.

        We pre-format diffs in the ACP layer rather than letting
        ``_format_tool_output`` JSON-parse them, so it needs a cheap
        check to skip the JSON path. Accept standard unified-diff
        markers (``diff``, ``index``, ``---``/``+++``, ``@@``) plus
        ACP's compact hunk body lines.
        """
        if not text:
            return False
        head = text.lstrip().splitlines()
        saw_old = False
        saw_new = False
        for line in head[:12]:
            stripped = line.strip()
            if stripped.startswith(("diff ", "index ", "@@")):
                return True
            if stripped.startswith("--- "):
                saw_old = True
            elif stripped.startswith("+++ "):
                saw_new = True
            if saw_old and saw_new:
                return True
            if stripped.startswith(("+ ", "- ", "+\t", "-\t")):
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


    def _strip_ansi(self, text: str) -> str:
        """Remove ANSI escape codes from text."""
        import re

        ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        return ansi_escape.sub("", text)

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

    def _thinking_loop_status(self, text: str) -> Optional[str]:
        """If `text` is agent-loop bookkeeping, return a compact live-status label.

        Returns None for genuine reasoning/content, which should be shown normally.
        """
        if not text:
            return None
        stripped = text.strip()
        lowered = stripped.lower()
        if not any(marker in lowered for marker in self._LOOP_BOOKKEEPING_MARKERS):
            return None
        if "reached maximum iterations" in lowered:
            return "Reached max iterations"
        match = re.search(r"iteration\s+(\d+)", lowered)
        if match:
            return f"Working… (step {match.group(1)})"
        return "Working…"

    def _set_thinking_status(self, status: str) -> None:
        """Update the live throbber's steady status label (normal thinking mode)."""
        try:
            indicator = self.query_one("#streaming-thinking", StreamingThinkingIndicator)
            indicator.status = status
        except Exception:
            pass

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

    def _is_calm_output(self) -> bool:
        """True when we should present a calm, summarized view (not verbose)."""
        return getattr(self, "thinking_verbosity", "normal") != "verbose"

    def _calm_verb_target(self, name: str, args: Optional[dict] = None) -> tuple:
        """Map a tool name + args to a friendly (verb, short target) pair."""
        args = args or {}
        try:
            log = self.query_one("#log", ConversationLog)
            verb = log._format_tool_name(name)
        except Exception:
            verb = (name or "tool").replace("_", " ").split(" ")[0].lower()
        target = (
            args.get("path")
            or args.get("file_path")
            or args.get("filePath")
            or args.get("command")
            or args.get("pattern")
            or args.get("query")
            or ""
        )
        target = str(target).strip()
        if target and "/" in target and " " not in target:
            parts = target.rstrip("/").split("/")
            target = "/".join(parts[-2:]) if len(parts) > 1 else parts[-1]
        if len(target) > 52:
            target = "…" + target[-51:]
        return verb, target

    def _maybe_show_thinking_hint(self, log: ConversationLog) -> None:
        """Once per session, tell the user how to see full detail."""
        if getattr(self, "_thinking_hint_shown", False):
            return
        self._thinking_hint_shown = True
        t = Text()
        t.append("  💡 ", style=THEME["muted"])
        t.append("Ctrl+T", style=f"bold {THEME['cyan']}")
        t.append(" or ", style=THEME["muted"])
        t.append(":thinking verbose", style=f"bold {THEME['cyan']}")
        t.append(" to see full reasoning & tool detail\n", style=THEME["muted"])
        log.write(t)

    def _calm_tool_running(self, name: str, args: Optional[dict], log: ConversationLog) -> None:
        """Update the live throbber with the in-progress action."""
        verb, target = self._calm_verb_target(name, args)
        icon = self._CALM_VERB_ICONS.get(verb, "✷")
        label = verb.capitalize()
        status = f"{icon} {label} {target}…" if target else f"{icon} {label}…"
        self._set_thinking_status(status)
        self._maybe_show_thinking_hint(log)

    def _calm_tool_done(
        self, name: str, args: Optional[dict], log: ConversationLog, ok: bool = True
    ) -> None:
        """Commit one tidy line for a finished tool (no raw output/diff)."""
        verb, target = self._calm_verb_target(name, args)
        self._calm_actions = getattr(self, "_calm_actions", 0) + 1
        icon = "✷" if ok else "✗"
        color = THEME["success"] if ok else THEME["error"]
        t = Text()
        t.append(f"  {icon} ", style=f"bold {color}")
        t.append(f"{verb:<7}", style=f"bold {THEME['text']}")
        if target:
            t.append(f" {target}", style=THEME["muted"])
        t.append("\n", style="")
        log.write(t)

    def _show_calm_summary(self, log: ConversationLog) -> None:
        """End-of-turn roll-up line shown in calm mode."""
        actions = getattr(self, "_calm_actions", 0)
        if actions <= 0:
            return
        elapsed = 0.0
        if getattr(self, "_thinking_start", 0):
            elapsed = max(0.0, time.time() - self._thinking_start)
        noun = "action" if actions == 1 else "actions"
        t = Text()
        t.append("  ✓ ", style=f"bold {THEME['success']}")
        t.append(f"done · {actions} {noun}", style=THEME["muted"])
        if elapsed:
            t.append(f" · {elapsed:.1f}s", style=THEME["dim"])
        t.append("\n", style="")
        log.write(t)
        self._calm_actions = 0

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

        if response_text.strip():
            log.write_final_response(
                response_text, agent=name, success=True, trailing_newline=False
            )

        # Simple footer line (no copy/open hints for cleaner UX)
        footer = Text()
        footer.append("\n", style="")
        log.write(footer)

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


    def _show_final_outcome(
        self, response_text: str, name: str, summary: dict, log: ConversationLog
    ):
        """Show a compact final outcome with the answer first."""
        # Store the response for :copy command
        log._last_response = response_text
        self._last_response = response_text

        duration = summary.get("duration", 0)
        tool_count = summary.get("tool_count", 0)
        files_modified = summary.get("files_modified", [])
        files_read = summary.get("files_read", [])
        file_diffs = summary.get("file_diffs", {})  # NEW: Get diff data

        # Only report files this turn actually changed (tracked by the agent).
        # We intentionally do NOT fall back to the ambient git working tree:
        # a simple question that edits nothing should show no change block,
        # even when the repo already has unrelated uncommitted edits. Use
        # ``:diff`` or the Changes sidebar to inspect the full working tree.

        # Keep prior turns in the log so users can scroll back through the
        # whole conversation (PgUp/PgDn). Instead of wiping the view each turn,
        # divide completed turns with a subtle separator.
        log.auto_scroll = True
        separator = Text()
        separator.append("\n")
        separator.append("  " + "─" * 44 + "\n", style=SQ_COLORS.text_muted)
        log.write(separator)

        header = Text()
        header.append("  Done", style=f"bold {SQ_COLORS.success}")
        header.append("  •  ", style=SQ_COLORS.text_muted)
        header.append(name, style=f"bold {SQ_COLORS.text_primary}")

        total_additions = sum(d.get("additions", 0) for d in file_diffs.values())
        total_deletions = sum(d.get("deletions", 0) for d in file_diffs.values())

        facts = [f"{duration:.1f}s"]
        if tool_count > 0:
            facts.append(f"{tool_count} tools")
        if files_read:
            facts.append(f"{len(files_read)} read")
        if files_modified:
            change_label = f"{len(files_modified)} changed"
            if total_additions > 0 or total_deletions > 0:
                change_label += f" (+{total_additions}/-{total_deletions})"
            facts.append(change_label)
        header.append("  •  ", style=SQ_COLORS.text_muted)
        header.append("  •  ".join(facts), style=SQ_COLORS.text_muted)
        header.append("\n\n")

        log.write(header)

        if response_text.strip():
            log.write_final_response(response_text, agent=name, success=True)

        # File changes are HIDDEN by default: a turn shows only a one-line
        # summary the user can expand. The full file panel and inline diffs
        # appear only in verbose mode (``:work verbose``); ``:diff`` opens the
        # changes on demand. This keeps simple turns from dumping a diff block.
        change_mode = getattr(log, "tool_output_mode", "normal")
        if files_modified and change_mode == "verbose":
            from superqode.widgets.response_changes import (
                render_file_changes_section,
                render_inline_file_diffs,
            )
            from rich.console import Console
            from io import StringIO

            changes_section = render_file_changes_section(files_modified, file_diffs, max_files=10)
            console = Console(file=StringIO(), width=120, legacy_windows=False)
            console.print(changes_section)
            inline_diffs = render_inline_file_diffs(files_modified, file_diffs, max_files=10)
            console.print(inline_diffs)
            log.write(console.file.getvalue())
        elif files_modified:
            # Collapsed one-liner (normal and minimal modes).
            self._write_collapsed_changes_line(log, files_modified, file_diffs)

        footer = Text()
        footer.append("  Actions: ", style=SQ_COLORS.text_muted)
        footer.append(":work", style=f"bold {SQ_COLORS.info}")
        footer.append(" summary", style=SQ_COLORS.text_muted)
        if files_modified:
            footer.append("  •  ", style=SQ_COLORS.text_muted)
            footer.append(":diff", style=f"bold {SQ_COLORS.info}")
            footer.append(" changes", style=SQ_COLORS.text_muted)
            footer.append("  •  ", style=SQ_COLORS.text_muted)
            footer.append(":undo", style=f"bold {SQ_COLORS.info}")
        footer.append("  •  ", style=SQ_COLORS.text_muted)
        footer.append(":select response", style=f"bold {SQ_COLORS.info}")
        footer.append("\n", style=SQ_COLORS.text_muted)
        log.write(footer)

        # NEW: Trigger sidebar auto-navigation if files were modified
        if files_modified:
            self.set_timer(0.2, lambda: self._navigate_to_sidebar_changes(files_modified))

        # Keep the view pinned to the latest response. We no longer clear the
        # log each turn, so scrolling home would jump away from the answer the
        # user just asked for — scroll to the end and resume follow mode.
        log.auto_scroll = True
        self.set_timer(0.1, lambda: log.scroll_end(animate=False))


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
            try:
                if self._acp_loop_runner is not None:
                    self._acp_loop_runner.run(self._acp_client.stop())
                else:
                    asyncio.create_task(self._acp_client.stop())
            except Exception:
                pass
            self._acp_client = None
            self._acp_client_key = None

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

    def _reset_mode_badge_after_role_run(self):
        """Reset mode badge to HOME after a role run completes."""
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


    def _agent_session_label(self, provider: str) -> str:
        """Session-banner label that names what actually runs the turn.

        Self-contained runtimes (Codex, Claude Agent SDK) execute their own
        agent loop and tools; labelling those sessions with SuperQode's
        native harness ("Harness: Core") misled users about whose harness
        was active.
        """
        pure = getattr(self, "_pure_mode", None)
        runtime_name = str(getattr(pure, "runtime_name", "") or "")
        if runtime_name in self._SELF_CONTAINED_RUNTIMES:
            friendly = {
                "codex-sdk": "Codex",
                "claude-agent-sdk": "Claude Agent SDK",
            }.get(runtime_name, runtime_name)
            return f"Runtime: {friendly} (agent-owned harness)"
        harness_name = ""
        try:
            harness_name = pure.get_status().get("harness", {}).get("name", "") if pure else ""
        except Exception:  # noqa: BLE001 - banner must never fail a send
            harness_name = ""
        if harness_name:
            return f"Harness: {_harness_display_name(harness_name)}"
        return f"BYOK {provider}"

    def _show_pure_tool_call(self, name: str, args: dict, log: ConversationLog):
        """Show Pure/BYOK/local tool calls through the shared tool renderer."""
        # Calm mode: surface the action in the live throbber, not a full row.
        if self._is_calm_output():
            self._calm_tool_running(name, args, log)
            return
        file_path = args.get("path", args.get("file_path", args.get("filePath", "")))
        command = args.get("command", "")
        log.add_tool_call(name, "running", file_path, command, "", args)

    def _show_pure_tool_result(self, name: str, result, log: ConversationLog):
        """Show Pure/BYOK/local tool results through the shared tool renderer."""
        success = bool(getattr(result, "success", False))
        # Calm mode: one tidy line per finished tool, no raw output/diff.
        if self._is_calm_output():
            metadata = getattr(result, "metadata", None) or {}
            # Streamed output chunks are progress, not completions. Committing
            # a line per chunk produced a stack of bare "run" rows on the
            # Codex runtime.
            if metadata.get("partial"):
                return
            # Forward every target-like field, not only path: bash results
            # carry "command" (a bare "run" line told the user nothing about
            # what ran), search tools carry "pattern"/"query".
            args = {
                key: metadata.get(key)
                for key in ("path", "command", "pattern", "query")
                if metadata.get(key)
            }
            self._calm_tool_done(name, args, log, ok=success)
            return
        status = "success" if success else "error"
        output = getattr(result, "output", "") if success else getattr(result, "error", "")
        output_str = str(output) if output else ""
        metadata = getattr(result, "metadata", None) or {}
        file_path = str(metadata.get("path") or "")
        diff_text = str(metadata.get("diff_text") or "")
        additions = metadata.get("additions")
        deletions = metadata.get("deletions")
        if not diff_text and output_str and self._looks_like_diff(output_str):
            diff_text = output_str
            output_str = "updated"
        log.add_tool_call(
            name,
            status,
            file_path,
            str(metadata.get("command") or ""),
            output_str,
            None,
            diff_text,
            None,
            additions if isinstance(additions, int) else None,
            deletions if isinstance(deletions, int) else None,
            metadata,
        )


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


    async def _warmup_ds4(self, client, model: str, log: ConversationLog) -> None:
        """Pre-load the DS4 model on connect, with a live elapsed-time indicator.

        DS4's first inference pays a large one-time cost paging the ~81GB model
        in from disk; doing it here (visibly) keeps the user's first prompt
        fast. Opt out with ``SUPERQODE_DS4_WARMUP=0``. Never fails the connect:
        a slow/failed warmup just leaves the model to load on first prompt.
        """
        import asyncio
        import os
        import time

        if os.getenv("SUPERQODE_DS4_WARMUP", "1").strip().lower() in ("0", "false", "no", "off"):
            return

        log.add_info("⏳ Loading model into memory (first start can be slow on a cold cache)…")
        task = asyncio.ensure_future(client.warmup(model))
        start = time.monotonic()
        next_tick = 10.0
        while not task.done():
            await asyncio.sleep(0.5)
            elapsed = time.monotonic() - start
            if elapsed >= next_tick:
                log.add_info(f"   …still loading the model ({int(elapsed)}s)")
                next_tick += 10.0

        result = await task
        if result.get("ok"):
            log.add_success(f"✓ DS4 ready (warm) — {result.get('elapsed', 0.0):.0f}s")
            log.add_info("Ready to chat! Type your message below.")
        else:
            # Don't block usage — the model will simply load on the first prompt.
            log.add_warning(
                "DS4 warmup did not complete "
                f"({result.get('error') or 'unknown error'}); the first prompt may be slow."
            )

    # =========================================================================
    # BYOK ENHANCED COMMANDS
    # =========================================================================


    def _providers_cmd(self, args: str, log: ConversationLog):
        """Show provider setup, labels, and representative models."""
        from superqode.providers.recommendations import provider_doctor_cards
        from superqode.providers.registry import PROVIDERS

        args = args.strip()
        parts = args.split(maxsplit=1) if args else []
        sub = parts[0].lower() if parts else ""
        subargs = parts[1].strip() if len(parts) > 1 else ""

        if sub in ("doctor", "check"):
            self._doctor_cmd(subargs, log)
            return

        if sub in {
            "list",
            "models",
            "guide",
            "recommend",
            "scan-free",
            "test",
            "monty",
            "ds4",
            "mlx",
        }:
            self._run_cli_group("providers", args, log, "Providers command")
            return

        if sub in ("smoke", "test"):
            self.run_worker(self._providers_smoke_cmd(subargs, log))
            return

        if sub in ("free", "scan-free", "store"):
            self.run_worker(self._providers_free_cmd(subargs, log))
            return

        provider_id = args or None
        if provider_id and provider_id not in PROVIDERS:
            log.add_error(f"Provider not found: {provider_id}")
            log.add_info("Use :providers to list providers or :recommend coding for suggestions.")
            return

        cards = provider_doctor_cards([provider_id] if provider_id else None)
        t = Text()
        t.append("\n  ☁ ", style=f"bold {THEME['cyan']}")
        t.append("Provider Guide\n\n", style=f"bold {THEME['text']}")
        t.append(
            "  Labels show setup readiness, cost/context, and tool support.\n\n",
            style=THEME["muted"],
        )

        for card in cards[:12]:
            status_style = THEME["success"] if card["configured"] else THEME["warning"]
            status = "ready" if card["configured"] else "missing"
            labels = ", ".join(card["labels"]) or "-"
            t.append(f"  {card['provider']:<16}", style=f"bold {THEME['cyan']}")
            t.append(f"{status:<8}", style=status_style)
            t.append(f"{card['name']}  ", style=THEME["text"])
            t.append(f"[{labels}]\n", style=THEME["dim"])
            t.append(f"    setup: {card['setup_hint']}\n", style=THEME["muted"])
            for model in card["models"][:3]:
                t.append(f"    - {model['model']:<28}", style=THEME["text"])
                t.append(f"{model['price']:<13}", style=THEME["gold"])
                t.append(f"{model['context']} ctx  ", style=THEME["cyan"])
                t.append(f"tools={model['tool_support']}\n", style=THEME["muted"])
            t.append("\n")

        t.append("  Commands: ", style=THEME["muted"])
        t.append(":providers <provider>", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":providers free --live openrouter", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(
            ":recommend coding|review|testing|budget|speed|large-context|reasoning",
            style=THEME["cyan"],
        )
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    async def _providers_free_cmd(self, args: str, log: ConversationLog):
        """Show free/local inference options from the TUI."""
        from superqode.providers.free_inference import (
            list_free_inference_offers,
            offer_status,
            scan_live_free_candidates,
        )

        tokens = (args or "").split()
        live = "--live" in tokens or "live" in tokens
        configured = "--configured" in tokens
        source_tokens = [
            token for token in tokens if token in {"openrouter", "models-dev", "litellm"}
        ]
        provider_tokens = [
            token
            for token in tokens
            if token
            not in {
                "--live",
                "live",
                "--configured",
                "openrouter",
                "models-dev",
                "litellm",
            }
        ]
        provider_filter = provider_tokens[0] if provider_tokens else None

        if live:
            log.add_info("Scanning live model/pricing catalogs...")
            candidates, errors = await asyncio.to_thread(
                scan_live_free_candidates,
                sources=source_tokens or None,
                limit=50,
            )
            if provider_filter:
                needle = provider_filter.lower()
                candidates = [
                    item
                    for item in candidates
                    if item.provider.lower() == needle
                    or needle in item.model.lower()
                    or needle in item.name.lower()
                ]
            self._show_command_output(
                log,
                self._format_live_free_inference(candidates, errors, source_tokens),
            )
            return

        offers = list_free_inference_offers(
            provider=provider_filter,
            configured_only=configured,
        )
        self._show_command_output(
            log,
            self._format_free_inference_offers(offers, offer_status),
        )


    async def _providers_smoke_cmd(self, args: str, log: ConversationLog):
        """Run a local provider smoke check from the TUI."""
        from superqode.providers.local.smoke import all_local_provider_ids, smoke_local_provider

        tokens = (args or "").split()
        if not tokens:
            log.add_info("Usage: :providers smoke <local-provider> [model] [--run]")
            log.add_info("Example: :providers smoke ollama")
            return

        provider = tokens[0]
        run_prompt = "--run" in tokens
        no_tool_test = "--no-tool-test" in tokens
        model_parts = [token for token in tokens[1:] if token not in ("--run", "--no-tool-test")]
        model = " ".join(model_parts).strip() or None

        if provider not in all_local_provider_ids():
            log.add_error(f"Local provider not found: {provider}")
            log.add_info(f"Available: {', '.join(all_local_provider_ids())}")
            return

        log.add_info(f"Checking {provider}...")
        payload = await smoke_local_provider(
            provider,
            model,
            run_prompt=run_prompt,
            tool_test=not no_tool_test,
        )
        self._show_command_output(log, self._format_local_smoke_result(payload))


    def _recommend_cmd(self, args: str, log: ConversationLog):
        """Recommend providers/models for a task."""
        from superqode.providers.recommendations import normalize_task, recommend_models

        task = normalize_task(args.strip() or "coding")
        recommendations = recommend_models(task, limit=8)
        self._recommendation_list = recommendations
        self._awaiting_recommendation_selection = bool(recommendations)
        t = Text()
        t.append("\n  ◆ ", style=f"bold {THEME['purple']}")
        t.append("Model Recommendations\n\n", style=f"bold {THEME['text']}")
        t.append("  Task: ", style=THEME["muted"])
        t.append(f"{task}\n\n", style=f"bold {THEME['cyan']}")

        if not recommendations:
            self._awaiting_recommendation_selection = False
            t.append("  No recommendations available.\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        for index, item in enumerate(recommendations, 1):
            setup_style = THEME["success"] if item.setup.configured else THEME["warning"]
            setup = "ready" if item.setup.configured else item.setup.setup_hint
            labels = ", ".join(item.labels[:6])
            t.append(f"  [{index}] ", style=THEME["dim"])
            t.append(f"{item.provider}/{item.model}\n", style=f"bold {THEME['text']}")
            t.append("      score ", style=THEME["muted"])
            t.append(f"{item.score:<3}", style=THEME["success"])
            t.append(" price ", style=THEME["muted"])
            t.append(f"{item.price:<13}", style=THEME["gold"])
            t.append(" context ", style=THEME["muted"])
            t.append(f"{item.context:<6}", style=THEME["cyan"])
            t.append(" tools ", style=THEME["muted"])
            t.append(
                f"{item.tool_support:<3}",
                style=THEME["success"] if item.tool_support == "yes" else THEME["dim"],
            )
            t.append(" setup ", style=THEME["muted"])
            t.append(f"{setup}\n", style=setup_style)
            t.append(f"      {item.reason}\n", style=THEME["muted"])
            if labels:
                t.append(f"      {labels}\n", style=THEME["dim"])
            t.append("\n")

        t.append("  Type a number to connect, or use ", style=THEME["muted"])
        t.append(":connect <provider>/<model>", style=THEME["cyan"])
        t.append(".\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _handle_recommendation_selection(self, selection: str, log: ConversationLog) -> bool:
        """Connect to a provider/model from the last :recommend list."""
        selection = (selection or "").strip()
        recommendations = getattr(self, "_recommendation_list", []) or []
        if not selection:
            return False
        if selection.lower() in ("back", "cancel", "q"):
            self._awaiting_recommendation_selection = False
            log.add_info("Recommendation selection cancelled.")
            return True
        if not selection.isdigit():
            return False
        index = int(selection) - 1
        if index < 0 or index >= len(recommendations):
            log.add_error(f"Invalid recommendation. Choose 1-{len(recommendations)}")
            return True

        item = recommendations[index]
        self._awaiting_recommendation_selection = False
        log.add_info(f"Connecting to {item.provider}/{item.model}...")
        if item.provider in ("ds4", "ollama", "lmstudio", "mlx", "vllm", "sglang", "tgi"):
            self._connect_local_mode(item.provider, item.model, log)
        else:
            self._connect_byok_mode(item.provider, item.model, log)
        return True

    def _sandbox_cmd(self, args: str, log: ConversationLog):
        """Show sandbox provider readiness in the TUI."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :sandbox arguments: {exc}")
            return
        if tokens and tokens[0] in {"doctor", "run"}:
            self._run_cli_passthrough(["sandbox", *tokens], log, "Sandbox command")
            return

        from superqode.sandbox import (
            get_sandbox_capabilities,
            sandbox_provider_status,
            supported_sandbox_backends,
        )

        requested = args.strip()
        backends = [requested] if requested else supported_sandbox_backends(include_cloud=True)
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['cyan']}")
        t.append("Sandbox Backends\n\n", style=f"bold {THEME['text']}")

        for backend in backends:
            status = sandbox_provider_status(backend)
            style = THEME["success"] if status.available else THEME["warning"]
            t.append(f"  {status.backend:<12}", style=f"bold {THEME['cyan']}")
            t.append(("ready" if status.available else "missing").ljust(9), style=style)
            t.append(f"{status.detail}\n", style=THEME["text"])
            try:
                caps = get_sandbox_capabilities(backend)
                t.append(
                    f"    read={caps.can_read} write={caps.can_write} shell={caps.can_shell} network={caps.can_network}\n",
                    style=THEME["muted"],
                )
            except ValueError:
                pass
            if status.required_env:
                t.append(f"    env: {', '.join(status.required_env)}\n", style=THEME["dim"])
            if status.optional_dependency:
                t.append(f"    install: {status.optional_dependency}\n", style=THEME["dim"])

        t.append("\n  Commands: ", style=THEME["muted"])
        t.append(":sandbox <backend>", style=THEME["cyan"])
        t.append(", CLI ", style=THEME["muted"])
        t.append("superqode sandbox run docker -- pytest -q", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _plugins_cmd(self, args: str, log: ConversationLog):
        """Manage project plugin manifests."""
        from superqode.plugins import (
            disable_plugin,
            disabled_plugin_ids,
            discover_plugin_manifests,
            enable_plugin,
            install_plugin,
            load_plugin_manifest,
            load_plugins,
            validate_plugin_manifest,
        )

        try:
            tokens = shlex.split((args or "").strip())
        except ValueError as exc:
            log.add_error(f"Could not parse :plugins arguments: {exc}")
            return
        subcommand = tokens[0].lower() if tokens else "list"
        subargs = tokens[1:]

        if subcommand in {"show", "list"} and subargs:
            self._run_cli_passthrough(["plugins", *tokens], log, "Plugins command")
            return

        if subcommand in {"add", "install"}:
            if not subargs:
                log.add_info("Usage: :plugins add <local-plugin-dir|plugin.json>")
                return
            if not self._ensure_project_trusted_for(log, "install a plugin"):
                return
            try:
                plugin = install_plugin(subargs[0], Path.cwd())
            except Exception as exc:
                log.add_error(f"Could not install plugin: {exc}")
                return
            log.add_success(f"Installed plugin {plugin.id} -> .superqode/plugins/{plugin.id}")
            return

        if subcommand in {"enable", "disable"}:
            if not subargs:
                log.add_info(f"Usage: :plugins {subcommand} <plugin-id>")
                return
            plugin_id = subargs[0]
            if subcommand == "enable":
                if not self._ensure_project_trusted_for(log, "enable a plugin"):
                    return
                changed = enable_plugin(plugin_id, Path.cwd())
                log.add_success(
                    f"Enabled plugin {plugin_id}"
                    if changed
                    else f"Plugin {plugin_id} was already enabled"
                )
            else:
                changed = disable_plugin(plugin_id, Path.cwd())
                log.add_success(
                    f"Disabled plugin {plugin_id}"
                    if changed
                    else f"Plugin {plugin_id} was already disabled"
                )
            return

        if subcommand in {"doctor", "validate"}:
            paths = discover_plugin_manifests(Path.cwd())
            if subargs:
                target = Path(subargs[0]).expanduser()
                if not target.is_absolute():
                    target = Path.cwd() / target
                if target.is_dir():
                    target = target / "plugin.json"
                paths = [target]
            t = Text()
            t.append("\n  Plugin Doctor\n\n", style=f"bold {THEME['purple']}")
            if not paths:
                t.append("  No plugin manifests found.\n", style=THEME["muted"])
                t.append("  Install one with ", style=THEME["muted"])
                t.append(":plugins add <path>", style=THEME["cyan"])
                t.append(".\n", style=THEME["muted"])
                self._show_command_output(log, t)
                return
            ok_count = 0
            for path in paths:
                issues = validate_plugin_manifest(path)
                label = str(path)
                try:
                    manifest = load_plugin_manifest(path)
                    label = f"{manifest.id}  ({path})"
                except Exception:
                    pass
                if not issues:
                    ok_count += 1
                    t.append(f"  OK   {label}\n", style=THEME["success"])
                else:
                    t.append(f"  FAIL {label}\n", style=THEME["error"])
                    for issue in issues:
                        t.append(f"       - {issue}\n", style=THEME["warning"])
            t.append(f"\n  {ok_count}/{len(paths)} manifests valid.\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        if subcommand not in {"list", "ls", "status"}:
            log.add_info("Usage: :plugins [list|doctor|add|enable|disable] ...")
            return

        plugins = []
        load_errors: list[tuple[Path, str]] = []
        for path in discover_plugin_manifests(Path.cwd()):
            try:
                plugins.append(load_plugin_manifest(path))
            except Exception as exc:
                load_errors.append((path, str(exc)))
        disabled = disabled_plugin_ids(Path.cwd())
        t = Text()
        t.append("\n  ◇ ", style=f"bold {THEME['purple']}")
        t.append("Plugins\n\n", style=f"bold {THEME['text']}")
        if not plugins and not load_errors:
            t.append("  No plugins found.\n", style=THEME["muted"])
            t.append(
                "  Expected manifests under .superqode/plugins/*/plugin.json.\n", style=THEME["dim"]
            )
            t.append("  Install one with ", style=THEME["muted"])
            t.append(":plugins add <path>", style=THEME["cyan"])
            t.append(".\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        for plugin in plugins:
            enabled = plugin.id not in disabled
            status = "enabled" if enabled else "disabled"
            status_style = THEME["success"] if enabled else THEME["warning"]
            t.append(f"  {plugin.id:<24}", style=f"bold {THEME['cyan']}")
            t.append(f"{plugin.version:<10}", style=THEME["success"])
            t.append(f"{status:<10}", style=status_style)
            t.append(f"{plugin.name}\n", style=THEME["text"])
            if plugin.description:
                t.append(f"    {plugin.description}\n", style=THEME["muted"])
            if plugin.commands:
                commands = [
                    str(item.get("name") or item.get("command") or item)
                    for item in plugin.commands
                    if isinstance(item, dict)
                ]
                t.append(f"    commands: {', '.join(commands)}\n", style=THEME["dim"])
            if plugin.tools:
                tools = [
                    str(item.get("name") or item.get("tool") or item)
                    for item in plugin.tools
                    if isinstance(item, dict)
                ]
                t.append(f"    tools: {', '.join(tools)}\n", style=THEME["dim"])
            if plugin.path:
                t.append(f"    {plugin.path}\n", style=THEME["dim"])
        for path, error in load_errors:
            t.append(f"  broken manifest  {path}\n", style=THEME["error"])
            t.append(f"    {error}\n", style=THEME["warning"])
        t.append("\n  Commands: ", style=THEME["muted"])
        t.append(":plugins doctor", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":plugins add <path>", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":plugins enable|disable <id>", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)


    def _memory_cmd(self, args: str, log: ConversationLog):
        """Manage SuperQode agent memory from the TUI."""
        from superqode.memory import available_memory_providers, create_memory_provider

        try:
            tokens = shlex.split((args or "").strip())
        except ValueError as exc:
            log.add_error(f"Could not parse :memory arguments: {exc}")
            return
        subcommand = tokens[0].lower() if tokens else "status"
        rest = tokens[1:]

        if subcommand in {"", "status"}:
            provider_name = rest[0] if rest else "local"
            try:
                status = create_memory_provider(provider_name, project_root=Path.cwd()).status()
            except Exception as exc:
                log.add_error(f"Could not inspect memory provider: {exc}")
                return
            t = Text()
            t.append("\n  Memory\n\n", style=f"bold {THEME['purple']}")
            t.append("  Provider ", style=THEME["muted"])
            t.append(f"{status.provider}\n", style=f"bold {THEME['cyan']}")
            t.append("  Status   ", style=THEME["muted"])
            state = self._memory_status_state(status)
            t.append(
                f"{state}\n",
                style=THEME["success"] if status.available else THEME["warning"],
            )
            t.append("  Records  ", style=THEME["muted"])
            t.append(f"{status.record_count}\n", style=THEME["text"])
            if status.path:
                t.append("  Path     ", style=THEME["muted"])
                t.append(f"{status.path}\n", style=THEME["dim"])
            if status.detail:
                t.append("  Detail   ", style=THEME["muted"])
                t.append(f"{status.detail}\n", style=THEME["text"])
            t.append("\n  Commands: ", style=THEME["muted"])
            t.append(":memory remember", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":memory search", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":memory providers", style=THEME["cyan"])
            t.append("\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        if subcommand in {"providers", "doctor"}:
            statuses = available_memory_providers(Path.cwd())
            t = Text()
            t.append("\n  Memory Providers\n\n", style=f"bold {THEME['purple']}")
            for status in statuses:
                state = self._memory_status_state(status)
                style = THEME["success"] if status.available else THEME["warning"]
                t.append(f"  {status.provider:<12}", style=f"bold {THEME['cyan']}")
                t.append(f"{state:<10}", style=style)
                t.append(f"{status.detail}\n", style=THEME["text"])
                if status.path:
                    t.append(f"    {status.path}\n", style=THEME["dim"])
            self._show_command_output(log, t)
            return

        if subcommand == "remember":
            text = " ".join(rest).strip()
            if not text:
                log.add_info("Usage: :memory remember <text>")
                return
            try:
                record = create_memory_provider("local", project_root=Path.cwd()).remember(text)
            except Exception as exc:
                log.add_error(f"Could not save memory: {exc}")
                return
            log.add_success(f"Remembered {record.id}")
            return

        if subcommand == "search":
            provider_name = "local"
            query_parts = rest
            if len(rest) >= 2 and rest[0] in {"local", "specmem", "mem0", "cognee", "supermemory"}:
                provider_name = rest[0]
                query_parts = rest[1:]
            query = " ".join(query_parts).strip()
            if not query:
                log.add_info("Usage: :memory search [local|specmem] <query>")
                return
            try:
                results = create_memory_provider(provider_name, project_root=Path.cwd()).search(
                    query
                )
            except Exception as exc:
                log.add_error(f"Could not search memory: {exc}")
                return
            t = Text()
            t.append("\n  Memory Search\n\n", style=f"bold {THEME['purple']}")
            if not results:
                t.append("  No memory matches.\n", style=THEME["muted"])
            for result in results:
                record = result.record
                t.append(f"  {record.id:<12}", style=f"bold {THEME['cyan']}")
                t.append(f"{result.provider:<8}", style=THEME["muted"])
                t.append(f"{record.kind:<10}", style=THEME["success"])
                t.append(f"score={result.score:.2f}\n", style=THEME["dim"])
                t.append(f"    {record.content}\n", style=THEME["text"])
            self._show_command_output(log, t)
            return

        if subcommand == "forget":
            if not rest:
                log.add_info("Usage: :memory forget <id>")
                return
            try:
                ok = create_memory_provider("local", project_root=Path.cwd()).forget(rest[0])
            except Exception as exc:
                log.add_error(f"Could not forget memory: {exc}")
                return
            if ok:
                log.add_success(f"Forgot {rest[0]}")
            else:
                log.add_error(f"Memory not found: {rest[0]}")
            return

        if subcommand == "export":
            provider_name = rest[0] if rest else "local"
            try:
                payload = create_memory_provider(provider_name, project_root=Path.cwd()).export()
            except Exception as exc:
                log.add_error(f"Could not export memory: {exc}")
                return
            out_path = Path(".superqode") / "exports" / f"memory-{provider_name}.json"
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
            except Exception as exc:
                log.add_error(f"Could not write memory export: {exc}")
                return
            log.add_success(f"Exported memory -> {out_path}")
            return

        log.add_info("Usage: :memory [status|providers|doctor|remember|search|forget|export]")

    def _memory_status_state(self, status) -> str:
        if getattr(status, "available", False):
            return "ready"
        if not getattr(status, "enabled", True):
            return "disabled"
        if getattr(status, "installed", None) is False:
            return "missing"
        return "missing"

    def _benchmark_cmd(self, args: str, log: ConversationLog):
        """Show benchmark harness status and optional task-file guidance."""
        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :benchmark arguments: {exc}")
            return
        if tokens and tokens[0] == "run":
            self._run_cli_passthrough(["benchmark", *tokens], log, "Benchmark command")
            return

        from superqode.benchmarks import DEFAULT_TARGETS, is_target_available

        t = Text()
        t.append("\n  ▤ ", style=f"bold {THEME['gold']}")
        t.append("Benchmark Harness\n\n", style=f"bold {THEME['text']}")
        for name, target in DEFAULT_TARGETS.items():
            available = is_target_available(target)
            style = THEME["success"] if available else THEME["warning"]
            t.append(f"  {name:<12}", style=f"bold {THEME['cyan']}")
            t.append(("available" if available else "missing").ljust(11), style=style)
            t.append(f"{' '.join(target.command)}\n", style=THEME["muted"])

        t.append("\n  CLI run:\n", style=THEME["muted"])
        t.append(
            "    superqode benchmark run tasks.json --target superqode --target opencode --target pi --target deepagents\n",
            style=THEME["cyan"],
        )
        if args.strip():
            t.append(
                "\n  TUI note: benchmark execution is CLI-backed for reproducible logs.\n",
                style=THEME["dim"],
            )
        self._show_command_output(log, t)


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

        self._call_ui(log.write, t)

    # ========================================================================
    # Local Provider Commands
    # ========================================================================


    @staticmethod
    def _parse_serve_args(subargs: str) -> tuple[str, dict]:
        """Parse ``<engine> [--model X] [--port N] [--ctx N] [--host H]``."""
        import shlex

        tokens = shlex.split(subargs)
        engine = tokens[0] if tokens else ""
        opts: dict = {}
        i = 1
        while i < len(tokens):
            tok = tokens[i]
            if tok in ("--model", "-m") and i + 1 < len(tokens):
                opts["model"] = tokens[i + 1]
                i += 2
            elif tok in ("--port", "-p") and i + 1 < len(tokens):
                opts["port"] = int(tokens[i + 1])
                i += 2
            elif tok == "--ctx" and i + 1 < len(tokens):
                opts["ctx"] = int(tokens[i + 1])
                i += 2
            elif tok == "--host" and i + 1 < len(tokens):
                opts["host"] = tokens[i + 1]
                i += 2
            elif tok == "--extra" and i + 1 < len(tokens):
                opts.setdefault("extra_args", []).append(tokens[i + 1])
                i += 2
            elif tok.startswith("--extra="):
                opts.setdefault("extra_args", []).append(tok.split("=", 1)[1])
                i += 1
            elif tok in ("--allow-download", "-y"):
                opts["allow_download"] = True
                i += 1
            else:
                i += 1
        return engine, opts


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


    def _acp_cmd(self, args: str, log: ConversationLog):
        """Handle :acp command with subcommands (list, install, model, doctor).

        Bare agent names are treated as connect targets so ``:acp grok`` works
        the same as ``:connect acp grok`` (Grok Build ACP, not the subscription
        harness path).
        """
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
        elif sub in ("doctor", "check"):
            self.run_worker(self._acp_doctor_cmd(subargs, log))
        else:
            # ":acp grok" / ":acp opencode" → connect that ACP agent by short name
            self._connect_acp_cmd(args.strip(), log)

    def _agents_cmd(self, args: str, log: ConversationLog):
        """Handle :agents as an alias for ACP agent management."""
        parts = args.split(maxsplit=1) if args else []
        sub = parts[0].lower() if parts else "list"
        subargs = parts[1] if len(parts) > 1 else ""

        if sub in ("list", ""):
            self._show_agents(log)
        elif sub in ("doctor", "check"):
            self.run_worker(self._acp_doctor_cmd(subargs, log))
        elif sub == "install":
            if subargs:
                self._install_agent(subargs, log)
            else:
                log.add_info("Usage: :agents install <name>")
        elif sub == "connect":
            self._connect_acp_cmd(subargs, log)
        else:
            self._run_cli_group("agents", args, log, "Agents command")

    async def _acp_doctor_cmd(self, args: str, log: ConversationLog):
        """Run ACP agent diagnostics from the TUI."""
        from superqode.acp.doctor import acp_doctor

        tokens = (args or "").split()
        live = any(token in ("--live", "live") for token in tokens)
        agent_parts = [token for token in tokens if token not in ("--live", "live")]
        agent = " ".join(agent_parts).strip() or None

        if agent:
            log.add_info(f"Checking ACP agent {agent}...")
        else:
            log.add_info("Checking ACP agents...")

        results = await acp_doctor(agent, live=live)
        if agent and not results:
            log.add_error(f"ACP agent not found: {agent}")
            return

        self._show_command_output(log, self._format_acp_doctor_results(results, live=live))


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
        t.append(f"  💡 ", style=THEME["muted"])
        t.append(f"Type a number ", style=THEME["dim"])
        t.append(f"(1-{len(agents)})", style=THEME["cyan"])
        t.append(" to select, or use ", style=THEME["dim"])
        t.append(f"↑↓", style=THEME["cyan"])
        t.append(" arrows + ", style=THEME["dim"])
        t.append(f"Enter", style=THEME["cyan"])
        t.append("\n\n", style=THEME["dim"])

        # Separate by installation status
        installed = []
        not_installed = []

        for agent_id, agent_data in agents.items():
            is_installed = check_agent_installed(agent_data)
            if is_installed:
                installed.append((agent_id, agent_data))
            else:
                not_installed.append((agent_id, agent_data))

        # ACP agent emojis (from https://agentclientprotocol.com/get-started/agents)
        agent_emojis = {
            "opencode": "🤖",  # Robot
            "claude": "🧠",  # Brain (Claude Code)
            "claude.com": "🧠",  # Brain (Claude Code)
            "gemini": "💎",  # Gem (Gemini CLI)
            "geminicli": "💎",  # Gem (Gemini CLI)
            "codex": "📝",  # Memo/code
            "codex.openai.com": "📝",  # Memo/code
            "grok": "G",  # Grok Build
            "x.ai": "G",  # Grok Build
            "openclaw": "🦞",  # OpenClaw
            "openclaw.ai": "🦞",  # OpenClaw
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
            "amp": "⚡",  # Lightning (Amp)
            "ampcode": "⚡",  # Lightning
            "ampcode.com": "⚡",  # Lightning
        }

        priority_order = {
            "opencode": 0,
            "opencode.ai": 0,
            "openclaw": 1,
            "openclaw.ai": 1,
            "claude": 2,
            "claude.com": 2,
            "codex": 3,
            "codex.openai.com": 3,
            "grok": 4,
            "x.ai": 4,
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
                    t.append(
                        f"[{num:2}] ",
                        style=self._picker_link_style(f"bold {THEME['success']}", num),
                    )
                    t.append(f"{emoji} ", style=THEME["success"])
                    t.append(f"{agent_data['short_name']:<15}", style=f"bold {THEME['success']}")
                    t.append(
                        f"{agent_data['name']}  ← SELECTED\n", style=f"bold {THEME['success']}"
                    )
                else:
                    t.append(
                        f"    [{num:2}] ",
                        style=self._picker_link_style(f"bold {THEME['text']}", num),
                    )
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
                    t.append(
                        f"[{num:2}] ",
                        style=self._picker_link_style(f"bold {THEME['success']}", num),
                    )
                    t.append(f"{emoji} ", style=THEME["warning"])
                    t.append(f"{agent_data['short_name']:<15}", style=f"bold {THEME['success']}")
                    t.append(
                        f"{agent_data['name']:<25}  ← SELECTED\n", style=f"bold {THEME['success']}"
                    )
                    if install_cmd:
                        t.append(f"         Install: ", style=THEME["dim"])
                        t.append(f"{install_cmd}\n", style=THEME["cyan"])
                else:
                    t.append(
                        f"    [{num:2}] ",
                        style=self._picker_link_style(f"bold {THEME['text']}", num),
                    )
                    t.append(f"{emoji} ", style=THEME["warning"])
                    t.append(f"{agent_data['short_name']:<15}", style=f"bold {THEME['text']}")
                    t.append(f"{agent_data['name']:<25}", style=THEME["muted"])

                    if install_cmd:
                        t.append(f"\n             Install: ", style=THEME["dim"])
                        t.append(f"{install_cmd}\n", style=THEME["cyan"])
                    else:
                        t.append(
                            f"\n             No install command available\n", style=THEME["dim"]
                        )
            t.append("\n", style="")

        t.append(f"  💡 Quick Actions:\n", style=THEME["muted"])
        t.append(f"    ", style=THEME["dim"])
        t.append(f"↑↓", style=THEME["cyan"])
        t.append(" arrows + ", style=THEME["dim"])
        t.append(f"Enter", style=THEME["cyan"])
        t.append(" or type a number\n", style=THEME["dim"])
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

    async def _a2a_cmd(self, args: str, log: ConversationLog):
        """Handle :a2a commands."""
        parts = args.split(maxsplit=1)
        subcommand = parts[0] if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        # Lazy load A2A commands
        if not hasattr(self, "_a2a_commands"):
            try:
                from .commands.a2a import create_a2a_commands

                self._a2a_commands = create_a2a_commands()
            except ImportError:
                log.add_error("A2A not installed. Run: uv tool install 'superqode[a2a]'")
                return

        await self._a2a_commands.handle_command(subcommand, subargs, log)

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

        refs = getattr(self, "_attached_refs", [])
        t.append(f"  📎 Attachments: ", style=THEME["muted"])
        t.append(f"{len(refs)}\n", style=THEME["cyan"] if refs else THEME["dim"])
        for ref in refs[:5]:
            t.append(f"     {ref}\n", style=THEME["dim"])
        if len(refs) > 5:
            t.append(f"     ... and {len(refs) - 5} more\n", style=THEME["dim"])

        log.write(t)

    def _show_harness_status(self, log: ConversationLog):
        """Show coding harness active state in one compact view."""
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Status\n\n", style=f"bold {THEME['text']}")

        session_id = "-"
        if hasattr(self, "_pure_mode"):
            try:
                session_id = self._pure_mode.get_current_session_id() or "-"
            except Exception:
                session_id = "-"

        git_branch = "-"
        git_dirty = "-"
        try:
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=Path.cwd(),
                text=True,
                capture_output=True,
                check=False,
                timeout=2,
            )
            git_branch = branch.stdout.strip() or "-"
            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=Path.cwd(),
                text=True,
                capture_output=True,
                check=False,
                timeout=2,
            )
            git_dirty = "dirty" if status.stdout.strip() else "clean"
        except Exception:
            pass

        fields = [
            ("Mode", self.current_mode or "home", THEME["purple"]),
            ("Provider", self.current_provider or "-", THEME["success"]),
            ("Model", self.current_model or "-", THEME["cyan"]),
            ("Agent", self.current_agent or "-", THEME["orange"]),
            ("Session", session_id[:12] if session_id != "-" else "-", THEME["text"]),
            ("Approval", self.approval_mode, THEME["warning"]),
            ("Attachments", str(len(getattr(self, "_attached_refs", []))), THEME["cyan"]),
            ("Branch", git_branch, THEME["text"]),
            ("Git", git_dirty, THEME["success"] if git_dirty == "clean" else THEME["warning"]),
            ("CWD", str(Path.cwd()), THEME["dim"]),
        ]
        for label, value, style in fields:
            t.append(f"  {label:<10}", style=THEME["muted"])
            t.append(f"{value}\n", style=style)

        refs = getattr(self, "_attached_refs", [])
        if refs:
            t.append("\n  Staged refs\n", style=f"bold {THEME['cyan']}")
            for ref in refs[:8]:
                t.append(f"    {ref}\n", style=THEME["dim"])
            if len(refs) > 8:
                t.append(f"    ... and {len(refs) - 8} more\n", style=THEME["dim"])

        if self.current_provider:
            try:
                from superqode.providers.recommendations import provider_doctor_cards

                card = provider_doctor_cards([self.current_provider])[0]
                labels = ", ".join(card["labels"][:6]) or "-"
                status = "ready" if card["configured"] else "needs setup"
                t.append("  Readiness ", style=THEME["muted"])
                t.append(
                    f"{status}",
                    style=THEME["success"] if card["configured"] else THEME["warning"],
                )
                t.append(f"  [{labels}]\n", style=THEME["dim"])
                if card["setup_hint"]:
                    t.append("  Setup     ", style=THEME["muted"])
                    t.append(f"{card['setup_hint']}\n", style=THEME["text"])
            except Exception:
                pass

        t.append("\n  Panels: ", style=THEME["muted"])
        t.append("Ctrl+B", style=THEME["cyan"])
        t.append(" toggle sidebar, ", style=THEME["muted"])
        t.append("Ctrl+1", style=THEME["cyan"])
        t.append(" harness, ", style=THEME["muted"])
        t.append("Ctrl+K", style=THEME["cyan"])
        t.append(" commands\n", style=THEME["muted"])
        t.append("  Recovery: ", style=THEME["muted"])
        t.append(":retry", style=THEME["cyan"])
        t.append("  ", style=THEME["muted"])
        t.append(":doctor current", style=THEME["cyan"])
        t.append("  ", style=THEME["muted"])
        t.append(":copy error\n", style=THEME["cyan"])

        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            sidebar.current_view = "harness"
            if not self.sidebar_visible:
                self.action_toggle_sidebar()
        except Exception:
            pass

        self._show_command_output(log, t)

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
        t.append(f"Connect to ACP agent (opencode, claude, etc.)\n\n", style=THEME["muted"])

        t.append(f"  ⚡ BYOK (Direct LLM)\n", style=f"bold {THEME['success']}")
        t.append(f"    :connect byok <p> <m>    ", style=THEME["success"])
        t.append(f"Connect to provider/model\n", style=THEME["muted"])
        t.append(f"    :connect                ", style=THEME["success"])
        t.append(f"Interactive picker (choose acp, byok, or local)\n\n", style=THEME["muted"])

        t.append(f"  ═══ All Commands ═══\n\n", style=f"bold {THEME['gold']}")

        sections = [
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
                    (":model", "Show current model card and runtime overrides"),
                    (
                        ":model switch <p>/<m>",
                        "Switch provider/model for native BYOK/local sessions",
                    ),
                    (":model reasoning <value>", "Set reasoning effort for future native runs"),
                    (":model temperature <n>", "Set temperature for future native runs"),
                    (":model doctor", "Check active provider/model readiness"),
                    (":providers [provider]", "Show provider setup and quality labels"),
                    (":doctor current", "Check active provider/model readiness"),
                    (":recommend <task>", "Recommend models for coding/review/testing/budget"),
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
                    (":local setup [model]", "TUI-first guide: pick model, serve, harness, smoke"),
                    (":local init", "Generate a local harness and run readiness smoke"),
                    (":local build", "Guided local harness builder without live model calls"),
                    (":local init --pack <pack> --skip-smoke", "Generate a harness with your pack"),
                    (":local migrate", "Plan prompt/skill migration to local models"),
                    (":local pack init", "Create a project-owned model policy pack"),
                    (":local optimize", "Benchmark local model candidates and role routing"),
                    (":local airplane prepare", "Create a strict no-network local harness"),
                    (":local airplane smoke", "Verify offline harness and local search readiness"),
                    (":local smoke", "Run non-destructive local coding readiness checks"),
                    (
                        ":local search <query>",
                        "Find a trusted model + how to get it (hardware-aware)",
                    ),
                    (":local labs", "Browse trusted models.dev local model labs"),
                    (":local warm <engine>", "Warm a model and measure first-token latency"),
                    (":local scan", "Scan for running local providers"),
                    (":local models", "List all available local models"),
                    (":local test <model>", "Test tool calling with a local model"),
                    (":local info <model>", "Show detailed model information"),
                    (":local recommend", "Show recommended coding models"),
                ],
            ),
            (
                "🔍 Search & Context (local-optimized)",
                THEME["cyan"],
                [
                    (
                        ":chat",
                        "Local/BYOK direct model chat: no repo context, no tools, shows TTFT + tok/s",
                    ),
                    (":chat off", "Leave chat mode and return to the full coding harness"),
                    (":hub", "Model-search mode: just type a model name to find it (size + fit)"),
                    (":hub <name>", "One-shot model search (short for :local search)"),
                    (":chat clear", "Clear the chat-mode conversation buffer"),
                    (":context", "Show the detected context window + compaction budgets"),
                    (":context <tokens>", "Pin the context window (e.g. :context 8192 / 16k)"),
                    (":context auto", "Re-detect the loaded window from the local server"),
                    (":workspace add <path>", "Register a repo for multi-repo search"),
                    (":workspace list", "List registered search repos"),
                    (":workspace remove <path>", "Unregister a repo"),
                    (
                        '(ask: "search all repos")',
                        "grep/glob fan out across the workspace (all_repos)",
                    ),
                    (":thinking", "Show thinking-log detail (Ctrl+T cycles Normal/Verbose/Off)"),
                    (":thinking verbose", "Show full per-iteration reasoning + tool detail"),
                    (
                        "env SUPERQODE_AUTO_COMPACT=0",
                        "Disable adaptive auto-compaction (on by default)",
                    ),
                    (
                        "env SUPERQODE_VERIFY_EDITS=0",
                        "Disable post-edit diagnostics (lint/syntax after edits)",
                    ),
                    (
                        "env SUPERQODE_FORMAT_ON_EDIT=1",
                        "Auto-format files after the agent edits them",
                    ),
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
                    (":a2a", "Show A2A workflow commands"),
                    (":context", "Show current work context"),
                    (":disconnect", "Disconnect from current agent"),
                    (":home", "Go home / disconnect from all"),
                ],
            ),
            (
                "🧰 Harness & MCP",
                THEME["teal"],
                [
                    (":tools [profile]", "Show tool profile and available built-in tools"),
                    (":skills", "List local project skills from .agents/skills"),
                    (":skills search <query>", "Search loaded local skills"),
                    (":skills info <name>", "Inspect a skill's metadata and instructions"),
                    (":skills add <name>", "Create a SKILL.md template for a new skill"),
                    (":skills import <path>", "Import a local skill file or directory"),
                    (":skills doctor", "Validate local skill metadata and duplicates"),
                    (
                        ":skills optimize <name> --harness <path> --tasks <path> --live",
                        "Run GEPA skill optimization and stage the result",
                    ),
                    (
                        ":skillopt export <skill> --tasks <path> --project <dir>",
                        "Export a SkillOpt-style workspace",
                    ),
                    (
                        ":skillopt check --baseline <path> --candidate <path>",
                        "Run the bounded-edit candidate gate",
                    ),
                    (":skills enable|disable <name>", "Toggle a local skill's enabled flag"),
                    (":recipes", "List reusable local workflows from .superqode/recipes"),
                    (":recipe run <name>", "Load or run a reusable workflow recipe"),
                    (
                        ":recipe doctor <name>",
                        "Validate recipe prompt, skills, model, and attachments",
                    ),
                    (":status", "Show active provider, model, sandbox/session, branch, approval"),
                    (":doctor tui", "Show full TUI readiness dashboard"),
                    (":harness", "Open the harness overview and show active state"),
                    (":harness <spec.yaml>", "Load a HarnessSpec into the TUI"),
                    (
                        ":harness inspect",
                        "Summarize active HarnessSpec policy, tools, workflow, hooks, checks",
                    ),
                    (
                        ":harness doctor",
                        "Check active HarnessSpec readiness, blockers, and fix hints",
                    ),
                    (":harness graph [run_id]", "Show planned graph or persisted run graph"),
                    (":harness runs", "List persisted HarnessSpec runs"),
                    (
                        ":harness wizard [name] --starter <template> --output <path>",
                        "Create a HarnessSpec from wizard defaults in the TUI",
                    ),
                    (":harness replay <run_id>", "Show exact replay readiness and next commands"),
                    (":harness fork <run_id> [event]", "Fork a persisted run at an event index"),
                    (
                        ":harness evidence <run_id>",
                        "Show run evidence, changes, checks, and result receipt",
                    ),
                    (":harness events <run_id>", "Show persisted event timeline for a harness run"),
                    (
                        ":harness mine-failures --eval-result eval.json",
                        "Mine structured self-improvement failures from harness JSON",
                    ),
                    (
                        ":harness logbook show",
                        "Show the file-backed self-improvement logbook",
                    ),
                    (
                        ":harness audit-candidate --base <path> --candidate <path>",
                        "Audit protected surfaces, eval gates, and reward-hacking risk",
                    ),
                    (
                        ":harness candidates list",
                        "Show accepted and rejected self-improvement candidates",
                    ),
                    (
                        ":harness improve --spec <path> --tasks <path>",
                        "Improve a HarnessSpec from mined failures and logbook memory",
                    ),
                    (
                        ":harness optimize --spec <path> --tasks <path>",
                        "Optimize a HarnessSpec through optional metaharness",
                    ),
                    (
                        ":harness optimize-inspect <run_dir>",
                        "Inspect a completed harness optimization run",
                    ),
                    (
                        ":harness optimize-ledger <run_dir>",
                        "Show candidate ledger for a harness optimization run",
                    ),
                    (":harness templates", "List built-in HarnessSpec templates"),
                    (":harness off", "Disable the active HarnessSpec"),
                    (
                        "$ superqode mcp",
                        "Expose harnesses over MCP (stdio; --http for HTTP) for any MCP client",
                    ),
                    (":retry", "Retry the last user prompt"),
                    (":work [verbose]", "Show last run tools, files, and commands"),
                    (":copy error", "Copy the latest error to clipboard"),
                    (":session current", "Show active session status"),
                    (":session list", "Show recent local/BYOK sessions"),
                    (":mcp status", "Show configured MCP servers"),
                    (":mcp connect [server]", "Connect one or all MCP servers"),
                    (":mcp connect <url|command>", "Add and connect a new MCP server target"),
                    (":mcp add <name> <url|command>", "Save an MCP server config"),
                    (":mcp reconnect [server]", "Reconnect one or all MCP servers"),
                    (":mcp doctor [server]", "Inspect MCP config, state, and capabilities"),
                    (":mcp disconnect [server]", "Disconnect one or all MCP servers"),
                    (":mcp tools", "List tools exposed by connected MCP servers"),
                    (":mcp resources", "List resources exposed by connected MCP servers"),
                    (":mcp attach <resource>", "Stage an MCP resource for the next prompt"),
                    (":mcp prompts", "List prompts exposed by connected MCP servers"),
                    (":sandbox [backend]", "Show Docker and remote sandbox readiness"),
                    (":plugins", "List local plugin manifests"),
                    (":plugins doctor", "Validate plugin manifests and references"),
                    (":plugins add <path>", "Install a local plugin package"),
                    (":plugins enable|disable <id>", "Toggle a plugin for this project"),
                    (":memory", "Show agent memory status"),
                    (":memory providers", "List local and SpecMem memory providers"),
                    (":memory remember <text>", "Store an explicit local memory"),
                    (":memory search <query>", "Search local agent memory"),
                    (":memory search specmem <q>", "Search .specmem Agent Experience Pack files"),
                    (":memory forget <id>", "Delete a local memory"),
                    (":memory export [provider]", "Export local or SpecMem memory JSON"),
                    (":local init", "Local Agentic Coding setup: harness + smoke test"),
                    (":local build", "Guided local harness builder without live model calls"),
                    (":local packs", "List model policy packs (tuned open-model defaults)"),
                    (":local pack init", "Create a project-owned model policy pack"),
                    (":local migrate", "Plan prompt/skill migration to local models"),
                    (":local optimize", "Benchmark local model candidates and role routing"),
                    (":benchmark", "Show benchmark target readiness and CLI usage"),
                ],
            ),
            (
                "🧰 Developer Workflows",
                THEME["success"],
                [
                    (":switchboard", "Open durable session graph cockpit"),
                    (":sw switch <id>", "Switch active graph session"),
                    (":sw fork-agent <id> --agent reviewer", "Fork work to another coding agent"),
                    (":sw handoff <id> --to <target>", "Send context from one session to another"),
                    (":sw approvals", "Show cross-agent approval inbox"),
                    (":sw share-tree <id>", "Export a portable session subtree"),
                    (":factory", "Show Software Factory status for current work"),
                    (
                        ":factory routes",
                        "List private, cheap, best, review, and no-subscription routes",
                    ),
                    (
                        ":factory switch-model <provider/model>",
                        "Move a session between model providers",
                    ),
                    (":factory switch-harness <name>", "Move a session between harnesses"),
                    (":factory fork-model --model local/qwen", "Fork work to another model worker"),
                    (
                        ":factory fork-harness --harness review",
                        "Fork work to another harness worker",
                    ),
                    (":tree", "Show saved session branches and forks"),
                    (":share", "Show local/offline session sharing options"),
                    (":share create [id]", "Create a portable superqode-share-v1 artifact"),
                    (":share export [id]", "Export a saved session as Markdown or JSON"),
                    (":share import <file>", "Import a shared SuperQode session artifact"),
                    (":share list", "List local share artifacts"),
                    (":share revoke <file>", "Delete a local share artifact"),
                    (":export markdown", "Export the current TUI transcript as Markdown"),
                    (":export json", "Export the current TUI transcript as JSON"),
                    (":trust", "Show project trust status"),
                    (":trust doctor", "Show project-local plugins, MCP config, and hooks"),
                    (":trust yes|no", "Allow or block project-local plugins/MCP on this machine"),
                    (":connect codex", "Use local Codex subscription via Codex SDK"),
                    (":codex status", "Show Codex SDK/app-server/account diagnostics"),
                    (":codex model|effort", "Pick Codex model and reasoning effort"),
                    (":codex sessions|resume|fork", "Manage Codex threads"),
                    (":connect claude", "Use local Claude Code through ACP"),
                    (":claude status", "Show Claude Agent SDK status"),
                    (":claude model|permission", "Pick Claude model and permission mode"),
                    (":claude sessions|resume", "Manage Claude Agent SDK sessions"),
                    (":connect antigravity", "Use signed-in Antigravity CLI"),
                    (":antigravity status", "Check local agy CLI status"),
                    (":antigravity migrate", "Show Gemini CLI migration steps"),
                    (":connect grok", "Grok Build, xAI's own agent over ACP"),
                    (":grok api", "SuperQode harness on the same subscription (opt-in)"),
                    (":grok status|login", "Check Grok CLI readiness or show login commands"),
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
                    (":plan", "Show the current live plan/TODO state"),
                    (":plan <task>", "Ask for a plan only; native tools stay disabled"),
                    (":plan approve", "Execute the last planned request with tools enabled"),
                    (":plan edit [task]", "Edit the pending planned request"),
                    (":plan reject", "Clear the pending plan request"),
                    (":plan on|off", "Toggle persistent planning-only mode"),
                    (":history", "Show command history"),
                    (":history clear", "Clear command history"),
                    (":transcript", "Open selectable conversation transcript"),
                    (":timeline", "Open replay-style timeline"),
                    (":rewind", "Edit and resend a previous prompt"),
                    (":checkpoints", "Show undo/redo checkpoints"),
                    ("/sessions", "Browse saved local provider sessions"),
                    ("/resume <id>", "Resume a session by full id or unique prefix"),
                    ("/fork [id]", "Branch the active local provider session"),
                    ("/compact", "Enable context compaction for the active session"),
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
                    (":attach <file|url>", "Insert @file or URL reference into the prompt"),
                    (":attach list", "Show staged prompt references"),
                    (":attach remove <n>", "Remove a staged prompt reference"),
                    (":prompt <file>", "Load a prompt file into the input buffer"),
                ],
            ),
            (
                "📝 Copy & Edit",
                THEME["teal"],
                [
                    (":edit", "Open external editor (Ctrl+E)"),
                    (":copy", "Copy last response to clipboard (Ctrl+Shift+C)"),
                    (":copy transcript", "Copy the current conversation transcript"),
                    (":select", "Open selectable text view"),
                    (":select transcript", "Open selectable conversation transcript"),
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
                "⌨️ Optional Vim Mode",
                THEME["gold"],
                [
                    (":vim", "Show optional Vim mode status"),
                    (":vim on|off", "Enable or disable Vim-style helpers"),
                    (":set vim|novim", "Vim-style mode aliases"),
                    (":w", "Export the current transcript"),
                    (":e <file>", "View a file"),
                    (":ls", "List sessions"),
                    (":grep <term>", "Search the workspace"),
                    ("q:", "Show Ex command history"),
                    ("@:", "Repeat the last Ex command"),
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
                    ("Ctrl+K", "Open command palette"),
                    ("Ctrl+B", "Toggle sidebar"),
                    ("Ctrl+E", "Open external editor"),
                    ("Ctrl+L", "Clear screen"),
                    ("Ctrl+Shift+C", "Copy last response"),
                    ("Ctrl+C", "Exit / Cancel"),
                    ("Tab", "Complete commands, names, models, and paths"),
                    ("→", "Complete commands, names, models, and paths"),
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
            log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker
        else:
            # Update during navigation - clear and write but don't scroll to home
            log.auto_scroll = False
            log.clear()
            log.write(content)
            # Don't scroll to home on navigation updates to reduce flickering
            log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker

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
        pure = getattr(self, "_pure_mode", None)
        if pure is not None:
            try:
                await asyncio.wait_for(pure.aclose(), timeout=2.0)
            except Exception:  # noqa: BLE001 - exit cleanup is best-effort
                pass

        # Stop ACP client
        if self._acp_client is not None:
            try:
                if self._acp_loop_runner is not None:
                    self._acp_loop_runner.run(self._acp_client.stop())
                else:
                    await asyncio.wait_for(self._acp_client.stop(), timeout=2.0)
            except Exception:
                pass
            self._acp_client = None
            self._acp_client_key = None
        if self._acp_loop_runner is not None:
            try:
                self._acp_loop_runner.close()
            except Exception:
                pass
            self._acp_loop_runner = None

        # Cancel all pending workers (this app's own background tasks).
        # NOTE: do NOT cancel asyncio.all_tasks() here — that includes
        # Textual's own message-pump task. Killing it freezes the app so the
        # goodbye timer below never fires and exit() never runs, forcing the
        # user to kill the process. Let self.exit() tear down Textual cleanly.
        try:
            self.workers.cancel_all()
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

        provider, model = self._active_local_provider_model()

        # Cancel BYOK/local agent loop and unload/stop local generation resources.
        try:
            pure = getattr(self, "_pure_mode", None)
            if pure is not None:
                pure.cancel()
                pure.disconnect()
        except Exception:
            pass
        if provider:
            self._teardown_local_model_runtime(provider, model)

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
            self._acp_client = None
            self._acp_client_key = None
        if self._acp_loop_runner is not None:
            try:
                self._acp_loop_runner.close()
            except Exception:
                pass
            self._acp_loop_runner = None

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
            log = self.query_one("#log", ConversationLog)
            self._do_exit(log)
        except Exception:
            # Fallback: just clean up and exit immediately
            self._cleanup_on_exit()
            self.exit()

    # ========================================================================
    # Coding Agent Features: Approval, Diff, Plan, History, File Viewer
    # ========================================================================

    def _handle_copy(self, log: ConversationLog, args: str = ""):
        """Handle :copy command - copy last response, error, prompt, or transcript."""
        target = (args or "").strip().lower()
        last_error = log.get_last_error()

        if target in ("error", "err"):
            content_to_copy = last_error
            content_type = "error"
        elif target in ("response", "answer", "last"):
            content_to_copy = self._last_response or log.get_last_response()
            content_type = "response"
        elif target in ("prompt", "request", "user"):
            content_to_copy = self._last_user_message or log.get_last_message("user")
            content_type = "prompt"
        elif target in ("all", "transcript", "log"):
            content_to_copy = log.get_all_text()
            content_type = "transcript"
        elif last_error:
            content_to_copy = last_error
            content_type = "error"
        elif self._last_response or log.get_last_response():
            content_to_copy = self._last_response or log.get_last_response()
            content_type = "response"
        else:
            content_to_copy = ""
            content_type = target or "response"

        if not content_to_copy:
            log.add_info(f"No {content_type} to copy yet")
            return

        from superqode.rendering.markdown import markdown_to_plain_text

        clean_response = markdown_to_plain_text(content_to_copy)

        # Save to file first (always useful)
        output_file = Path.home() / ".superqode" / f"last_{content_type}.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(clean_response)

        content_label = {
            "error": "Error",
            "prompt": "Prompt",
            "transcript": "Transcript",
        }.get(content_type, "Response")
        if self._copy_text_to_clipboard(clean_response):
            log.add_success(f"✅ {content_label} copied to clipboard!")
            log.add_info(f"📄 Also saved to: {output_file}")
        else:
            log.add_success(f"✅ {content_label} saved to: {output_file}")
            log.add_info("💡 Use :open to view and select text")

    def _handle_open(self, log: ConversationLog):
        """Handle :open command - open last response/error in external viewer for text selection."""
        last_error = log.get_last_error()
        content = last_error or self._last_response or log.get_last_response()
        content_type = "error" if last_error else "response"
        if not content:
            log.add_info("No response or error to open yet")
            return

        from superqode.rendering.markdown import markdown_to_plain_text

        clean_response = markdown_to_plain_text(content)

        # Save to file
        output_file = Path.home() / ".superqode" / f"last_{content_type}.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(clean_response)

        try:
            import subprocess
            import sys

            if sys.platform == "darwin":
                # macOS - open in default text editor
                subprocess.Popen(["open", str(output_file)])
                log.add_success(f"✅ Opened {content_type} in default editor")
            elif sys.platform.startswith("linux"):
                # Linux - try xdg-open
                subprocess.Popen(["xdg-open", str(output_file)])
                log.add_success(f"✅ Opened {content_type} in default editor")
            else:
                # Windows
                subprocess.Popen(["notepad", str(output_file)])
                log.add_success(f"✅ Opened {content_type} in Notepad")
        except Exception as e:
            log.add_info(f"📄 {content_type.title()} saved to: {output_file}")
            log.add_info("Open this file manually to select and copy text")

    def _handle_theme(self, args: str, log: ConversationLog):
        """Handle :theme command - open the picker or apply a named theme live.

        ``:theme`` opens the interactive picker; ``:theme <name>`` applies and
        persists a theme immediately. Themes apply live (no restart needed).
        """
        theme_name = args.strip().lower() if args else ""

        if theme_name:
            if self._apply_and_persist_theme(theme_name):
                log.add_success(f"Theme changed to: {theme_name}")
            else:
                log.add_error(f"Unknown theme: {theme_name}")
                log.add_info(f"Available: {', '.join(theme_names())}")
            return

        def _on_dismissed(name: str | None) -> None:
            self.set_timer(0.1, self._ensure_input_focus)
            if name and self._apply_and_persist_theme(name):
                log.add_success(f"Theme changed to: {name}")

        self.push_screen(ThemePicker(current=self._current_theme), callback=_on_dismissed)

    def _retry_last_message(self, log: ConversationLog):
        """Retry the last user prompt in the current session."""
        if not self._last_user_message:
            log.add_info("No previous prompt to retry")
            return
        if getattr(self, "is_busy", False):
            log.add_info("Agent is still running. Cancel or wait before retrying.")
            return

        prompt = self._last_user_message
        t = Text()
        t.append("\n  ↻ ", style=f"bold {THEME['cyan']}")
        t.append("Retrying last prompt\n", style=f"bold {THEME['text']}")
        preview = prompt.replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        t.append(f"  {preview}\n", style=THEME["muted"])
        log.write(t)
        self._handle_message(prompt, log)

    def _doctor_cmd(self, args: str, log: ConversationLog):
        """Show readiness for the current or requested provider."""
        from superqode.providers.recommendations import provider_doctor_cards
        from superqode.providers.registry import PROVIDERS

        tokens = (args or "").split()
        if any(token in ("tui", "dashboard", "all", "harness") for token in tokens):
            self._show_tui_doctor_dashboard(log)
            return
        live = any(token in ("--live", "live", "smoke") for token in tokens)
        provider = " ".join(
            token for token in tokens if token not in ("--live", "live", "smoke")
        ).strip()
        if provider in ("", "current", "."):
            pure = getattr(self, "_pure_mode", None)
            pure_session = getattr(pure, "session", None)
            provider = self.current_provider or getattr(pure_session, "provider", "")

        if not provider:
            log.add_info("No provider selected. Use :connect first or run :doctor <provider>.")
            return

        if provider not in PROVIDERS:
            log.add_error(f"Unknown provider: {provider}")
            return

        if live:
            self.run_worker(self._providers_smoke_cmd(provider, log))
            return

        card = provider_doctor_cards([provider])[0]
        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Provider Doctor\n\n", style=f"bold {THEME['text']}")

        configured = "ready" if card["configured"] else "needs setup"
        status_style = THEME["success"] if card["configured"] else THEME["warning"]
        t.append(f"  Provider     ", style=THEME["muted"])
        t.append(f"{card['name']} ({card['provider']})\n", style=f"bold {THEME['cyan']}")
        t.append(f"  Status       ", style=THEME["muted"])
        t.append(f"{configured}\n", style=status_style)
        t.append(f"  Setup        ", style=THEME["muted"])
        t.append(f"{card['setup_hint']}\n", style=THEME["text"])
        labels = ", ".join(card["labels"]) or "-"
        t.append(f"  Labels       ", style=THEME["muted"])
        t.append(f"{labels}\n\n", style=THEME["dim"])

        for model in card["models"][:5]:
            t.append(f"  - {model['model']}", style=THEME["text"])
            t.append(f"  {model['price']}", style=THEME["gold"])
            t.append(f"  {model['context']} ctx", style=THEME["cyan"])
            t.append(f"  tools={model['tool_support']}\n", style=THEME["muted"])

        t.append("\n  Actions: ", style=THEME["muted"])
        t.append(":retry", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":copy error", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":providers ", style=THEME["cyan"])
        t.append(provider, style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _show_tui_doctor_dashboard(self, log: ConversationLog):
        """Show a one-screen readiness dashboard for TUI agent runs."""
        rows: list[tuple[str, str, str, str]] = []

        def add(label: str, status: str, detail: str, action: str = "") -> None:
            rows.append((label, status, detail, action))

        provider = self.current_provider or "-"
        model = self.current_model or "-"
        if self.current_provider and self.current_model:
            provider_status = "ready"
            provider_detail = f"{provider}/{model}"
        elif self.current_provider:
            provider_status = "warn"
            provider_detail = f"{provider}/-"
        else:
            provider_status = "blocked"
            provider_detail = "no provider/model connected"
        add("Provider", provider_status, provider_detail, ":connect")

        try:
            from superqode.mcp import integration

            manager = getattr(integration, "_mcp_manager", None)
            if manager is None:
                add("MCP", "warn", "manager not initialized", ":mcp connect")
            else:
                summary = manager.get_status_summary()
                connected = summary.get("connected", 0)
                total = summary.get("total_servers", 0)
                status = "ready" if connected else "warn" if total else "warn"
                detail = (
                    f"{connected}/{total} connected, "
                    f"{summary.get('total_tools', 0)} tools, "
                    f"{summary.get('total_resources', 0)} resources, "
                    f"{summary.get('total_prompts', 0)} prompts"
                )
                add("MCP", status, detail, ":mcp connect")
        except Exception as exc:
            add("MCP", "warn", f"unavailable: {exc}", ":mcp doctor")

        try:
            from superqode.skills import load_skills

            skills = load_skills(Path.cwd())
            status = "ready" if skills else "warn"
            add("Skills", status, f"{len(skills)} loaded", ":skills doctor")
        except Exception as exc:
            add("Skills", "warn", f"unavailable: {exc}", ":skills doctor")

        try:
            recipes = self._load_local_recipes()
            issue_count = sum(len(self._recipe_issues(recipe)) for recipe in recipes.values())
            status = "ready" if recipes and issue_count == 0 else "warn"
            detail = f"{len(recipes)} loaded, {issue_count} issue(s)"
            add("Recipes", status, detail, ":recipe doctor")
        except Exception as exc:
            add("Recipes", "warn", f"unavailable: {exc}", ":recipe doctor")

        refs = list(getattr(self, "_attached_refs", []))
        mcp_refs = [ref for ref in refs if ref.startswith("mcp://")]
        file_refs = [ref for ref in refs if ref.startswith("@")]
        missing_files = []
        for ref in file_refs:
            path = Path(ref[1:]).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            if not path.exists():
                missing_files.append(ref)
        attach_status = "ready" if refs and not missing_files else "warn" if refs else "ready"
        add(
            "Attachments",
            attach_status,
            f"{len(refs)} staged, {len(mcp_refs)} MCP, {len(missing_files)} missing file(s)",
            ":attach list",
        )

        try:
            branch = (
                subprocess.run(
                    ["git", "branch", "--show-current"],
                    cwd=Path.cwd(),
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=2,
                ).stdout.strip()
                or "-"
            )
            dirty = subprocess.run(
                ["git", "status", "--short"],
                cwd=Path.cwd(),
                text=True,
                capture_output=True,
                check=False,
                timeout=2,
            ).stdout.strip()
            add(
                "Git",
                "warn" if dirty else "ready",
                f"{branch}, {'dirty' if dirty else 'clean'}",
                ":diff",
            )
        except Exception:
            add("Git", "warn", "not a git workspace or git unavailable", ":files")

        add("Approval", "ready", getattr(self, "approval_mode", "ask"), ":mode")
        session_id = "-"
        if hasattr(self, "_pure_mode"):
            try:
                session_id = self._pure_mode.get_current_session_id() or "-"
            except Exception:
                session_id = "-"
        add(
            "Session", "ready" if session_id != "-" else "warn", session_id[:12], ":session current"
        )

        blocked = sum(1 for _, status, _, _ in rows if status == "blocked")
        warnings = sum(1 for _, status, _, _ in rows if status == "warn")
        overall = "Blocked" if blocked else "Warnings" if warnings else "Ready"
        overall_style = (
            THEME["error"] if blocked else THEME["warning"] if warnings else THEME["success"]
        )

        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("TUI Doctor Dashboard\n\n", style=f"bold {THEME['text']}")
        t.append("  Status      ", style=THEME["muted"])
        t.append(f"{overall}", style=f"bold {overall_style}")
        t.append(f"  ({blocked} blocked, {warnings} warning(s))\n\n", style=THEME["dim"])

        status_style = {
            "ready": THEME["success"],
            "warn": THEME["warning"],
            "blocked": THEME["error"],
        }
        for label, status, detail, action in rows:
            t.append(f"  {label:<13}", style=THEME["muted"])
            t.append(f"{status:<8}", style=f"bold {status_style.get(status, THEME['text'])}")
            t.append(f"{detail}", style=THEME["text"])
            if action:
                t.append(f"  fix: {action}", style=THEME["cyan"])
            t.append("\n")

        t.append("\n  Run readiness: ", style=THEME["muted"])
        t.append(":doctor current", style=THEME["cyan"])
        t.append(" provider, ", style=THEME["muted"])
        t.append(":mcp doctor", style=THEME["cyan"])
        t.append(" MCP, ", style=THEME["muted"])
        t.append(":recipe doctor", style=THEME["cyan"])
        t.append(" recipes\n", style=THEME["cyan"])
        self._show_command_output(log, t)

    def _work_cmd(self, args: str, log: ConversationLog):
        """Show the tools, files, and commands from the last completed run."""
        summary = getattr(self, "_last_run_summary", {}) or {}
        if not summary:
            log.add_info("No completed agent work yet.")
            return

        mode = (args or "").strip().lower()
        verbose = mode in ("verbose", "full", "details")
        files_read = summary.get("files_read", []) or []
        files_modified = summary.get("files_modified", []) or []
        tools = summary.get("tools", []) or []
        commands_run = summary.get("commands_run", []) or []
        provider = summary.get("provider") or self.current_provider or "-"
        model = summary.get("model") or self.current_model or "-"

        t = Text()
        t.append("\n  ▤ ", style=f"bold {THEME['purple']}")
        t.append("Last Work Summary\n\n", style=f"bold {THEME['text']}")
        t.append("  Target      ", style=THEME["muted"])
        t.append(f"{provider}/{model}\n", style=f"bold {THEME['cyan']}")
        t.append("  Duration    ", style=THEME["muted"])
        t.append(f"{summary.get('duration', 0):.1f}s\n", style=THEME["text"])
        t.append("  Tools       ", style=THEME["muted"])
        t.append(f"{summary.get('tool_count', len(tools))}\n", style=THEME["text"])

        if files_read:
            t.append("  Files read  ", style=THEME["muted"])
            t.append(f"{len(files_read)}\n", style=THEME["cyan"])
        if files_modified:
            t.append("  Changed     ", style=THEME["muted"])
            t.append(f"{len(files_modified)}\n", style=THEME["success"])
        if commands_run:
            t.append("  Commands    ", style=THEME["muted"])
            t.append(f"{len(commands_run)}\n", style=THEME["orange"])

        def _append_items(title: str, items: list[str], style: str, limit: int = 5):
            if not items:
                return
            visible_items = items if verbose else items[:limit]
            t.append(f"\n  {title}\n", style=f"bold {THEME['text']}")
            for item in visible_items:
                t.append("  - ", style=THEME["dim"])
                t.append(f"{item}\n", style=style)
            hidden = len(items) - len(visible_items)
            if hidden > 0:
                t.append(f"  ... {hidden} more. Use :work verbose.\n", style=THEME["muted"])

        _append_items("Files Read", files_read, THEME["cyan"])
        _append_items("Files Changed", files_modified, THEME["success"])
        _append_items("Commands", commands_run, THEME["orange"])

        if tools:
            visible_tools = tools if verbose else tools[:8]
            t.append("\n  Tools\n", style=f"bold {THEME['text']}")
            for tool in visible_tools:
                name = tool.get("name", "tool")
                detail = tool.get("path") or tool.get("command") or tool.get("query") or ""
                status = tool.get("status", "")
                duration = tool.get("duration", 0.0) or 0.0
                kind = tool.get("kind", "")
                t.append("  - ", style=THEME["dim"])
                t.append(name, style=f"bold {THEME['purple']}")
                if kind:
                    t.append(f" [{kind}]", style=THEME["dim"])
                if status:
                    status_style = THEME["success"] if status == "success" else THEME["error"]
                    if status == "running":
                        status_style = THEME["warning"]
                    t.append(" ", style=THEME["dim"])
                    t.append(status, style=status_style)
                if duration:
                    t.append(f" {duration:.2f}s", style=THEME["muted"])
                if detail:
                    t.append("  ", style=THEME["dim"])
                    t.append(str(detail), style=THEME["muted"])
                t.append("\n")
            hidden = len(tools) - len(visible_tools)
            if hidden > 0:
                t.append(f"  ... {hidden} more. Use :work verbose.\n", style=THEME["muted"])

        t.append("\n  Actions: ", style=THEME["muted"])
        t.append(":diff", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":copy response", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":retry", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _session_cmd(self, args: str, log: ConversationLog):
        """Show the current coding session or recent sessions."""
        sub = (args or "").strip().lower()
        if sub in ("", "current", "."):
            self._show_harness_status(log)
            return

        if sub in ("list", "recent"):
            if not hasattr(self, "_pure_mode"):
                log.add_info("No local/BYOK session manager is active yet.")
                return
            sessions = self._pure_mode.list_sessions()
            t = Text()
            t.append("\n  📂 ", style=f"bold {THEME['orange']}")
            t.append("Recent Sessions\n\n", style=f"bold {THEME['text']}")
            if not sessions:
                t.append("  No sessions found.\n", style=THEME["muted"])
            for item in sessions:
                t.append(f"  {item['display_id']}  ", style=f"bold {THEME['cyan']}")
                t.append(f"{item['provider']}/{item['model']}  ", style=THEME["text"])
                t.append(f"{item['message_count']} messages\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        log.add_info("Usage: :session current or :session list")

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
                prompt_input = self.query_one("#prompt-input", SelectionAwareInput)
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

    def _handle_select(self, log: ConversationLog, args: str = ""):
        """Handle :select command - show response/error/transcript in a selectable screen."""
        target = (args or "").strip().lower()
        last_error = log.get_last_error()
        if target in ("error", "err"):
            content = last_error
            content_type = "Error"
        elif target in ("response", "answer", "last"):
            content = self._last_response or log.get_last_response()
            content_type = "Response"
        elif target in ("all", "transcript", "log"):
            content = log.get_all_text()
            content_type = "Transcript"
        elif target in ("prompt", "request", "user"):
            content = self._last_user_message or log.get_last_message("user")
            content_type = "Prompt"
        else:
            content = last_error or self._last_response or log.get_last_response()
            content_type = "Error" if last_error else "Response"
        if not content:
            log.add_info(f"No {content_type.lower()} to select yet")
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

            def __init__(self, content: str, title: str):
                super().__init__()
                self._content = content
                self._title = title

            def compose(self):
                with Vertical():
                    yield Static(f"📋 Select & Copy {self._title}", classes="title")
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
                self.notify(f"{self._title} copied to clipboard!", severity="information")

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

        from superqode.rendering.markdown import markdown_to_plain_text

        clean_response = markdown_to_plain_text(content)

        def on_screen_dismissed(_):
            # Return focus to input after screen is dismissed
            self.set_timer(0.1, self._ensure_input_focus)

        screen = SelectableScreen(clean_response, content_type)
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

    def _handle_permissions(self, log: ConversationLog):
        """Show active permission/approval policy and pending decisions."""
        t = Text()
        mode = getattr(self, "approval_mode", "ask")
        mode_style = {
            "auto": THEME["success"],
            "ask": THEME["warning"],
            "deny": THEME["error"],
        }.get(mode, THEME["text"])
        t.append("\n  🔐 ", style=f"bold {THEME['warning']}")
        t.append("Permission Policy\n\n", style=f"bold {THEME['text']}")
        t.append("  Mode        ", style=THEME["muted"])
        t.append(f"{mode}\n", style=f"bold {mode_style}")
        t.append("  Behavior    ", style=THEME["muted"])
        behavior = {
            "auto": "auto-approve tool requests",
            "ask": "ask before risky tools and project edits",
            "deny": "deny permission requests",
        }.get(mode, "unknown")
        t.append(f"{behavior}\n", style=THEME["text"])

        if getattr(self, "_permission_pending", False):
            tool = getattr(self, "_pending_tool_name", "") or "tool"
            t.append("  Pending     ", style=THEME["muted"])
            t.append(f"{tool}\n", style=f"bold {THEME['warning']}")
        else:
            t.append("  Pending     none\n", style=THEME["muted"])

        manager = getattr(self, "_approval_manager", None)
        pending = manager.get_pending() if manager is not None else []
        t.append("  Approvals   ", style=THEME["muted"])
        t.append(f"{len(pending)} pending\n", style=f"bold {THEME['text']}")
        if pending:
            for index, req in enumerate(pending[:8], 1):
                target = req.file_path or req.command or req.title
                t.append(f"    {index}. ", style=THEME["dim"])
                t.append(req.title, style=f"bold {THEME['text']}")
                if target:
                    t.append(f"  {target}", style=THEME["muted"])
                t.append("\n")
            if len(pending) > 8:
                t.append(f"    ... {len(pending) - 8} more\n", style=THEME["muted"])

        always_approve = sorted(getattr(manager, "always_approve", set()) or []) if manager else []
        always_reject = sorted(getattr(manager, "always_reject", set()) or []) if manager else []
        t.append("\n  Learned rules\n", style=f"bold {THEME['cyan']}")
        t.append("    always allow  ", style=THEME["muted"])
        t.append(", ".join(always_approve) if always_approve else "none", style=THEME["text"])
        t.append("\n")
        t.append("    always reject ", style=THEME["muted"])
        t.append(", ".join(always_reject) if always_reject else "none", style=THEME["text"])
        t.append("\n")

        t.append("\n  Commands: ", style=THEME["muted"])
        t.append(":mode auto|ask|deny", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":diff", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":approve", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":reject", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        log.write(t)

    def _handle_diff(self, args: str, log: ConversationLog):
        """Handle :diff command."""
        from rich.console import Console

        console = Console()

        # Initialize diff_viewer if it doesn't exist
        if not hasattr(self, "_diff_viewer") or self._diff_viewer is None:
            self._diff_viewer = DiffViewer(console)

        arg = args.strip().lower()

        # Check for mode argument
        if arg == "split":
            self._diff_viewer.set_mode(DiffMode.SPLIT)
            log.add_info("Diff mode: split (side-by-side)")
            return
        elif arg == "unified":
            self._diff_viewer.set_mode(DiffMode.UNIFIED)
            log.add_info("Diff mode: unified")
            return
        elif arg == "compact":
            self._diff_viewer.set_mode(DiffMode.COMPACT)
            log.add_info("Diff mode: compact")
            return

        sections: list[tuple[str, str]] = []

        # Include approval-manager pending diffs first, before the git view.
        approval_manager = getattr(self, "_approval_manager", None)
        if approval_manager:
            pending = approval_manager.get_pending()
            if pending:
                pending_lines = [f"Pending approval changes ({len(pending)})", ""]
                for req in pending:
                    if req.old_content is not None and req.new_content:
                        diff = compute_diff(
                            req.old_content, req.new_content, req.file_path or "file"
                        )
                        pending_lines.append(
                            f"# {req.file_path or 'file'}  +{diff.additions} -{diff.deletions}  "
                            f"approval:{req.id}"
                        )
                        import difflib

                        pending_lines.extend(
                            difflib.unified_diff(
                                req.old_content.splitlines(),
                                req.new_content.splitlines(),
                                fromfile=f"a/{req.file_path or 'file'}",
                                tofile=f"b/{req.file_path or 'file'}",
                                lineterm="",
                            )
                        )
                        pending_lines.append("")
                sections.append(("Pending approvals", "\n".join(pending_lines).strip()))

        sections.extend(self._current_git_diff_sections())

        if not sections:
            log.add_info("No diffs found. Use :diff split or :diff unified to set mode.")
            return

        if arg in ("files", "list", "index"):
            log.write(Text(self._format_diff_file_index(sections) + "\n", style=THEME["text"]))
            return

        if arg:
            filtered = self._filter_diff_sections(sections, arg)
            if not filtered:
                log.add_info(f"No diff matched: {args.strip()}")
                return
            sections = filtered

        self._open_diff_review_overlay(sections)

    def _current_git_diff_text(self) -> str:
        """Return a review-grade current diff document.

        Kept for tests and compatibility; ``:diff`` uses the same formatter.
        """
        return self._format_diff_review(self._current_git_diff_sections())

    def _current_git_diff_sections(self) -> list[tuple[str, str]]:
        """Return the current working-tree diff, including staged and untracked files."""
        chunks: list[tuple[str, str]] = []
        commands = (
            ("Working tree", ["git", "diff", "--no-ext-diff", "--"]),
            ("Staged", ["git", "diff", "--cached", "--no-ext-diff", "--"]),
        )
        for label, command in commands:
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            except Exception:
                continue
            if result.returncode == 0 and result.stdout.strip():
                chunks.append((label, result.stdout.rstrip()))

        try:
            result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            result = None
        if result is not None and result.returncode == 0:
            untracked_chunks: list[str] = []
            for raw_path in result.stdout.splitlines():
                path = raw_path.strip()
                if not path:
                    continue
                file_path = Path(path)
                if not file_path.is_file():
                    continue
                try:
                    data = file_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if len(data) > 200_000:
                    untracked_chunks.append(
                        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
                        f"--- /dev/null\n+++ b/{path}\n@@\n"
                        f"# file is too large to preview inline ({len(data):,} bytes)"
                    )
                    continue
                added = "\n".join(f"+{line}" for line in data.splitlines())
                untracked_chunks.append(
                    f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
                    f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(data.splitlines())} @@\n"
                    f"{added}"
                )
            if untracked_chunks:
                chunks.append(("Untracked", "\n\n".join(untracked_chunks)))
        return chunks


    def _diff_review_entries(self, sections: list[tuple[str, str]]) -> list[dict[str, Any]]:
        """Return file-level diff entries for review/navigation."""
        entries: list[dict[str, Any]] = []
        for label, text in sections:
            for path, chunk in self._split_unified_diff_by_file(text):
                stats = self._diff_file_stats(chunk)
                stat = stats[0] if stats else {"path": path, "additions": 0, "deletions": 0}
                entry = {
                    "section": label,
                    "path": stat.get("path") or path,
                    "additions": int(stat.get("additions") or 0),
                    "deletions": int(stat.get("deletions") or 0),
                    "patch": chunk,
                }
                approval_id = self._diff_chunk_approval_id(chunk)
                if approval_id:
                    entry["approval_id"] = approval_id
                entries.append(entry)
        return entries

    def _diff_chunk_approval_id(self, chunk: str) -> str:
        """Extract the pending approval id marker from a synthetic pending diff."""
        for line in chunk.splitlines()[:3]:
            marker = "approval:"
            if marker in line:
                return line.split(marker, 1)[1].strip().split()[0]
        return ""


    def _approve_diff_entry(self, entry: dict[str, Any], *, always: bool = False) -> str:
        """Approve a pending approval diff entry and apply its file change."""
        approval_id = str(entry.get("approval_id") or "")
        manager = getattr(self, "_approval_manager", None)
        if not approval_id or manager is None:
            return "This diff entry is not pending approval."
        request = next((req for req in manager.requests if req.id == approval_id), None)
        if request is None:
            return "Approval request is no longer pending."
        ok = manager.approve(approval_id, always=always)
        if not ok:
            return "Approval request is no longer pending."
        if request.new_content and request.file_path:
            try:
                self._file_manager.write(request.file_path, request.new_content)
            except Exception as exc:
                return f"Approved, but failed to write {request.file_path}: {exc}"
        suffix = " (always)" if always else ""
        return f"Approved: {request.title}{suffix}"

    def _reject_diff_entry(self, entry: dict[str, Any], *, always: bool = False) -> str:
        """Reject a pending approval diff entry."""
        approval_id = str(entry.get("approval_id") or "")
        manager = getattr(self, "_approval_manager", None)
        if not approval_id or manager is None:
            return "This diff entry is not pending approval."
        request = next((req for req in manager.requests if req.id == approval_id), None)
        if request is None:
            return "Approval request is no longer pending."
        ok = manager.reject(approval_id, always=always)
        if not ok:
            return "Approval request is no longer pending."
        suffix = " (never allow)" if always else ""
        return f"Rejected: {request.title}{suffix}"

    def _open_diff_entry_file(self, entry: dict[str, Any]) -> str:
        """Open a diff entry's file in the user's editor/default app."""
        import shlex

        path = str(entry.get("path") or "").strip()
        if not path or path == "(unknown)" or path.startswith("/dev/"):
            return "No file path for this diff entry."
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path
        if not file_path.exists():
            return f"File not found: {path}"
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if editor:
            command = [*shlex.split(editor), str(file_path)]
        elif sys.platform == "darwin":
            command = ["open", str(file_path)]
        elif sys.platform.startswith("win"):
            command = ["notepad", str(file_path)]
        else:
            command = ["xdg-open", str(file_path)]
        try:
            subprocess.Popen(command)
        except Exception as exc:
            return f"Failed to open {path}: {exc}"
        return f"Opened: {path}"

    def _filter_diff_sections(
        self,
        sections: list[tuple[str, str]],
        query: str,
    ) -> list[tuple[str, str]]:
        """Filter diff sections to hunks whose file path matches query."""
        query = query.strip().lower()
        if not query:
            return sections
        out: list[tuple[str, str]] = []
        for label, text in sections:
            chunks = self._split_unified_diff_by_file(text)
            matches = [
                chunk
                for path, chunk in chunks
                if query in path.lower() or path.lower().endswith(query)
            ]
            if matches:
                out.append((label, "\n\n".join(matches)))
        return out

    def _split_unified_diff_by_file(self, diff_text: str) -> list[tuple[str, str]]:
        """Split unified diff text into ``(path, chunk)`` file entries."""
        entries: list[tuple[str, str]] = []
        current_lines: list[str] = []
        current_path = ""

        def finish() -> None:
            nonlocal current_lines, current_path
            if current_lines:
                entries.append((current_path or "(unknown)", "\n".join(current_lines).rstrip()))
            current_lines = []
            current_path = ""

        for line in diff_text.splitlines():
            if line.startswith("diff --git "):
                finish()
                parts = line.split()
                if len(parts) >= 4:
                    current_path = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                current_lines.append(line)
                continue
            if line.startswith("# ") and " +" in line and " -" in line:
                finish()
                current_path = line[2:].split("  ", 1)[0]
                current_lines.append(line)
                continue
            if not current_lines:
                continue
            current_lines.append(line)
            if line.startswith("+++ b/") and not current_path:
                current_path = line.removeprefix("+++ b/")
        finish()
        return entries

    def _diff_file_stats(self, diff_text: str) -> list[dict[str, Any]]:
        """Extract per-file path/add/delete counts from unified diff text."""
        stats: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        def finish() -> None:
            nonlocal current
            if current is not None:
                stats.append(current)
            current = None

        for line in diff_text.splitlines():
            if line.startswith("diff --git "):
                finish()
                parts = line.split()
                path = ""
                if len(parts) >= 4:
                    path = parts[3]
                    if path.startswith("b/"):
                        path = path[2:]
                current = {"path": path, "additions": 0, "deletions": 0}
                continue
            if current is None:
                if line.startswith("# ") and " +" in line and " -" in line:
                    current = {"path": line[2:].split("  ", 1)[0], "additions": 0, "deletions": 0}
                else:
                    continue
            if line.startswith("+") and not line.startswith("+++"):
                current["additions"] = int(current.get("additions") or 0) + 1
            elif line.startswith("-") and not line.startswith("---"):
                current["deletions"] = int(current.get("deletions") or 0) + 1
        finish()
        return stats

    def _open_diff_review_overlay(self, sections: list[tuple[str, str]]) -> None:
        """Open an interactive diff review overlay with file navigation."""
        from textual.binding import Binding
        from textual.containers import Horizontal, Vertical
        from textual.screen import ModalScreen
        from textual.widgets import Button, Static, TextArea

        entries = self._diff_review_entries(sections)
        full_content = self._format_diff_review(sections)
        format_entry = self._format_diff_entry_review
        approve_entry = self._approve_diff_entry
        reject_entry = self._reject_diff_entry
        open_entry = self._open_diff_entry_file

        class DiffReviewScreen(ModalScreen):
            BINDINGS = [
                Binding("escape", "dismiss", "Close"),
                Binding("n", "next_file", "Next file"),
                Binding("p", "previous_file", "Previous file"),
                Binding("a", "show_all", "All files"),
                Binding("o", "open_current_file", "Open file"),
                Binding("x", "copy_current_patch", "Copy patch"),
                Binding("y", "approve_current", "Approve"),
                Binding("r", "reject_current", "Reject"),
                Binding("ctrl+c", "copy_current", "Copy"),
            ]

            CSS = """
            DiffReviewScreen {
                align: center middle;
            }

            DiffReviewScreen > Vertical {
                width: 94%;
                height: 92%;
                background: #0a0a0a;
                border: round #7c3aed;
                padding: 1;
            }

            DiffReviewScreen .title {
                text-align: center;
                color: #a855f7;
                text-style: bold;
                height: 2;
            }

            DiffReviewScreen .status {
                color: #67e8f9;
                height: 1;
                margin-bottom: 1;
            }

            DiffReviewScreen TextArea {
                height: 1fr;
                background: #000000;
                border: solid #1a1a1a;
            }

            DiffReviewScreen .hints {
                text-align: center;
                color: #71717a;
                height: 2;
            }

            DiffReviewScreen .buttons {
                height: 3;
                align: center middle;
            }
            """

            def __init__(self):
                super().__init__()
                self._content = full_content
                self._title = "Diff Review"
                self._entries = entries
                self._index = -1
                self._current_text = full_content

            def compose(self):
                with Vertical():
                    yield Static("🧾 Diff Review", classes="title")
                    yield Static(self._status_text(), id="diff-status", classes="status")
                    yield TextArea(self._current_text, id="text-area", read_only=True)
                    yield Static(
                        "n/p file • o open • x copy patch • y/r pending approval • a all • Esc close",
                        classes="hints",
                    )
                    with Horizontal(classes="buttons"):
                        yield Button("Prev", id="prev-file", variant="default")
                        yield Button("Next", id="next-file", variant="default")
                        yield Button("All Files", id="show-all", variant="primary")
                        yield Button("Open", id="open-current", variant="default")
                        yield Button("Copy Patch", id="copy-patch", variant="default")
                        yield Button("Approve", id="approve-current", variant="success")
                        yield Button("Reject", id="reject-current", variant="error")
                        yield Button("Copy View", id="copy-current", variant="default")
                        yield Button("Close", id="close-btn", variant="default")

            def on_button_pressed(self, event):
                if event.button.id == "prev-file":
                    self.action_previous_file()
                elif event.button.id == "next-file":
                    self.action_next_file()
                elif event.button.id == "show-all":
                    self.action_show_all()
                elif event.button.id == "open-current":
                    self.action_open_current_file()
                elif event.button.id == "copy-patch":
                    self.action_copy_current_patch()
                elif event.button.id == "approve-current":
                    self.action_approve_current()
                elif event.button.id == "reject-current":
                    self.action_reject_current()
                elif event.button.id == "copy-current":
                    self.action_copy_current()
                elif event.button.id == "close-btn":
                    self.dismiss()

            def action_next_file(self):
                if not self._entries:
                    return
                self._index = 0 if self._index < 0 else (self._index + 1) % len(self._entries)
                self._refresh_view()

            def action_previous_file(self):
                if not self._entries:
                    return
                self._index = (
                    len(self._entries) - 1
                    if self._index < 0
                    else (self._index - 1) % len(self._entries)
                )
                self._refresh_view()

            def action_show_all(self):
                self._index = -1
                self._refresh_view()

            def action_open_current_file(self):
                entry = self._selected_entry()
                if entry is None:
                    self._safe_notify("Select a file diff first", severity="warning")
                    return
                message = open_entry(entry)
                self._safe_notify(message, severity="information")

            def action_copy_current_patch(self):
                entry = self._selected_entry()
                if entry is None:
                    self._safe_notify("Select a file diff first", severity="warning")
                    return
                self._copy_to_clipboard(str(entry.get("patch") or ""))
                self._safe_notify("File patch copied", severity="information")

            def action_approve_current(self):
                entry = self._current_pending_entry()
                if entry is None:
                    self._safe_notify("Select a pending approval diff first", severity="warning")
                    return
                message = approve_entry(entry)
                self._safe_notify(message, severity="information")
                self._remove_current_entry_if_decided(entry)

            def action_reject_current(self):
                entry = self._current_pending_entry()
                if entry is None:
                    self._safe_notify("Select a pending approval diff first", severity="warning")
                    return
                message = reject_entry(entry)
                self._safe_notify(message, severity="warning")
                self._remove_current_entry_if_decided(entry)

            def action_copy_current(self):
                self._copy_to_clipboard(self._current_text)
                self._safe_notify("Diff copied", severity="information")

            def _safe_notify(self, message: str, *, severity: str = "information") -> None:
                try:
                    self.notify(message, severity=severity)
                except Exception:
                    pass

            def _selected_entry(self) -> dict[str, Any] | None:
                if self._index < 0 or self._index >= len(self._entries):
                    return None
                return self._entries[self._index]

            def _current_pending_entry(self) -> dict[str, Any] | None:
                entry = self._selected_entry()
                if entry is None:
                    return None
                if not entry.get("approval_id"):
                    return None
                return entry

            def _remove_current_entry_if_decided(self, entry: dict[str, Any]) -> None:
                if entry.get("approval_id") and entry in self._entries:
                    self._entries.remove(entry)
                    if not self._entries:
                        self._index = -1
                    elif self._index >= len(self._entries):
                        self._index = len(self._entries) - 1
                    self._refresh_view()

            def _refresh_view(self):
                if self._index < 0:
                    self._current_text = self._content
                else:
                    self._current_text = format_entry(
                        self._entries[self._index],
                        index=self._index,
                        total=len(self._entries),
                    )
                try:
                    self.query_one("#text-area", TextArea).load_text(self._current_text)
                    self.query_one("#diff-status", Static).update(self._status_text())
                except Exception:
                    pass

            def _status_text(self) -> str:
                if not self._entries:
                    return "No file entries"
                if self._index < 0:
                    return f"All files ({len(self._entries)})"
                entry = self._entries[self._index]
                return (
                    f"{self._index + 1}/{len(self._entries)}  "
                    f"[{entry.get('section')}] {entry.get('path')}  "
                    f"+{entry.get('additions')} -{entry.get('deletions')}"
                )

            def _copy_to_clipboard(self, text: str) -> None:
                try:
                    import pyperclip

                    pyperclip.copy(text)
                except Exception:
                    try:
                        self.app.copy_to_clipboard(text)
                    except Exception:
                        pass

        def on_screen_dismissed(_result=None):
            self._ensure_input_focus()

        self.push_screen(DiffReviewScreen(), callback=on_screen_dismissed)

    def _open_text_overlay(self, content: str, title: str) -> None:
        """Open a selectable text overlay for diffs/transcripts/large text."""
        from textual.screen import ModalScreen
        from textual.widgets import TextArea, Static, Button
        from textual.containers import Vertical, Horizontal
        from textual.binding import Binding

        class TextOverlayScreen(ModalScreen):
            BINDINGS = [
                Binding("escape", "dismiss", "Close"),
                Binding("ctrl+c", "copy_selection", "Copy"),
            ]

            CSS = """
            TextOverlayScreen {
                align: center middle;
            }

            TextOverlayScreen > Vertical {
                width: 92%;
                height: 90%;
                background: #0a0a0a;
                border: round #7c3aed;
                padding: 1;
            }

            TextOverlayScreen .title {
                text-align: center;
                color: #a855f7;
                text-style: bold;
                height: 2;
            }

            TextOverlayScreen TextArea {
                height: 1fr;
                background: #000000;
                border: solid #1a1a1a;
            }

            TextOverlayScreen .hints {
                text-align: center;
                color: #71717a;
                height: 2;
            }

            TextOverlayScreen .buttons {
                height: 3;
                align: center middle;
            }
            """

            def __init__(self, overlay_content: str, overlay_title: str):
                super().__init__()
                self._content = overlay_content
                self._title = overlay_title

            def compose(self):
                with Vertical():
                    yield Static(f"🧾 {self._title}", classes="title")
                    yield TextArea(self._content, id="text-area", read_only=True)
                    yield Static(
                        "Scroll to inspect • select text with mouse • Ctrl+C copy • Esc close",
                        classes="hints",
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
                try:
                    selected = self.query_one("#text-area", TextArea).selected_text
                    if selected:
                        self._copy_to_clipboard(selected)
                        self.notify("Selection copied", severity="information")
                        return
                except Exception:
                    pass
                self._copy_all()

            def _copy_all(self):
                self._copy_to_clipboard(self._content)
                self.notify(f"{self._title} copied", severity="information")

            def _copy_to_clipboard(self, text: str):
                try:
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

        def on_screen_dismissed(_):
            self.set_timer(0.1, self._ensure_input_focus)

        self.push_screen(TextOverlayScreen(content, title), callback=on_screen_dismissed)

    def _handle_plan(self, args: str, log: ConversationLog):
        """Handle :plan command."""
        arg_text = args.strip()
        arg_lower = arg_text.lower()

        if arg_lower in ("on", "enable", "enabled"):
            self._plan_mode_enabled = True
            self._refresh_plan_status_badge()
            log.add_success(
                "Plan mode enabled. New prompts will analyze only and will not execute native tools."
            )
            log.add_info(
                "Use :plan off to return to execution mode, or :plan run to execute the last planned request."
            )
            return

        if arg_lower in ("off", "disable", "disabled"):
            self._plan_mode_enabled = False
            self._refresh_plan_status_badge()
            log.add_success("Plan mode disabled. New prompts can execute tools again.")
            return

        if arg_lower == "review":
            self._render_plan_review(log)
            return

        if arg_lower == "edit" or arg_lower.startswith("edit "):
            pending = getattr(self, "_pending_plan_request", "").strip()
            replacement = arg_text[4:].strip() if arg_lower.startswith("edit ") else ""
            if replacement:
                self._pending_plan_request = replacement
                self._pending_plan_status = "pending"
                self._refresh_plan_status_badge()
                log.add_success(
                    "Plan request updated. Use :plan to review or :plan approve to run."
                )
                self._render_plan_review(log)
                return
            if not pending:
                log.add_info("No planned request is available. Use :plan <task> first.")
                return
            try:
                input_widget = self.query_one("#prompt-input", SelectionAwareInput)
                input_widget.value = f":plan {pending}"
                input_widget.focus()
                log.add_info("Loaded the planned request into the prompt for editing.")
            except Exception:
                log.add_info(f"Edit planned request with: :plan edit {pending}")
            return

        if arg_lower in ("run", "execute", "apply", "approve"):
            pending = getattr(self, "_pending_plan_request", "").strip()
            if not pending:
                log.add_info("No planned request is available. Use :plan <task> first.")
                return
            if getattr(self, "is_busy", False):
                log.add_info("Agent is already running. Wait for it to finish, then use :plan run.")
                return
            self._force_execute_once = True
            self._pending_plan_status = "approved"
            self._refresh_plan_status_badge()
            log.add_info("Executing the last planned request with tools enabled...")
            self._handle_message(pending, log)
            return

        if arg_lower in ("clear", "reset", "reject", "cancel"):
            self._plan_manager.clear()
            self._pending_plan_request = ""
            self._pending_plan_status = "rejected" if arg_lower in ("reject", "cancel") else ""
            self._force_plan_once = False
            self._force_execute_once = False
            self._refresh_plan_status_badge()
            log.add_success("Plan cleared")
            return

        if arg_lower in ("status", ""):
            status = "ON" if getattr(self, "_plan_mode_enabled", False) else "OFF"
            pending = getattr(self, "_pending_plan_request", "")
            log.add_info(f"Plan mode: {status}")
            if pending:
                log.add_info(f"Last planned request: {pending[:160]}")

        if arg_text and arg_lower not in ("status",):
            if getattr(self, "is_busy", False):
                log.add_info("Agent is already running. Wait for it to finish, then plan the task.")
                return
            self._force_plan_once = True
            self._pending_plan_request = arg_text
            self._pending_plan_status = "pending"
            self._refresh_plan_status_badge()
            log.add_info("Planning only. No native tools will be executed.")
            self._handle_message(arg_text, log)
            return

        self._render_plan_review(log)


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
