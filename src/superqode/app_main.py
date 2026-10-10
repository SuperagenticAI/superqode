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

import os
import re
import shutil  # noqa: F401  (patched as superqode.app_main.shutil by tests)
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static
from textual.binding import Binding
from textual.reactive import reactive
from textual import events
from textual.timer import Timer


from superqode.app.recipes import PromptCompletionCandidate, LocalRecipe  # noqa: F401


# Import from modular app package
from superqode.app.css import APP_CSS
from superqode.theming.css import theme_css
from superqode.app.models import AgentInfo
from superqode.app.prompt_stack import PromptSpec, PromptStack  # noqa: F401
from superqode.app.suggester import CommandSuggester
from superqode.app.widgets import (
    ColorfulStatusBar,
    TopScanningLine,
    BottomScanningLine,
    StreamingThinkingIndicator,
    ModeBadge,
    HintsBar,
    ConversationLog,
    NewOutputIndicator,
)
from superqode.widgets.command_palette import CommandPalette
from superqode.app.theme_bridge import (
    apply_theme as _apply_theme_palette,
    load_saved_theme,
)

# SuperQode modules
from superqode.plan import (
    PlanManager,
)
from superqode.history import HistoryManager
from superqode.sidebar import (
    CollapsibleSidebar,
)

# SuperQode Enhanced Display (unique design system)

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
from superqode.app.mixins.clickable_commands import ClickableCommandMixin
from superqode.app.mixins.pipy_commands import PiPyCommandMixin
from superqode.app.mixins.rlm_commands import RLMCommandMixin


from superqode.app.mixins.formatting import FormattingMixin


from superqode.app.mixins.model_catalog import ModelCatalogMixin


from superqode.app.mixins.local_models import LocalModelsMixin


from superqode.app.mixins.codex import CodexMixin


from superqode.app.mixins.dialogs import DialogsMixin


from superqode.app.mixins.commands_impl import CommandImplMixin


from superqode.app.mixins.agent_run import AgentRunMixin


from superqode.app.mixins.slash_commands import SlashCommandMixin


from superqode.app.mixins.helpers import HelpersMixin


from superqode.app.mixins.feedback import FeedbackMixin


from superqode.app.mixins.build_harness import BuildHarnessMixin


from superqode.app.mixins.explore import ExploreMixin


from superqode.app.mixins.tour import TourMixin


from superqode.app.mixins.harness_hub import HarnessHubMixin
from superqode.app.mixins.supervision import SupervisionMixin
from superqode.app.mixins.composer_blocks import ComposerBlocksMixin


