"""Startup: agent/keybinding/welcome loading, managers, discovery."""

from __future__ import annotations
import asyncio
from pathlib import Path
from typing import List, Optional
from textual import work
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.models import AgentStatus, AgentInfo
from superqode.app.widgets import (
    ModeBadge,
    HintsBar,
    ConversationLog,
)
from superqode.widgets.command_palette import PaletteCommand
from superqode.undo_manager import UndoManager
from superqode.app.welcome import render_welcome


class HelperStartupMixin:
    """Startup: agent/keybinding/welcome loading, managers, discovery."""

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
