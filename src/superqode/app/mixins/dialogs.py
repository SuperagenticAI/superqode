"""Modal screens and overlays."""

from __future__ import annotations

import asyncio
import sys
import os
import subprocess
import shutil
import time
from pathlib import Path
from typing import Any
from textual import work
from rich.text import Text
from rich.panel import Panel
from rich.box import ROUNDED
from superqode.app.constants import (
    GRADIENT,
    THEME,
    AGENT_ICONS,
)
from superqode.app.widgets import (
    ConversationLog,
)
from superqode.widgets.rewind_overlay import RewindOverlay, RewindTarget
from superqode.sidebar import (
    CollapsibleSidebar,
)
from superqode.design_system import (
    COLORS as SQ_COLORS,
    GRADIENT_PURPLE,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.inputs import SelectionAwareInput
from superqode.app.welcome import render_welcome
from superqode.app.recipes import LocalRecipe


#: How long the ACP picker serves a catalogue snapshot before a redraw
#: revalidates it in the background. Short enough that an agent installed from
#: another terminal shows up on the next keypress, long enough that holding an
#: arrow key does not re-read every agent file and re-scan PATH once per row.
ACP_CATALOG_TTL_SECONDS = 5.0


class DialogsMixin:
    """_show_/_open_ modal screens and overlays."""

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

    def _show_welcome(self, team_name: str):
        log = self.query_one("#log", ConversationLog)
        # Temporarily disable auto-scroll so we can scroll to top
        log.auto_scroll = False
        # expand=True makes the renderable fill the full log width so the
        # centered welcome blocks sit in the middle of the screen, not the left.
        log.write(
            render_welcome(
                self.agents,
                team_name,
                width=self._welcome_width(log),
                state=self._welcome_state(team_name),
            ),
            expand=True,
        )
        # Mark that the log currently shows only the welcome, so resizes can
        # re-flow it responsively until the user starts interacting.
        self._welcome_active = True
        # Show the first-run card until the first connection lands, and note
        # the visit for the session hint.
        self._maybe_show_onboarding(log)
        self._note_repository_visit()
        # Scroll to top so user sees the attractive header first
        log.scroll_home(animate=False)
        # Re-enable auto-scroll for future messages
        self.set_timer(0.2, lambda: setattr(log, "auto_scroll", True))

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
            harness = session.harness_id or "workbench"
            route = f"{provider}/{model}"
            t.append(f"  {display_id:<10}", style=f"bold {THEME['cyan']}")
            t.append(f"{harness[:17]:<19}", style=THEME["purple"])
            t.append(f"{route[:29]:<31}", style=THEME["text"])
            t.append(f"{session.message_count:>3} msgs  ", style=THEME["muted"])
            t.append(f"{session.updated_at[:19]}\n", style=THEME["dim"])

        t.append("\n  Use ", style=THEME["muted"])
        t.append(":sessions switch <id>", style=THEME["cyan"])
        t.append(" to restore its harness and history, or ", style=THEME["muted"])
        t.append("/fork <optional-new-id>", style=THEME["cyan"])
        t.append(" to branch the active session.\n", style=THEME["muted"])
        t.append("  Use ", style=THEME["muted"])
        t.append(":switchboard", style=THEME["cyan"])
        t.append(" for graph, handoff, approvals, and share-tree actions.\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _show_session_tree(self, log: ConversationLog):
        """Show saved sessions grouped by parent/fork relationship."""
        self._handle_switchboard("graph", log)

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
        runtime_getter = getattr(self, "_active_antigravity_runtime", None)
        runtime = runtime_getter() if callable(runtime_getter) else None
        t.append("    Auth      ", style=THEME["muted"])
        if getattr(runtime, "name", "") == "antigravity-sdk":
            t.append("Gemini API key handled by the SDK\n", style=THEME["text"])
        else:
            t.append("OS keyring / browser sign-in handled by agy\n", style=THEME["text"])
        if runtime is not None:
            t.append("    Runtime   ", style=THEME["muted"])
            t.append(f"{runtime.name}\n", style=THEME["text"])
            if getattr(runtime, "name", "") == "antigravity-cli":
                t.append("    Agent     ", style=THEME["muted"])
                t.append(f"{runtime.agent_name or 'default'}\n", style=THEME["text"])
            t.append("    Model     ", style=THEME["muted"])
            t.append(f"{runtime.config.model or 'default'}\n", style=THEME["text"])
            t.append("    Effort    ", style=THEME["muted"])
            t.append(f"{runtime.reasoning_effort or 'auto'}\n", style=THEME["text"])
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

    def _show_agy_help(self, log) -> None:
        """Show the native agy 1.1.x command tree available in SuperQode."""

        t = Text()
        t.append("\n  agy CLI commands in SuperQode\n\n", style=f"bold {THEME['text']}")
        sections = (
            (
                "Harness and session",
                (
                    (":agy connect", "connect the signed-in agy harness"),
                    (":agy run <prompt>", "send a prompt through the connected runtime"),
                    (":agy status", "binary, version, settings, runtime diagnostics"),
                    (":agy agent [name]", "list agents or select one for future turns"),
                    (":agy model [name]", "list models or select one for future turns"),
                    (":agy effort <auto|low|medium|high>", "set reasoning effort"),
                ),
            ),
            (
                "Native CLI",
                (
                    (":agy agents", "run `agy agents`"),
                    (":agy models", "run `agy models`"),
                    (":agy changelog", "show CLI release notes"),
                    (":agy version", "show the installed version"),
                    (":agy update", "update the agy installation"),
                    (":agy install [flags]", "configure PATH and shell integration"),
                ),
            ),
            (
                "Plugins",
                (
                    (":agy plugin list", "list imported plugins"),
                    (":agy plugin import [gemini|claude]", "import legacy plugins"),
                    (":agy plugin install <target>", "install a plugin"),
                    (":agy plugin uninstall <name>", "uninstall a plugin"),
                    (":agy plugin enable|disable <name>", "change plugin state"),
                    (":agy plugin validate [path]", "validate a plugin"),
                    (":agy plugin link <marketplace> <target>", "generate a marketplace link"),
                ),
            ),
            (
                "Interactive TUI and other routes",
                (
                    (":agy launch [flags]", "show a copyable external agy TUI command"),
                    (":agy continue", "show the workspace quick-resume command"),
                    (":agy resume <conversation-id>", "show an exact resume command"),
                    (":agy migrate", "show Gemini CLI migration steps"),
                    (":agy sdk", "use the local API-key SDK harness"),
                    (":agy managed", "use Google's hosted API-key agent"),
                    (":agy superqode", "use Google BYOK with SuperQode's harness"),
                ),
            ),
        )
        for title, rows in sections:
            t.append(f"  {title}\n", style=f"bold {THEME['purple']}")
            for command, description in rows:
                t.append(f"    {command:<42}", style=THEME["cyan"])
                t.append(f"{description}\n", style=THEME["muted"])
            t.append("\n")
        t.append(
            "  Account-backed commands run only when you explicitly enter them. "
            "`:agy help`, `:agy status`, and completion do not query your account.\n",
            style=THEME["dim"],
        )
        t.append(
            "  A full-screen TUI cannot be nested reliably inside SuperQode, so "
            "interactive panels (/resume, /agents, /config, /permissions, /mcp, "
            "/skills) are opened through :agy launch.\n",
            style=THEME["dim"],
        )
        log.write(t)

    def _show_agy_plugin_help(self, log) -> None:
        t = Text()
        t.append("\n  agy plugin commands\n\n", style=f"bold {THEME['text']}")
        for command, description in (
            (":agy plugin list", "List imported plugins"),
            (":agy plugin import [gemini|claude]", "Import legacy plugins"),
            (":agy plugin install <target>", "Install plugin or plugin@marketplace"),
            (":agy plugin uninstall <name>", "Uninstall a plugin"),
            (":agy plugin enable <name>", "Enable an installed plugin"),
            (":agy plugin disable <name>", "Disable an installed plugin"),
            (":agy plugin validate [path]", "Validate a plugin directory"),
            (":agy plugin link <marketplace> <target>", "Generate a marketplace link"),
        ):
            t.append(f"    {command:<44}", style=THEME["cyan"])
            t.append(f"{description}\n", style=THEME["muted"])
        log.write(t)

    def _show_antigravity_help(self, log) -> None:
        t = Text()
        t.append("\n  Antigravity in SuperQode\n\n", style=f"bold {THEME['text']}")
        t.append("  :connect antigravity       ", style=THEME["cyan"])
        t.append("Antigravity harness through signed-in agy\n", style=THEME["muted"])
        t.append("  :antigravity sdk           ", style=THEME["cyan"])
        t.append("Antigravity harness through its API-key SDK\n", style=THEME["muted"])
        t.append("  :antigravity managed       ", style=THEME["cyan"])
        t.append(
            "Antigravity harness in Google's hosted sandbox via Gemini API key\n",
            style=THEME["muted"],
        )
        t.append("  :antigravity superqode     ", style=THEME["cyan"])
        t.append("SuperQode harness with a Google API key\n", style=THEME["muted"])
        t.append("  :antigravity launch        ", style=THEME["cyan"])
        t.append("show the separate agy CLI handoff\n", style=THEME["muted"])
        t.append("  :antigravity status        ", style=THEME["cyan"])
        t.append("check binary/settings status\n", style=THEME["muted"])
        t.append("  :antigravity agent <name>  ", style=THEME["cyan"])
        t.append("select a CLI custom agent for future turns\n", style=THEME["muted"])
        t.append("  :antigravity model <name>  ", style=THEME["cyan"])
        t.append("select a CLI/SDK model for future turns\n", style=THEME["muted"])
        t.append("  :antigravity effort <level>", style=THEME["cyan"])
        t.append("set CLI/SDK thinking effort (or auto)\n", style=THEME["muted"])
        t.append("  :antigravity migrate       ", style=THEME["cyan"])
        t.append("show Gemini CLI migration steps\n", style=THEME["muted"])
        t.append(
            "\n  Structured SuperQode tool cards require an ACP/headless event stream. "
            "The managed and SDK routes provide typed events; agy does not document "
            "that stream yet.\n",
            style=THEME["dim"],
        )
        t.append(
            "  Managed execution is remote: it does not upload the current local "
            "repository automatically.\n",
            style=THEME["dim"],
        )
        log.write(t)

    def _show_prime_status(self, log) -> None:
        """Show Prime Agent readiness. Reads provider names, never secrets."""
        from superqode.providers import prime_agent as prime

        binary = prime.binary_path()
        t = Text()
        t.append("\n  Prime Agent status\n\n", style=f"bold {THEME['text']}")
        t.append("    Binary     ", style=THEME["muted"])
        t.append(
            f"{binary or 'not found'}\n",
            style=THEME["success" if binary else "warning"],
        )
        if binary:
            t.append("    Version    ", style=THEME["muted"])
            t.append(f"{prime.version() or 'unknown'}\n", style=THEME["text"])

        logins = prime.auth_providers()
        t.append("    Logins     ", style=THEME["muted"])
        t.append(
            f"{', '.join(logins)}\n" if logins else "none: run `prime-agent`, then `/login`\n",
            style=THEME["success" if logins else "warning"],
        )

        custom = prime.custom_providers()
        t.append("    Local      ", style=THEME["muted"])
        t.append(
            f"{', '.join(custom)} (models.json)\n" if custom else "none configured\n",
            style=THEME["success" if custom else "dim"],
        )

        opts = self._prime_opts()
        t.append("    Model      ", style=THEME["muted"])
        t.append(
            f"{opts.model}\n" if opts.model else "Prime Agent default\n",
            style=THEME["text"],
        )
        t.append("    Depth      ", style=THEME["muted"])
        t.append(
            f"{opts.max_depth} (RLM_MAX_DEPTH)\n"
            if opts.max_depth is not None
            else "Prime default (1)\n",
            style=THEME["text"] if opts.max_depth is not None else THEME["dim"],
        )
        t.append("    Goal       ", style=THEME["muted"])
        t.append(
            f"{opts.goal[:52]}\n" if opts.goal else "none\n",
            style=THEME["text"] if opts.goal else THEME["dim"],
        )
        t.append("    Autonomous ", style=THEME["muted"])
        if opts.autonomous:
            gates = f"{len(opts.gates)} gate(s)" if opts.gates else "no gates"
            t.append(f"on, {gates}\n", style=THEME["warning"])
            for gate in opts.gates:
                t.append(f"      {gate}\n", style=THEME["dim"])
        else:
            t.append("off\n", style=THEME["dim"])
        t.append("    Sandbox    ", style=THEME["muted"])
        t.append("none: IPython runs with your permissions\n", style=THEME["warning"])

        if not binary:
            t.append("\n  Install:\n", style=THEME["muted"])
            t.append(f"    {prime.INSTALL_HINT}\n", style=THEME["cyan"])
        t.append("\n  Commands:\n", style=THEME["muted"])
        t.append("    :prime models [search]     ", style=THEME["cyan"])
        t.append("list the model catalog\n", style=THEME["muted"])
        t.append("    :prime model               ", style=THEME["cyan"])
        t.append("pick a model, then connect\n", style=THEME["muted"])
        t.append("    :prime connect             ", style=THEME["cyan"])
        t.append("connect over ACP\n", style=THEME["muted"])
        log.write_feedback(t)

    def _show_prime_agents(self, log) -> None:
        """List Prime's live agent sessions, including the RLM subagent tree."""
        from superqode.providers import prime_agent as prime

        if not self._require_prime(log):
            return

        sessions = prime.list_agents()
        t = Text()
        t.append("\n  Prime Agent sessions\n\n", style=f"bold {THEME['text']}")
        if not sessions:
            t.append("  No active agents.\n\n", style=THEME["muted"])
            t.append(
                "  Sessions started from SuperQode over ACP run in their own\n"
                "  process and are not held by the background service.\n",
                style=THEME["dim"],
            )
            log.write_feedback(t)
            return

        for info in sessions:
            indent = "    " + ("  " * info.rlm_depth)
            marker = "└─ " if info.is_subagent else ""
            t.append(f"{indent}{marker}", style=THEME["muted"])
            t.append(f"{info.name or info.session_id[:12]:28s}", style=THEME["cyan"])
            t.append(f"{info.lifecycle or 'unknown':12s}", style=THEME["text"])
            state = "active" if info.active else info.activity or "idle"
            t.append(f"{state:10s}", style=THEME["success" if info.active else "dim"])
            if info.is_subagent:
                t.append(f"depth {info.rlm_depth}", style=THEME["dim"])
            t.append("\n")

        roots = sum(1 for info in sessions if not info.is_subagent)
        children = len(sessions) - roots
        t.append(f"\n  {roots} root, {children} RLM subagent(s)\n", style=THEME["muted"])
        log.write_feedback(t)

    def _show_prime_doctor(self, log) -> None:
        """Report Prime's background service health."""
        from superqode.providers import prime_agent as prime

        if not self._require_prime(log):
            return

        records = prime.doctor()
        t = Text()
        t.append("\n  Prime Agent background services\n\n", style=f"bold {THEME['text']}")
        if not records:
            t.append("  No background services running.\n", style=THEME["muted"])
            log.write_feedback(t)
            return

        for record in records:
            status = str(record.get("status") or "unknown")
            t.append("    pid ", style=THEME["muted"])
            t.append(f"{record.get('pid', '?')!s:8s}", style=THEME["cyan"])
            t.append(f"{str(record.get('version') or '?'):10s}", style=THEME["text"])
            t.append(f"{status:12s}", style=THEME["success" if status == "current" else "warning"])
            t.append(f"{record.get('sessionCount', 0)} session(s)\n", style=THEME["dim"])
            socket_path = record.get("socketPath")
            if socket_path:
                t.append(f"      {socket_path}\n", style=THEME["dim"])

        t.append("\n  Clean up stale services with ", style=THEME["muted"])
        t.append("prime-agent doctor --fix\n", style=THEME["cyan"])
        log.write_feedback(t)

    def _show_prime_schedules(self, log) -> None:
        """List Prime's scheduled and recurring prompts."""
        from superqode.providers import prime_agent as prime

        if not self._require_prime(log):
            return

        jobs = prime.list_schedules()
        t = Text()
        t.append("\n  Prime Agent scheduled prompts\n\n", style=f"bold {THEME['text']}")
        if not jobs:
            t.append("  Nothing scheduled.\n\n", style=THEME["muted"])
            t.append("  Add one with ", style=THEME["muted"])
            t.append("prime-agent schedule add\n", style=THEME["cyan"])
            log.write_feedback(t)
            return

        for job in jobs:
            t.append("    ", style=THEME["muted"])
            t.append(f"{str(job.get('id') or '?')[:14]:16s}", style=THEME["cyan"])
            t.append(
                f"{str(job.get('schedule') or job.get('cron') or ''):18s}", style=THEME["text"]
            )
            t.append(f"{str(job.get('status') or ''):10s}", style=THEME["dim"])
            prompt = str(job.get("prompt") or "").replace("\n", " ")
            t.append(f"{prompt[:40]}\n", style=THEME["dim"])
        log.write_feedback(t)

    def _show_prime_packages(self, log) -> None:
        """List Prime's installed capability packages."""
        from superqode.providers import prime_agent as prime

        if not self._require_prime(log):
            return

        packages = prime.list_packages()
        t = Text()
        t.append("\n  Prime Agent capability packages\n\n", style=f"bold {THEME['text']}")
        if not packages:
            t.append("  No packages installed.\n\n", style=THEME["muted"])
            t.append(
                "  Packages provide extensions, skills, prompts and themes:\n", style=THEME["muted"]
            )
            t.append("    prime-agent package install <source>\n", style=THEME["cyan"])
            log.write_feedback(t)
            return

        for line in packages:
            t.append(f"    {line}\n", style=THEME["text"])
        log.write_feedback(t)

    def _require_prime(self, log) -> bool:
        """Report a missing Prime install, shared by the :prime listings."""
        from superqode.providers import prime_agent as prime

        if prime.is_installed():
            return True
        log.add_error("Prime Agent is not installed.")
        log.add_info(f"  Install: {prime.INSTALL_HINT}")
        return False

    def _show_prime_login(self, log) -> None:
        """Point at Prime's own login flow; it owns its credentials."""
        t = Text()
        t.append("\n  Prime Agent login\n\n", style=f"bold {THEME['text']}")
        t.append(
            "  Prime Agent manages its own credentials. Run in a terminal:\n", style=THEME["muted"]
        )
        t.append("    prime-agent\n", style=THEME["cyan"])
        t.append("    /login\n", style=THEME["cyan"])
        t.append("\n  Subscriptions: ", style=THEME["muted"])
        t.append("ChatGPT Plus/Pro, Claude Pro/Max, GitHub Copilot\n", style=THEME["text"])
        t.append(
            "\n  GitHub Copilot only serves models enabled on the account. If a model\n"
            '  reports "not supported", enable it in VS Code under Copilot Chat,\n'
            "  model selector, Enable.\n",
            style=THEME["dim"],
        )
        t.append("\n  Free and offline: ", style=THEME["muted"])
        t.append("register local models in ~/.prime/agent/models.json\n", style=THEME["text"])
        t.append(
            '    {"providers": {"ollama": {"baseUrl": "http://localhost:11434/v1",\n'
            '      "api": "openai-completions", "apiKey": "ollama",\n'
            '      "models": [{"id": "qwen3.5:9b"}]}}}\n',
            style=THEME["cyan"],
        )
        t.append("\n  Then: ", style=THEME["muted"])
        t.append(":prime models", style=THEME["cyan"])
        t.append(" to confirm, ", style=THEME["muted"])
        t.append(":prime model", style=THEME["cyan"])
        t.append(" to choose.\n", style=THEME["muted"])
        log.write_feedback(t)

    def _show_prime_help(self, log) -> None:
        t = Text()
        t.append("\n  Prime Agent in SuperQode\n\n", style=f"bold {THEME['text']}")
        t.append("  :prime connect [model]     ", style=THEME["cyan"])
        t.append("connect Prime Agent over ACP\n", style=THEME["muted"])
        t.append("  :prime models [search]     ", style=THEME["cyan"])
        t.append("pick a model, optionally filtered\n", style=THEME["muted"])
        t.append("  :prime model <provider/id> ", style=THEME["cyan"])
        t.append("set a model directly, without the picker\n", style=THEME["muted"])
        t.append("  :prime local               ", style=THEME["cyan"])
        t.append("register local model servers with Prime\n", style=THEME["muted"])
        t.append("  :prime depth [n]           ", style=THEME["cyan"])
        t.append("recursion depth via RLM_MAX_DEPTH\n", style=THEME["muted"])
        t.append("  :prime goal [text]         ", style=THEME["cyan"])
        t.append("seed a persistent goal for the session\n", style=THEME["muted"])
        t.append("  :prime autonomous [gate]   ", style=THEME["cyan"])
        t.append("autonomous mode and completion gates\n", style=THEME["muted"])
        t.append("  :prime agents              ", style=THEME["cyan"])
        t.append("live sessions and the RLM subagent tree\n", style=THEME["muted"])
        t.append("  :prime schedule            ", style=THEME["cyan"])
        t.append("scheduled and recurring prompts\n", style=THEME["muted"])
        t.append("  :prime packages            ", style=THEME["cyan"])
        t.append("installed capability packages\n", style=THEME["muted"])
        t.append("  :prime status              ", style=THEME["cyan"])
        t.append("binary, version, logins, local providers\n", style=THEME["muted"])
        t.append("  :prime doctor              ", style=THEME["cyan"])
        t.append("background service health\n", style=THEME["muted"])
        t.append("  :prime update              ", style=THEME["cyan"])
        t.append("run Prime Agent's own updater\n", style=THEME["muted"])
        t.append("  :prime login               ", style=THEME["cyan"])
        t.append("how to authenticate, including free local models\n", style=THEME["muted"])
        t.append("  :prime help                ", style=THEME["cyan"])
        t.append("this help\n", style=THEME["muted"])
        t.append(
            "\n  Prime is an RLM agent: a persistent IPython kernel is its only\n"
            "  model-facing tool. It fixes the model at launch, so choosing one\n"
            "  reconnects rather than switching in place.\n",
            style=THEME["dim"],
        )
        t.append(
            "  Goal, autonomous and depth are start-time settings, so changing\n"
            "  one applies on the next :prime connect rather than in place.\n"
            "  /refine, /compact and /heartbeat stay in-session only: Prime\n"
            "  advertises no ACP commands, so sending one as a prompt reaches\n"
            "  the model as text instead of running it.\n",
            style=THEME["dim"],
        )
        t.append(
            "  The kernel runs with your permissions. There is no sandbox and no\n"
            "  approval prompt.\n",
            style=THEME["warning"],
        )
        log.write_feedback(t)

    def _show_grok_status(self, log) -> None:
        """Show local Grok CLI readiness. Cheap: no catalog probe, no token import."""
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
                "imported but expired — the CLI may already have refreshed; retry :grok api\n",
                style=THEME["warning"],
            )
        elif token.get("cli_login"):
            t.append("available: run :grok api to use SuperQode's harness\n", style=THEME["dim"])
        else:
            t.append("not imported\n", style=THEME["dim"])
        t.append("    Default   ", style=THEME["muted"])
        try:
            from superqode.providers.grok_cli_auth import (
                DEFAULT_SUBSCRIPTION_MODEL,
                peek_cached_cli_models,
            )

            listing = peek_cached_cli_models() or {}
            live_default = str(listing.get("default") or "")
            if live_default:
                t.append(f"{live_default}\n", style=THEME["text"])
            else:
                t.append(
                    f"{DEFAULT_SUBSCRIPTION_MODEL} (run :grok models for the live catalog)\n",
                    style=THEME["text"],
                )
        except Exception:  # noqa: BLE001 - status must never crash
            t.append("grok-4.6\n", style=THEME["text"])
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

    @staticmethod
    def _alternate_runtime_names(current: str, *, limit: int = 5) -> list[str]:
        """Installed runtimes that could execute this spec instead of ``current``.

        Only ready runtimes are listed: naming a backend the user cannot run
        would be an advert rather than a capability.
        """
        try:
            from superqode.runtime import list_runtimes

            return [
                runtime.name
                for runtime in list_runtimes()
                if runtime.ready and runtime.name != current
            ][:limit]
        except Exception:  # noqa: BLE001 - inspect must render without runtimes
            return []

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
        # The same spec runs through several agent frameworks. That is one of
        # the strongest reasons to own a harness at all, and it was previously
        # visible only in `:runtime list`, disconnected from any actual harness.
        alternatives = self._alternate_runtime_names(summary["runtime"]["backend"])
        if alternatives:
            t.append("\n  Also runs   ", style=THEME["muted"])
            t.append(" · ".join(alternatives), style=THEME["dim"])
            t.append("   ", style="")
            t.append(":runtime <name>", style=THEME["cyan"])
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

    def _show_superqode_demo(self, log: ConversationLog):
        """Show a demo of SuperQode's unique design system."""

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

    def _show_permission_modal(self, tool_name: str, tool_input: dict, reason: str):
        """Show a modal permission dialog for ASK mode."""
        from textual.screen import ModalScreen
        from textual.containers import Container, Horizontal
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

    def _show_permission_auto_approved(self, line: str, log: ConversationLog):
        """Show permission auto-approved (AUTO mode)."""
        t = Text()
        t.append("  🟢 ", style="#22c55e")
        t.append(f"{line}", style="#a1a1aa")
        t.append(" → ", style="#71717a")
        t.append("AUTO-APPROVED\n", style="bold #22c55e")
        log.write(t)

    def _show_permission_denied(self, line: str, log: ConversationLog):
        """Show permission denied (DENY mode)."""
        t = Text()
        t.append("  🔴 ", style="#ef4444")
        t.append(f"{line}", style="#a1a1aa")
        t.append(" → ", style="#71717a")
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
        t.append(" (use :mode deny to block destructive ops) │\n", style="#a1a1aa")
        t.append("  ╰─────────────────────────────────────────────────────────╯\n", style="#f59e0b")
        log.write(t)

    # Keep old methods for compatibility
    def _show_permission_alert(self, line: str, log: ConversationLog):
        """Show a permission alert to the user (legacy)."""
        self._show_permission_ask(line, log)

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
        header.append("is working...", style="#a1a1aa")
        header.append("  [Ctrl+T to hide logs]  [Esc to cancel]\n", style="#71717a")
        log.write(header)

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

    def _show_final_response(
        self, response_text: str, name: str, duration: float, log: ConversationLog
    ):
        """Show the final response with proper formatting and word wrapping."""
        # Store the response for :copy command
        self._last_response = response_text

        # Dim chrome: a single subtle rule + quiet completion note, so the
        # answer that follows is what stands out (not the separator).
        sep = Text()
        sep.append("\n")
        sep.append("  " + "─" * 44 + "\n", style=THEME["dim"])
        sep.append(f"  Done · {name} · {duration:.1f}s\n", style=THEME["dim"])
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
        total_tokens = int(summary.get("total_tokens", 0) or 0)

        # Only report files this turn actually changed (tracked by the agent).
        # We intentionally do NOT fall back to the ambient git working tree:
        # a simple question that edits nothing should show no change block,
        # even when the repo already has unrelated uncommitted edits. Use
        # ``:diff`` or the Changes sidebar to inspect the full working tree.

        log.auto_scroll = True

        # Commit any buffered streaming tail immediately beneath the answer
        # marker. The completion summary belongs after the answer; placing it
        # first made short buffered replies appear detached from their label.
        if response_text.strip():
            log.write_final_response(response_text, agent=name, success=True)

        # Keep prior turns in the log so users can scroll back through the
        # whole conversation (PgUp/PgDn). The subtle rule closes the answer and
        # introduces its quiet completion metadata.
        separator = Text()
        separator.append("\n")
        separator.append("  " + "─" * 44 + "\n", style=SQ_COLORS.text_muted)
        log.write(separator)

        # Dim chrome: this roll-up is SuperQode meta, not the answer — keep it
        # quiet so the response above it stays the prominent thing.
        header = Text()
        header.append("  Done", style=SQ_COLORS.text_ghost)
        header.append("  •  ", style=SQ_COLORS.text_ghost)
        header.append(name, style=SQ_COLORS.text_muted)

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
        if total_tokens > 0:
            facts.append(f"{total_tokens:,} toks")
        header.append("  •  ", style=SQ_COLORS.text_muted)
        header.append("  •  ".join(facts), style=SQ_COLORS.text_muted)
        header.append("\n\n")

        log.write(header)

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

        # NEW: Trigger sidebar auto-navigation if files were modified
        if files_modified:
            self.set_timer(0.2, lambda: self._navigate_to_sidebar_changes(files_modified))

        # Reveal at most one capability, after a completed turn.
        self._record_milestone("task_completed")
        # What the run did decides which hints become relevant.
        if files_modified:
            self._record_milestone("edited_files")
        if self._run_used_shell(summary):
            self._record_milestone("ran_shell")
        if self._run_hit_an_error(summary):
            self._record_milestone("hit_an_error")
        self._maybe_reveal_next_capability(log)

        # Keep the view pinned to the latest response. We no longer clear the
        # log each turn, so scrolling home would jump away from the answer the
        # user just asked for — scroll to the end and resume follow mode.
        log.auto_scroll = True
        self.set_timer(0.1, lambda: log.scroll_end(animate=False))

    #: Suggested commands, in the order they become useful. Only unused ones
    #: are offered.
    _WORTH_KNOWING: tuple[tuple[str, str], ...] = (
        (":diff", "review every change the agent made"),
        (":undo", "roll back the last agent edit"),
        (":trust", "decide once what may run without asking"),
        (":sandbox", "run commands away from your own shell"),
        (":memory", "facts that outlive the agent that learned them"),
        (":skills", "instructions you stop retyping"),
        (":tree", "branch and resume sessions"),
        (":harness", "swap the tool loop, keep the session"),
        (":mcp", "attach tool servers: databases, browsers, your APIs"),
        (":eval", "score harnesses on your own repository"),
        (":work", "verified work across repositories"),
    )

    def _append_unused_command_suggestions(self, text, limit: int = 5) -> None:
        """List up to ``limit`` commands this user has not run yet."""
        try:
            from superqode.app.progress import load_progress

            used = load_progress().commands_used
        except Exception:  # noqa: BLE001 - help must always render
            return

        unused = [(cmd, why) for cmd, why in self._WORTH_KNOWING if cmd.lstrip(":") not in used][
            :limit
        ]
        if not unused:
            return

        text.append("  ═══ You Have Not Tried ═══\n\n", style=f"bold {THEME['gold']}")
        width = max(len(cmd) for cmd, _why in unused)
        for command, why in unused:
            text.append(f"    {command:<{width}}  ", style=f"bold {THEME['success']}")
            text.append(f"{why}\n", style=THEME["muted"])
        text.append("\n", style="")

    @staticmethod
    def _run_used_shell(summary: dict) -> bool:
        """Whether this run executed a shell command.

        Gates the ``:trust`` and ``:sandbox`` hints.
        """
        if summary.get("commands_run"):
            return True
        tools = summary.get("tools") or ()
        shell_tools = {"bash", "shell", "run_command", "execute", "terminal"}
        for tool in tools:
            name = tool.get("name", "") if isinstance(tool, dict) else str(tool)
            if str(name).lower() in shell_tools:
                return True
        return False

    @staticmethod
    def _run_hit_an_error(summary: dict) -> bool:
        """Whether any tool in this run reported a failure."""
        for tool in summary.get("tools") or ():
            if not isinstance(tool, dict):
                continue
            if tool.get("error") or str(tool.get("status", "")).lower() in {"error", "failed"}:
                return True
        for command in summary.get("commands_run") or ():
            if isinstance(command, dict) and command.get("exit_code"):
                return True
        return False

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

    def _show_agents(
        self,
        log: ConversationLog,
        clear_log: bool = True,
        *,
        include_all: bool = True,
        catalog_tier: str = "all",
        reuse_snapshot: bool = False,
    ):
        """Show the curated ACP picker or a requested catalog tier."""
        # Recorded so back from a connected agent returns to this listing
        # rather than skipping past it to the category screen above.
        try:
            self._record_screen(
                f"connect:acp-agents:{catalog_tier}",
                "ACP agents",
                lambda: self._show_agents(
                    self.query_one("#log", ConversationLog),
                    include_all=include_all,
                    catalog_tier=catalog_tier,
                ),
            )
        except Exception:  # noqa: BLE001 - navigation chrome must never block the picker
            pass
        # Schedule async execution
        self._show_agents_async(
            log,
            clear_log=clear_log,
            include_all=include_all,
            catalog_tier=catalog_tier,
            reuse_snapshot=reuse_snapshot,
        )

    async def _acp_picker_catalog(self, reuse_snapshot: bool) -> tuple[dict, set[str]]:
        """Return the picker's agents and the ids that are installed.

        Building this costs a re-read of every agent TOML plus a PATH lookup
        per agent, which is far too much to repeat for a highlight move. Moving
        the cursor paints from the last snapshot and revalidates it in the
        background, so an agent installed from another terminal still lands
        without making navigation wait for the check.
        """
        if reuse_snapshot:
            snapshot = getattr(self, "_acp_picker_snapshot", None)
            if snapshot is not None:
                return snapshot
        return await self._build_acp_picker_catalog()

    async def _build_acp_picker_catalog(self) -> tuple[dict, set[str]]:
        """Read the agent catalogue and work out what is installed right now."""
        from superqode.agents.registry import get_all_acp_agents
        from superqode.commands.acp import check_agent_installed

        agents = await get_all_acp_agents()
        # `shutil.which` walks PATH per agent, so keep the whole sweep off the
        # event loop rather than stalling the terminal on a slow filesystem.
        installed_ids = await asyncio.to_thread(
            lambda: {
                agent_id
                for agent_id, agent_data in agents.items()
                if check_agent_installed(agent_data)
            }
        )
        snapshot = (agents, installed_ids)
        self._acp_picker_snapshot = snapshot
        self._acp_picker_snapshot_at = time.monotonic()
        return snapshot

    @work(exclusive=True, group="acp-catalog-revalidate")
    async def _revalidate_acp_catalog(self, log: ConversationLog) -> None:
        """Rebuild the catalogue behind a painted picker, and repaint if it moved.

        A new agent can land at any moment: installed from another terminal, or
        published to the official registry. Navigation must not wait on that
        check, but it must not hide the result either, so the redraw paints from
        the snapshot and this runs afterwards.
        """
        if (
            time.monotonic() - getattr(self, "_acp_picker_snapshot_at", 0.0)
            < ACP_CATALOG_TTL_SECONDS
        ):
            return
        if not getattr(self, "_awaiting_acp_agent_selection", False):
            return
        if getattr(self, "_awaiting_model_selection", False):
            return

        previous = getattr(self, "_acp_picker_snapshot", None)
        try:
            agents, installed_ids = await self._build_acp_picker_catalog()
        except Exception:  # noqa: BLE001 - a background check must never break the picker
            return

        # The user may have chosen an agent while the rebuild was in flight.
        if not getattr(self, "_awaiting_acp_agent_selection", False):
            return
        # Repainting the agent catalogue over a model picker flashes the whole
        # agent list across the screen mid-selection.
        if getattr(self, "_awaiting_model_selection", False):
            return
        if (
            previous is not None
            and set(previous[0]) == set(agents)
            and previous[1] == installed_ids
        ):
            return
        self._reshow_acp_agents(log)

    @work(exclusive=True)
    async def _show_agents_async(
        self,
        log: ConversationLog,
        clear_log: bool = True,
        *,
        include_all: bool = True,
        catalog_tier: str = "all",
        reuse_snapshot: bool = False,
    ):
        """Show ACP agents with installed agents first and catalog grouping."""
        import traceback
        from superqode.agents.registry import get_agent_installation_info

        try:
            agents, installed_ids = await self._acp_picker_catalog(reuse_snapshot)
        except Exception as e:
            log.add_error(f"Error loading agents: {e}")
            log.add_error(f"Details: {traceback.format_exc()}")
            return

        if not agents:
            log.add_info("No ACP agents found.")
            return

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        title = "Coding agents over ACP" if include_all else "ACP Agent Runtimes"
        if catalog_tier == "enterprise" and not include_all:
            title = "Enterprise ACP Agents"
        t.append(f"{title}\n", style=f"bold {THEME['text']}")
        t.append(
            f"  {len(agents)} in the registry. Each brings its own harness; "
            "SuperQode supplies the session, policy and evidence.\n\n",
            style=THEME["muted"],
        )

        # Installed agents are always visible. Missing agents are grouped so
        # the default view stays useful without becoming a registry dump.
        installed = []
        missing_by_tier = {"featured": [], "enterprise": [], "all": []}

        for agent_id, agent_data in agents.items():
            if agent_id in installed_ids:
                installed.append((agent_id, agent_data))
            else:
                tier = str(agent_data.get("catalog_tier") or "all")
                if tier not in missing_by_tier:
                    tier = "all"
                missing_by_tier[tier].append((agent_id, agent_data))

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
            priority = priority_order.get(agent_id)
            if priority is None:
                priority = priority_order.get(agent_short_name)
            if priority is not None:
                return (0, priority, agent_data["name"])
            return (1, 999, agent_data["name"])

        # Build the active view. The default shows the complete registry so no
        # agent is hidden; ``featured`` and ``enterprise`` narrow it on request.
        # Remembered so arrow-key redraws keep the view the user chose instead
        # of snapping back to the default.
        self._acp_catalog_view = "all" if include_all else catalog_tier
        installed_sorted = sorted(installed, key=sort_key)
        visible_groups: list[tuple[str, list]] = []
        if include_all:
            visible_groups = [
                ("Featured", sorted(missing_by_tier["featured"], key=sort_key)),
                ("Enterprise", sorted(missing_by_tier["enterprise"], key=sort_key)),
                ("Other registry agents", sorted(missing_by_tier["all"], key=sort_key)),
            ]
        elif catalog_tier == "enterprise":
            visible_groups = [("Enterprise", sorted(missing_by_tier["enterprise"], key=sort_key))]
        elif catalog_tier == "featured":
            visible_groups = [("Featured", sorted(missing_by_tier["featured"], key=sort_key))]
        else:
            visible_groups = [
                ("Featured", sorted(missing_by_tier["featured"], key=sort_key)),
                ("Enterprise", sorted(missing_by_tier["enterprise"], key=sort_key)),
                ("Other registry agents", sorted(missing_by_tier["all"], key=sort_key)),
            ]
        visible_groups = [(label, items) for label, items in visible_groups if items]
        all_agents = installed_sorted + [item for _, items in visible_groups for item in items]

        # Follow the highlighted agent by identity, not by position. A newly
        # installed agent joins the Ready now group and shifts every row below
        # it, and moving the highlight onto a neighbour under the user would
        # mean Enter connects something they never chose.
        previous_agents = getattr(self, "_acp_agent_list", []) or []
        current_highlight = getattr(self, "_acp_highlighted_agent_index", 0)
        anchor_id = ""
        if 0 <= current_highlight < len(previous_agents):
            anchor_id = str(previous_agents[current_highlight][0])

        # Store the list for selection
        self._acp_agent_list = all_agents
        self._awaiting_acp_agent_selection = True
        anchored = next(
            (index for index, (agent_id, _) in enumerate(all_agents) if str(agent_id) == anchor_id),
            None,
        )
        # Falling back to the old position keeps a view switch, which renumbers
        # everything, landing somewhere sensible rather than back at the top.
        self._acp_highlighted_agent_index = (
            anchored
            if anchored is not None
            else min(current_highlight, max(len(all_agents) - 1, 0))
        )

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

        # Show installed agents with numbers and highlighting
        if installed_sorted:
            t.append(f"  Ready now ({len(installed_sorted)})\n", style=f"bold {THEME['success']}")
            for num, (agent_id, agent_data) in enumerate(installed_sorted, 1):
                idx = num - 1
                is_highlighted = idx == getattr(self, "_acp_highlighted_agent_index", 0)

                row = self._picker_link_style(
                    f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}", num
                )
                t.append("  ", style="")
                self._append_picker_dot(t, num, highlighted=is_highlighted)
                t.append(f"[{num:2}] ", style=row)
                short_name = str(agent_data["short_name"])
                t.append(
                    short_name,
                    style=self._picker_link_style(
                        f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}",
                        num,
                        handle=True,
                    ),
                )
                self._append_picker_arrow(t, num)
                t.append(" " * max(0, 15 - len(short_name)), style=row)
                if is_highlighted:
                    t.append(f"{agent_data['name']}  ← SELECTED\n", style=row)
                else:
                    t.append(f"{agent_data['name']}\n", style=THEME["muted"])
            t.append("\n", style="")

        # Show missing agents by catalog group.
        next_num = len(installed_sorted) + 1
        for group_name, group_agents in visible_groups:
            t.append(
                f"  {group_name} ({len(group_agents)}) — one command away\n",
                style=f"bold {THEME['warning']}",
            )
            for num, (agent_id, agent_data) in enumerate(group_agents, next_num):
                idx = num - 1
                is_highlighted = idx == getattr(self, "_acp_highlighted_agent_index", 0)
                install_info = get_agent_installation_info(agent_data)
                install_cmd = install_info.get("command", "")

                row = self._picker_link_style(
                    f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}", num
                )
                t.append("  ", style="")
                self._append_picker_dot(t, num, highlighted=is_highlighted)
                t.append(f"[{num:2}] ", style=row)
                short_name = str(agent_data["short_name"])
                t.append(
                    short_name,
                    style=self._picker_link_style(
                        f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}",
                        num,
                        handle=True,
                    ),
                )
                self._append_picker_arrow(t, num)
                t.append(" " * max(0, 15 - len(short_name)), style=row)
                if is_highlighted:
                    t.append(f"{agent_data['name']:<25}  ← SELECTED\n", style=row)
                    if install_cmd:
                        t.append("         Install: ", style=THEME["dim"])
                        t.append(f"{install_cmd}\n", style=THEME["cyan"])
                else:
                    # Only the row being considered spends a second line on its
                    # install command; the rest stay one line each.
                    t.append(f"{agent_data['name']}\n", style=THEME["muted"])
            t.append("\n", style="")
            next_num += len(group_agents)

        t.append(f"  💡 Quick Actions:\n", style=THEME["muted"])
        t.append(f"    ", style=THEME["dim"])
        t.append(f"↑↓", style=THEME["cyan"])
        t.append(" arrows + ", style=THEME["dim"])
        t.append(f"Enter", style=THEME["cyan"])
        t.append(" or type a number\n", style=THEME["dim"])
        t.append(f"    Use ", style=THEME["dim"])
        t.append(f":connect acp <name>", style=THEME["pink"])
        t.append(f" to connect by name\n", style=THEME["dim"])
        if include_all:
            t.append("    Use ", style=THEME["dim"])
            t.append(":connect acp featured", style=THEME["cyan"])
            t.append(" or ", style=THEME["dim"])
            t.append(":connect acp enterprise", style=THEME["cyan"])
            t.append(" to narrow this list\n", style=THEME["dim"])
        else:
            t.append("    Use ", style=THEME["dim"])
            t.append(":connect acp", style=THEME["cyan"])
            t.append(" for every registry agent\n", style=THEME["dim"])
        t.append("    Use ", style=THEME["dim"])
        t.append(":connect acp refresh", style=THEME["cyan"])
        t.append(" to refresh the official registry cache\n", style=THEME["dim"])
        t.append(f"    Use ", style=THEME["dim"])
        t.append(f":acp install <name>", style=THEME["cyan"])
        t.append(f" to install missing agents\n", style=THEME["dim"])
        t.append(f"    Use ", style=THEME["dim"])
        t.append(f":home", style=THEME["cyan"])
        t.append(f" or ", style=THEME["dim"])
        t.append(f":back", style=THEME["cyan"])
        t.append(f" to cancel selection\n", style=THEME["dim"])

        # ACP is the reason this list is long, and the reason switching between
        # anything on it is cheap. Saying so here is what turns a directory of
        # third-party binaries into a coherent capability.
        t.append("\n  What ACP gives you here\n", style=f"bold {THEME['text']}")
        for bullet in (
            "one session store, memory and transcript across every agent above",
            "switch agent mid-task without losing context: :harness switch --fork",
            "your MCP servers, policies and approvals apply to all of them",
        ):
            t.append("    · ", style=THEME["dim"])
            t.append(f"{bullet}\n", style=THEME["muted"])
        t.append("    · ", style=THEME["dim"])
        t.append("SuperQode can also ", style=THEME["muted"])
        t.append("be", style=f"bold {THEME['muted']}")
        t.append(" an ACP agent: ", style=THEME["muted"])
        t.append("superqode serve acp", style=f"bold {THEME['cyan']}")
        t.append("  drive it from Zed or any ACP client\n", style=THEME["muted"])

        self._show_command_output(log, t, clear_log=clear_log)

        if reuse_snapshot:
            # The rows are on screen; now go and check whether they are stale.
            self._revalidate_acp_catalog(log)

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

    def _show_help(self, log: ConversationLog):
        t = Text()
        t.append("\n  ❓ ", style=f"bold {THEME['purple']}")
        t.append("SuperQode Commands\n\n", style=f"bold {THEME['purple']}")

        # A wall of 131 commands is a reference, not an answer. Point at the
        # two screens that answer "what can I do" with live state first, then
        # keep the full reference below for people who want to scan it.
        t.append("  ═══ Start Here ═══\n\n", style=f"bold {THEME['gold']}")
        t.append("    :connect", style=f"bold {THEME['success']}")
        t.append(
            "     choose who runs the coding loop: a ready-made agent,\n", style=THEME["muted"]
        )
        t.append("              ", style="")
        t.append("a SuperQode harness on your model, or one you build\n", style=THEME["muted"])
        t.append("    :explore", style=f"bold {THEME['success']}")
        t.append("     every capability available here, with live status\n", style=THEME["muted"])
        t.append("    :tour", style=f"bold {THEME['success']}")
        t.append(
            "        the ladder from a vendor agent to a harness you own,\n", style=THEME["muted"]
        )
        t.append("              ", style="")
        t.append("ticked off as you actually do each step\n\n", style=THEME["muted"])

        self._append_unused_command_suggestions(t)

        t.append("  ═══ All Commands ═══\n\n", style=f"bold {THEME['gold']}")

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
                    (
                        ":harness switch <name>",
                        "Continue the current session under another harness",
                    ),
                    (
                        ":harness switch <name> --fork",
                        "Fork the current session under another harness",
                    ),
                    (
                        ":sessions switch",
                        "Restore a saved session with its harness, model, and history",
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
                    (":factory", "Show Code Factory status for current work"),
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
                    (":runtime claude-agent-sdk", "Use Claude Agent SDK with ANTHROPIC_API_KEY"),
                    (":claude status", "Show Claude Agent SDK status"),
                    (":claude model|permission", "Pick Claude model and permission mode"),
                    (":claude sessions|resume", "Manage Claude Agent SDK sessions"),
                    (":connect antigravity", "Use signed-in Antigravity CLI"),
                    (":antigravity status", "Check local agy CLI status"),
                    (":antigravity migrate", "Show Gemini CLI migration steps"),
                    (":connect grok", "Grok Build, xAI's own agent over ACP"),
                    (":grok api", "SuperQode harness on the same subscription (opt-in)"),
                    (":grok status|login", "Check Grok CLI readiness or show login commands"),
                    (":tau use|login", "Select Tau and sync the active SuperQode route"),
                    (":tau status|providers|models", "Inspect Tau without leaving SuperQode"),
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
                "Optional Vim Navigation",
                THEME["gold"],
                [
                    (":vim", "Show optional Vim mode status"),
                    (":vim on|off", "Enable or disable modal terminal navigation"),
                    (":vim tutor", "Show modes, navigation keys, and supported scope"),
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
                color: #a1a1aa;
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
                    timeout = 1.0 if severity == "information" else 2.5
                    self.notify(message, severity=severity, timeout=timeout)
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
                color: #a1a1aa;
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
                        self.notify("Selection copied", severity="information", timeout=1)
                        return
                except Exception:
                    pass
                self._copy_all()

            def _copy_all(self):
                self._copy_to_clipboard(self._content)
                self.notify(f"{self._title} copied", severity="information", timeout=1)

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