class SuperQodeApp(
    ComposerBlocksMixin,
    SupervisionMixin,
    HarnessHubMixin,
    ExploreMixin,
    BuildHarnessMixin,
    TourMixin,
    FeedbackMixin,
    HelpersMixin,
    SlashCommandMixin,
    AgentRunMixin,
    CommandImplMixin,
    DialogsMixin,
    CodexMixin,
    LocalModelsMixin,
    ModelCatalogMixin,
    FormattingMixin,
    PickerNavigationMixin,
    PiPyCommandMixin,
    RLMCommandMixin,
    ClickableCommandMixin,
    CompletionMixin,
    MiscActionsMixin,
    EventHandlerMixin,
    ConnectMixin,
    McpMixin,
    HuggingFaceMixin,
    SwitchboardMixin,
    FactoryMixin,
    SidebarMixin,
    App,
):
    CSS = theme_css(APP_CSS)
    TITLE = "SuperQode"

    def get_default_screen(self):
        """Make the composer ready on activation, before delayed focus retries."""
        screen = super().get_default_screen()
        screen.AUTO_FOCUS = "#prompt-input"
        return screen

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Interrupt", show=True),
        Binding("ctrl+l", "clear_screen", "Clear", show=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=True),
        Binding("ctrl+t", "toggle_thinking", "Toggle Logs", show=True),
        Binding("ctrl+k", "command_palette", "Commands", show=True, priority=True),
        Binding("ctrl+o", "run_overview", "Runs", show=False, priority=True),
        Binding("ctrl+r", "rewind", "Rewind", show=True),
        Binding("ctrl+f", "search_transcript", "Search", show=True, priority=True),
        Binding("f1", "show_help", "Help", show=True),
        Binding("escape", "smart_cancel", "Cancel", show=True),
        Binding("pageup", "scroll_log_page_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_log_page_down", "Scroll Down", show=False),
        Binding("ctrl+home", "scroll_log_home", "Top", show=False),
        Binding("ctrl+end", "scroll_log_end", "Bottom", show=False),
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
        Binding("ctrl+y", "copy_code", "Yank Code", show=False),
        Binding("ctrl+shift+r", "search_history", "Search History", show=False),
        # External editor
        Binding("ctrl+e", "open_editor", "Editor", show=False),
        # Reword and resend the previous prompt
        Binding("ctrl+p", "edit_last_message", "Edit last message", show=False, priority=True),
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
    _connect_menu = "root"  # Which :connect screen is showing (root | subscriptions)
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
    _awaiting_agent_question = reactive(False)  # Agent needs user input
    _permission_pending = reactive(False)
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
    _force_plan_once: bool = False  # Run the next native prompt as plan-only
    _force_execute_once: bool = False  # Run the next prompt even if plan mode is enabled
    _pending_plan_request: str = ""  # Last planned request available for approval/execution
    _pending_plan_status: str = ""  # pending / approved / rejected
    _pending_plan_content: str = ""  # Exact model-authored plan awaiting review
    _approved_plan_for_next_run: str = ""  # One-shot execution context after approval

    def __init__(
        self,
        *,
        resume: str | None = None,
        fork_from: str | None = None,
        approval_mode: str | None = None,
        interaction_mode: str | None = None,
        theme_selection: str | None = None,
    ):
        from superqode.theming.terminal import terminal_driver

        super().__init__(driver_class=terminal_driver())
        self._startup_resume = resume or fork_from or ""
        self._startup_fork = bool(fork_from)
        self._startup_interaction_mode = interaction_mode
        if approval_mode is not None:
            self.approval_mode = approval_mode
        # Modal prompts declare their Enter/text/Esc/navigation behavior once
        # here instead of being hand-registered across five dispatch sites.
        self._prompts = PromptStack()
        # Apply the persisted accent theme before any widget renders so the
        # whole UI paints in the chosen palette from the first frame.
        self._current_theme = load_saved_theme()
        if theme_selection is not None:
            from superqode.app.theme_bridge import load_project_theme, resolve_selection

            if (
                not resolve_selection(theme_selection)
                and Path(theme_selection).expanduser().is_file()
            ):
                theme_selection = load_project_theme(Path(theme_selection))
            if not resolve_selection(theme_selection):
                raise ValueError(f"Unknown theme: {theme_selection}")
            self._current_theme = theme_selection
        _apply_theme_palette(self._current_theme)
        from superqode.theming.css import ThemeStylesheet
        from superqode.app.theme_bridge import textual_theme

        self.stylesheet = ThemeStylesheet(variables=self.get_css_variables())
        self.register_theme(textual_theme())
        self.theme = "superqode-live"
        self._theme_file_signature = None
        self._theme_save_error = None
        self._terminal_palette = {}
        self._terminal_theme_refresh_timer = None
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
        self._staged_images = {}
        self._current_images = []
        self._prompt_completion_candidates: list[PromptCompletionCandidate] = []
        self._prompt_completion_index = 0
        self._prompt_completion_visible = False
        self._history_manager = HistoryManager()
        self._plan_manager = PlanManager()
        self._vim_experience_enabled = self._load_vim_preference()
        self._vim_input_mode = "normal" if self._vim_experience_enabled else "insert"
        self._vim_pending_key = ""
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
                from superqode.widgets.run_overview import SupervisionBar

                yield SupervisionBar(id="supervision-bar")
                yield Static("", id="install-progress")

                # Prompt area stays usable while an agent is working.
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
                    yield Static("", id="attachment-bar")
                    yield Static("", id="dictation-guide")
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
                    yield NewOutputIndicator("", id="new-output-indicator")

                # Pinned, auto-updating plan/todo checklist (from todo_write).
                yield Static("", id="plan-review-panel")
                yield Static("", id="todo-panel")

                # Compact active tool strip, separate from the thinking indicator.
                yield Static("", id="active-tools")

                # Thinking indicator with changing text at bottom (shown when agent is thinking)
                yield StreamingThinkingIndicator(id="streaming-thinking")

                # Branded bottom sweep: active only while the agent is working.
                yield BottomScanningLine(id="thinking-wave-bottom")

        yield CommandPalette(commands=self._build_palette_commands(), id="command-palette")

    def get_css_variables(self):
        from superqode.app.theme_bridge import css_variables

        return {**super().get_css_variables(), **css_variables()}

    def _refresh_theme_view(self):
        if not self.is_running:
            return  # Shutdown removes children before all palette timers drain.
        from superqode.app.theme_bridge import textual_theme

        self.register_theme(textual_theme())
        self.mutate_reactive(App.theme)
        self.refresh_css(animate=False)
        for screen in self.screen_stack:
            # App.query only visits the default screen. Refresh mounted
            # overlays too, including the isolated system/auto preview.
            for widget in (screen, *screen.query("*")):
                refresh = getattr(widget, "refresh_theme_colors", None)
                if callable(refresh):
                    refresh()
                widget.refresh(repaint=True)

    def _query_terminal_theme(self):
        if self._current_theme not in {"system", "auto"} and "/" not in self._current_theme:
            return
        from superqode.theming.terminal import QUERY

        driver = self._driver
        if driver is not None and type(driver).__name__ == "ThemeLinuxDriver":
            driver.write(QUERY)
            driver.flush()

    def on_terminal_color_reply(self, message):
        from superqode.app.theme_bridge import set_terminal_colors

        if all(self._terminal_palette.get(key) == value for key, value in message.colors.items()):
            return
        self._terminal_palette.update(message.colors)
        set_terminal_colors(message.colors)
        if self._terminal_theme_refresh_timer is None:
            self._terminal_theme_refresh_timer = self.set_timer(0.1, self._finish_terminal_theme)

    def _finish_terminal_theme(self):
        self._terminal_theme_refresh_timer = None
        if self._current_theme in {"system", "auto"} or "/" in self._current_theme:
            if _apply_theme_palette(self._current_theme):
                self._refresh_theme_view()

    def _poll_theme_file(self):
        """Reload a complete changed user file, retaining the last working palette."""
        if not self.is_running:
            return
        from superqode import design_system as ds
        from superqode.app.theme_bridge import apply_theme, theme_directory
        from superqode.theming import load_theme_file, ThemeError

        active = ds.get_theme()
        path = Path(active.source)
        if not path.is_absolute() or path.parent.resolve() != theme_directory().resolve():
            return
        try:
            stat = path.stat()
            signature = (str(path), stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = (str(path), "missing")
        if signature == self._theme_file_signature:
            return
        self._theme_file_signature = signature
        try:
            updated = load_theme_file(path)
            if updated.name != active.name:
                raise ThemeError(
                    "Active theme was renamed; use :theme reload to discover its new name"
                )
            updated.source = active.source
            ds.THEMES[updated.name] = updated
        except ThemeError as exc:
            self.notify(str(exc)[:300], title="Theme retained", severity="warning", markup=False)
            return
        if apply_theme(self._current_theme):
            self._refresh_theme_view()

    def on_mount(self):
        from superqode.app.herdr import start

        start(self)
        self.set_interval(0.5, self._poll_theme_file)
        self.set_interval(3, self._query_terminal_theme)
        self.call_after_refresh(self._query_terminal_theme)
        from superqode.app.theme_bridge import theme_errors

        for error in theme_errors():
            self.notify(error[:300], title="Theme file", severity="warning", markup=False)
        self.set_interval(1, self._refresh_supervision_bar)
        self.set_interval(3, self._refresh_work_supervision_cache)
        self.run_worker(self._refresh_work_supervision_cache())
        self.call_after_refresh(self._refresh_supervision_bar)
        # Focus input after a short delay to ensure widgets are fully ready
        self.set_timer(0.1, self._focus_input_on_ready)
        self._set_prompt_border_title()
        self._refresh_harness_panel()
        self._sync_vim_state()
        self._load_welcome()
        self._init_draft_recovery()
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
        # Catalogs refresh once per launch; manual refresh stays available.
        # LiteLLM loads when a selected local/BYOK connection needs it.
        self.set_timer(0.5, self._start_models_dev_refresh)
        self.set_timer(0.5, self._start_acp_registry_refresh)
        self.set_timer(1.2, self._report_catalog_freshness)
        if os.getenv("SUPERQODE_STARTUP_HEALTH", "").strip().lower() in ("1", "true", "yes"):
            self._run_startup_health_check()
        # Auto-connect a connection profile if requested via --connect.
        if self._startup_resume:
            self.set_timer(0.1, self._run_startup_session)
        elif self._startup_interaction_mode:
            self._apply_interaction_mode(
                self._startup_interaction_mode, self.query_one("#log", ConversationLog)
            )
        if not self._startup_resume and os.getenv("SUPERQODE_CONNECT", "").strip():
            self.set_timer(1.0, self._run_startup_connect)

    def _run_startup_session(self) -> None:
        from superqode.app.herdr import sync

        log = self.query_one("#log", ConversationLog)
        if not self._handle_resume_session(self._startup_resume, log):
            self._herdr_restore_error = "Session restore failed"
            sync(self)
            return
        self._herdr_restore_error = ""
        if self._startup_fork:
            self._handle_fork_session("", log)
        if self._startup_interaction_mode:
            self._apply_interaction_mode(self._startup_interaction_mode, log)
        sync(self)

    def watch_approval_mode(self, mode: str) -> None:
        from superqode.app.herdr import sync

        sync(self)

    def watch__permission_pending(self, pending: bool) -> None:
        from superqode.app.herdr import sync

        sync(self)

    def watch__awaiting_agent_question(self, pending: bool) -> None:
        from superqode.app.herdr import sync

        sync(self)

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
        "interrupt",
        "undo_action",
        "redo_action",
        "toggle_split_view",
        "create_checkpoint",
        "rewind",
    }

    def _sidebar_has_focus(self) -> bool:
        if not self.screen_stack or not self.sidebar_visible:
            return False
        focused = self.focused
        return bool(
            self.sidebar_visible
            and focused is not None
            and any(isinstance(node, CollapsibleSidebar) for node in focused.ancestors_with_self)
        )

    def _focus_input_on_ready(self):
        """Focus the input box once widgets are ready."""
        if len(self.screen_stack) != 1:
            return
        if self.query("CommandPalette.show-palette"):
            return
        # Opening the sidebar requests focus after layout. The startup timer
        # can run before that request settles; respect the visible navigation
        # intent instead of racing it back to the composer.
        if self.sidebar_visible:
            return
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
        if len(self.screen_stack) != 1:
            return
        if self.query("CommandPalette.show-palette"):
            return
        if self._sidebar_has_focus():
            return
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
        try:
            sidebar = self.query_one("#sidebar")
            preferred = getattr(
                self,
                "_preferred_sidebar_width",
                getattr(sidebar, "_width", 34),
            )
            self._set_sidebar_width(preferred, event.size.width)
        except Exception:
            pass  # Resize may arrive before compose finishes.
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
            lock = getattr(log, "lock_viewport", None)
            if callable(lock):
                lock()
            else:
                log.auto_scroll = False
            log.scroll_page_up(animate=False)

    def action_scroll_log_page_down(self) -> None:
        """Scroll the conversation log down while keeping input focused."""
        log = self._conversation_log()
        if log is not None:
            lock = getattr(log, "lock_viewport", None)
            if callable(lock):
                lock()
            else:
                log.auto_scroll = False
            log.scroll_page_down(animate=False)
            settle = getattr(log, "resume_follow_if_at_end", None)
            if callable(settle):
                try:
                    log.call_after_refresh(settle)
                except Exception:
                    settle()

    def action_scroll_log_home(self) -> None:
        """Scroll the conversation log to the top."""
        log = self._conversation_log()
        if log is not None:
            lock = getattr(log, "lock_viewport", None)
            if callable(lock):
                lock()
            else:
                log.auto_scroll = False
            log.scroll_home(animate=False)

    def action_scroll_log_end(self) -> None:
        """Scroll the conversation log to the bottom and resume follow mode."""
        log = self._conversation_log()
        if log is not None:
            resume = getattr(log, "resume_follow", None)
            if callable(resume):
                resume()
            else:
                log.scroll_end(animate=False)
                log.auto_scroll = True

    def _typed_picker_digits(self) -> str:
        """Return the digits waiting in the prompt, if that is all it holds.

        A picker's Enter normally confirms the highlighted row. When the user
        has typed a row number instead, that number is the choice, and the
        submit path is what knows how to resolve it.
        """
        try:
            from superqode.app.inputs import SelectionAwareInput

            typed = (self.query_one("#prompt-input", SelectionAwareInput).value or "").strip()
        except Exception:  # noqa: BLE001 - key handling must never raise
            return ""
        return typed if typed.isdigit() else ""

    def on_key(self, event: events.Key) -> None:
        """Handle key events globally - intercept arrow keys during selection modes."""
        # Inline permission prompt: while a permission decision is pending,
        # y/n/a resolve it and escape cancels. Intercepted before the Input
        # widget so the keystroke never lands in the prompt buffer.
        if (
            len(self.screen_stack) == 1
            and getattr(self, "_permission_pending", False)
            and not getattr(self, "_awaiting_agent_question", False)
        ):
            if event.key in ("y", "n", "a", "escape"):
                event.stop()
                mapping = {"y": "y", "n": "n", "a": "a", "escape": "n"}
                self._handle_permission_input(mapping[event.key])
                self.set_timer(0.05, self._ensure_input_focus)
                return

        # Plan decisions use Alt shortcuts so ordinary composer typing remains
        # untouched. They are active only after a model-authored plan exists.
        if (
            event.key in ("alt+a", "alt+e", "alt+r")
            and getattr(self, "_pending_plan_status", "") == "pending"
            and bool(getattr(self, "_pending_plan_content", "").strip())
        ):
            event.stop()
            action = {"alt+a": "approve", "alt+e": "edit", "alt+r": "reject"}[event.key]
            self._handle_plan(action, self.query_one("#log", ConversationLog))
            return

        # Registry-driven setup cards must remain keyboard-operable even when
        # a prior mouse click or screen transition left focus outside the
        # composer. SelectionAwareInput owns these keys while focused; this is
        # the app-level fallback for every other widget.
        prompts = getattr(self, "_prompts", None)
        active_prompt = getattr(prompts, "active", None) if prompts is not None else None
        if active_prompt is not None and active_prompt.kind == "picker":
            if event.key in {"up", "down"} and prompts.navigate(-1 if event.key == "up" else 1):
                event.stop()
                event.prevent_default()
                self.set_timer(0.05, self._ensure_input_focus)
                return
            if event.key == "enter" and prompts.select():
                event.stop()
                event.prevent_default()
                self.set_timer(0.05, self._ensure_input_focus)
                return

        # When focus is outside the prompt, key B and Left Arrow still
        # mirror the visible browser-style Back control. Prompt focus handles
        # these itself so text cursor movement continues to work whenever text is present.
        token = (getattr(event, "character", None) or event.key or "").lower()
        if token in {"b", "left"} or event.key in {"b", "B", "left"}:
            try:
                prompt_value = self.query_one("#prompt-input", SelectionAwareInput).value
            except Exception:  # noqa: BLE001 - keyboard navigation must remain safe
                prompt_value = ""
            if self._navigate_back_from_keyboard(prompt_value):
                event.stop()
                return

        # Modal navigation also works when focus is in the sidebar or another
        # non-prompt widget. The prompt widget handles and stops the same event
        # before it bubbles here when it owns focus.
        if self._handle_vim_key(event):
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

            elif getattr(self, "_awaiting_explore", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_explore_up()
                elif event.key == "down":
                    self.action_navigate_explore_down()
                elif event.key == "enter":
                    self.action_toggle_explore_row()
                elif event.key == "right":
                    self.action_run_explore_command()

            elif getattr(self, "_awaiting_harness_import", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_harness_import_up()
                elif event.key == "down":
                    self.action_navigate_harness_import_down()
                elif event.key == "enter":
                    self.action_select_harness_import()

            elif getattr(self, "_awaiting_harness_preset", False):
                event.stop()
                handled = True
                if event.key == "up":
                    self.action_navigate_harness_preset_up()
                elif event.key == "down":
                    self.action_navigate_harness_preset_down()
                elif event.key == "enter":
                    self.action_select_harness_preset()

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
                # A typed model number must win over the highlighted row. This
                # branch mirrors the prompt-input dispatch, so it needs the same
                # escape: without it this handler ran first, consumed Enter, and
                # selected whatever was highlighted while the user watched their
                # typed number be ignored.
                if event.key == "enter" and self._typed_picker_digits():
                    pass  # fall through to the normal submit path
                else:
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
        if getattr(self, "_install_in_progress", False):
            if self._cancel_install():
                self.query_one("#log", ConversationLog).add_info("Stopping the installer…")
            return
        if getattr(self, "_awaiting_agent_question", False):
            self.action_cancel_agent()
            return
        # A registry-driven prompt is always the topmost modal thing on screen,
        # so it cancels first. Going through the stack runs the prompt's own
        # on_cancel hook, which is what returns to the picker underneath it.
        if getattr(self, "_prompts", None) is not None and self._prompts.active is not None:
            self._prompts.cancel()
            return

        # The visible Back control and Escape should restore the same screen.
        if self._in_selection_mode() and self._history.can_go_back and self._navigate_back():
            return

        # First check if we're in any selection mode
        if getattr(self, "_awaiting_local_model", False):
            self._awaiting_local_model = False
            log = self.query_one("#log", ConversationLog)
            # Return to local provider list for a clear "cancel" behavior
            self._show_local_provider_picker(log)
            return
        if getattr(self, "_awaiting_local_provider", False):
            # Esc means "back one step", not "start over". The step before
            # picking a provider is choosing where the model comes from.
            self._awaiting_local_provider = False
            self._return_to_model_step()
            return
        if getattr(self, "_awaiting_byok_model", False):
            self._awaiting_byok_model = False
            log = self.query_one("#log", ConversationLog)
            self._show_byok_providers(log)
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
            self._return_to_model_step()
            return
        if getattr(self, "_awaiting_connect_type", False):
            # Esc inside Subscriptions steps back to the root connect screen;
            # only the root screen cancels the flow.
            if self.action_connect_menu_back():
                return
            self._awaiting_connect_type = False
            log = self.query_one("#log", ConversationLog)
            log.add_info("Selection cancelled.")
            return
        # The build screens are reached from :connect build, so Esc returns
        # there. Leaving the user on a blank log is how a picker becomes a
        # dead end.
        for flag in ("_awaiting_harness_preset", "_awaiting_harness_import"):
            if getattr(self, flag, False):
                from superqode.providers.connection_profiles import CONNECT_MENU_BUILD

                setattr(self, flag, False)
                log = self.query_one("#log", ConversationLog)
                log.clear()
                self._show_connect_type_picker(log, menu=CONNECT_MENU_BUILD)
                return

        if getattr(self, "_awaiting_explore", False):
            # Explore is opened on its own, so Esc closes it rather than
            # jumping somewhere the user never asked for.
            self._awaiting_explore = False
            self.query_one("#log", ConversationLog).add_info(
                "Closed. Reopen the capability browser with :explore"
            )
            return

        if getattr(self, "_awaiting_acp_agent_selection", False):
            # The agent catalogue is opened from the existing-harness screen,
            # so Esc returns there rather than dropping the user out entirely.
            from superqode.providers.connection_profiles import CONNECT_MENU_AGENTS

            self._awaiting_acp_agent_selection = False
            log = self.query_one("#log", ConversationLog)
            log.clear()
            self._show_connect_type_picker(log, menu=CONNECT_MENU_AGENTS)
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
        if getattr(self, "_awaiting_harness_install", None):
            self._awaiting_harness_install = None
            self._clear_key_harness_session()
            log = self.query_one("#log", ConversationLog)
            log.add_info("Harness installation cancelled.")
            return

        # Then check if agent is running (ACP or BYOK)
        log = self.query_one("#log", ConversationLog)

        # Check for ACP operation first. A stale BYOK session may exist even
        # while an ACP agent is active, so cancellation must target ACP before
        # falling back to local/native mode.
        if self._acp_client is not None or self._agent_process is not None:
            self.action_cancel_agent()
            return

        # BYOK, local, and HarnessSpec runs (PiPy included) share this path.
        # PiPy has no builtin ``_agent``, so requiring one left Escape logging
        # "Cancel requested..." while the harness kept running.
        if self._pure_mode_run_is_active():
            if getattr(self, "_cancel_requested", False):
                return
            self._cancel_connected_run(log)
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

    def _pure_mode_run_is_active(self) -> bool:
        """True when Escape should stop a PureMode or harness turn."""
        pure = getattr(self, "_pure_mode", None)
        if not pure:
            return False
        # The builtin agent loop is the historical Escape target, including
        # when a turn is winding down and ``is_busy`` has already flipped.
        if getattr(pure, "_agent", None) is not None:
            return True
        if not getattr(self, "is_busy", False):
            return False
        if getattr(pure, "_runtime", None) is not None:
            return True
        if getattr(pure, "_harness_session", None) is not None:
            return True
        return bool(getattr(pure, "harness_enabled", False))

    def _clear_running_tools(self, log=None) -> None:
        target = log
        if target is None:
            try:
                target = self.query_one("#log", ConversationLog)
            except Exception:
                return
        clear = getattr(target, "clear_running_tools", None)
        if callable(clear):
            clear()

    def _cancel_connected_run(self, log) -> None:
        """Abort the live model or harness turn and unlock the composer."""
        self._queue_paused = True
        self._cancel_requested = True
        self._cancel_pending_decisions()
        pure = getattr(self, "_pure_mode", None)
        if pure is not None:
            pure.cancel()
        provider, model = self._active_local_provider_model()
        if provider:
            self._teardown_local_model_runtime(provider, model)
        self._stop_thinking()
        self._stop_stream_animation()
        self._clear_running_tools(log)
        self.is_busy = False
        log.add_info("🛑 Agent operation cancelled")

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
        """Stage composer image drops before insertion, once per paste event."""
        if getattr(event, "_image_paste_checked", False):
            return
        event._image_paste_checked = True
        if not isinstance(self.focused, SelectionAwareInput):
            return
        if self._stage_pasted_images(event.text) or self._fold_composer_paste(event.text):
            event.stop()
            event.prevent_default()

    # Runtimes that are self-contained (own model + auth) and can be used in the
    # TUI without a separate :connect step.
    _SELF_CONTAINED_RUNTIMES = frozenset(
        {
            "codex-cli",
            "codex-sdk",
            "copilot-sdk",
            "claude-agent-sdk",
            "antigravity-sdk",
            "antigravity-cli",
            "antigravity-managed",
            "devin-cli",
            "muse",
            # Subscription CLI runtimes: the vendor login supplies both auth and
            # model, so they must auto-connect like the other self-contained
            # runtimes. Without this, :connect copilot reported "Already on
            # runtime 'copilot-cli'" and returned without ever connecting, so
            # the next message failed with "Not connected".
            "copilot-cli",
            "grok-cli",
        }
    )

    def action_clear_screen(self):
        log = self.query_one("#log", ConversationLog)
        log.clear()
        team_name = Path.cwd().name or "SuperQode"
        # Temporarily disable auto-scroll so we can scroll to top
        log.auto_scroll = False
        log.write(
            render_welcome(
                self.agents,
                team_name,
                width=self._welcome_width(log),
                state=self._welcome_state(team_name),
            ),
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

    def action_interrupt(self) -> None:
        """Stop work without exiting; require two idle presses to quit."""
        from time import monotonic

        if getattr(self, "_install_in_progress", False):
            self._last_interrupt_at = None
            self.action_smart_cancel()
            return
        if self.is_busy or self._permission_pending or self._awaiting_agent_question:
            self._last_interrupt_at = None
            self.action_cancel_agent()
            return
        now = monotonic()
        previous = getattr(self, "_last_interrupt_at", None)
        if previous is not None and now - previous < 2.0:
            self._last_interrupt_at = None
            self.action_quit()
            return
        self._last_interrupt_at = now
        self.query_one("#log", ConversationLog).add_info(
            "Press Ctrl+C again within 2 seconds to exit, or use :exit. Your draft is kept."
        )

    def action_quit(self) -> None:
        """Clean up properly before an explicit exit."""
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
    app = SuperQodeApp()
    try:
        app.run()
    finally:
        from superqode.app.herdr import close

        close(app)


if __name__ == "__main__":
    run_textual_app()
