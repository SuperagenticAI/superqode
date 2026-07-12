"""Assorted small app helpers."""

from __future__ import annotations
import asyncio
import json
import os
import subprocess
import shutil
import shlex
import time
import concurrent.futures
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from textual.widgets import Static, Input
from textual import work
from rich.text import Text
from rich.panel import Panel
from rich.box import ROUNDED
from superqode.providers.model_specs import (
    split_provider_model_ref,
)
from superqode.app.constants import (
    GRADIENT,
    THEME,
    COMMANDS,
)
from superqode.app.models import AgentStatus, AgentInfo
from superqode.app.widgets import (
    ModeBadge,
    HintsBar,
    ConversationLog,
)
from superqode.widgets.command_palette import PaletteCommand
from superqode.app.theme_bridge import (
    apply_theme as _apply_theme_palette,
    save_theme,
)
from superqode.plan import (
    TaskStatus,
    TaskPriority,
)
from superqode.atomic import atomic_read
from superqode.file_viewer import (
    get_file_info,
)
from superqode.sidebar import (
    get_file_diff,
    CollapsibleSidebar,
)
from superqode.undo_manager import UndoManager

# --- helpers extracted from app_main (A1) ---
from superqode.app.inputs import SelectionAwareInput
from superqode.app.welcome import render_welcome
from superqode.app.recipes import PromptCompletionCandidate, LocalRecipe
from superqode.app.session_state import get_session, set_mode


class HelpersMixin:
    """State/parsing/resolution/predicate helpers used across the app."""

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
    def _set_prompt_border_title(self) -> None:
        """Give the prompt box a neutral code-focused title."""
        try:
            input_box = self.query_one("#input-box")
            input_box.border_title = "✎ Code"
        except Exception:
            pass
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
    def _call_ui(self, func, *args):
        """Run a UI callback from either worker threads or the app thread."""
        try:
            return self.call_from_thread(func, *args)
        except RuntimeError as e:
            message = str(e).lower()
            if "different thread" in message or "app thread" in message:
                return func(*args)
            raise
    def _conversation_log(self) -> ConversationLog | None:
        try:
            return self.query_one("#log", ConversationLog)
        except Exception:
            return None
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
    def _create_checkpoint_before_agent(self, operation_name: str = "Agent operation"):
        """Create a checkpoint before an agent operation."""
        if hasattr(self, "_undo_manager") and self._undo_manager:
            self._undo_manager.create_checkpoint(f"Before: {operation_name}")
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
    @staticmethod
    def _env_flag(name: str) -> bool:
        value = os.environ.get(name, "").strip().lower()
        return value in {"1", "true", "yes", "on"}
    def _record_ex_command(self, cmd: str, command_name: str) -> None:
        if not cmd.startswith(":"):
            return
        if command_name in {"vim", "set"}:
            return
        normalized = ":" + cmd[1:].strip()
        if normalized in {":", ":history"}:
            return
        self._last_ex_command = normalized
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
    def _user_message_history(self, log: ConversationLog) -> list[str]:
        """Return prior user messages (oldest first) for rewind/edit."""
        return [
            text for role, text, _agent in log._messages if role == "user" and str(text).strip()
        ]
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
    def _find_recipe(self, name: str) -> LocalRecipe | None:
        recipes = self._load_local_recipes()
        recipe = recipes.get(name)
        if recipe is not None:
            return recipe
        lowered = name.lower()
        return next((item for item in recipes.values() if item.name.lower() == lowered), None)
    def _set_prompt_prefill(self, value: str) -> None:
        """Put text in the prompt input and focus it."""
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            input_widget.value = value
            input_widget.cursor_position = len(value)
            input_widget.focus()
        except Exception:
            pass
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
        from superqode.app_main import SuperQodeApp
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
        from superqode.app_main import SuperQodeApp
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
        from superqode.app_main import SuperQodeApp
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
    def _factory(self):
        from superqode.session.factory import SoftwareFactory

        return SoftwareFactory(storage_dir=".superqode/sessions")
    def _resolve_share_session_id(self, value: str = "") -> str:
        from superqode.headless import resolve_session_id

        requested = (value or "").strip()
        if requested:
            return resolve_session_id(requested, ".superqode/sessions")
        current_id = self._current_session_id()
        if not current_id:
            raise ValueError("No active session. Use :sessions to choose one.")
        return resolve_session_id(current_id, ".superqode/sessions")
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
    def _import_share_artifact(self, path: Path, new_session_id: str = "") -> str:
        from superqode.session.share_artifacts import import_share_artifact

        return import_share_artifact(
            path,
            new_session_id=new_session_id,
            storage_dir=".superqode/sessions",
        )
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
    def _current_interaction_mode_name(self) -> str:
        if getattr(self, "_chat_mode", False):
            return "chat"
        if getattr(self, "_plan_mode_enabled", False):
            return "plan"
        return "build"
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
    def _use_jsonrpc_acp_client(self) -> bool:
        """Return True when the custom JSON-RPC ACP client is enabled."""
        import os

        mode = os.environ.get("SUPERQODE_ACP_CLIENT", "").strip().lower()
        return mode in {"custom", "jsonrpc", "rpc"}
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
    def _is_calm_output(self) -> bool:
        """True when we should present a calm, summarized view (not verbose)."""
        return getattr(self, "thinking_verbosity", "normal") != "verbose"
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
    def _memory_status_state(self, status) -> str:
        if getattr(status, "available", False):
            return "ready"
        if not getattr(status, "enabled", True):
            return "disabled"
        if getattr(status, "installed", None) is False:
            return "missing"
        return "missing"
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
    def _view_file(self, file_path: str, log: ConversationLog):
        """View file content with syntax highlighting."""
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
