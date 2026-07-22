"""Slash / ':' command dispatch."""

from __future__ import annotations
import os
import pty
import select
import signal
import subprocess
import shlex
import time
from pathlib import Path
from typing import Any
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)
from superqode.widgets.theme_picker import ThemePicker
from superqode.app.theme_bridge import (
    theme_names,
)
from superqode.diff_view import (
    compute_diff,
    DiffMode,
    DiffViewer,
)
from superqode.design_system import (
    COLORS as SQ_COLORS,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.inputs import SelectionAwareInput
from superqode.app.session_state import get_session, get_mode
from superqode.app.welcome import _harness_display_name


class SlashCommandMixin:
    """_handle_* slash-command dispatch."""

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
        elif c == "work" and args.strip():
            self._run_cli_group("work", args, log, "WorkOrder")
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
            # Python extensions receive unknown commands before the legacy
            # agent-shortcut fallback. Creating PureMode here also applies the
            # same project-trust gate used for extension tools and hooks.
            pure = self._ensure_pure_mode()
            extension_runtime = getattr(pure, "_extension_runtime", None)
            if extension_runtime is not None and c in extension_runtime.commands:
                self.run_worker(self._invoke_extension_command(c, args, log))
            else:
                # Agent shortcut
                agent_commands = self._agent_command_metadata()
                if c in agent_commands:
                    self._connect_agent(c)
                else:
                    log.add_error(f"Unknown command: {c}")
                    log.add_system("Type :help for available commands")

        # Always return focus to input after command completes
        # Use a small delay to ensure command output is displayed first
        self.set_timer(0.1, self._ensure_input_focus)

    async def _invoke_extension_command(
        self, command: str, args: str, log: ConversationLog
    ) -> None:
        """Run one trusted extension command with isolated error reporting."""
        import json

        from superqode.extensions import ExtensionContext

        pure = self._ensure_pure_mode()
        runtime = pure._extension_runtime
        session = getattr(pure, "session", None)
        context = ExtensionContext(
            root=Path.cwd(),
            harness_id=str(getattr(session, "harness_name", "") or "core"),
            provider=str(getattr(session, "provider", "") or ""),
            model=str(getattr(session, "model", "") or ""),
            session_id=str(pure.get_current_session_id() or ""),
        )
        try:
            result = await runtime.invoke_command(command, args, context=context)
        except Exception as exc:
            log.add_error(f"Extension command :{command} failed: {exc}")
            return
        if result is None:
            return
        if isinstance(result, str):
            output = result
        elif isinstance(result, (dict, list, tuple, bool, int, float)):
            output = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        else:
            output = str(result)
        if output:
            log.add_system(output)

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
        harness_name = ""
        try:
            status = pure_mode.get_status()
            harness = status.get("harness", {})
            harness_name = str(harness.get("name") or harness.get("id") or "")
            definition = getattr(pure_mode, "_harness_definition", None)
            if definition is not None:
                os.environ["SUPERQODE_HARNESS"] = str(definition.path or definition.id)
            self._refresh_harness_panel()
        except (AttributeError, TypeError):
            pass
        log.add_success(f"Resumed session {resolved_id[:8]} with {len(messages)} messages.")
        if harness_name:
            log.add_info(
                f"Restored harness: {_harness_display_name(harness_name)}. "
                "Other sessions remain saved."
            )
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

    def _handle_permission_auto(self, process, line: str):
        """Auto-handle permission requests (legacy)."""
        self._send_permission_response(process, "y")

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
